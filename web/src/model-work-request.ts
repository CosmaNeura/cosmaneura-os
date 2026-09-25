import {validMembershipAnalysis,type MembershipAnalysis} from "./membership-analysis-contract";
import type {BotAddress, BotRole, ConversationInput, HandoffRetryInput, Workspace, WorkspaceEntry} from "./workspace-api";
import {teamAddress, teamCanonical, teamClosed as closed, teamHash, teamLiteral, teamNatural, teamText, teamUuid} from "./team-setup-request";
import {validInboxAnalysis,type InboxAnalysis} from './inbox-analysis-contract';
import {validResearchAnalysis,type ResearchAnalysis} from './research-analysis-contract';

export const MODEL_REQUEST_BYTES=65536, MODEL_RETRY_BYTES=2048, MODEL_RECEIPT_BYTES=16384, MODEL_WORKSPACE_BYTES=12000000;
export const MODEL_STATES=["reserved","running","completed","failed","unknown","abandoned"] as const;
export const MODEL_REASONS=["model_unavailable","authority_changed","source_changed","dispatch_interrupted","reservation_expired","team_work_limit"] as const;
export type ModelReason=typeof MODEL_REASONS[number];
export type AdmissionObservation={id:string;state:typeof MODEL_STATES[number];unit:1;admitted_at:string;dispatch:"not_started"|"started"|"unconfirmed";usage:"unknown"|"verified";input_tokens:number|null;output_tokens:number|null};
export type ModelRequestObservation={contract_version:1;workspace_id:string;idempotency_key:string;request_sha256:string;
  outcome:"saved"|"reserved"|"running"|"unknown"|"failed"|"abandoned"|"not_found";admission:AdmissionObservation|null;saved_entry:{id:string;revision:number}|null;reason:ModelReason|null};
export type HandoffRetryObservation={contract_version:1;workspace_id:string;handoff_id:string;previous_attempt_id:string;idempotency_key:string;request_sha256:string;
  outcome:"recorded"|"not_found";recorded:null|{attempt_id:string;attempt_number:2|3;recorded_at:string;workspace_revision:number;
    status:"queued"|"running"|"completed"|"failed"|"interrupted";result_entry:{id:string;revision:number}|null;admission:AdmissionObservation|null;
    coverage:"durable_admission"|"retained_legacy";reason:ModelReason|"legacy_queued_unadmitted"|"legacy_running_unconfirmed"|null}};
export type EntryModelRequest={contract_version:1;request_sha256:string;request:{kind:"conversation";expected_revision:number;team_revision:number;idempotency_key:string;role:BotAddress;research_analysis?:ResearchAnalysis;inbox_analysis?:InboxAnalysis;membership_analysis?:MembershipAnalysis}|{kind:"private_handoff";handoff_id:string;attempt_id:string};
  bot:{address:BotAddress;agent_id:string;role:BotRole;name:string;team_revision:number};admission:AdmissionObservation;reason:ModelReason|null};
export type ModelOrigin="durable_admission_v1"|"legacy_unknown";
export type ModelOperation=({type:"ask";body:ConversationInput}|{type:"retry";handoffId:string;body:HandoffRetryInput})&{
  model_contract?:1;origin?:"durable_admission_v1";previous_model_request?:PreviousModelRequest};
export type PreviousModelRequest={workspace_id:string;operation:{type:"ask";body:ConversationInput}|{type:"retry";handoffId:string;body:HandoffRetryInput};
  request_sha256:string;outcome:ModelRequestObservation["outcome"]|HandoffRetryObservation["outcome"];observed_at:string;origin:ModelOrigin;legacy_uncertainty_acknowledged:boolean};
export const modelKey=(v:unknown):v is string=>typeof v==="string"&&/^[A-Za-z0-9._:-]{8,255}$/.test(v);
// Pydantic's existing Rust whitespace trim excludes Python's U+001C..U+001F.
export const modelStrip=(v:string)=>v.replace(/^[\u0009-\u000d\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+|[\u0009-\u000d\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$/g,"");
export function modelTime(v:unknown):v is string {
  if(typeof v!=="string")return false;
  const parts=/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,9})?(?:Z|[+-](\d{2}):(\d{2}))$/.exec(v);
  if(!parts)return false;
  const [,year,month,day,hour,minute,second,offsetHour='0',offsetMinute='0']=parts;
  const y=Number(year),m=Number(month),d=Number(day),days=[31,y%4===0&&(y%100!==0||y%400===0)?29:28,31,30,31,30,31,31,30,31,30,31];
  return y>=1&&m>=1&&m<=12&&d>=1&&d<=days[m-1]&&Number(hour)<24&&Number(minute)<60&&Number(second)<60&&Number(offsetHour)<24&&Number(offsetMinute)<60&&Number.isFinite(Date.parse(v));
}
const positive=(v:unknown):v is number=>teamNatural(v)&&v>=1;
const encodedSize=(v:unknown)=>new TextEncoder().encode(JSON.stringify(v)).length;
export function validConversation(v:unknown):v is ConversationInput {
  return closed(v,"expected_revision,team_revision,idempotency_key,role,content","research_analysis,inbox_analysis,membership_analysis")&&positive(v.expected_revision)&&positive(v.team_revision)&&modelKey(v.idempotency_key)&&
    teamAddress(v.role)&&typeof v.content==="string"&&teamText(modelStrip(v.content),4000,1)&&(!('research_analysis' in v)||validResearchAnalysis(v.research_analysis))&&(!('inbox_analysis' in v)||!('research_analysis' in v)&&validInboxAnalysis(v.inbox_analysis))&&(!('membership_analysis' in v)||!('research_analysis' in v)&&!('inbox_analysis' in v)&&validMembershipAnalysis(v.membership_analysis))&&encodedSize(v)<=MODEL_REQUEST_BYTES;
}
export function validHandoffRetry(v:unknown):v is HandoffRetryInput {
  return closed(v,"expected_revision,previous_attempt_id,idempotency_key")&&positive(v.expected_revision)&&teamUuid(v.previous_attempt_id)&&modelKey(v.idempotency_key)&&encodedSize(v)<=MODEL_RETRY_BYTES;
}
// Match Python json.dumps(sort_keys=True, separators=(",",":"), ensure_ascii=True).
export const modelCanonical=(v:unknown)=>teamCanonical(v).replace(/[\u007f-\uffff]/g,c=>"\\u"+c.charCodeAt(0).toString(16).padStart(4,"0"));
export async function modelRequestHash(body:ConversationInput|HandoffRetryInput):Promise<string> {
  const selected="content" in body?{expected:body.expected_revision,team_revision:body.team_revision,role:modelStrip(body.role),content:modelStrip(body.content),...(body.research_analysis?{research_analysis:body.research_analysis}:{}),...(body.inbox_analysis?{inbox_analysis:body.inbox_analysis}:{}),...(body.membership_analysis?{membership_analysis:body.membership_analysis}:{})}:
    {expected:body.expected_revision,previous_attempt:body.previous_attempt_id};
  const bytes=await crypto.subtle.digest("SHA-256",new TextEncoder().encode(modelCanonical(selected)));
  return [...new Uint8Array(bytes)].map(v=>v.toString(16).padStart(2,"0")).join("");
}
export function validAdmission(v:unknown):v is AdmissionObservation {
  if(!closed(v,"id,state,unit,admitted_at,dispatch,usage,input_tokens,output_tokens")||!teamUuid(v.id)||!teamLiteral(v.state,MODEL_STATES)||v.unit!==1||!modelTime(v.admitted_at)||
    !teamLiteral(v.dispatch,["not_started","started","unconfirmed"])||!teamLiteral(v.usage,["unknown","verified"]))return false;
  if(v.usage==="unknown"?(v.input_tokens!==null||v.output_tokens!==null):(!teamNatural(v.input_tokens)||!teamNatural(v.output_tokens)||v.input_tokens>999999||v.output_tokens>999999))return false;
  if(v.state==="reserved"||v.state==="abandoned")return v.dispatch==="not_started";
  if(v.state==="running"||v.state==="completed")return v.dispatch==="started";
  return v.state!=="unknown"||v.dispatch==="unconfirmed";
}
const anchor=(v:unknown):v is {id:string;revision:number}=>closed(v,"id,revision")&&teamUuid(v.id)&&positive(v.revision);
const reason=(v:unknown)=>v===null||teamLiteral(v,MODEL_REASONS);
export function validModelObservation(v:unknown):v is ModelRequestObservation {
  if(!closed(v,"contract_version,workspace_id,idempotency_key,request_sha256,outcome,admission,saved_entry,reason")||v.contract_version!==1||!teamUuid(v.workspace_id)||!modelKey(v.idempotency_key)||!teamHash(v.request_sha256)||
    !teamLiteral(v.outcome,["saved","reserved","running","unknown","failed","abandoned","not_found"])||!reason(v.reason)||v.admission!==null&&!validAdmission(v.admission))return false;
  if(v.outcome==="not_found")return v.admission===null&&v.saved_entry===null&&v.reason===null;
  if(v.outcome==="saved")return anchor(v.saved_entry)&&(v.admission===null||v.admission.state==="completed"||v.admission.state==="failed");
  return v.saved_entry===null&&v.admission!==null&&v.admission.state===v.outcome;
}
export function validRetryObservation(v:unknown):v is HandoffRetryObservation {
  if(!closed(v,"contract_version,workspace_id,handoff_id,previous_attempt_id,idempotency_key,request_sha256,outcome,recorded")||v.contract_version!==1||!teamUuid(v.workspace_id)||!teamUuid(v.handoff_id)||
    !teamUuid(v.previous_attempt_id)||!modelKey(v.idempotency_key)||!teamHash(v.request_sha256)||!teamLiteral(v.outcome,["recorded","not_found"]))return false;
  if(v.outcome==="not_found")return v.recorded===null;
  const r=v.recorded;
  if(!closed(r,"attempt_id,attempt_number,recorded_at,workspace_revision,status,result_entry,admission,coverage,reason")||!teamUuid(r.attempt_id)||![2,3].includes(Number(r.attempt_number))||typeof r.attempt_number!=="number"||
    !modelTime(r.recorded_at)||!positive(r.workspace_revision)||!teamLiteral(r.status,["queued","running","completed","failed","interrupted"])||
    r.result_entry!==null&&!anchor(r.result_entry)||!teamLiteral(r.coverage,["durable_admission","retained_legacy"])||
    !(reason(r.reason)||teamLiteral(r.reason,["legacy_queued_unadmitted","legacy_running_unconfirmed"])))return false;
  if(r.attempt_id===v.previous_attempt_id||(r.status==='completed')!==(r.result_entry!==null))return false;
  if(r.coverage==='retained_legacy')return r.admission===null;
  if(!validAdmission(r.admission))return false;
  const status={reserved:'queued',running:'running',completed:'completed',failed:'failed',unknown:'interrupted',abandoned:'interrupted'};
  return r.status===status[r.admission.state];
}
export async function exactModelObservation(v:unknown,workspaceId:string,operation:ModelOperation):Promise<boolean> {
  if(!validModelObservation(v)&&!validRetryObservation(v))return false;
  if(operation.type==='ask'?!validModelObservation(v):!validRetryObservation(v))return false;
  return v.workspace_id===workspaceId&&v.idempotency_key===operation.body.idempotency_key&&v.request_sha256===await modelRequestHash(operation.body)&&
    (operation.type!=="retry"||"handoff_id" in v&&v.handoff_id===operation.handoffId&&v.previous_attempt_id===operation.body.previous_attempt_id);
}
export function validEntryModel(v:unknown):v is EntryModelRequest {
  if(!closed(v,"contract_version,request_sha256,request,bot,admission,reason")||v.contract_version!==1||!teamHash(v.request_sha256)||!validAdmission(v.admission)||!reason(v.reason)||encodedSize(v)>2048)return false;
  const b=v.bot;if(!closed(b,"address,agent_id,role,name,team_revision")||!teamAddress(b.address)||!teamUuid(b.agent_id)||!teamLiteral(b.role,["scribe","visit_prep","follow_up","chief","custom","research"])||!teamText(b.name,40,1)||!positive(b.team_revision))return false;
  const r=v.request;
  if(closed(r,"kind,expected_revision,team_revision,idempotency_key,role","research_analysis,inbox_analysis,membership_analysis")&&r.kind==="conversation")return positive(r.expected_revision)&&positive(r.team_revision)&&modelKey(r.idempotency_key)&&teamAddress(r.role)&&r.role===b.address&&r.team_revision===b.team_revision&&(!('research_analysis' in r)||b.role==='research'&&validResearchAnalysis(r.research_analysis))&&(!('inbox_analysis' in r)||!('research_analysis' in r)&&b.role==='custom'&&validInboxAnalysis(r.inbox_analysis))&&(!('membership_analysis' in r)||!('research_analysis' in r)&&!('inbox_analysis' in r)&&b.role==='custom'&&validMembershipAnalysis(r.membership_analysis));
  return closed(r,"kind,handoff_id,attempt_id")&&r.kind==="private_handoff"&&teamUuid(r.handoff_id)&&teamUuid(r.attempt_id);
}
export async function validModelWorkspace(value:unknown,workspaceId:string):Promise<boolean> {
  if(!value||typeof value!=="object")return false;
  const w=value as Workspace;
  if(w.id!==workspaceId||!positive(w.revision)||!Array.isArray(w.entries)||w.entries.length>500||!Array.isArray(w.work_candidates))return false;
  if(w.model_contract_version!==1||!modelTime(w.model_observed_at))return false;
  const ids=new Set<string>(),admissions=new Set<string>(),requests=new Set<string>();let count=0;
  for(const entry of w.entries) {
    if(!entry||typeof entry!=="object"||!teamUuid(entry.id)||ids.has(entry.id)||!positive(entry.revision)||entry.revision>w.revision)return false;
    ids.add(entry.id);if(entry.model_request===undefined)continue;
    if(++count>50||!validEntryModel(entry.model_request)||admissions.has(entry.model_request.admission.id)||typeof entry.content!=="string")return false;
    const m=entry.model_request;admissions.add(m.admission.id);
    if(m.request.kind==="conversation") {
      if(entry.kind!=="conversation"||entry.revision!==m.request.expected_revision+1||requests.has(m.request.idempotency_key))return false;
      requests.add(m.request.idempotency_key);
      const body=conversationFromEntry(entry);if(!body)return false;
      if(!validConversation(body)||m.request_sha256!==await modelRequestHash(body))return false;
    } else if(entry.kind!=="handoff_result")return false;
    if(entry.reply&&(entry.reply.agent_id!==m.bot.agent_id||entry.reply.role!==m.bot.role||entry.reply.agent_name!==m.bot.name))return false;
  }
  return true;
}
/** Reconstruct the exact retained intent; omitting an analysis selection changes its hash. */
export function conversationFromEntry(entry:WorkspaceEntry):ConversationInput|null{
 const metadata=entry.model_request;if(!metadata||!validEntryModel(metadata)||metadata.request.kind!=='conversation'||typeof entry.content!=='string')return null;
 const r=metadata.request;return {expected_revision:r.expected_revision,team_revision:r.team_revision,idempotency_key:r.idempotency_key,role:r.role,content:entry.content,...(r.research_analysis?{research_analysis:structuredClone(r.research_analysis)}:{}),...(r.inbox_analysis?{inbox_analysis:structuredClone(r.inbox_analysis)}:{}),...(r.membership_analysis?{membership_analysis:structuredClone(r.membership_analysis)}:{})};
}
export function validModelOperation(v:unknown,previous=true):v is ModelOperation {
  if(!v||typeof v!=="object")return false;
  const op=v as Record<string,unknown>;
  if(op.type==="ask"?!closed(op,"type,body","model_contract,origin,previous_model_request")||!validConversation(op.body):
    op.type!=="retry"||!closed(op,"type,handoffId,body","model_contract,origin,previous_model_request")||!teamUuid(op.handoffId)||!validHandoffRetry(op.body))return false;
  if(op.model_contract!==undefined||op.origin!==undefined) {if(op.model_contract!==1||op.origin!=="durable_admission_v1")return false;}
  if(op.previous_model_request===undefined)return true;
  return previous&&op.model_contract===1&&validPreviousModelRequest(op.previous_model_request);
}
export function validPreviousModelRequest(p:unknown):p is PreviousModelRequest {
  return closed(p,"workspace_id,operation,request_sha256,outcome,observed_at,origin,legacy_uncertainty_acknowledged")&&teamUuid(p.workspace_id)&&
    validModelOperation(p.operation,false)&&Object.keys(p.operation).every(k=>["type","body","handoffId"].includes(k))&&teamHash(p.request_sha256)&&modelTime(p.observed_at)&&
    teamLiteral(p.outcome,["unknown","failed","abandoned","not_found"])&&teamLiteral(p.origin,["durable_admission_v1","legacy_unknown"])&&
    typeof p.legacy_uncertainty_acknowledged==="boolean"&&(p.origin!=="legacy_unknown"||p.legacy_uncertainty_acknowledged===true);
}
export const modelActive=(entry:WorkspaceEntry)=>entry.model_request!==undefined&&["reserved","running"].includes(entry.model_request.admission.state);
export const modelStateLabel=(state:AdmissionObservation["state"])=>({reserved:"Request recorded · waiting to start",running:"Request in progress",completed:"Response saved",failed:"Request failed",unknown:"Outcome unconfirmed",abandoned:"Request expired before starting"})[state];
