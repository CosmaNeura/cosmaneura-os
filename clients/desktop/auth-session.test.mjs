import assert from 'node:assert/strict';
import test from 'node:test';
import {createDesktopAuthSession} from './auth-session.mjs';

const nativeReady = {phase: 'ready', revision: '00000000-0000-4000-8000-000000000001',
  identity: {userId: 'user_one', sessionId: 'sess_one', organizationId: 'org_one'}};
const nativeOut = {phase: 'signedOut', revision: '00000000-0000-4000-8000-000000000002', identity: null};
const tick = () => new Promise(resolve => setImmediate(resolve));
function deferred() { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return {promise, resolve, reject}; }
function fixture(initialAccess = 'needs_login') {
  let access = initialAccess, current = nativeReady;
  const listeners = new Set(), writes = [], calls = [];
  const store = {read: async () => access, write: async next => { writes.push(next); access = next; }};
  const helper = {
    getState: async () => current,
    signIn: async () => { calls.push('signIn'); assert.equal(access, 'logout_pending'); current = nativeReady; return current; },
    signOut: async () => { calls.push('signOut'); assert.equal(access, 'logout_pending'); current = nativeOut; return current; },
    getToken: async revision => { calls.push(['getToken', revision]); return 'local.binding.fixture'; },
    subscribe: listener => { listeners.add(listener); return () => listeners.delete(listener); }, close: () => {},
  };
  return {helper, store, writes, calls, access: () => access,
    emit: value => { current = value; for (const listener of listeners) listener(value); },
    create: () => createDesktopAuthSession({enabled: true, createHelper: () => helper, accessStore: store})};
}

for (const method of ['sourcePrepare','sourceExtend']) test(`${method} binds the public revision to native auth and rejects a late reply`, async () => {
  const f=fixture('allowed'),session=await f.create(),revision=session.snapshot().revision,calls=[];
  let resolve;
  f.helper.sourceRequest=(method,payload)=>{calls.push({method,payload});return new Promise(done=>{resolve=done;});};
  try {
    const pending=session.sourceRequest(method,{preparationId:revision},revision);
    const rejected=assert.rejects(pending,/unavailable/);await tick();
    assert.equal(calls[0].payload.revision,nativeReady.revision);
    f.emit({...nativeReady,revision:'00000000-0000-4000-8000-000000000099'});
    resolve({grant:'invented late grant'});await rejected;
    await assert.rejects(session.sourceRequest('sourceAuthorize',{sourceLeaseId:revision},revision),/unavailable/);
    f.helper.sourceRequest=async(method,payload)=>{calls.push({method,payload});return null;};
    assert.equal(await session.sourceRequest('sourceStopped',{sourceLeaseId:revision}),null);
    assert.equal(calls.at(-1).payload.revision,undefined);
  } finally {session.close();}
});

test('disabled desktop auth constructs neither helper nor storage', async () => {
  const session = await createDesktopAuthSession({createHelper: () => assert.fail('helper'),
    accessStore: {read: () => assert.fail('storage')}});
  assert.equal((await session.getState()).phase, 'disabled');
  await assert.rejects(session.signIn(), /Native session unavailable/); session.close();
});

test('fresh local state does not silently adopt a restored native account', async () => {
  const f = fixture(); const session = await f.create();
  assert.equal(session.snapshot().phase, 'signedOut'); assert.equal(session.snapshot().identity, null);
  await assert.rejects(session.getToken(nativeReady.revision), /Native session unavailable/);
  const ready = await session.signIn(); assert.equal(ready.phase, 'ready');
  assert.notEqual(ready.revision, nativeReady.revision); assert.equal(f.access(), 'allowed');
  assert.deepEqual(f.writes, ['logout_pending', 'allowed']);
  assert.equal(await session.getToken(ready.revision), 'local.binding.fixture');
  assert.deepEqual(f.calls.at(-1), ['getToken', nativeReady.revision]); session.close();
});

test('unchanged native polling preserves the public revision and private state', async () => {
  const f = fixture('allowed'); const session = await f.create(); const before = session.snapshot();
  assert.deepEqual(await session.getState(), before); assert.deepEqual(await session.getState(), before);
  const fresh = {...nativeReady, revision: '00000000-0000-4000-8000-000000000003',
    identity: {...nativeReady.identity, sessionId: 'sess_other'}};
  f.emit(fresh); assert.notEqual(session.snapshot().revision, before.revision);
  await assert.rejects(session.getToken(before.revision), /Native session unavailable/); session.close();
});

test('sign-out persists intent before the helper request and stays blocked after failure/restart', async () => {
  const f = fixture('allowed'); let session = await f.create();
  f.helper.signOut = async () => { assert.equal(f.access(), 'logout_pending'); throw new Error('private SDK detail'); };
  await assert.rejects(session.signOut(), /^Error: Native session unavailable$/);
  assert.equal(session.snapshot().phase, 'signOutPending'); session.close();
  session = await f.create(); assert.equal(session.snapshot().phase, 'signOutPending');
  f.helper.signOut = async () => { f.emit(nativeOut); return nativeOut; };
  assert.equal((await session.signOut()).phase, 'signedOut'); assert.equal(f.access(), 'needs_login'); session.close();
});

test('logout discards an in-flight credential and closes access before a remote response', async () => {
  const f = fixture('allowed'); const session = await f.create(); const revision = session.snapshot().revision;
  const token = deferred(); f.helper.getToken = () => token.promise;
  const result = session.getToken(revision); const denied = assert.rejects(result, /Native session unavailable/); await tick();
  const logout = deferred(); f.helper.signOut = () => logout.promise;
  const finished = session.signOut(); await tick();
  assert.equal(session.snapshot().phase, 'signOutPending'); assert.equal(f.access(), 'logout_pending');
  token.resolve('local.binding.fixture'); await denied;
  f.emit(nativeOut); logout.resolve(nativeOut); await finished; session.close();
});

test('late hosted sign-in cannot undo a newer sign-out or persist allowed access', async () => {
  const f = fixture(); const session = await f.create(); const login = deferred();
  f.helper.signIn = () => login.promise;
  const result = session.signIn(); const denied = assert.rejects(result, /Native session unavailable/); await tick();
  await assert.rejects(session.signIn(), /Native session unavailable/);
  await session.signOut(); assert.equal(f.access(), 'needs_login');
  f.emit(nativeReady); login.resolve(nativeReady); await denied;
  assert.equal(session.snapshot().phase, 'signedOut'); assert.equal(f.access(), 'needs_login'); session.close();
});

test('storage failures close access before helper creation or any sign-in request', async () => {
  let created = false;
  const noRead = await createDesktopAuthSession({enabled: true, createHelper: () => { created = true; },
    accessStore: {read: async () => { throw new Error('private filesystem path'); }}});
  assert.equal(created, false); assert.equal(noRead.snapshot().phase, 'unavailable'); noRead.close();
  const f = fixture('allowed'); const session = await f.create();
  f.store.write = async () => { throw new Error('private path'); };
  await assert.rejects(session.signIn(), /^Error: Native session unavailable$/);
  assert.equal(session.snapshot().phase, 'unavailable'); assert.equal(f.calls.length, 0);
  await assert.rejects(session.getToken(session.snapshot().revision), /Native session unavailable/); session.close();
});

test('helper failure and session disposal deny old tokens', async () => {
  const f = fixture('allowed'); const session = await f.create(); const revision = session.snapshot().revision;
  f.emit({...nativeOut, phase: 'unavailable'}); assert.equal(session.snapshot().phase, 'unavailable');
  await assert.rejects(session.getToken(revision), /Native session unavailable/);
  session.close(); await assert.rejects(session.getToken(revision), /Native session unavailable/);
});
