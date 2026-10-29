import {WorkspaceApiError, type DraftHandoff, type Workspace, type WorkspaceIdentity} from './workspace-api';
import {workspaceFetch} from './workspace-protocol';
import {assertCurrentDesktopSession, workspaceAuthHeaders} from './workspace-auth-headers';
import {permittedWorkspaceApi} from './workspace-origin';
import {modelCanonical,modelTime, validModelWorkspace, MODEL_WORKSPACE_BYTES} from './model-work-request';
import {teamClosed, teamHash, teamNatural, teamText, teamUuid} from './team-setup-request';
import {parseVendorJson, vendorSha256} from './vendor-contract';

export type HandoffReviewDecision = 'accepted' | 'changes_requested';
export type HandoffReviewInput = {expected_revision:number;idempotency_key:string;attempt_id:string;result_entry_id:string;
  result_sha256:string;decision:HandoffReviewDecision;feedback:string};
export type HandoffReviewReceipt = {id:string;attempt_id:string;result_entry_id:string;result_sha256:string;
  decision:HandoffReviewDecision;feedback:string;created_at:string;revision_handoff_id?:string|null};
export type HandoffRevisionInput = {expected_revision:number;idempotency_key:string;review_id:string};
export type HandoffRevisionResponse = {entry_revision:number;revision_handoff_id:string;workspace:Workspace};
export type HandoffRevisionRequest = {parent_handoff_id:string;review_id:string;attempt_id:string;result_entry_id:string;result_sha256:string;feedback:string};
export type ReviewableHandoff = DraftHandoff & {result_sha256?:string|null;review?:HandoffReviewReceipt|null;revision_request?:HandoffRevisionRequest|null};
export type HandoffReviewResponse = {entry_revision:number;request_sha256:string;feedback_withheld:boolean;workspace:Workspace};
export type VerifiedHandoffResult = {attemptId:string;entryId:string;sha256:string;content:string};
const reviewKey=(value:unknown):value is string=>typeof value==='string'&&/^[A-Za-z0-9:_-]{8,100}$/.test(value);
const REFUSALS=new Set(['workspace_revision_conflict','handoff_result_already_reviewed','handoff_revision_already_requested',
  'handoff_sources_changed','handoff_context_changed','handoff_result_changed','handoff_result_unavailable','handoff_result_unverifiable',
  'handoff_review_stale','handoff_revision_stale','handoff_revision_unverifiable','handoff_revision_limit','handoff_revision_too_large',
  'invalid_handoff_review','invalid_handoff_revision','invalid_model_work_request','model_request_too_large','workspace_history_limit',
  'model_unavailable','team_work_limit','bot_capability_restricted','handoff_source_context_too_large','handoff_source_contract_unavailable']);
export class HandoffReviewRefusal extends WorkspaceApiError {
  constructor(status:number,code:string){super(status,code);this.name='HandoffReviewRefusal';}
}
/** These checks precede any effect for this key, even after a lost response. */
export const refusalProvesNoCommit=(error:HandoffReviewRefusal)=>['workspace_revision_conflict','handoff_result_already_reviewed',
  'handoff_revision_already_requested','invalid_handoff_review','invalid_handoff_revision','invalid_model_work_request','model_request_too_large'].includes(error.code??'');
export const refusalNeedsFreshAssignment=(code:string|undefined)=>['handoff_sources_changed','handoff_context_changed','handoff_result_changed',
  'handoff_result_unavailable','handoff_result_unverifiable','handoff_review_stale','handoff_revision_stale','handoff_revision_unverifiable',
  'handoff_revision_limit','bot_capability_restricted'].includes(code??'');

export function validHandoffReviewInput(value:unknown):value is HandoffReviewInput {
  return teamClosed(value,'expected_revision,idempotency_key,attempt_id,result_entry_id,result_sha256,decision,feedback') &&
    teamNatural(value.expected_revision) && value.expected_revision>0 && value.expected_revision<2147483647 && reviewKey(value.idempotency_key) &&
    teamUuid(value.attempt_id) && teamUuid(value.result_entry_id) && teamHash(value.result_sha256) &&
    (value.decision==='accepted'||value.decision==='changes_requested') && teamText(value.feedback,2000) && !value.feedback.includes('\0') &&
    (value.decision!=='changes_requested'||value.feedback.trim().length>0);
}
export const handoffReviewHash=(workspaceId:string,handoffId:string,body:HandoffReviewInput)=>vendorSha256(new TextEncoder().encode(modelCanonical({
  workspace_id:workspaceId,handoff_id:handoffId,...body,
})));

export function validHandoffReviewReceipt(value:unknown):value is HandoffReviewReceipt {
  return teamClosed(value,'id,attempt_id,result_entry_id,result_sha256,decision,feedback,created_at','revision_handoff_id') && teamUuid(value.id) &&
    teamUuid(value.attempt_id) && teamUuid(value.result_entry_id) && teamHash(value.result_sha256) &&
    (value.decision==='accepted'||value.decision==='changes_requested') && teamText(value.feedback,2000) && !value.feedback.includes('\0') &&
    (value.decision!=='changes_requested'||value.feedback.trim().length>0) && modelTime(value.created_at) &&
    (!('revision_handoff_id' in value)||value.revision_handoff_id===null||value.decision==='changes_requested'&&teamUuid(value.revision_handoff_id));
}

export function validHandoffRevisionInput(value:unknown):value is HandoffRevisionInput {
  return teamClosed(value,'expected_revision,idempotency_key,review_id')&&teamNatural(value.expected_revision)&&value.expected_revision>0&&
    value.expected_revision<2147483647&&reviewKey(value.idempotency_key)&&teamUuid(value.review_id);
}

/** Hash the complete saved reply; missing metadata and shortened previews cannot be reviewed. */
export async function verifiedHandoffResult(workspace:Workspace,handoff:ReviewableHandoff):Promise<VerifiedHandoffResult|null> {
  const current=workspace.handoffs?.find(value=>value.id===handoff.id) as ReviewableHandoff|undefined;
  if(!current||current.status!=='completed'||current.attempt_id!==handoff.attempt_id||current.result_entry_id!==handoff.result_entry_id||
    current.result_sha256!==handoff.result_sha256||!teamUuid(handoff.attempt_id)||!teamUuid(handoff.result_entry_id)||!teamHash(handoff.result_sha256))return null;
  const entry=workspace.entries.find(value=>value.id===handoff.result_entry_id);
  if(!entry||entry.kind!=='handoff_result'||!entry.reply||entry.reply.role!==handoff.recipient_role||
    entry.reply.agent_name!==handoff.recipient_name||handoff.recipient_agent_id&&entry.reply.agent_id!==handoff.recipient_agent_id||
    !teamText(entry.reply.content,200000,1))return null;
  const sha256=await vendorSha256(new TextEncoder().encode(entry.reply.content));
  return sha256===handoff.result_sha256?{attemptId:handoff.attempt_id,entryId:entry.id,sha256,content:entry.reply.content}:null;
}

function currentIdentity(identity:WorkspaceIdentity):void {
  if(!('mode' in identity))return;
  assertCurrentDesktopSession(identity);
  if(identity.mode==='clerk_jwt'&&identity.nativeSession&&!identity.nativeSession.isCurrent())throw new WorkspaceApiError(401);
}

async function exactResponse(value:unknown,workspaceId:string,handoffId:string,body:HandoffReviewInput):Promise<HandoffReviewResponse> {
  if(!teamClosed(value,'entry_revision,request_sha256,feedback_withheld,workspace')||value.entry_revision!==body.expected_revision+1||
    !teamHash(value.request_sha256)||typeof value.feedback_withheld!=='boolean'||value.request_sha256!==await handoffReviewHash(workspaceId,handoffId,body)||
    !await validModelWorkspace(value.workspace,workspaceId))throw new WorkspaceApiError(503);
  const workspace=value.workspace as Workspace;
  if(workspace.revision<Number(value.entry_revision))throw new WorkspaceApiError(503);
  const handoffs=workspace.handoffs;
  if(!Array.isArray(handoffs)||handoffs.filter(h=>h.id===handoffId).length!==1)throw new WorkspaceApiError(503);
  const review=(handoffs.find(h=>h.id===handoffId) as ReviewableHandoff).review;
  if(!validHandoffReviewReceipt(review)||review.attempt_id!==body.attempt_id||review.result_entry_id!==body.result_entry_id||
    review.result_sha256!==body.result_sha256||review.decision!==body.decision)throw new WorkspaceApiError(503);
  const entry=workspace.entries.find(e=>e.id===body.result_entry_id);
  if(!entry||entry.kind!=='handoff_result')throw new WorkspaceApiError(503);
  if(value.feedback_withheld){
    const notice=entry.calendar_import_source_state==='unavailable'?'Check the imported calendar summary before viewing this feedback.':entry.ehr_source_state==='unavailable'?'Check the reviewed EHR appointment before viewing this feedback.':(entry.fax_source_state==='unavailable'||entry.practice_fax_source_state==='unavailable')?'Check the reviewed fax passage before viewing this feedback.':(entry.google_source_state==='unavailable'||entry.microsoft_source_state==='unavailable')&&entry.calendar_source_state!=='unavailable'?'Email access must be checked before viewing this feedback.':'Check the selected calendar summary before viewing this feedback.';
    if((entry.google_source_state!=='unavailable'&&entry.microsoft_source_state!=='unavailable'&&entry.calendar_source_state!=='unavailable'&&entry.fax_source_state!=='unavailable'&&entry.practice_fax_source_state!=='unavailable'&&entry.calendar_import_source_state!=='unavailable'&&entry.ehr_source_state!=='unavailable')||entry.reply!=null||entry.content!==''||handoffs.find(h=>h.id===handoffId)!.review_status!=='stale'||
      review.feedback!==notice)throw new WorkspaceApiError(503);
  }else if(review.feedback!==body.feedback||(entry.google_source_state==='unavailable'||entry.microsoft_source_state==='unavailable'||entry.calendar_source_state==='unavailable'||entry.fax_source_state==='unavailable'||entry.practice_fax_source_state==='unavailable'||(entry.calendar_import_source_state==='unavailable'||entry.ehr_source_state==='unavailable'))||!entry.reply||!teamText(entry.reply.content,200000,1)||
    await vendorSha256(new TextEncoder().encode(entry.reply.content))!==body.result_sha256)throw new WorkspaceApiError(503);
  return {entry_revision:Number(value.entry_revision),request_sha256:value.request_sha256,feedback_withheld:value.feedback_withheld,workspace};
}

/** One bounded operation, including fresh credentials, streaming and exact result verification. */
async function command<T>(identity:WorkspaceIdentity,workspaceId:string,handoffId:string,kind:'review'|'revision',body:HandoffReviewInput|HandoffRevisionInput,
  validate:(value:unknown)=>Promise<T>,signal?:AbortSignal):Promise<T> {
  const submitted=Object.freeze({...body}),encoded=JSON.stringify(submitted);
  if(new TextEncoder().encode(encoded).length>16384)throw new WorkspaceApiError(422);
  const controller=new AbortController(),abort=()=>controller.abort(),deadline=Date.now()+30000;
  const check=()=>{if(Date.now()>=deadline)abort();controller.signal.throwIfAborted();currentIdentity(identity);};
  let reader:ReadableStreamDefaultReader<Uint8Array>|undefined,rejectAbort:(()=>void)|undefined;
  const cancel=(stream:{cancel:()=>Promise<unknown>}|null|undefined)=>{try{void stream?.cancel().catch(()=>{});}catch{/* Cancellation cannot replace the save outcome. */}};
  const cancelRead=()=>cancel(reader),interrupted=new Promise<never>((_,reject)=>{rejectAbort=()=>reject(new WorkspaceApiError(503));controller.signal.addEventListener('abort',rejectAbort,{once:true});});
  const wait=<T,>(operation:Promise<T>)=>Promise.race([operation,interrupted]);
  controller.signal.addEventListener('abort',cancelRead,{once:true});signal?.addEventListener('abort',abort,{once:true});
  if(signal?.aborted)abort();const timer=setTimeout(abort,30000);
  try {
    check();
    const base=import.meta.env.VITE_API_BASE?.trim().replace(/\/+$/,'')||'http://127.0.0.1:8000';
    if(!permittedWorkspaceApi(base,import.meta.env.VITE_DESKTOP_SYNTHETIC_ENABLED==='true',window.location.href))throw new WorkspaceApiError(503);
    const headers='mode' in identity?await wait(workspaceAuthHeaders(identity,base).catch(()=>{throw new WorkspaceApiError(401);})):new Headers({'Content-Type':'application/json','X-Box-Id':identity.boxId,'X-Actor-Principal-Id':identity.actorId});
    check();headers.set('X-Cosmas-Model-Contract','1');headers.set('X-Cosmas-Handoff-Review','1');
    const response=await wait(workspaceFetch(identity,`${base}/workspaces/${workspaceId}/handoffs/${handoffId}/${kind}`,{
      method:'POST',body:encoded,headers,signal:controller.signal,cache:'no-store',credentials:'omit',redirect:'error',referrerPolicy:'no-referrer'}));
    check();
    if([401,403,404,426].includes(response.status)){cancel(response.body);throw new WorkspaceApiError(response.status);}
    if(response.headers.get('content-type')?.split(';',1)[0].trim().toLowerCase()!=='application/json'||
      !response.headers.get('cache-control')?.split(',').some(v=>v.trim().toLowerCase()==='no-store')){cancel(response.body);throw new WorkspaceApiError(response.ok?503:response.status);}
    reader=response.body?.getReader();if(!reader)throw new WorkspaceApiError(503);
    const chunks:Uint8Array[]=[];let size=0;
    while(true){check();const part=await wait(reader.read());check();if(part.done)break;size+=part.value.length;
      if(size>MODEL_WORKSPACE_BYTES)throw new WorkspaceApiError(503);chunks.push(part.value);}
    const bytes=new Uint8Array(size);let offset=0;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length;}
    let value:unknown;try{value=parseVendorJson(new TextDecoder('utf-8',{fatal:true}).decode(bytes));}catch{throw new WorkspaceApiError(503);}
    check();if(response.status!==200){
      if([400,409,422].includes(response.status)&&teamClosed(value,'detail')&&typeof value.detail==='string'&&REFUSALS.has(value.detail))
        throw new HandoffReviewRefusal(response.status,value.detail);
      throw new WorkspaceApiError(response.ok?503:response.status);
    }
    const result=await wait(validate(value));check();return result;
  }catch(error){if(error instanceof WorkspaceApiError)throw error;throw new WorkspaceApiError(503);}
  finally{clearTimeout(timer);signal?.removeEventListener('abort',abort);controller.signal.removeEventListener('abort',cancelRead);
    if(rejectAbort)controller.signal.removeEventListener('abort',rejectAbort);
    if(reader){const owned=reader;try{void owned.cancel().catch(()=>{}).finally(()=>{try{owned.releaseLock();}catch{/* A discarded read may still settle. */}});}catch{/* Best effort only. */}}controller.abort();}
}

export async function saveHandoffReview(identity:WorkspaceIdentity,workspaceId:string,handoffId:string,body:HandoffReviewInput,
  signal?:AbortSignal):Promise<HandoffReviewResponse> {
  if(!teamUuid(workspaceId)||!teamUuid(handoffId)||!validHandoffReviewInput(body))throw new WorkspaceApiError(422);
  const submitted=Object.freeze({...body});return command(identity,workspaceId,handoffId,'review',submitted,
    value=>exactResponse(value,workspaceId,handoffId,submitted),signal);
}

export async function prepareHandoffRevision(identity:WorkspaceIdentity,workspaceId:string,handoffId:string,body:HandoffRevisionInput,
  signal?:AbortSignal):Promise<HandoffRevisionResponse> {
  if(!teamUuid(workspaceId)||!teamUuid(handoffId)||!validHandoffRevisionInput(body))throw new WorkspaceApiError(422);
  const submitted=Object.freeze({...body});
  return command(identity,workspaceId,handoffId,'revision',submitted,async value=>{
    if(!teamClosed(value,'entry_revision,revision_handoff_id,workspace')||value.entry_revision!==submitted.expected_revision+1||
      !teamUuid(value.revision_handoff_id)||value.revision_handoff_id===handoffId||!await validModelWorkspace(value.workspace,workspaceId))throw new WorkspaceApiError(503);
    const workspace=value.workspace as Workspace,parent=workspace.handoffs?.find(h=>h.id===handoffId) as ReviewableHandoff|undefined;
    const next=workspace.handoffs?.find(h=>h.id===value.revision_handoff_id) as ReviewableHandoff|undefined;
    const review=parent?.review,metadata=next?.revision_request;
    if(workspace.revision<Number(value.entry_revision)||!parent||!next||!validHandoffReviewReceipt(review)||review.id!==submitted.review_id||
      review.decision!=='changes_requested'||!['queued','running','completed','failed','interrupted'].includes(next.status)||
      next.recipient_role!==parent.recipient_role||next.recipient_name!==parent.recipient_name||next.recipient_agent_id!==parent.recipient_agent_id||
      next.recipient_key!==parent.recipient_key||next.origin_entry_id===parent.origin_entry_id||!teamClosed(metadata,'parent_handoff_id,review_id,attempt_id,result_entry_id,result_sha256,feedback')||
      metadata.parent_handoff_id!==parent.id||metadata.review_id!==review.id||metadata.attempt_id!==review.attempt_id||
      metadata.result_entry_id!==review.result_entry_id||metadata.result_sha256!==review.result_sha256||metadata.feedback!==review.feedback)throw new WorkspaceApiError(503);
    const request=workspace.entries.find(entry=>entry.id===next.origin_entry_id);
    if(!request||request.kind!=='conversation'||request.origin!=='authenticated_human'||request.revision!==value.entry_revision||request.reply)throw new WorkspaceApiError(503);
    const prior=workspace.entries.find(entry=>entry.id===review.result_entry_id);
    if(!prior?.reply||await vendorSha256(new TextEncoder().encode(prior.reply.content))!==review.result_sha256)throw new WorkspaceApiError(503);
    return {entry_revision:Number(value.entry_revision),revision_handoff_id:value.revision_handoff_id,workspace};
  },signal);
}
