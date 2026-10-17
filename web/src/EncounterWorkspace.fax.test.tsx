import {act} from 'react';
import {createRoot, type Root} from 'react-dom/client';
import {afterAll, afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {EncounterWorkspace} from './EncounterWorkspace';
import {readConnectionCatalog} from './connection-catalog-api';
import {faxConnectionSummary, readConnectionSummary} from './connection-summary';
import {memoryDraftStorage} from './draft-test-fixture';
import type {FaxReadiness} from './fax-readiness-api';
import {settingsNavigation} from './settings-test-navigation';
import {teamSetupApi} from './team-setup-api';
import {vendorApi} from './vendor-api';
import {vendorSetupApi} from './vendor-setup-api';
import {setupFixture} from './vendor-setup-test-fixture';
import {actualOptions} from './vendor-test-fixture';
import {workspaceApi, WorkspaceApiError, type ProviderTeam, type Workspace} from './workspace-api';

// Enable the actual setup mount as well as its Settings entry. Navigation,
// recording placeholder, recovery, and both fax surfaces remain real components.
vi.hoisted(() => vi.stubEnv('VITE_VENDOR_SETUP_ENABLED', 'true'));
vi.mock('./draft-store', async original => ({
  ...await original<typeof import('./draft-store')>(), privateDraftScope: async (scope: string) => scope,
}));
vi.mock('./connection-catalog-api', async original => ({
  ...await original<typeof import('./connection-catalog-api')>(), readConnectionCatalog: vi.fn(),
}));
vi.mock('./connection-summary', async original => ({
  ...await original<typeof import('./connection-summary')>(), readConnectionSummary: vi.fn(),
}));
const {webcrypto} = await vi.importActual<{webcrypto: Crypto}>('node:crypto');
const identity = {mode: 'clerk_jwt' as const, getToken: async () => null};
const workspace: Workspace & {appointment_id:string} = {
  id: '00000000-0000-4000-8000-000000000071', appointment_id: 'invented-fax-visit',
  label: 'Invented fax visit', revision: 1, entries: [], work_candidates: [],
};
const roles = ['scribe', 'visit_prep', 'follow_up', 'chief'] as const;
const names = ['Scribe', 'Visit Prep', 'Follow-up', 'Chief'];
const team: ProviderTeam = {
  revision: 1, recovery_scope: 'a'.repeat(64), template_version: 'provider-team-v1',
  llm: {enabled: false, model: 'gpt-4.1'},
  configuration: {practice_context: 'DPC', bots: roles.map((role, index) => ({
    role, name: names[index], enabled: true, response_style: 'brief', include_notebook: true, include_evidence: true,
  }))},
  members: roles.map((role, index) => ({
    role, agent_id: `invented-${role}`, name: names[index], initials: names[index].slice(0, 2),
    description: 'Invented teammate', prompt: 'Review saved context', capabilities: [],
  })),
};
const ready: FaxReadiness = {
  contract_version: 1,
  scope: {box_id: '00000000-0000-4000-8000-000000000001', owner_id: '00000000-0000-4000-8000-000000000002'},
  enabled: true, work_enabled: true, delivery_enabled: true,
  credential_access_configured: true, document_storage_configured: true,
  providers: (['spruce', 'srfax', 'documo', 'efax'] as const).map(id => ({
    id, installed_accounts: id === 'efax' ? 1 : 0, active_accounts: id === 'efax' ? 1 : 0,
    prepare_enabled_accounts: id === 'efax' ? 1 : 0, review_required_accounts: 0, unavailable_accounts: 0,
  })),
};

describe('Settings fax navigation in an encounter', () => {
  let host: HTMLDivElement, root: Root, scroll: ReturnType<typeof vi.fn>;
  const originalScroll = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollIntoView');

  beforeEach(async () => {
    Object.assign(globalThis, {IS_REACT_ACT_ENVIRONMENT: true});
    vi.stubGlobal('crypto', webcrypto);
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Unexpected HTTP in navigation test')));
    scroll = vi.fn();
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {configurable: true, value: scroll});
    vi.spyOn(workspaceApi, 'privateDraftSummaries').mockResolvedValue({contract_version:2,drafts:[],has_more:false});
    vi.spyOn(workspaceApi, 'catalog').mockResolvedValue([{
      appointment_id: workspace.appointment_id, workspace_id: workspace.id, label: workspace.label,
    }]);
    vi.spyOn(workspaceApi, 'open').mockImplementation(async () => ({
      identity, workspace: structuredClone(workspace), team: structuredClone(team),
    }));
    vi.spyOn(workspaceApi, 'team').mockResolvedValue(structuredClone(team));
    vi.spyOn(workspaceApi, 'read').mockResolvedValue(structuredClone(workspace));
    vi.spyOn(workspaceApi, 'ask');
    vi.spyOn(workspaceApi, 'append');
    vi.spyOn(workspaceApi, 'saveTeam');
    vi.spyOn(teamSetupApi, 'read').mockRejectedValue(new WorkspaceApiError(404));
    vi.mocked(readConnectionCatalog).mockResolvedValue({
      core: false, google: false, microsoft: false, scheduling: false, messaging: true, payments: false, portals: false,
    });
    vi.mocked(readConnectionSummary).mockResolvedValue(faxConnectionSummary(ready));
    vi.spyOn(vendorSetupApi, 'catalog').mockResolvedValue((await setupFixture()).emptyCatalog);
    vi.spyOn(vendorSetupApi, 'command');
    vi.spyOn(vendorApi, 'options').mockResolvedValue({...actualOptions(), workspace_id: workspace.id});
    vi.spyOn(vendorApi, 'catalog').mockResolvedValue({
      contract_version: 1, workspace_id: workspace.id, items: [], next_cursor: null,
      observed_at: '2026-10-01T12:00:00.000000Z',
    });
    vi.spyOn(vendorApi, 'execute');
    host = document.createElement('div'); document.body.append(host); root = createRoot(host);
    await act(async () => root.render(<EncounterWorkspace authenticated={identity} draftStorage={memoryDraftStorage()}/>));
  });

  afterEach(async () => {
    await act(async () => root?.unmount()); host?.remove();
    if (originalScroll) Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', originalScroll);
    else delete (HTMLElement.prototype as {scrollIntoView?: unknown}).scrollIntoView;
    vi.restoreAllMocks(); vi.clearAllMocks(); vi.unstubAllGlobals();
  });
  afterAll(() => vi.unstubAllEnvs());

  async function click(name: string) {
    const button = [...host.querySelectorAll<HTMLButtonElement>('button')].find(element =>
      !element.closest('[hidden]') && (element.textContent?.trim() === name || element.getAttribute('aria-label') === name));
    expect(button, `Visible button: ${name}`).toBeTruthy();
    expect(button!.matches(':disabled'), `Enabled button: ${name}`).toBe(false);
    await act(async () => button!.click());
  }

  async function chooseVisit() {
    const option = host.querySelector<HTMLButtonElement>('.team-encounter-option');
    expect(option?.textContent).toContain(workspace.label);
    await act(async () => option!.click());
  }

  async function openFaxSettings() {
    const settings = settingsNavigation(host);
    await settings.click('Team settings');
    await settings.click('Connections');
    await settings.click('Messaging & fax');
    expect(host.querySelector('.fax-connection-overview')?.textContent).toContain('An account is available for preparing a fax draft.');
  }

  function expectFaxDestination() {
    const target = host.querySelector<HTMLElement>('[aria-label="Messaging and fax work"]');
    expect(target).not.toBeNull();
    expect(target!.closest('[hidden]')).toBeNull();
    expect(target!.querySelector('[aria-label="Private vendor delivery"]')).not.toBeNull();
    expect(host.querySelector('.team-content')?.getAttribute('data-mobile-panel')).toBe('Work');
    expect(host.querySelector('.settings-hub')?.hasAttribute('hidden')).toBe(true);
    expect(document.activeElement).toBe(target);
    expect(scroll.mock.contexts.at(-1)).toBe(target);
    expect(scroll.mock.contexts.filter(element => element === target)).toHaveLength(1);
    expect(scroll.mock.contexts.some(element => (element as HTMLElement).getAttribute('aria-label') === 'Scribe recording')).toBe(false);
    expect(workspaceApi.ask).not.toHaveBeenCalled();
    expect(workspaceApi.append).not.toHaveBeenCalled();
    expect(workspaceApi.saveTeam).not.toHaveBeenCalled();
    expect(vendorApi.execute).not.toHaveBeenCalled();
    expect(vendorSetupApi.command).not.toHaveBeenCalled();
    expect(fetch).not.toHaveBeenCalled();
  }

  it('keeps fax work as the final focus and scroll destination when leaving Settings with Scribe selected', async () => {
    await click('Visits and notes'); await chooseVisit();
    const scribe = [...host.querySelectorAll<HTMLButtonElement>('.team-roster button')]
      .find(button => button.querySelector('strong')?.textContent === 'Scribe')!;
    await act(async () => scribe.click());
    const recording = host.querySelector('[aria-label="Scribe recording"]');
    expect(recording).not.toBeNull();
    expect(scroll.mock.contexts.at(-1)).toBe(recording);
    await openFaxSettings();
    scroll.mockClear();
    await click('Open fax work for this visit');
    // act includes the follow-up render that clears completed fax focus. A
    // recording effect triggered by that cleanup must not reclaim scrolling.
    expect(host.querySelector('.team-roster [aria-pressed="true"] strong')?.textContent).toBe('Scribe');
    expectFaxDestination();
    expect(workspaceApi.open).toHaveBeenCalledExactlyOnceWith(identity, workspace.appointment_id);
  });

  it('chooses a visit before opening fax work when Settings was opened from the dashboard', async () => {
    await openFaxSettings();
    await click('Choose a visit for fax work');
    expect(host.querySelector('.team-welcome h1')?.textContent).toBe('Choose a visit for fax work');
    expect(host.querySelector('.team-encounter-option')?.textContent).toContain('Open saved notes');
    expect(host.querySelector('[aria-label="Messaging and fax work"]')).toBeNull();
    expect(workspaceApi.open).not.toHaveBeenCalled();
    scroll.mockClear(); await chooseVisit();
    expectFaxDestination();
    expect(workspaceApi.open).toHaveBeenCalledExactlyOnceWith(identity, workspace.appointment_id);
  });
});
