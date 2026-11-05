/**
 * Reviewed public CosmasNativePracticeConnection Infos for Mac desktop host.
 * Mirrors scripts/native_practice_connection_info.py closed staging/production rules.
 * Public fields only — never accepts secrets, tokens, or private keys.
 */

const ORIGIN_HOST = /^(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$/;
const PRODUCTION_FRONTEND = 'https://clerk.cosmas.ai';
const PRODUCTION_ACCOUNT = 'https://enrollment-api.cosmas.ai';
const PRODUCTION_POLICY = 'practice-uuid-production-v1';
const STAGING_POLICIES = new Set(['exact', 'synthetic-practice-uuid-staging-v1']);

function exactOrigin(value) {
  if (typeof value !== 'string' || Buffer.byteLength(value, 'utf8') > 253) {
    throw new Error('Use an exact canonical HTTPS origin without a path or port.');
  }
  let url;
  try { url = new URL(value); } catch {
    throw new Error('Use an exact canonical HTTPS origin without a path or port.');
  }
  if (url.protocol !== 'https:' || value !== url.origin || url.port ||
      !ORIGIN_HOST.test(url.hostname) || url.hostname.endsWith('.localhost') ||
      /^\d+(?:\.\d+){3}$/.test(url.hostname)) {
    throw new Error('Use an exact canonical HTTPS origin without a path or port.');
  }
  return value;
}

function practicePublishableKey(key, host, {live}) {
  const prefix = live ? 'pk_live_' : 'pk_test_';
  if (typeof key !== 'string' || Buffer.byteLength(key, 'utf8') > 1024 || !key.startsWith(prefix) ||
      !/^[A-Za-z0-9+/_-]+={0,2}$/.test(key.slice(prefix.length))) {
    throw new Error('The account realm requires its exact Clerk frontend and public key.');
  }
  const encoded = key.slice(prefix.length).replace(/-/g, '+').replace(/_/g, '/');
  let decoded;
  try {
    decoded = Buffer.from(encoded + '='.repeat((4 - encoded.length % 4) % 4), 'base64').toString('utf8');
  } catch {
    throw new Error('The account public key must encode its exact Clerk frontend.');
  }
  if (decoded !== `${host}$`) {
    throw new Error('The account public key must encode its exact Clerk frontend.');
  }
}

function realmAndPolicy(value) {
  const realm = value.realm;
  if (!realm || typeof realm !== 'object' || Array.isArray(realm) ||
      Object.keys(realm).sort().join(',') !==
        'audience,frontendOrigin,keychainNamespace,profile,publishableKey' ||
      typeof realm.keychainNamespace !== 'string' ||
      !/^[a-f0-9]{64}$/.test(realm.keychainNamespace)) {
    throw new Error('The explicit account realm requires a reviewed profile and namespace.');
  }
  const frontend = exactOrigin(realm.frontendOrigin);
  const host = frontend.slice('https://'.length);
  if (Buffer.byteLength(host, 'utf8') > 245) {
    throw new Error('The account realm requires its exact Clerk frontend and public key.');
  }
  const policy = value.registeredPracticeOrigins ?? 'exact';
  const {profile, audience} = realm;
  if (profile === 'operational-staging-v1') {
    if (audience !== '' || !host.endsWith('.clerk.accounts.dev') ||
        typeof policy !== 'string' || !STAGING_POLICIES.has(policy)) {
      throw new Error('Use the reviewed exact or synthetic practice UUID origin policy.');
    }
    practicePublishableKey(realm.publishableKey, host, {live: false});
    return policy;
  }
  if (profile === 'operational-beta-v1') {
    if (typeof audience !== 'string' || !audience || Buffer.byteLength(audience, 'utf8') > 255 ||
        [...audience].some(ch => ch.charCodeAt(0) < 33 || ch.charCodeAt(0) > 126) ||
        frontend !== PRODUCTION_FRONTEND || value.accountOrigin !== PRODUCTION_ACCOUNT ||
        policy !== PRODUCTION_POLICY) {
      throw new Error(
        'Production native practice requires enrollment-api.cosmas.ai, clerk.cosmas.ai, ' +
        'a non-empty Clerk audience, and practice-uuid-production-v1.',
      );
    }
    practicePublishableKey(realm.publishableKey, host, {live: true});
    return policy;
  }
  throw new Error('The explicit account realm requires the native staging or production profile.');
}

/** Validate explicit public Infos JSON. Does not enable a missing option. */
export function validateNativePracticeInfos(value) {
  const required = new Set(['enabled', 'accountOrigin', 'realm', 'apiOrigins']);
  if (!value || typeof value !== 'object' || Array.isArray(value) || typeof value.enabled !== 'boolean') {
    throw new Error('Native practice configuration must match the owned Info schema.');
  }
  const keys = new Set(Object.keys(value));
  for (const key of required) {
    if (!keys.has(key)) throw new Error('Native practice configuration must match the owned Info schema.');
  }
  for (const key of keys) {
    if (!required.has(key) && key !== 'registeredPracticeOrigins' && key !== 'googleConnection') {
      throw new Error('Native practice configuration must match the owned Info schema.');
    }
  }
  exactOrigin(value.accountOrigin);
  const policy = realmAndPolicy(value);
  const origins = value.apiOrigins;
  if (!Array.isArray(origins) || origins.length > 32 || (policy === 'exact' && origins.length === 0)) {
    throw new Error('Use the reviewed exact, synthetic staging, or production practice UUID origin policy.');
  }
  const checked = origins.map(exactOrigin);
  if (new Set(checked).size !== checked.length) {
    throw new Error('Duplicate native API origins are not permitted.');
  }
  if ('googleConnection' in value) {
    const pair = value.googleConnection;
    if (!pair || typeof pair !== 'object' || Object.keys(pair).sort().join(',') !== 'callbackURI,clientID' ||
        typeof pair.clientID !== 'string' ||
        !/^[A-Za-z0-9_-]{1,200}\.apps\.googleusercontent\.com$/.test(pair.clientID) ||
        pair.callbackURI !== `${value.accountOrigin}/connections/google/callback`) {
      throw new Error(
        'Native practice Google requires an exact public client and the pinned account-service callback.',
      );
    }
  }
  return structuredClone(value);
}

export function isProductionNativePracticeInfos(infos) {
  return infos?.realm?.profile === 'operational-beta-v1';
}

/** Clear, fail-closed reason when production Infos is bound without a signed practice helper. */
export function productionPracticeHelperRequiredMessage() {
  return 'Production Mac practice needs the signed CosmasNativePracticeConnection helper ' +
    '(Clerk account realm on clerk.cosmas.ai). Electron fake/local enrollment cannot open real-data practices.';
}
