"""Authenticated file snapshots and explicit reviewed calendar-source custody."""

import base64
import binascii
import hashlib
import importlib.util
import re
from contextvars import ContextVar
from dataclasses import asdict
from datetime import UTC
from uuid import uuid4

from sqlalchemy import func, select

from cosmas_os.adapters.calendar_file_import import (
    MAX_BYTES,
    CalendarFileImportError,
    parse_calendar_file,
)
from cosmas_os.application import model_work
from cosmas_os.application import workspace as ws
from cosmas_os.calendar_import_models import (
    CalendarImportRequest,
    CalendarImportRevocation,
    CalendarImportSnapshot,
    CalendarImportSourceReview,
)
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.models import ExternalIdentity, WorkspaceEntry
from cosmas_os.ports.calendar_imports import Item, SnapshotPayload, Window

SOURCE_LABEL = "Imported calendar snapshot"
_KEY = re.compile(r"^[A-Za-z0-9:_-]{8,100}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_withheld_sources = ContextVar("calendar_import_withheld_sources", default=frozenset())


def _stamp(value):
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _identity(s, box, actor, account_id):
    ws._human(s, box, actor)
    account = s.scalar(select(ExternalIdentity).where(ExternalIdentity.id == account_id,
        ExternalIdentity.box_id == box, ExternalIdentity.principal_id == actor,
        ExternalIdentity.active.is_(True)).with_for_update(read=True).execution_options(populate_existing=True))
    if account is None:
        raise ws.WorkspaceError("workspace_access_denied", 403)
    return account


def authorize_request(s, box, actor, account_id, wid, *, reauthenticate=None):
    model_work.lock_owner(s, box, actor)
    if reauthenticate:
        reauthenticate()
    _identity(s, box, actor, account_id)
    return ws._workspace(s, box, actor, wid, writing=True)


def _scope(w, account_id):
    return dict(box_id=w.box_id, owner_id=w.owner_id, account_id=account_id,
                workspace_id=w.id, patient_link_id=w.patient_link_id)


def status(s, box, actor, account_id, wid, *, enabled, reauthenticate=None):
    w = authorize_request(s, box, actor, account_id, wid, reauthenticate=reauthenticate)
    return dict(status="available" if enabled and importlib.util.find_spec("icalendar") else "unavailable",
                scope=_scope(w, account_id), file_limit_bytes=MAX_BYTES, max_items=25,
                formats=["ics"], reported_sources=["atlas_md", "other_calendar"])


def _key(value):
    if not isinstance(value, str) or not _KEY.fullmatch(value):
        raise ws.WorkspaceError("invalid_calendar_import_request", 422)


def _digest(value):
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise ws.WorkspaceError("invalid_calendar_import_request", 422)


def _unused_key(s, wid, key):
    for table in (CalendarImportRequest, CalendarImportSourceReview, CalendarImportRevocation, WorkspaceEntry):
        if s.scalar(select(table.id).where(table.workspace_id == wid, table.idempotency_key == key)):
            raise ws.WorkspaceError("idempotency_conflict")


def upload_body(wid, key, byte_sha256, reported_source, window):
    return dict(kind="calendar-import-v1", action="upload", workspace_id=wid,
                idempotency_key=key, byte_sha256=byte_sha256, reported_source=reported_source, window=window)


def _request_body(read):
    return upload_body(read.workspace_id, read.idempotency_key, read.byte_sha256, read.reported_source,
        dict(starts_on=read.window_start.isoformat(), ends_on=read.window_end.isoformat(), timezone=read.timezone))


def _commitment(read, payload_sha256):
    return dict(kind="calendar-import-snapshot-v1", import_id=read.id, box_id=read.box_id,
        owner_id=read.owner_id, account_id=read.account_id, workspace_id=read.workspace_id,
        patient_link_id=read.patient_link_id, request_sha256=read.request_hash, payload_sha256=payload_sha256)


def item_hash(item):
    return payload_hash(dict(kind="calendar-import-item-v1", item=item.model_dump(mode="json")
                             if isinstance(item, Item) else item))


def _selected_hash(import_sha256, item_index, item_sha256):
    return payload_hash(dict(kind="calendar-import-selected-v1", import_sha256=import_sha256,
                             item_index=item_index, item_sha256=item_sha256))


def _snapshot(s, read):
    snap = s.scalar(select(CalendarImportSnapshot).where(CalendarImportSnapshot.import_id == read.id)
                    .execution_options(populate_existing=True))
    try:
        if snap is None or (snap.workspace_id, snap.box_id, snap.owner_id) != (read.workspace_id, read.box_id, read.owner_id):
            raise ValueError
        payload = SnapshotPayload.model_validate(snap.payload)
        if (payload.imported_at != _stamp(read.created_at) or payload.reported_source != read.reported_source
                or payload.window.model_dump(mode="json") != _request_body(read)["window"]
                or payload_hash(_request_body(read)) != read.request_hash
                or payload_hash(snap.payload) != snap.payload_sha256
                or payload_hash(_commitment(read, snap.payload_sha256)) != snap.source_sha256):
            raise ValueError
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ws.WorkspaceError("calendar_import_source_invalid") from None
    return snap


def _read(s, w, account_id, import_id):
    read = s.scalar(select(CalendarImportRequest).where(CalendarImportRequest.id == import_id,
        CalendarImportRequest.workspace_id == w.id, CalendarImportRequest.box_id == w.box_id,
        CalendarImportRequest.owner_id == w.owner_id, CalendarImportRequest.account_id == account_id)
        .execution_options(populate_existing=True))
    if read is None or read.patient_link_id != w.patient_link_id:
        raise ws.WorkspaceError("calendar_import_unavailable", 404)
    return read


def _revoked(s, read):
    return s.scalar(select(CalendarImportRevocation.id).where(CalendarImportRevocation.import_id == read.id)) is not None


def _receipt(s, w, read):
    snap = _snapshot(s, read)
    withheld = _revoked(s, read)
    for review in s.scalars(select(CalendarImportSourceReview).where(CalendarImportSourceReview.snapshot_id == snap.id)):
        try:
            historical_source(s, w, review.entry_id)
        except ws.WorkspaceError:
            withheld = True
    result = dict(status="withheld" if withheld else "imported", scope=_scope(w, read.account_id),
        import_id=read.id, idempotency_key=read.idempotency_key, request_sha256=read.request_hash,
        byte_sha256=read.byte_sha256, source_sha256=snap.source_sha256)
    if not withheld:
        result.update(payload_sha256=snap.payload_sha256, payload=snap.payload)
    return result


def inspect_import(s, box, actor, account_id, wid, *, import_id, reauthenticate=None):
    w = authorize_request(s, box, actor, account_id, wid, reauthenticate=reauthenticate)
    return _receipt(s, w, _read(s, w, account_id, import_id))


def resolve_import(s, box, actor, account_id, wid, *, key, reauthenticate=None):
    _key(key)
    w = authorize_request(s, box, actor, account_id, wid, reauthenticate=reauthenticate)
    read = s.scalar(select(CalendarImportRequest).where(CalendarImportRequest.workspace_id == wid,
        CalendarImportRequest.idempotency_key == key))
    if read is None:
        return dict(status="not_found", scope=_scope(w, account_id), workspace_id=wid, idempotency_key=key)
    return _receipt(s, w, _read(s, w, account_id, read.id))


def list_imports(s, box, actor, account_id, wid, *, reauthenticate=None):
    w = authorize_request(s, box, actor, account_id, wid, reauthenticate=reauthenticate)
    reads = list(s.scalars(select(CalendarImportRequest).where(CalendarImportRequest.workspace_id == wid,
        CalendarImportRequest.box_id == box, CalendarImportRequest.owner_id == actor,
        CalendarImportRequest.account_id == account_id, CalendarImportRequest.patient_link_id == w.patient_link_id)
        .order_by(CalendarImportRequest.created_at, CalendarImportRequest.id).limit(101)))
    if len(reads) > 100:
        raise ws.WorkspaceError("calendar_import_limit")
    items = []
    for read in reads:
        receipt = _receipt(s, w, read)
        snap = _snapshot(s, read)
        reviewed_indices = sorted(s.scalars(select(CalendarImportSourceReview.item_index).where(
            CalendarImportSourceReview.snapshot_id == snap.id)))
        items.append({key: receipt[key] for key in ("status", "import_id", "idempotency_key", "byte_sha256", "request_sha256", "source_sha256")}
            | dict(reported_source=read.reported_source, window=_request_body(read)["window"],
                   imported_at=_stamp(read.created_at), reviewed_item_indices=reviewed_indices))
    return dict(status="listed", scope=_scope(w, account_id), imports=items, more=False)


def upload(s, box, actor, account_id, wid, *, key, byte_sha256, file_base64, window,
           reported_source, reauthenticate=None):
    w = authorize_request(s, box, actor, account_id, wid, reauthenticate=reauthenticate)
    _key(key)
    _digest(byte_sha256)
    try:
        chosen = Window.model_validate(window)
        if reported_source not in ("atlas_md", "other_calendar") or not isinstance(file_base64, str) or len(file_base64) > 1398104:
            raise ValueError
        raw = base64.b64decode(file_base64, validate=True)
        if (not raw or len(raw) > MAX_BYTES or base64.b64encode(raw).decode("ascii") != file_base64
                or hashlib.sha256(raw).hexdigest() != byte_sha256):
            raise ValueError
    except (ValueError, TypeError, binascii.Error):
        raise ws.WorkspaceError("calendar_file_mismatch", 422) from None
    body = upload_body(wid, key, byte_sha256, reported_source, chosen.model_dump(mode="json"))
    request_hash = payload_hash(body)
    replay = s.scalar(select(CalendarImportRequest).where(CalendarImportRequest.workspace_id == wid,
        CalendarImportRequest.idempotency_key == key))
    if replay is not None:
        del raw
        if replay.request_hash != request_hash:
            raise ws.WorkspaceError("idempotency_conflict")
        return inspect_import(s, box, actor, account_id, wid, import_id=replay.id, reauthenticate=reauthenticate)
    _unused_key(s, wid, key)
    if ((s.scalar(select(func.count()).select_from(CalendarImportRequest).where(CalendarImportRequest.workspace_id == wid)) or 0) >= 100
            or (s.scalar(select(func.count()).select_from(CalendarImportRequest).where(
                CalendarImportRequest.box_id == box, CalendarImportRequest.owner_id == actor)) or 0) >= 500):
        raise ws.WorkspaceError("calendar_import_limit")
    try:
        parsed = parse_calendar_file(raw, chosen.parser_window())
    except CalendarFileImportError as exc:
        raise ws.WorkspaceError(exc.code, 422 if exc.code != "calendar_parser_unavailable" else 503) from None
    finally:
        del raw
    w = authorize_request(s, box, actor, account_id, wid, reauthenticate=reauthenticate)
    now = model_work.now(s).replace(microsecond=0)
    try:
        payload = SnapshotPayload.model_validate(dict(imported_at=_stamp(now), reported_source=reported_source,
            window=chosen.model_dump(mode="json"), items=[asdict(item) for item in parsed.items],
            total_events=parsed.total_events, matching_events=parsed.matching_events, more=parsed.more,
            coverage=parsed.coverage)).model_dump(mode="json")
    except (ValueError, TypeError):
        raise ws.WorkspaceError("calendar_event_invalid", 422) from None
    read = CalendarImportRequest(id=str(uuid4()), workspace_id=wid, box_id=box, owner_id=actor,
        account_id=account_id, patient_link_id=w.patient_link_id, idempotency_key=key,
        request_hash=request_hash, byte_sha256=byte_sha256, reported_source=reported_source,
        window_start=chosen.parser_window().starts_on, window_end=chosen.parser_window().ends_on,
        timezone=chosen.timezone, created_at=now)
    digest = payload_hash(payload)
    snap = CalendarImportSnapshot(id=str(uuid4()), workspace_id=wid, box_id=box, owner_id=actor,
        import_id=read.id, payload=payload, payload_sha256=digest,
        source_sha256=payload_hash(_commitment(read, digest)), created_at=now)
    s.add(read)
    s.flush()
    s.add(snap)
    s.flush()
    if reauthenticate:
        reauthenticate()
    authorize_request(s, box, actor, account_id, wid)
    s.commit()
    # Reacquire current custody after commit before any payload can be disclosed.
    return inspect_import(s, box, actor, account_id, wid, import_id=read.id, reauthenticate=reauthenticate)


def source_content(payload, item):
    if isinstance(item, Item):
        item = item.model_dump(mode="json")
    window = payload["window"]
    return "\n".join([
        SOURCE_LABEL,
        "Source reported by user: " + ("Atlas.md" if payload["reported_source"] == "atlas_md" else "Other calendar"),
        "Imported at: " + payload["imported_at"],
        "Title: " + (item["title"] or "(Untitled event)"),
        "Title truncated: " + ("yes" if item["title_truncated"] else "no"),
        "Starts: " + item["starts_at"], "Ends (exclusive): " + item["ends_at"],
        "All day: " + ("yes" if item["all_day"] else "no"),
        "Status: " + ("Cancelled" if item["cancelled"] else "Not marked cancelled"),
        "Window: " + window["starts_on"] + " through " + window["ends_on"] + " (end date excluded); timezone " + window["timezone"],
        "Coverage: Showing " + str(len(payload["items"])) + " of " + str(payload["matching_events"]) + " matching events in the supplied file. Other appointments may be missing.",
        "This staff-supplied calendar summary does not verify patient or chart identity, current availability, or a booking.",
    ])


def _review_body(wid, expected, key, import_id, source_sha256, item_index, item_sha256,
                 reviewed_visit, reviewed_exact_summary, reviewed_untrusted_source):
    return dict(action="review", workspace_id=wid, expected_revision=expected, idempotency_key=key,
        import_id=import_id, source_sha256=source_sha256, item_index=item_index, item_sha256=item_sha256,
        reviewed_visit=reviewed_visit, reviewed_exact_summary=reviewed_exact_summary,
        reviewed_untrusted_source=reviewed_untrusted_source)


def _revocation_body(wid, expected, key, import_id, source_sha256):
    return dict(action="revoke", workspace_id=wid, expected_revision=expected, idempotency_key=key,
                import_id=import_id, source_sha256=source_sha256)


def historical_source(s, w, entry_id):
    entry = s.get(WorkspaceEntry, entry_id)
    review = s.scalar(select(CalendarImportSourceReview).where(CalendarImportSourceReview.entry_id == entry_id))
    if (entry is None or review is None or (entry.workspace_id, entry.box_id, entry.actor_id, entry.kind)
            != (w.id, w.box_id, w.owner_id, "calendar_import_source")):
        raise ws.WorkspaceError("calendar_import_source_unavailable", 404)
    snap = s.get(CalendarImportSnapshot, review.snapshot_id)
    read = s.get(CalendarImportRequest, snap.import_id) if snap else None
    if snap is None or read is None:
        raise ws.WorkspaceError("calendar_import_source_invalid")
    _snapshot(s, read)
    item = next((row for row in snap.payload["items"] if row["item_index"] == review.item_index), None)
    if item is None:
        raise ws.WorkspaceError("calendar_import_source_invalid")
    content = source_content(snap.payload, item)
    body = _review_body(w.id, review.expected_revision, review.idempotency_key, read.id,
        review.import_sha256, review.item_index, review.item_sha256, review.reviewed_visit,
        review.reviewed_exact_summary, review.reviewed_untrusted_source)
    if ((read.workspace_id, read.box_id, read.owner_id, read.patient_link_id) != (w.id, w.box_id, w.owner_id, w.patient_link_id)
            or (review.workspace_id, review.box_id, review.owner_id, review.patient_link_id, review.workspace_revision)
            != (w.id, w.box_id, w.owner_id, w.patient_link_id, entry.revision)
            or item["cancelled"] or review.import_sha256 != snap.source_sha256
            or review.item_sha256 != item_hash(item)
            or review.source_sha256 != _selected_hash(review.import_sha256, review.item_index, review.item_sha256)
            or review.content_sha256 != hashlib.sha256(content.encode()).hexdigest() or entry.content != content
            or review.request_hash != payload_hash(body) or entry.request_hash != review.request_hash
            or entry.idempotency_key != review.idempotency_key or entry.source_label != SOURCE_LABEL
            or review.workspace_revision != review.expected_revision + 1
            or not all((review.reviewed_visit, review.reviewed_exact_summary, review.reviewed_untrusted_source))):
        raise ws.WorkspaceError("calendar_import_source_invalid")
    return entry


def validate_selected_source(s, w, entry_id):
    from cosmas_os.application import provider_team

    if (not provider_team.runtime_settings.workspace_calendar_import_available
            or (w.id, entry_id) in _withheld_sources.get()):
        raise ws.WorkspaceError("calendar_import_source_unavailable")
    model_work.read_workspace(s, w.box_id, w.owner_id, w.id)
    entry = historical_source(s, w, entry_id)
    review = s.scalar(select(CalendarImportSourceReview).where(CalendarImportSourceReview.entry_id == entry_id))
    snap = s.get(CalendarImportSnapshot, review.snapshot_id)
    read = s.get(CalendarImportRequest, snap.import_id)
    _identity(s, w.box_id, w.owner_id, read.account_id)
    if _revoked(s, read):
        raise ws.WorkspaceError("calendar_import_source_unavailable")
    return entry


def selected_entries(s, w, settings, at_revision):
    from cosmas_os.ports.bot_capabilities import supports_skill

    if not supports_skill(settings, "saved_context") or not settings["include_evidence"]:
        return []
    result = []
    for entry in s.scalars(select(WorkspaceEntry).where(WorkspaceEntry.workspace_id == w.id,
            WorkspaceEntry.box_id == w.box_id, WorkspaceEntry.actor_id == w.owner_id,
            WorkspaceEntry.kind == "calendar_import_source", WorkspaceEntry.revision <= at_revision).order_by(WorkspaceEntry.revision)):
        try:
            result.append(validate_selected_source(s, w, entry.id))
        except ws.WorkspaceError:
            continue
    return result


def _selection_receipt(s, w, read, review, entry, *, reauthenticate=None):
    w = authorize_request(s, w.box_id, w.owner_id, read.account_id, w.id, reauthenticate=reauthenticate)
    historical_source(s, w, entry.id)
    withheld = False
    try:
        validate_selected_source(s, w, entry.id)
    except ws.WorkspaceError:
        withheld = True
    token = _withheld_sources.set(_withheld_sources.get() | ({(w.id, entry.id)} if withheld else set()))
    try:
        workspace = ws.read(s, w.box_id, w.owner_id, w.id)
    finally:
        _withheld_sources.reset(token)
    return dict(entry_id=entry.id, entry_revision=entry.revision, workspace=workspace,
        source=dict(entry_id=entry.id, source_sha256=review.source_sha256, content_sha256=review.content_sha256),
        request_sha256=review.request_hash, source_withheld=withheld)


def select_review(s, box, actor, account_id, wid, *, expected, key, import_id, source_sha256,
                  item_index, item_sha256, reviewed_visit, reviewed_exact_summary,
                  reviewed_untrusted_source, reauthenticate=None):
    _key(key)
    _digest(source_sha256)
    _digest(item_sha256)
    if (type(expected) is not int or expected < 1 or type(item_index) is not int or not 0 <= item_index < 500
            or any(value is not True for value in (reviewed_visit, reviewed_exact_summary, reviewed_untrusted_source))):
        raise ws.WorkspaceError("invalid_calendar_import_review", 422)
    w = authorize_request(s, box, actor, account_id, wid, reauthenticate=reauthenticate)
    read = _read(s, w, account_id, import_id)
    snap = _snapshot(s, read)
    body = _review_body(wid, expected, key, import_id, source_sha256, item_index, item_sha256,
                        reviewed_visit, reviewed_exact_summary, reviewed_untrusted_source)
    request_hash = payload_hash(body)
    replay = s.scalar(select(CalendarImportSourceReview).where(CalendarImportSourceReview.workspace_id == wid,
        CalendarImportSourceReview.idempotency_key == key))
    if replay is not None:
        if replay.request_hash != request_hash:
            raise ws.WorkspaceError("idempotency_conflict")
        entry = historical_source(s, w, replay.entry_id)
        return _selection_receipt(s, w, read, replay, entry, reauthenticate=reauthenticate)
    _unused_key(s, wid, key)
    if _revoked(s, read):
        raise ws.WorkspaceError("calendar_import_source_unavailable")
    if expected != w.revision:
        raise ws.WorkspaceError("workspace_revision_conflict")
    item = next((row for row in snap.payload["items"] if row["item_index"] == item_index), None)
    if source_sha256 != snap.source_sha256 or item is None or item_hash(item) != item_sha256:
        raise ws.WorkspaceError("calendar_import_source_changed")
    if item["cancelled"]:
        raise ws.WorkspaceError("calendar_import_cancelled")
    if w.revision >= 500:
        raise ws.WorkspaceError("workspace_history_limit")
    if s.scalar(select(WorkspaceEntry.id).where(WorkspaceEntry.workspace_id == wid, WorkspaceEntry.idempotency_key == key)):
        raise ws.WorkspaceError("idempotency_conflict")
    if s.scalar(select(CalendarImportSourceReview.id).where(CalendarImportSourceReview.workspace_id == wid,
            CalendarImportSourceReview.snapshot_id == snap.id, CalendarImportSourceReview.item_index == item_index)):
        raise ws.WorkspaceError("calendar_import_already_selected")
    content = source_content(snap.payload, item)
    w.revision += 1
    entry = WorkspaceEntry(workspace_id=wid, box_id=box, actor_id=actor, revision=w.revision,
        kind="calendar_import_source", content=content, source_label=SOURCE_LABEL,
        idempotency_key=key, request_hash=request_hash)
    s.add(entry)
    s.flush()
    review = CalendarImportSourceReview(workspace_id=wid, box_id=box, owner_id=actor, entry_id=entry.id,
        snapshot_id=snap.id, patient_link_id=w.patient_link_id, expected_revision=expected,
        workspace_revision=w.revision, idempotency_key=key, request_hash=request_hash,
        import_sha256=source_sha256, item_index=item_index, item_sha256=item_sha256,
        source_sha256=_selected_hash(source_sha256, item_index, item_sha256),
        content_sha256=hashlib.sha256(content.encode()).hexdigest(), reviewed_visit=True,
        reviewed_exact_summary=True, reviewed_untrusted_source=True)
    s.add(review)
    ws._audit(s, w, "calendar_import_reviewed")
    if reauthenticate:
        reauthenticate()
    authorize_request(s, box, actor, account_id, wid)
    s.commit()
    return _selection_receipt(s, w, read, review, entry, reauthenticate=reauthenticate)


def revoke_import(s, box, actor, account_id, wid, *, expected, key, import_id, source_sha256, reauthenticate=None):
    _key(key)
    _digest(source_sha256)
    if type(expected) is not int or expected < 1:
        raise ws.WorkspaceError("invalid_calendar_import_request", 422)
    w = authorize_request(s, box, actor, account_id, wid, reauthenticate=reauthenticate)
    read = _read(s, w, account_id, import_id)
    snap = _snapshot(s, read)
    request_hash = payload_hash(_revocation_body(wid, expected, key, import_id, source_sha256))
    replay = s.scalar(select(CalendarImportRevocation).where(CalendarImportRevocation.workspace_id == wid,
        CalendarImportRevocation.idempotency_key == key))
    if replay is not None:
        if replay.request_hash != request_hash:
            raise ws.WorkspaceError("idempotency_conflict")
    else:
        _unused_key(s, wid, key)
        if expected != w.revision:
            raise ws.WorkspaceError("workspace_revision_conflict")
        if source_sha256 != snap.source_sha256:
            raise ws.WorkspaceError("calendar_import_source_changed")
        if _revoked(s, read):
            raise ws.WorkspaceError("calendar_import_source_unavailable")
        s.add(CalendarImportRevocation(workspace_id=wid, box_id=box, owner_id=actor,
            import_id=read.id, expected_revision=expected, idempotency_key=key,
            request_hash=request_hash, import_sha256=source_sha256))
        s.flush()
        if reauthenticate:
            reauthenticate()
        authorize_request(s, box, actor, account_id, wid)
        s.commit()
    w = authorize_request(s, box, actor, account_id, wid, reauthenticate=reauthenticate)
    return dict(status="revoked", scope=_scope(w, account_id), import_id=read.id, idempotency_key=key,
                request_sha256=request_hash, source_sha256=source_sha256, workspace=ws.read(s, box, actor, wid))
