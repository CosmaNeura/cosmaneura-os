import {validateOperationalNativeIdentity} from './operational-native-identity.mjs';

export const REGISTERED_NATIVE_PROFILE_CONTRACT = 'cosmas-native-workspace-profile.v1';
export const ACTIVE_NATIVE_WORKSPACE_CONTRACT = 'cosmabot.native-active-workspace.v1';
const uuid = value => typeof value === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(value);
const id = (value, prefix) => typeof value === 'string' && value.length <= 255 && value.startsWith(prefix) && value.length > prefix.length && /^[A-Za-z0-9_]+$/.test(value);
const exact = (value, fields) => value && typeof value === 'object' && !Array.isArray(value) &&
  Object.keys(value).sort().join(',') === [...fields].sort().join(',') && Reflect.ownKeys(value).length === fields.length &&
  Object.values(Object.getOwnPropertyDescriptors(value)).every(property => 'value' in property && property.enumerable);
const unavailable = () => {throw new Error('Registered native practice is unavailable');};
const digest = value => typeof value === 'string' && /^[0-9a-f]{64}$/.test(value);
/** Each registered data mode admits exactly one identity realm and workspace domain. */
const REGISTERED_ENVIRONMENTS = Object.freeze({
  synthetic: Object.freeze({profile: 'operational-staging-v1', domain: 'staging.cosmas.ai',
    issuer: origin => origin.endsWith('.clerk.accounts.dev'),
    reserved: ['onboarding.staging.cosmas.ai', 'enrollment-api.staging.cosmas.ai', 'api.staging.cosmas.ai']}),
  authorized_beta: Object.freeze({profile: 'operational-beta-v1', domain: 'workspace.cosmas.ai',
    issuer: origin => origin === 'https://clerk.cosmas.ai', reserved: ['api.workspace.cosmas.ai']}),
});

/** Public registry data only. Native code obtains and authenticates this response. */
export function validateRegisteredNativeProfile(value) {
  if (!exact(value, ['contract_version','client','nonce','native_origin','nativeIdentity','practice','workspace','data_mode','session','issued_at','expires_at']) ||
      value.contract_version !== REGISTERED_NATIVE_PROFILE_CONTRACT || !['apple','desktop'].includes(value.client) ||
      value.native_origin !== (value.client === 'apple' ? 'capacitor://localhost' : 'app://cosmas') ||
      !uuid(value.nonce) || !Object.hasOwn(REGISTERED_ENVIRONMENTS, value.data_mode) ||
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
  // Registered practices only: synthetic staging, or real-data production with
  // the production identity realm. Never a platform hostname or another realm.
  const environment = REGISTERED_ENVIRONMENTS[value.data_mode];
  const domain = '.' + environment.domain;
  if (nativeIdentity.profile !== environment.profile ||
      !environment.issuer(nativeIdentity.frontendOrigin) ||
      value.session.issuer !== nativeIdentity.frontendOrigin ||
      workspace.protocol !== 'https:' || workspace.username || workspace.password || workspace.port ||
      workspace.search || workspace.hash || workspace.pathname !== '/chief' ||
      !workspace.hostname.endsWith(domain) ||
      !/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(workspace.hostname.slice(0, -domain.length)) ||
      environment.reserved.includes(workspace.hostname) ||
      value.workspace.url !== workspace.origin + '/chief' ||
      nativeIdentity.apiOrigin !== 'https://api.' + workspace.hostname) unavailable();
  const practiceLabel=workspace.hostname.split('.')[0];
  if(uuid(practiceLabel)&&practiceLabel!==value.practice.practice_id)unavailable();
  // Real-data workspaces are always addressed by their own registered practice UUID.
  if(value.data_mode==='authorized_beta'&&practiceLabel!==value.practice.practice_id)unavailable();
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
