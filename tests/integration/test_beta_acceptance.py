from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from cosmas_os.adapters.local import InjectableClock, LocalBlobAdapter, SystemClock
from cosmas_os.application import beta_acceptance as beta_acceptance_module
from cosmas_os.application import services as svc
from cosmas_os.application.beta_acceptance import (
    AUDIT_REPLAY_CONTRACT,
    PURGE_ACCEPTANCE_CONTRACT,
    WORKFLOW_ACCEPTANCE_CONTRACT,
    BetaAcceptanceError,
    baseline_beta_workflow_acceptance,
    prepare_beta_purge_acceptance,
    verify_beta_audit_replay,
    verify_beta_purge_acceptance,
    verify_beta_workflow_acceptance,
)
from cosmas_os.application.seed import SYNTH_CSV
from cosmas_os.config import Settings
from cosmas_os.domain.enums import DecisionKind
from cosmas_os.models import (
    ActionRevision,
    AppointmentObservation,
    Artifact,
    AuditEvent,
    BoxContext,
    Decision,
    Operation,
    PatientLink,
    Principal,
    Ticket,
)
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
        source_pair_key="csv:jordan-lee",
        label="Jordan Lee",
    )
    ticket = svc.detect_and_open_chase(
        container,
        box_id,
        str(agents["chaser"]),
        appointment_id,
        link.id,
    )
    return ticket.id


def _inject_cross_box_linked_row(
    session,
    ticket: Ticket,
    revision: ActionRevision,
    owner_id: str,
    mutation: str,
    operation: Operation | None = None,
) -> None:
    other_box = BoxContext(display_name=f"Cross Box {mutation} Injection")
    session.add(other_box)
    session.flush()
    if mutation in {"revision", "operation"}:
        cross_revision = ActionRevision(
            ticket_id=ticket.id,
            box_id=other_box.id,
            revision_number=99,
            action_type=revision.action_type,
            target_ref=revision.target_ref,
            content=revision.content,
            payload=revision.payload,
            payload_hash=revision.payload_hash,
            automation_class=revision.automation_class,
            policy_version=revision.policy_version,
            charter_version=revision.charter_version,
            config_version=revision.config_version,
            created_by_principal_id=revision.created_by_principal_id,
        )
        session.add(cross_revision)
        session.flush()
        if mutation == "operation":
            session.add(
                Operation(
                    box_id=other_box.id,
                    ticket_id=ticket.id,
                    action_revision_id=cross_revision.id,
                    idempotency_key=f"cross-box:{cross_revision.id}",
                    adapter="notify",
                    status="succeeded",
                    attempt_count=1,
                )
            )
    elif mutation == "decision":
        session.add(
            Decision(
                box_id=other_box.id,
                ticket_id=ticket.id,
                action_revision_id=revision.id,
                actor_principal_id=owner_id,
                kind=DecisionKind.APPROVE.value,
            )
        )
    elif mutation == "audit":
        session.add(
            AuditEvent(
                box_id=other_box.id,
                aggregate_type="ticket",
                aggregate_id=ticket.id,
                event_type="decision.approved",
                action_revision_id=revision.id,
                payload_hash=revision.payload_hash,
                correlation_id=str(uuid4()),
                outcome="approved",
                detail={"operation_bound": True},
            )
        )
    else:
        assert operation is not None
        session.add(
            AuditEvent(
                box_id=other_box.id,
                aggregate_type="operation",
                aggregate_id=operation.id,
                event_type="operation.succeeded",
                action_revision_id=None,
                payload_hash=revision.payload_hash,
                correlation_id=str(uuid4()),
                outcome="succeeded",
                detail={"external_reference": operation.external_reference},
            )
        )
    session.commit()


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

    replay = verify_beta_audit_replay(session, runtime)
    replay_payload = _assert_self_hash(replay.sanitized_json())
    assert replay_payload["contract"] == AUDIT_REPLAY_CONTRACT
    assert replay_payload["box_scope_enforced"] is True
    assert replay_payload["cross_box_replay_denied"] is True
    assert replay_payload["operation_events_linked"] is True
    assert replay_payload["required_event_order_verified"] is True
    assert isinstance(replay_payload["timeline_event_count"], int)
    assert replay_payload["timeline_event_count"] == 3
    assert replay_payload["identifiers_returned"] is False
    assert ticket_id not in replay.sanitized_json()
    assert dispatched[0] not in replay.sanitized_json()

    operation = session.get(Operation, dispatched[0])
    revision = session.get(ActionRevision, operation.action_revision_id if operation else None)
    assert operation is not None and revision is not None
    fabricated = AuditEvent(
        box_id=str(seeded["box_id"]),
        aggregate_type="ticket",
        aggregate_id=ticket_id,
        event_type="operation.succeeded",
        action_revision_id=revision.id,
        payload_hash=revision.payload_hash,
        correlation_id=str(uuid4()),
        outcome="succeeded",
        detail={"external_reference": operation.external_reference},
    )
    session.add(fabricated)
    session.commit()
    with pytest.raises(BetaAcceptanceError, match="beta acceptance failed"):
        verify_beta_audit_replay(session, runtime)
    session.delete(fabricated)
    session.commit()

    original_timeline = svc.audit_timeline

    def timeline_with_content(*args, **kwargs):
        timeline = original_timeline(*args, **kwargs)
        timeline[0]["detail"] = {"patient_name": "Invented Acceptance Person"}
        return timeline

    monkeypatch.setattr(svc, "audit_timeline", timeline_with_content)
    with pytest.raises(BetaAcceptanceError, match="beta acceptance failed"):
        verify_beta_audit_replay(session, runtime)


@pytest.mark.parametrize(
    "mutation",
    ["ticket_version", "revision_content", "decision_kind", "operation_attempts"],
)
def test_audit_replay_rejects_drifted_workflow_semantics(
    session,
    tmp_path,
    monkeypatch,
    mutation: str,
) -> None:
    container = svc.Container(
        session,
        clock=SystemClock(),
        blob=LocalBlobAdapter(tmp_path / f"audit-{mutation}-blobs"),
    )
    seeded = svc.provision_box(container, f"Audit {mutation} Clinic")
    ticket_id = _open_synthetic_ticket(container, seeded)
    runtime = _beta_settings(str(seeded["box_id"]))
    monkeypatch.setattr(svc.settings, "sync_worker", True)
    result = svc.decide(
        container,
        ticket_id,
        str(seeded["owner_id"]),
        DecisionKind.APPROVE,
    )
    ticket = session.get(Ticket, ticket_id)
    operation = session.get(Operation, result["operation_id"])
    decision = session.scalar(select(Decision).where(Decision.ticket_id == ticket_id))
    revision = session.get(ActionRevision, ticket.current_revision_id if ticket else None)
    assert (
        ticket is not None
        and operation is not None
        and decision is not None
        and revision is not None
    )

    if mutation == "ticket_version":
        ticket.version = 3
    elif mutation == "revision_content":
        revision.content = "A different message not bound by the approved payload"
    elif mutation == "decision_kind":
        decision.kind = "reject"
    else:
        operation.attempt_count = 2
    session.commit()

    with pytest.raises(BetaAcceptanceError, match="beta acceptance failed"):
        verify_beta_audit_replay(session, runtime)


@pytest.mark.parametrize("mutation", ["revision", "decision", "operation", "audit"])
def test_workflow_baseline_rejects_cross_box_rows_linked_to_exact_ticket(
    session,
    tmp_path,
    mutation: str,
) -> None:
    container = svc.Container(
        session,
        clock=SystemClock(),
        blob=LocalBlobAdapter(tmp_path / f"baseline-cross-box-{mutation}-blobs"),
    )
    seeded = svc.provision_box(container, f"Baseline Cross Box {mutation} Clinic")
    ticket_id = _open_synthetic_ticket(container, seeded)
    runtime = _beta_settings(str(seeded["box_id"]))
    ticket = session.get(Ticket, ticket_id)
    revision = session.get(ActionRevision, ticket.current_revision_id if ticket else None)
    assert ticket is not None and revision is not None
    _inject_cross_box_linked_row(
        session,
        ticket,
        revision,
        str(seeded["owner_id"]),
        mutation,
    )

    with pytest.raises(BetaAcceptanceError, match="beta acceptance failed"):
        baseline_beta_workflow_acceptance(session, runtime, _HMAC_KEY)


@pytest.mark.parametrize(
    "mutation", ["revision", "decision", "operation", "audit", "operation_audit"]
)
def test_workflow_verify_rejects_cross_box_rows_linked_to_exact_ticket(
    session,
    tmp_path,
    monkeypatch,
    mutation: str,
) -> None:
    container = svc.Container(
        session,
        clock=SystemClock(),
        blob=LocalBlobAdapter(tmp_path / f"verify-cross-box-{mutation}-blobs"),
    )
    seeded = svc.provision_box(container, f"Verify Cross Box {mutation} Clinic")
    ticket_id = _open_synthetic_ticket(container, seeded)
    runtime = _beta_settings(str(seeded["box_id"]))
    state_json = baseline_beta_workflow_acceptance(session, runtime, _HMAC_KEY).sanitized_json()
    session.rollback()
    monkeypatch.setattr(svc.settings, "sync_worker", True)
    result = svc.decide(
        container,
        ticket_id,
        str(seeded["owner_id"]),
        DecisionKind.APPROVE,
    )
    ticket = session.get(Ticket, ticket_id)
    operation = session.get(Operation, result["operation_id"])
    revision = session.get(ActionRevision, ticket.current_revision_id if ticket else None)
    assert ticket is not None and operation is not None and revision is not None
    _inject_cross_box_linked_row(
        session,
        ticket,
        revision,
        str(seeded["owner_id"]),
        mutation,
        operation,
    )

    with pytest.raises(BetaAcceptanceError, match="beta acceptance failed"):
        verify_beta_workflow_acceptance(session, runtime, state_json, _HMAC_KEY)


@pytest.mark.parametrize("phase", ["baseline", "verify"])
def test_workflow_phases_reject_same_box_nonapproval_decision(
    session,
    tmp_path,
    monkeypatch,
    phase: str,
) -> None:
    container = svc.Container(
        session,
        clock=SystemClock(),
        blob=LocalBlobAdapter(tmp_path / f"{phase}-extra-reject-blobs"),
    )
    seeded = svc.provision_box(container, f"{phase} Extra Reject Clinic")
    ticket_id = _open_synthetic_ticket(container, seeded)
    runtime = _beta_settings(str(seeded["box_id"]))
    ticket = session.get(Ticket, ticket_id)
    revision = session.get(ActionRevision, ticket.current_revision_id if ticket else None)
    assert ticket is not None and revision is not None
    state_json = ""
    if phase == "verify":
        state_json = baseline_beta_workflow_acceptance(session, runtime, _HMAC_KEY).sanitized_json()
        session.rollback()
        monkeypatch.setattr(svc.settings, "sync_worker", True)
        svc.decide(
            container,
            ticket_id,
            str(seeded["owner_id"]),
            DecisionKind.APPROVE,
        )
    session.add(
        Decision(
            box_id=str(seeded["box_id"]),
            ticket_id=ticket.id,
            action_revision_id=revision.id,
            actor_principal_id=str(seeded["owner_id"]),
            kind=DecisionKind.REJECT.value,
        )
    )
    session.commit()

    with pytest.raises(BetaAcceptanceError, match="beta acceptance failed"):
        if phase == "baseline":
            baseline_beta_workflow_acceptance(session, runtime, _HMAC_KEY)
        else:
            verify_beta_workflow_acceptance(session, runtime, state_json, _HMAC_KEY)


@pytest.mark.parametrize(
    "mutation", ["revision", "decision", "operation", "audit", "operation_audit"]
)
def test_audit_replay_rejects_cross_box_rows_linked_to_exact_workflow(
    session,
    tmp_path,
    monkeypatch,
    mutation: str,
) -> None:
    container = svc.Container(
        session,
        clock=SystemClock(),
        blob=LocalBlobAdapter(tmp_path / f"audit-cross-box-{mutation}-blobs"),
    )
    seeded = svc.provision_box(container, f"Audit Cross Box {mutation} Clinic")
    ticket_id = _open_synthetic_ticket(container, seeded)
    runtime = _beta_settings(str(seeded["box_id"]))
    monkeypatch.setattr(svc.settings, "sync_worker", True)
    result = svc.decide(
        container,
        ticket_id,
        str(seeded["owner_id"]),
        DecisionKind.APPROVE,
    )
    ticket = session.get(Ticket, ticket_id)
    operation = session.get(Operation, result["operation_id"])
    revision = session.get(ActionRevision, ticket.current_revision_id if ticket else None)
    assert ticket is not None and operation is not None and revision is not None
    _inject_cross_box_linked_row(
        session,
        ticket,
        revision,
        str(seeded["owner_id"]),
        mutation,
        operation,
    )

    with pytest.raises(BetaAcceptanceError, match="beta acceptance failed"):
        verify_beta_audit_replay(session, runtime)


def test_audit_replay_rejects_self_consistent_message_and_hash_rewrite(
    session,
    tmp_path,
    monkeypatch,
) -> None:
    container = svc.Container(
        session,
        clock=SystemClock(),
        blob=LocalBlobAdapter(tmp_path / "audit-consistent-rewrite-blobs"),
    )
    seeded = svc.provision_box(container, "Audit Consistent Rewrite Clinic")
    ticket_id = _open_synthetic_ticket(container, seeded)
    runtime = _beta_settings(str(seeded["box_id"]))
    monkeypatch.setattr(svc.settings, "sync_worker", True)
    svc.decide(container, ticket_id, str(seeded["owner_id"]), DecisionKind.APPROVE)

    ticket = session.get(Ticket, ticket_id)
    revision = session.get(ActionRevision, ticket.current_revision_id if ticket else None)
    assert ticket is not None and revision is not None
    rewritten_message = "A different, internally consistent synthetic message"
    rewritten_payload = dict(revision.payload)
    rewritten_payload["body"] = rewritten_message
    rewritten_hash = hashlib.sha256(
        json.dumps(rewritten_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    revision.content = rewritten_message
    revision.payload = rewritten_payload
    revision.payload_hash = rewritten_hash
    events = session.scalars(
        select(AuditEvent).where(AuditEvent.action_revision_id == revision.id)
    ).all()
    assert len(events) == 3
    for event in events:
        event.payload_hash = rewritten_hash
    session.commit()

    with pytest.raises(BetaAcceptanceError, match="beta acceptance failed"):
        verify_beta_audit_replay(session, runtime)


def test_audit_replay_rejects_self_consistent_version_rewrite(
    session,
    tmp_path,
    monkeypatch,
) -> None:
    container = svc.Container(
        session,
        clock=SystemClock(),
        blob=LocalBlobAdapter(tmp_path / "audit-consistent-version-rewrite-blobs"),
    )
    seeded = svc.provision_box(container, "Audit Version Rewrite Clinic")
    ticket_id = _open_synthetic_ticket(container, seeded)
    runtime = _beta_settings(str(seeded["box_id"]))
    monkeypatch.setattr(svc.settings, "sync_worker", True)
    svc.decide(container, ticket_id, str(seeded["owner_id"]), DecisionKind.APPROVE)

    ticket = session.get(Ticket, ticket_id)
    revision = session.get(ActionRevision, ticket.current_revision_id if ticket else None)
    initiator = session.get(Principal, ticket.created_by_principal_id if ticket else None)
    assert ticket is not None and revision is not None and initiator is not None
    initiator.policy_version = revision.policy_version = "policy-v2"
    initiator.charter_version = revision.charter_version = "charter-v2"
    initiator.config_version = revision.config_version = "config-v2"
    events = session.scalars(
        select(AuditEvent).where(AuditEvent.action_revision_id == revision.id)
    ).all()
    assert len(events) == 3
    for event in events:
        if event.event_type != "operation.succeeded":
            event.policy_version = revision.policy_version
            event.charter_version = revision.charter_version
            event.config_version = revision.config_version
    session.commit()

    with pytest.raises(BetaAcceptanceError, match="beta acceptance failed"):
        verify_beta_audit_replay(session, runtime)


@pytest.mark.parametrize(
    "mutation",
    ["appointment", "patient_link", "non_owner_approver"],
)
def test_audit_replay_rejects_self_consistent_fixture_identity_rewrite(
    session,
    tmp_path,
    monkeypatch,
    mutation: str,
) -> None:
    container = svc.Container(
        session,
        clock=SystemClock(),
        blob=LocalBlobAdapter(tmp_path / f"audit-fixture-rewrite-{mutation}-blobs"),
    )
    seeded = svc.provision_box(container, f"Audit Fixture Rewrite {mutation} Clinic")
    ticket_id = _open_synthetic_ticket(container, seeded)
    runtime = _beta_settings(str(seeded["box_id"]))
    monkeypatch.setattr(svc.settings, "sync_worker", True)
    svc.decide(container, ticket_id, str(seeded["owner_id"]), DecisionKind.APPROVE)

    ticket = session.get(Ticket, ticket_id)
    revision = session.get(ActionRevision, ticket.current_revision_id if ticket else None)
    decision = session.scalar(select(Decision).where(Decision.ticket_id == ticket_id))
    appointment = session.get(AppointmentObservation, ticket.appointment_id if ticket else None)
    patient_link = session.get(PatientLink, ticket.patient_link_id if ticket else None)
    assert ticket is not None and revision is not None and decision is not None
    assert appointment is not None and patient_link is not None

    if mutation == "appointment":
        appointment.external_id = "appt-9009"
        appointment.start_at = datetime(2026, 9, 11, 16, 0, tzinfo=UTC)
        appointment.patient_label = patient_link.label = "Taylor Example"
        rewritten_payload = dict(revision.payload)
        rewritten_payload["appointment_ref"] = appointment.external_id
        revision.payload = rewritten_payload
        revision.payload_hash = hashlib.sha256(
            json.dumps(rewritten_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        for event in session.scalars(
            select(AuditEvent).where(AuditEvent.action_revision_id == revision.id)
        ).all():
            event.payload_hash = revision.payload_hash
    elif mutation == "patient_link":
        patient_link.source_pair_key = "csv:taylor-example"
        patient_link.label = appointment.patient_label = "Taylor Example"
    else:
        non_owner = Principal(
            box_id=str(seeded["box_id"]),
            principal_type="human",
            display_name="Pat Beta Member",
            state="active",
            is_owner=False,
        )
        session.add(non_owner)
        session.flush()
        decision.actor_principal_id = non_owner.id
        patient_link.confirmed_by_principal_id = non_owner.id
        approval = session.scalar(
            select(AuditEvent).where(
                AuditEvent.action_revision_id == revision.id,
                AuditEvent.event_type == "decision.approved",
            )
        )
        assert approval is not None
        approval.actor_principal_id = non_owner.id
        approval.approved_by_principal_id = non_owner.id
    session.commit()

    with pytest.raises(BetaAcceptanceError, match="beta acceptance failed"):
        verify_beta_audit_replay(session, runtime)


def test_audit_replay_rejects_consistently_future_dated_workflow(
    session,
    tmp_path,
    monkeypatch,
) -> None:
    container = svc.Container(
        session,
        clock=SystemClock(),
        blob=LocalBlobAdapter(tmp_path / "audit-future-workflow-blobs"),
    )
    seeded = svc.provision_box(container, "Audit Future Workflow Clinic")
    ticket_id = _open_synthetic_ticket(container, seeded)
    runtime = _beta_settings(str(seeded["box_id"]))
    monkeypatch.setattr(svc.settings, "sync_worker", True)
    result = svc.decide(
        container,
        ticket_id,
        str(seeded["owner_id"]),
        DecisionKind.APPROVE,
    )

    ticket = session.get(Ticket, ticket_id)
    revision = session.get(ActionRevision, ticket.current_revision_id if ticket else None)
    decision = session.scalar(select(Decision).where(Decision.ticket_id == ticket_id))
    operation = session.get(Operation, result["operation_id"])
    assert all(value is not None for value in (ticket, revision, decision, operation))
    assert ticket is not None and revision is not None and decision is not None
    assert operation is not None
    future = datetime(2035, 1, 1, tzinfo=UTC)
    ticket.created_at = future
    revision.created_at = future
    decision.created_at = future + timedelta(seconds=1)
    operation.created_at = future + timedelta(seconds=1)
    operation.started_at = future + timedelta(seconds=1)
    operation.completed_at = future + timedelta(seconds=2)
    events = session.scalars(
        select(AuditEvent).where(AuditEvent.action_revision_id == revision.id)
    ).all()
    assert len(events) == 3
    event_offsets = {
        "ticket.opened": 0,
        "decision.approved": 1,
        "operation.succeeded": 2,
    }
    for event in events:
        event.created_at = future + timedelta(seconds=event_offsets[event.event_type])
    session.commit()

    with pytest.raises(BetaAcceptanceError, match="beta acceptance failed"):
        verify_beta_audit_replay(session, runtime)


@pytest.mark.parametrize(
    "mutation",
    [
        "revision_before_ticket",
        "link_after_ticket",
        "ancient_link_attestation",
        "operation_before_creation",
        "decision_after_completion",
    ],
)
def test_audit_replay_rejects_causally_reordered_entities(
    session,
    tmp_path,
    monkeypatch,
    mutation: str,
) -> None:
    container = svc.Container(
        session,
        clock=SystemClock(),
        blob=LocalBlobAdapter(tmp_path / f"audit-chronology-{mutation}-blobs"),
    )
    seeded = svc.provision_box(container, f"Audit Chronology {mutation} Clinic")
    ticket_id = _open_synthetic_ticket(container, seeded)
    runtime = _beta_settings(str(seeded["box_id"]))
    monkeypatch.setattr(svc.settings, "sync_worker", True)
    result = svc.decide(
        container,
        ticket_id,
        str(seeded["owner_id"]),
        DecisionKind.APPROVE,
    )

    ticket = session.get(Ticket, ticket_id)
    revision = session.get(ActionRevision, ticket.current_revision_id if ticket else None)
    decision = session.scalar(select(Decision).where(Decision.ticket_id == ticket_id))
    operation = session.get(Operation, result["operation_id"])
    patient_link = session.get(PatientLink, ticket.patient_link_id if ticket else None)
    assert ticket is not None and revision is not None and decision is not None
    assert operation is not None and patient_link is not None
    assert operation.started_at is not None and operation.completed_at is not None
    if mutation == "revision_before_ticket":
        revision.created_at = ticket.created_at - timedelta(seconds=1)
    elif mutation == "link_after_ticket":
        patient_link.attested_at = ticket.created_at + timedelta(seconds=6)
    elif mutation == "ancient_link_attestation":
        opened = session.scalar(
            select(AuditEvent).where(
                AuditEvent.aggregate_id == ticket.id,
                AuditEvent.event_type == "ticket.opened",
            )
        )
        assert opened is not None
        patient_link.attested_at = opened.created_at - timedelta(seconds=6)
    elif mutation == "operation_before_creation":
        operation.started_at = operation.created_at - timedelta(seconds=6)
    else:
        decision.created_at = operation.completed_at + timedelta(seconds=1)
    session.commit()

    with pytest.raises(BetaAcceptanceError, match="beta acceptance failed"):
        verify_beta_audit_replay(session, runtime)


def test_audit_replay_allows_bounded_application_database_clock_skew(
    session,
    tmp_path,
    monkeypatch,
) -> None:
    container = svc.Container(
        session,
        clock=SystemClock(),
        blob=LocalBlobAdapter(tmp_path / "audit-bounded-skew-blobs"),
    )
    seeded = svc.provision_box(container, "Audit Bounded Skew Clinic")
    ticket_id = _open_synthetic_ticket(container, seeded)
    runtime = _beta_settings(str(seeded["box_id"]))
    monkeypatch.setattr(svc.settings, "sync_worker", True)
    result = svc.decide(
        container,
        ticket_id,
        str(seeded["owner_id"]),
        DecisionKind.APPROVE,
    )
    ticket = session.get(Ticket, ticket_id)
    operation = session.get(Operation, result["operation_id"])
    patient_link = session.get(PatientLink, ticket.patient_link_id if ticket else None)
    assert ticket is not None and operation is not None and patient_link is not None
    operation.started_at = operation.created_at - timedelta(seconds=2)
    session.commit()

    assert verify_beta_audit_replay(session, runtime).status == "verified"


def test_audit_replay_allows_bounded_audit_clock_ahead_of_database(
    session,
    tmp_path,
    monkeypatch,
) -> None:
    container = svc.Container(
        session,
        clock=SystemClock(),
        blob=LocalBlobAdapter(tmp_path / "audit-event-bounded-skew-blobs"),
    )
    seeded = svc.provision_box(container, "Audit Event Bounded Skew Clinic")
    ticket_id = _open_synthetic_ticket(container, seeded)
    runtime = _beta_settings(str(seeded["box_id"]))
    monkeypatch.setattr(svc.settings, "sync_worker", True)
    result = svc.decide(
        container,
        ticket_id,
        str(seeded["owner_id"]),
        DecisionKind.APPROVE,
    )
    ticket = session.get(Ticket, ticket_id)
    revision = session.get(ActionRevision, ticket.current_revision_id if ticket else None)
    decision = session.scalar(select(Decision).where(Decision.ticket_id == ticket_id))
    operation = session.get(Operation, result["operation_id"])
    patient_link = session.get(PatientLink, ticket.patient_link_id if ticket else None)
    assert ticket is not None and revision is not None and decision is not None
    assert operation is not None and patient_link is not None
    events = {
        event.event_type: event
        for event in session.scalars(
            select(AuditEvent).where(AuditEvent.action_revision_id == revision.id)
        ).all()
    }
    assert set(events) == {"ticket.opened", "decision.approved", "operation.succeeded"}
    database_observed_at = max(
        ticket.created_at,
        revision.created_at,
        decision.created_at,
        operation.created_at,
    )
    patient_link.attested_at = database_observed_at + timedelta(seconds=1)
    events["ticket.opened"].created_at = database_observed_at + timedelta(
        seconds=1, milliseconds=100
    )
    events["decision.approved"].created_at = database_observed_at + timedelta(
        seconds=1, milliseconds=200
    )
    operation.started_at = database_observed_at + timedelta(seconds=1, milliseconds=300)
    operation.completed_at = database_observed_at + timedelta(seconds=1, milliseconds=400)
    events["operation.succeeded"].created_at = database_observed_at + timedelta(
        seconds=1, milliseconds=500
    )
    session.commit()
    monkeypatch.setattr(
        beta_acceptance_module,
        "_database_now",
        lambda _session: database_observed_at,
    )

    assert verify_beta_audit_replay(session, runtime).status == "verified"


def test_audit_replay_binds_every_returned_timeline_field(
    session,
    tmp_path,
    monkeypatch,
) -> None:
    container = svc.Container(
        session,
        clock=SystemClock(),
        blob=LocalBlobAdapter(tmp_path / "audit-projection-rewrite-blobs"),
    )
    seeded = svc.provision_box(container, "Audit Projection Rewrite Clinic")
    ticket_id = _open_synthetic_ticket(container, seeded)
    runtime = _beta_settings(str(seeded["box_id"]))
    monkeypatch.setattr(svc.settings, "sync_worker", True)
    svc.decide(container, ticket_id, str(seeded["owner_id"]), DecisionKind.APPROVE)
    original_timeline = svc.audit_timeline

    def rewritten_timeline(*args, **kwargs):
        timeline = [dict(item) for item in original_timeline(*args, **kwargs)]
        timeline[0]["actor_principal_id"] = str(uuid4())
        timeline[1]["approved_by_principal_id"] = str(uuid4())
        timeline[2]["action_revision_id"] = str(uuid4())
        timeline[2]["payload_hash"] = "f" * 64
        return timeline

    monkeypatch.setattr(svc, "audit_timeline", rewritten_timeline)
    with pytest.raises(BetaAcceptanceError, match="beta acceptance failed"):
        verify_beta_audit_replay(session, runtime)


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


def test_workflow_acceptance_state_expiry_is_exclusive(
    session,
    tmp_path,
    monkeypatch,
) -> None:
    container = svc.Container(
        session,
        clock=SystemClock(),
        blob=LocalBlobAdapter(tmp_path / "expiry-boundary-blobs"),
    )
    seeded = svc.provision_box(container, "Expiry Boundary Clinic")
    _open_synthetic_ticket(container, seeded)
    runtime = _beta_settings(str(seeded["box_id"]))
    state = baseline_beta_workflow_acceptance(session, runtime, _HMAC_KEY)
    exact_expiry = datetime.fromisoformat(state.expires_at.replace("Z", "+00:00"))
    monkeypatch.setattr(
        beta_acceptance_module,
        "_database_now",
        lambda _session: exact_expiry,
    )

    with pytest.raises(BetaAcceptanceError, match="beta acceptance failed"):
        verify_beta_workflow_acceptance(
            session,
            runtime,
            state.sanitized_json(),
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
    receipt["deleted_at"] = receipt_deleted_at.astimezone(timezone(timedelta(hours=-7))).isoformat()
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
