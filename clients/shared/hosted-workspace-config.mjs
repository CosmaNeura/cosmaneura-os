/** Public build configuration only. This module never reads files or credentials. */
import {isPackagedWorkspaceDocument} from './workspace-document.mjs';

export function exactHostedOrigin(value) {
  if (typeof value !== 'string' || value.length > 253) return false;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && value === url.origin && !url.port &&
      !url.username && !url.password && !url.search && !url.hash &&
      /^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+$/.test(url.hostname) &&
      !url.hostname.endsWith('.localhost') && !/^\d+(?:\.\d+){3}$/.test(url.hostname);
  } catch { return false; }
}

export function resolveHostedWorkspace(env) {
  if (!env || env.VITE_WORKSPACE_HOSTED_ENABLED !== 'true' ||
      env.VITE_COSMAS_ENV !== 'early_adopter_beta' ||
      env.VITE_WORKSPACE_ENABLED !== 'true' || env.VITE_WORKSPACE_AUTHENTICATED_ENABLED !== 'true' ||
      env.VITE_DESKTOP_SYNTHETIC_ENABLED === 'true' ||
      env.VITE_WORKSPACE_APPLE_LOCAL_TRANSPORT_ENABLED === 'true' ||
      !['synthetic', 'authorized_beta'].includes(env.VITE_WORKSPACE_DATA_MODE) ||
      !['web', 'apple', 'desktop'].includes(env.VITE_WORKSPACE_HOSTED_CLIENT) ||
      !exactHostedOrigin(env.VITE_WORKSPACE_HOSTED_API_ORIGIN)) return null;
  const client = env.VITE_WORKSPACE_HOSTED_CLIENT;
  // Native composers bind authorized_beta to an explicit operational identity and
  // device custody profile. A web bundle alone is never an installable release.
  if ((env.VITE_WORKSPACE_DESKTOP_AUTH_ENABLED === 'true') !== (client === 'desktop') ||
      (env.VITE_WORKSPACE_NATIVE_AUTH_ENABLED === 'true') !== (client === 'apple') ||
      env.VITE_API_BASE !== (client === 'desktop' ? 'app://cosmas/api' : env.VITE_WORKSPACE_HOSTED_API_ORIGIN) ||
      client === 'web' && !exactHostedOrigin(env.VITE_WORKSPACE_WEB_ORIGIN) ||
      client !== 'web' && !!env.VITE_WORKSPACE_WEB_ORIGIN) return null;
  return Object.freeze({client, dataMode: env.VITE_WORKSPACE_DATA_MODE,
    apiOrigin: env.VITE_WORKSPACE_HOSTED_API_ORIGIN,
    apiBase: env.VITE_API_BASE,
    pageOrigin: client === 'web' ? env.VITE_WORKSPACE_WEB_ORIGIN :
      client === 'apple' ? 'capacitor://localhost' : 'app://cosmas'});
}

export function permittedHostedWorkspace(configuration, base, page, signed = false) {
  if (!configuration || base !== configuration.apiBase) return false;
  try {
    const location = new URL(page);
    if (location.username || location.password || location.port) return false;
    if (configuration.client === 'web') return location.origin === configuration.pageOrigin;
    if (configuration.client === 'desktop') return !signed && isPackagedWorkspaceDocument(page);
    return location.protocol === 'capacitor:' && location.hostname === 'localhost';
  } catch { return false; }
}
