"""A chat reservation must not invalidate its unchanged linked work handle."""

import pytest
from pydantic import SecretStr
from sqlalchemy.orm import Session
from tests.integration.test_follow_up import decide, prepare, propose

from cosmas_os.application import agent_tools, model_work, operations_status, provider_team
from cosmas_os.application import services as svc
from cosmas_os.application import workspace as ws


@pytest.fixture
def prepared(engine, monkeypatch):
    runtime = provider_team.runtime_settings
    monkeypatch.setattr(runtime, 'workspace_enabled', True)
    monkeypatch.setattr(runtime, 'workspace_llm_backend', 'azure_gpt41')
    monkeypatch.setattr(runtime, 'workspace_llm_api_key', SecretStr('invented-no-network'))
    monkeypatch.setattr(runtime, 'workspace_agent_tools_enabled', True)
    with Session(engine) as s:
        case = prepare(s, svc.provision_box(svc.Container(s), 'Invented status tools'))
        provider_team.save(s, case[0], case[1], expected=0, key='invented-team', configuration=provider_team.default_configuration())
        created = propose(s, case)
        item = created['workspace']['follow_ups'][0]
    return case, item


def test_status_tool_survives_its_own_reservation_and_unrelated_chat_entry(engine, prepared):
    case, item = prepared
    with Session(engine) as s:
        before = operations_status.read(s, case[0], case[1], case[2]['id'], kind='follow_up', record_id=item['ticket_id'])
        aid, _ = model_work.reserve_conversation(s, case[0], case[1], case[2]['id'],
            expected=ws.read(s, case[0], case[1], case[2]['id'])['revision'], team_revision=1,
            key='invented-status-tools', role='chief', content='What is the saved follow-up status?')
        claim = model_work.claim(s, case[0], case[1], aid)
    assert claim is not None
    selection = claim.envelope['tool_selection']['operations'][0]
    with Session(engine) as s:
        result = agent_tools.AgentToolExecutor(s, claim).execute({'tool':'read_current_operation_status', **selection})
        assert result['data']['evidence']['commitment'] == before['evidence']['commitment']
        assert result['data']['next_step']['code'] == 'review_and_approve'
        assert result['data']['evidence']['external_outcome'] == 'not_established'
        assert result['receipt']['actor_agent_id'] != result['receipt']['initiated_by_human_id']


def test_approval_and_delivery_change_status_commitment(engine, prepared):
    case, item = prepared
    with Session(engine) as s:
        before = operations_status.read(s, case[0], case[1], case[2]['id'], kind='follow_up', record_id=item['ticket_id'])
        decide(s, case, item)
        after = operations_status.read(s, case[0], case[1], case[2]['id'], kind='follow_up', record_id=item['ticket_id'])
        assert after['evidence']['commitment'] != before['evidence']['commitment']
        assert after['evidence']['external_outcome'] == 'synthetic_only'
