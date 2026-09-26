import {webcrypto} from 'node:crypto';
import {IDBFactory} from 'fake-indexeddb';
import {expect,it} from 'vitest';
import {openDraftStore,type DraftValue} from '../../../../web/src/draft-store';

const crypto=webcrypto as unknown as Crypto,scope='a'.repeat(64),other='b'.repeat(64);
const addresses=['account-editor:inbox-work','account-editor:inbox-handoffs'] as const;
const maximumValue=131072+512,maximumFrame=maximumValue+512;
const encode=(v:unknown)=>new TextEncoder().encode(JSON.stringify(v));
const small:DraftValue={schema:1,updatedAt:'2026-09-22T12:00:00.000Z',body:{retained_request:'invented exact original request',retained_receipt:'invented exact durable proof'}};
const maximum=()=>{const base={...small,body:{note:''}};return {...base,body:{note:'x'.repeat(maximumValue-encode(base).length)}};};
function nativeFixture(){
 const records=new Map<string,{key:string;data:string;revision:string}>();let dropCreate=false,dropSwap=false,creates=0,swaps=0;
 const plugin={
   get:async({key}:{key:string})=>{const record=records.get(key);if(!record)throw {code:'SECURE_QUEUE_NOT_FOUND'};return {...record};},
   create:async(record:{key:string;data:string})=>{if(records.has(record.key))throw {code:'SECURE_QUEUE_ALREADY_EXISTS'};records.set(record.key,{...record,revision:'1'});creates++;if(dropCreate){dropCreate=false;throw Error('Committed create reply lost');}return {revision:'1'};},
   compareAndSwap:async(record:{key:string;data:string;expectedRevision:string})=>{const old=records.get(record.key);if(!old||old.revision!==record.expectedRevision)throw {code:'SECURE_QUEUE_REVISION_CONFLICT'};const revision=String(BigInt(old.revision)+1n);records.set(record.key,{key:record.key,data:record.data,revision});swaps++;if(dropSwap){dropSwap=false;throw Error('Committed CAS reply lost');}return {revision};},
 };
 return {records,plugin,loseCreate(){dropCreate=true;},loseSwap(){dropSwap=true;},counts:()=>({creates,swaps})};
}

it.each([false,true])('preserves both exact Inbox address records at the framed value ceiling after reopen, with unchanged scoped CAS (native=%s)',async native=>{
 const f=nativeFixture(),options={scope,native,crypto,indexedDB:new IDBFactory(),...(native?{plugin:f.plugin}:{})},value=maximum();
 expect(encode(value).length).toBe(maximumValue);const first=await openDraftStore(options);
 for(const address of addresses){await first.write(address,null,value);await expect(first.write(address,'1',{...value,body:{note:value.body.note+'x'}})).rejects.toMatchObject({code:'invalid'});}
 first.close();const opened=await openDraftStore(options),stale=await openDraftStore(options);
 for(const address of addresses){expect((await opened.read(address)).value).toEqual(value);await opened.write(address,'1',small);await expect(stale.write(address,'1',value)).rejects.toMatchObject({code:'conflict'});}
 opened.close();stale.close();const foreign=await openDraftStore({...options,scope:other});for(const address of addresses)expect((await foreign.read(address)).value).toBeNull();foreign.close();
});

it('uses bounded canonical Base64 native frames and exact namespaced address binding',async()=>{
 const f=nativeFixture(),options={scope,native:true,crypto,indexedDB:new IDBFactory(),plugin:f.plugin},store=await openDraftStore(options);
 for(const address of addresses){await store.write(address,null,maximum());const record=f.records.get(`cosmas-private-draft:v1:${scope}:${address}`)!;
   const bytes=Buffer.from(record.data,'base64'),frame=JSON.parse(bytes.toString('utf8'));
   expect(Buffer.byteLength(record.key)).toBeLessThanOrEqual(512);expect(bytes.length).toBeLessThanOrEqual(maximumFrame);expect(record.data.length).toBeLessThanOrEqual(4*Math.ceil(maximumFrame/3));
   expect(bytes.toString('base64')).toBe(record.data);expect(frame).toEqual({version:1,scope,address,value:maximum()});
 }
 const first=f.records.get(`cosmas-private-draft:v1:${scope}:${addresses[0]}`)!;
 f.records.set(`cosmas-private-draft:v1:${scope}:${addresses[1]}`,{...first,key:`cosmas-private-draft:v1:${scope}:${addresses[1]}`});
 await expect(store.read(addresses[1])).rejects.toMatchObject({code:'integrity'});store.close();
});

it('recovers committed native create and CAS replies without an extra write or browser fallback',async()=>{
 const f=nativeFixture(),indexedDB=new IDBFactory(),options={scope,native:true,crypto,indexedDB,plugin:f.plugin};
 const store=await openDraftStore(options);f.loseCreate();const created=await store.write(addresses[0],null,maximum());expect(created.revision).toBe('1');
 f.loseSwap();const changed=await store.write(addresses[0],'1',small);expect(changed.revision).toBe('2');expect(changed.value).toEqual(small);expect(f.counts()).toEqual({creates:1,swaps:1});store.close();
 const reopened=await openDraftStore(options);expect(await reopened.read(addresses[0])).toEqual(changed);reopened.close();
 await expect(openDraftStore({...options,native:false})).rejects.toMatchObject({code:'profile'});
});

it.each([false,true])('denies nearby aliases and stored credentials without touching either exact Inbox record (native=%s)',async native=>{
 const f=nativeFixture(),store=await openDraftStore({scope,native,crypto,indexedDB:new IDBFactory(),...(native?{plugin:f.plugin}:{})});
 for(const address of addresses)await store.write(address,null,small);
 for(const address of ['account-editor:inbox','account-editor:inbox-work:other','account-editor:inbox-handoffs:other','editor:00000000-0000-4000-8000-000000000001:inbox-work'])await expect(store.write(address,null,small)).rejects.toMatchObject({code:'invalid'});
 await expect(store.write(addresses[0],'1',{...small,body:{token:'not stored'}})).rejects.toMatchObject({code:'invalid'});
 for(const address of addresses)expect((await store.read(address)).value).toEqual(small);store.close();
});
