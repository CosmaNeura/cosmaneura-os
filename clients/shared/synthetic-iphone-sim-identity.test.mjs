import assert from 'node:assert/strict';
import test from 'node:test';
import {
  dedicatedClerkHostsByProfile,
  OPERATIONAL_NATIVE_PROFILE,
  STAGING_NATIVE_PROFILE,
  PRODUCTION_NATIVE_PROFILE,
  validateOperationalNativeIdentity,
} from './operational-native-identity.mjs';
import {
  SYNTHETIC_IPHONE_SIM_PROFILE,
  assertSyntheticProfileNeverSelectedForRelease,
  assertSyntheticProfileRefusedByLiveValidators,
  isLiveOperationalNativeProfile,
  validateSyntheticIphoneSimIdentity,
} from './synthetic-iphone-sim-identity.mjs';

/**
 * Dedicated Clerk hosts: operational-beta-v1 admits clerk.cosmas.ai and
 * clerk.staging.cosmas.ai (CTO DECISION_LOG 12 Nov 2026 10:12 ET). No open
 * non-accounts.dev host rule. clerk.beta.cosmas.ai stays production-only.
 */
const OPERATIONAL_HOSTS_AT_MAIN = Object.freeze({
  [OPERATIONAL_NATIVE_PROFILE]: Object.freeze(['clerk.cosmas.ai', 'clerk.staging.cosmas.ai']),
  [STAGING_NATIVE_PROFILE]: Object.freeze(['clerk.staging.cosmas.ai']),
  [PRODUCTION_NATIVE_PROFILE]: Object.freeze(['clerk.beta.cosmas.ai']),
});

function pkTestFor(host) {
  return 'pk_test_' + Buffer.from(host + '$').toString('base64');
}

function pkLiveFor(host) {
  return 'pk_live_' + Buffer.from(host + '$').toString('base64');
}

test('dedicatedClerkHostsByProfile pins operational-beta-v1 to clerk.cosmas.ai and clerk.staging.cosmas.ai', () => {
  assert.deepEqual(dedicatedClerkHostsByProfile(), OPERATIONAL_HOSTS_AT_MAIN);
  assert.deepEqual(
    dedicatedClerkHostsByProfile()[OPERATIONAL_NATIVE_PROFILE],
    ['clerk.cosmas.ai', 'clerk.staging.cosmas.ai'],
    'operational-beta-v1 admits clerk.cosmas.ai and clerk.staging.cosmas.ai (CTO 12 Nov 10:12 ET)',
  );
  assert.equal(isLiveOperationalNativeProfile(OPERATIONAL_NATIVE_PROFILE), true);
  assert.equal(isLiveOperationalNativeProfile(STAGING_NATIVE_PROFILE), true);
  assert.equal(isLiveOperationalNativeProfile(PRODUCTION_NATIVE_PROFILE), true);
  assert.equal(isLiveOperationalNativeProfile(SYNTHETIC_IPHONE_SIM_PROFILE), false);
});

test('three operational profiles still accept their dedicated hosts and refuse synthetic.example', () => {
  const production = {
    version: 1,
    profile: PRODUCTION_NATIVE_PROFILE,
    client: 'apple',
    apiOrigin: 'https://api.beta.cosmas.ai',
    frontendOrigin: 'https://clerk.beta.cosmas.ai',
    publishableKey: pkLiveFor('clerk.beta.cosmas.ai'),
    organizationId: 'org_invented_beta',
    audience: 'cosmas-os-beta-api',
  };
  assert.deepEqual(
    validateOperationalNativeIdentity(production, 'apple', production.apiOrigin),
    production,
  );

  const staging = {
    version: 1,
    profile: STAGING_NATIVE_PROFILE,
    client: 'apple',
    apiOrigin: 'https://api.staging.cosmas.ai',
    frontendOrigin: 'https://clerk.staging.cosmas.ai',
    publishableKey: pkLiveFor('clerk.staging.cosmas.ai'),
    organizationId: 'org_invented_beta',
    audience: 'cosmas-os-beta-api',
  };
  assert.deepEqual(
    validateOperationalNativeIdentity(staging, 'apple', staging.apiOrigin),
    staging,
  );

  const beta = {
    version: 1,
    profile: OPERATIONAL_NATIVE_PROFILE,
    client: 'apple',
    apiOrigin: 'https://api.example.invalid',
    frontendOrigin: 'https://clerk.cosmas.ai',
    publishableKey: pkLiveFor('clerk.cosmas.ai'),
    organizationId: 'org_invented_beta',
    audience: 'cosmas-os-beta-api',
  };
  assert.deepEqual(
    validateOperationalNativeIdentity(beta, 'apple', beta.apiOrigin),
    beta,
  );

  assert.throws(() => validateOperationalNativeIdentity({
    ...production,
    frontendOrigin: 'https://clerk.synthetic.example',
    publishableKey: pkLiveFor('clerk.synthetic.example'),
  }, 'apple', production.apiOrigin));

  assert.throws(() => validateOperationalNativeIdentity({
    ...staging,
    frontendOrigin: 'https://clerk.synthetic.example',
    publishableKey: pkTestFor('clerk.synthetic.example'),
    audience: '',
  }, 'apple', staging.apiOrigin));

  assert.throws(() => validateOperationalNativeIdentity({
    ...beta,
    frontendOrigin: 'https://clerk.synthetic.example',
    publishableKey: pkLiveFor('clerk.synthetic.example'),
  }, 'apple', beta.apiOrigin));
});

test('synthetic-iphone-sim-v1 accepts clerk.synthetic.example with pk_test_ placeholder', () => {
  const identity = validateSyntheticIphoneSimIdentity({
    version: 1,
    profile: SYNTHETIC_IPHONE_SIM_PROFILE,
    client: 'apple',
    apiOrigin: 'https://api.synthetic.example',
    frontendOrigin: 'https://clerk.synthetic.example',
    publishableKey: pkTestFor('clerk.synthetic.example'),
    organizationId: 'org_synthetic_iphone_sim',
    audience: '',
  }, 'apple', 'https://api.synthetic.example');
  assert.equal(identity.profile, SYNTHETIC_IPHONE_SIM_PROFILE);
  assert.match(identity.publishableKey, /^pk_test_/);
  assert.ok(identity.frontendOrigin.endsWith('.synthetic.example'));
});

test('synthetic profile is refused by live/operational validators', () => {
  assertSyntheticProfileRefusedByLiveValidators();
});

test('synthetic profile can never be selected by Release or live profiles', () => {
  assertSyntheticProfileNeverSelectedForRelease((input) => {
    // Live operational selection: Release and beta/staging/production never
    // return the test-only synthetic-iphone-sim profile.
    if (input.configuration === 'Release') return input.profile || OPERATIONAL_NATIVE_PROFILE;
    if (input.bundleId === 'com.cosmasos.beta.ios') return OPERATIONAL_NATIVE_PROFILE;
    if (input.profile && isLiveOperationalNativeProfile(input.profile)) return input.profile;
    // Debug synthetic bundle may opt into the test-only profile explicitly.
    if (input.configuration === 'Debug' && input.bundleId === 'com.cosmasos.synthetic') {
      return SYNTHETIC_IPHONE_SIM_PROFILE;
    }
    return OPERATIONAL_NATIVE_PROFILE;
  });
  assert.throws(() => assertSyntheticProfileNeverSelectedForRelease(() => SYNTHETIC_IPHONE_SIM_PROFILE));
});

test('synthetic validator refuses live profiles, live keys, and non-example hosts', () => {
  const base = {
    version: 1,
    profile: SYNTHETIC_IPHONE_SIM_PROFILE,
    client: 'apple',
    apiOrigin: 'https://api.synthetic.example',
    frontendOrigin: 'https://clerk.synthetic.example',
    publishableKey: pkTestFor('clerk.synthetic.example'),
    organizationId: 'org_synthetic_iphone_sim',
    audience: '',
  };
  assert.throws(() => validateSyntheticIphoneSimIdentity({
    ...base, profile: PRODUCTION_NATIVE_PROFILE,
  }, 'apple', base.apiOrigin));
  assert.throws(() => validateSyntheticIphoneSimIdentity({
    ...base, publishableKey: pkLiveFor('clerk.synthetic.example'),
  }, 'apple', base.apiOrigin));
  assert.throws(() => validateSyntheticIphoneSimIdentity({
    ...base,
    frontendOrigin: 'https://clerk.beta.cosmas.ai',
    publishableKey: pkTestFor('clerk.beta.cosmas.ai'),
  }, 'apple', base.apiOrigin));
  assert.throws(() => validateSyntheticIphoneSimIdentity({
    ...base, audience: 'cosmas-os-beta-api',
  }, 'apple', base.apiOrigin));
});
