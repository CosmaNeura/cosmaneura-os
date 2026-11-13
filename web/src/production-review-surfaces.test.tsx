import {StrictMode, act, createElement} from 'react';
import {createRoot, type Root} from 'react-dom/client';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {PRODUCTION_API_ORIGIN} from '../../clients/shared/operational-native-identity.mjs';
import {NativeAuthenticatedWorkspace} from './NativeAuthenticatedWorkspace';
import {SettingsHub} from './SettingsHub';
import {EhrReadProviders} from './EhrReadProviders';
import {VendorWorkPanel} from './VendorWorkPanel';
import {readinessLabels} from './TeamSetupPanel';
import {TEST_STAGE_PHRASES} from './production-review-copy';
import {readConnectionCatalog} from './connection-catalog-api';
import {readConnectionSummary} from './connection-summary';
import {readinessFixture} from './connection-readiness-fixture';
import {vendorApi} from './vendor-api';
import {actual, actualOptions} from './vendor-test-fixture';
import {validateVendor} from './vendor-contract';
import {emptyVendorRecovery} from './vendor-recovery';
import type {NativeAuthState} from './native-auth';
import {ehrVisit} from './ehr-read-fixtures.test-support';

vi.mock('./connection-catalog-api', async (original) => ({
  ...(await original<typeof import('./connection-catalog-api')>()),
  readConnectionCatalog: vi.fn(),
}));
vi.mock('./connection-summary', async (original) => ({
  ...(await original<typeof import('./connection-summary')>()),
  readConnectionSummary: vi.fn(),
}));
vi.mock('./EhrReadMount', () => ({EhrReadMount: () => <div className="ehr-read-panel">Check Elation access</div>}));
vi.mock('./TebraMedicationMount', () => ({TebraMedicationMount: () => <div className="ehr-read-panel">Tebra medications</div>}));
vi.mock('./AthenaAllergyMount', () => ({AthenaAllergyMount: () => <div className="ehr-read-panel">Athena allergies</div>}));
vi.mock('./AthenaMedicationMount', () => ({AthenaMedicationMount: () => <div className="ehr-read-panel">Athena medications</div>}));

const {webcrypto} = await vi.importActual<{webcrypto: Crypto}>('node:crypto');

function assertNoTestStage(text: string | null | undefined) {
  const body = text ?? '';
  for (const phrase of TEST_STAGE_PHRASES) {
    expect(body, `must not contain: ${phrase}`).not.toContain(phrase);
  }
}

describe('production-review surfaces', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    Object.assign(globalThis, {IS_REACT_ACT_ENVIRONMENT: true});
    vi.stubGlobal('crypto', webcrypto);
    vi.stubEnv('VITE_WORKSPACE_HOSTED_API_ORIGIN', PRODUCTION_API_ORIGIN);
    vi.stubEnv('VITE_COMING_SOON_CONNECTIONS_ENABLED', 'true');
    container = document.createElement('div');
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('NativeAuthenticatedWorkspace sign-in unavailable has no test-stage wording', async () => {
    const plugin = {
      getState: vi.fn(async () => ({phase: 'disabled', revision: '00000000-0000-4000-8000-000000000099', identity: null} as NativeAuthState)),
      getToken: vi.fn(async () => ({token: 'local.binding.fixture', revision: '00000000-0000-4000-8000-000000000099'})),
      signIn: vi.fn(async () => {}),
      signOut: vi.fn(async () => {}),
      addListener: vi.fn(async () => ({remove: async () => {}})),
    };
    await act(async () =>
      root.render(
        createElement(StrictMode, null, createElement(NativeAuthenticatedWorkspace, {plugin, available: false})),
      ),
    );
    assertNoTestStage(container.textContent);
    expect(container.textContent).toContain('could not start sign-in');
  });

  it('EhrReadProviders on production shows the neutral unavailable line (no empty Records tabs)', async () => {
    await act(async () =>
      root.render(
        <EhrReadProviders
          identity={{mode: 'clerk_jwt', getToken: async () => null}}
          enabled
          workspace={ehrVisit}
          onAuthenticationLost={vi.fn()}
        />,
      ),
    );
    expect(container.textContent).toContain('Practice records are not available in this release.');
    expect(container.querySelector('[aria-label="Records system"]')).toBeNull();
    expect(container.querySelector('summary')?.textContent).toBe('Saved work recovery');
    assertNoTestStage(container.textContent);
  });

  it('EhrReadProviders on staging still shows the full Records system panel', async () => {
    vi.stubEnv('VITE_WORKSPACE_HOSTED_API_ORIGIN', 'https://api.staging.cosmas.ai');
    await act(async () =>
      root.render(
        <EhrReadProviders
          identity={{mode: 'clerk_jwt', getToken: async () => null}}
          enabled
          workspace={ehrVisit}
          onAuthenticationLost={vi.fn()}
        />,
      ),
    );
    expect(container.querySelector('[aria-label="Records system"]')).toBeTruthy();
    expect(container.textContent).not.toContain('Practice records are not available in this release.');
  });

  it('SettingsHub native directory uses checkKind discoveryOnly on production and staging', async () => {
    for (const [origin, label] of [
      [PRODUCTION_API_ORIGIN, 'Not available'],
      ['https://api.staging.cosmas.ai', 'Coming soon'],
    ] as const) {
      vi.stubEnv('VITE_WORKSPACE_HOSTED_API_ORIGIN', origin);
      // Pass line 302 (not coming_soon) so discoveryOnly is the only filter that hides the card.
      vi.mocked(readConnectionCatalog).mockResolvedValue(readinessFixture({payments: 'user_connectable'}));
      vi.mocked(readConnectionSummary).mockResolvedValue({
        label,
        reason: 'No connection or request is started here.',
        action: 'No action',
        tone: 'neutral',
        checkKind: 'availability',
      });
      await act(async () =>
        root.render(
          <SettingsHub
            open
            nativePresentation="workspace"
            initialScreen="connections"
            guidedConnections
            connectionIdentity={{mode: 'clerk_jwt', getToken: async () => null}}
            team={<p>Team</p>}
            payments={<button>Connect Stripe</button>}
            portals={<button>Connect portal</button>}
            teamSummary="5 coworkers"
            teamDirty={false}
            onClose={() => {}}
          />,
        ),
      );
      const paymentsCard = [...container.querySelectorAll('button')].find((b) => b.textContent?.includes('Payments'));
      expect(paymentsCard, origin).toBeUndefined();
      await act(async () => root.unmount());
      root = createRoot(container);
    }
  });

  it('SettingsHub keeps Not available cards with Review-saved-work on production web', async () => {
    vi.mocked(readConnectionCatalog).mockResolvedValue(readinessFixture());
    vi.mocked(readConnectionSummary).mockResolvedValue({
      label: 'Not available',
      reason: 'Live payment collection is not available in this release.',
      action: 'No action',
      tone: 'neutral',
      checkKind: 'availability',
    });
    await act(async () =>
      root.render(
        <SettingsHub
          open
          initialScreen="connections"
          guidedConnections
          connectionIdentity={{mode: 'clerk_jwt', getToken: async () => null}}
          team={<p>Team</p>}
          payments={<button>Connect Stripe</button>}
          portals={<button>Connect portal</button>}
          teamSummary="5 coworkers"
          teamDirty={false}
          onClose={() => {}}
        />,
      ),
    );
    expect(container.querySelector('[aria-label="Not available"]')).toBeTruthy();
    expect(container.querySelector('[aria-label="Coming soon"]')).toBeNull();
    expect(container.textContent).toMatch(/Review saved (Payments|Patient portals) work/);
    assertNoTestStage(container.textContent);
  });

  it('VendorWorkPanel disabled delivery uses production wording without beta phrasing', async () => {
    const options = validateVendor('Options', {...actualOptions(), enabled: false});
    vi.spyOn(vendorApi, 'options').mockResolvedValue(options);
    vi.spyOn(vendorApi, 'catalog').mockResolvedValue(validateVendor('Catalog', actual.catalog));
    const scope = {kind: 'workspace' as const, id: options.workspace_id};
    let saved = emptyVendorRecovery(scope);
    await act(async () =>
      root.render(
        <VendorWorkPanel
          identity={{mode: 'clerk_jwt', getToken: async () => 'invented-test-token'}}
          workspaceId={options.workspace_id}
          recovery={{
            authorize: vi.fn(async () => {}),
            load: vi.fn(async () => saved),
            persist: vi.fn(async (value) => {
              saved = value;
            }),
          }}
        />,
      ),
    );
    for (let i = 0; i < 80; i++) {
      if (container.textContent?.includes('Vendor delivery is disabled')) break;
      await act(async () => {
        await new Promise((r) => setTimeout(r, 5));
      });
    }
    expect(container.textContent).toContain('Vendor delivery is disabled for this environment.');
    expect(container.textContent).not.toContain('this beta environment');
    assertNoTestStage(container.textContent);
  });

  it('TeamSetupPanel readinessLabels use production Unavailable without beta', () => {
    expect(readinessLabels({VITE_WORKSPACE_HOSTED_API_ORIGIN: PRODUCTION_API_ORIGIN}).unavailable_in_beta).toBe(
      'Unavailable',
    );
    expect(readinessLabels({VITE_WORKSPACE_HOSTED_API_ORIGIN: 'https://api.staging.cosmas.ai'}).unavailable_in_beta).toBe(
      'Unavailable in this beta',
    );
  });
});
