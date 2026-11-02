import {validateOperationalNativeIdentity} from '../desktop/native-identity-config.mjs';

export const REGISTERED_NATIVE_PROFILE_CONTRACT = 'cosmas-native-workspace-profile.v1';
export const ACTIVE_NATIVE_WORKSPACE_CONTRACT = 'cosmabot.native-active-workspace.v1';
const uuid = value => typeof value === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(value);
const id = (value, prefix) => typeof value === 'string' && value.length <= 255 && value.startsWith(prefix) && value.length > prefix.length && /^[A-Za-z0-9_]+$/.test(value);
const exact = (value, fields) => value && typeof value === 'object' && !Array.isArray(value) &&
  Object.keys(value).sort().join(',') === [...fields].sort().join(',') && Reflect.ownKeys(value).length === fields.length &&
  Object.values(Object.getOwnPropertyDescriptors(value)).every(property => 'value' in property && property.enumerable);
const unavailable = () => {throw new Error('Registered native practice is unavailable');};
const digest = value => typeof value === 'string' && /^[0-9a-f]{64}$/.test(value);

/** Public registry data only. Native code obtains and authenticates this response. */
export function validateRegisteredNativeProfile(value) {
  if (!exact(value, ['contract_version','client','nonce','native_origin','nativeIdentity','practice','workspace','data_mode','session','issued_at','expires_at']) ||
      value.contract_version !== REGISTERED_NATIVE_PROFILE_CONTRACT || !['apple','desktop'].includes(value.client) ||
      value.native_origin !== (value.client === 'apple' ? 'capacitor://localhost' : 'app://cosmas') ||
      !uuid(value.nonce) || value.data_mode !== 'synthetic' ||
      !exact(value.practice, ['practice_id','box_id']) || !uuid(value.practice.practice_id) || !uuid(value.practice.box_id) ||
      !exact(value.workspace, ['url','source_commit','image_sha256','workspace_proof_sha256','member_proof_sha256','native_qualification_sha256']) ||
      typeof value.workspace.source_commit !== 'string' || !/^[0-9a-f]{40}$/.test(value.workspace.source_commit) ||
      !['image_sha256','workspace_proof_sha256','member_proof_sha256','native_qualification_sha256'].every(field => digest(value.workspace[field])) ||
      !exact(value.session, ['issuer','subject','session_id']) || !id(value.session.subject, 'user_') ||
      !id(value.session.session_id, 'sess_') || !Number.isSafeInteger(value.issued_at) || !Number.isSafeInteger(value.expires_at) ||
      value.issued_at <= 0 || value.expires_at <= value.issued_at || value.expires_at - value.issued_at > 120) unavailable();
  let nativeIdentity, workspace;
  try {
    if(!exact(value.nativeIdentity, ['version','profile','client','apiOrigin','publishableKey','frontendOrigin','organizationId','audience']))unavailable();
    nativeIdentity = validateOperationalNativeIdentity(value.nativeIdentity, value.client, value.nativeIdentity?.apiOrigin);
    workspace = new URL(value.workspace.url);
  } catch { unavailable(); }
  // This candidate registers independent synthetic practices, never a platform
  // hostname or the existing beta's compiled connection. Production is separate.
  if (nativeIdentity.profile !== 'operational-staging-v1' ||
      !nativeIdentity.frontendOrigin.endsWith('.clerk.accounts.dev') ||
      value.session.issuer !== nativeIdentity.frontendOrigin ||
      workspace.protocol !== 'https:' || workspace.username || workspace.password || workspace.port ||
      workspace.search || workspace.hash || workspace.pathname !== '/chief' ||
      !/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.staging\.cosmas\.ai$/.test(workspace.hostname) ||
      ['onboarding.staging.cosmas.ai','enrollment-api.staging.cosmas.ai','api.staging.cosmas.ai'].includes(workspace.hostname) ||
      value.workspace.url !== workspace.origin + '/chief' ||
      nativeIdentity.apiOrigin !== 'https://api.' + workspace.hostname) unavailable();
  const practiceLabel=workspace.hostname.split('.')[0];
  if(uuid(practiceLabel)&&practiceLabel!==value.practice.practice_id)unavailable();
  // Native activation checks receipt freshness once. Expiry is not a recurring
  // agreement, billing or sign-in gate: active auth and revision fence requests.
  return Object.freeze({...value, nativeIdentity, session: Object.freeze({...value.session}),
    practice:Object.freeze({...value.practice}),workspace:Object.freeze({...value.workspace})});
}

/** The app host emits this fixed document-start snapshot after native activation. */
export function validateActiveNativeWorkspace(value) {
  if (!exact(value, ['contract_version','revision','profile']) || value.contract_version !== ACTIVE_NATIVE_WORKSPACE_CONTRACT || !uuid(value.revision)) unavailable();
  return Object.freeze({contract_version:ACTIVE_NATIVE_WORKSPACE_CONTRACT, revision:value.revision,
    profile:validateRegisteredNativeProfile(value.profile)});
}
