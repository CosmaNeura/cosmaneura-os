import {workspaceFetch} from './workspace-protocol';
import {workspaceAuthHeaders,assertCurrentDesktopSession} from './workspace-auth-headers';
import {permittedWorkspaceApi} from './workspace-origin';
import {parseVendorJson,vendorUuid} from './vendor-contract';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from './workspace-api';
import {validateVisitPrep,type VisitPrepCommand,type VisitPrepReceipt} from './visit-prep-contract';

export const VISIT_PREP_BUILD=import.meta.env.VITE_WORKSPACE_VISIT_PREP_ENABLED==='true';
const maximum=262144;
const stop=(body:{cancel:()=>Promise<unknown>}|undefined|null)=>{try{void body?.cancel().catch(()=>{});}catch{/* Do not await abandoned transport. */}};
export async function readVisitPrep(identity:AuthenticatedWorkspaceIdentity,command:VisitPrepCommand,signal?:AbortSignal):Promise<VisitPrepReceipt>{
  if(!/^visit_prep_[0-7][0-9a-hjkmnp-tv-z]{25}$/.test(command.preparation_ref)||
    !/^[a-f0-9]{64}$/.test(command.connection_sha256)||!vendorUuid(command.workspace_id)||!vendorUuid(command.request_nonce)||
    command.bot.address!=='visit_prep'||!Number.isSafeInteger(command.bot.team_revision)||command.bot.team_revision<1)
    throw new WorkspaceApiError(422);
  const controller=new AbortController(),deadline=performance.now()+35000;
  let response:Response|undefined,reader:ReadableStreamDefaultReader<Uint8Array>|undefined;
  const abort=()=>controller.abort();
  const interrupted=new Promise<never>((_,reject)=>controller.signal.addEventListener('abort',()=>{
    stop(reader);if(!reader)stop(response?.body);reject(new WorkspaceApiError(503));
  },{once:true}));void interrupted.catch(()=>{});
  const wait=<T,>(promise:Promise<T>)=>Promise.race([promise,interrupted]);
  const check=()=>{if(performance.now()>=deadline)abort();controller.signal.throwIfAborted();assertCurrentDesktopSession(identity);
    if(identity.mode==='clerk_jwt'&&identity.nativeSession&&!identity.nativeSession.isCurrent())throw new WorkspaceApiError(401);};
  const timer=setTimeout(abort,35000);signal?.addEventListener('abort',abort,{once:true});if(signal?.aborted)abort();
  try{
    check();const base=import.meta.env.VITE_API_BASE?.trim().replace(/\/+$/,'')||'http://127.0.0.1:8000';
    if(base.includes('?')||base.includes('#')||!permittedWorkspaceApi(base,import.meta.env.VITE_DESKTOP_SYNTHETIC_ENABLED==='true',window.location.href))throw new WorkspaceApiError(503);
    const headers=await wait(workspaceAuthHeaders(identity,base));check();
    headers.set('X-Cosmas-Visit-Prep-Contract','1');headers.set('Accept','application/json');
    const url=base+'/provider-team/visit-prep/read';
    response=await wait(workspaceFetch(identity,url,{method:'POST',headers,body:JSON.stringify(command),
      signal:controller.signal,credentials:'omit',redirect:'error',cache:'no-store',referrerPolicy:'no-referrer'}).then(result=>{
        if(controller.signal.aborted){stop(result.body);throw new WorkspaceApiError(503);}return result;}));
    check();if(!response)throw new WorkspaceApiError(503);const length=response.headers.get('content-length');
    if(response.redirected||response.url&&response.url!==url||response.type==='opaque'||response.type==='opaqueredirect'||
      response.headers.get('content-type')?.split(';')[0]!=='application/json'||response.headers.has('content-encoding')||
      response.headers.get('referrer-policy')!=='no-referrer'||!response.headers.get('cache-control')?.split(',').some(v=>v.trim()==='no-store')||
      length!==null&&(!/^(?:0|[1-9][0-9]*)$/.test(length)||Number(length)>maximum))throw new WorkspaceApiError(502);
    reader=response.body?.getReader();if(!reader)throw new WorkspaceApiError(502);
    const bytes=new Uint8Array(maximum);let size=0;
    for(;;){const part=await wait(reader.read());check();if(part.done)break;
      if(Object.prototype.toString.call(part.value)!=='[object Uint8Array]'||part.value.byteLength>maximum-size)throw new WorkspaceApiError(502);
      bytes.set(part.value,size);size+=part.value.byteLength;}
    if(length!==null&&Number(length)!==size)throw new WorkspaceApiError(502);
    if(response.status!==200)throw new WorkspaceApiError([401,403,404,409,413,422,426,503,504].includes(response.status)?response.status:503);
    const value=parseVendorJson(new TextDecoder('utf-8',{fatal:true}).decode(bytes.subarray(0,size)));
    check();return validateVisitPrep(value,command);
  }catch(error){if(response&&[401,403,404].includes(response.status))throw new WorkspaceApiError(response.status);
    if(error instanceof WorkspaceApiError)throw error;throw new WorkspaceApiError(503);}
  finally{clearTimeout(timer);signal?.removeEventListener('abort',abort);stop(reader);if(!reader)stop(response?.body);
    try{reader?.releaseLock();}catch{/* The cancelled read may settle later. */}controller.abort();}
}
