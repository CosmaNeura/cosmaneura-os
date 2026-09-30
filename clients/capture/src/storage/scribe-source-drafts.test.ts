import {webcrypto} from 'node:crypto';
import {IDBFactory} from 'fake-indexeddb';
import {expect,it} from 'vitest';
import {openDraftStore,type DraftValue} from '../../../../web/src/draft-store';

const crypto=webcrypto as unknown as Crypto,scope='a'.repeat(64),otherScope='b'.repeat(64);
const workspaceId='00000000-0000-4000-8000-000000000071';
const address=`editor:${workspaceId}:scribe-source`;
const sourceDraft=()=>({
  kind:'editor',workspaceId,editor:'scribe-source',pending:'00000000-0000-4000-8000-000000000074',
  data:{idempotency_key:'00000000-0000-4000-8000-000000000074',expected_revision:2,
    selection:{version:1,session_id:'00000000-0000-4000-8000-000000000072',source_transcript_version:1,
      working_transcript_id:'00000000-0000-4000-8000-000000000073',working_transcript_version:2,snapshot_sha256:'c'.repeat(64)},
    reviewed:true,share_with_team:true},
});
function nativeFixture(){
  const records=new Map<string,{key:string;data:string;revision:string}>();let dropCreate=true,creates=0,swaps=0;
  const plugin={
    get:async({key}:{key:string})=>{const record=records.get(key);if(!record)throw {code:'SECURE_QUEUE_NOT_FOUND'};return {...record};},
    create:async(record:{key:string;data:string})=>{if(records.has(record.key))throw {code:'SECURE_QUEUE_ALREADY_EXISTS'};records.set(record.key,{...record,revision:'1'});creates++;if(dropCreate){dropCreate=false;throw Error('Committed reply lost');}return {revision:'1'};},
    compareAndSwap:async(record:{key:string;data:string;expectedRevision:string})=>{const old=records.get(record.key);if(!old||old.revision!==record.expectedRevision)throw {code:'SECURE_QUEUE_REVISION_CONFLICT'};const revision=String(BigInt(old.revision)+1n);records.set(record.key,{key:record.key,data:record.data,revision});swaps++;return {revision};},
  };
  return {records,plugin,counts:()=>({creates,swaps})};
}
async function raw(indexedDB:IDBFactory){
  const db=await new Promise<IDBDatabase>((resolve,reject)=>{const request=indexedDB.open(`cosmas-private-drafts:v1:${scope}`);request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);});
  const result=await new Promise<{records:{address:string;nonce:Uint8Array;ciphertext:ArrayBuffer;revision:string}[];key:CryptoKey}>((resolve,reject)=>{
    const tx=db.transaction(['sealed-drafts','metadata'],'readonly'),records=tx.objectStore('sealed-drafts').getAll(),key=tx.objectStore('metadata').get('draft-key-v1');
    tx.oncomplete=()=>resolve({records:records.result,key:key.result});tx.onabort=()=>reject(tx.error);
  });db.close();return result;
}

it.each([false,true])('opens and recovers the exact Scribe request through the actual scoped draft store (native=%s)',async native=>{
  // Native-port framing/retry coverage; not a physical-device/keychain acceptance claim.
  const fixture=nativeFixture(),indexedDB=new IDBFactory(),options={scope,native,crypto,indexedDB,...(native?{plugin:fixture.plugin}:{})};
  const store=await openDraftStore(options),draft=sourceDraft();
  const value:DraftValue={schema:1,updatedAt:'2026-09-30T12:00:00Z',body:draft};
  expect((await store.read(address)).value).toBeNull();
  const saved=await store.write(address,null,value);await store.write(address,saved.revision,value);
  expect((await store.read(address)).revision).toBe('1');store.close();
  const stored=await raw(indexedDB);
  if(native){
    expect(stored.records).toEqual([]);expect(fixture.counts()).toEqual({creates:1,swaps:0});
    const record=[...fixture.records.values()][0],frame=JSON.parse(Buffer.from(record.data,'base64').toString('utf8'));
    expect(Buffer.byteLength(record.key)).toBeLessThanOrEqual(512);
    expect(Buffer.from(record.data,'base64').length).toBeLessThanOrEqual(4608);
    expect(frame).toMatchObject({address,scope,value:{body:draft}});
  }else{
    expect(stored.key.extractable).toBe(false);await expect(crypto.subtle.exportKey('raw',stored.key)).rejects.toThrow();
    expect(stored.records).toHaveLength(1);expect(Object.keys(stored.records[0]).sort()).toEqual(['address','ciphertext','nonce','revision']);
    expect(new TextDecoder().decode(stored.records[0].ciphertext)).not.toContain(draft.pending);
  }
  const reopened=await openDraftStore(options),stale=await openDraftStore(options);
  expect(await reopened.read(address)).toEqual(saved);expect(await stale.read(address)).toEqual(saved);
  await reopened.write(address,saved.revision,null);
  const replacement=sourceDraft();replacement.pending='00000000-0000-4000-8000-000000000075';replacement.data.idempotency_key=replacement.pending;
  await expect(stale.write(address,saved.revision,{...value,body:replacement})).rejects.toMatchObject({code:'conflict'});
  expect((await reopened.read(address)).value).toBeNull();reopened.close();stale.close();
  const foreign=await openDraftStore({...options,scope:otherScope});
  expect((await foreign.read(address)).value).toBeNull();foreign.close();
});

it.each([false,true])('allows only the exact Scribe editor namespace and caps its framed value at 4 KiB (native=%s)',async native=>{
  const fixture=nativeFixture(),options={scope,native,crypto,indexedDB:new IDBFactory(),...(native?{plugin:fixture.plugin}:{})},store=await openDraftStore(options);
  const value:DraftValue={schema:1,updatedAt:'2026-09-30T12:00:00Z',body:{metadata:''}};
  const maximum={...value,body:{metadata:'x'.repeat(4096-new TextEncoder().encode(JSON.stringify(value)).length)}};
  await store.write(address,null,maximum);store.close();
  const reopened=await openDraftStore(options);expect((await reopened.read(address)).value).toEqual(maximum);
  await expect(reopened.write(address,'1',{...maximum,body:{metadata:maximum.body.metadata+'x'}})).rejects.toMatchObject({code:'invalid'});
  for(const bad of [address+':other',address.replace(':scribe-source',':scribe'),address.replace(':scribe-source',':scribe/source'),'account-editor:scribe-source',address.replace(workspaceId,'unbound')]){
    await expect(reopened.read(bad)).rejects.toMatchObject({code:'invalid'});
    await expect(reopened.write(bad,null,value)).rejects.toMatchObject({code:'invalid'});
  }
  expect((await reopened.read(address)).value).toEqual(maximum);reopened.close();
});
