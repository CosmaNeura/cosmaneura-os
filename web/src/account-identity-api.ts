import {workspaceFetch} from './workspace-protocol';
import {WorkspaceApiError,type WorkspaceIdentity,type AuthenticatedWorkspaceIdentity} from './workspace-api';
import {assertCurrentDesktopSession,workspaceAuthHeaders} from './workspace-auth-headers';
import {permittedWorkspaceApi} from './workspace-origin';
import {parseVendorJson,vendorObject,vendorUuid} from './vendor-contract';

export type AccountIdentity={contract_version:1;box_id:string;actor_id:string;recovery_scope:string};
const maximum=1024,deadlineMs=15000,path='/provider-team/identity';
const invalid=():never=>{throw new WorkspaceApiError(502);};

function closed(value:unknown,keys:string):value is Record<string,unknown>{
  return vendorObject(value)&&Object.keys(value).sort().join(',')===keys&&
    Reflect.ownKeys(value).length===Object.keys(value).length&&
    Object.values(Object.getOwnPropertyDescriptors(value)).every(p=>'value'in p&&p.enumerable);
}

/** Fresh account context only; this does not establish a role or grant access to a ticket. */
export function validateAccountIdentity(value:unknown):AccountIdentity{
  try{
    if(!closed(value,'actor_id,box_id,contract_version,recovery_scope')||value.contract_version!==1||
      !vendorUuid(value.box_id)||!vendorUuid(value.actor_id)||typeof value.recovery_scope!=='string'||
      value.recovery_scope.length!==64||!/^[a-f0-9]{64}$/.test(value.recovery_scope))return invalid();
    return {contract_version:1,box_id:value.box_id,actor_id:value.actor_id,recovery_scope:value.recovery_scope};
  }catch{return invalid();}
}

const errorCodes:Readonly<Record<number,readonly string[]>>={
  401:['identity_authentication_required'],403:['identity_access_denied'],404:['identity_unavailable'],
  405:['invalid_identity_request'],422:['invalid_identity_request'],
  426:['team_contract_required','workspace_client_update_required'],
  503:['identity_unavailable'],504:['identity_timeout'],
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
  throw new WorkspaceApiError(401,'identity_authentication_required');
}

async function read(identity:WorkspaceIdentity,signal?:AbortSignal):Promise<AccountIdentity>{
  const deadline=performance.now()+deadlineMs,controller=new AbortController();
  let interruption:WorkspaceApiError|undefined,response:Response|undefined,reader:ReadableStreamDefaultReader<Uint8Array>|undefined;
  const interrupt=(error:WorkspaceApiError)=>{
    if(!controller.signal.aborted){interruption=error;controller.abort();}
  };
  const expire=()=>interrupt(new WorkspaceApiError(504,'identity_timeout'));
  const abort=()=>interrupt(new WorkspaceApiError(503,'identity_unavailable'));
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
      try{assertCurrentDesktopSession(account);}catch{throw new WorkspaceApiError(401,'identity_authentication_required');}
      checkDeadline();
    };
    check();
    const base=import.meta.env.VITE_API_BASE?.trim().replace(/\/+$/,'')||'http://127.0.0.1:8000';
    if(base.includes('?')||base.includes('#')||!permittedWorkspaceApi(base,import.meta.env.VITE_DESKTOP_SYNTHETIC_ENABLED==='true',window.location.href))throw new WorkspaceApiError(503,'identity_unavailable');
    const headers=await wait(workspaceAuthHeaders(account,base).catch(()=>{throw new WorkspaceApiError(401,'identity_authentication_required');}));
    check();headers.set('X-Cosmas-Team-Contract','2');headers.set('X-Cosmas-Draft-Recovery','2');headers.set('Accept','application/json');
    const url=base+path;
    response=await wait(workspaceFetch(identity,url,{method:'GET',headers,signal:controller.signal,credentials:'omit',redirect:'error',cache:'no-store',referrerPolicy:'no-referrer'}).then(result=>{
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
    const result=validateAccountIdentity(value);check();return result;
  }catch(error){
    checkDeadline();
    if(error instanceof WorkspaceApiError){
      // An explicit authority denial still clears private UI when its payload
      // cannot be trusted. Retain no code or data from that invalid response.
      if(error.status===502&&response&&[401,403,404].includes(response.status))throw new WorkspaceApiError(response.status);
      throw error;
    }
    throw new WorkspaceApiError(503,'identity_unavailable');
  }finally{
    clearTimeout(timer);signal?.removeEventListener('abort',abort);
    stop(reader);if(!reader)stop(response?.body);
    try{reader?.releaseLock();}catch{/* An ignored read can settle after cancellation. */}
    controller.abort();
  }
}

export const accountIdentityApi={read};
