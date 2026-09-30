import assert from 'node:assert/strict';
import test from 'node:test';
import {permittedAuthenticatedApiPath, proxyAuthenticatedWorkspaceRequest} from './workspace-auth-proxy.mjs';

const id = '00000000-0000-4000-8000-000000000001';
const ready = {phase: 'ready', revision: id, identity: {userId: 'user_one', sessionId: 'sess_one', organizationId: 'org_one'}};
const response = value => Response.json(value, {headers: {'Cache-Control': 'no-store'}});
const tick = () => new Promise(resolve => setImmediate(resolve));

test('capture operation transport carries long corrections/reviews with finite bounds', async () => {
  const path=`/workspaces/${id}/capture/operations`;
  const body=JSON.stringify({content:'🩺'.repeat(500_000)});
  const accepted=await proxyAuthenticatedWorkspaceRequest(request(path,{method:'POST',body}),fixture(),async (_url,options)=>{
    assert.equal(new TextDecoder().decode(options.body),body);
    return response({text:'x'.repeat(26*1024*1024)});
  });
  assert.equal(accepted.status,200);
  assert.equal((await accepted.json()).text.length,26*1024*1024);
  const tooLarge=await proxyAuthenticatedWorkspaceRequest(request(path,{method:'POST',body:' '.repeat(4*1024*1024+1)}),fixture(),()=>assert.fail('no oversized request dispatch'));
  assert.equal(tooLarge.status,503);
  const oversized=await proxyAuthenticatedWorkspaceRequest(request(path,{method:'POST',body:'{}'}),fixture(),async()=>
    new Response(new Uint8Array(32*1024*1024+4097),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}));
  assert.equal(oversized.status,503);
});

test('preparation admits exact private read/review routes with bounded input and receipts', async () => {
  const base = `/workspaces/${id}/prep-work`;
  for (const [suffix, method] of [['', 'GET'], ['', 'POST'], ['/' + id, 'GET'], ['/' + id + '/decide', 'POST'], ['/' + id + '/verify', 'POST']]) {
    assert.equal(permittedAuthenticatedApiPath('app://cosmas/api' + base + suffix, method), base + suffix);
  }
  for (const [suffix, method] of [['/' + id, 'POST'], ['/' + id + '/decide', 'GET'], ['/' + id + '/verify', 'GET'],
    ['/' + id + '/send', 'POST'], ['/' + id + '/execute', 'POST'], ['/pages/' + id, 'GET'], ['?owner=' + id, 'GET']]) {
    assert.equal(permittedAuthenticatedApiPath('app://cosmas/api' + base + suffix, method), null);
  }
  const accepted = await proxyAuthenticatedWorkspaceRequest(request(base, {method:'POST',body:JSON.stringify({body:'x'.repeat(4000)})}), fixture(), async (url, options) => {
    assert.equal(url, 'http://127.0.0.1:8046' + base);
    assert.equal(options.headers.Authorization, 'Bearer local.binding.fixture');
    return response({entry_revision:3,items:[]});
  });
  assert.equal(accepted.status, 200);
  const input = await proxyAuthenticatedWorkspaceRequest(request(base, {method:'POST',body:JSON.stringify({body:'x'.repeat(32768)})}), fixture(), () => assert.fail('no upstream'));
  assert.equal(input.status, 503);
  const output = await proxyAuthenticatedWorkspaceRequest(request(base), fixture(), async () => response({body:'x'.repeat(1048576)}));
  assert.equal(output.status, 503);
});

test('forwards the known recovery generation without treating it as identity or action authority', async () => {
  const result = await proxyAuthenticatedWorkspaceRequest(request('/provider-team', {headers: {'X-Cosmas-Draft-Recovery': '2'}}), fixture(), async (_url, options) => {
    assert.equal(options.headers['X-Cosmas-Draft-Recovery'], '2');
    assert.equal(options.headers.Authorization, 'Bearer local.binding.fixture');
    return response({revision: 1});
  });
  assert.equal(result.status, 200);
  const invalid = await proxyAuthenticatedWorkspaceRequest(request('/provider-team', {headers: {'X-Cosmas-Draft-Recovery': 'unknown'}}), fixture(), () => assert.fail('no upstream'));
  assert.equal(invalid.status, 400);
});

test('private routines allow bounded configuration and history but no dispatch or foreign selectors', async () => {
  for (const bot of ['chief', 'scribe', 'follow_up', 'visit_prep', id]) {
    const path = '/provider-team/routines/' + bot;
    for (const method of ['GET', 'POST']) assert.equal(permittedAuthenticatedApiPath('app://cosmas/api' + path, method), path);
    assert.equal(permittedAuthenticatedApiPath('app://cosmas/api' + path + '/runs/' + id, 'GET'), path + '/runs/' + id);
    for (const suffix of ['/run', '/execute', '/send', '/runs/' + id]) assert.equal(permittedAuthenticatedApiPath('app://cosmas/api' + path + suffix, 'POST'), null);
  }
  for (const path of ['/provider-team/routines/custom', '/provider-team/routines/chief?owner=' + id, '/provider-team/routines/chief/runs'])
    assert.equal(permittedAuthenticatedApiPath('app://cosmas/api' + path, 'GET'), null);
  const path = '/provider-team/routines/chief';
  const accepted = await proxyAuthenticatedWorkspaceRequest(request(path, {method:'POST', body:'{}'}), fixture(), async (url, options) => {
    assert.equal(url, 'http://127.0.0.1:8046' + path); assert.equal(options.headers.Authorization, 'Bearer local.binding.fixture');
    return response({status:'paused'});
  });
  assert.equal(accepted.status, 200);
  const tooBig = await proxyAuthenticatedWorkspaceRequest(request(path, {method:'POST', body:JSON.stringify({text:'x'.repeat(2048)})}), fixture(), () => assert.fail('no upstream'));
  assert.equal(tooBig.status, 503);
  const reply = await proxyAuthenticatedWorkspaceRequest(request(path + '/runs/' + id), fixture(), async () => response({text:'x'.repeat(32768)}));
  assert.equal(reply.status, 503);
});

test('appointment preparation and review allow exact paths with bounded bodies', async () => {
  const path = `/workspaces/${id}/appointments/${id}`;
  const collection = `/workspaces/${id}/appointments`;
  for (const [suffix, method] of [['', 'GET'], ['', 'POST'], ['/pages/' + id, 'GET'], ['/current', 'POST']]) {
    assert.equal(permittedAuthenticatedApiPath('app://cosmas/api' + collection + suffix, method), collection + suffix);
  }
  for (const [suffix, method] of [['/current', 'GET'], ['/pages/' + id, 'POST'], ['/pages', 'GET'],
    ['/book', 'POST'], ['/reschedule', 'POST'], ['/cancel', 'POST'], ['/execute', 'POST']]) {
    assert.equal(permittedAuthenticatedApiPath('app://cosmas/api' + collection + suffix, method), null);
  }
  assert.equal(permittedAuthenticatedApiPath('app://cosmas/api' + path, 'GET'), path);
  assert.equal(permittedAuthenticatedApiPath('app://cosmas/api' + path + '/decide', 'POST'), path + '/decide');
  for (const [suffix, method] of [['', 'POST'], ['/send', 'POST'], ['/execute', 'GET'], ['/decide', 'GET'],
    ['/cancel', 'POST'], ['/reschedule', 'POST'], ['?patient_id=' + id, 'GET']]) {
    assert.equal(permittedAuthenticatedApiPath('app://cosmas/api' + path + suffix, method), null);
  }
  const body = JSON.stringify({revision_id: id, payload_hash: 'a'.repeat(64), choice: 'approve'});
  const auth = fixture();
  const pending = await proxyAuthenticatedWorkspaceRequest(request(path + '/decide', {method: 'POST', body}), auth,
    async (url, options) => {
      assert.equal(url, 'http://127.0.0.1:8046' + path + '/decide');
      assert.equal(new TextDecoder().decode(options.body), body);
      return response({state: 'approved', operation_status: 'pending', appointment_saved: false});
    });
  assert.equal(pending.status, 200);
  assert.equal((await pending.json()).appointment_saved, false);
  const oversized = await proxyAuthenticatedWorkspaceRequest(request(path + '/decide', {
    method: 'POST', body: JSON.stringify({private: 'x'.repeat(2048)})}), fixture(), () => assert.fail('no upstream'));
  assert.equal(oversized.status, 503);
  const largeReply = await proxyAuthenticatedWorkspaceRequest(request(path), fixture(),
    async () => response({private: 'x'.repeat(32768)}));
  assert.equal(largeReply.status, 503);
  for (const suffix of ['', '/current']) {
    const largeBody = await proxyAuthenticatedWorkspaceRequest(request(collection + suffix, {
      method: 'POST', body: JSON.stringify({private: 'x'.repeat(2048)})}), fixture(), () => assert.fail('no upstream'));
    assert.equal(largeBody.status, 503);
  }
  const largeCatalog = await proxyAuthenticatedWorkspaceRequest(request(collection), fixture(),
    async () => response({private: 'x'.repeat(32768)}));
  assert.equal(largeCatalog.status, 503);
});
function fixture() {
  let current = ready; const listeners = new Set(); let tokenCalls = 0;
  return {getState: async () => current, snapshot: () => current,
    getToken: async revision => { assert.equal(revision, id); tokenCalls++; return 'local.binding.fixture'; },
    subscribe: listener => { listeners.add(listener); return () => listeners.delete(listener); },
    change: () => { current = {phase: 'signedOut', revision: '00000000-0000-4000-8000-000000000002', identity: null};
      for (const listener of listeners) listener(current); }, tokenCalls: () => tokenCalls};
}
function request(path = '/workspaces', options = {}) {
  return new Request('app://cosmas/api' + path, {...options,
    headers: {'Content-Type': 'application/json', 'X-Cosmas-Desktop-Session': id, ...options.headers}});
}

test('existing Scribe source routes admit only exact reviewed selections before credentials', async () => {
  const packets={idempotency_key:'source-share-1',expected_revision:3,reviewed:true,share_with_team:true,
    selection:{version:1,session_id:id,source_transcript_version:2,working_transcript_id:id,
      working_transcript_version:3,snapshot_sha256:'a'.repeat(64)}};
  for (const [action,body] of [['existing',{idempotency_key:'source-read-1'}],['source-packets',packets]]) {
    const path=`/workspaces/${id}/capture/${action}`;
    assert.equal(permittedAuthenticatedApiPath('app://cosmas/api'+path,'POST'),path);
    for(const method of ['GET','PUT','PATCH','DELETE','HEAD','OPTIONS','post'])
      assert.equal(permittedAuthenticatedApiPath('app://cosmas/api'+path,method),null);
    for(const suffix of ['?','?owner='+id,'/send','/','/resolve'])
      assert.equal(permittedAuthenticatedApiPath('app://cosmas/api'+path+suffix,'POST'),null);
    assert.equal(permittedAuthenticatedApiPath('app://cosmas/api/ignored/../'+path.slice(1),'POST'),null);
    const auth=fixture();
    const result=await proxyAuthenticatedWorkspaceRequest(request(path,{method:'POST',body:JSON.stringify(body)}),auth,
      async (url,options)=>{
        assert.equal(url,'http://127.0.0.1:8046'+path);
        assert.deepEqual(JSON.parse(new TextDecoder().decode(options.body)),body);
        assert.equal(options.headers.Authorization,'Bearer local.binding.fixture');
        assert.equal(options.headers['X-Box-Id'],undefined);
        assert.equal(options.headers['X-Actor-Principal-Id'],undefined);
        assert.equal(options.credentials,'omit');assert.equal(options.redirect,'error');
        return response({status:'available'});
      });
    assert.equal(result.status,200);assert.equal(auth.tokenCalls(),1);
    for(const bad of [null,[],{}, {...body,url:'https://outside.invalid'}, {...body,idempotency_key:'short'},
      ...(action==='source-packets'?[{...body,reviewed:false},{...body,share_with_team:1},
        {...body,expected_revision:0},{...body,selection:{...packets.selection,snapshot_sha256:'bad'}},
        {...body,selection:{...packets.selection,patient_id:id}}]:[])]) {
      const auth=fixture();
      const rejected=await proxyAuthenticatedWorkspaceRequest(request(path,{method:'POST',body:JSON.stringify(bad)}),auth,
        ()=>assert.fail('No malformed Scribe source request dispatch'));
      assert.equal(rejected.status,400);assert.equal(auth.tokenCalls(),0);
    }
    const encoded=JSON.stringify(body),exact=encoded+' '.repeat(2048-Buffer.byteLength(encoded));
    assert.equal((await proxyAuthenticatedWorkspaceRequest(request(path,{method:'POST',body:exact}),fixture(),
      async()=>response({status:'available'}))).status,200);
    const oversizedAuth=fixture();
    assert.equal((await proxyAuthenticatedWorkspaceRequest(request(path,{method:'POST',body:exact+' '}),oversizedAuth,
      ()=>assert.fail('No oversized Scribe source request dispatch'))).status,503);
    assert.equal(oversizedAuth.tokenCalls(),0);
  }
});

test('allows exact private workspace/capture operations and denies demo/admin or generic effects', () => {
  for (const path of ['/workspaces', '/provider-team', `/workspaces/${id}`, '/practice-work', `/practice-work/${id}`, `/practice-work/pages/${id}`]) {
    assert.equal(permittedAuthenticatedApiPath('app://cosmas/api' + path, 'GET'), path);
  }
  for (const path of ['/workspaces', '/provider-team', `/workspaces/${id}/notes`, `/workspaces/${id}/capture/note-links`,
    `/practice-work/${id}/handoffs`, `/practice-work/${id}/complete`,
    `/workspaces/${id}/scheduling/availability`, `/workspaces/${id}/capture/operations`, `/workspaces/${id}/capture/prep`, `/workspaces/${id}/follow-ups/${id}/decide`, `/workspaces/${id}/notes/${id}/review`]) {
    assert.equal(permittedAuthenticatedApiPath('app://cosmas/api' + path, 'POST'), path);
  }
  for (const path of ['/synth/demo-queue', '/admin/identities/bind', '/retention/purge', '/queue',
    `/practice-work/${id}/send`, `/practice-work/${id}/decide`, `/practice-work/pages/${id}`,
    `/workspaces/${id}/scheduling/book`, `/workspaces/${id}/scheduling/cancel`, `/tickets/${id}/decide`, `/workspaces/${id}/follow-ups/${id}/send`, `/workspaces/${id}/notes/${id}/sign`]) {
    assert.equal(permittedAuthenticatedApiPath('app://cosmas/api' + path, 'POST'), null);
  }
  for (const url of ['https://cosmas/api/workspaces', 'app://other/api/workspaces', 'app://user@cosmas/api/workspaces',
    'app://cosmas:8046/api/workspaces', 'app://cosmas/api/workspaces?next=https://other.invalid', 'app://cosmas/api/%2e%2e/private']) {
    assert.equal(permittedAuthenticatedApiPath(url, 'GET'), null);
  }
});

test('appointment execution forwards only the exact bounded approved-operation command route', async () => {
  const path = `/workspaces/${id}/appointments/${id}/execute`;
  assert.equal(permittedAuthenticatedApiPath('app://cosmas/api' + path, 'POST'), path);
  for (const [suffix, method] of [['', 'GET'], ['/retry', 'POST'], ['?mode=submit', 'POST'], ['/send', 'POST']]) {
    assert.equal(permittedAuthenticatedApiPath('app://cosmas/api' + path + suffix, method), null);
  }
  for (const mode of ['submit', 'reconcile', 'retry']) {
    const body = JSON.stringify({operation_id: id, revision_id: id, payload_hash: 'a'.repeat(64), mode});
    const result = await proxyAuthenticatedWorkspaceRequest(request(path, {method: 'POST', body}), fixture(), async (url, options) => {
      assert.equal(url, 'http://127.0.0.1:8046' + path);
      assert.equal(new TextDecoder().decode(options.body), body);
      assert.equal(options.headers.Authorization, 'Bearer local.binding.fixture');
      assert.equal(options.headers['X-Cosmas-Team-Contract'], undefined);
      return response({appointment_saved: true, calendar_state: 'pending'});
    });
    assert.equal(result.status, 200);
    assert.equal((await result.json()).calendar_state, 'pending');
  }
  const oversized = await proxyAuthenticatedWorkspaceRequest(request(path, {method: 'POST', body: JSON.stringify({text: 'x'.repeat(2048)})}),
    fixture(), () => assert.fail('No oversized command dispatch'));
  assert.equal(oversized.status, 503);
});

test('injects a fresh token only in main and strips non-contract response headers', async () => {
  const auth = fixture(); const captured = [];
  const fetch = async (url, options) => { captured.push({url, options}); return Response.json({saved: true},
    {headers: {'Cache-Control': 'no-store', 'Set-Cookie': 'never-forwarded'}}); };
  for (let index = 0; index < 2; index++) {
    const result = await proxyAuthenticatedWorkspaceRequest(request('/provider-team', {method: 'POST', body: '{}'}), auth, fetch);
    assert.deepEqual(await result.json(), {saved: true}); assert.equal(result.headers.get('Set-Cookie'), null);
  }
  assert.equal(auth.tokenCalls(), 2);
  for (const {url, options} of captured) {
    assert.equal(url, 'http://127.0.0.1:8046/provider-team');
    assert.deepEqual(options.headers, {'Content-Type': 'application/json', Authorization: 'Bearer local.binding.fixture', Origin: 'app://cosmas'});
    assert.equal(options.redirect, 'error'); assert.equal(options.credentials, 'omit');
  }
});

for (const headers of [{Authorization: 'forged'}, {'X-Box-Id': id}, {'X-Actor-Principal-Id': id}, {Cookie: 'forged'},
  {Origin: 'https://outside.invalid'}, {'X-Cosmas-Desktop-Session': 'invalid'}]) {
  test('rejects renderer credential/identity/origin substitution: ' + Object.keys(headers).join(','), async () => {
    const result = await proxyAuthenticatedWorkspaceRequest(request('/workspaces', {headers}), fixture(), () => assert.fail('upstream'));
    assert.equal(result.status, 401);
  });
}

test('logout during token acquisition prevents the upstream request', async () => {
  const auth = fixture(); let release;
  auth.getToken = () => new Promise(resolve => { release = resolve; });
  const result = proxyAuthenticatedWorkspaceRequest(request(), auth, () => assert.fail('upstream'));
  await tick(); auth.change(); release('local.binding.fixture');
  assert.equal((await result).status, 401);
});

test('logout while an upstream reply is delayed discards private response bytes', async () => {
  const auth = fixture(); let release;
  const result = proxyAuthenticatedWorkspaceRequest(request(), auth, () => new Promise(resolve => { release = resolve; }));
  await tick(); auth.change(); release(response({secret: 'private invented note'}));
  const denied = await result; assert.equal(denied.status, 401);
  assert.equal((await denied.text()).includes('private invented note'), false);
});

test('malformed/oversize request data and uncacheable response contracts fail closed', async () => {
  for (const body of ['not-json', 'x'.repeat(128001)]) {
    const result = await proxyAuthenticatedWorkspaceRequest(request('/provider-team', {method: 'POST', body}), fixture(), () => assert.fail('upstream'));
    assert.equal(result.status, 503);
  }
  const result = await proxyAuthenticatedWorkspaceRequest(request(), fixture(), async () => Response.json({private: true}));
  assert.equal(result.status, 502); assert.equal((await result.text()).includes('private'), false);
});

for (const stage of ['initial state', 'credential', 'response', 'final state']) {
  test('deadline releases a stalled ' + stage + ' and prevents late dispatch', async t => {
    t.mock.timers.enable({apis: ['setTimeout']});
    const auth = fixture(); let release; let calls = 0; let reads = 0; let removed = 0;
    const never = () => new Promise(resolve => { release = resolve; });
    const originalSubscribe = auth.subscribe;
    auth.subscribe = listener => { const remove = originalSubscribe(listener); return () => { removed++; remove(); }; };
    if (stage === 'initial state') auth.getState = never;
    if (stage === 'credential') auth.getToken = never;
    if (stage === 'final state') auth.getState = async () => ++reads === 1 ? ready : never();
    const result = proxyAuthenticatedWorkspaceRequest(request('/provider-team'), auth, async () => {
      calls++;
      return stage === 'response' ? never() : response({private: 'must not escape an expired request'});
    });
    await tick();
    assert.equal(typeof release, 'function');
    t.mock.timers.tick(45001);
    const ended = await result;
    assert.equal(ended.status, 401);
    assert.equal((await ended.text()).includes('private'), false);
    assert.equal(removed, 1);
    const beforeLate = calls;
    release(stage === 'credential' ? 'local.binding.fixture' : stage === 'response' ? response({late: true}) : ready);
    await tick();
    assert.equal(calls, beforeLate);
    if (stage === 'credential' || stage === 'initial state') assert.equal(calls, 0);
  });
}

test('pre-aborted requests do not acquire native credentials or state', async () => {
  const controller = new AbortController(); controller.abort();
  const auth = fixture(); auth.getState = () => assert.fail('no state acquisition');
  const result = await proxyAuthenticatedWorkspaceRequest(request('/provider-team', {signal: controller.signal}), auth,
    () => assert.fail('no upstream request'));
  assert.equal(result.status, 503);
  assert.equal(auth.tokenCalls(), 0);
});

test('team setup exposes only paired read and pure rehearsal routes', async () => {
  for (const [path, method] of [['/provider-team', 'GET'], ['/provider-team', 'POST'],
    ['/provider-team/setup', 'GET'], ['/provider-team/rehearsal', 'POST']]) {
    assert.equal(permittedAuthenticatedApiPath('app://cosmas/api' + path, method), path);
    for (const version of ['1', '2']) {
      const result = await proxyAuthenticatedWorkspaceRequest(request(path, {method,
        ...(method === 'POST' ? {body: '{}'} : {}), headers: {'X-Cosmas-Team-Contract': version}}), fixture(), async (url, options) => {
        assert.equal(url, 'http://127.0.0.1:8046' + path);
        assert.equal(options.headers['X-Cosmas-Team-Contract'], version);
        assert.equal(options.headers.Authorization, 'Bearer local.binding.fixture');
        return response({local: true});
      });
      assert.equal(result.status, 200);
    }
  }
  for (const [path, method] of [['/provider-team/setup', 'POST'], ['/provider-team/rehearsal', 'GET'],
    ['/provider-team/setup/activate', 'POST'], ['/provider-team/presets', 'POST'],
    ['/provider-team/rehearsal/send', 'POST'], ['/provider-team/setup?owner=' + id, 'GET'],
    ['/provider-team/setup/', 'GET'], ['/provider-team/%73etup', 'GET']]) {
    assert.equal(permittedAuthenticatedApiPath('app://cosmas/api' + path, method), null);
  }
});

test('requires known team contract only on setup pairs and rejects combined or foreign headers', async () => {
  for (const [path, method, value] of [['/provider-team/setup', 'GET', null], ['/provider-team/rehearsal', 'POST', null],
    ['/provider-team', 'GET', '5'], ['/provider-team', 'POST', '1, 1'], ['/provider-team', 'POST', '1, 2'], ['/workspaces', 'GET', '1'],
    ['/provider-team/routines/chief', 'GET', '1']]) {
    const result = await proxyAuthenticatedWorkspaceRequest(request(path, {method,
      ...(method === 'POST' ? {body: '{}'} : {}), headers: value === null ? {} : {'X-Cosmas-Team-Contract': value}}),
    fixture(), () => assert.fail('no upstream request'));
    assert.equal(result.status, 426);
  }
  const legacy = await proxyAuthenticatedWorkspaceRequest(request('/provider-team'), fixture(), async (_url, options) => {
    assert.equal(options.headers['X-Cosmas-Team-Contract'], undefined);
    return response({revision: 0});
  });
  assert.equal(legacy.status, 200);
});

test('team bodies fit retained configurations while enforcing byte bounds only on exact routes', async () => {
  const body = JSON.stringify({text: '😀'.repeat(750000)});
  for (const path of ['/provider-team', '/provider-team/rehearsal']) {
    const accepted = await proxyAuthenticatedWorkspaceRequest(request(path, {method: 'POST', body,
      headers: {'X-Cosmas-Team-Contract': '1'}}), fixture(), async (_url, options) => {
      assert.equal(new TextDecoder().decode(options.body), body);
      return response({retained: true});
    });
    assert.equal(accepted.status, 200);
    const rejected = await proxyAuthenticatedWorkspaceRequest(request(path, {method: 'POST',
      body: JSON.stringify({text: '😀'.repeat(1048576)}), headers: {'X-Cosmas-Team-Contract': '1'}}), fixture(),
    () => assert.fail('no oversized request dispatch'));
    assert.equal(rejected.status, 503);
  }
  const unrelated = await proxyAuthenticatedWorkspaceRequest(request('/workspaces', {method: 'POST',
    body: JSON.stringify({text: 'x'.repeat(128000)})}), fixture(), () => assert.fail('unchanged route bound'));
  assert.equal(unrelated.status, 503);
  for (const path of ['/provider-team', '/provider-team/setup', '/provider-team/rehearsal']) {
    const result = await proxyAuthenticatedWorkspaceRequest(request(path, {
      ...(path.endsWith('/rehearsal') ? {method: 'POST', body: '{}'} : {}),
      headers: {'X-Cosmas-Team-Contract': '1'}}), fixture(), async () => response({text: 'x'.repeat(8388608)}));
    assert.equal(result.status, 503);
  }
});

test('logout releases a stalled credential before the helper responds', async () => {
  const auth = fixture(); let release; let dispatched = 0;
  auth.getToken = () => new Promise(resolve => { release = resolve; });
  const pending = proxyAuthenticatedWorkspaceRequest(request('/provider-team'), auth, async () => {
    dispatched++; return response({unexpected: true});
  });
  await tick(); auth.change();
  const ended = await pending;
  assert.equal(ended.status, 401);
  assert.equal(dispatched, 0);
  release('local.binding.fixture'); await tick();
  assert.equal(dispatched, 0);
});

for (const stage of ['request limit', 'response limit', 'invalid headers']) {
  test('rejects ' + stage + ' without waiting for stream cancellation', async t => {
    t.mock.timers.enable({apis: ['setTimeout']});
    const auth = fixture(); let removed = 0; let canceled = 0; let settled;
    const subscribe = auth.subscribe;
    auth.subscribe = listener => { const remove = subscribe(listener); return () => { removed++; remove(); }; };
    const body = new ReadableStream({
      start(controller) { controller.enqueue(new Uint8Array(stage === 'request limit' ? 4194305 : 8388609)); },
      cancel() { canceled++; return new Promise(() => {}); },
    });
    const input = request('/provider-team', stage === 'request limit'
      ? {method: 'POST', body, duplex: 'half'} : {});
    const pending = proxyAuthenticatedWorkspaceRequest(input, auth, async () => {
      assert.notEqual(stage, 'request limit', 'oversized request cannot dispatch');
      return new Response(body, {headers: {'Content-Type': stage === 'invalid headers' ? 'text/plain' : 'application/json',
        'Cache-Control': 'no-store'}});
    }).then(value => { settled = value; });
    await tick();
    assert.equal(settled?.status, stage === 'invalid headers' ? 502 : 503);
    assert.equal(canceled, 1);
    assert.equal(removed, 1);
    await pending;
  });
}

for (const stage of ['request', 'response']) {
  test('deadline releases a stalled ' + stage + ' reader despite stalled cancellation', async t => {
    t.mock.timers.enable({apis: ['setTimeout']});
    const auth = fixture(); let removed = 0; let canceled = 0; let calls = 0;
    const subscribe = auth.subscribe;
    auth.subscribe = listener => { const remove = subscribe(listener); return () => { removed++; remove(); }; };
    const body = new ReadableStream({
      pull() { return new Promise(() => {}); },
      cancel() { canceled++; return new Promise(() => {}); },
    });
    const pending = proxyAuthenticatedWorkspaceRequest(request('/provider-team', stage === 'request'
      ? {method: 'POST', body, duplex: 'half'} : {}), auth, async () => {
      calls++;
      return new Response(body, {headers: {'Content-Type': 'application/json', 'Cache-Control': 'no-store'}});
    });
    await tick(); t.mock.timers.tick(45001);
    const ended = await pending;
    assert.equal(ended.status, 401);
    assert.equal(removed, 1);
    assert.equal(canceled, 1);
    assert.equal(calls, stage === 'request' ? 0 : 1);
  });
}

const modelPaths = [`/workspaces/${id}/conversation`, `/workspaces/${id}/conversation/resolve`,
  `/workspaces/${id}/handoffs/${id}/retry`, `/workspaces/${id}/handoffs/${id}/retry/resolve`];
const modelHeaders = {'X-Cosmas-Model-Contract': '1'};
const jsonBytes = size => '{"text":"' + 'x'.repeat(size - 11) + '"}';

test('model negotiation forwards only exact submit and read-only resolve commands with unchanged bytes', async () => {
  for (const path of modelPaths) {
    assert.equal(permittedAuthenticatedApiPath('app://cosmas/api' + path, 'POST'), path);
    const body = '{"idempotency_key":"kept-unchanged","content":"\\u0061 😀"}';
    const receipt = '{"contract_version":1,"outcome":"unknown"}';
    const result = await proxyAuthenticatedWorkspaceRequest(request(path, {method: 'POST', body, headers: modelHeaders}),
      fixture(), async (url, options) => {
        assert.equal(url, 'http://127.0.0.1:8046' + path);
        assert.deepEqual([...options.body], [...new TextEncoder().encode(body)]);
        assert.equal(options.headers['X-Cosmas-Model-Contract'], '1');
        assert.equal(options.headers['X-Cosmas-Team-Contract'], undefined);
        assert.equal(options.headers.Authorization, 'Bearer local.binding.fixture');
        return new Response(receipt, {status: 409, headers: {'Content-Type': 'application/json', 'Cache-Control': 'no-store'}});
      });
    assert.equal(result.status, 409);
    assert.equal(await result.text(), receipt, 'unresolved receipt is not converted into a saved response');
    for (const [suffix, method] of [['', 'GET'], ['/', 'POST'], ['?owner=' + id, 'POST'], ['/send', 'POST'], ['/resolve', 'POST']]) {
      // The single documented /resolve suffix exists only on the original command.
      if (suffix === '/resolve' && !path.endsWith('/resolve')) continue;
      assert.equal(permittedAuthenticatedApiPath('app://cosmas/api' + path + suffix, method), null);
    }
  }
  for (const path of [`/workspaces/${id}/%63onversation`, `/workspaces/${id}/handoffs/${id}/resolve`,
    `/workspaces/${id}/conversation/execute`, `/workspaces/${id}/handoffs/${id}/retry%2fresolve`]) {
    assert.equal(permittedAuthenticatedApiPath('app://cosmas/api' + path, 'POST'), null);
  }
});

test('model contract rejects absent new-resolver, malformed, duplicate, combined and foreign negotiation before auth', async () => {
  const cases = modelPaths.flatMap(path => ['0', '2', '1, 1', '1, 2', ''].map(value => [path, 'POST', value]));
  cases.push(...modelPaths.filter(path => path.endsWith('/resolve')).map(path => [path, 'POST', null]));
  cases.push(['/workspaces', 'GET', '1'], ['/provider-team', 'GET', '1'],
    [`/workspaces/${id}/appointments/${id}/execute`, 'POST', '1'],
    [`/workspaces/${id}/capture/prep`, 'POST', '1'], [`/workspaces/${id}/entries`, 'POST', '1']);
  for (const [path, method, version] of cases) {
    const auth = fixture(); auth.getState = () => assert.fail('unsupported negotiation cannot acquire credentials');
    const result = await proxyAuthenticatedWorkspaceRequest(request(path, {method,
      ...(method === 'POST' ? {body: '{}'} : {}), headers: version === null ? {} : {'X-Cosmas-Model-Contract': version}}),
      auth, () => assert.fail('unsupported negotiation cannot dispatch'));
    assert.equal(result.status, 426, path + ' / ' + version);
  }
  const mixed = await proxyAuthenticatedWorkspaceRequest(request(modelPaths[0], {method: 'POST', body: '{}',
    headers: {...modelHeaders, 'X-Cosmas-Team-Contract': '2'}}), fixture(), () => assert.fail('team header cannot leak'));
  assert.equal(mixed.status, 426);
  const duplicate = new Request('app://cosmas/api' + modelPaths[0], {method: 'POST', body: '{}', headers: [
    ['Content-Type', 'application/json'], ['X-Cosmas-Desktop-Session', id],
    ['X-Cosmas-Model-Contract', '1'], ['x-cosmas-model-contract', '1']]});
  assert.equal((await proxyAuthenticatedWorkspaceRequest(duplicate, fixture(), () => assert.fail('duplicate header'))).status, 426);
});

test('original model paths retain missing-header legacy bounds without silently negotiating model authority', async () => {
  for (const path of modelPaths.filter(path => !path.endsWith('/resolve'))) {
    const body = jsonBytes(128000);
    const result = await proxyAuthenticatedWorkspaceRequest(request(path, {method: 'POST', body}), fixture(), async (_url, options) => {
      assert.equal(options.headers['X-Cosmas-Model-Contract'], undefined);
      assert.equal(options.body.byteLength, 128000);
      return new Response(jsonBytes(20000), {headers: {'Content-Type': 'application/json', 'Cache-Control': 'no-store'}});
    });
    assert.equal(result.status, 200);
    assert.equal((await result.arrayBuffer()).byteLength, 20000);
    const tooBig = await proxyAuthenticatedWorkspaceRequest(request(path, {method: 'POST', body: jsonBytes(128001)}), fixture(),
      () => assert.fail('legacy maximum unchanged'));
    assert.equal(tooBig.status, 503);
  }
});

test('negotiated model commands enforce exact byte ceilings on input and success or unresolved receipt', async () => {
  for (const path of modelPaths) {
    const maximum = path.includes('/conversation') ? 65536 : 2048;
    for (const status of [200, 409]) {
      const exact = await proxyAuthenticatedWorkspaceRequest(request(path, {method: 'POST', body: jsonBytes(maximum), headers: modelHeaders}),
        fixture(), async (_url, options) => {
          assert.equal(options.body.byteLength, maximum);
          return new Response(jsonBytes(16384), {status, headers: {'Content-Type': 'application/json', 'Cache-Control': 'no-store'}});
        });
      assert.equal(exact.status, status);
      assert.equal((await exact.arrayBuffer()).byteLength, 16384);
    }
    const overInput = await proxyAuthenticatedWorkspaceRequest(request(path, {method: 'POST', body: jsonBytes(maximum + 1), headers: modelHeaders}),
      fixture(), () => assert.fail('oversized model command cannot dispatch'));
    assert.equal(overInput.status, 503);
    const unicodeInput = await proxyAuthenticatedWorkspaceRequest(request(path, {method: 'POST',
      body: JSON.stringify({text: '😀'.repeat(maximum / 4)}), headers: modelHeaders}), fixture(), () => assert.fail('byte, not character limit'));
    assert.equal(unicodeInput.status, 503);
    for (const status of [200, 409]) {
      const overReply = await proxyAuthenticatedWorkspaceRequest(request(path, {method: 'POST', body: '{}', headers: modelHeaders}),
        fixture(), async () => new Response(jsonBytes(16385), {status, headers: {'Content-Type': 'application/json', 'Cache-Control': 'no-store'}}));
      assert.equal(overReply.status, 503);
    }
  }
});

test('negotiated model receipts reject malformed UTF-8 or JSON without exposing response content', async () => {
  for (const body of ['private not-json', new Uint8Array([0xff, 0xfe])]) {
    const result = await proxyAuthenticatedWorkspaceRequest(request(modelPaths[0], {method: 'POST', body: '{}', headers: modelHeaders}),
      fixture(), async () => new Response(body, {headers: {'Content-Type': 'application/json', 'Cache-Control': 'no-store'}}));
    assert.equal(result.status, 503);
    assert.equal((await result.text()).includes('private not-json'), false);
  }
});

test('workspace model metadata uses the exact read route with unchanged full workspace response bound', async () => {
  const path = `/workspaces/${id}`;
  const accepted = await proxyAuthenticatedWorkspaceRequest(request(path, {headers: modelHeaders}), fixture(), async (_url, options) => {
    assert.equal(options.headers['X-Cosmas-Model-Contract'], '1');
    return new Response(jsonBytes(12000000), {headers: {'Content-Type': 'application/json', 'Cache-Control': 'no-store'}});
  });
  assert.equal(accepted.status, 200);
  assert.equal((await accepted.arrayBuffer()).byteLength, 12000000);
  const rejected = await proxyAuthenticatedWorkspaceRequest(request(path, {headers: modelHeaders}), fixture(), async () =>
    new Response(jsonBytes(12000001), {headers: {'Content-Type': 'application/json', 'Cache-Control': 'no-store'}}));
  assert.equal(rejected.status, 503);
  for (const suffix of ['/appointments', '/prep-work']) {
    const result = await proxyAuthenticatedWorkspaceRequest(request(path + suffix, {headers: modelHeaders}), fixture(), () => assert.fail('foreign read'));
    assert.equal(result.status, 426);
  }
});

test('team resources and usage are read-only v2 routes with independent 16 KiB ceilings', async () => {
  for (const path of ['/provider-team/resources', '/provider-team/usage']) {
    assert.equal(permittedAuthenticatedApiPath('app://cosmas/api' + path, 'GET'), path);
    assert.equal(permittedAuthenticatedApiPath('app://cosmas/api' + path, 'POST'), null);
    for (const suffix of ['/', '?owner=' + id, '/' + id, '/execute']) {
      assert.equal(permittedAuthenticatedApiPath('app://cosmas/api' + path + suffix, 'GET'), null);
    }
    for (const version of [null, '1', '2, 2', '1, 2', '5']) {
      const result = await proxyAuthenticatedWorkspaceRequest(request(path, {headers: version === null ? {} : {'X-Cosmas-Team-Contract': version}}),
        fixture(), () => assert.fail('requires a supported policy contract'));
      assert.equal(result.status, 426);
    }
    const headers = {'X-Cosmas-Team-Contract': '2'};
    const exact = await proxyAuthenticatedWorkspaceRequest(request(path, {headers}), fixture(), async (_url, options) => {
      assert.equal(options.headers['X-Cosmas-Team-Contract'], '2');
      assert.equal(options.headers['X-Cosmas-Model-Contract'], undefined);
      return new Response(jsonBytes(16384), {headers: {'Content-Type': 'application/json', 'Cache-Control': 'no-store'}});
    });
    assert.equal(exact.status, 200);
    assert.equal((await exact.arrayBuffer()).byteLength, 16384);
    const over = await proxyAuthenticatedWorkspaceRequest(request(path, {headers}), fixture(), async () => response({text: 'x'.repeat(16384)}));
    assert.equal(over.status, 503, 'team metadata cannot inherit the 8 MiB setup ceiling');
  }
});

for (const stage of ['initial state', 'credential', 'response', 'final state']) {
  test('negotiated model 30-second deadline abandons stalled ' + stage + ' without a late dispatch or reply', async t => {
    t.mock.timers.enable({apis: ['setTimeout']});
    const auth = fixture(); let release; let calls = 0; let reads = 0; let removed = 0; let settled;
    const never = () => new Promise(resolve => { release = resolve; });
    const subscribe = auth.subscribe;
    auth.subscribe = listener => { const remove = subscribe(listener); return () => { removed++; remove(); }; };
    if (stage === 'initial state') auth.getState = never;
    if (stage === 'credential') auth.getToken = never;
    if (stage === 'final state') auth.getState = async () => ++reads === 1 ? ready : never();
    const pending = proxyAuthenticatedWorkspaceRequest(request(modelPaths[0], {method: 'POST', body: '{}', headers: modelHeaders}), auth, async () => {
      calls++; return stage === 'response' ? never() : response({private: 'must not escape'});
    }).then(value => { settled = value; return value; });
    await tick(); t.mock.timers.tick(29999); await tick(); assert.equal(settled, undefined);
    t.mock.timers.tick(1); const ended = await pending;
    assert.equal(ended.status, 401); assert.equal(removed, 1);
    assert.equal((await ended.text()).includes('must not escape'), false);
    const previousCalls = calls;
    release(stage === 'credential' ? 'local.binding.fixture' : stage === 'response' ? response({late: true}) : ready);
    await tick(); assert.equal(calls, previousCalls);
    if (stage === 'credential' || stage === 'initial state') assert.equal(calls, 0);
  });
}

test('model deadline is shared across state, credential, response and final authorization stages', async t => {
  t.mock.timers.enable({apis: ['setTimeout']});
  const auth = fixture(); let releaseState; let releaseToken; let releaseResponse; let reads = 0; let settled;
  auth.getState = () => ++reads === 1 ? new Promise(resolve => { releaseState = resolve; }) : new Promise(() => {});
  auth.getToken = () => new Promise(resolve => { releaseToken = resolve; });
  const pending = proxyAuthenticatedWorkspaceRequest(request(modelPaths[3], {method: 'POST', body: '{}', headers: modelHeaders}), auth,
    () => new Promise(resolve => { releaseResponse = resolve; })).then(value => { settled = value; return value; });
  await tick(); t.mock.timers.tick(10000); releaseState(ready);
  await tick(); t.mock.timers.tick(10000); releaseToken('local.binding.fixture');
  await tick(); t.mock.timers.tick(9999); releaseResponse(response({recorded: true}));
  await tick(); assert.equal(reads, 2); assert.equal(settled, undefined);
  t.mock.timers.tick(1); assert.equal((await pending).status, 401);
});

for (const stage of ['request', 'response']) {
  test('model deadline bounds stalled ' + stage + ' streams even when cancellation never finishes', async t => {
    t.mock.timers.enable({apis: ['setTimeout']});
    let canceled = 0; let calls = 0;
    const body = new ReadableStream({pull() { return new Promise(() => {}); }, cancel() { canceled++; return new Promise(() => {}); }});
    const pending = proxyAuthenticatedWorkspaceRequest(request(modelPaths[1], {method: 'POST',
      body: stage === 'request' ? body : '{}', ...(stage === 'request' ? {duplex: 'half'} : {}), headers: modelHeaders}),
    fixture(), async () => { calls++; return new Response(body, {headers: {'Content-Type': 'application/json', 'Cache-Control': 'no-store'}}); });
    await tick(); t.mock.timers.tick(30000);
    assert.equal((await pending).status, 401); assert.equal(canceled, 1); assert.equal(calls, stage === 'request' ? 0 : 1);
  });
}

for (const stage of ['request', 'response']) {
  test('model deadline still applies when ' + stage + ' parsing reaches expiry', async t => {
    t.mock.timers.enable({apis: ['setTimeout']});
    const parse = JSON.parse; const marker = 'deadline-parse-fixture';
    t.mock.method(JSON, 'parse', function(value, ...rest) {
      if (typeof value === 'string' && value.includes(marker)) t.mock.timers.tick(30000);
      return parse(value, ...rest);
    });
    const auth = fixture(); let calls = 0;
    const result = await proxyAuthenticatedWorkspaceRequest(request(modelPaths[0], {method: 'POST',
      body: stage === 'request' ? JSON.stringify({marker}) : '{}', headers: modelHeaders}), auth, async () => {
      calls++; return response({marker});
    });
    assert.equal(result.status, 401);
    assert.equal(calls, stage === 'request' ? 0 : 1);
    if (stage === 'request') assert.equal(auth.tokenCalls(), 0);
  });
}

test('missing-header original commands keep the legacy deadline while negotiated workspace reads use 30 seconds', async t => {
  t.mock.timers.enable({apis: ['setTimeout']});
  let legacyDone; let modernDone;
  const legacyAuth = fixture(); legacyAuth.getToken = () => new Promise(() => {});
  const modernAuth = fixture(); modernAuth.getToken = () => new Promise(() => {});
  const legacy = proxyAuthenticatedWorkspaceRequest(request(modelPaths[0], {method: 'POST', body: '{}'}), legacyAuth,
    () => assert.fail('no legacy dispatch')).then(result => { legacyDone = result; });
  const modern = proxyAuthenticatedWorkspaceRequest(request(`/workspaces/${id}`, {headers: modelHeaders}), modernAuth,
    () => assert.fail('no modern dispatch')).then(result => { modernDone = result; });
  await tick(); t.mock.timers.tick(30000); await tick();
  assert.equal(modernDone?.status, 401); assert.equal(legacyDone, undefined);
  t.mock.timers.tick(15000); await Promise.all([legacy, modern]); assert.equal(legacyDone.status, 401);
});

test('forwards current Inbox and Membership team generations without changing account and activity protocols',async()=>{
  for(const version of ['3','4']) {
  for(const path of ['/provider-team','/provider-team/setup','/provider-team/resources','/provider-team/usage']) {
    const result=await proxyAuthenticatedWorkspaceRequest(request(path,{headers:{'X-Cosmas-Team-Contract':version}}),fixture(),async(_url,options)=>{
      assert.equal(options.headers['X-Cosmas-Team-Contract'],version);return response({revision:1});
    });
    assert.equal(result.status,200);
  }
  }
});


test('connection catalog is a bounded authenticated read with no setup mutation', async () => {
  const path='/connections/catalog', headers={'X-Cosmas-Connection-Contract':'1'};
  assert.equal(permittedAuthenticatedApiPath('app://cosmas/api'+path,'GET'),path);
  for(const [suffix,method] of [['','POST'],['?account=other','GET'],['/google','GET']])
    assert.equal(permittedAuthenticatedApiPath('app://cosmas/api'+path+suffix,method),null);
  const denied=await proxyAuthenticatedWorkspaceRequest(request(path),fixture(),()=>assert.fail('contract required'));
  assert.equal(denied.status,426);
  const result=await proxyAuthenticatedWorkspaceRequest(request(path,{headers}),fixture(),async (_url,options)=>{
    assert.equal(options.headers['X-Cosmas-Connection-Contract'],'1');
    assert.equal(options.headers.Authorization,'Bearer local.binding.fixture');
    return response({version:1,services:[]});
  });
  assert.equal(result.status,200);
  const oversized=await proxyAuthenticatedWorkspaceRequest(request(path,{headers}),fixture(),async()=>response({body:'x'.repeat(4097)}));
  assert.equal(oversized.status,503);
});

test('selected Session Prep gets one bounded 90-second window while exact resolve retains 30 seconds', async t => {
  t.mock.timers.enable({apis:['setTimeout','Date']});
  const body=JSON.stringify({session_prep_analysis:{version:1,consented:true,brief_id:'a'.repeat(64),brief_version:1,snapshot_sha256:'b'.repeat(64)}});
  let submitted, resolved;
  const never=()=>new Promise(()=>{});
  const submit=proxyAuthenticatedWorkspaceRequest(request(`/workspaces/${id}/conversation`,{method:'POST',body,headers:modelHeaders}),fixture(),never).then(r=>{submitted=r;});
  const resolve=proxyAuthenticatedWorkspaceRequest(request(`/workspaces/${id}/conversation/resolve`,{method:'POST',body,headers:modelHeaders}),fixture(),never).then(r=>{resolved=r;});
  await tick();t.mock.timers.tick(30000);await tick();assert.equal(submitted,undefined);assert.equal(resolved?.status,401);
  t.mock.timers.tick(59999);await tick();assert.equal(submitted,undefined);
  t.mock.timers.tick(1);await Promise.all([submit,resolve]);assert.equal(submitted.status,401);
});
