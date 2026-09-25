"""Private, read-only navigation over durable model admissions and usage evidence."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, case, func, select, tuple_
from sqlalchemy.orm import Session, load_only

from cosmas_os.api.model_activity_schemas import PAGE_SIZE, ActivityResponse
from cosmas_os.application import model_work as work
from cosmas_os.application import provider_team as team
from cosmas_os.application import workspace as ws
from cosmas_os.application.encounter_access import patient_visible
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.models import (
    AppointmentObservation,
    EncounterWorkspace,
    ModelWorkAdmission,
    PatientLink,
    Principal,
    ProviderTeamRevision,
)

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _micros(value):
    delta = value.astimezone(UTC) - EPOCH
    return (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds


def _checksum(box, owner, view, body):
    return hashlib.sha256(
        work.canonical(
            {
                "contract": "cosmas-model-activity-cursor-v1",
                "box_id": box,
                "owner_id": owner,
                "view": view,
                "position": body,
            }
        )
    ).hexdigest()


def _cursor(box, owner, view, cutoff, row):
    body = f"{_micros(cutoff):016x}{_micros(row.admitted_at):016x}{UUID(row.id).hex}"
    return "a1" + body + _checksum(box, owner, view, body)


def _decode(value, box, owner, view, as_of):
    if value is None:
        return as_of, None
    if (
        len(value) != 130
        or not value.startswith("a1")
        or any(c not in "0123456789abcdef" for c in value[2:])
    ):
        raise ws.WorkspaceError("invalid_activity_cursor", 422)
    body = value[2:66]
    if value[66:] != _checksum(box, owner, view, body):
        raise ws.WorkspaceError("invalid_activity_cursor", 422)
    try:
        cutoff = EPOCH + timedelta(microseconds=int(body[:16], 16))
        admitted = EPOCH + timedelta(microseconds=int(body[16:32], 16))
        identifier = str(UUID(hex=body[32:]))
        if not EPOCH <= admitted <= cutoff <= as_of:
            raise ValueError()
    except (ValueError, OverflowError):
        raise ws.WorkspaceError("invalid_activity_cursor", 422) from None
    return cutoff, (admitted, identifier)


def _authorize(s, box, owner, external_identity_id):
    if external_identity_id is None:
        raise ws.WorkspaceError("activity_access_denied", 403)
    person = s.scalar(
        select(Principal.id).where(
            Principal.id == owner,
            Principal.box_id == box,
            Principal.principal_type == "human",
            Principal.state == "active",
            Principal.tombstoned_at.is_(None),
        )
    )
    if person is None:
        raise ws.WorkspaceError("activity_access_denied", 403)
    work._identity(s, box, owner, external_identity_id)


def read(
    s: Session,
    box: str,
    owner: str,
    *,
    view: str,
    cursor: str | None = None,
    external_identity_id: str,
    reauthenticate=None,
    clock=None,
    time_contract=1,
):
    if view not in {"attention", "recent"} or time_contract not in {1, 2}:
        raise ws.WorkspaceError("invalid_activity_request", 422)
    if reauthenticate:
        reauthenticate()
    _authorize(s, box, owner, external_identity_id)
    as_of = work.now(s, clock)
    cutoff, after = _decode(cursor, box, owner, view, as_of)
    model = ModelWorkAdmission
    attention = case(
        (and_(model.state == "reserved", model.reservation_expires_at <= as_of), "abandoned"),
        (and_(model.state == "running", model.lease_ends_at <= as_of), "unknown"),
        else_=model.state,
    ).in_(["reserved", "running", "unknown"])
    scoped = [model.box_id == box, model.owner_id == owner, model.admitted_at <= cutoff]
    accessible = (
        select(model.id)
        .join(
            EncounterWorkspace,
            and_(
                EncounterWorkspace.id == model.workspace_id,
                EncounterWorkspace.box_id == box,
                EncounterWorkspace.owner_id == owner,
            ),
        )
        .join(
            AppointmentObservation,
            and_(
                AppointmentObservation.id == EncounterWorkspace.appointment_id,
                AppointmentObservation.box_id == box,
                AppointmentObservation.patient_link_id == EncounterWorkspace.patient_link_id,
            ),
        )
        .join(
            PatientLink,
            and_(
                PatientLink.id == EncounterWorkspace.patient_link_id,
                PatientLink.box_id == box,
                PatientLink.state == "confirmed",
                PatientLink.revoked_at.is_(None),
                patient_visible(owner),
            ),
        )
        .where(*scoped)
    )
    access_ids = accessible.scalar_subquery()
    if time_contract == 1:
        # Old clients require an instant. These rows remain in withheld_total;
        # never infer a timezone or break the old closed response shape.
        access_ids = accessible.where(AppointmentObservation.start_at.is_not(None)).scalar_subquery()
    allowed = model.id.in_(access_ids)
    attention_total = (
        s.scalar(select(func.count()).select_from(model).where(*scoped, allowed, attention)) or 0
    )
    recent_total = (
        s.scalar(select(func.count()).select_from(model).where(*scoped, allowed, ~attention)) or 0
    )
    total = s.scalar(select(func.count()).select_from(model).where(*scoped)) or 0
    conditions = [*scoped, allowed, attention if view == "attention" else ~attention]
    if after:
        position = tuple_(model.admitted_at, model.id)
        conditions.append(position > after if view == "attention" else position < after)
    order = (
        (model.admitted_at.asc(), model.id.asc())
        if view == "attention"
        else (model.admitted_at.desc(), model.id.desc())
    )
    candidates = list(
        s.execute(
            select(model, model.request_body["role"].as_string())
            .where(*conditions)
            .options(
                load_only(
                    model.id,
                    model.workspace_id,
                    model.agent_id,
                    model.team_revision_id,
                    model.kind,
                    model.admitted_at,
                    model.reservation_expires_at,
                    model.state,
                    model.dispatch_id,
                    model.lease_ends_at,
                    model.request_entry_id,
                )
            )
            .order_by(*order)
            .limit(PAGE_SIZE + 1)
        )
    )
    rows = []
    for admission, address in candidates[:PAGE_SIZE]:
        workspace = work.read_workspace(s, box, owner, admission.workspace_id, external_identity_id)
        appointment = s.get(AppointmentObservation, workspace.appointment_id)
        version = s.get(ProviderTeamRevision, admission.team_revision_id)
        if (
            appointment is None
            or version is None
            or version.box_id != box
            or version.owner_id != owner
        ):
            raise ws.WorkspaceError("activity_unavailable", 503)
        config = next(
            (bot for bot in version.configuration["bots"] if team.bot_address(bot) == address), None
        )
        if config is None:
            raise ws.WorkspaceError("activity_unavailable", 503)
        rows.append(
            {
                "kind": admission.kind,
                "bot": {
                    "address": address,
                    "agent_id": admission.agent_id,
                    "role": config["role"],
                    "name": config["name"],
                    "team_revision": version.revision,
                },
                "encounter": {
                    "workspace_id": workspace.id,
                    "appointment_id": appointment.id,
                    "label": appointment.patient_label,
                    "starts_at": appointment.start_at.isoformat() if appointment.start_at else None,
                    **({"source_local_start": appointment.source_local_start.isoformat()
                        if appointment.source_local_start else None} if time_contract == 2 else {}),
                    "entry_id": admission.request_entry_id,
                },
                "admission": work.admission_observation(s, admission, as_of),
            }
        )
    has_more = len(candidates) > PAGE_SIZE
    value = {
        "contract_version": time_contract,
        "box_id": box,
        "owner_id": owner,
        "recovery_scope": payload_hash(
            {"contract": "cosmas-private-drafts-v1", "box_id": box, "owner_id": owner}
        ),
        "view": view,
        "as_of": as_of.isoformat(),
        "page": {
            "limit": PAGE_SIZE,
            "cursor": cursor,
            "next_cursor": _cursor(box, owner, view, cutoff, candidates[PAGE_SIZE - 1][0])
            if has_more
            else None,
            "has_more": has_more,
        },
        "coverage": {
            "rows": "durable_admissions_only",
            "paging": "live_current_access",
            "attention_total": attention_total,
            "recent_total": recent_total,
            "withheld_total": total - attention_total - recent_total,
            "legacy_rows_included": False,
        },
        "usage": work.usage(s, box, owner, as_of=as_of),
        "rows": rows,
    }
    closed = ActivityResponse.model_validate(value).model_dump(mode="json",
        exclude={"rows":{"__all__":{"encounter":{"source_local_start"}}}} if time_contract == 1 else None)
    # The page cursor freezes the admission cutoff, not later outcomes or source access.
    # Recheck before disclosure; a cursor never keeps a revoked source accessible.
    if reauthenticate:
        reauthenticate()
    _authorize(s, box, owner, external_identity_id)
    for row in rows:
        work.read_workspace(s, box, owner, row["encounter"]["workspace_id"], external_identity_id)
    return closed
