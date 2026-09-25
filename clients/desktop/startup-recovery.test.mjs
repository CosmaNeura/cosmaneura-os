import test from 'node:test';
import assert from 'node:assert/strict';
import {EventEmitter} from 'node:events';
import {createDesktopFailureHandler, destroyDesktopWorkspace, installDesktopLastWindowPolicy} from './startup-recovery.mjs';

test('startup failure waits only for native readiness and uses fixed guidance without opening a renderer',async()=>{
  const seen=[];const app={whenReady:async()=>seen.push(['ready']),exit:code=>seen.push(['exit',code])};
  const fail=createDesktopFailureHandler({app,dialog:{showMessageBoxSync:options=>seen.push(['dialog',options])},cleanup:()=>seen.push(['cleanup'])});
  await fail('untrusted source text');
  assert.equal(seen[0][0],'cleanup');assert.equal(seen[1][0],'ready');assert.equal(seen[2][0],'dialog');assert.match(seen[2][1].detail,/COSMAS_STARTUP_01/);
  assert.doesNotMatch(JSON.stringify(seen),/untrusted source text/);assert.deepEqual(seen.at(-1),['exit',1]);
});

test('renderer failure closes privileged access immediately, shows one dialog, and never auto-reloads or restarts',async()=>{
  let ready;const shown=[],exits=[];let cleanups=0,readies=0;
  const fail=createDesktopFailureHandler({app:{whenReady(){readies++;return new Promise(resolve=>{ready=resolve;});},exit:code=>exits.push(code)},
    dialog:{showMessageBoxSync:options=>shown.push(options)},cleanup:()=>cleanups++});
  const first=fail('renderer'),again=fail('startup');assert.equal(first,again);assert.equal(cleanups,1);
  await new Promise(setImmediate);assert.equal(readies,1);assert.equal(shown.length,0);ready();await first;
  assert.equal(shown.length,1);assert.deepEqual(shown[0].buttons,['Close CosmasOS']);
  assert.match(shown[0].detail,/submitted work may still finish/);assert.match(shown[0].detail,/COSMAS_RENDERER_01/);
  assert.deepEqual(exits,[1]);await fail('renderer');assert.equal(cleanups,1);assert.equal(shown.length,1);
});

test('private cleanup and dialog exceptions never escape to diagnostics or leave the app running',async()=>{
  let exited=0;
  const fail=createDesktopFailureHandler({app:{whenReady:async()=>{},exit:code=>{assert.equal(code,1);exited++;}},
    dialog:{showMessageBoxSync(){throw Error('PRIVATE DIALOG DETAIL');}},cleanup(){throw Error('PRIVATE SESSION DETAIL');}});
  await assert.doesNotReject(fail());assert.equal(exited,1);
});

test('failed renderer readiness still exits without a fallback renderer or automatic retry',async()=>{
  let exited=0;
  const fail=createDesktopFailureHandler({app:{whenReady:async()=>{throw Error('PRIVATE');},exit:()=>exited++},
    dialog:{showMessageBoxSync(){assert.fail('not ready');}}});
  await fail('renderer');assert.equal(exited,1);
});

test('failure closes privileged capabilities and destroys the renderer before native readiness or a dialog',async()=>{
  const seen=[];
  const fail=createDesktopFailureHandler({app:{whenReady:async()=>seen.push('ready'),exit:()=>seen.push('exit')},
    dialog:{showMessageBoxSync:()=>seen.push('dialog')},cleanup:()=>seen.push('capabilities-closed'),
    closeWorkspace:()=>{seen.push('renderer-destroyed');return true;}});
  const pending=fail('renderer');
  assert.deepEqual(seen,['capabilities-closed','renderer-destroyed']);await pending;
  assert.deepEqual(seen,['capabilities-closed','renderer-destroyed','ready','dialog','exit']);
});

test('unconfirmed or failed renderer destruction exits immediately instead of waiting behind a dialog',async()=>{
  for(const result of [false,undefined,'true','throw']) {
    let exited=0,closed=0;
    const fail=createDesktopFailureHandler({app:{whenReady:()=>assert.fail('must exit immediately'),exit:code=>{assert.equal(code,1);exited++;}},
      dialog:{showMessageBoxSync:()=>assert.fail('live renderer')},cleanup:()=>closed++,
      closeWorkspace:()=>{if(result==='throw')throw Error('PRIVATE');return result;}});
    await fail('renderer');await fail('startup');assert.equal(exited,1);assert.equal(closed,1);
  }
});

function delayedWindow(onClosed = () => {}) {
  const renderer = Object.assign(new EventEmitter(), {destroyed: false, isDestroyed() {return this.destroyed;}});
  const window = Object.assign(new EventEmitter(), {webContents: renderer, destroyed: false,
    isDestroyed() {return this.destroyed;}, destroy() {this.destroyed = true; this.emit('closed'); onClosed();}});
  return {window, renderer, destroyRenderer() {renderer.destroyed = true; renderer.emit('destroyed');}};
}

test('window destruction alone does not confirm renderer closure; both must complete and listeners are removed',async()=>{
  const f=delayedWindow();let done=false;
  const pending=destroyDesktopWorkspace(f.window).then(result=>{done=true;return result;});
  await new Promise(setImmediate);assert.equal(f.window.isDestroyed(),true);assert.equal(done,false);
  assert.equal(f.renderer.listenerCount('destroyed'),1);
  f.destroyRenderer();assert.equal(await pending,true);
  assert.equal(f.renderer.listenerCount('destroyed'),0);assert.equal(f.window.listenerCount('closed'),0);
  assert.equal(await destroyDesktopWorkspace(null),true);
});

test('a canceled closure removes late callbacks and cannot later establish success',async()=>{
  const f=delayedWindow(),controller=new AbortController();
  const pending=destroyDesktopWorkspace(f.window,{signal:controller.signal});
  controller.abort();assert.equal(await pending,false);f.destroyRenderer();
  assert.equal(f.renderer.listenerCount('destroyed'),0);assert.equal(f.window.listenerCount('closed'),0);
});

test('last-window policy suppresses implicit quit only while failure recovery is pending',()=>{
  const app=new EventEmitter();let failure=false,quits=0;app.quit=()=>quits++;
  installDesktopLastWindowPolicy(app,()=>failure);
  assert.equal(app.listenerCount('window-all-closed'),1);
  failure=true;app.emit('window-all-closed');assert.equal(quits,0);
  failure=false;app.emit('window-all-closed');assert.equal(quits,1);
});

test('actual asynchronous renderer closure must finish before the native dialog while default last-window quit stays suppressed',async()=>{
  const seen=[];const app=Object.assign(new EventEmitter(), {quit:()=>seen.push('quit'),
    whenReady:async()=>seen.push('native-ready'),exit:code=>seen.push(['exit',code])});
  let failure=false;
  installDesktopLastWindowPolicy(app,()=>failure);
  const f=delayedWindow(()=>app.emit('window-all-closed'));
  const fail=createDesktopFailureHandler({app,cleanup:()=>{failure=true;seen.push('auth-closed');},
    closeWorkspace:options=>destroyDesktopWorkspace(f.window,options),
    dialog:{showMessageBoxSync:()=>{assert.equal(f.renderer.isDestroyed(),true);seen.push('dialog');}}});
  const pending=fail('renderer');await new Promise(setImmediate);
  assert.deepEqual(seen,['auth-closed']);f.destroyRenderer();await pending;
  assert.deepEqual(seen,['auth-closed','native-ready','dialog',['exit',1]]);
});

test('closure deadline exits without a dialog, aborts pending observers and ignores late renderer completion',async()=>{
  const f=delayedWindow();let timeout,exits=0,cleanups=0,scheduledMs;
  const fail=createDesktopFailureHandler({app:{whenReady:()=>assert.fail('renderer still alive'),exit:code=>{assert.equal(code,1);exits++;}},
    cleanup:()=>cleanups++,closeWorkspace:options=>destroyDesktopWorkspace(f.window,options),
    dialog:{showMessageBoxSync:()=>assert.fail('renderer still alive')},
    setTimer:(callback,ms)=>{timeout=callback;scheduledMs=ms;return 1;},clearTimer:()=>{}});
  const pending=fail('renderer');assert.equal(cleanups,1);assert.equal(scheduledMs,5000);
  timeout();await pending;assert.equal(exits,1);assert.equal(f.renderer.listenerCount('destroyed'),0);
  f.destroyRenderer();await fail('renderer');assert.equal(exits,1);
});

test('reentrant failures share the exact pending promise until asynchronous closure completes',async()=>{
  const f=delayedWindow();let fail,reentrant,exits=0,cleanups=0;
  fail=createDesktopFailureHandler({app:{whenReady:async()=>{},exit:()=>exits++},
    cleanup:()=>{cleanups++;reentrant=fail('startup');},closeWorkspace:options=>destroyDesktopWorkspace(f.window,options),
    dialog:{showMessageBoxSync:()=>{}}});
  const pending=fail('renderer');assert.equal(reentrant,pending);assert.equal(fail('startup'),pending);
  f.destroyRenderer();await pending;assert.equal(cleanups,1);assert.equal(exits,1);
});
