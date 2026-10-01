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


def test_compact_source_and_draft_handles_preserve_exact_read_dependencies(clinic):
    from lab.connector_tools import ConnectorWorld
    from lab.store import digest

    app, store = clinic
    world = ConnectorWorld(store, 'compact-handles', CASE, app, prepare_fax=False)
    try:
        sources = world.execute('scribe', 'list_sources', {})
        command = {'body': 'Invented source faithful draft for human review.',
                   'source_refs': [sources[0]['source_ref']], 'dependency_roles': []}
        assert world.execute('scribe', 'save_connector_draft', command)['error'] == 'unread_or_foreign_citation'
        read = world.execute('scribe', 'read_selected_source', {'source_ref': sources[0]['source_ref']})
        assert read['id'] == sources[0]['id']
        saved = world.execute('scribe', 'save_connector_draft', command)
        assert saved['source_ids'] == [read['id']]
        assert world.execute('visit_prep', 'read_shared_draft', {'role': 'scribe'})['error'] == 'artifact_not_shared_with_this_agent'
        consumed = world.execute('chief', 'read_shared_draft', {'role': 'scribe'})
        assert consumed == saved
        assert world.artifact_reads['chief']['scribe'] == saved['sha256']
        assert saved['sha256'] == digest({k: v for k, v in saved.items() if k not in {'id', 'role', 'sha256'}})
        assert world.execute('chief', 'read_selected_source', {'source_ref': 'source-999'})['error'] == 'source_outside_selected_encounter'
    finally:
        world.close()
