import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import {installLiveBridge, LAB_ORIGIN, labSession} from './bridge';
import {workspaceApi, type ProviderTeam} from '../src/workspace-api';
import {modelWorkApi} from '../src/model-work-api';
import {conversationFixture, modelReceipt, modelTimestamp, modelUuid} from '../src/model-work-test-fixture';

const {webcrypto} = await vi.importActual<{webcrypto: Crypto}>('node:crypto');
const originalWorkspace = {...workspaceApi}, originalModel = {...modelWorkApi};
const roles = ['visit_prep', 'scribe', 'follow_up', 'chief'] as const;
const team: ProviderTeam = {revision: 1, template_version: 'provider-team-v1', recovery_scope: 'a'.repeat(64),
  llm: {enabled: true, model: 'Test service'}, capture: {enabled: false},
  configuration: {practice_context: 'Invented test practice', bots: roles.map(role => ({role, name: role, enabled: true,
    response_style: 'brief', include_notebook: true, include_evidence: true}))},
  members: roles.map((role, index) => ({role, name: role, agent_id: modelUuid(index + 100), initials: 'T', description: '', prompt: '', capabilities: []}))};
const workspace = {id: modelUuid(71), appointment_id: modelUuid(72), label: 'Invented test encounter', revision: 1,
  model_contract_version: 1, model_observed_at: modelTimestamp, entries: [], work_candidates: []};
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), {status, headers: {'Content-Type': 'application/json', 'Cache-Control': 'no-store'}});
const access = {mode: 'clerk_jwt' as const, getToken: vi.fn(async () => null)};
const address = `${LAB_ORIGIN}/?persona=provider&round=1`;
beforeEach(() => { vi.stubGlobal('crypto', webcrypto); });
afterEach(() => {
  Object.assign(workspaceApi, originalWorkspace); Object.assign(modelWorkApi, originalModel);
  vi.unstubAllGlobals(); vi.clearAllMocks();
});

it('admits only explicit local persona-round links', () => {
  expect(labSession(address)).toMatchObject({base: '/lab-api/provider/1'});
  for (const bad of [address.replace('127.0.0.1', 'localhost'), address.replace('5194', '5195'),
    address.replace('provider', 'administrator'), address.replace('round=1', 'round=3'),
    address + '&persona=pa', address + '#another-session', LAB_ORIGIN + '/']) {
    expect(() => labSession(bad)).toThrow('supplied local clinician test link');
  }
});

it('pins workspace and appointment identity and blocks cross-session and external fetches before transport', async () => {
  const fetcher = vi.fn(async () => json({workspace, team})); vi.stubGlobal('fetch', fetcher);
  await installLiveBridge(address);
  fetcher.mockClear();
  await expect(workspaceApi.read(access, modelUuid(999))).rejects.toMatchObject({status: 403});
  await expect(workspaceApi.open(access, modelUuid(999))).rejects.toMatchObject({status: 403});
  await expect(fetch(`${LAB_ORIGIN}/lab-api/nurse/1/workspace`)).rejects.toMatchObject({status: 503});
  await expect(fetch('https://example.invalid/')).rejects.toMatchObject({status: 503});
  expect(fetcher).not.toHaveBeenCalled();
  await fetch(`${LAB_ORIGIN}/@vite/client`);
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(access.getToken).not.toHaveBeenCalled();
});

it('preserves exact request bodies and receipts and refuses a mismatched response', async () => {
  const receipt = await modelReceipt();
  const fetcher = vi.fn().mockResolvedValueOnce(json({workspace, team})).mockResolvedValueOnce(json(receipt))
    .mockResolvedValueOnce(json({...receipt, request_sha256: 'b'.repeat(64)}));
  vi.stubGlobal('fetch', fetcher); await installLiveBridge(address);
  const operation = {type: 'ask' as const, body: conversationFixture};
  await expect(modelWorkApi.submit(access, workspace.id, operation)).resolves.toEqual(receipt);
  expect(fetcher.mock.calls[1][0]).toBe('/lab-api/provider/1/ask');
  expect(fetcher.mock.calls[1][1]).toMatchObject({body: JSON.stringify(conversationFixture), credentials: 'omit', redirect: 'error'});
  const headers = new Headers(fetcher.mock.calls[1][1].headers);
  expect(headers.has('Authorization')).toBe(false);
  await expect(modelWorkApi.resolve(access, workspace.id, operation)).rejects.toMatchObject({status: 503});
  expect(fetcher.mock.calls[2][0]).toBe('/lab-api/provider/1/resolve');
});

it('retains real unresolved admission state and refuses unsupported handoff retries', async () => {
  const receipt = {...await modelReceipt(), outcome: 'not_found', saved_entry: null};
  const fetcher = vi.fn().mockResolvedValueOnce(json({workspace, team})).mockResolvedValueOnce(json(receipt));
  vi.stubGlobal('fetch', fetcher); await installLiveBridge(address);
  await expect(modelWorkApi.resolve(access, workspace.id, {type: 'ask', body: conversationFixture})).resolves.toEqual(receipt);
  await expect(modelWorkApi.submit(access, workspace.id, {type: 'retry', handoffId: modelUuid(81),
    body: {expected_revision: 1, previous_attempt_id: modelUuid(82), idempotency_key: 'invented-retry-key'}})).rejects.toMatchObject({status: 503});
  expect(fetcher).toHaveBeenCalledTimes(2);
});
