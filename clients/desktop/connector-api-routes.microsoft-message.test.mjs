import assert from 'node:assert/strict';
import test from 'node:test';
import {connectorApiRoute, CONNECTOR_HEADERS} from './connector-api-routes.mjs';
import {permittedAuthenticatedApiPath, proxyAuthenticatedWorkspaceRequest as proxy} from './workspace-auth-proxy.mjs';

const id = '00000000-0000-4000-8000-000000000001';
const header = 'X-Cosmas-Microsoft-Messages';
const messagePath = '/connections/microsoft/messages';
const reviewPath = `/workspaces/${id}/microsoft-messages/review`;
const paths = [messagePath, reviewPath];
const tick = () => new Promise(resolve => setImmediate(resolve));
const sized = n => '"' + 'x'.repeat(n - 2) + '"';

function auth() {
  let state = {phase:'ready', revision:id, identity:{userId:'invented', sessionId:'invented', organizationId:'invented'}};
  const listeners = new Set();
  let tokens = 0, states = 0;
  return {getState:async() => {states++; return state;}, snapshot:() => state,
    getToken:async() => {tokens++; return 'invented.local.token';}, counts:() => ({tokens, states}),
    subscribe:fn => {listeners.add(fn); return () => listeners.delete(fn);},
    revoke() {state = {phase:'signedOut', revision:id, identity:null}; for (const fn of listeners) fn(state);}};
}
function request(path = messagePath, {headers = {}, body = '{}', method = 'POST'} = {}) {
  return new Request('app://cosmas/api' + path, {method,
    headers:{'Content-Type':'application/json', 'X-Cosmas-Desktop-Session':id, [header]:'1', ...headers},
    ...(method === 'POST' ? {body, duplex:'half'} : {})});
}
function response(body = '{}', status = 200, headers = {}) {
  return new Response(body, {status, headers:{'Content-Type':'application/json', 'Cache-Control':'no-store', ...headers}});
}

test('Microsoft message routes have one negotiated family and exact bounded plans', () => {
  assert.equal(CONNECTOR_HEADERS.filter(value => value === header).length, 1);
  for (const path of paths) {
    assert.deepEqual(connectorApiRoute(path, 'POST'), {header, input:8192,
      output:path === reviewPath ? 12000000 : 131072, seconds:50, strictResponse:true, errorOutput:2048});
    assert.equal(permittedAuthenticatedApiPath('app://cosmas/api' + path, 'POST'), path);
  }
});

test('message routes reject wrong verbs, queries, normalization and selected vendor endpoints', () => {
  for (const path of paths) {
    for (const method of ['GET','PUT','PATCH','DELETE','HEAD','OPTIONS','post']) {
      assert.equal(connectorApiRoute(path, method), null);
    }
    for (const suffix of ['?','?message_id=other','?endpoint=https://outside.invalid','/','/send','/attachments']) {
      assert.equal(connectorApiRoute(path + suffix, 'POST'), null);
      assert.equal(permittedAuthenticatedApiPath('app://cosmas/api' + path + suffix, 'POST'), null);
    }
    for (const url of ['https://outside.invalid' + path, 'app://outside/api' + path,
      'app://name:secret@cosmas/api' + path, 'app://cosmas/api' + path + '#fragment',
      'app://cosmas/api' + path.replace('/microsoft', '/extra/../microsoft'),
      'app://cosmas/api' + path.replace('microsoft', '%6dicrosoft')]) {
      assert.equal(permittedAuthenticatedApiPath(url, 'POST'), null, url);
    }
  }
  assert.equal(connectorApiRoute('/workspaces/not-a-uuid/microsoft-messages/review', 'POST'), null);
  assert.equal(connectorApiRoute('https://outlook.microsoftapis.com/outlook/v1/users/me/messages', 'POST'), null);
});

test('only the exact message contract is admitted before native credentials', async () => {
  for (const path of paths) {
    for (const value of [null, '', '0', '2', '1, 1']) {
      const req = request(path), session = auth();
      if (value === null) req.headers.delete(header); else req.headers.set(header, value);
      assert.equal((await proxy(req, session, () => assert.fail('unnegotiated dispatch'))).status, 426);
      assert.deepEqual(session.counts(), {tokens:0, states:0});
    }
    for (const other of CONNECTOR_HEADERS.filter(value => value !== header)) {
      const session = auth();
      assert.equal((await proxy(request(path, {headers:{[other]:'1'}}), session,
        () => assert.fail('mixed connector family'))).status, 426);
      assert.deepEqual(session.counts(), {tokens:0, states:0});
    }
  }
  assert.equal((await proxy(request('/provider-team'), auth(), () => assert.fail('misplaced family'))).status, 426);
});

test('message proxy preserves exact bytes and strips renderer-selected identity and upstream cookies', async () => {
  for (const path of paths) {
    const body = ' {"invented":"selected message command"} ';
    let calls = 0;
    const result = await proxy(request(path, {body, headers:{'X-Renderer-Endpoint':'https://outside.invalid'}}), auth(),
      async (url, options) => {
        calls++;
        assert.equal(url, 'http://127.0.0.1:8046' + path);
        assert.equal(options.method, 'POST');
        assert.equal(options.headers[header], '1');
        assert.equal(options.headers.Authorization, 'Bearer invented.local.token');
        assert.equal(options.headers['X-Cosmas-Microsoft-Connection'], undefined);
        assert.equal(options.headers['X-Cosmas-Desktop-Session'], undefined);
        assert.equal(options.headers['X-Renderer-Endpoint'], undefined);
        assert.deepEqual(options.body, new TextEncoder().encode(body));
        assert.equal(options.redirect, 'error');
        assert.equal(options.credentials, 'omit');
        return response('{}', 200, {'Set-Cookie':'invented=private'});
      });
    assert.equal(result.status, 200); assert.equal(calls, 1);
    assert.equal(result.headers.get('set-cookie'), null);
    assert.equal(result.headers.get('cache-control'), 'no-store');
  }
});

test('message request cap and malformed JSON refuse dispatch before native tokens', async () => {
  for (const path of paths) {
    let calls = 0;
    assert.equal((await proxy(request(path, {body:sized(8192)}), auth(), async () => {calls++; return response();})).status, 200);
    assert.equal(calls, 1);
    for (const body of [sized(8193), '{']) {
      const session = auth();
      assert.equal((await proxy(request(path, {body}), session, () => assert.fail('invalid body'))).status, 503);
      assert.equal(session.counts().tokens, 0);
    }
  }
});

test('message result and error responses are bounded before private bytes are disclosed', async () => {
  for (const path of paths) {
    const maximum = path === reviewPath ? 12000000 : 131072;
    const exact = await proxy(request(path), auth(), async () => response(sized(maximum)));
    assert.equal(exact.status, 200); assert.equal((await exact.arrayBuffer()).byteLength, maximum);
    assert.equal((await proxy(request(path), auth(), async () => response(sized(maximum + 1)))).status, 503);
    assert.equal((await proxy(request(path), auth(), async () => response(sized(2048), 409))).status, 409);
    assert.equal((await proxy(request(path), auth(), async () => response(sized(2049), 409))).status, 503);
    for (const headers of [{'Content-Type':'text/html'}, {'Cache-Control':'public'}, {'Content-Encoding':'identity'}, {'Content-Length':'0002'}]) {
      assert.equal((await proxy(request(path), auth(), async () => response('{}', 200, headers))).status, 502);
    }
  }
});

test('message proxy refuses renderer credentials and binary or artifact write authority', async () => {
  for (const forbidden of ['Authorization','X-Box-Id','X-Actor-Principal-Id','Cookie','Content-Encoding']) {
    const session = auth();
    assert.equal((await proxy(request(messagePath, {headers:{[forbidden]:'invented'}}), session,
      () => assert.fail('renderer credential'))).status, 401);
    assert.deepEqual(session.counts(), {tokens:0, states:0});
  }
  assert.equal((await proxy(request(messagePath, {headers:{'Content-Type':'application/pdf'}}), auth(), () => assert.fail('binary'))).status, 400);
  assert.equal((await proxy(request(reviewPath, {headers:{'X-Cosmas-Artifact-Write-Key':'invented-key'}}), auth(), () => assert.fail('artifact'))).status, 400);
});

test('message sign-out during a private response cancels disclosure with no retry', async () => {
  const session = auth(); let cancelled = 0, calls = 0;
  const pending = proxy(request(messagePath), session, async () => {calls++; return response(new ReadableStream({
    pull() {return new Promise(() => {});}, cancel() {cancelled++;}}));});
  await tick(); session.revoke();
  assert.equal((await pending).status, 401); assert.equal(calls, 1); assert.equal(cancelled, 1);
});

test('message 50-second budget fences a late credential and forbids later dispatch', async t => {
  t.mock.timers.enable({apis:['setTimeout']});
  const session = auth(); let release, calls = 0;
  session.getToken = () => new Promise(resolve => {release = resolve;});
  const pending = proxy(request(messagePath), session, async () => {calls++; return response();});
  await tick(); t.mock.timers.tick(50000);
  assert.equal((await pending).status, 504); release('invented.local.token'); await tick();
  assert.equal(calls, 0);
});
