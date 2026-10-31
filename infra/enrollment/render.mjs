import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
import { verifyStagingPreflight } from './staging-preflight.mjs';

const SECRET_NAMES = new Set([
  'ENROLLMENT_DATABASE_URL', 'ENROLLMENT_CLERK_SECRET_KEY', 'ENROLLMENT_INVITATION_SECRET', 'ENROLLMENT_RUNTIME_ADMISSION_SECRET',
  'ENROLLMENT_STRIPE_SECRET_KEY', 'ENROLLMENT_STRIPE_WEBHOOK_SECRET',
]);
const PUBLIC_NAMES = new Set([
  'ENROLLMENT_STRIPE_ACCOUNT_ID', 'ENROLLMENT_STRIPE_BASE_PRICE_ID',
  'ENROLLMENT_STRIPE_ADDITIONAL_PRICE_ID', 'ENROLLMENT_STRIPE_PORTAL_CONFIGURATION_ID',
]);
const FLAGS = new Set([
  'enabled', 'clerk_methods_verified', 'stripe_integration_enabled',
  'stripe_acquisition_enabled', 'commercial_terms_verified',
  'activation_available', 'production_qualified', 'provisioning_enabled',
]);
const exact = (value, names, label) => {
  if (!value || typeof value !== 'object' || Array.isArray(value) ||
      Object.keys(value).some(name => !names.includes(name))) throw new Error(`Invalid ${label} fields.`);
};
const requireValue = (condition, message) => { if (!condition) throw new Error(message); };
const hash = value => createHash('sha256').update(value).digest('hex');
const json = value => `${JSON.stringify(value, null, 2)}\n`;

function origin(value, environment, label) {
  requireValue(typeof value === 'string', `Configure ${label}.`);
  const url = new URL(value);
  const host = url.hostname;
  const owned = environment === 'production'
    ? label === 'workspace origin'
      ? host === 'app.cosmas.ai' || /^[a-z0-9]+(?:-[a-z0-9]+)*\.workspace\.cosmas\.ai$/.test(host)
      : ['app.cosmas.ai', 'api.cosmas.ai', 'enrollment-api.cosmas.ai', 'clerk.cosmas.ai'].includes(host)
    : host === 'staging.cosmas.ai' || host.endsWith('.staging.cosmas.ai');
  requireValue(url.protocol === 'https:' && owned && !url.username && !url.password &&
    !url.port && url.pathname === '/' && !url.search && !url.hash,
  `${label} must be an exact owned ${environment} HTTPS origin.`);
  return url.origin;
}

export function render(input, { preflightTrustFile } = {}) {
  exact(input, ['version', 'environment', 'source_commit', 'image', 'app_origin', 'api_origin',
    'workspace_origins', 'clerk', 'stripe', 'secret_references', 'readiness', 'qualification'], 'enrollment manifest');
  requireValue(input.version === 1 && ['staging', 'production'].includes(input.environment), 'Unsupported enrollment environment.');
  requireValue(/^[0-9a-f]{40}$/.test(input.source_commit), 'Use an exact source commit.');
  requireValue(typeof input.image === 'string' && /^[a-z0-9]+\.azurecr\.io\/[a-z0-9./_-]+@sha256:[0-9a-f]{64}$/.test(input.image),
    'Use the reviewed immutable CosmaBot ACR image.');
  const environment = input.environment;
  const app = origin(input.app_origin, environment, 'app origin');
  const api = origin(input.api_origin, environment, 'API origin');
  requireValue(app !== api, 'The app and enrollment API must have distinct origins.');
  requireValue(environment !== 'production' || app === 'https://app.cosmas.ai', 'Production enrollment uses app.cosmas.ai.');
  requireValue(Array.isArray(input.workspace_origins) && input.workspace_origins.length <= 20,
    'Configure the admitted workspace origins.');
  const workspaceOrigins = [...new Set(input.workspace_origins.map(value => origin(value, environment, 'workspace origin')))];

  exact(input.clerk, ['issuer', 'publishable_key', 'session_policy'], 'Clerk');
  const issuerUrl = new URL(input.clerk.issuer);
  const developmentHost = /^[a-z0-9]+(?:-[a-z0-9]+)*\.clerk\.accounts\.dev$/.test(issuerUrl.hostname);
  const issuer = environment === 'staging' && developmentHost
    ? issuerUrl.origin : origin(input.clerk.issuer, environment, 'Clerk issuer');
  requireValue(issuerUrl.protocol === 'https:' && !issuerUrl.username && !issuerUrl.password &&
    !issuerUrl.port && issuerUrl.pathname === '/' && !issuerUrl.search && !issuerUrl.hash,
    'Clerk issuer must be an exact HTTPS origin.');
  const keyType = environment === 'production' ? 'live' : 'test';
  const prefix = `pk_${keyType}_`;
  requireValue(typeof input.clerk.publishable_key === 'string' && input.clerk.publishable_key.startsWith(prefix),
    'Use the selected enrollment Clerk instance key.');
  const encoded = input.clerk.publishable_key.slice(prefix.length);
  requireValue(/^[A-Za-z0-9+/=_-]+$/.test(encoded), 'Invalid Clerk publishable key.');
  const host = Buffer.from(encoded, 'base64').toString('utf8');
  requireValue(host === `${new URL(issuer).hostname}$`, 'Clerk publishable key and issuer do not match.');
  requireValue(input.clerk.session_policy === 'default_session', 'Use the default live-verified Clerk session policy.');

  exact(input.stripe, [...PUBLIC_NAMES].map(name => name.replace('ENROLLMENT_STRIPE_', '').toLowerCase()), 'Stripe');
  const stripe = {};
  for (const [name, value] of Object.entries(input.stripe)) {
    const prefix = name === 'account_id' ? 'acct_' : name === 'portal_configuration_id' ? 'bpc_' : 'price_';
    requireValue(typeof value === 'string' && new RegExp(`^${prefix}[A-Za-z0-9_]+$`).test(value), 'Invalid Stripe catalog reference.');
    stripe[`ENROLLMENT_STRIPE_${name.toUpperCase()}`] = value;
  }
  if (stripe.ENROLLMENT_STRIPE_BASE_PRICE_ID && stripe.ENROLLMENT_STRIPE_ADDITIONAL_PRICE_ID) {
    requireValue(stripe.ENROLLMENT_STRIPE_BASE_PRICE_ID !== stripe.ENROLLMENT_STRIPE_ADDITIONAL_PRICE_ID,
      'First and additional human seats need distinct price references.');
  }

  exact(input.readiness, [...FLAGS], 'readiness');
  requireValue(Object.values(input.readiness).every(value => typeof value === 'boolean'), 'Readiness fields must be booleans.');
  const flags = Object.fromEntries([...FLAGS].map(name => [name, input.readiness[name] ?? false]));
  exact(input.qualification, ['source_commit', 'journey_sha256', 'production_sha256', 'staging_preflight'], 'qualification');
  requireValue(input.qualification.source_commit === input.source_commit, 'Qualification must bind the selected source.');
  const journeyQualified = /^[0-9a-f]{64}$/.test(input.qualification.journey_sha256 ?? '');
  let stagingPreflight;
  if (input.qualification.staging_preflight !== undefined) {
    requireValue(environment === 'staging' && !flags.stripe_acquisition_enabled && !flags.activation_available && !flags.production_qualified,
      'Development intake preflight cannot authorize acquisition, activation or production.');
    stagingPreflight = verifyStagingPreflight(input, input.qualification.staging_preflight, preflightTrustFile);
  }
  if (flags.enabled || flags.clerk_methods_verified) {
    requireValue(journeyQualified || stagingPreflight, 'Enabled registration needs a trusted configured-method staging intake preflight or full journey receipt.');
  }
  if (flags.stripe_acquisition_enabled || flags.activation_available) {
    requireValue(/^[0-9a-f]{64}$/.test(input.qualification.journey_sha256 ?? ''), 'Enabled enrollment needs its staged journey receipt.');
  }
  if (flags.production_qualified) {
    requireValue(environment === 'production' && /^[0-9a-f]{64}$/.test(input.qualification.production_sha256 ?? ''),
      'Production admission needs the matching production qualification receipt.');
  }
  requireValue(!flags.stripe_acquisition_enabled || flags.stripe_integration_enabled && flags.commercial_terms_verified,
    'Acquisition requires integration and agreed commercial terms.');
  requireValue(!flags.activation_available || flags.enabled && flags.provisioning_enabled && flags.stripe_acquisition_enabled && workspaceOrigins.length > 0,
    'Trial activation requires admitted enrollment, provisioning and billing.');
  requireValue(environment !== 'production' || !flags.enabled || flags.production_qualified,
    'Production registration requires actual production qualification.');

  exact(input.secret_references, [...SECRET_NAMES], 'secret references');
  const secretDefinitions = {};
  const secretEnv = {};
  for (const [name, value] of Object.entries(input.secret_references)) {
    requireValue(typeof value === 'string' && /^https:\/\/[a-z0-9-]+\.vault\.azure\.net\/secrets\/[A-Za-z0-9-]{1,127}\/[0-9a-f]{32}$/.test(value),
      'Secret inputs must be exact Key Vault versions, never credential values.');
    const secretName = `en-${hash(name).slice(0, 24)}`;
    secretDefinitions[secretName] = value;
    secretEnv[name] = secretName;
  }
  if (flags.enabled) {
    requireValue(secretEnv.ENROLLMENT_DATABASE_URL && secretEnv.ENROLLMENT_CLERK_SECRET_KEY && secretEnv.ENROLLMENT_INVITATION_SECRET,
      'Enabled registration needs database, Clerk and stable invitation secret references.');
  }
  if (flags.stripe_integration_enabled) {
    requireValue(secretEnv.ENROLLMENT_STRIPE_SECRET_KEY && secretEnv.ENROLLMENT_STRIPE_WEBHOOK_SECRET &&
      [...PUBLIC_NAMES].every(name => stripe[name]), 'Stripe integration needs the complete product/portal and secret references.');
  }
  requireValue(!flags.activation_available || secretEnv.ENROLLMENT_RUNTIME_ADMISSION_SECRET,
    'Trial activation requires the private runtime admission master reference.');
  const publicEnv = {
    ...Object.fromEntries(Object.entries(flags).map(([name, value]) => [`ENROLLMENT_${name.toUpperCase()}`, String(value)])),
    ENROLLMENT_DATA_MODE: environment === 'production' ? 'production' : 'synthetic',
    ENROLLMENT_PUBLIC_APP_ORIGIN: app,
    ENROLLMENT_ALLOWED_ORIGINS: JSON.stringify([app]),
    ENROLLMENT_ALLOWED_WORKSPACE_ORIGINS: JSON.stringify(workspaceOrigins),
    ENROLLMENT_CLERK_PUBLISHABLE_KEY: input.clerk.publishable_key,
    ENROLLMENT_CLERK_ISSUER: issuer,
    ENROLLMENT_CLERK_SESSION_POLICY: input.clerk.session_policy,
    ENROLLMENT_CLERK_AUTHORIZED_PARTIES: JSON.stringify([app]),
    ENROLLMENT_STRIPE_API_VERSION: '2025-09-30.clover',
    ENROLLMENT_STRIPE_LIVE_MODE: String(environment === 'production'),
    ...stripe,
  };
  const contract = {
    version: 1, environment, source_commit: input.source_commit, image: input.image,
    application_origin: app, enrollment_api_origin: api, api_prefix: '/enrollment/v1',
    signup_path: '/onboarding', sign_in_path: '/sign-in',
    pricing: { currency: 'usd', interval: 'month', first_human_cents: 30000,
      additional_human_cents: 10000, max_self_serve_humans: 10, trial_days: 14,
      paid_roles: 'every_human_user', above_limit: 'negotiated' },
    qualification: { ...input.qualification, ...(stagingPreflight ? { staging_preflight_sha256: stagingPreflight } : {}) },
    startup_command: ['uvicorn', 'cosmas_os.enrollment.api:app', '--host', '0.0.0.0', '--port', '8000'],
    migration_command: ['python', '-m', 'cosmas_os.enrollment.migration', 'upgrade'],
    rendered_only: true, deployed: false,
  };
  return {
    'public-env.json': publicEnv,
    'secret-references.json': { secret_definitions: secretDefinitions, secret_env: secretEnv },
    'web-build-env.json': { VITE_ENROLLMENT_ENABLED: 'true', VITE_ENROLLMENT_ACCOUNT_ONLY: 'true',
      VITE_ENROLLMENT_ACCOUNT_ORIGIN: app, VITE_ENROLLMENT_API_BASE: api,
      VITE_ENROLLMENT_CLERK_ISSUER: issuer, VITE_ENROLLMENT_CLERK_PUBLISHABLE_KEY: input.clerk.publishable_key,
      VITE_BUILD_SHA: input.source_commit },
    'workspace-account-env.json': Object.fromEntries(workspaceOrigins.map(workspace => [workspace, {
      CLERK_ISSUER: issuer,
      CLERK_JWKS_URL: `${issuer}/.well-known/jwks.json`,
      CLERK_SESSION_POLICY: 'enrollment_default',
      CLERK_AUDIENCE: '',
      CLERK_AUTHORIZED_PARTIES: [...new Set([app, workspace])].join(','),
      CORS_ALLOWED_ORIGINS: workspace,
      WORKSPACE_ENROLLMENT_MANAGED: 'true',
      WORKSPACE_ENROLLMENT_API_ORIGIN: api,
      WORKSPACE_ENROLLMENT_ORIGIN_ALLOWLIST: [...new Set([api, app])].join(','),
      WORKSPACE_ENROLLMENT_ACCOUNT_ORIGIN: app,
    }])),
    'deployment-contract.json': contract,
  };
}

async function main() {
  const args = process.argv.slice(2);
  requireValue([4, 6].includes(args.length) && args[0] === '--input' && args[2] === '--output' &&
    (args.length === 4 || args[4] === '--preflight-trust'),
    'Usage: node infra/enrollment/render.mjs --input reviewed.json --output new-directory [--preflight-trust protected-public-key.pem]');
  const input = JSON.parse(await readFile(resolve(args[1]), 'utf8'));
  const output = resolve(args[3]);
  const files = render(input, { preflightTrustFile: args.length === 6 ? resolve(args[5]) : undefined });
  await mkdir(output, { mode: 0o700 });
  const hashes = {};
  for (const [name, value] of Object.entries(files)) {
    const content = json(value);
    await writeFile(resolve(output, name), content, { mode: 0o600, flag: 'wx' });
    hashes[name] = hash(content);
  }
  await writeFile(resolve(output, 'RENDER.json'), json({ version: 1, source_commit: input.source_commit,
    files: hashes, rendered_only: true, deployed: false }), { mode: 0o600, flag: 'wx' });
  process.stdout.write(`Prepared ${Object.keys(files).length} enrollment configuration files; deployment remains separate.\n`);
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch(() => { process.stderr.write('Enrollment configuration could not be prepared; review the manifest and destination.\n'); process.exitCode = 1; });
}
