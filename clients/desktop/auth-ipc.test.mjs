import assert from 'node:assert/strict';
import test from 'node:test';
import {randomUUID} from 'node:crypto';
import {installAuthIpc, AUTH_CHANNELS} from './auth-ipc.mjs';

const state = {phase: 'signedOut', revision: '00000000-0000-4000-8000-000000000001', identity: null};
function fixture() {
  const handlers = new Map(), sends = [], calls = [];
  const renderer = {mainFrame: {url: 'app://cosmas/index.html'}, isDestroyed: () => false,
    send: (...args) => sends.push(args)};
  const ipc = {handle: (name, fn) => handlers.set(name, fn), removeHandler: name => handlers.delete(name)};
  let listener;
  const auth = {getState: async () => { calls.push('state'); return state; }, signIn: async () => state,
    signOut: async () => state, subscribe: fn => { listener = fn; return () => { listener = null; }; }};
  const dispose = installAuthIpc(ipc, renderer, auth);
  return {handlers, renderer, auth, dispose, sends, calls, emit: value => listener?.(value),
    event: {sender: renderer, senderFrame: renderer.mainFrame}, payload: () => ({schemaVersion: 1, requestId: randomUUID()})};
}
test('exposes three bounded operations and safe state events, with no credential channel', async () => {
  const f = fixture();
  assert.equal(f.handlers.size, 3); assert.equal([...f.handlers.keys()].some(name => name.includes('token')), false);
  assert.deepEqual(await f.handlers.get(AUTH_CHANNELS.getState)(f.event, f.payload()), state);
  f.emit(state); assert.deepEqual(f.sends, [[AUTH_CHANNELS.changed, state]]);
  f.dispose(); assert.equal(f.handlers.size, 0);
});

test('denies another renderer, subframe, document, extra payload and duplicate request', async () => {
  const f = fixture(); const handler = f.handlers.get(AUTH_CHANNELS.getState);
  for (const event of [{...f.event, sender: {}}, {...f.event, senderFrame: null},
    {...f.event, senderFrame: {url: 'app://cosmas/index.html'}}]) {
    await assert.rejects(handler(event, f.payload()), /Secure session operation unavailable/);
  }
  await assert.rejects(handler(f.event, {...f.payload(), token: 'forged'}), /Secure session operation unavailable/);
  const payload = f.payload(); await handler(f.event, payload);
  await assert.rejects(handler(f.event, payload), /Secure session operation unavailable/);
  f.renderer.mainFrame.url = 'app://cosmas/index.html?foreign=true';
  await assert.rejects(handler(f.event, f.payload()), /Secure session operation unavailable/);
  assert.equal(f.calls.length, 1); f.dispose();
});

test('rechecks the frame after an awaited operation and never publishes credential-bearing state', async () => {
  const f = fixture(); let release;
  f.auth.getState = () => new Promise(resolve => { release = resolve; });
  const result = f.handlers.get(AUTH_CHANNELS.getState)(f.event, f.payload());
  const denied = assert.rejects(result, /Secure session operation unavailable/);
  f.renderer.mainFrame.url = 'https://outside.invalid'; release(state); await denied;
  f.emit({...state, token: 'forged'}); assert.equal(f.sends.length, 0); f.dispose();
});

test('native state polling and events survive workspace fragment navigation in the same owned frame',async()=>{
  const f=fixture(),handler=f.handlers.get(AUTH_CHANNELS.getState);
  for(const fragment of ['', '#cosmas/home','#cosmas/settings',
    '#cosmas/notebook/00000000-0000-4000-8000-000000000084?helper=chief&material=Sources']){
    f.renderer.mainFrame.url='app://cosmas/index.html'+fragment;
    assert.deepEqual(await handler(f.event,f.payload()),state);
    f.emit(state);
  }
  assert.equal(f.calls.length,4);assert.equal(f.sends.length,4);
  await assert.rejects(handler({...f.event,senderFrame:{url:f.renderer.mainFrame.url}},f.payload()));
  assert.equal(f.calls.length,4);f.dispose();
});

test('a same-document fragment change during state verification preserves the original frame guard',async()=>{
  const f=fixture();let release;f.auth.getState=()=>new Promise(resolve=>{release=resolve;});
  const result=f.handlers.get(AUTH_CHANNELS.getState)(f.event,f.payload());
  f.renderer.mainFrame.url='app://cosmas/index.html#cosmas/home';release(state);
  assert.deepEqual(await result,state);
  for(const url of ['app://cosmas/index.html?foreign=true#cosmas/home','app://user@cosmas/index.html#cosmas/home',
    'app://cosmas:443/index.html#cosmas/home','app://cosmas/a/../index.html#cosmas/home']){
    f.renderer.mainFrame.url=url;
    await assert.rejects(f.handlers.get(AUTH_CHANNELS.getState)(f.event,f.payload()));
    f.emit(state);
  }
  assert.equal(f.sends.length,0);f.dispose();
});
