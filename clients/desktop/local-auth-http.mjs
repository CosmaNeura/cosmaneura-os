import {request as httpRequest} from 'node:http';
import {Readable} from 'node:stream';
import {connectorApiRoute, isModelActivityPath} from './connector-api-routes.mjs';

/** Direct loopback sockets: no ambient proxy, cookie jar, redirects or DNS. */
export function fetchLocalAuthenticatedWorkspace(url, options, requestImplementation = httpRequest) {
  return fetchAuthenticatedWorkspaceAtOrigin('http://127.0.0.1:8046', url, options, requestImplementation);
}

/** Called only by the two main-process transports with their pinned origin. */
export function fetchAuthenticatedWorkspaceAtOrigin(origin, url, options, requestImplementation) {
  const parsed = new URL(url);
  const target = parsed.pathname + parsed.search, connector = connectorApiRoute(target,options.method);
  const strictResponse = connector?.strictResponse || target === '/provider-team/identity' || isModelActivityPath(target);
  if (parsed.origin !== origin || parsed.username || parsed.password || parsed.hash ||
      !['GET', 'POST', 'PUT'].includes(options.method) || options.method === 'PUT' && !connector?.binaryRequest ||
      (parsed.search || options.method === 'PUT') && (!connector || new Headers(options.headers).get(connector.header) !== '1')) return Promise.reject(new Error('Local workspace unavailable'));
  if (parsed.pathname.startsWith('/provider-team/activity') && (
      !isModelActivityPath(target) || options.method !== 'GET' || options.body ||
      new Headers(options.headers).get('X-Cosmas-Team-Contract') !== '2' ||
      new Headers(options.headers).get('X-Cosmas-Draft-Recovery') !== '2'))
    return Promise.reject(new Error('Local workspace unavailable'));
  return new Promise((resolve, reject) => {
    const request = requestImplementation({host: parsed.hostname, port: Number(parsed.port) || 443, path: target,
      ...(parsed.protocol === 'https:' ? {servername: parsed.hostname, rejectUnauthorized: true, minVersion: 'TLSv1.2'} : {}),
      method: options.method, headers: options.headers, signal: options.signal, agent: false}, response => {
      if (!response.statusCode || response.statusCode >= 300 && response.statusCode < 400) {
        response.destroy(); reject(new Error('Local workspace unavailable')); return;
      }
      try {
        const headers = new Headers();
        for (const name of ['content-type', 'cache-control', ...(strictResponse ? ['content-length','content-encoding'] : [])]) {
          const value = response.headers[name];
          if (strictResponse && value !== undefined && typeof value !== 'string') throw new Error('Invalid private response metadata');
          if (typeof value === 'string') headers.set(name, value);
        }
        resolve(new Response(Readable.toWeb(response), {status: response.statusCode, headers}));
      } catch {
        // Unexpected upstream statuses/headers must close the request, not throw
        // from an EventEmitter callback and terminate the desktop process.
        response.destroy(); reject(new Error('Local workspace unavailable'));
      }
    });
    request.on('error', () => reject(new Error('Local workspace unavailable')));
    if (options.body) request.write(options.body);
    request.end();
  });
}
