import {workspaceFetch} from './workspace-protocol';
import {WorkspaceApiError,type WorkspaceIdentity} from './workspace-api';
import {assertCurrentDesktopSession,workspaceAuthHeaders} from './workspace-auth-headers';
import {permittedWorkspaceApi} from './workspace-origin';
import {parseVendorJson,vendorBytes,vendorCanonical,vendorObject,vendorUuid,VendorContractError} from './vendor-contract';
import {MembershipContractError,validateMembership,verifyMembershipView,sameMembershipScope} from './membership-contract';
import {validateMembershipOperation,verifyMembershipOperationReceipt,verifyMembershipBundle,membershipRoot,membershipOperationPath,membershipResolveRequest,type MembershipOperation} from './membership-operation';
import type {Scope} from './membership-schema';
import type {MembershipReviewBundle} from './membership-operation';
import {savedMembershipBinding,verifyMembershipSavedFinance} from './membership-saved-evidence';
const codes=new Set(['membership_work_unavailable','membership_unavailable','invalid_membership_request','membership_contract_required','membership_feature_disabled','membership_source_changed','membership_evidence_changed','membership_revision_changed','membership_result_changed','membership_exception_unresolved','membership_idempotency_conflict','membership_history_limit','membership_retirement_unavailable']);
function errorCode(v:unknown){if(!vendorObject(v)||Object.keys(v).sort().join(',')!=='contract_version,error'||v.contract_version!==1||!vendorObject(v.error)||Object.keys(v.error).join(',')!=='code'||typeof v.error.code!=='string'||!codes.has(v.error.code))return undefined;return v.error.code;}
type Read=(path:string,maximum:number,body?:string)=>Promise<unknown>;
/** One 15s budget includes credentials, both detail/history reads, exact hashing and final session fence. */
async function transport<T>(identity:WorkspaceIdentity,scope:Scope|{workspace_id:string},work:(read:Read)=>Promise<T>,signal?:AbortSignal):Promise<T>{
 const controller=new AbortController(),readers=new Set<ReadableStreamDefaultReader<Uint8Array>>(),deadline=performance.now()+15000;
 const stop=(stream:{cancel():Promise<unknown>}|null|undefined)=>{try{void stream?.cancel().catch(()=>{});}catch{}};
 const abort=()=>controller.abort(),check=()=>{if(performance.now()>=deadline)abort();controller.signal.throwIfAborted();if('mode'in identity)assertCurrentDesktopSession(identity);};
 const interrupted=new Promise<never>((_,reject)=>controller.signal.addEventListener('abort',()=>{readers.forEach(stop);reject(new WorkspaceApiError(503));},{once:true}));void interrupted.catch(()=>{});
 const wait=<V,>(v:Promise<V>)=>Promise.race([v,interrupted]);const timer=setTimeout(abort,15000);signal?.addEventListener('abort',abort,{once:true});if(signal?.aborted)abort();
 try{
  check();if('owner_id'in scope){validateMembership('Scope',scope);if(!('mode'in identity)&&(identity.boxId!==scope.box_id||identity.actorId!==scope.owner_id))throw new WorkspaceApiError(403);}else if(!vendorUuid(scope.workspace_id))throw new MembershipContractError();
  const base=import.meta.env.VITE_API_BASE?.trim().replace(/\/+$/,'')||'http://127.0.0.1:8000';if(!permittedWorkspaceApi(base,import.meta.env.VITE_DESKTOP_SYNTHETIC_ENABLED==='true',window.location.href))throw new WorkspaceApiError(503);
  const headers='mode'in identity?await wait(workspaceAuthHeaders(identity,base).catch(()=>{throw new WorkspaceApiError(401);})):new Headers({'X-Box-Id':identity.boxId,'X-Actor-Principal-Id':identity.actorId});
  check();headers.set('X-Cosmas-Membership-Contract','1');headers.set('Accept','application/json');headers.set('Content-Type','application/json');
  const read:Read=async(path,maximum,body)=>{
   check();const response=await wait(workspaceFetch(identity,base+path,{method:body===undefined?'GET':'POST',headers,body,signal:controller.signal,credentials:'omit',redirect:'error',cache:'no-store',referrerPolicy:'no-referrer'}));check();
   if([401,403,404,426].includes(response.status)){stop(response.body);throw new WorkspaceApiError(response.status);}
   const cap=response.status===200?maximum:2048,length=response.headers.get('content-length');
   if(!response.headers.get('cache-control')?.split(',').some(v=>v.trim().toLowerCase()==='no-store')||response.headers.get('content-type')?.split(';',1)[0].trim().toLowerCase()!=='application/json'||length!==null&&(!/^(?:0|[1-9][0-9]*)$/.test(length)||Number(length)>cap)){stop(response.body);throw new WorkspaceApiError(503);}
   const reader=response.body?.getReader();if(!reader)throw new WorkspaceApiError(503);readers.add(reader);const buffer=new Uint8Array(cap);let size=0;
   try{for(;;){check();const part=await wait(reader.read());check();if(part.done)break;if(part.value.byteLength>cap-size)throw new WorkspaceApiError(503);buffer.set(part.value,size);size+=part.value.byteLength;}
    const value=parseVendorJson(new TextDecoder('utf-8',{fatal:true}).decode(buffer.subarray(0,size)));check();if(response.status!==200)throw new WorkspaceApiError(response.ok?503:response.status,errorCode(value));return value;
   }finally{readers.delete(reader);stop(reader);try{reader.releaseLock();}catch{}}
  };
  const result=await wait(work(read));check();return result;
 }catch(e){if(e instanceof WorkspaceApiError)throw e;throw new WorkspaceApiError(e instanceof MembershipContractError||e instanceof VendorContractError?502:503);}
 finally{clearTimeout(timer);signal?.removeEventListener('abort',abort);readers.forEach(stop);controller.abort();}
}
const id=(v:string)=>{if(!vendorUuid(v))throw new MembershipContractError();return v;};
export const membershipApi={
 // The authenticated workspace intentionally omits owner IDs. Derive them only
 // from the current authorized options response; never from local draft data.
 bootstrap:(identity:WorkspaceIdentity,workspaceId:string,signal?:AbortSignal)=>transport(identity,{workspace_id:workspaceId},async read=>{const v=await verifyMembershipView('Options',await read(membershipRoot(workspaceId)+'/options',8192));if(v.scope.workspace_id!==workspaceId||!('mode'in identity)&&(v.scope.box_id!==identity.boxId||v.scope.owner_id!==identity.actorId))throw new WorkspaceApiError(403);return v;},signal),
 options:(identity:WorkspaceIdentity,scope:Scope,signal?:AbortSignal)=>transport(identity,scope,async read=>{const v=await verifyMembershipView('Options',await read(membershipRoot(scope.workspace_id)+'/options',8192));if(!sameMembershipScope(v.scope,scope))throw new MembershipContractError();return v;},signal),
 catalog:(identity:WorkspaceIdentity,scope:Scope,signal?:AbortSignal)=>transport(identity,scope,async read=>{const v=await verifyMembershipView('Catalog',await read(membershipRoot(scope.workspace_id),131072));if(!sameMembershipScope(v.scope,scope))throw new MembershipContractError();return v;},signal),
 detail:(identity:WorkspaceIdentity,scope:Scope,ticketId:string,signal?:AbortSignal)=>transport(identity,scope,async read=>{const path=membershipRoot(scope.workspace_id)+'/'+id(ticketId);const [d,h]=await Promise.all([read(path,32768),read(path+'/history',1048576)]);const v=await verifyMembershipBundle(d,h,scope);if(v.detail.summary.ticket_id!==ticketId)throw new MembershipContractError();return v;},signal),
 savedFinance:(identity:WorkspaceIdentity,scope:Scope,bundle:MembershipReviewBundle,signal?:AbortSignal)=>transport(identity,scope,async read=>{const binding=savedMembershipBinding(bundle),path=membershipRoot(scope.workspace_id)+'/'+id(binding.ticket_id)+'/results/'+id(binding.result_receipt_id)+'/finance-evidence';return verifyMembershipSavedFinance(await read(path,65536),scope,bundle);},signal),
 execute:(identity:WorkspaceIdentity,operation:MembershipOperation,signal?:AbortSignal)=>transport(identity,operation.scope,async read=>{const op=await validateMembershipOperation(operation);return verifyMembershipOperationReceipt(op,await read(membershipOperationPath(op),8192,vendorCanonical(op.request)));},signal),
 recover:(identity:WorkspaceIdentity,operation:MembershipOperation,signal?:AbortSignal)=>transport(identity,operation.scope,async read=>{const op=await validateMembershipOperation(operation);return verifyMembershipOperationReceipt(op,await read(membershipRoot(op.scope.workspace_id)+'/resolve',8192,vendorCanonical(membershipResolveRequest(op))));},signal),
 retire:(identity:WorkspaceIdentity,operation:MembershipOperation,signal?:AbortSignal)=>transport(identity,operation.scope,async read=>{const op=await validateMembershipOperation(operation),body={command_kind:op.kind,request:op.request,request_sha256:op.request_sha256};if(vendorBytes(body)>16384)throw new MembershipContractError();const value=await verifyMembershipOperationReceipt(op,await read(membershipRoot(op.scope.workspace_id)+'/retire',8192,vendorCanonical(body)));if(value.outcome==='not_found')throw new MembershipContractError();return value;},signal),
};
