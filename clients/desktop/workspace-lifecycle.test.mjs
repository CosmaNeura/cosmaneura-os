import test from 'node:test';
import assert from 'node:assert/strict';
import {EventEmitter} from 'node:events';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {installDesktopWorkspaceLifecycle, WORKSPACE_LIFECYCLE_CHANNEL} from './workspace-lifecycle.mjs';

const ENTRY = 'app://cosmas/index.html';
function fixture() {
  let time = 0, nextTimer = 0;
  const timers = new Map(), failures = [], ipc = new EventEmitter();
  const renderer = Object.assign(new EventEmitter(), {mainFrame: {url: ENTRY}, destroyed: false,
    isDestroyed() { return this.destroyed; }, getURL() { return this.mainFrame.url; }});
  const window = Object.assign(new EventEmitter(), {webContents: renderer, visible: true, focused: true,
    minimized: false, destroyed: false, isDestroyed() { return this.destroyed; },
    isVisible() { return this.visible; }, isMinimized() { return this.minimized; }, isFocused() { return this.focused; }});
  const dispose = installDesktopWorkspaceLifecycle({ipcMain: ipc, window, fail: kind => failures.push(kind),
    timeoutMs: 30_000, now: () => time,
    setTimer: (callback, wait) => {const id = ++nextTimer; timers.set(id, {callback, at: time + wait}); return id;},
    clearTimer: id => timers.delete(id)});
  function advance(ms) {
    time += ms;
    for (const [id, timer] of [...timers]) if (timer.at <= time) {timers.delete(id); timer.callback();}
  }
  const event = () => ({sender: renderer, senderFrame: renderer.mainFrame});
  return {ipc, renderer, window, failures, timers, dispose, advance, event,
    navigate: (options = {}) => renderer.emit('did-start-navigation', {url: ENTRY, isMainFrame: true, isSameDocument: false, ...options}),
    notice: (kind, sender = event(), ...extra) => ipc.emit(WORKSPACE_LIFECYCLE_CHANNEL, sender, kind, ...extra)};
}

test('document load does not satisfy startup; only owned current main-frame React ready cancels its deadline', () => {
  const f = fixture(); f.notice('ready'); f.navigate();
  f.renderer.emit('did-finish-load'); f.advance(29_999); assert.deepEqual(f.failures, []);
  f.notice('ready'); f.notice('ready'); f.advance(600_000);
  assert.deepEqual(f.failures, []); assert.equal(f.timers.size, 0); f.dispose();
});

test('missing bundle reaches one bounded startup failure and late ready cannot revive it', () => {
  const f = fixture(); f.navigate(); f.renderer.emit('did-finish-load'); f.advance(30_000);
  assert.deepEqual(f.failures, ['startup']); f.notice('ready'); f.notice('failed');
  f.renderer.emit('render-process-gone'); f.advance(300_000);
  assert.deepEqual(f.failures, ['startup']); assert.equal(f.timers.size, 0); f.dispose();
});

test('other senders, subframes, detached frames, wrong document and extra payload cannot send lifecycle notices', () => {
  const f = fixture(); f.navigate();
  for (const sender of [{...f.event(), sender: {}}, {...f.event(), senderFrame: null},
    {...f.event(), senderFrame: {url: ENTRY}}]) {f.notice('ready', sender); f.notice('failed', sender);}
  f.renderer.mainFrame.url = ENTRY + '?foreign=true'; f.notice('ready'); f.notice('failed');
  f.renderer.mainFrame.url = ENTRY;
  for (const kind of [null, {}, ['ready'], 1, ' ready', 'READY', 'reload']) f.notice(kind);
  f.notice('ready', f.event(), 'private'); f.notice('failed', f.event(), {});
  const detached = {sender: f.renderer, get senderFrame() {throw Error('detached');}};
  f.notice('failed', detached);
  assert.deepEqual(f.failures, []); f.advance(30_000); assert.deepEqual(f.failures, ['startup']); f.dispose();
});

test('a rendered boundary failure remains actionable after ready and permanently latches', () => {
  const f = fixture(); f.navigate(); f.notice('ready'); f.notice('failed');
  assert.deepEqual(f.failures, ['renderer']); f.notice('failed'); f.notice('ready');
  f.navigate(); f.advance(50_000); assert.deepEqual(f.failures, ['renderer']); f.dispose();
});

test('a new main document fails closed instead of accepting its ready as another startup generation', () => {
  const f = fixture(); f.navigate(); f.notice('ready'); const oldFrame = f.renderer.mainFrame;
  f.navigate(); f.renderer.mainFrame = {url: ENTRY};
  f.notice('ready', {sender: f.renderer, senderFrame: oldFrame}); f.notice('ready');
  assert.deepEqual(f.failures, ['renderer']); f.dispose();
});

test('same-document changes and subframe navigation do not restart the main-frame deadline', () => {
  const f = fixture(); f.navigate(); f.advance(20_000);
  f.navigate({isMainFrame: false, url: 'about:blank'}); f.navigate({isSameDocument: true});
  f.advance(10_000); assert.deepEqual(f.failures, ['startup']); f.dispose();
});

test('startup deadline counts only visible focused non-minimized time and stale timer callbacks are ignored', () => {
  const f = fixture(); f.navigate(); f.advance(10_000);
  const stale = [...f.timers.values()][0].callback;
  f.window.focused = false; f.window.emit('blur'); f.advance(600_000); stale();
  assert.deepEqual(f.failures, []); assert.equal(f.timers.size, 0);
  f.window.focused = true; f.window.emit('focus'); f.advance(10_000);
  f.window.minimized = true; f.window.emit('minimize'); f.advance(600_000);
  f.window.minimized = false; f.window.visible = false; f.window.emit('restore'); f.advance(600_000);
  f.window.visible = true; f.window.emit('show'); f.advance(9_999); assert.deepEqual(f.failures, []);
  f.advance(1); assert.deepEqual(f.failures, ['startup']); f.dispose();
});

test('main-frame load failure and renderer loss fail once without publishing raw errors', () => {
  const f = fixture(); f.navigate();
  f.renderer.emit('did-fail-load', {}, -1, 'PRIVATE DETAIL', ENTRY, false);
  assert.deepEqual(f.failures, []);
  f.renderer.emit('did-fail-load', {}, -1, 'PRIVATE DETAIL', ENTRY, true);
  f.renderer.emit('render-process-gone', {}, {reason: 'PRIVATE DETAIL'});
  assert.deepEqual(f.failures, ['startup']); f.dispose();
  const ready = fixture(); ready.navigate(); ready.notice('ready'); ready.renderer.emit('render-process-gone');
  assert.deepEqual(ready.failures, ['renderer']); ready.dispose();
});

test('dispose/normal close removes IPC, window listeners and timers without a late failure', () => {
  for (const close of [f => f.dispose(), f => f.window.emit('closed')]) {
    const f = fixture(); f.navigate(); const stale = [...f.timers.values()][0].callback; close(f); close(f);
    f.notice('failed'); stale(); f.advance(60_000); f.renderer.emit('render-process-gone');
    assert.deepEqual(f.failures, []); assert.equal(f.timers.size, 0);
    assert.equal(f.ipc.listenerCount(WORKSPACE_LIFECYCLE_CHANNEL), 0);
    assert.deepEqual(f.window.eventNames(), []); assert.deepEqual(f.renderer.eventNames(), []);
  }
});

for (const filename of ['preload.cjs', 'auth-preload.cjs']) test(`${filename} exposes only literal one-way lifecycle notices`, () => {
  const bridges = new Map(), sent = [];
  const electron = {contextBridge: {exposeInMainWorld: (name, value) => bridges.set(name, value)},
    ipcRenderer: {send: (...args) => {sent.push(args); return 'not returned';}}};
  vm.runInNewContext(readFileSync(new URL(filename, import.meta.url), 'utf8'), {
    require(name) {assert.equal(name, 'electron'); return electron;},
  });
  const bridge = bridges.get('cosmasWorkspaceLifecycle');
  assert.deepEqual(Object.keys(bridge), ['notify']); assert.equal(Object.isFrozen(bridge), true);
  for (const kind of [undefined, null, {}, ['ready'], 1, 'READY', 'reload', 'failed with private details']) {
    assert.equal(bridge.notify(kind), undefined);
  }
  assert.deepEqual(sent, []);
  assert.equal(bridge.notify('ready'), undefined); assert.equal(bridge.notify('failed'), undefined);
  assert.deepEqual(sent, [[WORKSPACE_LIFECYCLE_CHANNEL, 'ready'], [WORKSPACE_LIFECYCLE_CHANNEL, 'failed']]);
});
