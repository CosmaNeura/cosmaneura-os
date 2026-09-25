import type {EditorRecoveryAccess} from './editor-recovery';
import {editorAddress} from './draft-journal';
import {DraftStoreError} from './draft-store';
import {WorkspaceApiError,type WorkspaceIdentity} from './workspace-api';
import type {Document,Scope} from './membership-schema';
import {membershipApi} from './membership-api';
import {sameMembershipScope} from './membership-contract';
import {membershipFinanceProof,verifyMembershipEvidenceInventory,type MembershipEvidenceAccess,type MembershipEvidenceInventory} from './membership-evidence';
import {validateVendorRecovery} from './vendor-recovery';
import {validatePortalWorkRecovery} from './portal-work-recovery';
import {validateFinanceRecovery} from './finance-recovery';
import {verifyOperationReceipt,type VendorOperation} from './vendor-operation';
import {vendorApi,requirePdf} from './vendor-api';
import {financeApi} from './finance-api';
import {vendorCanonical} from './vendor-contract';
import type {ArtifactMetadata} from './vendor-schema';

/** Read-only seam over the existing owner-scoped journals and private APIs.
 * It never reconstructs a missing original finance request from a receipt. */
export function membershipEvidenceAdapter(identity:WorkspaceIdentity,scope:Scope,context:EditorRecoveryAccess,isCurrent:()=>boolean):MembershipEvidenceAccess{
 const check=(requested:Scope,signal?:AbortSignal)=>{if(signal?.aborted)throw new WorkspaceApiError(503);if(!isCurrent()||context.workspaceId!==scope.workspace_id||!sameMembershipScope(requested,scope))throw new WorkspaceApiError(403);};
 const bounded=async<T,>(requested:Scope,signal:AbortSignal|undefined,milliseconds:number,work:(signal:AbortSignal)=>Promise<T>):Promise<T>=>{
  check(requested,signal);const controller=new AbortController(),deadline=performance.now()+milliseconds,abort=()=>controller.abort();
  const interrupted=new Promise<never>((_,reject)=>controller.signal.addEventListener('abort',()=>reject(new WorkspaceApiError(503)),{once:true}));void interrupted.catch(()=>{});
  const timer=setTimeout(abort,milliseconds);signal?.addEventListener('abort',abort,{once:true});
  try{const value=await Promise.race([work(controller.signal),interrupted]);if(performance.now()>=deadline)abort();check(requested,controller.signal);return value;}
  finally{clearTimeout(timer);signal?.removeEventListener('abort',abort);controller.abort();}
 };
 const authorize=async(requested:Scope,signal?:AbortSignal)=>{check(requested,signal);const workspace=await context.authorize();check(requested,signal);if(workspace.id!==scope.workspace_id)throw new WorkspaceApiError(403);};
 const read=async(editor:'vendor-work'|'portal-work'|'finance-work',signal?:AbortSignal)=>{check(scope,signal);const d=await context.journal.load(editorAddress(scope.workspace_id,editor));check(scope,signal);if(d&&(d.kind!=='editor'||d.editor!==editor||d.workspaceId!==scope.workspace_id||d.pending!==null))throw new DraftStoreError('integrity');return d?.data??null;};
 const priorScope={kind:'workspace' as const,id:scope.workspace_id};
 async function custody(signal?:AbortSignal){
  const [vendorValue,portalValue]=await Promise.all([read('vendor-work',signal),read('portal-work',signal)]);check(scope,signal);
  const candidates:VendorOperation[]=[];
  if(vendorValue){const v=await validateVendorRecovery(vendorValue,priorScope);if(v.artifact_write)candidates.push(v.artifact_write);if(v.pending?.kind.startsWith('artifact_'))candidates.push(v.pending);}
  if(portalValue){const p=await validatePortalWorkRecovery(portalValue,priorScope);for(const pair of [...p.history,...(p.pending?[{pending:p.pending}]:[])])if(pair.pending.lane==='artifact')candidates.push(pair.pending.operation);}
  const unique=new Map<string,VendorOperation>();for(const op of candidates){if(op.kind!=='artifact_intent'&&op.kind!=='artifact_content')throw new DraftStoreError('integrity');const aid=(op.request as {artifact_id:string}).artifact_id;const previous=unique.get(aid);if(!previous||op.kind==='artifact_content')unique.set(aid,op);}
  if(unique.size>100)throw new DraftStoreError('integrity');
  return unique;
 }
 async function currentArtifact(op:VendorOperation,signal?:AbortSignal):Promise<ArtifactMetadata|null>{
  check(scope,signal);const receipt=await verifyOperationReceipt(op,await vendorApi.recover(identity,op,signal));check(scope,signal);
  if(!('artifact'in receipt))throw new DraftStoreError('integrity');return receipt.outcome==='recorded'&&receipt.artifact?.state==='ready'?receipt.artifact:null;
 }
 const sameDocument=(a:Document,b:Document)=>vendorCanonical(a)===vendorCanonical(b);
 return {
  async load(requested,signal){return bounded(requested,signal,30000,async signal=>{
   await authorize(requested,signal);const options=await membershipApi.options(identity,scope,signal);check(scope,signal);
   const inventory:MembershipEvidenceInventory={scope,documents:[],finance:[]};
   const [operations,financeValue]=await Promise.all([custody(signal),read('finance-work',signal)]);check(scope,signal);
   if(options.source)for(const op of operations.values()){const metadata=await currentArtifact(op,signal);if(metadata&&vendorCanonical(metadata.source)===vendorCanonical(options.source))inventory.documents.push({label:`Private supporting PDF ${inventory.documents.length+1}`,metadata});}
   if(financeValue){const f=await validateFinanceRecovery(financeValue,priorScope);if(f.pending?.kind==='verify'&&f.receipt?.outcome==='recorded')inventory.finance.push({operation:f.pending,receipt:f.receipt});}
   check(scope,signal);if(!options.source)return inventory;
   const result=await verifyMembershipEvidenceInventory(inventory,scope,options.source);check(scope,signal);return result;
   });
  },
  async preview(requested,document,signal){return bounded(requested,signal,60000,async signal=>{
   await authorize(requested,signal);const options=await membershipApi.options(identity,scope,signal);check(scope,signal);const op=(await custody(signal)).get(document.artifact_id);if(!op||!options.source)throw new WorkspaceApiError(409,'artifact_changed');
   const metadata=await currentArtifact(op,signal);if(!metadata||!sameDocument(metadata.document,document)||vendorCanonical(metadata.source)!==vendorCanonical(options.source))throw new WorkspaceApiError(409,'artifact_changed');
   check(scope,signal);const bytes=await vendorApi.preview(identity,scope.workspace_id,document,signal);check(scope,signal);await requirePdf(document,bytes);check(scope,signal);return bytes;
   });
  },
  async financeDetail(requested,ticketId,signal){return bounded(requested,signal,30000,async signal=>{
   await authorize(requested,signal);const value=await read('finance-work',signal);if(!value)throw new WorkspaceApiError(409,'membership_evidence_changed');
   const f=await validateFinanceRecovery(value,priorScope);if(f.pending?.kind!=='verify'||f.pending.target_id!==ticketId||f.receipt?.outcome!=='recorded')throw new WorkspaceApiError(409,'membership_evidence_changed');
   const detail=await financeApi.detail(identity,scope.workspace_id,ticketId,signal);check(scope,signal);await membershipFinanceProof({operation:f.pending,receipt:f.receipt},detail,scope);check(scope,signal);return detail;
   });
  },
 };
}
