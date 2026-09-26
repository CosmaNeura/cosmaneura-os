import {workspaceFetch} from './workspace-protocol';
import {WorkspaceApiError,type WorkspaceIdentity,type AuthenticatedWorkspaceIdentity} from './workspace-api';
import {assertCurrentDesktopSession,workspaceAuthHeaders} from './workspace-auth-headers';
import {permittedWorkspaceApi} from './workspace-origin';
import {parseVendorJson,vendorObject} from './vendor-contract';

import {isAthenaVisitLinkCommand,validateAthenaVisitLinkCommand,validateAthenaVisitLinkResult,type AthenaVisitLinkCommand,type AthenaVisitLinkResult} from './athena-visit-link-api';
import {validateCoreCommand,validateCoreConnection,type CoreConnectionCommand,type CoreConnectionResult} from './core-connection-contract';
import {isAppointmentSetupCommand,validateAppointmentSetupCommand,validateAppointmentSetupResult,type AppointmentSetupCommand,type AppointmentSetupResult} from './core-appointment-setup-contract';
import {isAthenaCommand,validateAthenaCommand,validateAthenaResult,type AthenaCommand,type AthenaResult} from './athena-connection-contract';
const maximum=69632,deadlineMs=35000,path='/connections/cosmaneura/read';
const invalid=():never=>{throw new WorkspaceApiError(502);};
const closed=(v:unknown,keys:string):v is Record<string,unknown>=>vendorObject(v)&&Object.keys(v).sort().join(',')===keys;
const errorCodes:Readonly<Record<number,readonly string[]>>={
  401:['core_connection_unavailable','core_connection_access_denied'],403:['core_connection_unavailable','core_connection_access_denied'],404:['core_connection_unavailable'],405:['core_connection_unavailable'],
  409:['core_connection_required','core_connection_review_required','core_connection_changed'],422:['invalid_core_connection_request'],
  426:['core_connection_contract_required','workspace_client_update_required','core_connection_unavailable'],503:['core_connection_unavailable'],504:['core_connection_unavailable'],
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
  throw new WorkspaceApiError(401,'core_connection_access_denied');
}

function read(identity:WorkspaceIdentity,command:CoreConnectionCommand,signal?:AbortSignal):Promise<CoreConnectionResult>;
function read(identity:WorkspaceIdentity,command:AthenaCommand,signal?:AbortSignal):Promise<AthenaResult>;
function read(identity:WorkspaceIdentity,command:AppointmentSetupCommand,signal?:AbortSignal):Promise<AppointmentSetupResult>;
function read(identity:WorkspaceIdentity,command:AthenaVisitLinkCommand,signal?:AbortSignal):Promise<AthenaVisitLinkResult>;
async function read(identity:WorkspaceIdentity,command:CoreConnectionCommand|AthenaCommand|AppointmentSetupCommand|AthenaVisitLinkCommand,signal?:AbortSignal):Promise<CoreConnectionResult|AthenaResult|AppointmentSetupResult|AthenaVisitLinkResult>{
  const deadline=performance.now()+deadlineMs,controller=new AbortController();
  let interruption:WorkspaceApiError|undefined,response:Response|undefined,reader:ReadableStreamDefaultReader<Uint8Array>|undefined;
  const interrupt=(error:WorkspaceApiError)=>{
    if(!controller.signal.aborted){interruption=error;controller.abort();}
  };
  const expire=()=>interrupt(new WorkspaceApiError(504,'core_connection_unavailable'));
  const abort=()=>interrupt(new WorkspaceApiError(503,'core_connection_unavailable'));
  const interrupted=new Promise<never>((_,reject)=>controller.signal.addEventListener('abort',()=>{
    stop(reader);if(!reader)stop(response?.body);reject(interruption);
  },{once:true}));
  void interrupted.catch(()=>{});
  const wait=<T,>(promise:Promise<T>)=>Promise.race([promise,interrupted]);
  const checkDeadline=()=>{if(performance.now()>=deadline)expire();if(controller.signal.aborted)throw interruption;};
  const timer=setTimeout(expire,deadlineMs);
  signal?.addEventListener('abort',abort,{once:true});if(signal?.aborted)abort();
  try{
    checkDeadline();if(isAthenaVisitLinkCommand(command))validateAthenaVisitLinkCommand(command);else if(isAppointmentSetupCommand(command))await wait(validateAppointmentSetupCommand(command));else if(isAthenaCommand(command))validateAthenaCommand(command);else validateCoreCommand(command);const account=signed(identity);
    const check=()=>{
      checkDeadline();
      try{assertCurrentDesktopSession(account);if(account.mode!=='desktop_native'&&account.nativeSession&&!account.nativeSession.isCurrent())throw new Error('Session changed');}catch{throw new WorkspaceApiError(401,'core_connection_access_denied');}
      checkDeadline();
    };
    check();
    const base=import.meta.env.VITE_API_BASE?.trim().replace(/\/+$/,'')||'http://127.0.0.1:8000';
    if(base.includes('?')||base.includes('#')||!permittedWorkspaceApi(base,import.meta.env.VITE_DESKTOP_SYNTHETIC_ENABLED==='true',window.location.href))throw new WorkspaceApiError(503,'core_connection_unavailable');
    const headers=await wait(workspaceAuthHeaders(account,base).catch(()=>{throw new WorkspaceApiError(401,'core_connection_access_denied');}));
    check();headers.set('X-Cosmas-Connection-Contract','1');headers.set('Content-Type','application/json');headers.set('X-Cosmas-Draft-Recovery','2');headers.set('Accept','application/json');
    const url=base+path;
    response=await wait(workspaceFetch(identity,url,{method:'POST',body:JSON.stringify(command),headers,signal:controller.signal,credentials:'omit',redirect:'error',cache:'no-store',referrerPolicy:'no-referrer'}).then(result=>{
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
    const result=await wait<CoreConnectionResult|AthenaResult|AppointmentSetupResult|AthenaVisitLinkResult>(isAthenaVisitLinkCommand(command)?validateAthenaVisitLinkResult(value,command):isAppointmentSetupCommand(command)?validateAppointmentSetupResult(value,command):isAthenaCommand(command)?validateAthenaResult(value,command):validateCoreConnection(value,command));check();return result;
  }catch(error){
    checkDeadline();
    if(error instanceof WorkspaceApiError){
      // An explicit authority denial still clears private UI when its payload
      // cannot be trusted. Retain no code or data from that invalid response.
      if(error.status===502&&response&&[401,403,404].includes(response.status))throw new WorkspaceApiError(response.status);
      throw error;
    }
    throw new WorkspaceApiError(503,'core_connection_unavailable');
  }finally{
    clearTimeout(timer);signal?.removeEventListener('abort',abort);
    stop(reader);if(!reader)stop(response?.body);
    try{reader?.releaseLock();}catch{/* An ignored read can settle after cancellation. */}
    controller.abort();
  }
}

export const coreConnectionApi={read};
