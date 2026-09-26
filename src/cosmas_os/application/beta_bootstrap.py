from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cosmas_os.config import Settings
from cosmas_os.domain.enums import (
    AutomationClass,
    CoverageStatus,
    PrincipalState,
    PrincipalType,
    TicketState,
)
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.models import (
    ActionRevision,
    AppointmentObservation,
    Artifact,
    AuditEvent,
    BoxContext,
    CapabilityConfig,
    Decision,
    ExternalIdentity,
    Operation,
    PatientLink,
    Principal,
    Ticket,
)

BOOTSTRAP_READBACK_CONTRACT = "cosmas-os-d3-beta-bootstrap-readback-v1"

_BASELINE_AGENT_DISPLAY_NAMES = {
    "scribe": "Scribe",
    "chief": "Chief",
    "chaser": "Chaser",
}
_BASELINE_POLICY_VERSION = "policy-v1"
_BASELINE_CHARTER_VERSION = "charter-v1"
_BASELINE_CONFIG_VERSION = "config-v1"
_APPLICATION_DATABASE_CLOCK_BOUND = timedelta(seconds=5)


def _database_now(session: Session) -> datetime:
    observed = session.scalar(select(func.clock_timestamp()))
    if not isinstance(observed, datetime):
        raise BetaBootstrapError("beta bootstrap readback differs from reviewed state")
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=UTC)
    return observed.astimezone(UTC)


class BetaBootstrapError(Exception):
    """A reviewed beta identity bootstrap cannot safely proceed."""


@dataclass(frozen=True)
class BetaBootstrapReadbackEvidence:
    contract: str
    status: str
    box_count: int
    active_owner_count: int
    active_baseline_agent_count: int
    clerk_binding_count: int
    clerk_binding_audit_count: int
    appointment_observation_count: int
    patient_link_count: int
    pending_ticket_count: int
    total_ticket_count: int
    action_revision_count: int
    decision_count: int
    operation_count: int
    artifact_count: int
    capability_config_count: int
    audit_event_count: int
    reviewed_manifest_matched: bool
    identifiers_returned: bool

    def sanitized_json(self) -> str:
        payload: dict[str, Any] = asdict(self)
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        payload["evidence_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))


class BetaBootstrapManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["cosmas-os/d3-beta-bootstrap/v1"]
    box_id: UUID
    clinic_display_name: str = Field(min_length=1, max_length=200)
    owner_display_name: str = Field(min_length=1, max_length=200)
    clerk_issuer: str = Field(min_length=1, max_length=255)
    clerk_subject: str = Field(min_length=1, max_length=255)
    clerk_organization_id: str = Field(min_length=1, max_length=255)
    reviewed_by: str = Field(min_length=1, max_length=200)
    evidence_ref: str = Field(min_length=1, max_length=255)

    @field_validator("box_id", mode="before")
    @classmethod
    def require_canonical_box_uuid(cls, value: object) -> object:
        if not isinstance(value, str):
            raise ValueError("Box ID must be a canonical UUID string")
        try:
            if str(UUID(value)) != value:
                raise ValueError("Box ID must be a canonical UUID string")
        except ValueError:
            raise ValueError("Box ID must be a canonical UUID string") from None
        return value

    @field_validator(
        "clinic_display_name",
        "owner_display_name",
        "clerk_issuer",
        "clerk_subject",
        "clerk_organization_id",
        "reviewed_by",
        "evidence_ref",
    )
    @classmethod
    def reject_surrounding_or_empty_whitespace(cls, value: str) -> str:
        if (
            not value.strip()
            or value != value.strip()
            or any(character in value for character in "\r\n\x00")
        ):
            raise ValueError("value must be non-empty without surrounding whitespace")
        return value

    @field_validator("clerk_subject")
    @classmethod
    def require_clerk_user_subject(cls, value: str) -> str:
        if not value.startswith("user_"):
            raise ValueError("Clerk subject must start with user_")
        return value

    @field_validator("clerk_organization_id")
    @classmethod
    def require_clerk_org(cls, value: str) -> str:
        if not value.startswith("org_"):
            raise ValueError("Clerk Organization ID must start with org_")
        return value


def _matches_runtime(manifest: BetaBootstrapManifest, runtime: Settings) -> bool:
    try:
        configured_box_id = UUID(runtime.beta_box_id or "")
    except ValueError:
        return False
    return (
        manifest.box_id == configured_box_id
        and manifest.clerk_issuer == runtime.clerk_issuer
        and manifest.clerk_organization_id == runtime.clerk_organization_id
        and manifest.evidence_ref == runtime.human_deploy_evidence_ref
    )


def _is_canonical_uuid(value: str | None) -> bool:
    if value is None:
        return False
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def bootstrap_beta_identity(
    session: Session,
    runtime: Settings,
    manifest: BetaBootstrapManifest,
) -> None:
    """Provision the first Box and reviewed Clerk binding in a dedicated empty DB."""

    runtime.validate_runtime_configuration()
    if runtime.cosmas_env != "early_adopter_beta" or not _matches_runtime(manifest, runtime):
        raise BetaBootstrapError("bootstrap manifest does not match the reviewed runtime")

    box_id = str(manifest.box_id)
    box_count = session.scalar(select(func.count()).select_from(BoxContext)) or 0
    existing_box = session.get(BoxContext, box_id)
    existing_binding = session.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.issuer == manifest.clerk_issuer,
            ExternalIdentity.subject == manifest.clerk_subject,
        )
    )
    if box_count or existing_binding:
        existing_owner = (
            session.get(Principal, existing_binding.principal_id)
            if existing_binding is not None
            else None
        )
        if (
            box_count == 1
            and existing_box
            and existing_binding
            and existing_box.id == box_id
            and existing_box.display_name == manifest.clinic_display_name
            and existing_binding.box_id == box_id
            and existing_binding.organization_id == manifest.clerk_organization_id
            and existing_binding.reviewed_by == manifest.reviewed_by
            and existing_binding.evidence_ref == manifest.evidence_ref
            and existing_binding.active
            and existing_owner is not None
            and existing_owner.box_id == box_id
            and existing_owner.principal_type == PrincipalType.HUMAN.value
            and existing_owner.state == PrincipalState.ACTIVE.value
            and existing_owner.is_owner
            and existing_owner.display_name == manifest.owner_display_name
        ):
            return
        raise BetaBootstrapError("dedicated beta database is not empty or already differs")

    try:
        box = BoxContext(id=box_id, display_name=manifest.clinic_display_name)
        session.add(box)
        session.flush()

        owner = Principal(
            box_id=box_id,
            principal_type=PrincipalType.HUMAN.value,
            display_name=manifest.owner_display_name,
            is_owner=True,
            state=PrincipalState.ACTIVE.value,
        )
        session.add(owner)
        session.flush()

        for agent_key, display_name in (
            ("scribe", "Scribe"),
            ("chief", "Chief"),
            ("chaser", "Chaser"),
        ):
            session.add(
                Principal(
                    box_id=box_id,
                    principal_type=PrincipalType.AGENT.value,
                    display_name=display_name,
                    agent_key=agent_key,
                    is_owner=False,
                    state=PrincipalState.ACTIVE.value,
                )
            )

        binding = ExternalIdentity(
            box_id=box_id,
            principal_id=owner.id,
            provider="clerk",
            issuer=manifest.clerk_issuer,
            subject=manifest.clerk_subject,
            organization_id=manifest.clerk_organization_id,
            active=True,
            reviewed_by=manifest.reviewed_by,
            evidence_ref=manifest.evidence_ref,
        )
        session.add(binding)
        session.flush()
        session.add(
            AuditEvent(
                box_id=box_id,
                aggregate_type="external_identity",
                aggregate_id=binding.id,
                event_type="external_identity.bound",
                actor_principal_id=owner.id,
                correlation_id=str(uuid4()),
                outcome="reviewed",
                detail={"provider": "clerk", "human_deploy": True},
            )
        )
        session.commit()
    except Exception:
        session.rollback()
        raise


def seed_beta_synthetic_queue(session: Session, runtime: Settings) -> None:
    """Load only the repository's fixed synthetic chase into a reviewed beta Box."""

    from cosmas_os.application import services as svc
    from cosmas_os.application.seed import SYNTH_CSV

    runtime.validate_runtime_configuration()
    if runtime.cosmas_env != "early_adopter_beta" or runtime.data_mode != "synthetic":
        raise BetaBootstrapError("synthetic beta seed is unavailable in this data mode")
    box_id = runtime.beta_box_id
    if not box_id:
        raise BetaBootstrapError("beta Box is not configured")

    box_count = session.scalar(select(func.count()).select_from(BoxContext)) or 0
    box = session.get(BoxContext, box_id)
    owner = session.scalar(
        select(Principal).where(
            Principal.box_id == box_id,
            Principal.principal_type == PrincipalType.HUMAN.value,
            Principal.is_owner.is_(True),
            Principal.state == PrincipalState.ACTIVE.value,
        )
    )
    chaser = session.scalar(
        select(Principal).where(
            Principal.box_id == box_id,
            Principal.principal_type == PrincipalType.AGENT.value,
            Principal.agent_key == "chaser",
            Principal.state == PrincipalState.ACTIVE.value,
        )
    )
    binding = session.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.box_id == box_id,
            ExternalIdentity.organization_id == runtime.clerk_organization_id,
            ExternalIdentity.active.is_(True),
        )
    )
    if box_count != 1 or not box or not owner or not chaser or not binding:
        raise BetaBootstrapError("reviewed beta identity bootstrap is incomplete")

    pending = session.scalar(
        select(Ticket).where(
            Ticket.box_id == box_id,
            Ticket.state == "pending_approval",
        )
    )
    if pending:
        return

    c = svc.Container(session)
    appointment = session.scalar(
        select(AppointmentObservation).where(
            AppointmentObservation.box_id == box_id,
            AppointmentObservation.external_id == "appt-1001",
        )
    )
    appointment_id = appointment.id if appointment else svc.import_schedule(c, box_id, SYNTH_CSV)[0]
    link = svc.attest_patient_link(
        c,
        box_id,
        owner.id,
        source_pair_key="csv:jordan-lee",
        label="Jordan Lee",
    )
    svc.detect_and_open_chase(c, box_id, chaser.id, appointment_id, link.id)


def verify_beta_bootstrap_state(
    session: Session,
    runtime: Settings,
    manifest: BetaBootstrapManifest,
) -> BetaBootstrapReadbackEvidence:
    """Return a stable, identifier-free readback of the exact bootstrap result."""

    runtime.validate_runtime_configuration()
    if runtime.cosmas_env != "early_adopter_beta" or not _matches_runtime(manifest, runtime):
        raise BetaBootstrapError("bootstrap manifest does not match the reviewed runtime")
    box_id = str(manifest.box_id)
    observed_at = _database_now(session)
    boxes = list(session.scalars(select(BoxContext)).all())
    principals = list(session.scalars(select(Principal)).all())
    owners = [
        principal
        for principal in principals
        if principal.principal_type == PrincipalType.HUMAN.value
        and principal.state == PrincipalState.ACTIVE.value
        and principal.is_owner
        and principal.display_name == manifest.owner_display_name
    ]
    agents = [
        principal
        for principal in principals
        if principal.principal_type == PrincipalType.AGENT.value
        and principal.state == PrincipalState.ACTIVE.value
        and not principal.is_owner
        and principal.agent_key in {"scribe", "chief", "chaser"}
    ]
    owner_defaults_match = len(owners) == 1 and (
        owners[0].box_id == box_id
        and owners[0].agent_key is None
        and owners[0].policy_version == _BASELINE_POLICY_VERSION
        and owners[0].charter_version == _BASELINE_CHARTER_VERSION
        and owners[0].config_version == _BASELINE_CONFIG_VERSION
        and owners[0].tombstoned_at is None
    )
    agents_by_key = {agent.agent_key: agent for agent in agents if agent.agent_key is not None}
    agent_defaults_match = len(agents_by_key) == len(_BASELINE_AGENT_DISPLAY_NAMES) and all(
        agent_key in agents_by_key
        and agents_by_key[agent_key].box_id == box_id
        and agents_by_key[agent_key].display_name == expected_display_name
        and agents_by_key[agent_key].policy_version == _BASELINE_POLICY_VERSION
        and agents_by_key[agent_key].charter_version == _BASELINE_CHARTER_VERSION
        and agents_by_key[agent_key].config_version == _BASELINE_CONFIG_VERSION
        and agents_by_key[agent_key].tombstoned_at is None
        for agent_key, expected_display_name in _BASELINE_AGENT_DISPLAY_NAMES.items()
    )
    bindings = list(session.scalars(select(ExternalIdentity)).all())
    binding_audits = []
    if len(bindings) == 1:
        binding_audits = list(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.box_id == box_id,
                    AuditEvent.aggregate_type == "external_identity",
                    AuditEvent.aggregate_id == bindings[0].id,
                    AuditEvent.event_type == "external_identity.bound",
                )
            ).all()
        )
    appointments = list(session.scalars(select(AppointmentObservation)).all())
    patient_links = list(session.scalars(select(PatientLink)).all())
    tickets = list(session.scalars(select(Ticket)).all())
    revisions = list(session.scalars(select(ActionRevision)).all())
    decisions = list(session.scalars(select(Decision)).all())
    operations = list(session.scalars(select(Operation)).all())
    artifacts = list(session.scalars(select(Artifact)).all())
    capability_configs = list(session.scalars(select(CapabilityConfig)).all())
    audit_events = list(session.scalars(select(AuditEvent)).all())
    pending_tickets = [
        ticket for ticket in tickets if ticket.state == TicketState.PENDING_APPROVAL.value
    ]
    appointment_by_external_id = {
        appointment.external_id: appointment for appointment in appointments
    }
    expected_appointments = {
        "appt-1001": (datetime(2026, 9, 10, 15, 0, tzinfo=UTC), "Jordan Lee"),
        "appt-1002": (datetime(2026, 9, 11, 16, 30, tzinfo=UTC), "Riley Quinn"),
    }
    appointments_match = len(appointment_by_external_id) == 2
    for external_id, (start_at, patient_label) in expected_appointments.items():
        appointment = appointment_by_external_id.get(external_id)
        appointments_match = appointments_match and appointment is not None
        if appointment is not None:
            appointments_match = appointments_match and (
                appointment.box_id == box_id
                and appointment.source == "csv"
                and appointment.start_at is not None
                and appointment.start_at.astimezone(UTC) == start_at
                and appointment.patient_label == patient_label
                and appointment.coverage_status == CoverageStatus.MISSING.value
            )

    relationship_matches = False
    audit_relationships_match = False
    chronology_matches = False
    if (
        len(boxes) == 1
        and len(patient_links) == len(tickets) == len(revisions) == 1
        and len(agents) == 3
        and len(owners) == 1
        and len(bindings) == 1
    ):
        link = patient_links[0]
        ticket = tickets[0]
        revision = revisions[0]
        chaser = next((agent for agent in agents if agent.agent_key == "chaser"), None)
        expected_chaser_id = chaser.id if chaser is not None else None
        first_appointment = appointment_by_external_id.get("appt-1001")
        second_appointment = appointment_by_external_id.get("appt-1002")
        expected_payload = {
            "action": "notify.patient_insurance_request",
            "channel": "fake_secure_link",
            "body": (
                "Please use the secure link to share insurance information before your visit. "
                "This message contains no clinical details."
            ),
            "target_ref": f"patient_link:{link.id}",
            "appointment_ref": "appt-1001",
        }
        relationship_matches = (
            chaser is not None
            and link.box_id == box_id
            and link.source_pair_key == "csv:jordan-lee"
            and link.label == "Jordan Lee"
            and link.confirmed_by_principal_id == owners[0].id
            and link.attested_at is not None
            and link.revoked_at is None
            and link.state == "confirmed"
            and first_appointment is not None
            and first_appointment.patient_link_id == link.id
            and second_appointment is not None
            and second_appointment.patient_link_id is None
            and ticket.box_id == box_id
            and ticket.lane == "artifact_chase"
            and ticket.state == TicketState.PENDING_APPROVAL.value
            and ticket.version == 1
            and ticket.created_by_principal_id == chaser.id
            and ticket.appointment_id == first_appointment.id
            and ticket.patient_link_id == link.id
            and ticket.current_revision_id == revision.id
            and ticket.closed_at is None
            and revision.ticket_id == ticket.id
            and revision.box_id == box_id
            and revision.revision_number == 1
            and revision.action_type == "notify.patient_insurance_request"
            and revision.target_ref == f"patient_link:{link.id}"
            and revision.content == expected_payload["body"]
            and revision.payload == expected_payload
            and revision.payload_hash == payload_hash(expected_payload)
            and revision.automation_class == AutomationClass.HITL_REQUIRED.value
            and revision.policy_version == chaser.policy_version
            and revision.charter_version == chaser.charter_version
            and revision.config_version == chaser.config_version
            and revision.created_by_principal_id == chaser.id
            and not revision.invalidated
        )
        audits_by_type = {event.event_type: event for event in audit_events}
        if len(audits_by_type) == len(audit_events) == 3:
            binding_audit = audits_by_type.get("external_identity.bound")
            link_audit = audits_by_type.get("patient_link.attested")
            ticket_audit = audits_by_type.get("ticket.opened")
            correlation_ids = {
                event.correlation_id
                for event in audit_events
                if _is_canonical_uuid(event.correlation_id)
            }
            audit_relationships_match = (
                binding_audit is not None
                and link_audit is not None
                and ticket_audit is not None
                and len(correlation_ids) == 3
                and all(_is_canonical_uuid(event.id) for event in audit_events)
                and all(event.created_at is not None for event in audit_events)
                and binding_audit.box_id == box_id
                and binding_audit.aggregate_type == "external_identity"
                and binding_audit.aggregate_id == bindings[0].id
                and binding_audit.actor_principal_id == owners[0].id
                and binding_audit.initiated_by_principal_id is None
                and binding_audit.approved_by_principal_id is None
                and binding_audit.action_revision_id is None
                and binding_audit.payload_hash is None
                and binding_audit.policy_version is None
                and binding_audit.charter_version is None
                and binding_audit.config_version is None
                and binding_audit.outcome == "reviewed"
                and binding_audit.detail == {"provider": "clerk", "human_deploy": True}
                and link_audit.box_id == box_id
                and link_audit.aggregate_type == "patient_link"
                and link_audit.aggregate_id == link.id
                and link_audit.actor_principal_id == owners[0].id
                and link_audit.initiated_by_principal_id is None
                and link_audit.approved_by_principal_id is None
                and link_audit.action_revision_id is None
                and link_audit.payload_hash is None
                and link_audit.policy_version is None
                and link_audit.charter_version is None
                and link_audit.config_version is None
                and link_audit.outcome == "ok"
                and link_audit.detail == {}
                and ticket_audit.box_id == box_id
                and ticket_audit.aggregate_type == "ticket"
                and ticket_audit.aggregate_id == ticket.id
                and ticket_audit.actor_principal_id == expected_chaser_id
                and ticket_audit.initiated_by_principal_id == expected_chaser_id
                and ticket_audit.approved_by_principal_id is None
                and ticket_audit.action_revision_id == revision.id
                and ticket_audit.payload_hash == revision.payload_hash
                and ticket_audit.policy_version == revision.policy_version
                and ticket_audit.charter_version == revision.charter_version
                and ticket_audit.config_version == revision.config_version
                and ticket_audit.outcome == "pending_approval"
                and ticket_audit.detail == {}
            )
            binding_audit_at = binding_audit.created_at if binding_audit is not None else None
            link_audit_at = link_audit.created_at if link_audit is not None else None
            ticket_audit_at = ticket_audit.created_at if ticket_audit is not None else None
            database_timestamps = [
                boxes[0].created_at,
                *(principal.created_at for principal in principals),
                bindings[0].created_at,
                ticket.created_at,
                revision.created_at,
                binding_audit_at,
            ]
            chronology_matches = (
                all(
                    timestamp is not None
                    and timestamp.tzinfo is not None
                    and timestamp.astimezone(UTC) <= observed_at
                    for timestamp in database_timestamps
                )
                and link.attested_at is not None
                and link.attested_at.tzinfo is not None
                and link.attested_at.astimezone(UTC)
                <= observed_at + _APPLICATION_DATABASE_CLOCK_BOUND
                and binding_audit_at is not None
                and link_audit_at is not None
                and ticket_audit_at is not None
                and all(
                    timestamp.tzinfo is not None
                    and timestamp.astimezone(UTC) <= observed_at + _APPLICATION_DATABASE_CLOCK_BOUND
                    for timestamp in (link.attested_at, link_audit_at, ticket_audit_at)
                )
                and boxes[0].created_at <= owners[0].created_at
                and boxes[0].created_at <= min(agent.created_at for agent in agents)
                and owners[0].created_at <= bindings[0].created_at
                and bindings[0].created_at <= binding_audit_at
                and ticket.created_at <= revision.created_at
                # Patient-link and synthetic-ticket audit timestamps are
                # emitted by the application clock. Keep their causal chain
                # strict and independently constrain each cross-clock edge to
                # the documented five-second application/database bound.
                and link.attested_at <= link_audit_at <= ticket_audit_at
                and link.attested_at >= link_audit_at - _APPLICATION_DATABASE_CLOCK_BOUND
                and binding_audit_at <= link.attested_at + _APPLICATION_DATABASE_CLOCK_BOUND
                and link_audit_at <= ticket.created_at + _APPLICATION_DATABASE_CLOCK_BOUND
                and ticket.created_at <= ticket_audit_at + _APPLICATION_DATABASE_CLOCK_BOUND
            )
    if (
        len(boxes) != 1
        or boxes[0].id != box_id
        or boxes[0].display_name != manifest.clinic_display_name
        or len(principals) != 4
        or len(owners) != 1
        or not owner_defaults_match
        or len(agents) != 3
        or {agent.agent_key for agent in agents} != {"scribe", "chief", "chaser"}
        or not agent_defaults_match
        or len(bindings) != 1
        or bindings[0].box_id != box_id
        or bindings[0].provider != "clerk"
        or bindings[0].issuer != manifest.clerk_issuer
        or bindings[0].subject != manifest.clerk_subject
        or bindings[0].organization_id != manifest.clerk_organization_id
        or not bindings[0].active
        or bindings[0].principal_id != owners[0].id
        or bindings[0].reviewed_by != manifest.reviewed_by
        or bindings[0].evidence_ref != manifest.evidence_ref
        or len(binding_audits) != 1
        or binding_audits[0].actor_principal_id != owners[0].id
        or binding_audits[0].outcome != "reviewed"
        or binding_audits[0].detail != {"provider": "clerk", "human_deploy": True}
        or len(appointments) != 2
        or not appointments_match
        or len(patient_links) != 1
        or len(tickets) != 1
        or len(pending_tickets) != 1
        or len(revisions) != 1
        or decisions
        or operations
        or artifacts
        or capability_configs
        or not relationship_matches
        or not audit_relationships_match
        or not chronology_matches
    ):
        raise BetaBootstrapError("beta bootstrap readback differs from reviewed state")
    return BetaBootstrapReadbackEvidence(
        contract=BOOTSTRAP_READBACK_CONTRACT,
        status="verified",
        box_count=len(boxes),
        active_owner_count=len(owners),
        active_baseline_agent_count=len(agents),
        clerk_binding_count=len(bindings),
        clerk_binding_audit_count=len(binding_audits),
        appointment_observation_count=len(appointments),
        patient_link_count=len(patient_links),
        pending_ticket_count=len(pending_tickets),
        total_ticket_count=len(tickets),
        action_revision_count=len(revisions),
        decision_count=len(decisions),
        operation_count=len(operations),
        artifact_count=len(artifacts),
        capability_config_count=len(capability_configs),
        audit_event_count=len(audit_events),
        reviewed_manifest_matched=True,
        identifiers_returned=False,
    )
