import {randomUUID} from 'node:crypto';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const PHASES = new Set(['disabled', 'loading', 'signedOut', 'signingIn', 'ready', 'signOutPending', 'unavailable']);
const ERROR = () => new Error('Native session unavailable');
const SOURCE_METHODS = new Set(['sourcePrepare', 'sourceAuthorize', 'sourceExtend', 'sourceRelease', 'sourceStopped', 'sourcePreparationRelease']);
function object(value, fields) {
  if (!value || typeof value !== 'object' || Array.isArray(value) ||
      Object.keys(value).length !== fields.length || !fields.every(key => Object.hasOwn(value, key))) throw ERROR();
  return value;
}
export function parseAuthState(value) {
  object(value, ['phase', 'revision', 'identity']);
  if (!PHASES.has(value.phase) || !UUID.test(value.revision)) throw ERROR();
  let identity = null;
  if (value.phase === 'ready') {
    object(value.identity, ['userId', 'sessionId', 'organizationId']);
    for (const [key, prefix] of [['userId', 'user_'], ['sessionId', 'sess_'], ['organizationId', 'org_']]) {
      const id = value.identity[key];
      if (typeof id !== 'string' || id.length > 255 || !id.startsWith(prefix) ||
          id.length <= prefix.length || !/^[A-Za-z0-9_]+$/.test(id)) throw ERROR();
    }
    identity = Object.freeze({...value.identity});
  } else if (value.identity !== null) throw ERROR();
  return Object.freeze({phase: value.phase, revision: value.revision, identity});
}
export const closedAuthState = phase => Object.freeze({phase, revision: randomUUID(), identity: null});
export function sameAuthState(a, b) {
  return a && b && a.phase === b.phase && a.revision === b.revision &&
    a.identity?.userId === b.identity?.userId && a.identity?.sessionId === b.identity?.sessionId &&
    a.identity?.organizationId === b.identity?.organizationId;
}

/** Dedicated pipes to one packaged helper. The renderer never receives this object. */
// The native coordinator fences access at 30/180 seconds. Leave five seconds
// for its error/state frames to arrive before treating the helper as dead.
// A deliberate recovery may first need macOS approval for an existing Keychain
// item after release signing. Background startup retains the short deadline.
export function createAuthHelperClient(child, {interactiveStartup = false,
  startupTimeoutMs = interactiveStartup === true ? 185000 : 10000,
  requestTimeoutMs = 35000, signInTimeoutMs = 185000} = {}) {
  let alive = true;
  let ready = false;
  let current = closedAuthState('loading');
  let parts = [];
  let frameSize = 0;
  const pending = new Map();
  const listeners = new Set();
  let completeStartup;
  const startup = new Promise(resolve => { completeStartup = resolve; });
  const startupTimer = setTimeout(fail, startupTimeoutMs);

  function publish(next) {
    if (current.revision === next.revision && !sameAuthState(current, next)) throw ERROR();
    const changed = !sameAuthState(current, next);
    current = next;
    if (changed) for (const listener of listeners) { try { listener(current); } catch { /* No raw listener errors. */ } }
  }
  function fail() {
    if (!alive) return;
    alive = false; clearTimeout(startupTimer); completeStartup(false);
    for (const request of pending.values()) { clearTimeout(request.timer); request.reject(ERROR()); }
    pending.clear(); parts = []; frameSize = 0;
    publish(closedAuthState('unavailable'));
    child.stdin.destroy(); child.stdout.destroy(); child.stderr?.destroy();
    if (child.exitCode === null && child.signalCode === null) child.kill('SIGTERM');
  }
  function receive(bytes) {
    const value = JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(bytes));
    if (value?.event === 'ready') {
      object(value, ['event', 'version']);
      if (ready || value.version !== 1) throw ERROR();
      ready = true; clearTimeout(startupTimer); completeStartup(true); return;
    }
    if (!ready) throw ERROR();
    if (value?.event === 'authStateChanged') {
      object(value, ['event', 'state']); publish(parseAuthState(value.state)); return;
    }
    const request = pending.get(value?.id);
    if (!request || typeof value.ok !== 'boolean') throw ERROR();
    let result;
    if (value.ok) {
      object(value, ['id', 'ok', 'result']);
      if (request.method === 'getToken') {
        object(value.result, ['token', 'revision']);
        if (value.result.revision !== request.revision || typeof value.result.token !== 'string' ||
            value.result.token.length > 8192 || !/^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/.test(value.result.token)) throw ERROR();
        result = value.result.token;
      } else if (SOURCE_METHODS.has(request.method)) {
        // Main-only caller validates the exact grant/decision before use. Source
        // secrets never enter the auth-state/preload API.
        if (['sourcePrepare', 'sourceAuthorize', 'sourceExtend'].includes(request.method)) {
          if (!value.result || typeof value.result !== 'object' || Array.isArray(value.result)) throw ERROR();
        } else if (value.result !== null) throw ERROR();
        result = value.result;
      } else {
        result = parseAuthState(value.result);
        if ((request.method === 'signIn' && result.phase !== 'ready') ||
            (request.method === 'signOut' && result.phase !== 'signedOut')) throw ERROR();
        publish(result);
      }
    } else {
      object(value, ['id', 'ok', 'error']);
      if (value.error !== 'native_auth_unavailable') throw ERROR();
    }
    pending.delete(value.id); clearTimeout(request.timer);
    if (value.ok) request.resolve(result); else request.reject(ERROR());
  }
  child.stdout.on('data', chunk => {
    if (!alive) return;
    try {
      if (!Buffer.isBuffer(chunk)) throw ERROR();
      let start = 0;
      while (start < chunk.length) {
        const end = chunk.indexOf(10, start);
        const segment = chunk.subarray(start, end === -1 ? chunk.length : end);
        frameSize += segment.length;
        if (frameSize >= 16384) throw ERROR();
        parts.push(segment);
        if (end === -1) break;
        const frame = Buffer.concat(parts, frameSize); parts = []; frameSize = 0;
        receive(frame); if (!alive) return; start = end + 1;
      }
    } catch { fail(); }
  });
  child.stdout.on('end', fail); child.stdout.on('error', fail); child.stdin.on('error', fail);
  child.stderr?.on('data', () => { /* Native diagnostics never enter renderer/log output. */ });
  child.stderr?.on('error', fail);
  child.on('error', fail); child.on('exit', fail);

  async function call(method, revision, sourcePayload) {
    if (!alive || !await startup || !alive || pending.size >= 32) throw ERROR();
    if (method === 'getToken' && (typeof revision !== 'string' || !UUID.test(revision))) throw ERROR();
    const id = randomUUID();
    const payload = SOURCE_METHODS.has(method) ? {id, method, payload: sourcePayload}
      : {id, method, ...(revision === undefined ? {} : {revision})};
    const frame = JSON.stringify(payload) + '\n';
    if (Buffer.byteLength(frame) > 1024) throw ERROR();
    return new Promise((resolve, reject) => {
      const timer = setTimeout(fail, method === 'signIn' ? signInTimeoutMs : requestTimeoutMs);
      pending.set(id, {method, revision, resolve, reject, timer});
      child.stdin.write(frame, error => { if (error) fail(); });
    });
  }
  return Object.freeze({
    getState: () => call('getState'), signIn: () => call('signIn'), signOut: () => call('signOut'),
    getToken: revision => call('getToken', revision), snapshot: () => current,
    sourceRequest: (method, payload) => {
      if (!SOURCE_METHODS.has(method) || !payload || typeof payload !== 'object' || Array.isArray(payload)) return Promise.reject(ERROR());
      return call(method, undefined, payload);
    },
    subscribe: listener => { listeners.add(listener); return () => listeners.delete(listener); },
    close: fail,
  });
}
