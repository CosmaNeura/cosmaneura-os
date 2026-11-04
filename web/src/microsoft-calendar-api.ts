import {workspaceApiBase} from './workspace-base';
import {workspaceFetch} from './workspace-protocol';
import {permittedWorkspaceApi} from './workspace-origin';
import {workspaceAuthHeaders,assertCurrentDesktopSession} from './workspace-auth-headers';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity,type Workspace} from './workspace-api';
import {modelCanonical,modelTime,validModelWorkspace,MODEL_WORKSPACE_BYTES} from './model-work-request';
import {teamCanonical,teamClosed,teamHash,teamNatural,teamUuid} from './team-setup-request';
import {parseVendorJson,vendorSha256} from './vendor-contract';
import {MICROSOFT_CONNECTION_BUILD} from './microsoft-connection-api';
import {PERSONAL_CONNECTION_DEADLINE_MS} from './connection-operation-health';

export const MICROSOFT_CALENDAR_BUILD=MICROSOFT_CONNECTION_BUILD&&import.meta.env.VITE_MICROSOFT_MESSAGE_ENABLED==='true';
export type MicrosoftCalendarStatus={contract_version:1;state:'connected'|'sign_in_required';calendar_read:boolean;account:{label:string;email:string}|null};
export type MicrosoftCalendarWindow={starts_at:string;ends_at:string};
export type MicrosoftCalendarEvent={id:string;subject:string;starts_at:string;ends_at:string;all_day:boolean;cancelled:boolean};
export type MicrosoftCalendarObservation={kind:'calendar';account:{label:string;email:string};items:MicrosoftCalendarEvent[];more:boolean;observed_at:string;window:MicrosoftCalendarWindow};
export type MicrosoftCalendarReceipt={contract_version:1;observation_id:string;observation_key:string;source_sha256:string;payload_sha256:string;observation:MicrosoftCalendarObservation};
export type MicrosoftCalendarResolve={status:'not_found'|'unconfirmed';observation_id:string|null;observation_key:string};
export type MicrosoftCalendarObserveRequest={action:'observe';idempotency_key:string};
export type MicrosoftCalendarReviewRequest={expected_revision:number;idempotency_key:string;observation_id:string;observation_sha256:string;event_id:string;event_sha256:string;reviewed_exact_summary:true;reviewed_untrusted_source:true}&{reviewed_visit:true};
export type MicrosoftCalendarReviewResponse={entry_id:string;entry_revision:number;request_sha256:string;source_withheld:boolean;workspace:Workspace;source:{entry_id:string;source_sha256:string;content_sha256:string}};
const id=(v:unknown):v is string=>typeof v==='string'&&/^[A-Za-z0-9_+=/-]{1,2048}$/.test(v);
const text=(v:unknown,max:number):v is string=>typeof v==='string'&&Array.from(v).length<=max&&!/[\u0000-\u001f\u007f]/.test(v);
const account=(v:unknown)=>teamClosed(v,'label,email')&&text(v.label,256)&&!!v.label&&text(v.email,320)&&!!v.email;
const utc=(v:unknown):v is string=>modelTime(v)&&/(?:Z|\+00:00)$/.test(v);
export const microsoftCalendarKey=(v:unknown):v is string=>teamUuid(v);
export function validMicrosoftCalendarStatus(v:unknown):v is MicrosoftCalendarStatus {
 return teamClosed(v,'contract_version,state,calendar_read,account')&&v.contract_version===1&&['connected','sign_in_required'].includes(String(v.state))&&typeof v.calendar_read==='boolean'&&(v.state==='connected'?account(v.account):v.account===null&&v.calendar_read===false);
}
export function validMicrosoftCalendarWindow(v:unknown):v is MicrosoftCalendarWindow {
 return teamClosed(v,'starts_at,ends_at')&&utc(v.starts_at)&&utc(v.ends_at)&&Date.parse(v.ends_at)-Date.parse(v.starts_at)===7*86400000;
}
export function validMicrosoftCalendarEvent(v:unknown,window?:MicrosoftCalendarWindow):v is MicrosoftCalendarEvent {
 if(!teamClosed(v,'id,subject,starts_at,ends_at,all_day,cancelled')||!id(v.id)||!text(v.subject,998)||typeof v.all_day!=='boolean'||typeof v.cancelled!=='boolean')return false;
 return modelTime(v.starts_at)&&modelTime(v.ends_at)&&Date.parse(v.ends_at)>Date.parse(v.starts_at)&&(!window||Date.parse(v.ends_at)>Date.parse(window.starts_at)&&Date.parse(v.starts_at)<Date.parse(window.ends_at));
}
export function validMicrosoftCalendarObservation(v:unknown):v is MicrosoftCalendarObservation {
 return teamClosed(v,'kind,account,items,more,observed_at,window')&&v.kind==='calendar'&&account(v.account)&&typeof v.more==='boolean'&&utc(v.observed_at)&&validMicrosoftCalendarWindow(v.window)&&Date.parse(v.observed_at)>=Date.parse(v.window.starts_at)&&Date.parse(v.observed_at)<Date.parse(v.window.ends_at)&&Array.isArray(v.items)&&v.items.length<=25&&new Set(v.items.map(r=>r?.id)).size===v.items.length&&v.items.every(r=>validMicrosoftCalendarEvent(r,v.window as MicrosoftCalendarWindow));
}
export function validMicrosoftCalendarObserveRequest(v:unknown):v is MicrosoftCalendarObserveRequest {return teamClosed(v,'action,idempotency_key')&&v.action==='observe'&&microsoftCalendarKey(v.idempotency_key);}
export function validMicrosoftCalendarReviewRequest(v:unknown):v is MicrosoftCalendarReviewRequest {
 const fields='expected_revision,idempotency_key,observation_id,observation_sha256,event_id,event_sha256,reviewed_exact_summary,reviewed_untrusted_source';
 return (teamClosed(v,fields+',reviewed_visit')&&v.reviewed_visit===true)&&teamNatural(v.expected_revision)&&v.expected_revision>0&&v.expected_revision<2147483647&&microsoftCalendarKey(v.idempotency_key)&&teamUuid(v.observation_id)&&teamHash(v.observation_sha256)&&id(v.event_id)&&teamHash(v.event_sha256)&&v.reviewed_exact_summary===true&&v.reviewed_untrusted_source===true;
}
const sha=(s:string)=>vendorSha256(new TextEncoder().encode(s));
export const microsoftCalendarEventHash=(event:MicrosoftCalendarEvent)=>sha(modelCanonical(event));
export const microsoftCalendarReviewHash=(workspaceId:string,body:MicrosoftCalendarReviewRequest)=>sha(modelCanonical({workspace_id:workspaceId,...body}));
export const microsoftCalendarSourceHash=(receipt:MicrosoftCalendarReceipt,event:MicrosoftCalendarEvent)=>microsoftCalendarEventHash(event).then(event_sha256=>sha(modelCanonical({observation_sha256:receipt.source_sha256,event_id:event.id,event_sha256})));
// Graph returns exact instants even when an event has an all-day marker.
export const microsoftCalendarValidUntil=(observation:MicrosoftCalendarObservation,event:MicrosoftCalendarEvent)=>Math.min(Date.parse(observation.window.ends_at),Date.parse(event.ends_at));
export function microsoftCalendarSourceContent(observation:MicrosoftCalendarObservation,event:MicrosoftCalendarEvent):string {
 return `Outlook calendar summary (frozen observation)\nAccount: ${observation.account.label} <${observation.account.email}>\nEvent: ${event.subject}\nStarts: ${event.starts_at}\nEnds (exclusive): ${event.ends_at}\nAll day: ${event.all_day?'yes':'no'}\nStatus: ${event.cancelled?'cancelled':'not marked cancelled'}\nObserved: ${observation.observed_at}\nWindow: ${observation.window.starts_at} to ${observation.window.ends_at}\nCoverage: ${observation.more?'partial (more events available)':'up to 25 events in the primary calendar'}\n\nThis observed summary does not establish current availability or a booking.`;
}
export async function validMicrosoftCalendarReceipt(v:unknown):Promise<boolean> {
 return teamClosed(v,'contract_version,observation_id,observation_key,source_sha256,payload_sha256,observation')&&v.contract_version===1&&teamUuid(v.observation_id)&&microsoftCalendarKey(v.observation_key)&&teamHash(v.source_sha256)&&teamHash(v.payload_sha256)&&validMicrosoftCalendarObservation(v.observation)&&await sha(teamCanonical(v.observation))===v.payload_sha256;
}
export class MicrosoftCalendarRefusal extends WorkspaceApiError {constructor(status:number,code:string){super(status,code);this.name='MicrosoftCalendarRefusal';}}
export const microsoftCalendarServiceUnavailable=(e:unknown)=>e instanceof MicrosoftCalendarRefusal&&e.status===404&&e.code==='microsoft_calendar_unavailable';
const REFUSALS=new Set(['microsoft_calendar_consent_required','microsoft_calendar_grant_unavailable','microsoft_calendar_grant_changed','microsoft_calendar_source_invalid','microsoft_calendar_source_superseded','microsoft_calendar_source_expired','microsoft_calendar_source_changed','microsoft_calendar_observation_unconfirmed','microsoft_calendar_observation_unavailable','microsoft_calendar_observation_limit','microsoft_calendar_source_unavailable','invalid_microsoft_calendar_review','microsoft_calendar_not_observed','microsoft_calendar_patient_mismatch','microsoft_calendar_already_selected','workspace_revision_conflict','workspace_history_limit','idempotency_conflict','invalid_microsoft_calendar_request']);
export const microsoftCalendarReviewProvesNoCommit=(e:unknown)=>e instanceof MicrosoftCalendarRefusal&&['workspace_revision_conflict','microsoft_calendar_patient_mismatch','microsoft_calendar_already_selected','invalid_microsoft_calendar_request'].includes(e.code??'');
type Request=MicrosoftCalendarObserveRequest|MicrosoftCalendarReviewRequest|{action:'status'}|{action:'inspect';observation_id:string}|{action:'resolve';idempotency_key:string};
async function send<T>(identity:AuthenticatedWorkspaceIdentity,path:string,body:Request,validate:(value:unknown)=>Promise<T>,signal?:AbortSignal,large=false):Promise<T> {
  if(!MICROSOFT_CALENDAR_BUILD)throw new WorkspaceApiError(404);
  const base=workspaceApiBase(identity);
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
    headers.set('X-Cosmas-Microsoft-Calendar','1');headers.set('Accept','application/json');
    response=await wait(workspaceFetch(identity,base+path,{method:'POST',headers,body:encoded,signal:controller.signal,cache:'no-store',credentials:'omit',redirect:'error',referrerPolicy:'no-referrer'}));check();
    if([401,403,426].includes(response.status))throw new WorkspaceApiError(response.status);
    if(response.redirected||response.headers.has('content-encoding')||response.headers.get('content-type')?.split(';',1)[0].trim().toLowerCase()!=='application/json'||
      !response.headers.get('cache-control')?.split(',').some(v=>v.trim().toLowerCase()==='no-store'))throw new WorkspaceApiError(502);
    reader=response.body?.getReader();if(!reader)throw new WorkspaceApiError(502);const cap=response.ok?(large?MODEL_WORKSPACE_BYTES:131072):2048;
    const chunks:Uint8Array[]=[];let size=0;
    for(;;){const part=await wait(reader.read());check();if(part.done)break;size+=part.value.length;if(size>cap)throw new WorkspaceApiError(502);chunks.push(part.value);}
    const bytes=new Uint8Array(size);let at=0;for(const chunk of chunks){bytes.set(chunk,at);at+=chunk.length;}
    let value:unknown;try{value=parseVendorJson(new TextDecoder('utf-8',{fatal:true}).decode(bytes));}catch{throw new WorkspaceApiError(502);}
    if(response.status===404&&teamClosed(value,'detail')&&value.detail==='microsoft_calendar_unavailable')throw new MicrosoftCalendarRefusal(404,value.detail);
    if(response.status!==200){if([400,409,422].includes(response.status)&&teamClosed(value,'detail')&&typeof value.detail==='string'&&REFUSALS.has(value.detail))throw new MicrosoftCalendarRefusal(response.status,value.detail);throw new WorkspaceApiError(response.status);}
    const result=await wait(validate(value));check();return result;
  }catch(error){
    // Only a validated named service refusal narrows a404. Malformed or unknown
    // responses retain the existing authority-denial behavior.
    if(response?.status===404&&!microsoftCalendarServiceUnavailable(error)&&!(error instanceof WorkspaceApiError&&[401,403,426].includes(error.status)))throw new WorkspaceApiError(404);
    if(error instanceof WorkspaceApiError)throw error;throw new WorkspaceApiError(503);}
  finally{clearTimeout(timer);signal?.removeEventListener('abort',abort);controller.signal.removeEventListener('abort',rejectAbort);cancel(reader??response?.body);try{reader?.releaseLock();}catch{/* Discarded read may settle. */}controller.abort();}
}
const invalid=():never=>{throw new WorkspaceApiError(502);};
const receipt=async(v:unknown)=>await validMicrosoftCalendarReceipt(v)?v as MicrosoftCalendarReceipt:invalid();
export const microsoftCalendarApi={
 status:(identity:AuthenticatedWorkspaceIdentity,signal?:AbortSignal)=>send(identity,'/connections/microsoft/calendar-summaries',{action:'status'},async v=>validMicrosoftCalendarStatus(v)?v:invalid(),signal),
 observe:(identity:AuthenticatedWorkspaceIdentity,body:MicrosoftCalendarObserveRequest,signal?:AbortSignal)=>{
  if(!validMicrosoftCalendarObserveRequest(body))throw new WorkspaceApiError(422);return send(identity,'/connections/microsoft/calendar-summaries',body,async v=>{const r=await receipt(v);return r.observation_key===body.idempotency_key?r:invalid();},signal);},
 inspect:(identity:AuthenticatedWorkspaceIdentity,anchor:MicrosoftCalendarReceipt,signal?:AbortSignal)=>send(identity,'/connections/microsoft/calendar-summaries',{action:'inspect',observation_id:anchor.observation_id},async v=>{const r=await receipt(v);return modelCanonical(r)===modelCanonical(anchor)?r:invalid();},signal),
 resolve:(identity:AuthenticatedWorkspaceIdentity,key:string,signal?:AbortSignal)=>{
  if(!microsoftCalendarKey(key))throw new WorkspaceApiError(422);return send<MicrosoftCalendarReceipt|MicrosoftCalendarResolve>(identity,'/connections/microsoft/calendar-summaries',{action:'resolve',idempotency_key:key},async v=>{
   if(teamClosed(v,'status,observation_id,observation_key')&&v.observation_key===key&&(v.status==='not_found'?v.observation_id===null:v.status==='unconfirmed'&&teamUuid(v.observation_id)))return v as MicrosoftCalendarResolve;
   const r=await receipt(v);return r.observation_key===key?r:invalid();},signal);},
 review:async(identity:AuthenticatedWorkspaceIdentity,workspaceId:string,body:MicrosoftCalendarReviewRequest,anchor:MicrosoftCalendarReceipt,signal?:AbortSignal)=>{
  const event=anchor.observation.items.find(i=>i.id===body.event_id);
  if(!teamUuid(workspaceId)||!validMicrosoftCalendarReviewRequest(body)||!await validMicrosoftCalendarReceipt(anchor)||!event||body.event_sha256!==await microsoftCalendarEventHash(event)||anchor.observation_id!==body.observation_id||anchor.source_sha256!==body.observation_sha256)throw new WorkspaceApiError(422);
  return send(identity,`/workspaces/${workspaceId}/microsoft-calendar/review`,body,async v=>{
   const content=microsoftCalendarSourceContent(anchor.observation,event);
   if(body.event_sha256!==await microsoftCalendarEventHash(event)||!teamClosed(v,'entry_id,entry_revision,request_sha256,source_withheld,workspace,source')||!teamUuid(v.entry_id)||v.entry_revision!==body.expected_revision+1||!teamHash(v.request_sha256)||typeof v.source_withheld!=='boolean'||v.request_sha256!==await microsoftCalendarReviewHash(workspaceId,body)||!teamClosed(v.source,'entry_id,source_sha256,content_sha256')||v.source.entry_id!==v.entry_id||v.source.source_sha256!==await microsoftCalendarSourceHash(anchor,event)||v.source.content_sha256!==await sha(content)||!await validModelWorkspace(v.workspace,workspaceId))return invalid();
   const w=v.workspace as Workspace,e=w.entries.find(e=>e.id===v.entry_id);
   if(!v.source_withheld&&!w.appointment_id)return invalid();
   if(w.revision<Number(v.entry_revision)||!e||e.kind!=='microsoft_calendar'||e.revision!==v.entry_revision)return invalid();
   if(v.source_withheld){if(e.microsoft_calendar_source_state!=='unavailable'||e.content!==''||e.source_label!=='Unavailable Outlook calendar source')return invalid();}
   else if(e.microsoft_calendar_source_state!=='current'||e.content!==content||await sha(e.content)!==v.source.content_sha256)return invalid();
   return v as MicrosoftCalendarReviewResponse;
  },signal,true);},
};
