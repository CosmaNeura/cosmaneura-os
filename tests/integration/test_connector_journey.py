"""Active connector tools must leave exact evidence and observed proposal receipts."""
import pytest
from lab.connector_journey import CASE, JourneyWorld, run_connectors
from lab.store import LabError
from tests.integration.test_virtual_clinic_lab import clinic as clinic


def test_five_bot_connector_replay_persists_selected_sources_and_unsubmitted_proposal(clinic):
    app, store = clinic
    result = run_connectors(app, store, 'connector-journey-test', None, concurrency=3)
    assert result['passed'], result['failures']
    assert all(result['checks'].values())
    assert len(result['artifacts']) == 5
    assert len(result['application']['fax_receipts']) == 2
    assert result['application']['external_effects'] == 0


def test_fax_provider_review_is_not_available_as_an_agent_tool(clinic):
    app, store = clinic
    world = JourneyWorld(store, 'connector-no-review', CASE, app, prepare_fax=False)
    try:
        assert world.execute('chief', 'prepare_fax_fixture', {})['error'] == 'unknown_tool'
        assert world.execute('follow_up', 'fax_readiness', {'provider': 'documo'})['error'] == 'fax_fixture_provider_review_required'
        with pytest.raises(LabError, match='fax_receipt'):
            world.validate_saved_artifact('follow_up')
        assert world.fax is None
    finally:
        world.close()


def test_research_saved_lookup_is_not_disclosed_after_role_revocation(clinic, monkeypatch):
    from lab.research_tools import ResearchTools
    from sqlalchemy.orm import Session

    from cosmas_os.application import workspace

    app, _ = clinic
    tools = ResearchTools(app)
    with Session(app.engine) as session:
        revision = workspace.read(session, app.box, app.owner, app.workspace)['revision']
    tools.call('research', 'research_lookup_trials', {
        'idempotency_key': 'research-role-revoke-test', 'expected_workspace_revision': revision})
    calls = 0
    def check(role):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise LabError('agent_authority_unavailable')
    monkeypatch.setattr(app, 'check_agent', check)
    with pytest.raises(LabError, match='agent_authority_unavailable'):
        tools.call('research', 'research_resolve_lookup', {'idempotency_key': 'research-role-revoke-test'})
    assert tools.calls == 1
