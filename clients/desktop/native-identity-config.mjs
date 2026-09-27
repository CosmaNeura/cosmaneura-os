import {exactHostedApiOrigin as exactHostedOrigin} from './hosted-auth-http.mjs';

export const OPERATIONAL_NATIVE_PROFILE = 'operational-beta-v1';
export const STAGING_NATIVE_PROFILE = 'operational-staging-v1';
const fields = ['version', 'profile', 'client', 'apiOrigin', 'publishableKey', 'frontendOrigin', 'organizationId', 'audience'];
const unavailable = () => { throw new Error('Operational native identity configuration is incomplete or inconsistent'); };

/** Authentication and data authorization are separate, explicit build inputs. */
export function validateOperationalNativeDataMode(value, identity) {
  if (!['synthetic', 'authorized_beta'].includes(value) ||
      identity?.profile === STAGING_NATIVE_PROFILE && value !== 'synthetic') unavailable();
  return value;
}

/** Public build input only. Never selects an account or fetches a credential. */
export function validateOperationalNativeIdentity(value, client, apiOrigin) {
  const staging = value?.profile === STAGING_NATIVE_PROFILE;
  const prefix = staging ? 'pk_test_' : 'pk_live_';
  if (!value || typeof value !== 'object' || Array.isArray(value) ||
      Object.keys(value).length !== fields.length || fields.some(key => !Object.hasOwn(value, key)) ||
      value.version !== 1 || ![OPERATIONAL_NATIVE_PROFILE, STAGING_NATIVE_PROFILE].includes(value.profile) ||
      !['apple', 'desktop'].includes(client) || value.client !== client || value.apiOrigin !== apiOrigin ||
      !exactHostedOrigin(apiOrigin) || !exactHostedOrigin(value.frontendOrigin) ||
      new URL(value.frontendOrigin).hostname.endsWith('.clerk.accounts.dev') !== staging ||
      !/^[a-z]/.test(new URL(value.frontendOrigin).hostname.split('.').at(-1)) ||
      typeof value.publishableKey !== 'string' || value.publishableKey.length > 1024 ||
      !value.publishableKey.startsWith(prefix) ||
      !/^[A-Za-z0-9+/_-]+={0,2}$/.test(value.publishableKey.slice(prefix.length)) ||
      typeof value.organizationId !== 'string' || !/^org_[A-Za-z0-9_]{1,251}$/.test(value.organizationId) ||
      typeof value.audience !== 'string' ||
      (staging ? value.audience !== '' : !/^[\x21-\x7e]{1,255}$/.test(value.audience))) unavailable();
  try {
    const encoded = value.publishableKey.slice(prefix.length).replaceAll('-', '+').replaceAll('_', '/');
    if (atob(encoded) !== new URL(value.frontendOrigin).hostname + '$') unavailable();
  } catch { unavailable(); }
  return Object.freeze({...value});
}

export function operationalNativeBundle(client) {
  if (client === 'apple') return 'com.cosmasos.beta.ios';
  if (client === 'desktop') return 'com.cosmasos.beta.desktop.auth';
  return unavailable();
}

export function operationalNativeAuthSettings(value) {
  const checked = validateOperationalNativeIdentity(value, value?.client, value?.apiOrigin);
  return {enabled: true, profile: checked.profile, publishableKey: checked.publishableKey,
    frontendOrigin: checked.frontendOrigin, organizationId: checked.organizationId, audience: checked.audience};
}
