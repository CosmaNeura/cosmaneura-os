import {beforeEach,afterEach,expect,it,vi} from 'vitest';
import {DraftJournal,editorAddress,type EditorDraft} from './draft-journal';
import {memoryDraftStorage} from './draft-test-fixture';
import {emptyMembershipRecovery,withMembershipCommand,validateMembershipRecovery} from './membership-recovery';
import {process,membershipFixtureScope as scope,membershipHistoryOperations} from './membership-test-fixture';
import {validateMembership} from './membership-contract';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
beforeEach(()=>vi.stubGlobal('crypto',webcrypto));afterEach(()=>vi.unstubAllGlobals());

it('retains exact membership commands and full local history across journal reopen without altering older namespaces',async()=>{
 const factory=memoryDraftStorage(),options={scope:'a'.repeat(64)},address=editorAddress(scope.workspace_id,'membership-work'),history=validateMembership('History',process.history),ops=await membershipHistoryOperations(history);let data=emptyMembershipRecovery(scope);
 for(let i=0;i<3;i++){data=withMembershipCommand(data,ops[i]);data.receipt=history.items[i].receipt;}data=withMembershipCommand(data,ops[3]);data.draft.result_evidence='Unsent edited text';
 const draft:EditorDraft={kind:'editor',editor:'membership-work',workspaceId:scope.workspace_id,pending:null,data},journal=new DraftJournal(await factory(options));
 const oldAddress=editorAddress(scope.workspace_id,'private-note'),old:EditorDraft={kind:'editor',editor:'private-note',workspaceId:scope.workspace_id,pending:null,data:{text:'Existing note'}};
 await journal.load(oldAddress);await journal.persist(oldAddress,old);await journal.load(address);await journal.persist(address,draft);journal.close();
 const reopened=new DraftJournal(await factory(options));expect(await reopened.load(address)).toEqual(draft);expect(await reopened.load(oldAddress)).toEqual(old);
 const altered=structuredClone(data);altered.pending!.request_sha256='f'.repeat(64);await expect(reopened.persist(address,{...draft,data:altered})).rejects.toMatchObject({code:'integrity'});
 await expect(reopened.persist(address,{...draft,data:{...data,scope:{...scope,workspace_id:crypto.randomUUID()}}})).rejects.toMatchObject({code:'integrity'});
 await expect(reopened.persist(address,{...draft,data:{...data,consent_restored:true}})).rejects.toMatchObject({code:'integrity'});
 await expect(reopened.persist(address,{...draft,pending:crypto.randomUUID()})).rejects.toMatchObject({code:'integrity'});
 expect(await reopened.load(address)).toEqual(draft);reopened.close();
});
it('binds journal membership owner/box to fresh mount authority and rejects another stored scope',async()=>{
 const data=emptyMembershipRecovery(scope);
 await expect(validateMembershipRecovery(data,{...scope,owner_id:crypto.randomUUID()})).rejects.toThrow();
 await expect(validateMembershipRecovery(data,{...scope,box_id:crypto.randomUUID()})).rejects.toThrow();
});
