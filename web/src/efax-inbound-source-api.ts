import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity,type Workspace} from './workspace-api';
import {EFAX_INBOUND_BUILD} from './efax-inbound-api';
import {workspaceAuthHeaders,assertCurrentDesktopSession} from './workspace-auth-headers';
import {workspaceFetch} from './workspace-protocol';
import {permittedWorkspaceApi} from './workspace-origin';
import {teamClosed} from './team-setup-request';
import {vendorCanonical,vendorDigest,vendorSha256,vendorUuid,parseVendorJson} from './vendor-contract';

export const EFAX_INBOUND_SOURCE_BUILD=EFAX_INBOUND_BUILD&&import.meta.env.VITE_EFAX_INBOUND_SOURCE_ENABLED==='true';
export type EFaxSourceScope={box_id:string;owner_id:string;workspace_id:string};
export type EFaxSourceOffer={operation_id:string;document_sha256:string;pages:number;label?:string};
export type EFaxSourceVisit={id:string;label:string;revision:number};
export type EFaxSourceReviewRequest={expected_revision:number;idempotency_key:string;operation_id:string;document_sha256:string;passage:string;page_numbers:number[];
 reviewed_patient:true;reviewed_exact_document:true;reviewed_exact_text:true;reviewed_untrusted_source:true};
export type EFaxSourceReceipt={contract_version:1;scope:EFaxSourceScope;idempotency_key:string;request_sha256:string;review_id:string;entry_id:string;entry_revision:number;operation_id:string;source_sha256:string;content_sha256:string;document_sha256:string;page_numbers:number[];
 coverage:'human_selected_passage';extraction:'human_entered_no_ocr';source_withheld:boolean;state:'saved'};
export type EFaxSourceMissing={contract_version:1;scope:EFaxSourceScope;idempotency_key:string;state:'not_found'};
export const EFAX_SOURCE_LABEL='Received eFax: human-reviewed passage';
export const EFAX_SOURCE_WITHHELD_LABEL='Unavailable fax source';
export const efaxSourceKey=(v:unknown):v is string=>typeof v==='string'&&/^[A-Za-z0-9:_-]{8,100}$/.test(v);
export const efaxSourceHash=(v:unknown):v is string=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v);
const integer=(v:unknown,min:number,max:number):v is number=>typeof v==='number'&&Number.isInteger(v)&&v>=min&&v<=max;
const text=(v:unknown,max:number):v is string=>typeof v==='string'&&Array.from(v).length<=max&&!/[\u0000-\u0008\u000b-\u001f\u007f]/.test(v);
const invalid=():never=>{throw new WorkspaceApiError(502,'efax_inbound_source_response_invalid');};
export const validEFaxSourceScope=(v:unknown):v is EFaxSourceScope=>teamClosed(v,'box_id,owner_id,workspace_id')&&vendorUuid(v.box_id)&&vendorUuid(v.owner_id)&&vendorUuid(v.workspace_id);
export const validEFaxSourceOffer=(v:unknown):v is EFaxSourceOffer=>teamClosed(v,'operation_id,document_sha256,pages','label')&&vendorUuid(v.operation_id)&&efaxSourceHash(v.document_sha256)&&integer(v.pages,1,50)&&(!('label'in v)||text(v.label,160)&&!!v.label.trim()&&!/[\n\t]/.test(v.label));
export const validEFaxSourceVisit=(v:unknown):v is EFaxSourceVisit=>teamClosed(v,'id,label,revision')&&vendorUuid(v.id)&&text(v.label,320)&&!!v.label.trim()&&!/[\n\t]/.test(v.label)&&integer(v.revision,1,500);
export function validEFaxSourceReviewRequest(v:unknown):v is EFaxSourceReviewRequest{
 if(!teamClosed(v,'expected_revision,idempotency_key,operation_id,document_sha256,passage,page_numbers,reviewed_patient,reviewed_exact_document,reviewed_exact_text,reviewed_untrusted_source')||
 !integer(v.expected_revision,1,500)||!efaxSourceKey(v.idempotency_key)||!vendorUuid(v.operation_id)||!efaxSourceHash(v.document_sha256)||
 !text(v.passage,12000)||!v.passage.trim()||!Array.isArray(v.page_numbers)||!v.page_numbers.length||v.page_numbers.length>50||
 !v.page_numbers.every((p,i,a)=>integer(p,1,50)&&(i===0||p>a[i-1]))||
 !['reviewed_patient','reviewed_exact_document','reviewed_exact_text','reviewed_untrusted_source'].every(k=>v[k]===true))return false;
 try{vendorCanonical(v);return new TextEncoder().encode(JSON.stringify(v)).length<=65536;}catch{return false;}
}
export const efaxSourceRequestHash=(scope:EFaxSourceScope,request:EFaxSourceReviewRequest)=>vendorDigest('cosmas-efax-inbound-source-command.v1',{scope,request});
export async function verifyEFaxSourceReceipt(value:unknown,scope:EFaxSourceScope,request:EFaxSourceReviewRequest):Promise<EFaxSourceReceipt>{
 if(!validEFaxSourceScope(scope)||!validEFaxSourceReviewRequest(request)||
 !teamClosed(value,'contract_version,scope,idempotency_key,request_sha256,review_id,entry_id,entry_revision,operation_id,source_sha256,content_sha256,document_sha256,page_numbers,coverage,extraction,source_withheld,state')||
 value.contract_version!==1||!validEFaxSourceScope(value.scope)||vendorCanonical(value.scope)!==vendorCanonical(scope)||value.idempotency_key!==request.idempotency_key||
 !efaxSourceHash(value.request_sha256)||value.request_sha256!==await efaxSourceRequestHash(scope,request)||!vendorUuid(value.review_id)||!vendorUuid(value.entry_id)||
 value.entry_revision!==request.expected_revision+1||value.operation_id!==request.operation_id||value.document_sha256!==request.document_sha256||
 !efaxSourceHash(value.source_sha256)||!efaxSourceHash(value.content_sha256)||value.content_sha256!==await vendorSha256(new TextEncoder().encode(request.passage))||
 vendorCanonical(value.page_numbers)!==vendorCanonical(request.page_numbers)||value.coverage!=='human_selected_passage'||value.extraction!=='human_entered_no_ocr'||
 typeof value.source_withheld!=='boolean'||value.state!=='saved')return invalid();
 return value as EFaxSourceReceipt;
}
const REFUSALS=new Set(['efax_inbound_source_disabled','efax_inbound_source_unavailable','efax_inbound_source_invalid','efax_inbound_source_superseded',
 'efax_inbound_source_review_invalid','efax_inbound_source_changed','efax_inbound_source_document_changed','efax_inbound_source_patient_mismatch','efax_inbound_source_pages_invalid',
 'efax_inbound_grant_unavailable','efax_inbound_grant_changed','efax_inbound_disabled','workspace_revision_conflict','workspace_history_limit','idempotency_conflict']);
async function send(identity:AuthenticatedWorkspaceIdentity,scope:EFaxSourceScope,body:EFaxSourceReviewRequest|{idempotency_key:string},resolve:boolean,signal?:AbortSignal):Promise<unknown>{
 if(!EFAX_INBOUND_SOURCE_BUILD)throw new WorkspaceApiError(404);
 if(!validEFaxSourceScope(scope))throw new WorkspaceApiError(422);
 const base=import.meta.env.VITE_API_BASE?.trim().replace(/\/+$/,'')||'http://127.0.0.1:8000';
 if(!permittedWorkspaceApi(base,import.meta.env.VITE_DESKTOP_SYNTHETIC_ENABLED==='true',window.location.href))throw new WorkspaceApiError(503);
 const encoded=JSON.stringify(structuredClone(body));if(new TextEncoder().encode(encoded).length>(resolve?2048:65536))throw new WorkspaceApiError(422);
 const c=new AbortController(),abort=()=>c.abort();let rejectAbort:()=>void=()=>{};
 const interrupted=new Promise<never>((_,reject)=>{rejectAbort=()=>reject(new WorkspaceApiError(503));});void interrupted.catch(()=>{});
 c.signal.addEventListener('abort',rejectAbort,{once:true});signal?.addEventListener('abort',abort,{once:true});
 const timer=setTimeout(abort,50000),wait=<T,>(p:Promise<T>)=>Promise.race([p,interrupted]);
 let response:Response|undefined,reader:ReadableStreamDefaultReader<Uint8Array>|undefined;
 const check=()=>{if(c.signal.aborted)throw new WorkspaceApiError(503);assertCurrentDesktopSession(identity);if(identity.mode==='clerk_jwt'&&identity.nativeSession&&!identity.nativeSession.isCurrent())throw new WorkspaceApiError(401);};
 try{
  if(signal?.aborted)abort();check();const headers=await wait(workspaceAuthHeaders(identity,base).catch(()=>{throw new WorkspaceApiError(401);}));check();
  headers.set('X-Cosmas-EFax-Inbound','1');headers.set('Accept','application/json');
  response=await wait(workspaceFetch(identity,base+'/workspaces/'+scope.workspace_id+'/efax-inbound-source'+(resolve?'/resolve':''),{method:'POST',headers,body:encoded,signal:c.signal,cache:'no-store',credentials:'omit',redirect:'error',referrerPolicy:'no-referrer'}));check();
  if([401,403,404,426].includes(response.status))throw new WorkspaceApiError(response.status);
  if(response.redirected||response.headers.has('content-encoding')||response.headers.get('content-type')?.split(';',1)[0].trim().toLowerCase()!=='application/json'||
  !response.headers.get('cache-control')?.split(',').some(v=>v.trim().toLowerCase()==='no-store'))return invalid();
  reader=response.body?.getReader();if(!reader)return invalid();const chunks:Uint8Array[]=[];let count=0;
  for(;;){const next=await wait(reader.read());check();if(next.done)break;count+=next.value.length;if(count>(response.ok?16384:2048))return invalid();chunks.push(next.value);}
  const bytes=new Uint8Array(count);let at=0;for(const part of chunks){bytes.set(part,at);at+=part.length;}
  let value:unknown;try{value=parseVendorJson(new TextDecoder('utf-8',{fatal:true}).decode(bytes));}catch{return invalid();}
  if(response.status!==200){if([400,409,422].includes(response.status)&&teamClosed(value,'error')&&teamClosed(value.error,'code')&&typeof value.error.code==='string'&&REFUSALS.has(value.error.code))throw new WorkspaceApiError(response.status,value.error.code);throw new WorkspaceApiError(response.status);}
  check();return value;
 }catch(error){if(error instanceof WorkspaceApiError)throw error;throw new WorkspaceApiError(503);}
 finally{clearTimeout(timer);signal?.removeEventListener('abort',abort);c.signal.removeEventListener('abort',rejectAbort);try{void(reader??response?.body)?.cancel().catch(()=>{});}catch{/* Best effort. */}try{reader?.releaseLock();}catch{/* Pending reader. */}c.abort();}
}
export const efaxSourceApi={
 review:async(identity:AuthenticatedWorkspaceIdentity,scope:EFaxSourceScope,request:EFaxSourceReviewRequest,signal?:AbortSignal)=>{
  if(!validEFaxSourceReviewRequest(request))throw new WorkspaceApiError(422);
  return verifyEFaxSourceReceipt(await send(identity,scope,request,false,signal),scope,request);
 },
 resolve:async(identity:AuthenticatedWorkspaceIdentity,scope:EFaxSourceScope,request:EFaxSourceReviewRequest,signal?:AbortSignal):Promise<EFaxSourceReceipt|EFaxSourceMissing>=>{
  if(!validEFaxSourceReviewRequest(request))throw new WorkspaceApiError(422);
  const value=await send(identity,scope,{idempotency_key:request.idempotency_key},true,signal);
  if(teamClosed(value,'contract_version,scope,idempotency_key,state')&&value.contract_version===1&&validEFaxSourceScope(value.scope)&&vendorCanonical(value.scope)===vendorCanonical(scope)&&value.idempotency_key===request.idempotency_key&&value.state==='not_found')return value as EFaxSourceMissing;
  return verifyEFaxSourceReceipt(value,scope,request);
 },
};
export async function verifyEFaxSourceWorkspace(workspace:Workspace,receipt:EFaxSourceReceipt,request:EFaxSourceReviewRequest){
 const entry=workspace.entries.find(e=>e.id===receipt.entry_id);
 if(workspace.id!==receipt.scope.workspace_id||workspace.revision<receipt.entry_revision||!entry||entry.kind!=='efax_inbound_source'||entry.revision!==receipt.entry_revision||
 receipt.source_withheld||entry.fax_source_state!=='current'||entry.source_label!==EFAX_SOURCE_LABEL||entry.content!==request.passage||
 await vendorSha256(new TextEncoder().encode(entry.content))!==receipt.content_sha256)throw new WorkspaceApiError(409,'efax_inbound_source_unavailable');
 return entry;
}
