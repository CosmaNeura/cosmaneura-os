/** Shared Account-screen public URL rules for App Store 5.1.1(i). */
export const ACCOUNT_PUBLIC_URL_KEYS = Object.freeze([
  'VITE_PRIVACY_POLICY_URL',
  'VITE_SUPPORT_URL',
]);

const ALLOWED_HOST = 'cosmas.ai';

/**
 * Accept only https URLs on host cosmas.ai with no credentials and no explicit port.
 * Invalid, blank, or missing values yield null (no link / omit from build).
 */
export function validAccountPublicUrl(value) {
  const trimmed = typeof value === 'string' ? value.trim() : '';
  if (!trimmed) return null;
  try {
    const url = new URL(trimmed);
    if (url.protocol !== 'https:') return null;
    if (url.username || url.password) return null;
    if (url.port) return null;
    if (url.hostname !== ALLOWED_HOST) return null;
    return url.href;
  } catch {
    return null;
  }
}

/**
 * Optional retained/build env pass-through. Omitted keys stay omitted.
 * Present keys must be valid https://cosmas.ai/… URLs or the build fails.
 */
export function accountPublicUrlPassThrough(env) {
  const out = {};
  for (const key of ACCOUNT_PUBLIC_URL_KEYS) {
    if (!Object.hasOwn(env, key)) continue;
    if (!validAccountPublicUrl(env[key])) {
      throw new Error(`Invalid ${key}; use an https://cosmas.ai/… URL with no credentials or port`);
    }
    out[key] = env[key];
  }
  return out;
}
