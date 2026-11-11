"""Admin deletion removes one patient's rows and files and leaves everyone else."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, ProgrammingError
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
from cosmas_os.domain.rules import AuthorizationError, DomainError
from cosmas_os.google_message_models import (
    GoogleMessageReadRequest,
    GoogleMessageSnapshot,
    GoogleMessageSourceReview,
)
from cosmas_os.microsoft_message_models import (
    MicrosoftMessageReadRequest,
    MicrosoftMessageSnapshot,
    MicrosoftMessageSourceReview,
)
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
PARENT_REVISION = "a46f2c09d853"
DELETION_ROLE = "cosmas_patient_deletion"
GUARD_FUNCTIONS = (
    "reject_workspace_history_change",
    "reject_provider_history_change",
    "immutable_patient_setup",
    "reject_scheduling_account_change",
)
_ENSURE_ROLE_SQL = ROOT / "scripts" / "ensure-patient-deletion-role.sql"


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
            "WHERE table_schema = 'public' AND column_name = 'patient_link_id' "
            "AND table_name NOT IN ("
            "  'patient_deletion_pending_files',"
            "  'patient_deletion_in_progress'"
            ")"
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
        clause = " OR ".join(f"strpos({_quote(column)}::text, :needle) > 0" for column in columns)
        found += int(
            session.scalar(
                text(f"SELECT count(*) FROM public.{_quote(table)} WHERE {clause}"),
                {"needle": needle},
            )
            or 0
        )
    return found


def _record(session: Session, box: str, owner: str, scribe_id: str, workspace_id: str) -> str:
    if (
        session.scalar(select(ExternalIdentity.id).where(ExternalIdentity.principal_id == owner))
        is None
    ):
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
    if (
        session.scalar(
            select(ProviderTeamRevision.id).where(ProviderTeamRevision.owner_id == owner)
        )
        is None
    ):
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
        container,
        box,
        container.session.scalar(
            select(Principal.id).where(Principal.box_id == box, Principal.agent_key == "chaser")
        ),
        appointment_id,
        link.id,
    )
    svc.decide(container, ticket.id, owner, DecisionKind.APPROVE)
    svc.simulate_upload_and_verify(container, ticket.id, owner, PNG, PNG)
    opened = workspace.create(container.session, box, owner, appointment_id, f"workspace-{slug}")
    workspace.append(
        container.session,
        box,
        owner,
        opened["id"],
        expected=opened["revision"],
        key=f"{slug}-transcript",
        kind="scratchpad",
        content=transcript,
    )
    noted = note_review.save(
        container.session,
        box,
        owner,
        opened["id"],
        expected=opened["revision"] + 1,
        key=f"{slug}-note",
        base_note_id=None,
        source_reply_id=None,
        content=note,
    )
    first_note = noted["workspace"]["note"]["latest"]["id"]
    note_review.save(
        container.session,
        box,
        owner,
        opened["id"],
        expected=noted["entry_revision"],
        key=f"{slug}-note-revised",
        base_note_id=first_note,
        source_reply_id=None,
        content=note + " revised",
    )
    workspace.append(
        container.session,
        box,
        owner,
        opened["id"],
        expected=noted["entry_revision"] + 1,
        key=f"{slug}-message",
        kind="conversation",
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
        container,
        label=names["label"],
        slug="casey-" + names["label"].split()[-1],
        note=names["note"],
        message=names["message"],
        transcript=names["transcript"],
        **common,
    )
    morgan = _visit(
        container,
        label=names["morgan_label"],
        slug="morgan-" + names["morgan_label"].split()[-1],
        note=names["morgan_note"],
        message=names["morgan_message"],
        transcript=names["morgan_transcript"],
        **common,
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


def _calls(session: Session, actor: str | None, patient_id: str, blob: LocalBlobAdapter, *, confirm: bool):
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
    # Throwaway synth only: create John's deletion role here, never via CI workflows.
    _ensure_patient_deletion_role(session)
    arranged = _arrange(session, blob)
    _bind_session_admin(session, str(arranged["owner_id"]), str(arranged["box_id"]))
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
    assert (
        isinstance(casey, dict) and isinstance(names, dict) and isinstance(blob, LocalBlobAdapter)
    )
    patient_id = str(casey["patient_id"])
    files = list(_paths(blob, casey).values()) + _upload_paths(
        session, blob, str(casey["ticket_id"])
    )
    assert all(path.is_file() for path in files)
    client = TestClient(app)
    path = f"/admin/patients/{patient_id}/records"
    admin_role, admin_url = _separate_admin_identity(session)
    try:
        for _actor, headers in (
            (staff, {"X-Box-Id": owner_box, "X-Actor-Principal-Id": staff}),
            (agent, {"X-Box-Id": owner_box, "X-Actor-Principal-Id": agent}),
        ):
            refused = client.post(path, json={"confirm": True}, headers=headers)
            assert refused.status_code == 403
            assert str(names["label"]) not in refused.text
            assert str(names["note"]) not in refused.text
            cli = CliRunner().invoke(
                cli_app,
                ["delete-patient-records", patient_id, "--confirm"],
                env={"COSMAS_ADMIN_DATABASE_URL": admin_url},
            )
            assert cli.exit_code == 1
            assert "admin authority required" in (cli.stderr or "")
            assert str(names["label"]) not in (cli.stderr or "")
            assert str(names["note"]) not in (cli.stderr or "")
    finally:
        _drop_admin_identity(session, admin_role)

    assert session.get(PatientLink, patient_id) is not None
    assert all(path.is_file() for path in files)
    assert (
        session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.event_type == "patient.records_deleted",
                AuditEvent.aggregate_id == patient_id,
            )
        )
        == 0
    )


def test_dry_run_returns_counts_and_deletes_nothing(practice) -> None:
    session = practice["session"]
    blob = practice["blob"]
    owner = str(practice["owner_id"])
    casey = practice["casey"]
    names = practice["names"]
    assert (
        isinstance(casey, dict) and isinstance(names, dict) and isinstance(blob, LocalBlobAdapter)
    )
    patient_id = str(casey["patient_id"])
    files = list(_paths(blob, casey).values()) + _upload_paths(
        session, blob, str(casey["ticket_id"])
    )
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
    blocked = TestClient(app).post(
        f"/admin/patients/{patient_id}/records",
        json={"confirm": True},
        headers={"X-Box-Id": str(practice["box_id"]), "X-Actor-Principal-Id": owner},
    )
    assert blocked.status_code == 403
    assert "admin command" in blocked.text
    assert str(names["label"]) not in blocked.text

    assert session.get(PatientLink, patient_id) is not None
    assert _patient_link_counts(session, patient_id) == before
    assert all(path.is_file() for path in files)
    assert (
        session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.event_type == "patient.records_deleted",
                AuditEvent.aggregate_id == patient_id,
            )
        )
        == 0
    )


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
    assert all(
        keyed[table] == 1
        for table in (
            "appointment_observations",
            "tickets",
            "encounter_workspaces",
            "scheduling_patient_accounts",
        )
    )
    files = list(_paths(blob, casey).values()) + _upload_paths(
        session, blob, str(casey["ticket_id"])
    )
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
    assert (
        isinstance(casey, dict) and isinstance(morgan, dict) and isinstance(blob, LocalBlobAdapter)
    )
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
    assert (
        isinstance(casey, dict) and isinstance(names, dict) and isinstance(blob, LocalBlobAdapter)
    )
    patient_id = str(casey["patient_id"])
    _calls(session, owner, patient_id, blob, confirm=True)

    rows = list(
        session.scalars(
            select(AuditEvent).where(
                AuditEvent.event_type == "patient.records_deleted",
                AuditEvent.aggregate_id == patient_id,
            )
        )
    )
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
    assert (
        isinstance(casey, dict) and isinstance(morgan, dict) and isinstance(blob, LocalBlobAdapter)
    )
    patient_id = str(casey["patient_id"])
    morgan_id = str(morgan["patient_id"])
    morgan_files = list(_paths(blob, morgan).values())
    first = _calls(session, owner, patient_id, blob, confirm=True)
    assert first["deleted"] is True

    with pytest.raises(DomainError, match="patient not found"):
        _calls(session, owner, patient_id, blob, confirm=True)
    session.rollback()
    admin_role, admin_url = _separate_admin_identity(session)
    try:
        _autocommit(session, f"GRANT cosmas_patient_deletion TO {admin_role}")
        _autocommit(
            session,
            f"GRANT EXECUTE ON FUNCTION public.delete_patient_keyed_records_plan(uuid) TO {admin_role}",
        )
        _autocommit(
            session,
            f"GRANT EXECUTE ON FUNCTION public.delete_patient_keyed_records(uuid) TO {admin_role}",
        )
        session.execute(
            text(
                """
                INSERT INTO public.patient_deletion_admin_bindings (db_role, principal_id, box_id)
                VALUES (:role, CAST(:principal AS uuid), CAST(:box AS uuid))
                ON CONFLICT (db_role) DO UPDATE
                  SET principal_id = EXCLUDED.principal_id,
                      box_id = EXCLUDED.box_id
                """
            ),
            {"role": admin_role, "principal": owner, "box": practice["box_id"]},
        )
        session.commit()
        cli = CliRunner().invoke(
            cli_app,
            ["delete-patient-records", patient_id, "--confirm"],
            env={"COSMAS_ADMIN_DATABASE_URL": admin_url},
        )
    finally:
        _drop_admin_identity(session, admin_role)
    assert cli.exit_code == 1
    assert (cli.stderr or "").strip() == "patient not found"
    assert session.get(PatientLink, patient_id) is None
    assert session.get(PatientLink, morgan_id) is not None
    assert all(path.is_file() for path in morgan_files)
    assert (
        session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.event_type == "patient.records_deleted",
                AuditEvent.aggregate_id == patient_id,
            )
        )
        == 1
    )


GUARDED_TABLES = (
    "workspace_entries",
    "workspace_replies",
    "scheduling_patient_setup_requests",
    "scheduling_patient_accounts",
)


_GUARD_MESSAGE = {
    "reject_workspace_history_change": "workspace history is immutable",
    "reject_provider_history_change": "provider history is immutable",
    "immutable_patient_setup": "patient setup history is immutable",
    "reject_scheduling_account_change": "Scheduling correspondence is immutable",
}


def _literal(column_type: str) -> str:
    if column_type == "uuid":
        return "'11111111-1111-4111-8111-111111111111'::uuid"
    if column_type == "jsonb":
        return "'{}'::jsonb"
    if column_type == "boolean":
        return "true"
    if column_type in {"integer", "bigint", "smallint"}:
        return "2"
    if column_type == "date":
        return "DATE '2026-09-10'"
    if column_type.startswith("timestamp"):
        return "TIMESTAMPTZ '2026-09-10 12:00:00+00'"
    if column_type == "text":
        return "'a'"
    if column_type == "integer[]":
        return "ARRAY[1]::integer[]"
    matched = re.fullmatch(r"character varying(?:\((\d+)\))?", column_type)
    if matched:
        length = int(matched.group(1) or "1")
        return "'" + ("a" * min(length, 32)) + "'"
    raise AssertionError(f"unsupported column type {column_type}")


def _patient_link_tables(session: Session) -> list[str]:
    return [
        str(table)
        for table in session.scalars(
            text(
                "SELECT table_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND column_name = 'patient_link_id' "
                "AND table_name NOT IN ("
                "  'patient_deletion_pending_files',"
                "  'patient_deletion_in_progress'"
                ") "
                "ORDER BY table_name"
            )
        )
    ]


def _seed_patient_linked_row(
    connection,
    table: str,
    *,
    patient_id: str,
    box_id: str,
    owner_id: str,
    known: dict[str, str],
) -> None:
    """Insert one synthetic row for a patient_link_id table. Fail closed on gaps."""

    columns = connection.execute(
        text(
            "SELECT a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull, "
            "pg_get_expr(ad.adbin, ad.adrelid) IS NOT NULL "
            "FROM pg_attribute a "
            "JOIN pg_class c ON c.oid = a.attrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "LEFT JOIN pg_attrdef ad ON ad.adrelid = a.attrelid AND ad.adnum = a.attnum "
            "WHERE n.nspname = 'public' AND c.relname = :table "
            "AND a.attnum > 0 AND NOT a.attisdropped AND a.attgenerated = '' "
            "ORDER BY a.attnum"
        ),
        {"table": table},
    ).all()
    names: list[str] = []
    values: list[str] = []
    present = {str(name) for name, _type, _required, _default in columns}
    for name, column_type, required, has_default in columns:
        column = str(name)
        if column == "patient_link_id":
            names.append(_quote(column))
            values.append(f"'{patient_id}'::uuid")
            continue
        if column == "box_id" and "box_id" in present:
            names.append(_quote(column))
            values.append(f"'{box_id}'::uuid")
            continue
        if column == "owner_id" and "owner_id" in present:
            names.append(_quote(column))
            values.append(f"'{owner_id}'::uuid")
            continue
        if column in known:
            names.append(_quote(column))
            values.append(f"'{known[column]}'::uuid")
            continue
        if has_default and str(column_type).startswith("timestamp"):
            continue
        if not required:
            continue
        names.append(_quote(column))
        if str(column_type) == "uuid":
            values.append(f"'{uuid4()}'::uuid")
        elif "sha256" in column or column.endswith("_hash") or column.endswith("hash"):
            values.append("'" + ("ab" * 32) + "'")
        elif column == "idempotency_key":
            values.append(f"'seedkey_{uuid4().hex[:8]}'")
        else:
            values.append(_literal(str(column_type)))
    if "patient_link_id" not in {str(name) for name, *_ in columns}:
        raise AssertionError(f"{table} has no patient_link_id column")
    connection.execute(
        text(
            f"INSERT INTO public.{_quote(table)} ({', '.join(names)}) VALUES ({', '.join(values)})"
        )
    )


def _check_constraints(connection, tables: Sequence[str]) -> list[tuple[str, str, str]]:
    rows = connection.execute(
        text(
            "SELECT c.relname, con.conname, pg_get_constraintdef(con.oid) "
            "FROM pg_constraint con "
            "JOIN pg_class c ON c.oid = con.conrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND con.contype = 'c' "
            "AND c.relname = ANY(:tables) "
            "ORDER BY c.relname, con.conname"
        ),
        {"tables": list(tables)},
    ).all()
    return [(str(table), str(name), str(definition)) for table, name, definition in rows]


def _seed_all_patient_linked_tables(session: Session, practice: dict[str, object]) -> list[str]:
    """Seed every patient_link_id table for one patient. Name any table that cannot be seeded."""

    casey = practice["casey"]
    assert isinstance(casey, dict)
    patient_id = str(casey["patient_id"])
    box_id = str(practice["box_id"])
    owner_id = str(practice["owner_id"])
    known = {
        "ticket_id": str(casey["ticket_id"]),
        "workspace_id": str(casey["workspace_id"]),
        "appointment_id": str(casey["appointment_id"]),
        "recording_id": str(casey["recording_id"]),
        "target_workspace_id": str(casey["workspace_id"]),
        "origin_workspace_id": str(casey["workspace_id"]),
    }
    finish_id = session.scalar(
        select(PrivateRecordingFinish.id).where(
            PrivateRecordingFinish.recording_id == casey["recording_id"]
        )
    )
    if finish_id is not None:
        known["finish_id"] = str(finish_id)
    note_id = session.scalar(
        select(WorkspaceNote.id).where(WorkspaceNote.workspace_id == casey["workspace_id"]).limit(1)
    )
    if note_id is not None:
        known["note_id"] = str(note_id)
    tables = _patient_link_tables(session)
    if len(tables) != 34:
        raise AssertionError(f"expected 34 patient-linked tables, found {len(tables)}: {tables}")
    bind = session.get_bind()
    with bind.connect() as connection:
        transaction = connection.begin()
        dropped: list[tuple[str, str, str]] = []
        try:
            connection.execute(text("SET LOCAL session_replication_role = replica"))
            # Generic path: temporarily clear CHECKs so every patient_link_id
            # table can take one synthetic row. Restore before the test returns.
            dropped = _check_constraints(connection, tables)
            for table, name, _definition in dropped:
                connection.execute(
                    text(f"ALTER TABLE public.{_quote(table)} DROP CONSTRAINT {_quote(name)}")
                )
            for table in tables:
                existing = connection.scalar(
                    text(
                        f"SELECT count(*) FROM public.{_quote(table)} "
                        "WHERE patient_link_id = CAST(:patient AS uuid)"
                    ),
                    {"patient": patient_id},
                )
                if int(existing or 0) > 0:
                    continue
                try:
                    _seed_patient_linked_row(
                        connection,
                        table,
                        patient_id=patient_id,
                        box_id=box_id,
                        owner_id=owner_id,
                        known=known,
                    )
                except Exception as exc:  # noqa: BLE001 - name the table; never skip
                    raise AssertionError(
                        f"could not seed patient-linked table {table}: {exc}"
                    ) from exc
            _seed_ehr_request_snapshot_cycle(
                connection,
                patient_id=patient_id,
                box_id=box_id,
                owner_id=owner_id,
            )
            for table, name, definition in dropped:
                connection.execute(
                    text(
                        f"ALTER TABLE public.{_quote(table)} "
                        f"ADD CONSTRAINT {_quote(name)} {definition} NOT VALID"
                    )
                )
            transaction.commit()
        except Exception:
            transaction.rollback()
            raise
    session.expire_all()
    counts = _patient_link_counts(session, patient_id)
    missing = [table for table in tables if counts.get(table, 0) < 1]
    if missing:
        raise AssertionError("could not seed patient-linked table(s): " + ", ".join(missing))
    snapshots = int(
        session.scalar(
            text(
                "SELECT count(*) FROM public.ehr_read_snapshots s "
                "JOIN public.ehr_read_requests r ON r.id = s.observation_id "
                "WHERE r.patient_link_id = CAST(:patient AS uuid)"
            ),
            {"patient": patient_id},
        )
        or 0
    )
    if snapshots < 1:
        raise AssertionError("could not seed ehr_read_snapshots for the patient")
    return tables


def _seed_ehr_request_snapshot_cycle(
    connection,
    *,
    patient_id: str,
    box_id: str,
    owner_id: str,
) -> None:
    """Attach a saved EHR snapshot (and a child request) to one patient request."""

    request = connection.execute(
        text(
            """
            SELECT id, box_id, owner_id FROM public.ehr_read_requests
             WHERE patient_link_id = CAST(:patient AS uuid)
             ORDER BY created_at NULLS LAST, id
             LIMIT 1
            """
        ),
        {"patient": patient_id},
    ).first()
    if request is None:
        raise AssertionError("ehr_read_requests row missing for snapshot seed")
    request_id, request_box, request_owner = (
        str(request[0]),
        str(request[1]),
        str(request[2]),
    )
    snapshot_id = str(uuid4())
    digest = "ab" * 32
    connection.execute(
        text(
            """
            INSERT INTO public.ehr_read_snapshots (
              id, observation_id, payload, payload_sha256, source_sha256,
              box_id, owner_id
            ) VALUES (
              CAST(:snapshot AS uuid), CAST(:request AS uuid), '{}'::jsonb,
              :digest, :digest, CAST(:box AS uuid), CAST(:owner AS uuid)
            )
            ON CONFLICT DO NOTHING
            """
        ),
        {
            "snapshot": snapshot_id,
            "request": request_id,
            "digest": digest,
            "box": request_box or box_id,
            "owner": request_owner or owner_id,
        },
    )
    # Child request that points at the saved snapshot closes the cycle the
    # DEFERRABLE FKs must survive during one-transaction deletion.
    existing_child = connection.scalar(
        text(
            """
            SELECT 1 FROM public.ehr_read_requests
             WHERE patient_link_id = CAST(:patient AS uuid)
               AND parent_snapshot_id = CAST(:snapshot AS uuid)
             LIMIT 1
            """
        ),
        {"patient": patient_id, "snapshot": snapshot_id},
    )
    if existing_child:
        return
    parent = (
        connection.execute(
            text(
                """
            SELECT binding_id, account_id, connection_id, credential_generation,
                   binding_digest, workspace_id
              FROM public.ehr_read_requests
             WHERE id = CAST(:request AS uuid)
            """
            ),
            {"request": request_id},
        )
        .mappings()
        .one()
    )
    connection.execute(
        text(
            """
            INSERT INTO public.ehr_read_requests (
              id, binding_id, account_id, connection_id, credential_generation,
              binding_digest, kind, ordinal, idempotency_key, request_hash,
              request_json, parent_snapshot_id, item_handle, workspace_id,
              patient_link_id, valid_until, box_id, owner_id, transport
            ) VALUES (
              CAST(:id AS uuid), CAST(:binding AS uuid), CAST(:account AS uuid),
              CAST(:connection AS uuid), CAST(:credential AS uuid), :digest,
              'lab_report', :ordinal, :idempotency, :digest, '{}'::jsonb,
              CAST(:snapshot AS uuid), CAST(:item AS uuid),
              CAST(:workspace AS uuid), CAST(:patient AS uuid),
              now() + interval '10 minutes', CAST(:box AS uuid), CAST(:owner AS uuid),
              'mock'
            )
            """
        ),
        {
            "id": str(uuid4()),
            "binding": str(parent["binding_id"]),
            "account": str(parent["account_id"]),
            "connection": str(parent["connection_id"]),
            "credential": str(parent["credential_generation"]),
            "digest": str(parent["binding_digest"]) if parent["binding_digest"] else digest,
            "ordinal": int(
                connection.scalar(
                    text(
                        "SELECT COALESCE(MAX(ordinal), 0) + 1 "
                        "FROM public.ehr_read_requests "
                        "WHERE binding_id = CAST(:binding AS uuid)"
                    ),
                    {"binding": str(parent["binding_id"])},
                )
                or 1
            ),
            "idempotency": f"seedchild_{uuid4().hex[:8]}",
            "snapshot": snapshot_id,
            "item": str(uuid4()),
            "workspace": str(parent["workspace_id"]) if parent["workspace_id"] else None,
            "patient": patient_id,
            "box": request_box or box_id,
            "owner": request_owner or owner_id,
        },
    )


def _guarded_triggers(connection) -> list[tuple[str, str]]:
    rows = connection.execute(
        text(
            "SELECT c.relname, p.proname FROM pg_trigger t "
            "JOIN pg_proc p ON p.oid = t.tgfoid "
            "JOIN pg_class c ON c.oid = t.tgrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND NOT t.tgisinternal "
            "AND p.proname = ANY(:names) "
            "GROUP BY c.relname, p.proname ORDER BY c.relname"
        ),
        {"names": list(GUARD_FUNCTIONS)},
    ).all()
    return [(str(table), str(function)) for table, function in rows]


def _insert_guard_row(connection, table: str) -> None:
    columns = connection.execute(
        text(
            "SELECT a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull, "
            "pg_get_expr(ad.adbin, ad.adrelid) IS NOT NULL "
            "FROM pg_attribute a "
            "JOIN pg_class c ON c.oid = a.attrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "LEFT JOIN pg_attrdef ad ON ad.adrelid = a.attrelid AND ad.adnum = a.attnum "
            "WHERE n.nspname = 'public' AND c.relname = :table "
            "AND a.attnum > 0 AND NOT a.attisdropped AND a.attgenerated = '' "
            "ORDER BY a.attnum"
        ),
        {"table": table},
    ).all()
    names: list[str] = []
    values: list[str] = []
    for name, column_type, required, has_default in columns:
        if has_default and str(column_type).startswith("timestamp"):
            continue
        if not required:
            continue
        names.append(_quote(str(name)))
        values.append(_literal(str(column_type)))
    if names:
        connection.execute(
            text(
                f"INSERT INTO public.{_quote(table)} ({', '.join(names)}) VALUES ({', '.join(values)})"
            )
        )
    else:
        connection.execute(text(f"INSERT INTO public.{_quote(table)} DEFAULT VALUES"))


def _autocommit(session: Session, statement: str) -> None:
    bind = session.get_bind()
    with bind.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(text(statement))


def _run_statements(connection, statements: tuple[str, ...]) -> None:
    for statement in statements:
        connection.execute(text(statement))


def _run_ensure_patient_deletion_role_sql(connection) -> None:
    """Execute John's real ensure script. No copy and no extra grants."""

    sql = _ENSURE_ROLE_SQL.read_text(encoding="utf-8")
    connection.execute(text(sql))


def _ensure_patient_deletion_role(session: Session) -> None:
    """John's role setup, limited to this throwaway synthetic database session."""

    bind = session.get_bind()
    with bind.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        _run_ensure_patient_deletion_role_sql(connection)
        connection.execute(text("GRANT cosmas_patient_deletion TO CURRENT_USER"))


def _ensure_patient_deletion_role_on(engine) -> None:
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        _run_ensure_patient_deletion_role_sql(connection)
        connection.execute(text("GRANT cosmas_patient_deletion TO CURRENT_USER"))


def _bind_session_admin(session: Session, principal_id: str, box_id: str) -> None:
    session.execute(
        text(
            """
            INSERT INTO public.patient_deletion_admin_bindings (db_role, principal_id, box_id)
            VALUES (session_user, CAST(:principal AS uuid), CAST(:box AS uuid))
            ON CONFLICT (db_role) DO UPDATE
              SET principal_id = EXCLUDED.principal_id,
                  box_id = EXCLUDED.box_id
            """
        ),
        {"principal": principal_id, "box": box_id},
    )
    session.commit()


def _drop_patient_deletion_role(admin_engine, databases: tuple[str, ...]) -> None:
    """Return function ownership, then drop the cluster role for no-role migrate tests."""

    url = make_url(os.environ.get("DATABASE_URL", settings.database_url))
    # Include postgres: John's ensure script may have granted schema usage there.
    for database in tuple(dict.fromkeys((*databases, "postgres"))):
        engine = create_engine(url.set(database=database))
        try:
            with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
                role_present = connection.scalar(
                    text("SELECT 1 FROM pg_roles WHERE rolname = :role"),
                    {"role": DELETION_ROLE},
                )
                if connection.scalar(
                    text(
                        "SELECT to_regprocedure('public.delete_patient_keyed_records(uuid)')"
                    )
                ):
                    connection.execute(
                        text(
                            "ALTER FUNCTION public.delete_patient_keyed_records(uuid) "
                            "OWNER TO CURRENT_USER"
                        )
                    )
                if role_present:
                    connection.execute(
                        text(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {DELETION_ROLE}")
                    )
                    connection.execute(text(f"REVOKE ALL ON SCHEMA public FROM {DELETION_ROLE}"))
                    connection.execute(
                        text(
                            "DO $$ BEGIN "
                            "IF to_regprocedure('public.delete_patient_keyed_records(uuid)') "
                            "IS NOT NULL THEN "
                            "REVOKE ALL ON FUNCTION "
                            "public.delete_patient_keyed_records(uuid) "
                            "FROM cosmas_patient_deletion; "
                            "END IF; "
                            "IF to_regprocedure("
                            "'public._cosmas_apply_patient_deletion_mutate(uuid)') "
                            "IS NOT NULL THEN "
                            "REVOKE ALL ON FUNCTION "
                            "public._cosmas_apply_patient_deletion_mutate(uuid) "
                            "FROM cosmas_patient_deletion; "
                            "END IF; "
                            "END $$"
                        )
                    )
                    connection.execute(
                        text("REASSIGN OWNED BY cosmas_patient_deletion TO CURRENT_USER")
                    )
                    connection.execute(text("DROP OWNED BY cosmas_patient_deletion"))
        finally:
            engine.dispose()
    with admin_engine.connect() as connection:
        connection.execute(text(f"DROP ROLE IF EXISTS {DELETION_ROLE}"))


def _runtime_engine(session: Session, role: str):
    url = make_url(os.environ.get("DATABASE_URL", settings.database_url))
    database = str(session.scalar(text("SELECT current_database()")))
    password = "invented-runtime-password-123456"
    _autocommit(
        session,
        f"CREATE ROLE {role} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT "
        f"PASSWORD '{password}'",
    )
    _autocommit(session, f'GRANT CONNECT ON DATABASE "{database}" TO {role}')
    _autocommit(session, f"GRANT USAGE ON SCHEMA public TO {role}")
    return create_engine(
        url.set(
            drivername="postgresql+psycopg", username=role, password=password, database=database
        )
    )


def _drop_runtime_role(session: Session, role: str) -> None:
    _autocommit(session, f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {role}")
    _autocommit(session, f"REVOKE ALL ON SCHEMA public FROM {role}")
    database = str(session.scalar(text("SELECT current_database()")))
    _autocommit(session, f'REVOKE CONNECT ON DATABASE "{database}" FROM {role}')
    _autocommit(session, f"DROP ROLE IF EXISTS {role}")


def test_runtime_role_cannot_delete_guarded_tables_with_the_flag() -> None:
    """A runtime login that sets the flag by hand still cannot delete any guarded table."""

    url = make_url(os.environ.get("DATABASE_URL", settings.database_url))
    assert url.host in {"127.0.0.1", "localhost"}
    database = "patdel_guard_" + uuid4().hex[:12]
    role = "patient_runtime_" + uuid4().hex[:12]
    password = "invented-runtime-password-123456"
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    target = create_engine(url.set(database=database))
    runtime = None
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{database}"'))
    try:
        _migrate(target, EXPECTED_SCHEMA_REVISION, downgrade=False)
        with admin.connect() as connection:
            connection.execute(
                text(
                    f"CREATE ROLE {role} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT "
                    f"PASSWORD '{password}'"
                )
            )
            connection.execute(text(f'GRANT CONNECT ON DATABASE "{database}" TO {role}'))
        with target.begin() as connection:
            connection.execute(text(f"GRANT USAGE ON SCHEMA public TO {role}"))
            guarded = _guarded_triggers(connection)
            tables = [table for table, _function in guarded]
            assert set(GUARDED_TABLES) <= set(tables)
            checks = connection.execute(
                text(
                    "SELECT c.relname, con.conname FROM pg_constraint con "
                    "JOIN pg_class c ON c.oid = con.conrelid "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE con.contype = 'c' AND n.nspname = 'public' AND c.relname = ANY(:tables)"
                ),
                {"tables": tables},
            ).all()
            for table, constraint in checks:
                connection.execute(
                    text(
                        f"ALTER TABLE public.{_quote(str(table))} DROP CONSTRAINT {_quote(str(constraint))}"
                    )
                )
            connection.execute(text("SET LOCAL session_replication_role = replica"))
            for table in tables:
                _insert_guard_row(connection, table)
            connection.execute(
                text(
                    "GRANT SELECT, DELETE ON "
                    + ", ".join(f"public.{_quote(table)}" for table in tables)
                    + f" TO {role}"
                )
            )
        runtime = create_engine(
            url.set(
                drivername="postgresql+psycopg", username=role, password=password, database=database
            )
        )
        for table, function in guarded:
            message = _GUARD_MESSAGE[function]
            with runtime.connect() as connection:
                transaction = connection.begin()
                refused = False
                try:
                    # Caller-settable gates are gone; a runtime role still cannot
                    # delete guarded history even after SET ROLE attempts fail.
                    connection.execute(
                        text(
                            f"DELETE FROM public.{_quote(table)} "
                            f"WHERE ctid = (SELECT ctid FROM public.{_quote(table)} LIMIT 1)"
                        )
                    )
                except (ProgrammingError, IntegrityError) as exc:
                    refused = message in str(exc)
                finally:
                    transaction.rollback()
            assert refused, table
            with target.connect() as connection:
                assert connection.scalar(text(f"SELECT count(*) FROM public.{_quote(table)}")) == 1
    finally:
        if runtime is not None:
            runtime.dispose()
        target.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
            connection.execute(text(f"DROP ROLE IF EXISTS {role}"))
        admin.dispose()


def _separate_admin_identity(session: Session) -> tuple[str, str]:
    runtime_url = os.environ.get("DATABASE_URL", settings.database_url)
    parsed = make_url(runtime_url)
    role = "patient_admin_" + uuid4().hex[:12]
    password = parsed.password
    assert isinstance(password, str) and password
    quoted = session.scalar(text("SELECT quote_literal(:password)"), {"password": password})
    assert isinstance(quoted, str)
    _autocommit(session, f"CREATE ROLE {role} LOGIN SUPERUSER PASSWORD {quoted}")
    admin_url = parsed.set(username=role).render_as_string(hide_password=False)
    assert admin_url != runtime_url
    assert make_url(admin_url).username == role
    assert make_url(admin_url).username != parsed.username
    return role, admin_url


def _drop_admin_identity(session: Session, role: str) -> None:
    _autocommit(
        session,
        f"REVOKE ALL ON FUNCTION public.delete_patient_keyed_records(uuid) FROM {role}",
    )
    _autocommit(
        session,
        f"REVOKE ALL ON FUNCTION public.delete_patient_keyed_records_plan(uuid) FROM {role}",
    )
    _autocommit(session, f"DROP ROLE IF EXISTS {role}")


def test_runtime_role_cannot_set_role_to_the_deletion_role(practice) -> None:
    session = practice["session"]
    role = "patient_runtime_" + uuid4().hex[:12]
    runtime = _runtime_engine(session, role)
    try:
        chain = session.scalar(
            text(
                "WITH RECURSIVE granted_roles AS ("
                "  SELECT m.roleid FROM pg_auth_members m "
                "  JOIN pg_roles member ON member.oid = m.member "
                "  WHERE member.rolname = :role "
                "  UNION "
                "  SELECT m.roleid FROM pg_auth_members m "
                "  JOIN granted_roles parent ON m.member = parent.roleid"
                ") "
                "SELECT EXISTS ("
                "  SELECT 1 FROM granted_roles granted_role "
                "  JOIN pg_roles granted ON granted.oid = granted_role.roleid "
                "  WHERE granted.rolname = 'cosmas_patient_deletion'"
                ")"
            ),
            {"role": role},
        )
        assert chain is False
        with runtime.connect() as connection:
            transaction = connection.begin()
            try:
                for privilege in ("MEMBER", "USAGE", "SET"):
                    allowed = connection.scalar(
                        text(
                            "SELECT pg_has_role(current_user, 'cosmas_patient_deletion', :privilege)"
                        ),
                        {"privilege": privilege},
                    )
                    assert allowed is False
                with pytest.raises(ProgrammingError, match="permission denied"):
                    connection.execute(text("SET ROLE cosmas_patient_deletion"))
            finally:
                transaction.rollback()
    finally:
        runtime.dispose()
        _drop_runtime_role(session, role)


def test_admin_cli_refuses_a_missing_or_runtime_database_url(practice, monkeypatch) -> None:
    session = practice["session"]
    patient_id = str(practice["casey"]["patient_id"])
    runtime_url = os.environ.get("DATABASE_URL", settings.database_url)
    monkeypatch.delenv("COSMAS_ADMIN_DATABASE_URL", raising=False)
    missing = CliRunner().invoke(
        cli_app, ["delete-patient-records", patient_id, "--confirm"]
    )
    assert missing.exit_code == 1
    assert "admin database identity is not configured" in (missing.stderr or "")
    assert "admin authority required" not in (missing.stderr or "")
    monkeypatch.setenv("COSMAS_ADMIN_DATABASE_URL", runtime_url)
    same = CliRunner().invoke(
        cli_app, ["delete-patient-records", patient_id, "--confirm"]
    )
    assert same.exit_code == 1
    assert "admin database identity is not configured" in (same.stderr or "")
    renamed = (
        make_url(runtime_url)
        .set(query={"application_name": "patient-deletion"})
        .render_as_string(hide_password=False)
    )
    assert renamed != runtime_url
    monkeypatch.setenv("COSMAS_ADMIN_DATABASE_URL", renamed)
    same_role = CliRunner().invoke(
        cli_app, ["delete-patient-records", patient_id, "--confirm"]
    )
    assert same_role.exit_code == 1
    assert "admin database identity is not configured" in (same_role.stderr or "")
    assert session.get(PatientLink, patient_id) is not None


def test_runtime_role_cannot_execute_the_deletion_function(practice) -> None:
    session = practice["session"]
    role = "patient_runtime_" + uuid4().hex[:12]
    runtime = _runtime_engine(session, role)
    try:
        assert (
            session.scalar(
                text(
                    "SELECT NOT EXISTS (SELECT 1 FROM pg_auth_members m "
                    "JOIN pg_roles granted ON granted.oid = m.roleid "
                    "JOIN pg_roles member ON member.oid = m.member "
                    "WHERE granted.rolname = 'cosmas_patient_deletion' AND member.rolname = :role)"
                ),
                {"role": role},
            )
            is True
        )
        with runtime.begin() as connection:
            with pytest.raises(ProgrammingError, match="permission denied"):
                connection.execute(text("SET ROLE cosmas_patient_deletion"))
        with runtime.begin() as connection:
            with pytest.raises(ProgrammingError, match="permission denied"):
                connection.execute(
                    text(
                        "SELECT public.delete_patient_keyed_records("
                        "CAST(:patient AS uuid))"
                    ),
                    {
                        "patient": practice["casey"]["patient_id"],
                    },
                )
        assert (
            session.scalar(
                text(
                    "SELECT has_function_privilege(:role, "
                    "'public.delete_patient_keyed_records(uuid)', 'EXECUTE')"
                ),
                {"role": role},
            )
            is False
        )
    finally:
        runtime.dispose()
        _drop_runtime_role(session, role)


def test_audit_log_rows_survive_with_identifiers_removed(practice) -> None:
    session = practice["session"]
    blob = practice["blob"]
    owner = str(practice["owner_id"])
    casey = practice["casey"]
    names = practice["names"]
    patient_id = str(casey["patient_id"])
    attested = session.scalar(
        select(AuditEvent).where(
            AuditEvent.event_type == "patient_link.attested",
            AuditEvent.aggregate_id == patient_id,
        )
    )
    assert attested is not None
    attested_id = attested.id
    attested_actor = attested.actor_principal_id
    attested_at = attested.created_at
    _calls(session, owner, patient_id, blob, confirm=True)
    session.expire_all()
    kept = session.get(AuditEvent, attested_id)
    assert kept is not None
    assert kept.actor_principal_id == attested_actor
    assert kept.created_at == attested_at
    assert kept.event_type == "patient_link.attested"
    assert kept.aggregate_id == "redacted"
    assert kept.aggregate_id != patient_id
    assert kept.detail == {}
    stored = session.scalar(
        text("SELECT row_to_json(audit_events)::text FROM audit_events WHERE id = :id"),
        {"id": attested_id},
    )
    assert isinstance(stored, str)
    assert patient_id not in stored
    assert str(names["label"]) not in stored
    assert str(names["note"]) not in stored
    deletion = session.scalar(
        select(AuditEvent).where(
            AuditEvent.event_type == "patient.records_deleted",
            AuditEvent.aggregate_id == patient_id,
        )
    )
    assert deletion is not None
    assert deletion.id != attested_id


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
            name: str(
                connection.scalar(
                    text(
                        "SELECT pg_get_functiondef(p.oid) FROM pg_proc p "
                        "JOIN pg_namespace n ON n.oid = p.pronamespace "
                        "WHERE n.nspname = 'public' AND p.proname = :name"
                    ),
                    {"name": name},
                )
            )
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
        # Role must exist before migrate so ownership handoff runs on this synth DB.
        _ensure_patient_deletion_role_on(admin)
        _migrate(target, EXPECTED_SCHEMA_REVISION, downgrade=False)
        assert _revision(target) == EXPECTED_SCHEMA_REVISION
        assert all("_cosmas_patient_deletion_active" in body for body in _guard_bodies(target).values())
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
        assert all("_cosmas_patient_deletion_active" not in body for body in _guard_bodies(target).values())
        with Session(target) as session:
            with pytest.raises(ProgrammingError, match="workspace history is immutable"):
                session.execute(
                    text("DELETE FROM private_recording_finishes WHERE id = :id"),
                    {"id": finish_id},
                )
                session.commit()
            session.rollback()

        _migrate(target, EXPECTED_SCHEMA_REVISION, downgrade=False)
        assert _revision(target) == EXPECTED_SCHEMA_REVISION
        assert all("_cosmas_patient_deletion_active" in body for body in _guard_bodies(target).values())
        with Session(target) as session:
            with pytest.raises(ProgrammingError, match="workspace history is immutable"):
                session.execute(
                    text("DELETE FROM private_recording_finishes WHERE id = :id"),
                    {"id": finish_id},
                )
                session.commit()
            session.rollback()
            _ensure_patient_deletion_role(session)
            _bind_session_admin(
                session, str(arranged["owner_id"]), str(arranged["box_id"])
            )
            _calls(
                session,
                str(arranged["owner_id"]),
                str(arranged["casey"]["patient_id"]),
                blob,
                confirm=True,
            )
            assert session.get(PrivateRecordingFinish, finish_id) is None
            assert session.get(PatientLink, arranged["casey"]["patient_id"]) is None
    finally:
        target.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def test_migration_applies_when_deletion_role_is_missing(caplog) -> None:
    url = make_url(os.environ.get("DATABASE_URL", settings.database_url))
    assert url.host in {"127.0.0.1", "localhost"}
    shared = str(url.database)
    name = "patdel_norole_" + uuid4().hex[:12]
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    target = create_engine(url.set(database=name))
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        _drop_patient_deletion_role(admin, (shared, name))
        with caplog.at_level(logging.INFO, logger="alembic.runtime.migration"):
            _migrate(target, EXPECTED_SCHEMA_REVISION, downgrade=False)
        assert _revision(target) == EXPECTED_SCHEMA_REVISION
        assert "cosmas_patient_deletion is missing; grant skipped" in caplog.text
        with target.connect() as connection:
            owner = connection.scalar(
                text(
                    "SELECT r.rolname FROM pg_proc p "
                    "JOIN pg_roles r ON r.oid = p.proowner "
                    "WHERE p.oid = 'public.delete_patient_keyed_records(uuid)'::regprocedure"
                )
            )
            assert owner is not None
            assert owner != DELETION_ROLE
            assert (
                connection.scalar(
                    text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": DELETION_ROLE}
                )
                is None
            )
    finally:
        target.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        # Restore John's role for later tests on this synthetic cluster.
        _ensure_patient_deletion_role_on(create_engine(url))
        admin.dispose()


def test_confirm_refuses_when_deletion_role_is_missing(engine, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "blob_root", str(tmp_path / "blobs"))
    blob = LocalBlobAdapter(tmp_path / "blobs")
    session = Session(engine)
    admin = create_engine(
        make_url(os.environ.get("DATABASE_URL", settings.database_url)).set(database="postgres"),
        isolation_level="AUTOCOMMIT",
    )
    try:
        arranged = _arrange(session, blob)
        casey = arranged["casey"]
        patient_id = str(casey["patient_id"])
        files = list(_paths(blob, casey).values()) + _upload_paths(
            session, blob, str(casey["ticket_id"])
        )
        assert all(path.is_file() for path in files)
        before = _patient_link_counts(session, patient_id)
        _drop_patient_deletion_role(
            admin, (str(session.scalar(text("SELECT current_database()"))),)
        )
        with pytest.raises(DomainError, match="deletion role not configured"):
            _calls(session, str(arranged["owner_id"]), patient_id, blob, confirm=True)
        session.rollback()
        assert _patient_link_counts(session, patient_id) == before
        assert all(path.is_file() for path in files)
        dry = _calls(session, str(arranged["owner_id"]), patient_id, blob, confirm=False)
        assert dry["dry_run"] is True
        assert dry["deleted"] is False
        assert dry["tables"]
    finally:
        _ensure_patient_deletion_role(session)
        session.close()
        admin.dispose()


def test_migration_applies_as_restricted_migrator_with_and_without_deletion_role(caplog) -> None:
    """Compact-style migrator: non-superuser DB owner, no SET on the deletion role."""

    url = make_url(os.environ.get("DATABASE_URL", settings.database_url))
    assert url.host in {"127.0.0.1", "localhost"}
    shared = str(url.database)
    password = "invented-compact-migrator-password"
    quoted = None
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        quoted = connection.scalar(text("SELECT quote_literal(:password)"), {"password": password})
    assert isinstance(quoted, str)

    def _restricted_database(suffix: str) -> tuple[str, str, object]:
        database = f"patdel_restr_{suffix}_" + uuid4().hex[:10]
        migrator = f"patdel_mig_{suffix}_" + uuid4().hex[:10]
        with admin.connect() as connection:
            connection.execute(
                text(
                    f"CREATE ROLE {migrator} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                    f"NOINHERIT PASSWORD {quoted}"
                )
            )
            connection.execute(text(f'CREATE DATABASE "{database}" OWNER {migrator}'))
        engine = create_engine(
            url.set(
                drivername="postgresql+psycopg",
                username=migrator,
                password=password,
                database=database,
            )
        )
        return database, migrator, engine

    without_db, without_role, without_engine = _restricted_database("no")
    with_db, with_role, with_engine = _restricted_database("yes")
    try:
        _drop_patient_deletion_role(admin, (shared, without_db, with_db))
        with caplog.at_level(logging.INFO, logger="alembic.runtime.migration"):
            _migrate(without_engine, EXPECTED_SCHEMA_REVISION, downgrade=False)
        assert _revision(without_engine) == EXPECTED_SCHEMA_REVISION
        assert "cosmas_patient_deletion is missing; grant skipped" in caplog.text
        with without_engine.connect() as connection:
            assert connection.scalar(text("SELECT current_user")) == without_role
            owner = connection.scalar(
                text(
                    "SELECT r.rolname FROM pg_proc p "
                    "JOIN pg_roles r ON r.oid = p.proowner "
                    "WHERE p.oid = to_regprocedure("
                    "'public.delete_patient_keyed_records(uuid)')"
                )
            )
            assert owner == without_role

        # Role exists on the cluster but this migrator cannot SET ROLE to it.
        with admin.connect() as connection:
            connection.execute(
                text(
                    "DO $$ BEGIN "
                    "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cosmas_patient_deletion') THEN "
                    "CREATE ROLE cosmas_patient_deletion NOLOGIN NOINHERIT; "
                    "END IF; END $$"
                )
            )
        caplog.clear()
        with caplog.at_level(logging.INFO, logger="alembic.runtime.migration"):
            _migrate(with_engine, EXPECTED_SCHEMA_REVISION, downgrade=False)
        assert _revision(with_engine) == EXPECTED_SCHEMA_REVISION
        with with_engine.connect() as connection:
            assert connection.scalar(text("SELECT current_user")) == with_role
            assert not connection.scalar(
                text("SELECT pg_has_role(current_user, :role, 'SET')"),
                {"role": DELETION_ROLE},
            )
            owner = connection.scalar(
                text(
                    "SELECT r.rolname FROM pg_proc p "
                    "JOIN pg_roles r ON r.oid = p.proowner "
                    "WHERE p.oid = to_regprocedure("
                    "'public.delete_patient_keyed_records(uuid)')"
                )
            )
            assert owner == with_role
            assert connection.scalar(
                text(
                    "SELECT has_function_privilege(:role, "
                    "'public.delete_patient_keyed_records(uuid)', 'EXECUTE')"
                ),
                {"role": DELETION_ROLE},
            )
    finally:
        without_engine.dispose()
        with_engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{without_db}" WITH (FORCE)'))
            connection.execute(text(f'DROP DATABASE IF EXISTS "{with_db}" WITH (FORCE)'))
            connection.execute(text(f"DROP ROLE IF EXISTS {without_role}"))
            connection.execute(text(f"DROP ROLE IF EXISTS {with_role}"))
        _ensure_patient_deletion_role_on(create_engine(url))
        admin.dispose()


def test_admin_cli_prints_each_fixed_refusal_reason(practice) -> None:
    session = practice["session"]
    owner = str(practice["owner_id"])
    casey = practice["casey"]
    names = practice["names"]
    assert isinstance(casey, dict) and isinstance(names, dict)
    patient_id = str(casey["patient_id"])
    admin_role, admin_url = _separate_admin_identity(session)
    env = {"COSMAS_ADMIN_DATABASE_URL": admin_url}
    try:
        missing_flags = CliRunner().invoke(
            cli_app,
            ["delete-patient-records", patient_id],
            env=env,
        )
        assert missing_flags.exit_code == 1
        assert (missing_flags.stderr or "").strip() == "confirm required"
        assert str(names["label"]) not in (missing_flags.stderr or "")

        bad_patient = CliRunner().invoke(
            cli_app,
            ["delete-patient-records", "not-a-patient-id", "--dry-run"],
            env=env,
        )
        assert bad_patient.exit_code == 1
        assert (bad_patient.stderr or "").strip() == "invalid patient id"
        assert "Traceback" not in (bad_patient.stderr or "")

        # Bind the admin LOGIN so dry-run can resolve the actor, then probe missing patient.
        _autocommit(session, f"GRANT cosmas_patient_deletion TO {admin_role}")
        _autocommit(
            session,
            f"GRANT EXECUTE ON FUNCTION public.delete_patient_keyed_records_plan(uuid) TO {admin_role}",
        )
        _autocommit(
            session,
            f"GRANT EXECUTE ON FUNCTION public.delete_patient_keyed_records(uuid) TO {admin_role}",
        )
        session.execute(
            text(
                """
                INSERT INTO public.patient_deletion_admin_bindings (db_role, principal_id, box_id)
                VALUES (:role, CAST(:principal AS uuid), CAST(:box AS uuid))
                ON CONFLICT (db_role) DO UPDATE
                  SET principal_id = EXCLUDED.principal_id,
                      box_id = EXCLUDED.box_id
                """
            ),
            {"role": admin_role, "principal": owner, "box": practice["box_id"]},
        )
        session.commit()
        missing_patient = CliRunner().invoke(
            cli_app,
            [
                "delete-patient-records",
                "00000000-0000-4000-8000-000000000099",
                "--dry-run",
            ],
            env=env,
        )
        assert missing_patient.exit_code == 1
        assert (missing_patient.stderr or "").strip() == "patient not found"
        assert "Traceback" not in (missing_patient.stderr or "")

        session.execute(
            text("DELETE FROM public.patient_deletion_admin_bindings WHERE db_role = :role"),
            {"role": admin_role},
        )
        session.commit()
        not_admin = CliRunner().invoke(
            cli_app,
            ["delete-patient-records", patient_id, "--confirm"],
            env=env,
        )
        assert not_admin.exit_code == 1
        assert (not_admin.stderr or "").strip() == "admin authority required"
        assert str(names["label"]) not in (not_admin.stderr or "")
    finally:
        _drop_admin_identity(session, admin_role)

    admin = create_engine(
        make_url(os.environ.get("DATABASE_URL", settings.database_url)).set(database="postgres"),
        isolation_level="AUTOCOMMIT",
    )
    try:
        _drop_patient_deletion_role(
            admin, (str(session.scalar(text("SELECT current_database()"))),)
        )
        admin_role, admin_url = _separate_admin_identity(session)
        try:
            no_role = CliRunner().invoke(
                cli_app,
                ["delete-patient-records", patient_id, "--confirm"],
                env={"COSMAS_ADMIN_DATABASE_URL": admin_url},
            )
            assert no_role.exit_code == 1
            assert (no_role.stderr or "").strip() == "deletion role not configured"
            assert "Traceback" not in (no_role.stderr or "")
            assert str(names["label"]) not in (no_role.stderr or "")
            assert session.get(PatientLink, patient_id) is not None
        finally:
            _drop_admin_identity(session, admin_role)
    finally:
        _ensure_patient_deletion_role(session)
        admin.dispose()


def test_ticket_keyed_audit_event_is_redacted_and_second_patient_stays(practice) -> None:
    session = practice["session"]
    blob = practice["blob"]
    owner = str(practice["owner_id"])
    casey = practice["casey"]
    morgan = practice["morgan"]
    names = practice["names"]
    assert isinstance(casey, dict) and isinstance(morgan, dict) and isinstance(names, dict)
    patient_id = str(casey["patient_id"])
    ticket_id = str(casey["ticket_id"])
    morgan_ticket = str(morgan["ticket_id"])
    label = str(names["label"])
    ticket_event = AuditEvent(
        box_id=str(practice["box_id"]),
        aggregate_type="ticket",
        aggregate_id=ticket_id,
        event_type="ticket.synthetic_label",
        actor_principal_id=owner,
        outcome="recorded",
        detail={"label": label, "note": str(names["note"])},
    )
    morgan_event = AuditEvent(
        box_id=str(practice["box_id"]),
        aggregate_type="ticket",
        aggregate_id=morgan_ticket,
        event_type="ticket.synthetic_label",
        actor_principal_id=owner,
        outcome="recorded",
        detail={"label": str(names["morgan_label"])},
    )
    session.add(ticket_event)
    session.add(morgan_event)
    session.commit()
    ticket_event_id = ticket_event.id
    morgan_event_id = morgan_event.id

    _calls(session, owner, patient_id, blob, confirm=True)
    session.expire_all()

    redacted = session.get(AuditEvent, ticket_event_id)
    assert redacted is not None
    assert redacted.aggregate_id == "redacted"
    assert redacted.detail == {}
    assert redacted.event_type == "ticket.synthetic_label"
    assert label not in json.dumps(redacted.detail)

    kept = session.get(AuditEvent, morgan_event_id)
    assert kept is not None
    assert kept.aggregate_id == morgan_ticket
    assert kept.detail == {"label": str(names["morgan_label"])}
    assert session.get(PatientLink, str(morgan["patient_id"])) is not None


def test_confirm_clears_all_thirty_four_patient_linked_tables(practice) -> None:
    session = practice["session"]
    blob = practice["blob"]
    owner = str(practice["owner_id"])
    casey = practice["casey"]
    assert isinstance(casey, dict) and isinstance(blob, LocalBlobAdapter)
    patient_id = str(casey["patient_id"])
    tables = _seed_all_patient_linked_tables(session, practice)
    assert len(tables) == 34
    before = _patient_link_counts(session, patient_id)
    assert all(before[table] >= 1 for table in tables)
    _calls(session, owner, patient_id, blob, confirm=True)
    after = _patient_link_counts(session, patient_id)
    leftover = [table for table in tables if after.get(table, 0) != 0]
    assert leftover == [], f"patient-linked rows left in: {', '.join(leftover)}"
    assert len(tables) == 34


def test_admin_delete_as_nonsuperuser_with_deletion_role(practice) -> None:
    session = practice["session"]
    blob = practice["blob"]
    owner = str(practice["owner_id"])
    casey = practice["casey"]
    assert isinstance(casey, dict) and isinstance(blob, LocalBlobAdapter)
    patient_id = str(casey["patient_id"])
    runtime_url = os.environ.get("DATABASE_URL", settings.database_url)
    parsed = make_url(runtime_url)
    password = parsed.password
    assert isinstance(password, str) and password
    role = "patient_admin_ns_" + uuid4().hex[:10]
    quoted = session.scalar(text("SELECT quote_literal(:password)"), {"password": password})
    assert isinstance(quoted, str)
    database = str(session.scalar(text("SELECT current_database()")))
    _autocommit(
        session,
        f"CREATE ROLE {role} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE INHERIT PASSWORD {quoted}",
    )
    try:
        # Login identity for the admin CLI only. Deletion-role grants come only
        # from John's real ensure script (no copy, no extra grants).
        _autocommit(session, f"GRANT CONNECT ON DATABASE {_quote(database)} TO {role}")
        _autocommit(session, f"GRANT USAGE ON SCHEMA public TO {role}")
        _autocommit(
            session,
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {role}",
        )
        _autocommit(session, f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {role}")
        _autocommit(
            session,
            f"GRANT EXECUTE ON FUNCTION public.delete_patient_keyed_records(uuid) TO {role}",
        )
        _autocommit(
            session,
            f"GRANT EXECUTE ON FUNCTION public.delete_patient_keyed_records_plan(uuid) TO {role}",
        )
        _ensure_patient_deletion_role(session)
        can_insert_audit = session.scalar(
            text(
                "SELECT has_table_privilege('cosmas_patient_deletion', "
                "'public.audit_events', 'INSERT')"
            )
        )
        assert can_insert_audit is False
        can_update_audit = session.scalar(
            text(
                "SELECT has_table_privilege('cosmas_patient_deletion', "
                "'public.audit_events', 'UPDATE')"
            )
        )
        assert can_update_audit is False
        is_super = session.scalar(
            text("SELECT rolsuper FROM pg_roles WHERE rolname = :role"), {"role": role}
        )
        assert is_super is False
        _autocommit(session, f"GRANT cosmas_patient_deletion TO {role}")
        session.execute(
            text(
                """
                INSERT INTO public.patient_deletion_admin_bindings (db_role, principal_id, box_id)
                VALUES (:role, CAST(:principal AS uuid), CAST(:box AS uuid))
                ON CONFLICT (db_role) DO UPDATE
                  SET principal_id = EXCLUDED.principal_id,
                      box_id = EXCLUDED.box_id
                """
            ),
            {"role": role, "principal": owner, "box": practice["box_id"]},
        )
        session.commit()
        admin_url = parsed.set(username=role).render_as_string(hide_password=False)
        assert make_url(admin_url).username == role
        cli = CliRunner().invoke(
            cli_app,
            ["delete-patient-records", patient_id, "--confirm"],
            env={"COSMAS_ADMIN_DATABASE_URL": admin_url},
        )
        assert cli.exit_code == 0, cli.stderr
        report = json.loads(cli.stdout)
        assert report["deleted"] is True
        assert session.get(PatientLink, patient_id) is None
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.event_type == "patient.records_deleted",
                    AuditEvent.aggregate_id == patient_id,
                )
            )
            == 1
        )
    finally:
        _autocommit(session, f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {role}")
        _autocommit(session, f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {role}")
        _autocommit(
            session,
            f"REVOKE ALL ON FUNCTION public.delete_patient_keyed_records(uuid) FROM {role}",
        )
        _autocommit(
            session,
            f"REVOKE ALL ON FUNCTION public.delete_patient_keyed_records_plan(uuid) FROM {role}",
        )
        _autocommit(session, f"REVOKE ALL ON SCHEMA public FROM {role}")
        _autocommit(session, f"REVOKE ALL ON DATABASE {_quote(database)} FROM {role}")
        _autocommit(session, f"DROP ROLE IF EXISTS {role}")


def test_patient_with_saved_ehr_snapshot_can_be_deleted(practice) -> None:
    session = practice["session"]
    blob = practice["blob"]
    owner = str(practice["owner_id"])
    casey = practice["casey"]
    assert isinstance(casey, dict) and isinstance(blob, LocalBlobAdapter)
    patient_id = str(casey["patient_id"])
    box_id = str(practice["box_id"])
    owner_id = str(practice["owner_id"])
    bind = session.get_bind()
    with bind.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text("SET LOCAL session_replication_role = replica"))
            dropped = _check_constraints(connection, ["ehr_read_requests"])
            for table, name, _definition in dropped:
                connection.execute(
                    text(f"ALTER TABLE public.{_quote(table)} DROP CONSTRAINT {_quote(name)}")
                )
            # Seed a bare request if arrange left none with patient_link_id.
            existing = connection.scalar(
                text(
                    "SELECT count(*) FROM public.ehr_read_requests "
                    "WHERE patient_link_id = CAST(:patient AS uuid)"
                ),
                {"patient": patient_id},
            )
            if int(existing or 0) < 1:
                _seed_patient_linked_row(
                    connection,
                    "ehr_read_requests",
                    patient_id=patient_id,
                    box_id=box_id,
                    owner_id=owner_id,
                    known={
                        "workspace_id": str(casey["workspace_id"]),
                        "ticket_id": str(casey["ticket_id"]),
                    },
                )
            _seed_ehr_request_snapshot_cycle(
                connection,
                patient_id=patient_id,
                box_id=box_id,
                owner_id=owner_id,
            )
            for table, name, definition in dropped:
                connection.execute(
                    text(
                        f"ALTER TABLE public.{_quote(table)} "
                        f"ADD CONSTRAINT {_quote(name)} {definition} NOT VALID"
                    )
                )
            transaction.commit()
        except Exception:
            transaction.rollback()
            raise
    session.expire_all()
    before_snapshots = int(
        session.scalar(
            text(
                "SELECT count(*) FROM public.ehr_read_snapshots s "
                "JOIN public.ehr_read_requests r ON r.id = s.observation_id "
                "WHERE r.patient_link_id = CAST(:patient AS uuid)"
            ),
            {"patient": patient_id},
        )
        or 0
    )
    assert before_snapshots >= 1
    deferred = session.execute(
        text(
            """
            SELECT conname, condeferrable, condeferred
              FROM pg_constraint
             WHERE conname IN (
               'ehr_read_snapshots_observation_id_box_id_owner_id_fkey',
               'fk_ehr_read_request_parent'
             )
             ORDER BY conname
            """
        )
    ).all()
    assert len(deferred) == 2
    assert all(row[1] is True for row in deferred)
    _calls(session, owner, patient_id, blob, confirm=True)
    assert session.get(PatientLink, patient_id) is None
    after_snapshots = int(
        session.scalar(
            text(
                "SELECT count(*) FROM public.ehr_read_snapshots s "
                "JOIN public.ehr_read_requests r ON r.id = s.observation_id "
                "WHERE r.patient_link_id = CAST(:patient AS uuid)"
            ),
            {"patient": patient_id},
        )
        or 0
    )
    assert after_snapshots == 0


def test_pending_file_delete_failure_is_finished_on_rerun(practice, monkeypatch) -> None:
    session = practice["session"]
    blob = practice["blob"]
    owner = str(practice["owner_id"])
    casey = practice["casey"]
    assert isinstance(casey, dict) and isinstance(blob, LocalBlobAdapter)
    patient_id = str(casey["patient_id"])
    files = list(_paths(blob, casey).values()) + _upload_paths(
        session, blob, str(casey["ticket_id"])
    )
    assert all(path.is_file() for path in files)

    from cosmas_os.application import patient_deletion as deletion_mod

    real_unlink = deletion_mod._unlink
    failures = {"count": 0}

    def _fail_once(path: Path) -> None:
        if failures["count"] == 0:
            failures["count"] += 1
            raise deletion_mod.DomainError("stored files could not be deleted")
        real_unlink(path)

    monkeypatch.setattr(deletion_mod, "_unlink", _fail_once)
    with pytest.raises(DomainError, match="database delete completed; stored files pending"):
        _calls(session, owner, patient_id, blob, confirm=True)
    session.rollback()
    assert session.get(PatientLink, patient_id) is None
    pending = int(
        session.scalar(
            text(
                "SELECT count(*) FROM public.patient_deletion_pending_files "
                "WHERE patient_link_id = CAST(:patient AS uuid)"
            ),
            {"patient": patient_id},
        )
        or 0
    )
    assert pending >= 1
    assert any(path.is_file() for path in files)

    monkeypatch.setattr(deletion_mod, "_unlink", real_unlink)
    report = _calls(session, owner, patient_id, blob, confirm=True)
    assert report["deleted"] is False
    assert report["pending_files_finished"] >= 1
    leftover = int(
        session.scalar(
            text(
                "SELECT count(*) FROM public.patient_deletion_pending_files "
                "WHERE patient_link_id = CAST(:patient AS uuid)"
            ),
            {"patient": patient_id},
        )
        or 0
    )
    assert leftover == 0
    assert all(not path.exists() for path in files)


def test_deletion_function_refuses_other_practice_patient(practice) -> None:
    session = practice["session"]
    blob = practice["blob"]
    owner = str(practice["owner_id"])
    casey = practice["casey"]
    assert isinstance(casey, dict) and isinstance(blob, LocalBlobAdapter)
    patient_id = str(casey["patient_id"])
    other = svc.Container(session, blob=blob)
    foreign = svc.provision_box(other, "Invented Other Practice")
    foreign_owner = str(foreign["owner_id"])
    foreign_patient = svc.attest_patient_link(
        other,
        foreign["box_id"],
        foreign_owner,
        source_pair_key="csv:foreign-patient",
        label="Invented Foreign Patient",
    )
    session.commit()
    foreign_id = str(foreign_patient.id)
    before_foreign = _patient_link_counts(session, foreign_id)
    with pytest.raises(AuthorizationError, match="admin authority required"):
        _calls(session, owner, foreign_id, blob, confirm=True)
    session.rollback()
    assert _patient_link_counts(session, foreign_id) == before_foreign
    assert session.get(PatientLink, foreign_id) is not None
    before = _patient_link_counts(session, patient_id)
    assert before
    # Same-practice owner still works through the application path.
    _calls(session, owner, patient_id, blob, confirm=True)
    assert session.get(PatientLink, patient_id) is None


def test_guc_bypass_cannot_edit_notes_or_audit(practice) -> None:
    """T13: SET cosmas.patient_deletion cannot bypass immutability."""

    session = practice["session"]
    casey = practice["casey"]
    assert isinstance(casey, dict)
    note_id = session.scalar(
        select(WorkspaceNote.id).where(WorkspaceNote.workspace_id == casey["workspace_id"])
    )
    assert note_id is not None
    audit_id = session.scalar(select(AuditEvent.id).limit(1))
    assert audit_id is not None
    role = "patient_runtime_guc_" + uuid4().hex[:10]
    runtime = _runtime_engine(session, role)
    try:
        # Notes: grant DML so the immutability trigger is what refuses.
        # Audit: no DML grant — privilege check refuses even with the GUC set.
        _autocommit(
            session,
            f"GRANT SELECT, UPDATE, DELETE ON public.workspace_notes TO {role}",
        )
        _autocommit(session, f"GRANT SELECT ON public.audit_events TO {role}")
        for statement in (
            "SET cosmas.patient_deletion = '1'",
            "SET LOCAL cosmas.patient_deletion = '1'",
        ):
            with runtime.begin() as connection:
                connection.execute(text(statement))
                with pytest.raises(ProgrammingError, match="workspace history is immutable"):
                    connection.execute(
                        text(
                            "UPDATE public.workspace_notes SET content = 'x' "
                            "WHERE id = CAST(:id AS uuid)"
                        ),
                        {"id": note_id},
                    )
            with runtime.begin() as connection:
                connection.execute(text(statement))
                with pytest.raises(ProgrammingError, match="workspace history is immutable"):
                    connection.execute(
                        text("DELETE FROM public.workspace_notes WHERE id = CAST(:id AS uuid)"),
                        {"id": note_id},
                    )
            with runtime.begin() as connection:
                connection.execute(text(statement))
                with pytest.raises(ProgrammingError, match="permission denied"):
                    connection.execute(
                        text(
                            "UPDATE public.audit_events SET detail = '{}'::jsonb "
                            "WHERE id = CAST(:id AS uuid)"
                        ),
                        {"id": audit_id},
                    )
            with runtime.begin() as connection:
                connection.execute(text(statement))
                with pytest.raises(ProgrammingError, match="permission denied"):
                    connection.execute(
                        text("DELETE FROM public.audit_events WHERE id = CAST(:id AS uuid)"),
                        {"id": audit_id},
                    )
        bind = session.get_bind()
        with bind.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text("SET LOCAL ROLE cosmas_patient_deletion"))
                connection.execute(text("SET LOCAL cosmas.patient_deletion = '1'"))
                with pytest.raises(ProgrammingError, match="permission denied"):
                    connection.execute(
                        text(
                            "UPDATE public.workspace_notes SET content = 'x' "
                            "WHERE id = CAST(:id AS uuid)"
                        ),
                        {"id": note_id},
                    )
            finally:
                transaction.rollback()
        with bind.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text("SET LOCAL ROLE cosmas_patient_deletion"))
                connection.execute(text("SET LOCAL cosmas.patient_deletion = '1'"))
                with pytest.raises(ProgrammingError, match="permission denied"):
                    connection.execute(
                        text(
                            "UPDATE public.audit_events SET detail = '{}'::jsonb "
                            "WHERE id = CAST(:id AS uuid)"
                        ),
                        {"id": audit_id},
                    )
            finally:
                transaction.rollback()
    finally:
        runtime.dispose()
        _drop_runtime_role(session, role)


def test_unclassified_reachable_table_refuses_delete(practice) -> None:
    """T14: a reachable table not on PATIENT_OWNED/EXCLUSIVE_CONTENT/PRESERVE/SHARED refuses."""

    session = practice["session"]
    blob = practice["blob"]
    owner = str(practice["owner_id"])
    casey = practice["casey"]
    assert isinstance(casey, dict) and isinstance(blob, LocalBlobAdapter)
    patient_id = str(casey["patient_id"])
    ticket_id = str(casey["ticket_id"])
    session.execute(
        text(
            """
            CREATE TABLE public.patient_deletion_probe_ticket_child (
              id uuid PRIMARY KEY,
              ticket_id uuid NOT NULL REFERENCES public.tickets(id)
            )
            """
        )
    )
    session.execute(
        text(
            """
            INSERT INTO public.patient_deletion_probe_ticket_child (id, ticket_id)
            VALUES (gen_random_uuid(), CAST(:ticket AS uuid))
            """
        ),
        {"ticket": ticket_id},
    )
    session.commit()
    try:
        with pytest.raises(Exception, match="schema not classified for patient deletion"):
            _calls(session, owner, patient_id, blob, confirm=True)
        session.rollback()
        assert session.get(PatientLink, patient_id) is not None
    finally:
        session.execute(text("DROP TABLE IF EXISTS public.patient_deletion_probe_ticket_child"))
        session.commit()


def test_deletion_function_has_no_plan_argument_overload(practice) -> None:
    session = practice["session"]
    rows = session.execute(
        text(
            """
            SELECT p.proname, pg_get_function_identity_arguments(p.oid) AS args
              FROM pg_proc p
              JOIN pg_namespace n ON n.oid = p.pronamespace
             WHERE n.nspname = 'public'
               AND p.proname IN (
                 'delete_patient_keyed_records',
                 '_cosmas_apply_patient_deletion_mutate',
                 '_cosmas_apply_patient_deletion_plan'
               )
             ORDER BY p.proname, args
            """
        )
    ).all()
    signatures = {(str(name), str(args)) for name, args in rows}
    assert ("delete_patient_keyed_records", "p_patient uuid") in signatures
    assert ("_cosmas_apply_patient_deletion_mutate", "p_patient uuid") in signatures
    assert all("jsonb" not in args for _name, args in signatures)
    assert all(name != "_cosmas_apply_patient_deletion_plan" for name, _args in signatures)
    # Only the two-uuid entry exists for the public function.
    public = [args for name, args in signatures if name == "delete_patient_keyed_records"]
    assert public == ["p_patient uuid"]


def _message_models(provider: str):
    if provider == "google":
        return (
            GoogleMessageReadRequest,
            GoogleMessageSnapshot,
            GoogleMessageSourceReview,
            "google_message",
        )
    if provider == "microsoft":
        return (
            MicrosoftMessageReadRequest,
            MicrosoftMessageSnapshot,
            MicrosoftMessageSourceReview,
            "microsoft_message",
        )
    raise AssertionError(provider)


def _seed_message_snapshot_review(
    session: Session,
    *,
    provider: str,
    box: str,
    owner: str,
    workspace_id: str,
    patient_id: str,
    snapshot_id: str | None = None,
    ordinal: int = 1,
) -> str:
    """Attach a synthetic message snapshot review for exclusive-content tests.

    Custody triggers require live credentials and exact digests; tests insert
    under session_replication_role=replica so the exclusive-content path is
    what is under test, not the provider custody guards.
    """

    _read_model, _snapshot_model, _review_model, entry_kind = _message_models(provider)
    del _read_model, _snapshot_model, _review_model
    account_id = session.scalar(
        select(ExternalIdentity.id).where(ExternalIdentity.principal_id == owner)
    )
    assert account_id is not None
    digest = "a" * 64
    read_table = f"{provider}_message_read_requests"
    snap_table = f"{provider}_message_snapshots"
    review_table = f"{provider}_message_source_reviews"
    workspace = session.get(EncounterWorkspace, workspace_id)
    assert workspace is not None
    expected = int(workspace.revision)
    content = f"synthetic {provider} exclusive review {uuid4().hex[:8]}"
    content_sha = hashlib.sha256(content.encode()).hexdigest()
    entry_id = str(uuid4())
    review_id = str(uuid4())
    bind = session.get_bind()
    with bind.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text("SET LOCAL session_replication_role = replica"))
            if snapshot_id is None:
                read_id = str(uuid4())
                snapshot_id = str(uuid4())
                connection.execute(
                    text(
                        f"""
                        INSERT INTO public.{_quote(read_table)} (
                          id, account_id, ordinal, kind, idempotency_key,
                          request_hash, binding_digest, grant_sha256, connected_at,
                          box_id, owner_id
                        ) VALUES (
                          CAST(:id AS uuid), CAST(:account AS uuid), :ordinal, 'list',
                          :key, :digest, :digest, :digest, timestamptz '2026-09-10T00:00:00Z',
                          CAST(:box AS uuid), CAST(:owner AS uuid)
                        )
                        """
                    ),
                    {
                        "id": read_id,
                        "account": account_id,
                        "ordinal": ordinal,
                        "key": f"{provider}-list-{ordinal}-{uuid4().hex[:8]}",
                        "digest": digest,
                        "box": box,
                        "owner": owner,
                    },
                )
                connection.execute(
                    text(
                        f"""
                        INSERT INTO public.{_quote(snap_table)} (
                          id, read_id, payload, payload_sha256, source_sha256,
                          box_id, owner_id
                        ) VALUES (
                          CAST(:id AS uuid), CAST(:read AS uuid),
                          CAST(:payload AS jsonb), :digest, :digest,
                          CAST(:box AS uuid), CAST(:owner AS uuid)
                        )
                        """
                    ),
                    {
                        "id": snapshot_id,
                        "read": read_id,
                        "payload": json.dumps(
                            {
                                "kind": "mail",
                                "subject": "Invented exclusive message",
                                "content": "synthetic exclusive-content body",
                            }
                        ),
                        "digest": digest,
                        "box": box,
                        "owner": owner,
                    },
                )
            connection.execute(
                text(
                    """
                    INSERT INTO public.workspace_entries (
                      id, workspace_id, box_id, actor_id, revision, kind, content,
                      idempotency_key, request_hash
                    ) VALUES (
                      CAST(:id AS uuid), CAST(:workspace AS uuid), CAST(:box AS uuid),
                      CAST(:owner AS uuid), :revision, :kind, :content, :key, :digest
                    )
                    """
                ),
                {
                    "id": entry_id,
                    "workspace": workspace_id,
                    "box": box,
                    "owner": owner,
                    "revision": expected + 1,
                    "kind": entry_kind,
                    "content": content,
                    "key": f"{provider}-entry-{uuid4().hex}",
                    "digest": digest,
                },
            )
            connection.execute(
                text(
                    f"""
                    INSERT INTO public.{_quote(review_table)} (
                      id, entry_id, snapshot_id, patient_link_id, expected_revision,
                      workspace_revision, idempotency_key, request_hash, source_sha256,
                      content_sha256, reviewed_patient, reviewed_exact_message,
                      reviewed_untrusted_source, workspace_id, box_id, owner_id
                    ) VALUES (
                      CAST(:id AS uuid), CAST(:entry AS uuid), CAST(:snapshot AS uuid),
                      CAST(:patient AS uuid), :expected, :workspace_revision, :key,
                      :digest, :digest, :content_sha, true, true, true,
                      CAST(:workspace AS uuid), CAST(:box AS uuid), CAST(:owner AS uuid)
                    )
                    """
                ),
                {
                    "id": review_id,
                    "entry": entry_id,
                    "snapshot": snapshot_id,
                    "patient": patient_id,
                    "expected": expected,
                    "workspace_revision": expected + 1,
                    "key": f"{provider}-review-{uuid4().hex}",
                    "digest": digest,
                    "content_sha": content_sha,
                    "workspace": workspace_id,
                    "box": box,
                    "owner": owner,
                },
            )
            connection.execute(
                text(
                    """
                    UPDATE public.encounter_workspaces
                       SET revision = :revision
                     WHERE id = CAST(:workspace AS uuid)
                    """
                ),
                {"revision": expected + 1, "workspace": workspace_id},
            )
            transaction.commit()
        except Exception:
            transaction.rollback()
            raise
    session.expire_all()
    assert snapshot_id is not None
    return snapshot_id


@pytest.mark.parametrize("provider", ["google", "microsoft"])
def test_exclusive_message_snapshot_deleted_when_only_reviewer(practice, provider) -> None:
    """T15: delete A when A is the snapshot's only reviewer; snapshot is gone."""

    session = practice["session"]
    blob = practice["blob"]
    owner = str(practice["owner_id"])
    box = str(practice["box_id"])
    casey = practice["casey"]
    assert isinstance(casey, dict) and isinstance(blob, LocalBlobAdapter)
    patient_id = str(casey["patient_id"])
    workspace_id = str(casey["workspace_id"])
    snapshot_id = _seed_message_snapshot_review(
        session,
        provider=provider,
        box=box,
        owner=owner,
        workspace_id=workspace_id,
        patient_id=patient_id,
        ordinal=10,
    )
    _, snapshot_model, review_model, _ = _message_models(provider)
    dry = _calls(session, owner, patient_id, blob, confirm=False)
    table_key = f"{provider}_message_snapshots"
    assert int(dry["tables"].get(table_key, 0)) == 1
    assert dry["message snapshots retained, still used by another patient"] == 0
    assert session.get(snapshot_model, snapshot_id) is not None
    report = _calls(session, owner, patient_id, blob, confirm=True)
    assert report["deleted"] is True
    assert int(report["tables"].get(table_key, 0)) == 1
    assert report["message snapshots retained, still used by another patient"] == 0
    assert session.get(snapshot_model, snapshot_id) is None
    assert (
        session.scalar(
            select(func.count()).select_from(review_model).where(
                review_model.patient_link_id == patient_id
            )
        )
        == 0
    )


@pytest.mark.parametrize("provider", ["google", "microsoft"])
def test_exclusive_message_snapshot_retained_when_second_patient_reviews(
    practice, provider
) -> None:
    """T16: A and B review the same snapshot; delete A; snapshot stays; retained=1."""

    session = practice["session"]
    blob = practice["blob"]
    owner = str(practice["owner_id"])
    box = str(practice["box_id"])
    casey = practice["casey"]
    morgan = practice["morgan"]
    assert (
        isinstance(casey, dict)
        and isinstance(morgan, dict)
        and isinstance(blob, LocalBlobAdapter)
    )
    casey_id = str(casey["patient_id"])
    morgan_id = str(morgan["patient_id"])
    snapshot_id = _seed_message_snapshot_review(
        session,
        provider=provider,
        box=box,
        owner=owner,
        workspace_id=str(casey["workspace_id"]),
        patient_id=casey_id,
        ordinal=20,
    )
    _seed_message_snapshot_review(
        session,
        provider=provider,
        box=box,
        owner=owner,
        workspace_id=str(morgan["workspace_id"]),
        patient_id=morgan_id,
        snapshot_id=snapshot_id,
        ordinal=21,
    )
    _, snapshot_model, review_model, _ = _message_models(provider)
    dry = _calls(session, owner, casey_id, blob, confirm=False)
    table_key = f"{provider}_message_snapshots"
    assert table_key not in dry["tables"] or int(dry["tables"].get(table_key, 0)) == 0
    assert dry["message snapshots retained, still used by another patient"] == 1
    assert int(dry["exclusive_retained"].get(table_key, 0)) == 1
    report = _calls(session, owner, casey_id, blob, confirm=True)
    assert report["deleted"] is True
    assert report["message snapshots retained, still used by another patient"] == 1
    assert session.get(snapshot_model, snapshot_id) is not None
    assert (
        session.scalar(
            select(func.count()).select_from(review_model).where(
                review_model.patient_link_id == casey_id
            )
        )
        == 0
    )
    assert (
        session.scalar(
            select(func.count()).select_from(review_model).where(
                review_model.patient_link_id == morgan_id,
                review_model.snapshot_id == snapshot_id,
            )
        )
        == 1
    )
