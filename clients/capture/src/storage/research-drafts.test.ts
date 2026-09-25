import {webcrypto} from 'node:crypto';
import {IDBFactory} from 'fake-indexeddb';
import {expect,it} from 'vitest';
import {openDraftStore,type DraftValue} from '../../../../web/src/draft-store';
const crypto=webcrypto as unknown as Crypto;
const address='editor:00000000-0000-4000-8000-000000000071:research:00000000-0000-4000-8000-000000000072';
const value:DraftValue={schema:1,updatedAt:'2026-09-22T18:00:00Z',body:{version:1,query:'Invented private retained query',pending:{idempotency_key:'00000000-0000-4000-8000-000000000074'}}};
it('uses existing sealed IndexedDB custody, scoped UUID address and compare-and-swap recovery for Research',async()=>{
 const options={scope:'a'.repeat(64),native:false,indexedDB:new IDBFactory(),crypto};const first=await openDraftStore(options),saved=await first.write(address,null,value);first.close();
 const reopened=await openDraftStore(options),stale=await openDraftStore(options);expect(await reopened.read(address)).toEqual(saved);await reopened.write(address,saved.revision,{...value,body:{query:'Second private version'}});await expect(stale.write(address,saved.revision,value)).rejects.toMatchObject({code:'conflict'});
 const foreign=await openDraftStore({...options,scope:'b'.repeat(64)});expect((await foreign.read(address)).value).toBeNull();for(const bad of [address.replace(':research:',':research/'),address.replace(/000000000072$/,'invalid'),address.replace(':research:00000000-0000-4000-8000-000000000072',':research')])await expect(reopened.read(bad)).rejects.toMatchObject({code:'invalid'});reopened.close();stale.close();foreign.close();
});
it('bounds only the new Research record to16KiB without enlarging the existing journal',async()=>{
 const store=await openDraftStore({scope:'c'.repeat(64),native:false,indexedDB:new IDBFactory(),crypto});await expect(store.write(address,null,{...value,body:{text:'x'.repeat(16384)}})).rejects.toMatchObject({code:'invalid'});expect((await store.read(address)).value).toBeNull();store.close();
});
