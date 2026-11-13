/**
 * Public Account-screen destinations for App Store guideline 5.1.1(i).
 *
 * Config keys (Vite build env):
 * - VITE_PRIVACY_POLICY_URL
 * - VITE_SUPPORT_URL
 *
 * No built-in defaults. Each link renders only when its env value is a valid
 * https://cosmas.ai/… URL. Production/review profiles set these after John
 * publishes the pages; staging leaves them unset so testers see no 404s.
 *
 * Mac desktop (`VITE_WORKSPACE_HOSTED_CLIENT=desktop`) never shows the links:
 * Electron denies window.open / target=_blank.
 */

const ALLOWED_HOST = 'cosmas.ai';

/** True when this build is the Mac desktop app (window.open is blocked). */
export function accountPublicLinksHiddenOnClient(): boolean {
  return import.meta.env.VITE_WORKSPACE_HOSTED_CLIENT === 'desktop';
}

/**
 * Accept only https URLs on host cosmas.ai with no credentials.
 * Invalid, blank, or missing values yield null (no link).
 */
export function validAccountPublicUrl(value: string | undefined): string | null {
  const trimmed = value?.trim();
  if (!trimmed) return null;
  try {
    const url = new URL(trimmed);
    if (url.protocol !== 'https:') return null;
    if (url.username || url.password) return null;
    if (url.hostname !== ALLOWED_HOST) return null;
    return url.href;
  } catch {
    return null;
  }
}

/** Resolved Privacy Policy URL from `VITE_PRIVACY_POLICY_URL`, or null. */
export function privacyPolicyUrl(): string | null {
  return validAccountPublicUrl(import.meta.env.VITE_PRIVACY_POLICY_URL);
}

/** Resolved Support URL from `VITE_SUPPORT_URL`, or null. */
export function supportUrl(): string | null {
  return validAccountPublicUrl(import.meta.env.VITE_SUPPORT_URL);
}
