"""Invented conversations exercise real PostgreSQL ownership and read state."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from tests.integration import test_google_message_model_work as google
from tests.integration import test_handoff_review as handoff
from tests.integration import test_model_work_admission as model_work
from tests.integration.test_provider_team import ask
from tests.integration.test_provider_team import case as provider_case
from tests.integration.test_workspace_auth import signed_workspace as signed_fixture

from cosmas_os.application import conversation_inbox as inbox
from cosmas_os.application import model_work as work
from cosmas_os.application import provider_team as team
from cosmas_os.application import workspace as ws
from cosmas_os.conversation_models import ConversationReadMarker
from cosmas_os.models import (
    EncounterWorkspace,
    PatientLink,
    Principal,
    WorkspaceEntry,
    WorkspaceReply,
)

case = provider_case
signed_workspace = signed_fixture
google_case = google.google_case
review_case = handoff.case
model = handoff.model
enabled = model_work.enabled


def test_only_human_opened_conversations_appear_not_a_default_roster(session, case):
    box, owner, w, _ = case
    assert inbox.read(session, box, owner)['rows'] == []
    inbox.update_marker(session, box, owner, w['id'], 'chief')
    rows = inbox.read(session, box, owner)['rows']
    assert [r['bot']['address'] for r in rows] == ['chief']
    assert rows[0]['unread'] is False
    ask(session, case)
    assert {r['bot']['address'] for r in inbox.read(session, box, owner)['rows']} == {'chief', 'visit_prep'}


def test_seen_watermark_is_monotonic_and_manual_unread_is_separate(session, case):
    box, owner, w, _ = case
    ask(session, case)
    first = inbox.read(session, box, owner)['rows'][0]
    saved = inbox.update_marker(session, box, owner, w['id'], 'visit_prep', watermark=first['watermark'])
    assert inbox.read(session, box, owner)['rows'][0]['unread'] is False
    manual = inbox.update_marker(session, box, owner, w['id'], 'visit_prep', manual_unread=True, expected_version=saved['marker_version'])
    # A delayed auto-read and a stale explicit read cannot undo Mark unread.
    stale = inbox.update_marker(session, box, owner, w['id'], 'visit_prep', watermark=first['watermark'], manual_unread=False, expected_version=saved['marker_version'])
    assert stale['manual_unread'] is True
    assert inbox.read(session, box, owner)['rows'][0]['unread'] is True
    cleared = inbox.update_marker(session, box, owner, w['id'], 'visit_prep', watermark=first['watermark'], manual_unread=False, expected_version=manual['marker_version'])
    assert cleared['manual_unread'] is False
    with pytest.raises(DBAPIError), session.begin_nested():
        marker = session.get(ConversationReadMarker, (w['id'], next(m['agent_id'] for m in case[3]['members'] if m['role'] == 'visit_prep')))
        marker.seen_at -= timedelta(seconds=1)
        session.flush()


def test_reply_arrival_becomes_unread_without_a_workspace_revision_change(session, case):
    box, owner, w, _ = case
    result = ask(session, case)
    first = inbox.read(session, box, owner)['rows'][0]
    inbox.update_marker(session, box, owner, w['id'], 'visit_prep', watermark=first['watermark'])
    # A second saved request has an earlier creation time than its reply arrival.
    old_revision = session.get(EncounterWorkspace, w['id']).revision
    entry = WorkspaceEntry(workspace_id=w['id'], box_id=box, actor_id=owner, revision=old_revision + 1,
        kind='conversation', content='Invented second question', source_label=None, idempotency_key='invented-second', request_hash='b' * 64)
    session.add(entry)
    session.get(EncounterWorkspace, w['id']).revision += 1
    session.commit()
    original = session.get(WorkspaceReply, result['entry_id'])
    before_reply_revision = session.get(EncounterWorkspace, w['id']).revision
    reply = WorkspaceReply(entry_id=entry.id, workspace_id=w['id'], box_id=box, owner_id=owner,
        agent_id=original.agent_id, team_revision_id=original.team_revision_id, agent_name=original.agent_name,
        role=original.role, backend=original.backend, context_revision=old_revision, content='Invented late answer', citations=[])
    session.add(reply)
    session.commit()
    latest = inbox.read(session, box, owner)['rows'][0]
    assert latest['unread'] and latest['preview'] == 'Invented late answer'
    assert latest['last_activity_at'] > first['last_activity_at']
    assert session.get(EncounterWorkspace, w['id']).revision == before_reply_revision
    inbox.update_marker(session, box, owner, w['id'], 'visit_prep', watermark=latest['watermark'])
    inbox.update_marker(session, box, owner, w['id'], 'visit_prep', watermark=first['watermark'])
    assert inbox.read(session, box, owner)['rows'][0]['unread'] is False


def test_owner_agent_and_revoked_patient_boundaries(session, case):
    box, owner, w, config = case
    ask(session, case)
    other = Principal(box_id=box, principal_type='human', display_name='Invented other reader')
    session.add(other)
    session.commit()
    assert inbox.read(session, box, other.id)['rows'] == []
    with pytest.raises(ws.WorkspaceError):
        inbox.update_marker(session, box, other.id, w['id'], 'chief')
    with pytest.raises(ws.WorkspaceError):
        inbox.read(session, box, config['members'][0]['agent_id'])
    workspace = session.get(EncounterWorkspace, w['id'])
    session.get(PatientLink, workspace.patient_link_id).revoked_at = datetime.now(UTC)
    session.commit()
    assert inbox.read(session, box, owner)['rows'] == []
    with pytest.raises(ws.WorkspaceError):
        inbox.update_marker(session, box, owner, w['id'], 'visit_prep')


def test_private_note_threads_and_bounded_stable_paging(session, case):
    box, owner, _, _ = case
    for index in range(23):
        w = ws.create_private_draft(session, box, owner, f'Invented note {index}', f'invented-note-{index}')
        inbox.update_marker(session, box, owner, w['id'], 'chief')
    statements = []
    def counted(*args):
        statements.append(args[2])
    event.listen(session.get_bind(), 'before_cursor_execute', counted)
    try:
        first = inbox.read(session, box, owner)
    finally:
        event.remove(session.get_bind(), 'before_cursor_execute', counted)
    assert len(first['rows']) == 20 and first['next_cursor']
    assert len(statements) <= 22  # Fixed batch count, independent of 20 rows.
    second = inbox.read(session, box, owner, cursor=first['next_cursor'])
    assert len(second['rows']) == 3 and second['next_cursor'] is None
    assert len({r['workspace_id'] for r in first['rows'] + second['rows']}) == 23
    with pytest.raises(ws.WorkspaceError):
        inbox.read(session, box, owner, cursor=first['next_cursor'][:-1] + ('0' if first['next_cursor'][-1] != '0' else '1'))


def test_inbox_api_is_no_store_and_rejects_invalid_markers(session, signed_workspace):
    case = signed_workspace
    team.save(session, case.box, case.actor, expected=0, key='invented-team', configuration=team.default_configuration())
    headers = {'Authorization': 'Bearer ' + case.token(), 'X-Cosmas-Conversations': '1', 'X-Cosmas-Team-Contract': '2', 'X-Cosmas-Draft-Recovery': '2'}
    response = case.client.get('/workspaces/conversations', headers=headers)
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'no-store'
    path = f"/workspaces/{case.workspace['id']}/conversations/chief/read"
    opened = case.client.post(path, headers=headers, json={})
    assert opened.status_code == 200, opened.text
    rejected = case.client.post(path, headers=headers, json={'watermark': 'r1' + '0' * 113})
    assert rejected.status_code == 422 and rejected.headers['cache-control'] == 'no-store'
    assert case.client.get('/workspaces/conversations?include=all-bots', headers=headers).status_code == 422


def test_failed_or_expired_model_result_is_not_idle(engine, enabled):
    box, owner, wid, _ = model_work.case(engine)
    at = datetime.now(UTC)
    with Session(engine) as s:
        admission, _ = work.reserve_conversation(s, box, owner, wid, clock=lambda: at, **model_work.command())
        assert admission
        result = inbox.read(s, box, owner, clock=lambda: at + timedelta(minutes=5))
        assert result['rows'][0]['attention'] == 'needs_check'


def test_delegation_is_a_chief_attention_card_not_an_automatic_specialist_chat(session, review_case):
    box, owner, w, _, _, _, _ = review_case
    initial = inbox.read(session, box, owner)
    assert [r['bot']['address'] for r in initial['rows']] == ['chief']
    assert initial['rows'][0]['attention'] == 'needs_review'
    handoff.review(session, review_case)
    assert inbox.read(session, box, owner)['rows'][0]['attention'] == 'idle'


def test_selected_source_preview_remains_withheld_after_revocation(google_case):
    f = google_case
    with Session(f.engine) as s:
        inbox.update_marker(s, f.box, f.owner, f.wid, 'chief')
        before = inbox.read(s, f.box, f.owner)['rows'][0]
        assert before['preview_withheld'] and f.port.text not in before['preview']
    google.change_source(f, 'disconnect')
    with Session(f.engine) as s:
        after = inbox.read(s, f.box, f.owner)['rows'][0]
        assert after['preview_withheld'] and f.port.text not in after['preview']


def test_a_watermark_from_another_bot_cannot_mark_this_chat_read(session, case):
    box, owner, w, _ = case
    ask(session, case)
    row = inbox.read(session, box, owner)['rows'][0]
    with pytest.raises(ws.WorkspaceError):
        inbox.update_marker(session, box, owner, w['id'], 'chief', watermark=row['watermark'])
