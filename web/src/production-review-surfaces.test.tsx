import {StrictMode, act, createElement} from 'react';
import {createRoot, type Root} from 'react-dom/client';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {PRODUCTION_API_ORIGIN} from '../../clients/shared/operational-native-identity.mjs';
import {NativeAuthenticatedWorkspace} from './NativeAuthenticatedWorkspace';
import {SettingsHub} from './SettingsHub';
import {AthenaAllergyPanel} from './AthenaAllergyPanel';
import {VendorWorkPanel} from './VendorWorkPanel';
import {readinessLabels} from './TeamSetupPanel';
import {TEST_STAGE_PHRASES} from './production-review-copy';
import {readConnectionCatalog} from './connection-catalog-api';
import {readConnectionSummary} from './connection-summary';
import {readinessFixture} from './connection-readiness-fixture';
import {athenaAllergyApi, ATHENA_CORE} from './athena-allergy-api';
import {athenaFixtureBinding, athenaFixtureScope} from '../ux-acceptance/athena-allergy-fixtures';
import {vendorApi} from './vendor-api';
import {actual, actualOptions} from './vendor-test-fixture';
import {validateVendor} from './vendor-contract';
import {emptyVendorRecovery} from './vendor-recovery';
import type {NativeAuthState} from './native-auth';

vi.mock('./connection-catalog-api', async (original) => ({
  ...(await original<typeof import('./connection-catalog-api')>()),
  readConnectionCatalog: vi.fn(),
}));
vi.mock('./connection-summary', async (original) => ({
  ...(await original<typeof import('./connection-summary')>()),
  readConnectionSummary: vi.fn(),
}));

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

  it('SettingsHub force-hides coming-soon cards and keeps discovery keyed off checkKind', async () => {
    vi.mocked(readConnectionCatalog).mockResolvedValue(readinessFixture());
    vi.mocked(readConnectionSummary).mockResolvedValue({
      label: 'Needs setup',
      reason: 'Sign in to connect your account.',
      action: 'Connect account',
      tone: 'attention',
      checkKind: 'account',
    });
    await act(async () =>
      root.render(
        <SettingsHub
          open
          initialScreen="connections"
          guidedConnections
          connectionIdentity={{mode: 'clerk_jwt', getToken: async () => null}}
          team={<p>Team</p>}
          portals={<button>Connect portal</button>}
          payments={<button>Connect Stripe</button>}
          teamSummary="5 coworkers"
          teamDirty={false}
          onClose={() => {}}
        />,
      ),
    );
    expect(container.querySelector('[aria-label="Coming soon"]')).toBeNull();
    expect(container.querySelector('[aria-label="Not available"]')).toBeNull();
    assertNoTestStage(container.textContent);
  });

  it('Athena allergy panel with mock/synthetic transport is hidden on production', async () => {
    vi.spyOn(athenaAllergyApi, 'status').mockResolvedValue({
      contract_version: 1,
      ...ATHENA_CORE,
      mode: 'synthetic',
      transport: 'mock',
      status: 'ready',
      ...athenaFixtureBinding,
      practice_label: 'Invented clinical connection',
    });
    await act(async () =>
      root.render(
        <AthenaAllergyPanel
          identity={{mode: 'clerk_jwt', getToken: vi.fn()}}
          scope={athenaFixtureScope}
          workspace={{id: athenaFixtureScope.workspace_id, label: 'Invented visit', revision: 5}}
          recovery={{
            authorize: vi.fn(async () => {}),
            load: vi.fn(async () => null),
            persist: vi.fn(async () => {}),
          }}
          onAuthenticationLost={vi.fn()}
        />,
      ),
    );
    expect(container.querySelector('.ehr-read-panel')).toBeNull();
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
