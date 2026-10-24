"""Invented conversations exercise real PostgreSQL ownership and read state."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from tests.integration import test_clinical_team_drafts as clinical_drafts
from tests.integration import test_google_message_model_work as google
from tests.integration import test_handoff_review as handoff
from tests.integration import test_model_work_admission as model_work
from tests.integration.test_provider_team import ask
from tests.integration.test_provider_team import case as provider_case
from tests.integration.test_workspace_auth import signed_workspace as signed_fixture

from cosmas_os.application import conversation_inbox as inbox
from cosmas_os.application import handoff_review, note_review
from cosmas_os.application import model_work as work
from cosmas_os.application import provider_team as team
from cosmas_os.application import workspace as ws
from cosmas_os.conversation_models import ConversationReadMarker
from cosmas_os.models import (
    AppointmentObservation,
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
clinical = clinical_drafts.clinical
bridge = clinical_drafts.bridge
capture_case = clinical_drafts.capture_case


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


def test_changes_requested_stays_actionable_until_revision_is_queued_and_reviewed(session, review_case, monkeypatch):
    box, owner, w, _, _, _, _ = review_case
    original = handoff_review.review_for
    class NoDatabase:
        def __getattr__(self, name):
            pytest.fail(f'Revision snapshot attempted database access: {name}')
    def checked(s, workspace, assignment, attempt, **options):
        return original(NoDatabase() if options.get('snapshot') is not None else s,
            workspace, assignment, attempt, **options)
    monkeypatch.setattr(handoff_review, 'review_for', checked)
    response, receipt = handoff.changes_requested(session, review_case)
    assert inbox.read(session, box, owner)['rows'][0]['attention'] == 'needs_review'
    revised = handoff.revise(session, review_case, response, receipt)
    assert inbox.read(session, box, owner)['rows'][0]['attention'] == 'working'
    assert handoff.shared.worker(session)
    assert inbox.read(session, box, owner)['rows'][0]['attention'] == 'needs_review'
    current = ws.read(session, box, owner, w['id'])
    child = next(h for h in current['handoffs'] if h['id'] == revised['revision_handoff_id'])
    child_case = box, owner, current, review_case[3], review_case[4], child, child['result_sha256']
    handoff.review(session, child_case, key='invented-inbox-revision-accepted')
    assert inbox.read(session, box, owner)['rows'][0]['attention'] == 'idle'


def test_reviewed_handoff_query_count_is_constant_across_twenty_conversations(session, review_case):
    box, owner, _, config, patient, _, _ = review_case
    handoff.review(session, review_case)
    def measured():
        statements = []
        def counted(*args):
            statements.append(args[2])
        event.listen(session.get_bind(), 'before_cursor_execute', counted)
        try:
            result = inbox.read(session, box, owner)
        finally:
            event.remove(session.get_bind(), 'before_cursor_execute', counted)
        return result['rows'], len(statements)
    first, first_count = measured()
    assert len(first) == 1 and first[0]['attention'] == 'idle'
    for index in range(19):
        appointment = AppointmentObservation(box_id=box, patient_link_id=patient,
            external_id=str(uuid4()), source='synthetic', start_at=datetime.now(UTC),
            patient_label=f'Invented reviewed visit {index}')
        session.add(appointment)
        session.commit()
        w = ws.create(session, box, owner, appointment.id, f'invented-reviewed-visit-{index}')
        handoff.shared.assign(session, (box, owner, w, config, patient), key=f'invented-assignment-{index}')
        assert handoff.shared.worker(session)
        current = ws.read(session, box, owner, w['id'])
        h = current['handoffs'][0]
        handoff.review(session, (box, owner, current, config, patient, h, h['result_sha256']),
            key=f'invented-reviewed-result-{index}')
    rows, populated_count = measured()
    assert len(rows) == 20 and all(row['attention'] == 'idle' for row in rows)
    assert populated_count == first_count <= 26


def test_review_snapshot_matches_sql_and_fails_closed_when_required_inputs_are_missing(session, review_case, monkeypatch):
    box, owner, _, _, _, _, _ = review_case
    handoff.review(session, review_case)
    captured = []
    original = handoff_review.review_for
    def remember(s, w, assignment, attempt, **options):
        result = original(s, w, assignment, attempt, **options)
        captured.append((w, assignment, attempt, options['snapshot'], result))
        return result
    monkeypatch.setattr(handoff_review, 'review_for', remember)
    assert inbox.read(session, box, owner)['rows'][0]['attention'] == 'idle'
    w, assignment, attempt, snapshot, expected = captured[0]
    assert expected == original(session, w, assignment, attempt)
    class NoDatabase:
        def __getattr__(self, name):
            pytest.fail(f'Preloaded review attempted database access: {name}')
    assert expected == original(NoDatabase(), w, assignment, attempt, snapshot=snapshot)
    for incomplete in [replace(snapshot, admissions={}), replace(snapshot, replies={}),
        replace(snapshot, attempts=()), replace(snapshot, clinical=replace(snapshot.clinical, entries={})),
        replace(snapshot, team=replace(snapshot.team, principals={})),
        replace(snapshot, team=replace(snapshot.team, current=None))]:
        assert original(NoDatabase(), w, assignment, attempt, snapshot=incomplete) is None


def test_accepted_clinical_drafts_use_shared_review_authority_for_each_open_chat(clinical, monkeypatch):
    f = clinical
    receipt = clinical_drafts.shared(f)
    calls = []
    chief = clinical_drafts.reserve(f, receipt)
    result = clinical_drafts.dispatch(f, chief, calls)
    with Session(f.engine) as s:
        work.settle(s, chief, result)
    for _ in range(2):
        assert work.process_next(lambda: clinical_drafts.sessions(f.engine),
            dispatch=lambda claim: clinical_drafts.dispatch(f, claim, calls))
    with Session(f.engine) as s:
        snapshot = ws.read(s, f.box, f.actor, f.workspace['id'])
        for h in snapshot['handoffs']:
            assert receipt['source_entry_id'] in {source['entry_id'] for source in h['task_brief']['source_versions']}
            reviewed = handoff_review.review(s, f.box, f.actor, f.workspace['id'], h['id'],
                expected=snapshot['revision'], key='invented-inbox-accept-' + h['recipient_role'],
                attempt_id=h['attempt_id'], result_entry_id=h['result_entry_id'],
                result_sha256=h['result_sha256'], decision='accepted', feedback='')
            snapshot = reviewed['workspace']
        note = snapshot['note']['latest']
        reviewed_note = note_review.review(s, f.box, f.actor, f.workspace['id'], note['id'],
            expected=snapshot['revision'], key='invented-inbox-note-review',
            content_hash=note['content_hash'], source_hash=note['source_fingerprint'])
        assert all(h['review_status'] == 'current' for h in reviewed_note['workspace']['handoffs'])
        for bot in ('follow_up', f.research_id):
            inbox.update_marker(s, f.box, f.actor, f.workspace['id'], bot)
        checks = []
        original = handoff_review.review_for
        class NoDatabase:
            def __getattr__(self, name):
                pytest.fail(f'Clinical snapshot attempted database access: {name}')
        def counted(session, workspace, assignment, attempt, **options):
            checks.append(assignment.id)
            assert options['snapshot'] is not None
            return original(NoDatabase(), workspace, assignment, attempt, **options)
        monkeypatch.setattr(handoff_review, 'review_for', counted)
        statements = []
        def query_counted(*args):
            statements.append(args[2])
        event.listen(s.get_bind(), 'before_cursor_execute', query_counted)
        try:
            rows = inbox.read(s, f.box, f.actor)['rows']
        finally:
            event.remove(s.get_bind(), 'before_cursor_execute', query_counted)
        assert {row['bot']['address'] for row in rows} == {'chief', 'follow_up', f.research_id}
        assert all(row['attention'] == 'idle' for row in rows)
        assert len(checks) == len(set(checks)) == 2  # Shared review once, not once per chat.
        assert len(statements) <= 26  # Includes clinical source and locked-principal batches.


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
