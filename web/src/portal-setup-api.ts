import {workspaceFetch} from './workspace-protocol';
import {WorkspaceApiError,type WorkspaceIdentity} from './workspace-api';
import {workspaceAuthHeaders,assertCurrentDesktopSession} from './workspace-auth-headers';
import {permittedWorkspaceApi} from './workspace-origin';
import {parseVendorJson,vendorCanonical} from './vendor-contract';
import {vendorObject,vendorUuid,VendorContractError} from './vendor-contract';
import {validatePortalOperation,verifyPortalCatalog,verifyPortalDetail,verifyPortalReceipt,type PortalOperation} from './portal-setup-contract';

async function exchange<T>(identity:WorkspaceIdentity,path:string,verify:(v:unknown)=>Promise<T>,body?:unknown):Promise<T>{
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),15000);
  const interrupted=new Promise<never>((_,reject)=>controller.signal.addEventListener('abort',()=>reject(new WorkspaceApiError(503)),{once:true}));void interrupted.catch(()=>{});
  const wait=<V,>(promise:Promise<V>)=>Promise.race([promise,interrupted]);
  const current=()=>{controller.signal.throwIfAborted();if('mode'in identity)assertCurrentDesktopSession(identity);};
  let reader:ReadableStreamDefaultReader<Uint8Array>|undefined;
  try{
    const base=import.meta.env.VITE_API_BASE?.trim().replace(/\/+$/,'')||'http://127.0.0.1:8000';
    if(!permittedWorkspaceApi(base,import.meta.env.VITE_DESKTOP_SYNTHETIC_ENABLED==='true',window.location.href))throw new WorkspaceApiError(503);
    current();const headers='mode'in identity?await wait(workspaceAuthHeaders(identity,base)):new Headers({'X-Box-Id':identity.boxId,'X-Actor-Principal-Id':identity.actorId});current();
    headers.set('X-Cosmas-Portal-Contract','1');headers.set('Content-Type','application/json');headers.set('Accept','application/json');
    const response=await wait(workspaceFetch(identity,base+path,{method:body===undefined?'GET':'POST',headers,body:body===undefined?undefined:vendorCanonical(body),signal:controller.signal,credentials:'omit',redirect:'error',cache:'no-store',referrerPolicy:'no-referrer'}));current();
    if([401,403,404,426].includes(response.status))throw new WorkspaceApiError(response.status);
    if(response.headers.get('content-type')?.split(';')[0]!=='application/json'||!response.headers.get('cache-control')?.split(',').some(v=>v.trim()==='no-store'))throw new WorkspaceApiError(503);
    reader=response.body?.getReader();if(!reader)throw new WorkspaceApiError(503);const chunks:Uint8Array[]=[];let length=0;
    while(true){const piece=await wait(reader.read());current();if(piece.done)break;length+=piece.value.byteLength;if(length>2_097_152)throw new WorkspaceApiError(503);chunks.push(piece.value);}
    const bytes=new Uint8Array(length);let offset=0;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length;}
    const value=parseVendorJson(new TextDecoder('utf-8',{fatal:true}).decode(bytes));
    if(response.status!==200)throw new WorkspaceApiError(response.status);
    const checked=await wait(verify(value));current();return checked;
  }catch(error){if(error instanceof WorkspaceApiError)throw error;throw new WorkspaceApiError(503);}
  finally{clearTimeout(timer);try{void reader?.cancel().catch(()=>{});}catch{/* Retain saved request. */}controller.abort();}
}
export const portalSetupApi={
  catalog:(identity:WorkspaceIdentity)=>exchange(identity,'/portal-setup',verifyPortalCatalog),
  detail:(identity:WorkspaceIdentity,id:string)=>{if(!vendorUuid(id))throw new VendorContractError();return exchange(identity,'/portal-setup/'+id,async value=>{const result=await verifyPortalDetail(value);if(result.connection_id!==id)throw new VendorContractError();return result;});},
  history:(identity:WorkspaceIdentity,id:string)=>{if(!vendorUuid(id))throw new VendorContractError();return exchange(identity,'/portal-setup/'+id+'/history',async(value)=>{if(!vendorObject(value)||Object.keys(value).sort().join(',')!=='connection_id,contract_version,receipts'||value.contract_version!==1||value.connection_id!==id||!Array.isArray(value.receipts)||value.receipts.length>1000)throw new VendorContractError();const rows=await Promise.all(value.receipts.map(v=>verifyPortalReceipt(v)));if(rows.some((row,index)=>row.connection_id!==id||row.effect?.version!==index+1))throw new VendorContractError();return rows;});},
  command:async(identity:WorkspaceIdentity,operation:PortalOperation)=>{const op=await validatePortalOperation(operation);return exchange(identity,'/portal-setup/'+op.kind,value=>verifyPortalReceipt(value,op),op.request);},
  resolve:async(identity:WorkspaceIdentity,operation:PortalOperation)=>{const op=await validatePortalOperation(operation);return exchange(identity,'/portal-setup/resolve',value=>verifyPortalReceipt(value,op),{command_kind:op.kind,idempotency_key:op.request.idempotency_key,request_sha256:op.request_sha256});},
};
