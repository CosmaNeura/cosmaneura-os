import {WORKSPACE_BUILD,WORKSPACE_AUTHENTICATED_BUILD,WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from './workspace-api';
import {assertCurrentDesktopSession,workspaceAuthHeaders} from './workspace-auth-headers';
import {workspaceFetch} from './workspace-protocol';
import {permittedWorkspaceApi} from './workspace-origin';
import {parseVendorJson,vendorCanonical,vendorObject,vendorSha256,vendorUuid} from './vendor-contract';

export const FAX_INBOUND_BUILD=WORKSPACE_BUILD&&WORKSPACE_AUTHENTICATED_BUILD&&import.meta.env.VITE_FAX_INBOUND_ENABLED==='true';
export type FaxScope={box_id:string;owner_id:string};
export type FaxProvider='srfax'|'documo'|'spruce';
export type FaxRequestMap={
 grant:{idempotency_key:string;connection_id:string;reviewed_account:true;image_enabled:boolean;expires_at:string};
 revoke:{idempotency_key:string;grant_id:string};
 observe:{idempotency_key:string;grant_id:string;starts_at:string;ends_at:string;limit:number};
 propose:{idempotency_key:string;grant_id:string;observation_id:string;observation_sha256:string;source_sha256:string};
 decide:{idempotency_key:string;ticket_id:string;revision_id:string;expected_version:number;choice:'approve'|'reject';reviewed_exact_fax:boolean};
 acquire:{idempotency_key:string;ticket_id:string;revision_id:string;expected_version:number;approval_sha256:string};
};
export type FaxKind=keyof FaxRequestMap;
export type FaxPending={[K in FaxKind]:{kind:K;request:FaxRequestMap[K]}}[FaxKind];
const bad=():never=>{throw new WorkspaceApiError(502,'fax_inbound_response_invalid');};
export const faxHash=(v:unknown):v is string=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v);
const key=(v:unknown):v is string=>typeof v==='string'&&/^[A-Za-z0-9:_-]{8,100}$/.test(v);
const integer=(v:unknown,min:number,max:number)=>Number.isSafeInteger(v)&&Number(v)>=min&&Number(v)<=max;
const canonicalStamp=(v:unknown):v is string=>typeof v==='string'&&/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$/.test(v)&&Number.isFinite(Date.parse(v))&&new Date(v).toISOString()===v.replace('Z','.000Z');
const stamp=(v:unknown):v is string=>typeof v==='string'&&/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)$/.test(v)&&Number.isFinite(Date.parse(v));
export function faxObject(v:unknown,required:string,optional=''):v is Record<string,unknown>{return vendorObject(v)&&Reflect.ownKeys(v).length===Object.keys(v).length&&Object.values(Object.getOwnPropertyDescriptors(v)).every(p=>'value'in p&&p.enumerable)&&required.split(',').filter(Boolean).every(k=>Object.hasOwn(v,k))&&Object.keys(v).every(k=>(required+','+optional).split(',').includes(k));}
export function validFaxScope(v:unknown):v is FaxScope{return faxObject(v,'box_id,owner_id')&&vendorUuid(v.box_id)&&vendorUuid(v.owner_id);}
/** Matches Python canonical JSON with ensure_ascii=False. */
export async function faxCommitment(value:unknown):Promise<string>{
 const canonical=vendorCanonical(value);
 return vendorSha256(new TextEncoder().encode(canonical));
}
export function validateFaxPending(value:unknown):FaxPending{
 if(!faxObject(value,'kind,request')||typeof value.kind!=='string'||!['grant','revoke','observe','propose','decide','acquire'].includes(value.kind)||!vendorObject(value.request))return bad();
 const p=value as unknown as FaxPending,r=p.request;
 const fields={grant:'idempotency_key,connection_id,reviewed_account,image_enabled,expires_at',revoke:'idempotency_key,grant_id',observe:'idempotency_key,grant_id,starts_at,ends_at,limit',propose:'idempotency_key,grant_id,observation_id,observation_sha256,source_sha256',decide:'idempotency_key,ticket_id,revision_id,expected_version,choice,reviewed_exact_fax',acquire:'idempotency_key,ticket_id,revision_id,expected_version,approval_sha256'};
 if(!faxObject(r,fields[p.kind])||!key(r.idempotency_key)||new TextEncoder().encode(vendorCanonical(p)).length>8192)return bad();
 for(const n of ['connection_id','grant_id','observation_id','ticket_id','revision_id'])if(n in r&&!vendorUuid((r as unknown as Record<string,unknown>)[n]))return bad();
 if(p.kind==='grant'&&(p.request.reviewed_account!==true||typeof p.request.image_enabled!=='boolean'||!canonicalStamp(p.request.expires_at)))return bad();
 if(p.kind==='observe'&&(!canonicalStamp(p.request.starts_at)||!canonicalStamp(p.request.ends_at)||!integer(p.request.limit,1,25)||Date.parse(p.request.ends_at)<=Date.parse(p.request.starts_at)||Date.parse(p.request.ends_at)-Date.parse(p.request.starts_at)>7*86400000))return bad();
 if(p.kind==='propose'&&(!faxHash(p.request.observation_sha256)||!faxHash(p.request.source_sha256)))return bad();
 if(p.kind==='decide'&&(!integer(p.request.expected_version,1,100)||!['approve','reject'].includes(p.request.choice)||typeof p.request.reviewed_exact_fax!=='boolean'||p.request.choice==='approve'&&!p.request.reviewed_exact_fax))return bad();
 if(p.kind==='acquire'&&(!integer(p.request.expected_version,1,100)||!faxHash(p.request.approval_sha256)))return bad();
 return p;
}

/** Fixed product origin, bounded stream, fresh identity, no retries or external URLs. */
export async function faxInboundRequest(identity:AuthenticatedWorkspaceIdentity,path:string,body:unknown,signal?:AbortSignal,binary=false):Promise<unknown>{
 if(!/^\/fax-inbound(?:\/(?:grant|revoke|observe|propose|decide|acquire|resolve)|\/document\/[a-f0-9-]{36}|\/proposal\/[a-f0-9-]{36}\/[a-f0-9-]{36})?$/.test(path))throw new WorkspaceApiError(422);
 const c=new AbortController(),deadline=performance.now()+50000;let response:Response|undefined,reader:ReadableStreamDefaultReader<Uint8Array>|undefined;
 const stop=(stream:{cancel:()=>Promise<unknown>}|undefined|null)=>{try{void stream?.cancel().catch(()=>{});}catch{}};
 const abort=()=>c.abort(),interrupted=new Promise<never>((_,reject)=>c.signal.addEventListener('abort',()=>{stop(reader??response?.body);reject(new WorkspaceApiError(503,'fax_inbound_unconfirmed'));},{once:true}));void interrupted.catch(()=>{});
 const wait=<T,>(p:Promise<T>)=>Promise.race([p,interrupted]);const timer=setTimeout(abort,50000);signal?.addEventListener('abort',abort,{once:true});
 const check=()=>{if(performance.now()>=deadline)c.abort();if(c.signal.aborted)throw new WorkspaceApiError(503,'fax_inbound_unconfirmed');assertCurrentDesktopSession(identity);if(identity.mode==='clerk_jwt'&&identity.nativeSession&&!identity.nativeSession.isCurrent())throw new WorkspaceApiError(401);};
 try{
  if(signal?.aborted)abort();check();const base=import.meta.env.VITE_API_BASE?.trim().replace(/\/+$/,'')||'http://127.0.0.1:8000';
  if(base.includes('?')||base.includes('#')||!permittedWorkspaceApi(base,import.meta.env.VITE_DESKTOP_SYNTHETIC_ENABLED==='true',window.location.href))throw new WorkspaceApiError(503);
  const headers=await wait(workspaceAuthHeaders(identity,base));check();headers.set('X-Cosmas-Fax-Inbound','1');headers.set('Accept',binary?'application/pdf':'application/json');
  const payload=body===undefined?undefined:JSON.stringify(body);if(payload!==undefined&&new TextEncoder().encode(payload).length>8192)throw new WorkspaceApiError(422);
  response=await wait(workspaceFetch(identity,base+path,{method:body===undefined?'GET':'POST',headers,body:payload,signal:c.signal,credentials:'omit',cache:'no-store',redirect:'error',referrerPolicy:'no-referrer'}).then(r=>{if(c.signal.aborted){stop(r.body);throw new WorkspaceApiError(503);}return r;}));check();
  if(!response)return bad();
  if([401,403,404,426].includes(response.status))throw new WorkspaceApiError(response.status);
  const maximum=response.status===200?(binary?1048576:131072):2048,length=response.headers.get('content-length'),type=response.headers.get('content-type')?.split(';')[0].trim().toLowerCase();
  if(response.redirected||!response.headers.get('cache-control')?.split(',').some(v=>v.trim().toLowerCase()==='no-store')||!response.body||response.headers.get('content-encoding')&&response.headers.get('content-encoding')!=='identity'||type!==(binary&&response.status===200?'application/pdf':'application/json')||length!==null&&(!/^\d+$/.test(length)||Number(length)>maximum))return bad();
  reader=response.body.getReader();const chunks:Uint8Array[]= [];let size=0;
  while(true){const part=await wait(reader.read());check();if(part.done)break;size+=part.value.length;if(size>maximum)return bad();chunks.push(part.value);}
  const bytes=new Uint8Array(size);let offset=0;for(const part of chunks){bytes.set(part,offset);offset+=part.length;}check();
  if(binary&&response.status===200){if(new TextDecoder().decode(bytes.slice(0,5))!=='%PDF-')return bad();return bytes;}
  let value:unknown;try{value=parseVendorJson(new TextDecoder('utf-8',{fatal:true}).decode(bytes));}catch{return bad();}
  if(response.status!==200){if(!faxObject(value,'error')||typeof value.error!=='string'||!/^fax_inbound_[a-z_]{1,64}$/.test(value.error))throw new WorkspaceApiError(response.status);throw new WorkspaceApiError(response.status,value.error);}
  return value;
 }catch(e){if(e instanceof WorkspaceApiError)throw e;throw new WorkspaceApiError(503,'fax_inbound_unconfirmed');}
 finally{clearTimeout(timer);signal?.removeEventListener('abort',abort);stop(reader??response?.body);try{reader?.releaseLock();}catch{}c.abort();}
}

export type FaxMetadata={ordinal:number;source_sha256:string;sender_label:string;sender_number:string|null;sender_identity:'provider_reported_unverified';received_at:string;pages:number;viewed:boolean|null;image_available:boolean;image_block_reason:string|null};
export type FaxStatus={contract_version:1;installations:Array<{connection_id:string;label:string;vendor:FaxProvider;metadata_available:boolean;image_available:boolean;image_block_reason:string|null}>;grants:Array<{grant_id:string;label:string;image_enabled:boolean;expires_at:string;state:'granted'|'revoked'|'expired'|'installation_changed'}>};
export type FaxReceipt={contract_version:1;scope:FaxScope;kind:FaxKind;idempotency_key:string;request_sha256:string;public_request_sha256:string;receipt_sha256:string;source_withheld:boolean;state:'granted'|'revoked'|'observed'|'pending_approval'|'approved'|'rejected'|'outcome_unconfirmed'|'acquired';grant_id?:string;label?:string;vendor?:FaxProvider;image_enabled?:boolean;expires_at?:string;observation_id?:string;source_sha256?:string;inbox_complete?:false;items?:FaxMetadata[];ticket_id?:string;revision_id?:string;version?:number;decision_id?:string;approval_sha256?:string|null;operation_id?:string;retry_allowed?:false;document_sha256?:string|null;pages?:number|null};
export type FaxNotFound={contract_version:1;state:'not_found';idempotency_key:string};
export type FaxProposal={contract_version:1;scope:FaxScope;ticket_id:string;revision_id:string;version:number;state:'pending_approval'|'approved'|'rejected'|'needs_verify';expires_at:string;expired:boolean;label:string;vendor:FaxProvider;source_sha256:string;fax:{received_at:string;pages:number;viewed:boolean|null;sender_label:string;sender_number:string|null;sender_identity:'provider_reported_unverified';image_available:boolean};payload_sha256:string;source_withheld:false;receipt_sha256:string};
const text=(v:unknown,max:number):v is string=>typeof v==='string'&&v.trim().length>0&&Array.from(v).length<=max&&!/[\x00-\x1f\x7f]/.test(v);
const provider=(v:unknown):v is FaxProvider=>v==='srfax'||v==='documo'||v==='spruce';
const sameScope=(a:unknown,b:FaxScope)=>validFaxScope(a)&&vendorCanonical(a)===vendorCanonical(b);
export function validateFaxStatus(v:unknown):FaxStatus{
 if(!faxObject(v,'contract_version,installations,grants')||v.contract_version!==1||!Array.isArray(v.installations)||v.installations.length>20||!Array.isArray(v.grants)||v.grants.length>100)return bad();
 if(v.installations.some(i=>!faxObject(i,'connection_id,label,vendor,metadata_available,image_available,image_block_reason')||!vendorUuid(i.connection_id)||!text(i.label,80)||!provider(i.vendor)||typeof i.metadata_available!=='boolean'||typeof i.image_available!=='boolean'||i.image_block_reason!==null&&!text(i.image_block_reason,80)||i.vendor==='spruce'&&i.image_available))return bad();
 if(v.grants.some(g=>!faxObject(g,'grant_id,label,image_enabled,expires_at,state')||!vendorUuid(g.grant_id)||!text(g.label,80)||typeof g.image_enabled!=='boolean'||!stamp(g.expires_at)||!['granted','revoked','expired','installation_changed'].includes(String(g.state))))return bad();
 if(new Set(v.installations.map(i=>i.connection_id)).size!==v.installations.length||new Set(v.grants.map(g=>g.grant_id)).size!==v.grants.length)return bad();return v as FaxStatus;
}
export function validateFaxMetadata(v:unknown):FaxMetadata{
 if(!faxObject(v,'ordinal,source_sha256,sender_label,sender_number,sender_identity,received_at,pages,viewed,image_available,image_block_reason')||!integer(v.ordinal,1,25)||!faxHash(v.source_sha256)||!text(v.sender_label,160)||!stamp(v.received_at)||!integer(v.pages,0,10000)||v.viewed!==null&&typeof v.viewed!=='boolean'||v.sender_identity!=='provider_reported_unverified'||v.sender_number!==null&&!text(v.sender_number,80)||typeof v.image_available!=='boolean'||v.image_available&&Number(v.pages)<1||v.image_block_reason!==null&&!text(v.image_block_reason,80))return bad();return v as FaxMetadata;
}
async function sealed(v:Record<string,unknown>):Promise<void>{const {receipt_sha256,...body}=v;if(!faxHash(receipt_sha256)||receipt_sha256!==await faxCommitment(body))return bad();}
export async function validateFaxReceipt(v:unknown,scope:FaxScope,p?:FaxPending):Promise<FaxReceipt>{
 const optional='grant_id,label,vendor,image_enabled,expires_at,observation_id,source_sha256,inbox_complete,items,ticket_id,revision_id,version,decision_id,approval_sha256,operation_id,retry_allowed,document_sha256,pages';
 if(!faxObject(v,'contract_version,scope,kind,idempotency_key,request_sha256,public_request_sha256,receipt_sha256,source_withheld,state',optional)||v.contract_version!==1||!sameScope(v.scope,scope)||!key(v.idempotency_key)||!['grant','revoke','observe','propose','decide','acquire'].includes(String(v.kind))||!faxHash(v.request_sha256)||!faxHash(v.public_request_sha256)||typeof v.source_withheld!=='boolean'||!['granted','revoked','observed','pending_approval','approved','rejected','outcome_unconfirmed','acquired'].includes(String(v.state)))return bad();
 await sealed(v);const r=v as unknown as FaxReceipt;
 for(const n of ['grant_id','observation_id','ticket_id','revision_id','decision_id','operation_id'])if(n in v&&!vendorUuid(v[n]))return bad();
 if('expires_at'in v&&!stamp(v.expires_at))return bad();
 if('label'in v&&!text(v.label,80)||'vendor'in v&&!provider(v.vendor)||'image_enabled'in v&&typeof v.image_enabled!=='boolean'||'version'in v&&!integer(v.version,1,100)||'approval_sha256'in v&&v.approval_sha256!==null&&!faxHash(v.approval_sha256)||'source_sha256'in v&&!faxHash(v.source_sha256))return bad();
 if(r.kind==='observe'&&r.state==='observed'){
  if(!vendorUuid(r.observation_id)||!faxHash(r.source_sha256)||r.inbox_complete!==false||!Array.isArray(r.items)||r.items.length>25||r.source_withheld)return bad();
  r.items.forEach(validateFaxMetadata);if(new Set(r.items.map(i=>i.source_sha256)).size!==r.items.length||r.items.some((i,index)=>i.ordinal!==index+1))return bad();
 }
 if(r.kind==='acquire'&&(r.retry_allowed!==false||!vendorUuid(r.operation_id)||!vendorUuid(r.ticket_id)||!vendorUuid(r.revision_id)))return bad();
 if(r.source_withheld&&('items'in r||r.document_sha256!=null||r.pages!=null))return bad();
 if(r.state==='acquired'&&!r.source_withheld&&(!faxHash(r.document_sha256)||!integer(r.pages,1,50)))return bad();
 if(p){validateFaxPending(p);if(r.kind!==p.kind||r.idempotency_key!==p.request.idempotency_key||r.public_request_sha256!==await faxCommitment(p.request))return bad();
  for(const n of ['grant_id','ticket_id','revision_id','observation_id'])if(n in p.request&&n in r&&(r as unknown as Record<string,unknown>)[n]!== (p.request as unknown as Record<string,unknown>)[n])return bad();
  if(p.kind==='observe'&&r.items?.some(i=>Date.parse(i.received_at)<Date.parse(p.request.starts_at)||Date.parse(i.received_at)>Date.parse(p.request.ends_at)))return bad();
  if(p.kind==='decide'&&(r.state!==(p.request.choice==='approve'?'approved':'rejected')||r.version!==p.request.expected_version+1)||p.kind==='acquire'&&r.version!==p.request.expected_version+1)return bad();
 }return r;
}
export async function validateFaxProposal(v:unknown,scope:FaxScope,ticket:string,revision:string):Promise<FaxProposal>{
 if(!faxObject(v,'contract_version,scope,ticket_id,revision_id,version,state,expires_at,expired,label,vendor,source_sha256,fax,payload_sha256,source_withheld,receipt_sha256')||v.contract_version!==1||!sameScope(v.scope,scope)||v.ticket_id!==ticket||v.revision_id!==revision||!vendorUuid(ticket)||!vendorUuid(revision)||!integer(v.version,1,100)||!['pending_approval','approved','rejected','needs_verify'].includes(String(v.state))||!stamp(v.expires_at)||typeof v.expired!=='boolean'||!text(v.label,80)||!provider(v.vendor)||!faxHash(v.source_sha256)||!faxHash(v.payload_sha256)||v.source_withheld!==false||!faxObject(v.fax,'received_at,pages,viewed,sender_label,sender_number,sender_identity,image_available')||!stamp(v.fax.received_at)||!integer(v.fax.pages,1,50)||v.fax.viewed!==null&&typeof v.fax.viewed!=='boolean'||v.fax.sender_number!==null&&!text(v.fax.sender_number,80)||v.fax.sender_identity!=='provider_reported_unverified'||!text(v.fax.sender_label,160)||v.fax.image_available!==true)return bad();
 await sealed(v);return v as unknown as FaxProposal;
}
export const faxInboundApi={
 status:async(i:AuthenticatedWorkspaceIdentity,signal?:AbortSignal)=>validateFaxStatus(await faxInboundRequest(i,'/fax-inbound',undefined,signal)),
 command:async(i:AuthenticatedWorkspaceIdentity,s:FaxScope,p:FaxPending,signal?:AbortSignal)=>{validateFaxPending(p);return validateFaxReceipt(await faxInboundRequest(i,'/fax-inbound/'+p.kind,p.request,signal),s,p);},
 resolve:async(i:AuthenticatedWorkspaceIdentity,s:FaxScope,p:FaxPending,signal?:AbortSignal):Promise<FaxReceipt|FaxNotFound>=>{validateFaxPending(p);const v=await faxInboundRequest(i,'/fax-inbound/resolve',{idempotency_key:p.request.idempotency_key},signal);if(faxObject(v,'contract_version,state,idempotency_key')&&v.contract_version===1&&v.state==='not_found'&&v.idempotency_key===p.request.idempotency_key)return v as FaxNotFound;return validateFaxReceipt(v,s,p);},
 proposal:async(i:AuthenticatedWorkspaceIdentity,s:FaxScope,ticket:string,revision:string,signal?:AbortSignal)=>validateFaxProposal(await faxInboundRequest(i,'/fax-inbound/proposal/'+ticket+'/'+revision,undefined,signal),s,ticket,revision),
 document:async(i:AuthenticatedWorkspaceIdentity,r:FaxReceipt,signal?:AbortSignal)=>{if(r.kind!=='acquire'||r.state!=='acquired'||r.source_withheld||!vendorUuid(r.operation_id)||!faxHash(r.document_sha256))return bad();const bytes=await faxInboundRequest(i,'/fax-inbound/document/'+r.operation_id,undefined,signal,true);if(!(bytes instanceof Uint8Array)||await vendorSha256(bytes)!==r.document_sha256)return bad();return bytes;},
};
