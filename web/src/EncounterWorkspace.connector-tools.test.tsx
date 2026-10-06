/** Actual shell + DraftJournal, with controlled signed HTTP and component store. */
import {act} from 'react';
import {createRoot, type Root} from 'react-dom/client';
import {beforeEach, afterEach, expect, it, vi} from 'vitest';
import {memoryDraftStorage} from './draft-test-fixture';
import {EncounterWorkspace} from './EncounterWorkspace';
import {workspaceApi, type Workspace} from './workspace-api';
import {teamFixture, teamUuid as uuid} from './team-setup-test-fixture';
const {webcrypto} = await vi.importActual<{webcrypto: Crypto}>('node:crypto');
vi.hoisted(() => {vi.stubEnv('VITE_COSMAS_ENV', 'synth_os'); vi.stubEnv('VITE_WORKSPACE_ENABLED', 'true'); vi.stubEnv('VITE_WORKSPACE_AUTHENTICATED_ENABLED', 'true');});
vi.mock('./team-setup-api', async () => {const {WorkspaceApiError} = await import('./workspace-api'); return {teamSetupApi: {read: vi.fn().mockRejectedValue(new WorkspaceApiError(404))}};});
vi.mock('./draft-store', async original => ({...await original<typeof import('./draft-store')>(), privateDraftScope: async (s: string) => s}));
vi.mock('./workspace-api', async original => {const actual = await original<typeof import('./workspace-api')>(); return {...actual,
  workspaceApi: {...actual.workspaceApi, team: vi.fn(), catalog: vi.fn(), open: vi.fn(), read: vi.fn(), ask: vi.fn()}};});
vi.mock('./ResearchPanelLoader', () => ({ResearchPanelLoader: () => <p>Controlled public research boundary</p>}));
const identity = {mode: 'clerk_jwt' as const, getToken: async () => 'invented-signed-current-session'};
const baseTeam = teamFixture(), researchId = uuid(105);
baseTeam.configuration.bots.push({role: 'research', name: 'Research', instance_id: researchId, enabled: true,
  response_style: 'brief', include_notebook: true, include_evidence: true});
const team = teamFixture(baseTeam.configuration); team.capture = {enabled: false}; team.scheduling = {enabled: false};
let root: Root, host: HTMLDivElement, storage: ReturnType<typeof memoryDraftStorage>, approved: boolean, reads: number, approvals: unknown[], lostApproval: boolean;
const current: Workspace = {id: uuid(71), appointment_id: uuid(72), label: 'Invented connector review visit', revision: 1,
  entries: [], handoffs: [], work_candidates: [], model_contract_version: 1, model_observed_at: '2026-10-06T15:00:00Z'};
const row = () => ({contract: 'agent-research.review.v1', workspace_id: current.id, ticket_id: uuid(81), revision_id: uuid(82),
  payload_hash: 'b'.repeat(64), query: 'Evidence on dust exposure and cough in adults', topic: 'literature', sources: ['pubmed'],
  expires_at: '2099-10-06T17:00:00Z', bot: researchId, team_revision: team.revision, run_id: null,
  state: approved ? 'approved' : 'pending_approval', next_step: approved ? 'ask_research_to_execute' : 'review_query'});
const json = (v: unknown) => new Response(JSON.stringify(v), {headers: {'Content-Type': 'application/json', 'Cache-Control': 'no-store'}});
const visible = (e: Element) => !e.closest('[hidden]');
const button = (name: string) => [...host.querySelectorAll<HTMLButtonElement>('button')].find(e => visible(e) && (e.textContent?.trim() === name || e.getAttribute('aria-label') === name));
async function wait(check: () => void) {for (let i = 0; i < 200; i++) {let passed = false; await act(async () => {await new Promise(r => setTimeout(r, 2)); try {check(); passed = true;} catch {}}); if (passed) return;} check();}
async function click(name: string) {await wait(() => {expect(button(name), name).toBeTruthy(); expect(button(name)!.disabled, name).toBe(false);}); await act(async () => button(name)!.click());}
const mount = async () => {root = createRoot(host); await act(async () => root.render(<EncounterWorkspace authenticated={identity} draftStorage={storage}/>));};
const open = async () => {await click('Choose an encounter'); await wait(() => expect(host.querySelector('.team-encounter-option')).toBeTruthy());
  await act(async () => host.querySelector<HTMLButtonElement>('.team-encounter-option')!.click());
  await wait(() => expect([...host.querySelectorAll('.team-roster button')].find(e => e.querySelector('strong')?.textContent === 'Research')).toBeTruthy());
  await act(async () => [...host.querySelectorAll<HTMLButtonElement>('.team-roster button')].find(e => e.querySelector('strong')?.textContent === 'Research')!.click());};
beforeEach(async () => {vi.clearAllMocks(); vi.stubGlobal('crypto', webcrypto); vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); vi.stubEnv('VITE_API_BASE', 'http://127.0.0.1:8000');
  storage = memoryDraftStorage(); approved = false; reads = 0; approvals = []; lostApproval = false;
  vi.mocked(workspaceApi.team).mockResolvedValue(team); vi.mocked(workspaceApi.catalog).mockResolvedValue([{appointment_id: current.appointment_id, label: current.label, workspace_id: current.id}]);
  vi.mocked(workspaceApi.open).mockResolvedValue({identity, workspace: current, team}); vi.mocked(workspaceApi.read).mockResolvedValue(current);
  vi.stubGlobal('fetch', async (url: string, init: RequestInit) => {
    if (url.endsWith('/agent-research')) {reads++; return json({contract: 'agent-research.history.v1', workspace_id: current.id, proposals: [row()]});}
    if (url.endsWith('/review')) {approvals.push(JSON.parse(init.body as string)); approved = true;
      if (lostApproval) throw new TypeError('Lost response after synthetic commit'); return json(row());}
    throw new Error('No provider/model network allowed in this shell trial');
  }); host = document.createElement('div'); document.body.append(host); await mount();});
afterEach(async () => {await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals(); vi.unstubAllEnvs();});

it('reaches bot query review through the actual Research workspace, saves approval, and composes a later explicit request', async () => {
  await open(); await click('Load proposed queries'); expect(host.textContent).toContain('Evidence on dust exposure');
  expect(button('Approve public search')!.disabled).toBe(true);
  await act(async () => host.querySelector<HTMLInputElement>('[aria-label="Proposed public query"] input')!.click());
  await click('Approve public search'); expect(approvals).toEqual([{revision_id: uuid(82), payload_hash: 'b'.repeat(64), public_query_confirmed: true}]);
  await click('Ask Research about this approved query');
  expect(host.querySelector<HTMLTextAreaElement>('#team-question')!.value).toContain(uuid(82));
  expect(workspaceApi.ask).not.toHaveBeenCalled(); expect(reads).toBe(1);
  await act(async () => root.unmount()); await mount(); await open(); await click('Restore notebook draft'); await click('Load proposed queries');
  expect(host.textContent).toContain('approved'); expect(approvals).toHaveLength(1);
});
it('locks real workspace edits while approval is uncertain and recovers only through saved status', async () => {
  lostApproval = true; await open(); await click('Load proposed queries');
  await act(async () => host.querySelector<HTMLInputElement>('[aria-label="Proposed public query"] input')!.click());
  await click('Approve public search');
  await wait(() => expect(host.querySelector<HTMLTextAreaElement>('#team-question')!.disabled).toBe(true));
  expect(host.querySelector<HTMLTextAreaElement>('#team-notebook')!.disabled).toBe(true);
  expect(button('Team settings')!.disabled).toBe(true);
  expect([...host.querySelectorAll<HTMLButtonElement>('.team-roster button')].every(e => e.disabled)).toBe(true);
  await click('Check saved query review'); expect(approvals).toHaveLength(1);
  await wait(() => expect(host.querySelector<HTMLTextAreaElement>('#team-question')!.disabled).toBe(false));
});
