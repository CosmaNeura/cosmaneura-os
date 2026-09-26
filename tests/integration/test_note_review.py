from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from cosmas_os.api import app as api_module
from cosmas_os.application import note_review as notes
from cosmas_os.application import provider_team
from cosmas_os.application import services as svc
from cosmas_os.application import workspace as ws
from cosmas_os.models import (
    AppointmentObservation,
    Decision,
    Operation,
    PatientLink,
    Principal,
    Ticket,
    WorkspaceNote,
    WorkspaceNoteReview,
    WorkspaceReply,
)


def prepare(session, seeded):
    box, actor = seeded["box_id"], seeded["owner_id"]
    link = PatientLink(
        box_id=box,
        source_pair_key="note:" + str(uuid4()),
        label="Invented note",
        state="confirmed",
        confirmed_by_principal_id=actor,
        attested_at=datetime.now(UTC),
    )
    session.add(link)
    session.flush()
    a = AppointmentObservation(
        box_id=box,
        patient_link_id=link.id,
        external_id=str(uuid4()),
        source="synthetic",
        start_at=datetime.now(UTC),
        patient_label="Invented person",
    )
    session.add(a)
    session.commit()
    w = ws.create(session, box, actor, a.id, "create-note")
    return box, actor, w, link.id


@pytest.fixture
def case(session, seeded):
    return prepare(session, seeded)


def save(s, case, **changes):
    box, actor, w, _ = case
    return notes.save(
        s,
        box,
        actor,
        w["id"],
        **{
            "expected": 1,
            "key": "save-note",
            "base_note_id": None,
            "source_reply_id": None,
            "content": "Invented agenda remains planned.",
            **changes,
        },
    )["workspace"]


def review(s, case, w, **changes):
    n = w["note"]["latest"]
    return notes.review(
        s,
        case[0],
        case[1],
        w["id"],
        n["id"],
        **{
            "expected": w["revision"],
            "key": "review-note",
            "content_hash": n["content_hash"],
            "source_hash": n["source_fingerprint"],
            **changes,
        },
    )["workspace"]


def test_exact_review_is_private_immutable_and_new_edit_needs_review(session, case):
    before = [
        session.scalar(select(func.count()).select_from(t)) for t in (Ticket, Decision, Operation)
    ]
    w = save(session, case)
    first = w["note"]["latest"]
    assert first["review"] is None
    checked = review(session, case, w)
    assert checked["note"]["latest"]["review"]["reviewer_id"] == case[1]
    edited = save(
        session,
        case,
        expected=checked["revision"],
        key="edit-note",
        base_note_id=first["id"],
        content="Human correction: still planned.",
    )
    assert edited["note"]["latest"]["version"] == 2
    assert edited["note"]["latest"]["review"] is None
    assert edited["note"]["history"][0]["review"] is not None
    assert [
        session.scalar(select(func.count()).select_from(t)) for t in (Ticket, Decision, Operation)
    ] == before
    for table, rowid in (
        ("workspace_notes", first["id"]),
        ("workspace_note_reviews", checked["note"]["latest"]["review"]["id"]),
    ):
        for statement in (
            f"UPDATE {table} SET request_hash = 'changed' WHERE id = :id",
            f"DELETE FROM {table} WHERE id = :id",
        ):
            with pytest.raises(DBAPIError), session.begin_nested():
                session.execute(text(statement), {"id": rowid})


def test_save_and_review_replay_exact_snapshot_without_approving_new_edits(session, case):
    w = save(session, case)
    checked = review(session, case, w)
    save(
        session,
        case,
        expected=checked["revision"],
        key="new-version",
        base_note_id=w["note"]["latest"]["id"],
        content="Changed invented note.",
    )
    assert save(session, case) == w
    assert review(session, case, w) == checked
    with pytest.raises(ws.WorkspaceError, match="idempotency_conflict"):
        save(session, case, content="Changed retry")
    with pytest.raises(ws.WorkspaceError, match="idempotency_conflict"):
        review(session, case, w, content_hash="0" * 64)
    with pytest.raises(ws.WorkspaceError, match="note_revision_conflict"):
        review(session, case, w, key="review-new-request", expected=4)


def test_source_changes_invalidate_review_until_human_reconciles_and_saves(session, case):
    w = save(session, case)
    checked = review(session, case, w)
    fresh = ws.append(
        session,
        case[0],
        case[1],
        w["id"],
        expected=checked["revision"],
        key="source-update",
        kind="scratchpad",
        content="Corrected invented agenda.",
    )["workspace"]
    assert fresh["note"]["latest"]["sources_changed"] is True
    assert fresh["note"]["latest"]["review"] is not None  # Historical receipt retained.
    edited = save(
        session,
        case,
        expected=fresh["revision"],
        key="edit-stale",
        base_note_id=fresh["note"]["latest"]["id"],
        content="An edited note.",
    )
    with pytest.raises(ws.WorkspaceError, match="sources_or_content_changed"):
        review(session, case, edited, key="stale-review")
    reconciled = save(
        session,
        case,
        expected=edited["revision"],
        key="reconcile-note",
        base_note_id=edited["note"]["latest"]["id"],
        content="Reconciled invented note.",
        sources_reconciled=True,
    )
    assert reconciled["note"]["latest"]["sources_changed"] is False
    assert review(session, case, reconciled, key="fresh-review")["note"]["latest"]["review"]


def test_chat_does_not_invalidate_sources_but_stale_revision_and_payload_are_denied(session, case):
    w = save(session, case)
    fresh = ws.append(
        session,
        case[0],
        case[1],
        w["id"],
        expected=w["revision"],
        key="chat-update",
        kind="conversation",
        content="Invented question.",
    )["workspace"]
    assert fresh["note"]["latest"]["sources_changed"] is False
    with pytest.raises(ws.WorkspaceError, match="workspace_revision_conflict"):
        review(session, case, w)
    with pytest.raises(ws.WorkspaceError, match="sources_or_content_changed"):
        review(session, case, fresh, content_hash="0" * 64)
    assert review(session, case, fresh)["note"]["latest"]["review"]


@pytest.mark.parametrize("principal_type", ["human", "agent"])
def test_other_humans_and_agents_cannot_save_or_review(session, case, principal_type):
    w = save(session, case)
    p = Principal(
        box_id=case[0],
        principal_type=principal_type,
        display_name="Other invented actor",
        state="active",
        is_owner=True,
    )
    session.add(p)
    session.commit()
    other = (case[0], p.id, case[2], case[3])
    with pytest.raises(ws.WorkspaceError):
        save(session, other, expected=w["revision"])
    with pytest.raises(ws.WorkspaceError):
        review(session, other, w)


@pytest.mark.parametrize("revocation", ["owner", "link"])
def test_revocation_prevents_read_and_even_idempotent_retry(session, case, revocation):
    w = save(session, case)
    if revocation == "owner":
        session.get(Principal, case[1]).state = "disabled"
    else:
        session.get(PatientLink, case[3]).revoked_at = datetime.now(UTC)
    session.commit()
    with pytest.raises(ws.WorkspaceError):
        save(session, case)
    with pytest.raises(ws.WorkspaceError):
        review(session, case, w)
    with pytest.raises(ws.WorkspaceError):
        ws.read(session, case[0], case[1], w["id"])


def test_review_database_binding_denies_wrong_hash_and_owner(session, case):
    w = save(session, case)
    n = w["note"]["latest"]
    for changes in (
        {"content_hash": "0" * 64},
        {"owner_id": str(uuid4())},
        {"box_id": str(uuid4())},
    ):
        with pytest.raises(DBAPIError), session.begin_nested():
            session.add(
                WorkspaceNoteReview(
                    **{
                        "workspace_id": w["id"],
                        "box_id": case[0],
                        "owner_id": case[1],
                        "note_id": n["id"],
                        "workspace_revision": 3,
                        "content_hash": n["content_hash"],
                        "source_fingerprint": n["source_fingerprint"],
                        "idempotency_key": "forged-review",
                        "request_hash": "0" * 64,
                        **changes,
                    }
                )
            )
            session.flush()


def test_foreign_scope_and_unavailable_generated_source_are_denied(session, case):
    foreign = svc.provision_box(svc.Container(session), "Other invented practice")
    with pytest.raises(ws.WorkspaceError):
        save(session, (foreign["box_id"], foreign["owner_id"], case[2], case[3]))
    with pytest.raises(ws.WorkspaceError, match="note_source_unavailable"):
        save(session, case, source_reply_id=case[2]["entries"][0]["id"])
    with pytest.raises(ws.WorkspaceError, match="note_revision_conflict"):
        save(session, case, base_note_id=str(uuid4()))


def test_api_gate_validation_and_exact_review(session, case, monkeypatch):
    monkeypatch.setattr(api_module.settings, "workspace_enabled", True)
    api_module.app.dependency_overrides[api_module.get_session] = lambda: session
    headers = {"X-Box-Id": case[0], "X-Actor-Principal-Id": case[1]}
    path = f"/workspaces/{case[2]['id']}/notes"
    try:
        with TestClient(api_module.app) as client:
            body = {
                "expected_revision": 1,
                "idempotency_key": "api-note-key",
                "content": "Invented note.",
            }
            r = client.post(path, headers=headers, json=body)
            assert r.status_code == 200
            w = r.json()["workspace"]
            n = w["note"]["latest"]
            r = client.post(
                path + f"/{n['id']}/review",
                headers=headers,
                json={
                    "expected_revision": w["revision"],
                    "idempotency_key": "api-review-key",
                    "content_hash": n["content_hash"],
                    "source_fingerprint": n["source_fingerprint"],
                },
            )
            assert r.status_code == 200
            bad = client.post(path, headers=headers, json={**body, "sources_reconciled": "true"})
            assert bad.status_code == 422
            assert "Invented note." not in bad.text
            monkeypatch.setattr(api_module.settings, "workspace_enabled", False)
            assert client.post(path, headers=headers, json=body).status_code == 404
    finally:
        api_module.app.dependency_overrides.clear()


def test_note_parent_database_scope_is_enforced(session, case):
    w = save(session, case)
    n = session.get(WorkspaceNote, w["note"]["latest"]["id"])
    with pytest.raises(DBAPIError), session.begin_nested():
        session.add(
            WorkspaceNote(
                workspace_id=n.workspace_id,
                box_id=n.box_id,
                owner_id=n.owner_id,
                version=2,
                workspace_revision=3,
                parent_id=str(uuid4()),
                source_revision=1,
                content="Invented",
                content_hash="0" * 64,
                source_fingerprint="0" * 64,
                idempotency_key="bad-parent",
                request_hash="0" * 64,
            )
        )
        session.flush()


def test_scribe_lineage_keeps_original_source_context_until_human_reconciliation(session, case):
    box, actor, w, _ = case
    team = provider_team.save(
        session,
        box,
        actor,
        expected=0,
        key="team-for-note",
        configuration=provider_team.default_configuration(),
    )
    turn = ws.append(
        session,
        box,
        actor,
        w["id"],
        expected=1,
        key="scribe-turn",
        kind="conversation",
        content="Make an invented draft.",
    )
    session.add(
        WorkspaceReply(
            entry_id=turn["entry_id"],
            workspace_id=w["id"],
            box_id=box,
            owner_id=actor,
            agent_id=next(m["agent_id"] for m in team["members"] if m["role"] == "scribe"),
            team_revision_id=provider_team.current(session, box, actor).id,
            agent_name="Scribe",
            role="scribe",
            backend="azure_gpt41_source_draft_v1",
            content="Quoted invented agenda.",
            context_revision=1,
            citations=[],
        )
    )
    session.commit()
    ws.append(
        session,
        box,
        actor,
        w["id"],
        expected=2,
        key="newer-source",
        kind="evidence",
        source_label="Invented correction",
        content="Changed rehearsal evidence.",
    )
    copied = save(session, case, expected=3, source_reply_id=turn["entry_id"])
    n = copied["note"]["latest"]
    assert n["source_revision"] == 1 and n["sources_changed"]
    with pytest.raises(ws.WorkspaceError, match="sources_or_content_changed"):
        review(session, case, copied)
    with pytest.raises(ws.WorkspaceError, match="note_source_required"):
        save(session, case, expected=4, key="erase-lineage", base_note_id=n["id"])
    fixed = save(
        session,
        case,
        expected=4,
        key="reconciled-generated",
        base_note_id=n["id"],
        source_reply_id=turn["entry_id"],
        sources_reconciled=True,
        content="Human reconciled note.",
    )
    assert not fixed["note"]["latest"]["sources_changed"]
    assert fixed["note"]["latest"]["source_reply_id"] == turn["entry_id"]


def test_concurrent_note_saves_have_one_winner_and_reopen_from_new_session(engine):
    with Session(engine) as s:
        seed = svc.provision_box(svc.Container(s), "Invented note concurrency")
        case = prepare(s, seed)
    barrier = Barrier(2)

    def writer(i):
        with Session(engine) as s:
            barrier.wait(timeout=10)
            try:
                save(s, case, key=f"parallel-note-{i}", content=f"Invented draft {i}.")
                return "saved"
            except ws.WorkspaceError as e:
                return e.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(writer, (1, 2))) == ["note_revision_conflict", "saved"]
    with Session(engine) as s:
        w = ws.read(s, case[0], case[1], case[2]["id"])
        assert w["revision"] == 2
        assert len(w["note"]["history"]) == 1
        assert w["note"]["latest"]["version"] == 1
