"""Private incoming evidence and local human review; no sender or vendor mutation.

Only an internal caller can ingest a snapshot. The independent reviewed read
grant must still be current when evidence commits. A browser cannot provide a
snapshot, an endpoint, credentials or new read authority.
"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import NoReturn
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from sqlalchemy import func, select

from cosmas_os.api import inbox_work_schemas as schema
from cosmas_os.api import vendor_work_schemas as public
from cosmas_os.application import vendor_settings
from cosmas_os.application import vendor_work as common
from cosmas_os.application import workspace as ws
from cosmas_os.inbox_models import InboxEvent, InboxItem, InboxSource
from cosmas_os.models import EncounterWorkspace
from cosmas_os.ports.scribe_capture import ProtectedModel
from cosmas_os.ports.vendor_connectors import ConnectionSelection, Timestamp, digest
from cosmas_os.ports.vendor_inbox import (
    SpruceInboxReadBinding,
    SpruceInboxSnapshot,
    compare_inbox_snapshots,
)
from cosmas_os.vendor_models import VendorConnectionVersion, VendorCorrespondenceVersion

MAX_EVENTS = 100
MAX_SOURCES = 50
SAFE_READ_ERRORS = frozenset(
    {
        "authority_required",
        "reference_unavailable",
        "response_invalid",
        "response_too_large",
        "provider_throttled",
        "provider_unavailable",
        "request_timeout",
        "source_scope_changed",
    }
)


@dataclass(frozen=True)
class InboxPolicy:
    enabled: bool = False

    def __post_init__(self):
        if type(self.enabled) is not bool:
            raise ValueError("Explicit inbox feature policy required")


DEFAULT_POLICY = InboxPolicy()


class InboxReadGrant(ProtectedModel):
    grant_id: UUID
    binding: SpruceInboxReadBinding
    label: str = Field(strict=True, min_length=1, max_length=80)
    reviewed_by: UUID
    review_reference: str = Field(
        strict=True, min_length=1, max_length=120, pattern=r"^[A-Za-z0-9:_-]+$"
    )
    reviewed_inbox_read: public.Confirmed
    reviewed_at: Timestamp
    expires_at: Timestamp
    correspondence_public_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def explicit_owner_authority(self):
        if (
            self.reviewed_by != self.binding.selection.owner_id
            or self.expires_at <= self.reviewed_at
        ):
            raise ValueError("Owner-reviewed inbox read authority required")
        return self

    def commitment(self):
        return digest("cosmas-inbox-read-grant.v1", self.model_dump(mode="json"))


class InboxRegistry:
    def __init__(self, grants=()):
        values = {}
        for supplied in grants:
            if type(supplied) is not InboxReadGrant:
                raise ValueError("Exact server-installed inbox grants required")
            value = InboxReadGrant.model_validate(supplied.model_dump(mode="python"))
            if str(value.grant_id) in values:
                raise ValueError("Duplicate inbox grant")
            values[str(value.grant_id)] = value
        if len(values) > 100:
            raise ValueError("At most100 reviewed inbox sources")
        self.grants = MappingProxyType(values)


EMPTY_REGISTRY = InboxRegistry()


def no_registry():
    return EMPTY_REGISTRY


def error(code, status=409) -> NoReturn:
    raise ws.WorkspaceError(code, status)


def final_authority(s):
    check = s.info.get("inbox_final_authority")
    if check is not None:
        check()


def owner(s, box, actor, *, writing=False):
    try:
        return vendor_settings.owner(s, box, actor, writing=writing)
    except ws.WorkspaceError:
        error("inbox_unavailable", 404)


def scope(box, actor):
    return {"box_id": box, "owner_id": actor}


def grant_current(s, box, actor, grant, registry=no_registry):
    """Separate read grant, current native account, and exact reviewed mapping."""
    registered = registry()
    if type(registered) is not InboxRegistry:
        error("inbox_binding_unavailable")
    current = registered.grants.get(str(grant.grant_id))
    if current is None or current != grant or current.commitment() != grant.commitment():
        error("inbox_binding_unavailable")
    binding = grant.binding
    now = common._clock(s)
    if (str(binding.selection.box_id), str(binding.selection.owner_id)) != (
        box,
        actor,
    ) or not grant.reviewed_at <= now < grant.expires_at:
        error("inbox_binding_unavailable")
    owner(s, box, actor)
    vendor_settings.patient(s, box, str(binding.patient_link_id))
    native = s.scalar(
        select(VendorConnectionVersion)
        .where(VendorConnectionVersion.id == str(binding.selection.connection_id))
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    correspondence = s.scalar(
        select(VendorCorrespondenceVersion)
        .where(VendorCorrespondenceVersion.id == str(binding.correspondence_version_id))
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if (
        native is None
        or correspondence is None
        or not native.is_current
        or native.revoked_at
        or not correspondence.is_current
        or correspondence.revoked_at
        or correspondence.expires_at <= now
    ):
        error("inbox_binding_unavailable")
    if (
        ConnectionSelection.model_validate(native.private_selection) != binding.selection
        or native.private_sha256 != binding.selection.commitment()
    ):
        error("inbox_binding_unavailable")
    if (
        correspondence.box_id,
        correspondence.owner_id,
        correspondence.connection_version_id,
        correspondence.patient_link_id,
        correspondence.private_sha256,
        correspondence.public_sha256,
    ) != (
        box,
        actor,
        native.id,
        str(binding.patient_link_id),
        binding.correspondence_sha256,
        grant.correspondence_public_sha256,
    ):
        error("inbox_binding_unavailable")
    if digest(
        "cosmas-vendor-correspondence.v1", correspondence.private_proof
    ) != correspondence.private_sha256 or correspondence.private_proof.get("destination") != {
        "channel": "secure",
        "contact_id": binding.contact_id,
    }:
        error("inbox_binding_unavailable")
    # Outbound read_enabled/write_enabled flags intentionally confer no inbox
    # authority. The separate reviewed grant above is mandatory in every case.
    return grant


def item(s, box, actor, iid, *, writing=False):
    owner(s, box, actor, writing=writing)
    row = s.scalar(
        select(InboxItem)
        .where(InboxItem.id == iid, InboxItem.box_id == box, InboxItem.owner_id == actor)
        .with_for_update(read=not writing)
        .execution_options(populate_existing=True)
    )
    if row is None:
        error("inbox_unavailable", 404)
    try:
        vendor_settings.patient(s, box, row.patient_link_id)
        grant = InboxReadGrant.model_validate(row.grant)
        if grant.commitment() != row.grant_sha256:
            error("inbox_integrity", 503)
    except ws.WorkspaceError:
        error("inbox_unavailable", 404)
    return row


def source_snapshot(row):
    if digest("cosmas-inbox-stored-snapshot.v1", row.snapshot) != row.snapshot_sha256:
        error("inbox_integrity", 503)
    value = SpruceInboxSnapshot.model_validate(row.snapshot)
    if value.source_sha256 != row.source_sha256:
        error("inbox_integrity", 503)
    return value


def authorize_read(s, grant, *, registry=no_registry, policy=DEFAULT_POLICY):
    """Fresh callback for the adapter before credentials, each GET and disclosure."""
    if type(grant) is not InboxReadGrant or not policy.enabled:
        error("inbox_feature_disabled", 403)
    box, actor = str(grant.binding.selection.box_id), str(grant.binding.selection.owner_id)
    grant_current(s, box, actor, grant, registry)
    row = s.scalar(
        select(InboxItem).where(
            InboxItem.box_id == box,
            InboxItem.owner_id == actor,
            InboxItem.grant_id == str(grant.grant_id),
        )
    )
    if row is not None and (
        row.grant_sha256 != grant.commitment()
        or row.version >= 92
        or s.scalar(
            select(func.count()).select_from(InboxSource).where(InboxSource.item_id == row.id)
        )
        >= MAX_SOURCES
    ):
        error("inbox_history_limit")
    final_authority(s)
    grant_current(s, box, actor, grant, registry)
    return True


def head(s, row):
    value = s.get(InboxSource, row.current_source_id) if row.current_source_id else None
    if value is not None and value.item_id != row.id:
        error("inbox_integrity", 503)
    return value


def latest(s, row, kind):
    return s.scalar(
        select(InboxEvent)
        .where(
            InboxEvent.item_id == row.id,
            InboxEvent.origin == "human",
            InboxEvent.kind == kind,
            InboxEvent.source_id == row.current_source_id,
            InboxEvent.response["outcome"].astext == "recorded",
        )
        .order_by(InboxEvent.version.desc())
        .limit(1)
    )


def workspace_current(s, row, review):
    if review is None:
        return False
    q = review.request
    w = s.scalar(
        select(EncounterWorkspace)
        .where(EncounterWorkspace.id == q["workspace_id"])
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if w is None or (w.box_id, w.owner_id, w.patient_link_id, w.revision) != (
        row.box_id,
        row.owner_id,
        row.patient_link_id,
        q["expected_workspace_revision"],
    ):
        return False
    try:
        ws._encounter(s, row.box_id, w.appointment_id, w.patient_link_id, owner=w.owner_id)
    except ws.WorkspaceError:
        return False
    return True


def chain(s, row):
    review, triage, result, verified = [
        latest(s, row, k) for k in ("review", "triage", "result", "verify")
    ]
    if (
        triage
        and triage.request["classification"] == "administrative_review"
        and (review is None or triage.version <= review.version)
    ):
        triage = None
    if result and (
        triage is None
        or result.request["triage_receipt_id"] != triage.id
        or result.version <= triage.version
    ):
        result = None
    if verified and (
        result is None
        or verified.request["result_receipt_id"] != result.id
        or verified.version <= result.version
    ):
        verified = None
    return review, triage, result, verified


def summary(s, row, registry=no_registry):
    grant = InboxReadGrant.model_validate(row.grant)
    try:
        grant_current(s, row.box_id, row.owner_id, grant, registry)
        current = True
    except ws.WorkspaceError:
        current = False
    source = head(s, row)
    snapshot = source_snapshot(source) if source else None
    review, triage, result, verified = chain(s, row)
    workspace_ok = workspace_current(s, row, review)
    state = "needs_review"
    if row.read_issue or row.source_conflict or snapshot and snapshot.incomplete_content:
        state = "needs_human"
    elif review is not None and workspace_ok:
        state = "reviewed"
    if triage is not None:
        state = (
            "triaged"
            if triage.request["classification"] == "administrative_review" and workspace_ok
            else "needs_human"
        )
    if (
        result is not None
        and triage is not None
        and result.request["triage_receipt_id"] == triage.id
    ):
        state = (
            "result_recorded"
            if result.request["disposition"] == "local_review_complete" and workspace_ok
            else "needs_human"
        )
        if (
            verified is not None
            and verified.request["result_receipt_id"] == result.id
            and state == "result_recorded"
        ):
            state = "closed_local_review"
    if not current or row.read_issue or row.source_conflict:
        state = "needs_human"
    elif review is not None and not workspace_ok:
        state = "needs_review"
    return schema.Summary.model_validate(
        {
            "item_id": row.id,
            "version": row.version,
            "label": grant.label,
            "patient_link_id": row.patient_link_id,
            "source_id": source.id if source else None,
            "source_sha256": source.source_sha256 if source else None,
            "state": state,
            "source_conflict": row.source_conflict,
            "read_issue": row.read_issue,
            "binding_current": current,
            "incomplete_content": snapshot.incomplete_content if snapshot else True,
            "workspace_id": review.request["workspace_id"] if review else None,
            "workspace_current": workspace_ok,
            "classification": triage.request["classification"] if triage else None,
            "human_review_required": True,
            "vendor_latest_state_verified": False,
            "external_action_performed": False,
            "handoff_available": False,
        }
    ).public()


def source_metadata(row):
    p = source_snapshot(row)
    return {
        "source_id": row.id,
        "sequence": row.sequence,
        "source_sha256": row.source_sha256,
        "created_at": public.timestamp(p.created_at),
        "modified_at": public.timestamp(p.modified_at),
        "observed_at": public.timestamp(p.observed_at),
        "incomplete_content": p.incomplete_content,
    }


def source_view(item, row):
    p = source_snapshot(row)
    grant = InboxReadGrant.model_validate(item.grant)
    value = {
        **source_metadata(row),
        "vendor": "spruce",
        "conversation_id": p.binding.conversation_id,
        "item_reference": p.binding.item_id,
        "contact_id": p.binding.contact_id,
        "patient_link_id": item.patient_link_id,
        "correspondence_version_id": str(p.binding.correspondence_version_id),
        "correspondence_public_sha256": grant.correspondence_public_sha256,
        "text": p.text,
        **p.unsupported.model_dump(mode="json"),
        "conversation_archived": p.conversation_archived,
        "conversation_read_only": p.conversation_read_only,
        "item_response_sha256": p.item_response_sha256,
        "conversation_response_sha256": p.conversation_response_sha256,
        "trust": "untrusted_external_text",
    }
    value["projection_sha256"] = public.public_digest("cosmas-inbox-source-view.v1", value)
    return schema.Source.model_validate(value).public()


def response(event):
    domain = (
        "cosmas-inbox-receipt.v1" if event.origin == "human" else "cosmas-inbox-read-receipt.v1"
    )
    if public.public_digest(domain, event.response) != event.receipt_sha256:
        error("inbox_integrity", 503)
    value = {**event.response, "receipt_sha256": event.receipt_sha256}
    return schema.Receipt.model_validate(value).public() if event.origin == "human" else value


def effect(s, row, registry):
    v = summary(s, row, registry)
    return {k: v[k] for k in ("item_id", "version", "source_id", "source_sha256", "state")}


def saved(s, row, origin, kind, key, request_hash):
    found = s.scalar(
        select(InboxEvent).where(
            InboxEvent.item_id == row.id,
            InboxEvent.origin == origin,
            InboxEvent.idempotency_key == key,
        )
    )
    if found and (found.kind != kind or found.request_sha256 != request_hash):
        error("inbox_idempotency_conflict")
    return found


def ingest(s, grant, snapshot, key, *, registry=no_registry, policy=DEFAULT_POLICY):
    """Internal-only source admission. There is deliberately no corresponding HTTP route."""
    if type(grant) is not InboxReadGrant or type(snapshot) is not SpruceInboxSnapshot:
        error("inbox_invalid_internal_source", 400)
    snapshot = SpruceInboxSnapshot.model_validate(snapshot.model_dump(mode="python"))
    if snapshot.binding != grant.binding:
        error("inbox_binding_unavailable")
    return _read_event(s, grant, snapshot, key, None, registry, policy)


def read_failed(s, grant, key, safe_error, *, registry=no_registry, policy=DEFAULT_POLICY):
    """Retain only a closed failure code; no failed response, URL or raw body."""
    if type(grant) is not InboxReadGrant or safe_error not in SAFE_READ_ERRORS:
        error("inbox_invalid_internal_source", 400)
    return _read_event(s, grant, None, key, safe_error, registry, policy)


def _read_event(s, grant, snapshot, key, safe_error, registry, policy):
    from pydantic import TypeAdapter

    TypeAdapter(public.Key).validate_python(key)
    box, actor = str(grant.binding.selection.box_id), str(grant.binding.selection.owner_id)
    owner(s, box, actor, writing=True)
    row = s.scalar(
        select(InboxItem)
        .where(
            InboxItem.box_id == box,
            InboxItem.owner_id == actor,
            InboxItem.grant_id == str(grant.grant_id),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    q = {
        "grant_sha256": grant.commitment(),
        "snapshot_sha256": digest(
            "cosmas-inbox-stored-snapshot.v1", snapshot.model_dump(mode="json")
        )
        if snapshot
        else None,
        "safe_error": safe_error,
        "idempotency_key": key,
        "observed_at": snapshot.model_dump(mode="json")["observed_at"] if snapshot else None,
        "item_response_sha256": snapshot.item_response_sha256 if snapshot else None,
        "conversation_response_sha256": snapshot.conversation_response_sha256 if snapshot else None,
    }
    request_hash = public.public_digest("cosmas-inbox-ingest-request.v1", q)
    kind = "ingest" if snapshot else "read_failed"
    if row:
        prior = saved(s, row, "read", kind, key, request_hash)
        if prior:
            final_authority(s)
            return response(prior)
        if row.grant_sha256 != grant.commitment():
            error("inbox_binding_unavailable")
    if not policy.enabled:
        error("inbox_feature_disabled", 403)
    grant_current(s, box, actor, grant, registry)
    now = common._clock(s)
    if row is None:
        if (
            s.scalar(
                select(func.count())
                .select_from(InboxItem)
                .where(InboxItem.box_id == box, InboxItem.owner_id == actor)
            )
            >= 100
        ):
            error("inbox_history_limit")
        row = InboxItem(
            id=str(uuid4()),
            box_id=box,
            owner_id=actor,
            grant_id=str(grant.grant_id),
            grant_sha256=grant.commitment(),
            grant=grant.model_dump(mode="json"),
            patient_link_id=str(grant.binding.patient_link_id),
            version=1,
            current_source_id=None,
            source_conflict=False,
            read_issue=None,
            created_at=now,
        )
        s.add(row)
        s.flush()
    else:
        if row.version >= 92:
            error("inbox_history_limit")
        row.version += 1
    previous = head(s, row)
    source = None
    relation = "failure"
    if snapshot is not None:
        relation = (
            compare_inbox_snapshots(source_snapshot(previous), snapshot) if previous else "new"
        )
        if relation == "scope_changed":
            error("inbox_binding_unavailable")
        source = s.scalar(
            select(InboxSource).where(
                InboxSource.item_id == row.id, InboxSource.source_sha256 == snapshot.source_sha256
            )
        )
        if source is None:
            number = (
                s.scalar(
                    select(func.count())
                    .select_from(InboxSource)
                    .where(InboxSource.item_id == row.id)
                )
                + 1
            )
            if number > MAX_SOURCES:
                error("inbox_history_limit")
            payload = snapshot.model_dump(mode="json")
            source = InboxSource(
                id=str(uuid4()),
                box_id=box,
                owner_id=actor,
                item_id=row.id,
                sequence=number,
                source_sha256=snapshot.source_sha256,
                snapshot=payload,
                snapshot_sha256=digest("cosmas-inbox-stored-snapshot.v1", payload),
                recorded_at=now,
            )
            s.add(source)
            s.flush()
        if relation in {"new", "newer"}:
            row.current_source_id = source.id
            row.source_conflict = False
        elif relation == "conflict":
            # Keep the prior head. A conflicting arrival cannot win by arrival time.
            row.source_conflict = True
        if relation in {"new", "newer", "same"}:
            row.read_issue = None
    else:
        row.read_issue = safe_error
    # Persist the mutable projection before the immutable event's BEFORE guard;
    # the deferred chain guard still requires both in this same transaction.
    s.flush([row])
    eid = str(uuid4())
    value = {
        "id": eid,
        "item_id": row.id,
        "version": row.version,
        "outcome": relation,
        "source_id": source.id if source else None,
        "source_sha256": source.source_sha256 if source else None,
        "safe_error": safe_error,
        "observed_at": public.timestamp(snapshot.observed_at) if snapshot else None,
        "item_response_sha256": q["item_response_sha256"],
        "conversation_response_sha256": q["conversation_response_sha256"],
        "request_sha256": request_hash,
        "grant_sha256": grant.commitment(),
        "recorded_at": public.timestamp(now),
    }
    checksum = public.public_digest("cosmas-inbox-read-receipt.v1", value)
    event = InboxEvent(
        id=eid,
        box_id=box,
        owner_id=actor,
        item_id=row.id,
        version=row.version,
        origin="read",
        kind=kind,
        idempotency_key=key,
        request=q,
        request_sha256=request_hash,
        source_id=source.id if source else None,
        response=value,
        receipt_sha256=checksum,
        recorded_at=now,
    )
    s.add(event)
    s.flush()
    final_authority(s)
    grant_current(s, box, actor, grant, registry)
    s.commit()
    return response(event)


def _reason(s, row, kind, q, registry, policy):
    if q.expected_version != row.version:
        return "inbox_version_changed"
    source = head(s, row)
    if (q.source_id, q.source_sha256) != (
        source.id if source else None,
        source.source_sha256 if source else None,
    ):
        return "inbox_source_changed"
    if not policy.enabled:
        return "inbox_feature_disabled"
    if row.version >= (98 if kind in {"result", "verify"} else 96):
        return "inbox_history_limit"
    grant = InboxReadGrant.model_validate(row.grant)
    try:
        grant_current(s, row.box_id, row.owner_id, grant, registry)
    except ws.WorkspaceError:
        return "inbox_binding_unavailable"
    review, triage, result, _ = chain(s, row)
    blocked = (
        row.read_issue
        or row.source_conflict
        or source is None
        or source_snapshot(source).incomplete_content
    )
    if kind == "review":
        if source is None or row.source_conflict or row.read_issue:
            return "inbox_source_changed"
        w = s.scalar(
            select(EncounterWorkspace)
            .where(EncounterWorkspace.id == q.workspace_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if w is None or (
            w.box_id,
            w.owner_id,
            w.patient_link_id,
            w.revision,
            q.patient_link_id,
        ) != (
            row.box_id,
            row.owner_id,
            row.patient_link_id,
            q.expected_workspace_revision,
            row.patient_link_id,
        ):
            return "inbox_workspace_changed"
        try:
            ws._encounter(s, row.box_id, w.appointment_id, w.patient_link_id, owner=w.owner_id)
        except ws.WorkspaceError:
            return "inbox_workspace_changed"
    elif kind == "triage":
        if q.classification == "administrative_review":
            if blocked:
                return "inbox_exception_unresolved"
            if review is None or not workspace_current(s, row, review):
                return "inbox_review_required"
    elif kind == "result":
        if triage is None or (triage.id, triage.receipt_sha256) != (
            q.triage_receipt_id,
            q.triage_receipt_sha256,
        ):
            return "inbox_triage_required"
        if q.disposition == "local_review_complete" and (
            blocked
            or triage.request["classification"] != "administrative_review"
            or not workspace_current(s, row, review)
        ):
            return "inbox_exception_unresolved"
    else:
        if result is None or (result.id, result.receipt_sha256) != (
            q.result_receipt_id,
            q.result_receipt_sha256,
        ):
            return "inbox_result_changed"
        if (
            blocked
            or result.request["disposition"] != "local_review_complete"
            or triage is None
            or triage.id != result.request["triage_receipt_id"]
            or triage.request["classification"] != "administrative_review"
            or not workspace_current(s, row, review)
        ):
            return "inbox_exception_unresolved"
    return None


def command(s, box, actor, iid, kind, q, *, registry=no_registry, policy=DEFAULT_POLICY):
    if kind not in schema.COMMANDS or type(q) is not schema.COMMANDS[kind] or q.item_id != iid:
        error("invalid_inbox_request", 400)
    row = item(s, box, actor, iid, writing=True)
    request_hash = schema.request_digest(kind, scope(box, actor), q)
    previous = saved(s, row, "human", kind, q.idempotency_key, request_hash)
    if previous:
        final_authority(s)
        return response(previous)
    if row.version >= MAX_EVENTS:
        error("inbox_history_limit")
    if q.source_id is not None:
        proof = s.get(InboxSource, q.source_id)
        if proof is None or proof.item_id != iid or proof.source_sha256 != q.source_sha256:
            error("invalid_inbox_request", 400)
    elif q.source_sha256 is not None:
        error("invalid_inbox_request", 400)
    reason = _reason(s, row, kind, q, registry, policy)
    row.version += 1
    s.flush([row])
    eid, now = str(uuid4()), common._clock(s)
    value = {
        "contract_version": 1,
        "scope": scope(box, actor),
        "command_kind": kind,
        "idempotency_key": q.idempotency_key,
        "request_sha256": request_hash,
        "outcome": "rejected" if reason else "recorded",
        "effect": None,
        "rejection": reason,
        "receipt_id": eid,
        "recorded_at": public.timestamp(now),
    }
    event = InboxEvent(
        id=eid,
        box_id=box,
        owner_id=actor,
        item_id=iid,
        version=row.version,
        origin="human",
        kind=kind,
        idempotency_key=q.idempotency_key,
        request=q.public(),
        request_sha256=request_hash,
        source_id=q.source_id,
        response=value,
        receipt_sha256="0" * 64,
        recorded_at=now,
    )
    # The view includes this new immutable event; no text is copied into F8/audits.
    s.add(event)
    with s.no_autoflush:
        if not reason:
            value["effect"] = effect(s, row, registry)
            if kind == "triage":
                state = "triaged" if q.classification == "administrative_review" else "needs_human"
            elif kind == "result":
                state = (
                    "result_recorded" if q.disposition == "local_review_complete" else "needs_human"
                )
            else:
                state = "reviewed" if kind == "review" else "closed_local_review"
            value["effect"]["state"] = state
    event.response = dict(value)
    event.receipt_sha256 = public.public_digest("cosmas-inbox-receipt.v1", value)
    s.flush()
    final_authority(s)
    # A final grant loss turns an uncommitted admission into no admission. The
    # exact request remains safely resolvable/retryable; recorded rejection keys
    # are permanently inert even if state later becomes favorable.
    if not reason:
        grant_current(s, box, actor, InboxReadGrant.model_validate(row.grant), registry)
    s.commit()
    return response(event)


def resolve(s, box, actor, q, *, registry=no_registry, policy=DEFAULT_POLICY):
    row = item(s, box, actor, q.item_id)
    found = saved(s, row, "human", q.command_kind, q.idempotency_key, q.request_sha256)
    final_authority(s)
    return (
        response(found)
        if found
        else schema.Receipt.model_validate(
            {
                "contract_version": 1,
                "scope": scope(box, actor),
                "command_kind": q.command_kind,
                "idempotency_key": q.idempotency_key,
                "request_sha256": q.request_sha256,
                "outcome": "not_found",
                "effect": None,
                "rejection": None,
                "receipt_id": None,
                "recorded_at": None,
                "receipt_sha256": None,
            }
        ).public()
    )


def detail(s, box, actor, iid, *, registry=no_registry, policy=DEFAULT_POLICY):
    row = item(s, box, actor, iid)
    v = summary(s, row, registry)
    current = head(s, row)
    records = {k: latest(s, row, k) for k in schema.COMMANDS}
    active_triage = chain(s, row)[1]
    enabled = policy.enabled and v["binding_current"]
    open_ = enabled and row.version < 96
    value = {
        "contract_version": 1,
        "scope": scope(box, actor),
        "summary": v,
        "source": source_view(row, current) if current else None,
        "latest_review": response(records["review"]) if records["review"] else None,
        "latest_triage": response(records["triage"]) if records["triage"] else None,
        "latest_result": response(records["result"]) if records["result"] else None,
        "latest_verification": response(records["verify"]) if records["verify"] else None,
        "availability": {
            "review": bool(open_ and current and not row.source_conflict and not row.read_issue),
            "triage": bool(open_),
            "result": bool(enabled and row.version < 98 and active_triage),
            "verify": bool(
                enabled
                and row.version < 98
                and v["state"] == "result_recorded"
                and not v["incomplete_content"]
            ),
            "history_capacity_remaining": MAX_EVENTS - row.version,
        },
    }
    final_authority(s)
    return public.bounded(schema.Detail.model_validate(value).public(), 65536)


def catalog(s, box, actor, *, registry=no_registry, policy=DEFAULT_POLICY):
    owner(s, box, actor)
    rows = list(
        s.scalars(
            select(InboxItem)
            .where(InboxItem.box_id == box, InboxItem.owner_id == actor)
            .order_by(InboxItem.id)
            .limit(101)
        )
    )
    if len(rows) > 100:
        error("inbox_history_limit")
    values = []
    for row in rows:
        try:
            item(s, box, actor, row.id)
        except ws.WorkspaceError:
            continue
        values.append(summary(s, row, registry))
    final_authority(s)
    return public.bounded(
        schema.Catalog(
            contract_version=1,
            scope=schema.Scope(**scope(box, actor)),
            enabled=policy.enabled,
            items=values,
        ).public(),
        131072,
    )


def history(s, box, actor, iid, *, registry=no_registry, policy=DEFAULT_POLICY):
    item(s, box, actor, iid)
    sources = list(
        s.scalars(
            select(InboxSource).where(InboxSource.item_id == iid).order_by(InboxSource.sequence)
        )
    )
    events = list(
        s.scalars(select(InboxEvent).where(InboxEvent.item_id == iid).order_by(InboxEvent.version))
    )
    result = {
        "contract_version": 1,
        "scope": scope(box, actor),
        "item_id": iid,
        "sources": [source_metadata(v) for v in sources],
        "reads": [response(v) for v in events if v.origin == "read"],
        "commands": [
            {"request": v.request, "receipt": response(v)} for v in events if v.origin == "human"
        ],
    }
    final_authority(s)
    return public.bounded(schema.History.model_validate(result).public(), 2097152)


def read_source(s, box, actor, iid, sid, *, registry=no_registry, policy=DEFAULT_POLICY):
    row = item(s, box, actor, iid)
    src = s.get(InboxSource, sid)
    if src is None or src.item_id != iid:
        error("inbox_unavailable", 404)
    value = source_view(row, src)
    final_authority(s)
    return public.bounded(value, 65536)
