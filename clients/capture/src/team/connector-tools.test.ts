import {describe, expect, it, vi} from 'vitest';
import {ConnectorTools, parseConnectorCatalog, parseAgentResearchHistory, type ConnectorTransport} from './connector-tools';

const tool = (id = 'google.connection_status', enabled = true) => ({name: id.replace('.', '_'), title: 'Check account',
  description: 'Read current account state.', annotations: {readOnlyHint: true},
  _meta: {'ai.cosmas/operation': {id, plugin: id.split('.')[0], feature_enabled: enabled, agent_callable: true,
    external_send: false, implementation: 'first_party_http', account_status: 'not_checked', operation_health: 'not_checked',
    http: {path: 'https://untrusted.invalid/never-used'}}}});
const catalog = (rows = [tool()]) => ({tools: rows, _meta: {'ai.cosmas/contract': 'cosmas.plugins.v1'}});

describe('signed connector client', () => {
  it('uses fixed paths and closed status commands, ignoring catalog routing metadata', async () => {
    const transport = vi.fn<ConnectorTransport>().mockResolvedValueOnce(catalog()).mockResolvedValueOnce({state: 'connected'});
    expect((await new ConnectorTools(transport).status('google.connection_status')).state).toBe('connected');
    expect(transport.mock.calls.map(([path]) => path)).toEqual(['/connections/plugins', '/connections/google/session']);
    expect(transport.mock.calls[1][1]).toMatchObject({method: 'POST', contractHeader: 'X-Cosmas-Google-Connection',
      body: {action: 'status', include_capabilities: true}});
  });
  it('does not execute disabled tools or automatically repeat an unconfirmed response', async () => {
    const transport = vi.fn<ConnectorTransport>().mockResolvedValue(catalog([tool('google.connection_status', false)]));
    await expect(new ConnectorTools(transport).status('google.connection_status')).rejects.toMatchObject({code: 'connector_unavailable'});
    expect(transport).toHaveBeenCalledTimes(1);
    transport.mockReset().mockResolvedValueOnce(catalog()).mockRejectedValueOnce(new Error('lost response'));
    await expect(new ConnectorTools(transport).status('google.connection_status')).rejects.toThrow('lost response');
    expect(transport).toHaveBeenCalledTimes(2);
  });
  it('rejects a fabricated write ID before catalog or execution', async () => {
    const transport = vi.fn<ConnectorTransport>();
    await expect(new ConnectorTools(transport).status('google.disconnect' as never)).rejects.toMatchObject({code: 'invalid_connector_request'});
    expect(transport).not.toHaveBeenCalled();
  });
  it.each([catalog([tool(), tool()]), catalog([{...tool(), name: 'wrong'}]),
    {...catalog(), _meta: {'ai.cosmas/contract': 'future'}},
    catalog([{...tool(), _meta: {'ai.cosmas/operation': {...tool()._meta['ai.cosmas/operation'], feature_enabled: 'false' as never}}}])])(
    'rejects malformed discovery rather than inferring capability', value => expect(() => parseConnectorCatalog(value)).toThrow());
});

it('binds reviewed research metadata to one workspace and preserves expired/unknown states', () => {
  const id = '00000000-0000-4000-8000-000000000001';
  const row = {contract: 'agent-research.review.v1', workspace_id: id, ticket_id: id,
    revision_id: id, payload_hash: 'a'.repeat(64), state: 'outcome_unconfirmed', query: 'Dust and cough',
    topic: 'literature', sources: ['pubmed'], expires_at: '2026-10-06T17:00:00Z', bot: id, team_revision: 1,
    run_id: null, next_step: 'wait_for_result'};
  const value = {contract: 'agent-research.history.v1', workspace_id: id, proposals: [row]};
  expect(parseAgentResearchHistory(value, id).proposals[0].state).toBe('outcome_unconfirmed');
  expect(() => parseAgentResearchHistory({...value, proposals: [row, row]}, id)).toThrow();
  expect(() => parseAgentResearchHistory({...value, proposals: [{...row, next_step: 'ask_research_to_execute'}]}, id)).toThrow();
  expect(() => parseAgentResearchHistory(value, '00000000-0000-4000-8000-000000000002')).toThrow();
});
