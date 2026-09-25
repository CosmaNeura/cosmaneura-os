import {workspaceFetch} from './workspace-protocol';
import {WorkspaceApiError,type WorkspaceIdentity} from './workspace-api';
import {assertCurrentDesktopSession,workspaceAuthHeaders} from './workspace-auth-headers';
import {permittedWorkspaceApi} from './workspace-origin';
import {parseVendorJson,vendorCanonical,vendorBytes,vendorUuid,VendorContractError} from './vendor-contract';
import {VendorSetupContractError,validateVendorSetup,validateVendorSetupOperation,verifyVendorSetupView,verifyVendorSetupReceipt,type VendorSetupOperation,type VendorSetupScope} from './vendor-setup-contract';
type Prepared={path:string;method:'GET'|'POST';body?:string};
const stop=(stream:{cancel:()=>Promise<unknown>}|null|undefined)=>{try{void stream?.cancel().catch(()=>{});}catch{/* Cancellation does not replace the result. */}};
const codes=new Set(['vendor_setup_unavailable','invalid_vendor_setup_request','vendor_setup_client_update_required','vendor_setup_request_too_large','vendor_installation_changed','vendor_patient_unavailable','vendor_setup_integrity','vendor_setup_idempotency_conflict','vendor_account_changed','vendor_permission_expired','vendor_setup_changed','vendor_setup_limit','vendor_setup_already_exists','vendor_setup_disabled','vendor_setup_revision_required','vendor_binding_unavailable','vendor_setup_inactive']);
function safeError(value:unknown):string|undefined{if(!value||typeof value!=='object')return;const v=value as {error?:{code?:unknown}};if(Object.keys(v).join(',')==='error'&&v.error&&Object.keys(v.error).join(',')==='code'&&typeof v.error.code==='string'&&codes.has(v.error.code))return v.error.code;}
/** A single 15-second budget includes credentials, hashing, bounded HTTP reading and exact verification. */
async function exchange<T>(identity:WorkspaceIdentity,maximum:number,prepare:()=>Promise<Prepared>,verify:(value:unknown)=>Promise<T>,signal?:AbortSignal):Promise<T>{
  const controller=new AbortController(),deadline=performance.now()+15000,abort=()=>controller.abort();let reader:ReadableStreamDefaultReader<Uint8Array>|undefined;
  const check=()=>{if(performance.now()>=deadline)abort();controller.signal.throwIfAborted();if('mode'in identity)assertCurrentDesktopSession(identity);};
  const interrupted=new Promise<never>((_,reject)=>controller.signal.addEventListener('abort',()=>reject(new WorkspaceApiError(503)),{once:true}));void interrupted.catch(()=>{});
  const wait=<V,>(promise:Promise<V>)=>Promise.race([promise,interrupted]);
  const timer=setTimeout(abort,15000),cancel=()=>stop(reader);signal?.addEventListener('abort',abort,{once:true});controller.signal.addEventListener('abort',cancel,{once:true});if(signal?.aborted)abort();
  try{
    check();const prepared=await wait(prepare());check();
    const base=import.meta.env.VITE_API_BASE?.trim().replace(/\/+$/,'')||'http://127.0.0.1:8000';if(!permittedWorkspaceApi(base,import.meta.env.VITE_DESKTOP_SYNTHETIC_ENABLED==='true',window.location.href))throw new WorkspaceApiError(503);
    const headers='mode'in identity?await wait(workspaceAuthHeaders(identity,base).catch(()=>{throw new WorkspaceApiError(401);})):new Headers({'X-Box-Id':identity.boxId,'X-Actor-Principal-Id':identity.actorId});
    check();headers.set('X-Cosmas-Vendor-Setup-Contract','1');headers.set('Accept','application/json');headers.set('Content-Type','application/json');
    const response=await wait(workspaceFetch(identity,base+prepared.path,{method:prepared.method,headers,body:prepared.body,signal:controller.signal,credentials:'omit',redirect:'error',cache:'no-store',referrerPolicy:'no-referrer'}));
    check();if([401,403,404,426].includes(response.status)){stop(response.body);throw new WorkspaceApiError(response.status);}
    const responseMaximum=response.status===200?maximum:2048;const length=response.headers.get('content-length');
    if(!response.headers.get('cache-control')?.split(',').some(v=>v.trim().toLowerCase()==='no-store')||response.headers.get('content-type')?.split(';',1)[0].trim().toLowerCase()!=='application/json'||length!==null&&(!/^(?:0|[1-9][0-9]*)$/.test(length)||Number(length)>responseMaximum)){stop(response.body);throw new WorkspaceApiError(503);}
    reader=response.body?.getReader();if(!reader)throw new WorkspaceApiError(503);const buffer=new Uint8Array(responseMaximum);let size=0;
    while(true){check();const part=await wait(reader.read());check();if(part.done)break;if(part.value.byteLength>responseMaximum-size)throw new WorkspaceApiError(503);buffer.set(part.value,size);size+=part.value.byteLength;}
    const value=parseVendorJson(new TextDecoder('utf-8',{fatal:true}).decode(buffer.subarray(0,size)));check();if(response.status!==200)throw new WorkspaceApiError(response.ok?503:response.status,safeError(value));
    const result=await wait(verify(value));check();return result;
  }catch(e){if(e instanceof WorkspaceApiError)throw e;throw new WorkspaceApiError(e instanceof VendorSetupContractError||e instanceof VendorContractError?502:503);}
  finally{clearTimeout(timer);signal?.removeEventListener('abort',abort);controller.signal.removeEventListener('abort',cancel);stop(reader);try{reader?.releaseLock();}catch{/* A discarded read may still settle. */}controller.abort();}
}
const id=(value:string)=>{if(!vendorUuid(value))throw new VendorSetupContractError();return value;};
const scope=(identity:WorkspaceIdentity,value:VendorSetupScope,expected?:VendorSetupScope)=>{validateVendorSetup('Scope',value);if(expected&&vendorCanonical(value)!==vendorCanonical(expected)||!('mode'in identity)&&(value.box_id!==identity.boxId||value.owner_id!==identity.actorId))throw new VendorSetupContractError();};
export const vendorSetupApi={
  catalog:(identity:WorkspaceIdentity,signal?:AbortSignal)=>exchange(identity,131072,async()=>({path:'/vendor-settings',method:'GET'}),async value=>{const c=await verifyVendorSetupView('Catalog',value);scope(identity,c.scope);return c;},signal),
  detail:(identity:WorkspaceIdentity,expected:VendorSetupScope,setupId:string,signal?:AbortSignal)=>exchange(identity,32768,async()=>{scope(identity,expected);return {path:'/vendor-settings/'+id(setupId),method:'GET'};},async value=>{const d=await verifyVendorSetupView('Detail',value);scope(identity,d.scope,expected);if(d.summary.setup_id!==setupId)throw new VendorSetupContractError();return d;},signal),
  history:(identity:WorkspaceIdentity,expected:VendorSetupScope,setupId:string,signal?:AbortSignal)=>exchange(identity,1048576,async()=>{scope(identity,expected);return {path:'/vendor-settings/'+id(setupId)+'/history',method:'GET'};},async value=>{const h=await verifyVendorSetupView('History',value);scope(identity,h.scope,expected);if(h.setup_id!==setupId)throw new VendorSetupContractError();return h;},signal),
  command:(identity:WorkspaceIdentity,operation:VendorSetupOperation,signal?:AbortSignal)=>exchange(identity,8192,async()=>{const op=await validateVendorSetupOperation(operation);scope(identity,op.scope);if(vendorBytes(op.request)>8192)throw new VendorSetupContractError();return {path:'/vendor-settings/'+op.kind,method:'POST',body:vendorCanonical(op.request)};},async value=>{const r=await verifyVendorSetupReceipt(value,operation);if(r.outcome!=='recorded')throw new VendorSetupContractError();return r;},signal),
  resolve:(identity:WorkspaceIdentity,operation:VendorSetupOperation,signal?:AbortSignal)=>exchange(identity,8192,async()=>{const op=await validateVendorSetupOperation(operation);scope(identity,op.scope);return {path:'/vendor-settings/resolve',method:'POST',body:vendorCanonical({command_kind:op.kind,idempotency_key:op.request.idempotency_key,request_sha256:op.request_sha256})};},value=>verifyVendorSetupReceipt(value,operation),signal),
};
