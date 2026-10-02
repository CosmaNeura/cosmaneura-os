import type {Workspace} from './workspace-api';
import type {HandoffReviewInput,HandoffReviewReceipt,HandoffRevisionInput} from './handoff-review-api';
import {handoffReviewHash} from './handoff-review-api';
import {handoffRecoveryAnchor,handoffRevisionHash,type HandoffReviewRecovery} from './handoff-review-recovery';
import {vendorSha256} from './vendor-contract';
export const reviewUuid=(n:number)=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
export const reviewTime='2026-10-02T14:00:00Z';
export const reviewIdentity={mode:'clerk_jwt' as const,getToken:async()=> 'invented-review-token'};
export async function reviewWorkspace():Promise<Workspace>{
  const content='Invented Shawn visit, DOB unavailable. Prepare draft follow-up; clinician must confirm medicines. Café detail is invented.';
  const hash=await vendorSha256(new TextEncoder().encode(content)),attempt=reviewUuid(4),entry=reviewUuid(5);
  return {id:reviewUuid(1),appointment_id:reviewUuid(2),label:'Invented visit without DOB',revision:3,model_contract_version:1,model_observed_at:reviewTime,
    entries:[{id:entry,revision:3,kind:'handoff_result',content:'Saved private result',source_label:null,origin:'human',ticket:null,created_at:reviewTime,
      reply:{agent_name:'Follow-up',agent_id:reviewUuid(9),role:'follow_up',backend:'synthetic-wire',context_revision:1,content,citations:[]}}],work_candidates:[],
    handoffs:[{id:reviewUuid(3),origin_entry_id:reviewUuid(6),recipient_role:'follow_up',recipient_name:'Follow-up',recipient_agent_id:reviewUuid(9),brief:'Prepare draft',
      context_revision:1,status:'completed',attempt_id:attempt,attempt_count:1,result_entry_id:entry,result_sha256:hash,error_code:null,
      attempts:[{id:attempt,number:1,status:'completed',error_code:null}]}]};
}
export async function reviewRecord(w:Workspace,kind:'feedback'|'review'|'revision'='review'):Promise<HandoffReviewRecovery>{
  const h=w.handoffs![0],anchor=handoffRecoveryAnchor(w,h)!,feedback='Please add a clinician owner and due date. Café fact is invented.';
  if(kind==='feedback')return {...anchor,version:1,feedback,asking_changes:true,pending:null};
  if(kind==='review'){
    const body:HandoffReviewInput={expected_revision:w.revision,idempotency_key:reviewUuid(20),attempt_id:h.attempt_id,result_entry_id:h.result_entry_id!,
      result_sha256:h.result_sha256!,decision:'changes_requested',feedback};
    return {...anchor,version:1,feedback,asking_changes:true,pending:{kind,body,request_sha256:await handoffReviewHash(w.id,h.id,body)}};
  }
  const review:HandoffReviewReceipt={id:reviewUuid(21),attempt_id:h.attempt_id,result_entry_id:h.result_entry_id!,result_sha256:h.result_sha256!,
    decision:'changes_requested',feedback,created_at:reviewTime};
  const body:HandoffRevisionInput={expected_revision:w.revision,idempotency_key:reviewUuid(22),review_id:review.id};
  return {...anchor,version:1,feedback,asking_changes:false,pending:{kind,body,request_sha256:await handoffRevisionHash(w.id,h.id,body),review}};
}
export async function reviewReply(w:Workspace,body:HandoffReviewInput){
  const h=w.handoffs![0],review:HandoffReviewReceipt={id:reviewUuid(21),attempt_id:body.attempt_id,result_entry_id:body.result_entry_id,result_sha256:body.result_sha256,
    decision:body.decision,feedback:body.feedback,created_at:reviewTime};
  return {entry_revision:body.expected_revision+1,request_sha256:await handoffReviewHash(w.id,h.id,body),feedback_withheld:false,
    workspace:{...w,revision:Math.max(w.revision,body.expected_revision+1),handoffs:[{...h,review,review_status:'current' as const}]}};
}
export function unavailableReviewWorkspace(w:Workspace):Workspace{
  return {...w,entries:w.entries.map(e=>({...e,reply:null,content:'',google_source_state:'unavailable' as const})),
    handoffs:w.handoffs!.map(h=>({...h,review_status:'stale' as const,...(h.review?{review:{...h.review,feedback:'Email access must be checked before viewing this feedback.'}}:{})}))};
}
