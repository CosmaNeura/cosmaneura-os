"""Admin deletion removes one patient's rows and files and leaves everyone else."""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
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

PNG = b"\x89PNG\r\n\x1a\n" + b"synthetic-card"
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


def test_owner_deletes_only_the_target_patient(engine, tmp_path, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    blob = LocalBlobAdapter(tmp_path / "blobs")
    with Session(engine) as session:
        arranged = _arrange(session, blob)
        owner = str(arranged["owner_id"])
        staff = str(arranged["staff_id"])
        scribe = str(arranged["agents"]["scribe"])
        casey = arranged["casey"]
        morgan = arranged["morgan"]
        names = arranged["names"]
        assert isinstance(casey, dict) and isinstance(morgan, dict) and isinstance(names, dict)
        patient_id = str(casey["patient_id"])
        morgan_id = str(morgan["patient_id"])
        before_morgan = _patient_link_counts(session, morgan_id)
        before_casey = _patient_link_counts(session, patient_id)
        assert session.get(PatientLink, patient_id) is not None
        assert before_casey["appointment_observations"] == 1
        assert before_casey["tickets"] == 1
        assert before_casey["encounter_workspaces"] == 1
        assert before_casey["scheduling_patient_accounts"] == 1
        assert _count(session, WorkspaceNote, "workspace_id", str(casey["workspace_id"])) == 2
        assert _count(session, WorkspaceEntry, "workspace_id", str(casey["workspace_id"])) >= 3
        assert _count(session, PrivateRecording, "id", str(casey["recording_id"])) == 1
        assert _count(session, PrivateRecordingFinish, "recording_id", str(casey["recording_id"])) == 1
        assert _count(session, Artifact, "ticket_id", str(casey["ticket_id"])) == 2
        audio = blob.root / str(casey["recording_id"]) / "audio" / "clip.wav"
        exported = blob.root / str(casey["workspace_id"]) / "exports" / "note.pdf"
        morgan_audio = blob.root / str(morgan["recording_id"]) / "audio" / "clip.wav"
        assert audio.is_file() and exported.is_file() and morgan_audio.is_file()

        with pytest.raises(DomainError, match="invalid patient id"):
            delete_patient_records(
                session, actor_principal_id=owner, patient_link_id=str(names["label"]),
                confirm=True, blob=blob, file_roots=storage_roots(blob),
            )
        for actor in (staff, scribe):
            with pytest.raises(AuthorizationError, match="admin authority required"):
                delete_patient_records(
                    session, actor_principal_id=actor, patient_link_id=patient_id,
                    confirm=True, blob=blob, file_roots=storage_roots(blob),
                )
        assert session.get(PatientLink, patient_id) is not None
        assert audio.is_file()

        preview = delete_patient_records(
            session, actor_principal_id=owner, patient_link_id=patient_id,
            confirm=False, blob=blob, file_roots=storage_roots(blob),
        )
        assert preview["dry_run"] is True
        assert preview["deleted"] is False
        assert preview["tables"]["patient_links"] == 1
        assert preview["tables"]["appointment_observations"] == 1
        assert preview["tables"]["encounter_workspaces"] == 1
        assert preview["tables"]["scheduling_patient_accounts"] == 1
        assert preview["files"] == {"audio": 1, "uploads": 2, "exports": 1}
        assert session.scalar(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.event_type == "patient.records_deleted",
                AuditEvent.aggregate_id == patient_id,
            )
        ) == 0
        assert audio.is_file() and exported.is_file()

        deleted = delete_patient_records(
            session, actor_principal_id=owner, patient_link_id=patient_id,
            confirm=True, blob=blob, file_roots=storage_roots(blob),
        )
        assert deleted["deleted"] is True
        assert deleted["dry_run"] is False
        assert deleted["files"] == {"audio": 1, "uploads": 2, "exports": 1}
        assert session.get(PatientLink, patient_id) is None
        assert all(count == 0 for count in _patient_link_counts(session, patient_id).values())
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
        assert not audio.exists() and not exported.exists()
        assert not (blob.root / str(casey["recording_id"])).exists()
        assert morgan_audio.is_file()
        assert (blob.root / str(morgan["workspace_id"]) / "exports" / "note.pdf").is_file()
        assert (blob.root / "keep" / "unrelated.txt").is_file()
        assert _patient_link_counts(session, morgan_id) == before_morgan
        assert session.get(PatientLink, morgan_id) is not None
        assert _count(session, WorkspaceNote, "workspace_id", str(morgan["workspace_id"])) == 2
        assert _text_hits(session, str(names["label"])) == 0
        assert _text_hits(session, str(names["note"])) == 0
        assert _text_hits(session, str(names["message"])) == 0
        assert _text_hits(session, str(names["transcript"])) == 0
        assert _text_hits(session, str(names["morgan_label"])) > 0

        audit_rows = list(session.scalars(
            select(AuditEvent).where(
                AuditEvent.event_type == "patient.records_deleted",
                AuditEvent.aggregate_id == patient_id,
            )
        ))
        assert len(audit_rows) == 1
        audit = audit_rows[0]
        rendered = json.dumps(
            {
                "aggregate_id": audit.aggregate_id,
                "aggregate_type": audit.aggregate_type,
                "actor_principal_id": audit.actor_principal_id,
                "detail": audit.detail,
                "event_type": audit.event_type,
                "outcome": audit.outcome,
            },
            sort_keys=True,
        )
        assert audit.actor_principal_id == owner
        assert audit.aggregate_id == patient_id
        assert audit.detail == {}
        assert audit.created_at is not None
        assert str(names["label"]) not in rendered
        assert str(names["note"]) not in rendered
        stored = session.scalar(
            text(
                "SELECT row_to_json(audit_events)::text FROM audit_events "
                "WHERE event_type = 'patient.records_deleted' "
                "AND aggregate_id = :patient_id"
            ),
            {"patient_id": patient_id},
        )
        assert isinstance(stored, str)
        assert str(names["label"]) not in stored
        assert str(names["note"]) not in stored
        assert str(names["message"]) not in stored

        repeated = delete_patient_records(
            session, actor_principal_id=owner, patient_link_id=patient_id,
            confirm=True, blob=blob, file_roots=storage_roots(blob),
        )
        assert repeated["deleted"] is False
        assert repeated["tables"] == {}
        assert repeated["files"] == {"audio": 0, "uploads": 0, "exports": 0}
        assert session.scalar(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.event_type == "patient.records_deleted",
                AuditEvent.aggregate_id == patient_id,
            )
        ) == 1
        assert session.get(PatientLink, morgan_id) is not None
        assert morgan_audio.is_file()
        assert str(names["label"]) not in caplog.text
        assert str(names["note"]) not in caplog.text
        assert settings.data_mode == "synthetic"


def test_api_and_cli_share_the_admin_service(engine, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "blob_root", str(tmp_path / "blobs"))
    with Session(engine) as session:
        arranged = _arrange(session, LocalBlobAdapter(tmp_path / "blobs"))
    owner = str(arranged["owner_id"])
    staff = str(arranged["staff_id"])
    box = str(arranged["box_id"])
    casey = arranged["casey"]
    morgan = arranged["morgan"]
    names = arranged["names"]
    assert isinstance(casey, dict) and isinstance(morgan, dict) and isinstance(names, dict)
    patient_id = str(casey["patient_id"])
    headers = {"X-Box-Id": box, "X-Actor-Principal-Id": owner}
    staff_headers = {"X-Box-Id": box, "X-Actor-Principal-Id": staff}
    client = TestClient(app)
    path = f"/admin/patients/{patient_id}/records"

    refused = client.post(path, json={"confirm": True}, headers=staff_headers)
    assert refused.status_code == 403
    assert str(names["label"]) not in refused.text
    staff_cli = CliRunner().invoke(
        cli_app, ["delete-patient-records", patient_id, "--actor", staff, "--confirm"]
    )
    assert staff_cli.exit_code == 1
    assert "admin authority required" in (staff_cli.stderr or "")
    assert str(names["label"]) not in (staff_cli.stderr or "")

    preview = client.post(path, json={}, headers=headers)
    assert preview.status_code == 200
    assert preview.json()["dry_run"] is True
    assert preview.json()["deleted"] is False
    assert preview.json()["files"]["uploads"] == 2
    confirmed = client.post(path, json={"confirm": True}, headers=headers)
    assert confirmed.status_code == 200
    assert confirmed.json()["deleted"] is True
    assert str(names["label"]) not in confirmed.text
    repeated = CliRunner().invoke(
        cli_app, ["delete-patient-records", patient_id, "--actor", owner, "--confirm"]
    )
    assert repeated.exit_code == 0
    assert json.loads(repeated.stdout)["deleted"] is False
    assert str(names["label"]) not in repeated.stdout

    with Session(engine) as session:
        assert session.get(PatientLink, patient_id) is None
        assert session.get(PatientLink, str(morgan["patient_id"])) is not None
        assert all(count == 0 for count in _patient_link_counts(session, patient_id).values())
        assert settings.data_mode == "synthetic"
