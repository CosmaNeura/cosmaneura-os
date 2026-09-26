import {beforeEach,afterEach,expect,it,vi} from 'vitest';
import {DraftJournal,accountEditorAddress,type AccountEditorDraft} from './draft-journal';
import {memoryDraftStorage} from './draft-test-fixture';
import {emptyVendorSetupRecovery,validateVendorSetupRecovery} from './vendor-setup-recovery';
import {setupFixture,setupScope} from './vendor-setup-test-fixture';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');beforeEach(()=>vi.stubGlobal('crypto',webcrypto));afterEach(()=>vi.unstubAllGlobals());
it('reopens an exact pending activation and retains its earlier full proposal/proof after invalid writes',async()=>{
 const f=await setupFixture(),factory=memoryDraftStorage(),address=accountEditorAddress('vendor-setup'),record={...emptyVendorSetupRecovery(setupScope),pending:f.activateOp,commands:[{operation:f.accountOp,receipt:f.accountReceipt}]};
 const draft:AccountEditorDraft={kind:'account-editor',editor:'vendor-setup',pending:null,data:record};const journal=new DraftJournal(await factory({scope:'8'.repeat(64)}));await journal.load(address);await journal.persist(address,draft);journal.close();
 const reopened=new DraftJournal(await factory({scope:'8'.repeat(64)}));expect(await reopened.load(address)).toEqual(draft);
 for(const data of [{...record,pending:{...f.activateOp,request:{...f.activateOp.request,reviewed_sender:false}}},{...record,activation_checks:[true,true]},{...record,commands:[...record.commands,...record.commands]}])await expect(reopened.persist(address,{...draft,data})).rejects.toMatchObject({code:'integrity'});
 await expect(reopened.persist(address,{...draft,pending:f.accountReview.setup_id})).rejects.toMatchObject({code:'integrity'});expect(await reopened.load(address)).toEqual(draft);reopened.close();
});
it('withholds the exact account namespace across encrypted-owner scopes and rejects unrelated editor namespaces',async()=>{
 const factory=memoryDraftStorage(),address=accountEditorAddress('vendor-setup'),record=emptyVendorSetupRecovery(setupScope),draft:AccountEditorDraft={kind:'account-editor',editor:'vendor-setup',pending:null,data:record};const journal=new DraftJournal(await factory({scope:'9'.repeat(64)}));await journal.load(address);await journal.persist(address,draft);
 await expect(validateVendorSetupRecovery(record,{...setupScope,owner_id:setupScope.box_id})).rejects.toThrow();await journal.load(accountEditorAddress('finance-setup'));await expect(journal.persist(accountEditorAddress('finance-setup'),draft)).rejects.toMatchObject({code:'integrity'});
 const foreign=new DraftJournal(await factory({scope:'a'.repeat(64)}));expect(await foreign.load(address)).toBeNull();expect(await journal.load(address)).toEqual(draft);journal.close();foreign.close();
});
it('preserves the first writer’s whole exact receipt on a competing stale journal write',async()=>{
 const f=await setupFixture(),factory=memoryDraftStorage(),options={scope:'7'.repeat(64)},address=accountEditorAddress('vendor-setup'),first=new DraftJournal(await factory(options)),second=new DraftJournal(await factory(options));await first.load(address);await second.load(address);
 const data={...emptyVendorSetupRecovery(setupScope),pending:f.accountOp,receipt:f.accountReceipt},draft:AccountEditorDraft={kind:'account-editor',editor:'vendor-setup',pending:null,data};await first.persist(address,draft);await expect(second.persist(address,{...draft,data:{...data,receipt:null}})).rejects.toMatchObject({code:'conflict'});expect(await second.load(address)).toEqual(draft);first.close();second.close();
});
