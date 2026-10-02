import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
import {DraftJournal,editorAddress, type EditorDraft} from './draft-journal';
import {openDraftStore} from './draft-store';
import {validateHandoffReviewRecovery,handoffRecoveryMatches} from './handoff-review-recovery';
import {reviewUuid,reviewRecord,reviewWorkspace} from './handoff-review-recovery-fixture';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
beforeEach(()=>{vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);});
afterEach(()=>vi.unstubAllGlobals());
it.each(['feedback','review','revision'] as const)('round trips %s through actual AES-GCM store with account/address isolation',async kind=>{
  const w=await reviewWorkspace(),data=await reviewRecord(w,kind),idb=new IDBFactory(),scope='a'.repeat(64),editor=`handoff-review:${w.handoffs![0].id}` as const,address=editorAddress(w.id,editor);
  const options={scope,native:false,indexedDB:idb,crypto:webcrypto},store=await openDraftStore(options),journal=new DraftJournal(store);
  const draft:EditorDraft={kind:'editor',workspaceId:w.id,editor,data,pending:data.pending?.body.idempotency_key??null};
  await journal.load(address);await journal.persist(address,draft);
  const db=await new Promise<IDBDatabase>((resolve,reject)=>{const request=idb.open(`cosmas-private-drafts:v1:${scope}`);request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);});
  const sealed=await new Promise<unknown[]>((resolve,reject)=>{const request=db.transaction('sealed-drafts').objectStore('sealed-drafts').getAll();request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);});
  expect(sealed).toHaveLength(1);expect(JSON.stringify(sealed)).not.toContain(data.feedback);expect(JSON.stringify(sealed)).not.toContain('invented-review-token');
  expect(sealed[0]).toMatchObject({address,nonce:expect.any(Uint8Array),ciphertext:expect.any(ArrayBuffer)});db.close();journal.close();
  const reopened=new DraftJournal(await openDraftStore(options));expect(await reopened.load(address)).toEqual(draft);
  await expect(reopened.load(editorAddress(reviewUuid(777),editor))).resolves.toBeNull();reopened.close();
  const other=new DraftJournal(await openDraftStore({...options,scope:'b'.repeat(64)}));expect(await other.load(address)).toBeNull();other.close();
});
it('rejects altered command/hash/encounter authority and arbitrary or excessive store address records',async()=>{
  const w=await reviewWorkspace(),record=await reviewRecord(w),pending=record.pending!;
  if(pending.kind!=='review')throw new Error('Wrong fixture');
  const changed=[{...record,workspace_id:reviewUuid(88)},{...record,handoff_id:reviewUuid(89)},{...record,appointment_id:'guessed-patient'},
    {...record,authorization:'must-not-store'},{...record,feedback:'x'.repeat(2001)},
    {...record,pending:{...pending,body:{...pending.body,feedback:'Altered body'}}},
    {...record,pending:{...pending,body:{...pending.body,expected_revision:pending.body.expected_revision+1}}},
    {...record,pending:{...pending,body:{...pending.body,result_sha256:'f'.repeat(64)}}}];
  for(const item of changed)await expect(validateHandoffReviewRecovery(item,w.id,w.handoffs![0].id)).rejects.toMatchObject({code:'integrity'});
  const store=await openDraftStore({scope:'d'.repeat(64),native:false,indexedDB:new IDBFactory(),crypto:webcrypto});
  for(const address of [`editor:${w.id}:handoff-review:arbitrary`,`editor:${w.id}:handoff-review:${w.handoffs![0].id}:extra`])await expect(store.read(address)).rejects.toMatchObject({code:'invalid'});
  const address=editorAddress(w.id,`handoff-review:${w.handoffs![0].id}`);
  await expect(store.write(address,null,{schema:1,updatedAt:new Date().toISOString(),body:{value:'x'.repeat(34000)}})).rejects.toMatchObject({code:'invalid'});
  expect(await store.read(address)).toEqual({revision:null,value:null});store.close();
});
it('keeps feedback on its exact original result instead of adopting a newer attempt or visit',async()=>{
 const w=await reviewWorkspace(),record=await reviewRecord(w,'feedback');expect(handoffRecoveryMatches(record,w,w.handoffs![0])).toBe(true);
 expect(handoffRecoveryMatches(record,{...w,appointment_id:reviewUuid(90)},w.handoffs![0])).toBe(false);
 expect(handoffRecoveryMatches(record,w,{...w.handoffs![0],attempt_id:reviewUuid(91)})).toBe(false);
 const r=await reviewRecord(w,'revision');if(r.pending?.kind!=='revision')throw new Error('Wrong fixture');
 await expect(validateHandoffReviewRecovery({...r,pending:{...r.pending,review:{...r.pending.review,result_sha256:'f'.repeat(64)}}},w.id,w.handoffs![0].id)).rejects.toMatchObject({code:'integrity'});
});
