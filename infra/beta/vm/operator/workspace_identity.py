"""Reviewed staging owner identity alias; preserves the Box, principal and old binding.

Operator-only maintenance tool, never an HTTP endpoint. The deployment wrapper
must fence access and quiesce API/worker processes before applying or reversing.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from cosmas_os.config import Settings
from cosmas_os.models import (
    AuditEvent,
    BoxContext,
    CoreCaptureAccount,
    ExternalIdentity,
    ModelWorkAdmission,
    Principal,
    SchedulingAccount,
)


class Refused(ValueError):
    """Fixed diagnostic only; never print database or credential exceptions."""


class Transition(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    contract: Literal["cosmas-shared-staging-identity-v1"]
    transition_id: str
    box_id: str
    owner_id: str
    source_id: str
    target_id: str
    source_issuer: str = Field(pattern=r"^https://[a-z0-9]+(?:[.-][a-z0-9]+)*$")
    source_subject: str = Field(pattern=r"^user_[A-Za-z0-9_]{1,251}$")
    source_organization: str = Field(pattern=r"^org_[A-Za-z0-9_]{1,251}$")
    target_issuer: str = Field(pattern=r"^https://[a-z0-9]+(?:-[a-z0-9]+)*\.clerk\.accounts\.dev$")
    target_subject: str = Field(pattern=r"^user_[A-Za-z0-9_]{1,251}$")
    target_organization: str = Field(pattern=r"^org_[A-Za-z0-9_]{1,251}$")
    reviewed_by: str = Field(min_length=1, max_length=200)
    evidence_ref: str = Field(min_length=1, max_length=255)
    target_membership_verified: Literal[True]
    expires_at: str

    @field_validator("target_membership_verified", mode="before")
    @classmethod
    def exact_attestation(cls, value):
        if value is not True:
            raise ValueError("explicit membership verification required")
        return value

    @field_validator("transition_id", "box_id", "owner_id", "source_id", "target_id")
    @classmethod
    def canonical_uuid(cls, value):
        if str(UUID(value)) != value:
            raise ValueError("canonical UUID required")
        return value

    @model_validator(mode="after")
    def distinct_identity(self):
        if self.source_id == self.target_id or self.source_issuer == self.target_issuer:
            raise ValueError("distinct identity required")
        return self

    def digest(self):
        # Renewed maintenance may authorize rollback later without rewriting the
        # immutable identity operation or silently extending its original grant.
        return hashlib.sha256(json.dumps(self.model_dump(exclude={"expires_at"}), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def load_plan(raw: str) -> Transition:
    if len(raw.encode()) > 16384:
        raise Refused("manifest_size")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise Refused("duplicate_manifest_field")
            result[key] = value
        return result

    return Transition.model_validate(json.loads(raw, object_pairs_hook=unique))


def _matches(binding, plan, *, target):
    prefix = "target" if target else "source"
    return binding is not None and (
        binding.id == getattr(plan, prefix + "_id")
        and binding.box_id == plan.box_id and binding.principal_id == plan.owner_id
        and binding.provider == "clerk"
        and binding.issuer == getattr(plan, prefix + "_issuer")
        and binding.subject == getattr(plan, prefix + "_subject")
        and binding.organization_id == getattr(plan, prefix + "_organization")
    )


def transition(session: Session, runtime: Settings, plan: Transition, action: str, *, now=None):
    """Caller owns the transaction: commit only this operation, rollback on refusal."""
    if action not in {"plan", "apply", "rollback"}:
        raise Refused("action")
    now = now or datetime.now(UTC)
    expires = datetime.fromisoformat(plan.expires_at)
    if expires.tzinfo is None or expires.utcoffset() != timedelta(0) or not now < expires <= now + timedelta(hours=24):
        raise Refused("approval_expired_or_unbounded")
    runtime.validate_runtime_configuration()
    boundaries = {(plan.source_issuer, plan.source_organization), (plan.target_issuer, plan.target_organization)}
    if (runtime.cosmas_env != "early_adopter_beta" or runtime.data_mode != "synthetic"
            or runtime.auth_mode != "clerk_jwt" or runtime.beta_box_id != plan.box_id
            or (runtime.clerk_issuer, runtime.clerk_organization_id) not in boundaries):
        raise Refused("runtime_boundary")
    box_query = select(BoxContext).where(BoxContext.id == plan.box_id)
    owner_query = select(Principal).where(Principal.id == plan.owner_id, Principal.box_id == plan.box_id)
    if action != "plan":
        box_query, owner_query = box_query.with_for_update(), owner_query.with_for_update()
    box = session.scalar(box_query)
    owner = session.scalar(owner_query.execution_options(populate_existing=True))
    if (box is None or session.scalar(select(func.count()).select_from(BoxContext)) != 1
            or owner is None or owner.principal_type != "human" or owner.state != "active" or not owner.is_owner):
        raise Refused("existing_owner_boundary")
    source = session.get(ExternalIdentity, plan.source_id, populate_existing=True)
    if source is None or not _matches(source, plan, target=False) or not source.active:
        raise Refused("source_binding_changed")
    # No automatic transfer of clinical/scheduling authority or active work.
    binding_ids = [plan.source_id, plan.target_id]
    for account in (CoreCaptureAccount, SchedulingAccount):
        if session.scalar(select(account.id).where(account.external_identity_id.in_(binding_ids), account.revoked_at.is_(None)).limit(1)):
            raise Refused("connected_account_requires_separate_transition")
    if session.scalar(select(ModelWorkAdmission.id).where(ModelWorkAdmission.box_id == plan.box_id,
            ModelWorkAdmission.owner_id == plan.owner_id, ModelWorkAdmission.state.in_(["reserved", "running"])).limit(1)):
        raise Refused("active_work_requires_drain")
    targets = session.scalars(select(ExternalIdentity).where(
        (ExternalIdentity.id == plan.target_id)
        | ((ExternalIdentity.issuer == plan.target_issuer) & (ExternalIdentity.subject == plan.target_subject))
        | ((ExternalIdentity.issuer == plan.target_issuer) & (ExternalIdentity.organization_id == plan.target_organization)
           & (ExternalIdentity.principal_id == plan.owner_id)))).all()
    if len(targets) > 1:
        raise Refused("ambiguous_target_binding")
    target = targets[0] if targets else None
    events = session.scalars(select(AuditEvent).where(AuditEvent.correlation_id == plan.transition_id)).all()
    digest = plan.digest()
    if any(event.box_id != plan.box_id or event.aggregate_type != "external_identity"
           or event.aggregate_id != plan.target_id or event.outcome != "approved"
           or event.initiated_by_principal_id != plan.owner_id or event.approved_by_principal_id != plan.owner_id
           or event.actor_principal_id != plan.owner_id or event.payload_hash != digest
           or event.event_type not in {"shared_identity_bound", "shared_identity_rollback"} for event in events):
        raise Refused("transition_evidence_changed")
    applied = any(event.event_type == "shared_identity_bound" for event in events)
    reversed_ = any(event.event_type == "shared_identity_rollback" for event in events)
    if len(events) != int(applied) + int(reversed_) or (reversed_ and not applied):
        raise Refused("transition_evidence_changed")
    if target is not None and (not _matches(target, plan, target=True) or not applied
            or target.reviewed_by != plan.reviewed_by or target.evidence_ref != plan.evidence_ref
            or target.active == reversed_):
        raise Refused("target_binding_changed")
    if target is None and events:
        raise Refused("transition_binding_missing")
    if action == "plan":
        return {"status": "rolled_back" if reversed_ else "already_applied" if applied else "ready", "request_sha256": digest}
    if action == "apply":
        if reversed_:
            raise Refused("rolled_back_transition_cannot_reapply")
        if applied:
            return {"status": "already_applied", "request_sha256": digest}
        target = ExternalIdentity(id=plan.target_id, box_id=plan.box_id, principal_id=plan.owner_id,
            provider="clerk", issuer=plan.target_issuer, subject=plan.target_subject,
            organization_id=plan.target_organization, active=True, reviewed_by=plan.reviewed_by, evidence_ref=plan.evidence_ref)
        session.add(target)
        event_type, status = "shared_identity_bound", "applied"
    else:
        if target is None or not applied:
            raise Refused("transition_not_applied")
        if reversed_:
            return {"status": "already_rolled_back", "request_sha256": digest}
        target.active = False
        event_type, status = "shared_identity_rollback", "rolled_back"
    session.add(AuditEvent(id=str(uuid4()), box_id=plan.box_id, aggregate_type="external_identity",
        aggregate_id=plan.target_id, event_type=event_type, actor_principal_id=plan.owner_id,
        initiated_by_principal_id=plan.owner_id, approved_by_principal_id=plan.owner_id,
        correlation_id=plan.transition_id, payload_hash=digest, outcome="approved",
        detail={"source_binding_id": plan.source_id, "evidence_ref": plan.evidence_ref,
                "maintenance_expires_at": plan.expires_at}))
    session.flush()
    return {"status": status, "request_sha256": digest}


def main():
    """Run inside the existing staging runtime; all credentials stay in-process."""
    if len(sys.argv) != 4 or sys.argv[3] != "--confirm-reviewed-staging-maintenance":
        raise Refused("explicit_maintenance_confirmation_required")
    plan = load_plan(sys.argv[2])
    sys.path.insert(0, "/opt/cosmabot/runtime")
    # Canonical runtime module mounted in the maintenance container, not a wheel dependency.
    from entrypoint import (  # pyright: ignore[reportMissingImports]
        API_UID,
        load_environment,
        read_json,
    )

    if os.geteuid() != API_UID:
        raise Refused("runtime_user")
    values = load_environment(read_json(Path("/opt/cosmabot/runtime/runtime.json")), Path("/run/cosmabot/secrets"))
    os.environ["SSL_CERT_FILE"] = "/etc/ssl/certs/ca-certificates.crt"

    class MountedRuntime(Settings):
        @classmethod
        def settings_customise_sources(cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings):
            return (init_settings,)

    runtime = MountedRuntime(**{key.lower(): value for key, value in values.items() if key.lower() in Settings.model_fields})
    engine = create_engine(runtime.database_url)
    try:
        with Session(engine) as session, session.begin():
            session.execute(text("SET LOCAL lock_timeout='5s'"))
            session.execute(text("SET LOCAL statement_timeout='15s'"))
            if sys.argv[1] == "plan":
                session.execute(text("SET TRANSACTION READ ONLY"))
            result = transition(session, runtime, plan, sys.argv[1])
        print(json.dumps(result, sort_keys=True))
    finally:
        engine.dispose()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print(json.dumps({"error": "Reviewed staging identity transition refused; no exception values disclosed"}))
        raise SystemExit(1) from None
