import assert from 'node:assert/strict';
import test from 'node:test';
import {readFile} from 'node:fs/promises';
import {runInContext} from 'node:vm';
import {randomUUID} from 'node:crypto';
import {createRequire} from 'node:module';
const {JSDOM}=createRequire(new URL('../../web/package.json',import.meta.url))('jsdom');

const script=await readFile(new URL('../shared/cosmaneura-navigation-dom.js',import.meta.url),'utf8');
const request=()=>({schemaVersion:1,requestId:randomUUID(),expectedRevision:randomUUID(),href:'https://clinical.example.invalid/notes/appointment_00000000000000000000000001'});
const settle=()=>new Promise(resolve=>setImmediate(resolve));
function fixture({available=true,submit}={}) {
  const dom=new JSDOM('<!doctype html><button type="button"><span>Open in Cosmaneura</span></button>',{url:'https://isolated.example.invalid',runScripts:'outside-only'});
  const w=dom.window,d=w.document,b=d.querySelector('button'),calls=[],receipts=[];
  let listener;const add=d.addEventListener.bind(d);
  d.addEventListener=(name,fn,...options)=>{if(name==='click')listener=fn;return add(name,fn,...options);};
  d.addEventListener('cosmas-cosmaneura-record-navigation',event=>receipts.push(JSON.parse(event.detail)));
  runInContext(script,dom.getInternalVMContext());
  const payload=request();b.setAttribute('data-cosmaneura-record-link',JSON.stringify(payload));
  w.installCosmaneuraTrustedClicks(available,async p=>{calls.push(p);return submit?submit(p):{schemaVersion:1,requestId:p.requestId,status:'opened'};});
  return {dom,w,d,b,payload,calls,receipts,click:(overrides={})=>listener({isTrusted:true,button:0,target:b.querySelector('span'),preventDefault(){},...overrides})};
}

test('real programmatic DOM clicks and forged untrusted events cannot invoke private transport',async()=>{
  const f=fixture();f.b.click();f.b.dispatchEvent(new f.w.MouseEvent('click',{bubbles:true}));f.click({isTrusted:false});await settle();
  assert.equal(f.calls.length,0);assert.equal(f.receipts.length,0);f.dom.window.close();
});

test('synthetic trusted-event harness covers enabled button, serial dispatch and exact receipt only',async()=>{
  let resolve;const f=fixture({submit:p=>new Promise(r=>{resolve=()=>r({schemaVersion:1,requestId:p.requestId,status:'opened'});})});
  f.click();f.click();await settle();assert.equal(f.calls.length,1);resolve();await settle();
  assert.deepEqual(f.receipts,[{schemaVersion:1,requestId:f.payload.requestId,status:'opened'}]);
  f.click();await settle();assert.equal(f.calls.length,1);
  f.b.setAttribute('data-cosmaneura-record-link',JSON.stringify(request()));f.click();await settle();assert.equal(f.calls.length,2);resolve();await settle();f.dom.window.close();
});

test('disabled, inert, foreign, nonbutton, detached and nonprimary targets never dispatch',async()=>{
  for(const mutate of [f=>{f.b.disabled=true;},f=>f.b.setAttribute('aria-disabled','true'),f=>f.b.setAttribute('inert',''),
    f=>f.b.remove(),f=>{f.b.outerHTML='<a data-cosmaneura-record-link="{}">Open</a>';},
    f=>{const fieldset=f.d.createElement('fieldset');fieldset.disabled=true;f.b.replaceWith(fieldset);fieldset.append(f.b);}]) {
    const f=fixture();mutate(f);f.click();await settle();assert.equal(f.calls.length,0);f.dom.window.close();
  }
  const f=fixture();f.click({button:1});f.click({target:f.d.body});f.click({target:{closest:()=>f.b}});await settle();assert.equal(f.calls.length,0);f.dom.window.close();
  const off=fixture({available:false});off.click();await settle();assert.equal(off.calls.length,0);off.dom.window.close();
});

test('bad payload and mismatched or private response surface only unavailable outcome',async()=>{
  for(const value of ['{',JSON.stringify({...request(),token:'private'}),'x'.repeat(2049),JSON.stringify({...request(),requestId:'invalid'})]) {
    const f=fixture();f.b.setAttribute('data-cosmaneura-record-link',value);f.click();await settle();assert.equal(f.calls.length,0);f.dom.window.close();
  }
  for(const submit of [async()=>{throw new Error('secret response');},async p=>({schemaVersion:1,requestId:p.requestId,status:'opened',token:'private'}),async()=>({schemaVersion:1,requestId:randomUUID(),status:'opened'})]) {
    const f=fixture({submit});f.click();await settle();assert.deepEqual(f.receipts,[{schemaVersion:1,requestId:f.payload.requestId,status:'unavailable'}]);f.dom.window.close();
  }
});

test('only type=button is admitted; later bubble cancellation prevents private native submit',async()=>{
  for(const type of ['submit','reset','invalid']) {
    const f=fixture();f.b.setAttribute('type',type);f.click();await settle();assert.equal(f.calls.length,0);f.dom.window.close();
  }
  const f=fixture();let cancelled=false;
  const event={isTrusted:true,button:0,target:f.b,get defaultPrevented(){return cancelled;},preventDefault(){cancelled=true;}};
  // Preserve the shared defaultPrevented getter instead of fixture's object spread.
  let receive;const add=f.d.addEventListener.bind(f.d);
  f.d.addEventListener=(name,fn,...options)=>{if(name==='click')receive=fn;return add(name,fn,...options);};
  f.w.installCosmaneuraTrustedClicks(true,async p=>{f.calls.push(p);return {schemaVersion:1,requestId:p.requestId,status:'opened'};});
  receive(event);event.preventDefault();await settle();
  assert.equal(f.calls.length,0);assert.equal(f.receipts.at(-1).status,'unavailable');f.dom.window.close();
});

test('accepted capture snapshot survives the bubble handler disabling its pending button',async()=>{
  const f=fixture();f.click();f.b.disabled=true;await settle();
  assert.equal(f.calls.length,1);assert.equal(f.receipts[0].status,'opened');f.dom.window.close();
});
