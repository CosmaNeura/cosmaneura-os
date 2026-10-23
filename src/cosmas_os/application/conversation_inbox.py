"""Bounded owner-only inbox over existing bot conversations, never group chats."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import String, and_, cast, func, literal, or_, select, tuple_, union, union_all

from cosmas_os.application import workspace as ws
from cosmas_os.application.encounter_access import patient_visible
from cosmas_os.conversation_models import ConversationReadMarker as Marker
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.models import (
    ActionRevision,
    AppointmentObservation,
    EncounterWorkspace,
    FollowUpSource,
    ModelWorkAdmission,
    PatientLink,
    ProviderBot,
    ProviderTeamRevision,
    Ticket,
    WorkspaceEntry,
    WorkspaceHandoff,
    WorkspaceHandoffAttempt,
    WorkspaceHandoffReview,
    WorkspaceNote,
    WorkspaceNoteReview,
    WorkspaceReply,
    WorkspaceTitleRevision,
)

PAGE_SIZE = 20
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
CONNECTOR_KINDS = {'google_message', 'google_calendar', 'efax_inbound_source', 'fax_inbound_source'}


def _micros(value):
    delta = value.astimezone(UTC) - EPOCH
    return (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds


def _checksum(box, owner, purpose, body):
    return payload_hash({'contract': 'conversation-inbox.v1', 'box': box, 'owner': owner,
                         'purpose': purpose, 'position': body})


def _cursor(box, owner, cutoff, row):
    body = f'{_micros(cutoff):016x}{_micros(row.at):016x}{UUID(row.workspace_id).hex}{UUID(row.agent_id).hex}'
    return 'c1' + body + _checksum(box, owner, 'page', body)


def _decode_cursor(value, box, owner, now):
    if value is None:
        return now, None
    if len(value) != 162 or not value.startswith('c1') or any(c not in '0123456789abcdef' for c in value[2:]):
        raise ws.WorkspaceError('invalid_conversation_cursor', 422)
    body = value[2:98]
    if value[98:] != _checksum(box, owner, 'page', body):
        raise ws.WorkspaceError('invalid_conversation_cursor', 422)
    try:
        cutoff = EPOCH + timedelta(microseconds=int(body[:16], 16))
        at = EPOCH + timedelta(microseconds=int(body[16:32], 16))
        if not EPOCH <= at <= cutoff <= now:
            raise ValueError()
        return cutoff, (at, str(UUID(hex=body[32:64])), str(UUID(hex=body[64:])))
    except (ValueError, OverflowError):
        raise ws.WorkspaceError('invalid_conversation_cursor', 422) from None


def _watermark(box, owner, wid, agent, at, event_id):
    body = f'{_micros(at):016x}{event_id}'
    return 'r1' + body + _checksum(box, owner, f'{wid}:{agent}', body)


def _decode_watermark(value, box, owner, wid, agent):
    if not isinstance(value, str) or len(value) != 115 or not value.startswith('r1'):
        raise ws.WorkspaceError('invalid_conversation_watermark', 422)
    body = value[2:51]
    if value[51:] != _checksum(box, owner, f'{wid}:{agent}', body):
        raise ws.WorkspaceError('invalid_conversation_watermark', 422)
    try:
        return EPOCH + timedelta(microseconds=int(body[:16], 16)), body[16:]
    except (ValueError, OverflowError):
        raise ws.WorkspaceError('invalid_conversation_watermark', 422) from None


def _event_id(kind, identifier):
    return literal(kind) + func.replace(cast(identifier, String), '-', '')


def _events(box, owner):
    """Arrival clocks include replies; the workspace revision is not a clock."""
    e, r, a, h, attempt = WorkspaceEntry, WorkspaceReply, ModelWorkAdmission, WorkspaceHandoff, WorkspaceHandoffAttempt
    direct = select(e.workspace_id, func.coalesce(a.agent_id, r.agent_id).label('agent_id')).select_from(e).outerjoin(
        a, and_(a.request_entry_id == e.id, a.box_id == box, a.owner_id == owner, a.kind == 'conversation')
    ).outerjoin(r, and_(r.entry_id == e.id, r.box_id == box, r.owner_id == owner)).where(
        e.box_id == box, e.actor_id == owner, e.kind == 'conversation', or_(a.agent_id.is_not(None), r.agent_id.is_not(None)))
    base = union(direct, select(Marker.workspace_id, Marker.agent_id).where(Marker.box_id == box, Marker.owner_id == owner)).subquery()
    requests = select(e.workspace_id, func.coalesce(a.agent_id, r.agent_id).label('agent_id'), e.created_at.label('at'), _event_id('e', e.id).label('event_id')).select_from(e).outerjoin(
        a, and_(a.request_entry_id == e.id, a.box_id == box, a.owner_id == owner, a.kind == 'conversation')
    ).outerjoin(r, and_(r.entry_id == e.id, r.box_id == box, r.owner_id == owner)).where(e.box_id == box, e.actor_id == owner, e.kind == 'conversation')
    replies = select(r.workspace_id, r.agent_id, r.created_at, _event_id('r', r.entry_id)).where(r.box_id == box, r.owner_id == owner)
    opened = select(Marker.workspace_id, Marker.agent_id, EncounterWorkspace.created_at, _event_id('o', Marker.agent_id)).join(EncounterWorkspace, EncounterWorkspace.id == Marker.workspace_id).where(Marker.box_id == box, Marker.owner_id == owner)
    finalized = select(a.workspace_id, a.agent_id, a.finalized_at, _event_id('m', a.id)).where(a.box_id == box, a.owner_id == owner, a.finalized_at.is_not(None))
    assigned = [select(h.workspace_id, agent, func.coalesce(attempt.completed_at, attempt.started_at, attempt.created_at), _event_id('h', attempt.id)).join(
        attempt, attempt.handoff_id == h.id).where(h.box_id == box, h.owner_id == owner) for agent in (h.issuer_agent_id, h.recipient_agent_id)]
    note_events = select(WorkspaceNote.workspace_id, ProviderBot.agent_id, WorkspaceNote.created_at, _event_id('n', WorkspaceNote.id)).join(
        ProviderBot, and_(ProviderBot.box_id == box, ProviderBot.owner_id == owner, ProviderBot.role.in_(['chief', 'scribe']))).where(
        WorkspaceNote.box_id == box, WorkspaceNote.owner_id == owner)
    events = union_all(requests, replies, opened, finalized, *assigned, note_events).subquery()
    return select(events).join(base, and_(base.c.workspace_id == events.c.workspace_id, base.c.agent_id == events.c.agent_id)).subquery()


def _accessible(box, owner, events):
    w, appointment, link = EncounterWorkspace, AppointmentObservation, PatientLink
    return select(events, w, appointment.patient_label).join(w, and_(w.id == events.c.workspace_id, w.box_id == box, w.owner_id == owner)).outerjoin(
        appointment, and_(appointment.id == w.appointment_id, appointment.box_id == box, appointment.patient_link_id == w.patient_link_id)
    ).outerjoin(link, and_(link.id == w.patient_link_id, link.box_id == box, link.state == 'confirmed', link.revoked_at.is_(None), patient_visible(owner))).where(
        or_(and_(w.appointment_id.is_(None), w.patient_link_id.is_(None), w.draft_title.is_not(None)), and_(appointment.id.is_not(None), link.id.is_not(None))))


def _source_versions(entries, settings):
    sources = [e for e in entries if e.kind in {'scratchpad', 'evidence', 'synthetic_source'}]
    chosen = ([e for e in sources if e.kind == 'scratchpad'][-1:] if settings.get('include_notebook') else [])
    if settings.get('include_evidence'):
        chosen += [e for e in sources if e.kind in {'evidence', 'synthetic_source'}]
    return [{'entry_id': e.id, 'revision': e.revision, 'label': e.source_label or 'Your jotted notes', 'kind': e.kind,
             'sha256': hashlib.sha256(e.content.encode()).hexdigest()} for e in chosen]


def read(s, box, owner, *, cursor=None, fence=None, clock=None):
    if fence:
        fence()
    ws._human(s, box, owner)
    now = clock() if clock else s.scalar(select(func.clock_timestamp()))
    cutoff, after = _decode_cursor(cursor, box, owner, now)
    events = _events(box, owner)
    ranked = select(events, func.row_number().over(partition_by=[events.c.workspace_id, events.c.agent_id], order_by=[events.c.at.desc(), events.c.event_id.desc()]).label('rank')).where(events.c.at <= cutoff).subquery()
    query = _accessible(box, owner, ranked).where(ranked.c.rank == 1)
    if after:
        query = query.where(tuple_(ranked.c.at, ranked.c.workspace_id, ranked.c.agent_id) < after)
    rows = list(s.execute(query.order_by(ranked.c.at.desc(), ranked.c.workspace_id.desc(), ranked.c.agent_id.desc()).limit(PAGE_SIZE + 1)))
    more, rows = len(rows) > PAGE_SIZE, rows[:PAGE_SIZE]
    if not rows:
        return {'contract_version': 1, 'as_of': now.isoformat(), 'rows': [], 'next_cursor': None}
    ids = {row.workspace_id for row in rows}
    # Hold current patient/reference custody through response construction, in batches.
    locked_workspaces = list(s.scalars(select(EncounterWorkspace).where(EncounterWorkspace.id.in_(ids), EncounterWorkspace.box_id == box, EncounterWorkspace.owner_id == owner).with_for_update(read=True).execution_options(populate_existing=True)))
    appointment_ids = [w.appointment_id for w in locked_workspaces if w.appointment_id]
    link_ids = [w.patient_link_id for w in locked_workspaces if w.patient_link_id]
    if appointment_ids:
        list(s.scalars(select(AppointmentObservation).where(AppointmentObservation.id.in_(appointment_ids), AppointmentObservation.box_id == box).with_for_update(read=True).execution_options(populate_existing=True)))
        list(s.scalars(select(PatientLink).where(PatientLink.id.in_(link_ids), PatientLink.box_id == box).with_for_update(read=True).execution_options(populate_existing=True)))
    still_visible = {item.workspace_id for item in s.execute(_accessible(box, owner, ranked).where(ranked.c.rank == 1, ranked.c.workspace_id.in_(ids)))}
    if still_visible != ids:
        raise ws.WorkspaceError('conversation_access_changed', 403)
    # Bulk reads keep page cost independent of the number of conversations.
    entries = defaultdict(list)
    for entry in s.scalars(select(WorkspaceEntry).where(WorkspaceEntry.box_id == box, WorkspaceEntry.workspace_id.in_(ids)).order_by(WorkspaceEntry.revision)):
        entries[entry.workspace_id].append(entry)
    replies = {reply.entry_id: reply for reply in s.scalars(select(WorkspaceReply).where(WorkspaceReply.box_id == box, WorkspaceReply.owner_id == owner, WorkspaceReply.workspace_id.in_(ids)))}
    admission_columns = [ModelWorkAdmission.workspace_id, ModelWorkAdmission.agent_id, ModelWorkAdmission.kind, ModelWorkAdmission.state,
        ModelWorkAdmission.reservation_expires_at, ModelWorkAdmission.lease_ends_at, ModelWorkAdmission.source_sha256, ModelWorkAdmission.handoff_attempt_id,
        ModelWorkAdmission.request_entry_id, ModelWorkAdmission.admitted_at]
    admissions = list(s.execute(select(*admission_columns).where(ModelWorkAdmission.box_id == box, ModelWorkAdmission.owner_id == owner, ModelWorkAdmission.workspace_id.in_(ids))))
    bots = {bot.agent_id: bot for bot in s.scalars(select(ProviderBot).where(ProviderBot.box_id == box, ProviderBot.owner_id == owner))}
    version = s.scalar(select(ProviderTeamRevision).where(ProviderTeamRevision.box_id == box, ProviderTeamRevision.owner_id == owner).order_by(ProviderTeamRevision.revision.desc()).limit(1))
    configs = {item.get('instance_id') or item['role']: item for item in version.configuration['bots']} if version else {}
    markers = {(m.workspace_id, m.agent_id): m for m in s.scalars(select(Marker).where(Marker.box_id == box, Marker.owner_id == owner, Marker.workspace_id.in_(ids)))}
    titles = {}
    for title in s.scalars(select(WorkspaceTitleRevision).where(WorkspaceTitleRevision.box_id == box, WorkspaceTitleRevision.owner_id == owner, WorkspaceTitleRevision.workspace_id.in_(ids)).order_by(WorkspaceTitleRevision.version)):
        titles[title.workspace_id] = title.title
    handoffs = list(s.scalars(select(WorkspaceHandoff).where(WorkspaceHandoff.box_id == box, WorkspaceHandoff.owner_id == owner, WorkspaceHandoff.workspace_id.in_(ids))))
    attempts = {}
    for attempt in s.scalars(select(WorkspaceHandoffAttempt).where(WorkspaceHandoffAttempt.box_id == box, WorkspaceHandoffAttempt.owner_id == owner, WorkspaceHandoffAttempt.workspace_id.in_(ids)).order_by(WorkspaceHandoffAttempt.number)):
        attempts[attempt.handoff_id] = attempt
    reviews = {review.attempt_id: review for review in s.scalars(select(WorkspaceHandoffReview).where(WorkspaceHandoffReview.box_id == box, WorkspaceHandoffReview.owner_id == owner, WorkspaceHandoffReview.workspace_id.in_(ids)))}
    notes = {}
    for note in s.scalars(select(WorkspaceNote).where(WorkspaceNote.box_id == box, WorkspaceNote.owner_id == owner, WorkspaceNote.workspace_id.in_(ids)).order_by(WorkspaceNote.version)):
        notes[note.workspace_id] = note
    note_reviews = {review.note_id for review in s.scalars(select(WorkspaceNoteReview).where(WorkspaceNoteReview.box_id == box, WorkspaceNoteReview.owner_id == owner, WorkspaceNoteReview.workspace_id.in_(ids)))}
    work = list(s.execute(select(FollowUpSource.workspace_id, Ticket.state).join(Ticket, and_(Ticket.id == FollowUpSource.ticket_id, Ticket.box_id == box)).where(FollowUpSource.box_id == box, FollowUpSource.owner_id == owner, FollowUpSource.workspace_id.in_(ids))))
    query_work = list(s.execute(select(ActionRevision.payload, Ticket.state).join(Ticket, and_(Ticket.current_revision_id == ActionRevision.id, Ticket.box_id == box, Ticket.created_by_principal_id == owner, Ticket.lane == 'encounter_agent_research')).where(ActionRevision.payload['workspace_id'].astext.in_(ids))))
    output = []
    for row in rows:
        w, agent = row.EncounterWorkspace, bots.get(row.agent_id)
        if agent is None:
            raise ws.WorkspaceError('conversation_unavailable', 503)
        address = agent.instance_id or agent.role
        config = configs.get(address, {})
        local = entries[w.id]
        selected_sources = any(e.kind in CONNECTOR_KINDS for e in local)
        relevant = [a for a in admissions if a.workspace_id == w.id and a.agent_id == agent.agent_id]
        uncertain = any(a.state in {'unknown', 'failed', 'abandoned'} or a.state == 'running' and a.lease_ends_at <= now or a.state == 'reserved' and a.reservation_expires_at <= now for a in relevant)
        working = any(a.state == 'running' and a.lease_ends_at > now or a.state == 'reserved' and a.reservation_expires_at > now for a in relevant)
        needs_review = False
        for handoff in handoffs:
            if handoff.workspace_id != w.id or agent.agent_id not in {handoff.issuer_agent_id, handoff.recipient_agent_id}:
                continue
            attempt = attempts.get(handoff.id)
            if attempt is None:
                uncertain = True
                continue
            if attempt.status in {'queued', 'running'}:
                working = True
                continue
            if attempt.status != 'completed':
                uncertain = True
                continue
            review, result = reviews.get(attempt.id), replies.get(attempt.result_entry_id)
            recipient = bots[handoff.recipient_agent_id]
            recipient_config = configs.get(recipient.instance_id or recipient.role, {})
            chief_config = configs.get('chief', {})
            admission = next((a for a in admissions if a.handoff_attempt_id == attempt.id), None)
            current = bool(review and result and version and admission and review.source_sha256 == admission.source_sha256 and handoff.team_revision_id == version.id and
                review.result_entry_id == attempt.result_entry_id and review.agent_id == result.agent_id and
                review.result_sha256 == hashlib.sha256(result.content.encode()).hexdigest() and
                review.source_versions == _source_versions(local, recipient_config) and
                all(c.get('enabled') and not c.get('retired') and not set(c.get('blocked_capabilities', [])) & {'model_answer', 'private_draft_handoff'} for c in (chief_config, recipient_config)))
            if selected_sources:
                # Summary never grants source authority. Full review rechecks custody.
                uncertain = True
            elif not current:
                needs_review = True
        if agent.role in {'chief', 'scribe'} and w.id in notes:
            note = notes[w.id]
            source_rows = [e for e in local if e.kind in {'scratchpad', 'evidence', 'synthetic_source'}]
            latest = next((e.id for e in reversed(source_rows) if e.kind == 'scratchpad'), None)
            fingerprint = payload_hash([{'id': e.id, 'revision': e.revision, 'content': e.content} for e in source_rows if e.kind != 'scratchpad' or e.id == latest])
            needs_review |= note.id not in note_reviews or note.source_fingerprint != fingerprint
        if agent.role in {'chief', 'follow_up'}:
            needs_review |= any(item.workspace_id == w.id and item.state not in {'closed', 'completed', 'rejected', 'cancelled'} for item in work)
        needs_review |= any(item.payload.get('workspace_id') == w.id and (agent.role == 'chief' or item.payload.get('bot') == address) and item.state not in {'completed', 'closed', 'rejected', 'cancelled'} for item in query_work)
        attention = 'needs_review' if needs_review else 'needs_check' if uncertain else 'working' if working else 'idle'
        history = [e for e in local if e.kind == 'conversation' and (e.id in replies and replies[e.id].agent_id == agent.agent_id or any(a.request_entry_id == e.id for a in relevant))]
        last = history[-1] if history else None
        reply = replies.get(last.id) if last else None
        preview = (reply.content if reply else last.content if last else 'Start a conversation')[:180]
        if selected_sources:
            preview = 'Open this conversation to check its selected sources.'
        marker = markers.get((w.id, agent.agent_id))
        seen = (marker.seen_at, marker.seen_id) if marker and marker.seen_at else None
        output.append({'workspace_id': w.id, 'appointment_id': w.appointment_id, 'context_label': titles.get(w.id) or row.patient_label or w.draft_title,
            'bot': {'address': address, 'role': agent.role, 'name': config.get('name', agent.role.replace('_', ' ').title()), 'available': bool(config.get('enabled') and not config.get('retired'))},
            'preview': preview, 'preview_withheld': selected_sources, 'attention': attention, 'last_activity_at': row.at.isoformat(),
            'watermark': _watermark(box, owner, w.id, agent.agent_id, row.at, row.event_id),
            'unread': bool(marker and marker.manual_unread or row.event_id[0] != 'o' and (seen is None or (row.at, row.event_id) > seen)),
            'manual_unread': marker.manual_unread if marker else False, 'marker_version': marker.version if marker else 0})
    if fence:
        fence()
    return {'contract_version': 1, 'as_of': now.isoformat(), 'rows': output,
            'next_cursor': _cursor(box, owner, cutoff, rows[-1]) if more else None}


def update_marker(s, box, owner, wid, address, *, watermark=None, manual_unread=None, expected_version=None, fence=None):
    if fence:
        fence()
    ws._human(s, box, owner, creating=True)
    ws._workspace(s, box, owner, wid, allow_private=True)
    agent = s.scalar(select(ProviderBot).where(ProviderBot.box_id == box, ProviderBot.owner_id == owner,
        or_(ProviderBot.instance_id == address if _uuid(address) else literal(False), and_(ProviderBot.instance_id.is_(None), ProviderBot.role == address))))
    if agent is None:
        raise ws.WorkspaceError('conversation_unavailable', 404)
    marker = s.get(Marker, (wid, agent.agent_id), with_for_update=True)
    old_version = marker.version if marker else 0
    if marker is None:
        marker = Marker(workspace_id=wid, agent_id=agent.agent_id, box_id=box, owner_id=owner)
        s.add(marker)
        s.flush()
    observed = None
    if watermark is not None:
        observed = _decode_watermark(watermark, box, owner, wid, agent.agent_id)
        events = _events(box, owner)
        if s.scalar(select(events.c.event_id).where(events.c.workspace_id == wid, events.c.agent_id == agent.agent_id,
                events.c.at == observed[0], events.c.event_id == observed[1]).limit(1)) is None:
            raise ws.WorkspaceError('invalid_conversation_watermark', 422)
        if marker.seen_at is None or observed > (marker.seen_at, marker.seen_id):
            marker.seen_at, marker.seen_id = observed
    # An automatic/late read never undoes a newer explicit Mark unread.
    if manual_unread is not None and expected_version == old_version:
        marker.manual_unread = manual_unread
    if s.is_modified(marker, include_collections=False):
        marker.version += 1
    if fence:
        fence()
    s.commit()
    return {'contract_version': 1, 'marker_version': marker.version, 'manual_unread': marker.manual_unread,
            'seen_watermark': _watermark(box, owner, wid, agent.agent_id, marker.seen_at, marker.seen_id) if marker.seen_at else None}


def _uuid(value):
    try:
        return str(UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        return False
