from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from cosmas_os.adapters.local import InjectableClock, LocalBlobAdapter, SystemClock
from cosmas_os.application import services as svc
from cosmas_os.application.beta_acceptance import (
    PURGE_ACCEPTANCE_CONTRACT,
    WORKFLOW_ACCEPTANCE_CONTRACT,
    BetaAcceptanceError,
    baseline_beta_workflow_acceptance,
    prepare_beta_purge_acceptance,
    verify_beta_purge_acceptance,
    verify_beta_workflow_acceptance,
)
from cosmas_os.application.seed import SYNTH_CSV
from cosmas_os.config import Settings
from cosmas_os.domain.enums import DecisionKind
from cosmas_os.models import Artifact, Operation
from cosmas_os.ports import BlobRepresentationAbsence

_HMAC_KEY = bytes.fromhex("a1" * 32)
_UAMI_CLIENT_ID = "11111111-1111-4111-8111-111111111111"


def _beta_settings(box_id: str) -> Settings:
    return Settings(
        database_url=(
            "postgresql+psycopg://runtime:invented-secret@database.example.invalid/"
            "cosmas_os?sslmode=verify-full&sslrootcert=system"
        ),
        redis_url=(
            "rediss://:invented-secret@redis.example.invalid:10000/0?ssl_cert_reqs=required"
        ),
        cosmas_env="early_adopter_beta",
        data_mode="synthetic",
        auth_mode="clerk_jwt",
        cors_allowed_origins="https://web.example.invalid",
        synth_seed=False,
        blob_backend="azure",
        azure_storage_account_url="https://storage.example.invalid",
        azure_blob_container="box-artifacts",
        clerk_issuer="https://clerk.example.invalid",
        clerk_jwks_url="https://clerk.example.invalid/.well-known/jwks.json",
        clerk_audience="cosmas-beta",
        clerk_organization_id="org_synthetic",
        clerk_authorized_parties="https://web.example.invalid",
        beta_box_id=box_id,
        human_deploy_evidence_ref="review:synthetic-beta-acceptance",
        sync_worker=False,
    )


def _open_synthetic_ticket(container: svc.Container, seeded: dict[str, object]) -> str:
    box_id = str(seeded["box_id"])
    owner_id = str(seeded["owner_id"])
    agents = seeded["agents"]
    assert isinstance(agents, dict)
    appointment_id = svc.import_schedule(container, box_id, SYNTH_CSV)[0]
    link = svc.attest_patient_link(
        container,
        box_id,
        owner_id,
        source_pair_key=f"acceptance:{uuid4().hex}",
        label="Invented Acceptance Person",
    )
    ticket = svc.detect_and_open_chase(
        container,
        box_id,
        str(agents["chaser"]),
        appointment_id,
        link.id,
    )
    return ticket.id


def _assert_self_hash(serialized: str) -> dict[str, object]:
    payload = json.loads(serialized)
    evidence_hash = payload.pop("evidence_sha256")
    assert (
        evidence_hash
        == hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    return payload


def test_workflow_acceptance_binds_one_async_browser_approval(
    session,
    tmp_path,
    monkeypatch,
) -> None:
    blob = LocalBlobAdapter(tmp_path / "workflow-blobs")
    container = svc.Container(session, clock=SystemClock(), blob=blob)
    seeded = svc.provision_box(container, "Acceptance Test Clinic")
    ticket_id = _open_synthetic_ticket(container, seeded)
    runtime = _beta_settings(str(seeded["box_id"]))

    state = baseline_beta_workflow_acceptance(session, runtime, _HMAC_KEY)
    state_json = state.sanitized_json()
    state_payload = _assert_self_hash(state_json)
    assert state_payload["contract"] == WORKFLOW_ACCEPTANCE_CONTRACT
    assert ticket_id not in state_json
    assert str(seeded["box_id"]) not in state_json
    assert _HMAC_KEY.hex() not in state_json
    session.rollback()

    dispatched: list[str] = []
    from cosmas_os.worker import tasks

    monkeypatch.setattr(svc.settings, "sync_worker", False)
    monkeypatch.setattr(tasks.execute_operation_task, "delay", dispatched.append)
    result = svc.decide(
        container,
        ticket_id,
        str(seeded["owner_id"]),
        DecisionKind.APPROVE,
    )
    assert dispatched == [result["operation_id"]]

    with pytest.raises(BetaAcceptanceError, match="beta acceptance failed"):
        verify_beta_workflow_acceptance(session, runtime, state_json, _HMAC_KEY)
    session.rollback()

    svc.execute_operation(container, dispatched[0])
    evidence = verify_beta_workflow_acceptance(session, runtime, state_json, _HMAC_KEY)
    evidence_payload = _assert_self_hash(evidence.sanitized_json())

    assert evidence_payload["status"] == "verified"
    assert evidence_payload["approval_decision_delta"] == 1
    assert evidence_payload["durable_operation_delta"] == 1
    assert evidence_payload["worker_attempted"] is True
    assert evidence_payload["fake_notify_receipt_verified"] is True
    assert ticket_id not in evidence.sanitized_json()
    assert dispatched[0] not in evidence.sanitized_json()


def test_workflow_acceptance_handles_cross_clock_skew_but_rejects_reversed_worker_time(
    session,
    tmp_path,
    monkeypatch,
) -> None:
    blob = LocalBlobAdapter(tmp_path / "clock-skew-workflow-blobs")
    container = svc.Container(session, clock=SystemClock(), blob=blob)
    seeded = svc.provision_box(container, "Clock Skew Acceptance Clinic")
    ticket_id = _open_synthetic_ticket(container, seeded)
    runtime = _beta_settings(str(seeded["box_id"]))

    state = baseline_beta_workflow_acceptance(session, runtime, _HMAC_KEY)
    state_json = state.sanitized_json()
    session.rollback()

    issued_at = datetime.fromisoformat(state.issued_at.replace("Z", "+00:00"))
    container.clock = InjectableClock(issued_at - timedelta(seconds=1))
    dispatched: list[str] = []
    from cosmas_os.worker import tasks

    monkeypatch.setattr(svc.settings, "sync_worker", False)
    monkeypatch.setattr(tasks.execute_operation_task, "delay", dispatched.append)
    result = svc.decide(
        container,
        ticket_id,
        str(seeded["owner_id"]),
        DecisionKind.APPROVE,
    )
    svc.execute_operation(container, dispatched[0])

    operation = session.get(Operation, result["operation_id"])
    assert operation is not None
    assert operation.started_at is not None
    assert operation.completed_at is not None
    assert operation.created_at > operation.started_at
    assert (
        verify_beta_workflow_acceptance(session, runtime, state_json, _HMAC_KEY).status
        == "verified"
    )

    operation.completed_at = operation.started_at - timedelta(microseconds=1)
    session.commit()
    with pytest.raises(BetaAcceptanceError, match="beta acceptance failed"):
        verify_beta_workflow_acceptance(session, runtime, state_json, _HMAC_KEY)


def test_workflow_acceptance_rejects_tampered_opaque_state(session, tmp_path) -> None:
    container = svc.Container(
        session,
        clock=SystemClock(),
        blob=LocalBlobAdapter(tmp_path / "tamper-blobs"),
    )
    seeded = svc.provision_box(container, "Tamper Test Clinic")
    _open_synthetic_ticket(container, seeded)
    runtime = _beta_settings(str(seeded["box_id"]))
    state = json.loads(
        baseline_beta_workflow_acceptance(session, runtime, _HMAC_KEY).sanitized_json()
    )
    state["expires_at"] = datetime(2099, 1, 1, tzinfo=UTC).isoformat().replace("+00:00", "Z")

    with pytest.raises(BetaAcceptanceError, match="beta acceptance failed"):
        verify_beta_workflow_acceptance(
            session,
            runtime,
            json.dumps(state, sort_keys=True, separators=(",", ":")),
            _HMAC_KEY,
        )


def test_purge_acceptance_requires_browser_purge_then_proves_recoverable_absence(
    session,
    tmp_path,
) -> None:
    blob = LocalBlobAdapter(tmp_path / "purge-blobs")
    container = svc.Container(session, clock=SystemClock(), blob=blob)
    seeded = svc.provision_box(container, "Purge Acceptance Clinic")
    runtime = _beta_settings(str(seeded["box_id"]))

    state = prepare_beta_purge_acceptance(
        session,
        runtime,
        _HMAC_KEY,
        managed_identity_client_id=_UAMI_CLIENT_ID,
        expected_managed_identity_client_id=_UAMI_CLIENT_ID,
        blob=blob,
    )
    state_json = state.sanitized_json()
    state_payload = _assert_self_hash(state_json)
    artifact = session.scalar(
        select(Artifact).where(Artifact.classification == "synthetic_purge_acceptance")
    )
    assert artifact is not None
    assert state_payload["contract"] == PURGE_ACCEPTANCE_CONTRACT
    assert artifact.id not in state_json
    assert str(seeded["box_id"]) not in state_json
    assert _HMAC_KEY.hex() not in state_json

    with pytest.raises(BetaAcceptanceError, match="beta acceptance failed"):
        verify_beta_purge_acceptance(
            session,
            runtime,
            state_json,
            _HMAC_KEY,
            managed_identity_client_id=_UAMI_CLIENT_ID,
            expected_managed_identity_client_id=_UAMI_CLIENT_ID,
            blob=blob,
        )
    session.rollback()

    receipts = svc.purge_due_artifacts(
        container,
        str(seeded["box_id"]),
        str(seeded["owner_id"]),
    )
    assert len(receipts) == 1
    # PostgreSQL renders timestamptz values in the database session timezone.
    # An equivalent offset in the immutable receipt must still bind to the same
    # purge instant when the model is later reloaded in another timezone.
    receipt = dict(artifact.purge_receipt or {})
    receipt_deleted_at = datetime.fromisoformat(str(receipt["deleted_at"]))
    receipt["deleted_at"] = receipt_deleted_at.astimezone(
        timezone(timedelta(hours=-7))
    ).isoformat()
    artifact.purge_receipt = receipt
    session.commit()
    evidence = verify_beta_purge_acceptance(
        session,
        runtime,
        state_json,
        _HMAC_KEY,
        managed_identity_client_id=_UAMI_CLIENT_ID,
        expected_managed_identity_client_id=_UAMI_CLIENT_ID,
        blob=blob,
    )
    evidence_payload = _assert_self_hash(evidence.sanitized_json())

    assert evidence_payload["status"] == "verified"
    assert evidence_payload["application_tombstone_verified"] is True
    assert evidence_payload["purge_receipt_verified"] is True
    assert evidence_payload["blob_current_representation_absent"] is True
    assert evidence_payload["blob_version_representations_absent"] is True
    assert evidence_payload["blob_snapshot_representations_absent"] is True
    assert evidence_payload["blob_deleted_representations_absent"] is True
    assert evidence_payload["blob_recoverable_absence_verified"] is True
    assert artifact.id not in evidence.sanitized_json()


def test_purge_acceptance_rejects_a_recoverable_blob_version(session, tmp_path) -> None:
    class LingeringVersionBlob(LocalBlobAdapter):
        def probe_recoverable_absence(self, key: str) -> BlobRepresentationAbsence:
            proof = super().probe_recoverable_absence(key)
            return BlobRepresentationAbsence(
                current_absent=proof.current_absent,
                versions_absent=False,
                snapshots_absent=proof.snapshots_absent,
                deleted_absent=proof.deleted_absent,
            )

    blob = LocalBlobAdapter(tmp_path / "recoverable-version-blobs")
    container = svc.Container(session, clock=SystemClock(), blob=blob)
    seeded = svc.provision_box(container, "Recoverable Version Clinic")
    runtime = _beta_settings(str(seeded["box_id"]))
    state = prepare_beta_purge_acceptance(
        session,
        runtime,
        _HMAC_KEY,
        managed_identity_client_id=_UAMI_CLIENT_ID,
        expected_managed_identity_client_id=_UAMI_CLIENT_ID,
        blob=blob,
    )
    svc.purge_due_artifacts(
        container,
        str(seeded["box_id"]),
        str(seeded["owner_id"]),
    )

    with pytest.raises(BetaAcceptanceError, match="beta acceptance failed"):
        verify_beta_purge_acceptance(
            session,
            runtime,
            state.sanitized_json(),
            _HMAC_KEY,
            managed_identity_client_id=_UAMI_CLIENT_ID,
            expected_managed_identity_client_id=_UAMI_CLIENT_ID,
            blob=LingeringVersionBlob(blob.root),
        )


def test_purge_acceptance_rejects_wrong_runtime_identity_before_writes(session, tmp_path) -> None:
    blob = LocalBlobAdapter(tmp_path / "identity-blobs")
    container = svc.Container(session, clock=SystemClock(), blob=blob)
    seeded = svc.provision_box(container, "Identity Guard Clinic")
    runtime = _beta_settings(str(seeded["box_id"]))

    with pytest.raises(BetaAcceptanceError, match="beta acceptance failed"):
        prepare_beta_purge_acceptance(
            session,
            runtime,
            _HMAC_KEY,
            managed_identity_client_id=_UAMI_CLIENT_ID,
            expected_managed_identity_client_id="22222222-2222-4222-8222-222222222222",
            blob=blob,
        )

    assert (
        session.scalars(
            select(Artifact).where(Artifact.classification == "synthetic_purge_acceptance")
        ).all()
        == []
    )
    assert list((tmp_path / "identity-blobs").rglob("*.bin")) == []
