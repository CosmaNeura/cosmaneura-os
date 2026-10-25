import {workspaceFetch} from './workspace-protocol';
import {permittedWorkspaceApi} from './workspace-origin';
import {workspaceAuthHeaders,assertCurrentDesktopSession} from './workspace-auth-headers';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity,type Workspace} from './workspace-api';
import {modelCanonical,modelTime,validModelWorkspace,MODEL_WORKSPACE_BYTES} from './model-work-request';
import {teamClosed,teamHash,teamNatural,teamUuid} from './team-setup-request';
import {parseVendorJson,vendorSha256} from './vendor-contract';
import {PERSONAL_CONNECTION_DEADLINE_MS} from './connection-operation-health';

export const EHR_READ_BUILD=import.meta.env.VITE_EHR_READ_ENABLED==='true';
export type EhrProvider='elation'|'tebra';
export const ehrProvider=(value:{provider?:EhrProvider}):EhrProvider=>value.provider??'elation';
export const ehrProviderName=(provider:EhrProvider)=>provider==='tebra'?'Tebra':'Elation';
export const ehrProviderFields=(provider:EhrProvider):{provider:'tebra'}|Record<string,never>=>provider==='tebra'?{provider:'tebra'}:{};
export type EhrPractice={label:string;timezone:string};
export type EhrTransport='mock'|'vendor_sandbox';
export type EhrInstallation={id:string;sha256:string};
export const ehrTransport=(value:{transport?:EhrTransport}):EhrTransport=>value.transport??'mock';
export const ehrTransportLabel=(value:{transport?:EhrTransport;provider?:EhrProvider})=>ehrProvider(value)==='tebra'?'Local example — invented Tebra records':ehrTransport(value)==='vendor_sandbox'?'Elation sandbox — invented test data':'Local example';
export type EhrInstallRequest={action:'install';installation_id:string;installation_sha256:string;idempotency_key:string};
export type EhrInstallReceipt={contract_version:1;status:'installed'|'unavailable';transport:'vendor_sandbox';installation_id:string;installation_sha256:string;connection_id:string;binding_sha256:string;idempotency_key:string;request_sha256:string};
export type EhrReadStatus={contract_version:1;provider:EhrProvider;mode:'synthetic';status:'not_enabled'|'not_configured'|'setup_required'|'ready';transport?:EhrTransport;installation?:EhrInstallation|null;connection_id:string|null;binding_sha256:string|null;practice:EhrPractice|null};
export type EhrWindow={starts_at:string;ends_at:string};
export type EhrWindowItem={handle:string;sha256:string;starts_at:string;ends_at:string;status:string|null;selectable:boolean};
export type EhrPatient={first_name:string;last_name:string;birth_date:string}|{full_name:string;birth_date:string};
export const ehrPatientName=(patient:EhrPatient)=>'full_name' in patient?patient.full_name:patient.first_name+' '+patient.last_name;
export type EhrVerifiedItem={handle:string;sha256:string;starts_at:string;ends_at:string;status:string|null;patient:EhrPatient};
type ObservationBase={provider:EhrProvider;mode:'synthetic';practice:EhrPractice;observed_at:string;window:EhrWindow;coverage:'end_of_results'|'more_rows_available'|'returned_rows_only'};
export type EhrWindowObservation=ObservationBase&{kind:'window';items:EhrWindowItem[]};
export type EhrVerifiedObservation=ObservationBase&{kind:'verified_visit';item:EhrVerifiedItem};
export type EhrObservation=EhrWindowObservation|EhrVerifiedObservation;
export type EhrReceipt={contract_version:1;provider?:EhrProvider;transport?:EhrTransport;connection_id:string;binding_sha256:string;observation_id:string;observation_key:string;source_sha256:string;payload_sha256:string;observation:EhrObservation};
export type EhrResolve={provider?:EhrProvider;status:'not_found'|'unconfirmed';observation_id:string|null;observation_key:string};
export type EhrObserveRequest={provider?:EhrProvider;action:'observe';connection_id:string;binding_sha256:string;starts_at:string;ends_at:string;idempotency_key:string};
export type EhrVerifyRequest={provider?:EhrProvider;last_name?:string;birth_date?:string;action:'verify';connection_id:string;binding_sha256:string;observation_id:string;observation_sha256:string;item_handle:string;item_sha256:string;idempotency_key:string};
export type EhrReviewRequest={provider?:EhrProvider;expected_revision:number;idempotency_key:string;observation_id:string;observation_sha256:string;item_handle:string;item_sha256:string;reviewed_visit:true;reviewed_patient_identity:true;reviewed_exact_snapshot:true;reviewed_untrusted_source:true};
export type EhrReviewResponse={provider?:EhrProvider;transport?:EhrTransport;entry_id:string;entry_revision:number;request_sha256:string;source_withheld:boolean;workspace:Workspace;source:{entry_id:string;source_sha256:string;content_sha256:string}};
export type EhrCommand=EhrObserveRequest|EhrVerifyRequest;
type EhrRequest=EhrCommand|EhrReviewRequest|EhrInstallRequest|{action:'status';provider?:EhrProvider}|{action:'inspect';observation_id:string;provider?:EhrProvider}|{action:'resolve';idempotency_key:string;provider?:EhrProvider};
const text=(v:unknown,max:number):v is string=>typeof v==='string'&&Array.from(v).length<=max&&!!v.trim()&&!/[\u0000-\u001f\u007f]/.test(v);
const practice=(v:unknown):v is EhrPractice=>{if(!teamClosed(v,'label,timezone')||!text(v.label,200)||!text(v.timezone,100))return false;try{new Intl.DateTimeFormat('en',{timeZone:v.timezone});return true;}catch{return false;}};
export const ehrKey=(v:unknown):v is string=>typeof v==='string'&&/^[A-Za-z0-9:_-]{8,100}$/.test(v);
const statuses=['Scheduled','Confirmed','Checked Out','Cancelled','With Doctor','In Room','Checked In','In Room - Vitals Taken','Not Seen','Billed'];
const tebraStatuses=['Confirmed','Check-in','No-show','Check-out','Rescheduled','Scheduled','Cancelled'];
const status=(v:unknown,provider:EhrProvider)=>v===null&&provider==='elation'||typeof v==='string'&&(provider==='tebra'?tebraStatuses:statuses).includes(v);
const day=(v:unknown):v is string=>typeof v==='string'&&/^\d{4}-\d\d-\d\d$/.test(v)&&modelTime(v+'T00:00:00Z')&&new Date(v+'T00:00:00Z').toISOString().slice(0,10)===v;
export const ehrHash=(v:unknown)=>vendorSha256(new TextEncoder().encode(modelCanonical(v)));
export const ehrContentHash=(s:string)=>vendorSha256(new TextEncoder().encode(s));
export const ehrItemHash=(item:EhrWindowItem|EhrVerifiedItem)=>{const {sha256:_,...body}=item;return ehrHash({kind:'patient' in item?'ehr_verified_item.v1':'ehr_window_item.v1',item:body});};
export const ehrReviewHash=(workspaceId:string,body:EhrReviewRequest)=>ehrHash({workspace_id:workspaceId,...body});
export const ehrSourceHash=(receipt:EhrReceipt,item:EhrVerifiedItem)=>ehrHash({observation_sha256:receipt.source_sha256,item_handle:item.handle,item_sha256:item.sha256});
export function validEhrWindow(v:unknown):v is EhrWindow{return teamClosed(v,'starts_at,ends_at')&&modelTime(v.starts_at)&&modelTime(v.ends_at)&&Date.parse(v.ends_at)>Date.parse(v.starts_at)&&Date.parse(v.ends_at)-Date.parse(v.starts_at)<=7*86400000;}
const validProvider=(v:Record<string,unknown>)=>v.provider===undefined||v.provider==='elation'||v.provider==='tebra';
export const validTebraIdentity=(lastName:unknown,birthDate:unknown)=>text(lastName,255)&&lastName===lastName.trim()&&day(birthDate)&&birthDate>='1850-01-01'&&birthDate<=new Date().toISOString().slice(0,10);
const validTransport=(v:Record<string,unknown>)=>v.transport===undefined||v.transport==='mock'||v.transport==='vendor_sandbox';
const validInstallation=(v:unknown)=>teamClosed(v,'id,sha256')&&teamUuid(v.id)&&teamHash(v.sha256);
export function validEhrStatus(v:unknown):v is EhrReadStatus{
 if(!teamClosed(v,'contract_version,provider,mode,status,connection_id,binding_sha256,practice','transport,installation')||v.contract_version!==1||!['elation','tebra'].includes(String(v.provider))||v.mode!=='synthetic'||!validTransport(v))return false;
 if(v.provider==='tebra'&&(v.transport!=='mock'||v.installation!==null||v.status==='setup_required'))return false;
 const installed=v.installation!==undefined&&v.installation!==null;
 if(installed&&(!validInstallation(v.installation)||v.transport!=='vendor_sandbox'))return false;
 if(v.status==='setup_required')return v.transport==='vendor_sandbox'&&installed&&v.connection_id===null&&v.binding_sha256===null&&practice(v.practice);
 if(v.status==='ready')return teamUuid(v.connection_id)&&teamHash(v.binding_sha256)&&practice(v.practice)&&(v.transport!=='vendor_sandbox'||installed);
 return ['not_enabled','not_configured'].includes(String(v.status))&&v.connection_id===null&&v.binding_sha256===null&&v.practice===null&&!installed;
}
export function validEhrInstall(v:unknown):v is EhrInstallRequest{return teamClosed(v,'action,installation_id,installation_sha256,idempotency_key')&&v.action==='install'&&teamUuid(v.installation_id)&&teamHash(v.installation_sha256)&&ehrKey(v.idempotency_key);}
export async function validEhrInstallReceipt(v:unknown,body:EhrInstallRequest):Promise<boolean>{return validEhrInstall(body)&&teamClosed(v,'contract_version,status,transport,installation_id,installation_sha256,connection_id,binding_sha256,idempotency_key,request_sha256')&&v.contract_version===1&&['installed','unavailable'].includes(String(v.status))&&v.transport==='vendor_sandbox'&&v.installation_id===body.installation_id&&v.installation_sha256===body.installation_sha256&&v.idempotency_key===body.idempotency_key&&teamUuid(v.connection_id)&&teamHash(v.binding_sha256)&&v.request_sha256===await ehrHash(body);}
export function validEhrCommand(v:unknown):v is EhrCommand{
 if(!v||typeof v!=='object')return false;const r=v as Record<string,unknown>;
 if(!validProvider(r)||!teamUuid(r.connection_id)||!teamHash(r.binding_sha256)||!ehrKey(r.idempotency_key))return false;
 return r.action==='observe'?teamClosed(r,'action,connection_id,binding_sha256,starts_at,ends_at,idempotency_key','provider')&&validEhrWindow({starts_at:r.starts_at,ends_at:r.ends_at}):r.action==='verify'&&teamClosed(r,'action,connection_id,binding_sha256,observation_id,observation_sha256,item_handle,item_sha256,idempotency_key'+(r.provider==='tebra'?',last_name,birth_date':''),'provider')&&(r.provider!=='tebra'||validTebraIdentity(r.last_name,r.birth_date))&&teamUuid(r.observation_id)&&teamHash(r.observation_sha256)&&teamUuid(r.item_handle)&&teamHash(r.item_sha256);
}
export function validEhrReview(v:unknown):v is EhrReviewRequest{return teamClosed(v,'expected_revision,idempotency_key,observation_id,observation_sha256,item_handle,item_sha256,reviewed_visit,reviewed_patient_identity,reviewed_exact_snapshot,reviewed_untrusted_source','provider')&&validProvider(v)&&teamNatural(v.expected_revision)&&v.expected_revision>0&&v.expected_revision<2147483647&&ehrKey(v.idempotency_key)&&teamUuid(v.observation_id)&&teamHash(v.observation_sha256)&&teamUuid(v.item_handle)&&teamHash(v.item_sha256)&&v.reviewed_visit===true&&v.reviewed_patient_identity===true&&v.reviewed_exact_snapshot===true&&v.reviewed_untrusted_source===true;}
async function validItem(v:unknown,window:EhrWindow,verified:boolean,provider:EhrProvider):Promise<boolean>{
 if(!teamClosed(v,verified?'handle,sha256,starts_at,ends_at,status,patient':'handle,sha256,starts_at,ends_at,status,selectable')||!teamUuid(v.handle)||!teamHash(v.sha256)||!modelTime(v.starts_at)||!modelTime(v.ends_at)||Date.parse(v.ends_at)<=Date.parse(v.starts_at)||Date.parse(v.starts_at)<Date.parse(window.starts_at)||Date.parse(v.starts_at)>=Date.parse(window.ends_at)||!status(v.status,provider))return false;
 if(verified){if(provider==='tebra'){if(!teamClosed(v.patient,'full_name,birth_date')||!text(v.patient.full_name,255)||!day(v.patient.birth_date)||v.patient.birth_date<'1850-01-01'||v.patient.birth_date>new Date().toISOString().slice(0,10))return false;}else if(!teamClosed(v.patient,'first_name,last_name,birth_date')||!text(v.patient.first_name,70)||!text(v.patient.last_name,70)||!day(v.patient.birth_date))return false;}else if(typeof v.selectable!=='boolean')return false;
 return v.sha256===await ehrItemHash(v as EhrWindowItem|EhrVerifiedItem);
}
export async function validEhrReceipt(v:unknown):Promise<boolean>{
 if(!teamClosed(v,'contract_version,connection_id,binding_sha256,observation_id,observation_key,source_sha256,payload_sha256,observation','transport,provider')||!validProvider(v)||!validTransport(v)||v.contract_version!==1||!teamUuid(v.connection_id)||!teamHash(v.binding_sha256)||!teamUuid(v.observation_id)||!ehrKey(v.observation_key)||!teamHash(v.source_sha256)||!teamHash(v.payload_sha256)||!v.observation||typeof v.observation!=='object')return false;
 const o=v.observation as Record<string,unknown>,verified=o.kind==='verified_visit';
 if(!teamClosed(o,'kind,provider,mode,practice,observed_at,window,coverage,'+(verified?'item':'items'))||!['window','verified_visit'].includes(String(o.kind))||!['elation','tebra'].includes(String(o.provider))||o.mode!=='synthetic'||!practice(o.practice)||!modelTime(o.observed_at)||!validEhrWindow(o.window)||!(o.provider==='tebra'?o.coverage==='returned_rows_only':['end_of_results','more_rows_available'].includes(String(o.coverage))))return false;
 if(ehrProvider(v as EhrReceipt)!==o.provider||o.provider==='tebra'&&v.transport!=='mock')return false;
 if(verified){if(!await validItem(o.item,o.window,true,o.provider as EhrProvider))return false;}else if(!Array.isArray(o.items)||o.items.length>25||new Set(o.items.map(i=>i?.handle)).size!==o.items.length||!(await Promise.all(o.items.map(i=>validItem(i,o.window as EhrWindow,false,o.provider as EhrProvider)))).every(Boolean))return false;
 return v.payload_sha256===await ehrHash(o);
}
export class EhrReadRefusal extends WorkspaceApiError {constructor(status:number,code:string){super(status,code);this.name='EhrReadRefusal';}}
const REFUSALS=new Set(['ehr_sandbox_installation_unavailable','ehr_sandbox_installation_changed','ehr_sandbox_setup_unavailable','ehr_sandbox_generation_already_installed','ehr_sandbox_quota_exceeded','ehr_read_source_unavailable','ehr_read_observation_unavailable','ehr_read_history_limit','invalid_ehr_read_request','invalid_ehr_read_review','ehr_read_unavailable','ehr_read_binding_unavailable','ehr_read_binding_changed','ehr_read_unconfirmed','ehr_read_expired','ehr_read_superseded','ehr_read_source_invalid','ehr_read_source_changed','ehr_read_not_observed','ehr_read_appointment_changed','ehr_read_record_unavailable','ehr_read_timeout','ehr_read_rate_limited','ehr_read_permission_denied','ehr_read_authentication_required','ehr_read_response_invalid','ehr_read_response_too_large','ehr_read_too_many_results','idempotency_conflict','workspace_revision_conflict','workspace_history_limit']);
export const ehrReviewProvesNoCommit=(e:unknown)=>e instanceof EhrReadRefusal&&['workspace_revision_conflict','invalid_ehr_read_review'].includes(e.code??'');
async function send<T>(identity:AuthenticatedWorkspaceIdentity,path:string,body:EhrRequest,validate:(value:unknown)=>Promise<T>,signal?:AbortSignal,large=false):Promise<T> {
  if(!EHR_READ_BUILD)throw new WorkspaceApiError(404);
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
    headers.set('X-Cosmas-Ehr-Read','1');headers.set('Accept','application/json');
    response=await wait(workspaceFetch(identity,base+path,{method:'POST',headers,body:encoded,signal:controller.signal,cache:'no-store',credentials:'omit',redirect:'error',referrerPolicy:'no-referrer'}));check();
    if([401,403,404,426].includes(response.status))throw new WorkspaceApiError(response.status);
    if(response.redirected||response.headers.has('content-encoding')||response.headers.get('content-type')?.split(';',1)[0].trim().toLowerCase()!=='application/json'||
      !response.headers.get('cache-control')?.split(',').some(v=>v.trim().toLowerCase()==='no-store'))throw new WorkspaceApiError(502);
    reader=response.body?.getReader();if(!reader)throw new WorkspaceApiError(502);const cap=response.ok?(large?MODEL_WORKSPACE_BYTES:131072):2048;
    const chunks:Uint8Array[]=[];let size=0;
    for(;;){const part=await wait(reader.read());check();if(part.done)break;size+=part.value.length;if(size>cap)throw new WorkspaceApiError(502);chunks.push(part.value);}
    const bytes=new Uint8Array(size);let at=0;for(const chunk of chunks){bytes.set(chunk,at);at+=chunk.length;}
    let value:unknown;try{value=parseVendorJson(new TextDecoder('utf-8',{fatal:true}).decode(bytes));}catch{throw new WorkspaceApiError(502);}
    if(response.status!==200){if([400,409,422,429,502,503].includes(response.status)&&teamClosed(value,'detail')&&typeof value.detail==='string'&&REFUSALS.has(value.detail))throw new EhrReadRefusal(response.status,value.detail);throw new WorkspaceApiError(response.status);}
    const result=await wait(validate(value));check();return result;
  }catch(error){if(error instanceof WorkspaceApiError)throw error;throw new WorkspaceApiError(503);}
  finally{clearTimeout(timer);signal?.removeEventListener('abort',abort);controller.signal.removeEventListener('abort',rejectAbort);cancel(reader??response?.body);try{reader?.releaseLock();}catch{/* Discarded read may settle. */}controller.abort();}
}
const invalid=():never=>{throw new WorkspaceApiError(502,'ehr_read_response_invalid');};
const receipt=async(v:unknown)=>await validEhrReceipt(v)?v as EhrReceipt:invalid();
export function ehrMatchesCommand(r:EhrReceipt,b:EhrCommand,anchor:EhrReceipt|null):boolean{
 if(ehrProvider(r)!==ehrProvider(b)||r.observation.provider!==ehrProvider(b)||r.observation_key!==b.idempotency_key||r.connection_id!==b.connection_id||r.binding_sha256!==b.binding_sha256)return false;
 if(b.action==='observe')return r.observation.kind==='window'&&Date.parse(r.observation.window.starts_at)===Date.parse(b.starts_at)&&Date.parse(r.observation.window.ends_at)===Date.parse(b.ends_at);
 const item=anchor?.observation.kind==='window'?anchor.observation.items.find(i=>i.handle===b.item_handle&&i.sha256===b.item_sha256&&i.selectable):null;
 return !!item&&anchor?.observation.provider===ehrProvider(b)&&ehrTransport(r)===ehrTransport(anchor!)&&anchor?.connection_id===b.connection_id&&anchor.binding_sha256===b.binding_sha256&&anchor?.observation_id===b.observation_id&&anchor.source_sha256===b.observation_sha256&&r.observation.kind==='verified_visit'&&r.observation.item.handle===item.handle&&r.observation.item.starts_at===item.starts_at&&r.observation.item.ends_at===item.ends_at&&r.observation.item.status===item.status&&(b.provider!=='tebra'||r.observation.item.patient.birth_date===b.birth_date)&&modelCanonical(r.observation.practice)===modelCanonical(anchor.observation.practice)&&modelCanonical(r.observation.window)===modelCanonical(anchor.observation.window)&&r.observation.coverage===anchor.observation.coverage;
}
export function ehrSourceContent(o:EhrVerifiedObservation):string{
 const i=o.item,p=i.patient,coverage=o.coverage==='returned_rows_only'?'Showing returned appointments only; this is not a complete schedule.':o.coverage==='more_rows_available'?'Showing this page; more appointments may be available.':'Showing the returned page.';
 return `${ehrProviderName(o.provider)} selected visit (synthetic frozen observation)\nPractice: ${o.practice.label}\nPatient: ${ehrPatientName(p)}\nBirth date: ${p.birth_date}\nStarts: ${i.starts_at}\nEnds: ${i.ends_at}\nAppointment status: ${i.status||'not provided'}\nObserved: ${o.observed_at}\nCoverage: ${coverage}\n\nThis reviewed snapshot does not book or update the EHR.`;
}
export async function verifyEhrReviewResponse(v:unknown,workspaceId:string,body:EhrReviewRequest,anchor:EhrReceipt):Promise<EhrReviewResponse>{
 const item=anchor.observation.kind==='verified_visit'?anchor.observation.item:null;
 if(!item||anchor.observation_id!==body.observation_id||anchor.source_sha256!==body.observation_sha256||item.handle!==body.item_handle||item.sha256!==body.item_sha256||!teamClosed(v,'entry_id,entry_revision,request_sha256,source_withheld,workspace,source','transport,provider')||!validProvider(v)||ehrProvider(v as EhrReviewResponse)!==anchor.observation.provider||ehrProvider(body)!==anchor.observation.provider||!validTransport(v)||anchor.observation.provider==='tebra'&&v.transport!=='mock'||ehrTransport(v as EhrReviewResponse)!==ehrTransport(anchor)||!teamUuid(v.entry_id)||v.entry_revision!==body.expected_revision+1||typeof v.source_withheld!=='boolean'||v.request_sha256!==await ehrReviewHash(workspaceId,body)||!teamClosed(v.source,'entry_id,source_sha256,content_sha256')||v.source.entry_id!==v.entry_id||v.source.source_sha256!==await ehrSourceHash(anchor,item)||!teamHash(v.source.content_sha256)||v.source.content_sha256!==await ehrContentHash(ehrSourceContent(anchor.observation as EhrVerifiedObservation))||!await validModelWorkspace(v.workspace,workspaceId))return invalid();
 const w=v.workspace as Workspace,e=w.entries.find(e=>e.id===v.entry_id);
 if(w.revision<Number(v.entry_revision)||!e||e.kind!=='ehr_read_source'||e.revision!==v.entry_revision)return invalid();
 if(v.source_withheld){if(e.ehr_source_state!=='unavailable'||e.content!==''||e.source_label!=='Unavailable EHR source')return invalid();}else if(e.ehr_source_state!=='current'||e.source_label!==ehrProviderName(anchor.observation.provider)+': reviewed appointment'||e.content!==ehrSourceContent(anchor.observation as EhrVerifiedObservation)||typeof e.content!=='string'||await ehrContentHash(e.content)!==v.source.content_sha256)return invalid();
 return v as EhrReviewResponse;
}
async function validCommandAnchor(body:EhrCommand,anchor:EhrReceipt|null):Promise<boolean>{
 if(body.action==='observe')return anchor===null;
 if(!anchor||anchor.observation.provider!==ehrProvider(body)||!await validEhrReceipt(anchor)||anchor.observation.kind!=='window'||anchor.connection_id!==body.connection_id||anchor.binding_sha256!==body.binding_sha256||anchor.observation_id!==body.observation_id||anchor.source_sha256!==body.observation_sha256)return false;
 return anchor.observation.items.some(i=>i.selectable&&i.handle===body.item_handle&&i.sha256===body.item_sha256);
}
const receiptCanonical=(r:EhrReceipt)=>modelCanonical({...r,transport:ehrTransport(r),provider:ehrProvider(r)});
export const ehrReadApi={
 install:async(identity:AuthenticatedWorkspaceIdentity,body:EhrInstallRequest,signal?:AbortSignal)=>{if(!validEhrInstall(body))throw new WorkspaceApiError(422);return send(identity,'/connections/ehr/reads',body,async v=>await validEhrInstallReceipt(v,body)?v as EhrInstallReceipt:invalid(),signal);},
 resolveInstall:async(identity:AuthenticatedWorkspaceIdentity,body:EhrInstallRequest,signal?:AbortSignal)=>{if(!validEhrInstall(body))throw new WorkspaceApiError(422);return send<EhrInstallReceipt|EhrResolve>(identity,'/connections/ehr/reads',{action:'resolve',idempotency_key:body.idempotency_key},async v=>{if(teamClosed(v,'status,observation_id,observation_key')&&v.status==='not_found'&&v.observation_id===null&&v.observation_key===body.idempotency_key)return v as EhrResolve;return await validEhrInstallReceipt(v,body)?v as EhrInstallReceipt:invalid();},signal);},
 status:(identity:AuthenticatedWorkspaceIdentity,signal?:AbortSignal,provider:EhrProvider='elation')=>send(identity,'/connections/ehr/reads',{action:'status',...ehrProviderFields(provider)},async v=>validEhrStatus(v)&&v.provider===provider?v:invalid(),signal),
 execute:async(identity:AuthenticatedWorkspaceIdentity,body:EhrCommand,anchor:EhrReceipt|null,signal?:AbortSignal,transport:EhrTransport=anchor?ehrTransport(anchor):'mock')=>{if(!validEhrCommand(body)||!await validCommandAnchor(body,anchor))throw new WorkspaceApiError(422);return send(identity,'/connections/ehr/reads',body,async v=>{const r=await receipt(v);return ehrTransport(r)===transport&&ehrMatchesCommand(r,body,anchor)?r:invalid();},signal);},
 inspect:async(identity:AuthenticatedWorkspaceIdentity,anchor:EhrReceipt,signal?:AbortSignal)=>{if(!await validEhrReceipt(anchor))throw new WorkspaceApiError(422);return send(identity,'/connections/ehr/reads',{action:'inspect',observation_id:anchor.observation_id,...ehrProviderFields(anchor.observation.provider)},async v=>{const r=await receipt(v);return receiptCanonical(r)===receiptCanonical(anchor)?r:invalid();},signal);},
 resolve:(identity:AuthenticatedWorkspaceIdentity,body:EhrCommand,anchor:EhrReceipt|null,signal?:AbortSignal,transport:EhrTransport=anchor?ehrTransport(anchor):'mock')=>{if(!validEhrCommand(body))throw new WorkspaceApiError(422);return send<EhrReceipt|EhrResolve>(identity,'/connections/ehr/reads',{action:'resolve',idempotency_key:body.idempotency_key,...ehrProviderFields(ehrProvider(body))},async v=>{
  if(teamClosed(v,'status,observation_id,observation_key','provider')&&validProvider(v)&&ehrProvider(v as EhrResolve)===ehrProvider(body)&&v.observation_key===body.idempotency_key&&(v.status==='not_found'?v.observation_id===null:v.status==='unconfirmed'&&teamUuid(v.observation_id)))return v as EhrResolve;
  const r=await receipt(v);return ehrTransport(r)===transport&&ehrMatchesCommand(r,body,anchor)?r:invalid();},signal);},
 review:async(identity:AuthenticatedWorkspaceIdentity,workspaceId:string,body:EhrReviewRequest,anchor:EhrReceipt,signal?:AbortSignal)=>{if(!teamUuid(workspaceId)||!validEhrReview(body)||ehrProvider(body)!==anchor.observation.provider||!await validEhrReceipt(anchor)||anchor.observation.kind!=='verified_visit'||body.observation_id!==anchor.observation_id||body.observation_sha256!==anchor.source_sha256||body.item_handle!==anchor.observation.item.handle||body.item_sha256!==anchor.observation.item.sha256)throw new WorkspaceApiError(422);return send(identity,`/workspaces/${workspaceId}/ehr-read/review`,body,v=>verifyEhrReviewResponse(v,workspaceId,body,anchor),signal,true);},
};
