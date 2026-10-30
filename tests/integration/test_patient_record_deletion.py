"""Admin deletion removes one patient's rows and files and leaves everyone else."""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from cosmas_os.adapters.local import LocalBlobAdapter
from cosmas_os.api.app import app
from cosmas_os.application import note_review, workspace
from cosmas_os.application import services as svc
from cosmas_os.application.patient_deletion import delete_patient_records, storage_roots
from cosmas_os.cli import app as cli_app
from cosmas_os.config import settings
from cosmas_os.domain.enums import DecisionKind, PrincipalState, PrincipalType
from cosmas_os.models import (
    ActionRevision,
    AppointmentObservation,
    Artifact,
    AuditEvent,
    Decision,
    EncounterWorkspace,
    ExternalIdentity,
    Operation,
    PatientLink,
    Principal,
    ProviderBot,
    ProviderTeamRevision,
    SchedulingPatientAccount,
    Ticket,
    WorkspaceEntry,
    WorkspaceNote,
)
from cosmas_os.private_recording_models import PrivateRecording, PrivateRecordingFinish
from cosmas_os.runtime_schema import EXPECTED_SCHEMA_REVISION

PNG = b"\x89PNG\r\n\x1a\n" + b"synthetic-card"
ROOT = Path(__file__).resolve().parents[2]
PARENT_REVISION = "y24f0a87c631"
GUARD_FUNCTIONS = (
    "reject_workspace_history_change",
    "reject_provider_history_change",
    "immutable_patient_setup",
    "reject_scheduling_account_change",
)


def _names(token: str) -> dict[str, str]:
    return {
        "label": f"Casey North {token}",
        "note": f"synthetic-casey-note {token} about the invented visit",
        "message": f"synthetic-casey-message {token} from the front desk",
        "transcript": f"synthetic-casey-transcript {token} of the invented visit",
        "morgan_label": f"Morgan West {token}",
        "morgan_note": f"synthetic-morgan-note {token} about the invented visit",
        "morgan_message": f"synthetic-morgan-message {token} from the front desk",
        "morgan_transcript": f"synthetic-morgan-transcript {token} of the invented visit",
    }
_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


def _quote(name: str) -> str:
    if _IDENT.fullmatch(name) is None:
        raise AssertionError("unexpected database identifier")
    return '"' + name + '"'


def _csv(external_id: str, label: str) -> str:
    return (
        "external_id,start_at,patient_label,source\n"
        f"{external_id},2026-09-10T15:00:00+00:00,{label},csv\n"
    )


def _patient_link_counts(session: Session, patient_id: str) -> dict[str, int]:
    tables = session.scalars(
        text(
            "SELECT table_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND column_name = 'patient_link_id'"
        )
    )
    counts: dict[str, int] = {}
    for table in tables:
        counts[str(table)] = int(
            session.scalar(
                text(
                    f"SELECT count(*) FROM public.{_quote(str(table))} "
                    "WHERE patient_link_id = :patient_id"
                ),
                {"patient_id": patient_id},
            )
            or 0
        )
    return counts


def _text_hits(session: Session, needle: str) -> int:
    grouped: dict[str, list[str]] = {}
    for table, column in session.execute(
        text(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND data_type IN "
            "('text', 'character varying', 'json', 'jsonb')"
        )
    ):
        grouped.setdefault(str(table), []).append(str(column))
    found = 0
    for table, columns in grouped.items():
        clause = " OR ".join(
            f"strpos({_quote(column)}::text, :needle) > 0" for column in columns
        )
        found += int(
            session.scalar(
                text(f"SELECT count(*) FROM public.{_quote(table)} WHERE {clause}"),
                {"needle": needle},
            )
            or 0
        )
    return found


def _record(session: Session, box: str, owner: str, scribe_id: str, workspace_id: str) -> str:
    if session.scalar(
        select(ExternalIdentity.id).where(ExternalIdentity.principal_id == owner)
    ) is None:
        session.add(
            ExternalIdentity(
                box_id=box,
                principal_id=owner,
                provider="clerk",
                issuer="https://invented.clerk.example",
                subject="user_invented_" + uuid4().hex,
                organization_id="org_invented_" + uuid4().hex,
                reviewed_by="Invented reviewer",
                evidence_ref="test:patient-deletion",
            )
        )
        session.flush()
    identity_id = session.scalar(
        select(ExternalIdentity.id).where(ExternalIdentity.principal_id == owner)
    )
    if session.get(ProviderBot, scribe_id) is None:
        session.add(ProviderBot(agent_id=scribe_id, box_id=box, owner_id=owner, role="scribe"))
    if session.scalar(
        select(ProviderTeamRevision.id).where(ProviderTeamRevision.owner_id == owner)
    ) is None:
        session.add(
            ProviderTeamRevision(
                box_id=box,
                owner_id=owner,
                revision=1,
                template_version="team-v1",
                configuration={"bots": [{"role": "scribe"}]},
                idempotency_key="patient-deletion-team",
                request_hash="a" * 64,
            )
        )
        session.flush()
    team_id = session.scalar(
        select(ProviderTeamRevision.id).where(ProviderTeamRevision.owner_id == owner)
    )
    recording = PrivateRecording(
        workspace_id=workspace_id,
        box_id=box,
        owner_id=owner,
        external_identity_id=identity_id,
        agent_id=scribe_id,
        team_revision_id=team_id,
        workspace_revision=1,
        local_recording_id=str(uuid4()),
        request_key=str(uuid4()),
        request_sha256="b" * 64,
        recovery_scope="c" * 64,
        request={"capture": "metadata"},
        started_at=datetime(2026, 9, 10, tzinfo=UTC),
    )
    session.add(recording)
    session.flush()
    session.add(
        PrivateRecordingFinish(
            recording_id=recording.id,
            request_key=str(uuid4()),
            request_sha256="d" * 64,
            request={"capture": "metadata"},
            capture_state="finished",
            manifest_sha256="e" * 64,
            chunks=1,
            frames=1,
            ended_at=datetime(2026, 9, 10, 0, 5, tzinfo=UTC),
        )
    )
    session.commit()
    return recording.id


def _visit(
    container: svc.Container,
    *,
    box: str,
    owner: str,
    scribe_id: str,
    blob: LocalBlobAdapter,
    label: str,
    slug: str,
    note: str,
    message: str,
    transcript: str,
) -> dict[str, str]:
    appointment_id = svc.import_schedule(container, box, _csv(f"visit-{slug}", label))[0]
    link = svc.attest_patient_link(
        container, box, owner, source_pair_key=f"csv:{slug}", label=label
    )
    ticket = svc.detect_and_open_chase(
        container, box, container.session.scalar(
            select(Principal.id).where(Principal.box_id == box, Principal.agent_key == "chaser")
        ),
        appointment_id,
        link.id,
    )
    svc.decide(container, ticket.id, owner, DecisionKind.APPROVE)
    svc.simulate_upload_and_verify(container, ticket.id, owner, PNG, PNG)
    opened = workspace.create(container.session, box, owner, appointment_id, f"workspace-{slug}")
    workspace.append(
        container.session, box, owner, opened["id"],
        expected=opened["revision"], key=f"{slug}-transcript", kind="scratchpad", content=transcript,
    )
    noted = note_review.save(
        container.session, box, owner, opened["id"],
        expected=opened["revision"] + 1, key=f"{slug}-note", base_note_id=None,
        source_reply_id=None, content=note,
    )
    first_note = noted["workspace"]["note"]["latest"]["id"]
    note_review.save(
        container.session, box, owner, opened["id"],
        expected=noted["entry_revision"], key=f"{slug}-note-revised", base_note_id=first_note,
        source_reply_id=None, content=note + " revised",
    )
    workspace.append(
        container.session, box, owner, opened["id"],
        expected=noted["entry_revision"] + 1, key=f"{slug}-message", kind="conversation",
        content=message,
    )
    container.session.add(
        SchedulingPatientAccount(
            box_id=box,
            patient_link_id=link.id,
            practice_id=str(uuid4()),
            patient_id=str(uuid4()),
            reviewed_by="Invented reviewer",
            evidence_ref="test:patient-deletion",
            reviewed_at=datetime(2026, 9, 10, tzinfo=UTC),
        )
    )
    container.session.commit()
    recording_id = _record(container.session, box, owner, scribe_id, opened["id"])
    root = blob.root
    (root / recording_id / "audio").mkdir(parents=True)
    (root / recording_id / "audio" / "clip.wav").write_bytes(b"RIFF-invented-audio")
    (root / opened["id"] / "exports").mkdir(parents=True)
    (root / opened["id"] / "exports" / "note.pdf").write_bytes(b"%PDF-invented")
    return {
        "patient_id": link.id,
        "appointment_id": appointment_id,
        "ticket_id": ticket.id,
        "workspace_id": opened["id"],
        "recording_id": recording_id,
    }


def _arrange(session: Session, blob: LocalBlobAdapter) -> dict[str, object]:
    names = _names(uuid4().hex)
    container = svc.Container(session, blob=blob)
    seeded = svc.provision_box(container, "Invented Deletion Practice")
    staff = Principal(
        box_id=seeded["box_id"],
        principal_type=PrincipalType.HUMAN.value,
        display_name="Sam Clerk",
        is_owner=False,
        state=PrincipalState.ACTIVE.value,
    )
    session.add(staff)
    session.commit()
    common = {
        "box": seeded["box_id"],
        "owner": seeded["owner_id"],
        "scribe_id": seeded["agents"]["scribe"],
        "blob": blob,
    }
    casey = _visit(
        container, label=names["label"], slug="casey-" + names["label"].split()[-1],
        note=names["note"], message=names["message"], transcript=names["transcript"], **common,
    )
    morgan = _visit(
        container, label=names["morgan_label"], slug="morgan-" + names["morgan_label"].split()[-1],
        note=names["morgan_note"], message=names["morgan_message"],
        transcript=names["morgan_transcript"], **common,
    )
    (blob.root / "keep").mkdir(parents=True)
    (blob.root / "keep" / "unrelated.txt").write_text("keep this file", encoding="utf-8")
    return {"staff_id": staff.id, "casey": casey, "morgan": morgan, "names": names, **seeded}


def _count(session: Session, model, column: str, value: str) -> int:
    return int(
        session.scalar(
            select(func.count()).select_from(model).where(getattr(model, column) == value)
        )
        or 0
    )


def _calls(session: Session, actor: str, patient_id: str, blob: LocalBlobAdapter, *, confirm: bool):
    return delete_patient_records(
        session,
        actor_principal_id=actor,
        patient_link_id=patient_id,
        confirm=confirm,
        blob=blob,
        file_roots=storage_roots(blob),
    )


def _paths(blob: LocalBlobAdapter, visit: dict[str, str]) -> dict[str, Path]:
    return {
        "audio": blob.root / visit["recording_id"] / "audio" / "clip.wav",
        "export": blob.root / visit["workspace_id"] / "exports" / "note.pdf",
    }


def _upload_paths(session: Session, blob: LocalBlobAdapter, ticket_id: str) -> list[Path]:
    keys = list(session.scalars(select(Artifact.blob_key).where(Artifact.ticket_id == ticket_id)))
    assert len(keys) == 2
    return [blob.root / str(key) for key in keys]


@pytest.fixture
def practice(engine, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "blob_root", str(tmp_path / "blobs"))
    blob = LocalBlobAdapter(tmp_path / "blobs")
    session = Session(engine)
    arranged = _arrange(session, blob)
    arranged["blob"] = blob
    arranged["session"] = session
    try:
        yield arranged
    finally:
        session.close()


def test_staff_and_agent_are_refused_by_the_api_and_the_cli(practice) -> None:
    session = practice["session"]
    blob = practice["blob"]
    owner_box = str(practice["box_id"])
    staff = str(practice["staff_id"])
    agent = str(practice["agents"]["scribe"])
    casey = practice["casey"]
    names = practice["names"]
    assert isinstance(casey, dict) and isinstance(names, dict) and isinstance(blob, LocalBlobAdapter)
    patient_id = str(casey["patient_id"])
    files = list(_paths(blob, casey).values()) + _upload_paths(session, blob, str(casey["ticket_id"]))
    assert all(path.is_file() for path in files)
    client = TestClient(app)
    path = f"/admin/patients/{patient_id}/records"

    for actor, headers in (
        (staff, {"X-Box-Id": owner_box, "X-Actor-Principal-Id": staff}),
        (agent, {"X-Box-Id": owner_box, "X-Actor-Principal-Id": agent}),
    ):
        refused = client.post(path, json={"confirm": True}, headers=headers)
        assert refused.status_code == 403
        assert str(names["label"]) not in refused.text
        assert str(names["note"]) not in refused.text
        cli = CliRunner().invoke(
            cli_app, ["delete-patient-records", patient_id, "--actor", actor, "--confirm"]
        )
        assert cli.exit_code == 1
        assert "admin authority required" in (cli.stderr or "")
        assert str(names["label"]) not in (cli.stderr or "")
        assert str(names["note"]) not in (cli.stderr or "")

    assert session.get(PatientLink, patient_id) is not None
    assert all(path.is_file() for path in files)
    assert session.scalar(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.event_type == "patient.records_deleted",
            AuditEvent.aggregate_id == patient_id,
        )
    ) == 0


def test_dry_run_returns_counts_and_deletes_nothing(practice) -> None:
    session = practice["session"]
    blob = practice["blob"]
    owner = str(practice["owner_id"])
    casey = practice["casey"]
    names = practice["names"]
    assert isinstance(casey, dict) and isinstance(names, dict) and isinstance(blob, LocalBlobAdapter)
    patient_id = str(casey["patient_id"])
    files = list(_paths(blob, casey).values()) + _upload_paths(session, blob, str(casey["ticket_id"]))
    before = _patient_link_counts(session, patient_id)
    assert before["appointment_observations"] == 1
    assert before["tickets"] == 1
    assert before["encounter_workspaces"] == 1
    assert before["scheduling_patient_accounts"] == 1
    assert _count(session, WorkspaceNote, "workspace_id", str(casey["workspace_id"])) == 2

    preview = _calls(session, owner, patient_id, blob, confirm=False)
    assert preview["dry_run"] is True
    assert preview["deleted"] is False
    assert preview["patient_link_id"] == patient_id
    assert preview["tables"]["patient_links"] == 1
    assert preview["tables"]["appointment_observations"] == 1
    assert preview["tables"]["tickets"] == 1
    assert preview["tables"]["encounter_workspaces"] == 1
    assert preview["tables"]["scheduling_patient_accounts"] == 1
    assert preview["files"] == {"audio": 1, "uploads": 2, "exports": 1}

    api = TestClient(app).post(
        f"/admin/patients/{patient_id}/records",
        json={},
        headers={"X-Box-Id": str(practice["box_id"]), "X-Actor-Principal-Id": owner},
    )
    assert api.status_code == 200
    assert api.json()["dry_run"] is True
    assert api.json()["deleted"] is False
    assert api.json()["files"] == {"audio": 1, "uploads": 2, "exports": 1}
    assert str(names["label"]) not in api.text

    assert session.get(PatientLink, patient_id) is not None
    assert _patient_link_counts(session, patient_id) == before
    assert all(path.is_file() for path in files)
    assert session.scalar(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.event_type == "patient.records_deleted",
            AuditEvent.aggregate_id == patient_id,
        )
    ) == 0


def test_confirm_removes_every_patient_keyed_table_and_that_patients_files(practice) -> None:
    session = practice["session"]
    blob = practice["blob"]
    owner = str(practice["owner_id"])
    casey = practice["casey"]
    assert isinstance(casey, dict) and isinstance(blob, LocalBlobAdapter)
    patient_id = str(casey["patient_id"])
    keyed = _patient_link_counts(session, patient_id)
    assert {
        "appointment_observations",
        "tickets",
        "encounter_workspaces",
        "scheduling_patient_accounts",
    } <= set(keyed)
    assert all(keyed[table] == 1 for table in (
        "appointment_observations", "tickets", "encounter_workspaces", "scheduling_patient_accounts",
    ))
    files = list(_paths(blob, casey).values()) + _upload_paths(session, blob, str(casey["ticket_id"]))
    assert all(path.is_file() for path in files)

    deleted = _calls(session, owner, patient_id, blob, confirm=True)
    assert deleted["deleted"] is True
    assert deleted["dry_run"] is False
    assert deleted["files"] == {"audio": 1, "uploads": 2, "exports": 1}
    assert session.get(PatientLink, patient_id) is None
    after = _patient_link_counts(session, patient_id)
    assert set(after) == set(keyed)
    assert after
    assert all(count == 0 for count in after.values())
    for model, column, value in (
        (AppointmentObservation, "id", casey["appointment_id"]),
        (Ticket, "id", casey["ticket_id"]),
        (ActionRevision, "ticket_id", casey["ticket_id"]),
        (Decision, "ticket_id", casey["ticket_id"]),
        (Operation, "ticket_id", casey["ticket_id"]),
        (Artifact, "ticket_id", casey["ticket_id"]),
        (EncounterWorkspace, "id", casey["workspace_id"]),
        (WorkspaceEntry, "workspace_id", casey["workspace_id"]),
        (WorkspaceNote, "workspace_id", casey["workspace_id"]),
        (PrivateRecording, "id", casey["recording_id"]),
        (PrivateRecordingFinish, "recording_id", casey["recording_id"]),
        (SchedulingPatientAccount, "patient_link_id", patient_id),
    ):
        assert _count(session, model, column, str(value)) == 0
    assert all(not path.exists() for path in files)
    assert not (blob.root / str(casey["recording_id"])).exists()


def test_second_patient_rows_and_files_stay(practice) -> None:
    session = practice["session"]
    blob = practice["blob"]
    owner = str(practice["owner_id"])
    casey = practice["casey"]
    morgan = practice["morgan"]
    assert isinstance(casey, dict) and isinstance(morgan, dict) and isinstance(blob, LocalBlobAdapter)
    morgan_id = str(morgan["patient_id"])
    before = _patient_link_counts(session, morgan_id)
    morgan_files = list(_paths(blob, morgan).values()) + _upload_paths(
        session, blob, str(morgan["ticket_id"])
    )
    notes = _count(session, WorkspaceNote, "workspace_id", str(morgan["workspace_id"]))
    assert notes == 2
    assert all(path.is_file() for path in morgan_files)
    kept = blob.root / "keep" / "unrelated.txt"
    assert kept.is_file()

    _calls(session, owner, str(casey["patient_id"]), blob, confirm=True)

    assert session.get(PatientLink, morgan_id) is not None
    assert _patient_link_counts(session, morgan_id) == before
    assert _count(session, WorkspaceNote, "workspace_id", str(morgan["workspace_id"])) == notes
    assert _count(session, PrivateRecording, "id", str(morgan["recording_id"])) == 1
    assert _count(session, Artifact, "ticket_id", str(morgan["ticket_id"])) == 2
    assert all(path.is_file() for path in morgan_files)
    assert kept.is_file()


def test_audit_row_records_only_who_when_and_the_internal_id(practice) -> None:
    session = practice["session"]
    blob = practice["blob"]
    owner = str(practice["owner_id"])
    casey = practice["casey"]
    names = practice["names"]
    assert isinstance(casey, dict) and isinstance(names, dict) and isinstance(blob, LocalBlobAdapter)
    patient_id = str(casey["patient_id"])
    _calls(session, owner, patient_id, blob, confirm=True)

    rows = list(session.scalars(
        select(AuditEvent).where(
            AuditEvent.event_type == "patient.records_deleted",
            AuditEvent.aggregate_id == patient_id,
        )
    ))
    assert len(rows) == 1
    audit = rows[0]
    assert audit.actor_principal_id == owner
    assert audit.created_at is not None
    assert audit.aggregate_id == patient_id
    assert audit.aggregate_type == "patient_link"
    assert audit.detail == {}
    assert audit.outcome == "deleted"
    assert audit.initiated_by_principal_id is None
    assert audit.approved_by_principal_id is None
    assert audit.action_revision_id is None
    assert audit.payload_hash is None
    stored = session.scalar(
        text(
            "SELECT row_to_json(audit_events)::text FROM audit_events "
            "WHERE event_type = 'patient.records_deleted' AND aggregate_id = :patient_id"
        ),
        {"patient_id": patient_id},
    )
    assert isinstance(stored, str)
    for secret in (names["label"], names["note"], names["message"], names["transcript"]):
        assert str(secret) not in stored
        assert _text_hits(session, str(secret)) == 0


def test_repeat_delete_is_a_safe_no_op(practice) -> None:
    session = practice["session"]
    blob = practice["blob"]
    owner = str(practice["owner_id"])
    casey = practice["casey"]
    morgan = practice["morgan"]
    assert isinstance(casey, dict) and isinstance(morgan, dict) and isinstance(blob, LocalBlobAdapter)
    patient_id = str(casey["patient_id"])
    morgan_id = str(morgan["patient_id"])
    morgan_files = list(_paths(blob, morgan).values())
    first = _calls(session, owner, patient_id, blob, confirm=True)
    assert first["deleted"] is True

    second = _calls(session, owner, patient_id, blob, confirm=True)
    assert second["deleted"] is False
    assert second["dry_run"] is False
    assert second["tables"] == {}
    assert second["files"] == {"audio": 0, "uploads": 0, "exports": 0}
    cli = CliRunner().invoke(
        cli_app, ["delete-patient-records", patient_id, "--actor", owner, "--confirm"]
    )
    assert cli.exit_code == 0
    assert json.loads(cli.stdout)["deleted"] is False
    assert session.get(PatientLink, patient_id) is None
    assert session.get(PatientLink, morgan_id) is not None
    assert all(path.is_file() for path in morgan_files)
    assert session.scalar(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.event_type == "patient.records_deleted",
            AuditEvent.aggregate_id == patient_id,
        )
    ) == 1


def _migrate(target, revision: str, *, downgrade: bool) -> None:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.attributes["configure_logger"] = False
    with target.begin() as connection:
        config.attributes["connection"] = connection
        if downgrade:
            command.downgrade(config, revision)
        else:
            command.upgrade(config, revision)


def _revision(target) -> str:
    with target.connect() as connection:
        return str(connection.scalar(text("SELECT version_num FROM alembic_version")))


def _guard_bodies(target) -> dict[str, str]:
    with target.connect() as connection:
        return {
            name: str(connection.scalar(
                text("SELECT pg_get_functiondef(p.oid) FROM pg_proc p "
                     "JOIN pg_namespace n ON n.oid = p.pronamespace "
                     "WHERE n.nspname = 'public' AND p.proname = :name"),
                {"name": name},
            ))
            for name in GUARD_FUNCTIONS
        }


def test_patient_deletion_guard_migration_upgrades_and_downgrades(tmp_path) -> None:
    url = make_url(os.environ.get("DATABASE_URL", settings.database_url))
    assert url.host in {"127.0.0.1", "localhost"}
    name = "patdel_" + uuid4().hex
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    target = create_engine(url.set(database=name))
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        _migrate(target, EXPECTED_SCHEMA_REVISION, downgrade=False)
        assert _revision(target) == EXPECTED_SCHEMA_REVISION
        assert all("cosmas.patient_deletion" in body for body in _guard_bodies(target).values())
        blob = LocalBlobAdapter(tmp_path / "blobs")
        with Session(target) as session:
            arranged = _arrange(session, blob)
            finish_id = session.scalar(
                select(PrivateRecordingFinish.id).where(
                    PrivateRecordingFinish.recording_id == arranged["casey"]["recording_id"]
                )
            )
            assert finish_id is not None
            with pytest.raises(ProgrammingError, match="workspace history is immutable"):
                session.execute(
                    text("DELETE FROM private_recording_finishes WHERE id = :id"),
                    {"id": finish_id},
                )
                session.commit()
            session.rollback()

        _migrate(target, PARENT_REVISION, downgrade=True)
        assert _revision(target) == PARENT_REVISION
        assert all("cosmas.patient_deletion" not in body for body in _guard_bodies(target).values())
        with Session(target) as session:
            with pytest.raises(ProgrammingError, match="workspace history is immutable"):
                session.execute(text("SELECT set_config('cosmas.patient_deletion', 'on', true)"))
                session.execute(
                    text("DELETE FROM private_recording_finishes WHERE id = :id"),
                    {"id": finish_id},
                )
                session.commit()
            session.rollback()

        _migrate(target, EXPECTED_SCHEMA_REVISION, downgrade=False)
        assert _revision(target) == EXPECTED_SCHEMA_REVISION
        assert all("cosmas.patient_deletion" in body for body in _guard_bodies(target).values())
        with Session(target) as session:
            session.execute(text("SELECT set_config('cosmas.patient_deletion', 'on', true)"))
            session.execute(
                text("DELETE FROM private_recording_finishes WHERE id = :id"),
                {"id": finish_id},
            )
            session.commit()
            assert session.get(PrivateRecordingFinish, finish_id) is None
    finally:
        target.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()
