import {workspaceFetch} from './workspace-protocol';
import {WorkspaceApiError,type WorkspaceIdentity} from './workspace-api';
import {assertCurrentDesktopSession,workspaceAuthHeaders} from './workspace-auth-headers';
import {permittedWorkspaceApi} from './workspace-origin';
import {parseVendorJson,validateVendor,vendorCanonical,vendorSha256,vendorUuid,verifyVendorView,VendorContractError,type VendorReceipt} from './vendor-contract';
import {validateVendorOperation,vendorOperationPath,vendorRequestLimit,vendorResolveRequest,verifyOperationReceipt,canRetireVendorOperation,isVendorPreparationKind,type VendorOperation} from './vendor-operation';
import type {Document,VendorArtifactContent,VendorContractTypes} from './vendor-schema';

type Prepared={path:string;method:'GET'|'POST'|'PUT';body?:string|Uint8Array;contentType?:string;writeKey?:string};
const media=(value:string|null)=>value?.split(';',1)[0].trim().toLowerCase();
const noStore=(headers:Headers)=>headers.get('cache-control')?.split(',').some(v=>v.trim().toLowerCase()==='no-store');
const stop=(stream:{cancel:()=>Promise<unknown>}|null|undefined)=>{try{void stream?.cancel().catch(()=>{});}catch{/* Cancellation must not replace the outcome. */}};

/** One monotonic budget includes credentials, input/hash checks, HTTP streaming and receipt verification. No automatic retries. */
async function exchange<T>(identity:WorkspaceIdentity,seconds:number,maximum:number,prepare:()=>Promise<Prepared>,verify:(value:unknown)=>Promise<T>,signal?:AbortSignal,pdf?:Document):Promise<T>{
  const controller=new AbortController(),deadline=performance.now()+seconds*1000;
  const abort=()=>controller.abort();const check=()=>{if(performance.now()>=deadline)abort();controller.signal.throwIfAborted();if('mode'in identity)assertCurrentDesktopSession(identity);};
  let reader:ReadableStreamDefaultReader<Uint8Array>|undefined;
  const interrupted=new Promise<never>((_,reject)=>controller.signal.addEventListener('abort',()=>reject(new WorkspaceApiError(503)),{once:true}));
  // The rejection always has a consumer, including an already-aborted caller before its first await.
  void interrupted.catch(()=>{});
  const wait=<V,>(promise:Promise<V>)=>Promise.race([promise,interrupted]);
  const timer=setTimeout(abort,seconds*1000);signal?.addEventListener('abort',abort,{once:true});if(signal?.aborted)abort();
  const cancel=()=>stop(reader);controller.signal.addEventListener('abort',cancel,{once:true});
  try{
    check();const prepared=await wait(prepare());check();
    const base=import.meta.env.VITE_API_BASE?.trim().replace(/\/+$/,'')||'http://127.0.0.1:8000';
    if(!permittedWorkspaceApi(base,import.meta.env.VITE_DESKTOP_SYNTHETIC_ENABLED==='true',window.location.href))throw new WorkspaceApiError(503);
    let headers:Headers;if('mode'in identity)headers=await wait(workspaceAuthHeaders(identity,base).catch(()=>{throw new WorkspaceApiError(401);}));
    else headers=new Headers({'X-Box-Id':identity.boxId,'X-Actor-Principal-Id':identity.actorId});
    check();headers.set('X-Cosmas-Vendor-Contract','1');headers.set('Accept',pdf?'application/pdf':'application/json');
    headers.set('Content-Type',prepared.contentType??'application/json');if(prepared.writeKey)headers.set('X-Cosmas-Artifact-Write-Key',prepared.writeKey);
    const response=await wait(workspaceFetch(identity,base+prepared.path,{method:prepared.method,headers,body:prepared.body as BodyInit|undefined,signal:controller.signal,credentials:'omit',redirect:'error',cache:'no-store',referrerPolicy:'no-referrer'}));
    check();if([401,403,404,426].includes(response.status)){stop(response.body);throw new WorkspaceApiError(response.status);}
    const isPdf=!!pdf&&response.status===200;const limit=isPdf?pdf.byte_length:maximum;
    const length=response.headers.get('content-length');
    if(!noStore(response.headers)||media(response.headers.get('content-type'))!==(isPdf?'application/pdf':'application/json')||length!==null&&(!/^(?:0|[1-9][0-9]*)$/.test(length)||Number(length)>limit||isPdf&&Number(length)!==limit)){
      stop(response.body);throw new WorkspaceApiError(503);
    }
    reader=response.body?.getReader();if(!reader)throw new WorkspaceApiError(503);
    const buffer=new Uint8Array(limit);let size=0;
    while(true){check();const part=await wait(reader.read());check();if(part.done)break;if(part.value.byteLength>limit-size)throw new WorkspaceApiError(503);buffer.set(part.value,size);size+=part.value.byteLength;}
    check();
    if(isPdf){const bytes=buffer.subarray(0,size);await wait(requirePdf(pdf,bytes));check();const result=await wait(verify(bytes));check();return result;}
    const value=parseVendorJson(new TextDecoder('utf-8',{fatal:true}).decode(buffer.subarray(0,size)));
    if(response.status!==200){throw new WorkspaceApiError(response.ok?503:response.status,safeError(value));}
    const checked=await wait(verify(value));check();return checked;
  }catch(error){if(error instanceof WorkspaceApiError)throw error;throw new WorkspaceApiError(error instanceof VendorContractError?502:503);}
  finally{clearTimeout(timer);signal?.removeEventListener('abort',abort);controller.signal.removeEventListener('abort',cancel);stop(reader);try{reader?.releaseLock();}catch{/* A discarded read can still settle. */}controller.abort();}
}
const codes=new Set(['invalid_vendor_request','vendor_work_unavailable','vendor_feature_disabled','vendor_idempotency_conflict','vendor_revision_changed','vendor_source_changed','vendor_selection_changed','vendor_permission_unavailable','vendor_approval_expired','vendor_submit_already_claimed','vendor_reference_unavailable','vendor_original_account_unavailable','vendor_read_in_progress','vendor_result_changed','vendor_evidence_changed','vendor_exception_unresolved','vendor_history_limit','vendor_credential_text_forbidden','artifact_unavailable','artifact_changed','artifact_write_in_progress','artifact_write_unconfirmed','vendor_unavailable']);
function safeError(value:unknown):string|undefined {if(!value||typeof value!=='object')return;const v=value as {contract_version:unknown;error?:{code?:unknown}};if(Object.keys(v).sort().join(',')==='contract_version,error'&&v.contract_version===1&&v.error&&Object.keys(v.error).join(',')==='code'&&typeof v.error.code==='string'&&codes.has(v.error.code))return v.error.code;}
export async function requirePdf(document:Document,bytes:Uint8Array):Promise<void>{validateVendor('Document',document);if(bytes.byteLength!==document.byte_length||bytes.byteLength<5||new TextDecoder('ascii').decode(bytes.subarray(0,5))!=='%PDF-'||await vendorSha256(bytes)!==document.sha256)throw new VendorContractError();}
const id=(value:string)=>{if(!vendorUuid(value))throw new VendorContractError();return value;};
const cursor=(value?:string)=>{if(value===undefined)return '';if(!/^[\x21-\x7e]{1,512}$/.test(value))throw new VendorContractError();return '?cursor='+encodeURIComponent(value);};
const root=(wid:string)=>`/workspaces/${id(wid)}/vendor-work`;
/** Saved database facts only; never calls the fax provider. */
export function readVendorSavedFaxStatus<T>(identity:WorkspaceIdentity,wid:string,tid:string,verify:(value:unknown)=>Promise<T>,signal?:AbortSignal):Promise<T>{
  return exchange(identity,30,8192,async()=>({path:root(wid)+'/'+id(tid)+'/status',method:'GET'}),verify,signal);
}
export function readVendorPracticeCatalog<T>(identity:WorkspaceIdentity,page:string|undefined,verify:(value:unknown)=>Promise<T>,signal?:AbortSignal):Promise<T>{
  return exchange(identity,30,1048576,async()=>({path:page===undefined?'/practice-work':`/practice-work/pages/${id(page)}`,method:'GET'}),verify,signal);
}
const read=<N extends 'Options'|'Catalog'|'Detail'|'ObservationPage'|'SharedVendorDetail'>(identity:WorkspaceIdentity,name:N,path:()=>string,bind:(value:VendorContractTypes[N])=>boolean,signal?:AbortSignal)=>exchange(identity,30,65536,async()=>({path:path(),method:'GET'}),async value=>{const result=await verifyVendorView(name,value);if(!bind(result))throw new VendorContractError();return result;},signal);
export const vendorApi={
  options:(identity:WorkspaceIdentity,wid:string,signal?:AbortSignal)=>read(identity,'Options',()=>root(wid)+'/options',v=>v.workspace_id===wid,signal),
  catalog:(identity:WorkspaceIdentity,wid:string,next?:string,signal?:AbortSignal)=>read(identity,'Catalog',()=>root(wid)+cursor(next),v=>v.workspace_id===wid,signal),
  detail:(identity:WorkspaceIdentity,wid:string,tid:string,signal?:AbortSignal)=>read(identity,'Detail',()=>root(wid)+'/'+id(tid),v=>v.workspace_id===wid&&v.summary.ticket_id===tid,signal),
  observations:(identity:WorkspaceIdentity,wid:string,tid:string,operationId:string,next?:string,signal?:AbortSignal)=>read(identity,'ObservationPage',()=>root(wid)+'/'+id(tid)+'/observations'+cursor(next),v=>v.ticket_id===tid&&v.operation_id===operationId,signal),
  shared:(identity:WorkspaceIdentity,tid:string,viewerId:string,signal?:AbortSignal)=>read(identity,'SharedVendorDetail',()=>'/practice-work/'+id(tid),v=>v.ticket_id===tid&&v.viewer_id===viewerId,signal),
  /** Resolves only Cosmas's saved local command receipt. Does not read or send to a provider. */
  recover:(identity:WorkspaceIdentity,operation:VendorOperation,signal?:AbortSignal)=>exchange<VendorReceipt>(identity,30,16384,async()=>{const op=await validateVendorOperation(operation);return {path:vendorOperationPath(op,true),method:'POST',body:vendorCanonical(vendorResolveRequest(op))};},value=>verifyOperationReceipt(operation,value),signal),
  /** Permanently blocks an exact unadmitted owner action. An existing recorded effect wins the race. */
  retire:(identity:WorkspaceIdentity,operation:VendorOperation,signal?:AbortSignal)=>exchange<VendorReceipt>(identity,30,16384,async()=>{
    const op=await validateVendorOperation(operation);if(!canRetireVendorOperation(op))throw new VendorContractError();
    const preparation=isVendorPreparationKind(op.kind);
    const request=validateVendor(preparation?'VendorPreparationRetire':'VendorRetire',{command_kind:op.kind,request:op.request,request_sha256:op.request_sha256});
    return {path:preparation?`/workspaces/${op.scope.id}/vendor-preparations/retire`:`/workspaces/${op.scope.id}/vendor-work/${op.target_id}/retire`,method:'POST',body:vendorCanonical(request)};
  },async value=>{const result=await verifyOperationReceipt(operation,value);if(!['recorded','retired'].includes(result.outcome))throw new VendorContractError();return result;},signal),
  /** Explicit user action only. Retry keeps the original exact request and idempotency key. */
  execute:(identity:WorkspaceIdentity,operation:VendorOperation,signal?:AbortSignal)=>exchange<VendorReceipt>(identity,30,16384,async()=>{const op=await validateVendorOperation(operation);if(op.kind==='artifact_content')throw new VendorContractError();const body=vendorCanonical(op.request);if(new TextEncoder().encode(body).length>vendorRequestLimit(op.kind))throw new VendorContractError();return {path:vendorOperationPath(op),method:'POST',body};},value=>verifyOperationReceipt(operation,value),signal),
  upload:(identity:WorkspaceIdentity,operation:VendorOperation,file:Blob,signal?:AbortSignal)=>exchange<VendorReceipt>(identity,60,8192,async()=>{
    const op=await validateVendorOperation(operation);if(op.kind!=='artifact_content')throw new VendorContractError();const r=op.request as VendorArtifactContent;
    if(file.size!==r.byte_length)throw new VendorContractError();const bytes=new Uint8Array(await file.arrayBuffer());await requirePdf({artifact_id:r.artifact_id,sha256:r.sha256,byte_length:r.byte_length,media_type:r.media_type},bytes);
    return {path:vendorOperationPath(op),method:'PUT',body:bytes,contentType:'application/pdf',writeKey:r.idempotency_key};
  },value=>verifyOperationReceipt(operation,value),signal),
  preview:(identity:WorkspaceIdentity,wid:string,document:Document,signal?:AbortSignal)=>exchange<Uint8Array>(identity,60,8192,async()=>{validateVendor('Document',document);return {path:`/workspaces/${id(wid)}/vendor-artifacts/${document.artifact_id}/content`,method:'GET'};},async value=>{if(!(value instanceof Uint8Array))throw new VendorContractError();return value;},signal,document),
};
