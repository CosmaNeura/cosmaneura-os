import assert from 'node:assert/strict';
import test from 'node:test';
import { render } from './render.mjs';

const sample = () => ({
  version: 1, environment: 'staging', source_commit: '1'.repeat(40),
  image: `inventedenrollment.azurecr.io/cosmabot-enrollment@sha256:${'2'.repeat(64)}`,
  app_origin: 'https://staging.cosmas.ai', api_origin: 'https://enrollment-api.staging.cosmas.ai',
  workspace_origins: [], clerk: {
    issuer: 'https://clerk.staging.cosmas.ai',
    publishable_key: `pk_test_${Buffer.from('clerk.staging.cosmas.ai$').toString('base64')}`,
    session_policy: 'default_session',
  }, stripe: {}, secret_references: {}, readiness: {},
  qualification: { source_commit: '1'.repeat(40) },
});

test('a prepared configuration does not grant registration, trial access or deployment', () => {
  const files = render(sample());
  assert.equal(files['public-env.json'].ENROLLMENT_ENABLED, 'false');
  assert.equal(files['public-env.json'].ENROLLMENT_ACTIVATION_AVAILABLE, 'false');
  assert.equal(files['deployment-contract.json'].deployed, false);
  assert.equal(files['deployment-contract.json'].pricing.paid_roles, 'every_human_user');
  assert.equal(files['deployment-contract.json'].pricing.above_limit, 'negotiated');
  assert.equal(files['public-env.json'].ENROLLMENT_CLERK_SESSION_POLICY, 'default_session');
  assert.equal(files['web-build-env.json'].VITE_ENROLLMENT_API_BASE, sample().api_origin);
  assert.equal(files['web-build-env.json'].VITE_ENROLLMENT_ACCOUNT_ONLY, 'true');
  assert.equal('ENROLLMENT_CLERK_AUDIENCE' in files['public-env.json'], false);
});

test('the separate staging account build owns its root without replacing beta workspace configuration', () => {
  const files = render({ ...sample(), app_origin: 'https://onboarding.staging.cosmas.ai' });
  assert.equal(files['public-env.json'].ENROLLMENT_PUBLIC_APP_ORIGIN, 'https://onboarding.staging.cosmas.ai');
  assert.equal(files['web-build-env.json'].VITE_ENROLLMENT_ACCOUNT_ONLY, 'true');
  assert.equal(files['web-build-env.json'].VITE_ENROLLMENT_API_BASE, 'https://enrollment-api.staging.cosmas.ai');
  assert.equal('VITE_CLERK_PUBLISHABLE_KEY' in files['web-build-env.json'], false);
  assert.equal('VITE_API_BASE' in files['web-build-env.json'], false);
});

test('wrong product origins and mismatched Clerk identity are rejected', () => {
  for (const patch of [
    { app_origin: 'https://app.cosmaneura.com' },
    { api_origin: 'https://api.staging.cosmas.ai.evil.example' },
    { clerk: { ...sample().clerk, publishable_key: `pk_test_${Buffer.from('other.example$').toString('base64')}` } },
    { clerk: { ...sample().clerk, audience: 'cosmas-enrollment' } },
  ]) assert.throws(() => render({ ...sample(), ...patch }));
});

test('development enrollment uses its matching Clerk development instance without changing token templates', () => {
  const value = sample();
  value.clerk.issuer = 'https://invented-clinic.clerk.accounts.dev';
  value.clerk.publishable_key = `pk_test_${Buffer.from('invented-clinic.clerk.accounts.dev$').toString('base64')}`;
  assert.equal(render(value)['public-env.json'].ENROLLMENT_CLERK_ISSUER, value.clerk.issuer);
  value.clerk.issuer += '/unexpected';
  assert.throws(() => render(value));
});

test('practice setup admits the account session without making it a clinical workspace session', () => {
  const value = sample();
  value.workspace_origins = ['https://example-practice.staging.cosmas.ai'];
  const env = render(value)['workspace-account-env.json'][value.workspace_origins[0]];
  assert.equal(env.CLERK_AUTHORIZED_PARTIES, `${value.app_origin},${value.workspace_origins[0]}`);
  assert.equal(env.CORS_ALLOWED_ORIGINS, value.workspace_origins[0]);
  assert.equal(env.WORKSPACE_ENROLLMENT_API_ORIGIN, value.api_origin);
  assert.equal(env.WORKSPACE_ENROLLMENT_ACCOUNT_ORIGIN, value.app_origin);
  assert.equal(env.CLERK_SESSION_POLICY, 'enrollment_default');
  assert.equal(env.WORKSPACE_ENROLLMENT_MANAGED, 'true');
  assert.equal(JSON.stringify(env).includes('SECRET'), false);
  assert.equal('BETA_BOX_ID' in env, false);
});

test('credentials and unrelated runtime privileges cannot enter rendered browser configuration', () => {
  assert.throws(() => render({ ...sample(), secret_references: { ENROLLMENT_CLERK_SECRET_KEY: 'sk_test_do_not_store' } }));
  assert.throws(() => render({ ...sample(), secret_references: { CORE_CAPTURE_TOKEN: 'https://invented.vault.azure.net/secrets/key/' + '3'.repeat(32) } }));
  assert.throws(() => render({ ...sample(), clerk: { ...sample().clerk, secret_key: 'sk_test_do_not_store' } }));
  const value = sample();
  value.secret_references.ENROLLMENT_DATABASE_URL = `https://inventedenrollment.vault.azure.net/secrets/database/${'3'.repeat(32)}`;
  const output = render(value);
  assert.equal(JSON.stringify(output['web-build-env.json']).includes('vault.azure.net'), false);
  assert.equal(JSON.stringify(output['public-env.json']).includes('vault.azure.net'), false);
});

test('production cannot inherit a staging key or enable registration without qualification', () => {
  const value = sample();
  value.environment = 'production'; value.app_origin = 'https://app.cosmas.ai';
  value.api_origin = 'https://enrollment-api.cosmas.ai'; value.clerk.issuer = 'https://clerk.cosmas.ai';
  assert.throws(() => render(value));
  value.clerk.publishable_key = `pk_live_${Buffer.from('clerk.cosmas.ai$').toString('base64')}`;
  value.workspace_origins = ['https://example-practice.workspace.cosmas.ai'];
  assert.equal(render(value)['public-env.json'].ENROLLMENT_STRIPE_LIVE_MODE, 'true');
  assert.equal(render(value)['public-env.json'].ENROLLMENT_ALLOWED_WORKSPACE_ORIGINS,
    JSON.stringify(value.workspace_origins));
  value.readiness.enabled = true;
  assert.throws(() => render(value));
});

test('trial activation cannot precede provisioning or a complete admitted billing contract', () => {
  const value = sample(); value.readiness.activation_available = true;
  assert.throws(() => render(value));
  value.readiness.stripe_acquisition_enabled = true;
  value.qualification.journey_sha256 = '4'.repeat(64);
  assert.throws(() => render(value));
  value.readiness = { enabled: true, clerk_methods_verified: true };
  value.secret_references = {
    ENROLLMENT_DATABASE_URL: `https://inventedenrollment.vault.azure.net/secrets/database/${'3'.repeat(32)}`,
    ENROLLMENT_CLERK_SECRET_KEY: `https://inventedenrollment.vault.azure.net/secrets/clerk/${'3'.repeat(32)}`,
  };
  value.qualification.source_commit = '5'.repeat(40);
  assert.throws(() => render(value));
});
