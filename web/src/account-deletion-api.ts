import {workspaceFetch} from './workspace-protocol';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity,type WorkspaceIdentity} from './workspace-api';
import {assertCurrentDesktopSession,workspaceAuthHeaders} from './workspace-auth-headers';
import {permittedWorkspaceApi} from './workspace-origin';
import {parseVendorJson,vendorObject} from './vendor-contract';

export const ACCOUNT_DELETE_CONFIRM='delete_my_account';
const path='/account/delete';
const maximum=512;
const deadlineMs=15000;
const errorCodes:Readonly<Record<number,readonly string[]>>={
  400:['account deletion requires explicit confirmation','transfer ownership before deleting this owner account','account deletion is temporarily unavailable'],
  401:['identity_authentication_required','authentication required'],
  403:['account deletion is unavailable','identity_access_denied','access denied'],
  503:['account deletion is temporarily unavailable','provisioning_identity_unavailable'],
};

function closed(value:unknown,keys:string):value is Record<string,unknown>{
  return vendorObject(value)&&Object.keys(value).sort().join(',')===keys&&
    Reflect.ownKeys(value).length===Object.keys(value).length&&
    Object.values(Object.getOwnPropertyDescriptors(value)).every(p=>'value'in p&&p.enumerable);
}

function signed(value:WorkspaceIdentity):AuthenticatedWorkspaceIdentity{
  if(value&&typeof value==='object'&&'mode'in value&&
    (value.mode==='clerk_jwt'&&typeof value.getToken==='function'||
      value.mode==='desktop_native'&&typeof value.revision==='string'&&typeof value.isCurrent==='function'))return value;
  throw new WorkspaceApiError(401);
}

function serverError(status:number,value:unknown):WorkspaceApiError{
  if(!closed(value,'detail')||typeof value.detail!=='string')return new WorkspaceApiError(502);
  if(errorCodes[status]?.includes(value.detail))return new WorkspaceApiError(status,value.detail);
  return new WorkspaceApiError(502);
}

const stop=(stream:{cancel:()=>Promise<unknown>}|null|undefined)=>{try{void stream?.cancel().catch(()=>{});}catch{/* best effort */}};

async function deleteAccount(identity:WorkspaceIdentity,confirm:string,signal?:AbortSignal):Promise<{status:'deleted'}>{
  if(confirm!==ACCOUNT_DELETE_CONFIRM)throw new WorkspaceApiError(400,'account deletion requires explicit confirmation');
  const deadline=performance.now()+deadlineMs,controller=new AbortController();
  let interruption:WorkspaceApiError|undefined,response:Response|undefined,reader:ReadableStreamDefaultReader<Uint8Array>|undefined;
  const interrupt=(error:WorkspaceApiError)=>{if(!controller.signal.aborted){interruption=error;controller.abort();}};
  const expire=()=>interrupt(new WorkspaceApiError(504));
  const abort=()=>interrupt(new WorkspaceApiError(503));
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
      try{assertCurrentDesktopSession(account);}catch{throw new WorkspaceApiError(401);}
      checkDeadline();
    };
    check();
    const base=import.meta.env.VITE_API_BASE?.trim().replace(/\/+$/,'')||'http://127.0.0.1:8000';
    if(base.includes('?')||base.includes('#')||!permittedWorkspaceApi(base,import.meta.env.VITE_DESKTOP_SYNTHETIC_ENABLED==='true',window.location.href))throw new WorkspaceApiError(503);
    const headers=await wait(workspaceAuthHeaders(account,base).catch(()=>{throw new WorkspaceApiError(401);}));
    check();headers.set('Accept','application/json');
    const url=base+path;
    response=await wait(workspaceFetch(identity,url,{
      method:'POST',headers,signal:controller.signal,credentials:'omit',redirect:'error',cache:'no-store',
      referrerPolicy:'no-referrer',body:JSON.stringify({confirm}),
    }).then(result=>{if(controller.signal.aborted){stop(result.body);throw interruption;}return result;}));
    check();if(!response)throw new WorkspaceApiError(502);
    const length=response.headers.get('content-length');
    if(response.redirected||response.type==='opaque'||response.type==='opaqueredirect'||response.url&&response.url!==url||
      response.status!==200&&!Object.hasOwn(errorCodes,response.status)||
      !response.headers.get('cache-control')?.split(',').some(v=>v.trim().toLowerCase()==='no-store')||
      response.headers.get('content-type')?.split(';',1)[0].trim().toLowerCase()!=='application/json'||
      response.headers.has('content-encoding')||
      length!==null&&(!/^(?:0|[1-9][0-9]*)$/.test(length)||Number(length)>maximum))throw new WorkspaceApiError(502);
    reader=response.body?.getReader();if(!reader)throw new WorkspaceApiError(502);
    const bytes=new Uint8Array(maximum);let size=0;
    for(;;){
      check();const part=await wait(reader.read());check();if(part.done)break;
      if(!ArrayBuffer.isView(part.value)||Object.prototype.toString.call(part.value)!=='[object Uint8Array]'||part.value.byteLength>maximum-size)throw new WorkspaceApiError(502);
      bytes.set(part.value,size);size+=part.value.byteLength;
    }
    if(length!==null&&Number(length)!==size)throw new WorkspaceApiError(502);
    let value:unknown;
    try{value=parseVendorJson(new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(bytes.subarray(0,size)));}catch{throw new WorkspaceApiError(502);}
    check();
    if(response.status!==200)throw serverError(response.status,value);
    if(!closed(value,'status')||value.status!=='deleted')throw new WorkspaceApiError(502);
    return {status:'deleted'};
  }catch(error){
    checkDeadline();
    if(error instanceof WorkspaceApiError)throw error;
    throw new WorkspaceApiError(503);
  }finally{
    clearTimeout(timer);signal?.removeEventListener('abort',abort);
    stop(reader);if(!reader)stop(response?.body);
    try{reader?.releaseLock();}catch{/* ignored */}
    controller.abort();
  }
}

export const accountDeletionApi={deleteAccount};
