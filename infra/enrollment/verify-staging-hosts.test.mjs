import assert from 'node:assert/strict';
import test from 'node:test';
import { verifyStagingHosts } from './verify-staging-hosts.mjs';
const app = 'https://onboarding.staging.cosmas.ai', api = 'https://enrollment-api.staging.cosmas.ai';
const contract = { environment: 'staging', application_origin: app, enrollment_api_origin: api, source_commit: '1'.repeat(40) };
const env = { ENROLLMENT_PUBLIC_APP_ORIGIN: app, ENROLLMENT_CLERK_PUBLISHABLE_KEY: 'pk_test_invented',
  ENROLLMENT_CLERK_ISSUER: 'https://invented-clinic.clerk.accounts.dev', ENROLLMENT_DATA_MODE: 'synthetic',
  ENROLLMENT_ENABLED: 'false', ENROLLMENT_ACTIVATION_AVAILABLE: 'false' };
const shell = '<title>CosmaBot · Account setup</title><div id="root"></div><script src="/assets/index-synthetic.js"></script>';
function network(patch = () => ({})) {
  const calls = [];
  const request = async (url, options) => {
    calls.push({ url, options });
    let body = shell, json = false;
    if (url.endsWith('/healthz')) body = 'ok\n';
    if (url.endsWith('.js')) body = 'account_build';
    if (url.endsWith('/cosmas-enrollment-build.json')) {
      json = true; body = { kind: 'enrollment-account', account_only: true, clinical_workspace: false,
        source_commit: contract.source_commit, application_origin: app, enrollment_api_origin: api,
        clerk_issuer: env.ENROLLMENT_CLERK_ISSUER };
    }
    if (url.endsWith('/health')) { json = true; body = { component: 'enrollment', data_mode: 'synthetic' }; }
    if (url.endsWith('/operational-ready')) { json = true; body = { component: 'enrollment', operational_ready: true }; }
    if (url.endsWith('/config')) { json = true; body = { contract_version: 'enrollment.v1', data_mode: 'synthetic',
      clerk_publishable_key: env.ENROLLMENT_CLERK_PUBLISHABLE_KEY, enabled: false, activation_available: false }; }
    const value = patch(url, body);
    return new Response(json ? JSON.stringify(value.body ?? body) : value.body ?? body,
      { status: value.status ?? 200, headers: { 'content-type': value.mediaType ?? (json ? 'application/json' : url.endsWith('.js') ? 'application/javascript' : 'text/html'),
        ...(url.startsWith(api) ? { 'access-control-allow-origin': value.origin ?? app, 'cache-control': 'no-store' } : {}) } });
  };
  return { request, calls };
}
test('host qualification measures the fixed account routes and closed API without granting journey admission', async () => {
  const { request, calls } = network();
  const receipt = await verifyStagingHosts(contract, env, request);
  assert.equal(receipt.enrollment_enabled, false);
  assert.equal(receipt.staged_customer_journey_qualified, false);
  assert.equal(receipt.production_qualified, false);
  assert.ok(calls.some(call => call.url === app + '/workspaces'));
  assert.ok(calls.every(call => call.options.credentials === 'omit' && call.options.redirect === 'error'));
});
test('a foreign or beta origin cannot turn the public checker into a caller-selected request', async () => {
  for (const origin of ['https://staging.cosmas.ai', 'https://onboarding.staging.cosmas.ai.evil.example']) {
    await assert.rejects(verifyStagingHosts({ ...contract, application_origin: origin }, env,
      () => assert.fail('No request should run for a foreign contract')));
  }
});
test('stale source, beta account key, CORS mismatch and missing SPA routes fail host qualification', async () => {
  for (const patch of [
    (url, body) => url.endsWith('cosmas-enrollment-build.json') ? { body: { ...body, source_commit: '2'.repeat(40) } } : {},
    (url, body) => url.endsWith('/config') ? { body: { ...body, clerk_publishable_key: 'pk_live_beta' } } : {},
    url => url.endsWith('/config') ? { origin: 'https://staging.cosmas.ai' } : {},
    url => url.endsWith('/workspaces') ? { body: '<title>Workspace</title>' } : {},
    url => url.endsWith('.js') ? { mediaType: 'text/html' } : {},
    url => url.endsWith('/operational-ready') ? { status: 503, body: { component: 'enrollment', operational_ready: false } } : {},
  ]) await assert.rejects(verifyStagingHosts(contract, env, network(patch).request));
});
