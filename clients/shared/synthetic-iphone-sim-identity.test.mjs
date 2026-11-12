import assert from 'node:assert/strict';
import test from 'node:test';
import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
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

/** Frozen operational allow-lists at the #357 tip this branch started from. */
const OPERATIONAL_HOSTS_AT_MAIN = Object.freeze({
  [OPERATIONAL_NATIVE_PROFILE]: Object.freeze([]),
  [STAGING_NATIVE_PROFILE]: Object.freeze(['clerk.staging.cosmas.ai']),
  [PRODUCTION_NATIVE_PROFILE]: Object.freeze(['clerk.beta.cosmas.ai']),
});

/** SHA-256 of operational-native-identity.mjs at origin/main tip b95379ff. */
const OPERATIONAL_IDENTITY_SHA256_AT_MAIN =
  '3771a149d41036144dabde7fea2a53fb10764ac002a045f5450c7122b6548036';

function pkTestFor(host) {
  return 'pk_test_' + Buffer.from(host + '$').toString('base64');
}

function pkLiveFor(host) {
  return 'pk_live_' + Buffer.from(host + '$').toString('base64');
}

test('operational-native-identity.mjs stays byte-identical to main tip b95379ff', () => {
  const path = fileURLToPath(new URL('./operational-native-identity.mjs', import.meta.url));
  const raw = readFileSync(path);
  const digest = createHash('sha256').update(raw).digest('hex');
  assert.equal(
    digest,
    OPERATIONAL_IDENTITY_SHA256_AT_MAIN,
    'operational-native-identity.mjs must stay byte-identical to main (b95379ff)',
  );
  assert.deepEqual(dedicatedClerkHostsByProfile(), OPERATIONAL_HOSTS_AT_MAIN);
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
