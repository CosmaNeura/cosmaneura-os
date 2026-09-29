import assert from 'node:assert/strict';
import test from 'node:test';
import {createDesktopAuthSession} from './auth-session.mjs';
import {installSignInPresentation} from './sign-in-presentation.mjs';

const ready = {phase: 'ready', revision: '00000000-0000-4000-8000-000000000001',
  identity: {userId: 'user_test', sessionId: 'sess_test', organizationId: 'org_test'}};
const out = {phase: 'signedOut', revision: '00000000-0000-4000-8000-000000000002', identity: null};
const tick = () => new Promise(resolve => setImmediate(resolve));
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
}
function windowFixture() {
  const calls = [];
  return {calls, window: {isDestroyed: () => false, isMinimized: () => false,
    webContents: {isDestroyed: () => false}, restore: () => calls.push('restore'),
    show: () => calls.push('show'), focus: () => calls.push('focus')}};
}
function eventFixture() {
  let listener;
  const {calls, window} = windowFixture();
  const dispose = installSignInPresentation({subscribe: fn => { listener = fn; return () => {}; }}, window);
  return {calls, window, dispose, emit: phase => listener({phase})};
}

test('returns only after native sign-in and durable access persistence complete', async () => {
  const nativeCompletion = deferred(), persistence = deferred(), {calls, window} = windowFixture();
  let access = 'needs_login', native = out, listener;
  const auth = await createDesktopAuthSession({enabled: true,
    accessStore: {read: async () => access, write: async next => {
      if (next === 'allowed') await persistence.promise;
      access = next;
    }},
    createHelper: () => ({getState: async () => native, close: () => {},
      subscribe: fn => { listener = fn; return () => {}; },
      signIn: () => nativeCompletion.promise})});
  const dispose = installSignInPresentation(auth, window);
  try {
    const signing = auth.signIn(); await tick();
    native = ready; listener(ready); nativeCompletion.resolve(ready); await tick();
    assert.equal(auth.snapshot().phase, 'signingIn');
    assert.equal(access, 'logout_pending');
    assert.deepEqual(calls, []);
    persistence.resolve();
    assert.equal((await signing).phase, 'ready');
    assert.equal(access, 'allowed');
    assert.deepEqual(calls, ['show', 'focus']);
    await auth.getState(); assert.deepEqual(calls, ['show', 'focus']);
  } finally {dispose(); auth.close();}
});

test('returns on cancelled or failed sign-in without admitting the native account', async () => {
  const nativeCompletion = deferred(), {calls, window} = windowFixture();
  let access = 'needs_login';
  const auth = await createDesktopAuthSession({enabled: true,
    accessStore: {read: async () => access, write: async next => { access = next; }},
    createHelper: () => ({getState: async () => ready, close: () => {},
      subscribe: () => () => {}, signIn: () => nativeCompletion.promise})});
  const dispose = installSignInPresentation(auth, window);
  try {
    const failed = assert.rejects(auth.signIn(), /Native session unavailable/);
    await tick(); nativeCompletion.reject(new Error('cancelled')); await failed;
    assert.equal(access, 'logout_pending');
    assert.equal(auth.snapshot().phase, 'signOutPending');
    assert.equal(auth.snapshot().identity, null);
    assert.deepEqual(calls, ['show', 'focus']);
  } finally {dispose(); auth.close();}
});

test('restored sessions, background polling and sign-out do not steal focus', () => {
  const f = eventFixture();
  for (const phase of ['loading', 'ready', 'ready', 'signOutPending', 'signedOut', 'unavailable']) f.emit(phase);
  assert.deepEqual(f.calls, []); f.dispose();
});

test('restores a minimized window once per completed attempt', () => {
  const f = eventFixture(); f.window.isMinimized = () => true;
  for (const phase of ['signingIn', 'signingIn', 'ready', 'ready']) f.emit(phase);
  assert.deepEqual(f.calls, ['restore', 'show', 'focus']);
  f.emit('signingIn'); f.emit('unavailable');
  assert.deepEqual(f.calls, ['restore', 'show', 'focus', 'restore', 'show', 'focus']); f.dispose();
});

test('destroyed windows or renderers and disposed listeners cannot be reopened', () => {
  for (const target of ['window', 'renderer', 'disposed']) {
    const f = eventFixture(); f.emit('signingIn');
    if (target === 'window') f.window.isDestroyed = () => true;
    else if (target === 'renderer') f.window.webContents.isDestroyed = () => true;
    else f.dispose();
    f.emit('ready'); assert.deepEqual(f.calls, []); f.dispose();
  }
});

test('a presentation failure cannot escape into the auth completion', () => {
  const f = eventFixture(); f.window.show = () => { throw new Error('window closed'); };
  f.emit('signingIn'); assert.doesNotThrow(() => f.emit('ready'));
  assert.deepEqual(f.calls, []); f.dispose();
});
