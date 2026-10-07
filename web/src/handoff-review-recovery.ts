import {DraftStoreError} from './draft-store';
import {teamClosed,teamHash,teamNatural,teamText,teamUuid} from './team-setup-request';
import {modelCanonical} from './model-work-request';
import {vendorSha256} from './vendor-contract';
import {handoffReviewHash,validHandoffReviewInput,validHandoffRevisionInput,validHandoffReviewReceipt,
  type HandoffReviewInput,type HandoffRevisionInput,type HandoffReviewReceipt} from './handoff-review-api';
import type {DraftHandoff,Workspace} from './workspace-api';

export type HandoffRecoveryAnchor={workspace_id:string;appointment_id:string|null;handoff_id:string;origin_entry_id:string;context_revision:number;
  recipient:{role:DraftHandoff['recipient_role'];name:string;agent_id:string|null;key:string|null};
  result:{attempt_id:string;result_entry_id:string;result_sha256:string}};
export type HandoffRecoveryPending={kind:'review';body:HandoffReviewInput;request_sha256:string}|
  {kind:'revision';body:HandoffRevisionInput;request_sha256:string;review:HandoffReviewReceipt};
export type HandoffReviewRecovery=HandoffRecoveryAnchor&{version:1;feedback:string;asking_changes:boolean;pending:HandoffRecoveryPending|null};
export const handoffRevisionHash=(workspaceId:string,handoffId:string,body:HandoffRevisionInput)=>
  vendorSha256(new TextEncoder().encode(modelCanonical({workspace_id:workspaceId,handoff_id:handoffId,...body})));
const invalid=():never=>{throw new DraftStoreError('integrity');};
const roles=['scribe','visit_prep','follow_up','research','custom'];

/** Account scope is authenticated by the existing encrypted journal. This adds exact encounter/result custody. */
export async function validateHandoffReviewRecovery(value:unknown,workspaceId:string,handoffId:string):Promise<HandoffReviewRecovery>{
  if(!teamClosed(value,'version,workspace_id,appointment_id,handoff_id,origin_entry_id,context_revision,recipient,result,feedback,asking_changes,pending')||
    value.version!==1||value.workspace_id!==workspaceId||value.handoff_id!==handoffId||!teamUuid(value.workspace_id)||value.appointment_id!==null&&!teamUuid(value.appointment_id)||
    !teamUuid(value.handoff_id)||!teamUuid(value.origin_entry_id)||!teamNatural(value.context_revision)||value.context_revision>2147483646||
    !teamClosed(value.recipient,'role,name,agent_id,key')||!roles.includes(String(value.recipient.role))||!teamText(value.recipient.name,40,1)||
    value.recipient.agent_id!==null&&!teamUuid(value.recipient.agent_id)||value.recipient.key!==null&&(!teamText(value.recipient.key,100,1)||value.recipient.key.includes('\0'))||
    !teamClosed(value.result,'attempt_id,result_entry_id,result_sha256')||!teamUuid(value.result.attempt_id)||!teamUuid(value.result.result_entry_id)||!teamHash(value.result.result_sha256)||
    !teamText(value.feedback,2000)||value.feedback.includes('\0')||typeof value.asking_changes!=='boolean')return invalid();
  if(new TextEncoder().encode(modelCanonical(value)).byteLength>32768)return invalid();
  const pending=value.pending;
  if(pending!==null){
    if(!teamClosed(pending,'kind,body,request_sha256',pending&&typeof pending==='object'&&'kind'in pending&&pending.kind==='revision'?'review':'')||!teamHash(pending.request_sha256))return invalid();
    if(pending.kind==='review'){
      if(!validHandoffReviewInput(pending.body)||pending.body.attempt_id!==value.result.attempt_id||pending.body.result_entry_id!==value.result.result_entry_id||
        pending.body.result_sha256!==value.result.result_sha256||pending.body.decision==='changes_requested'&&pending.body.feedback!==value.feedback||
        pending.request_sha256!==await handoffReviewHash(workspaceId,handoffId,pending.body))return invalid();
    }else if(pending.kind==='revision'){
      if(!validHandoffRevisionInput(pending.body)||!validHandoffReviewReceipt(pending.review)||pending.body.review_id!==pending.review.id||
        pending.review.decision!=='changes_requested'||pending.review.attempt_id!==value.result.attempt_id||pending.review.result_entry_id!==value.result.result_entry_id||
        pending.review.result_sha256!==value.result.result_sha256||pending.request_sha256!==await handoffRevisionHash(workspaceId,handoffId,pending.body))return invalid();
    }else return invalid();
  }
  return structuredClone(value) as HandoffReviewRecovery;
}

export function handoffRecoveryAnchor(workspace:Workspace,handoff:DraftHandoff):HandoffRecoveryAnchor|null{
  if(!handoff.result_entry_id||!handoff.result_sha256)return null;
  return {workspace_id:workspace.id,appointment_id:workspace.appointment_id,handoff_id:handoff.id,origin_entry_id:handoff.origin_entry_id,
    context_revision:handoff.context_revision,recipient:{role:handoff.recipient_role,name:handoff.recipient_name,agent_id:handoff.recipient_agent_id??null,key:handoff.recipient_key??null},
    result:{attempt_id:handoff.attempt_id,result_entry_id:handoff.result_entry_id,result_sha256:handoff.result_sha256}};
}

/** A changed draft does not authorize a new decision. Historical exact-command replay remains separate. */
export function handoffRecoveryMatches(record:HandoffRecoveryAnchor,workspace:Workspace,handoff:DraftHandoff):boolean{
  const current=handoffRecoveryAnchor(workspace,handoff);
  const {workspace_id,appointment_id,handoff_id,origin_entry_id,context_revision,recipient,result}=record;
  return current!==null&&modelCanonical({workspace_id,appointment_id,handoff_id,origin_entry_id,context_revision,recipient,result})===modelCanonical(current);
}
