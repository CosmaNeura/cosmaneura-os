import {afterEach, expect, it, vi} from 'vitest';
import {agentResearchApi, connectorToolsApi} from './connector-tools-api';

const identity = {mode: 'clerk_jwt' as const, getToken: vi.fn(async () => 'invented-current-session')};
const catalog = (enabled = true) => ({tools: [{name: 'google_connection_status', title: 'Check Google',
  description: 'Read current local account state.', annotations: {readOnlyHint: true},
  _meta: {'ai.cosmas/operation': {id: 'google.connection_status', plugin: 'google', feature_enabled: enabled,
    agent_callable: true, external_send: false, implementation: 'first_party_http',
    account_status: 'not_checked', operation_health: 'not_checked'}}}], _meta: {'ai.cosmas/contract': 'cosmas.plugins.v1'}});
const response = (value: unknown) => new Response(JSON.stringify(value), {headers: {'Content-Type': 'application/json', 'Cache-Control': 'no-store'}});
afterEach(() => {vi.unstubAllGlobals(); vi.unstubAllEnvs(); vi.useRealTimers(); identity.getToken.mockClear();});

it('uses the existing fresh session for discovery and each operation without a token file', async () => {
  vi.stubEnv('VITE_API_BASE', 'http://127.0.0.1:8000');
  const fetcher = vi.fn().mockResolvedValueOnce(response(catalog())).mockResolvedValueOnce(response({state: 'sign_in_required', account: null, connected_at: null, capabilities: {mail: false, calendar: false}}));
  vi.stubGlobal('fetch', fetcher);
  expect((await connectorToolsApi(identity).status('google.connection_status')).state).toBe('sign_in_required');
  expect(identity.getToken).toHaveBeenCalledTimes(2);
  expect(identity.getToken).toHaveBeenNthCalledWith(1, {skipCache: true});
  expect(fetcher.mock.calls[1][1]).toMatchObject({method: 'POST', cache: 'no-store', credentials: 'omit', redirect: 'error'});
  expect(fetcher.mock.calls[1][1].headers.get('Authorization')).toBe('Bearer invented-current-session');
  expect(fetcher.mock.calls[1][1].headers.get('X-Cosmas-Google-Connection')).toBe('1');
  expect(JSON.parse(fetcher.mock.calls[1][1].body)).toEqual({action: 'status', include_capabilities: true});
});
it('withholds a read after sign-in changes and refuses redirects', async () => {
  let current = true;
  vi.stubGlobal('fetch', async () => {current = false; return response(catalog());});
  await expect(connectorToolsApi({...identity, nativeSession: {revision: 'invented', isCurrent: () => current}}).catalog()).rejects.toMatchObject({status: 401});
  const redirected = response(catalog()); Object.defineProperty(redirected, 'redirected', {value: true});
  vi.stubGlobal('fetch', async () => redirected);
  await expect(connectorToolsApi(identity).catalog()).rejects.toMatchObject({status: 502});
});
it('ends a stalled signed catalog without retrying it', async () => {
  vi.useFakeTimers(); const fetcher = vi.fn(() => new Promise<Response>(() => {})); vi.stubGlobal('fetch', fetcher);
  const result = expect(connectorToolsApi(identity).catalog()).rejects.toMatchObject({status: 503});
  await vi.advanceTimersByTimeAsync(15000); await result; expect(fetcher).toHaveBeenCalledTimes(1);
});

it('binds human research approval to its exact handle and existing signed Research contract', async () => {
  const id = (n: number) => `00000000-0000-4000-8000-${n.toString().padStart(12, '0')}`;
  const approval = {ticket_id: id(2), revision_id: id(3), payload_hash: 'a'.repeat(64), public_query_confirmed: true as const};
  const row = {contract: 'agent-research.review.v1', workspace_id: id(1), ticket_id: approval.ticket_id,
    revision_id: approval.revision_id, payload_hash: approval.payload_hash,
    state: 'approved', query: 'Dust exposure and cough', topic: 'literature', sources: ['pubmed'],
    expires_at: '2099-10-06T17:00:00Z', bot: id(4), team_revision: 1, run_id: null, next_step: 'ask_research_to_execute'};
  const fetcher = vi.fn().mockResolvedValueOnce(response(row)).mockResolvedValueOnce(response({...row, payload_hash: 'b'.repeat(64)}));
  vi.stubGlobal('fetch', fetcher);
  expect((await agentResearchApi.approve(identity, id(1), approval)).state).toBe('approved');
  expect(fetcher.mock.calls[0][0]).toContain(`/agent-research/${id(2)}/review`);
  expect(fetcher.mock.calls[0][1].headers.get('X-Cosmas-Research-Contract')).toBe('1');
  expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({revision_id: id(3), payload_hash: approval.payload_hash, public_query_confirmed: true});
  await expect(agentResearchApi.approve(identity, id(1), approval)).rejects.toMatchObject({status: 502});
});
