import {exactHostedOrigin, resolveHostedWorkspace} from './hosted-workspace-config.mjs';

/** One client feature set. Server/account grants and action approvals remain separate. */
export const BETA_FEATURE_PROFILE = 'operational-beta-v1';
export const BETA_FEATURE_FLAGS = Object.freeze([
  'VITE_AI_ACTIVITY_ENABLED', 'VITE_ATHENA_CONNECTION_ENABLED', 'VITE_ATHENA_VISIT_LINK_ENABLED',
  'VITE_CONNECTION_ONBOARDING_ENABLED', 'VITE_CORE_APPOINTMENT_SETUP_ENABLED',
  'VITE_CORE_CONNECTION_ENABLED', 'VITE_COSMANEURA_RECORD_ENABLED',
  'VITE_FINANCE_SETUP_ENABLED', 'VITE_FINANCE_WORK_ENABLED', 'VITE_INBOX_ENABLED',
  'VITE_INBOX_HANDOFF_ENABLED', 'VITE_MEMBERSHIP_WORK_ENABLED', 'VITE_PORTAL_SETUP_ENABLED',
  'VITE_PORTAL_WORK_ENABLED', 'VITE_VENDOR_SETUP_ENABLED', 'VITE_WORKSPACE_APPOINTMENTS_ENABLED',
  'VITE_WORKSPACE_CAPTURE_ENABLED', 'VITE_WORKSPACE_CAPTURE_NOTES_ENABLED',
  'VITE_WORKSPACE_CAPTURE_CORRECTIONS_ENABLED', 'VITE_WORKSPACE_CAPTURE_RECOVERY_ENABLED',
  'VITE_WORKSPACE_CAPTURE_SOURCE_ENABLED', 'VITE_WORKSPACE_CAPTURE_LONG_VISITS_ENABLED',
  'VITE_WORKSPACE_PREP_ENABLED', 'VITE_WORKSPACE_PREP_WORK_ENABLED',
  'VITE_WORKSPACE_GOOGLE_CONNECTION_ENABLED', 'VITE_WORKSPACE_MICROSOFT_CONNECTION_ENABLED', 'VITE_WORKSPACE_ROUTINES_ENABLED',
  'VITE_WORKSPACE_SCHEDULING_ENABLED', 'VITE_WORKSPACE_SCHEDULING_LOGIN_ENABLED',
  'VITE_WORKSPACE_SCHEDULING_ENROLLMENT_ENABLED',
]);
const foundations = ['VITE_WORKSPACE_ENABLED', 'VITE_WORKSPACE_AUTHENTICATED_ENABLED', 'VITE_WORKSPACE_HOSTED_ENABLED'];
const forbidden = ['VITE_DESKTOP_SYNTHETIC_ENABLED', 'VITE_WORKSPACE_APPLE_LOCAL_TRANSPORT_ENABLED', 'VITE_COMPACT_LOCAL'];
const captureFlags = ['VITE_CAPTURE_E2E_MICROPHONE_ENABLED', 'VITE_CAPTURE_IOS_NATIVE_PCM_ENABLED'];
const knownGates = new Set([...BETA_FEATURE_FLAGS, ...foundations, ...forbidden, ...captureFlags,
  'VITE_WORKSPACE_NATIVE_AUTH_ENABLED', 'VITE_WORKSPACE_DESKTOP_AUTH_ENABLED']);
const fail = message => { throw new Error(`Beta feature profile refused: ${message}`); };
function set(env, name, value) {
  if (env[name] !== undefined && env[name] !== '' && env[name] !== value) fail(`${name} conflicts with ${BETA_FEATURE_PROFILE}`);
  env[name] = value;
}
function uploads(value) {
  if (typeof value !== 'string') fail('VITE_CAPTURE_UPLOAD_ORIGINS is required');
  const origins = value.split(',');
  if (!origins.length || origins.length > 4 || new Set(origins).size !== origins.length ||
      !origins.every(exactHostedOrigin)) fail('capture requires one to four distinct exact HTTPS upload origins');
  return origins;
}

export function resolveBetaFeatureProfile(input) {
  return resolveProfile(input, true);
}

function resolveProfile(input, checkPublishableKey) {
  if (input.VITE_WORKSPACE_FEATURE_PROFILE !== BETA_FEATURE_PROFILE) fail(`select VITE_WORKSPACE_FEATURE_PROFILE=${BETA_FEATURE_PROFILE}`);
  const env = {...input};
  // Catch stale recipes and misspelled gates instead of silently shipping partial UI.
  for (const key of Object.keys(env)) {
    if (key.startsWith('VITE_') && key.endsWith('_ENABLED') && !knownGates.has(key)) fail(`unknown feature gate ${key}`);
  }
  set(env, 'VITE_COSMAS_ENV', 'early_adopter_beta');
  for (const key of [...foundations, ...BETA_FEATURE_FLAGS]) set(env, key, 'true');
  for (const key of forbidden) set(env, key, 'false');
  const client = env.VITE_WORKSPACE_HOSTED_CLIENT;
  if (!['web', 'desktop', 'apple'].includes(client)) fail('select the web, desktop or apple client');
  set(env, 'VITE_WORKSPACE_NATIVE_AUTH_ENABLED', client === 'apple' ? 'true' : 'false');
  set(env, 'VITE_WORKSPACE_DESKTOP_AUTH_ENABLED', client === 'desktop' ? 'true' : 'false');
  const hosted = resolveHostedWorkspace(env);
  if (!hosted) fail('hosted identity, data mode or origin configuration is incomplete or inconsistent');
  if (checkPublishableKey && client === 'web' && !(hosted.dataMode === 'synthetic' ? /^pk_(test|live)_\S+$/ : /^pk_live_\S+$/).test(env.VITE_CLERK_PUBLISHABLE_KEY ?? '')) fail('a Clerk publishable key is required for the selected web data profile');
  if (!exactHostedOrigin(env.VITE_COSMANEURA_WEB_ORIGIN) ||
      !/[a-z]/.test(new URL(env.VITE_COSMANEURA_WEB_ORIGIN).hostname.split('.').at(-1)[0])) fail('an exact Core web origin is required');
  const captureMode = env.VITE_WORKSPACE_CAPTURE_MODE;
  if (!['synthetic', 'browser_microphone', 'ios_native'].includes(captureMode) ||
      captureMode === 'ios_native' && client !== 'apple' ||
      captureMode === 'browser_microphone' && client === 'apple' ||
      captureMode === 'synthetic' && hosted.dataMode !== 'synthetic') fail('select a supported capture mode for this client/data profile');
  set(env, captureFlags[0], captureMode === 'browser_microphone' ? 'true' : 'false');
  set(env, captureFlags[1], captureMode === 'ios_native' ? 'true' : 'false');
  const uploadOrigins = uploads(env.VITE_CAPTURE_UPLOAD_ORIGINS);
  const manifest = {version: 1, profile: BETA_FEATURE_PROFILE, ...hosted,
    enabledFlags: [...BETA_FEATURE_FLAGS], captureMode, captureUploadOrigins: uploadOrigins,
    coreWebOrigin: env.VITE_COSMANEURA_WEB_ORIGIN, athenaAccess: 'read_only'};
  return {env: Object.freeze(env), manifest};
}

/** Validate emitted public configuration without requiring an authentication key. */
export function validateBetaFeatureManifest(manifest) {
  if (!manifest || !Array.isArray(manifest.captureUploadOrigins)) fail('feature manifest is missing');
  const resolved = resolveProfile({
    VITE_WORKSPACE_FEATURE_PROFILE: manifest.profile,
    VITE_WORKSPACE_HOSTED_CLIENT: manifest.client, VITE_WORKSPACE_DATA_MODE: manifest.dataMode,
    VITE_WORKSPACE_HOSTED_API_ORIGIN: manifest.apiOrigin, VITE_API_BASE: manifest.apiBase,
    VITE_WORKSPACE_WEB_ORIGIN: manifest.client === 'web' ? manifest.pageOrigin : '',
    VITE_WORKSPACE_CAPTURE_MODE: manifest.captureMode,
    VITE_CAPTURE_UPLOAD_ORIGINS: manifest.captureUploadOrigins.join(','),
    VITE_COSMANEURA_WEB_ORIGIN: manifest.coreWebOrigin,
  }, false).manifest;
  const canonical = value => JSON.stringify(value, Object.keys(value).sort());
  // Arrays are ordered public configuration; no extra or omitted keys accepted.
  if (canonical(manifest) !== canonical(resolved)) fail('feature manifest is incomplete or inconsistent');
  return manifest;
}

/** Called by both native composers before any output directory is created. */
export function validateNativeBetaProfile(manifest, expected) {
  validateBetaFeatureManifest(manifest);
  if (!expected || !['desktop', 'apple'].includes(expected.client)) fail('native configuration is missing');
  if (manifest.client !== expected.client ||
      manifest.apiOrigin !== expected.apiOrigin || manifest.coreWebOrigin !== expected.coreWebOrigin ||
      JSON.stringify(manifest.captureUploadOrigins) !== JSON.stringify(expected.captureUploadOrigins)) fail('native and web feature/origin profiles differ');
  if (expected.client === 'desktop' && expected.microphoneCapture !== (manifest.captureMode === 'browser_microphone') ||
      expected.client === 'apple' && manifest.captureMode === 'ios_native' &&
      (!expected.renewableNativeCapture || !expected.nativeRendererRecovery ||
       (manifest.dataMode === 'authorized_beta' || expected.deviceCustody === true ?
         expected.deviceCustody !== true || expected.simulatorCustody === true : !expected.simulatorCustody))) fail('native capture support differs from the web build');
  return manifest;
}
