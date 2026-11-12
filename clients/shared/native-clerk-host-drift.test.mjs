import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {dedicatedClerkHostsByProfile, OPERATIONAL_NATIVE_PROFILE, STAGING_NATIVE_PROFILE,
  PRODUCTION_NATIVE_PROFILE} from './operational-native-identity.mjs';

const SWIFT_PATH = fileURLToPath(new URL(
  '../apple/native-auth/Sources/CosmasNativeAuth/NativeClerkConfiguration.swift', import.meta.url));

/** Named Swift↔JS host-map differences. Staging behaviour is unchanged this PR. */
export const INTENTIONAL_CLERK_HOST_DRIFT = Object.freeze([
  Object.freeze({
    profile: STAGING_NATIVE_PROFILE,
    swift: Object.freeze([]),
    js: Object.freeze(['clerk.staging.cosmas.ai']),
    reason: 'JS operational-staging-v1 accepts dedicated clerk.staging.cosmas.ai with pk_live_; '
      + 'Swift operationalStaging has an empty allow-list and refuses it. Unchanged this PR. '
      + 'Named exception approved by CTO (decision B, 11 Nov 2026). Follow-up after #354: '
      + 'invented-host-input.json beta identity becomes clerk.cosmas.ai, goldens regenerated, JS beta pinned.',
  }),
  Object.freeze({
    profile: OPERATIONAL_NATIVE_PROFILE,
    swift: Object.freeze(['clerk.cosmas.ai', 'clerk.staging.cosmas.ai']),
    js: Object.freeze([]),
    reason: 'Swift operational-beta-v1 admits clerk.cosmas.ai and clerk.staging.cosmas.ai; '
      + 'JS still has an empty dedicated allow-list for that profile. Exact named exception; '
      + 'JS side unchanged this PR.',
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
  assert.deepEqual(swiftHosts[PRODUCTION_NATIVE_PROFILE], ['clerk.beta.cosmas.ai']);
  assert.deepEqual(jsHosts[PRODUCTION_NATIVE_PROFILE], ['clerk.beta.cosmas.ai']);
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
  // Clearing a named exception without updating either map must fail.
  assert.throws(() => assertSwiftJsClerkHostsAligned(swiftHosts, jsHosts, []));
});
