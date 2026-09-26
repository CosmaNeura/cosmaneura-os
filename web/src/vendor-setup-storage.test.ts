// @vitest-environment node
import {describe,expect,it,vi} from 'vitest';
import {openDraftStore,type DraftValue} from './draft-store';
// Reuse the installed Scribe storage harness; no new dependency or custody backend.
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const scope='a'.repeat(64),id='account-editor:vendor-setup';
const size=(v:unknown)=>new TextEncoder().encode(JSON.stringify(v)).length;
function exact(bytes:number):DraftValue{const v:DraftValue={schema:1,updatedAt:'2026-09-22T12:00:00.000Z',body:{text:''}};return {...v,body:{text:'x'.repeat(bytes-size(v))}};}
function native(){const records=new Map<string,{key:string;data:string;revision:string}>();let lost=true;return {
 get:async({key}:{key:string})=>{if(!records.has(key))throw {code:'SECURE_QUEUE_NOT_FOUND'};return {...records.get(key)!};},
 create:async(v:{key:string;data:string})=>{if(records.has(v.key))throw {code:'SECURE_QUEUE_ALREADY_EXISTS'};records.set(v.key,{...v,revision:'1'});if(lost){lost=false;throw Error('Committed bridge response lost');}return {revision:'1'};},
 compareAndSwap:async(v:{key:string;data:string;expectedRevision:string})=>{const old=records.get(v.key);if(old?.revision!==v.expectedRevision)throw {code:'SECURE_QUEUE_REVISION_CONFLICT'};const revision=String(BigInt(old.revision)+1n);records.set(v.key,{key:v.key,data:v.data,revision});return {revision};},
};}
describe('vendor settings use existing bounded draft custody',()=>{
 it.each([false,true])('preserves whole128KiB frame bound, reopen, scope isolation and CAS (native bridge double=%s)',async useNative=>{
  const options={scope,native:useNative,indexedDB:new IDBFactory(),crypto:webcrypto,...(useNative?{plugin:native()}:{})},store=await openDraftStore(options),maximum=exact(131072);
  await store.write(id,null,maximum);await expect(store.write(id,'1',exact(131073))).rejects.toMatchObject({code:'invalid'});await expect(store.write(id+':unbound',null,maximum)).rejects.toMatchObject({code:'invalid'});store.close();
  const reopened=await openDraftStore(options),stale=await openDraftStore(options);expect((await reopened.read(id)).value).toEqual(maximum);const smaller=exact(1024);await reopened.write(id,'1',smaller);await expect(stale.write(id,'1',maximum)).rejects.toMatchObject({code:'conflict'});reopened.close();stale.close();
  const foreign=await openDraftStore({...options,scope:'b'.repeat(64)});expect((await foreign.read(id)).value).toBeNull();foreign.close();
 });
});
