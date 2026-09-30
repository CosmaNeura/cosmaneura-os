import {webcrypto} from 'node:crypto';
import {IDBFactory} from 'fake-indexeddb';
import {afterEach,expect,it,vi} from 'vitest';
import {EncryptedIndexedDbFlowStore} from './encrypted-store';

const crypto=webcrypto as unknown as Crypto;
afterEach(()=>vi.restoreAllMocks());
async function fixture(){
  const indexedDB=new IDBFactory(),databaseName=crypto.randomUUID();
  const open=()=>EncryptedIndexedDbFlowStore.open({databaseName,indexedDB,crypto});
  const store=await open(),sessionId=crypto.randomUUID();
  const saved={schemaVersion:5 as const,mode:'configured_core' as const,sessionId,startedAt:new Date().toISOString(),
    completeIdempotencyKey:crypto.randomUUID(),leaseRequest:null,leaseIdempotencyKey:null,
    profileSelection:{request:{schema_version:'1.0' as const,profile_id:'visit-60m-v1' as const,channels:['microphone' as const]},
      idempotencyKey:crypto.randomUUID(),receipt:null}};
  await store.putPreparationState(saved);
  const raw=await new Promise<IDBDatabase>((resolve,reject)=>{const r=indexedDB.open(databaseName);r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});
  async function get(area:string,key:string){
    return new Promise<any>((resolve,reject)=>{const tx=raw.transaction(area,'readonly'),r=tx.objectStore(area).get(key);
      tx.oncomplete=()=>resolve(r.result);tx.onabort=()=>reject(tx.error);});
  }
  async function put(area:string,value:unknown,key?:string){
    await new Promise<void>((resolve,reject)=>{const tx=raw.transaction(area,'readwrite');
      if(key)tx.objectStore(area).put(value,key);else tx.objectStore(area).put(value);
      tx.oncomplete=()=>resolve();tx.onabort=()=>reject(tx.error);});
  }
  const close=()=>{store.close();raw.close();};
  return {store,saved,open,get,put,close};
}

it('atomically retains the exact sealed intent and its opaque key while continuing standard preparation',async()=>{
  const f=await fixture();
  try{
    const original=await f.get('encrypted-flow-records','preparation');
    await f.store.continueEmptyProfilePreparation(f.saved);
    const {profileSelection:_,...rest}=f.saved;
    expect(await f.store.getPreparationState()).toEqual({...rest,schemaVersion:7});
    const archive=await f.get('metadata',`empty-profile-preparation:${f.saved.sessionId}`);
    expect(archive.original).toEqual(original);expect(archive.localKey.extractable).toBe(false);
    const plaintext=await crypto.subtle.decrypt({name:'AES-GCM',iv:archive.original.nonce,
      additionalData:new TextEncoder().encode('cosmaneura-capture-flow-state:v1:preparation')},archive.localKey,archive.original.ciphertext);
    expect(JSON.parse(new TextDecoder().decode(plaintext))).toEqual(f.saved);new Uint8Array(plaintext).fill(0);
    await expect(f.store.putPreparationState(f.saved)).rejects.toThrow();
    await expect(f.store.continueEmptyProfilePreparation(f.saved)).rejects.toThrow();
    const reopened=await f.open();expect(await reopened.getPreparationState()).toEqual({...rest,schemaVersion:7});reopened.close();
  }finally{f.close();}
});

it.each(['active','reservation','session-key','changed-intent'])('refuses %s without altering the original preparation',async obstacle=>{
  const f=await fixture();
  try{
    const before=await f.get('encrypted-flow-records','preparation');
    if(obstacle==='session-key'){
      const key=await crypto.subtle.generateKey({name:'AES-GCM',length:256},false,['encrypt','decrypt']);
      await f.put('session-keys',key,f.saved.sessionId);
    }else if(obstacle==='active'||obstacle==='reservation'){
      await f.put('encrypted-flow-records',{...before,key:obstacle==='active'?'active':'intent:synthetic-reservation'});
    }
    const expected=obstacle==='changed-intent'?{...f.saved,completeIdempotencyKey:crypto.randomUUID()}:f.saved;
    await expect(f.store.continueEmptyProfilePreparation(expected)).rejects.toThrow();
    expect(await f.get('encrypted-flow-records','preparation')).toEqual(before);
    expect(await f.get('metadata',`empty-profile-preparation:${f.saved.sessionId}`)).toBeUndefined();
  }finally{f.close();}
});

it('blocks an older preparation writer that finishes sealing after recovery commits',async()=>{
  const f=await fixture(),other=await f.open();
  let release!:()=>void,entered!:()=>void;
  const gate=new Promise<void>(resolve=>{release=resolve;}),started=new Promise<void>(resolve=>{entered=resolve;});
  const encrypt=crypto.subtle.encrypt.bind(crypto.subtle);
  vi.spyOn(crypto.subtle,'encrypt').mockImplementationOnce(async(...args)=>{entered();await gate;return encrypt(...args);});
  try{
    const stale=other.putPreparationState(f.saved).then(()=>true,()=>false);
    await started;
    await f.store.continueEmptyProfilePreparation(f.saved);
    release();expect(await stale).toBe(false);
    expect(await f.store.getPreparationState()).toMatchObject({schemaVersion:7,sessionId:f.saved.sessionId});
    expect(await f.get('metadata',`empty-profile-preparation:${f.saved.sessionId}`)).toBeDefined();
  }finally{release();other.close();f.close();}
});
