import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity,WORKSPACE_BUILD,WORKSPACE_AUTHENTICATED_BUILD} from './workspace-api';
import {workspaceFetch} from './workspace-protocol';
import {assertCurrentDesktopSession,workspaceAuthHeaders} from './workspace-auth-headers';
import {permittedWorkspaceApi} from './workspace-origin';
import {teamCanonical,teamClosed,teamHash,teamNatural,teamText,teamUuid} from './team-setup-request';
import {parseVendorJson,vendorSha256} from './vendor-contract';

export const SCHEDULING_PATIENT_BUILD=WORKSPACE_BUILD&&WORKSPACE_AUTHENTICATED_BUILD&&import.meta.env.VITE_WORKSPACE_SCHEDULING_PATIENT_SETUP_ENABLED==='true';
export type SchedulingPatientSearch={kind:'search';query:string;birth_date:string|null};
export type SchedulingPatientPreviewCommand={action:'preview';expected_revision:number;idempotency_key:string;search:SchedulingPatientSearch};
export type SchedulingPatientConfirmCommand={action:'confirm';expected_revision:number;idempotency_key:string;preview_id:string;preview_sha256:string;choice_ref:string;identity_sha256:string;
  reviewed_same_patient:true;reviewed_exact_identity:true};
export type SchedulingPatientCommand=SchedulingPatientPreviewCommand|SchedulingPatientConfirmCommand;
export type SchedulingPatientChoice={choice_ref:string;display_name:string;birth_date:string|null;subject_revision:number;identity_sha256:string};
export type SchedulingPatientPreview={checked_at:string;expires_at:string;choices:SchedulingPatientChoice[];more:boolean};
export type SchedulingPatientMapping={mapping_id:string;mapping_sha256:string;identity_sha256:string;subject_revision:number};
export type SchedulingPatientReceipt={contract_version:1;kind:'preview'|'confirm';request_id:string|null;request_key:string;request_sha256:string|null;
  status:'saved'|'unconfirmed'|'not_found';source_withheld:boolean;source_sha256:string|null;preview:SchedulingPatientPreview|null;mapping:SchedulingPatientMapping|null};
export type SchedulingPatientStatus={contract_version:1;state:'linked'|'link_required';mapping_id:string|null};
const invalid=():never=>{throw new WorkspaceApiError(502,'scheduling_patient_receipt_invalid');};
const uuid=(v:unknown):v is string=>teamUuid(v)&&v!=='00000000-0000-0000-0000-000000000000';
const text=(v:unknown,max:number):v is string=>teamText(v,max,1)&&v===v.trim()&&!/[\u0000-\u001f\u007f]/.test(v);
export function validSchedulingPatientDate(value:unknown):value is string|null{
 if(value===null)return true;if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(value)||value<'0001-01-01')return false;
 const at=new Date(value+'T00:00:00Z');return Number.isFinite(at.getTime())&&at.toISOString().slice(0,10)===value&&value<=new Date().toISOString().slice(0,10);
}
const stamp=(v:unknown):v is string=>typeof v==='string'&&/^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/.test(v)&&Number.isFinite(Date.parse(v));
export const schedulingPatientDigest=(domain:string,value:unknown)=>vendorSha256(new TextEncoder().encode(teamCanonical([domain,value])));
export const schedulingPatientRequestHash=(workspaceId:string,request:SchedulingPatientCommand)=>schedulingPatientDigest('cosmas-scheduling-patient-command.v1',{workspace_id:workspaceId,request});
export function validSchedulingPatientCommand(input:unknown):input is SchedulingPatientCommand{
 const value=input as Record<string,unknown>;
 if(!value||typeof value!=='object'||!('action'in value))return false;
 if(value.action==='preview')return teamClosed(value,'action,expected_revision,idempotency_key,search')&&teamNatural(value.expected_revision)&&value.expected_revision>0&&value.expected_revision<2147483647&&uuid(value.idempotency_key)&&
  teamClosed(value.search,'kind,query,birth_date')&&value.search.kind==='search'&&text(value.search.query,120)&&validSchedulingPatientDate(value.search.birth_date);
 return teamClosed(value,'action,expected_revision,idempotency_key,preview_id,preview_sha256,choice_ref,identity_sha256,reviewed_same_patient,reviewed_exact_identity')&&value.action==='confirm'&&
  teamNatural(value.expected_revision)&&value.expected_revision>0&&value.expected_revision<2147483647&&uuid(value.idempotency_key)&&uuid(value.preview_id)&&teamHash(value.preview_sha256)&&uuid(value.choice_ref)&&teamHash(value.identity_sha256)&&
  value.reviewed_same_patient===true&&value.reviewed_exact_identity===true;
}
export async function validSchedulingPatientChoice(value:unknown):Promise<boolean>{
 if(!teamClosed(value,'choice_ref,display_name,birth_date,subject_revision,identity_sha256')||!uuid(value.choice_ref)||!text(value.display_name,120)||!validSchedulingPatientDate(value.birth_date)||
  !teamNatural(value.subject_revision)||value.subject_revision<1||!teamHash(value.identity_sha256))return false;
 const {identity_sha256,...identity}=value;return identity_sha256===await schedulingPatientDigest('cosmas-scheduling-patient-identity.v1',identity);
}
export async function validateSchedulingPatientReceipt(value:unknown):Promise<SchedulingPatientReceipt>{
 if(!teamClosed(value,'contract_version,kind,request_id,request_key,request_sha256,status,source_withheld,source_sha256,preview,mapping')||value.contract_version!==1||
  !['preview','confirm'].includes(String(value.kind))||!uuid(value.request_key)||!['saved','unconfirmed','not_found'].includes(String(value.status))||typeof value.source_withheld!=='boolean')return invalid();
 if(value.status==='not_found'){
  if(value.request_id!==null||value.request_sha256!==null||value.source_sha256!==null||value.preview!==null||value.mapping!==null||value.source_withheld)return invalid();
 }else{
  if(!uuid(value.request_id)||!teamHash(value.request_sha256))return invalid();
  if(value.status==='unconfirmed'){if(value.source_sha256!==null||value.preview!==null||value.mapping!==null)return invalid();}
  else if(!teamHash(value.source_sha256))return invalid();
  if(value.source_withheld&&(value.preview!==null||value.mapping!==null))return invalid();
  if(value.status==='saved'&&!value.source_withheld){
   if(value.kind==='preview'){
    const p=value.preview;if(value.mapping!==null||!teamClosed(p,'checked_at,expires_at,choices,more')||!stamp(p.checked_at)||!stamp(p.expires_at)||
     Date.parse(p.checked_at)>=Date.parse(p.expires_at)||Date.parse(p.expires_at)-Date.parse(p.checked_at)>300000||typeof p.more!=='boolean'||!Array.isArray(p.choices)||p.choices.length>5||
     p.more&&p.choices.length!==5||new Set(p.choices.map(c=>c?.choice_ref)).size!==p.choices.length)return invalid();
    for(const choice of p.choices)if(!await validSchedulingPatientChoice(choice))return invalid();
   }else if(value.preview!==null||!teamClosed(value.mapping,'mapping_id,mapping_sha256,identity_sha256,subject_revision')||!uuid(value.mapping.mapping_id)||!teamHash(value.mapping.mapping_sha256)||
    !teamHash(value.mapping.identity_sha256)||!teamNatural(value.mapping.subject_revision)||value.mapping.subject_revision<1)return invalid();
  }
 }
 return structuredClone(value) as SchedulingPatientReceipt;
}
export function validateSchedulingPatientStatus(value:unknown):SchedulingPatientStatus{
 if(!teamClosed(value,'contract_version,state,mapping_id')||value.contract_version!==1||!['linked','link_required'].includes(String(value.state))||
  (value.state==='linked'?!uuid(value.mapping_id):value.mapping_id!==null))return invalid();return value as SchedulingPatientStatus;
}
export class SchedulingPatientRefusal extends WorkspaceApiError {constructor(status:number,code:string){super(status,code);this.name='SchedulingPatientRefusal';}}
const REFUSALS=new Set(['scheduling_patient_setup_unavailable','scheduling_connection_required','scheduling_patient_grant_unavailable','scheduling_patient_source_changed','scheduling_patient_account_changed',
 'scheduling_patient_preview_superseded','scheduling_patient_preview_expired','scheduling_patient_receipt_invalid','scheduling_patient_receipt_unavailable','scheduling_patient_response_unconfirmed',
 'scheduling_patient_setup_limit','scheduling_patient_mapping_review_required','scheduling_patient_correspondence_required','workspace_revision_conflict','workspace_access_denied','encounter_unavailable','idempotency_conflict','invalid_scheduling_patient_request']);
type ReadCommand={action:'status'}|{action:'inspect';request_id:string}|{action:'resolve';kind:'preview'|'confirm';idempotency_key:string};
async function send<T>(identity:AuthenticatedWorkspaceIdentity,workspaceId:string,body:SchedulingPatientCommand|ReadCommand,validate:(value:unknown)=>Promise<T>,signal?:AbortSignal):Promise<T>{
 if(!SCHEDULING_PATIENT_BUILD)throw new WorkspaceApiError(404);
 if(!uuid(workspaceId))throw new WorkspaceApiError(422);
 const encoded=JSON.stringify(Object.freeze({...body}));if(new TextEncoder().encode(encoded).byteLength>4096)throw new WorkspaceApiError(422);
 const base=import.meta.env.VITE_API_BASE?.trim().replace(/\/+$/,'')||'http://127.0.0.1:8000';
 if(!permittedWorkspaceApi(base,import.meta.env.VITE_DESKTOP_SYNTHETIC_ENABLED==='true',window.location.href))throw new WorkspaceApiError(503);
 const c=new AbortController(),abort=()=>c.abort(),deadline=Date.now()+50000;let response:Response|undefined,reader:ReadableStreamDefaultReader<Uint8Array>|undefined;
 const stop=(v:{cancel:()=>Promise<unknown>}|null|undefined)=>{try{void v?.cancel().catch(()=>{});}catch{/* bounded cleanup */}};
 const interrupted=new Promise<never>((_,reject)=>c.signal.addEventListener('abort',()=>{stop(reader);if(!reader)stop(response?.body);reject(new WorkspaceApiError(503));},{once:true}));
 const wait=<V,>(v:Promise<V>)=>Promise.race([v,interrupted]),check=()=>{if(Date.now()>=deadline)c.abort();if(c.signal.aborted)throw new WorkspaceApiError(503);assertCurrentDesktopSession(identity);
  if(identity.mode==='clerk_jwt'&&identity.nativeSession&&!identity.nativeSession.isCurrent())throw new WorkspaceApiError(401);};
 const timer=setTimeout(abort,50000);signal?.addEventListener('abort',abort,{once:true});if(signal?.aborted)abort();
 try{
  check();const headers=await wait(workspaceAuthHeaders(identity,base).catch(()=>{throw new WorkspaceApiError(401);}));check();headers.set('X-Cosmas-Scheduling-Patient','1');headers.set('Accept','application/json');
  response=await wait(workspaceFetch(identity,base+`/workspaces/${workspaceId}/scheduling-patient/setup`,{method:'POST',headers,body:encoded,signal:c.signal,cache:'no-store',credentials:'omit',redirect:'error',referrerPolicy:'no-referrer'}));check();
  if([401,403,404,426].includes(response.status))throw new WorkspaceApiError(response.status);
  if(response.redirected||response.headers.has('content-encoding')||response.headers.get('content-type')?.split(';',1)[0].trim().toLowerCase()!=='application/json'||!response.headers.get('cache-control')?.split(',').some(v=>v.trim().toLowerCase()==='no-store'))return invalid();
  reader=response.body?.getReader();if(!reader)return invalid();const chunks:Uint8Array[]=[];let size=0;
  for(;;){const part=await wait(reader.read());check();if(part.done)break;size+=part.value.byteLength;if(size>(response.ok?32768:2048))return invalid();chunks.push(part.value);}
  const bytes=new Uint8Array(size);let offset=0;for(const part of chunks){bytes.set(part,offset);offset+=part.length;}
  let value:unknown;try{value=parseVendorJson(new TextDecoder('utf-8',{fatal:true}).decode(bytes));}catch{return invalid();}
  if(response.status!==200){if([400,409,422].includes(response.status)&&teamClosed(value,'detail')&&typeof value.detail==='string'&&REFUSALS.has(value.detail))throw new SchedulingPatientRefusal(response.status,value.detail);throw new WorkspaceApiError(response.status);}
  const result=await wait(validate(value));check();return result;
 }catch(e){if(e instanceof WorkspaceApiError)throw e;throw new WorkspaceApiError(503);}
 finally{clearTimeout(timer);signal?.removeEventListener('abort',abort);stop(reader);if(!reader)stop(response?.body);c.abort();}
}
const boundReceipt=async(value:unknown,workspaceId:string,command:SchedulingPatientCommand)=>{
 const r=await validateSchedulingPatientReceipt(value);if(r.status==='not_found'||r.kind!==command.action||r.request_key!==command.idempotency_key||r.request_sha256!==await schedulingPatientRequestHash(workspaceId,command)||
   command.action==='confirm'&&r.mapping!==null&&r.mapping.identity_sha256!==command.identity_sha256)return invalid();return r;
};
export const schedulingPatientApi={
 status:(identity:AuthenticatedWorkspaceIdentity,wid:string,signal?:AbortSignal)=>send(identity,wid,{action:'status'},async v=>validateSchedulingPatientStatus(v),signal),
 command:(identity:AuthenticatedWorkspaceIdentity,wid:string,body:SchedulingPatientCommand,signal?:AbortSignal)=>{if(!validSchedulingPatientCommand(body))throw new WorkspaceApiError(422);return send(identity,wid,body,v=>boundReceipt(v,wid,body),signal);},
 inspect:(identity:AuthenticatedWorkspaceIdentity,wid:string,requestId:string,signal?:AbortSignal)=>{if(!uuid(requestId))throw new WorkspaceApiError(422);return send(identity,wid,{action:'inspect',request_id:requestId},async v=>{const r=await validateSchedulingPatientReceipt(v);if(r.request_id!==requestId)return invalid();return r;},signal);},
 resolve:(identity:AuthenticatedWorkspaceIdentity,wid:string,body:SchedulingPatientCommand,signal?:AbortSignal)=>{if(!validSchedulingPatientCommand(body))throw new WorkspaceApiError(422);return send(identity,wid,{action:'resolve',kind:body.action,idempotency_key:body.idempotency_key},async v=>{const r=await validateSchedulingPatientReceipt(v);if(r.kind!==body.action||r.request_key!==body.idempotency_key||r.status!=='not_found'&&r.request_sha256!==await schedulingPatientRequestHash(wid,body)||
  body.action==='confirm'&&r.mapping!==null&&r.mapping.identity_sha256!==body.identity_sha256)return invalid();return r;},signal);},
};
