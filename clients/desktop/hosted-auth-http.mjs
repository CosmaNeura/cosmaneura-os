import {request as httpsRequest} from 'node:https';
import {fetchAuthenticatedWorkspaceAtOrigin} from './local-auth-http.mjs';

export function exactHostedApiOrigin(value) {
  if (typeof value !== 'string' || value.length > 253) return false;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && value === url.origin && !url.port &&
      /^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+$/.test(url.hostname) &&
      !url.hostname.endsWith('.localhost') && !/^\d+(?:\.\d+){3}$/.test(url.hostname);
  } catch { return false; }
}

/** Pin the reviewed service before login; the renderer cannot select a target. */
export function createHostedWorkspaceTransport(apiOrigin, requestImplementation = httpsRequest) {
  if (!exactHostedApiOrigin(apiOrigin)) throw new Error('Hosted workspace unavailable');
  return (url, options) => fetchAuthenticatedWorkspaceAtOrigin(apiOrigin, url, options, requestImplementation);
}
