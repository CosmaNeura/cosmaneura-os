// Operator-attested measurements for synthetic Development intake, never billing.
import { createHash, createPrivateKey, createPublicKey, sign, verify } from 'node:crypto';
import { lstatSync, readFileSync, realpathSync, writeFileSync } from 'node:fs';
import { isAbsolute, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const APP = 'https://onboarding.staging.cosmas.ai';
const API = 'https://enrollment-api.staging.cosmas.ai';
const CONTRACT = 'enrollment-staging-intake-preflight.v1';
const ROOT = resolve(fileURLToPath(new URL('../../', import.meta.url)));
const requireValue = (value, message) => { if (!value) throw new Error(`Staging preflight: ${message}`); };
const digest = value => createHash('sha256').update(value).digest('hex');
const sha = value => typeof value === 'string' && /^[0-9a-f]{64}$/.test(value) && value !== '0'.repeat(64);
const uuid = value => typeof value === 'string' && /^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(value);
const exact = (value, names) => requireValue(value && typeof value === 'object' && !Array.isArray(value) &&
  Object.keys(value).length === names.length && Object.keys(value).every(name => names.includes(name)), 'unexpected or missing measurement fields');
const canonical = value => JSON.stringify(value, (_key, item) => item && typeof item === 'object' && !Array.isArray(item)
  ? Object.fromEntries(Object.keys(item).sort().map(key => [key, item[key]])) : item);

function protectedRead(path, limit = 1_000_000) {
  requireValue(typeof path === 'string' && isAbsolute(path) && !resolve(path).startsWith(ROOT + sep) &&
    realpathSync(path) === path, 'use an independently protected operator key outside the checkout');
  const info = lstatSync(path);
  const parent = lstatSync(resolve(path, '..'));
  requireValue(info.isFile() && !info.isSymbolicLink() && info.size <= limit && (info.mode & 0o777) === 0o600 &&
    info.uid === process.getuid() && parent.isDirectory() && (parent.mode & 0o777) === 0o700 && parent.uid === process.getuid(),
  'operator evidence/key custody must be owner-only');
  return readFileSync(path);
}

function keyFile(path, privateKey = false) {
  const bytes = protectedRead(path, 4096);
  requireValue(bytes.toString().startsWith(privateKey ? '-----BEGIN PRIVATE KEY-----' : '-----BEGIN PUBLIC KEY-----'), 'wrong operator key type');
  const key = privateKey ? createPrivateKey(bytes) : createPublicKey(bytes);
  requireValue(key.asymmetricKeyType === 'ed25519', 'use the separately trusted Ed25519 operator key');
  return key;
}

function configuredClerk(configuration) {
  exact(configuration, ['instance_id', 'instance_environment_type', 'instance_allowed_origins', 'test_mode',
    'auth_password', 'first_factors', 'email_address', 'password', 'sign_up_mode', 'social']);
  requireValue(/^ins_[A-Za-z0-9_]{1,240}$/.test(configuration.instance_id) &&
    configuration.instance_environment_type === 'development' && configuration.test_mode === true &&
    (configuration.instance_allowed_origins === null || canonical(configuration.instance_allowed_origins) === canonical([APP])) &&
    configuration.auth_password === 'required' && configuration.sign_up_mode === 'restricted' &&
    Array.isArray(configuration.first_factors) && configuration.first_factors.length <= 32 &&
    configuration.first_factors.every(factor => typeof factor === 'string' && /^[a-z_]{1,80}$/.test(factor)) &&
    ['password', 'oauth_google', 'oauth_microsoft'].every(factor => configuration.first_factors.includes(factor)),
  'require actual Development instance, restricted signup and configured first factors');
  exact(configuration.email_address, ['enabled', 'required', 'verify_at_sign_up']);
  exact(configuration.password, ['enabled', 'required']);
  requireValue(Object.values(configuration.email_address).every(value => value === true) &&
    Object.values(configuration.password).every(value => value === true), 'email/password configuration is incomplete');
  exact(configuration.social, ['oauth_google', 'oauth_microsoft']);
  for (const [strategy, method] of Object.entries(configuration.social)) {
    exact(method, ['enabled', 'authenticatable', 'strategy', 'not_selectable', 'deprecated']);
    requireValue(method.enabled === true && method.authenticatable === true && method.strategy === strategy &&
      method.not_selectable === false && method.deprecated === false, 'OAuth method is not configured for sign-in');
  }
}

// Derive only configuration facts from the existing sanitized successful FAPI
// environment and BAPI instance-read artifacts; omit organization policy.
export function clerkConfigurationFromReceipts(frontend, backend) {
  requireValue(frontend?.http_status === 200 && frontend.vendor_writes === false &&
    backend?.kind === 'cosmabot.dev-clerk.instance-read.v1' && backend.vendor_writes === false &&
    backend.public_build_key_matches === true && backend.key_is_test === true,
  'require successful actual FAPI environment and matching BAPI Development instance receipts');
  const settings = frontend.settings;
  const auth = settings?.auth_config;
  const display = settings?.display_config;
  const users = settings?.user_settings;
  const instance = backend.selected_settings;
  requireValue(auth?.object === 'auth_config' && display?.object === 'display_config' && instance?.object === 'instance' &&
    display.instance_environment_type === instance.environment_type, 'provider metadata objects/environments do not match');
  const attributes = users?.attributes;
  const social = users?.social;
  const configuration = {
    instance_id: instance.id, instance_environment_type: instance.environment_type, instance_allowed_origins: instance.allowed_origins,
    test_mode: auth.test_mode, auth_password: auth.password, first_factors: auth.first_factors,
    email_address: { enabled: attributes?.email_address?.enabled, required: attributes?.email_address?.required,
      verify_at_sign_up: attributes?.email_address?.verify_at_sign_up },
    password: { enabled: attributes?.password?.enabled, required: attributes?.password?.required },
    sign_up_mode: users?.sign_up?.mode,
    social: Object.fromEntries(['oauth_google', 'oauth_microsoft'].map(strategy => [strategy,
      Object.fromEntries(['enabled', 'authenticatable', 'strategy', 'not_selectable', 'deprecated'].map(name => [name, social?.[strategy]?.[name]]))])),
  };
  configuredClerk(configuration);
  return configuration;
}

function boundClerkIdentity(clerk, issuedAt) {
  const binding = clerk.identity_binding;
  exact(binding, ['kind', 'observed_at', 'issuer', 'publishable_key_sha256', 'authorized_parties', 'instance_id', 'frontend', 'backend']);
  exact(binding.frontend, ['url', 'http_status', 'environment_sha256']);
  exact(binding.backend, ['url', 'http_status', 'instance_sha256']);
  requireValue(binding.kind === 'cosmabot.dev-clerk.identity-binding.v1' && Number.isSafeInteger(binding.observed_at) &&
    binding.observed_at <= issuedAt && binding.observed_at >= issuedAt - 86400 &&
    binding.issuer === clerk.issuer && binding.publishable_key_sha256 === digest(clerk.publishable_key) &&
    canonical(binding.authorized_parties) === canonical([APP]) && binding.instance_id === clerk.configuration.instance_id &&
    binding.frontend.url === `${clerk.issuer}/v1/environment` && binding.frontend.http_status === 200 &&
    binding.frontend.environment_sha256 === clerk.policy_evidence_sha256 &&
    binding.backend.url === 'https://api.clerk.com/v1/instance' && binding.backend.http_status === 200 &&
    binding.backend.instance_sha256 === clerk.instance_evidence_sha256 && sha(clerk.identity_evidence_sha256),
  'retained actual request/key/instance/party identity binding does not match this Development intake');
}

function measurements(payload) {
  exact(payload, ['contract_version', 'purpose', 'environment', 'synthetic_only', 'source_commit', 'image',
    'app_origin', 'api_origin', 'issued_at', 'expires_at', 'database', 'hosting', 'clerk']);
  const now = Math.floor(Date.now() / 1000);
  requireValue(payload.contract_version === CONTRACT && payload.purpose === 'development-intake-only' &&
    payload.environment === 'staging' && payload.synthetic_only === true && /^[0-9a-f]{40}$/.test(payload.source_commit) &&
    payload.app_origin === APP && payload.api_origin === API && Number.isSafeInteger(payload.issued_at) &&
    Number.isSafeInteger(payload.expires_at) && payload.issued_at <= now && payload.expires_at > now &&
    payload.expires_at > payload.issued_at && payload.expires_at - payload.issued_at <= 86400,
  'receipt is stale or not synthetic Development intake');

  const db = payload.database;
  exact(db, ['subscription_id', 'tenant_id', 'resource_group_name', 'location', 'registry_server', 'key_vault_uri',
    'server_fqdn', 'database', 'runtime_login', 'runtime_secret_reference', 'execution_evidence_sha256', 'check']);
  const suffix = /^rg-cosmabot-enrollment-staging-([a-z0-9]{6,8})$/.exec(db.resource_group_name ?? '')?.[1];
  requireValue(suffix && uuid(db.subscription_id) && uuid(db.tenant_id) && ['centralus', 'eastus2'].includes(db.location) &&
    db.registry_server === `acrcbotenrstg${suffix}.azurecr.io` &&
    typeof payload.image === 'string' && new RegExp(`^${db.registry_server.replaceAll('.', '\\.')}/[a-z0-9./_-]+@sha256:[0-9a-f]{64}$`).test(payload.image) &&
    db.key_vault_uri === `https://kv-cbot-enr-stg-${suffix}.vault.azure.net/` &&
    db.server_fqdn === `psql-cosmabot-enrollment-staging-${suffix}.postgres.database.azure.com` &&
    db.database === 'cosmabot_enrollment' && db.runtime_login === 'enrollment_runtime' &&
    new RegExp(`^${db.key_vault_uri.replaceAll('.', '\\.')}secrets/enrollment-database-url/[0-9a-f]{32}$`).test(db.runtime_secret_reference) &&
    sha(db.execution_evidence_sha256), 'the database/image must bind the actual owned foundation and runtime secret');
  exact(db.check, ['contract_version', 'schema_version', 'runtime_role_checked', 'immutable_receipt_checked',
    'grant_table_count', 'azure_connectivity_qualified', 'restore_qualified', 'journey_qualified',
    'managed_database_ownership_acl_checked', 'provider_database_default_access_allowed', 'provider_database_count']);
  requireValue(db.check.contract_version === 'enrollment-database-check.v2' && db.check.schema_version === 'enrollment_20261031_v1' &&
    db.check.runtime_role_checked === true && db.check.immutable_receipt_checked === true && db.check.grant_table_count === 9 &&
    db.check.managed_database_ownership_acl_checked === true && db.check.provider_database_default_access_allowed === true &&
    db.check.provider_database_count === 2 &&
    db.check.azure_connectivity_qualified === false && db.check.restore_qualified === false && db.check.journey_qualified === false,
  'require the actual restricted-role/schema receipt without inventing restore or journey qualification');

  const host = payload.hosting;
  exact(host, ['version', 'kind', 'source_commit', 'application_origin', 'enrollment_api_origin', 'dns_tls_and_routes_checked',
    'enrollment_enabled', 'activation_available', 'central_database_operational', 'account_paths',
    'staged_customer_journey_qualified', 'production_qualified']);
  requireValue(host.version === 1 && host.kind === 'enrollment-staging-hosts' && host.source_commit === payload.source_commit &&
    host.application_origin === APP && host.enrollment_api_origin === API && host.dns_tls_and_routes_checked === true &&
    host.central_database_operational === true && host.enrollment_enabled === false && host.activation_available === false &&
    canonical(host.account_paths) === canonical(['/', '/onboarding', '/sign-in', '/sign-up', '/workspaces']) &&
    host.staged_customer_journey_qualified === false && host.production_qualified === false,
  'require the actual closed-host TLS/routes/operational receipt for this source');

  const clerk = payload.clerk;
  exact(clerk, ['issuer', 'publishable_key', 'authorized_parties', 'methods', 'invite_only', 'policy_evidence_sha256',
    'instance_evidence_sha256', 'configuration', 'identity_binding', 'identity_evidence_sha256']);
  requireValue(/^https:\/\/[a-z0-9]+(?:-[a-z0-9]+)*\.clerk\.accounts\.dev$/.test(clerk.issuer) &&
    typeof clerk.publishable_key === 'string' && clerk.publishable_key.startsWith('pk_test_') &&
    Buffer.from(clerk.publishable_key.slice(8), 'base64').toString() === `${new URL(clerk.issuer).hostname}$` &&
    canonical(clerk.authorized_parties) === canonical([APP]) && clerk.invite_only === true && sha(clerk.policy_evidence_sha256) &&
    sha(clerk.instance_evidence_sha256),
  'require the measured matching invite-only Development instance and exact account party');
  configuredClerk(clerk.configuration);
  boundClerkIdentity(clerk, payload.issued_at);
  exact(clerk.methods, ['password', 'google', 'microsoft']);
  for (const method of Object.values(clerk.methods)) {
    exact(method, ['configured', 'evidence_sha256']);
    requireValue(method.configured === true && method.evidence_sha256 === clerk.policy_evidence_sha256,
      'all three configured methods must bind the retained successful FAPI environment');
  }
}

// Signing is an explicit operator attestation after reviewing actual retained
// measurements; it performs no vendor calls and is not itself a measurement.
export function signStagingPreflight(payload, operatorPrivateKeyFile, evidenceFiles) {
  measurements(payload);
  exact(evidenceFiles, ['database_check', 'database_execution', 'hosting', 'clerk_environment', 'clerk_instance', 'clerk_identity']);
  const evidence = Object.fromEntries(Object.entries(evidenceFiles).map(([name, path]) => [name, protectedRead(path)]));
  requireValue(canonical(JSON.parse(evidence.database_check)) === canonical(payload.database.check) &&
    canonical(JSON.parse(evidence.hosting)) === canonical(payload.hosting) &&
    digest(evidence.database_execution) === payload.database.execution_evidence_sha256 &&
    digest(evidence.clerk_environment) === payload.clerk.policy_evidence_sha256 &&
    digest(evidence.clerk_instance) === payload.clerk.instance_evidence_sha256 &&
    digest(evidence.clerk_identity) === payload.clerk.identity_evidence_sha256 &&
    canonical(JSON.parse(evidence.clerk_identity)) === canonical(payload.clerk.identity_binding) &&
    canonical(clerkConfigurationFromReceipts(JSON.parse(evidence.clerk_environment), JSON.parse(evidence.clerk_instance))) === canonical(payload.clerk.configuration),
  'retained actual component receipts and derived configured-method metadata must match before attesting');
  return { payload, signature: sign(null, Buffer.from(canonical(payload)), keyFile(operatorPrivateKeyFile, true)).toString('base64') };
}

export function verifyStagingPreflight(input, receipt, operatorPublicKeyFile) {
  exact(receipt, ['payload', 'signature']);
  const signature = typeof receipt.signature === 'string' ? Buffer.from(receipt.signature, 'base64') : Buffer.alloc(0);
  requireValue(signature.length === 64 && signature.toString('base64') === receipt.signature &&
    verify(null, Buffer.from(canonical(receipt.payload)), keyFile(operatorPublicKeyFile), signature), 'receipt has no trusted operator signature');
  measurements(receipt.payload);
  const payload = receipt.payload;
  requireValue(input.environment === 'staging' && input.app_origin === APP && input.api_origin === API &&
    payload.source_commit === input.source_commit && payload.image === input.image &&
    payload.clerk.issuer === input.clerk.issuer && payload.clerk.publishable_key === input.clerk.publishable_key &&
    input.clerk.session_policy === 'default_session' &&
    payload.database.runtime_secret_reference === input.secret_references.ENROLLMENT_DATABASE_URL &&
    Object.values(input.secret_references).every(reference => reference.startsWith(payload.database.key_vault_uri + 'secrets/')),
  'receipt does not bind this selected source/image/host/identity/database configuration');
  return digest(canonical(receipt));
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const args = process.argv.slice(2);
    requireValue(args.length === 8 && args[0] === '--input' && args[2] === '--evidence' &&
      args[4] === '--private-key' && args[6] === '--output',
    'usage: --input protected-draft.json --evidence protected-evidence-paths.json --private-key protected-key.pem --output new-receipt.json');
    const payload = JSON.parse(protectedRead(resolve(args[1])));
    const evidenceFiles = JSON.parse(protectedRead(resolve(args[3])));
    const receipt = signStagingPreflight(payload, resolve(args[5]), evidenceFiles);
    const output = resolve(args[7]);
    const parent = realpathSync(resolve(output, '..'));
    const info = lstatSync(parent);
    requireValue(parent === resolve(output, '..') && !output.startsWith(ROOT + sep) &&
      info.isDirectory() && info.uid === process.getuid() && (info.mode & 0o777) === 0o700,
    'receipt destination must be an independently protected directory');
    writeFileSync(output, JSON.stringify(receipt, null, 2) + '\n', { mode: 0o600, flag: 'wx' });
    process.stdout.write('Prepared a signed staging intake attestation; no deployment or journey qualification was performed.\n');
  } catch {
    process.stderr.write('Staging intake attestation refused; review custody, scope, freshness and actual retained evidence.\n');
    process.exitCode = 1;
  }
}
