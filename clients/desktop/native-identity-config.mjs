import {exactHostedApiOrigin as exactHostedOrigin} from './hosted-auth-http.mjs';

export const OPERATIONAL_NATIVE_PROFILE = 'operational-beta-v1';
const fields = ['version', 'profile', 'client', 'apiOrigin', 'publishableKey', 'frontendOrigin', 'organizationId', 'audience'];
const unavailable = () => { throw new Error('Operational native identity configuration is incomplete or inconsistent'); };

/** Public build input only. Never selects an account or fetches a credential. */
export function validateOperationalNativeIdentity(value, client, apiOrigin) {
  if (!value || typeof value !== 'object' || Array.isArray(value) ||
      Object.keys(value).length !== fields.length || fields.some(key => !Object.hasOwn(value, key)) ||
      value.version !== 1 || value.profile !== OPERATIONAL_NATIVE_PROFILE ||
      !['apple', 'desktop'].includes(client) || value.client !== client || value.apiOrigin !== apiOrigin ||
      !exactHostedOrigin(apiOrigin) || !exactHostedOrigin(value.frontendOrigin) ||
      new URL(value.frontendOrigin).hostname.endsWith('.clerk.accounts.dev') ||
      !/^[a-z]/.test(new URL(value.frontendOrigin).hostname.split('.').at(-1)) ||
      typeof value.publishableKey !== 'string' || value.publishableKey.length > 1024 ||
      !/^pk_live_[A-Za-z0-9+/_-]+={0,2}$/.test(value.publishableKey) ||
      typeof value.organizationId !== 'string' || !/^org_[A-Za-z0-9_]{1,251}$/.test(value.organizationId) ||
      typeof value.audience !== 'string' || !/^[\x21-\x7e]{1,255}$/.test(value.audience)) unavailable();
  try {
    const encoded = value.publishableKey.slice('pk_live_'.length).replaceAll('-', '+').replaceAll('_', '/');
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
  return {enabled: true, profile: OPERATIONAL_NATIVE_PROFILE, publishableKey: checked.publishableKey,
    frontendOrigin: checked.frontendOrigin, organizationId: checked.organizationId, audience: checked.audience};
}
