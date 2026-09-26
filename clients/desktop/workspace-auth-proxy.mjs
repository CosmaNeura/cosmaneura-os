import {sameAuthState} from './auth-helper-client.mjs';
import {exactHostedApiOrigin} from './hosted-auth-http.mjs';
import {connectorApiRoute, CONNECTOR_HEADERS, isModelActivityPath} from './connector-api-routes.mjs';

const API_ORIGIN = 'http://127.0.0.1:8046';
const ID = '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}';
const BOT = `(?:chief|scribe|visit_prep|follow_up|${ID})`;
const READ = new RegExp(`^/(?:workspaces(?:/${ID}(?:/(?:appointments(?:/(?:pages/)?${ID})?|prep-work(?:/${ID})?))?)?|provider-team(?:/(?:identity|setup|resources|usage|routines/${BOT}(?:/runs/${ID})?))?|practice-work(?:/(?:pages/)?${ID})?)$`);
const WRITE = new RegExp(`^/(?:provider-team(?:/(?:rehearsal|routines/${BOT}))?|practice-work/${ID}/(?:handoffs|complete)|workspaces(?:/${ID}/(?:entries|conversation(?:/resolve)?|work-links|handoffs/${ID}/retry(?:/resolve)?|notes(?:/${ID}/review)?|follow-ups(?:/${ID}/(?:decide|complete))?|appointments(?:/(?:current|${ID}/(?:decide|execute)))?|prep-work(?:/${ID}/(?:decide|verify))?|scheduling/availability|capture/(?:admission|operations|notes|note-links|prep)))?)$`);
const MODEL_COMMAND = new RegExp(`^/workspaces/${ID}/(?:conversation(?:/resolve)?|handoffs/${ID}/retry(?:/resolve)?)$`);
const WORKSPACE_READ = new RegExp(`^/workspaces/${ID}$`);
const ROUTINE_RUN_READ = new RegExp(`^/provider-team/routines/${BOT}/runs/${ID}$`);
const REVISION = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

export function permittedAuthenticatedApiPath(url, method) {
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== 'app:' || parsed.hostname !== 'cosmas' || parsed.port || parsed.username ||
        parsed.password || parsed.hash || !parsed.pathname.startsWith('/api/')) return null;
    const path = parsed.pathname.slice(4) + parsed.search;
    const connector = connectorApiRoute(path,method);
    if ((connector?.strictResponse || path === '/provider-team/identity' || isModelActivityPath(path)) &&
        (url !== 'app://cosmas/api' + path || url.includes('?') && connector?.canonicalQuery !== true)) return null;
    if (connector) return path;
    return !parsed.search && (method === 'GET' && (READ.test(path) || isModelActivityPath(path)) || method === 'POST' && WRITE.test(path)) ? path : null;
  } catch { return null; }
}
function unavailable(status) {
  return new Response('{"detail":"Desktop workspace request unavailable"}', {status,
    headers: {'Content-Type': 'application/json', 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'}});
}
function untilAborted(operation, signal) {
  signal.throwIfAborted();
  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = (callback, value) => {
      if (settled) return;
      settled = true;
      signal.removeEventListener('abort', abort);
      callback(value);
    };
    const abort = () => finish(reject, signal.reason);
    signal.addEventListener('abort', abort, {once: true});
    // A late credential/result cannot resume dispatch after this request ends.
    Promise.resolve().then(() => { signal.throwIfAborted(); return operation(); })
      .then(value => finish(resolve, value), error => finish(reject, error));
  });
}
function cancelBody(body) {
  // Rejection and credential cleanup must not depend on an untrusted stream
  // finishing its underlying cancellation callback.
  try { void Promise.resolve(body?.cancel()).catch(() => {}); } catch { /* best effort */ }
}
async function boundedBytes(stream, maximum, signal) {
  if (!stream) return new Uint8Array();
  const reader = stream.getReader(); const chunks = []; let size = 0;
  const abort = () => cancelBody(reader);
  signal.addEventListener('abort', abort, {once: true});
  try {
    while (true) {
      signal.throwIfAborted(); const {done, value} = await untilAborted(() => reader.read(), signal); signal.throwIfAborted();
      if (done) break;
      size += value.byteLength;
      if (size > maximum) { cancelBody(reader); throw new Error('body_limit'); }
      chunks.push(value);
    }
    const bytes = new Uint8Array(size); let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
    return bytes;
  } finally { signal.removeEventListener('abort', abort); reader.releaseLock(); }
}

/** Fresh native credentials enter only this main-process transport. */
export async function proxyAuthenticatedWorkspaceRequest(request, auth, fetchImplementation = fetch, apiOrigin = API_ORIGIN) {
  if (apiOrigin !== API_ORIGIN && !exactHostedApiOrigin(apiOrigin)) return unavailable(503);
  const path = permittedAuthenticatedApiPath(request.url, request.method);
  if (!path) return unavailable(404);
  const workspaceProtocol=request.headers.get('X-Cosmas-Workspace-Protocol');
  if(workspaceProtocol!==null && workspaceProtocol!=='1')return unavailable(426);
  const routineRun = request.method === 'GET' && ROUTINE_RUN_READ.test(path);
  const routineContract = request.headers.get('X-Cosmas-Routine-Contract');
  // Generation 2 changes only an exact saved-run read. Missing negotiation
  // retains the existing legacy read; it never upgrades configuration or saves.
  if (routineContract !== null && (routineContract !== '2' || !routineRun ||
      request.url !== 'app://cosmas/api' + path)) return unavailable(426);
  let connector = connectorApiRoute(path,request.method);
  for (const header of CONNECTOR_HEADERS) {
    const value = request.headers.get(header);
    if (value !== null && (value !== '1' || connector?.header !== header)) return unavailable(426);
  }
  if (connector && !request.headers.has(connector.header)) {
    if (connector.optional) connector = null;
    else return unavailable(426);
  }
  const writeKey = request.headers.get('X-Cosmas-Artifact-Write-Key');
  if (connector?.binaryRequest ? !writeKey || !/^[A-Za-z0-9:_-]{8,100}$/.test(writeKey) : writeKey !== null) return unavailable(400);
  const revision = request.headers.get('X-Cosmas-Desktop-Session');
  if (!revision || !REVISION.test(revision) ||
      ['Authorization', 'X-Box-Id', 'X-Actor-Principal-Id', 'Cookie', 'Content-Encoding'].some(name => request.headers.has(name)) ||
      request.headers.has('Origin') && request.headers.get('Origin') !== 'app://cosmas') return unavailable(401);
  const contentType = connector?.binaryRequest ? 'application/pdf' : 'application/json';
  if (request.headers.get('Content-Type')?.split(';', 1)[0].trim() !== contentType) return unavailable(400);
  const identityPath = path === '/provider-team/identity';
  const activityPath = isModelActivityPath(path);
  const activityContract=request.headers.get('X-Cosmas-Activity-Contract');
  if(activityContract!==null&&(!activityPath||!['1','2'].includes(activityContract)))return unavailable(426);
  const recoveryGeneration = request.headers.get('X-Cosmas-Draft-Recovery');
  if ((identityPath || activityPath) && recoveryGeneration !== '2') return unavailable(426);
  if (recoveryGeneration !== null && !['1', '2'].includes(recoveryGeneration)) return unavailable(400);
  const strictResponse = identityPath || activityPath || connector?.strictResponse;
  const teamPath = ['/provider-team', '/provider-team/setup', '/provider-team/rehearsal'].includes(path);
  const teamInfoPath = activityPath || ['/provider-team/resources', '/provider-team/usage', '/provider-team/identity'].includes(path);
  const teamContract = request.headers.get('X-Cosmas-Team-Contract');
  if (teamContract !== null && (!['1', '2', '3', '4'].includes(teamContract) || !teamPath && !teamInfoPath) ||
      teamPath && path !== '/provider-team' && teamContract === null ||
      teamInfoPath && !(activityPath || identityPath ? teamContract === '2' : ['2', '3', '4'].includes(teamContract)) || identityPath && recoveryGeneration !== '2') return unavailable(426);
  const modelCommand = request.method === 'POST' && MODEL_COMMAND.test(path);
  const workspaceRead = request.method === 'GET' && WORKSPACE_READ.test(path);
  const modelContract = request.headers.get('X-Cosmas-Model-Contract');
  if (modelContract !== null && (modelContract !== '1' || !modelCommand && !workspaceRead) ||
      modelCommand && path.endsWith('/resolve') && modelContract !== '1') return unavailable(426);
  // Missing negotiation on the two original command paths reaches the backend
  // only for its exact legacy/deterministic compatibility checks. It is never
  // upgraded here into authority for a new model admission.
  const modelReceipt = modelCommand && modelContract === '1';
  const controller = new AbortController();
  const signal = AbortSignal.any([controller.signal, request.signal]);
  let expired = false, authorityStatus = null;
  const timer = setTimeout(() => { expired = true; controller.abort(); }, identityPath || activityPath ? 15000 : connector ? connector.seconds * 1000 : routineRun || modelContract === '1' ? 30000 : path.endsWith('/capture/notes') ? 120000 : 45000);
  const remove = auth.subscribe(state => { if (state.phase !== 'ready' || state.revision !== revision) controller.abort(); });
  try {
    const before = await untilAborted(() => auth.getState(), signal);
    if (before.phase !== 'ready' || before.revision !== revision) return unavailable(401);
    const appointmentPath = path.endsWith('/appointments') || path.includes('/appointments/');
    const prepWorkPath = path.endsWith('/prep-work') || path.includes('/prep-work/');
    const routinePath = path.startsWith('/provider-team/routines/');
    const maximumInput = identityPath || activityPath ? 0 : connector ? connector.input : modelReceipt ? (path.includes('/conversation') ? 65536 : 2048) : teamPath ? 4194304 : teamInfoPath ? 2048 : prepWorkPath ? (path.endsWith('/prep-work') ? 32768 : 2048) : (path.endsWith('/capture/admission') || path.endsWith('/scheduling/availability') || appointmentPath || routinePath) ? 2048 : path.endsWith('/capture/notes') ? 270336 :
      path.endsWith('/capture/operations') ? 4194304 : path.includes('/capture/') ? 1048576 : 128000;
    const body = await boundedBytes(request.body, maximumInput, signal);
    if (request.method === 'GET' && body.length) return unavailable(400);
    if (request.method === 'POST') JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(body));
    const token = await untilAborted(() => auth.getToken(revision), signal);
    signal.throwIfAborted();
    if (!sameAuthState(before, auth.snapshot()) || typeof token !== 'string' || token.length > 8192 ||
        !/^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/.test(token)) return unavailable(401);
    const response = await untilAborted(() => Promise.resolve(fetchImplementation(apiOrigin + path, {
      method: request.method, headers: {'Content-Type': contentType, 'Authorization': 'Bearer ' + token,
        ...(workspaceProtocol ? {'X-Cosmas-Workspace-Protocol':workspaceProtocol} : {}),
        'Origin': 'app://cosmas', ...(recoveryGeneration ? {'X-Cosmas-Draft-Recovery': recoveryGeneration} : {}),
        ...(teamContract ? {'X-Cosmas-Team-Contract': teamContract} : {}),
        ...(activityContract ? {'X-Cosmas-Activity-Contract': activityContract} : {}),
        ...(modelContract ? {'X-Cosmas-Model-Contract': modelContract} : {}),
        ...(routineContract ? {'X-Cosmas-Routine-Contract': routineContract} : {}),
        ...(connector ? {[connector.header]:'1'} : {}),
        ...(writeKey ? {'X-Cosmas-Artifact-Write-Key':writeKey} : {})}, body: request.method === 'POST' || request.method === 'PUT' ? body : undefined,
      redirect: 'error', credentials: 'omit', cache: 'no-store', signal,
    })).then(value => {
      if (signal.aborted) { cancelBody(value.body); signal.throwIfAborted(); }
      return value;
    }), signal);
    if(workspaceProtocol && response.status>=200 && response.status<300 && response.headers.get('X-Cosmas-Workspace-Protocol')!=='1'){cancelBody(response.body);return unavailable(426);}
    if (strictResponse && [401,403,404].includes(response.status)) authorityStatus = response.status;
    const responseType = connector?.binaryResponse && response.status === 200 ? 'application/pdf' : 'application/json';
    const maximumOutput = identityPath ? 1024 : activityPath ? response.status === 200 ? 65536 : 1024 : connector ? connector.errorOutput && response.status !== 200 ? connector.errorOutput : connector.binaryResponse && response.status !== 200 ? 8192 : connector.output : modelReceipt || teamInfoPath ? 16384 : teamPath ? 8388608 : prepWorkPath ? 1048576 : appointmentPath || routinePath ? 32768 : path.endsWith('/scheduling/availability') ? 1048576 : path.endsWith('/capture/operations') ? 32 * 1024 * 1024 + 4096 : path.includes('/capture/') ? 25169920 : 12000000;
    const length = response.headers.get('Content-Length');
    if (response.headers.get('Content-Type')?.split(';', 1)[0].trim() !== responseType ||
        !response.headers.get('Cache-Control')?.split(',').some(value => value.trim().toLowerCase() === 'no-store') ||
        strictResponse && (response.redirected || response.type === 'opaque' || response.type === 'opaqueredirect' || response.headers.has('Content-Encoding') ||
          length !== null && (!/^(?:0|[1-9][0-9]*)$/.test(length) || Number(length) > maximumOutput))) {
      cancelBody(response.body); return unavailable(authorityStatus ?? 502);
    }
    const bytes = await boundedBytes(response.body, maximumOutput, signal);
    if (strictResponse && length !== null && Number(length) !== bytes.byteLength) return unavailable(authorityStatus ?? 502);
    if (modelReceipt) JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(bytes));
    signal.throwIfAborted();
    const after = await untilAborted(() => auth.getState(), signal); signal.throwIfAborted();
    if (!sameAuthState(before, after)) return unavailable(401);
    return new Response(bytes, {status: response.status, headers: {'Content-Type': responseType,
      'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
      ...(response.headers.has('X-Cosmas-Workspace-Protocol') ? {'X-Cosmas-Workspace-Protocol':response.headers.get('X-Cosmas-Workspace-Protocol')} : {})}});
  } catch { return unavailable(strictResponse && expired ? 504 : controller.signal.aborted ? 401 : authorityStatus ?? 503); }
  finally { clearTimeout(timer); remove(); }
}
