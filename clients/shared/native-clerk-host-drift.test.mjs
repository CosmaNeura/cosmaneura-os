import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {dedicatedClerkHostsByProfile, OPERATIONAL_NATIVE_PROFILE, STAGING_NATIVE_PROFILE,
  PRODUCTION_NATIVE_PROFILE} from './operational-native-identity.mjs';

const SWIFT_PATH = fileURLToPath(new URL(
  '../apple/native-auth/Sources/CosmasNativeAuth/NativeClerkConfiguration.swift', import.meta.url));

/**
 * Named Swift↔JS host-map differences. Staging behaviour is unchanged this PR.
 *
 * What the staging exception allows (JS only):
 * - operational-staging-v1 + dedicated host clerk.staging.cosmas.ai + pk_live_
 *   encoding that host + non-empty audience.
 * - operational-staging-v1 + strict *.clerk.accounts.dev host + pk_test_
 *   encoding that host + empty audience.
 *
 * What it does not allow:
 * - Production Clerk/API hosts (clerk.beta.cosmas.ai / api.beta.cosmas.ai) on staging.
 * - Live clerk.cosmas.ai on staging.
 * - Swift operationalStaging dedicated clerk.staging.cosmas.ai (Swift allow-list is
 *   empty; Swift admits only the accounts.dev path for operationalStaging).
 * - pk_test_ on the dedicated staging host, or pk_live_ on accounts.dev.
 */
export const INTENTIONAL_CLERK_HOST_DRIFT = Object.freeze([
  Object.freeze({
    profile: OPERATIONAL_NATIVE_PROFILE,
    swift: Object.freeze(['clerk.cosmas.ai']),
    js: Object.freeze(['clerk.cosmas.ai', 'clerk.staging.cosmas.ai']),
    reason: 'CTO DECISION_LOG 12 Nov 2026 10:12 ET: JS/Python operational-beta-v1 admits '
      + 'clerk.cosmas.ai and clerk.staging.cosmas.ai for shipped TestFlight 1107/1110/1120 '
      + 'and synthetic Mac 1120. Swift still pins clerk.cosmas.ai only on this branch; '
      + 'a separate Swift PR will align. PENDING_SWIFT_PR — do not treat as silent skip.',
  }),
  Object.freeze({
    profile: STAGING_NATIVE_PROFILE,
    swift: Object.freeze([]),
    js: Object.freeze(['clerk.staging.cosmas.ai']),
    reason: 'JS operational-staging-v1 allows dedicated clerk.staging.cosmas.ai with '
      + 'pk_live_ (and separately allows strict *.clerk.accounts.dev with pk_test_). '
      + 'Swift operationalStaging has an empty dedicated allow-list and admits only the '
      + 'accounts.dev path. Named filming-hold exception; owner decision pending. '
      + 'Production-review hosts are not part of this exception.',
  }),
]);

export function extractSwiftAllowedClerkHosts(source) {
  const cases = {};
  const enumMatch = source.match(/public enum NativeIdentityProfile:[^{]+\{([\s\S]*?)\n\}/);
  assert.ok(enumMatch, 'NativeIdentityProfile enum missing');
  const body = enumMatch[1];
  for (const match of body.matchAll(/case\s+(\w+)\s*=\s*"([^"]+)"/g)) {
    cases[match[1]] = match[2];
  }
  const switchMatch = body.match(/public var allowedClerkHosts:\s*Set<String>\s*\{([\s\S]*?)\n    \}/);
  assert.ok(switchMatch, 'allowedClerkHosts switch missing');
  const hostsByProfile = {};
  for (const raw of Object.values(cases)) hostsByProfile[raw] = [];
  const switchBody = switchMatch[1];
  for (const arm of switchBody.matchAll(/case\s+([\w\s,.]+):\s*\n\s*return\s+(\[[^\]]*\]|\[\])/g)) {
    const hosts = [...arm[2].matchAll(/"([^"]+)"/g)].map(item => item[1]).sort();
    for (const name of arm[1].split(',').map(part => part.trim().replace(/^\./, ''))) {
      const raw = cases[name];
      assert.ok(raw, `unknown profile case ${name}`);
      hostsByProfile[raw] = hosts;
    }
  }
  return hostsByProfile;
}

export function assertSwiftJsClerkHostsAligned(swiftHosts, jsHosts, exceptions = INTENTIONAL_CLERK_HOST_DRIFT) {
  const shared = [OPERATIONAL_NATIVE_PROFILE, STAGING_NATIVE_PROFILE, PRODUCTION_NATIVE_PROFILE];
  const exceptionByProfile = Object.fromEntries(exceptions.map(item => [item.profile, item]));
  for (const profile of shared) {
    const swift = [...(swiftHosts[profile] || [])].sort();
    const js = [...(jsHosts[profile] || [])].sort();
    const planned = exceptionByProfile[profile];
    if (planned) {
      assert.deepEqual(swift, [...planned.swift].sort(), `${profile} swift exception drift`);
      assert.deepEqual(js, [...planned.js].sort(), `${profile} js exception drift`);
      continue;
    }
    assert.deepEqual(swift, js, `${profile} Swift/JS Clerk host allow-list mismatch`);
  }
}

test('shared profile Clerk hosts match Swift allow-list except named exceptions', () => {
  const source = readFileSync(SWIFT_PATH, 'utf8');
  const swiftHosts = extractSwiftAllowedClerkHosts(source);
  const jsHosts = dedicatedClerkHostsByProfile();
  assertSwiftJsClerkHostsAligned(swiftHosts, jsHosts);
  // PENDING_SWIFT_PR: Swift still clerk.cosmas.ai only; JS includes staging for shipped builds.
  assert.deepEqual(swiftHosts[OPERATIONAL_NATIVE_PROFILE], ['clerk.cosmas.ai']);
  assert.deepEqual(jsHosts[OPERATIONAL_NATIVE_PROFILE], ['clerk.cosmas.ai', 'clerk.staging.cosmas.ai']);
  assert.deepEqual(swiftHosts[PRODUCTION_NATIVE_PROFILE], ['clerk.beta.cosmas.ai']);
  assert.deepEqual(jsHosts[PRODUCTION_NATIVE_PROFILE], ['clerk.beta.cosmas.ai']);
  assert.equal(INTENTIONAL_CLERK_HOST_DRIFT.some(item => item.profile === OPERATIONAL_NATIVE_PROFILE), true);
  assert.match(
    INTENTIONAL_CLERK_HOST_DRIFT.find(item => item.profile === OPERATIONAL_NATIVE_PROFILE).reason,
    /PENDING_SWIFT_PR/);
});

test('Clerk host drift detector fails when either side is mutated', () => {
  const source = readFileSync(SWIFT_PATH, 'utf8');
  const swiftHosts = extractSwiftAllowedClerkHosts(source);
  const jsHosts = dedicatedClerkHostsByProfile();
  assert.throws(() => assertSwiftJsClerkHostsAligned(
    {...swiftHosts, [PRODUCTION_NATIVE_PROFILE]: ['clerk.evil.example']}, jsHosts));
  assert.throws(() => assertSwiftJsClerkHostsAligned(
    swiftHosts, {...jsHosts, [PRODUCTION_NATIVE_PROFILE]: ['clerk.evil.example']}));
  assert.throws(() => assertSwiftJsClerkHostsAligned(
    {...swiftHosts, [OPERATIONAL_NATIVE_PROFILE]: ['clerk.evil.example']}, jsHosts));
  assert.throws(() => assertSwiftJsClerkHostsAligned(
    swiftHosts, {...jsHosts, [OPERATIONAL_NATIVE_PROFILE]: []}));
  // Clearing the staging exception without aligning either map must fail.
  assert.throws(() => assertSwiftJsClerkHostsAligned(swiftHosts, jsHosts, []));
});
