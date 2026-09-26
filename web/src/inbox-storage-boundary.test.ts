import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
import type {SecureQueuePlugin,VersionedSecureQueueRecord} from '../../clients/capture/plugins/secure-queue/definitions';
import {openDraftStore} from './draft-store';
import {DraftJournal,accountEditorAddress,type AccountEditorDraft} from './draft-journal';
import {emptyInboxDraft,emptyInboxRecovery,validateInboxRecovery} from './inbox-recovery';
import {inboxFixtureScope} from './inbox-test-fixture';
import {emptyInboxHandoffRecovery,validateInboxHandoffRecovery} from './inbox-handoff-recovery';
import {inboxHandoffActor as actor} from './inbox-handoff-test-fixture';
import {vendorBytes} from './vendor-contract';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const MAX=131072;
let idb:IDBFactory;
beforeEach(()=>{vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);idb=new IDBFactory();});
afterEach(()=>vi.unstubAllGlobals());
async function fullRecord(editor:'inbox-work'|'inbox-handoffs'){
  if(editor==='inbox-work'){
    const record=emptyInboxRecovery(inboxFixtureScope);
    record.drafts=Array.from({length:100},()=>emptyInboxDraft(crypto.randomUUID(),null,null));
    for(const draft of record.drafts)draft.instructions='x'.repeat(Math.min(2000,MAX-vendorBytes(record)));
    expect(vendorBytes(record)).toBe(MAX);return validateInboxRecovery(record,inboxFixtureScope);
  }
  const record=emptyInboxHandoffRecovery(actor);
  record.drafts=Array.from({length:100},()=>({kind:'ticket',ticket_id:crypto.randomUUID(),owner_id:actor.actor_id,source_item_id:null,recipient_id:'',evidence:''}));
  for(const draft of record.drafts)if(draft.kind==='ticket')draft.evidence='x'.repeat(Math.min(2000,MAX-vendorBytes(record)));
  expect(vendorBytes(record)).toBe(MAX);return validateInboxHandoffRecovery(record,actor);
}
function nativeSeam(){
  const records=new Map<string,VersionedSecureQueueRecord>();
  const missing=()=>Object.assign(Error('Missing invented record'),{code:'SECURE_QUEUE_NOT_FOUND'});
  const conflict=()=>Object.assign(Error('Conflicting invented record'),{code:'SECURE_QUEUE_REVISION_CONFLICT'});
  const plugin:Pick<SecureQueuePlugin,'get'|'create'|'compareAndSwap'>={
    get:vi.fn(async({key})=>{const value=records.get(key);if(!value)throw missing();return structuredClone(value);}),
    create:vi.fn(async value=>{if(records.has(value.key))throw conflict();records.set(value.key,{...value,revision:'1'});return {revision:'1'};}),
    compareAndSwap:vi.fn(async value=>{const old=records.get(value.key);if(!old||old.revision!==value.expectedRevision)throw conflict();const revision=String(BigInt(old.revision)+1n);records.set(value.key,{key:value.key,data:value.data,revision});return {revision};}),
  };
  return {records,plugin};
}
for(const native of [false,true])for(const editor of ['inbox-work','inbox-handoffs'] as const){
  it(`retains a full128KiB ${editor} body with its value/frame wrappers in ${native?'native bridge seam':'real AES-GCM browser storage'}`,async()=>{
    const data=await fullRecord(editor),address=accountEditorAddress(editor),{records,plugin}=nativeSeam();
    const options={scope:'a'.repeat(64),native,indexedDB:idb,crypto:webcrypto,...(native?{plugin}:{})};
    const store=await openDraftStore(options),journal=new DraftJournal(store);await journal.load(address);
    const value:AccountEditorDraft={kind:'account-editor',editor,pending:null,data};await journal.persist(address,value);
    const sealed=await store.read(address);expect(vendorBytes(sealed.value)).toBeGreaterThan(MAX);expect(vendorBytes(sealed.value)).toBeLessThanOrEqual(MAX+512);
    const revision=sealed.revision;
    if(native){expect(records.size).toBe(1);expect(atob([...records.values()][0].data).length).toBeLessThanOrEqual(MAX+1024);}
    journal.close();
    const second=new DraftJournal(await openDraftStore(options));expect(await second.load(address)).toEqual(value);
    const invalid=structuredClone(value);
    const last=(invalid.data as typeof data).drafts.at(-1)!;
    if('instructions'in last)last.instructions+='x';else if(last.kind==='ticket')last.evidence+='x';
    expect(vendorBytes(invalid.data)).toBe(MAX+1);
    await expect(second.persist(address,invalid)).rejects.toMatchObject({code:'integrity'});second.close();
    const third=await openDraftStore(options);expect(await third.read(address)).toEqual({...sealed,revision});third.close();
  });
}
