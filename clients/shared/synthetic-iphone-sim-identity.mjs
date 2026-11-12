/**
 * Test-only synthetic iPhone Simulator identity profile.
 *
 * Separate from the three operational profiles in
 * operational-native-identity.mjs (operational-beta-v1,
 * operational-staging-v1, operational-production-v1). Post-#354,
 * operational-beta-v1 admits clerk.cosmas.ai and clerk.staging.cosmas.ai.
 *
 * Accepts only *.synthetic.example origins with a pk_test_ placeholder that
 * encodes the invented host. No real Clerk keys, no live hosts.
 */
import {exactHostedOrigin} from './hosted-workspace-config.mjs';
import {
  OPERATIONAL_NATIVE_PROFILE,
  STAGING_NATIVE_PROFILE,
  PRODUCTION_NATIVE_PROFILE,
  validateOperationalNativeIdentity,
} from './operational-native-identity.mjs';

/** Distinct from every operational / live native identity profile. */
export const SYNTHETIC_IPHONE_SIM_PROFILE = 'synthetic-iphone-sim-v1';

const LIVE_PROFILES = Object.freeze([
  OPERATIONAL_NATIVE_PROFILE,
  STAGING_NATIVE_PROFILE,
  PRODUCTION_NATIVE_PROFILE,
]);

const fields = [
  'version', 'profile', 'client', 'apiOrigin', 'publishableKey',
  'frontendOrigin', 'organizationId', 'audience',
];

const unavailable = () => {
  throw new Error('Synthetic iPhone Simulator identity is incomplete or inconsistent');
};

function hostnameOf(origin) {
  return exactHostedOrigin(origin) ? new URL(origin).hostname : '';
}

function isSyntheticExampleHost(hostname) {
  return typeof hostname === 'string' && hostname.endsWith('.synthetic.example');
}

/** True when a profile string is one of the three operational/live profiles. */
export function isLiveOperationalNativeProfile(profile) {
  return LIVE_PROFILES.includes(profile);
}

/**
 * Validate a test-only synthetic-iphone-sim-v1 identity.
 * Never accepts operational-beta / staging / production profile names.
 */
export function validateSyntheticIphoneSimIdentity(value, client, apiOrigin) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) unavailable();
  if (Object.keys(value).length !== fields.length || fields.some(key => !Object.hasOwn(value, key))) {
    unavailable();
  }
  if (value.version !== 1 || value.profile !== SYNTHETIC_IPHONE_SIM_PROFILE) unavailable();
  if (isLiveOperationalNativeProfile(value.profile)) unavailable();
  if (!['apple', 'desktop'].includes(client) || value.client !== client) unavailable();
  if (value.apiOrigin !== apiOrigin || !exactHostedOrigin(apiOrigin)) unavailable();
  const frontendOrigin = exactHostedOrigin(value.frontendOrigin) ? value.frontendOrigin : '';
  if (!frontendOrigin) unavailable();
  const frontendHost = hostnameOf(frontendOrigin);
  const apiHost = hostnameOf(apiOrigin);
  if (!isSyntheticExampleHost(frontendHost) || !isSyntheticExampleHost(apiHost)) unavailable();
  if (!/^[a-z]/.test(frontendHost.split('.').at(-1))) unavailable();
  if (typeof value.publishableKey !== 'string' || value.publishableKey.length > 1024) unavailable();
  if (!value.publishableKey.startsWith('pk_test_')) unavailable();
  if (!/^[A-Za-z0-9+/_-]+={0,2}$/.test(value.publishableKey.slice('pk_test_'.length))) unavailable();
  if (typeof value.organizationId !== 'string'
      || !/^org_[A-Za-z0-9_]{1,251}$/.test(value.organizationId)) unavailable();
  // Staging-style empty audience for invented pk_test_ hosts.
  if (value.audience !== '') unavailable();
  try {
    const encoded = value.publishableKey.slice('pk_test_'.length)
      .replaceAll('-', '+').replaceAll('_', '/');
    if (atob(encoded) !== frontendHost + '$') unavailable();
  } catch {
    unavailable();
  }
  return Object.freeze({...value});
}

/**
 * Prove the operational validator never accepts the synthetic-iphone-sim-v1
 * profile name, and that dedicated beta/staging/production allow-lists refuse
 * *.synthetic.example. operational-beta-v1 admits only clerk.cosmas.ai and
 * clerk.staging.cosmas.ai (no open non-accounts.dev host rule).
 */
export function assertSyntheticProfileRefusedByLiveValidators({
  client = 'apple',
  apiOrigin = 'https://api.synthetic.example',
  frontendOrigin = 'https://clerk.synthetic.example',
  organizationId = 'org_synthetic_iphone_sim',
} = {}) {
  const hostname = new URL(frontendOrigin).hostname;
  const pkTest = 'pk_test_' + Buffer.from(hostname + '$').toString('base64');
  const pkLive = 'pk_live_' + Buffer.from(hostname + '$').toString('base64');

  // Synthetic profile name is unknown to the operational allow-list.
  try {
    validateOperationalNativeIdentity({
      version: 1,
      profile: SYNTHETIC_IPHONE_SIM_PROFILE,
      client,
      apiOrigin,
      publishableKey: pkTest,
      frontendOrigin,
      organizationId,
      audience: '',
    }, client, apiOrigin);
    throw new Error('operational validator must refuse synthetic-iphone-sim-v1');
  } catch (error) {
    if (!/incomplete or inconsistent/.test(String(error?.message || error))) throw error;
  }

  for (const profile of [
    OPERATIONAL_NATIVE_PROFILE, STAGING_NATIVE_PROFILE, PRODUCTION_NATIVE_PROFILE,
  ]) {
    const publishableKey = profile === STAGING_NATIVE_PROFILE ? pkTest : pkLive;
    const audience = profile === STAGING_NATIVE_PROFILE ? '' : 'cosmas-os-beta-api';
    try {
      validateOperationalNativeIdentity({
        version: 1,
        profile,
        client,
        apiOrigin,
        publishableKey,
        frontendOrigin,
        organizationId,
        audience,
      }, client, apiOrigin);
      throw new Error(`operational validator must refuse *.synthetic.example on ${profile}`);
    } catch (error) {
      if (!/incomplete or inconsistent/.test(String(error?.message || error))) throw error;
    }
  }

  // Live beta admits clerk.cosmas.ai / clerk.staging.cosmas.ai only; never synthetic-iphone-sim-v1.
  if (!LIVE_PROFILES.includes(OPERATIONAL_NATIVE_PROFILE)) {
    throw new Error('operational-beta-v1 missing from live profile set');
  }
}

/** Release / live selection must never return the synthetic simulator profile. */
export function assertSyntheticProfileNeverSelectedForRelease(selector) {
  if (typeof selector !== 'function') {
    throw new Error('Release selector must be a function');
  }
  for (const input of [
    {configuration: 'Release', bundleId: 'com.cosmasos.beta.ios'},
    {configuration: 'Release', bundleId: 'com.cosmasos.synthetic'},
    {configuration: 'Debug', bundleId: 'com.cosmasos.beta.ios'},
    {configuration: 'Release', profile: OPERATIONAL_NATIVE_PROFILE},
    {configuration: 'Release', profile: STAGING_NATIVE_PROFILE},
    {configuration: 'Release', profile: PRODUCTION_NATIVE_PROFILE},
  ]) {
    const selected = selector(input);
    if (selected === SYNTHETIC_IPHONE_SIM_PROFILE) {
      throw new Error(
        `synthetic-iphone-sim-v1 must never be selected for ${JSON.stringify(input)}`,
      );
    }
  }
}
