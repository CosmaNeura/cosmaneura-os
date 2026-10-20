import {assertCurrentDesktopSession,workspaceAuthHeaders} from './workspace-auth-headers';
import {workspaceFetch} from './workspace-protocol';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from './workspace-api';
import {parseVendorJson} from './vendor-contract';
import {validShareSavedNoteInput,verifyClinicalNoteShareReceipt,type ShareSavedNoteInput} from './clinical-team-contract';

async function request(identity:AuthenticatedWorkspaceIdentity,workspaceId:string,body:ShareSavedNoteInput,resolve:boolean) {
  if(!validShareSavedNoteInput(body)||!/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(workspaceId))throw new WorkspaceApiError(422);
  const base=import.meta.env.VITE_API_BASE?.trim().replace(/\/+$/,'')||'http://127.0.0.1:8000';
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),30000);
  let reader:ReadableStreamDefaultReader<Uint8Array>|undefined;
  const interrupted=new Promise<never>((_,reject)=>controller.signal.addEventListener('abort',()=>reject(new WorkspaceApiError(503)),{once:true}));
  const wait=<T,>(value:Promise<T>)=>Promise.race([value,interrupted]);
  const check=()=>{controller.signal.throwIfAborted();assertCurrentDesktopSession(identity);
    if('nativeSession'in identity&&identity.nativeSession&&!identity.nativeSession.isCurrent())throw new WorkspaceApiError(401);};
  try {
    check();const headers=await wait(workspaceAuthHeaders(identity,base));check();headers.set('X-Cosmas-Clinical-Team','1');
    const response=await wait(workspaceFetch(identity,`${base}/workspaces/${workspaceId}/note/team-source${resolve?'/resolve':''}`,
      {method:'POST',headers,body:JSON.stringify(body),signal:controller.signal,credentials:'omit',cache:'no-store',redirect:'error',referrerPolicy:'no-referrer'}));check();
    if(!response.ok)throw new WorkspaceApiError(response.status);
    const length=response.headers.get('content-length');
    if(response.redirected||response.headers.get('content-type')?.split(';',1)[0].trim()!=='application/json'||
      response.type==='opaque'||response.type==='opaqueredirect'||response.headers.has('content-encoding')||
      !response.headers.get('cache-control')?.split(',').some(v=>v.trim().toLowerCase()==='no-store')||
      length!==null&&(!/^(?:0|[1-9][0-9]*)$/.test(length)||Number(length)>12000000))throw new WorkspaceApiError(502);
    reader=response.body?.getReader();if(!reader)throw new WorkspaceApiError(502);
    const chunks:Uint8Array[]=[];let size=0;
    for(;;){const part=await wait(reader.read());check();if(part.done)break;size+=part.value.length;if(size>12000000)throw new WorkspaceApiError(502);chunks.push(part.value);}
    if(length!==null&&Number(length)!==size)throw new WorkspaceApiError(502);
    const bytes=new Uint8Array(size);let at=0;for(const chunk of chunks){bytes.set(chunk,at);at+=chunk.length;}
    const value=parseVendorJson(new TextDecoder('utf-8',{fatal:true}).decode(bytes));
    const receipt=await wait(verifyClinicalNoteShareReceipt(value,workspaceId,body));check();return receipt;
  }catch(cause){if(cause instanceof WorkspaceApiError)throw cause;throw new WorkspaceApiError(503);}
  finally{clearTimeout(timer);try{void reader?.cancel().catch(()=>{});reader?.releaseLock();}catch{/* The exact share remains recoverable. */}controller.abort();}
}
export const clinicalTeamApi={share:(identity:AuthenticatedWorkspaceIdentity,wid:string,body:ShareSavedNoteInput)=>request(identity,wid,body,false),
  resolve:(identity:AuthenticatedWorkspaceIdentity,wid:string,body:ShareSavedNoteInput)=>request(identity,wid,body,true)};
