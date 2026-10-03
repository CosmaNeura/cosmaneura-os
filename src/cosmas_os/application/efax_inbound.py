"""Owner/account eFax inbox ledger; no provider I/O, model access or patient writes.

A caller commits a claim and then commits mark_invocation before its effectful GET.
Nothing scans or retries this ledger. Recovery reads retained evidence only.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import NoReturn
from uuid import UUID, uuid4

from sqlalchemy import func, select

from cosmas_os.application import workspace as ws
from cosmas_os.config import settings
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.efax_inbound_models import (
    EFaxInboundAcquisition,
    EFaxInboundGrant,
    EFaxInboundImageRevision,
    EFaxInboundInvocation,
    EFaxInboundObservation,
    EFaxInboundObservationRequest,
    EFaxInboundOutcome,
    EFaxInboundReceipt,
)
from cosmas_os.models import ActionRevision, Decision, Operation, Principal, Ticket
from cosmas_os.ports.efax_inbound import (
    ImageApproval,
    ImageCommand,
    ImageReceipt,
    ListRequest,
    ListSnapshot,
)
from cosmas_os.ports.vendor_connectors import ConnectionSelection, digest

LANE = "account_efax_inbound"
ADAPTER = "efax_inbound_once"
MAX_PDF_BYTES = 1_048_576
_KEY = re.compile(r"^[A-Za-z0-9:_-]{8,100}$")


@dataclass(frozen=True, repr=False)
class Installation:
    """Trusted server installation, never constructed from a public request."""

    selection: ConnectionSelection
    label: str
    metadata_enabled: bool
    image_enabled: bool

    def __post_init__(self):
        selection = ConnectionSelection.model_validate(self.selection.model_dump(mode="python"))
        if (
            selection.vendor != "efax"
            or selection.environment != "production"
            or not isinstance(self.label, str)
            or not 1 <= len(self.label) <= 80
            or any(ord(c) < 32 or ord(c) == 127 for c in self.label)
            or type(self.metadata_enabled) is not bool
            or type(self.image_enabled) is not bool
        ):
            raise ValueError("closed eFax inbound installation required")
        object.__setattr__(self, "selection", selection)


@dataclass(frozen=True, repr=False)
class ObservationIntent:
    box_id: str
    owner_id: str
    grant_id: str
    request: ListRequest


@dataclass(frozen=True, repr=False)
class Invocation:
    box_id: str
    owner_id: str
    grant_id: str
    operation_id: str
    token: str
    command: ImageCommand
    approval: ImageApproval
    snapshot: ListSnapshot


def error(code, status=409) -> NoReturn:
    raise ws.WorkspaceError(code, status)


def _gate():
    if not settings.workspace_available or not getattr(settings, "efax_inbound_enabled", False):
        error("efax_inbound_disabled", 403)


def _owner(s, box, actor, *, writing=False, gated=True):
    if gated:
        _gate()
    owner = ws._human(s, box, actor, creating=writing)
    if not owner.is_owner:
        error("efax_inbound_unavailable", 404)
    return owner


def _now(s):
    return s.scalar(select(func.clock_timestamp())).astimezone(UTC)


def _stamp(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        error("efax_inbound_request_invalid", 400)
    return value.astimezone(UTC)


def canonical_public_timestamp(value):
    """Public digest/display projection; retained private timestamps stay exact.

    New API commands have whole seconds. Older private fractional timestamps are
    projected to the preceding UTC second, never extending their expiry.
    """
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            error("efax_inbound_source_invalid")
    return _stamp(value).isoformat(timespec="seconds").replace("+00:00", "Z")


def _key(value):
    if type(value) is not str or not _KEY.fullmatch(value):
        error("efax_inbound_request_invalid", 400)
    return value


def account_sha256(selection):
    """Stable remote account fence: credential, connection version and owner are excluded."""
    return digest(
        "cosmas-efax-inbound-account.v1",
        {
            "box_id": str(selection.box_id),
            "vendor": "efax",
            "environment": selection.environment,
            "remote_account_id": selection.remote_account_id,
        },
    )


def _installation(grant):
    return Installation(
        ConnectionSelection.model_validate(grant.selection),
        grant.label,
        grant.metadata_enabled,
        grant.image_enabled,
    )


def _current(s, grant, current, *, image=False, installation=None):
    _gate()
    now = _now(s)
    if grant.revoked_at is not None or now >= grant.expires_at or not grant.metadata_enabled:
        error("efax_inbound_grant_unavailable")
    retained = _installation(grant)
    if (
        retained.selection.commitment() != grant.selection_sha256
        or account_sha256(retained.selection) != grant.account_sha256
        or str(retained.selection.connection_id) != grant.connection_id
        or str(retained.selection.box_id) != grant.box_id
        or str(retained.selection.owner_id) != grant.owner_id
        or image
        and not grant.image_enabled
        or installation is not None
        and installation != retained
    ):
        error("efax_inbound_grant_changed")
    try:
        if current is None or current(s, grant) is not True:
            error("efax_inbound_grant_unavailable")
    except ws.WorkspaceError:
        raise
    except Exception:
        error("efax_inbound_grant_unavailable")


def _grant(s, box, actor, grant_id, *, current, image=False, writing=False):
    _owner(s, box, actor, writing=writing)
    row = s.scalar(
        select(EFaxInboundGrant)
        .where(
            EFaxInboundGrant.id == grant_id,
            EFaxInboundGrant.box_id == box,
            EFaxInboundGrant.owner_id == actor,
        )
        .with_for_update(read=not writing)
        .execution_options(populate_existing=True)
    )
    if row is None:
        error("efax_inbound_unavailable", 404)
    _current(s, row, current, image=image)
    return row


def _request_sha(box, actor, kind, request):
    return digest(
        "cosmas-efax-inbound-public-command.v1",
        {
            "box_id": box,
            "owner_id": actor,
            "kind": kind,
            "request": request,
        },
    )


def _previous(s, box, actor, kind, key, request):
    _key(key)
    sha = _request_sha(box, actor, kind, request)
    row = s.scalar(
        select(EFaxInboundReceipt).where(
            EFaxInboundReceipt.box_id == box,
            EFaxInboundReceipt.owner_id == actor,
            EFaxInboundReceipt.idempotency_key == key,
        )
    )
    if row is not None and (
        row.kind != kind or row.request_sha256 != sha or row.request != request
    ):
        error("efax_inbound_idempotency_conflict")
    return row, sha


def _record(s, box, actor, kind, key, request, result, sha):
    row = EFaxInboundReceipt(
        box_id=box,
        owner_id=actor,
        kind=kind,
        idempotency_key=key,
        request=request,
        request_sha256=sha,
        result=result,
    )
    s.add(row)
    s.flush()
    return _receipt(row)


def _receipt(row):
    public_request = {**row.request, "idempotency_key": row.idempotency_key}
    if row.kind == "grant":
        public_request = {
            k: public_request[k]
            for k in (
                "installation_id",
                "reviewed_account",
                "reviewed_mark_read",
                "image_enabled",
                "expires_at",
                "idempotency_key",
            )
        }
    for field in ("expires_at", "starts_at", "ends_at"):
        if field in public_request:
            public_request[field] = canonical_public_timestamp(public_request[field])
    public_result = dict(row.result)
    if "expires_at" in public_result:
        public_result["expires_at"] = canonical_public_timestamp(public_result["expires_at"])
    scope = {"box_id": row.box_id, "owner_id": row.owner_id}
    return {
        "contract_version": 1,
        "scope": scope,
        "idempotency_key": row.idempotency_key,
        "kind": row.kind,
        "public_request_sha256": digest(
            "cosmas-efax-inbound-api-command.v1",
            {
                "scope": scope,
                "kind": row.kind,
                "request": public_request,
            },
        ),
        "receipt_id": row.id,
        "request_sha256": row.request_sha256,
        **public_result,
    }


def grant(
    s,
    box,
    actor,
    installation,
    *,
    key,
    reviewed_account,
    reviewed_mark_read,
    expires_at,
    image_enabled=False,
    current=None,
):
    """An explicit independent grant; prior outbound permissions confer no authority."""
    _owner(s, box, actor, writing=True)
    if not isinstance(installation, Installation):
        error("efax_inbound_request_invalid", 400)
    expires = _stamp(expires_at)
    request = dict(
        installation_id=str(installation.selection.connection_id),
        installation_sha256=installation.selection.commitment(),
        label=installation.label,
        metadata_enabled=True,
        image_enabled=image_enabled,
        reviewed_account=reviewed_account,
        reviewed_mark_read=reviewed_mark_read,
        expires_at=expires.isoformat(),
    )
    previous, sha = _previous(s, box, actor, "grant", key, request)
    if previous:
        return _receipt(previous)
    now = _now(s)
    if (
        reviewed_account is not True
        or type(image_enabled) is not bool
        or type(reviewed_mark_read) is not bool
        or image_enabled
        and reviewed_mark_read is not True
        or not installation.metadata_enabled
        or image_enabled
        and not installation.image_enabled
        or str(installation.selection.box_id) != box
        or str(installation.selection.owner_id) != actor
        or not now < expires <= now + timedelta(days=30)
    ):
        error("efax_inbound_request_invalid", 400)
    try:
        if current is None or current(s, installation) is not True:
            error("efax_inbound_grant_unavailable")
    except ws.WorkspaceError:
        raise
    except Exception:
        error("efax_inbound_grant_unavailable")
    row = EFaxInboundGrant(
        id=str(uuid4()),
        box_id=box,
        owner_id=actor,
        connection_id=str(installation.selection.connection_id),
        account_sha256=account_sha256(installation.selection),
        selection=installation.selection.model_dump(mode="json"),
        selection_sha256=installation.selection.commitment(),
        label=installation.label,
        metadata_enabled=True,
        image_enabled=image_enabled,
        reviewed_by=actor,
        reviewed_at=now,
        expires_at=expires,
        request_sha256=sha,
    )
    s.add(row)
    result = _record(
        s,
        box,
        actor,
        "grant",
        key,
        request,
        {
            "grant_id": row.id,
            "state": "granted",
            "label": row.label,
            "metadata_enabled": True,
            "image_enabled": image_enabled,
            "expires_at": expires.isoformat(),
        },
        sha,
    )
    s.commit()
    return result


def revoke_grant(s, box, actor, grant_id, *, key):
    _owner(s, box, actor, writing=True, gated=False)
    request = {"grant_id": grant_id}
    previous, sha = _previous(s, box, actor, "revoke", key, request)
    if previous:
        return _receipt(previous)
    row = s.scalar(
        select(EFaxInboundGrant)
        .where(
            EFaxInboundGrant.id == grant_id,
            EFaxInboundGrant.box_id == box,
            EFaxInboundGrant.owner_id == actor,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        error("efax_inbound_unavailable", 404)
    if row.revoked_at is None:
        row.revoked_at = _now(s)
    result = _record(
        s,
        box,
        actor,
        "revoke",
        key,
        request,
        {
            "grant_id": row.id,
            "state": "revoked",
        },
        sha,
    )
    s.commit()
    return result


def status(s, box, actor, *, current=None):
    _owner(s, box, actor, gated=False)
    rows = s.scalars(
        select(EFaxInboundGrant)
        .where(
            EFaxInboundGrant.box_id == box,
            EFaxInboundGrant.owner_id == actor,
        )
        .order_by(EFaxInboundGrant.reviewed_at.desc())
    ).all()
    grants = []
    for row in rows[:50]:
        try:
            _current(s, row, current)
            state = "available"
        except ws.WorkspaceError:
            state = "unavailable"
        grants.append(
            {
                "grant_id": row.id,
                "label": row.label,
                "state": state,
                "image_enabled": row.image_enabled and state == "available",
                "expires_at": canonical_public_timestamp(row.expires_at),
            }
        )
    return {
        "contract_version": 1,
        "scope": {"box_id": box, "owner_id": actor},
        "enabled": bool(
            settings.workspace_available and getattr(settings, "efax_inbound_enabled", False)
        ),
        "grants": grants,
    }


def reserve_observation(
    s, box, actor, grant_id, *, key, starts_at, ends_at, limit=25, offset=0, current=None
):
    g = _grant(s, box, actor, grant_id, current=current, writing=True)
    starts, ends = _stamp(starts_at), _stamp(ends_at)
    request = dict(
        grant_id=grant_id,
        starts_at=starts.isoformat(),
        ends_at=ends.isoformat(),
        limit=limit,
        offset=offset,
    )
    previous, sha = _previous(s, box, actor, "observe", key, request)
    if previous:
        return resolve_observation(s, box, actor, key=key, current=current), None
    try:
        wire = ListRequest(
            selection=ConnectionSelection.model_validate(g.selection),
            request_id=uuid4(),
            starts_at=starts,
            ends_at=ends,
            limit=limit,
            offset=offset,
        )
    except Exception:
        error("efax_inbound_request_invalid", 400)
    if ends > _now(s) + timedelta(seconds=5):
        error("efax_inbound_request_invalid", 400)
    row = EFaxInboundObservationRequest(
        id=str(wire.request_id),
        box_id=box,
        owner_id=actor,
        grant_id=g.id,
        request=wire.model_dump(mode="json"),
        request_sha256=digest(
            "cosmas-efax-inbound-observation-request.v1", wire.model_dump(mode="json")
        ),
    )
    s.add(row)
    result = _record(
        s,
        box,
        actor,
        "observe",
        key,
        request,
        {
            "observation_id": row.id,
            "grant_id": g.id,
            "state": "unconfirmed",
        },
        sha,
    )
    intent = ObservationIntent(box, actor, g.id, wire)
    s.commit()
    return result, intent


def _observation(s, box, actor, observation_id):
    row = s.scalar(
        select(EFaxInboundObservation).where(
            EFaxInboundObservation.request_id == observation_id,
            EFaxInboundObservation.box_id == box,
            EFaxInboundObservation.owner_id == actor,
        )
    )
    if row is None:
        error("efax_inbound_observation_unconfirmed")
    try:
        snapshot = ListSnapshot.model_validate(row.payload)
        if (
            str(snapshot.request.request_id) != row.request_id
            or snapshot.source_sha256 != row.source_sha256
            or digest("cosmas-efax-inbound-snapshot-payload.v1", row.payload) != row.payload_sha256
        ):
            raise ValueError
    except Exception:
        error("efax_inbound_source_invalid")
    return row, snapshot


def settle_observation(s, intent, snapshot, *, current=None):
    _owner(s, intent.box_id, intent.owner_id, writing=True)
    request = s.scalar(
        select(EFaxInboundObservationRequest)
        .where(
            EFaxInboundObservationRequest.id == str(intent.request.request_id),
            EFaxInboundObservationRequest.box_id == intent.box_id,
            EFaxInboundObservationRequest.owner_id == intent.owner_id,
        )
        .with_for_update(read=True)
    )
    if (
        request is None
        or request.grant_id != intent.grant_id
        or request.request != intent.request.model_dump(mode="json")
    ):
        error("efax_inbound_source_invalid")
    _grant(s, intent.box_id, intent.owner_id, intent.grant_id, current=current)
    try:
        checked = ListSnapshot.model_validate(snapshot.model_dump(mode="python"))
        if checked.request != intent.request or not _now(s) - timedelta(
            minutes=5
        ) <= checked.observed_at <= _now(s) + timedelta(seconds=5):
            raise ValueError
    except Exception:
        error("efax_inbound_source_invalid")
    prior = s.scalar(
        select(EFaxInboundObservation).where(EFaxInboundObservation.request_id == request.id)
    )
    payload = checked.model_dump(mode="json")
    if prior:
        if prior.payload != payload:
            error("efax_inbound_source_invalid")
    else:
        s.add(
            EFaxInboundObservation(
                id=str(uuid4()),
                box_id=intent.box_id,
                owner_id=intent.owner_id,
                request_id=request.id,
                payload=payload,
                payload_sha256=digest("cosmas-efax-inbound-snapshot-payload.v1", payload),
                source_sha256=checked.source_sha256,
            )
        )
    s.commit()
    receipt = s.scalar(
        select(EFaxInboundReceipt).where(
            EFaxInboundReceipt.box_id == intent.box_id,
            EFaxInboundReceipt.owner_id == intent.owner_id,
            EFaxInboundReceipt.kind == "observe",
            EFaxInboundReceipt.result["observation_id"].as_string() == request.id,
        )
    )
    if receipt is None:
        error("efax_inbound_source_invalid")
    return {
        **_receipt(receipt),
        "state": "observed",
        "source_sha256": checked.source_sha256,
        "snapshot": _public_snapshot(checked),
    }


def _public_snapshot(snapshot):
    value = snapshot.model_dump(mode="json")
    # The full request includes private account/user-id/credential references.
    value["request"] = {
        k: value["request"][k] for k in ("request_id", "starts_at", "ends_at", "limit", "offset")
    }
    for field in ("starts_at", "ends_at"):
        value["request"][field] = canonical_public_timestamp(value["request"][field])
    return value


def resolve_observation(s, box, actor, *, key, current=None):
    _owner(s, box, actor, gated=False)
    _key(key)
    receipt = s.scalar(
        select(EFaxInboundReceipt).where(
            EFaxInboundReceipt.box_id == box,
            EFaxInboundReceipt.owner_id == actor,
            EFaxInboundReceipt.idempotency_key == key,
            EFaxInboundReceipt.kind == "observe",
        )
    )
    if receipt is None:
        return {
            "contract_version": 1,
            "scope": {"box_id": box, "owner_id": actor},
            "idempotency_key": key,
            "kind": "observe",
            "state": "not_found",
        }
    result = _receipt(receipt)
    request = s.get(EFaxInboundObservationRequest, result["observation_id"])
    try:
        if request is None:
            raise ValueError
        _grant(s, box, actor, request.grant_id, current=current)
        _, snapshot = _observation(s, box, actor, request.id)
        result.update(
            state="observed",
            source_sha256=snapshot.source_sha256,
            snapshot=_public_snapshot(snapshot),
        )
    except ws.WorkspaceError:
        result.update(
            state="unavailable"
            if request
            and s.scalar(
                select(EFaxInboundObservation.id).where(
                    EFaxInboundObservation.request_id == request.id
                )
            )
            else "unconfirmed",
            source_withheld=True,
        )
    return result


def _revision(s, box, actor, ticket_id, revision_id=None, *, current=None, active=True):
    _owner(s, box, actor, writing=True, gated=active)
    t = s.scalar(
        select(Ticket)
        .where(
            Ticket.id == ticket_id,
            Ticket.box_id == box,
            Ticket.created_by_principal_id == actor,
            Ticket.lane == LANE,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if t is None:
        error("efax_inbound_unavailable", 404)
    r = s.get(EFaxInboundImageRevision, revision_id or t.current_revision_id)
    a = s.get(ActionRevision, r.action_revision_id) if r else None
    if (
        r is None
        or r.box_id != box
        or r.owner_id != actor
        or r.ticket_id != t.id
        or a is None
        or a.payload_hash != r.action_sha256
        or payload_hash(a.payload) != a.payload_hash
        or a.invalidated
        or a.action_type != "efax_inbound_image"
        or a.created_by_principal_id != actor
        or t.current_revision_id != r.action_revision_id
        or t.patient_link_id is not None
        or t.appointment_id is not None
    ):
        error("efax_inbound_revision_changed")
    try:
        command = ImageCommand.model_validate(r.command)
        obs, snapshot = _observation(s, box, actor, r.observation_id)
        selected = next(item for item in snapshot.items if str(item.fax_id) == r.fax_id)
        if (
            command.commitment() != r.command_sha256
            or str(command.operation_id) != r.operation_id
            or str(command.fax_id) != r.fax_id
            or command.source_sha256 != obs.source_sha256
            or command.selection != snapshot.request.selection
            or digest("cosmas-efax-inbound-fax.v1", selected.model_dump(mode="json"))
            != r.fax_sha256
            or a.payload
            != {
                "contract_version": 1,
                "inbound_revision_id": r.action_revision_id,
                "command_sha256": r.command_sha256,
            }
        ):
            raise ValueError
    except Exception:
        error("efax_inbound_source_invalid")
    g = s.get(EFaxInboundGrant, r.grant_id)
    if (
        g is None
        or g.box_id != box
        or g.owner_id != actor
        or g.selection != command.selection.model_dump(mode="json")
    ):
        error("efax_inbound_grant_changed")
    if active:
        _current(s, g, current, image=True)
    return t, r, g, command, snapshot


def propose_image(
    s,
    box,
    actor,
    *,
    key,
    grant_id,
    observation_id,
    observation_sha256,
    fax_id,
    fax_sha256,
    current=None,
):
    g = _grant(s, box, actor, grant_id, current=current, image=True, writing=True)
    request = dict(
        grant_id=grant_id,
        observation_id=observation_id,
        observation_sha256=observation_sha256,
        fax_id=fax_id,
        fax_sha256=fax_sha256,
    )
    previous, sha = _previous(s, box, actor, "propose", key, request)
    if previous:
        return _receipt(previous)
    obs, snapshot = _observation(s, box, actor, observation_id)
    parent = s.get(EFaxInboundObservationRequest, observation_id)
    try:
        selected = next(item for item in snapshot.items if str(item.fax_id) == fax_id)
        if (
            parent is None
            or parent.grant_id != g.id
            or obs.source_sha256 != observation_sha256
            or snapshot.request.selection != ConnectionSelection.model_validate(g.selection)
            or digest("cosmas-efax-inbound-fax.v1", selected.model_dump(mode="json")) != fax_sha256
            or selected.fax_status == "NOT_STORED"
            or not 1 <= selected.pages <= 50
            or not _now(s) - timedelta(minutes=5)
            <= snapshot.observed_at
            <= _now(s) + timedelta(seconds=5)
        ):
            raise ValueError
    except Exception:
        error("efax_inbound_source_invalid")
    ticket_id, revision_id, operation_id = str(uuid4()), str(uuid4()), str(uuid4())
    command = ImageCommand(
        selection=snapshot.request.selection,
        operation_id=UUID(operation_id),
        source_sha256=snapshot.source_sha256,
        fax_id=fax_id,
        expires_at=min(_now(s) + timedelta(minutes=5), g.expires_at),
    )
    payload = {
        "contract_version": 1,
        "inbound_revision_id": revision_id,
        "command_sha256": command.commitment(),
    }
    owner = s.get(Principal, actor)
    if owner is None:
        error("efax_inbound_unavailable", 404)
    ticket = Ticket(
        id=ticket_id,
        box_id=box,
        lane=LANE,
        state="pending_approval",
        version=1,
        created_by_principal_id=actor,
        current_revision_id=revision_id,
    )
    action = ActionRevision(
        id=revision_id,
        ticket_id=ticket_id,
        box_id=box,
        revision_number=1,
        action_type="efax_inbound_image",
        target_ref="private-inbound-fax",
        content="Private received-fax image acquisition; downloading marks the fax downloaded/read.",
        payload=payload,
        payload_hash=payload_hash(payload),
        automation_class="hitl_required",
        policy_version=owner.policy_version,
        charter_version=owner.charter_version,
        config_version=owner.config_version,
        created_by_principal_id=actor,
    )
    s.add(ticket)
    s.flush()
    s.add(action)
    s.flush()
    s.add(
        EFaxInboundImageRevision(
            action_revision_id=revision_id,
            box_id=box,
            owner_id=actor,
            ticket_id=ticket_id,
            grant_id=g.id,
            observation_id=observation_id,
            operation_id=operation_id,
            fax_id=fax_id,
            fax_sha256=fax_sha256,
            action_sha256=action.payload_hash,
            command=command.model_dump(mode="json"),
            command_sha256=command.commitment(),
        )
    )
    result = _record(
        s,
        box,
        actor,
        "propose",
        key,
        request,
        {
            "ticket_id": ticket_id,
            "revision_id": revision_id,
            "version": 1,
            "state": "approval_required",
            "command_sha256": command.commitment(),
            "side_effect": command.side_effect,
            "expires_at": command.expires_at.isoformat(),
        },
        sha,
    )
    s.commit()
    return result


def decide_image(
    s,
    box,
    actor,
    *,
    key,
    ticket_id,
    revision_id,
    expected_version,
    choice,
    reviewed_mark_read,
    current=None,
):
    t, r, _, command, _ = _revision(s, box, actor, ticket_id, revision_id, current=current)
    request = dict(
        ticket_id=ticket_id,
        revision_id=revision_id,
        expected_version=expected_version,
        choice=choice,
        reviewed_mark_read=reviewed_mark_read,
    )
    previous, sha = _previous(s, box, actor, "decide", key, request)
    if previous:
        return _receipt(previous)
    if (
        type(expected_version) is not int
        or t.version != expected_version
        or t.state != "pending_approval"
        or choice not in ("approve", "reject")
        or type(reviewed_mark_read) is not bool
        or choice == "approve"
        and reviewed_mark_read is not True
        or _now(s) >= command.expires_at
    ):
        error("efax_inbound_revision_changed")
    decision = Decision(
        id=str(uuid4()),
        box_id=box,
        ticket_id=t.id,
        action_revision_id=r.action_revision_id,
        actor_principal_id=actor,
        kind=choice,
        note=None,
    )
    s.add(decision)
    t.state, t.version = ("approved" if choice == "approve" else "rejected"), t.version + 1
    if choice == "approve":
        s.add(
            Operation(
                id=r.operation_id,
                box_id=box,
                ticket_id=t.id,
                action_revision_id=r.action_revision_id,
                idempotency_key="efax-inbound:" + r.operation_id,
                adapter=ADAPTER,
                status="pending",
                attempt_count=0,
            )
        )
    result = _record(
        s,
        box,
        actor,
        "decide",
        key,
        request,
        {
            "ticket_id": t.id,
            "revision_id": r.action_revision_id,
            "version": t.version,
            "state": t.state,
            "decision_id": decision.id,
            "approval_sha256": sha if choice == "approve" else None,
        },
        sha,
    )
    s.commit()
    return result


def claim_image(
    s, box, actor, *, key, ticket_id, revision_id, expected_version, approval_sha256, current=None
):
    t, r, g, command, snapshot = _revision(s, box, actor, ticket_id, revision_id, current=current)
    request = dict(
        ticket_id=ticket_id,
        revision_id=revision_id,
        expected_version=expected_version,
        approval_sha256=approval_sha256,
    )
    previous, sha = _previous(s, box, actor, "acquire", key, request)
    if previous:
        return resolve_image(s, box, actor, key=key, current=current), None
    approval_receipt = s.scalar(
        select(EFaxInboundReceipt).where(
            EFaxInboundReceipt.box_id == box,
            EFaxInboundReceipt.owner_id == actor,
            EFaxInboundReceipt.kind == "decide",
            EFaxInboundReceipt.request_sha256 == approval_sha256,
        )
    )
    decision = (
        s.get(Decision, approval_receipt.result.get("decision_id")) if approval_receipt else None
    )
    op = s.scalar(select(Operation).where(Operation.id == r.operation_id).with_for_update())
    now = _now(s)
    if (
        type(expected_version) is not int
        or t.version != expected_version
        or t.state != "approved"
        or op is None
        or op.adapter != ADAPTER
        or op.attempt_count != 0
        or op.status != "pending"
        or approval_receipt is None
        or approval_receipt.request.get("choice") != "approve"
        or approval_receipt.request.get("revision_id") != r.action_revision_id
        or decision is None
        or decision.kind != "approve"
        or decision.actor_principal_id != actor
        or decision.action_revision_id != r.action_revision_id
        or now >= command.expires_at
        or s.scalar(
            select(EFaxInboundAcquisition.operation_id).where(
                EFaxInboundAcquisition.box_id == box,
                EFaxInboundAcquisition.account_sha256 == g.account_sha256,
                EFaxInboundAcquisition.fax_id == r.fax_id,
            )
        )
        is not None
    ):
        error("efax_inbound_acquisition_fenced")
    approval = ImageApproval(
        operation_id=command.operation_id,
        command_sha256=command.commitment(),
        selection_sha256=command.selection.commitment(),
        operator_id=actor,
        approved_at=approval_receipt.created_at,
        expires_at=command.expires_at,
        reviewed_exact_fax=True,
        approved_mark_downloaded_or_read=True,
    )
    token = str(uuid4())
    claim = EFaxInboundAcquisition(
        operation_id=op.id,
        ticket_id=t.id,
        action_revision_id=r.action_revision_id,
        box_id=box,
        owner_id=actor,
        account_sha256=g.account_sha256,
        fax_id=r.fax_id,
        token_sha256=hashlib.sha256(token.encode()).hexdigest(),
        approval=approval.model_dump(mode="json"),
        approval_sha256=approval_sha256,
        claimed_at=now,
        deadline=min(now + timedelta(seconds=45), command.expires_at),
    )
    op.status, op.attempt_count, op.started_at = "running", 1, now
    t.version += 1
    s.add(claim)
    result = _record(
        s,
        box,
        actor,
        "acquire",
        key,
        request,
        {
            "ticket_id": t.id,
            "revision_id": r.action_revision_id,
            "operation_id": op.id,
            "version": t.version,
            "state": "claimed",
            "retry_allowed": False,
        },
        sha,
    )
    invocation = Invocation(box, actor, g.id, op.id, token, command, approval, snapshot)
    s.commit()
    return result, invocation


def _claimed(s, invocation):
    row = s.scalar(
        select(EFaxInboundAcquisition)
        .where(
            EFaxInboundAcquisition.operation_id == invocation.operation_id,
            EFaxInboundAcquisition.box_id == invocation.box_id,
            EFaxInboundAcquisition.owner_id == invocation.owner_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        row is None
        or row.token_sha256 != hashlib.sha256(invocation.token.encode()).hexdigest()
        or invocation.command.operation_id != invocation.approval.operation_id
        or str(invocation.command.operation_id) != row.operation_id
        or row.approval != invocation.approval.model_dump(mode="json")
    ):
        error("efax_inbound_claim_fenced")
    r = s.get(EFaxInboundImageRevision, row.action_revision_id)
    if (
        r is None
        or r.grant_id != invocation.grant_id
        or r.command != invocation.command.model_dump(mode="json")
        or r.command_sha256 != invocation.command.commitment()
        or invocation.snapshot.source_sha256 != invocation.command.source_sha256
    ):
        error("efax_inbound_claim_fenced")
    _, snapshot = _observation(s, invocation.box_id, invocation.owner_id, r.observation_id)
    if snapshot.model_dump(mode="json") != invocation.snapshot.model_dump(mode="json"):
        error("efax_inbound_claim_fenced")
    return row


def authorize_invocation(s, invocation, *, current=None):
    _owner(s, invocation.box_id, invocation.owner_id)
    row = _claimed(s, invocation)
    g = _grant(
        s, invocation.box_id, invocation.owner_id, invocation.grant_id, current=current, image=True
    )
    if (
        row.account_sha256 != g.account_sha256
        or _now(s) >= row.deadline
        or s.get(EFaxInboundOutcome, row.operation_id)
    ):
        error("efax_inbound_claim_fenced")
    return True


def mark_invocation(s, invocation, *, current=None):
    """Must finish its commit before the adapter issues its single image GET."""
    _owner(s, invocation.box_id, invocation.owner_id, writing=True)
    authorize_invocation(s, invocation, current=current)
    if s.get(EFaxInboundInvocation, invocation.operation_id) is not None:
        error("efax_inbound_acquisition_fenced")
    s.add(
        EFaxInboundInvocation(
            operation_id=invocation.operation_id,
            box_id=invocation.box_id,
            owner_id=invocation.owner_id,
            started_at=_now(s),
        )
    )
    op = s.get(Operation, invocation.operation_id)
    if op is None:
        error("efax_inbound_claim_fenced")
    op.status = "unknown"
    s.commit()
    return True


def settle_image(s, invocation, receipt, document=None):
    """Persist validated late evidence privately, including after authority revocation."""
    row = _claimed(s, invocation)
    try:
        checked = ImageReceipt.model_validate(receipt.model_dump(mode="python"))
        if (
            str(checked.operation_id) != invocation.operation_id
            or checked.command_sha256 != invocation.command.commitment()
            or checked.selection_sha256 != invocation.command.selection.commitment()
            or checked.fax_id != invocation.command.fax_id
        ):
            raise ValueError
        marker = s.get(EFaxInboundInvocation, row.operation_id)
        if checked.attempted != (marker is not None):
            raise ValueError
        if checked.state == "acquired":
            expected_source = digest(
                "cosmas-efax-inbound-image.v1",
                {
                    "command_sha256": invocation.command.commitment(),
                    "list_source_sha256": invocation.snapshot.source_sha256,
                    "fax_id": str(checked.fax_id),
                    "response_sha256": checked.response_sha256,
                    "document_sha256": checked.document_sha256,
                    "byte_length": checked.byte_length,
                    "pages": checked.pages,
                },
            )
            selected = next(
                item for item in invocation.snapshot.items if item.fax_id == checked.fax_id
            )
            if (
                type(document) is not bytes
                or not 1 <= len(document) <= MAX_PDF_BYTES
                or not document.startswith(b"%PDF-")
                or len(document) != checked.byte_length
                or hashlib.sha256(document).hexdigest() != checked.document_sha256
                or checked.source_sha256 != expected_source
                or checked.pages != selected.pages
            ):
                raise ValueError
        elif document is not None:
            raise ValueError
    except Exception:
        error("efax_inbound_result_invalid")
    value = checked.model_dump(mode="json")
    sha = digest("cosmas-efax-inbound-receipt.v1", value)
    previous = s.get(EFaxInboundOutcome, row.operation_id)
    if previous:
        if (
            previous.receipt_sha256 != sha
            or previous.receipt != value
            or previous.document != document
        ):
            error("efax_inbound_result_conflict")
        return {
            "contract_version": 1,
            "operation_id": row.operation_id,
            "state": previous.state,
            "receipt_sha256": previous.receipt_sha256,
        }
    s.add(
        EFaxInboundOutcome(
            operation_id=row.operation_id,
            box_id=row.box_id,
            owner_id=row.owner_id,
            state=checked.state,
            receipt=value,
            receipt_sha256=sha,
            document=document,
            document_sha256=checked.document_sha256,
            byte_length=checked.byte_length,
            pages=checked.pages,
        )
    )
    op = s.get(Operation, row.operation_id)
    if op is None:
        error("efax_inbound_claim_fenced")
    op.status = (
        "succeeded"
        if checked.state == "acquired"
        else ("unknown" if checked.state == "outcome_unconfirmed" else "failed")
    )
    op.result_receipt_hash, op.completed_at = sha, _now(s)
    s.commit()
    return {
        "contract_version": 1,
        "operation_id": row.operation_id,
        "state": checked.state,
        "receipt_sha256": sha,
    }


def resolve_image(s, box, actor, *, key, current=None):
    _owner(s, box, actor, gated=False)
    _key(key)
    receipt = s.scalar(
        select(EFaxInboundReceipt).where(
            EFaxInboundReceipt.box_id == box,
            EFaxInboundReceipt.owner_id == actor,
            EFaxInboundReceipt.idempotency_key == key,
            EFaxInboundReceipt.kind == "acquire",
        )
    )
    if receipt is None:
        return {
            "contract_version": 1,
            "scope": {"box_id": box, "owner_id": actor},
            "idempotency_key": key,
            "kind": "acquire",
            "state": "not_found",
            "retry_allowed": False,
            "content_available": False,
            "source_withheld": False,
            "document": None,
        }
    result = _receipt(receipt)
    claim = s.get(EFaxInboundAcquisition, result["operation_id"])
    outcome = s.get(EFaxInboundOutcome, result["operation_id"])
    marker = s.get(EFaxInboundInvocation, result["operation_id"])
    result.update(
        state="outcome_unconfirmed" if marker else "claimed",
        retry_allowed=False,
        content_available=False,
        source_withheld=False,
        document=None,
    )
    if outcome:
        result.update(state=outcome.state, receipt_sha256=outcome.receipt_sha256)
    # Retained state itself is a commitment, not fresh content authority.
    try:
        if claim is None:
            error("efax_inbound_source_invalid")
        r = s.get(EFaxInboundImageRevision, claim.action_revision_id)
        if r is None:
            error("efax_inbound_source_invalid")
        _grant(s, box, actor, r.grant_id, current=current, image=True)
        if outcome:
            result["content_available"] = outcome.state == "acquired"
            if result["content_available"]:
                checked = ImageReceipt.model_validate(outcome.receipt)
                if (
                    outcome.document is None
                    or checked.document_sha256 != outcome.document_sha256
                    or checked.byte_length != outcome.byte_length
                    or checked.pages != outcome.pages
                    or outcome.receipt_sha256
                    != digest("cosmas-efax-inbound-receipt.v1", outcome.receipt)
                    or hashlib.sha256(outcome.document).hexdigest() != outcome.document_sha256
                    or len(outcome.document) != outcome.byte_length
                ):
                    error("efax_inbound_source_invalid")
                result["document"] = {
                    "sha256": outcome.document_sha256,
                    "byte_length": outcome.byte_length,
                    "pages": outcome.pages,
                }
    except ws.WorkspaceError:
        result["content_available"] = False
        result["document"] = None
        result["source_withheld"] = True
    return result


def document(s, box, actor, operation_id, *, current=None):
    _owner(s, box, actor)
    claim = s.scalar(
        select(EFaxInboundAcquisition)
        .where(
            EFaxInboundAcquisition.operation_id == operation_id,
            EFaxInboundAcquisition.box_id == box,
            EFaxInboundAcquisition.owner_id == actor,
        )
        .with_for_update(read=True)
    )
    if claim is None:
        error("efax_inbound_unavailable", 404)
    r = s.get(EFaxInboundImageRevision, claim.action_revision_id)
    _grant(s, box, actor, r.grant_id, current=current, image=True)
    outcome = s.get(EFaxInboundOutcome, operation_id)
    if outcome is None or outcome.state != "acquired" or outcome.document is None:
        error("efax_inbound_document_unavailable")
    checked = ImageReceipt.model_validate(outcome.receipt)
    if (
        len(outcome.document) != outcome.byte_length
        or hashlib.sha256(outcome.document).hexdigest() != outcome.document_sha256
        or outcome.receipt_sha256 != digest("cosmas-efax-inbound-receipt.v1", outcome.receipt)
        or checked.document_sha256 != outcome.document_sha256
    ):
        error("efax_inbound_source_invalid")
    return outcome.document


def recover(s, box, actor, *, key):
    """Recover only the original commitment/result; never authorize fresh work."""
    _owner(s, box, actor, gated=False)
    _key(key)
    receipt = s.scalar(
        select(EFaxInboundReceipt).where(
            EFaxInboundReceipt.box_id == box,
            EFaxInboundReceipt.owner_id == actor,
            EFaxInboundReceipt.idempotency_key == key,
        )
    )
    if receipt is None:
        return {
            "contract_version": 1,
            "scope": {"box_id": box, "owner_id": actor},
            "idempotency_key": key,
            "kind": "recover",
            "state": "not_found",
        }
    return {**_receipt(receipt), "kind": receipt.kind, "historical": True}


def proposal(s, box, actor, ticket_id, *, current=None):
    _owner(s, box, actor, gated=False)
    t, r, g, command, snapshot = _revision(
        s,
        box,
        actor,
        ticket_id,
        current=current,
        active=False,
    )
    result = {
        "contract_version": 1,
        "scope": {"box_id": box, "owner_id": actor},
        "ticket_id": t.id,
        "revision_id": r.action_revision_id,
        "version": t.version,
        "state": t.state,
        "command_sha256": r.command_sha256,
        "expires_at": canonical_public_timestamp(command.expires_at),
        "side_effect": command.side_effect,
        "source_withheld": True,
    }
    try:
        _current(s, g, current, image=True)
        if _now(s) >= command.expires_at:
            error("efax_inbound_approval_expired")
        selected = next(item for item in snapshot.items if str(item.fax_id) == r.fax_id)
        result.update(
            source_withheld=False,
            fax=selected.model_dump(mode="json"),
            fax_sha256=r.fax_sha256,
            observation_id=r.observation_id,
            observation_sha256=snapshot.source_sha256,
            account_label=g.label,
        )
    except ws.WorkspaceError:
        result["state"] = "unavailable"
    return result
