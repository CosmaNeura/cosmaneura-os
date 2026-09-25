import {workspaceFetch} from './workspace-protocol';
import {WorkspaceApiError,type WorkspaceIdentity} from './workspace-api';
import {assertCurrentDesktopSession,workspaceAuthHeaders} from './workspace-auth-headers';
import {permittedWorkspaceApi} from './workspace-origin';
import {parseVendorJson,vendorCanonical,vendorUuid,vendorObject,VendorContractError} from './vendor-contract';
import {validatePortalWorkOperation,verifyPortalWorkReceipt,verifyPortalWorkDetail,verifyPortalWorkCatalog,verifyPortalWorkObservations,portalWorkPath,portalWorkResolve,type PortalWorkOperation,type PortalWorkDetail} from './portal-work-contract';
type Prepared={path:string;method:'GET'|'POST';body?:string};
const stop=(stream:{cancel:()=>Promise<unknown>}|null|undefined)=>{try{void stream?.cancel().catch(()=>{});}catch{/* Cancellation does not replace the result. */}};
function safeError(value:unknown):string|undefined{if(vendorObject(value)&&Object.keys(value).join(',')==='detail'&&typeof value.detail==='string'&&/^(?:invalid_)?portal_work_[a-z_]{1,80}$/.test(value.detail))return value.detail;}
/** A single 50-second budget includes credentials, hashing, bounded HTTP reading and exact verification. */
async function exchange<T>(identity:WorkspaceIdentity,maximum:number,prepare:()=>Promise<Prepared>,verify:(value:unknown)=>Promise<T>,signal?:AbortSignal):Promise<T>{
  const controller=new AbortController(),deadline=performance.now()+50000,abort=()=>controller.abort();let reader:ReadableStreamDefaultReader<Uint8Array>|undefined;
  const check=()=>{if(performance.now()>=deadline)abort();controller.signal.throwIfAborted();if('mode'in identity)assertCurrentDesktopSession(identity);};
  const interrupted=new Promise<never>((_,reject)=>controller.signal.addEventListener('abort',()=>reject(new WorkspaceApiError(503)),{once:true}));void interrupted.catch(()=>{});
  const wait=<V,>(promise:Promise<V>)=>Promise.race([promise,interrupted]);
  const timer=setTimeout(abort,50000),cancel=()=>stop(reader);signal?.addEventListener('abort',abort,{once:true});controller.signal.addEventListener('abort',cancel,{once:true});if(signal?.aborted)abort();
  try{
    check();const prepared=await wait(prepare());check();
    const base=import.meta.env.VITE_API_BASE?.trim().replace(/\/+$/,'')||'http://127.0.0.1:8000';if(!permittedWorkspaceApi(base,import.meta.env.VITE_DESKTOP_SYNTHETIC_ENABLED==='true',window.location.href))throw new WorkspaceApiError(503);
    const headers='mode'in identity?await wait(workspaceAuthHeaders(identity,base).catch(()=>{throw new WorkspaceApiError(401);})):new Headers({'X-Box-Id':identity.boxId,'X-Actor-Principal-Id':identity.actorId});
    check();headers.set('X-Cosmas-Portal-Work-Contract','1');headers.set('Accept','application/json');headers.set('Content-Type','application/json');
    const response=await wait(workspaceFetch(identity,base+prepared.path,{method:prepared.method,headers,body:prepared.body,signal:controller.signal,credentials:'omit',redirect:'error',cache:'no-store',referrerPolicy:'no-referrer'}));
    check();if([401,403,404,426].includes(response.status)){stop(response.body);throw new WorkspaceApiError(response.status);}
    const length=response.headers.get('content-length');
    if(!response.headers.get('cache-control')?.split(',').some(v=>v.trim().toLowerCase()==='no-store')||response.headers.get('content-type')?.split(';',1)[0].trim().toLowerCase()!=='application/json'||length!==null&&(!/^(?:0|[1-9][0-9]*)$/.test(length)||Number(length)>maximum)){stop(response.body);throw new WorkspaceApiError(503);}
    reader=response.body?.getReader();if(!reader)throw new WorkspaceApiError(503);const buffer=new Uint8Array(maximum);let size=0;
    while(true){check();const part=await wait(reader.read());check();if(part.done)break;if(part.value.byteLength>maximum-size)throw new WorkspaceApiError(503);buffer.set(part.value,size);size+=part.value.byteLength;}
    const value=parseVendorJson(new TextDecoder('utf-8',{fatal:true}).decode(buffer.subarray(0,size)));check();if(response.status!==200)throw new WorkspaceApiError(response.ok?503:response.status,safeError(value));
    const result=await wait(verify(value));check();return result;
  }catch(e){if(e instanceof WorkspaceApiError)throw e;throw new WorkspaceApiError(e instanceof VendorContractError?502:503);}
  finally{clearTimeout(timer);signal?.removeEventListener('abort',abort);controller.signal.removeEventListener('abort',cancel);stop(reader);try{reader?.releaseLock();}catch{/* A discarded read may still settle. */}controller.abort();}
}
const id=(value:string)=>{if(!vendorUuid(value))throw new VendorContractError();return value;};
const root=(wid:string)=>`/workspaces/${id(wid)}/portal-work`;
export const portalWorkApi={
 catalog:(identity:WorkspaceIdentity,wid:string,signal?:AbortSignal)=>exchange(identity,2_097_152,async()=>({path:root(wid),method:'GET'}),async value=>{const c=await verifyPortalWorkCatalog(value);if(c.scope.id!==wid)throw new VendorContractError();return c;},signal),
 detail:(identity:WorkspaceIdentity,wid:string,tid:string,signal?:AbortSignal)=>exchange(identity,65536,async()=>({path:root(wid)+'/'+id(tid),method:'GET'}),async value=>{const d=await verifyPortalWorkDetail(value);if(d.scope.id!==wid||d.ticket_id!==tid)throw new VendorContractError();return d;},signal),
 observations:(identity:WorkspaceIdentity,detail:PortalWorkDetail,signal?:AbortSignal)=>exchange(identity,1_048_576,async()=>({path:root(detail.scope.id)+'/'+id(detail.ticket_id)+'/observations',method:'GET'}),value=>verifyPortalWorkObservations(value,detail),signal),
 execute:(identity:WorkspaceIdentity,operation:PortalWorkOperation,signal?:AbortSignal)=>exchange(identity,8192,async()=>{const op=await validatePortalWorkOperation(operation);return {path:portalWorkPath(op),method:'POST',body:vendorCanonical(op.request)};},value=>verifyPortalWorkReceipt(value,operation),signal),
 recover:(identity:WorkspaceIdentity,operation:PortalWorkOperation,signal?:AbortSignal)=>exchange(identity,8192,async()=>{const op=await validatePortalWorkOperation(operation);return {path:portalWorkPath(op,true),method:'POST',body:vendorCanonical(portalWorkResolve(op))};},value=>verifyPortalWorkReceipt(value,operation),signal),
};
