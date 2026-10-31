// @vitest-environment node
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
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
