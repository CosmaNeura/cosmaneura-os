import assert from 'node:assert/strict';
import test, {after} from 'node:test';
import {EventEmitter} from 'node:events';
import {PassThrough} from 'node:stream';
import {networkGuardInstalled, blockedNetworkAttempts} from './test-support/deny-network.mjs';
import {permittedAuthenticatedApiPath, proxyAuthenticatedWorkspaceRequest as proxy} from './workspace-auth-proxy.mjs';
import {fetchLocalAuthenticatedWorkspace as local} from './local-auth-http.mjs';
import {permittedApiPath as syntheticPath, proxyWorkspaceRequest as syntheticProxy} from './api-proxy.mjs';

const id = '00000000-0000-4000-8000-000000000001';
const origin = 'app://cosmas/api';
const base = '/provider-team/routines/chief';
const path = base + '/runs/' + id;
const header = 'X-Cosmas-Routine-Contract';
const contract = {[header]: '2'};
const tick = () => new Promise(resolve => setImmediate(resolve));
const ready = {phase: 'ready', revision: id,
  identity: {userId: 'invented', sessionId: 'invented', organizationId: 'invented'}};
function auth() {
  let state = ready, reads = 0, tokens = 0;
  const listeners = new Set();
  return {
    getState: async () => { reads++; return state; }, snapshot: () => state,
    getToken: async () => { tokens++; return 'invented.local.token'; },
    subscribe: listener => { listeners.add(listener); return () => listeners.delete(listener); },
    counts: () => ({reads, tokens}), listeners: () => listeners.size,
    revoke() { state = {phase: 'signedOut', revision: id, identity: null}; for (const listener of listeners) listener(state); },
  };
}
const request = (target = path, headers = contract, method = 'GET', body, signal) => new Request(origin + target, {
  method, headers: {'Content-Type': 'application/json', 'X-Cosmas-Desktop-Session': id, ...headers},
  ...(body === undefined ? {} : {body, duplex: 'half'}), signal,
});
const json = (body = '{}', status = 200, headers = {}) => new Response(body, {status,
  headers: {'Content-Type': 'application/json', 'Cache-Control': 'no-store', ...headers}});

after(() => {
  assert.equal(networkGuardInstalled, true);
  assert.equal(blockedNetworkAttempts(), 0, 'Every request must use an injected implementation; no ambient network attempt is allowed');
});

test('forwards only exact saved-run generation 2 with a fresh native token for every admitted bot', async () => {
  for (const bot of ['chief', 'scribe', 'follow_up', 'visit_prep', id]) {
    const target = '/provider-team/routines/' + bot + '/runs/' + id;
    const session = auth(); let calls = 0;
    const result = await proxy(request(target, {...contract, 'X-Renderer-Endpoint': 'https://outside.invalid'}), session, async (url, options) => {
      calls++;
      assert.equal(url, 'http://127.0.0.1:8046' + target);
      assert.equal(options.method, 'GET'); assert.equal(options.body, undefined);
      assert.deepEqual(options.headers, {'Content-Type': 'application/json', Authorization: 'Bearer invented.local.token',
        Origin: 'app://cosmas', [header]: '2'});
      assert.equal(options.redirect, 'error'); assert.equal(options.credentials, 'omit'); assert.equal(options.cache, 'no-store');
      return json('{"invented":"retained brief"}', 200, {'Set-Cookie': 'withheld'});
    });
    assert.equal(result.status, 200); assert.equal(await result.text(), '{"invented":"retained brief"}');
    assert.equal(result.headers.get('Set-Cookie'), null); assert.equal(calls, 1);
    assert.deepEqual(session.counts(), {reads: 2, tokens: 1}); assert.equal(session.listeners(), 0);
  }
});

test('preserves unnegotiated routine configuration reads, saves and legacy saved-run reads', async () => {
  for (const [target, method, body] of [[base, 'GET'], [base, 'POST', '{}'], [path, 'GET']]) {
    let calls = 0;
    const result = await proxy(request(target, {}, method, body), auth(), async (_url, options) => {
      calls++; assert.equal(options.headers[header], undefined);
      assert.equal(options.method, method); assert.equal(options.body === undefined ? undefined : new TextDecoder().decode(options.body), body);
      return json('{"invented":"legacy"}');
    });
    assert.equal(result.status, 200); assert.equal(await result.text(), '{"invented":"legacy"}'); assert.equal(calls, 1);
  }
});

test('rejects malformed or duplicate routine contract values before native credential access', async () => {
  for (const value of ['', '1', '3', '02', '2.0', '2, 2', '2, 1', 'two']) {
    const session = auth(); let calls = 0;
    const result = await proxy(request(path, {[header]: value}), session, () => { calls++; return json(); });
    assert.equal(result.status, 426, value); assert.deepEqual(session.counts(), {reads: 0, tokens: 0}); assert.equal(calls, 0);
  }
  const duplicate = request(); duplicate.headers.append(header, '2'); const session = auth(); let calls = 0;
  assert.equal((await proxy(duplicate, session, () => { calls++; return json(); })).status, 426);
  assert.deepEqual(session.counts(), {reads: 0, tokens: 0}); assert.equal(calls, 0);
});

test('rejects routine negotiation on configuration, save and every other sampled admitted family', async () => {
  for (const [target, method, headers, body] of [
    [base, 'GET', contract], [base, 'POST', contract, '{}'], ['/provider-team', 'GET', contract],
    ['/provider-team/resources', 'GET', {...contract, 'X-Cosmas-Team-Contract': '2'}],
    ['/workspaces/' + id, 'GET', contract],
    ['/provider-team/identity', 'GET', {...contract, 'X-Cosmas-Team-Contract': '2', 'X-Cosmas-Draft-Recovery': '2'}],
    ['/inbox', 'GET', {...contract, 'X-Cosmas-Inbox-Contract': '1'}],
  ]) {
    const session = auth(); let calls = 0;
    const result = await proxy(request(target, headers, method, body), session, () => { calls++; return json(); });
    assert.equal(result.status, 426, target); assert.deepEqual(session.counts(), {reads: 0, tokens: 0}); assert.equal(calls, 0);
  }
});

test('does not admit new methods, query selectors, malformed bots or saved-run route suffixes', async () => {
  for (const [target, method] of [
    [path, 'POST'], [path, 'PUT'], [path, 'DELETE'], [path, 'HEAD'], [path, 'OPTIONS'],
    [path + '?owner=' + id, 'GET'], [path + '/', 'GET'], [path + '/execute', 'GET'],
    [base + '/runs', 'GET'], [base + '/execute', 'POST'],
    [path.replace('/chief/', '/custom/'), 'GET'], [path.replace(id, id.toUpperCase().replace(/1$/, 'A')), 'GET'],
    [base + '/runs/not-a-uuid', 'GET'],
  ]) {
    assert.equal(permittedAuthenticatedApiPath(origin + target, method), null, target + ' ' + method);
    const session = auth(); let calls = 0;
    const result = await proxy(request(target, contract, method, method === 'POST' ? '{}' : undefined), session, () => { calls++; return json(); });
    assert.equal(result.status, 404); assert.deepEqual(session.counts(), {reads: 0, tokens: 0}); assert.equal(calls, 0);
  }
  const session = auth(); let calls = 0;
  const result = await proxy(request(path + '?'), session, () => { calls++; return json(); });
  assert.equal(result.status, 426); assert.deepEqual(session.counts(), {reads: 0, tokens: 0}); assert.equal(calls, 0);
});

test('rejects cross-family contracts and renderer-supplied authority on the saved-run route', async () => {
  for (const extra of [{'X-Cosmas-Team-Contract': '2'}, {'X-Cosmas-Model-Contract': '1'}, {'X-Cosmas-Inbox-Contract': '1'},
    {'X-Cosmas-Vendor-Contract': '1'}, {Authorization: 'Bearer invented'}, {'X-Actor-Principal-Id': id},
    {'X-Box-Id': id}, {Cookie: 'invented=1'}, {Origin: 'https://outside.invalid'}]) {
    const session = auth(); let calls = 0;
    const result = await proxy(request(path, {...contract, ...extra}), session, () => { calls++; return json(); });
    assert.ok([401, 426].includes(result.status)); assert.deepEqual(session.counts(), {reads: 0, tokens: 0}); assert.equal(calls, 0);
  }
});

test('retains the 32 KiB saved-run response ceiling and unchanged routine save input ceiling', async () => {
  for (const headers of [{}, contract]) {
    const exact = '"' + 'x'.repeat(32766) + '"';
    const accepted = await proxy(request(path, headers), auth(), async () => json(exact));
    assert.equal(accepted.status, 200); assert.equal(Buffer.byteLength(await accepted.text()), 32768);
    const oversized = await proxy(request(path, headers), auth(), async () => json(exact + ' '));
    assert.equal(oversized.status, 503); assert.doesNotMatch(await oversized.text(), /xxxxx/);
  }
  const session = auth(); let calls = 0;
  const oversized = await proxy(request(base, {}, 'POST', '"' + 'x'.repeat(2047) + '"'), session, () => { calls++; return json(); });
  assert.equal(oversized.status, 503); assert.equal(calls, 0); assert.equal(session.counts().tokens, 0);
});

test('bounds the entire saved-run call to 30 seconds including token acquisition without late dispatch', async t => {
  t.mock.timers.enable({apis: ['setTimeout']});
  for (const headers of [{}, contract]) {
    const session = auth(); let release, calls = 0, completed = false;
    session.getToken = () => new Promise(resolve => { release = resolve; });
    const pending = proxy(request(path, headers), session, () => { calls++; return json(); }).then(value => { completed = true; return value; });
    await tick(); t.mock.timers.tick(29999); await tick(); assert.equal(completed, false);
    t.mock.timers.tick(1); await tick(); assert.equal(completed, true);
    assert.equal((await pending).status, 401); release('invented.local.token'); await tick();
    assert.equal(calls, 0); assert.equal(session.listeners(), 0);
  }
});

test('retains the same 30 second saved-run budget while its response stream stalls', async t => {
  t.mock.timers.enable({apis: ['setTimeout']}); let cancelled = 0, completed = false;
  const pending = proxy(request(), auth(), async () => new Response(new ReadableStream({
    pull() { return new Promise(() => {}); }, cancel() { cancelled++; },
  }), {headers: {'Content-Type': 'application/json', 'Cache-Control': 'no-store'}})).then(value => { completed = true; return value; });
  await tick(); t.mock.timers.tick(30000); await tick(); assert.equal(completed, true);
  assert.equal((await pending).status, 401); assert.equal(cancelled, 1);
});

test('clears an in-flight saved brief on native session loss without retrying or releasing its late body', async () => {
  const session = auth(); let release, calls = 0, cancelled = 0;
  const pending = proxy(request(), session, () => { calls++; return new Promise(resolve => { release = resolve; }); });
  await tick(); session.revoke(); assert.equal((await pending).status, 401);
  release(new Response(new ReadableStream({cancel() { cancelled++; }}), {headers: {'Content-Type': 'application/json', 'Cache-Control': 'no-store'}}));
  await tick(); assert.equal(calls, 1); assert.equal(cancelled, 1); assert.equal(session.listeners(), 0);
});

test('carries the exact routine header through the direct adapter using a request stub and no sockets', async () => {
  let calls = 0, endpoint;
  const transport = (url, options) => local(url, options, (config, reply) => {
    calls++; endpoint = config; const req = new EventEmitter();
    req.write = () => assert.fail('GET body must not be written');
    req.end = () => {
      const res = new PassThrough(); res.statusCode = 200;
      res.headers = {'content-type': 'application/json', 'cache-control': 'no-store', 'set-cookie': 'withheld'};
      reply(res); res.end('{"invented":"saved"}');
    };
    return req;
  });
  const result = await proxy(request(), auth(), transport);
  assert.equal(result.status, 200); assert.equal(await result.text(), '{"invented":"saved"}'); assert.equal(calls, 1);
  assert.equal(endpoint.host, '127.0.0.1'); assert.equal(endpoint.port, 8046); assert.equal(endpoint.path, path);
  assert.equal(endpoint.method, 'GET'); assert.equal(endpoint.agent, false); assert.equal(endpoint.headers[header], '2');
  assert.equal(endpoint.headers.Authorization, 'Bearer invented.local.token'); assert.equal(endpoint.headers['X-Cosmas-Desktop-Session'], undefined);
  assert.equal(result.headers.get('Set-Cookie'), null);
});

test('keeps saved-run inspection out of the retained synthetic desktop transport', async () => {
  assert.equal(syntheticPath(origin + path, 'GET'), null); let calls = 0;
  assert.equal((await syntheticProxy(request(), () => { calls++; return json(); })).status, 404); assert.equal(calls, 0);
});
