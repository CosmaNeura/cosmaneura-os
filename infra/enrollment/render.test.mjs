import assert from 'node:assert/strict';
import test from 'node:test';
import { createHash, createPrivateKey, generateKeyPairSync, sign } from 'node:crypto';
import { chmodSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { render } from './render.mjs';
import { signStagingPreflight } from './staging-preflight.mjs';

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

// Invented local evidence/key fixtures exercise trust and binding; they are not
// actual provider measurements and are never written into a deployment input.
function intakeFixture(t) {
  const directory = mkdtempSync(join(realpathSync(tmpdir()), 'cosmabot-preflight-test-'));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  chmodSync(directory, 0o700);
  const { publicKey, privateKey } = generateKeyPairSync('ed25519');
  const save = (name, content) => {
    const path = join(directory, name);
    writeFileSync(path, content, { mode: 0o600 });
    return path;
  };
  const trust = save('public.pem', publicKey.export({ type: 'spki', format: 'pem' }));
  const key = save('private.pem', privateKey.export({ type: 'pkcs8', format: 'pem' }));
  const input = sample();
  input.app_origin = 'https://onboarding.staging.cosmas.ai';
  input.image = `acrcbotenrstgabcdef.azurecr.io/cosmabot-enrollment@sha256:${'2'.repeat(64)}`;
  input.clerk.issuer = 'https://invented-clinic.clerk.accounts.dev';
  input.clerk.publishable_key = `pk_test_${Buffer.from('invented-clinic.clerk.accounts.dev$').toString('base64')}`;
  input.readiness = { enabled: true, clerk_methods_verified: true };
  const vault = 'https://kv-cbot-enr-stg-abcdef.vault.azure.net/';
  input.secret_references = Object.fromEntries([
    ['ENROLLMENT_DATABASE_URL', 'enrollment-database-url'],
    ['ENROLLMENT_CLERK_SECRET_KEY', 'enrollment-clerk-key'],
    ['ENROLLMENT_INVITATION_SECRET', 'enrollment-invitation-secret'],
  ].map(([name, secret]) => [name, `${vault}secrets/${secret}/${'3'.repeat(32)}`]));
  const now = Math.floor(Date.now() / 1000);
  const payload = {
    contract_version: 'enrollment-staging-intake-preflight.v1', purpose: 'development-intake-only',
    environment: 'staging', synthetic_only: true, source_commit: input.source_commit, image: input.image,
    app_origin: input.app_origin, api_origin: input.api_origin, issued_at: now, expires_at: now + 3600,
    database: {
      subscription_id: '11111111-1111-1111-1111-111111111111', tenant_id: '22222222-2222-2222-2222-222222222222',
      resource_group_name: 'rg-cosmabot-enrollment-staging-abcdef', location: 'centralus',
      registry_server: 'acrcbotenrstgabcdef.azurecr.io', key_vault_uri: vault,
      server_fqdn: 'psql-cosmabot-enrollment-staging-abcdef.postgres.database.azure.com',
      database: 'cosmabot_enrollment', runtime_login: 'enrollment_runtime',
      runtime_secret_reference: input.secret_references.ENROLLMENT_DATABASE_URL,
      execution_evidence_sha256: '', check: {
        contract_version: 'enrollment-database-check.v1', schema_version: 'enrollment_20261031_v1',
        runtime_role_checked: true, immutable_receipt_checked: true, grant_table_count: 9,
        azure_connectivity_qualified: false, restore_qualified: false, journey_qualified: false,
      },
    },
    hosting: {
      version: 1, kind: 'enrollment-staging-hosts', source_commit: input.source_commit,
      application_origin: input.app_origin, enrollment_api_origin: input.api_origin,
      dns_tls_and_routes_checked: true, enrollment_enabled: false, activation_available: false,
      central_database_operational: true, account_paths: ['/', '/onboarding', '/sign-in', '/sign-up', '/workspaces'],
      staged_customer_journey_qualified: false, production_qualified: false,
    },
    clerk: {
      issuer: input.clerk.issuer, publishable_key: input.clerk.publishable_key, authorized_parties: [input.app_origin],
      invite_only: true, policy_evidence_sha256: '', instance_evidence_sha256: '', identity_evidence_sha256: '', methods: {}, configuration: {
        instance_id: 'ins_inventedfixture', instance_environment_type: 'development', instance_allowed_origins: null,
        test_mode: true, auth_password: 'required', first_factors: ['password', 'oauth_google', 'oauth_microsoft'],
        email_address: { enabled: true, required: true, verify_at_sign_up: true },
        password: { enabled: true, required: true }, sign_up_mode: 'restricted',
        social: Object.fromEntries(['oauth_google', 'oauth_microsoft'].map(strategy => [strategy,
          { enabled: true, authenticatable: true, strategy, not_selectable: false, deprecated: false }])),
      },
    },
  };
  const evidenceFiles = {
    database_check: save('database-check.json', JSON.stringify(payload.database.check)),
    hosting: save('hosting.json', JSON.stringify(payload.hosting)),
  };
  const configuration = payload.clerk.configuration;
  const metadata = {
    clerk_environment: { http_status: 200, vendor_writes: false, settings: {
      auth_config: { object: 'auth_config', test_mode: true, password: configuration.auth_password,
        first_factors: configuration.first_factors },
      display_config: { object: 'display_config', instance_environment_type: 'development' },
      user_settings: { attributes: { email_address: configuration.email_address, password: configuration.password },
        social: configuration.social, sign_up: { mode: configuration.sign_up_mode } },
      // Organization policy is outside the configured-method preflight scope.
      organization_settings: { force_organization_selection: true, max_allowed_memberships: 5 },
    } },
    clerk_instance: { kind: 'cosmabot.dev-clerk.instance-read.v1', vendor_writes: false,
      public_build_key_matches: true, key_is_test: true,
      selected_settings: { object: 'instance', id: configuration.instance_id, environment_type: 'development', allowed_origins: null } },
  };
  const execution = 'Invented local execution evidence; not an actual measurement.\n';
  evidenceFiles.database_execution = save('database_execution.txt', execution);
  payload.database.execution_evidence_sha256 = createHash('sha256').update(execution).digest('hex');
  for (const [name, receipt] of Object.entries(metadata)) {
    const content = JSON.stringify(receipt);
    evidenceFiles[name] = save(`${name}.json`, content);
    const sha = createHash('sha256').update(content).digest('hex');
    if (name === 'clerk_environment') payload.clerk.policy_evidence_sha256 = sha;
    else payload.clerk.instance_evidence_sha256 = sha;
  }
  payload.clerk.methods = Object.fromEntries(['password', 'google', 'microsoft'].map(name =>
    [name, { configured: true, evidence_sha256: payload.clerk.policy_evidence_sha256 }]));
  payload.clerk.identity_binding = {
    kind: 'cosmabot.dev-clerk.identity-binding.v1', observed_at: now,
    issuer: input.clerk.issuer, publishable_key_sha256: createHash('sha256').update(input.clerk.publishable_key).digest('hex'),
    authorized_parties: [input.app_origin], instance_id: configuration.instance_id,
    frontend: { url: `${input.clerk.issuer}/v1/environment`, http_status: 200, environment_sha256: payload.clerk.policy_evidence_sha256 },
    backend: { url: 'https://api.clerk.com/v1/instance', http_status: 200, instance_sha256: payload.clerk.instance_evidence_sha256 },
  };
  const identity = JSON.stringify(payload.clerk.identity_binding);
  evidenceFiles.clerk_identity = save('clerk-identity.json', identity);
  payload.clerk.identity_evidence_sha256 = createHash('sha256').update(identity).digest('hex');
  const attach = () => { input.qualification.staging_preflight = signStagingPreflight(payload, key, evidenceFiles); };
  attach();
  return { input, payload, trust, key, evidenceFiles, attach, directory };
}

test('trusted configured-method Development preflight permits auth testing/intake while trial and deployment stay closed', t => {
  const { input, trust } = intakeFixture(t);
  const files = render(input, { preflightTrustFile: trust });
  const env = files['public-env.json'];
  assert.equal(env.ENROLLMENT_ENABLED, 'true');
  assert.equal(env.ENROLLMENT_CLERK_METHODS_VERIFIED, 'true');
  assert.equal(env.ENROLLMENT_DATA_MODE, 'synthetic');
  for (const flag of ['STRIPE_ACQUISITION_ENABLED', 'ACTIVATION_AVAILABLE', 'PRODUCTION_QUALIFIED']) {
    assert.equal(env[`ENROLLMENT_${flag}`], 'false');
  }
  assert.equal(files['deployment-contract.json'].deployed, false);
  assert.match(files['deployment-contract.json'].qualification.staging_preflight_sha256, /^[0-9a-f]{64}$/);
  assert.equal(JSON.stringify(files['web-build-env.json']).includes('signature'), false);
  assert.equal(JSON.stringify(env).includes('evidence_sha256'), false);
  assert.equal('journey_sha256' in input.qualification, false);
  assert.equal('verified' in input.qualification.staging_preflight.payload.clerk.methods.google, false);
  assert.equal(input.qualification.staging_preflight.payload.clerk.methods.google.configured, true);
});

test('protected signer and renderer CLIs complete intake configuration without overwriting evidence', t => {
  const { input, payload, trust, key, evidenceFiles, directory } = intakeFixture(t);
  const draft = join(directory, 'draft.json');
  const evidence = join(directory, 'evidence-paths.json');
  const receipt = join(directory, 'new-receipt.json');
  writeFileSync(draft, JSON.stringify(payload), { mode: 0o600 });
  writeFileSync(evidence, JSON.stringify(evidenceFiles), { mode: 0o600 });
  const signer = fileURLToPath(new URL('./staging-preflight.mjs', import.meta.url));
  const signerArgs = [signer, '--input', draft, '--evidence', evidence, '--private-key', key, '--output', receipt];
  assert.equal(spawnSync(process.execPath, signerArgs, { encoding: 'utf8' }).status, 0);
  const original = readFileSync(receipt);
  assert.equal(spawnSync(process.execPath, signerArgs, { encoding: 'utf8' }).status, 1);
  assert.deepEqual(readFileSync(receipt), original);
  input.qualification.staging_preflight = JSON.parse(original);
  const manifest = join(directory, 'intake-manifest.json');
  writeFileSync(manifest, JSON.stringify(input), { mode: 0o600 });
  const output = join(directory, 'rendered');
  const renderer = fileURLToPath(new URL('./render.mjs', import.meta.url));
  const rendered = spawnSync(process.execPath, [renderer, '--input', manifest, '--output', output,
    '--preflight-trust', trust], { encoding: 'utf8' });
  assert.equal(rendered.status, 0, rendered.stderr);
  const env = JSON.parse(readFileSync(join(output, 'public-env.json')));
  assert.equal(env.ENROLLMENT_ENABLED, 'true');
  assert.equal(env.ENROLLMENT_STRIPE_ACQUISITION_ENABLED, 'false');
  assert.equal(env.ENROLLMENT_ACTIVATION_AVAILABLE, 'false');
  assert.equal(JSON.parse(readFileSync(join(output, 'deployment-contract.json'))).deployed, false);
});

test('intake has no implicit trust, and untrusted or altered signatures cannot authorize it', t => {
  const fixture = intakeFixture(t);
  assert.throws(() => render(fixture.input));
  const other = intakeFixture(t);
  assert.throws(() => render(fixture.input, { preflightTrustFile: other.trust }));
  fixture.input.qualification.staging_preflight.payload.clerk.invite_only = false;
  assert.throws(() => render(fixture.input, { preflightTrustFile: fixture.trust }));
  fixture.payload.clerk.invite_only = true;
  fixture.attach();
  chmodSync(fixture.trust, 0o644);
  assert.throws(() => render(fixture.input, { preflightTrustFile: fixture.trust }));
});

test('signed intake cannot be reused for another source, API image, host, identity or database version', t => {
  const { input, trust } = intakeFixture(t);
  const changes = [
    value => { value.source_commit = '4'.repeat(40); value.qualification.source_commit = value.source_commit; },
    value => { value.image = value.image.replace('2'.repeat(64), '4'.repeat(64)); },
    value => { value.app_origin = 'https://staging.cosmas.ai'; },
    value => { value.api_origin = 'https://other.staging.cosmas.ai'; },
    value => { value.clerk.issuer = 'https://other.clerk.accounts.dev'; value.clerk.publishable_key = `pk_test_${Buffer.from('other.clerk.accounts.dev$').toString('base64')}`; },
    value => { value.secret_references.ENROLLMENT_DATABASE_URL = value.secret_references.ENROLLMENT_DATABASE_URL.replace('3'.repeat(32), '4'.repeat(32)); },
    value => { value.secret_references.ENROLLMENT_CLERK_SECRET_KEY = `https://foreign.vault.azure.net/secrets/key/${'3'.repeat(32)}`; },
  ];
  for (const change of changes) {
    const changed = structuredClone(input); change(changed);
    assert.throws(() => render(changed, { preflightTrustFile: trust }));
  }
});

test('operator attestation requires retained evidence, exact methods/invite policy and fresh schema/host checks', t => {
  const { payload, key, evidenceFiles } = intakeFixture(t);
  for (const change of [
    value => { value.clerk.invite_only = false; },
    value => { value.clerk.authorized_parties.push('https://staging.cosmas.ai'); },
    value => { value.clerk.methods.google.configured = false; },
    value => { value.clerk.methods.google = { verified: true, evidence_sha256: value.clerk.policy_evidence_sha256 }; },
    value => { delete value.clerk.methods.microsoft; },
    value => { value.database.check.runtime_role_checked = false; },
    value => { value.database.check.schema_version = 'old-schema'; },
    value => { value.hosting.dns_tls_and_routes_checked = false; },
    value => { value.hosting.enrollment_enabled = true; },
    value => { value.expires_at = value.issued_at - 1; },
    value => { value.issued_at += 86400; value.expires_at += 86400; },
    value => { value.database.execution_evidence_sha256 = '4'.repeat(64); },
    value => { value.clerk.methods.password.evidence_sha256 = '4'.repeat(64); },
  ]) {
    const changed = structuredClone(payload); change(changed);
    assert.throws(() => signStagingPreflight(changed, key, evidenceFiles));
  }
  assert.throws(() => signStagingPreflight(payload, key));
  writeFileSync(evidenceFiles.hosting, '{}', { mode: 0o600 });
  assert.throws(() => signStagingPreflight(payload, key, evidenceFiles));
});

test('arbitrary configured flags cannot replace successful structured FAPI/BAPI metadata', t => {
  const fixture = intakeFixture(t);
  const originalEnvironment = JSON.parse(readFileSync(fixture.evidenceFiles.clerk_environment));
  const originalInstance = JSON.parse(readFileSync(fixture.evidenceFiles.clerk_instance));
  for (const [name, change] of [
    ['clerk_environment', value => { value.http_status = 401; }],
    ['clerk_environment', value => { value.settings.auth_config.test_mode = false; }],
    ['clerk_environment', value => { value.settings.user_settings.attributes.password.enabled = false; }],
    ['clerk_environment', value => { value.settings.user_settings.social.oauth_google.authenticatable = false; }],
    ['clerk_environment', value => { value.settings.user_settings.social.oauth_microsoft.strategy = 'oauth_google'; }],
    ['clerk_environment', value => { value.settings.user_settings.sign_up.mode = 'public'; }],
    ['clerk_instance', value => { value.selected_settings.environment_type = 'production'; }],
    ['clerk_instance', value => { value.public_build_key_matches = false; }],
    ['clerk_instance', value => { delete value.selected_settings.id; }],
  ]) {
    const changed = structuredClone(name === 'clerk_environment' ? originalEnvironment : originalInstance); change(changed);
    const bytes = JSON.stringify(changed); const sha = createHash('sha256').update(bytes).digest('hex');
    writeFileSync(fixture.evidenceFiles[name], bytes, { mode: 0o600 });
    const payload = structuredClone(fixture.payload);
    if (name === 'clerk_environment') {
      payload.clerk.policy_evidence_sha256 = sha;
      for (const method of Object.values(payload.clerk.methods)) method.evidence_sha256 = sha;
      payload.clerk.identity_binding.frontend.environment_sha256 = sha;
    } else {
      payload.clerk.instance_evidence_sha256 = sha;
      payload.clerk.identity_binding.backend.instance_sha256 = sha;
    }
    const identityBytes = JSON.stringify(payload.clerk.identity_binding);
    writeFileSync(fixture.evidenceFiles.clerk_identity, identityBytes, { mode: 0o600 });
    payload.clerk.identity_evidence_sha256 = createHash('sha256').update(identityBytes).digest('hex');
    // Every claimed configured flag stays true and the evidence hashes match;
    // the actual provider fields still have to support those claims.
    assert.throws(() => signStagingPreflight(payload, fixture.key, fixture.evidenceFiles));
    writeFileSync(fixture.evidenceFiles[name], JSON.stringify(name === 'clerk_environment' ? originalEnvironment : originalInstance), { mode: 0o600 });
  }
});

test('configured evidence cannot be signed for a different internally matching Clerk issuer/key or instance', t => {
  const { payload, key, evidenceFiles } = intakeFixture(t);
  for (const change of [
    value => { value.clerk.issuer = 'https://other-instance.clerk.accounts.dev'; value.clerk.publishable_key = `pk_test_${Buffer.from('other-instance.clerk.accounts.dev$').toString('base64')}`; },
    value => { value.clerk.configuration.instance_id = 'ins_otherinstance'; },
    value => { value.clerk.identity_binding.frontend.url = 'https://other-instance.clerk.accounts.dev/v1/environment'; },
    value => { value.clerk.identity_binding.publishable_key_sha256 = '4'.repeat(64); },
    value => { value.clerk.identity_binding.authorized_parties = ['https://staging.cosmas.ai']; },
    value => { delete value.clerk.identity_binding; },
  ]) {
    const changed = structuredClone(payload); change(changed);
    assert.throws(() => signStagingPreflight(changed, key, evidenceFiles));
  }
});

test('renderer independently rejects a trusted signature over expired or unsafe measurements', t => {
  const { input, payload, key, trust } = intakeFixture(t);
  for (const change of [
    value => { value.expires_at = value.issued_at - 1; },
    value => { value.database.check.runtime_role_checked = false; },
    value => { value.clerk.invite_only = false; },
    value => { value.clerk.authorized_parties.push('https://staging.cosmas.ai'); },
    value => { value.clerk.configuration.sign_up_mode = 'public'; },
    value => { value.clerk.configuration.social.oauth_google.authenticatable = false; },
    value => { value.hosting.dns_tls_and_routes_checked = false; },
  ]) {
    const altered = structuredClone(payload); change(altered);
    const bytes = JSON.stringify(altered, (_name, value) => value && typeof value === 'object' && !Array.isArray(value)
      ? Object.fromEntries(Object.keys(value).sort().map(name => [name, value[name]])) : value);
    const signature = sign(null, Buffer.from(bytes), createPrivateKey(readFileSync(key))).toString('base64');
    const changed = structuredClone(input); changed.qualification.staging_preflight = { payload: altered, signature };
    assert.throws(() => render(changed, { preflightTrustFile: trust }));
  }
});

test('preflight never substitutes for full acquisition/activation or any production qualification', t => {
  const { input, trust } = intakeFixture(t);
  for (const flag of ['stripe_acquisition_enabled', 'activation_available', 'production_qualified']) {
    const changed = structuredClone(input); changed.readiness[flag] = true;
    assert.throws(() => render(changed, { preflightTrustFile: trust }));
    changed.qualification.journey_sha256 = '4'.repeat(64);
    assert.throws(() => render(changed, { preflightTrustFile: trust }));
  }
  const production = structuredClone(input);
  production.environment = 'production'; production.app_origin = 'https://app.cosmas.ai';
  production.api_origin = 'https://enrollment-api.cosmas.ai';
  production.clerk.issuer = 'https://clerk.cosmas.ai';
  production.clerk.publishable_key = `pk_live_${Buffer.from('clerk.cosmas.ai$').toString('base64')}`;
  production.qualification.journey_sha256 = '4'.repeat(64);
  production.qualification.production_sha256 = '5'.repeat(64);
  production.readiness.production_qualified = true;
  assert.throws(() => render(production, { preflightTrustFile: trust }));
  const noPreflight = structuredClone(input); delete noPreflight.qualification.staging_preflight;
  assert.throws(() => render(noPreflight, { preflightTrustFile: trust }));
});
