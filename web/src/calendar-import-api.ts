import {workspaceFetch} from './workspace-protocol';
import {permittedWorkspaceApi} from './workspace-origin';
import {workspaceAuthHeaders,assertCurrentDesktopSession} from './workspace-auth-headers';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity,type Workspace} from './workspace-api';
import {parseVendorJson} from './vendor-contract';
import {PERSONAL_CONNECTION_DEADLINE_MS} from './connection-operation-health';
import {modelCanonical,modelTime,validModelWorkspace,MODEL_WORKSPACE_BYTES} from './model-work-request';
import {teamClosed,teamHash,teamNatural,teamUuid} from './team-setup-request';
import {vendorSha256} from './vendor-contract';

export const CALENDAR_IMPORT_BUILD=import.meta.env.VITE_CALENDAR_IMPORT_ENABLED==='true';
export const CALENDAR_IMPORT_BYTES=1024*1024;
export type CalendarReportedSource='atlas_md'|'other_calendar';
export type CalendarImportWindow={starts_on:string;ends_on:string;timezone:string};
export type CalendarUploadIntent={action:'upload';idempotency_key:string;byte_sha256:string;reported_source:CalendarReportedSource;window:CalendarImportWindow};
export type CalendarUploadRequest=CalendarUploadIntent&{file_base64:string};
export type CalendarImportScope={box_id:string;owner_id:string;account_id:string;workspace_id:string;patient_link_id:string};
export type CalendarImportItem={item_index:number;title:string;title_truncated:boolean;starts_at:string;ends_at:string;all_day:boolean;cancelled:boolean};
export type CalendarImportPayload={imported_at:string;reported_source:CalendarReportedSource;window:CalendarImportWindow;items:CalendarImportItem[];total_events:number;matching_events:number;more:boolean;coverage:'file_window_only'};
export type CalendarReviewRequest={expected_revision:number;idempotency_key:string;import_id:string;source_sha256:string;item_index:number;item_sha256:string;reviewed_visit:true;reviewed_exact_summary:true;reviewed_untrusted_source:true};
export type CalendarRevokeRequest={action:'revoke';expected_revision:number;idempotency_key:string;import_id:string;source_sha256:string};
export const calendarHash=(value:unknown)=>vendorSha256(new TextEncoder().encode(modelCanonical(value)));
export const calendarBytesHash=(value:Uint8Array)=>vendorSha256(value);
export const calendarItemHash=(item:CalendarImportItem)=>calendarHash({kind:'calendar-import-item-v1',item});
export const calendarReviewHash=(workspaceId:string,body:CalendarReviewRequest)=>calendarHash({...body,action:'review',workspace_id:workspaceId});
export const calendarRevokeHash=(workspaceId:string,body:CalendarRevokeRequest)=>calendarHash({...body,workspace_id:workspaceId});
export const calendarSelectedHash=(importHash:string,item:CalendarImportItem)=>calendarItemHash(item).then(itemHash=>calendarHash({kind:'calendar-import-selected-v1',import_sha256:importHash,item_index:item.item_index,item_sha256:itemHash}));
export const calendarKey=(value:unknown):value is string=>typeof value==='string'&&/^[A-Za-z0-9:_-]{8,100}$/.test(value);
export const calendarDate=(value:unknown):value is string=>typeof value==='string'&&/^\d{4}-\d\d-\d\d$/.test(value)&&modelTime(value+'T00:00:00Z')&&value>='1900-01-01'&&value<='2100-12-31';
export function calendarWeekEnd(start:string):string|null {if(!calendarDate(start))return null;try{const end=new Date(Date.parse(start+'T00:00:00Z')+7*86400000).toISOString().slice(0,10);return calendarDate(end)?end:null;}catch{return null;}}
export function validCalendarWindow(value:unknown):value is CalendarImportWindow {
 if(!teamClosed(value,'starts_on,ends_on,timezone')||!calendarDate(value.starts_on)||value.ends_on!==calendarWeekEnd(value.starts_on)||typeof value.timezone!=='string'||value.timezone.length>128||!value.timezone)return false;
 try{new Intl.DateTimeFormat('en',{timeZone:value.timezone});return true;}catch{return false;}
}
export const validCalendarScope=(value:unknown):value is CalendarImportScope=>teamClosed(value,'box_id,owner_id,account_id,workspace_id,patient_link_id')&&teamUuid(value.box_id)&&teamUuid(value.owner_id)&&teamUuid(value.account_id)&&teamUuid(value.workspace_id)&&teamUuid(value.patient_link_id);
const stamp=(value:unknown):value is string=>typeof value==='string'&&/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$/.test(value)&&modelTime(value);
/** Round-trip local midnight instead of assuming every civil week has 168 hours. */
export function calendarMidnight(day:string,timezone:string):number {
 if(!calendarDate(day))throw new Error('Invalid calendar date.');
 const wall=Date.parse(day+'T00:00:00Z'),formatter=new Intl.DateTimeFormat('en-CA',{timeZone:timezone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'});
 let guess=wall;for(let attempt=0;attempt<4;attempt++){const parts=Object.fromEntries(formatter.formatToParts(new Date(guess)).map(p=>[p.type,p.value]));const shown=Date.parse(`${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}:${parts.second}Z`);if(shown===wall)return guess;guess+=wall-shown;}
 throw new Error('This calendar date could not be read in the chosen timezone.');
}
function validItem(value:unknown):value is CalendarImportItem {
 if(!teamClosed(value,'item_index,title,title_truncated,starts_at,ends_at,all_day,cancelled')||!teamNatural(value.item_index)||value.item_index>=500||typeof value.title!=='string'||Array.from(value.title).length>300||typeof value.title_truncated!=='boolean'||value.title_truncated&&Array.from(value.title).length!==300||typeof value.all_day!=='boolean'||typeof value.cancelled!=='boolean')return false;
 if(/\p{C}/u.test(value.title)||/\p{C}/u.test(value.title.normalize('NFKC'))||/%[0-9a-fA-F]{2}|&[^\s;]+;/.test(value.title.normalize('NFKC'))||/(?:[a-z][a-z0-9+.-]*:(?=\S)|[a-z][a-z0-9+.-]*\s*:\s*\/\/|\/\/|\\\\|\bwww\.)/i.test(value.title.normalize('NFKC')))return false;
 if(value.all_day? !calendarDate(value.starts_at)||!calendarDate(value.ends_at):!stamp(value.starts_at)||!stamp(value.ends_at)||value.starts_at<'1900'||value.ends_at>='2101')return false;
 return String(value.ends_at)>String(value.starts_at);
}
export function validCalendarPayload(value:unknown):value is CalendarImportPayload {
 if(!teamClosed(value,'imported_at,reported_source,window,items,total_events,matching_events,more,coverage')||!stamp(value.imported_at)||!['atlas_md','other_calendar'].includes(String(value.reported_source))||!validCalendarWindow(value.window)||!Array.isArray(value.items)||value.items.length>25||!teamNatural(value.total_events)||value.total_events>500||!teamNatural(value.matching_events)||value.matching_events>value.total_events||value.items.length!==Math.min(value.matching_events,25)||value.more!==(value.matching_events>25)||value.coverage!=='file_window_only')return false;
 try{const start=calendarMidnight(value.window.starts_on,value.window.timezone),end=calendarMidnight(value.window.ends_on,value.window.timezone),seen=new Set<number>();let order=-Infinity,index=-1;
  for(const row of value.items){if(!validItem(row)||row.item_index>=value.total_events||seen.has(row.item_index))return false;seen.add(row.item_index);
   const at=row.all_day?calendarMidnight(row.starts_at,value.window.timezone):Date.parse(row.starts_at);
   if(row.all_day?row.starts_at>=value.window.ends_on||row.ends_at<=value.window.starts_on:at>=end||Date.parse(row.ends_at)<=start)return false;
   if(at<order||at===order&&row.item_index<index)return false;order=at;index=row.item_index;
  }return true;
 }catch{return false;}
}
export function validCalendarReview(value:unknown):value is CalendarReviewRequest {
 return teamClosed(value,'expected_revision,idempotency_key,import_id,source_sha256,item_index,item_sha256,reviewed_visit,reviewed_exact_summary,reviewed_untrusted_source')&&teamNatural(value.expected_revision)&&value.expected_revision>0&&calendarKey(value.idempotency_key)&&teamUuid(value.import_id)&&teamHash(value.source_sha256)&&teamNatural(value.item_index)&&value.item_index<500&&teamHash(value.item_sha256)&&value.reviewed_visit===true&&value.reviewed_exact_summary===true&&value.reviewed_untrusted_source===true;
}
export function validCalendarRevoke(value:unknown):value is CalendarRevokeRequest {
 return teamClosed(value,'action,expected_revision,idempotency_key,import_id,source_sha256')&&value.action==='revoke'&&teamNatural(value.expected_revision)&&value.expected_revision>0&&calendarKey(value.idempotency_key)&&teamUuid(value.import_id)&&teamHash(value.source_sha256);
}
export function validCalendarUploadIntent(value:unknown):value is CalendarUploadIntent {
 return teamClosed(value,'action,idempotency_key,byte_sha256,reported_source,window')&&value.action==='upload'&&calendarKey(value.idempotency_key)&&teamHash(value.byte_sha256)&&['atlas_md','other_calendar'].includes(String(value.reported_source))&&validCalendarWindow(value.window);
}
/** File bytes, file names and feed URLs are never part of this retained intent. */
export const calendarUploadHash=(workspaceId:string,intent:CalendarUploadIntent)=>{
 if(!teamUuid(workspaceId)||!validCalendarUploadIntent(intent))throw new Error('Invalid calendar import request.');
 return calendarHash({kind:'calendar-import-v1',workspace_id:workspaceId,...intent});
};
export function calendarBase64(bytes:Uint8Array):string {
 if(bytes.byteLength<1||bytes.byteLength>CALENDAR_IMPORT_BYTES)throw new Error('Choose a calendar file no larger than 1 MB.');
 let value='';for(let at=0;at<bytes.length;at+=16384)value+=String.fromCharCode(...bytes.subarray(at,at+16384));return btoa(value);
}

export type CalendarImportStatus={status:'available'|'unavailable';scope:CalendarImportScope;file_limit_bytes:1048576;max_items:25;formats:['ics'];reported_sources:['atlas_md','other_calendar']};
type CalendarCommitment={scope:CalendarImportScope;import_id:string;idempotency_key:string;request_sha256:string;byte_sha256:string;source_sha256:string};
export type CalendarImported=CalendarCommitment&{status:'imported';payload_sha256:string;payload:CalendarImportPayload};
export type CalendarWithheld=CalendarCommitment&{status:'withheld'};
export type CalendarImportReceipt=CalendarImported|CalendarWithheld;
export type CalendarNotFound={status:'not_found';scope:CalendarImportScope;workspace_id:string;idempotency_key:string};
export type CalendarImportListItem={reviewed_item_indices:number[];import_id:string;idempotency_key:string;byte_sha256:string;request_sha256:string;source_sha256:string;reported_source:CalendarReportedSource;window:CalendarImportWindow;imported_at:string;status:'imported'|'withheld'};
export type CalendarImportList={status:'listed';scope:CalendarImportScope;imports:CalendarImportListItem[];more:false};
export type CalendarReviewResponse={entry_id:string;entry_revision:number;workspace:Workspace;source:{entry_id:string;source_sha256:string;content_sha256:string};request_sha256:string;source_withheld:boolean};
export type CalendarRevokeResponse={status:'revoked';scope:CalendarImportScope;import_id:string;idempotency_key:string;request_sha256:string;source_sha256:string;workspace:Workspace};
export const sameCalendarScope=(a:CalendarImportScope,b:CalendarImportScope)=>modelCanonical(a)===modelCanonical(b);
export function validCalendarStatus(value:unknown):value is CalendarImportStatus {
 return teamClosed(value,'status,scope,file_limit_bytes,max_items,formats,reported_sources')&&['available','unavailable'].includes(String(value.status))&&validCalendarScope(value.scope)&&value.file_limit_bytes===CALENDAR_IMPORT_BYTES&&value.max_items===25&&modelCanonical(value.formats)==='["ics"]'&&modelCanonical(value.reported_sources)==='["atlas_md","other_calendar"]';
}
export async function validCalendarReceipt(value:unknown):Promise<boolean>{
 if(!teamClosed(value,'status,scope,import_id,idempotency_key,request_sha256,byte_sha256,source_sha256',(value as {status?:unknown}|null)?.status==='imported'?'payload_sha256,payload':'')||!['imported','withheld'].includes(String(value.status))||!validCalendarScope(value.scope)||!teamUuid(value.import_id)||!calendarKey(value.idempotency_key)||!teamHash(value.request_sha256)||!teamHash(value.byte_sha256)||!teamHash(value.source_sha256))return false;
 if(value.status==='withheld')return true;
 if(!validCalendarPayload(value.payload)||!teamHash(value.payload_sha256)||value.payload_sha256!==await calendarHash(value.payload))return false;
 return value.source_sha256===await calendarHash({kind:'calendar-import-snapshot-v1',import_id:value.import_id,...value.scope,request_sha256:value.request_sha256,payload_sha256:value.payload_sha256})&&value.request_sha256===await calendarUploadHash(value.scope.workspace_id,{action:'upload',idempotency_key:value.idempotency_key,byte_sha256:value.byte_sha256,reported_source:value.payload.reported_source,window:value.payload.window});
}
export async function calendarMatchesUpload(value:CalendarImportReceipt,scope:CalendarImportScope,intent:CalendarUploadIntent):Promise<boolean>{
 return sameCalendarScope(value.scope,scope)&&value.idempotency_key===intent.idempotency_key&&value.byte_sha256===intent.byte_sha256&&value.request_sha256===await calendarUploadHash(scope.workspace_id,intent);
}
export function calendarSourceContent(payload:CalendarImportPayload,item:CalendarImportItem):string {
 const window=payload.window;
 return ['Imported calendar snapshot','Source reported by user: '+(payload.reported_source==='atlas_md'?'Atlas.md':'Other calendar'),'Imported at: '+payload.imported_at,'Title: '+(item.title||'(Untitled event)'),'Title truncated: '+(item.title_truncated?'yes':'no'),'Starts: '+item.starts_at,'Ends (exclusive): '+item.ends_at,'All day: '+(item.all_day?'yes':'no'),'Status: '+(item.cancelled?'Cancelled':'Not marked cancelled'),'Window: '+window.starts_on+' through '+window.ends_on+' (end date excluded); timezone '+window.timezone,'Coverage: Showing '+payload.items.length+' of '+payload.matching_events+' matching events in the supplied file. Other appointments may be missing.','This staff-supplied calendar summary does not verify patient or chart identity, current availability, or a booking.'].join('\n');
}
export async function calendarReviewMatches(body:CalendarReviewRequest,anchor:CalendarImported):Promise<boolean>{
 const item=anchor.payload.items.find(item=>item.item_index===body.item_index);
 return validCalendarReview(body)&&body.import_id===anchor.import_id&&body.source_sha256===anchor.source_sha256&&!!item&&!item.cancelled&&body.item_sha256===await calendarItemHash(item);
}
export class CalendarImportRefusal extends WorkspaceApiError {constructor(status:number,code:string){super(status,code);this.name='CalendarImportRefusal';}}
const REFUSALS=new Set(['invalid_calendar_import_request','invalid_calendar_import_review','calendar_file_mismatch','calendar_import_limit','calendar_import_unavailable','calendar_import_source_invalid','calendar_import_source_unavailable','calendar_import_source_changed','calendar_import_cancelled','calendar_import_already_selected','calendar_file_too_large','calendar_file_invalid','calendar_window_invalid','calendar_event_limit','calendar_structure_limit','calendar_duplicate_uid','calendar_recurrence_unsupported','calendar_floating_time','calendar_timezone_invalid','calendar_timezone_conflict','calendar_uri_in_title','calendar_event_invalid','calendar_parser_unavailable','idempotency_conflict','workspace_revision_conflict','workspace_history_limit']);
export const calendarReviewProvesNoCommit=(e:unknown)=>e instanceof CalendarImportRefusal&&['workspace_revision_conflict','invalid_calendar_import_review','calendar_import_cancelled','calendar_import_already_selected'].includes(e.code??'');
async function send<T>(identity:AuthenticatedWorkspaceIdentity,path:string,body:object,validate:(value:unknown)=>Promise<T>,signal?:AbortSignal,large=false):Promise<T> {
  if(!CALENDAR_IMPORT_BUILD||identity.mode!=='clerk_jwt')throw new WorkspaceApiError(404);
  const base=import.meta.env.VITE_API_BASE?.trim().replace(/\/+$/,'')||'http://127.0.0.1:8000';
  if(!permittedWorkspaceApi(base,import.meta.env.VITE_DESKTOP_SYNTHETIC_ENABLED==='true',window.location.href))throw new WorkspaceApiError(503);
  const encoded=JSON.stringify(Object.freeze({...body}));if(new TextEncoder().encode(encoded).length>1500000)throw new WorkspaceApiError(422);
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
    headers.set('X-Cosmas-Calendar-Import','1');headers.set('Accept','application/json');
    response=await wait(workspaceFetch(identity,base+path,{method:'POST',headers,body:encoded,signal:controller.signal,cache:'no-store',credentials:'omit',redirect:'error',referrerPolicy:'no-referrer'}));check();
    if([401,403,404,426].includes(response.status))throw new WorkspaceApiError(response.status);
    if(response.redirected||response.headers.has('content-encoding')||response.headers.get('content-type')?.split(';',1)[0].trim().toLowerCase()!=='application/json'||
      !response.headers.get('cache-control')?.split(',').some(v=>v.trim().toLowerCase()==='no-store'))throw new WorkspaceApiError(502);
    reader=response.body?.getReader();if(!reader)throw new WorkspaceApiError(502);const cap=response.ok?(large?MODEL_WORKSPACE_BYTES:131072):2048;
    const chunks:Uint8Array[]=[];let size=0;
    for(;;){const part=await wait(reader.read());check();if(part.done)break;size+=part.value.length;if(size>cap)throw new WorkspaceApiError(502);chunks.push(part.value);}
    const bytes=new Uint8Array(size);let at=0;for(const chunk of chunks){bytes.set(chunk,at);at+=chunk.length;}
    let value:unknown;try{value=parseVendorJson(new TextDecoder('utf-8',{fatal:true}).decode(bytes));}catch{throw new WorkspaceApiError(502);}
    if(response.status!==200){if([400,409,422,429,502,503].includes(response.status)&&teamClosed(value,'detail')&&typeof value.detail==='string'&&REFUSALS.has(value.detail))throw new CalendarImportRefusal(response.status,value.detail);throw new WorkspaceApiError(response.status);}
    const result=await wait(validate(value));check();return result;
  }catch(error){if(error instanceof WorkspaceApiError)throw error;throw new WorkspaceApiError(503);}
  finally{clearTimeout(timer);signal?.removeEventListener('abort',abort);controller.signal.removeEventListener('abort',rejectAbort);cancel(reader??response?.body);try{reader?.releaseLock();}catch{/* Discarded read may settle. */}controller.abort();}
}

const invalid=():never=>{throw new WorkspaceApiError(502,'calendar_import_response_invalid');};
export async function verifyCalendarReview(value:unknown,body:CalendarReviewRequest,anchor:CalendarImported):Promise<CalendarReviewResponse>{
 const wid=anchor.scope.workspace_id,item=anchor.payload.items.find(item=>item.item_index===body.item_index);
 if(!await calendarReviewMatches(body,anchor)||!item||!teamClosed(value,'entry_id,entry_revision,workspace,source,request_sha256,source_withheld')||!teamUuid(value.entry_id)||value.entry_revision!==body.expected_revision+1||value.request_sha256!==await calendarReviewHash(wid,body)||typeof value.source_withheld!=='boolean'||!teamClosed(value.source,'entry_id,source_sha256,content_sha256')||value.source.entry_id!==value.entry_id||value.source.source_sha256!==await calendarSelectedHash(anchor.source_sha256,item)||value.source.content_sha256!==await calendarBytesHash(new TextEncoder().encode(calendarSourceContent(anchor.payload,item)))||!await validModelWorkspace(value.workspace,wid))return invalid();
 const workspace=value.workspace as Workspace,entry=workspace.entries.find(entry=>entry.id===value.entry_id);
 if(!entry||entry.revision!==value.entry_revision||entry.kind!=='calendar_import_source')return invalid();
 if(value.source_withheld?entry.calendar_import_source_state!=='unavailable'||entry.content!==''||entry.source_label!=='Unavailable calendar import':entry.calendar_import_source_state!=='current'||entry.content!==calendarSourceContent(anchor.payload,item)||entry.source_label!=='Imported calendar snapshot')return invalid();
 return value as CalendarReviewResponse;
}
const path=(wid:string)=>{if(!teamUuid(wid))throw new WorkspaceApiError(422);return `/workspaces/${wid}/calendar-imports`;};
const receipt=async(value:unknown)=>await validCalendarReceipt(value)?value as CalendarImportReceipt:invalid();
export async function validCalendarListItem(value:unknown,scope:CalendarImportScope):Promise<boolean>{
 if(!teamClosed(value,'reviewed_item_indices,import_id,idempotency_key,byte_sha256,request_sha256,source_sha256,reported_source,window,imported_at,status')||!Array.isArray(value.reviewed_item_indices)||value.reviewed_item_indices.length>25||value.reviewed_item_indices.some((n,i,a)=>!teamNatural(n)||n>=500||i>0&&n<=a[i-1])||!teamUuid(value.import_id)||!calendarKey(value.idempotency_key)||!teamHash(value.byte_sha256)||!teamHash(value.request_sha256)||!teamHash(value.source_sha256)||!['atlas_md','other_calendar'].includes(String(value.reported_source))||!validCalendarWindow(value.window)||!stamp(value.imported_at)||!['imported','withheld'].includes(String(value.status)))return false;
 return value.request_sha256===await calendarUploadHash(scope.workspace_id,{action:'upload',idempotency_key:value.idempotency_key,byte_sha256:value.byte_sha256,reported_source:value.reported_source as CalendarReportedSource,window:value.window});
}
export const calendarImportApi={
 list:(identity:AuthenticatedWorkspaceIdentity,scope:CalendarImportScope,signal?:AbortSignal)=>{if(!validCalendarScope(scope))throw new WorkspaceApiError(422);return send(identity,path(scope.workspace_id),{action:'list'},async value=>{
  if(!teamClosed(value,'status,scope,imports,more')||value.status!=='listed'||!validCalendarScope(value.scope)||!sameCalendarScope(value.scope,scope)||value.more!==false||!Array.isArray(value.imports)||value.imports.length>100)return invalid();
  const ids=new Set<string>(),keys=new Set<string>();let order='';for(const row of value.imports){if(!await validCalendarListItem(row,scope))return invalid();const item=row as CalendarImportListItem,next=item.imported_at+':'+item.import_id;if(ids.has(item.import_id)||keys.has(item.idempotency_key)||next<order)return invalid();ids.add(item.import_id);keys.add(item.idempotency_key);order=next;}
  return value as CalendarImportList;
 },signal);},
 inspectListed:async(identity:AuthenticatedWorkspaceIdentity,scope:CalendarImportScope,item:CalendarImportListItem,signal?:AbortSignal)=>{if(!validCalendarScope(scope)||!await validCalendarListItem(item,scope))throw new WorkspaceApiError(422);return send(identity,path(scope.workspace_id),{action:'inspect',import_id:item.import_id},async value=>{const r=await receipt(value);return (r.status==='withheld'||item.reviewed_item_indices.every(index=>r.payload.items.some(row=>row.item_index===index&&!row.cancelled)))&&r.import_id===item.import_id&&r.source_sha256===item.source_sha256&&(item.status!=='withheld'||r.status==='withheld')&&await calendarMatchesUpload(r,scope,{action:'upload',idempotency_key:item.idempotency_key,byte_sha256:item.byte_sha256,reported_source:item.reported_source,window:item.window})?r:invalid();},signal);},

 status:(identity:AuthenticatedWorkspaceIdentity,wid:string,signal?:AbortSignal)=>send(identity,path(wid),{action:'status'},async value=>validCalendarStatus(value)&&value.scope.workspace_id===wid?value:invalid(),signal),
 upload:async(identity:AuthenticatedWorkspaceIdentity,scope:CalendarImportScope,intent:CalendarUploadIntent,fileBase64:string,signal?:AbortSignal)=>{
  if(!validCalendarScope(scope)||!validCalendarUploadIntent(intent)||typeof fileBase64!=='string'||fileBase64.length<4||fileBase64.length>1398104)throw new WorkspaceApiError(422);
  return send(identity,path(scope.workspace_id),{...intent,file_base64:fileBase64},async value=>{const r=await receipt(value);return await calendarMatchesUpload(r,scope,intent)?r:invalid();},signal);
 },
 resolve:(identity:AuthenticatedWorkspaceIdentity,scope:CalendarImportScope,intent:CalendarUploadIntent,signal?:AbortSignal)=>{if(!validCalendarScope(scope)||!validCalendarUploadIntent(intent))throw new WorkspaceApiError(422);return send<CalendarImportReceipt|CalendarNotFound>(identity,path(scope.workspace_id),{action:'resolve',idempotency_key:intent.idempotency_key},async value=>{
  if(teamClosed(value,'status,scope,workspace_id,idempotency_key')&&value.status==='not_found'&&validCalendarScope(value.scope)&&sameCalendarScope(value.scope,scope)&&value.workspace_id===scope.workspace_id&&value.idempotency_key===intent.idempotency_key)return value as CalendarNotFound;
  const r=await receipt(value);return await calendarMatchesUpload(r,scope,intent)?r:invalid();
 },signal);},
 inspect:async(identity:AuthenticatedWorkspaceIdentity,anchor:CalendarImportReceipt,signal?:AbortSignal)=>{if(!await validCalendarReceipt(anchor))throw new WorkspaceApiError(422);return send(identity,path(anchor.scope.workspace_id),{action:'inspect',import_id:anchor.import_id},async value=>{
  const r=await receipt(value);for(const key of ['scope','import_id','idempotency_key','request_sha256','byte_sha256','source_sha256'] as const)if(modelCanonical(r[key])!==modelCanonical(anchor[key]))return invalid();
  if(anchor.status==='withheld'&&r.status!=='withheld'||anchor.status==='imported'&&r.status==='imported'&&modelCanonical(r)!==modelCanonical(anchor))return invalid();return r;
 },signal);},
 review:async(identity:AuthenticatedWorkspaceIdentity,body:CalendarReviewRequest,anchor:CalendarImported,signal?:AbortSignal)=>{if(!await validCalendarReceipt(anchor)||!await calendarReviewMatches(body,anchor))throw new WorkspaceApiError(422);return send(identity,path(anchor.scope.workspace_id)+'/review',body,value=>verifyCalendarReview(value,body,anchor),signal,true);},
 revoke:async(identity:AuthenticatedWorkspaceIdentity,body:CalendarRevokeRequest,anchor:CalendarImportReceipt,signal?:AbortSignal)=>{
  if(!validCalendarRevoke(body)||!await validCalendarReceipt(anchor)||body.import_id!==anchor.import_id||body.source_sha256!==anchor.source_sha256)throw new WorkspaceApiError(422);
  return send(identity,path(anchor.scope.workspace_id),body,async value=>{
   if(!teamClosed(value,'status,scope,import_id,idempotency_key,request_sha256,source_sha256,workspace')||value.status!=='revoked'||!validCalendarScope(value.scope)||!sameCalendarScope(value.scope,anchor.scope)||value.import_id!==body.import_id||value.idempotency_key!==body.idempotency_key||value.source_sha256!==body.source_sha256||value.request_sha256!==await calendarRevokeHash(anchor.scope.workspace_id,body)||!await validModelWorkspace(value.workspace,anchor.scope.workspace_id)||(value.workspace as Workspace).revision<body.expected_revision)return invalid();
   return value as CalendarRevokeResponse;
  },signal,true);
 },
};
