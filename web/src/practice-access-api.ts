import {invitationToken,validateInvitationCommand,validateInvitationReceipt,validateInvitationResolution,validateInvitations,type CreateInvitation,type RevokeInvitation,type InvitationOperation} from './practice-invitation-contract';
import {workspaceFetch} from './workspace-protocol';
import {validateWorkspaceCompatibility} from './workspace-protocol';
import {validateMembersPage,validateMemberChange,validateMemberChangeResult,type MemberChange} from './practice-members-contract';
import {WorkspaceApiError,type WorkspaceIdentity,type AuthenticatedWorkspaceIdentity} from './workspace-api';
import {assertCurrentDesktopSession,workspaceAuthHeaders} from './workspace-auth-headers';
import {permittedWorkspaceApi} from './workspace-origin';
import {parseVendorJson,vendorUuid} from './vendor-contract';
import {accessName,accessObject,invalidAccess,validateAccessStatus,validateAccessList,validateAccessDecision,validateAccessReview,validatePracticeSetup,validateCompletePracticeSetup,type CompletePracticeSetup,type AccessReview,type AccessDecision} from './practice-access-contract';

const deadlineMs=15000;
const invalid=invalidAccess;
const closed=accessObject;

const errorCodes:Readonly<Record<number,readonly string[]>>={
  401:['practice_access_authentication_required'],403:['practice_access_denied'],404:['practice_access_not_found'],
  405:['invalid_practice_access_request'],409:['practice_access_conflict','practice_invitation_unavailable'],422:['invalid_practice_access_request'],
  426:['practice_access_contract_required','workspace_client_update_required','workspace_protocol_required'],429:['practice_access_limit'],
  503:['practice_access_unavailable'],504:['practice_access_timeout'],
};
function serverError(status:number,value:unknown):WorkspaceApiError{
  if(!closed(value,'detail')||typeof value.detail!=='string'||!errorCodes[status]?.includes(value.detail))return invalid();
  return new WorkspaceApiError(status,value.detail);
}
const stop=(stream:{cancel:()=>Promise<unknown>}|null|undefined)=>{try{void stream?.cancel().catch(()=>{});}catch{/* Cancellation is best effort and must not extend the deadline. */}};
function signed(value:WorkspaceIdentity):AuthenticatedWorkspaceIdentity{
  if(value&&typeof value==='object'&&'mode'in value&&
    (value.mode==='clerk_jwt'&&typeof value.getToken==='function'||
      value.mode==='desktop_native'&&typeof value.revision==='string'&&typeof value.isCurrent==='function'))return value;
  throw new WorkspaceApiError(401,'practice_access_authentication_required');
}

async function send<T>(identity:WorkspaceIdentity,path:string,validate:(value:unknown)=>T,body?:object,signal?:AbortSignal,compatibility=false):Promise<T>{
  const maximum=compatibility?4096:131072;
  const encoded=body===undefined?undefined:JSON.stringify(body);
  if(encoded!==undefined && new TextEncoder().encode(encoded).length>4096)throw new WorkspaceApiError(422);
  const deadline=performance.now()+deadlineMs,controller=new AbortController();
  let interruption:WorkspaceApiError|undefined,response:Response|undefined,reader:ReadableStreamDefaultReader<Uint8Array>|undefined;
  const interrupt=(error:WorkspaceApiError)=>{
    if(!controller.signal.aborted){interruption=error;controller.abort();}
  };
  const expire=()=>interrupt(new WorkspaceApiError(504,'practice_access_timeout'));
  const abort=()=>interrupt(new WorkspaceApiError(503,'practice_access_unavailable'));
  const interrupted=new Promise<never>((_,reject)=>controller.signal.addEventListener('abort',()=>{
    stop(reader);if(!reader)stop(response?.body);reject(interruption);
  },{once:true}));
  void interrupted.catch(()=>{});
  const wait=<T,>(promise:Promise<T>)=>Promise.race([promise,interrupted]);
  const checkDeadline=()=>{if(performance.now()>=deadline)expire();if(controller.signal.aborted)throw interruption;};
  const timer=setTimeout(expire,deadlineMs);
  signal?.addEventListener('abort',abort,{once:true});if(signal?.aborted)abort();
  try{
    checkDeadline();const account=signed(identity);
    const check=()=>{
      checkDeadline();
      try{assertCurrentDesktopSession(account);if(account.mode==='clerk_jwt' && account.nativeSession && !account.nativeSession.isCurrent())throw new Error();}catch{throw new WorkspaceApiError(401,'practice_access_authentication_required');}
      checkDeadline();
    };
    check();
    const base=import.meta.env.VITE_API_BASE?.trim().replace(/\/+$/,'')||'http://127.0.0.1:8000';
    if(base.includes('?')||base.includes('#')||!permittedWorkspaceApi(base,import.meta.env.VITE_DESKTOP_SYNTHETIC_ENABLED==='true',window.location.href))throw new WorkspaceApiError(503,'practice_access_unavailable');
    const headers=await wait(workspaceAuthHeaders(account,base).catch(()=>{throw new WorkspaceApiError(401,'practice_access_authentication_required');}));
    check();headers.set('X-Cosmas-Practice-Access-Contract','1');headers.set('X-Cosmas-Draft-Recovery','2');headers.set('Accept','application/json');
    const url=base+path;
    response=await wait(workspaceFetch(identity,url,{method:encoded===undefined?'GET':'POST',...(encoded===undefined?{}:{body:encoded}),headers,signal:controller.signal,credentials:'omit',redirect:'error',cache:'no-store',referrerPolicy:'no-referrer'},compatibility).then(result=>{
      // A transport which ignores AbortSignal must not retain a late private response.
      if(controller.signal.aborted){stop(result.body);throw interruption;}
      return result;
    }));
    check();if(!response)return invalid();
    const length=response.headers.get('content-length');
    if(response.redirected||response.type==='opaque'||response.type==='opaqueredirect'||response.url&&response.url!==url||
      response.status!==200&&!Object.hasOwn(errorCodes,response.status)||
      !response.headers.get('cache-control')?.split(',').some(v=>v.trim().toLowerCase()==='no-store')||
      response.headers.get('content-type')?.split(';',1)[0].trim().toLowerCase()!=='application/json'||
      response.headers.has('content-encoding')||
      length!==null&&(!/^(?:0|[1-9][0-9]*)$/.test(length)||Number(length)>maximum))return invalid();
    reader=response.body?.getReader();if(!reader)return invalid();
    const bytes=new Uint8Array(maximum);let size=0;
    for(;;){
      check();const part=await wait(reader.read());check();if(part.done)break;
      if(!ArrayBuffer.isView(part.value)||Object.prototype.toString.call(part.value)!=='[object Uint8Array]'||part.value.byteLength>maximum-size)return invalid();
      bytes.set(part.value,size);size+=part.value.byteLength;
    }
    if(length!==null&&Number(length)!==size)return invalid();
    let value:unknown;
    try{value=parseVendorJson(new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(bytes.subarray(0,size)));}catch{return invalid();}
    check();
    if(response.status!==200)throw serverError(response.status,value);
    const result=validate(value);check();return result;
  }catch(error){
    checkDeadline();
    if(error instanceof WorkspaceApiError){
      // An explicit authority denial still clears private UI when its payload
      // cannot be trusted. Retain no code or data from that invalid response.
      if(error.status===502&&response&&[401,403,404].includes(response.status))throw new WorkspaceApiError(response.status);
      throw error;
    }
    throw new WorkspaceApiError(503,'practice_access_unavailable');
  }finally{
    clearTimeout(timer);signal?.removeEventListener('abort',abort);
    stop(reader);if(!reader)stop(response?.body);
    try{reader?.releaseLock();}catch{/* An ignored read can settle after cancellation. */}
    controller.abort();
  }
}

export const practiceAccessApi={
  resolveInvitation:(identity:WorkspaceIdentity,operation:InvitationOperation,signal?:AbortSignal)=>{
    const exact=validateInvitationCommand(operation.body,operation.type==='create');
    return send(identity,`/practice-access/invitation/${operation.type}/resolve`,value=>validateInvitationResolution(value,operation),exact,signal);
  },
  invitations:(identity:WorkspaceIdentity,signal?:AbortSignal)=>send(identity,'/practice-access/invitations',validateInvitations,undefined,signal),
  createInvitation:(identity:WorkspaceIdentity,command:CreateInvitation,signal?:AbortSignal)=>{
    const exact=validateInvitationCommand(command,true);
    return send(identity,'/practice-access/invitation/create',value=>validateInvitationReceipt(value,{type:'create',body:exact}),exact,signal);
  },
  revokeInvitation:(identity:WorkspaceIdentity,command:RevokeInvitation,signal?:AbortSignal)=>{
    const exact=validateInvitationCommand(command,false);
    return send(identity,'/practice-access/invitation/revoke',value=>validateInvitationReceipt(value,{type:'revoke',body:exact}),exact,signal);
  },
  joinInvitation:(identity:WorkspaceIdentity,command:{idempotency_key:string;display_name:string;token:string},signal?:AbortSignal)=>{
    if(!closed(command,'display_name,idempotency_key,token')||!vendorUuid(command.idempotency_key)||!accessName(command.display_name)||!invitationToken(command.token))throw new WorkspaceApiError(422,'invalid_practice_access_request');
    return send(identity,'/practice-access/invitation/join',validateAccessStatus,{...command},signal);
  },
  setup:(identity:WorkspaceIdentity,signal?:AbortSignal)=>send(identity,'/practice-access/setup',validatePracticeSetup,undefined,signal),
  confirmSetup:(identity:WorkspaceIdentity,command:CompletePracticeSetup,signal?:AbortSignal)=>send(identity,'/practice-access/setup/complete',validatePracticeSetup,validateCompletePracticeSetup(command),signal),
  compatibility:(identity:WorkspaceIdentity,signal?:AbortSignal)=>send(identity,'/practice-access/compatibility',validateWorkspaceCompatibility,undefined,signal,true),
  members:(identity:WorkspaceIdentity,after:string|null,signal?:AbortSignal)=>{
    if(after!==null&&!vendorUuid(after))throw new WorkspaceApiError(422,'invalid_practice_access_request');
    return send(identity,'/practice-access/members',value=>validateMembersPage(value,after),{after_id:after},signal);
  },
  memberChange:(identity:WorkspaceIdentity,command:MemberChange,signal?:AbortSignal)=>{
    const exact=validateMemberChange(command);
    return send(identity,'/practice-access/member-change',value=>validateMemberChangeResult(value,exact),exact,signal);
  },
  read:(identity:WorkspaceIdentity,signal?:AbortSignal)=>send(identity,'/practice-access',validateAccessStatus,undefined,signal),
  request:(identity:WorkspaceIdentity,command:{idempotency_key:string;display_name:string},signal?:AbortSignal)=>{
    if(!closed(command,'display_name,idempotency_key') || !vendorUuid(command.idempotency_key) || !accessName(command.display_name))throw new WorkspaceApiError(422,'invalid_practice_access_request');
    return send(identity,'/practice-access/request',validateAccessStatus,{...command},signal);
  },
  cancel:(identity:WorkspaceIdentity,command:AccessReview,signal?:AbortSignal)=>send(identity,'/practice-access/cancel',validateAccessStatus,validateAccessReview(command),signal),
  pending:(identity:WorkspaceIdentity,signal?:AbortSignal)=>send(identity,'/practice-access/requests',validateAccessList,undefined,signal),
  decide:(identity:WorkspaceIdentity,command:AccessDecision,signal?:AbortSignal)=>{
    const exact=validateAccessReview(command,true) as AccessDecision;
    return send(identity,'/practice-access/decide',value=>validateAccessDecision(value,exact),exact,signal);
  },
};
