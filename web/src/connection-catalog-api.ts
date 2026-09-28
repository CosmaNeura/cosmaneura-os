import {workspaceFetch} from './workspace-protocol';
import {WorkspaceApiError, type AuthenticatedWorkspaceIdentity} from './workspace-api';
import {assertCurrentDesktopSession, workspaceAuthHeaders} from './workspace-auth-headers';
import {parseVendorJson} from './vendor-contract';

export const CONNECTION_IDS = ['core','google','microsoft','scheduling','messaging','payments','portals'] as const;
export type ConnectionId = typeof CONNECTION_IDS[number];
export type ConnectionCatalog = Record<ConnectionId, boolean>;
export function parseConnectionCatalog(value:unknown):ConnectionCatalog {
  if(!value || typeof value!=='object' || Array.isArray(value) ||
    Object.keys(value).sort().join(',')!=='services,version')throw new WorkspaceApiError(502);
  const data=value as {version:unknown;services:unknown};
  if(data.version!==1||!Array.isArray(data.services)||data.services.length!==CONNECTION_IDS.length)throw new WorkspaceApiError(502);
  const result={} as ConnectionCatalog;
  for(const row of data.services){
    if(!row||typeof row!=='object'||Object.keys(row).sort().join(',')!=='id,setup_available'||
      !CONNECTION_IDS.includes(row.id)||typeof row.setup_available!=='boolean'||Object.hasOwn(result,row.id))throw new WorkspaceApiError(502);
    result[row.id as ConnectionId]=row.setup_available;
  }
  return result;
}

export async function readConnectionCatalog(identity:AuthenticatedWorkspaceIdentity, signal:AbortSignal):Promise<ConnectionCatalog>{
  const controller=new AbortController(), abort=()=>controller.abort();
  const interrupted=new Promise<never>((_,reject)=>controller.signal.addEventListener('abort',()=>reject(new WorkspaceApiError(503)),{once:true}));
  void interrupted.catch(()=>{});
  const wait=<T,>(promise:Promise<T>)=>Promise.race([promise,interrupted]);
  const check=()=>{controller.signal.throwIfAborted();assertCurrentDesktopSession(identity);
    if(identity.mode!=='desktop_native'&&identity.nativeSession&&!identity.nativeSession.isCurrent())throw new WorkspaceApiError(401);};
  const timer=setTimeout(abort,15000);signal.addEventListener('abort',abort,{once:true});
  let response:Response|undefined, reader:ReadableStreamDefaultReader<Uint8Array>|undefined;
  const cancel=(body:{cancel:()=>Promise<unknown>}|null|undefined)=>{try{void body?.cancel().catch(()=>{});}catch{/* already closed */}};
  try{
    if(signal.aborted)abort();check();
    const base=import.meta.env.VITE_API_BASE?.trim().replace(/\/+$/,'')||'http://127.0.0.1:8000';
    const headers=await wait(workspaceAuthHeaders(identity,base));check();
    headers.set('X-Cosmas-Connection-Contract','1');headers.set('Accept','application/json');
    response=await wait(workspaceFetch(identity,base+'/connections/catalog',{method:'GET',headers,signal:controller.signal,
      credentials:'omit',cache:'no-store',redirect:'error',referrerPolicy:'no-referrer'}).then(result=>{
      if(controller.signal.aborted){cancel(result.body);throw new WorkspaceApiError(503);}return result;
    }));check();
    if(!response)throw new WorkspaceApiError(503);
    if([401,403,404,426].includes(response.status))throw new WorkspaceApiError(response.status);
    if(response.status!==200||response.redirected||response.headers.has('content-encoding')||
      response.headers.get('content-type')?.split(';',1)[0]!=='application/json'||
      !response.headers.get('cache-control')?.split(',').some(v=>v.trim()==='no-store'))throw new WorkspaceApiError(502);
    reader=response.body?.getReader();if(!reader)throw new WorkspaceApiError(502);
    const bytes=new Uint8Array(4096);let size=0;
    for(;;){const part=await wait(reader.read());check();if(part.done)break;
      if(part.value.byteLength>bytes.length-size)throw new WorkspaceApiError(502);
      bytes.set(part.value,size);size+=part.value.byteLength;}
    return parseConnectionCatalog(parseVendorJson(new TextDecoder('utf-8',{fatal:true}).decode(bytes.subarray(0,size))));
  }finally{
    clearTimeout(timer);signal.removeEventListener('abort',abort);cancel(reader??response?.body);
    try{reader?.releaseLock();}catch{/* already released */}controller.abort();
  }
}
