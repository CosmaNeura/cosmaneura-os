import {workspaceFetch} from './workspace-protocol';
import {WorkspaceApiError,type WorkspaceIdentity} from './workspace-api';
import {assertCurrentDesktopSession,workspaceAuthHeaders} from './workspace-auth-headers';
import {permittedWorkspaceApi} from './workspace-origin';
import {parseVendorJson,vendorCanonical,vendorUuid,VendorContractError} from './vendor-contract';
import {FinanceContractError,verifyFinanceView} from './finance-contract';
import {validateFinanceOperation,financeOperationPath,financeRequestLimit,financeResolveRequest,verifyFinanceOperationReceipt,type FinanceOperation} from './finance-operation';
import type {FinanceContractTypes,FinanceResponse} from './finance-schema';

type Prepared={path:string;method:'GET'|'POST';body?:string};
const stop=(stream:{cancel:()=>Promise<unknown>}|null|undefined)=>{try{void stream?.cancel().catch(()=>{});}catch{/* Cancellation does not replace the result. */}};
const codes=new Set(['invalid_finance_request','finance_contract_required','finance_work_unavailable','finance_unavailable','finance_feature_disabled','finance_source_changed','finance_selection_changed','finance_idempotency_conflict','finance_revision_changed','finance_history_limit','finance_private_text_forbidden','finance_approval_expired','finance_submit_already_claimed','finance_original_account_unavailable','finance_reference_unavailable','finance_read_in_progress','finance_evidence_changed','finance_result_changed','finance_exception_unresolved']);
function safeError(value:unknown):string|undefined{if(!value||typeof value!=='object')return;const v=value as {contract_version:unknown;error?:{code?:unknown}};if(Object.keys(v).sort().join(',')==='contract_version,error'&&v.contract_version===1&&v.error&&Object.keys(v.error).join(',')==='code'&&typeof v.error.code==='string'&&codes.has(v.error.code))return v.error.code;}
/** A single 30-second budget includes credentials, hashing, bounded HTTP reading and exact verification. */
async function exchange<T>(identity:WorkspaceIdentity,maximum:number,prepare:()=>Promise<Prepared>,verify:(value:unknown)=>Promise<T>,signal?:AbortSignal):Promise<T>{
  const controller=new AbortController(),deadline=performance.now()+30000,abort=()=>controller.abort();let reader:ReadableStreamDefaultReader<Uint8Array>|undefined;
  const check=()=>{if(performance.now()>=deadline)abort();controller.signal.throwIfAborted();if('mode'in identity)assertCurrentDesktopSession(identity);};
  const interrupted=new Promise<never>((_,reject)=>controller.signal.addEventListener('abort',()=>reject(new WorkspaceApiError(503)),{once:true}));void interrupted.catch(()=>{});
  const wait=<V,>(promise:Promise<V>)=>Promise.race([promise,interrupted]);
  const timer=setTimeout(abort,30000),cancel=()=>stop(reader);signal?.addEventListener('abort',abort,{once:true});controller.signal.addEventListener('abort',cancel,{once:true});if(signal?.aborted)abort();
  try{
    check();const prepared=await wait(prepare());check();
    const base=import.meta.env.VITE_API_BASE?.trim().replace(/\/+$/,'')||'http://127.0.0.1:8000';if(!permittedWorkspaceApi(base,import.meta.env.VITE_DESKTOP_SYNTHETIC_ENABLED==='true',window.location.href))throw new WorkspaceApiError(503);
    const headers='mode'in identity?await wait(workspaceAuthHeaders(identity,base).catch(()=>{throw new WorkspaceApiError(401);})):new Headers({'X-Box-Id':identity.boxId,'X-Actor-Principal-Id':identity.actorId});
    check();headers.set('X-Cosmas-Finance-Contract','1');headers.set('Accept','application/json');headers.set('Content-Type','application/json');
    const response=await wait(workspaceFetch(identity,base+prepared.path,{method:prepared.method,headers,body:prepared.body,signal:controller.signal,credentials:'omit',redirect:'error',cache:'no-store',referrerPolicy:'no-referrer'}));
    check();if([401,403,404,426].includes(response.status)){stop(response.body);throw new WorkspaceApiError(response.status);}
    const length=response.headers.get('content-length');
    if(!response.headers.get('cache-control')?.split(',').some(v=>v.trim().toLowerCase()==='no-store')||response.headers.get('content-type')?.split(';',1)[0].trim().toLowerCase()!=='application/json'||length!==null&&(!/^(?:0|[1-9][0-9]*)$/.test(length)||Number(length)>maximum)){stop(response.body);throw new WorkspaceApiError(503);}
    reader=response.body?.getReader();if(!reader)throw new WorkspaceApiError(503);const buffer=new Uint8Array(maximum);let size=0;
    while(true){check();const part=await wait(reader.read());check();if(part.done)break;if(part.value.byteLength>maximum-size)throw new WorkspaceApiError(503);buffer.set(part.value,size);size+=part.value.byteLength;}
    const value=parseVendorJson(new TextDecoder('utf-8',{fatal:true}).decode(buffer.subarray(0,size)));check();if(response.status!==200)throw new WorkspaceApiError(response.ok?503:response.status,safeError(value));
    const result=await wait(verify(value));check();return result;
  }catch(e){if(e instanceof WorkspaceApiError)throw e;throw new WorkspaceApiError(e instanceof FinanceContractError||e instanceof VendorContractError?502:503);}
  finally{clearTimeout(timer);signal?.removeEventListener('abort',abort);controller.signal.removeEventListener('abort',cancel);stop(reader);try{reader?.releaseLock();}catch{/* A discarded read may still settle. */}controller.abort();}
}
const id=(v:string)=>{if(!vendorUuid(v))throw new FinanceContractError();return v;};
const root=(wid:string)=>`/workspaces/${id(wid)}/finance-work`;
const cursor=(v?:string)=>{if(v===undefined)return '';if(v.length>512||!/^[A-Za-z0-9_-]+\.[a-f0-9]{64}$/.test(v))throw new FinanceContractError();return '?cursor='+encodeURIComponent(v);};
const read=<N extends 'FinanceOptions'|'FinanceCatalog'|'FinanceDetail'|'FinanceObservations'>(identity:WorkspaceIdentity,name:N,path:()=>string,bind:(v:FinanceContractTypes[N])=>boolean,signal?:AbortSignal)=>exchange(identity,65536,async()=>({path:path(),method:'GET'}),async value=>{const v=await verifyFinanceView(name,value);if(!bind(v))throw new FinanceContractError();return v;},signal);
export const financeApi={
  options:(identity:WorkspaceIdentity,wid:string,signal?:AbortSignal)=>read(identity,'FinanceOptions',()=>root(wid)+'/options',v=>v.workspace_id===wid,signal),
  catalog:(identity:WorkspaceIdentity,wid:string,next?:string,signal?:AbortSignal)=>read(identity,'FinanceCatalog',()=>root(wid)+cursor(next),v=>v.workspace_id===wid,signal),
  detail:(identity:WorkspaceIdentity,wid:string,tid:string,signal?:AbortSignal)=>read(identity,'FinanceDetail',()=>root(wid)+'/'+id(tid),v=>v.workspace_id===wid&&v.summary.ticket_id===tid,signal),
  observations:(identity:WorkspaceIdentity,wid:string,tid:string,operationId:string,next?:string,signal?:AbortSignal)=>read(identity,'FinanceObservations',()=>root(wid)+'/'+id(tid)+'/observations'+cursor(next),v=>v.workspace_id===wid&&v.ticket_id===tid&&v.operation_id===operationId,signal),
  /** Only the immutable Cosmas receipt is read; no Stripe request is made by this resolver. */
  recover:(identity:WorkspaceIdentity,operation:FinanceOperation,signal?:AbortSignal)=>exchange<FinanceResponse>(identity,16384,async()=>{const op=await validateFinanceOperation(operation);return {path:financeOperationPath(op,true),method:'POST',body:vendorCanonical(financeResolveRequest(op))};},v=>verifyFinanceOperationReceipt(operation,v),signal),
  /** An explicit user action; any retry retains the complete original request and key. */
  execute:(identity:WorkspaceIdentity,operation:FinanceOperation,signal?:AbortSignal)=>exchange<FinanceResponse>(identity,16384,async()=>{const op=await validateFinanceOperation(operation);const body=vendorCanonical(op.request);if(new TextEncoder().encode(body).length>financeRequestLimit(op.kind))throw new FinanceContractError();return {path:financeOperationPath(op),method:'POST',body};},v=>verifyFinanceOperationReceipt(operation,v),signal),
};
