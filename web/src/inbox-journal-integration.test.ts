import {beforeEach,afterEach,it,expect,vi} from 'vitest';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
import {openDraftStore} from './draft-store';
import {DraftJournal,accountEditorAddress} from './draft-journal';
import {emptyInboxRecovery,emptyInboxDraft} from './inbox-recovery';
import {inboxFixtureOperation,inboxFixtureScope} from './inbox-test-fixture';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
let idb:IDBFactory;
const address=accountEditorAddress('inbox-work'),scope='1'.repeat(64);
const store=()=>openDraftStore({scope,native:false,indexedDB:idb,crypto:webcrypto});
beforeEach(()=>{vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);idb=new IDBFactory();});
afterEach(()=>vi.unstubAllGlobals());
it('reopens the same encrypted Inbox draft and pending command through a fresh store and journal',async()=>{
  const operation=await inboxFixtureOperation(),record={...emptyInboxRecovery(inboxFixtureScope),pending:operation,drafts:[{...emptyInboxDraft(operation.request.item_id,operation.request.source_id!,operation.request.source_sha256!),instructions:'Preserved human review text'}]};
  const first=new DraftJournal(await store());expect(await first.load(address)).toBeNull();await first.persist(address,{kind:'account-editor',editor:'inbox-work',pending:null,data:record});first.close();
  const second=new DraftJournal(await store());expect(await second.load(address)).toEqual({kind:'account-editor',editor:'inbox-work',pending:null,data:record});second.close();
});
it('rejects an altered saved operation before replacing the prior durable Inbox record',async()=>{
  const operation=await inboxFixtureOperation(),record={...emptyInboxRecovery(inboxFixtureScope),pending:operation};
  const journal=new DraftJournal(await store());await journal.load(address);await journal.persist(address,{kind:'account-editor',editor:'inbox-work',pending:null,data:record});
  const changed=structuredClone(record);changed.pending.request_sha256='f'.repeat(64);
  await expect(journal.persist(address,{kind:'account-editor',editor:'inbox-work',pending:null,data:changed})).rejects.toMatchObject({code:'integrity'});journal.close();
  const second=new DraftJournal(await store());expect((await second.load(address))?.kind).toBe('account-editor');expect((await second.load(address) as {data:unknown}).data).toEqual(record);second.close();
});
