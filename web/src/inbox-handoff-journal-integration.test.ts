import {beforeEach,afterEach,it,expect,vi} from 'vitest';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
import {openDraftStore} from './draft-store';
import {DraftJournal,accountEditorAddress,type AccountEditorDraft} from './draft-journal';
import {emptyInboxHandoffRecovery} from './inbox-handoff-recovery';
import {inboxHandoffActor,inboxHandoffFixtureOperation} from './inbox-handoff-test-fixture';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
let idb:IDBFactory;
const address=accountEditorAddress('inbox-handoffs');
const store=(scope='1'.repeat(64))=>openDraftStore({scope,native:false,indexedDB:idb,crypto:webcrypto});
beforeEach(()=>{vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);idb=new IDBFactory();});
afterEach(()=>vi.unstubAllGlobals());
it('retains an exact handoff command in a reopened encrypted actor journal and separates another actor namespace',async()=>{
  const record={...emptyInboxHandoffRecovery(inboxHandoffActor),pending:await inboxHandoffFixtureOperation('decide')};
  const first=new DraftJournal(await store());await first.load(address);await first.persist(address,{kind:'account-editor',editor:'inbox-handoffs',pending:null,data:record});first.close();
  const second=new DraftJournal(await store());expect((await second.load(address) as AccountEditorDraft).data).toEqual(record);second.close();
  const foreign=new DraftJournal(await store('2'.repeat(64)));expect(await foreign.load(address)).toBeNull();foreign.close();
});
it('rejects a different actor or corrupted request before replacing retained handoff proof',async()=>{
  const record={...emptyInboxHandoffRecovery(inboxHandoffActor),pending:await inboxHandoffFixtureOperation('decide')};
  const journal=new DraftJournal(await store());await journal.load(address);await journal.persist(address,{kind:'account-editor',editor:'inbox-handoffs',pending:null,data:record});
  for(const change of ['actor','digest']){
    const invalid=structuredClone(record);
    if(change==='actor')invalid.actor.actor_id=crypto.randomUUID();else invalid.pending.request_sha256='e'.repeat(64);
    await expect(journal.persist(address,{kind:'account-editor',editor:'inbox-handoffs',pending:null,data:invalid})).rejects.toMatchObject({code:'integrity'});
  }
  journal.close();const reader=new DraftJournal(await store());expect((await reader.load(address) as AccountEditorDraft).data).toEqual(record);reader.close();
});
