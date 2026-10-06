"""Human-reviewed vendor delivery on F8; local commands never invoke a connector.

Network orchestration commits durable claims before leaving this module. Exact
recovery is a read of immutable command effects, independent of current sources.
"""

import base64
import hmac
import html
import json
import secrets
from datetime import UTC, timedelta
from typing import NoReturn
from urllib.parse import unquote
from uuid import UUID, uuid4

from sqlalchemy import func, select

from cosmas_os.api import vendor_work_schemas as public
from cosmas_os.application import core_note_review, note_review
from cosmas_os.application import workspace as ws
from cosmas_os.config import settings
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.models import (
    ActionRevision,
    AuditEvent,
    Decision,
    EncounterWorkspace,
    FollowUpSource,
    Operation,
    Principal,
    Ticket,
    WorkHandoff,
    WorkspaceNoteReview,
)
from cosmas_os.ports import vendor_connectors as private
from cosmas_os.vendor_models import (
    VendorArtifact,
    VendorCommandReceipt,
    VendorConnectionVersion,
    VendorCorrespondenceVersion,
    VendorProviderObservation,
    VendorReadClaim,
    VendorSubmitClaim,
    VendorWork,
    VendorWorkRevision,
)
from cosmas_os.vendor_retirement_models import VendorCommandRetirement, VendorPreparationRetirement

LANE = "encounter_vendor_delivery"
ADAPTER = "workspace_vendor"
CONTENT = "Vendor delivery — private review"
SOURCE_KIND = "vendor_reviewed_note"
_CURSOR_KEY = secrets.token_bytes(32)


def error(code, status=409) -> NoReturn:
    raise ws.WorkspaceError(code, status)


def _clock(s):
    return s.scalar(select(func.clock_timestamp())).astimezone(UTC)


def _gate():
    if not settings.workspace_available or not settings.vendor_work_enabled:
        error("vendor_feature_disabled", 403)


def _final_authority(s):
    """API installs a current signed-identity fence; local fixtures have none."""
    check = s.info.get("vendor_final_authority")
    if check is not None:
        check()


def _owner(s, box, actor, wid, *, writing=False, others=()):
    for person in sorted({actor, *others}):
        ws._human(s, box, person, creating=writing)
    w = s.scalar(
        select(EncounterWorkspace)
        .where(
            EncounterWorkspace.id == wid,
            EncounterWorkspace.box_id == box,
            EncounterWorkspace.owner_id == actor,
        )
        .with_for_update(read=not writing)
        .execution_options(populate_existing=True)
    )
    if w is None:
        error("vendor_work_unavailable", 404)
    ws._encounter(s, box, w.appointment_id, w.patient_link_id, owner=w.owner_id)
    return w


def _scope(w, kind="workspace", tid=None):
    return {"kind": kind, "id": w.id if kind == "workspace" else tid}


def _saved(s, wid, actor, key):
    for model in (VendorCommandReceipt, VendorCommandRetirement, VendorPreparationRetirement):
        query = select(model).where(model.workspace_id == wid, model.actor_id == actor,
                                    model.idempotency_key == key)
        if model is VendorCommandReceipt:
            query = query.where(model.origin == "user")
        row = s.scalar(query)
        if row is not None:
            return row
    return None


def _receipt(s, w, actor, kind, request, *, scope=None):
    scope = scope or _scope(w)
    digest = public.request_digest(kind, scope, request)
    saved = _saved(s, w.id, actor, request.idempotency_key)
    if saved and (
        saved.command_kind != kind
        or saved.request_sha256 != digest
        or saved.scope_kind != scope["kind"]
        or saved.scope_id != scope["id"]
    ):
        error("vendor_idempotency_conflict")
    return saved, digest


def command_response(s, row):
    if isinstance(row, VendorPreparationRetirement):
        from cosmas_os.application import vendor_preparation_retirement
        return vendor_preparation_retirement.response(s, row)
    if isinstance(row, VendorCommandRetirement):
        from cosmas_os.application import vendor_retirement
        return vendor_retirement.response(s, row)
    value = {
        "contract_version": 1,
        "scope": {"kind": row.scope_kind, "id": row.scope_id},
        "command_kind": row.command_kind,
        "idempotency_key": row.idempotency_key,
        "request_sha256": row.request_sha256,
        "outcome": "recorded",
        "effect": row.effect["effect"],
        "summary": row.effect["summary"],
        "observed_at": public.timestamp(_clock(s)),
    }
    body = public.CommandResponse.model_validate(value).public()
    check = {
        k: body[k]
        for k in ("scope", "command_kind", "idempotency_key", "request_sha256", "effect", "summary")
    }
    check["effect"] = {k: v for k, v in check["effect"].items() if k != "receipt_sha256"}
    if public.public_digest("cosmas-vendor-public-receipt.v1", check) != row.receipt_sha256:
        error("vendor_unavailable", 503)
    return public.bounded(body, 16384)


def _record(
    s,
    w,
    actor,
    kind,
    request,
    digest,
    t,
    r,
    effect,
    *,
    publication=None,
    result=None,
    result_receipt=None,
    scope=None,
):
    _final_authority(s)
    now, rid = _clock(s), str(uuid4())
    scope = scope or _scope(w)
    public_effect = {
        "ticket_id": t.id,
        "operation_id": r.intended_operation_id,
        "revision_id": r.action_revision_id,
        "payload_hash": r.payload_hash,
        "receipt_id": rid,
        "effect_version": t.version,
        "recorded_at": public.timestamp(now),
    }
    summary = {"effect": effect, "publication_recorded": publication is not None}
    sha = public.public_digest(
        "cosmas-vendor-public-receipt.v1",
        {
            "scope": scope,
            "command_kind": kind,
            "idempotency_key": request.idempotency_key,
            "request_sha256": digest,
            "effect": public_effect,
            "summary": summary,
        },
    )
    public_effect["receipt_sha256"] = sha
    row = VendorCommandReceipt(
        id=rid,
        box_id=w.box_id,
        workspace_id=w.id,
        owner_id=w.owner_id,
        actor_id=actor,
        scope_kind=scope["kind"],
        scope_id=scope["id"],
        command_kind=kind,
        idempotency_key=request.idempotency_key,
        public_request=request.public(),
        request_sha256=digest,
        ticket_id=t.id,
        action_revision_id=r.action_revision_id,
        operation_id=r.intended_operation_id,
        effect_version=t.version,
        effect={"effect": public_effect, "summary": summary},
        receipt_sha256=sha,
        recorded_at=now,
        publication_projection=publication,
        publication_sha256=public.public_digest("cosmas-vendor-public-review.v1", publication)
        if publication
        else None,
        result_payload=result,
        result_receipt_id=result_receipt.id if result_receipt else None,
        observation_head_sha256=request.observation_head.sha256
        if isinstance(request, (public.VendorResult, public.VendorVerify))
        else None,
        evidence_sha256=request.evidence_sha256
        if isinstance(request, (public.VendorResult, public.VendorVerify))
        else None,
    )
    s.add(row)
    s.flush()
    s.add(
        AuditEvent(
            box_id=w.box_id,
            aggregate_type="ticket",
            aggregate_id=t.id,
            event_type="vendor_work." + kind,
            actor_principal_id=actor,
            action_revision_id=r.action_revision_id,
            payload_hash=r.payload_hash,
            outcome=effect,
            detail={"operation_id": r.intended_operation_id, "receipt_id": rid},
        )
    )
    return row


def _source(s, w, source, core_checked=None):
    n = note_review._latest(s, w.id)
    if (
        n is None
        or n.id != source.note_id
        or n.content_hash != source.content_sha256
        or n.source_fingerprint != source.source_fingerprint
        or note_review.source_fingerprint(s, w.id, w.revision) != n.source_fingerprint
        or not s.scalar(select(WorkspaceNoteReview.id).where(WorkspaceNoteReview.note_id == n.id))
    ):
        error("vendor_source_changed")
    try:
        core_note_review.require_current(s, n, core_checked)
    except ws.WorkspaceError:
        error("vendor_source_changed")
    return n


def _connection_view(row):
    view = {k: v for k, v in row.public_view.items() if k != "public_sha256"}
    view["availability"] = (
        "revoked"
        if row.revoked_at
        else "enabled"
        if row.is_current and row.write_enabled
        else "read_only"
        if row.read_enabled
        else "disabled"
    )
    view["public_sha256"] = public.public_digest("cosmas-vendor-public-selection.v1", view)
    return public.ConnectionView.model_validate(view).public()


def _managed_connection(s, w, connection_id, *, mutating=True):
    guard = s.info.get("vendor_managed_selection_guard")
    if guard is not None:
        guard(w, connection_id, mutating=mutating)


def _managed_available(s, w, connection_id, *, mutating=True):
    try:
        _managed_connection(s, w, connection_id, mutating=mutating)
        return True
    except ws.WorkspaceError:
        return False


def _available_connection_view(s, w, row):
    view = _connection_view(row)
    if not _managed_available(s, w, row.id):
        view["availability"] = (
            "read_only" if _managed_available(s, w, row.id, mutating=False) else "disabled"
        )
        view["public_sha256"] = public.public_digest(
            "cosmas-vendor-public-selection.v1",
            {key: value for key, value in view.items() if key != "public_sha256"},
        )
    return view


def _correspondence_view(row, now):
    view = {k: v for k, v in row.public_view.items() if k != "public_sha256"}
    view["permission"] = (
        "revoked"
        if row.revoked_at or not row.is_current
        else "expired"
        if row.expires_at <= now
        else "reviewed"
    )
    view["public_sha256"] = public.public_digest("cosmas-vendor-public-selection.v1", view)
    return public.CorrespondenceView.model_validate(view).public()


def _connection(s, w, selection, action):
    row = s.scalar(
        select(VendorConnectionVersion)
        .where(
            VendorConnectionVersion.id == selection.id,
            VendorConnectionVersion.box_id == w.box_id,
            VendorConnectionVersion.owner_id == w.owner_id,
        )
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if (
        row is None
        or row.revision != selection.revision
        or not row.is_current
        or row.revoked_at
        or not row.write_enabled
    ):
        error("vendor_selection_changed")
    view = _connection_view(row)
    if view["public_sha256"] != selection.public_sha256 or action not in view["actions"]:
        error("vendor_selection_changed")
    try:
        chosen = private.ConnectionSelection.model_validate(row.private_selection)
        if (
            str(chosen.connection_id),
            str(chosen.box_id),
            str(chosen.owner_id),
            chosen.vendor,
            chosen.environment,
        ) != (
            row.id,
            w.box_id,
            w.owner_id,
            row.vendor,
            row.environment,
        ) or chosen.commitment() != row.private_sha256:
            raise ValueError
    except ValueError:
        error("vendor_selection_changed")
    _managed_connection(s, w, row.id)
    return row, chosen, view


def _correspondence(s, w, selected, connection, action, now):
    if selected is None:
        return None, None
    row = s.scalar(
        select(VendorCorrespondenceVersion)
        .where(
            VendorCorrespondenceVersion.id == selected.id,
            VendorCorrespondenceVersion.connection_version_id == connection.id,
            VendorCorrespondenceVersion.box_id == w.box_id,
            VendorCorrespondenceVersion.owner_id == w.owner_id,
            VendorCorrespondenceVersion.patient_link_id == w.patient_link_id,
        )
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if (
        row is None
        or row.revision != selected.revision
        or not row.is_current
        or row.revoked_at
        or row.expires_at <= now
    ):
        error("vendor_permission_unavailable")
    view = _correspondence_view(row, now)
    if view["public_sha256"] != selected.public_sha256 or view["channel"] != (
        "secure" if action == "spruce_secure_message" else "fax"
    ):
        error("vendor_selection_changed")
    if private.digest("cosmas-vendor-correspondence.v1", row.private_proof) != row.private_sha256:
        error("vendor_selection_changed")
    return row, view


def _artifact(s, w, document, source):
    row = s.scalar(
        select(VendorArtifact)
        .where(
            VendorArtifact.artifact_id == document.artifact_id,
            VendorArtifact.workspace_id == w.id,
            VendorArtifact.box_id == w.box_id,
            VendorArtifact.owner_id == w.owner_id,
        )
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if (
        row is None
        or row.state != "ready"
        or (row.sha256, row.byte_length, row.media_type)
        != (document.sha256, document.byte_length, document.media_type)
        or (row.note_id, row.content_hash, row.source_fingerprint)
        != (source.note_id, source.content_sha256, source.source_fingerprint)
    ):
        error("artifact_unavailable")
    return row


def _known_private_text(s, w, config):
    tokens = {
        str(private.ConnectionSelection.model_validate(config.private_selection).credential_ref)
    }
    from cosmas_os.models import WorkspaceCoreNoteSource

    for row in s.scalars(
        select(WorkspaceCoreNoteSource).where(WorkspaceCoreNoteSource.workspace_id == w.id)
    ):
        for name in ("schema_ref", "transcript_ref", "note_ref"):
            value = getattr(row, name)
            if value:
                tokens.add(value)
                if "_" in value:
                    tokens.add(value.split("_", 1)[1])

        def collect(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if (
                        key.endswith(("_ref", "_url", "_token"))
                        and isinstance(item, str)
                        and len(item) >= 8
                    ):
                        tokens.add(item)
                    else:
                        collect(item)
            elif isinstance(value, list):
                for item in value:
                    collect(item)

        collect(row.notebook_source)
    return tokens


def _guard_text(s, w, config, *values):
    tokens = _known_private_text(s, w, config)
    for value in values:
        if value is None:
            continue
        for _ in range(2):
            value = html.unescape(unquote(value))
        if any(token.casefold() in value.casefold() for token in tokens):
            error("vendor_credential_text_forbidden", 422)


def _bound(s, w, tid, *, revision_id=None, writing=True):
    work = s.scalar(
        select(VendorWork).where(
            VendorWork.ticket_id == tid,
            VendorWork.workspace_id == w.id,
            VendorWork.box_id == w.box_id,
            VendorWork.owner_id == w.owner_id,
        )
    )
    if work is None:
        error("vendor_work_unavailable", 404)
    t = s.scalar(
        select(Ticket)
        .where(Ticket.id == tid)
        .with_for_update(read=not writing)
        .execution_options(populate_existing=True)
    )
    r = s.get(VendorWorkRevision, revision_id or t.current_revision_id)
    a = s.get(ActionRevision, r.action_revision_id) if r else None
    if (
        r is None
        or a is None
        or r.ticket_id != tid
        or r.owner_id != w.owner_id
        or t.lane != LANE
        or a.invalidated
    ):
        error("vendor_revision_changed")
    command = private.VendorCommand.model_validate(r.private_command)
    if (
        command.commitment() != r.private_command_sha256
        or payload_hash(a.payload) != r.payload_hash
        or r.payload_hash != a.payload_hash
        or public.public_digest("cosmas-vendor-public-review.v1", r.public_review)
        != r.review_sha256
        or public.request_digest(
            "propose", _scope(w), public.VendorProposal.model_validate(r.public_proposal)
        )
        != r.request_sha256
    ):
        error("vendor_unavailable", 503)
    return work, t, r, command


def _check_bound(t, r, request):
    if (
        request.expected_version,
        request.revision_id,
        request.operation_id,
        request.payload_hash,
    ) != (t.version, t.current_revision_id, r.intended_operation_id, r.payload_hash):
        error("vendor_revision_changed")


def _operation(s, r):
    return s.scalar(
        select(Operation)
        .where(Operation.id == r.intended_operation_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _head(s, r):
    row = s.scalar(
        select(VendorProviderObservation)
        .where(VendorProviderObservation.operation_id == r.intended_operation_id)
        .order_by(VendorProviderObservation.sequence.desc())
        .limit(1)
    )
    return (
        {"sequence": row.sequence, "sha256": row.head_sha256}
        if row
        else {
            "sequence": 0,
            "sha256": public.public_digest(
                "cosmas-vendor-observation-head.v1",
                {"operation_id": r.intended_operation_id, "sequence": 0},
            ),
        }
    )


def _latest_result(s, r):
    return s.scalar(
        select(VendorCommandReceipt)
        .where(
            VendorCommandReceipt.action_revision_id == r.action_revision_id,
            VendorCommandReceipt.command_kind == "result",
        )
        .order_by(VendorCommandReceipt.effect_version.desc())
        .limit(1)
    )


def _evidence(s, r):
    result = _latest_result(s, r)
    head = _head(s, r)
    return head, public.public_digest(
        "cosmas-vendor-evidence.v1",
        {
            "operation_id": r.intended_operation_id,
            "observation_head": head,
            "result_receipt_id": result.id if result else None,
            "result_receipt_sha256": result.receipt_sha256 if result else None,
        },
    )


def _publication(s, r):
    return s.scalar(
        select(VendorCommandReceipt).where(
            VendorCommandReceipt.action_revision_id == r.action_revision_id,
            VendorCommandReceipt.publication_projection.is_not(None),
        )
    )


def _safe_publication(r):
    review = public.Review.model_validate(r.public_review)
    return {
        "body": review.expected_outcome,
        "due_date": review.due_date,
        "expected_outcome": review.expected_outcome,
        "action": r.action,
        "account_label": review.connection.label,
    }


def _responsible(s, r):
    row = s.scalar(
        select(WorkHandoff)
        .where(
            WorkHandoff.ticket_id == r.ticket_id,
            WorkHandoff.action_revision_id == r.action_revision_id,
            WorkHandoff.payload_hash == r.payload_hash,
            WorkHandoff.kind.in_(("accept", "reclaim")),
        )
        .order_by(WorkHandoff.sequence.desc())
        .limit(1)
    )
    return row.to_id if row else r.owner_id


def _states(s, t, r):
    observations = list(
        s.scalars(
            select(VendorProviderObservation)
            .where(VendorProviderObservation.operation_id == r.intended_operation_id)
            .order_by(VendorProviderObservation.sequence)
        )
    )
    acceptance = {o.public_observation.get("acceptance") for o in observations} - {None}
    transport = {o.public_observation.get("transport") for o in observations} - {None}
    ac = acceptance & {"accepted", "rejected"}
    tr = transport & {"delivered", "failed"}
    conflict = len(ac) > 1 or len(tr) > 1
    claim = s.get(VendorSubmitClaim, r.intended_operation_id)
    dispatch = claim.dispatch if claim else "not_started"
    if claim and claim.completed_at is None and _clock(s) >= claim.deadline:
        dispatch = "unconfirmed"
    result = _latest_result(s, r)
    state = (
        "none"
        if result is None
        else "recorded_exception"
        if result.result_payload["disposition"] in {"reported_exception", "unable_to_establish"}
        else "recorded_success"
    )
    return {
        "submit_claimed": claim is not None,
        "dispatch": dispatch,
        "acceptance": next(iter(ac))
        if len(ac) == 1
        else "unconfirmed"
        if acceptance
        else "not_observed",
        "transport": next(iter(tr))
        if len(tr) == 1
        else "unknown"
        if len(tr) > 1 or "unknown" in transport
        else "pending"
        if transport
        else "not_observed",
        "conflicting_evidence": conflict,
        "result": state,
        "verification": "verified"
        if t.state == "closed" and t.current_revision_id == r.action_revision_id
        else "exception_unresolved"
        if state == "recorded_exception"
        else "pending",
    }


def _summary(s, t, r):
    head, evidence = _evidence(s, r)
    body = {
        "ticket_id": t.id,
        "version": t.version,
        "revision_id": r.action_revision_id,
        "operation_id": r.intended_operation_id,
        "payload_hash": r.payload_hash,
        "action": r.action,
        "state": t.state if t.current_revision_id == r.action_revision_id else "superseded",
        "published": _publication(s, r) is not None,
        **_states(s, t, r),
        "due_date": r.public_review["due_date"],
        "outcome_excerpt": r.public_review["expected_outcome"][:160],
        "responsible_id": _responsible(s, r),
        "observation_head": head,
        "evidence_sha256": evidence,
    }
    return public.Summary.model_validate(body).public()


def _person(s, pid):
    p = s.get(Principal, pid)
    return {
        "id": pid,
        "name": public.safe_label(p.display_name),
        "available": p.state == "active" and p.tombstoned_at is None,
    }


def _verification_reason(state, result, owner_id):
    if result is None:
        return "result_required"
    if state["result"] == "recorded_exception":
        return "exception_unresolved"
    manual = result.result_payload["disposition"] == "verified_in_vendor" and result.actor_id == owner_id
    if (state["conflicting_evidence"] or state["acceptance"] != "accepted" or state["transport"] != "delivered") and not manual:
        return "manual_verification_required"
    return "available"


def _availability(s, w, t, r, summary):
    def decision(reason):
        return {"allowed": reason == "available", "reason": reason}

    current = t.current_revision_id == r.action_revision_id
    open_ = t.state in {"pending_approval", "approved"}
    base = "not_current" if not current else "closed" if not open_ else "available"
    claimed = summary["submit_claimed"]
    new = (
        base
        if base != "available"
        else "feature_disabled"
        if not settings.vendor_work_enabled
        else "expired"
        if _clock(s) >= r.expires_at
        else "available"
    )
    result = _latest_result(s, r)
    if new == "available":
        note = note_review._latest(s, w.id)
        config = s.get(VendorConnectionVersion, r.connection_version_id)
        correspondence = s.get(VendorCorrespondenceVersion, r.correspondence_version_id) if r.correspondence_version_id else None
        if note is None or (note.id, note.content_hash, note.source_fingerprint) != (r.note_id, r.content_hash, r.source_fingerprint) or note_review.source_fingerprint(s, w.id, w.revision) != r.source_fingerprint:
            new = "source_changed"
        elif config is None or not config.is_current or not config.write_enabled or config.revoked_at or not _managed_available(s, w, config.id):
            new = "selection_changed"
        elif correspondence and (not correspondence.is_current or correspondence.revoked_at or correspondence.expires_at <= _clock(s)):
            new = "permission_unavailable"
        elif r.artifact_id and (artifact := s.get(VendorArtifact, r.artifact_id)) and artifact.state != "ready":
            new = "artifact_unavailable"
    reconcile = "feature_disabled" if not settings.vendor_io_enabled else "reference_unavailable"
    if settings.vendor_io_enabled and claimed:
        config = s.get(VendorConnectionVersion, r.connection_version_id)
        if config is None or config.revoked_at or not config.read_enabled or not _managed_available(s, w, config.id, mutating=False):
            reconcile = "original_account_unavailable"
        else:
            from cosmas_os.application.vendor_execution import _reference
            try:
                _reference(s, r, private.VendorCommand.model_validate(r.private_command))
                reconcile = "available"
            except ws.WorkspaceError:
                pass
            if reconcile == "available" and s.scalar(select(VendorReadClaim.id).where(
                    VendorReadClaim.operation_id == r.intended_operation_id, VendorReadClaim.completed_at.is_(None),
                    VendorReadClaim.deadline > _clock(s))):
                reconcile = "read_in_progress"
            elif reconcile == "available" and s.scalar(select(func.count()).select_from(VendorReadClaim).where(
                    VendorReadClaim.operation_id == r.intended_operation_id)) >= 100:
                reconcile = "history_limit"
    return {
        "approve": decision(new if t.state == "pending_approval" else "not_approved"),
        "reject": decision(base if t.state == "pending_approval" else "not_approved"),
        "withdraw": decision("submit_already_claimed" if claimed else base),
        "publish": decision(
            "already_published"
            if summary["published"]
            else base
            if t.state == "approved"
            else "not_approved"
        ),
        "submit": decision(
            "submit_already_claimed"
            if claimed
            else "not_approved"
            if t.state != "approved"
            else "feature_disabled"
            if not settings.vendor_io_enabled
            else new
        ),
        "reconcile": decision(reconcile),
        "result": decision(base if t.state == "approved" else "not_approved"),
        "verify": decision(
            base
            if base != "available"
            else "not_approved" if t.state != "approved"
            else _verification_reason(summary, result, w.owner_id)
        ),
    }


def detail(s, box, actor, wid, tid):
    w = _owner(s, box, actor, wid)
    _, t, r, _ = _bound(s, w, tid, writing=False)
    result = _latest_result(s, r)
    summary = _summary(s, t, r)
    body = {
        "contract_version": 1,
        "workspace_id": wid,
        "view_version": t.version,
        "observed_at": public.timestamp(_clock(s)),
        "summary": summary,
        "review": r.public_review,
        "review_sha256": r.review_sha256,
        "latest_result": None
        if result is None
        else {
            "receipt_id": result.id,
            "receipt_sha256": result.receipt_sha256,
            "actor": _person(s, result.actor_id),
            **result.result_payload,
            "recorded_at": public.timestamp(result.recorded_at),
        },
        "availability": _availability(s, w, t, r, summary),
    }
    return public.bounded(public.Detail.model_validate(body).public(), 65536)


def options(s, box, actor, wid):
    w = _owner(s, box, actor, wid)
    now = _clock(s)
    connections = list(
        s.scalars(
            select(VendorConnectionVersion)
            .where(
                VendorConnectionVersion.box_id == box,
                VendorConnectionVersion.owner_id == actor,
                VendorConnectionVersion.is_current.is_(True),
            )
            .order_by(VendorConnectionVersion.id)
            .limit(10)
        )
    )
    correspondences = list(
        s.scalars(
            select(VendorCorrespondenceVersion)
            .where(
                VendorCorrespondenceVersion.box_id == box,
                VendorCorrespondenceVersion.owner_id == actor,
                VendorCorrespondenceVersion.patient_link_id == w.patient_link_id,
                VendorCorrespondenceVersion.is_current.is_(True),
                VendorCorrespondenceVersion.connection_version_id.in_([c.id for c in connections]),
            )
            .order_by(VendorCorrespondenceVersion.id)
            .limit(10)
        )
    )
    n = note_review._latest(s, wid)
    source = (
        {
            "kind": "reviewed_note",
            "note_id": n.id,
            "content_sha256": n.content_hash,
            "source_fingerprint": n.source_fingerprint,
        }
        if n
        and n.source_fingerprint == note_review.source_fingerprint(s, wid, w.revision)
        and s.scalar(select(WorkspaceNoteReview.id).where(WorkspaceNoteReview.note_id == n.id))
        else None
    )
    return public.bounded(
        public.Options.model_validate(
            {
                "contract_version": 1,
                "workspace_id": wid,
                "entry_revision": w.revision,
                "enabled": settings.vendor_work_enabled,
                "connections": [_available_connection_view(s, w, c) for c in connections],
                "correspondences": [_correspondence_view(c, now) for c in correspondences],
                "source": source,
                "observed_at": public.timestamp(now),
            }
        ).public(),
        65536,
    )


def resolve(s, box, actor, wid, request):
    w = _owner(s, box, actor, wid)
    row = _saved(s, wid, actor, request.idempotency_key)
    if row and (
        row.command_kind != request.command_kind
        or row.request_sha256 != request.request_sha256
        or row.scope_kind != "workspace"
    ):
        error("vendor_idempotency_conflict")
    if row:
        return command_response(s, row)
    return {
        "contract_version": 1,
        "scope": _scope(w),
        **request.public(),
        "outcome": "not_found",
        "effect": None,
        "summary": None,
        "observed_at": public.timestamp(_clock(s)),
    }


def _cursor(scope, last):
    body = public.canonical({"scope": scope, "last": last})
    signature = hmac.digest(_CURSOR_KEY, body, "sha256")
    return base64.urlsafe_b64encode(body + signature).rstrip(b"=").decode("ascii")


def _after(cursor, scope):
    if cursor is None:
        return None
    try:
        if type(cursor) is not str or not 1 <= len(cursor) <= 512 or not cursor.isascii():
            raise ValueError
        raw = base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
        body, supplied = raw[:-32], raw[-32:]
        if not hmac.compare_digest(hmac.digest(_CURSOR_KEY, body, "sha256"), supplied):
            raise ValueError
        value = json.loads(body)
        if set(value) != {"scope", "last"} or value["scope"] != scope:
            raise ValueError
        return public._uuid(value["last"])
    except (ValueError, TypeError, KeyError):
        error("invalid_vendor_request", 400)


def catalog(s, box, actor, wid, cursor=None):
    w = _owner(s, box, actor, wid)
    scope = {"kind": "vendor_catalog", "workspace_id": wid, "owner_id": actor, "box_id": box}
    after = _after(cursor, scope)
    query = select(VendorWork.ticket_id).where(
        VendorWork.workspace_id == wid, VendorWork.box_id == box, VendorWork.owner_id == actor
    )
    if after:
        query = query.where(VendorWork.ticket_id > after)
    ids = list(s.scalars(query.order_by(VendorWork.ticket_id).limit(26)))
    items = []
    for tid in ids[:25]:
        _, t, r, _ = _bound(s, w, tid, writing=False)
        items.append(_summary(s, t, r))
    return public.bounded(
        public.Catalog.model_validate(
            {
                "contract_version": 1,
                "workspace_id": wid,
                "items": items,
                "next_cursor": _cursor(scope, ids[24]) if len(ids) > 25 else None,
                "observed_at": public.timestamp(_clock(s)),
            }
        ).public(),
        65536,
    )


def observations(s, box, actor, wid, tid, cursor=None):
    w = _owner(s, box, actor, wid)
    _, t, r, _ = _bound(s, w, tid, writing=False)
    scope = {
        "kind": "vendor_observations",
        "operation_id": r.intended_operation_id,
        "owner_id": actor,
        "box_id": box,
    }
    after = _after(cursor, scope)
    query = select(VendorProviderObservation).where(
        VendorProviderObservation.operation_id == r.intended_operation_id
    )
    if after:
        prior = s.get(VendorProviderObservation, after)
        if prior is None or prior.operation_id != r.intended_operation_id:
            error("invalid_vendor_request", 400)
        query = query.where(VendorProviderObservation.sequence > prior.sequence)
    rows = list(s.scalars(query.order_by(VendorProviderObservation.sequence).limit(21)))
    return public.bounded(
        public.ObservationPage.model_validate(
            {
                "contract_version": 1,
                "ticket_id": tid,
                "operation_id": r.intended_operation_id,
                "observations": [row.public_observation for row in rows[:20]],
                "head": _head(s, r),
                "next_cursor": _cursor(scope, rows[19].id) if len(rows) > 20 else None,
                "observed_at": public.timestamp(_clock(s)),
            }
        ).public(),
        65536,
    )


def propose(s, box, actor, wid, request, *, core_checked=None):
    request = public.VendorProposal.model_validate(request.public())
    w = _owner(s, box, actor, wid, writing=True)
    prior, digest = _receipt(s, w, actor, "propose", request)
    if prior:
        return command_response(s, prior)
    _gate()
    if w.revision != request.expected_workspace_revision:
        error("vendor_source_changed")
    n = _source(s, w, request.source, core_checked)
    config, selection, cv = _connection(s, w, request.connection, request.action)
    now = _clock(s)
    correspondence, correspondence_view = _correspondence(
        s, w, request.correspondence, config, request.action, now
    )
    _guard_text(s, w, config, request.message, request.expected_outcome)
    expiry = (
        min(now + timedelta(hours=24), correspondence.expires_at)
        if correspondence
        else now + timedelta(hours=24)
    )
    if s.scalar(
        select(VendorWorkRevision.action_revision_id).where(
            VendorWorkRevision.intended_operation_id == request.proposed_operation_id
        )
    ):
        error("vendor_idempotency_conflict")
    if request.revises:
        _, t, previous, _ = _bound(s, w, request.revises.ticket_id)
        if (t.version, t.current_revision_id, previous.payload_hash) != (
            request.revises.expected_version,
            request.revises.revision_id,
            request.revises.payload_hash,
        ) or t.state not in {"pending_approval", "approved"}:
            error("vendor_revision_changed")
        if s.get(VendorSubmitClaim, previous.intended_operation_id):
            error("vendor_submit_already_claimed")
        if previous.revision_number >= 20:
            error("vendor_history_limit")
        old_op = _operation(s, previous)
        if old_op:
            old_op.status, old_op.completed_at = "cancelled", now
        number = previous.revision_number + 1
        t.version += 1
        t.state, t.closed_at = "pending_approval", None
    else:
        if (
            s.scalar(
                select(func.count()).select_from(VendorWork).where(VendorWork.workspace_id == wid)
            )
            >= 100
        ):
            error("vendor_history_limit")
        t = Ticket(
            id=str(uuid4()),
            box_id=box,
            lane=LANE,
            state="pending_approval",
            version=1,
            created_by_principal_id=actor,
            appointment_id=w.appointment_id,
            patient_link_id=w.patient_link_id,
        )
        s.add(t)
        number = 1
    revision_id = str(uuid4())
    document = None
    if request.document:
        _artifact(s, w, request.document, request.source)
        document = private.DocumentBinding.model_validate(request.document.public())
    upload = None
    if request.uploaded_media_operation_id:
        ur = s.scalar(
            select(VendorWorkRevision).where(
                VendorWorkRevision.intended_operation_id == request.uploaded_media_operation_id,
                VendorWorkRevision.workspace_id == wid,
                VendorWorkRevision.owner_id == actor,
                VendorWorkRevision.box_id == box,
            )
        )
        if (
            ur is None
            or ur.action != "spruce_media_upload"
            or ur.connection_version_id != config.id
            or (ur.note_id, ur.content_hash, ur.source_fingerprint)
            != (n.id, n.content_hash, n.source_fingerprint)
        ):
            error("artifact_unavailable")
        observation = s.scalar(
            select(VendorProviderObservation)
            .where(
                VendorProviderObservation.operation_id == ur.intended_operation_id,
                VendorProviderObservation.kind == "submission",
                VendorProviderObservation.private_reference.is_not(None),
            )
            .order_by(VendorProviderObservation.sequence.desc())
            .limit(1)
        )
        if observation is None or observation.public_observation.get("acceptance") != "accepted":
            error("artifact_unavailable")
        uploaded_intent = private.VendorCommand.model_validate(ur.private_command).intent
        if not isinstance(uploaded_intent, private.MediaUploadIntent):
            error("artifact_unavailable")
        document = uploaded_intent.document
        upload = private.UploadedMedia(
            document=document,
            reference=private.ProviderReference.model_validate(observation.private_reference),
        )
    if request.action == "spruce_media_upload":
        if document is None:
            error("artifact_unavailable")
        intent = private.MediaUploadIntent(document=document)
    elif request.action.startswith("spruce"):
        if correspondence is None:
            error("vendor_permission_unavailable")
        intent = private.SpruceMessageIntent(
            internal_endpoint_id=config.routing["internal_endpoint_id"],
            destination=correspondence.private_proof["destination"],
            text=request.message or "",
            attachment=upload,
        )
    else:
        if correspondence is None or document is None:
            error("artifact_unavailable")
        intent = private.FaxIntent(
            caller_id=config.routing["caller_id"],
            destination=correspondence.private_proof["destination"],
            sender_email=config.routing.get("sender_email"),
            document=document,
        )
    command = private.VendorCommand(
        selection=selection,
        operation_id=UUID(request.proposed_operation_id),
        revision_id=UUID(revision_id),
        expires_at=expiry,
        intent=intent,
    )
    review = {
        "ticket_id": t.id,
        "revision_id": revision_id,
        "operation_id": request.proposed_operation_id,
        "action": request.action,
        "connection": cv,
        "source": request.source.public(),
        "due_date": request.due_date,
        "expected_outcome": request.expected_outcome,
        "share_to_practice": request.share_to_practice,
        "expires_at": public.timestamp(expiry),
    }
    if correspondence_view:
        review["correspondence"] = correspondence_view
    if request.document:
        review["document"] = request.document.public()
    if upload:
        review["uploaded_media"] = {
            "operation_id": request.uploaded_media_operation_id,
            "document": {
                k: v
                for k, v in upload.document.model_dump(mode="json").items()
                if k != "display_name"
            },
        }
    if request.message is not None:
        review["message"] = request.message
    if request.supersedes_operation_id:
        previous = s.scalar(
            select(VendorWorkRevision).where(
                VendorWorkRevision.intended_operation_id == request.supersedes_operation_id,
                VendorWorkRevision.workspace_id == wid,
                VendorWorkRevision.box_id == box,
                VendorWorkRevision.owner_id == actor,
                VendorWorkRevision.patient_link_id == w.patient_link_id,
            )
        )
        if previous is None or s.get(VendorSubmitClaim, previous.intended_operation_id) is None:
            error("vendor_revision_changed")
        state = _states(s, s.get(Ticket, previous.ticket_id), previous)
        review["supersedes"] = {
            "ticket_id": previous.ticket_id,
            "operation_id": previous.intended_operation_id,
            "action": previous.action,
            "prior_dispatch": state["dispatch"],
            "prior_acceptance": state["acceptance"],
            "prior_transport": state["transport"],
            "uncertainty_acknowledged": True,
        }
    review = public.Review.model_validate(review).public()
    review_sha = public.public_digest("cosmas-vendor-public-review.v1", review)
    source_proof = {
        "source": request.source.public(),
        "connection_sha256": config.private_sha256,
        "correspondence_sha256": correspondence.private_sha256 if correspondence else None,
        "core": core_checked.model_dump(mode="json") if core_checked else None,
    }
    source_sha = private.digest("cosmas-vendor-source.v1", source_proof)
    envelope = {
        "action": "vendor_delivery." + request.action,
        "private_command_sha256": command.commitment(),
        "review_sha256": review_sha,
        "request_sha256": digest,
        "source_sha256": source_sha,
        "selection_sha256": selection.commitment(),
        "correspondence_sha256": correspondence.private_sha256 if correspondence else None,
        "operation_id": request.proposed_operation_id,
    }
    action = ActionRevision(
        id=revision_id,
        ticket_id=t.id,
        box_id=box,
        revision_number=number,
        action_type="vendor_delivery." + request.action,
        target_ref="vendor_work:" + t.id,
        content=CONTENT,
        payload=envelope,
        payload_hash=payload_hash(envelope),
        automation_class="hitl_required",
        policy_version="vendor-human-review-v1",
        charter_version="private-delivery-v1",
        config_version="vendor-c1",
        created_by_principal_id=actor,
    )
    s.add(action)
    s.flush()
    t.current_revision_id = revision_id
    if not request.revises:
        s.add(
            FollowUpSource(
                ticket_id=t.id,
                box_id=box,
                workspace_id=wid,
                owner_id=actor,
                source_kind=SOURCE_KIND,
                note_id=n.id,
                content_hash=n.content_hash,
                source_fingerprint=n.source_fingerprint,
                action_revision_id=revision_id,
                payload_hash=action.payload_hash,
                workspace_revision=w.revision,
                idempotency_key="vendor-origin:" + request.proposed_operation_id,
                request_hash=digest,
            )
        )
        s.add(
            VendorWork(
                ticket_id=t.id,
                box_id=box,
                workspace_id=wid,
                owner_id=actor,
                patient_link_id=w.patient_link_id,
                origin_revision_id=revision_id,
                origin_operation_id=request.proposed_operation_id,
                supersedes_operation_id=request.supersedes_operation_id,
            )
        )
    r = VendorWorkRevision(
        action_revision_id=revision_id,
        ticket_id=t.id,
        box_id=box,
        workspace_id=wid,
        owner_id=actor,
        patient_link_id=w.patient_link_id,
        revision_number=number,
        action=request.action,
        payload_hash=action.payload_hash,
        intended_operation_id=request.proposed_operation_id,
        source_workspace_revision=w.revision,
        note_id=n.id,
        content_hash=n.content_hash,
        source_fingerprint=n.source_fingerprint,
        connection_version_id=config.id,
        correspondence_version_id=correspondence.id if correspondence else None,
        artifact_id=request.document.artifact_id if request.document else None,
        uploaded_media_operation_id=request.uploaded_media_operation_id,
        private_command=command.model_dump(mode="json"),
        private_command_sha256=command.commitment(),
        source_proof=source_proof,
        source_proof_sha256=source_sha,
        public_proposal=request.public(),
        request_sha256=digest,
        public_review=review,
        review_sha256=review_sha,
        expires_at=expiry,
    )
    s.add(r)
    s.flush()
    receipt = _record(
        s, w, actor, "propose", request, digest, t, r, "revised" if request.revises else "proposed"
    )
    s.commit()
    return command_response(s, receipt)


def _new_current(s, w, r, core_checked):
    proposal = public.VendorProposal.model_validate(r.public_proposal)
    _source(s, w, proposal.source, core_checked)
    c, chosen, _ = _connection(s, w, proposal.connection, proposal.action)
    now = _clock(s)
    co, _ = _correspondence(s, w, proposal.correspondence, c, proposal.action, now)
    if (
        now >= r.expires_at
        or chosen.commitment() != r.source_proof["connection_sha256"]
        or (co.private_sha256 if co else None) != r.source_proof["correspondence_sha256"]
    ):
        error("vendor_approval_expired")
    if proposal.document:
        _artifact(s, w, proposal.document, proposal.source)
    return c, co


def decide(s, box, actor, wid, tid, request, *, core_checked=None, external_identity_id=None):
    w = _owner(s, box, actor, wid, writing=True)
    old, digest = _receipt(s, w, actor, "decide", request)
    if old:
        if old.ticket_id != tid:
            error("vendor_idempotency_conflict")
        return command_response(s, old)
    if request.choice == "approve":
        candidate = s.get(VendorWorkRevision, request.revision_id)
        if (
            candidate is None
            or candidate.workspace_id != wid
            or candidate.owner_id != actor
            or candidate.ticket_id != tid
        ):
            error("vendor_work_unavailable", 404)
        _gate()
        _new_current(s, w, candidate, core_checked)
    _, t, r, _ = _bound(s, w, tid)
    _check_bound(t, r, request)
    if request.review_sha256 != r.review_sha256 or t.state != "pending_approval":
        error("vendor_revision_changed")
    if request.choice == "approve" and _clock(s) >= r.expires_at:
        error("vendor_approval_expired")
    delegation = None
    if request.follow_up_bot_id is not None:
        from cosmas_os.application import model_work, provider_team
        from cosmas_os.ports.bot_capabilities import supports_skill

        model_work._identity(s, box, actor, external_identity_id)
        if external_identity_id is None:
            error("vendor_permission_unavailable", 403)
        version = provider_team.current(s, box, actor)
        address = provider_team.address_for_agent(s, box, actor, request.follow_up_bot_id)
        if version is None:
            error("vendor_permission_unavailable", 403)
        _, bot, bot_settings = provider_team.active_bot(s, box, actor, address, version.revision)
        if (r.public_review["action"] != "spruce_secure_message"
            or r.public_review.get("uploaded_media") is not None
            or bot.role != "follow_up"
            or not supports_skill(bot_settings, "saved_context")
            or not supports_skill(bot_settings, "work_status")
            or provider_team.blocked(bot_settings, "model_answer")
            or not settings.workspace_agent_tools_enabled):
            error("vendor_permission_unavailable", 403)
        delegation = {"agent_id": bot.agent_id, "team_revision_id": version.id,
            "external_identity_id": external_identity_id}
    t.version += 1
    t.state = "approved" if request.choice == "approve" else "rejected"
    s.add(
        Decision(
            box_id=box,
            ticket_id=tid,
            action_revision_id=r.action_revision_id,
            actor_principal_id=actor,
            kind=request.choice,
        )
    )
    if request.choice == "approve":
        s.add(
            Operation(
                id=r.intended_operation_id,
                box_id=box,
                ticket_id=tid,
                action_revision_id=r.action_revision_id,
                idempotency_key="os-vendor:" + r.intended_operation_id,
                adapter=ADAPTER,
                status="pending",
                attempt_count=0,
            )
        )
    receipt = _record(
        s,
        w,
        actor,
        "decide",
        request,
        digest,
        t,
        r,
        t.state,
        publication=_safe_publication(r)
        if request.choice == "approve" and r.public_review["share_to_practice"]
        else None,
    )
    if delegation is not None:
        detail = {**delegation, "approval_receipt_id": receipt.id,
            "approval_receipt_sha256": receipt.receipt_sha256, "revision_id": r.action_revision_id,
            "payload_hash": r.payload_hash, "operation_id": r.intended_operation_id}
        s.add(AuditEvent(box_id=box, aggregate_type="vendor_work", aggregate_id=tid,
            event_type="workspace.agent_delivery_authorized", actor_principal_id=actor,
            initiated_by_principal_id=actor, outcome="approved", payload_hash=model_work.digest(detail),
            detail=detail))
    s.commit()
    return command_response(s, receipt)


def withdraw(s, box, actor, wid, tid, request):
    w = _owner(s, box, actor, wid, writing=True)
    old, digest = _receipt(s, w, actor, "withdraw", request)
    if old:
        if old.ticket_id != tid:
            error("vendor_idempotency_conflict")
        return command_response(s, old)
    _, t, r, _ = _bound(s, w, tid)
    _check_bound(t, r, request)
    if s.get(VendorSubmitClaim, r.intended_operation_id):
        error("vendor_submit_already_claimed")
    if t.state not in {"pending_approval", "approved"}:
        error("vendor_revision_changed")
    op = _operation(s, r)
    if op:
        op.status, op.completed_at = "cancelled", _clock(s)
    t.state, t.version = "withdrawn", t.version + 1
    receipt = _record(s, w, actor, "withdraw", request, digest, t, r, "withdrawn")
    s.commit()
    return command_response(s, receipt)


def publish(s, box, actor, wid, tid, request):
    w = _owner(s, box, actor, wid, writing=True)
    old, digest = _receipt(s, w, actor, "publish", request)
    if old:
        if old.ticket_id != tid:
            error("vendor_idempotency_conflict")
        return command_response(s, old)
    _, t, r, _ = _bound(s, w, tid)
    _check_bound(t, r, request)
    if t.state != "approved" or request.review_sha256 != r.review_sha256 or _publication(s, r):
        error("vendor_revision_changed")
    t.version += 1
    receipt = _record(
        s, w, actor, "publish", request, digest, t, r, "published", publication=_safe_publication(r)
    )
    s.commit()
    return command_response(s, receipt)


def record_result(s, box, actor, wid, tid, request):
    w = _owner(s, box, actor, wid, writing=True)
    old, digest = _receipt(s, w, actor, "result", request)
    if old:
        if old.ticket_id != tid:
            error("vendor_idempotency_conflict")
        return command_response(s, old)
    _, t, r, _ = _bound(s, w, tid)
    _check_bound(t, r, request)
    if t.state != "approved":
        error("vendor_revision_changed")
    if _evidence(s, r) != (request.observation_head.public(), request.evidence_sha256):
        error("vendor_evidence_changed")
    _guard_text(s, w, s.get(VendorConnectionVersion, r.connection_version_id), request.evidence)
    t.version += 1
    receipt = _record(
        s,
        w,
        actor,
        "result",
        request,
        digest,
        t,
        r,
        "result_recorded",
        result={
            "disposition": request.disposition,
            "evidence": request.evidence,
            "observation_head": request.observation_head.public(),
        },
    )
    s.commit()
    return command_response(s, receipt)


def verify(s, box, actor, wid, tid, request):
    w = _owner(s, box, actor, wid, writing=True)
    old, digest = _receipt(s, w, actor, "verify", request)
    if old:
        if old.ticket_id != tid:
            error("vendor_idempotency_conflict")
        return command_response(s, old)
    _, t, r, _ = _bound(s, w, tid)
    _check_bound(t, r, request)
    if t.state != "approved":
        error("vendor_revision_changed")
    result = _latest_result(s, r)
    if result is None or (result.id, result.receipt_sha256) != (
        request.result_receipt_id,
        request.result_receipt_sha256,
    ):
        error("vendor_result_changed")
    if _evidence(s, r) != (request.observation_head.public(), request.evidence_sha256):
        error("vendor_evidence_changed")
    state = _states(s, t, r)
    if (
        _verification_reason(state, result, actor) != "available"
        or request.reviewed_conflicting_evidence != state["conflicting_evidence"]
    ):
        error("vendor_exception_unresolved")
    t.state, t.closed_at, t.version = "closed", _clock(s), t.version + 1
    receipt = _record(
        s, w, actor, "verify", request, digest, t, r, "verified", result_receipt=result
    )
    s.commit()
    return command_response(s, receipt)
