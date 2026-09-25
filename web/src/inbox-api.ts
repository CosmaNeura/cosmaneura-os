import {workspaceFetch} from './workspace-protocol';
import {WorkspaceApiError,type WorkspaceIdentity} from './workspace-api';
import {assertCurrentDesktopSession,workspaceAuthHeaders} from './workspace-auth-headers';
import {permittedWorkspaceApi} from './workspace-origin';
import {parseVendorJson,vendorBytes,vendorCanonical,vendorObject,vendorUuid,VendorContractError} from './vendor-contract';
import {InboxContractError,validateInbox,validateInboxOperation,verifyInboxOperationReceipt,verifyInboxView,verifyInboxBundle,sameInboxScope,inboxSourceMetadata,inboxOperationPath,inboxResolveRequest,type InboxOperation} from './inbox-contract';
import type {Scope,SourceMetadata} from './inbox-schema';

const codes=new Set(['inbox_unavailable','inbox_integrity','invalid_inbox_request','inbox_contract_required','inbox_feature_disabled','inbox_binding_unavailable','inbox_source_changed','inbox_version_changed','inbox_workspace_changed','inbox_review_required','inbox_triage_required','inbox_result_changed','inbox_exception_unresolved','inbox_history_limit','inbox_idempotency_conflict']);
function errorCode(v:unknown):string|undefined {
  if(!vendorObject(v)||Object.keys(v).sort().join(',')!=='contract_version,error'||v.contract_version!==1||!vendorObject(v.error)||Object.keys(v.error).join(',')!=='code'||typeof v.error.code!=='string'||!codes.has(v.error.code))return;
  return v.error.code;
}
const id=(v:string)=>{if(!vendorUuid(v))throw new InboxContractError();return v;};
function checkScope(identity:WorkspaceIdentity,scope:Scope,expected?:Scope){
  validateInbox('Scope',scope);
  if(expected&&!sameInboxScope(scope,expected)||!('mode'in identity)&&(scope.box_id!==identity.boxId||scope.owner_id!==identity.actorId))throw new WorkspaceApiError(403);
}
type Read=(path:string,maximum:number,body?:string)=>Promise<unknown>;
type Prepared<T>={scope?:Scope;run:(read:Read)=>Promise<T>};
const stop=(stream:{cancel:()=>Promise<unknown>}|null|undefined)=>{try{void stream?.cancel().catch(()=>{});}catch{/* Cancellation cannot replace the result. */}};

/** One deadline covers preparation, fresh credentials, all bytes, hashes and the final session check. */
async function exchange<T>(identity:WorkspaceIdentity,prepare:()=>Promise<Prepared<T>>,signal?:AbortSignal):Promise<T>{
  const controller=new AbortController(),readers=new Set<ReadableStreamDefaultReader<Uint8Array>>(),deadline=performance.now()+15000;
  const abort=()=>controller.abort(),check=()=>{if(performance.now()>=deadline)abort();controller.signal.throwIfAborted();if('mode'in identity)assertCurrentDesktopSession(identity);};
  const interrupted=new Promise<never>((_,reject)=>controller.signal.addEventListener('abort',()=>{readers.forEach(stop);reject(new WorkspaceApiError(503));},{once:true}));void interrupted.catch(()=>{});
  const wait=<V,>(promise:Promise<V>)=>Promise.race([promise,interrupted]);
  const timer=setTimeout(abort,15000);signal?.addEventListener('abort',abort,{once:true});if(signal?.aborted)abort();
  try{
    check();if(!('mode'in identity))validateInbox('Scope',{box_id:identity.boxId,owner_id:identity.actorId});
    const prepared=await wait(prepare());check();if(prepared.scope)checkScope(identity,prepared.scope);
    const base=import.meta.env.VITE_API_BASE?.trim().replace(/\/+$/,'')||'http://127.0.0.1:8000';
    if(!permittedWorkspaceApi(base,import.meta.env.VITE_DESKTOP_SYNTHETIC_ENABLED==='true',window.location.href))throw new WorkspaceApiError(503);
    const headers='mode'in identity?await wait(workspaceAuthHeaders(identity,base).catch(()=>{throw new WorkspaceApiError(401);})):new Headers({'X-Box-Id':identity.boxId,'X-Actor-Principal-Id':identity.actorId});
    check();headers.set('X-Cosmas-Inbox-Contract','1');headers.set('Accept','application/json');headers.set('Content-Type','application/json');
    const read:Read=async(path,maximum,body)=>{
      check();if(body!==undefined&&new TextEncoder().encode(body).byteLength>8192)throw new InboxContractError();
      const response=await wait(workspaceFetch(identity,base+path,{method:body===undefined?'GET':'POST',headers,body,signal:controller.signal,credentials:'omit',redirect:'error',cache:'no-store',referrerPolicy:'no-referrer'}));check();
      if([401,403,404,426].includes(response.status)){stop(response.body);throw new WorkspaceApiError(response.status);}
      const cap=response.status===200?maximum:2048,length=response.headers.get('content-length');
      if(!response.headers.get('cache-control')?.split(',').some(v=>v.trim().toLowerCase()==='no-store')||response.headers.get('content-type')?.split(';',1)[0].trim().toLowerCase()!=='application/json'||length!==null&&(!/^(?:0|[1-9][0-9]*)$/.test(length)||Number(length)>cap)){stop(response.body);throw new WorkspaceApiError(503);}
      const reader=response.body?.getReader();if(!reader)throw new WorkspaceApiError(503);readers.add(reader);const buffer=new Uint8Array(cap);let size=0;
      try{
        for(;;){check();const part=await wait(reader.read());check();if(part.done)break;if(part.value.byteLength>cap-size)throw new WorkspaceApiError(503);buffer.set(part.value,size);size+=part.value.byteLength;}
        const value=parseVendorJson(new TextDecoder('utf-8',{fatal:true}).decode(buffer.subarray(0,size)));check();
        if(response.status!==200)throw new WorkspaceApiError(response.ok?503:response.status,errorCode(value));return value;
      }finally{readers.delete(reader);stop(reader);try{reader.releaseLock();}catch{/* A discarded read may settle later. */}}
    };
    const result=await wait(prepared.run(read));check();return result;
  }catch(e){if(e instanceof WorkspaceApiError)throw e;throw new WorkspaceApiError(e instanceof InboxContractError||e instanceof VendorContractError?502:503);}
  finally{clearTimeout(timer);signal?.removeEventListener('abort',abort);readers.forEach(stop);controller.abort();}
}
export const inboxApi={
  // The signed identity need not contain Box/owner IDs. Derive them only from
  // this authorized catalog before loading any owner-scoped recovery storage.
  catalog:(identity:WorkspaceIdentity,signal?:AbortSignal)=>exchange(identity,async()=>({run:async read=>{const value=await verifyInboxView('Catalog',await read('/inbox',131072));checkScope(identity,value.scope);return value;}}),signal),
  detail:(identity:WorkspaceIdentity,scope:Scope,itemId:string,signal?:AbortSignal)=>exchange(identity,async()=>{
    validateInbox('Scope',scope);const expected=structuredClone(scope),path='/inbox/'+id(itemId);
    return {scope:expected,run:async read=>{const [detail,history]=await Promise.all([read(path,65536),read(path+'/history',2097152)]);const bundle=await verifyInboxBundle(detail,history,expected);if(bundle.detail.summary.item_id!==itemId)throw new InboxContractError();return bundle;}};
  },signal),
  history:(identity:WorkspaceIdentity,scope:Scope,itemId:string,signal?:AbortSignal)=>exchange(identity,async()=>{
    validateInbox('Scope',scope);const expected=structuredClone(scope),path='/inbox/'+id(itemId)+'/history';
    return {scope:expected,run:async read=>{const value=await verifyInboxView('History',await read(path,2097152));checkScope(identity,value.scope,expected);if(value.item_id!==itemId)throw new InboxContractError();return value;}};
  },signal),
  reviewOptions:(identity:WorkspaceIdentity,scope:Scope,itemId:string,signal?:AbortSignal)=>exchange(identity,async()=>{
    validateInbox('Scope',scope);const expected=structuredClone(scope),path='/inbox/'+id(itemId)+'/review-options';
    return {scope:expected,run:async read=>{const value=await verifyInboxView('ReviewOptions',await read(path,131072));checkScope(identity,value.scope,expected);if(value.item_id!==itemId)throw new InboxContractError();return value;}};
  },signal),
  source:(identity:WorkspaceIdentity,scope:Scope,itemId:string,source:SourceMetadata,patientLinkId:string,signal?:AbortSignal)=>exchange(identity,async()=>{
    validateInbox('Scope',scope);const expected=structuredClone(scope),metadata=validateInbox('SourceMetadata',source),patient=id(patientLinkId),path='/inbox/'+id(itemId)+'/sources/'+id(metadata.source_id);
    return {scope:expected,run:async read=>{const value=await verifyInboxView('Source',await read(path,65536));if(value.patient_link_id!==patient||vendorCanonical(inboxSourceMetadata(value))!==vendorCanonical(metadata))throw new InboxContractError();return value;}};
  },signal),
  execute:(identity:WorkspaceIdentity,operation:InboxOperation,signal?:AbortSignal)=>exchange(identity,async()=>{
    const op=await validateInboxOperation(operation);if(vendorBytes(op.request)>8192)throw new InboxContractError();
    return {scope:op.scope,run:async read=>verifyInboxOperationReceipt(op,await read(inboxOperationPath(op),8192,vendorCanonical(op.request)))};
  },signal),
  recover:(identity:WorkspaceIdentity,operation:InboxOperation,signal?:AbortSignal)=>exchange(identity,async()=>{
    const op=await validateInboxOperation(operation);
    return {scope:op.scope,run:async read=>verifyInboxOperationReceipt(op,await read('/inbox/resolve',8192,vendorCanonical(inboxResolveRequest(op))))};
  },signal),
};
