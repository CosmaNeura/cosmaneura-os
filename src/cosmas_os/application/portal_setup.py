"""Local reviewed portal administration; no provider calls or credential lookup."""

from dataclasses import dataclass
from datetime import UTC
from typing import NoReturn
from uuid import uuid4

from sqlalchemy import func, select

from cosmas_os.adapters.vendor_connectors.portals import (
    PRODUCTION_PORTALS,
    PortalProfile,
    PortalRegistry,
)
from cosmas_os.api import portal_setup_schemas as schema
from cosmas_os.api.vendor_work_schemas import public_digest, timestamp
from cosmas_os.application import workspace as ws
from cosmas_os.config import settings
from cosmas_os.models import AuditEvent, PatientLink
from cosmas_os.portal_models import PortalSetup, PortalSetupReceipt, PortalSetupRevision
from cosmas_os.ports.vendor_connectors import ConnectionSelection, PortalCorrespondence, VendorError


def error(code, status=409) -> NoReturn:
    raise ws.WorkspaceError(code, status)


@dataclass(frozen=True)
class Installation:
    selection: ConnectionSelection
    profile: PortalProfile
    label: str


def installation_mode(item: Installation):
    return (
        "synthetic"
        if item.profile.portal_id.startswith("synthetic_")
        else item.selection.environment
    )


class Catalog:
    """Explicit installed profiles; real providers require host configuration."""

    def __init__(
        self,
        registry: PortalRegistry = PRODUCTION_PORTALS,
        installations: tuple[Installation, ...] = (),
        *,
        allow_live_profiles: bool = False,
    ):
        if type(allow_live_profiles) is not bool or len(installations) > 50:
            raise ValueError("Bounded explicit portal installation required")
        self.allow_live_profiles = allow_live_profiles
        self.registry = registry
        self.installations = {}
        for item in installations:
            profile = PortalProfile.model_validate(item.profile.model_dump(mode="python"))
            selection = ConnectionSelection.model_validate(item.selection.model_dump(mode="python"))
            if (
                selection.vendor != "portal"
                or not self.permitted_profile(selection, profile)
                or not 1 <= len(item.label) <= 80
                or str(selection.connection_id) in self.installations
            ):
                raise ValueError("An explicit named portal installation is required")
            capabilities = [
                row.capability for row in profile.capabilities if row.evidence == "documented"
            ]
            if not capabilities or any(
                registry.resolve(selection, profile.portal_id, capability).profile != profile
                for capability in capabilities
            ):
                raise ValueError("Installed portal implementation does not match")
            self.installations[str(selection.connection_id)] = Installation(
                selection, profile, item.label
            )

    def permitted_profile(self, selection, profile):
        invented = profile.portal_id.startswith("synthetic_")
        synthetic_origins = all(origin.endswith(".example.invalid") for origin in profile.origins)
        if invented or synthetic_origins:
            return invented and synthetic_origins and selection.environment == "sandbox"
        return self.allow_live_profiles and not any(
            origin.endswith(".invalid") for origin in profile.origins
        )

    def require(self, box, owner, installation_id, profile_sha, configuration_sha):
        item = self.installations.get(installation_id)
        if (
            item is None
            or str(item.selection.box_id) != box
            or str(item.selection.owner_id) != owner
        ):
            error("portal_profile_unavailable")
        if (
            item.profile.commitment() != profile_sha
            or item.selection.configuration_sha256 != configuration_sha
        ):
            error("portal_profile_changed")
        for capability in item.profile.capabilities:
            if capability.evidence == "documented":
                try:
                    if (
                        self.registry.resolve(
                            item.selection, item.profile.portal_id, capability.capability
                        ).profile
                        != item.profile
                    ):
                        error("portal_profile_changed")
                except VendorError:
                    error("portal_profile_changed")
        return item


EMPTY_CATALOG = Catalog()


def _owner(s, box, actor, *, writing=False, require_gate=True):
    p = ws._human(s, box, actor, creating=writing)
    if not p.is_owner:
        error("portal_setup_unavailable", 404)
    if require_gate and (
        not settings.workspace_available or not getattr(settings, "portal_setup_enabled", False)
    ):
        error("portal_setup_disabled", 403)
    return p


def _fence(s):
    check = s.info.get("portal_setup_authority")
    if check is not None:
        check()


def _now(s):
    return s.scalar(select(func.clock_timestamp())).astimezone(UTC)


def _patient(s, box, patient_id):
    patient = s.scalar(
        select(PatientLink)
        .where(
            PatientLink.id == patient_id,
            PatientLink.box_id == box,
            PatientLink.state == "confirmed",
            PatientLink.revoked_at.is_(None),
            PatientLink.source_owner_id.is_(None),
        )
        .with_for_update(read=True)
    )
    if patient is None:
        error("portal_patient_unavailable")
    return patient


def _latest(s, connection_id):
    return s.scalar(
        select(PortalSetupReceipt)
        .where(PortalSetupReceipt.connection_id == connection_id)
        .order_by(PortalSetupReceipt.version.desc())
        .limit(1)
    )


def _connection(s, box, owner, connection_id):
    value = s.scalar(
        select(PortalSetup)
        .where(
            PortalSetup.id == connection_id,
            PortalSetup.box_id == box,
            PortalSetup.owner_id == owner,
        )
        .with_for_update()
    )
    if value is None:
        error("portal_setup_unavailable", 404)
    return value


def request_digest(box, owner, kind, request):
    return public_digest(
        "cosmas-portal-setup-request.v1",
        {
            "scope": {"box_id": box, "owner_id": owner},
            "command_kind": kind,
            "request": request.public(),
        },
    )


def _old(s, box, owner, kind, request):
    digest = request_digest(box, owner, kind, request)
    row = s.scalar(
        select(PortalSetupReceipt).where(
            PortalSetupReceipt.box_id == box,
            PortalSetupReceipt.owner_id == owner,
            PortalSetupReceipt.idempotency_key == request.idempotency_key,
        )
    )
    if row and (row.command_kind != kind or row.request_sha256 != digest):
        error("portal_idempotency_conflict")
    return row, digest


def _response(row):
    value = row.response
    if (
        value.get("receipt_sha256") != row.receipt_sha256
        or public_digest(
            "cosmas-portal-setup-receipt.v1",
            {key: child for key, child in value.items() if key != "receipt_sha256"},
        )
        != row.receipt_sha256
    ):
        error("portal_setup_integrity", 503)
    return value


def _record(s, box, owner, kind, request, digest, revision, version, state):
    _fence(s)
    rid = str(uuid4())
    now = _now(s)
    response = {
        "contract_version": 1,
        "outcome": "recorded",
        "scope": {"box_id": box, "owner_id": owner},
        "connection_id": revision.connection_id,
        "command_kind": kind,
        "idempotency_key": request.idempotency_key,
        "request_sha256": digest,
        "receipt_id": rid,
        "recorded_at": timestamp(now),
        "effect": {
            "version": version,
            "revision_id": revision.id,
            "state": state,
            "review_sha256": revision.review_sha256,
        },
    }
    sha = public_digest("cosmas-portal-setup-receipt.v1", response)
    response["receipt_sha256"] = sha
    row = PortalSetupReceipt(
        id=rid,
        box_id=box,
        owner_id=owner,
        connection_id=revision.connection_id,
        revision_id=revision.id,
        version=version,
        state=state,
        command_kind=kind,
        idempotency_key=request.idempotency_key,
        request=request.public(),
        request_sha256=digest,
        response=response,
        receipt_sha256=sha,
        recorded_at=now,
    )
    s.add(row)
    s.add(
        AuditEvent(
            box_id=box,
            aggregate_type="portal_setup",
            aggregate_id=revision.connection_id,
            actor_principal_id=owner,
            event_type="portal_setup." + kind,
            outcome=state,
            detail={"revision_id": revision.id, "receipt_id": rid},
        )
    )
    s.flush()
    _fence(s)
    s.commit()
    return _response(row)


def catalog(s, box, owner, installed=EMPTY_CATALOG):
    _owner(s, box, owner, require_gate=False)
    profiles = []
    for installation_id, item in sorted(installed.installations.items()):
        if not settings.workspace_available or not getattr(settings, "portal_setup_enabled", False):
            break
        if str(item.selection.box_id) != box or str(item.selection.owner_id) != owner:
            continue
        try:
            installed.require(
                box,
                owner,
                installation_id,
                item.profile.commitment(),
                item.selection.configuration_sha256,
            )
        except ws.WorkspaceError:
            continue
        profiles.append(
            {
                "installation_id": installation_id,
                "portal_id": item.profile.portal_id,
                "label": item.label,
                "profile_sha256": item.profile.commitment(),
                "configuration_sha256": item.selection.configuration_sha256,
                "capabilities": [
                    {"capability": cap.capability, "evidence": cap.evidence}
                    for cap in item.profile.capabilities
                ],
                "mode": installation_mode(item),
                "mapping_requirements": list(item.profile.correspondence),
            }
        )
    patients = [
        {"id": p.id, "label": p.label}
        for p in s.scalars(
            select(PatientLink)
            .where(
                PatientLink.box_id == box,
                PatientLink.state == "confirmed",
                PatientLink.revoked_at.is_(None),
                PatientLink.source_owner_id.is_(None),
            )
            .order_by(PatientLink.id)
            .limit(100)
        )
    ]
    connections = [
        detail(s, box, owner, c.id, installed)
        for c in s.scalars(
            select(PortalSetup)
            .where(PortalSetup.box_id == box, PortalSetup.owner_id == owner)
            .order_by(PortalSetup.created_at.desc())
            .limit(50)
        )
    ]
    return {
        "contract_version": 1,
        "scope": {"box_id": box, "owner_id": owner},
        "profiles": profiles,
        "patients": patients,
        "connections": connections,
        "live_portals_configured": any(profile["mode"] != "synthetic" for profile in profiles),
    }


def detail(s, box, owner, connection_id, installed=EMPTY_CATALOG):
    _owner(s, box, owner, require_gate=False)
    _connection(s, box, owner, connection_id)
    latest = _latest(s, connection_id)
    if latest is None:
        error("portal_setup_integrity", 503)
    r = s.get(PortalSetupRevision, latest.revision_id)
    reason = "available"
    try:
        installed.require(box, owner, r.installation_id, r.profile_sha256, r.configuration_sha256)
        _patient(s, box, r.patient_link_id)
    except ws.WorkspaceError as exc:
        reason = exc.code
    if not settings.workspace_available or not getattr(settings, "portal_setup_enabled", False):
        reason = "portal_setup_disabled"
    return {
        "connection_id": connection_id,
        "version": latest.version,
        "revision_id": r.id,
        "revision": r.revision,
        "state": latest.state,
        "usable_locally": latest.state == "active" and reason == "available",
        "availability": reason,
        "review": r.review,
        "review_sha256": r.review_sha256,
        "last_receipt": _response(latest),
    }


def history(s, box, owner, connection_id):
    _owner(s, box, owner, require_gate=False)
    _connection(s, box, owner, connection_id)
    rows = list(
        s.scalars(
            select(PortalSetupReceipt)
            .where(PortalSetupReceipt.connection_id == connection_id)
            .order_by(PortalSetupReceipt.version)
        )
    )
    return {
        "contract_version": 1,
        "connection_id": connection_id,
        "receipts": [_response(row) for row in rows],
    }


def propose(s, box, owner, request, installed=EMPTY_CATALOG):
    _owner(s, box, owner, writing=True, require_gate=False)
    old, digest = _old(s, box, owner, "propose", request)
    if old:
        return _response(old)
    _owner(s, box, owner, writing=True)
    item = installed.require(
        box, owner, request.installation_id, request.profile_sha256, request.configuration_sha256
    )
    allowed = {c.capability for c in item.profile.capabilities if c.evidence == "documented"}
    if not set(request.capabilities) <= allowed:
        error("portal_capability_unavailable")
    patient = _patient(s, box, request.mappings.patient_link_id)
    # The selected practice mapping must match the installed account; no inferred correspondence.
    if request.mappings.practice_reference != item.selection.remote_account_id:
        error("portal_practice_changed")
    existing = s.get(PortalSetup, request.connection_id)
    if existing:
        _connection(s, box, owner, request.connection_id)
        head = _latest(s, request.connection_id)
        if head.state == "revoked" or head.version != request.expected_version:
            error("portal_setup_changed")
        previous = s.get(PortalSetupRevision, head.revision_id)
        number = previous.revision + 1
        version = head.version + 1
    else:
        if request.expected_version != 0:
            error("portal_setup_changed")
        if (
            s.scalar(
                select(func.count())
                .select_from(PortalSetup)
                .where(PortalSetup.box_id == box, PortalSetup.owner_id == owner)
            )
            >= 50
        ):
            error("portal_setup_limit")
        s.add(PortalSetup(id=request.connection_id, box_id=box, owner_id=owner, created_at=_now(s)))
        s.flush()
        number = version = 1
    if number > 100 or version > 1000:
        error("portal_setup_limit")
    mapping_ids = {
        purpose + "_mapping_id": str(uuid4()) for purpose in ("practice", "patient", "recipient")
    }
    mappings_sha = public_digest(
        "cosmas-portal-setup-mappings.v1",
        {
            "scope": {"box_id": box, "owner_id": owner},
            "installation_id": request.installation_id,
            "profile_sha256": request.profile_sha256,
            "configuration_sha256": request.configuration_sha256,
            "ids": mapping_ids,
            "mappings": request.mappings.public(),
        },
    )
    review = {
        "connection_id": request.connection_id,
        "installation_id": request.installation_id,
        "portal_id": item.profile.portal_id,
        "profile_label": item.label,
        "mode": installation_mode(item),
        "profile_sha256": request.profile_sha256,
        "configuration_sha256": request.configuration_sha256,
        "capabilities": sorted(request.capabilities),
        "mappings": {**request.mappings.public(), "patient_label": patient.label},
        "mapping_ids": mapping_ids,
        "mappings_sha256": mappings_sha,
    }
    r = PortalSetupRevision(
        connection_id=request.connection_id,
        box_id=box,
        owner_id=owner,
        revision=number,
        installation_id=request.installation_id,
        portal_id=item.profile.portal_id,
        profile_sha256=request.profile_sha256,
        configuration_sha256=request.configuration_sha256,
        patient_link_id=patient.id,
        **mapping_ids,
        mappings_sha256=mappings_sha,
        review=review,
        review_sha256=public_digest("cosmas-portal-setup-review.v1", review),
        created_at=_now(s),
    )
    s.add(r)
    s.flush()
    return _record(s, box, owner, "propose", request, digest, r, version, "pending_review")


def command(s, box, owner, kind, request, installed=EMPTY_CATALOG):
    if kind not in {"activate", "disable", "revoke"}:
        error("invalid_portal_request", 422)
    _owner(s, box, owner, writing=True, require_gate=False)
    old, digest = _old(s, box, owner, kind, request)
    if old:
        return _response(old)
    # Disable/revoke and historical resolution remain available if the feature is disabled.
    if kind == "activate":
        _owner(s, box, owner, writing=True)
    _connection(s, box, owner, request.connection_id)
    head = _latest(s, request.connection_id)
    r = s.get(PortalSetupRevision, head.revision_id)
    if head.state == "revoked" or (head.version, r.id, r.review_sha256) != (
        request.expected_version,
        request.revision_id,
        request.review_sha256,
    ):
        error("portal_setup_changed")
    if kind == "activate":
        if head.state not in {"pending_review", "disabled"}:
            error("portal_setup_changed")
        installed.require(box, owner, r.installation_id, r.profile_sha256, r.configuration_sha256)
        _patient(s, box, r.patient_link_id)
    if kind == "disable" and head.state == "disabled":
        error("portal_setup_changed")
    return _record(
        s,
        box,
        owner,
        kind,
        request,
        digest,
        r,
        head.version + 1,
        {"activate": "active", "disable": "disabled", "revoke": "revoked"}[kind],
    )


def resolve(s, box, owner, request):
    _owner(s, box, owner, require_gate=False)
    row = s.scalar(
        select(PortalSetupReceipt).where(
            PortalSetupReceipt.box_id == box,
            PortalSetupReceipt.owner_id == owner,
            PortalSetupReceipt.idempotency_key == request.idempotency_key,
        )
    )
    if row is None:
        return {
            "contract_version": 1,
            "outcome": "not_found",
            "scope": {"box_id": box, "owner_id": owner},
            "command_kind": request.command_kind,
            "idempotency_key": request.idempotency_key,
            "request_sha256": request.request_sha256,
        }
    if row.command_kind != request.command_kind or row.request_sha256 != request.request_sha256:
        error("portal_idempotency_conflict")
    return _response(row)


def active_correspondence(s, box, owner, connection_id, capability, installed=EMPTY_CATALOG):
    """Pure current mapping lookup for future explicitly authorized portal work."""
    _owner(s, box, owner)
    d = detail(s, box, owner, connection_id, installed)
    if not d["usable_locally"] or capability not in d["review"]["capabilities"]:
        error("portal_connection_inactive")
    r = s.get(PortalSetupRevision, d["revision_id"])
    item = installed.require(
        box, owner, r.installation_id, r.profile_sha256, r.configuration_sha256
    )
    correspondence = PortalCorrespondence(
        patient_mapping_id=r.patient_mapping_id,
        practice_mapping_id=r.practice_mapping_id,
        recipient_mapping_id=r.recipient_mapping_id,
        mappings_sha256=r.mappings_sha256,
    )
    return (
        item.selection,
        correspondence,
        schema.Mappings.model_validate(
            {key: d["review"]["mappings"][key] for key in schema.Mappings.model_fields}
        ),
    )
