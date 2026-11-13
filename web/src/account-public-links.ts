/**
 * Public Account-screen destinations for App Store guideline 5.1.1(i).
 *
 * Config keys (Vite build env):
 * - VITE_PRIVACY_POLICY_URL
 * - VITE_SUPPORT_URL
 *
 * TODO(John): publish the final Privacy Policy and Support URLs, then replace
 * these clearly marked placeholder defaults in build/env composition.
 */
export const DEFAULT_PRIVACY_POLICY_URL = 'https://cosmas.ai/privacy';
export const DEFAULT_SUPPORT_URL = 'https://cosmas.ai/support';

function configuredUrl(value: string | undefined, fallback: string): string {
  const trimmed = value?.trim();
  return trimmed ? trimmed : fallback;
}

/** Resolved Privacy Policy URL from `VITE_PRIVACY_POLICY_URL`, else the placeholder default. */
export function privacyPolicyUrl(): string {
  return configuredUrl(import.meta.env.VITE_PRIVACY_POLICY_URL, DEFAULT_PRIVACY_POLICY_URL);
}

/** Resolved Support URL from `VITE_SUPPORT_URL`, else the placeholder default. */
export function supportUrl(): string {
  return configuredUrl(import.meta.env.VITE_SUPPORT_URL, DEFAULT_SUPPORT_URL);
}
