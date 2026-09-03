from __future__ import annotations

from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cosmas_os.config import Settings
from cosmas_os.domain.enums import PrincipalState, PrincipalType
from cosmas_os.models import (
    AppointmentObservation,
    AuditEvent,
    BoxContext,
    ExternalIdentity,
    Principal,
    Ticket,
)


class BetaBootstrapError(Exception):
    """A reviewed beta identity bootstrap cannot safely proceed."""


class BetaBootstrapManifest(BaseModel):
    schema_version: Literal["cosmas-os/d3-beta-bootstrap/v1"]
    box_id: UUID
    clinic_display_name: str = Field(min_length=1, max_length=200)
    owner_display_name: str = Field(min_length=1, max_length=200)
    clerk_issuer: str = Field(min_length=1, max_length=255)
    clerk_subject: str = Field(min_length=1, max_length=255)
    clerk_organization_id: str = Field(min_length=1, max_length=255)
    reviewed_by: str = Field(min_length=1, max_length=200)
    evidence_ref: str = Field(min_length=1, max_length=255)

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
        if not value.strip() or value != value.strip():
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
