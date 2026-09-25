import assert from 'node:assert/strict';
import test from 'node:test';
import {randomUUID} from 'node:crypto';
import {EventEmitter} from 'node:events';
import {COSMANEURA_CHANNELS, cosmaneuraOrigin, parseCosmaneuraRequest, installCosmaneuraNavigation} from './cosmaneura-navigation.mjs';

const origin = 'https://clinical.example.invalid';
const href = origin + '/notes/appointment_00000000000000000000000001';
const revision = '00000000-0000-4000-8000-000000000001';
const ready = {phase:'ready', revision, identity:{userId:'user_invented',sessionId:'sess_invented',organizationId:'org_invented'}};
const payload = () => ({schemaVersion:1,requestId:randomUUID(),expectedRevision:revision,href});
const invalidOrigins = ['https://clinical.example.invalid/', 'http://clinical.example.invalid', 'https://clinical.example.invalid:443',
  'https://clinical.example.invalid:8443', 'https://127.1', 'https://2130706433', 'https://0x7f000001', 'https://[::1]',
  'https://clinical.example.invalid:65536', 'https://clinical.example.invalid:01', 'https://clinical.example.invalid?x=1',
  'https://clinical.example.invalid#fragment', 'https://user@clinical.example.invalid', 'https://Clinical.example.invalid',
  'https://clinical..example.invalid','https://-clinical.example.invalid','https://127.0.0.1','https://localhost',
  'https://clinical.example.invalid\\outside','https://clínical.example.invalid',null,{},' https://clinical.example.invalid'];

test('empty native origin is disabled and canonical HTTPS origin is required', () => {
  assert.equal(cosmaneuraOrigin(), null);
  assert.equal(cosmaneuraOrigin(origin), origin);
  for (const value of invalidOrigins) assert.throws(() => cosmaneuraOrigin(value), undefined, String(value));
});

test('only exact note references pass; normalization, redirects and credential material never do', () => {
  assert.deepEqual(parseCosmaneuraRequest(payload(),origin).href,href);
  for (const value of [href+'/',href+'?token=secret',href+'#note',href.replace('/notes/','/x/../notes/'),
    href.replace('/notes/','/%6eotes/'),href.replace('/notes/','//notes/'),href.replace('/notes/','\\notes\\'),
    href.replace('clinical.example.invalid','clinical.example.invalid.evil.invalid'),href.replace('https://','https://user@'),
    href.replace('appointment_0','appointment_8'),href.replace('appointment_0','appointment_I'),href+'\n',
    origin+'/redirect?url='+href,origin+'/notes/appointment_'+ '0'.repeat(27)]) {
    assert.throws(() => parseCosmaneuraRequest({...payload(),href:value},origin), undefined, value);
  }
  for(const extra of [{schemaVersion:true},{expectedRevision:'wrong'},{requestId:revision.toUpperCase()}, {token:'secret'}]) {
    // A digit-only UUID is unchanged by uppercase; use one with letters for this vector.
    const value = {...payload(),...extra}; if ('requestId' in extra) value.requestId='AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA';
    assert.throws(() => parseCosmaneuraRequest(value,origin));
  }
  assert.throws(() => parseCosmaneuraRequest(payload(),null));
});

function fixture(webOrigin = origin) {
  const handlers = new Map(), listeners = new Map(), opened=[];
  let state=ready, destroyed=false;
  const renderer=Object.assign(new EventEmitter(), {mainFrame:{url:'app://cosmas/index.html'},getURL:()=>renderer.mainFrame.url,isDestroyed:()=>destroyed});
  const ipcMain={on:(n,f)=>listeners.set(n,f),removeListener:n=>listeners.delete(n),handle:(n,f)=>handlers.set(n,f),removeHandler:n=>handlers.delete(n)};
  const auth={snapshot:()=>state,getState:async()=>state};
  const dispose=installCosmaneuraNavigation({ipcMain,renderer,auth,webOrigin,openExternal:async value=>{opened.push(value);}});
  const event={sender:renderer,senderFrame:renderer.mainFrame};
  return {handlers,listeners,renderer,auth,dispose,event,opened,setState:value=>{state=value;},destroy:()=>{destroyed=true;},
    open:(value=payload(),eventOverride=event)=>handlers.get(COSMANEURA_CHANNELS.open)(eventOverride,value)};
}

test('dispatches one exact URL after fresh same-session check; no navigation or token capability', async()=>{
  const f=fixture(), request=payload();
  const receipt=await f.open(request);
  assert.deepEqual(receipt,{schemaVersion:1,requestId:request.requestId,status:'opened'});
  assert.deepEqual(f.opened,[href]);
  await assert.rejects(f.open(request)); assert.equal(f.opened.length,1);
  f.dispose(); assert.equal(f.handlers.size,0);assert.equal(f.listeners.size,0);
});

test('default-off capability and malformed sender/frame/session fail before browser dispatch',async()=>{
  const off=fixture(''); const e={...off.event};off.listeners.get(COSMANEURA_CHANNELS.capability)(e);assert.equal(e.returnValue,false);
  await assert.rejects(off.open());assert.deepEqual(off.opened,[]);
  const f=fixture();
  for(const event of [{...f.event,sender:{}},{...f.event,senderFrame:null},{...f.event,senderFrame:{url:'app://cosmas/index.html'}}]) await assert.rejects(f.open(payload(),event));
  f.renderer.mainFrame.url='app://cosmas/index.html?external=1';await assert.rejects(f.open());
  f.renderer.mainFrame.url='app://cosmas/index.html';
  for(const state of [{phase:'signedOut',revision,identity:null},{...ready,revision:randomUUID()},{...ready,identity:null}]) {f.setState(state);await assert.rejects(f.open());}
  assert.deepEqual(f.opened,[]);
});

test('session change, replacement frame and disposal during fresh check prevent the effect', async()=>{
  for(const change of [f=>f.setState({...ready,revision:randomUUID()}),f=>{f.renderer.mainFrame={url:'app://cosmas/index.html'};},
    f=>f.renderer.emit('did-start-navigation',{},'app://cosmas/index.html',false,true),f=>f.dispose(),f=>f.destroy()]) {
    const f=fixture();let resolve;f.auth.getState=()=>new Promise(r=>{resolve=r;});
    const result=f.open();const rejected=assert.rejects(result);change(f);resolve(ready);await rejected;assert.deepEqual(f.opened,[]);
  }
});

test('only one pending dispatch; open failures are generic and never automatically retried', async()=>{
  const f=fixture();let resolve;f.auth.getState=()=>new Promise(r=>{resolve=r;});
  const first=f.open();await assert.rejects(f.open());resolve(ready);await first;assert.equal(f.opened.length,1);
  const listeners=new Map(),renderer=f.renderer;
  const ipcMain={on(){},removeListener(){},handle:(n,fn)=>listeners.set(n,fn),removeHandler(){}};
  let attempts=0;
  installCosmaneuraNavigation({ipcMain,renderer,auth:{snapshot:()=>ready,getState:async()=>ready},webOrigin:origin,
    openExternal:async()=>{attempts++;throw new Error('private browser error');}});
  const request=payload();
  await assert.rejects(listeners.get(COSMANEURA_CHANNELS.open)(f.event,request),{message:'Cosmaneura navigation unavailable'});
  await assert.rejects(listeners.get(COSMANEURA_CHANNELS.open)(f.event,request));assert.equal(attempts,1);
});

test('12-second pre-dispatch deadline fences late auth and retains a single unresolved attempt', async t=>{
  t.mock.timers.enable({apis:['setTimeout']});
  const f=fixture();let resolve;f.auth.getState=()=>new Promise(r=>{resolve=r;});
  const request=payload(), operation=f.open(request), rejected=assert.rejects(operation);
  t.mock.timers.tick(12_000);await rejected;
  await assert.rejects(f.open());assert.deepEqual(f.opened,[]);
  resolve(ready);await Promise.resolve();await Promise.resolve();
  assert.deepEqual(f.opened,[]);await assert.rejects(f.open(request));
});

test('12-second missing OS callback is unconfirmed; no second dispatch or late success receipt',async t=>{
  t.mock.timers.enable({apis:['setTimeout']});
  const f=fixture();const handlers=new Map();let complete;let effects=0;
  const ipcMain={on(){},removeListener(){},handle:(n,fn)=>handlers.set(n,fn),removeHandler(){}};
  installCosmaneuraNavigation({ipcMain,renderer:f.renderer,auth:f.auth,webOrigin:origin,
    openExternal:()=>{effects++;return new Promise(r=>{complete=r;});}});
  const call=p=>handlers.get(COSMANEURA_CHANNELS.open)(f.event,p);
  const operation=call(payload()), rejected=assert.rejects(operation);await Promise.resolve();
  assert.equal(effects,1);t.mock.timers.tick(12_000);await rejected;
  await assert.rejects(call(payload()));assert.equal(effects,1);
  complete();await Promise.resolve();await Promise.resolve();assert.equal(effects,1);
});
