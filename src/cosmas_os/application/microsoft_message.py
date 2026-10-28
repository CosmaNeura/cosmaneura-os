"""Human-only Microsoft message custody. No note, clinical review, model or F8 writes."""

from __future__ import annotations

import hashlib
import json
import re
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

from sqlalchemy import func, select

from cosmas_os.application import model_work
from cosmas_os.application import workspace as ws
from cosmas_os.domain.hashing import canonical_json, payload_hash
from cosmas_os.microsoft_connection_models import MicrosoftConnectionCredential
from cosmas_os.microsoft_message_models import (
    MicrosoftMessageReadRequest,
    MicrosoftMessageSnapshot,
    MicrosoftMessageSourceReview,
)
from cosmas_os.models import ExternalIdentity, WorkspaceEntry
from cosmas_os.ports.microsoft_message import (
    MicrosoftMessageBinding,
    MicrosoftMessageRead,
    MicrosoftMessageSelection,
)

_binding_reader = None
_ID = re.compile(r"^[A-Za-z0-9_+/=-]{1,2048}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


@contextmanager
def install_binding_reader(reader):
    """Lifecycle-owned, DB-only reader shared by HTTP and model worker threads."""
    global _binding_reader
    previous, _binding_reader = _binding_reader, reader
    try:
        yield
    finally:
        _binding_reader = previous


def _identity(s, box, actor, account_id, *, writing=False):
    ws._human(s, box, actor, creating=writing)
    row = s.scalar(
        select(ExternalIdentity)
        .where(
            ExternalIdentity.id == account_id,
            ExternalIdentity.box_id == box,
            ExternalIdentity.principal_id == actor,
            ExternalIdentity.active.is_(True),
        )
        .with_for_update(read=not writing)
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise ws.WorkspaceError("workspace_access_denied", 403)
    return row


def _scoped_identity(account):
    return SimpleNamespace(
        box_id=account.box_id,
        principal_id=account.principal_id,
        auth_mode="clerk_jwt",
        external_identity_id=account.id,
        organization_id=account.organization_id,
    )


def _binding(s, account, *, require_full=True, port=None):
    credential = s.scalar(
        select(MicrosoftConnectionCredential)
        .where(
            MicrosoftConnectionCredential.account_id == account.id,
        )
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if (
        credential is None
        or credential.status != "ready"
        or credential.sealed is None
        or credential.expires_at <= datetime.now(UTC)
    ):
        raise ws.WorkspaceError("microsoft_message_grant_unavailable")
    try:
        if port is not None:
            result = port.message_binding(
                _scoped_identity(account), require_full=require_full, session=s
            )
        elif _binding_reader is not None:
            result = _binding_reader(s, account, require_full)
        else:
            raise ValueError("missing binding reader")
        if not isinstance(result, MicrosoftMessageBinding):
            result = MicrosoftMessageBinding.model_validate(result)
        if (result.account_id, result.binding_digest, result.connected_at) != (
            account.id,
            credential.binding_digest,
            credential.connected_at,
        ):
            raise ValueError("binding changed")
    except ws.WorkspaceError:
        raise
    except Exception:
        raise ws.WorkspaceError("microsoft_message_grant_unavailable") from None
    return result


def _same_binding(read, binding):
    return (read.account_id, read.binding_digest, read.connected_at, read.grant_sha256) == (
        binding.account_id,
        binding.binding_digest,
        binding.connected_at,
        binding.grant_sha256,
    )


def _authorize(s, read, *, port=None, require_full=True):
    account = _identity(s, read.box_id, read.owner_id, read.account_id)
    if not _same_binding(read, _binding(s, account, require_full=require_full, port=port)):
        raise ws.WorkspaceError("microsoft_message_grant_changed")
    return account


def _request_body(
    kind, account_id, observation_id=None, observation_sha256=None, message_id=None, thread_id=None
):
    return dict(
        kind=kind,
        account_id=account_id,
        observation_id=observation_id,
        observation_sha256=observation_sha256,
        message_id=message_id,
        thread_id=thread_id,
    )


def _commitment(read, payload_sha256):
    return payload_hash(
        dict(
            read_id=read.id,
            account_id=read.account_id,
            ordinal=read.ordinal,
            request_hash=read.request_hash,
            binding_digest=read.binding_digest,
            grant_sha256=read.grant_sha256,
            payload_sha256=payload_sha256,
        )
    )


def _payload_digest(payload):
    # Match existing PostgreSQL vendor_public_canonical UTF-8 text serialization.
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _aware(value):
    if not isinstance(value, str):
        raise ValueError("invalid time")
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("invalid time")
    return result


def _list_payload(payload):
    if not isinstance(payload, dict) or set(payload) != {
        "kind",
        "account",
        "items",
        "more",
        "observed_at",
    }:
        raise ValueError("invalid mail observation")
    account, items = payload["account"], payload["items"]
    if (
        payload["kind"] != "mail"
        or type(payload["more"]) is not bool
        or not isinstance(account, dict)
        or set(account) != {"label", "email"}
        or any(not isinstance(account[k], str) or len(account[k]) > 320 for k in account)
        or not isinstance(items, list)
        or len(items) > 25
    ):
        raise ValueError("invalid mail observation")
    _aware(payload["observed_at"])
    seen = set()
    for item in items:
        if (
            not isinstance(item, dict)
            or set(item)
            not in (
                {"id", "subject", "sender", "received_at", "is_read"},
                {"id", "thread_id", "subject", "sender", "received_at", "is_read"},
            )
            or not isinstance(item["id"], str)
            or not _ID.fullmatch(item["id"])
            or item["id"] in seen
            or type(item["is_read"]) is not bool
            or any(
                not isinstance(item[k], str) or len(item[k]) > limit
                for k, limit in (("subject", 998), ("sender", 320))
            )
            or "thread_id" in item
            and (not isinstance(item["thread_id"], str) or not _ID.fullmatch(item["thread_id"]))
        ):
            raise ValueError("invalid mail observation")
        _aware(item["received_at"])
        seen.add(item["id"])
    if len(canonical_json(payload).encode()) > 60000:
        raise ValueError("oversize mail observation")
    return payload


def _snapshot(s, read, *, verify_parent=True):
    snap = s.scalar(select(MicrosoftMessageSnapshot).where(MicrosoftMessageSnapshot.read_id == read.id))
    if snap is None:
        raise ws.WorkspaceError("microsoft_message_read_unconfirmed", 409)
    try:
        if (snap.box_id, snap.owner_id) != (read.box_id, read.owner_id):
            raise ValueError("snapshot scope")
        if read.request_hash != payload_hash(
            _request_body(
                read.kind,
                read.account_id,
                read.observation_id,
                read.observation_sha256,
                read.message_id,
                read.thread_id,
            )
        ):
            raise ValueError("request changed")
        if snap.payload_sha256 != _payload_digest(
            snap.payload
        ) or snap.source_sha256 != _commitment(read, snap.payload_sha256):
            raise ValueError("snapshot changed")
        if read.kind == "list":
            _list_payload(snap.payload)
        elif read.kind == "message":
            parsed = MicrosoftMessageRead.model_validate_json(canonical_json(snap.payload))
            if (
                parsed.message_id != read.message_id
                or read.thread_id is not None
                and parsed.thread_id != read.thread_id
            ):
                raise ValueError("message changed")
            if not _same_binding(read, parsed.custody):
                raise ValueError("custody changed")
            if (
                parsed.content is not None
                and parsed.content_sha256 != hashlib.sha256(parsed.content.encode()).hexdigest()
            ):
                raise ValueError("content changed")
            if verify_parent:
                parent = s.get(MicrosoftMessageReadRequest, read.observation_id)
                if (
                    parent is None
                    or parent.kind != "list"
                    or (parent.box_id, parent.owner_id, parent.account_id)
                    != (read.box_id, read.owner_id, read.account_id)
                ):
                    raise ValueError("observation scope")
                prior = _snapshot(s, parent, verify_parent=False)
                if prior.source_sha256 != read.observation_sha256 or not any(
                    item["id"] == read.message_id
                    and (read.thread_id is None or item.get("thread_id") == read.thread_id)
                    for item in prior.payload["items"]
                ):
                    raise ValueError("unobserved selection")
        else:
            raise ValueError("invalid kind")
    except (ValueError, TypeError, KeyError):
        raise ws.WorkspaceError("microsoft_message_source_invalid") from None
    return snap


def _receipt(read, snap):
    return dict(
        read_id=read.id,
        read_key=read.idempotency_key,
        kind=read.kind,
        observation_id=read.id if read.kind == "list" else read.observation_id,
        source_sha256=snap.source_sha256,
        payload_sha256=snap.payload_sha256,
        status="observed" if read.kind == "list" else snap.payload["status"],
        message={k: v for k, v in snap.payload.items() if k != "custody"}
        if read.kind == "message"
        else None,
        observation=snap.payload if read.kind == "list" else None,
    )


def _access(s, box, actor, account_id, reauthenticate):
    model_work.lock_owner(s, box, actor)
    if reauthenticate is not None:
        reauthenticate()
    return _identity(s, box, actor, account_id, writing=True)


def _read(
    s,
    box,
    actor,
    external_identity_id,
    *,
    key,
    kind,
    port,
    observation_id=None,
    observation_sha256=None,
    message_id=None,
    thread_id=None,
    reauthenticate=None,
):
    if not isinstance(key, str) or not 1 <= len(key) <= 100 or "\0" in key:
        raise ws.WorkspaceError("invalid_microsoft_message_request", 422)
    if kind == "message":
        try:
            if not isinstance(message_id, str):
                raise ValueError("invalid message ID")
            selection = MicrosoftMessageSelection(message_id=message_id, thread_id=thread_id)
            if not isinstance(observation_sha256, str) or not _DIGEST.fullmatch(observation_sha256):
                raise ValueError("invalid hash")
        except (ValueError, TypeError):
            raise ws.WorkspaceError("invalid_microsoft_message_request", 422) from None
    account = _access(s, box, actor, external_identity_id, reauthenticate)
    body = _request_body(
        kind, account.id, observation_id, observation_sha256, message_id, thread_id
    )
    request_hash = payload_hash(body)
    replay = s.scalar(
        select(MicrosoftMessageReadRequest).where(
            MicrosoftMessageReadRequest.box_id == box,
            MicrosoftMessageReadRequest.owner_id == actor,
            MicrosoftMessageReadRequest.idempotency_key == key,
        )
    )
    if replay is not None:
        if replay.request_hash != request_hash:
            raise ws.WorkspaceError("idempotency_conflict")
        _authorize(s, replay, port=port, require_full=kind == "message")
        return _receipt(replay, _snapshot(s, replay))
    binding = _binding(s, account, port=port, require_full=kind == "message")
    if kind == "message":
        parent = s.get(MicrosoftMessageReadRequest, observation_id)
        if (
            parent is None
            or parent.kind != "list"
            or (parent.box_id, parent.owner_id, parent.account_id) != (box, actor, account.id)
        ):
            raise ws.WorkspaceError("microsoft_message_observation_unavailable", 404)
        _authorize(s, parent, port=port, require_full=False)
        snap = _snapshot(s, parent)
        if snap.source_sha256 != observation_sha256 or not any(
            item["id"] == message_id and (thread_id is None or item.get("thread_id") == thread_id)
            for item in snap.payload["items"]
        ):
            raise ws.WorkspaceError("microsoft_message_not_observed")
    ordinal = (
        s.scalar(
            select(func.max(MicrosoftMessageReadRequest.ordinal)).where(
                MicrosoftMessageReadRequest.account_id == account.id
            )
        )
        or 0
    ) + 1
    read = MicrosoftMessageReadRequest(
        box_id=box,
        owner_id=actor,
        ordinal=ordinal,
        idempotency_key=key,
        request_hash=request_hash,
        binding_digest=binding.binding_digest,
        connected_at=binding.connected_at,
        grant_sha256=binding.grant_sha256,
        **body,
    )
    s.add(read)
    s.flush()
    read_id = read.id
    provider_identity = _scoped_identity(account)
    s.commit()  # Persist reservation and release all owner/account locks before provider I/O.
    try:
        if kind == "list":
            payload = _list_payload(port.mail(provider_identity))
        else:
            result = port.read_message(provider_identity, selection)
            if not isinstance(result, MicrosoftMessageRead):
                result = MicrosoftMessageRead.model_validate(result)
            payload = result.model_dump(mode="json")
        _access(s, box, actor, external_identity_id, reauthenticate)
        read = s.get(MicrosoftMessageReadRequest, read_id, populate_existing=True)
        _authorize(s, read, port=port, require_full=kind == "message")
        snap = MicrosoftMessageSnapshot(
            box_id=box,
            owner_id=actor,
            read_id=read.id,
            payload=payload,
            payload_sha256=_payload_digest(payload),
            source_sha256=_commitment(read, _payload_digest(payload)),
        )
        s.add(snap)
        s.flush()
        _snapshot(s, read)
        if reauthenticate is not None:
            reauthenticate()
        _authorize(s, read, port=port, require_full=kind == "message")
        s.commit()
        return _receipt(read, snap)
    except ws.WorkspaceError:
        s.rollback()
        raise
    except Exception:
        s.rollback()
        raise ws.WorkspaceError("microsoft_message_read_unconfirmed", 503) from None


def list_observed(s, box, actor, external_identity_id, *, key, port, reauthenticate=None):
    return _read(
        s,
        box,
        actor,
        external_identity_id,
        key=key,
        kind="list",
        port=port,
        reauthenticate=reauthenticate,
    )


def read_selected(
    s,
    box,
    actor,
    external_identity_id,
    *,
    key,
    observation_id,
    observation_sha256,
    message_id,
    thread_id=None,
    port,
    reauthenticate=None,
):
    return _read(
        s,
        box,
        actor,
        external_identity_id,
        key=key,
        kind="message",
        port=port,
        observation_id=observation_id,
        observation_sha256=observation_sha256,
        message_id=message_id,
        thread_id=thread_id,
        reauthenticate=reauthenticate,
    )


def inspect_read(s, box, actor, external_identity_id, *, read_id, port, reauthenticate=None):
    _access(s, box, actor, external_identity_id, reauthenticate)
    read = s.get(MicrosoftMessageReadRequest, read_id)
    if read is None or (read.box_id, read.owner_id, read.account_id) != (
        box,
        actor,
        external_identity_id,
    ):
        raise ws.WorkspaceError("microsoft_message_read_unavailable", 404)
    _authorize(s, read, port=port, require_full=read.kind == "message")
    result = _receipt(read, _snapshot(s, read))
    if reauthenticate is not None:
        reauthenticate()
    _authorize(s, read, port=port, require_full=read.kind == "message")
    return result


def resolve_read(s, box, actor, external_identity_id, *, key, kind, port, reauthenticate=None):
    """Reconcile a lost local reply without another provider request."""
    if kind not in {"list", "message"} or not isinstance(key, str) or not 1 <= len(key) <= 100:
        raise ws.WorkspaceError("invalid_microsoft_message_request", 422)
    _access(s, box, actor, external_identity_id, reauthenticate)
    read = s.scalar(
        select(MicrosoftMessageReadRequest).where(
            MicrosoftMessageReadRequest.box_id == box,
            MicrosoftMessageReadRequest.owner_id == actor,
            MicrosoftMessageReadRequest.idempotency_key == key,
        )
    )
    if read is None:
        return dict(status="not_found", kind=kind, read_key=key, read_id=None)
    if (read.account_id, read.kind) != (external_identity_id, kind):
        raise ws.WorkspaceError("idempotency_conflict")
    try:
        _authorize(s, read, port=port, require_full=kind == "message")
    except ws.WorkspaceError as error:
        if error.code not in {"microsoft_message_grant_unavailable", "microsoft_message_grant_changed"}:
            raise
        # Current CosmaBot owner/account access was checked above. Old provider
        # custody cannot disclose a snapshot, but its exact intent can be retained
        # while the human explicitly starts work with a new connected grant.
        if reauthenticate is not None:
            reauthenticate()
        return dict(status="unavailable", kind=kind, read_key=key, read_id=read.id)
    snap = s.scalar(
        select(MicrosoftMessageSnapshot.id).where(MicrosoftMessageSnapshot.read_id == read.id)
    )
    if snap is None:
        return dict(status="unconfirmed", kind=kind, read_key=key, read_id=read.id)
    return inspect_read(
        s,
        box,
        actor,
        external_identity_id,
        read_id=read.id,
        port=port,
        reauthenticate=reauthenticate,
    )


def _latest(s, read):
    newer = s.scalar(
        select(MicrosoftMessageReadRequest.id)
        .where(
            MicrosoftMessageReadRequest.account_id == read.account_id,
            MicrosoftMessageReadRequest.kind == "message",
            MicrosoftMessageReadRequest.message_id == read.message_id,
            MicrosoftMessageReadRequest.ordinal > read.ordinal,
        )
        .limit(1)
    )
    if newer is not None:
        raise ws.WorkspaceError("microsoft_message_source_superseded")


def historical_source(s, w, entry_id):
    entry = s.get(WorkspaceEntry, entry_id)
    review = s.scalar(
        select(MicrosoftMessageSourceReview).where(MicrosoftMessageSourceReview.entry_id == entry_id)
    )
    if (
        entry is None
        or review is None
        or (entry.workspace_id, entry.box_id, entry.actor_id, entry.kind)
        != (w.id, w.box_id, w.owner_id, "microsoft_message")
    ):
        raise ws.WorkspaceError("microsoft_message_source_unavailable", 404)
    snap = s.get(MicrosoftMessageSnapshot, review.snapshot_id)
    read = s.get(MicrosoftMessageReadRequest, snap.read_id) if snap is not None else None
    if snap is None or read is None or read.kind != "message":
        raise ws.WorkspaceError("microsoft_message_source_invalid")
    if (snap.box_id, snap.owner_id, read.box_id, read.owner_id) != (
        w.box_id,
        w.owner_id,
        w.box_id,
        w.owner_id,
    ):
        raise ws.WorkspaceError("microsoft_message_source_invalid")
    _snapshot(s, read)
    body = dict(
        expected=review.expected_revision,
        read_id=read.id,
        source_sha256=review.source_sha256,
        patient_link_id=review.patient_link_id,
        reviewed_patient=review.reviewed_patient,
        reviewed_exact_message=review.reviewed_exact_message,
        reviewed_untrusted_source=review.reviewed_untrusted_source,
    )
    if (
        review.workspace_id,
        review.box_id,
        review.owner_id,
        review.patient_link_id,
        review.workspace_revision,
        review.source_sha256,
        review.content_sha256,
    ) != (
        w.id,
        w.box_id,
        w.owner_id,
        w.patient_link_id,
        entry.revision,
        snap.source_sha256,
        snap.payload.get("content_sha256"),
    ) or (
        snap.payload.get("status") != "complete"
        or entry.content != snap.payload.get("content")
        or entry.content != ""
        and hashlib.sha256(entry.content.encode()).hexdigest() != review.content_sha256
        or review.workspace_revision != review.expected_revision + 1
        or not all(
            (
                review.reviewed_patient,
                review.reviewed_exact_message,
                review.reviewed_untrusted_source,
            )
        )
        or review.request_hash != payload_hash(body)
        or entry.request_hash != review.request_hash
        or entry.idempotency_key != review.idempotency_key
        or entry.source_label != ("Outlook message: " + snap.payload["subject"])[:160]
    ):
        raise ws.WorkspaceError("microsoft_message_source_invalid")
    return entry


def validate_selected_source(s, w, entry_id):
    model_work.read_workspace(s, w.box_id, w.owner_id, w.id)
    entry = historical_source(s, w, entry_id)
    review = s.scalar(
        select(MicrosoftMessageSourceReview).where(MicrosoftMessageSourceReview.entry_id == entry_id)
    )
    snap = s.get(MicrosoftMessageSnapshot, review.snapshot_id)
    read = s.get(MicrosoftMessageReadRequest, snap.read_id)
    _authorize(s, read)
    _latest(s, read)
    return entry


def selected_entries(s, w, settings, at_revision):
    from cosmas_os.ports.bot_capabilities import supports_skill

    if not supports_skill(settings, "saved_context") or not settings["include_evidence"]:
        return []
    entries = list(
        s.scalars(
            select(WorkspaceEntry)
            .where(
                WorkspaceEntry.workspace_id == w.id,
                WorkspaceEntry.box_id == w.box_id,
                WorkspaceEntry.actor_id == w.owner_id,
                WorkspaceEntry.kind == "microsoft_message",
                WorkspaceEntry.revision <= at_revision,
            )
            .order_by(WorkspaceEntry.revision)
        )
    )
    result = []
    for entry in entries:
        try:
            result.append(validate_selected_source(s, w, entry.id))
        except ws.WorkspaceError:
            continue  # Historical source remains retained; never disclose an invalid current source.
    return result


def _selection_receipt(s, w, read, review, entry):
    """Confirm the exact saved public command without restoring source authority."""
    workspace = ws.read(s, w.box_id, w.owner_id, w.id)
    projected = next(e for e in workspace["entries"] if e["id"] == entry.id)
    return dict(
        entry_id=entry.id,
        entry_revision=entry.revision,
        workspace=workspace,
        source=dict(entry_id=entry.id, source_sha256=review.source_sha256,
                    content_sha256=review.content_sha256),
        request_sha256=payload_hash(dict(
            workspace_id=w.id, expected_revision=review.expected_revision,
            idempotency_key=review.idempotency_key, read_id=read.id,
            source_sha256=review.source_sha256, content_sha256=review.content_sha256,
            reviewed_patient=review.reviewed_patient,
            reviewed_exact_message=review.reviewed_exact_message,
            reviewed_untrusted_source=review.reviewed_untrusted_source,
        )),
        source_withheld=projected.get("microsoft_source_state") == "unavailable",
    )


def select_review(
    s,
    box,
    actor,
    wid,
    *,
    expected,
    key,
    read_id,
    source_sha256,
    patient_link_id,
    reviewed_patient,
    reviewed_exact_message,
    reviewed_untrusted_source,
    port=None,
    external_identity_id=None,
    reauthenticate=None,
) -> dict:
    if (
        type(expected) is not int
        or expected < 1
        or not isinstance(key, str)
        or not 1 <= len(key) <= 100
        or "\0" in key
        or not isinstance(source_sha256, str)
        or not _DIGEST.fullmatch(source_sha256)
        or any(
            value is not True
            for value in (reviewed_patient, reviewed_exact_message, reviewed_untrusted_source)
        )
    ):
        raise ws.WorkspaceError("invalid_microsoft_message_review", 422)
    model_work.lock_owner(s, box, actor)
    if reauthenticate is not None:
        reauthenticate()
    w = ws._workspace(s, box, actor, wid, writing=True)
    read = s.get(MicrosoftMessageReadRequest, read_id)
    if (
        read is None
        or read.kind != "message"
        or (read.box_id, read.owner_id) != (box, actor)
        or (external_identity_id is not None and read.account_id != external_identity_id)
    ):
        raise ws.WorkspaceError("microsoft_message_read_unavailable", 404)
    # A saved receipt remains recoverable after OAuth revocation. The signed-in
    # owner/account must still be active; replay never permits another source read.
    _identity(s, box, actor, read.account_id)
    snap = _snapshot(s, read)
    body = dict(
        expected=expected,
        read_id=read_id,
        source_sha256=source_sha256,
        patient_link_id=patient_link_id,
        reviewed_patient=reviewed_patient,
        reviewed_exact_message=reviewed_exact_message,
        reviewed_untrusted_source=reviewed_untrusted_source,
    )
    request_hash = payload_hash(body)
    replay = s.scalar(
        select(MicrosoftMessageSourceReview).where(
            MicrosoftMessageSourceReview.workspace_id == wid,
            MicrosoftMessageSourceReview.idempotency_key == key,
        )
    )
    if replay is not None:
        if replay.request_hash != request_hash:
            raise ws.WorkspaceError("idempotency_conflict")
        entry = historical_source(s, w, replay.entry_id)
        if reauthenticate is not None:
            reauthenticate()
        return _selection_receipt(s, w, read, replay, entry)
    _authorize(s, read, port=port)
    if s.scalar(
        select(WorkspaceEntry.id).where(
            WorkspaceEntry.workspace_id == wid, WorkspaceEntry.idempotency_key == key
        )
    ):
        raise ws.WorkspaceError("idempotency_conflict")
    if expected != w.revision:
        raise ws.WorkspaceError("workspace_revision_conflict")
    if patient_link_id != w.patient_link_id:
        raise ws.WorkspaceError("microsoft_message_patient_mismatch")
    if snap.source_sha256 != source_sha256:
        raise ws.WorkspaceError("microsoft_message_source_changed")
    if snap.payload.get("status") != "complete" or not snap.payload.get("content"):
        raise ws.WorkspaceError("microsoft_message_incomplete")
    _latest(s, read)
    if w.revision >= 500:
        raise ws.WorkspaceError("workspace_history_limit")
    if s.scalar(
        select(MicrosoftMessageSourceReview.id).where(
            MicrosoftMessageSourceReview.workspace_id == wid,
            MicrosoftMessageSourceReview.snapshot_id == snap.id,
        )
    ):
        raise ws.WorkspaceError("microsoft_message_already_selected")
    w.revision += 1
    entry = WorkspaceEntry(
        workspace_id=wid,
        box_id=box,
        actor_id=actor,
        revision=w.revision,
        kind="microsoft_message",
        content=snap.payload["content"],
        source_label=("Outlook message: " + snap.payload["subject"])[:160],
        idempotency_key=key,
        request_hash=request_hash,
    )
    s.add(entry)
    s.flush()
    review = MicrosoftMessageSourceReview(
        workspace_id=wid,
        box_id=box,
        owner_id=actor,
        entry_id=entry.id,
        snapshot_id=snap.id,
        workspace_revision=w.revision,
        idempotency_key=key,
        request_hash=request_hash,
        content_sha256=snap.payload["content_sha256"],
        **{k: v for k, v in body.items() if k != "read_id" and k != "expected"},
        expected_revision=expected,
    )
    s.add(review)
    ws._audit(s, w, "microsoft_message_reviewed")
    if reauthenticate is not None:
        reauthenticate()
    _authorize(s, read, port=port)
    _latest(s, read)
    s.commit()
    return _selection_receipt(s, w, read, review, entry)
