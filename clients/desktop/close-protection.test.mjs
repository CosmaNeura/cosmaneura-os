import test from 'node:test';
import assert from 'node:assert/strict';
import {EventEmitter} from 'node:events';
import {installDesktopCloseProtection, cleanupOnConfirmedQuit} from './close-protection.mjs';
import {createDesktopAuthSession} from './auth-session.mjs';

test('native stop completes before auth cleanup and a lost stop response can retry', async () => {
  const app=new EventEmitter();let attempts=0,cleaned=0,failures=0,prevented=0;
  let cleanupFinished, failureReported;
  const cleanupComplete=new Promise(resolve=>{cleanupFinished=resolve;});
  const failureComplete=new Promise(resolve=>{failureReported=resolve;});
  const event={preventDefault(){prevented++;}};
  app.quit=()=>app.emit('will-quit',event);
  cleanupOnConfirmedQuit(app,()=>{cleaned++;cleanupFinished();},{beforeCleanup:async()=>{if(++attempts===1)throw Error('Invented stop loss');},onFailure:()=>{failures++;failureReported();}});
  app.quit();app.quit();await failureComplete;
  assert.equal(attempts,1);assert.equal(cleaned,0);assert.equal(failures,1);
  app.quit();await cleanupComplete;
  assert.equal(attempts,2);assert.equal(cleaned,1);assert.equal(prevented,3);
  app.quit();assert.equal(cleaned,1);
});

test('close defaults to keeping the window; only explicit close overrides the renderer veto', () => {
  const window = {webContents: new EventEmitter()}; let selection = 0, overrides = 0;
  installDesktopCloseProtection(window, {showMessageBoxSync(owner, options) {
    assert.equal(owner, window); assert.equal(options.defaultId, 0); assert.equal(options.cancelId, 0);
    assert.deepEqual(options.buttons, ['Keep working', 'Close anyway']);
    assert.match(options.detail, /already submitted may still finish/);
    return selection;
  }});
  const event = {preventDefault: () => overrides++};
  for (selection of [0, -1, undefined]) window.webContents.emit('will-prevent-unload', event);
  assert.equal(overrides, 0);
  selection = 1; window.webContents.emit('will-prevent-unload', event);
  assert.equal(overrides, 1);
});

test('a failed native dialog preserves the window', () => {
  const window = {webContents: new EventEmitter()};
  installDesktopCloseProtection(window, {showMessageBoxSync() {throw Error('Invented dialog failure');}});
  let forced = false;
  window.webContents.emit('will-prevent-unload', {preventDefault: () => {forced = true;}});
  assert.equal(forced, false);
});

test('cancelled quit keeps a real auth-session object usable; confirmed quit closes exactly once', async () => {
  const app = new EventEmitter(); let closed = 0, ipcRemoved = 0;
  const native = {phase:'ready',revision:'00000000-0000-4000-8000-000000000020',identity:{userId:'user_invented',sessionId:'sess_invented',organizationId:'org_invented'}};
  const auth = await createDesktopAuthSession({enabled:true,
    accessStore:{read:async()=> 'allowed',write:async()=>{}},
    createHelper:()=>({subscribe:()=>()=>{},getState:async()=>native,getToken:async()=> 'invented.signed.token',close:()=>closed++})});
  cleanupOnConfirmedQuit(app,()=>{ipcRemoved++;auth.close();});
  const before = await auth.getState();assert.equal(before.phase,'ready');
  app.emit('before-quit', {preventDefault(){}});
  assert.equal(closed,0);assert.equal(ipcRemoved,0);
  assert.equal(await auth.getToken(before.revision),'invented.signed.token');
  app.emit('will-quit');app.emit('will-quit');
  assert.equal(closed,1);assert.equal(ipcRemoved,1);
  await assert.rejects(auth.getToken(before.revision),/unavailable/);
});
