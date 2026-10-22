"""Closed saved-note requests keep human directions outside clinical evidence."""
import json
from dataclasses import dataclass
from types import SimpleNamespace
from uuid import uuid4

import pytest

from cosmas_os.api.clinical_note_share_schemas import ShareSavedNote
from cosmas_os.application import clinical_note_share as share
from cosmas_os.application import workspace as ws
from cosmas_os.domain.hashing import canonical_json, payload_hash
from cosmas_os.models import WorkspaceEntry, WorkspaceNote


@dataclass(frozen=True)
class Context:
    question: str
    sources: tuple
    handoff_targets: tuple


def selected():
    owner, box, wid, nid, eid = (str(uuid4()) for _ in range(5))
    note = SimpleNamespace(id=nid, workspace_id=wid, box_id=box, owner_id=owner,
        version=3, content='Invented saved note: medicine list unknown.',
        content_hash=payload_hash({'content': 'Invented saved note: medicine list unknown.'}),
        source_fingerprint='a' * 64)
    body = ShareSavedNote(expected_revision=2, idempotency_key='invented-directions-share',
        note_id=nid, note_version=3, content_hash=note.content_hash,
        source_fingerprint=note.source_fingerprint, share_with_team=True)
    entry = SimpleNamespace(id=eid, workspace_id=wid, box_id=box, actor_id=owner,
        kind='conversation', source_label=share.LABEL, idempotency_key=body.idempotency_key,
        request_hash=share._hash(body), content=canonical_json(share._snapshot(note, body)))
    values = {(WorkspaceEntry, eid): entry, (WorkspaceNote, nid): note}
    session = SimpleNamespace(get=lambda cls, id: values.get((cls, id)))
    workspace = SimpleNamespace(id=wid, box_id=box, owner_id=owner)
    context = Context('Original question', (SimpleNamespace(entry_id=eid, content=note.content),),
        ({'role': 'follow_up', 'address': 'follow_up'}, {'role': 'research', 'address': str(uuid4())}))
    request = {'contract': 'clinical-team-drafts.request.v2', 'source_entry_id': eid,
        'note_id': nid, 'note_version': 3, 'content_hash': note.content_hash,
        'owner_directions': '  Keep the email brief.\nIdentify missing evidence. 界🩺  '}
    return session, workspace, context, note, entry, request


def test_directions_are_exact_human_instructions_and_do_not_change_saved_evidence_or_v1():
    s, w, context, note, _, request = selected()
    v1 = {k: v for k, v in request.items() if k != 'owner_directions'}
    v1['contract'] = share.REQUEST_CONTRACT
    expected = share.clinical_request(s, w, {'role': 'chief'}, json.dumps(v1), context)
    result = share.clinical_request(s, w, {'role': 'chief'}, json.dumps(request, ensure_ascii=False), context)
    assert result.question.startswith(expected.question)
    assert 'Human drafting directions' in result.question
    assert json.dumps(request['owner_directions'], ensure_ascii=False) in result.question
    assert 'not clinical facts' in result.question and 'permission' in result.question
    assert result.sources is context.sources and context.sources[0].content == note.content
    assert 'patient email draft with Subject and Body' in result.question
    assert 'Drug and treatment questions' in result.question and 'never sent' in result.question
    assert share.clinical_request(s, w, {'role': 'chief'}, json.dumps(v1), context) == expected


@pytest.mark.parametrize('boundary', ['owner', 'note_version', 'note_hash', 'missing_source'])
def test_directions_do_not_bypass_exact_saved_note_authority_or_selection(boundary):
    s, w, context, note, _, request = selected()
    if boundary == 'owner':
        note.owner_id = str(uuid4())
    elif boundary == 'note_version':
        request['note_version'] += 1
    elif boundary == 'note_hash':
        request['content_hash'] = 'b' * 64
    else:
        context = Context(context.question, (), context.handoff_targets)
    with pytest.raises(ws.WorkspaceError, match='clinical_note_source_'):
        share.clinical_request(s, w, {'role': 'chief'}, json.dumps(request), context)


@pytest.mark.parametrize('directions', ['', None, 2, 'x' * 2001, '\x00' * 700], ids=['empty', 'null', 'number', 'direction_limit', 'serialized_limit'])
def test_closed_v2_rejects_invalid_or_oversized_directions_before_using_sources(directions):
    s, w, context, _, _, request = selected()
    request['owner_directions'] = directions
    with pytest.raises(ws.WorkspaceError, match='clinical_team_request_invalid'):
        share.clinical_request(s, w, {'role': 'chief'}, json.dumps(request), context)


def test_unknown_fields_are_not_permissions_and_v1_stays_closed():
    s, w, context, _, _, request = selected()
    request['send_email'] = True
    with pytest.raises(ws.WorkspaceError, match='clinical_team_request_invalid'):
        share.clinical_request(s, w, {'role': 'chief'}, json.dumps(request), context)
    request.pop('send_email')
    request['contract'] = share.REQUEST_CONTRACT
    with pytest.raises(ws.WorkspaceError, match='clinical_team_request_invalid'):
        share.clinical_request(s, w, {'role': 'chief'}, json.dumps(request), context)


@pytest.mark.parametrize('boundary', ['ready', 'llm', 'source_grant', 'model_grant', 'draft_grant'])
def test_deployed_v2_capability_reuses_existing_chief_readiness_and_permissions(monkeypatch, boundary):
    from cosmas_os.application import provider_team as team
    config = team.default_configuration()
    chief = next(bot for bot in config['bots'] if bot['role'] == 'chief')
    if boundary == 'source_grant':
        chief['include_evidence'] = False
    elif boundary == 'model_grant':
        chief['blocked_capabilities'] = ['model_answer']
    elif boundary == 'draft_grant':
        chief['blocked_capabilities'] = ['private_draft_handoff']
    class Runtime:
        workspace_llm_available = boundary != 'llm'
        def __getattr__(self, name):
            return False
    monkeypatch.setattr(team, 'runtime_settings', Runtime())
    monkeypatch.setattr(team, '_human', lambda *args: None)
    version = SimpleNamespace(revision=1, template_version='provider-team-v1', configuration=config)
    result = team.read(SimpleNamespace(scalars=lambda *args: []), str(uuid4()), str(uuid4()), version=version)
    member = next(row for row in result['members'] if row['role'] == 'chief')
    cap = next(row for row in member['capabilities'] if row['key'] == 'workspace.clinical.drafts')
    assert cap['contract'] == 'clinical-team-drafts.request.v2'
    assert cap['state'] == ('enabled' if boundary == 'ready' else 'awaiting_connection')
    assert chief.get('blocked_capabilities', []) == ([] if boundary not in {'model_grant', 'draft_grant'} else
        ['model_answer' if boundary == 'model_grant' else 'private_draft_handoff'])
