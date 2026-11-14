import {exactHostedOrigin} from './hosted-workspace-config.mjs';

export const OPERATIONAL_NATIVE_PROFILE = 'operational-beta-v1';
export const STAGING_NATIVE_PROFILE = 'operational-staging-v1';
/** Production-review builds on clerk.beta.cosmas.ai; live Infos stay operational-beta-v1. */
export const PRODUCTION_NATIVE_PROFILE = 'operational-production-v1';
/** Closed installation profiles that may accompany a native identity load. */
export const PRODUCTION_INSTALLATION_PROFILE = 'production';
export const BETA_INSTALLATION_PROFILE = 'beta';
export const STAGING_INSTALLATION_PROFILE = 'staging';
/**
 * Exact Clerk hosts pinned per dedicated profile. No wildcards.
 * Staging may also use a strict `*.clerk.accounts.dev` host with pk_test_
 * (handled separately). operational-beta-v1 admits clerk.cosmas.ai and
 * clerk.staging.cosmas.ai (CTO DECISION_LOG 12 Nov 2026 10:12 ET — shipped
 * TestFlight/Mac builds). clerk.beta.cosmas.ai stays production-only.
 */
const DEDICATED_CLERK_HOSTS_BY_PROFILE = Object.freeze({
  [OPERATIONAL_NATIVE_PROFILE]: Object.freeze(new Set([
    'clerk.cosmas.ai', 'clerk.staging.cosmas.ai',
  ])),
  [STAGING_NATIVE_PROFILE]: Object.freeze(new Set(['clerk.staging.cosmas.ai'])),
  [PRODUCTION_NATIVE_PROFILE]: Object.freeze(new Set(['clerk.beta.cosmas.ai'])),
});
/** Production-review API origin; required when profile is operational-production-v1. */
export const PRODUCTION_API_ORIGIN = 'https://api.beta.cosmas.ai';
const ALLOWED_PROFILES = Object.freeze([
  OPERATIONAL_NATIVE_PROFILE, STAGING_NATIVE_PROFILE, PRODUCTION_NATIVE_PROFILE,
]);
const fields = ['version', 'profile', 'client', 'apiOrigin', 'publishableKey', 'frontendOrigin', 'organizationId', 'audience'];
const unavailable = () => { throw new Error('Operational native identity configuration is incomplete or inconsistent'); };
/** Strict development Clerk host: one or more DNS labels, then .clerk.accounts.dev. */
const ACCOUNTS_DEV_HOST = /^[a-z0-9-]+(?:\.[a-z0-9-]+)*\.clerk\.accounts\.dev$/;

/** Sorted exact hosts for each dedicated profile entry (empty array when absent). */
export function dedicatedClerkHostsByProfile() {
  return Object.freeze(Object.fromEntries(
    ALLOWED_PROFILES.map(profile => {
      const hosts = DEDICATED_CLERK_HOSTS_BY_PROFILE[profile];
      return [profile, Object.freeze(hosts instanceof Set ? [...hosts].sort() : [])];
    })));
}

/** True only for a strict *.clerk.accounts.dev hostname (no suffix tricks). */
export function isAccountsDevClerkHost(hostname) {
  return typeof hostname === 'string' && ACCOUNTS_DEV_HOST.test(hostname);
}

/**
 * Refuse operational-production-v1 unless the closed production installation
 * profile is present. Used by desktop, renderer, and simulator loaders.
 */
export function requireProductionInstallationProfile(identity, installationProfile) {
  if (identity?.profile === PRODUCTION_NATIVE_PROFILE
      && installationProfile !== PRODUCTION_INSTALLATION_PROFILE) {
    unavailable();
  }
  return installationProfile;
}

/** Authentication and data authorization are separate, explicit build inputs. */
export function validateOperationalNativeDataMode(value, identity) {
  if (!['synthetic', 'authorized_beta'].includes(value) ||
      identity?.profile === STAGING_NATIVE_PROFILE && value !== 'synthetic') unavailable();
  return value;
}

/** Public build input only. Never selects an account or fetches a credential. */
export function validateOperationalNativeIdentity(value, client, apiOrigin) {
  const staging = value?.profile === STAGING_NATIVE_PROFILE;
  const production = value?.profile === PRODUCTION_NATIVE_PROFILE;
  const frontendOrigin = typeof value?.frontendOrigin === 'string' && exactHostedOrigin(value.frontendOrigin)
    ? value.frontendOrigin : '';
  const hostname = frontendOrigin ? new URL(frontendOrigin).hostname : '';
  const dedicatedHosts = DEDICATED_CLERK_HOSTS_BY_PROFILE[value?.profile];
  const dedicatedFrontend = dedicatedHosts instanceof Set && dedicatedHosts.has(hostname);
  const developmentFrontend = !dedicatedFrontend && isAccountsDevClerkHost(hostname);
  const prefix = staging && developmentFrontend ? 'pk_test_' : 'pk_live_';
  const hostAllowed = staging
    ? (developmentFrontend || dedicatedFrontend)
    : dedicatedFrontend;
  if (!value || typeof value !== 'object' || Array.isArray(value) ||
      Object.keys(value).length !== fields.length || fields.some(key => !Object.hasOwn(value, key)) ||
      value.version !== 1 || !ALLOWED_PROFILES.includes(value.profile) ||
      !['apple', 'desktop'].includes(client) || value.client !== client || value.apiOrigin !== apiOrigin ||
      !exactHostedOrigin(apiOrigin) || !frontendOrigin || !hostAllowed ||
      (production && apiOrigin !== PRODUCTION_API_ORIGIN) ||
      // PRODUCTION_API_ORIGIN is production-only; beta/staging identities may not carry it.
      (!production && apiOrigin === PRODUCTION_API_ORIGIN) ||
      !/^[a-z]/.test(hostname.split('.').at(-1)) ||
      typeof value.publishableKey !== 'string' || value.publishableKey.length > 1024 ||
      !value.publishableKey.startsWith(prefix) ||
      !/^[A-Za-z0-9+/_-]+={0,2}$/.test(value.publishableKey.slice(prefix.length)) ||
      typeof value.organizationId !== 'string' || !/^org_[A-Za-z0-9_]{1,251}$/.test(value.organizationId) ||
      typeof value.audience !== 'string' ||
      (staging && developmentFrontend ? value.audience !== '' : !/^[\x21-\x7e]{1,255}$/.test(value.audience))) unavailable();
  try {
    const encoded = value.publishableKey.slice(prefix.length).replaceAll('-', '+').replaceAll('_', '/');
    if (atob(encoded) !== hostname + '$') unavailable();
  } catch { unavailable(); }
  return Object.freeze({...value});
}

/**
 * Loader entry used by desktop / renderer / simulator paths: validate the public
 * identity, then refuse operational-production-v1 without installation profile
 * `production`.
 */
export function loadOperationalNativeIdentity(value, client, apiOrigin, installationProfile) {
  const identity = validateOperationalNativeIdentity(value, client, apiOrigin);
  requireProductionInstallationProfile(identity, installationProfile);
  return identity;
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
