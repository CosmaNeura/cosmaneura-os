import {expect,it} from 'vitest';
import {DraftJournal,accountEditorAddress,type AccountEditorDraft} from './draft-journal';
import {memoryDraftStorage} from './draft-test-fixture';
import {emptyFinanceSetupRecovery,validateFinanceSetupRecovery} from './finance-setup-recovery';
import {setupFixture,setupScope} from './finance-setup-test-fixture';

it('reopens a payment-account activation with its earlier review proof and preserves both on rejected edits',async()=>{
  const f=await setupFixture(),factory=memoryDraftStorage(),address=accountEditorAddress('finance-setup');
  const record={...emptyFinanceSetupRecovery(setupScope),selected_setup_id:f.accountPending.summary.setup_id,
    pending:f.activateOp,commands:[{operation:f.accountOp,receipt:f.accountReceipt}]};
  const draft:AccountEditorDraft={kind:'account-editor',editor:'finance-setup',pending:null,data:record};
  const journal=new DraftJournal(await factory({scope:'8'.repeat(64)}));await journal.load(address);await journal.persist(address,draft);journal.close();
  const reopened=new DraftJournal(await factory({scope:'8'.repeat(64)}));expect(await reopened.load(address)).toEqual(draft);
  const altered={...record,pending:{...record.pending,request:{...record.pending.request,reviewed_account:false}}};
  await expect(reopened.persist(address,{...draft,data:altered})).rejects.toMatchObject({code:'integrity'});
  await expect(reopened.persist(address,{...draft,data:{...record,activation_checks:[true,true,true]}})).rejects.toMatchObject({code:'integrity'});
  expect(await reopened.load(address)).toEqual(draft);reopened.close();
});

it('withholds payment settings across owner and account recovery scopes',async()=>{
  const factory=memoryDraftStorage(),address=accountEditorAddress('finance-setup'),data=emptyFinanceSetupRecovery(setupScope);
  const journal=new DraftJournal(await factory({scope:'9'.repeat(64)}));await journal.load(address);
  await journal.persist(address,{kind:'account-editor',editor:'finance-setup',pending:null,data});
  await expect(validateFinanceSetupRecovery(data,{...setupScope,owner_id:setupScope.box_id})).rejects.toThrow();
  const foreign=new DraftJournal(await factory({scope:'a'.repeat(64)}));expect(await foreign.load(address)).toBeNull();
  journal.close();foreign.close();
});
