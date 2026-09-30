import {PERSONAL_CONNECTION_DEADLINE_MS} from './connection-operation-health';
import {workspaceFetch} from './workspace-protocol';
import {WorkspaceApiError, WORKSPACE_BUILD, WORKSPACE_AUTHENTICATED_BUILD, type AuthenticatedWorkspaceIdentity} from './workspace-api';
import {assertCurrentDesktopSession, workspaceAuthHeaders} from './workspace-auth-headers';
import {parseVendorJson} from './vendor-contract';

export const MICROSOFT_CONNECTION_BUILD=WORKSPACE_BUILD&&WORKSPACE_AUTHENTICATED_BUILD&&import.meta.env.VITE_WORKSPACE_MICROSOFT_CONNECTION_ENABLED==='true';
export type MicrosoftAction='status'|'start'|'disconnect'|'mail'|'calendar';
export type MicrosoftAccount={label:string;email:string};
export type MicrosoftStatus={state:'connected'|'sign_in_required'|'sign_in_pending'|'completing_sign_in';account:MicrosoftAccount|null;connected_at:string|null};
export type MicrosoftStart={authorization_url:string;expires_at:string};
export type MicrosoftMail={id:string;subject:string;sender:string;received_at:string;is_read:boolean};
export type MicrosoftEvent={id:string;subject:string;starts_at:string;ends_at:string;cancelled:boolean;all_day:boolean};
export type MicrosoftView=({kind:'mail';items:MicrosoftMail[]}|{kind:'calendar';items:MicrosoftEvent[]})&{account:MicrosoftAccount;more:boolean;observed_at:string};
const closed=(value:unknown,keys:string):value is Record<string,unknown>=>!!value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).sort().join(',')===keys.split(',').sort().join(',');
const string=(value:unknown,max:number):value is string=>typeof value==='string'&&value.length<=max&&!/[\u0000-\u001f\u007f]/.test(value);
const instant=(value:unknown):value is string=>typeof value==='string'&&/(?:Z|[+-]\d\d:\d\d)$/.test(value)&&Number.isFinite(Date.parse(value));
const account=(value:unknown):value is MicrosoftAccount=>closed(value,'label,email')&&string(value.label,256)&&!!value.label&&string(value.email,320)&&!!value.email;
const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
export function validMicrosoftAuthorizationUrl(value:unknown):value is string {
  if(typeof value!=='string'||value.length>4096||/[\u0000-\u0020\u007f]/.test(value))return false;
  try{
    const url=new URL(value),q=url.searchParams,tenant=url.pathname.split('/')[1];
    const keys=['client_id','code_challenge','code_challenge_method','prompt','redirect_uri','response_mode','response_type','scope','state'];
    if(url.origin!=='https://login.microsoftonline.com'||url.username||url.password||url.hash||!uuid.test(tenant)||
      url.pathname!==`/${tenant}/oauth2/v2.0/authorize`||[...q.keys()].sort().join(',')!==keys.join(',')||keys.some(k=>q.getAll(k).length!==1)||
      !uuid.test(q.get('client_id')||'')||q.get('response_type')!=='code'||q.get('response_mode')!=='query'||q.get('prompt')!=='select_account'||
      q.get('scope')!=='offline_access User.Read Mail.Read Calendars.Read'||q.get('code_challenge_method')!=='S256'||
      ['state','code_challenge'].some(k=>!/^[A-Za-z0-9_-]{43}$/.test(q.get(k)||'')))return false;
    const callback=new URL(q.get('redirect_uri')!);
    return callback.protocol==='https:'&&!callback.username&&!callback.password&&!callback.search&&!callback.hash&&
      (!callback.port||callback.port==='443')&&callback.pathname==='/connections/microsoft/callback';
  }catch{return false;}
}
export function validateMicrosoftResponse(value:unknown,action:MicrosoftAction):MicrosoftStatus|MicrosoftStart|MicrosoftView|{state:'disconnected'} {
  if(action==='start'&&closed(value,'authorization_url,expires_at')&&validMicrosoftAuthorizationUrl(value.authorization_url)&&instant(value.expires_at)&&
    Date.parse(value.expires_at)>Date.now()&&Date.parse(value.expires_at)<=Date.now()+610000)return value as MicrosoftStart;
  if(action==='disconnect'&&closed(value,'state')&&value.state==='disconnected')return {state:'disconnected'};
  if(action==='status'&&closed(value,'state,account,connected_at')&&['connected','sign_in_required','sign_in_pending','completing_sign_in'].includes(String(value.state))&&
    (value.account===null||account(value.account))&&(value.connected_at===null||instant(value.connected_at))&&
    (value.state==='connected'?account(value.account)&&instant(value.connected_at):value.account===null))return value as MicrosoftStatus;
  if((action==='mail'||action==='calendar')&&closed(value,'kind,account,items,more,observed_at')&&value.kind===action&&account(value.account)&&
    typeof value.more==='boolean'&&instant(value.observed_at)&&Array.isArray(value.items)&&value.items.length<=25&&value.items.every(row=>{
      if(!closed(row,action==='mail'?'id,subject,sender,received_at,is_read':'id,subject,starts_at,ends_at,cancelled,all_day')||!string(row.id,2048)||!row.id||!string(row.subject,998))return false;
      return action==='mail'?string(row.sender,320)&&instant(row.received_at)&&typeof row.is_read==='boolean':
        instant(row.starts_at)&&instant(row.ends_at)&&Date.parse(row.ends_at)>=Date.parse(row.starts_at)&&typeof row.cancelled==='boolean'&&typeof row.all_day==='boolean';
    }))return value as MicrosoftView;
  throw new WorkspaceApiError(502);
}

export async function microsoftConnectionRequest(identity:AuthenticatedWorkspaceIdentity, action:MicrosoftAction, signal?:AbortSignal):Promise<MicrosoftStatus|MicrosoftStart|MicrosoftView|{state:'disconnected'}>{
  if(!MICROSOFT_CONNECTION_BUILD)throw new WorkspaceApiError(404);
  const base=import.meta.env.VITE_API_BASE?.trim().replace(/\/+$/,'')||'http://127.0.0.1:8000';
  const controller=new AbortController();const abort=()=>controller.abort();
  let rejectAbort:()=>void=()=>undefined;
  const interrupted=new Promise<never>((_,reject)=>{rejectAbort=()=>reject(new WorkspaceApiError(503));});
  void interrupted.catch(()=>{}); // An already-aborted caller may exit before the first race.
  controller.signal.addEventListener('abort',rejectAbort,{once:true});
  const timer=setTimeout(abort,PERSONAL_CONNECTION_DEADLINE_MS);signal?.addEventListener('abort',abort,{once:true});
  let response:Response|undefined,reader:ReadableStreamDefaultReader<Uint8Array>|undefined;
  const cancel=(body:{cancel:()=>Promise<unknown>}|null|undefined)=>{try{void body?.cancel().catch(()=>{});}catch{/* canceled */}};
  const check=()=>{controller.signal.throwIfAborted();assertCurrentDesktopSession(identity);if(identity.mode!=='desktop_native'&&identity.nativeSession&&!identity.nativeSession.isCurrent())throw new WorkspaceApiError(401);};
  const wait=<T,>(promise:Promise<T>)=>Promise.race([promise,interrupted]);
  try {
    if(signal?.aborted)abort();check();
    const headers=await wait(workspaceAuthHeaders(identity,base));check();
    headers.set('X-Cosmas-Microsoft-Connection','1');headers.set('Accept','application/json');
    response=await wait(workspaceFetch(identity,base+'/connections/microsoft/session',{method:'POST',headers,body:JSON.stringify({action}),
      signal:controller.signal,cache:'no-store',credentials:'omit',redirect:'error',referrerPolicy:'no-referrer'}).then(value=>{
      if(controller.signal.aborted){cancel(value.body);throw new WorkspaceApiError(503);}return value;
    }));check();
    if(!response)throw new WorkspaceApiError(503);
    if([401,403,404,409].includes(response.status))throw new WorkspaceApiError(response.status);
    if(response.status!==200||response.redirected||response.headers.has('content-encoding')||
      response.headers.get('content-type')?.split(';',1)[0]!=='application/json'||
      !response.headers.get('cache-control')?.split(',').some(v=>v.trim()==='no-store'))throw new WorkspaceApiError(502);
    reader=response.body?.getReader();if(!reader)throw new WorkspaceApiError(502);
    const bytes=new Uint8Array(131072);let size=0;
    for(;;){const part=await wait(reader.read());check();if(part.done)break;if(part.value.byteLength>bytes.length-size)throw new WorkspaceApiError(502);bytes.set(part.value,size);size+=part.value.byteLength;}
    const value:unknown=parseVendorJson(new TextDecoder('utf-8',{fatal:true}).decode(bytes.subarray(0,size)));check();
    return validateMicrosoftResponse(value, action);
  }finally{
    clearTimeout(timer);signal?.removeEventListener('abort',abort);controller.signal.removeEventListener('abort',rejectAbort);
    cancel(reader??response?.body);try{reader?.releaseLock();}catch{/* released */}controller.abort();
  }
}
