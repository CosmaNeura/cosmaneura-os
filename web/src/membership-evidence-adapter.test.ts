import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {membershipEvidenceAdapter} from './membership-evidence-adapter';
import {DraftJournal,editorAddress} from './draft-journal';
import {editorDraft,type EditorRecoveryAccess} from './editor-recovery';
import {memoryDraftStorage} from './draft-test-fixture';
import {emptyVendorRecovery} from './vendor-recovery';
import {emptyPortalWorkRecovery} from './portal-work-recovery';
import {emptyFinanceRecovery} from './finance-recovery';
import {validateVendorOperation,verifyOperationReceipt} from './vendor-operation';
import {prepareFinanceOperation} from './finance-operation';
import {validateFinance} from './finance-contract';
import {validateVendor} from './vendor-contract';
import {membershipApi} from './membership-api';
import {vendorApi} from './vendor-api';
import {financeApi} from './finance-api';
import {membershipFixtureScope,http} from './membership-test-fixture';
import {processR3} from './finance-test-fixture';
import portal from './__fixtures__/portal-work/actual-portal-work.json';
import {WorkspaceApiError} from './workspace-api';
import type {Scope} from './membership-schema';
import {validateMembership} from './membership-contract';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const journals:DraftJournal[]=[];
beforeEach(()=>{vi.stubGlobal('crypto',webcrypto);vi.spyOn(vendorApi,'execute');vi.spyOn(vendorApi,'upload');vi.spyOn(financeApi,'execute');});
afterEach(()=>{journals.splice(0).forEach(j=>j.close());vi.restoreAllMocks();vi.unstubAllGlobals();vi.useRealTimers();});
async function setup(scope:Scope){const journal=new DraftJournal(await memoryDraftStorage()({scope:'c'.repeat(64)}));journals.push(journal);let current=true;const context:EditorRecoveryAccess={journal,workspaceId:scope.workspace_id,authorize:vi.fn(async()=>({id:scope.workspace_id,appointment_id:scope.workspace_id,label:'Invented private workspace',revision:1,entries:[],work_candidates:[]})),denied:vi.fn()};return {journal,context,close:()=>{current=false;},access:membershipEvidenceAdapter({boxId:scope.box_id,actorId:scope.owner_id},scope,context,()=>current)};}
async function custody(kind:'vendor-work'|'portal-work'='vendor-work'){
 const scope={box_id:portal.identity.boxId,owner_id:portal.identity.actorId,workspace_id:portal.workspace_id},s=await setup(scope),op=await validateVendorOperation(portal.custody.operations[1]),receipt=await verifyOperationReceipt(op,portal.custody.responses[1]),artifact=validateVendor('ArtifactMetadata',portal.artifact);
 if(!('artifact'in receipt))throw Error('Expected artifact fixture');
 const data=kind==='vendor-work'?{...emptyVendorRecovery(op.scope),artifact,artifact_write:op,pending:op,receipt}:{...emptyPortalWorkRecovery({kind:'workspace',id:scope.workspace_id}),artifact,pending:{lane:'artifact' as const,operation:op},receipt};
 await s.journal.load(editorAddress(scope.workspace_id,kind));await s.journal.persist(editorAddress(scope.workspace_id,kind),editorDraft(scope.workspace_id,kind,data));
 vi.spyOn(membershipApi,'options').mockResolvedValue(validateMembership('Options',{...http.options,scope,source:artifact.source}));vi.spyOn(vendorApi,'recover').mockResolvedValue(receipt);const bytes=Uint8Array.from(atob(portal.custody.pdf_base64),c=>c.charCodeAt(0));vi.spyOn(vendorApi,'preview').mockResolvedValue(bytes);
 return {...s,scope,op,receipt,artifact,bytes};
}
describe('membership evidence adapter over actual retained custody and finance records',()=>{
 it.each(['vendor-work','portal-work'] as const)('resolves current artifact metadata from the %s journal without sending or changing its record',async kind=>{
  const s=await custody(kind),address=editorAddress(s.scope.workspace_id,kind),before=await s.journal.load(address),result=await s.access.load(s.scope);expect(result.documents[0].metadata).toEqual(s.artifact);expect(result.finance).toEqual([]);expect(vendorApi.recover).toHaveBeenCalledWith(expect.anything(),s.op,expect.any(AbortSignal));expect(await s.journal.load(address)).toEqual(before);expect(vendorApi.execute).not.toHaveBeenCalled();expect(vendorApi.upload).not.toHaveBeenCalled();expect(financeApi.execute).not.toHaveBeenCalled();
 });
 it('requires a locally retained exact document goal and checks all bytes before preview disclosure',async()=>{const s=await custody();expect(await s.access.preview(s.scope,s.artifact.document)).toEqual(s.bytes);await expect(s.access.preview(s.scope,{...s.artifact.document,artifact_id:crypto.randomUUID()})).rejects.toMatchObject({status:409});expect(vendorApi.preview).toHaveBeenCalledTimes(1);vi.mocked(vendorApi.preview).mockResolvedValueOnce(new Uint8Array(s.bytes.length));await expect(s.access.preview(s.scope,s.artifact.document)).rejects.toThrow();});
 it.each(['source','quarantined','not_found'])('withholds %s artifact choices and never uploads',async kind=>{const s=await custody();if(kind==='source')vi.mocked(membershipApi.options).mockResolvedValue(validateMembership('Options',{...http.options,scope:s.scope,source:{...s.artifact.source,note_id:crypto.randomUUID()}}));else if(kind==='quarantined'){const r=structuredClone(s.receipt);if(!r.artifact)throw Error('fixture');r.artifact.state='quarantined';vi.mocked(vendorApi.recover).mockResolvedValue(r);}else vi.mocked(vendorApi.recover).mockResolvedValue({...s.receipt,outcome:'not_found',effect:null,artifact:null});expect((await s.access.load(s.scope)).documents).toEqual([]);expect(vendorApi.upload).not.toHaveBeenCalled();});
 it.each(['scope','denied','late'])('fails closed for %s authority before private evidence disclosure',async kind=>{const s=await custody();if(kind==='scope'){await expect(s.access.load({...s.scope,owner_id:crypto.randomUUID()})).rejects.toMatchObject({status:403});expect(s.context.authorize).not.toHaveBeenCalled();}else if(kind==='denied'){vi.mocked(s.context.authorize).mockRejectedValue(new WorkspaceApiError(403));await expect(s.access.load(s.scope)).rejects.toMatchObject({status:403});}else{vi.mocked(vendorApi.recover).mockImplementation(async()=>{s.close();return s.receipt;});await expect(s.access.load(s.scope)).rejects.toMatchObject({status:403});}expect(vendorApi.preview).not.toHaveBeenCalled();});
 it('offers only the retained exact finance verify pair and freshly checks current detail',async()=>{
  const detail=validateFinance('FinanceDetail',processR3.verified_detail),scope={...membershipFixtureScope,workspace_id:detail.workspace_id},s=await setup(scope),c=processR3.commands.find(c=>c.kind==='verify')!,op=await prepareFinanceOperation({kind:'workspace',id:scope.workspace_id},'verify',detail.summary.ticket_id,validateFinance('FinanceVerify',c.request)),receipt=validateFinance('FinanceResponse',c.response),address=editorAddress(scope.workspace_id,'finance-work');
  await s.journal.load(address);await s.journal.persist(address,editorDraft(scope.workspace_id,'finance-work',{...emptyFinanceRecovery(op.scope),pending:op,receipt}));vi.spyOn(membershipApi,'options').mockResolvedValue(validateMembership('Options',{...http.options,scope,source:detail.review.source}));vi.spyOn(financeApi,'detail').mockResolvedValue(detail);
  expect((await s.access.load(scope)).finance).toEqual([{operation:op,receipt}]);expect(financeApi.detail).not.toHaveBeenCalled();expect(await s.access.financeDetail(scope,detail.summary.ticket_id)).toEqual(detail);expect(financeApi.execute).not.toHaveBeenCalled();
  const historical={...emptyFinanceRecovery(op.scope),receipts:[receipt]};await s.journal.persist(address,editorDraft(scope.workspace_id,'finance-work',historical));expect((await s.access.load(scope)).finance).toEqual([]);await expect(s.access.financeDetail(scope,detail.summary.ticket_id)).rejects.toMatchObject({status:409});expect(financeApi.detail).toHaveBeenCalledTimes(1);
 });
 it('ends a blocked authorization within the whole30s evidence budget without starting API reads',async()=>{const s=await custody();vi.mocked(s.context.authorize).mockImplementation(()=>new Promise(()=>{}));vi.useFakeTimers();const request=expect(s.access.load(s.scope)).rejects.toMatchObject({status:503});await vi.advanceTimersByTimeAsync(30001);await request;expect(membershipApi.options).not.toHaveBeenCalled();expect(vendorApi.recover).not.toHaveBeenCalled();});
});
