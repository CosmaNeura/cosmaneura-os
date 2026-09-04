from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

from azure.core.exceptions import ResourceNotFoundError
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from cosmas_os.adapters.azure import AzureBlobAdapter
from cosmas_os.config import Settings
from cosmas_os.domain.enums import (
    AutomationClass,
    DecisionKind,
    OperationStatus,
    PrincipalState,
    PrincipalType,
    TicketState,
)
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.domain.rules import AuthorizationError
from cosmas_os.models import (
    ActionRevision,
    AppointmentObservation,
    Artifact,
    AuditEvent,
    Decision,
    Operation,
    PatientLink,
    Principal,
    Ticket,
)
from cosmas_os.ports import BlobPort

WORKFLOW_ACCEPTANCE_CONTRACT = "cosmas-os-d3-workflow-acceptance-v1"
AUDIT_REPLAY_CONTRACT = "cosmas-os-d3-audit-replay-acceptance-v1"
PURGE_ACCEPTANCE_CONTRACT = "cosmas-os-d3-physical-purge-acceptance-v1"

_HANDLE_PATTERN = r"^[0-9a-f]{64}$"
_KEY_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_STATE_LIFETIME = timedelta(hours=4)
_PURGE_CLASSIFICATION = "synthetic_purge_acceptance"
_PURGE_CONTENT = b"COSMAS_OS_SYNTHETIC_PURGE_ACCEPTANCE_V1\n"
_PURGE_CONTENT_TYPE = "application/octet-stream"
_PURGE_RETAIN_DAYS = 7
_SYNTHETIC_APPOINTMENT_REF = "appt-1001"
_SYNTHETIC_APPOINTMENT_START = datetime(2026, 9, 10, 15, 0, tzinfo=UTC)
_SYNTHETIC_PATIENT_LABEL = "Jordan Lee"
_SYNTHETIC_PATIENT_LINK_SOURCE = "csv:jordan-lee"
_SYNTHETIC_MESSAGE = (
    "Please use the secure link to share insurance information before your visit. "
    "This message contains no clinical details."
)
_SYNTHETIC_POLICY_VERSION = "policy-v1"
_SYNTHETIC_CHARTER_VERSION = "charter-v1"
_SYNTHETIC_CONFIG_VERSION = "config-v1"
_WORKER_AUDIT_CLOCK_BOUND = timedelta(seconds=5)


class BetaAcceptanceError(RuntimeError):
    """A live beta acceptance assertion failed without exposing its inputs."""


def _reject_acceptance_if(*conditions: bool) -> None:
    if any(conditions):
        raise BetaAcceptanceError("beta acceptance failed")


class _SignedState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract: str
    stage: Literal["baseline", "setup"]
    status: Literal["ready_for_browser"]
    issued_at: str
    expires_at: str
    state_mac: str = Field(pattern=_HANDLE_PATTERN)
    evidence_sha256: str = Field(pattern=_HANDLE_PATTERN)

    def sanitized_json(self) -> str:
        return _canonical_json(self.model_dump())


class WorkflowBaselineState(_SignedState):
    contract: Literal["cosmas-os-d3-workflow-acceptance-v1"]
    stage: Literal["baseline"]
    ticket_handle: str = Field(pattern=_HANDLE_PATTERN)
    pending_ticket_count: Literal[1]
    approval_decision_count: Literal[0]
    operation_count: Literal[0]
    approval_audit_count: Literal[0]
    success_audit_count: Literal[0]


class PurgeSetupState(_SignedState):
    contract: Literal["cosmas-os-d3-physical-purge-acceptance-v1"]
    stage: Literal["setup"]
    artifact_handle: str = Field(pattern=_HANDLE_PATTERN)
    due_unpurged_artifact_count: Literal[1]
    purge_audit_count: Literal[0]
    blob_current_representation_readable: Literal[True]


@dataclass(frozen=True)
class WorkflowAcceptanceEvidence:
    contract: str
    stage: str
    status: str
    completed_at: str
    state_bound: bool
    async_dispatch_configured: bool
    current_revision_valid: bool
    approval_decision_delta: int
    durable_operation_delta: int
    worker_attempted: bool
    operation_succeeded: bool
    fake_notify_receipt_verified: bool
    ticket_sent: bool
    approval_audit_delta: int
    success_audit_delta: int
    approval_precedes_worker_success: bool

    def sanitized_payload(self) -> dict[str, str | bool | int]:
        return asdict(self)

    def sanitized_json(self) -> str:
        return _evidence_json(self.sanitized_payload())


@dataclass(frozen=True)
class AuditReplayEvidence:
    contract: str
    stage: str
    status: str
    completed_at: str
    box_scope_enforced: bool
    cross_box_replay_denied: bool
    ticket_timeline_replayed: bool
    operation_events_linked: bool
    required_event_order_verified: bool
    no_content_fields_returned: bool
    timeline_event_count: int
    identifiers_returned: bool
    content_returned: bool

    def sanitized_payload(self) -> dict[str, str | bool | int]:
        return asdict(self)

    def sanitized_json(self) -> str:
        return _evidence_json(self.sanitized_payload())


@dataclass(frozen=True)
class PurgeAcceptanceEvidence:
    contract: str
    stage: str
    status: str
    completed_at: str
    state_bound: bool
    owner_authorized_purge_observed: bool
    owner_authority_verified: bool
    application_tombstone_verified: bool
    purge_receipt_verified: bool
    purge_audit_delta: int
    blob_current_representation_absent: bool
    blob_version_representations_absent: bool
    blob_snapshot_representations_absent: bool
    blob_deleted_representations_absent: bool
    blob_recoverable_absence_verified: bool
    due_unpurged_probe_count: int

    def sanitized_payload(self) -> dict[str, str | bool | int]:
        return asdict(self)

    def sanitized_json(self) -> str:
        return _evidence_json(self.sanitized_payload())


def acceptance_failure_json(contract: str) -> str:
    return _canonical_json({"contract": contract, "status": "failed"})


def decode_acceptance_hmac_key(value: str | None) -> bytes:
    """Decode the wrapper-provided, ephemeral 256-bit state-binding key."""

    if value is None or _KEY_PATTERN.fullmatch(value) is None:
        raise BetaAcceptanceError("beta acceptance failed")
    return bytes.fromhex(value)


def _require_hmac_key(key: bytes) -> None:
    if len(key) != 32:
        raise BetaAcceptanceError("beta acceptance failed")


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _evidence_json(payload: dict[str, Any]) -> str:
    canonical = _canonical_json(payload)
    result = dict(payload)
    result["evidence_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return _canonical_json(result)


def _utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise BetaAcceptanceError("beta acceptance failed")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_utc_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise BetaAcceptanceError("beta acceptance failed") from None
    if parsed.tzinfo is None or _utc_timestamp(parsed) != value:
        raise BetaAcceptanceError("beta acceptance failed")
    return parsed.astimezone(UTC)


def _timestamp_matches(value: object, expected: datetime | None) -> bool:
    """Compare persisted ISO timestamps by instant, independent of DB session timezone."""

    if not isinstance(value, str) or expected is None or expected.tzinfo is None:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, OverflowError):
        return False
    return parsed.tzinfo is not None and parsed == expected


def _database_now(session: Session) -> datetime:
    # PostgreSQL now() is fixed at transaction start and can precede a worker's
    # just-recorded wall-clock timestamps.  clock_timestamp() is the live DB
    # boundary required for strict no-future evidence validation.
    observed = session.scalar(select(func.clock_timestamp()))
    if not isinstance(observed, datetime):
        raise BetaAcceptanceError("beta acceptance failed")
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=UTC)
    return observed.astimezone(UTC)


def _validate_runtime(runtime: Settings, *, require_blob: bool) -> str:
    try:
        runtime.validate_runtime_configuration()
        box_id = str(UUID(runtime.beta_box_id or ""))
    except Exception:
        raise BetaAcceptanceError("beta acceptance failed") from None
    if (
        runtime.cosmas_env != "early_adopter_beta"
        or runtime.data_mode != "synthetic"
        or runtime.sync_worker
        or (require_blob and runtime.blob_backend != "azure")
    ):
        raise BetaAcceptanceError("beta acceptance failed")
    if box_id != runtime.beta_box_id:
        raise BetaAcceptanceError("beta acceptance failed")
    return box_id


def _canonical_client_id(value: str | None) -> str:
    try:
        canonical = str(UUID(value or ""))
    except ValueError:
        raise BetaAcceptanceError("beta acceptance failed") from None
    if canonical != value:
        raise BetaAcceptanceError("beta acceptance failed")
    return canonical


def _validate_exact_runtime_identity(
    actual_client_id: str | None,
    expected_client_id: str | None,
) -> str:
    actual = _canonical_client_id(actual_client_id)
    expected = _canonical_client_id(expected_client_id)
    if not hmac.compare_digest(actual, expected):
        raise BetaAcceptanceError("beta acceptance failed")
    return actual


def _opaque_handle(key: bytes, domain: str, box_id: str, record_id: str) -> str:
    material = f"{domain}\0{box_id}\0{record_id}".encode()
    return hmac.new(key, material, hashlib.sha256).hexdigest()


def _signed_state_payload(payload: dict[str, Any], key: bytes) -> dict[str, Any]:
    state_mac = hmac.new(
        key,
        _canonical_json(payload).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    with_mac = {**payload, "state_mac": state_mac}
    return {
        **with_mac,
        "evidence_sha256": hashlib.sha256(_canonical_json(with_mac).encode("utf-8")).hexdigest(),
    }


def _validate_signed_state(state: _SignedState, key: bytes, now: datetime) -> None:
    state_values = state.model_dump()
    evidence_sha256 = state_values.pop("evidence_sha256")
    if not hmac.compare_digest(
        evidence_sha256,
        hashlib.sha256(_canonical_json(state_values).encode("utf-8")).hexdigest(),
    ):
        raise BetaAcceptanceError("beta acceptance failed")
    state_mac = state_values.pop("state_mac")
    if not hmac.compare_digest(
        state_mac,
        hmac.new(
            key,
            _canonical_json(state_values).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest(),
    ):
        raise BetaAcceptanceError("beta acceptance failed")
    issued_at = _parse_utc_timestamp(state.issued_at)
    expires_at = _parse_utc_timestamp(state.expires_at)
    if expires_at - issued_at != _STATE_LIFETIME or now < issued_at or now >= expires_at:
        raise BetaAcceptanceError("beta acceptance failed")


def _validate_workflow_revision(revision: ActionRevision | None, ticket: Ticket) -> ActionRevision:
    if (
        revision is None
        or revision.id != ticket.current_revision_id
        or revision.ticket_id != ticket.id
        or revision.box_id != ticket.box_id
        or revision.invalidated
        or revision.action_type != "notify.patient_insurance_request"
        or revision.automation_class != AutomationClass.HITL_REQUIRED.value
        or revision.payload.get("channel") != "fake_secure_link"
        or payload_hash(revision.payload) != revision.payload_hash
    ):
        raise BetaAcceptanceError("beta acceptance failed")
    return revision


def _workflow_counts(
    session: Session,
    ticket: Ticket,
) -> tuple[list[ActionRevision], list[Decision], list[Operation], list[AuditEvent]]:
    revisions = list(
        session.scalars(select(ActionRevision).where(ActionRevision.ticket_id == ticket.id)).all()
    )
    decisions = list(session.scalars(select(Decision).where(Decision.ticket_id == ticket.id)).all())
    operations = list(
        session.scalars(select(Operation).where(Operation.ticket_id == ticket.id)).all()
    )
    linked_audits = list(
        session.scalars(
            select(AuditEvent).where(
                or_(
                    AuditEvent.action_revision_id == ticket.current_revision_id,
                    and_(
                        AuditEvent.aggregate_type == "ticket",
                        AuditEvent.aggregate_id == ticket.id,
                    ),
                    and_(
                        AuditEvent.aggregate_type == "operation",
                        AuditEvent.aggregate_id.in_([operation.id for operation in operations]),
                    ),
                )
            )
        ).all()
    )
    return revisions, decisions, operations, linked_audits


def baseline_beta_workflow_acceptance(
    session: Session,
    runtime: Settings,
    hmac_key: bytes,
) -> WorkflowBaselineState:
    """Bind a protected, ID-free state record to one pending synthetic ticket."""

    try:
        _require_hmac_key(hmac_key)
        box_id = _validate_runtime(runtime, require_blob=False)
        pending = list(
            session.scalars(
                select(Ticket)
                .where(
                    Ticket.box_id == box_id,
                    Ticket.state == TicketState.PENDING_APPROVAL.value,
                )
                .with_for_update()
            ).all()
        )
        if len(pending) != 1:
            raise BetaAcceptanceError("beta acceptance failed")
        ticket = pending[0]
        revisions, decisions, operations, linked_audits = _workflow_counts(session, ticket)
        if len(revisions) != 1 or decisions or operations or len(linked_audits) != 1:
            raise BetaAcceptanceError("beta acceptance failed")
        revision = _validate_workflow_revision(revisions[0], ticket)
        opened = linked_audits[0]
        if (
            opened.box_id != box_id
            or opened.aggregate_type != "ticket"
            or opened.aggregate_id != ticket.id
            or opened.event_type != "ticket.opened"
            or opened.actor_principal_id != revision.created_by_principal_id
            or opened.initiated_by_principal_id != revision.created_by_principal_id
            or opened.approved_by_principal_id is not None
            or opened.action_revision_id != revision.id
            or opened.payload_hash != revision.payload_hash
            or opened.policy_version != revision.policy_version
            or opened.charter_version != revision.charter_version
            or opened.config_version != revision.config_version
            or opened.outcome != "pending_approval"
            or opened.detail != {}
        ):
            raise BetaAcceptanceError("beta acceptance failed")

        observed_at = _database_now(session)
        payload = {
            "contract": WORKFLOW_ACCEPTANCE_CONTRACT,
            "stage": "baseline",
            "status": "ready_for_browser",
            "issued_at": _utc_timestamp(observed_at),
            "expires_at": _utc_timestamp(observed_at + _STATE_LIFETIME),
            "ticket_handle": _opaque_handle(hmac_key, "workflow-ticket", box_id, ticket.id),
            "pending_ticket_count": 1,
            "approval_decision_count": 0,
            "operation_count": 0,
            "approval_audit_count": 0,
            "success_audit_count": 0,
        }
        return WorkflowBaselineState.model_validate(_signed_state_payload(payload, hmac_key))
    except BetaAcceptanceError:
        raise
    except Exception:
        raise BetaAcceptanceError("beta acceptance failed") from None


def _parse_workflow_state(state_json: str, key: bytes, now: datetime) -> WorkflowBaselineState:
    try:
        state = WorkflowBaselineState.model_validate_json(state_json)
    except (ValidationError, ValueError):
        raise BetaAcceptanceError("beta acceptance failed") from None
    _validate_signed_state(state, key, now)
    return state


def verify_beta_workflow_acceptance(
    session: Session,
    runtime: Settings,
    state_json: str,
    hmac_key: bytes,
) -> WorkflowAcceptanceEvidence:
    """Verify the browser approval produced one durable async worker outcome."""

    try:
        _require_hmac_key(hmac_key)
        box_id = _validate_runtime(runtime, require_blob=False)
        observed_at = _database_now(session)
        state = _parse_workflow_state(state_json, hmac_key, observed_at)
        candidates = list(session.scalars(select(Ticket).where(Ticket.box_id == box_id)).all())
        matches = [
            ticket
            for ticket in candidates
            if hmac.compare_digest(
                _opaque_handle(hmac_key, "workflow-ticket", box_id, ticket.id),
                state.ticket_handle,
            )
        ]
        if len(matches) != 1:
            raise BetaAcceptanceError("beta acceptance failed")
        ticket = matches[0]
        revisions, decisions, operations, linked_audits = _workflow_counts(session, ticket)
        if len(revisions) != 1:
            raise BetaAcceptanceError("beta acceptance failed")
        revision = _validate_workflow_revision(revisions[0], ticket)
        approval_audits = [
            event for event in linked_audits if event.event_type == "decision.approved"
        ]
        success_audits = [
            event for event in linked_audits if event.event_type == "operation.succeeded"
        ]
        opened_audits = [event for event in linked_audits if event.event_type == "ticket.opened"]
        if (
            len(decisions) - state.approval_decision_count != 1
            or len(operations) - state.operation_count != 1
            or len(approval_audits) - state.approval_audit_count != 1
            or len(success_audits) - state.success_audit_count != 1
            or len(opened_audits) != 1
            or len(linked_audits) != 3
        ):
            raise BetaAcceptanceError("beta acceptance failed")

        decision = decisions[0]
        operation = operations[0]
        opened_audit = opened_audits[0]
        approval_audit = approval_audits[0]
        matching_success_audits = [
            event
            for event in success_audits
            if event.aggregate_type == "operation" and event.aggregate_id == operation.id
        ]
        if len(matching_success_audits) - state.success_audit_count != 1:
            raise BetaAcceptanceError("beta acceptance failed")
        success_audit = matching_success_audits[0]
        approver = session.get(Principal, decision.actor_principal_id)
        expected_reference = f"fake-{operation.id}"
        expected_receipt_hash = payload_hash(
            {"ref": expected_reference, "status": OperationStatus.SUCCEEDED.value}
        )
        issued_at = _parse_utc_timestamp(state.issued_at)
        timestamps = (
            decision.created_at,
            operation.created_at,
            operation.started_at,
            operation.completed_at,
            approval_audit.created_at,
            success_audit.created_at,
        )
        if (
            decision.box_id != box_id
            or decision.kind != DecisionKind.APPROVE.value
            or decision.action_revision_id != revision.id
            or decision.ticket_id != ticket.id
            or decision.note is not None
            or approver is None
            or approver.box_id != box_id
            or approver.principal_type != PrincipalType.HUMAN.value
            or approver.state != PrincipalState.ACTIVE.value
            or not approver.is_owner
            or approver.agent_key is not None
            or approver.policy_version != revision.policy_version
            or approver.charter_version != revision.charter_version
            or approver.config_version != revision.config_version
            or approver.tombstoned_at is not None
            or operation.box_id != box_id
            or operation.action_revision_id != revision.id
            or operation.ticket_id != ticket.id
            or operation.adapter != "notify"
            or operation.status != OperationStatus.SUCCEEDED.value
            or operation.attempt_count != 1
            or operation.error_message is not None
            or not hmac.compare_digest(operation.external_reference or "", expected_reference)
            or not hmac.compare_digest(operation.result_receipt_hash or "", expected_receipt_hash)
            or ticket.state != TicketState.SENT.value
            or opened_audit.box_id != box_id
            or opened_audit.aggregate_type != "ticket"
            or opened_audit.aggregate_id != ticket.id
            or opened_audit.event_type != "ticket.opened"
            or opened_audit.actor_principal_id != revision.created_by_principal_id
            or opened_audit.initiated_by_principal_id != revision.created_by_principal_id
            or opened_audit.approved_by_principal_id is not None
            or opened_audit.action_revision_id != revision.id
            or opened_audit.payload_hash != revision.payload_hash
            or opened_audit.policy_version != revision.policy_version
            or opened_audit.charter_version != revision.charter_version
            or opened_audit.config_version != revision.config_version
            or opened_audit.outcome != "pending_approval"
            or opened_audit.detail != {}
            or approval_audit.box_id != box_id
            or approval_audit.aggregate_type != "ticket"
            or approval_audit.aggregate_id != ticket.id
            or approval_audit.event_type != "decision.approved"
            or approval_audit.actor_principal_id != decision.actor_principal_id
            or approval_audit.initiated_by_principal_id is not None
            or approval_audit.action_revision_id != revision.id
            or approval_audit.payload_hash != revision.payload_hash
            or approval_audit.approved_by_principal_id != decision.actor_principal_id
            or approval_audit.policy_version != revision.policy_version
            or approval_audit.charter_version != revision.charter_version
            or approval_audit.config_version != revision.config_version
            or approval_audit.outcome != "approved"
            or approval_audit.detail != {"operation_bound": True}
            or success_audit.box_id != box_id
            or success_audit.aggregate_type != "operation"
            or success_audit.aggregate_id != operation.id
            or success_audit.event_type != "operation.succeeded"
            or success_audit.actor_principal_id is not None
            or success_audit.initiated_by_principal_id is not None
            or success_audit.approved_by_principal_id is not None
            or success_audit.action_revision_id != revision.id
            or success_audit.payload_hash != revision.payload_hash
            or success_audit.policy_version is not None
            or success_audit.charter_version is not None
            or success_audit.config_version is not None
            or success_audit.outcome != "succeeded"
            or success_audit.detail != {"external_reference": expected_reference}
            or any(value is None for value in timestamps)
        ):
            raise BetaAcceptanceError("beta acceptance failed")
        assert operation.started_at is not None
        assert operation.completed_at is not None
        # PostgreSQL creation timestamps share a transaction clock. API audit
        # and worker timestamps can come from separate application hosts, so
        # only their cross-host causal edges receive the explicit skew bound.
        if not (
            issued_at <= decision.created_at + _WORKER_AUDIT_CLOCK_BOUND
            and decision.created_at <= operation.created_at
            and operation.started_at <= operation.completed_at
            and operation.completed_at <= success_audit.created_at
            and abs((approval_audit.created_at - operation.created_at).total_seconds())
            <= _WORKER_AUDIT_CLOCK_BOUND.total_seconds()
            and approval_audit.created_at <= operation.started_at + _WORKER_AUDIT_CLOCK_BOUND
            and all(
                value.tzinfo is not None and value.astimezone(UTC) <= observed_at
                for value in (decision.created_at, operation.created_at)
            )
            and all(
                value.tzinfo is not None
                and value.astimezone(UTC) <= observed_at + _WORKER_AUDIT_CLOCK_BOUND
                for value in (
                    operation.started_at,
                    operation.completed_at,
                    approval_audit.created_at,
                    success_audit.created_at,
                )
            )
        ):
            raise BetaAcceptanceError("beta acceptance failed")

        return WorkflowAcceptanceEvidence(
            contract=WORKFLOW_ACCEPTANCE_CONTRACT,
            stage="post_browser",
            status="verified",
            completed_at=_utc_timestamp(observed_at),
            state_bound=True,
            async_dispatch_configured=True,
            current_revision_valid=True,
            approval_decision_delta=1,
            durable_operation_delta=1,
            worker_attempted=True,
            operation_succeeded=True,
            fake_notify_receipt_verified=True,
            ticket_sent=True,
            approval_audit_delta=1,
            success_audit_delta=1,
            approval_precedes_worker_success=True,
        )
    except BetaAcceptanceError:
        raise
    except Exception:
        raise BetaAcceptanceError("beta acceptance failed") from None


def verify_beta_audit_replay(
    session: Session,
    runtime: Settings,
) -> AuditReplayEvidence:
    """Replay one completed synthetic workflow without exporting row identifiers or content."""

    from cosmas_os.application import services as svc

    try:
        box_id = _validate_runtime(runtime, require_blob=False)
        observed_at = _database_now(session)
        tickets = list(session.scalars(select(Ticket).where(Ticket.box_id == box_id)).all())
        if len(tickets) != 1 or tickets[0].state != TicketState.SENT.value:
            raise BetaAcceptanceError("beta acceptance failed")
        ticket = tickets[0]
        revisions = list(
            session.scalars(
                select(ActionRevision).where(ActionRevision.ticket_id == ticket.id)
            ).all()
        )
        decisions = list(
            session.scalars(select(Decision).where(Decision.ticket_id == ticket.id)).all()
        )
        operations = list(
            session.scalars(select(Operation).where(Operation.ticket_id == ticket.id)).all()
        )
        if len(revisions) != 1 or len(decisions) != 1 or len(operations) != 1:
            raise BetaAcceptanceError("beta acceptance failed")
        revision = _validate_workflow_revision(revisions[0], ticket)
        decision = decisions[0]
        operation = operations[0]
        approver = session.get(Principal, decision.actor_principal_id)
        initiator = session.get(Principal, ticket.created_by_principal_id)
        appointment = session.get(AppointmentObservation, ticket.appointment_id)
        patient_link = session.get(PatientLink, ticket.patient_link_id)
        expected_reference = f"fake-{operation.id}"
        expected_receipt_hash = payload_hash(
            {"ref": expected_reference, "status": OperationStatus.SUCCEEDED.value}
        )
        expected_payload = {
            "action": "notify.patient_insurance_request",
            "channel": "fake_secure_link",
            "body": _SYNTHETIC_MESSAGE,
            "target_ref": f"patient_link:{ticket.patient_link_id}",
            "appointment_ref": _SYNTHETIC_APPOINTMENT_REF,
        }
        _reject_acceptance_if(
            ticket.version != 2,
            ticket.lane != "artifact_chase",
            ticket.closed_at is not None,
            ticket.current_revision_id != revision.id,
            ticket.appointment_id is None,
            ticket.patient_link_id is None,
            initiator is None,
            appointment is None,
            patient_link is None,
            approver is None,
        )
        assert initiator is not None
        assert appointment is not None
        assert patient_link is not None
        assert approver is not None
        _reject_acceptance_if(
            initiator.box_id != box_id,
            initiator.principal_type != PrincipalType.AGENT.value,
            initiator.agent_key != "chaser",
            initiator.display_name != "Chaser",
            initiator.state != PrincipalState.ACTIVE.value,
            initiator.is_owner,
            initiator.policy_version != _SYNTHETIC_POLICY_VERSION,
            initiator.charter_version != _SYNTHETIC_CHARTER_VERSION,
            initiator.config_version != _SYNTHETIC_CONFIG_VERSION,
            initiator.tombstoned_at is not None,
            appointment.box_id != box_id,
            appointment.external_id != _SYNTHETIC_APPOINTMENT_REF,
            appointment.source != "csv",
            appointment.start_at.astimezone(UTC) != _SYNTHETIC_APPOINTMENT_START,
            appointment.patient_label != _SYNTHETIC_PATIENT_LABEL,
            appointment.coverage_status != "missing",
            appointment.patient_link_id != ticket.patient_link_id,
            patient_link.box_id != box_id,
            patient_link.id != ticket.patient_link_id,
            patient_link.source_pair_key != _SYNTHETIC_PATIENT_LINK_SOURCE,
            patient_link.label != _SYNTHETIC_PATIENT_LABEL,
            patient_link.confirmed_by_principal_id != decision.actor_principal_id,
            patient_link.attested_at is None,
            patient_link.state != "confirmed",
            patient_link.revoked_at is not None,
        )
        _reject_acceptance_if(
            revision.revision_number != 1,
            revision.action_type != "notify.patient_insurance_request",
            revision.created_by_principal_id != initiator.id,
            revision.target_ref != f"patient_link:{ticket.patient_link_id}",
            revision.content != _SYNTHETIC_MESSAGE,
            revision.payload != expected_payload,
            revision.payload_hash != payload_hash(expected_payload),
            revision.policy_version != initiator.policy_version,
            revision.charter_version != initiator.charter_version,
            revision.config_version != initiator.config_version,
            decision.kind != DecisionKind.APPROVE.value,
            decision.box_id != box_id,
            decision.ticket_id != ticket.id,
            decision.action_revision_id != revision.id,
            decision.note is not None,
            approver.box_id != box_id,
            approver.principal_type != PrincipalType.HUMAN.value,
            approver.state != PrincipalState.ACTIVE.value,
            not approver.is_owner,
            approver.agent_key is not None,
            approver.policy_version != _SYNTHETIC_POLICY_VERSION,
            approver.charter_version != _SYNTHETIC_CHARTER_VERSION,
            approver.config_version != _SYNTHETIC_CONFIG_VERSION,
            approver.tombstoned_at is not None,
        )
        _reject_acceptance_if(
            operation.box_id != box_id,
            operation.ticket_id != ticket.id,
            operation.action_revision_id != revision.id,
            operation.idempotency_key != f"op:{revision.id}",
            operation.adapter != "notify",
            operation.status != OperationStatus.SUCCEEDED.value,
            operation.attempt_count != 1,
            operation.error_message is not None,
            not hmac.compare_digest(operation.external_reference or "", expected_reference),
            not hmac.compare_digest(operation.result_receipt_hash or "", expected_receipt_hash),
            operation.started_at is None,
            operation.completed_at is None,
        )
        assert operation.started_at is not None
        assert operation.completed_at is not None
        assert patient_link.attested_at is not None
        _reject_acceptance_if(
            operation.started_at > operation.completed_at,
            any(
                value is None or value.tzinfo is None or value.astimezone(UTC) > observed_at
                for value in (
                    ticket.created_at,
                    revision.created_at,
                    decision.created_at,
                    operation.created_at,
                )
            ),
            any(
                value.tzinfo is None
                or value.astimezone(UTC) > observed_at + _WORKER_AUDIT_CLOCK_BOUND
                for value in (
                    operation.started_at,
                    operation.completed_at,
                    patient_link.attested_at,
                )
            ),
        )

        linked_events = list(
            session.scalars(
                select(AuditEvent)
                .where(
                    or_(
                        AuditEvent.action_revision_id == revision.id,
                        and_(
                            AuditEvent.aggregate_type == "ticket",
                            AuditEvent.aggregate_id == ticket.id,
                        ),
                        and_(
                            AuditEvent.aggregate_type == "operation",
                            AuditEvent.aggregate_id == operation.id,
                        ),
                    )
                )
                .order_by(AuditEvent.created_at, AuditEvent.id)
            ).all()
        )
        ticket_events = [
            event
            for event in linked_events
            if event.aggregate_type == "ticket" and event.aggregate_id == ticket.id
        ]
        operation_events = [
            event
            for event in linked_events
            if event.aggregate_type == "operation" and event.aggregate_id == operation.id
        ]
        if len(ticket_events) != 2 or len(operation_events) != 1:
            raise BetaAcceptanceError("beta acceptance failed")
        opened, approved = ticket_events
        succeeded = operation_events[0]
        correlation_ids: set[str] = set()
        for event in (opened, approved, succeeded):
            try:
                correlation_id = str(UUID(str(event.correlation_id)))
            except ValueError:
                raise BetaAcceptanceError("beta acceptance failed") from None
            if correlation_id != event.correlation_id or event.created_at is None:
                raise BetaAcceptanceError("beta acceptance failed")
            if (
                event.created_at.tzinfo is None
                or event.created_at.astimezone(UTC) > observed_at + _WORKER_AUDIT_CLOCK_BOUND
            ):
                raise BetaAcceptanceError("beta acceptance failed")
            correlation_ids.add(correlation_id)
        _reject_acceptance_if(
            len(correlation_ids) != 3,
            len(linked_events) != 3,
            opened.box_id != box_id,
            opened.aggregate_type != "ticket",
            opened.aggregate_id != ticket.id,
            opened.event_type != "ticket.opened",
            opened.actor_principal_id != initiator.id,
            opened.initiated_by_principal_id != initiator.id,
            opened.approved_by_principal_id is not None,
            opened.action_revision_id != revision.id,
            opened.payload_hash != revision.payload_hash,
            opened.policy_version != revision.policy_version,
            opened.charter_version != revision.charter_version,
            opened.config_version != revision.config_version,
            opened.outcome != "pending_approval",
            opened.detail != {},
            approved.box_id != box_id,
            approved.aggregate_type != "ticket",
            approved.aggregate_id != ticket.id,
            approved.event_type != "decision.approved",
            approved.actor_principal_id != decision.actor_principal_id,
            approved.initiated_by_principal_id is not None,
            approved.approved_by_principal_id != decision.actor_principal_id,
            approved.action_revision_id != revision.id,
            approved.payload_hash != revision.payload_hash,
            approved.policy_version != revision.policy_version,
            approved.charter_version != revision.charter_version,
            approved.config_version != revision.config_version,
            approved.outcome != "approved",
            approved.detail != {"operation_bound": True},
        )
        _reject_acceptance_if(
            succeeded.box_id != box_id,
            succeeded.aggregate_type != "operation",
            succeeded.aggregate_id != operation.id,
            succeeded.event_type != "operation.succeeded",
            succeeded.actor_principal_id is not None,
            succeeded.initiated_by_principal_id is not None,
            succeeded.approved_by_principal_id is not None,
            succeeded.action_revision_id != revision.id,
            succeeded.payload_hash != revision.payload_hash,
            succeeded.policy_version is not None,
            succeeded.charter_version is not None,
            succeeded.config_version is not None,
            succeeded.outcome != "succeeded",
            succeeded.detail != {"external_reference": expected_reference},
            not (
                ticket.created_at
                <= revision.created_at
                <= decision.created_at
                <= operation.created_at
            ),
            not (operation.started_at <= operation.completed_at <= succeeded.created_at),
            # Ticket/revision/decision/operation creation use PostgreSQL's
            # transaction clock. Link/worker/audit timestamps use the
            # application clock. Preserve strict same-clock order above and
            # permit only this bounded inversion at each causal clock edge.
            patient_link.attested_at > ticket.created_at + _WORKER_AUDIT_CLOCK_BOUND,
            patient_link.attested_at < opened.created_at - _WORKER_AUDIT_CLOCK_BOUND,
            patient_link.attested_at > opened.created_at + _WORKER_AUDIT_CLOCK_BOUND,
            revision.created_at > opened.created_at + _WORKER_AUDIT_CLOCK_BOUND,
            opened.created_at > decision.created_at + _WORKER_AUDIT_CLOCK_BOUND,
            abs((approved.created_at - operation.created_at).total_seconds())
            > _WORKER_AUDIT_CLOCK_BOUND.total_seconds(),
            approved.created_at > operation.started_at + _WORKER_AUDIT_CLOCK_BOUND,
            operation.started_at < operation.created_at - _WORKER_AUDIT_CLOCK_BOUND,
        )

        container = svc.Container(session)
        timeline = svc.audit_timeline(container, box_id, ticket.id)
        allowed_fields = {
            "event_type",
            "actor_principal_id",
            "approved_by_principal_id",
            "action_revision_id",
            "payload_hash",
            "outcome",
            "created_at",
        }
        if not timeline or any(set(item) != allowed_fields for item in timeline):
            raise BetaAcceptanceError("beta acceptance failed")
        expected_event_outcomes = {
            "ticket.opened": "pending_approval",
            "decision.approved": "approved",
            "operation.succeeded": "succeeded",
        }
        timeline_timestamps: list[datetime] = []
        for item in timeline:
            event_type = item["event_type"]
            if (
                event_type not in expected_event_outcomes
                or item["outcome"] != expected_event_outcomes[event_type]
                or item["created_at"] is None
            ):
                raise BetaAcceptanceError("beta acceptance failed")
            try:
                created_at = datetime.fromisoformat(str(item["created_at"]).replace("Z", "+00:00"))
            except ValueError:
                raise BetaAcceptanceError("beta acceptance failed") from None
            if created_at.tzinfo is None:
                raise BetaAcceptanceError("beta acceptance failed")
            timeline_timestamps.append(created_at.astimezone(UTC))
            for key in (
                "actor_principal_id",
                "approved_by_principal_id",
                "action_revision_id",
            ):
                value = item[key]
                if value is not None and str(UUID(str(value))) != value:
                    raise BetaAcceptanceError("beta acceptance failed")
            value = item["payload_hash"]
            if value is not None and not re.fullmatch(_HANDLE_PATTERN, str(value)):
                raise BetaAcceptanceError("beta acceptance failed")
        if timeline_timestamps != sorted(timeline_timestamps):
            raise BetaAcceptanceError("beta acceptance failed")
        event_types = [str(item["event_type"]) for item in timeline]
        if (
            event_types != ["ticket.opened", "decision.approved", "operation.succeeded"]
            or len(timeline) != 3
        ):
            raise BetaAcceptanceError("beta acceptance failed")
        expected_timeline = [
            {
                "event_type": event.event_type,
                "actor_principal_id": event.actor_principal_id,
                "approved_by_principal_id": event.approved_by_principal_id,
                "action_revision_id": event.action_revision_id,
                "payload_hash": event.payload_hash,
                "outcome": event.outcome,
                "created_at": event.created_at.isoformat(),
            }
            for event in (opened, approved, succeeded)
        ]
        if timeline != expected_timeline:
            raise BetaAcceptanceError("beta acceptance failed")

        alternate_box = str(UUID(int=UUID(box_id).int ^ 1))
        try:
            svc.audit_timeline(container, alternate_box, ticket.id)
        except AuthorizationError:
            pass
        else:
            raise BetaAcceptanceError("beta acceptance failed")

        return AuditReplayEvidence(
            contract=AUDIT_REPLAY_CONTRACT,
            stage="live_replay",
            status="verified",
            completed_at=_utc_timestamp(_database_now(session)),
            box_scope_enforced=True,
            cross_box_replay_denied=True,
            ticket_timeline_replayed=True,
            operation_events_linked=True,
            required_event_order_verified=True,
            no_content_fields_returned=True,
            timeline_event_count=len(timeline),
            identifiers_returned=False,
            content_returned=False,
        )
    except BetaAcceptanceError:
        raise
    except Exception:
        raise BetaAcceptanceError("beta acceptance failed") from None


def _make_blob_adapter(runtime: Settings, client_id: str) -> AzureBlobAdapter:
    if (
        not runtime.azure_storage_account_url
        or not runtime.azure_blob_container
        or not runtime.beta_box_id
    ):
        raise BetaAcceptanceError("beta acceptance failed")
    return AzureBlobAdapter.from_user_assigned_managed_identity(
        account_url=runtime.azure_storage_account_url,
        container_name=runtime.azure_blob_container,
        box_id=runtime.beta_box_id,
        client_id=client_id,
    )


def _purge_blob_key(box_id: str, artifact_id: str) -> str:
    return f"{box_id}/purge-acceptance/{artifact_id}.bin"


def _due_unpurged_artifacts(session: Session, box_id: str, now: datetime) -> list[Artifact]:
    cutoff = now - timedelta(days=_PURGE_RETAIN_DAYS)
    return list(
        session.scalars(
            select(Artifact)
            .join(Ticket, Ticket.id == Artifact.ticket_id)
            .where(
                Artifact.box_id == box_id,
                Artifact.purged_at.is_(None),
                Ticket.box_id == box_id,
                Ticket.state == TicketState.CLOSED.value,
                Ticket.closed_at.is_not(None),
                Ticket.closed_at <= cutoff,
            )
        ).all()
    )


def _purge_audits(session: Session, artifact: Artifact) -> list[AuditEvent]:
    return list(
        session.scalars(
            select(AuditEvent).where(
                AuditEvent.box_id == artifact.box_id,
                AuditEvent.aggregate_type == "artifact",
                AuditEvent.aggregate_id == artifact.id,
                AuditEvent.event_type == "artifact.purged",
            )
        ).all()
    )


def prepare_beta_purge_acceptance(
    session: Session,
    runtime: Settings,
    hmac_key: bytes,
    *,
    managed_identity_client_id: str | None,
    expected_managed_identity_client_id: str | None,
    blob: BlobPort | None = None,
) -> PurgeSetupState:
    """Prepare one due, invented artifact for a normal authenticated purge call."""

    actual_blob = blob
    created_blob_key: str | None = None
    try:
        _require_hmac_key(hmac_key)
        box_id = _validate_runtime(runtime, require_blob=True)
        client_id = _validate_exact_runtime_identity(
            managed_identity_client_id,
            expected_managed_identity_client_id,
        )
        if actual_blob is None:
            actual_blob = _make_blob_adapter(runtime, client_id)
        observed_at = _database_now(session)
        existing = list(
            session.scalars(
                select(Artifact).where(
                    Artifact.box_id == box_id,
                    Artifact.classification == _PURGE_CLASSIFICATION,
                    Artifact.purged_at.is_(None),
                )
            ).all()
        )
        due_before = _due_unpurged_artifacts(session, box_id, observed_at)
        if len(existing) > 1 or any(
            art.classification != _PURGE_CLASSIFICATION for art in due_before
        ):
            raise BetaAcceptanceError("beta acceptance failed")

        if existing:
            artifact = existing[0]
            if due_before != [artifact] or artifact.blob_key != _purge_blob_key(
                box_id, artifact.id
            ):
                raise BetaAcceptanceError("beta acceptance failed")
        else:
            if due_before:
                raise BetaAcceptanceError("beta acceptance failed")
            chasers = list(
                session.scalars(
                    select(Principal).where(
                        Principal.box_id == box_id,
                        Principal.principal_type == PrincipalType.AGENT.value,
                        Principal.agent_key == "chaser",
                        Principal.state == PrincipalState.ACTIVE.value,
                    )
                ).all()
            )
            if len(chasers) != 1:
                raise BetaAcceptanceError("beta acceptance failed")
            ticket = Ticket(
                box_id=box_id,
                lane="artifact_chase",
                state=TicketState.CLOSED.value,
                created_by_principal_id=chasers[0].id,
                closed_at=observed_at - timedelta(days=_PURGE_RETAIN_DAYS + 1),
            )
            session.add(ticket)
            session.flush()
            artifact = Artifact(
                box_id=box_id,
                ticket_id=ticket.id,
                classification=_PURGE_CLASSIFICATION,
                side="front",
                content_type=_PURGE_CONTENT_TYPE,
            )
            session.add(artifact)
            session.flush()
            created_blob_key = _purge_blob_key(box_id, artifact.id)
            stored_name = actual_blob.put_bytes(
                created_blob_key,
                _PURGE_CONTENT,
                _PURGE_CONTENT_TYPE,
            )
            if stored_name != created_blob_key:
                raise BetaAcceptanceError("beta acceptance failed")
            artifact.blob_key = created_blob_key
            session.add(
                AuditEvent(
                    box_id=box_id,
                    aggregate_type="artifact",
                    aggregate_id=artifact.id,
                    event_type="acceptance.purge_probe_prepared",
                    correlation_id=str(uuid4()),
                    outcome="synthetic",
                    detail={"classification": _PURGE_CLASSIFICATION},
                    created_at=observed_at,
                )
            )
            session.commit()
            created_blob_key = None

        if actual_blob.get_bytes(_purge_blob_key(box_id, artifact.id)) != _PURGE_CONTENT:
            raise BetaAcceptanceError("beta acceptance failed")
        if len(_due_unpurged_artifacts(session, box_id, observed_at)) != 1:
            raise BetaAcceptanceError("beta acceptance failed")
        if _purge_audits(session, artifact):
            raise BetaAcceptanceError("beta acceptance failed")

        payload = {
            "contract": PURGE_ACCEPTANCE_CONTRACT,
            "stage": "setup",
            "status": "ready_for_browser",
            "issued_at": _utc_timestamp(observed_at),
            "expires_at": _utc_timestamp(observed_at + _STATE_LIFETIME),
            "artifact_handle": _opaque_handle(hmac_key, "purge-artifact", box_id, artifact.id),
            "due_unpurged_artifact_count": 1,
            "purge_audit_count": 0,
            "blob_current_representation_readable": True,
        }
        return PurgeSetupState.model_validate(_signed_state_payload(payload, hmac_key))
    except BetaAcceptanceError:
        session.rollback()
        if created_blob_key is not None and actual_blob is not None:
            try:
                actual_blob.delete(created_blob_key)
            except Exception:
                pass
        raise
    except Exception:
        session.rollback()
        if created_blob_key is not None and actual_blob is not None:
            try:
                actual_blob.delete(created_blob_key)
            except Exception:
                pass
        raise BetaAcceptanceError("beta acceptance failed") from None


def _default_blob_not_found(error: Exception) -> bool:
    return isinstance(error, (FileNotFoundError, ResourceNotFoundError))


def _parse_purge_state(state_json: str, key: bytes, now: datetime) -> PurgeSetupState:
    try:
        state = PurgeSetupState.model_validate_json(state_json)
    except (ValidationError, ValueError):
        raise BetaAcceptanceError("beta acceptance failed") from None
    _validate_signed_state(state, key, now)
    return state


def verify_beta_purge_acceptance(
    session: Session,
    runtime: Settings,
    state_json: str,
    hmac_key: bytes,
    *,
    managed_identity_client_id: str | None,
    expected_managed_identity_client_id: str | None,
    blob: BlobPort | None = None,
    blob_not_found: Callable[[Exception], bool] = _default_blob_not_found,
) -> PurgeAcceptanceEvidence:
    """Verify the application tombstone and exact-key recoverable Blob absence."""

    try:
        _require_hmac_key(hmac_key)
        box_id = _validate_runtime(runtime, require_blob=True)
        client_id = _validate_exact_runtime_identity(
            managed_identity_client_id,
            expected_managed_identity_client_id,
        )
        actual_blob = blob or _make_blob_adapter(runtime, client_id)
        observed_at = _database_now(session)
        state = _parse_purge_state(state_json, hmac_key, observed_at)
        candidates = list(
            session.scalars(
                select(Artifact).where(
                    Artifact.box_id == box_id,
                    Artifact.classification == _PURGE_CLASSIFICATION,
                )
            ).all()
        )
        matches = [
            artifact
            for artifact in candidates
            if hmac.compare_digest(
                _opaque_handle(hmac_key, "purge-artifact", box_id, artifact.id),
                state.artifact_handle,
            )
        ]
        if len(matches) != 1:
            raise BetaAcceptanceError("beta acceptance failed")
        artifact = matches[0]
        ticket = session.get(Ticket, artifact.ticket_id)
        audits = _purge_audits(session, artifact)
        receipt = artifact.purge_receipt
        purge_actor = (
            session.get(Principal, audits[0].actor_principal_id)
            if len(audits) == 1 and audits[0].actor_principal_id is not None
            else None
        )
        if (
            ticket is None
            or ticket.box_id != box_id
            or ticket.state != TicketState.CLOSED.value
            or artifact.blob_key is not None
            or artifact.purged_at is None
            or not isinstance(receipt, dict)
            or receipt.get("artifact_id") != artifact.id
            or receipt.get("retention_rule") != f"closed_plus_{_PURGE_RETAIN_DAYS}d"
            or receipt.get("outcome") != "purged"
            or not _timestamp_matches(receipt.get("deleted_at"), artifact.purged_at)
            or len(audits) - state.purge_audit_count != 1
            or audits[0].outcome != "purged"
            or audits[0].detail
            != {
                "retention_rule": f"closed_plus_{_PURGE_RETAIN_DAYS}d",
                "owner_authorized": True,
            }
            or purge_actor is None
            or purge_actor.box_id != box_id
            or purge_actor.principal_type != PrincipalType.HUMAN.value
            or purge_actor.state != PrincipalState.ACTIVE.value
            or not purge_actor.is_owner
        ):
            raise BetaAcceptanceError("beta acceptance failed")

        blob_key = _purge_blob_key(box_id, artifact.id)
        try:
            actual_blob.get_bytes(blob_key)
        except Exception as error:  # noqa: BLE001 - provider absence is explicitly normalized
            if not blob_not_found(error):
                raise BetaAcceptanceError("beta acceptance failed") from None
        else:
            raise BetaAcceptanceError("beta acceptance failed")

        absence = actual_blob.probe_recoverable_absence(blob_key)
        if not absence.verified:
            raise BetaAcceptanceError("beta acceptance failed")

        due_probe_count = len(
            [
                item
                for item in _due_unpurged_artifacts(session, box_id, observed_at)
                if item.classification == _PURGE_CLASSIFICATION
            ]
        )
        if due_probe_count != 0:
            raise BetaAcceptanceError("beta acceptance failed")

        return PurgeAcceptanceEvidence(
            contract=PURGE_ACCEPTANCE_CONTRACT,
            stage="post_browser",
            status="verified",
            completed_at=_utc_timestamp(observed_at),
            state_bound=True,
            owner_authorized_purge_observed=True,
            owner_authority_verified=True,
            application_tombstone_verified=True,
            purge_receipt_verified=True,
            purge_audit_delta=1,
            blob_current_representation_absent=absence.current_absent,
            blob_version_representations_absent=absence.versions_absent,
            blob_snapshot_representations_absent=absence.snapshots_absent,
            blob_deleted_representations_absent=absence.deleted_absent,
            blob_recoverable_absence_verified=absence.verified,
            due_unpurged_probe_count=0,
        )
    except BetaAcceptanceError:
        raise
    except Exception:
        raise BetaAcceptanceError("beta acceptance failed") from None
