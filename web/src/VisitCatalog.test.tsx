import {act} from 'react';
import {createRoot, type Root} from 'react-dom/client';
import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import {VISIT_CATALOG_VIEWS, VisitCatalog} from './VisitCatalog';
import {workspaceApi, type AuthenticatedWorkspaceIdentity, type WorkspaceEncounter} from './workspace-api';

const {readFileSync}=await vi.importActual<{readFileSync:(path:string,encoding:'utf8')=>string}>('node:fs');
const {fileURLToPath}=await vi.importActual<{fileURLToPath:(url:string)=>string}>('node:url');

vi.mock('./workspace-api', async original => {
  const mod = await original<typeof import('./workspace-api')>();
  return {...mod, workspaceApi: {...mod.workspaceApi, privateDraftSummaries: vi.fn()}};
});

const identity = {mode: 'clerk_jwt', getToken: async () => 'invented.token.value'} as AuthenticatedWorkspaceIdentity;
const visits: WorkspaceEncounter[] = [
  {appointment_id: 'invented-visit-1', label: 'Invented Jordan Café', start_at: '2026-10-28T15:00:00.000Z', source: 'synthetic', workspace_id: null},
];

let host: HTMLDivElement, root: Root;

beforeEach(() => {
  Object.assign(globalThis, {IS_REACT_ACT_ENVIRONMENT: true});
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
  vi.mocked(workspaceApi.privateDraftSummaries).mockResolvedValue({contract_version: 2, drafts: [], has_more: false});
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

async function mount() {
  await act(async () => root.render(
    <VisitCatalog
      identity={identity}
      visits={visits}
      locked={false}
      recordingActive={false}
      onOpen={() => {}}
      onPrivateNote={() => {}}
      onConnections={() => {}}
    />,
  ));
}

it('keeps visit views as a single-line scrollable tab strip with ≥14px type', async () => {
  await mount();
  const tabs = host.querySelector('.visit-catalog-tabs')!;
  expect([...tabs.querySelectorAll('button')].map(button => button.textContent)).toEqual([...VISIT_CATALOG_VIEWS]);
  expect(host.querySelector('.team-encounter-picker')).toBeTruthy();
  expect(host.textContent).toContain('Invented Jordan Café');

  const css = readFileSync(fileURLToPath(import.meta.url).replace(/[^/]+$/, 'visit-catalog.css'), 'utf8');
  expect(css).toContain('.visit-catalog-tabs');
  expect(css).toContain('flex-wrap: nowrap');
  expect(css).toContain('overflow-x: auto');
  expect(css).toContain('white-space: nowrap');
  expect(css).toContain('font-size: 14px');
  expect(css).toContain('@media (max-width: 360px)');
  expect(css).toMatch(/\.team-encounter-picker\s*\{[^}]*font-size:\s*14px/);
});

it('switches the Unlinked notes view without leaving the catalog', async () => {
  await mount();
  const tabs = host.querySelector('.visit-catalog-tabs')!;
  await act(async () => (tabs.querySelector('button:last-child') as HTMLButtonElement).click());
  expect(workspaceApi.privateDraftSummaries).toHaveBeenCalledWith(identity);
  expect(host.textContent).toContain('No unlinked notes yet.');
});
