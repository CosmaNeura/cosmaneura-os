import {workspaceFetch} from './workspace-protocol';
import {WorkspaceApiError,type WorkspaceIdentity} from './workspace-api';
import {assertCurrentDesktopSession,workspaceAuthHeaders} from './workspace-auth-headers';
import {permittedWorkspaceApi} from './workspace-origin';
import {parseVendorJson,vendorBytes,vendorCanonical,vendorObject,VendorContractError} from './vendor-contract';
import {InboxHandoffContractError,validateInboxHandoff,validateInboxHandoffActor,validateInboxHandoffOperation,verifyInboxHandoffOperationReceipt,verifyInboxHandoffView,inboxHandoffOperationPath,inboxHandoffResolvePath,inboxHandoffResolveRequest,type InboxHandoffOperation,type InboxHandoffActor} from './inbox-handoff-contract';
import type {Scope} from './inbox-handoff-schema';

const codes=new Set(['inbox_handoff_unavailable','inbox_handoff_integrity','invalid_inbox_handoff','inbox_handoff_contract_required','inbox_handoff_idempotency_conflict','inbox_handoff_history_limit','inbox_handoff_changed']);
function errorCode(v:unknown):string|undefined {
  if(!vendorObject(v)||Object.keys(v).sort().join(',')!=='contract_version,error'||v.contract_version!==1||!vendorObject(v.error)||Object.keys(v.error).join(',')!=='code'||typeof v.error.code!=='string'||!codes.has(v.error.code))return;
  return v.error.code;
}
function checkActor(identity:WorkspaceIdentity,actor:InboxHandoffActor){
  validateInboxHandoffActor(actor);
  if(!('mode'in identity)&&(actor.box_id!==identity.boxId||actor.actor_id!==identity.actorId))throw new WorkspaceApiError(403);
}
type Read=(path:string,maximum:number,body?:string)=>Promise<unknown>;
type Prepared<T>={actor:InboxHandoffActor;run:(read:Read)=>Promise<T>};
const stop=(stream:{cancel:()=>Promise<unknown>}|null|undefined)=>{try{void stream?.cancel().catch(()=>{});}catch{/* Cancellation cannot replace the result. */}};

/** One deadline covers preparation, fresh credentials, all bytes, hashes and the final session check. */
async function exchange<T>(identity:WorkspaceIdentity,prepare:()=>Promise<Prepared<T>>,signal?:AbortSignal):Promise<T>{
  const controller=new AbortController(),readers=new Set<ReadableStreamDefaultReader<Uint8Array>>(),deadline=performance.now()+15000;
  const abort=()=>controller.abort(),check=()=>{if(performance.now()>=deadline)abort();controller.signal.throwIfAborted();if('mode'in identity)assertCurrentDesktopSession(identity);};
  const interrupted=new Promise<never>((_,reject)=>controller.signal.addEventListener('abort',()=>{readers.forEach(stop);reject(new WorkspaceApiError(503));},{once:true}));void interrupted.catch(()=>{});
  const wait=<V,>(promise:Promise<V>)=>Promise.race([promise,interrupted]);
  const timer=setTimeout(abort,15000);signal?.addEventListener('abort',abort,{once:true});if(signal?.aborted)abort();
  try{
    check();if(!('mode'in identity))validateInboxHandoffActor({box_id:identity.boxId,actor_id:identity.actorId});
    const prepared=await wait(prepare());check();checkActor(identity,prepared.actor);
    const base=import.meta.env.VITE_API_BASE?.trim().replace(/\/+$/,'')||'http://127.0.0.1:8000';
    if(!permittedWorkspaceApi(base,import.meta.env.VITE_DESKTOP_SYNTHETIC_ENABLED==='true',window.location.href))throw new WorkspaceApiError(503);
    const headers='mode'in identity?await wait(workspaceAuthHeaders(identity,base).catch(()=>{throw new WorkspaceApiError(401);})):new Headers({'X-Box-Id':identity.boxId,'X-Actor-Principal-Id':identity.actorId});
    check();headers.set('X-Cosmas-Inbox-Handoff-Contract','1');headers.set('Accept','application/json');headers.set('Content-Type','application/json');
    const read:Read=async(path,maximum,body)=>{
      check();if(body!==undefined&&new TextEncoder().encode(body).byteLength>8192)throw new InboxHandoffContractError();
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
  }catch(e){if(e instanceof WorkspaceApiError)throw e;throw new WorkspaceApiError(e instanceof InboxHandoffContractError||e instanceof VendorContractError?502:503);}
  finally{clearTimeout(timer);signal?.removeEventListener('abort',abort);readers.forEach(stop);controller.abort();}
}
export const inboxHandoffApi={
  // Catalog does not carry an actor scope. The caller supplies an already-authorized
  // account context; only an explicit detail request binds a ticket's originator.
  catalog:(identity:WorkspaceIdentity,actor:InboxHandoffActor,signal?:AbortSignal)=>exchange(identity,async()=>({actor:validateInboxHandoffActor(actor),run:async read=>verifyInboxHandoffView('Catalog',await read('/inbox-handoffs',131072))}),signal),
  detail:(identity:WorkspaceIdentity,scope:Scope,signal?:AbortSignal)=>exchange(identity,async()=>{
    const expected=validateInboxHandoff('Scope',scope);if(expected.kind!=='ticket')throw new InboxHandoffContractError();
    return {actor:{box_id:expected.box_id,actor_id:expected.actor_id},run:async read=>verifyInboxHandoffView('Detail',await read('/inbox-handoffs/'+expected.id,65536),expected)};
  },signal),
  execute:(identity:WorkspaceIdentity,operation:InboxHandoffOperation,signal?:AbortSignal)=>exchange(identity,async()=>{
    const op=await validateInboxHandoffOperation(operation);if(vendorBytes(op.request)>8192)throw new InboxHandoffContractError();
    return {actor:{box_id:op.scope.box_id,actor_id:op.scope.actor_id},run:async read=>{
      const receipt=await verifyInboxHandoffOperationReceipt(op,await read(inboxHandoffOperationPath(op),16384,vendorCanonical(op.request)));
      if(receipt.outcome==='not_found')throw new InboxHandoffContractError();return receipt;
    }};
  },signal),
  recover:(identity:WorkspaceIdentity,operation:InboxHandoffOperation,signal?:AbortSignal)=>exchange(identity,async()=>{
    const op=await validateInboxHandoffOperation(operation);
    return {actor:{box_id:op.scope.box_id,actor_id:op.scope.actor_id},run:async read=>verifyInboxHandoffOperationReceipt(op,await read(inboxHandoffResolvePath(op),16384,vendorCanonical(inboxHandoffResolveRequest(op))))};
  },signal),
};
