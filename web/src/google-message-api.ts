import {workspaceFetch} from './workspace-protocol';
import {permittedWorkspaceApi} from './workspace-origin';
import {workspaceAuthHeaders,assertCurrentDesktopSession} from './workspace-auth-headers';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity,type Workspace} from './workspace-api';
import {modelCanonical,modelTime,validModelWorkspace,MODEL_WORKSPACE_BYTES} from './model-work-request';
import {teamCanonical,teamClosed,teamHash,teamNatural,teamUuid} from './team-setup-request';
import {parseVendorJson,vendorSha256} from './vendor-contract';
import {GOOGLE_CONNECTION_BUILD} from './google-connection-api';
import {PERSONAL_CONNECTION_DEADLINE_MS} from './connection-operation-health';

export const GOOGLE_MESSAGE_BUILD=GOOGLE_CONNECTION_BUILD&&import.meta.env.VITE_WORKSPACE_GOOGLE_MESSAGE_ENABLED==='true';
export type GoogleMessageStatus={contract_version:1;state:'connected'|'sign_in_required';full_mail_read:boolean;account:{label:string;email:string}|null};
export type GoogleMessageHeader={id:string;thread_id?:string;subject:string;sender:string;received_at:string;is_read:boolean};
export type GoogleMessageObservation={kind:'mail';account:{label:string;email:string};items:GoogleMessageHeader[];more:boolean;observed_at:string};
export type GoogleMessageContent={message_id:string;thread_id:string;history_id:string|null;subject:string;sender:string;received_at:string;is_read:boolean;
  observed_at:string;status:'complete'|'needs_human';content:string|null;reason:'attachment'|'html_only'|'unsupported_mime'|'oversize'|'ambiguous'|'invalid_encoding'|null;
  raw_sha256:string;content_sha256:string|null};
export type GoogleMessageReceipt={read_id:string;read_key:string;kind:'list'|'message';observation_id:string;source_sha256:string;payload_sha256:string;
  status:'observed'|'complete'|'needs_human';message:GoogleMessageContent|null;observation:GoogleMessageObservation|null};
export type GoogleMessageResolve={status:'not_found'|'unconfirmed';kind:'list'|'message';read_key:string;read_id:string|null};
export type GoogleMessageListRequest={action:'list';idempotency_key:string};
export type GoogleMessageReadRequest={action:'read';idempotency_key:string;observation_id:string;observation_sha256:string;message_id:string;thread_id?:string};
export type GoogleMessageReviewRequest={expected_revision:number;idempotency_key:string;read_id:string;source_sha256:string;
  reviewed_patient:true;reviewed_exact_message:true;reviewed_untrusted_source:true};
export type GoogleMessageReviewResponse={entry_id:string;entry_revision:number;request_sha256:string;source_withheld:boolean;workspace:Workspace;source:{entry_id:string;source_sha256:string;content_sha256:string}};
const id=(v:unknown):v is string=>typeof v==='string'&&/^[A-Za-z0-9_-]{1,128}$/.test(v);
const text=(v:unknown,max:number):v is string=>typeof v==='string'&&Array.from(v).length<=max&&!/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(v);
const headerText=(v:unknown,max:number):v is string=>text(v,max)&&!/[\n\r\t]/.test(v);
const account=(v:unknown)=>teamClosed(v,'label,email')&&headerText(v.label,320)&&!!v.label&&headerText(v.email,320)&&!!v.email;
export const googleMessageKey=(v:unknown):v is string=>teamUuid(v);
export function validGoogleMessageStatus(v:unknown):v is GoogleMessageStatus {
  return teamClosed(v,'contract_version,state,full_mail_read,account')&&v.contract_version===1&&['connected','sign_in_required'].includes(String(v.state))&&
    typeof v.full_mail_read==='boolean'&&(v.state==='connected'?account(v.account):v.account===null&&v.full_mail_read===false);
}
export function validGoogleMessageListRequest(v:unknown):v is GoogleMessageListRequest {return teamClosed(v,'action,idempotency_key')&&v.action==='list'&&googleMessageKey(v.idempotency_key);}
export function validGoogleMessageReadRequest(v:unknown):v is GoogleMessageReadRequest {
  return teamClosed(v,'action,idempotency_key,observation_id,observation_sha256,message_id','thread_id')&&v.action==='read'&&googleMessageKey(v.idempotency_key)&&
    teamUuid(v.observation_id)&&teamHash(v.observation_sha256)&&id(v.message_id)&&(!('thread_id'in v)||id(v.thread_id));
}
export function validGoogleMessageReviewRequest(v:unknown):v is GoogleMessageReviewRequest {
  return teamClosed(v,'expected_revision,idempotency_key,read_id,source_sha256,reviewed_patient,reviewed_exact_message,reviewed_untrusted_source')&&
    teamNatural(v.expected_revision)&&v.expected_revision>0&&v.expected_revision<2147483647&&googleMessageKey(v.idempotency_key)&&teamUuid(v.read_id)&&
    teamHash(v.source_sha256)&&v.reviewed_patient===true&&v.reviewed_exact_message===true&&v.reviewed_untrusted_source===true;
}
export const googleMessageReviewHash=(workspaceId:string,body:GoogleMessageReviewRequest,contentSha256:string)=>vendorSha256(new TextEncoder().encode(modelCanonical({
  workspace_id:workspaceId,...body,content_sha256:contentSha256,
})));
function observation(v:unknown):v is GoogleMessageObservation {
  return teamClosed(v,'kind,account,items,more,observed_at')&&v.kind==='mail'&&account(v.account)&&typeof v.more==='boolean'&&modelTime(v.observed_at)&&
    Array.isArray(v.items)&&v.items.length<=25&&new Set(v.items.map(r=>r?.id)).size===v.items.length&&v.items.every(r=>
      teamClosed(r,'id,subject,sender,received_at,is_read','thread_id')&&id(r.id)&&(!('thread_id'in r)||id(r.thread_id))&&
      headerText(r.subject,998)&&headerText(r.sender,320)&&modelTime(r.received_at)&&typeof r.is_read==='boolean');
}
function content(v:unknown):v is GoogleMessageContent {
  if(!teamClosed(v,'message_id,thread_id,history_id,subject,sender,received_at,is_read,observed_at,status,content,reason,raw_sha256,content_sha256')||
    !id(v.message_id)||!id(v.thread_id)||!(v.history_id===null||typeof v.history_id==='string'&&/^[0-9]{1,32}$/.test(v.history_id))||
    !headerText(v.subject,998)||!headerText(v.sender,320)||!modelTime(v.received_at)||!modelTime(v.observed_at)||typeof v.is_read!=='boolean'||!teamHash(v.raw_sha256))return false;
  return v.status==='complete'?text(v.content,5000)&&v.reason===null&&teamHash(v.content_sha256):v.status==='needs_human'&&v.content===null&&v.content_sha256===null&&
    ['attachment','html_only','unsupported_mime','oversize','ambiguous','invalid_encoding'].includes(String(v.reason));
}
export async function validGoogleMessageReceipt(v:unknown):Promise<boolean> {
  if(!teamClosed(v,'read_id,read_key,kind,observation_id,source_sha256,payload_sha256,status,message,observation')||!teamUuid(v.read_id)||!googleMessageKey(v.read_key)||
    !teamUuid(v.observation_id)||!teamHash(v.source_sha256)||!teamHash(v.payload_sha256))return false;
  if(v.kind==='list') {
    if(v.status!=='observed'||v.message!==null||v.observation_id!==v.read_id||!observation(v.observation))return false;
  }else if(v.kind==='message') {
    if(v.observation!==null||!content(v.message)||v.status!==v.message.status||v.read_id===v.observation_id)return false;
    if(v.message.status==='complete'&&await vendorSha256(new TextEncoder().encode(v.message.content!))!==v.message.content_sha256)return false;
  }else return false;
  // Message payload commitment includes sealed custody fields withheld from the browser.
  return v.kind==='message'||await vendorSha256(new TextEncoder().encode(teamCanonical(v.observation)))===v.payload_sha256;
}
export class GoogleMessageRefusal extends WorkspaceApiError {constructor(status:number,code:string){super(status,code);this.name='GoogleMessageRefusal';}}
const REFUSALS=new Set(['google_mail_consent_required','google_message_grant_unavailable','google_message_grant_changed','google_message_source_invalid','google_message_source_superseded',
  'google_message_source_changed','google_message_read_unconfirmed','google_message_not_observed','google_message_incomplete','google_message_patient_mismatch',
  'google_message_already_selected','workspace_revision_conflict','workspace_history_limit','idempotency_conflict','invalid_google_message_request']);
/** Only these definitive refusals permit releasing a new review intent; provider read reservations are never discarded on an error. */
export const googleReviewProvesNoCommit=(error:unknown)=>error instanceof GoogleMessageRefusal&&
  ['workspace_revision_conflict','google_message_incomplete','google_message_patient_mismatch','google_message_already_selected','invalid_google_message_request'].includes(error.code??'');
type Request=GoogleMessageListRequest|GoogleMessageReadRequest|GoogleMessageReviewRequest|{action:'status'}|{action:'inspect';read_id:string}|{action:'resolve';idempotency_key:string;kind:'list'|'message'};
async function send<T>(identity:AuthenticatedWorkspaceIdentity,path:string,body:Request,validate:(value:unknown)=>Promise<T>,signal?:AbortSignal,large=false):Promise<T> {
  if(!GOOGLE_MESSAGE_BUILD)throw new WorkspaceApiError(404);
  const base=import.meta.env.VITE_API_BASE?.trim().replace(/\/+$/,'')||'http://127.0.0.1:8000';
  if(!permittedWorkspaceApi(base,import.meta.env.VITE_DESKTOP_SYNTHETIC_ENABLED==='true',window.location.href))throw new WorkspaceApiError(503);
  const encoded=JSON.stringify(Object.freeze({...body}));if(new TextEncoder().encode(encoded).length>4096)throw new WorkspaceApiError(422);
  const controller=new AbortController(),abort=()=>controller.abort();let rejectAbort:()=>void=()=>{};
  const interrupted=new Promise<never>((_,reject)=>{rejectAbort=()=>reject(new WorkspaceApiError(503));});void interrupted.catch(()=>{});
  controller.signal.addEventListener('abort',rejectAbort,{once:true});signal?.addEventListener('abort',abort,{once:true});
  const timer=setTimeout(abort,PERSONAL_CONNECTION_DEADLINE_MS),wait=<V,>(promise:Promise<V>)=>Promise.race([promise,interrupted]);
  let response:Response|undefined,reader:ReadableStreamDefaultReader<Uint8Array>|undefined;
  const cancel=(value:{cancel:()=>Promise<unknown>}|null|undefined)=>{try{void value?.cancel().catch(()=>{});}catch{/* Best effort. */}};
  const check=()=>{if(controller.signal.aborted)throw new WorkspaceApiError(503);assertCurrentDesktopSession(identity);
    if(identity.mode==='clerk_jwt'&&identity.nativeSession&&!identity.nativeSession.isCurrent())throw new WorkspaceApiError(401);};
  try {
    if(signal?.aborted)abort();check();const headers=await wait(workspaceAuthHeaders(identity,base).catch(()=>{throw new WorkspaceApiError(401);}));check();
    headers.set('X-Cosmas-Google-Messages','1');headers.set('Accept','application/json');
    response=await wait(workspaceFetch(identity,base+path,{method:'POST',headers,body:encoded,signal:controller.signal,cache:'no-store',credentials:'omit',redirect:'error',referrerPolicy:'no-referrer'}));check();
    if([401,403,404,426].includes(response.status))throw new WorkspaceApiError(response.status);
    if(response.redirected||response.headers.has('content-encoding')||response.headers.get('content-type')?.split(';',1)[0].trim().toLowerCase()!=='application/json'||
      !response.headers.get('cache-control')?.split(',').some(v=>v.trim().toLowerCase()==='no-store'))throw new WorkspaceApiError(502);
    reader=response.body?.getReader();if(!reader)throw new WorkspaceApiError(502);const cap=response.ok?(large?MODEL_WORKSPACE_BYTES:131072):2048;
    const chunks:Uint8Array[]=[];let size=0;
    for(;;){const part=await wait(reader.read());check();if(part.done)break;size+=part.value.length;if(size>cap)throw new WorkspaceApiError(502);chunks.push(part.value);}
    const bytes=new Uint8Array(size);let at=0;for(const chunk of chunks){bytes.set(chunk,at);at+=chunk.length;}
    let value:unknown;try{value=parseVendorJson(new TextDecoder('utf-8',{fatal:true}).decode(bytes));}catch{throw new WorkspaceApiError(502);}
    if(response.status!==200){if([400,409,422].includes(response.status)&&teamClosed(value,'detail')&&typeof value.detail==='string'&&REFUSALS.has(value.detail))throw new GoogleMessageRefusal(response.status,value.detail);throw new WorkspaceApiError(response.status);}
    const result=await wait(validate(value));check();return result;
  }catch(error){if(error instanceof WorkspaceApiError)throw error;throw new WorkspaceApiError(503);}
  finally{clearTimeout(timer);signal?.removeEventListener('abort',abort);controller.signal.removeEventListener('abort',rejectAbort);cancel(reader??response?.body);try{reader?.releaseLock();}catch{/* Discarded read may settle. */}controller.abort();}
}
const invalid=():never=>{throw new WorkspaceApiError(502);};
const receipt=async(v:unknown)=>await validGoogleMessageReceipt(v)?v as GoogleMessageReceipt:invalid();
export const googleMessageApi={
  status:(identity:AuthenticatedWorkspaceIdentity,signal?:AbortSignal)=>send(identity,'/connections/google/messages',{action:'status'},async v=>validGoogleMessageStatus(v)?v:invalid(),signal),
  list:(identity:AuthenticatedWorkspaceIdentity,body:GoogleMessageListRequest,signal?:AbortSignal)=>{
    if(!validGoogleMessageListRequest(body))throw new WorkspaceApiError(422);return send(identity,'/connections/google/messages',body,async v=>{const r=await receipt(v);return r.kind==='list'&&r.read_key===body.idempotency_key?r:invalid();},signal);},
  read:(identity:AuthenticatedWorkspaceIdentity,body:GoogleMessageReadRequest,signal?:AbortSignal)=>{
    if(!validGoogleMessageReadRequest(body))throw new WorkspaceApiError(422);return send(identity,'/connections/google/messages',body,async v=>{const r=await receipt(v);return r.kind==='message'&&r.read_key===body.idempotency_key&&r.observation_id===body.observation_id&&
      r.message!.message_id===body.message_id&&(!body.thread_id||r.message!.thread_id===body.thread_id)?r:invalid();},signal);},
  inspect:(identity:AuthenticatedWorkspaceIdentity,anchor:GoogleMessageReceipt,signal?:AbortSignal)=>send(identity,'/connections/google/messages',{action:'inspect',read_id:anchor.read_id},async v=>{
    const r=await receipt(v);return modelCanonical(r)===modelCanonical(anchor)?r:invalid();},signal),
  resolve:(identity:AuthenticatedWorkspaceIdentity,key:string,kind:'list'|'message',signal?:AbortSignal)=>{
    if(!googleMessageKey(key)||!['list','message'].includes(kind))throw new WorkspaceApiError(422);
    return send<GoogleMessageReceipt|GoogleMessageResolve>(identity,'/connections/google/messages',{action:'resolve',idempotency_key:key,kind},async v=>{
      if(teamClosed(v,'status,kind,read_key,read_id')&&v.kind===kind&&v.read_key===key&&
        (v.status==='not_found'?v.read_id===null:v.status==='unconfirmed'&&teamUuid(v.read_id)))return v as GoogleMessageResolve;
      const r=await receipt(v);return r.kind===kind&&r.read_key===key?r:invalid();},signal);},
  review:(identity:AuthenticatedWorkspaceIdentity,workspaceId:string,body:GoogleMessageReviewRequest,message:GoogleMessageReceipt,signal?:AbortSignal)=>{
    if(!teamUuid(workspaceId)||!validGoogleMessageReviewRequest(body)||message.kind!=='message'||message.status!=='complete'||message.read_id!==body.read_id||message.source_sha256!==body.source_sha256)throw new WorkspaceApiError(422);
    return send(identity,`/workspaces/${workspaceId}/google-messages/review`,body,async v=>{
      if(!teamClosed(v,'entry_id,entry_revision,request_sha256,source_withheld,workspace,source')||!teamUuid(v.entry_id)||v.entry_revision!==body.expected_revision+1||
        !teamHash(v.request_sha256)||typeof v.source_withheld!=='boolean'||v.request_sha256!==await googleMessageReviewHash(workspaceId,body,message.message!.content_sha256!)||
        !teamClosed(v.source,'entry_id,source_sha256,content_sha256')||v.source.entry_id!==v.entry_id||v.source.source_sha256!==body.source_sha256||
        v.source.content_sha256!==message.message!.content_sha256||!await validModelWorkspace(v.workspace,workspaceId))return invalid();
      const w=v.workspace as Workspace,e=w.entries.find(e=>e.id===v.entry_id);
      if(w.revision<Number(v.entry_revision)||!e||String(e.kind)!=='google_message'||e.revision!==v.entry_revision)return invalid();
      if(v.source_withheld){if(e.google_source_state!=='unavailable'||e.content!==''||e.source_label!=='Unavailable email source')return invalid();}
      else if(e.google_source_state==='unavailable'||e.content!==message.message!.content||await vendorSha256(new TextEncoder().encode(e.content))!==v.source.content_sha256)return invalid();
      return v as GoogleMessageReviewResponse;
    },signal,true);},
};
