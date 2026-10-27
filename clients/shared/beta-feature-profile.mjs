import {exactHostedOrigin, resolveHostedWorkspace} from './hosted-workspace-config.mjs';

/** One client feature set. Server/account grants and action approvals remain separate. */
export const BETA_FEATURE_PROFILE = 'operational-beta-v1';
export const NATIVE_STAGING_FEATURE_PROFILE = 'first-owner-staging-v1';
export const STANDALONE_FEATURE_PROFILE = 'standalone-practice-v1';
const stagingFlags = ['VITE_AI_ACTIVITY_ENABLED', 'VITE_WORKSPACE_ROUTINES_ENABLED'];
export const BETA_FEATURE_FLAGS = Object.freeze([
  'VITE_AI_ACTIVITY_ENABLED', 'VITE_ATHENA_CONNECTION_ENABLED', 'VITE_ATHENA_VISIT_LINK_ENABLED',
  'VITE_CONNECTION_ONBOARDING_ENABLED', 'VITE_CORE_APPOINTMENT_SETUP_ENABLED',
  'VITE_CORE_CONNECTION_ENABLED', 'VITE_COSMANEURA_RECORD_ENABLED',
  'VITE_EFAX_INBOUND_ENABLED', 'VITE_EFAX_INBOUND_SOURCE_ENABLED',
  'VITE_FAX_INBOUND_ENABLED', 'VITE_FAX_INBOUND_SOURCE_ENABLED',
  'VITE_FINANCE_SETUP_ENABLED', 'VITE_FINANCE_WORK_ENABLED', 'VITE_INBOX_ENABLED',
  'VITE_INBOX_HANDOFF_ENABLED', 'VITE_MEMBERSHIP_WORK_ENABLED', 'VITE_PORTAL_SETUP_ENABLED',
  'VITE_PORTAL_WORK_ENABLED', 'VITE_VENDOR_SETUP_ENABLED', 'VITE_WORKSPACE_APPOINTMENTS_ENABLED',
  'VITE_WORKSPACE_CAPTURE_ENABLED', 'VITE_WORKSPACE_CAPTURE_NOTES_ENABLED',
  'VITE_WORKSPACE_CAPTURE_CORRECTIONS_ENABLED', 'VITE_WORKSPACE_CAPTURE_RECOVERY_ENABLED',
  'VITE_WORKSPACE_CAPTURE_SOURCE_ENABLED', 'VITE_WORKSPACE_CAPTURE_LONG_VISITS_ENABLED',
  'VITE_WORKSPACE_PREP_ENABLED', 'VITE_WORKSPACE_PREP_WORK_ENABLED',
  'VITE_WORKSPACE_GOOGLE_CONNECTION_ENABLED', 'VITE_WORKSPACE_GOOGLE_MESSAGE_ENABLED', 'VITE_WORKSPACE_GOOGLE_CALENDAR_ENABLED', 'VITE_WORKSPACE_MICROSOFT_CONNECTION_ENABLED', 'VITE_WORKSPACE_ROUTINES_ENABLED',
  'VITE_WORKSPACE_SCHEDULING_ENABLED', 'VITE_WORKSPACE_SCHEDULING_LOGIN_ENABLED',
  'VITE_WORKSPACE_SCHEDULING_ENROLLMENT_ENABLED',
]);
const foundations = ['VITE_WORKSPACE_ENABLED', 'VITE_WORKSPACE_AUTHENTICATED_ENABLED', 'VITE_WORKSPACE_HOSTED_ENABLED'];
const forbidden = ['VITE_DESKTOP_SYNTHETIC_ENABLED', 'VITE_WORKSPACE_APPLE_LOCAL_TRANSPORT_ENABLED', 'VITE_COMPACT_LOCAL'];
const captureFlags = ['VITE_CAPTURE_E2E_MICROPHONE_ENABLED', 'VITE_CAPTURE_IOS_NATIVE_PCM_ENABLED'];
const patientSetupFlag = 'VITE_WORKSPACE_SCHEDULING_PATIENT_SETUP_ENABLED';
// These reviewed consumers require separate matching API contracts. Omission
// preserves existing releases; a retained native environment must opt in.
const pilotFlags = ['VITE_MESSAGES_ENABLED', 'VITE_EHR_READ_ENABLED',
  'VITE_CALENDAR_IMPORT_ENABLED', 'VITE_MICROSOFT_MESSAGE_ENABLED'];
// These clients use CosmaBot's own API. Provider accounts and server grants
// remain separately configured; this list never activates an external service.
export const STANDALONE_FEATURE_FLAGS = Object.freeze([
  'VITE_AI_ACTIVITY_ENABLED', 'VITE_CONNECTION_ONBOARDING_ENABLED',
  'VITE_EFAX_INBOUND_ENABLED', 'VITE_EFAX_INBOUND_SOURCE_ENABLED',
  'VITE_FAX_INBOUND_ENABLED', 'VITE_FAX_INBOUND_SOURCE_ENABLED',
  'VITE_INBOX_ENABLED', 'VITE_INBOX_HANDOFF_ENABLED', 'VITE_VENDOR_SETUP_ENABLED',
  'VITE_WORKSPACE_APPOINTMENTS_ENABLED', 'VITE_WORKSPACE_GOOGLE_CONNECTION_ENABLED',
  'VITE_WORKSPACE_GOOGLE_MESSAGE_ENABLED', 'VITE_WORKSPACE_GOOGLE_CALENDAR_ENABLED',
  'VITE_WORKSPACE_MICROSOFT_CONNECTION_ENABLED', 'VITE_WORKSPACE_ROUTINES_ENABLED',
  'VITE_WORKSPACE_SCHEDULING_ENABLED', 'VITE_WORKSPACE_SCHEDULING_LOGIN_ENABLED',
  'VITE_WORKSPACE_SCHEDULING_ENROLLMENT_ENABLED', ...pilotFlags,
]);
// The same existing platform hosts are reserved by infra/beta/environment.
// This rejects known collisions, not a claim that arbitrary public DNS proves
// deployment isolation; resource ownership must also be reviewed before use.
const platformHosts = new Set(['app.cosmaneura.com', 'staging-app.cosmaneura.com',
  'chat.cosmaneura.com', 'staging-chat.cosmaneura.com']);
const knownGates = new Set([patientSetupFlag, ...pilotFlags, ...BETA_FEATURE_FLAGS, ...foundations, ...forbidden, ...captureFlags,
  'VITE_WORKSPACE_NATIVE_AUTH_ENABLED', 'VITE_WORKSPACE_DESKTOP_AUTH_ENABLED']);
const fail = message => { throw new Error(`Beta feature profile refused: ${message}`); };
function set(env, name, value) {
  if (env[name] !== undefined && env[name] !== '' && env[name] !== value) fail(`${name} conflicts with ${env.VITE_WORKSPACE_FEATURE_PROFILE}`);
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
  const staging = input.VITE_WORKSPACE_FEATURE_PROFILE === NATIVE_STAGING_FEATURE_PROFILE;
  const standalone = input.VITE_WORKSPACE_FEATURE_PROFILE === STANDALONE_FEATURE_PROFILE;
  if (!staging && !standalone && input.VITE_WORKSPACE_FEATURE_PROFILE !== BETA_FEATURE_PROFILE) fail(`select a supported VITE_WORKSPACE_FEATURE_PROFILE`);
  const env = {...input};
  // Catch stale recipes and misspelled gates instead of silently shipping partial UI.
  for (const key of Object.keys(env)) {
    if (key.startsWith('VITE_') && key.endsWith('_ENABLED') && !knownGates.has(key)) fail(`unknown feature gate ${key}`);
  }
  for (const key of pilotFlags) if (Object.hasOwn(env, key)) {
    if (!['true', 'false'].includes(env[key])) fail(`select an explicit true or false for ${key}`);
    if (staging && env[key] === 'true') fail('pilot features are disabled for first-owner staging');
  }
  set(env, 'VITE_COSMAS_ENV', 'early_adopter_beta');
  for (const key of foundations) set(env, key, 'true');
  for (const key of BETA_FEATURE_FLAGS) set(env, key,
    (standalone ? STANDALONE_FEATURE_FLAGS.includes(key) : !staging || stagingFlags.includes(key)) ? 'true' : 'false');
  if (standalone) for (const key of pilotFlags) set(env, key, 'true');
  for (const key of forbidden) set(env, key, 'false');
  // Receiver remains unqualified; ship the correspondence capability dark.
  set(env, patientSetupFlag, 'false');
  const client = env.VITE_WORKSPACE_HOSTED_CLIENT;
  if (!['web', 'desktop', 'apple'].includes(client)) fail('select the web, desktop or apple client');
  if (staging && (client === 'web' || env.VITE_WORKSPACE_DATA_MODE !== 'synthetic')) fail('first-owner staging requires a native client and synthetic data');
  if (standalone && env.VITE_WORKSPACE_DATA_MODE !== 'synthetic') fail('standalone practice requires explicit synthetic data');
  set(env, 'VITE_WORKSPACE_NATIVE_AUTH_ENABLED', client === 'apple' ? 'true' : 'false');
  set(env, 'VITE_WORKSPACE_DESKTOP_AUTH_ENABLED', client === 'desktop' ? 'true' : 'false');
  const hosted = resolveHostedWorkspace(env);
  if (!hosted) fail('hosted identity, data mode or origin configuration is incomplete or inconsistent');
  if (standalone) {
    for (const origin of [hosted.apiOrigin, ...(client === 'web' ? [hosted.pageOrigin] : [])]) {
      if (platformHosts.has(new URL(origin).hostname)) fail('standalone practice requires dedicated CosmaBot API and web origins');
    }
    if (checkPublishableKey && !/^pk_(test|live)_\S+$/.test(env.VITE_CLERK_PUBLISHABLE_KEY ?? '')) fail('standalone practice requires an explicit Clerk public identity');
    set(env, 'VITE_COSMANEURA_WEB_ORIGIN', '');
    set(env, 'VITE_CAPTURE_UPLOAD_ORIGINS', '');
    set(env, 'VITE_WORKSPACE_CAPTURE_MODE', 'disabled');
    for (const key of captureFlags) set(env, key, 'false');
    return {env: Object.freeze(env), manifest: {version: 1, profile: STANDALONE_FEATURE_PROFILE, ...hosted,
      enabledFlags: [...STANDALONE_FEATURE_FLAGS], disabledFlags: [...knownGates].filter(key => env[key] === 'false'),
      authentication: 'verified_hosted_identity', platformAccess: 'disabled',
      captureMode: 'disabled', captureUploadOrigins: [], coreWebOrigin: '', athenaAccess: 'disabled'}};
  }
  if (staging) {
    set(env, 'VITE_COSMANEURA_WEB_ORIGIN', '');
    set(env, 'VITE_CAPTURE_UPLOAD_ORIGINS', '');
    set(env, 'VITE_WORKSPACE_CAPTURE_MODE', 'disabled');
    for (const key of captureFlags) set(env, key, 'false');
    return {env: Object.freeze(env), manifest: {version: 1, profile: NATIVE_STAGING_FEATURE_PROFILE, ...hosted,
      enabledFlags: [...stagingFlags], captureMode: 'disabled', captureUploadOrigins: [],
      coreWebOrigin: '', athenaAccess: 'read_only'}};
  }
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
    enabledFlags: [...BETA_FEATURE_FLAGS, ...pilotFlags.filter(key => env[key] === 'true')], captureMode, captureUploadOrigins: uploadOrigins,
    coreWebOrigin: env.VITE_COSMANEURA_WEB_ORIGIN, athenaAccess: 'read_only'};
  return {env: Object.freeze(env), manifest};
}

/** Validate emitted public configuration without requiring an authentication key. */
export function validateBetaFeatureManifest(manifest) {
  if (!manifest || !Array.isArray(manifest.captureUploadOrigins) || !Array.isArray(manifest.enabledFlags)) fail('feature manifest is missing');
  const resolved = resolveProfile({
    VITE_WORKSPACE_FEATURE_PROFILE: manifest.profile,
    VITE_WORKSPACE_HOSTED_CLIENT: manifest.client, VITE_WORKSPACE_DATA_MODE: manifest.dataMode,
    VITE_WORKSPACE_HOSTED_API_ORIGIN: manifest.apiOrigin, VITE_API_BASE: manifest.apiBase,
    VITE_WORKSPACE_WEB_ORIGIN: manifest.client === 'web' ? manifest.pageOrigin : '',
    VITE_WORKSPACE_CAPTURE_MODE: manifest.captureMode,
    VITE_CAPTURE_UPLOAD_ORIGINS: manifest.captureUploadOrigins.join(','),
    VITE_COSMANEURA_WEB_ORIGIN: manifest.coreWebOrigin,
    ...Object.fromEntries(pilotFlags.filter(key => manifest.enabledFlags.includes(key)).map(key => [key, 'true'])),
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
  if (manifest.profile === NATIVE_STAGING_FEATURE_PROFILE && expected.microphoneCapture === true) fail('native capture is disabled for first-owner staging');
  if (manifest.profile === STANDALONE_FEATURE_PROFILE && expected.microphoneCapture === true) fail('native capture is disabled for standalone practice');
  if (expected.client === 'desktop' && expected.microphoneCapture !== (manifest.captureMode === 'browser_microphone') ||
      expected.client === 'apple' && manifest.captureMode === 'ios_native' &&
      (!expected.renewableNativeCapture || !expected.nativeRendererRecovery ||
       (manifest.dataMode === 'authorized_beta' || expected.deviceCustody === true ?
         expected.deviceCustody !== true || expected.simulatorCustody === true : !expected.simulatorCustody))) fail('native capture support differs from the web build');
  return manifest;
}
