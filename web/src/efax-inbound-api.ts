import {WorkspaceApiError,WORKSPACE_BUILD,WORKSPACE_AUTHENTICATED_BUILD,type AuthenticatedWorkspaceIdentity} from './workspace-api';
import {assertCurrentDesktopSession,workspaceAuthHeaders} from './workspace-auth-headers';
import {workspaceFetch} from './workspace-protocol';
import {permittedWorkspaceApi} from './workspace-origin';
import {parseVendorJson,vendorCanonical,vendorDigest,vendorObject,vendorSha256,vendorUuid} from './vendor-contract';

export const EFAX_INBOUND_BUILD=WORKSPACE_BUILD&&WORKSPACE_AUTHENTICATED_BUILD&&import.meta.env.VITE_EFAX_INBOUND_ENABLED==='true';
export type EFaxScope={box_id:string;owner_id:string};
export type EFaxGrant={grant_id:string;label:string;state:'available'|'unavailable';image_enabled:boolean;expires_at:string};
export type EFaxStatus={contract_version:1;scope:EFaxScope;enabled:boolean;grants:EFaxGrant[];installations:Array<{installation_id:string;label:string;metadata_available:boolean;image_available:boolean}>};
export type EFaxMetadata={fax_id:string;size:number;duration:number;pages:number;image_downloaded:boolean;completed_timestamp:string;destination_fax_number:string;originating_fax_number:string;originating_fax_tsid:string;fax_status:'STORED'|'NOT_STORED'|null};
export type EFaxSnapshot={request:{request_id:string;starts_at:string;ends_at:string;limit:number;offset:number};first_record:number;last_record:number;items:EFaxMetadata[];observed_at:string;raw_sha256:string;source_sha256:string;scope:'one_received_metadata_page';inbox_complete:false;continuation:'unknown'};
export type EFaxRequests={
 grant:{idempotency_key:string;installation_id:string;reviewed_account:true;reviewed_mark_read:boolean;image_enabled:boolean;expires_at:string};
 revoke:{idempotency_key:string;grant_id:string};
 observe:{idempotency_key:string;grant_id:string;starts_at:string;ends_at:string;limit:25;offset:0};
 propose:{idempotency_key:string;grant_id:string;observation_id:string;observation_sha256:string;fax_id:string;fax_sha256:string};
 decide:{idempotency_key:string;ticket_id:string;revision_id:string;expected_version:number;choice:'approve'|'reject';reviewed_mark_read:boolean};
 acquire:{idempotency_key:string;ticket_id:string;revision_id:string;expected_version:number;approval_sha256:string};
};
export type EFaxKind=keyof EFaxRequests;
export type EFaxPending={[K in EFaxKind]:{kind:K;request:EFaxRequests[K]}}[EFaxKind];
export type EFaxReceipt={contract_version:1;scope:EFaxScope;kind:EFaxKind;idempotency_key:string;receipt_id:string;request_sha256:string;public_request_sha256?:string;historical?:boolean;
 state:'granted'|'revoked'|'unconfirmed'|'unavailable'|'observed'|'approval_required'|'approved'|'rejected'|'claimed'|'outcome_unconfirmed'|'acquired'|'needs_human'|'not_attempted';
 grant_id?:string;label?:string;metadata_enabled?:boolean;image_enabled?:boolean;expires_at?:string;observation_id?:string;source_sha256?:string;snapshot?:EFaxSnapshot;
 ticket_id?:string;revision_id?:string;version?:number;command_sha256?:string;side_effect?:'marks_fax_downloaded_or_read';decision_id?:string;approval_sha256?:string|null;operation_id?:string;
 retry_allowed?:false;content_available?:boolean;source_withheld?:boolean;receipt_sha256?:string;document?:{sha256:string;byte_length:number;pages:number}|null};
export type EFaxNotFound={contract_version:1;scope:EFaxScope;idempotency_key:string;kind:EFaxKind|'recover';state:'not_found'};
export type EFaxResolve=EFaxReceipt|EFaxNotFound;
export const efaxMissing=(value:EFaxResolve):value is EFaxNotFound=>value.state==='not_found';
export type EFaxProposal={contract_version:1;scope:EFaxScope;ticket_id:string;revision_id:string;version:number;state:'pending_approval'|'approved'|'rejected'|'unavailable';command_sha256:string;expires_at:string;side_effect:'marks_fax_downloaded_or_read';source_withheld:boolean;
 fax?:EFaxMetadata;fax_sha256?:string;observation_id?:string;observation_sha256?:string;account_label?:string};
const bad=():never=>{throw new WorkspaceApiError(502,'efax_inbound_response_invalid');};
const obj=(v:unknown):v is Record<string,unknown>=>vendorObject(v)&&Reflect.ownKeys(v).length===Object.keys(v).length&&Object.values(Object.getOwnPropertyDescriptors(v)).every(p=>'value'in p&&p.enumerable);
const closed=(v:unknown,required:string,optional=''):v is Record<string,unknown>=>obj(v)&&required.split(',').filter(Boolean).every(k=>Object.hasOwn(v,k))&&Object.keys(v).every(k=>(required+','+optional).split(',').includes(k));
const hash=(v:unknown):v is string=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v);
const key=(v:unknown):v is string=>typeof v==='string'&&/^[A-Za-z0-9:_-]{8,100}$/.test(v);
const integer=(v:unknown,a:number,b:number):v is number=>Number.isInteger(v)&&Number(v)>=a&&Number(v)<=b;
const text=(v:unknown,max:number):v is string=>typeof v==='string'&&v.length<=max&&!/[\x00-\x1f\x7f]/.test(v);
const stamp=(v:unknown):v is string=>typeof v==='string'&&/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)$/.test(v)&&Number.isFinite(Date.parse(v));
const commandStamp=(v:unknown):v is string=>typeof v==='string'&&/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$/.test(v)&&Number.isFinite(Date.parse(v))&&new Date(v).toISOString()===v.replace('Z','.000Z');
export const efaxUtcSeconds=(date:Date):string=>date.toISOString().replace(/\.\d{3}Z$/,'Z');
const sameScope=(v:unknown,s:EFaxScope):boolean=>closed(v,'box_id,owner_id')&&vendorUuid(v.box_id)&&vendorUuid(v.owner_id)&&v.box_id===s.box_id&&v.owner_id===s.owner_id;
export const efaxFaxHash=(fax:EFaxMetadata)=>vendorDigest('cosmas-efax-inbound-fax.v1',fax);
export const efaxPublicHash=(scope:EFaxScope,p:EFaxPending)=>vendorDigest('cosmas-efax-inbound-api-command.v1',{scope,kind:p.kind,request:p.request});
export function validateEFaxPending(value:unknown):EFaxPending{
 if(!closed(value,'kind,request')||!['grant','revoke','observe','propose','decide','acquire'].includes(String(value.kind))||!obj(value.request))return bad();
 const r=value.request;if(!key(r.idempotency_key))return bad();
 const uuidFields={grant:['installation_id'],revoke:['grant_id'],observe:['grant_id'],propose:['grant_id','observation_id','fax_id'],decide:['ticket_id','revision_id'],acquire:['ticket_id','revision_id']} as const;
 if(uuidFields[value.kind as EFaxKind].some(k=>!vendorUuid(r[k])))return bad();
 const fields={grant:'idempotency_key,installation_id,reviewed_account,reviewed_mark_read,image_enabled,expires_at',revoke:'idempotency_key,grant_id',observe:'idempotency_key,grant_id,starts_at,ends_at,limit,offset',propose:'idempotency_key,grant_id,observation_id,observation_sha256,fax_id,fax_sha256',decide:'idempotency_key,ticket_id,revision_id,expected_version,choice,reviewed_mark_read',acquire:'idempotency_key,ticket_id,revision_id,expected_version,approval_sha256'};
 if(!closed(r,fields[value.kind as EFaxKind]))return bad();
 if(value.kind==='grant'&&(r.reviewed_account!==true||typeof r.image_enabled!=='boolean'||typeof r.reviewed_mark_read!=='boolean'||r.image_enabled&&!r.reviewed_mark_read||!commandStamp(r.expires_at)))return bad();
 if(value.kind==='observe'&&(!commandStamp(r.starts_at)||!commandStamp(r.ends_at)||Date.parse(r.ends_at)<=Date.parse(r.starts_at)||Date.parse(r.ends_at)-Date.parse(r.starts_at)>604800000||r.limit!==25||r.offset!==0))return bad();
 if(value.kind==='propose'&&(!hash(r.observation_sha256)||!hash(r.fax_sha256)))return bad();
 if(value.kind==='decide'&&(!integer(r.expected_version,1,100)||!['approve','reject'].includes(String(r.choice))||typeof r.reviewed_mark_read!=='boolean'||r.choice==='approve'&&!r.reviewed_mark_read))return bad();
 if(value.kind==='acquire'&&(!integer(r.expected_version,1,100)||!hash(r.approval_sha256)))return bad();
 vendorCanonical(value);return value as EFaxPending;
}
export function validateEFaxMetadata(v:unknown):EFaxMetadata{
 if(!closed(v,'fax_id,size,duration,pages,image_downloaded,completed_timestamp,destination_fax_number,originating_fax_number,originating_fax_tsid,fax_status')||!vendorUuid(v.fax_id)||!integer(v.size,0,16777216)||!integer(v.duration,0,86400)||!integer(v.pages,0,10000)||typeof v.image_downloaded!=='boolean'||!stamp(v.completed_timestamp)||!text(v.originating_fax_tsid,128)||![null,'STORED','NOT_STORED'].includes(v.fax_status as string|null)||![v.destination_fax_number,v.originating_fax_number].every(n=>typeof n==='string'&&/^\+?[0-9]{1,31}$/.test(n)))return bad();return v as EFaxMetadata;
}
export function validateEFaxStatus(v:unknown,scope:EFaxScope):EFaxStatus{
 if(!closed(v,'contract_version,scope,enabled,grants,installations')||v.contract_version!==1||!sameScope(v.scope,scope)||typeof v.enabled!=='boolean'||!Array.isArray(v.grants)||v.grants.length>50||!Array.isArray(v.installations)||v.installations.length>50)return bad();
 for(const g of v.grants)if(!closed(g,'grant_id,label,state,image_enabled,expires_at')||!vendorUuid(g.grant_id)||!text(g.label,80)||!g.label||!['available','unavailable'].includes(String(g.state))||typeof g.image_enabled!=='boolean'||g.state==='unavailable'&&g.image_enabled||!stamp(g.expires_at))return bad();
 for(const i of v.installations)if(!closed(i,'installation_id,label,metadata_available,image_available')||!vendorUuid(i.installation_id)||!text(i.label,80)||!i.label||typeof i.metadata_available!=='boolean'||typeof i.image_available!=='boolean')return bad();
 if(new Set(v.grants.map(g=>g.grant_id)).size!==v.grants.length||new Set(v.installations.map(i=>i.installation_id)).size!==v.installations.length)return bad();return v as EFaxStatus;
}
function snapshot(v:unknown):EFaxSnapshot{
 if(!closed(v,'request,first_record,last_record,items,observed_at,raw_sha256,source_sha256,scope,inbox_complete,continuation')||!closed(v.request,'request_id,starts_at,ends_at,limit,offset')||!vendorUuid(v.request.request_id)||!stamp(v.request.starts_at)||!stamp(v.request.ends_at)||!integer(v.request.limit,1,25)||!integer(v.request.offset,0,5000)||Date.parse(v.request.ends_at)-Date.parse(v.request.starts_at)>604800000||Date.parse(v.request.ends_at)<=Date.parse(v.request.starts_at)||!integer(v.first_record,0,2147483647)||!integer(v.last_record,0,2147483647)||!Array.isArray(v.items)||v.items.length>v.request.limit||!stamp(v.observed_at)||!hash(v.raw_sha256)||!hash(v.source_sha256)||v.scope!=='one_received_metadata_page'||v.inbox_complete!==false||v.continuation!=='unknown')return bad();
 let previous=Infinity;const seen=new Set();for(const raw of v.items){const f=validateEFaxMetadata(raw),at=Date.parse(f.completed_timestamp);if(seen.has(f.fax_id)||at>previous||at<Date.parse(v.request.starts_at)||at>Date.parse(v.request.ends_at))return bad();seen.add(f.fax_id);previous=at;}return v as EFaxSnapshot;
}
export function validateEFaxReceipt(v:unknown,scope:EFaxScope):EFaxReceipt{
 const extra='public_request_sha256,historical,grant_id,label,metadata_enabled,image_enabled,expires_at,observation_id,source_sha256,snapshot,ticket_id,revision_id,version,command_sha256,side_effect,decision_id,approval_sha256,operation_id,retry_allowed,content_available,source_withheld,receipt_sha256,document';
 if(!closed(v,'contract_version,scope,kind,idempotency_key,receipt_id,request_sha256,state',extra)||v.contract_version!==1||!sameScope(v.scope,scope)||!['grant','revoke','observe','propose','decide','acquire'].includes(String(v.kind))||!key(v.idempotency_key)||!vendorUuid(v.receipt_id)||!hash(v.request_sha256)||!['granted','revoked','unconfirmed','unavailable','observed','approval_required','approved','rejected','claimed','outcome_unconfirmed','acquired','needs_human','not_attempted'].includes(String(v.state)))return bad();
 const fields={grant:'grant_id,label,metadata_enabled,image_enabled,expires_at',revoke:'grant_id',observe:'grant_id,observation_id,source_sha256,snapshot,source_withheld',propose:'ticket_id,revision_id,version,command_sha256,side_effect,expires_at',decide:'ticket_id,revision_id,version,decision_id,approval_sha256',acquire:'ticket_id,revision_id,operation_id,version,retry_allowed,content_available,source_withheld,receipt_sha256,document'};
 if(!closed(v,'contract_version,scope,kind,idempotency_key,receipt_id,request_sha256,state','public_request_sha256,historical,'+fields[v.kind as EFaxKind]))return bad();
 for(const n of ['grant_id','observation_id','ticket_id','revision_id','decision_id','operation_id'])if(n in v&&!vendorUuid(v[n]))return bad();
 for(const n of ['public_request_sha256','source_sha256','command_sha256','receipt_sha256'])if(n in v&&!hash(v[n]))return bad();
 for(const n of ['historical','metadata_enabled','image_enabled','content_available','source_withheld'])if(n in v&&typeof v[n]!=='boolean')return bad();
 if('approval_sha256'in v&&v.approval_sha256!==null&&!hash(v.approval_sha256)||'version'in v&&!integer(v.version,1,100)||'label'in v&&(!text(v.label,80)||!v.label)||'expires_at'in v&&!stamp(v.expires_at)||'side_effect'in v&&v.side_effect!=='marks_fax_downloaded_or_read'||'retry_allowed'in v&&v.retry_allowed!==false)return bad();
 if(v.kind==='grant'&&(v.state!=='granted'||!vendorUuid(v.grant_id)||!text(v.label,80)||v.metadata_enabled!==true||typeof v.image_enabled!=='boolean'||!stamp(v.expires_at)))return bad();
 if(v.kind==='revoke'&&(v.state!=='revoked'||!vendorUuid(v.grant_id)))return bad();
 if(v.kind==='observe'){if(!vendorUuid(v.observation_id)||!vendorUuid(v.grant_id)||!['observed','unavailable','unconfirmed'].includes(String(v.state)))return bad();if(v.state==='observed'){const s=snapshot(v.snapshot);if(v.source_withheld===true||s.source_sha256!==v.source_sha256||s.request.request_id!==v.observation_id)return bad();}else if('snapshot'in v||'source_sha256'in v)return bad();}
 if(v.kind==='propose'&&(v.state!=='approval_required'||!vendorUuid(v.ticket_id)||!vendorUuid(v.revision_id)||!integer(v.version,1,100)||!hash(v.command_sha256)||v.side_effect!=='marks_fax_downloaded_or_read'||!stamp(v.expires_at)))return bad();
 if(v.kind==='decide'&&(!['approved','rejected'].includes(String(v.state))||!vendorUuid(v.ticket_id)||!vendorUuid(v.revision_id)||!vendorUuid(v.decision_id)||!integer(v.version,1,100)||v.state==='approved'&&!hash(v.approval_sha256)||v.state==='rejected'&&v.approval_sha256!==null))return bad();
 if(v.kind==='acquire'){if(!vendorUuid(v.ticket_id)||!vendorUuid(v.revision_id)||!vendorUuid(v.operation_id)||!integer(v.version,1,100)||v.retry_allowed!==false||typeof v.content_available!=='boolean'||typeof v.source_withheld!=='boolean'||!['claimed','outcome_unconfirmed','acquired','needs_human','not_attempted'].includes(String(v.state)))return bad();if(v.content_available){if(v.state!=='acquired'||v.source_withheld===true||!closed(v.document,'sha256,byte_length,pages')||!hash(v.document.sha256)||!integer(v.document.byte_length,1,1048576)||!integer(v.document.pages,1,50))return bad();}else if(v.document!==null)return bad();}
 return v as EFaxReceipt;
}
export async function verifyEFaxReceipt(v:unknown,scope:EFaxScope,p:EFaxPending):Promise<EFaxReceipt>{
 const r=validateEFaxReceipt(v,scope);if(r.kind!==p.kind||r.idempotency_key!==p.request.idempotency_key)return bad();
 if(r.public_request_sha256!==await efaxPublicHash(scope,p))return bad();
 for(const name of ['grant_id','ticket_id','revision_id','observation_id'] as const)if(name in p.request&&r[name]!==undefined&&r[name]!==p.request[name as keyof typeof p.request])return bad();
 if(p.kind==='observe'&&r.snapshot&&(r.snapshot.request.starts_at!==p.request.starts_at&&Date.parse(r.snapshot.request.starts_at)!==Date.parse(p.request.starts_at)||Date.parse(r.snapshot.request.ends_at)!==Date.parse(p.request.ends_at)||r.snapshot.request.limit!==25||r.snapshot.request.offset!==0))return bad();
 if(p.kind==='decide'&&(r.state!==(p.request.choice==='approve'?'approved':'rejected')||r.version!==p.request.expected_version+1)||p.kind==='acquire'&&r.version!==p.request.expected_version+1)return bad();return r;
}
export async function validateEFaxProposal(v:unknown,scope:EFaxScope,ticket:string):Promise<EFaxProposal>{
 if(!closed(v,'contract_version,scope,ticket_id,revision_id,version,state,command_sha256,expires_at,side_effect,source_withheld','fax,fax_sha256,observation_id,observation_sha256,account_label')||v.contract_version!==1||!sameScope(v.scope,scope)||v.ticket_id!==ticket||!vendorUuid(v.revision_id)||!integer(v.version,1,100)||!['pending_approval','approved','rejected','unavailable'].includes(String(v.state))||!hash(v.command_sha256)||!stamp(v.expires_at)||v.side_effect!=='marks_fax_downloaded_or_read'||typeof v.source_withheld!=='boolean')return bad();
 if(v.source_withheld){if(['fax','fax_sha256','observation_id','observation_sha256','account_label'].some(k=>k in v))return bad();}else{const fax=validateEFaxMetadata(v.fax);if(!hash(v.fax_sha256)||v.fax_sha256!==await efaxFaxHash(fax)||!vendorUuid(v.observation_id)||!hash(v.observation_sha256)||!text(v.account_label,80)||!v.account_label)return bad();}return v as EFaxProposal;
}

async function request(identity:AuthenticatedWorkspaceIdentity,path:string,body:unknown,signal?:AbortSignal,binary=false):Promise<unknown>{
 const c=new AbortController(),deadline=performance.now()+45000;let response:Response|undefined,reader:ReadableStreamDefaultReader<Uint8Array>|undefined;
 const stop=(stream:{cancel:()=>Promise<unknown>}|undefined|null)=>{try{void stream?.cancel().catch(()=>{});}catch{}};
 const abort=()=>c.abort(),interrupted=new Promise<never>((_,reject)=>c.signal.addEventListener('abort',()=>{stop(reader??response?.body);reject(new WorkspaceApiError(503,'efax_inbound_unconfirmed'));},{once:true}));void interrupted.catch(()=>{});
 const wait=<T,>(p:Promise<T>)=>Promise.race([p,interrupted]);const timer=setTimeout(abort,45000);signal?.addEventListener('abort',abort,{once:true});
 const check=()=>{if(performance.now()>=deadline)c.abort();if(c.signal.aborted)throw new WorkspaceApiError(503,'efax_inbound_unconfirmed');assertCurrentDesktopSession(identity);if(identity.mode==='clerk_jwt'&&identity.nativeSession&&!identity.nativeSession.isCurrent())throw new WorkspaceApiError(401);};
 try{if(signal?.aborted)abort();check();const base=import.meta.env.VITE_API_BASE?.trim().replace(/\/+$/,'')||'http://127.0.0.1:8000';if(base.includes('?')||base.includes('#')||!permittedWorkspaceApi(base,import.meta.env.VITE_DESKTOP_SYNTHETIC_ENABLED==='true',window.location.href))throw new WorkspaceApiError(503);
  const headers=await wait(workspaceAuthHeaders(identity,base));check();headers.set('X-Cosmas-EFax-Inbound','1');headers.set('Accept',binary?'application/pdf':'application/json');if(body!==undefined)headers.set('Content-Type','application/json');
  const url=base+path;response=await wait(workspaceFetch(identity,url,{method:body===undefined?'GET':'POST',headers,body:body===undefined?undefined:JSON.stringify(body),signal:c.signal,credentials:'omit',cache:'no-store',redirect:'error',referrerPolicy:'no-referrer'}).then(r=>{if(c.signal.aborted){stop(r.body);throw new WorkspaceApiError(503);}return r;}));check();
  if(!response)return bad();
  const maximum=response.status===200?(binary?1048576:65536):2048,length=response.headers.get('content-length'),type=response.headers.get('content-type')?.split(';')[0].trim().toLowerCase();
  if(response.redirected||response.type==='opaque'||response.type==='opaqueredirect'||response.url&&response.url!==url||response.headers.has('content-encoding')||!response.headers.get('cache-control')?.split(',').some(v=>v.trim().toLowerCase()==='no-store')||type!==(binary&&response.status===200?'application/pdf':'application/json')||length!==null&&(!/^(?:0|[1-9][0-9]*)$/.test(length)||Number(length)>maximum))return bad();
  if(binary&&response.status===200&&(response.headers.get('x-content-type-options')!=='nosniff'||response.headers.get('content-disposition')!=='attachment; filename=received-fax.pdf'))return bad();
  reader=response.body?.getReader();if(!reader)return bad();const bytes=new Uint8Array(maximum);let size=0;for(;;){const part=await wait(reader.read());check();if(part.done)break;if(part.value.byteLength>maximum-size)return bad();bytes.set(part.value,size);size+=part.value.byteLength;}if(length!==null&&Number(length)!==size)return bad();
  if(binary&&response.status===200)return bytes.slice(0,size);
  let value:unknown;try{value=parseVendorJson(new TextDecoder('utf-8',{fatal:true}).decode(bytes.slice(0,size)));}catch{return bad();}check();if(response.status!==200){if(!closed(value,'error')||!closed(value.error,'code')||typeof value.error.code!=='string'||!/^efax_inbound_[a-z_]{1,64}$/.test(value.error.code))return bad();throw new WorkspaceApiError(response.status,value.error.code);}return value;
 }catch(e){if(e instanceof WorkspaceApiError)throw e;throw new WorkspaceApiError(503,'efax_inbound_unconfirmed');}finally{clearTimeout(timer);signal?.removeEventListener('abort',abort);stop(reader??response?.body);try{reader?.releaseLock();}catch{}c.abort();}
}
export const efaxInboundApi={
 status:async(i:AuthenticatedWorkspaceIdentity,s:EFaxScope,signal?:AbortSignal)=>validateEFaxStatus(await request(i,'/efax-inbound',undefined,signal),s),
 command:async(i:AuthenticatedWorkspaceIdentity,s:EFaxScope,p:EFaxPending,signal?:AbortSignal)=>verifyEFaxReceipt(await request(i,'/efax-inbound/'+p.kind,validateEFaxPending(p).request,signal),s,p),
 resolve:async(i:AuthenticatedWorkspaceIdentity,s:EFaxScope,p:EFaxPending,signal?:AbortSignal):Promise<EFaxResolve>=>{validateEFaxPending(p);const v=await request(i,'/efax-inbound/resolve',{idempotency_key:p.request.idempotency_key,kind:p.kind==='observe'?'observation':p.kind==='acquire'?'image':'command'},signal);const missingFields='contract_version,scope,idempotency_key,kind,state'+(p.kind==='acquire'?',retry_allowed,content_available,source_withheld,document':'');if(closed(v,missingFields)&&v.contract_version===1&&sameScope(v.scope,s)&&v.state==='not_found'&&v.idempotency_key===p.request.idempotency_key&&v.kind===(p.kind==='observe'?'observe':p.kind==='acquire'?'acquire':'recover')&&(p.kind!=='acquire'||v.retry_allowed===false&&v.content_available===false&&v.source_withheld===false&&v.document===null))return v as EFaxNotFound;return verifyEFaxReceipt(v,s,p);},
 proposal:async(i:AuthenticatedWorkspaceIdentity,s:EFaxScope,ticket:string,signal?:AbortSignal)=>{if(!vendorUuid(ticket))return bad();return validateEFaxProposal(await request(i,'/efax-inbound/proposals/'+ticket,undefined,signal),s,ticket);},
 document:async(i:AuthenticatedWorkspaceIdentity,r:EFaxReceipt,signal?:AbortSignal)=>{if(r.kind!=='acquire'||r.state!=='acquired'||!r.content_available||r.source_withheld||!vendorUuid(r.operation_id)||!r.document||!hash(r.document.sha256)||!integer(r.document.byte_length,1,1048576))return bad();const data=await request(i,'/efax-inbound/documents/'+r.operation_id,undefined,signal,true) as Uint8Array;if(data.length!==r.document.byte_length||new TextDecoder().decode(data.slice(0,5))!=='%PDF-'||await vendorSha256(data)!==r.document.sha256)return bad();return data;},
};
