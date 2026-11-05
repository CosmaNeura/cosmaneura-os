import assert from 'node:assert/strict';
import test from 'node:test';
import {randomUUID} from 'node:crypto';
import {installPracticeIpc, PRACTICE_CHANNELS} from './practice-ipc.mjs';
import {createDesktopPracticeSession} from './practice-session.mjs';

async function fixture() {
  const handlers = new Map(), sends = [];
  const renderer = {
    mainFrame: {url: 'app://cosmas/index.html'}, isDestroyed: () => false,
    send: (...args) => sends.push(args),
  };
  const ipc = {
    handle: (name, fn) => handlers.set(name, fn),
    removeHandler: name => handlers.delete(name),
  };
  const practice = await createDesktopPracticeSession({enabled: true});
  const dispose = installPracticeIpc(ipc, renderer, practice);
  return {
    handlers, renderer, practice, dispose, sends,
    event: {sender: renderer, senderFrame: renderer.mainFrame},
    payload: (extra = {}) => ({schemaVersion: 1, requestId: randomUUID(), ...extra}),
  };
}

test('exposes practice methods without a credential channel and pushes account events', async () => {
  const f = await fixture();
  assert.equal([...f.handlers.keys()].some(name => name.includes('token') && !name.includes('account-token')), false);
  assert.ok(f.handlers.has(PRACTICE_CHANNELS.capabilities));
  assert.ok(f.handlers.has(PRACTICE_CHANNELS.activateRegisteredPractice));
  const caps = await f.handlers.get(PRACTICE_CHANNELS.capabilities)(f.event, f.payload());
  assert.equal(caps.available, true);
  const signedIn = await f.handlers.get(PRACTICE_CHANNELS.beginAccountSignIn)(f.event, f.payload());
  assert.equal(signedIn.phase, 'accountReady');
  assert.equal(f.sends.length, 2); // signingIn + accountReady
  assert.equal(f.sends[1][0], PRACTICE_CHANNELS.changed);
  const snapshot = await f.handlers.get(PRACTICE_CHANNELS.activateRegisteredPractice)(
    f.event, f.payload({expectedRevision: signedIn.revision}));
  assert.equal(snapshot.profile.client, 'desktop');
  f.dispose();
  assert.equal(f.handlers.size, 0);
  f.practice.close();
});

test('denies another renderer and forged payloads', async () => {
  const f = await fixture();
  const handler = f.handlers.get(PRACTICE_CHANNELS.capabilities);
  await assert.rejects(handler({...f.event, sender: {}}, f.payload()), /unavailable/);
  await assert.rejects(handler(f.event, {...f.payload(), token: 'forged'}), /unavailable/);
  f.renderer.mainFrame.url = 'https://outside.invalid';
  await assert.rejects(handler(f.event, f.payload()), /unavailable/);
  f.dispose();
  f.practice.close();
});
