import {act} from 'react';
import {createRoot, type Root} from 'react-dom/client';
import {beforeEach, afterEach, expect, it, vi} from 'vitest';
import {AgentResearchReviewPanel} from './AgentResearchReviewPanel';
import {agentResearchApi} from './connector-tools-api';
import type {AgentResearchReview} from '../../clients/capture/src/team/connector-tools';
import {validateAgentResearchRecovery, type AgentResearchRecovery} from './agent-research-recovery';
vi.mock('./connector-tools-api', () => ({agentResearchApi: {list: vi.fn(), approve: vi.fn()}}));

const uuid = (n: number) => `00000000-0000-4000-8000-${n.toString().padStart(12, '0')}`;
const workspaceId = uuid(1), identity = {mode: 'clerk_jwt' as const, getToken: async () => 'invented'};
const proposal: AgentResearchReview = {contract: 'agent-research.review.v1', workspace_id: workspaceId,
  ticket_id: uuid(2), revision_id: uuid(3), payload_hash: 'a'.repeat(64), state: 'pending_approval',
  query: 'Evidence on dust exposure and cough in adults', topic: 'literature', sources: ['pubmed'],
  expires_at: '2099-10-06T17:00:00Z', bot: uuid(4), team_revision: 1, run_id: null, next_step: 'review_query'};
let root: Root, host: HTMLDivElement, saved: AgentResearchRecovery | null;
const events: string[] = [];
const recovery = {authorize: vi.fn(async () => {}), load: vi.fn(async () => saved),
  persist: vi.fn(async (value: AgentResearchRecovery | null) => {events.push(value ? 'persist' : 'clear'); saved = value;})};
const button = (label: string) => [...host.querySelectorAll('button')].find(value => value.textContent === label)!;
const mount = () => act(async () => root.render(<AgentResearchReviewPanel identity={identity} workspaceId={workspaceId} recovery={recovery}/>));
const load = () => act(async () => button('Load proposed queries').click());
beforeEach(() => {vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); saved = null; events.length = 0; vi.clearAllMocks();
  vi.mocked(agentResearchApi.list).mockResolvedValue({contract: 'agent-research.history.v1', workspace_id: workspaceId, proposals: [proposal]});
  vi.mocked(agentResearchApi.approve).mockImplementation(async () => {events.push('approve'); return {...proposal, state: 'approved', next_step: 'ask_research_to_execute'};});
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);});
afterEach(async () => {await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals();});

it('persists exact human approval before dispatch and does not start a model or public search', async () => {
  await mount(); expect(agentResearchApi.list).not.toHaveBeenCalled(); await load();
  expect(button('Approve public search').disabled).toBe(true);
  await act(async () => host.querySelector<HTMLInputElement>('input')!.click());
  await act(async () => button('Approve public search').click());
  expect(events).toEqual(['persist', 'approve', 'clear']);
  expect(agentResearchApi.approve).toHaveBeenCalledWith(identity, workspaceId, {ticket_id: proposal.ticket_id,
    revision_id: proposal.revision_id, payload_hash: proposal.payload_hash, public_query_confirmed: true}, expect.any(AbortSignal));
  expect(saved).toBeNull(); expect(host.textContent).toContain('Ask Research to run this reviewed query');
});
it('sends no approval when encrypted recovery persistence fails', async () => {
  recovery.persist.mockRejectedValueOnce(new Error('storage unavailable'));
  await mount(); await load(); await act(async () => host.querySelector<HTMLInputElement>('input')!.click());
  await act(async () => button('Approve public search').click());
  expect(agentResearchApi.approve).not.toHaveBeenCalled();
  expect(host.textContent).toContain('approval was not sent'); expect(button('Load proposed queries').disabled).toBe(true);
});
it('preserves lost approval across remount and resolves it by reading, without another POST', async () => {
  vi.mocked(agentResearchApi.approve).mockRejectedValue(new Error('lost response'));
  await mount(); await load(); await act(async () => host.querySelector<HTMLInputElement>('input')!.click());
  await act(async () => button('Approve public search').click());
  expect(saved?.pending?.revision_id).toBe(proposal.revision_id);
  await act(async () => root.unmount()); root = createRoot(host);
  await mount(); expect(host.textContent).toContain('exact earlier review is retained');
  vi.mocked(agentResearchApi.list).mockResolvedValue({contract: 'agent-research.history.v1', workspace_id: workspaceId,
    proposals: [{...proposal, state: 'approved', next_step: 'ask_research_to_execute'}]});
  await act(async () => button('Check saved query review').click());
  expect(agentResearchApi.approve).toHaveBeenCalledTimes(1); expect(saved).toBeNull();
});
it('refuses a recovered review for a different workspace or an extra authority field', () => {
  const pending = {ticket_id: proposal.ticket_id, revision_id: proposal.revision_id, payload_hash: proposal.payload_hash, public_query_confirmed: true};
  expect(() => validateAgentResearchRecovery({contract: 'agent-research-review-recovery.v1', workspace_id: uuid(9), pending}, workspaceId)).toThrow();
  expect(() => validateAgentResearchRecovery({contract: 'agent-research-review-recovery.v1', workspace_id: workspaceId,
    pending: {...pending, provider_url: 'https://untrusted.invalid'}}, workspaceId)).toThrow();
});
