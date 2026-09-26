import {expect,it} from 'vitest';
import {DraftJournal,editorAddress,type EditorDraft} from './draft-journal';
import {memoryDraftStorage} from './draft-test-fixture';
import {emptyPortalWorkRecovery,validatePortalWorkPending,verifyPortalWorkSaved,withPortalWorkCommand,type PortalWorkPending} from './portal-work-recovery';
import {validatePortalWorkOperation,verifyPortalWorkReceipt} from './portal-work-contract';
import {validateVendor,vendorDigest} from './vendor-contract';
import actual from './__fixtures__/portal-work/actual-portal-work.json';

it('reopens exact portal approval history and pending upload in the owner journal',async()=>{
 const factory=memoryDraftStorage(),options={scope:'8'.repeat(64)},wid=actual.workspace_id;
 const pending:PortalWorkPending={lane:'portal_work',operation:await validatePortalWorkOperation(actual.operations[1])};
 const first:PortalWorkPending={lane:'portal_work',operation:await validatePortalWorkOperation(actual.operations[0])};
 const receipt=await verifyPortalWorkReceipt(actual.receipts[0],first.operation);
 const data={...emptyPortalWorkRecovery({kind:'workspace',id:wid}),pending,history:[{pending:first,receipt}]};
 const draft:EditorDraft={kind:'editor',workspaceId:wid,editor:'portal-work',pending:null,data};
 const address=editorAddress(wid,'portal-work'),journal=new DraftJournal(await factory(options));
 await journal.load(address);await journal.persist(address,draft);journal.close();
 const reopened=new DraftJournal(await factory(options));expect(await reopened.load(address)).toEqual(draft);
 const altered=structuredClone(data);
 if (!('payload_hash' in altered.pending.operation.request)) throw new Error('Expected exact bound approval');
 altered.pending.operation.request.payload_hash='f'.repeat(64);
 await expect(reopened.persist(address,{...draft,data:altered})).rejects.toMatchObject({code:'integrity'});
 await expect(reopened.persist(address,{...draft,data:{...data,scope:{kind:'workspace',id:crypto.randomUUID()}}})).rejects.toMatchObject({code:'integrity'});
 await expect(reopened.persist(address,{...draft,data:{...data,approval_restored:true}})).rejects.toMatchObject({code:'integrity'});
 expect(await reopened.load(address)).toEqual(draft);reopened.close();
});

it('reopens the exact retired PDF request and proof in history without dropping admitted custody',async()=>{
 const factory=memoryDraftStorage(),options={scope:'7'.repeat(64)},wid=actual.workspace_id,scope={kind:'workspace' as const,id:wid};
 const first=await validatePortalWorkPending({lane:'artifact',operation:actual.custody.operations[0]},scope),pending=await validatePortalWorkPending({lane:'artifact',operation:actual.custody.operations[1]},scope),op=pending.operation;
 const binding={scope,command_kind:op.kind,idempotency_key:op.request.idempotency_key,request_sha256:op.request_sha256},retirement={receipt_id:crypto.randomUUID(),retired_at:actual.custody.intent_response.observed_at};
 const proof=validateVendor('PreparationArtifactRetirementResponse',{contract_version:1,...binding,outcome:'retired',artifact:null,effect:null,retirement:{...retirement,receipt_sha256:await vendorDigest('cosmas-vendor-public-preparation-retirement.v1',{...binding,retirement})},observed_at:retirement.retired_at});
 const settled={...emptyPortalWorkRecovery(scope),pending,receipt:proof,artifact:validateVendor('ArtifactMetadata',actual.custody.intent_response.artifact),history:[{pending:first,receipt:await verifyPortalWorkSaved(first,actual.custody.intent_response)}]};
 const data=withPortalWorkCommand(settled,{lane:'portal_work',operation:await validatePortalWorkOperation(actual.operations[0])});
 const draft:EditorDraft={kind:'editor',workspaceId:wid,editor:'portal-work',pending:null,data},address=editorAddress(wid,'portal-work'),journal=new DraftJournal(await factory(options));
 await journal.load(address);await journal.persist(address,draft);journal.close();
 const reopened=new DraftJournal(await factory(options));expect(await reopened.load(address)).toEqual(draft);expect(data.history.at(-1)).toEqual({pending,receipt:proof});expect(data.artifact).toEqual(settled.artifact);
 const altered=structuredClone(data);altered.history[1].pending.operation.request.idempotency_key='different-exact-request';
 await expect(reopened.persist(address,{...draft,data:altered})).rejects.toMatchObject({code:'integrity'});expect(await reopened.load(address)).toEqual(draft);reopened.close();
});
