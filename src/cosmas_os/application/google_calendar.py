"""Human calendar-summary custody; no booking, note, model or calendar writes."""

from __future__ import annotations

import hashlib
import json
import re
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import func, select

from cosmas_os.application import model_work
from cosmas_os.application import workspace as ws
from cosmas_os.domain.hashing import canonical_json, payload_hash
from cosmas_os.google_calendar_models import (
    GoogleCalendarObservationRequest,
    GoogleCalendarPrivateSourceReview,
    GoogleCalendarSnapshot,
    GoogleCalendarSourceReview,
)
from cosmas_os.google_connection_models import GoogleConnectionCredential
from cosmas_os.models import ExternalIdentity, WorkspaceEntry
from cosmas_os.ports.google_calendar import (
    GoogleCalendarBinding,
    GoogleCalendarEvent,
    GoogleCalendarObservation,
    GoogleCalendarRead,
    GoogleCalendarWindow,
)

_binding_reader = None
_withheld_sources = ContextVar("google_calendar_withheld_sources", default=frozenset())
_KEY = re.compile(r"^[A-Za-z0-9:_-]{8,100}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


@contextmanager
def install_binding_reader(reader):
    global _binding_reader
    previous, _binding_reader = _binding_reader, reader
    try:
        yield
    finally:
        _binding_reader = previous


def _identity(s, box, actor, account_id, *, writing=False):
    ws._human(s, box, actor, creating=writing)
    account = s.scalar(select(ExternalIdentity).where(ExternalIdentity.id == account_id,
        ExternalIdentity.box_id == box, ExternalIdentity.principal_id == actor,
        ExternalIdentity.active.is_(True)).with_for_update(read=not writing).execution_options(populate_existing=True))
    if account is None:
        raise ws.WorkspaceError("workspace_access_denied", 403)
    return account


def _scoped_identity(account):
    return SimpleNamespace(box_id=account.box_id, principal_id=account.principal_id,
        external_identity_id=account.id, auth_mode="clerk_jwt", organization_id=account.organization_id)


def _binding(s, account, *, port=None):
    credential = s.scalar(select(GoogleConnectionCredential).where(GoogleConnectionCredential.account_id == account.id)
        .with_for_update(read=True).execution_options(populate_existing=True))
    if (credential is None or credential.status != "ready" or credential.sealed is None
            or credential.expires_at <= model_work.now(s)):
        raise ws.WorkspaceError("google_calendar_grant_unavailable")
    try:
        if port is not None:
            binding = port.calendar_binding(_scoped_identity(account), session=s)
        elif _binding_reader is not None:
            binding = _binding_reader(s, account)
        else:
            raise ValueError("binding reader unavailable")
        binding = GoogleCalendarBinding.model_validate(binding)
        if (binding.account_id, binding.binding_digest, binding.connected_at) != (
                account.id, credential.binding_digest, credential.connected_at):
            raise ValueError("binding changed")
    except ws.WorkspaceError:
        raise
    except Exception:
        raise ws.WorkspaceError("google_calendar_grant_unavailable") from None
    return binding


def _same_binding(read, binding):
    return (read.account_id, read.binding_digest, read.connected_at, read.grant_sha256) == (
        binding.account_id, binding.binding_digest, binding.connected_at, binding.grant_sha256)


def _authorize(s, read, *, port=None):
    account = _identity(s, read.box_id, read.owner_id, read.account_id)
    if not _same_binding(read, _binding(s, account, port=port)):
        raise ws.WorkspaceError("google_calendar_grant_changed")
    return account


def _access(s, box, actor, account_id, reauthenticate):
    model_work.lock_owner(s, box, actor)
    if reauthenticate is not None:
        reauthenticate()
    return _identity(s, box, actor, account_id, writing=True)


def _payload_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _request_body(account_id, key):
    return dict(action="observe", account_id=account_id, idempotency_key=key)


def _commitment(read, digest):
    def stamp(value):
        return value.astimezone(UTC).isoformat(timespec="microseconds")

    return _payload_digest(dict(observation_id=read.id, account_id=read.account_id,
        ordinal=read.ordinal, request_hash=read.request_hash, binding_digest=read.binding_digest,
        connected_at=stamp(read.connected_at), grant_sha256=read.grant_sha256,
        window_start=stamp(read.window_start), window_end=stamp(read.window_end), payload_sha256=digest))


def _snapshot(s, read):
    snap = s.scalar(select(GoogleCalendarSnapshot).where(GoogleCalendarSnapshot.observation_id == read.id))
    if snap is None:
        raise ws.WorkspaceError("google_calendar_observation_unconfirmed")
    try:
        parsed = GoogleCalendarObservation.model_validate_json(canonical_json(snap.payload))
        if ((snap.box_id, snap.owner_id) != (read.box_id, read.owner_id)
                or read.request_hash != payload_hash(_request_body(read.account_id, read.idempotency_key))
                or (parsed.window.starts_at, parsed.window.ends_at) != (read.window_start, read.window_end)
                or snap.payload_sha256 != _payload_digest(snap.payload)
                or snap.source_sha256 != _commitment(read, snap.payload_sha256)):
            raise ValueError("invalid snapshot commitment")
    except (ValueError, TypeError, KeyError):
        raise ws.WorkspaceError("google_calendar_source_invalid") from None
    return snap


def _receipt(read, snap):
    return dict(contract_version=1, observation_id=read.id, observation_key=read.idempotency_key,
        source_sha256=snap.source_sha256, payload_sha256=snap.payload_sha256, observation=snap.payload)


def observe(s, box, actor, external_identity_id, *, key, port, reauthenticate=None):
    if not isinstance(key, str) or _KEY.fullmatch(key) is None:
        raise ws.WorkspaceError("invalid_google_calendar_request", 422)
    account = _access(s, box, actor, external_identity_id, reauthenticate)
    replay = s.scalar(select(GoogleCalendarObservationRequest).where(
        GoogleCalendarObservationRequest.box_id == box, GoogleCalendarObservationRequest.owner_id == actor,
        GoogleCalendarObservationRequest.idempotency_key == key))
    request_hash = payload_hash(_request_body(account.id, key))
    if replay is not None:
        if replay.request_hash != request_hash:
            raise ws.WorkspaceError("idempotency_conflict")
        _authorize(s, replay, port=port)
        _observation_current(s, replay)
        return _receipt(replay, _snapshot(s, replay))
    binding = _binding(s, account, port=port)
    start = model_work.now(s).astimezone(UTC)
    window = GoogleCalendarWindow(starts_at=start, ends_at=start + timedelta(days=7))
    ordinal = (s.scalar(select(func.max(GoogleCalendarObservationRequest.ordinal)).where(
        GoogleCalendarObservationRequest.account_id == account.id)) or 0) + 1
    if ordinal > 500:
        raise ws.WorkspaceError("google_calendar_observation_limit")
    read = GoogleCalendarObservationRequest(box_id=box, owner_id=actor, account_id=account.id,
        ordinal=ordinal, idempotency_key=key, request_hash=request_hash,
        binding_digest=binding.binding_digest, grant_sha256=binding.grant_sha256,
        connected_at=binding.connected_at, window_start=start, window_end=window.ends_at)
    s.add(read)
    s.flush()
    read_id, provider_identity = read.id, _scoped_identity(account)
    s.commit()  # The exact reservation survives a lost reply; release all locks before Google I/O.
    try:
        result = GoogleCalendarRead.model_validate(port.calendar_observation(provider_identity, window=window))
        if result.custody != binding or result.observation.window != window:
            raise ws.WorkspaceError("google_calendar_grant_changed")
        payload = result.observation.model_dump(mode="json")
        if len(canonical_json(payload).encode()) > 60000:
            raise ValueError("bounded observation unavailable")
        _access(s, box, actor, external_identity_id, reauthenticate)
        read = s.get(GoogleCalendarObservationRequest, read_id, populate_existing=True)
        _authorize(s, read, port=port)
        _observation_current(s, read)
        snap = GoogleCalendarSnapshot(box_id=box, owner_id=actor, observation_id=read.id,
            payload=payload, payload_sha256=_payload_digest(payload), source_sha256=_commitment(read, _payload_digest(payload)))
        s.add(snap)
        s.flush()
        _snapshot(s, read)
        if reauthenticate is not None:
            reauthenticate()
        _authorize(s, read, port=port)
        _observation_current(s, read)
        s.commit()
        return _receipt(read, snap)
    except ws.WorkspaceError:
        s.rollback()
        raise
    except Exception:
        s.rollback()
        raise ws.WorkspaceError("google_calendar_observation_unconfirmed", 503) from None


def inspect_observation(s, box, actor, external_identity_id, *, observation_id, port, reauthenticate=None):
    _access(s, box, actor, external_identity_id, reauthenticate)
    read = s.get(GoogleCalendarObservationRequest, observation_id)
    if read is None or (read.box_id, read.owner_id, read.account_id) != (box, actor, external_identity_id):
        raise ws.WorkspaceError("google_calendar_observation_unavailable", 404)
    _authorize(s, read, port=port)
    _observation_current(s, read)
    receipt = _receipt(read, _snapshot(s, read))
    if reauthenticate is not None:
        reauthenticate()
    _authorize(s, read, port=port)
    _observation_current(s, read)
    return receipt


def resolve_observation(s, box, actor, external_identity_id, *, key, port, reauthenticate=None):
    if not isinstance(key, str) or _KEY.fullmatch(key) is None:
        raise ws.WorkspaceError("invalid_google_calendar_request", 422)
    _access(s, box, actor, external_identity_id, reauthenticate)
    read = s.scalar(select(GoogleCalendarObservationRequest).where(
        GoogleCalendarObservationRequest.box_id == box, GoogleCalendarObservationRequest.owner_id == actor,
        GoogleCalendarObservationRequest.idempotency_key == key))
    if read is None:
        return dict(status="not_found", observation_id=None, observation_key=key)
    if read.account_id != external_identity_id:
        raise ws.WorkspaceError("idempotency_conflict")
    _authorize(s, read, port=port)
    _observation_current(s, read)
    if s.scalar(select(GoogleCalendarSnapshot.id).where(GoogleCalendarSnapshot.observation_id == read.id)) is None:
        return dict(status="unconfirmed", observation_id=read.id, observation_key=key)
    return inspect_observation(s, box, actor, external_identity_id, observation_id=read.id,
        port=port, reauthenticate=reauthenticate)


def _latest(s, read):
    if s.scalar(select(GoogleCalendarObservationRequest.id).where(
        GoogleCalendarObservationRequest.account_id == read.account_id,
        GoogleCalendarObservationRequest.ordinal > read.ordinal).limit(1)) is not None:
        raise ws.WorkspaceError("google_calendar_source_superseded")


def _observation_current(s, read):
    _latest(s, read)
    if model_work.now(s) >= read.window_end:
        raise ws.WorkspaceError("google_calendar_source_expired")


def event_hash(event):
    return payload_hash(event.model_dump(mode="json") if isinstance(event, GoogleCalendarEvent) else event)


def source_content(observation, event):
    value = observation.model_dump(mode="json") if isinstance(observation, GoogleCalendarObservation) else observation
    item = event.model_dump(mode="json") if isinstance(event, GoogleCalendarEvent) else event
    return ("Google calendar summary (frozen observation)\n"
        f"Account: {value['account']['label']} <{value['account']['email']}>\n"
        f"Event: {item['subject']}\nStarts: {item['starts_at']}\nEnds (exclusive): {item['ends_at']}\n"
        f"All day: {'yes' if item['all_day'] else 'no'}\nStatus: {'cancelled' if item['cancelled'] else 'not marked cancelled'}\n"
        f"Observed: {value['observed_at']}\nWindow: {value['window']['starts_at']} to {value['window']['ends_at']}\n"
        f"Coverage: {'partial (more events available)' if value['more'] else 'up to 25 events in the primary calendar'}\n\n"
        "This observed summary does not establish current availability or a booking.")


def valid_until(observation, event):
    _, end = event.bounds()
    if event.all_day:
        # Earliest possible exclusive date-end using offsets strictly <24h;
        # this is a conservative authority bound, not a claimed event timezone.
        nominal = datetime.combine(end, datetime.min.time(), UTC)
        end = nominal - timedelta(days=1) if end > date.min else datetime.min.replace(tzinfo=UTC)
    if not isinstance(end, datetime):
        raise ValueError("calendar end invalid")
    return min(observation.window.ends_at, end)


def _review_body(wid, expected, key, observation_id, observation_sha256, event_id, event_sha256,
                 reviewed_visit, reviewed_exact_summary, reviewed_untrusted_source, *, reviewed_private_notebook=None):
    return dict(workspace_id=wid, expected_revision=expected, idempotency_key=key,
        observation_id=observation_id, observation_sha256=observation_sha256, event_id=event_id,
        event_sha256=event_sha256,
        **({"reviewed_private_notebook": True} if reviewed_private_notebook is True else {"reviewed_visit": reviewed_visit}),
        reviewed_exact_summary=reviewed_exact_summary, reviewed_untrusted_source=reviewed_untrusted_source)


def _review_for_entry(s, entry_id):
    rows = [s.scalar(select(model).where(model.entry_id == entry_id))
            for model in (GoogleCalendarSourceReview, GoogleCalendarPrivateSourceReview)]
    found = [row for row in rows if row is not None]
    if len(found) > 1:
        raise ws.WorkspaceError("google_calendar_source_invalid")
    return found[0] if found else None


def _review_context(review):
    return {"reviewed_private_notebook": True} if isinstance(review, GoogleCalendarPrivateSourceReview) else {}


def historical_source(s, w, entry_id):
    entry = s.get(WorkspaceEntry, entry_id)
    review = _review_for_entry(s, entry_id)
    if (entry is None or review is None or (entry.workspace_id, entry.box_id, entry.actor_id, entry.kind)
            != (w.id, w.box_id, w.owner_id, "google_calendar")):
        raise ws.WorkspaceError("google_calendar_source_unavailable", 404)
    snap = s.get(GoogleCalendarSnapshot, review.snapshot_id)
    read = s.get(GoogleCalendarObservationRequest, snap.observation_id) if snap is not None else None
    if snap is None or read is None:
        raise ws.WorkspaceError("google_calendar_source_invalid")
    _snapshot(s, read)
    observation = GoogleCalendarObservation.model_validate_json(canonical_json(snap.payload))
    event = next((item for item in observation.items if item.id == review.event_id), None)
    if event is None:
        raise ws.WorkspaceError("google_calendar_source_invalid")
    content = source_content(snap.payload, event)
    body = _review_body(w.id, review.expected_revision, review.idempotency_key, read.id,
        review.observation_sha256, review.event_id, review.event_sha256,
        getattr(review, "reviewed_visit", None), review.reviewed_exact_summary, review.reviewed_untrusted_source, **_review_context(review))
    private = isinstance(review, GoogleCalendarPrivateSourceReview)
    context_valid = ((w.draft_title is not None and review.reviewed_private_notebook is True) if private else
                     (w.appointment_id is not None and review.patient_link_id == w.patient_link_id and review.reviewed_visit is True))
    if ((review.workspace_id, review.box_id, review.owner_id, review.workspace_revision)
            != (w.id, w.box_id, w.owner_id, entry.revision)
            or not context_valid
            or (snap.box_id, snap.owner_id, read.box_id, read.owner_id) != (w.box_id, w.owner_id, w.box_id, w.owner_id)
            or review.observation_sha256 != snap.source_sha256 or review.event_sha256 != event_hash(event)
            or review.source_sha256 != payload_hash(dict(observation_sha256=review.observation_sha256,
                event_id=event.id, event_sha256=review.event_sha256))
            or review.valid_until != valid_until(observation, event)
            or review.content_sha256 != hashlib.sha256(content.encode()).hexdigest() or entry.content != content
            or review.request_hash != payload_hash(body) or entry.request_hash != review.request_hash
            or entry.idempotency_key != review.idempotency_key
            or entry.source_label != ("Google calendar: " + event.subject)[:160]
            or review.workspace_revision != review.expected_revision + 1
            or review.reviewed_exact_summary is not True or review.reviewed_untrusted_source is not True):
        raise ws.WorkspaceError("google_calendar_source_invalid")
    return entry


def validate_selected_source(s, w, entry_id):
    if (w.id, entry_id) in _withheld_sources.get():
        raise ws.WorkspaceError("google_calendar_source_unavailable")
    model_work.read_workspace(s, w.box_id, w.owner_id, w.id)
    entry = historical_source(s, w, entry_id)
    review = _review_for_entry(s, entry_id)
    if review is None:
        raise ws.WorkspaceError("google_calendar_source_unavailable")
    if isinstance(review, GoogleCalendarPrivateSourceReview) and (
            w.appointment_id is not None or w.patient_link_id is not None or w.draft_title is None):
        raise ws.WorkspaceError("google_calendar_source_unavailable")
    snap = s.get(GoogleCalendarSnapshot, review.snapshot_id)
    read = s.get(GoogleCalendarObservationRequest, snap.observation_id)
    _authorize(s, read)
    _latest(s, read)
    if model_work.now(s) >= review.valid_until:
        raise ws.WorkspaceError("google_calendar_source_expired")
    return entry


def selected_entries(s, w, settings, at_revision):
    from cosmas_os.ports.bot_capabilities import supports_skill
    if not supports_skill(settings, "saved_context") or not settings["include_evidence"]:
        return []
    entries = list(s.scalars(select(WorkspaceEntry).where(WorkspaceEntry.workspace_id == w.id,
        WorkspaceEntry.box_id == w.box_id, WorkspaceEntry.actor_id == w.owner_id,
        WorkspaceEntry.kind == "google_calendar", WorkspaceEntry.revision <= at_revision).order_by(WorkspaceEntry.revision)))
    result = []
    for entry in entries:
        try:
            result.append(validate_selected_source(s, w, entry.id))
        except ws.WorkspaceError:
            continue
    return result


def _selection_receipt(s, w, read, review, entry):
    workspace = ws.read(s, w.box_id, w.owner_id, w.id)
    projected = next(row for row in workspace["entries"] if row["id"] == entry.id)
    withheld = projected.get("calendar_source_state") == "unavailable"
    try:
        validate_selected_source(s, w, entry.id)
    except ws.WorkspaceError:
        withheld = True
    if withheld:
        # A feature/grant can change between projection and this final check.
        # Once withheld, keep this source unavailable through the entire fresh
        # projection, including uncited drafts, revision briefs and feedback.
        # Context-local state cannot deny another request or restore authority
        # if a volatile reader happens to report a recovered grant mid-read.
        token = _withheld_sources.set(_withheld_sources.get() | {(w.id, entry.id)})
        try:
            workspace = ws.read(s, w.box_id, w.owner_id, w.id)
        finally:
            _withheld_sources.reset(token)
    return dict(entry_id=entry.id, entry_revision=entry.revision, workspace=workspace,
        source=dict(entry_id=entry.id, source_sha256=review.source_sha256, content_sha256=review.content_sha256),
        request_sha256=payload_hash(_review_body(w.id, review.expected_revision, review.idempotency_key,
            read.id, review.observation_sha256, review.event_id, review.event_sha256,
            getattr(review, "reviewed_visit", None), review.reviewed_exact_summary, review.reviewed_untrusted_source, **_review_context(review))),
        source_withheld=withheld)


def select_review(s, box, actor, wid, *, expected, key, observation_id, observation_sha256,
                  event_id, event_sha256, reviewed_visit=None, reviewed_private_notebook=None, reviewed_exact_summary,
                  reviewed_untrusted_source, port=None, external_identity_id=None, reauthenticate=None):
    private = reviewed_private_notebook is True and reviewed_visit is None
    visit = reviewed_visit is True and reviewed_private_notebook is None
    if (type(expected) is not int or expected < 1 or not isinstance(key, str) or _KEY.fullmatch(key) is None
            or any(not isinstance(value, str) or _DIGEST.fullmatch(value) is None for value in (observation_sha256, event_sha256))
            or not (private or visit)
            or any(value is not True for value in (reviewed_exact_summary, reviewed_untrusted_source))):
        raise ws.WorkspaceError("invalid_google_calendar_review", 422)
    model_work.lock_owner(s, box, actor)
    if reauthenticate is not None:
        reauthenticate()
    w = ws._workspace(s, box, actor, wid, writing=True, allow_private=private)
    review_model = GoogleCalendarPrivateSourceReview if private else GoogleCalendarSourceReview
    read = s.get(GoogleCalendarObservationRequest, observation_id)
    if (read is None or (read.box_id, read.owner_id) != (box, actor)
            or external_identity_id is not None and read.account_id != external_identity_id):
        raise ws.WorkspaceError("google_calendar_observation_unavailable", 404)
    _identity(s, box, actor, read.account_id)
    snap = _snapshot(s, read)
    body = _review_body(wid, expected, key, observation_id, observation_sha256, event_id,
        event_sha256, reviewed_visit, reviewed_exact_summary, reviewed_untrusted_source,
        reviewed_private_notebook=reviewed_private_notebook)
    request_hash = payload_hash(body)
    replays = [s.scalar(select(model).where(model.workspace_id == wid, model.idempotency_key == key))
               for model in (GoogleCalendarSourceReview, GoogleCalendarPrivateSourceReview)]
    replay = next((row for row in replays if row is not None), None)
    if replay is not None:
        if replay.request_hash != request_hash:
            raise ws.WorkspaceError("idempotency_conflict")
        entry = historical_source(s, w, replay.entry_id)
        if reauthenticate is not None:
            reauthenticate()
        return _selection_receipt(s, w, read, replay, entry)
    if private and (w.appointment_id is not None or w.patient_link_id is not None or w.draft_title is None):
        raise ws.WorkspaceError("google_calendar_private_notebook_required")
    _authorize(s, read, port=port)
    _latest(s, read)
    if expected != w.revision:
        raise ws.WorkspaceError("workspace_revision_conflict")
    if observation_sha256 != snap.source_sha256:
        raise ws.WorkspaceError("google_calendar_source_changed")
    observation = GoogleCalendarObservation.model_validate_json(canonical_json(snap.payload))
    event = next((item for item in observation.items if item.id == event_id), None)
    if event is None or event_hash(event) != event_sha256:
        raise ws.WorkspaceError("google_calendar_not_observed")
    expires = valid_until(observation, event)
    if model_work.now(s) >= expires:
        raise ws.WorkspaceError("google_calendar_source_expired")
    if w.revision >= 500:
        raise ws.WorkspaceError("workspace_history_limit")
    if s.scalar(select(WorkspaceEntry.id).where(WorkspaceEntry.workspace_id == wid, WorkspaceEntry.idempotency_key == key)):
        raise ws.WorkspaceError("idempotency_conflict")
    if s.scalar(select(review_model.id).where(review_model.workspace_id == wid,
            review_model.snapshot_id == snap.id, review_model.event_id == event_id)):
        raise ws.WorkspaceError("google_calendar_already_selected")
    content = source_content(snap.payload, event)
    content_sha = hashlib.sha256(content.encode()).hexdigest()
    source_sha = payload_hash(dict(observation_sha256=observation_sha256, event_id=event_id, event_sha256=event_sha256))
    w.revision += 1
    entry = WorkspaceEntry(workspace_id=wid, box_id=box, actor_id=actor, revision=w.revision,
        kind="google_calendar", content=content, source_label=("Google calendar: " + event.subject)[:160],
        idempotency_key=key, request_hash=request_hash)
    s.add(entry)
    s.flush()
    review = review_model(workspace_id=wid, box_id=box, owner_id=actor,
        entry_id=entry.id, snapshot_id=snap.id,
        **({"reviewed_private_notebook": True} if private else {"patient_link_id": w.patient_link_id, "reviewed_visit": True}),
        expected_revision=expected, workspace_revision=w.revision, idempotency_key=key,
        request_hash=request_hash, observation_sha256=observation_sha256, event_id=event_id,
        event_sha256=event_sha256, source_sha256=source_sha, content_sha256=content_sha,
        valid_until=expires, reviewed_exact_summary=True, reviewed_untrusted_source=True)
    s.add(review)
    ws._audit(s, w, "google_calendar_reviewed")
    if reauthenticate is not None:
        reauthenticate()
    _authorize(s, read, port=port)
    _latest(s, read)
    if model_work.now(s) >= expires:
        raise ws.WorkspaceError("google_calendar_source_expired")
    s.commit()
    return _selection_receipt(s, w, read, review, entry)
