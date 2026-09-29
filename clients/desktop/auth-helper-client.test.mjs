import assert from 'node:assert/strict';
import test from 'node:test';
import {EventEmitter} from 'node:events';
import {PassThrough, Writable} from 'node:stream';
import {createAuthHelperClient} from './auth-helper-client.mjs';

const revision = '00000000-0000-4000-8000-000000000001';
const ready = {phase: 'ready', revision, identity: {userId: 'user_one', sessionId: 'sess_one', organizationId: 'org_one'}};
const tick = () => new Promise(resolve => setImmediate(resolve));

test('source replies use the private pipe without changing public auth state', async () => {
  const f=fixture();f.send({event:'ready',version:1});f.send({event:'authStateChanged',state:ready});
  try {
    const payload={preparationId:revision,workspaceId:revision,sessionId:revision,leaseId:revision,
      leaseReceiptId:revision,leaseGeneration:1,captureAuthorizedUntil:new Date().toISOString(),revision};
    const prepared=f.client.sourceRequest('sourcePrepare',payload);await tick();
    assert.deepEqual(f.requests[0].payload,payload);
    const result={grant:{sourceLeaseId:revision},processFence:{epoch:revision}};
    f.send({id:f.requests[0].id,ok:true,result});assert.deepEqual(await prepared,result);
    const stopped=f.client.sourceRequest('sourceStopped',{sourceLeaseId:revision});await tick();
    f.send({id:f.requests[1].id,ok:true,result:null});assert.equal(await stopped,null);
    assert.deepEqual(f.client.snapshot(),ready);
    await assert.rejects(f.client.sourceRequest('sourcePrepare',{padding:'x'.repeat(1024)}),/unavailable/);
    assert.equal(f.requests.length,2);
  } finally {f.client.close();}
});
function fixture(options) {
  const child = new EventEmitter();
  const requests = [];
  child.stdin = new Writable({write(bytes, _encoding, callback) { requests.push(JSON.parse(bytes.toString())); callback(); }});
  child.stdout = new PassThrough(); child.stderr = new PassThrough(); child.exitCode = null; child.signalCode = null;
  child.kills = 0; child.kill = () => { child.kills++; child.signalCode = 'SIGTERM'; child.emit('exit', null, 'SIGTERM'); };
  const client = createAuthHelperClient(child, options);
  const send = value => child.stdout.write(Buffer.from(JSON.stringify(value) + '\n'));
  return {child, client, requests, send};
}

test('waits for exact handshake, correlates requests, and returns tokens only through the main client', async () => {
  const f = fixture();
  try {
    const pending = f.client.getState(); await tick(); assert.equal(f.requests.length, 0);
    f.send({event: 'ready', version: 1}); await tick();
    f.send({id: f.requests[0].id, ok: true, result: ready}); assert.deepEqual(await pending, ready);
    const token = f.client.getToken(revision); await tick();
    assert.equal(f.requests[1].method, 'getToken'); assert.equal(f.requests[1].revision, revision);
    f.send({id: f.requests[1].id, ok: true, result: {token: 'local.binding.fixture', revision}});
    assert.equal(await token, 'local.binding.fixture'); assert.deepEqual(f.client.snapshot(), ready);
    assert.equal(JSON.stringify(f.client.snapshot()).includes('fixture'), false);
  } finally { f.client.close(); }
});

test('handles fragmented and coalesced frames without losing response ordering', async () => {
  const f = fixture();
  try {
    const handshake = Buffer.from('{"event":"ready","version":1}\n');
    for (const byte of handshake) f.child.stdout.write(Buffer.from([byte]));
    const first = f.client.getState(), second = f.client.getState(); await tick();
    f.child.stdout.write(Buffer.from(f.requests.slice().reverse().map(request => JSON.stringify({id: request.id, ok: true, result: ready})).join('\n') + '\n'));
    assert.deepEqual(await Promise.all([first, second]), [ready, ready]);
  } finally { f.client.close(); }
});

test('publishes identity changes and rejects contradictory data under one revision', async () => {
  const f = fixture(); const states = [];
  const remove = f.client.subscribe(state => states.push(state));
  f.send({event: 'ready', version: 1}); f.send({event: 'authStateChanged', state: ready});
  const altered = {...ready, identity: {...ready.identity, sessionId: 'sess_other'}};
  f.send({event: 'authStateChanged', state: altered});
  assert.equal(f.child.kills, 1); assert.equal(states.at(-1).phase, 'unavailable');
  assert.equal(states.at(-1).identity, null); remove();
});

test('sanitizes recognized errors without logging or returning native details', async () => {
  const f = fixture();
  try {
    f.send({event: 'ready', version: 1});
    const call = f.client.signIn(); const rejected = assert.rejects(call, /^Error: Native session unavailable$/); await tick();
    f.child.stderr.write('private SDK diagnostics are discarded');
    f.send({id: f.requests[0].id, ok: false, error: 'native_auth_unavailable'}); await rejected;
    assert.equal(f.child.kills, 0);
  } finally { f.client.close(); }
});

for (const reply of [
  {event: 'ready', version: 2}, {event: 'ready', version: 1, token: 'secret'},
  {id: revision, ok: true, result: ready}, {event: 'authStateChanged', state: {phase: 'ready', revision, identity: null}},
]) test('fails closed for unknown, premature, or malformed native data: ' + JSON.stringify(reply), async () => {
  const f = fixture(); const call = f.client.getState(); const rejected = assert.rejects(call, /Native session unavailable/);
  f.send(reply); await rejected; assert.equal(f.child.kills, 1); assert.equal(f.client.snapshot().phase, 'unavailable');
});

test('oversize and invalid UTF-8 frames terminate the helper and all pending work', async () => {
  for (const bytes of [Buffer.alloc(16384, 65), Buffer.from([0xff, 10])]) {
    const f = fixture(); f.send({event: 'ready', version: 1});
    const call = f.client.getState(); const rejected = assert.rejects(call, /Native session unavailable/); await tick();
    f.child.stdout.write(bytes); await rejected; assert.equal(f.child.kills, 1);
  }
});

test('a duplicate response cannot be mistaken for later work', async () => {
  const f = fixture(); f.send({event: 'ready', version: 1});
  const call = f.client.getState(); await tick();
  const reply = {id: f.requests[0].id, ok: true, result: ready}; f.send(reply); await call;
  f.send(reply); assert.equal(f.child.kills, 1);
});

test('mismatched token revisions never return credentials', async () => {
  const f = fixture(); f.send({event: 'ready', version: 1});
  const call = f.client.getToken(revision); const rejected = assert.rejects(call, /Native session unavailable/); await tick();
  f.send({id: f.requests[0].id, ok: true, result: {token: 'local.binding.fixture', revision: '00000000-0000-4000-8000-000000000002'}});
  await rejected; assert.equal(f.child.kills, 1);
});

test('startup and request timeouts terminate only the owned helper', async () => {
  const first = fixture({startupTimeoutMs: 10}); await assert.rejects(first.client.getState(), /Native session unavailable/);
  assert.equal(first.child.kills, 1);
  const second = fixture({requestTimeoutMs: 10}); second.send({event: 'ready', version: 1});
  await assert.rejects(second.client.getState(), /Native session unavailable/); assert.equal(second.child.kills, 1);
});

test('explicit recovery can finish Keychain startup after the background deadline', async t => {
  t.mock.timers.enable({apis: ['setTimeout']});
  const f = fixture({interactiveStartup: true});
  const pending = f.client.signIn();
  try {
    t.mock.timers.tick(120000); await tick();
    assert.equal(f.child.kills, 0); assert.equal(f.requests.length, 0);
    assert.equal(f.client.snapshot().phase, 'loading');
    f.send({event: 'ready', version: 1}); await tick();
    assert.equal(f.requests[0].method, 'signIn');
    f.send({id: f.requests[0].id, ok: true, result: ready});
    assert.deepEqual(await pending, ready);
    t.mock.timers.tick(185000); assert.equal(f.child.kills, 0);
  } finally { f.client.close(); }
});

test('both startup modes remain bounded and only an explicit boolean extends the deadline', async t => {
  t.mock.timers.enable({apis: ['setTimeout']});
  for (const interactiveStartup of [false, 'true', true]) {
    const f = fixture({interactiveStartup});
    const pending = assert.rejects(f.client.getState(), /Native session unavailable/);
    const deadline = interactiveStartup === true ? 185000 : 10000;
    t.mock.timers.tick(deadline - 1); assert.equal(f.child.kills, 0);
    t.mock.timers.tick(1); await pending;
    assert.equal(f.child.kills, 1); assert.equal(f.requests.length, 0);
    assert.equal(f.client.snapshot().phase, 'unavailable');
  }
});

test('closing during interactive startup immediately rejects work without waiting for its deadline', async t => {
  t.mock.timers.enable({apis: ['setTimeout']});
  const f = fixture({interactiveStartup: true});
  const pending = assert.rejects(f.client.signIn(), /Native session unavailable/);
  t.mock.timers.tick(20000); f.client.close(); await pending;
  assert.equal(f.child.kills, 1); assert.equal(f.requests.length, 0);
  t.mock.timers.tick(185000); assert.equal(f.child.kills, 1);
});

for (const [method, nativeDeadline] of [['signIn', 180000], ['signOut', 30000]]) {
  test('allows the native ' + method + ' deadline to report a closed state before terminating its pipe', async t => {
    t.mock.timers.enable({apis: ['setTimeout']});
    const f = fixture(); f.send({event: 'ready', version: 1});
    const pending = f.client[method]().then(() => false, () => true);
    try {
      await tick();
      t.mock.timers.tick(nativeDeadline);
      assert.equal(f.child.kills, 0);
      const closed = {phase: 'signOutPending', revision, identity: null};
      f.send({event: 'authStateChanged', state: closed});
      f.send({id: f.requests[0].id, ok: false, error: 'native_auth_unavailable'});
      assert.equal(await pending, true);
      t.mock.timers.tick(5000);
      assert.equal(f.child.kills, 0);
      const state = f.client.getState(); await tick();
      f.send({id: f.requests[1].id, ok: true, result: closed});
      assert.deepEqual(await state, closed);
    } finally { f.client.close(); await pending; }
  });
}

test('a helper crash rejects in-flight work and closes the current state', async () => {
  const f = fixture(); f.send({event: 'ready', version: 1}); f.send({event: 'authStateChanged', state: ready});
  const call = f.client.getToken(revision); const rejected = assert.rejects(call, /Native session unavailable/); await tick();
  f.child.exitCode = 1; f.child.emit('exit', 1, null); await rejected;
  assert.equal(f.client.snapshot().phase, 'unavailable'); assert.equal(f.child.kills, 0);
});
