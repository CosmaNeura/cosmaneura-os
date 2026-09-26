// The renderer can reach only this loopback synthetic API through its own app origin.
const API_ORIGIN = 'http://127.0.0.1:8018';
const UUID = '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}';
const READ = new RegExp(`^/(?:workspaces(?:/${UUID})?|provider-team|queue|tickets/${UUID}/timeline)$`);
const WRITE = new RegExp(`^/(?:synth/demo-queue|provider-team|workspaces(?:/${UUID}/(?:entries|conversation|work-links|handoffs/${UUID}/retry|notes(?:/${UUID}/review)?|follow-ups(?:/${UUID}/(?:decide|complete))?))?|tickets/${UUID}/(?:decide|edit|close))$`);
const ID = new RegExp(`^${UUID}$`);

export function permittedApiPath(url, method) {
  let parsed;
  try { parsed = new URL(url); } catch { return null; }
  if (parsed.protocol !== 'app:' || parsed.hostname !== 'cosmas' || parsed.port ||
      parsed.username || parsed.password || parsed.search || parsed.hash ||
      !parsed.pathname.startsWith('/api/')) return null;
  const path = parsed.pathname.slice(4);
  return ((method === 'GET' && READ.test(path)) || (method === 'POST' && WRITE.test(path))) ? path : null;
}

async function boundedBytes(stream, limit) {
  if (!stream) return new Uint8Array();
  const reader = stream.getReader();
  const chunks = [];
  let size = 0;
  try {
    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > limit) { await reader.cancel(); throw new Error('body_limit'); }
      chunks.push(value);
    }
  } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  return bytes;
}

function unavailable(status) {
  return new Response('{"detail":"Synthetic desktop request unavailable"}', {
    status, headers: {'Content-Type': 'application/json', 'Cache-Control': 'no-store'},
  });
}

export async function proxyWorkspaceRequest(request, fetchImplementation = fetch) {
  const path = permittedApiPath(request.url, request.method);
  if (!path) return unavailable(404);
  const headers = new Headers({'Content-Type': 'application/json'});
  for (const name of ['X-Box-Id', 'X-Actor-Principal-Id']) {
    const value = request.headers.get(name);
    if (value && !ID.test(value)) return unavailable(400);
    if (value) headers.set(name, value);
  }
  try {
    const body = await boundedBytes(request.body, 128_000);
    const response = await fetchImplementation(API_ORIGIN + path, {
      method: request.method, headers,
      body: request.method === 'POST' ? body : undefined,
      redirect: 'error', credentials: 'omit', cache: 'no-store', signal: AbortSignal.timeout(45_000),
    });
    if (!response.headers.get('content-type')?.startsWith('application/json')) return unavailable(502);
    const bytes = await boundedBytes(response.body, 12_000_000);
    return new Response(bytes, {status: response.status, headers: {
      'Content-Type': 'application/json', 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
    }});
  } catch { return unavailable(503); }
}
