import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from cosmas_os.api import app as api_module
from cosmas_os.application import services as svc
from cosmas_os.application import workspace as ws
from cosmas_os.models import (
    AppointmentObservation,
    AuditEvent,
    EncounterWorkspace,
    PatientLink,
    Principal,
    Ticket,
)


def encounter(s, box, actor):
    link = PatientLink(
        box_id=box,
        source_pair_key="invented:" + str(uuid4()),
        label="Invented person",
        state="confirmed",
        confirmed_by_principal_id=actor,
        attested_at=datetime.now(UTC),
    )
    s.add(link)
    s.flush()
    a = AppointmentObservation(
        box_id=box,
        external_id="invented-" + str(uuid4()),
        source="synthetic",
        start_at=datetime.now(UTC),
        patient_label="Invented person",
        patient_link_id=link.id,
    )
    s.add(a)
    s.commit()
    return a


@pytest.fixture
def case(session, seeded):
    box, actor = seeded["box_id"], seeded["owner_id"]
    a = encounter(session, box, actor)
    w = ws.create(session, box, actor, a.id, "create-key")
    return box, actor, a, w


def append(s, case, *, key="entry-key", expected=1, **kwargs):
    box, actor, _, w = case
    return ws.append(
        s,
        box,
        actor,
        w["id"],
        expected=expected,
        key=key,
        **{**dict(kind="scratchpad", content="Invented private note"), **kwargs},
    )


def test_saved_entries_replay_and_conflict_preserve_history(session, case):
    first = append(session, case)
    replay = append(session, case)
    assert replay["entry_id"] == first["entry_id"]
    assert replay["entry_revision"] == 2
    with pytest.raises(ws.WorkspaceError, match="idempotency_conflict"):
        append(session, case, content="Changed retry")
    with pytest.raises(ws.WorkspaceError, match="revision_conflict"):
        append(session, case, key="other-key")
    latest = append(
        session, case, key="other-key", expected=2, kind="conversation", content="Invented question"
    )
    assert [e["revision"] for e in latest["workspace"]["entries"]] == [1, 2, 3]
    assert latest["workspace"]["entries"][-1]["origin"] == "authenticated_human"
    old_retry = append(session, case)
    assert old_retry["workspace"]["revision"] == 2
    assert len(old_retry["workspace"]["entries"]) == 2
    # The editor must not silently acquire authority to overwrite an unseen edit.
    with pytest.raises(ws.WorkspaceError, match="revision_conflict"):
        append(session, case, key="after-old-retry", expected=old_retry["workspace"]["revision"])


def test_hosted_creation_starts_empty_and_keeps_saved_work_on_replay(session, seeded, monkeypatch):
    from cosmas_os.api.auth import RequestIdentity
    from cosmas_os.api.workspace_schemas import WorkspaceCreate

    box, actor = seeded["box_id"], seeded["owner_id"]
    appointment = encounter(session, box, actor)
    monkeypatch.setattr(api_module.settings, "cosmas_env", "early_adopter_beta")
    body = WorkspaceCreate(appointment_id=appointment.id, idempotency_key="hosted-create-key")
    identity = RequestIdentity(box_id=box, principal_id=actor, auth_mode="clerk_jwt")
    created = api_module.create_workspace(body, session, identity)
    assert created["revision"] == 1 and created["entries"] == []
    saved = ws.append(session, box, actor, created["id"], expected=1, key="hosted-note-key",
                      kind="scratchpad", content="Invented clinician's explicit note")
    reopened = api_module.create_workspace(body, session, identity)
    assert reopened["id"] == created["id"] and reopened["revision"] == 2
    assert reopened["entries"] == saved["workspace"]["entries"]
    assert [entry["kind"] for entry in reopened["entries"]] == ["scratchpad"]


def test_same_box_owner_and_other_box_cannot_read_or_write_private_workspace(session, case):
    box, actor, a, w = case
    other = Principal(
        box_id=box, principal_type="human", display_name="Other", state="active", is_owner=True
    )
    session.add(other)
    session.commit()
    foreign = svc.provision_box(svc.Container(session), "Other invented practice")
    for b, u in [(box, other.id), (foreign["box_id"], foreign["owner_id"])]:
        with pytest.raises(ws.WorkspaceError, match="workspace_unavailable"):
            ws.read(session, b, u, w["id"])
        with pytest.raises(ws.WorkspaceError, match="workspace_unavailable"):
            ws.append(
                session,
                b,
                u,
                w["id"],
                expected=1,
                key="forged-key",
                kind="conversation",
                content="forged",
            )
        assert all(item["workspace_id"] != w["id"] for item in ws.catalog(session, b, u))
    personal = ws.create(session, box, other.id, a.id, "other-create")
    assert personal["id"] != w["id"]


@pytest.mark.parametrize("revoke", ["human", "tombstone", "patient"])
def test_revocation_blocks_existing_history(session, case, revoke):
    box, actor, a, w = case
    if revoke == "patient":
        session.get(PatientLink, a.patient_link_id).revoked_at = datetime.now(UTC)
    elif revoke == "tombstone":
        session.get(Principal, actor).tombstoned_at = datetime.now(UTC)
    else:
        session.get(Principal, actor).state = "disabled"
    session.commit()
    with pytest.raises(ws.WorkspaceError):
        ws.read(session, box, actor, w["id"])
    with pytest.raises(ws.WorkspaceError):
        append(session, case)


def test_create_requires_confirmed_matching_encounter_and_key(session, case):
    box, actor, a, w = case
    assert ws.create(session, box, actor, a.id, "create-key")["id"] == w["id"]
    a2 = encounter(session, box, actor)
    with pytest.raises(ws.WorkspaceError, match="idempotency_conflict"):
        ws.create(session, box, actor, a2.id, "create-key")
    session.get(PatientLink, a2.patient_link_id).state = "unconfirmed"
    session.commit()
    with pytest.raises(ws.WorkspaceError, match="encounter_unavailable"):
        ws.create(session, box, actor, a2.id, "create-second")


def test_link_only_matching_work_without_copying_private_text(session, case):
    box, actor, a, w = case
    a2 = encounter(session, box, actor)
    valid = Ticket(
        box_id=box,
        created_by_principal_id=actor,
        appointment_id=a.id,
        patient_link_id=a.patient_link_id,
        lane="synthetic_followup",
        state="pending_approval",
    )
    wrong = Ticket(
        box_id=box,
        created_by_principal_id=actor,
        appointment_id=a2.id,
        patient_link_id=a2.patient_link_id,
        lane="synthetic_followup",
        state="draft",
    )
    session.add_all([valid, wrong])
    session.commit()
    with pytest.raises(ws.WorkspaceError, match="work_unavailable"):
        append(session, case, kind="work_link", content="", ticket_id=wrong.id)
    result = append(session, case, kind="work_link", content="", ticket_id=valid.id)
    assert result["workspace"]["entries"][-1]["ticket"]["state"] == "pending_approval"
    assert valid.current_revision_id is None
    assert result["workspace"]["entries"][-1]["content"] == ""
    with pytest.raises(ws.WorkspaceError, match="work_already_linked"):
        append(
            session,
            case,
            key="link-again",
            expected=2,
            kind="work_link",
            content="",
            ticket_id=valid.id,
        )


def test_database_scope_and_immutable_history(session, case):
    box, actor, a, w = case
    entry_id = w["entries"][0]["id"]
    for statement in [
        "UPDATE workspace_entries SET content='changed' WHERE id=:id",
        "DELETE FROM workspace_entries WHERE id=:id",
    ]:
        with pytest.raises(DBAPIError), session.begin_nested():
            session.execute(text(statement), {"id": entry_id})
    foreign = svc.provision_box(svc.Container(session), "Foreign synthetic practice")
    foreign_appointment = encounter(session, foreign["box_id"], foreign["owner_id"])
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(
            EncounterWorkspace(
                box_id=box,
                owner_id=actor,
                appointment_id=foreign_appointment.id,
                patient_link_id=foreign_appointment.patient_link_id,
                create_key="bad-scope",
                revision=1,
            )
        )
        session.flush()


def test_audit_is_metadata_only_and_rollback_discards_uncommitted_changes(session, case):
    box, actor, _, w = case
    append(session, case)
    events = list(session.scalars(select(AuditEvent).where(AuditEvent.aggregate_id == w["id"])))
    assert events and all(set(e.detail) == {"revision"} for e in events)
    assert "Invented private note" not in repr([e.detail for e in events])
    with pytest.raises(RuntimeError), session.begin_nested():
        session.get(EncounterWorkspace, w["id"]).revision = 90
        session.flush()
        raise RuntimeError("simulate crash before commit")
    assert ws.read(session, box, actor, w["id"])["revision"] == 2


def test_concurrent_writes_one_wins_and_new_sessions_reopen(engine):
    with Session(engine) as s:
        seed = svc.provision_box(svc.Container(s), "Concurrency invented practice")
        box, actor = seed["box_id"], seed["owner_id"]
        a = encounter(s, box, actor)
        w = ws.create(s, box, actor, a.id, "concurrent-create")
    barrier = Barrier(2)

    def writer(i):
        with Session(engine) as s:
            barrier.wait(timeout=10)
            try:
                ws.append(
                    s,
                    box,
                    actor,
                    w["id"],
                    expected=1,
                    key=f"parallel-{i}",
                    kind="scratchpad",
                    content=f"Invented revision {i}",
                )
                return "saved"
            except ws.WorkspaceError as e:
                return e.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(writer, [1, 2])) == ["saved", "workspace_revision_conflict"]
    with Session(engine) as s:
        restored = ws.read(s, box, actor, w["id"])
        assert restored["revision"] == 2 and len(restored["entries"]) == 2


def test_api_gate_safe_errors_and_private_response(session, case, monkeypatch):
    box, actor, _, w = case

    def session_override():
        yield session

    api_module.app.dependency_overrides[api_module.get_session] = session_override
    headers = {"X-Box-Id": box, "X-Actor-Principal-Id": actor}
    monkeypatch.setattr(api_module.settings, "workspace_enabled", False)
    try:
        with TestClient(api_module.app) as client:
            assert client.get("/workspaces").status_code == 404
            monkeypatch.setattr(api_module.settings, "workspace_enabled", True)
            response = client.get(f"/workspaces/{w['id']}", headers=headers)
            assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
            response = client.post(
                f"/workspaces/{w['id']}/entries",
                headers=headers,
                json={"content": "private-marker", "origin": "core", "expected_revision": 1},
            )
            assert response.status_code == 422
            assert "private-marker" not in response.text and "input" not in response.text
            response = client.post(
                f"/workspaces/{w['id']}/entries",
                headers=headers,
                json={
                    "content": "Saved invented question",
                    "kind": "conversation",
                    "expected_revision": 1,
                    "idempotency_key": "http-entry-key",
                },
            )
            assert response.status_code == 200
    finally:
        api_module.app.dependency_overrides.clear()


def test_additive_migration_readiness_and_data_preserving_recovery():
    url = make_url(os.environ["DATABASE_URL"])
    # This test creates its own database only on the explicitly disposable local
    # workspace cluster, never on an inherited arbitrary DATABASE_URL.
    assert url.host in {"127.0.0.1", "localhost"} and url.database.startswith("w1a_")
    name = "w1a_migration_" + uuid4().hex
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    target = create_engine(url.set(database=name))
    root = Path(__file__).resolve().parents[2]
    with admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))

    def migrate(revision, downgrade=False):
        cfg = Config(str(root / "alembic.ini"))
        cfg.set_main_option("script_location", str(root / "migrations"))
        with target.begin() as c:
            cfg.attributes["connection"] = c
            (command.downgrade if downgrade else command.upgrade)(cfg, revision)

    try:
        migrate("0002_external_identities")
        with Session(target) as s:
            seed = svc.provision_box(svc.Container(s), "Migration invented practice")
            a = encounter(s, seed["box_id"], seed["owner_id"])
            appointment_id = a.id
            with pytest.raises(HTTPException) as error:
                api_module.ready(s)
            assert error.value.status_code == 503
        migrate("head")
        with Session(target) as s:
            assert api_module.ready(s)["status"] == "ready"
            w = ws.create(s, seed["box_id"], seed["owner_id"], appointment_id, "migration-create")
            ws.append(
                s,
                seed["box_id"],
                seed["owner_id"],
                w["id"],
                expected=1,
                key="migration-note",
                kind="scratchpad",
                content="Survives recovery",
            )
        with pytest.raises(
            RuntimeError,
            match="Preserve incoming publication and responsibility history; disable the route instead",
        ):
            migrate("0002_external_identities", downgrade=True)
        with Session(target) as s:
            assert (
                ws.read(s, seed["box_id"], seed["owner_id"], w["id"])["entries"][-1]["content"]
                == "Survives recovery"
            )
            assert api_module.ready(s)["status"] == "ready"
    finally:
        target.dispose()
        with admin.connect() as c:
            c.execute(text(f'DROP DATABASE "{name}"'))
        admin.dispose()
