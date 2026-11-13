import {validAccountPublicUrl} from '../../clients/shared/account-public-url.mjs';

/**
 * Public Account-screen destinations for App Store guideline 5.1.1(i).
 *
 * Config keys (Vite build env):
 * - VITE_PRIVACY_POLICY_URL
 * - VITE_SUPPORT_URL
 *
 * No built-in defaults. Each link renders only when its env value is a valid
 * https://cosmas.ai/… URL. Optional pass-throughs are allowed in
 * `scripts/build-native-renderer.mjs` and `Dockerfile.web` (ARG/ENV); leave them
 * unset in staging so testers see no links. After John publishes the pages,
 * production and review builds may set them to https://cosmas.ai/cosmabot/privacy
 * and https://cosmas.ai/cosmabot/support.
 *
 * Mac desktop (`VITE_WORKSPACE_HOSTED_CLIENT=desktop`) never shows the links:
 * Electron denies window.open / target=_blank.
 */

export {validAccountPublicUrl};

/** True when this build is the Mac desktop app (window.open is blocked). */
export function accountPublicLinksHiddenOnClient(): boolean {
  return import.meta.env.VITE_WORKSPACE_HOSTED_CLIENT === 'desktop';
}

/** Resolved Privacy Policy URL from `VITE_PRIVACY_POLICY_URL`, or null. */
export function privacyPolicyUrl(): string | null {
  return validAccountPublicUrl(import.meta.env.VITE_PRIVACY_POLICY_URL);
}

/** Resolved Support URL from `VITE_SUPPORT_URL`, or null. */
export function supportUrl(): string | null {
  return validAccountPublicUrl(import.meta.env.VITE_SUPPORT_URL);
}
