/**
 * Infos-bound HTTPS enrollment wire for Mac CosmasDesktopPractice.
 * Origin is always app://cosmas. Renderer never picks accountOrigin or paths.
 * No redirects. Public Infos only — Bearer still comes from a signed account helper.
 */

import {request as httpsRequest} from 'node:https';
import {isProductionNativePracticeInfos, validateNativePracticeInfos} from './practice-infos-config.mjs';

const NATIVE_PATHS = Object.freeze({
  config: '/enrollment/v1/native/config',
  status: '/enrollment/v1/native/status',
  practices: '/enrollment/v1/native/practices',
  selectPractice: '/enrollment/v1/native/select-practice',
  profile: '/enrollment/v1/native/profile',
  practice: '/enrollment/v1/native/practice',
  join: '/enrollment/v1/native/join',
  document: '/enrollment/v1/native/document',
  accept: '/enrollment/v1/native/accept',
  receipt: '/enrollment/v1/native/receipt',
  quote: '/enrollment/v1/native/quote',
  checkout: '/enrollment/v1/native/checkout',
  recover: '/enrollment/v1/native/recover',
  confirmWorkspace: '/enrollment/v1/native/confirm-workspace',
  invitation: '/enrollment/v1/native/invitation',
  portal: '/enrollment/v1/native/portal',
});

const ORIGIN_ONLY = new Set(['config']);

function requestJson(accountOrigin, path, {method = 'GET', headers = {}, body, requestImplementation}) {
  const url = new URL(path, accountOrigin);
  if (url.origin !== accountOrigin) throw new Error('Desktop practice enrollment origin mismatch');
  const payload = body === undefined ? undefined : Buffer.from(JSON.stringify(body), 'utf8');
  return new Promise((resolve, reject) => {
    const req = requestImplementation(url, {
      method,
      headers: {
        ...headers,
        Accept: 'application/json',
        ...(payload ? {'Content-Type': 'application/json', 'Content-Length': String(payload.length)} : {}),
      },
      timeout: 15_000,
    }, res => {
      if (res.statusCode && res.statusCode >= 300 && res.statusCode < 400) {
        res.resume();
        reject(new Error('Desktop practice enrollment refused redirects'));
        return;
      }
      const chunks = [];
      res.on('data', chunk => chunks.push(chunk));
      res.on('end', () => {
        const raw = Buffer.concat(chunks).toString('utf8');
        let parsed = null;
        if (raw) {
          try { parsed = JSON.parse(raw); } catch {
            reject(new Error('Desktop practice enrollment returned non-JSON'));
            return;
          }
        }
        resolve({status: res.statusCode ?? 0, body: parsed});
      });
    });
    req.on('timeout', () => { req.destroy(); reject(new Error('Desktop practice enrollment timed out')); });
    req.on('error', reject);
    if (payload) req.write(payload);
    req.end();
  });
}

/**
 * @param {{infos: object, getBearerToken?: () => Promise<string>,
 *   requestImplementation?: typeof httpsRequest}} options
 */
export function createHttpsPracticeAccountWire({
  infos,
  getBearerToken,
  requestImplementation = httpsRequest,
} = {}) {
  const closed = validateNativePracticeInfos(infos);
  if (!closed.enabled) {
    throw new Error('Native practice Infos is disabled; omit Connect practice instead of wiring a dark host.');
  }
  const accountOrigin = closed.accountOrigin;
  const nativeOrigin = 'app://cosmas';

  async function enrollmentRequest(operation, body, {idempotencyKey} = {}) {
    const path = NATIVE_PATHS[operation];
    if (!path) return {status: 404, body: {detail: 'unknown_operation'}};
    const headers = {Origin: nativeOrigin};
    if (!ORIGIN_ONLY.has(operation)) {
      if (typeof getBearerToken !== 'function') {
        throw new Error(
          isProductionNativePracticeInfos(closed)
            ? 'Production Mac practice enrollment needs a signed account-realm bearer token.'
            : 'Desktop practice enrollment needs an account bearer token.',
        );
      }
      headers.Authorization = `Bearer ${await getBearerToken()}`;
    }
    if (idempotencyKey !== undefined) headers['Idempotency-Key'] = idempotencyKey;
    const method = ['config', 'status', 'practices', 'document', 'receipt', 'quote', 'invitation', 'portal']
      .includes(operation) ? 'GET' : 'POST';
    return requestJson(accountOrigin, path, {
      method, headers, body: method === 'GET' ? undefined : (body ?? {}), requestImplementation,
    });
  }

  return Object.freeze({
    infos: closed,
    accountOrigin,
    nativeOrigin,
    production: isProductionNativePracticeInfos(closed),
    enrollmentRequest,
  });
}
