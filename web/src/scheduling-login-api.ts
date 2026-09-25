import {workspaceFetch} from './workspace-protocol';
import {WorkspaceApiError, type AuthenticatedWorkspaceIdentity} from './workspace-api';
import {assertCurrentDesktopSession, workspaceAuthHeaders} from './workspace-auth-headers';
import {SCHEDULING_BUILD} from './scheduling-api';
import {parseVendorJson} from './vendor-contract';

export const SCHEDULING_LOGIN_BUILD = SCHEDULING_BUILD && import.meta.env.VITE_WORKSPACE_SCHEDULING_LOGIN_ENABLED === 'true';
export type SchedulingLoginStatus = {state:'connected'|'sign_in_required'|'sign_in_pending'|'completing_sign_in';label:string;connected_at:string|null};
export type SchedulingLoginStart = {authorization_url:string;expires_at:string};
const closed=(value:unknown,keys:string):value is Record<string,unknown>=>!!value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).sort().join(',')===keys;

export function validGoogleSchedulingUrl(value:unknown):value is string {
  if(typeof value!=='string'||value.length>4096)return false;
  try {
    const url=new URL(value),query=url.searchParams;
    const required=['access_type','client_id','code_challenge','code_challenge_method','nonce','prompt','redirect_uri','response_type','scope','state'];
    if(url.origin!=='https://accounts.google.com'||url.pathname!=='/o/oauth2/v2/auth'||url.hash||url.username||url.password||
      [...query.keys()].sort().join(',')!==required.sort().join(',')||required.some(key=>query.getAll(key).length!==1)||
      query.get('response_type')!=='code'||query.get('scope')!=='openid email'||query.get('access_type')!=='offline'||
      query.get('prompt')!=='consent select_account'||query.get('code_challenge_method')!=='S256'||
      !query.get('client_id')?.endsWith('.apps.googleusercontent.com')||
      ['state','nonce','code_challenge'].some(key=>!/^[A-Za-z0-9_-]{43}$/.test(query.get(key)||'')))return false;
    const callback=new URL(query.get('redirect_uri')!);
    return callback.protocol==='https:'&&!callback.username&&!callback.password&&!callback.search&&!callback.hash&&
      (!callback.port||callback.port==='443')&&callback.pathname==='/connections/scheduling/google/callback';
  }catch{return false;}
}

export async function requestSchedulingSession<T>(identity:AuthenticatedWorkspaceIdentity, command:object, validate:(value:unknown)=>T|Promise<T>, signal?:AbortSignal):Promise<T>{
  if(!SCHEDULING_LOGIN_BUILD)throw new WorkspaceApiError(404);
  const base=import.meta.env.VITE_API_BASE?.trim().replace(/\/+$/,'')||'http://127.0.0.1:8000';
  const controller=new AbortController();const abort=()=>controller.abort();
  let rejectAbort:()=>void=()=>undefined;
  const interrupted=new Promise<never>((_,reject)=>{rejectAbort=()=>reject(new WorkspaceApiError(503));});
  void interrupted.catch(()=>{}); // An already-aborted caller may exit before the first race.
  controller.signal.addEventListener('abort',rejectAbort,{once:true});
  const timer=setTimeout(abort,20000);signal?.addEventListener('abort',abort,{once:true});
  let response:Response|undefined,reader:ReadableStreamDefaultReader<Uint8Array>|undefined;
  const cancel=(body:{cancel:()=>Promise<unknown>}|null|undefined)=>{try{void body?.cancel().catch(()=>{});}catch{/* canceled */}};
  const check=()=>{controller.signal.throwIfAborted();assertCurrentDesktopSession(identity);if(identity.mode!=='desktop_native'&&identity.nativeSession&&!identity.nativeSession.isCurrent())throw new WorkspaceApiError(401);};
  const wait=<T,>(promise:Promise<T>)=>Promise.race([promise,interrupted]);
  try {
    if(new TextEncoder().encode(JSON.stringify(command)).length>2048)throw new WorkspaceApiError(422);
    if(signal?.aborted)abort();check();
    const headers=await wait(workspaceAuthHeaders(identity,base));check();
    headers.set('X-Cosmas-Scheduling-Login','1');headers.set('Accept','application/json');headers.set('Content-Type','application/json');
    response=await wait(workspaceFetch(identity,base+'/connections/scheduling/session',{method:'POST',headers,body:JSON.stringify(command),
      signal:controller.signal,cache:'no-store',credentials:'omit',redirect:'error',referrerPolicy:'no-referrer'}).then(value=>{
      if(controller.signal.aborted){cancel(value.body);throw new WorkspaceApiError(503);}return value;
    }));check();
    if(!response)throw new WorkspaceApiError(503);
    if([401,403,404,409].includes(response.status))throw new WorkspaceApiError(response.status);
    if(response.status!==200||response.redirected||response.headers.has('content-encoding')||
      response.headers.get('content-type')?.split(';',1)[0]!=='application/json'||
      !response.headers.get('cache-control')?.split(',').some(v=>v.trim()==='no-store'))throw new WorkspaceApiError(502);
    reader=response.body?.getReader();if(!reader)throw new WorkspaceApiError(502);
    const bytes=new Uint8Array(69632);let size=0;
    for(;;){const part=await wait(reader.read());check();if(part.done)break;if(part.value.byteLength>bytes.length-size)throw new WorkspaceApiError(502);bytes.set(part.value,size);size+=part.value.byteLength;}
    const value:unknown=parseVendorJson(new TextDecoder('utf-8',{fatal:true}).decode(bytes.subarray(0,size)));check();
    const result=await wait(Promise.resolve(validate(value)));check();return result;
  }finally{
    clearTimeout(timer);signal?.removeEventListener('abort',abort);controller.signal.removeEventListener('abort',rejectAbort);
    cancel(reader??response?.body);try{reader?.releaseLock();}catch{/* released */}controller.abort();
  }
}


export async function schedulingLoginRequest(identity:AuthenticatedWorkspaceIdentity, action:'status'|'start'|'disconnect', signal?:AbortSignal):Promise<SchedulingLoginStatus|SchedulingLoginStart|{state:'disconnected'}>{
  return requestSchedulingSession(identity,{action},value=>{
    if(action==='start'&&closed(value,'authorization_url,expires_at')&&validGoogleSchedulingUrl(value.authorization_url)&&
      typeof value.expires_at==='string'&&Date.parse(value.expires_at)>Date.now()&&Date.parse(value.expires_at)<=Date.now()+610000)return value as SchedulingLoginStart;
    if(action==='disconnect'&&closed(value,'state')&&value.state==='disconnected')return {state:'disconnected'};
    if(action==='status'&&closed(value,'connected_at,label,state')&&['connected','sign_in_required','sign_in_pending','completing_sign_in'].includes(String(value.state))&&
      typeof value.label==='string'&&value.label.length>0&&value.label.length<=120&&(value.connected_at===null||typeof value.connected_at==='string'&&Number.isFinite(Date.parse(value.connected_at))))return value as SchedulingLoginStatus;
    throw new WorkspaceApiError(502);
  },signal);
}
