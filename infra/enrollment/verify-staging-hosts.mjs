// Read-only DNS/TLS/route qualification for the fixed staging account hosts.
// This receipt is never account, billing, practice or production admission.
import { readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
const APP = 'https://onboarding.staging.cosmas.ai';
const API = 'https://enrollment-api.staging.cosmas.ai';
const requireValue = (condition, message) => { if (!condition) throw new Error(message); };

export async function verifyStagingHosts(contract, publicEnv, request = fetch) {
  requireValue(contract.environment === 'staging' && contract.application_origin === APP &&
    contract.enrollment_api_origin === API && /^[0-9a-f]{40}$/.test(contract.source_commit),
    'Use the exact separate staging account/API deployment contract.');
  requireValue(publicEnv.ENROLLMENT_PUBLIC_APP_ORIGIN === APP &&
    publicEnv.ENROLLMENT_CLERK_PUBLISHABLE_KEY?.startsWith('pk_test_') &&
    publicEnv.ENROLLMENT_DATA_MODE === 'synthetic', 'Use the matching public Development Clerk configuration.');
  async function get(origin, path, statuses = [200], json = false, mediaTypes = []) {
    const url = origin + path;
    const response = await request(url, { redirect: 'error', credentials: 'omit', cache: 'no-store',
      headers: { Accept: json ? 'application/json' : '*/*', ...(origin === API ? { Origin: APP } : {}) },
      signal: AbortSignal.timeout(10000) });
    requireValue(!response.redirected && (!response.url || response.url === url) && statuses.includes(response.status),
      'The exact owned HTTPS route is unavailable or redirected.');
    const mediaType = response.headers.get('content-type')?.split(';')[0];
    requireValue(!mediaTypes.length || mediaTypes.includes(mediaType), 'The browser route has the wrong MIME type.');
    if (origin === API) {
      requireValue(response.headers.get('access-control-allow-origin') === APP,
        'The enrollment API must admit exactly the separate account origin.');
      requireValue(response.headers.get('cache-control')?.split(',').some(value => value.trim() === 'no-store'),
        'Enrollment public configuration must not be cached.');
    }
    const body = await response.text();
    requireValue(Buffer.byteLength(body) <= 2_000_000, 'Unexpected hosting response size.');
    if (json) {
      requireValue(mediaType === 'application/json', 'Expected public JSON.');
      return JSON.parse(body);
    }
    return body;
  }
  requireValue((await get(APP, '/healthz')).trim() === 'ok', 'The account web health route is not nginx health.');
  const manifest = await get(APP, '/cosmas-enrollment-build.json', [200], true);
  requireValue(manifest.kind === 'enrollment-account' && manifest.account_only === true &&
    manifest.clinical_workspace === false && manifest.source_commit === contract.source_commit &&
    manifest.application_origin === APP && manifest.enrollment_api_origin === API &&
    manifest.clerk_issuer === publicEnv.ENROLLMENT_CLERK_ISSUER, 'The deployed account image is stale or incorrectly bound.');
  let shell;
  for (const path of ['/', '/onboarding', '/sign-in', '/sign-up', '/workspaces']) {
    const page = await get(APP, path, [200], false, ['text/html']);
    requireValue(page.includes('CosmaBot · Account setup') && page.includes('id="root"') &&
      /src="\/assets\/[A-Za-z0-9._-]+\.js"/.test(page), 'The account SPA route is not serving the account build.');
    requireValue(shell === undefined || shell === page, 'An account bookmark served a different workspace shell.');
    shell = page;
  }
  const asset = /src="(\/assets\/[A-Za-z0-9._-]+\.js)"/.exec(shell)[1];
  requireValue((await get(APP, asset, [200], false, ['application/javascript', 'text/javascript'])).length > 0,
    'The account JavaScript asset is unavailable.');
  const health = await get(API, '/health', [200], true);
  requireValue(health.component === 'enrollment' && health.data_mode === 'synthetic', 'The API is not the synthetic enrollment service.');
  const operational = await get(API, '/operational-ready', [200], true);
  requireValue(operational.component === 'enrollment' && operational.operational_ready === true,
    'The enrollment API cannot reach its own migrated database.');
  const config = await get(API, '/enrollment/v1/config', [200], true);
  requireValue(config.contract_version === 'enrollment.v1' && config.data_mode === 'synthetic' &&
    config.clerk_publishable_key === publicEnv.ENROLLMENT_CLERK_PUBLISHABLE_KEY &&
    config.enabled === (publicEnv.ENROLLMENT_ENABLED === 'true') &&
    config.activation_available === (publicEnv.ENROLLMENT_ACTIVATION_AVAILABLE === 'true'),
    'The public account API configuration differs from the selected closed/open staging contract.');
  return { version: 1, kind: 'enrollment-staging-hosts', source_commit: contract.source_commit,
    application_origin: APP, enrollment_api_origin: API, dns_tls_and_routes_checked: true,
    enrollment_enabled: config.enabled, activation_available: config.activation_available,
    central_database_operational: true,
    account_paths: ['/', '/onboarding', '/sign-in', '/sign-up', '/workspaces'],
    staged_customer_journey_qualified: false, production_qualified: false };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const args = process.argv.slice(2);
    requireValue(args.length === 4 && args[0] === '--rendered' && args[2] === '--output',
      'Usage: node infra/enrollment/verify-staging-hosts.mjs --rendered DIRECTORY --output NEW-RECEIPT.json');
    const directory = resolve(args[1]);
    const contract = JSON.parse(await readFile(resolve(directory, 'deployment-contract.json'), 'utf8'));
    const publicEnv = JSON.parse(await readFile(resolve(directory, 'public-env.json'), 'utf8'));
    const receipt = await verifyStagingHosts(contract, publicEnv);
    await writeFile(resolve(args[3]), JSON.stringify(receipt, null, 2) + '\n', { mode: 0o600, flag: 'wx' });
    process.stdout.write('The fixed staging HTTPS hosts and account routes passed; customer journey qualification remains separate.\n');
  } catch {
    process.stderr.write('Staging host verification failed; keep activation closed and check DNS, certificates, exact images and public account bindings.\n');
    process.exitCode = 1;
  }
}
