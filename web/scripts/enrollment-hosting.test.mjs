// @vitest-environment node
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
const {test} = await import(process.env.VITEST ? 'vitest' : 'node:test');
import { resolveEnrollmentBuild } from './enrollment-build-config.mjs';
import { renderEnrollmentNginx } from './render-enrollment-nginx.mjs';
const sample = () => ({ VITE_ENROLLMENT_ENABLED: 'true', VITE_ENROLLMENT_ACCOUNT_ONLY: 'true',
  VITE_ENROLLMENT_ACCOUNT_ORIGIN: 'https://onboarding.staging.cosmas.ai',
  VITE_ENROLLMENT_API_BASE: 'https://enrollment-api.staging.cosmas.ai',
  VITE_ENROLLMENT_CLERK_ISSUER: 'https://invented-clinic.clerk.accounts.dev',
  VITE_ENROLLMENT_CLERK_PUBLISHABLE_KEY: `pk_test_${Buffer.from('invented-clinic.clerk.accounts.dev$').toString('base64')}`,
  VITE_BUILD_SHA: '1'.repeat(40) });

test('the account image binds the fixed separate host/API and matching Development Clerk', () => {
  const manifest = resolveEnrollmentBuild(sample());
  assert.equal(manifest.kind, 'enrollment-account');
  assert.equal(manifest.account_only, true);
  assert.equal(manifest.clinical_workspace, false);
  assert.equal(manifest.application_origin, sample().VITE_ENROLLMENT_ACCOUNT_ORIGIN);
  assert.equal(manifest.source_commit, '1'.repeat(40));
});
test('foreign, beta, production and mixed account/workspace build bindings fail closed', () => {
  for (const patch of [
    { VITE_ENROLLMENT_ACCOUNT_ONLY: 'false' }, { VITE_ENROLLMENT_ENABLED: 'false' },
    { VITE_ENROLLMENT_ACCOUNT_ORIGIN: 'https://staging.cosmas.ai' },
    { VITE_ENROLLMENT_ACCOUNT_ORIGIN: 'https://onboarding.staging.cosmas.ai.evil.example' },
    { VITE_ENROLLMENT_API_BASE: 'https://enrollment-api.cosmas.ai' },
    { VITE_ENROLLMENT_CLERK_ISSUER: 'https://invented-clinic.clerk.accounts.dev/unexpected' },
    { VITE_ENROLLMENT_CLERK_PUBLISHABLE_KEY: `pk_test_${Buffer.from('other.clerk.accounts.dev$').toString('base64')}` },
    { VITE_CLERK_PUBLISHABLE_KEY: 'beta-key' }, { VITE_WORKSPACE_FEATURE_PROFILE: 'operational-beta-v1' },
    { VITE_WORKSPACE_HOSTED_API_ORIGIN: 'https://api.staging.cosmas.ai' }, { VITE_BUILD_SHA: 'short' },
    { VITE_COSMAS_ENV: 'synth_os', VITE_WORKSPACE_ENABLED: 'true', VITE_API_BASE: 'https://api.staging.cosmas.ai' },
    { VITE_WORKSPACE_NATIVE_AUTH_ENABLED: 'true' }, { VITE_CORE_CONNECTION_ENABLED: 'true' },
  ]) assert.throws(() => resolveEnrollmentBuild({ ...sample(), ...patch }));
});
test('account hosting retains all SPA routes and denies microphone/payment permissions', async () => {
  const template = await readFile(new URL('../nginx.conf', import.meta.url), 'utf8');
  assert.equal(renderEnrollmentNginx(template, resolveEnrollmentBuild(sample())), template);
  assert.throws(() => renderEnrollmentNginx(template.replace('microphone=()', 'microphone=(self)'), resolveEnrollmentBuild(sample())));
  assert.throws(() => renderEnrollmentNginx(template, { ...resolveEnrollmentBuild(sample()), account_only: false }));
});
test('Dockerfile preserves the default beta path and explicitly selects account builds', async () => {
  const docker = await readFile(new URL('../../Dockerfile.web', import.meta.url), 'utf8');
  assert.match(docker, /ARG WEB_BUILD_PROFILE=beta/);
  assert.match(docker, /operational-beta-v1.*pnpm run build:beta/);
  assert.match(docker, /enrollment\)[\s\S]*pnpm run build:enrollment/);
  for (const name of Object.keys(sample())) assert.match(docker, new RegExp(`ARG ${name}`));
});

// Execute the image's real profile-selection shell; substitute only the package
// runner so this check exercises its environment and the existing validators
// without rebuilding TypeScript or pulling a container image.
async function runDockerProfile(env) {
  const docker = await readFile(new URL('../../Dockerfile.web', import.meta.url), 'utf8');
  const command = docker.match(/^RUN --network=none (case "\$WEB_BUILD_PROFILE" in[\s\S]*?\n    esac)$/m)?.[1];
  assert.ok(command, 'the image must retain an explicit hosted build profile');
  const directory = await mkdtemp(join(tmpdir(), 'cosmabot-web-profile-'));
  try {
    const probe = join(directory, 'package-runner.mjs');
    await writeFile(probe, `
import {resolveBetaFeatureProfile} from ${JSON.stringify(new URL('../../clients/shared/beta-feature-profile.mjs', import.meta.url).href)};
import {resolveEnrollmentBuild} from ${JSON.stringify(new URL('./enrollment-build-config.mjs', import.meta.url).href)};
const [command, script] = process.argv.slice(2);
if (command !== 'run') throw new Error('Unexpected package command');
const result = script === 'build:beta' ? resolveBetaFeatureProfile(process.env).manifest
  : script === 'build:enrollment' ? resolveEnrollmentBuild(process.env)
  : (() => { throw new Error('Unexpected build script'); })();
process.stdout.write(JSON.stringify(result));
`, { mode: 0o600 });
    return spawnSync('/bin/sh', ['-c',
      'pnpm() { "$WEB_PROFILE_TEST_NODE" "$WEB_PROFILE_TEST_SCRIPT" "$@"; };\n' + command.replace(/\\\n/g, ' ')],
    { env: { WEB_PROFILE_TEST_NODE: process.execPath, WEB_PROFILE_TEST_SCRIPT: probe, ...env },
      encoding: 'utf8', timeout: 10_000, maxBuffer: 64 * 1024 });
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
}

test('the actual beta image shell isolates empty enrollment arguments and rejects active enrollment flags', async () => {
  const env = { WEB_BUILD_PROFILE: 'beta', VITE_WORKSPACE_FEATURE_PROFILE: '',
    VITE_WORKSPACE_HOSTED_CLIENT: 'web', VITE_WORKSPACE_DATA_MODE: 'synthetic',
    VITE_WORKSPACE_HOSTED_API_ORIGIN: 'https://api.example.invalid', VITE_API_BASE: 'https://api.example.invalid',
    VITE_WORKSPACE_WEB_ORIGIN: 'https://workspace.example.invalid', VITE_COSMANEURA_WEB_ORIGIN: 'https://core.example.invalid',
    VITE_CAPTURE_UPLOAD_ORIGINS: 'https://uploads.example.invalid', VITE_WORKSPACE_CAPTURE_MODE: 'browser_microphone',
    VITE_CLERK_PUBLISHABLE_KEY: 'pk_test_invented', VITE_MESSAGES_ENABLED: 'true',
    ...Object.fromEntries(Object.keys(sample()).filter(name => name.startsWith('VITE_ENROLLMENT_')).map(name => [name, ''])) };
  const result = await runDockerProfile(env);
  assert.equal(result.status, 0, result.stderr);
  assert.equal(JSON.parse(result.stdout).profile, 'operational-beta-v1');
  for (const name of ['VITE_ENROLLMENT_ENABLED', 'VITE_ENROLLMENT_ACCOUNT_ONLY']) {
    for (const value of ['true', 'false']) {
      const denied = await runDockerProfile({ ...env, [name]: value });
      assert.notEqual(denied.status, 0);
      assert.equal(denied.stdout, '', 'a conflicting profile must not start a package build');
    }
  }
});

test('the actual enrollment image shell retains its account bindings and passes the account validator', async () => {
  const result = await runDockerProfile({ WEB_BUILD_PROFILE: 'enrollment', ...sample(),
    VITE_MESSAGES_ENABLED: 'false', VITE_WORKSPACE_HOSTED_CLIENT: 'web',
    VITE_WORKSPACE_DATA_MODE: 'synthetic', VITE_WORKSPACE_CAPTURE_MODE: 'browser_microphone' });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(JSON.parse(result.stdout).kind, 'enrollment-account');
  assert.equal(JSON.parse(result.stdout).clinical_workspace, false);
});
