import {workspaceFetch} from './workspace-protocol';
import {WorkspaceApiError, type AuthenticatedWorkspaceIdentity} from './workspace-api';
import {workspaceAuthHeaders, assertCurrentDesktopSession} from './workspace-auth-headers';
import {permittedWorkspaceApi} from './workspace-origin';
import {parseVendorJson, vendorUuid} from './vendor-contract';
import {configuredCoreWebOrigin, validCoreWebOrigin, validateRecordLocation,
  RECORD_LOCATION_BYTES, RECORD_LOCATION_DEADLINE_MS, type CoreRecordLocation} from './core-record-location';

const stop=(value:{cancel:()=>Promise<unknown>}|null|undefined)=>{try{void value?.cancel().catch(()=>{});}catch{/* Best effort. */}};

async function location(identity:AuthenticatedWorkspaceIdentity,workspace:string,signal?:AbortSignal):Promise<CoreRecordLocation>{
  const origin=configuredCoreWebOrigin();
  if(!vendorUuid(workspace)||!validCoreWebOrigin(origin))throw new WorkspaceApiError(503);
  const controller=new AbortController(),deadline=performance.now()+RECORD_LOCATION_DEADLINE_MS;
  let response:Response|undefined,reader:ReadableStreamDefaultReader<Uint8Array>|undefined;
  const abort=()=>controller.abort();
  const interrupted=new Promise<never>((_,reject)=>controller.signal.addEventListener('abort',()=>{
    stop(reader);if(!reader)stop(response?.body);reject(new WorkspaceApiError(503));
  },{once:true}));
  void interrupted.catch(()=>{});
  const wait=<T,>(value:Promise<T>)=>Promise.race([value,interrupted]);
  const check=()=>{
    if(performance.now()>=deadline)abort();controller.signal.throwIfAborted();
    assertCurrentDesktopSession(identity);
    if(identity.mode==='clerk_jwt'&&identity.nativeSession&&!identity.nativeSession.isCurrent())throw new WorkspaceApiError(401);
  };
  const timer=setTimeout(abort,RECORD_LOCATION_DEADLINE_MS);
  signal?.addEventListener('abort',abort,{once:true});if(signal?.aborted)abort();
  try {
    check();
    const base=import.meta.env.VITE_API_BASE?.trim().replace(/\/+$/,'')||'http://127.0.0.1:8000';
    if(base.includes('?')||base.includes('#')||!permittedWorkspaceApi(base,import.meta.env.VITE_DESKTOP_SYNTHETIC_ENABLED==='true',window.location.href))throw new WorkspaceApiError(503);
    const headers=await wait(workspaceAuthHeaders(identity,base).catch(()=>{throw new WorkspaceApiError(401);}));
    check();headers.set('X-Cosmas-Record-Contract','1');headers.set('Accept','application/json');
    const url=base+'/workspaces/'+workspace+'/cosmaneura-record/location';
    response=await wait(workspaceFetch(identity,url,{method:'GET',headers,signal:controller.signal,credentials:'omit',redirect:'error',cache:'no-store',referrerPolicy:'no-referrer'}).then(value=>{
      if(controller.signal.aborted){stop(value.body);throw new WorkspaceApiError(503);}return value;
    }));
    check();if(!response)throw new WorkspaceApiError(502);const length=response.headers.get('content-length');
    if(response.redirected||response.type==='opaque'||response.type==='opaqueredirect'||response.url&&response.url!==url||
      !response.headers.get('cache-control')?.split(',').some(v=>v.trim().toLowerCase()==='no-store')||
      response.headers.get('content-type')?.split(';',1)[0].trim().toLowerCase()!=='application/json'||response.headers.has('content-encoding')||
      length!==null&&(!/^(?:0|[1-9][0-9]*)$/.test(length)||Number(length)>RECORD_LOCATION_BYTES))throw new WorkspaceApiError(502);
    reader=response.body?.getReader();if(!reader)throw new WorkspaceApiError(502);
    const bytes=new Uint8Array(RECORD_LOCATION_BYTES);let size=0;
    for(;;){
      check();const part=await wait(reader.read());check();if(part.done)break;
      if(Object.prototype.toString.call(part.value)!=='[object Uint8Array]'||part.value.byteLength>bytes.length-size)throw new WorkspaceApiError(502);
      bytes.set(part.value,size);size+=part.value.byteLength;
    }
    if(length!==null&&Number(length)!==size)throw new WorkspaceApiError(502);
    let value:unknown;
    try{value=parseVendorJson(new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(bytes.subarray(0,size)));}catch{throw new WorkspaceApiError(502);}
    check();
    if(response.status!==200)throw new WorkspaceApiError([401,403,404,409,422,426,503,504].includes(response.status)?response.status:502);
    return validateRecordLocation(value,workspace,origin);
  }catch(error){
    if(response&&[401,403,404].includes(response.status))throw new WorkspaceApiError(response.status);
    if(error instanceof WorkspaceApiError)throw error;
    throw new WorkspaceApiError(503);
  }finally{
    clearTimeout(timer);signal?.removeEventListener('abort',abort);stop(reader);if(!reader)stop(response?.body);
    try{reader?.releaseLock();}catch{/* An abandoned read may settle later. */}controller.abort();
  }
}
export const coreRecordApi={location};
