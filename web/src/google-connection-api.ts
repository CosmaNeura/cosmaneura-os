import {workspaceFetch} from './workspace-protocol';
import {googleNavigationConfig,validGoogleNavigationUrl} from '../../clients/desktop/google-navigation.mjs';
import {WorkspaceApiError, WORKSPACE_BUILD, WORKSPACE_AUTHENTICATED_BUILD, type AuthenticatedWorkspaceIdentity} from './workspace-api';
import {assertCurrentDesktopSession, workspaceAuthHeaders} from './workspace-auth-headers';
import {parseVendorJson} from './vendor-contract';

export const GOOGLE_CONNECTION_BUILD=WORKSPACE_BUILD&&WORKSPACE_AUTHENTICATED_BUILD&&import.meta.env.VITE_WORKSPACE_GOOGLE_CONNECTION_ENABLED==='true';
export type GoogleAction='status'|'start'|'disconnect'|'mail'|'calendar';
export type GoogleAccount={label:string;email:string};
export type GoogleStatus={state:'connected'|'sign_in_required'|'sign_in_pending'|'completing_sign_in';account:GoogleAccount|null;connected_at:string|null;capabilities?:{mail:boolean;calendar:boolean}};
export type GoogleStart={authorization_url:string;expires_at:string};
export type GoogleMail={id:string;subject:string;sender:string;received_at:string;is_read:boolean};
export type GoogleEvent={id:string;subject:string;starts_at:string;ends_at:string;all_day:boolean;cancelled:boolean};
export type GoogleView=({kind:'mail';items:GoogleMail[]}|{kind:'calendar';items:GoogleEvent[]})&{account:GoogleAccount;more:boolean;observed_at:string};
const closed=(value:unknown,keys:string):value is Record<string,unknown>=>!!value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).sort().join(',')===keys.split(',').sort().join(',');
const string=(value:unknown,max:number):value is string=>typeof value==='string'&&value.length<=max&&!/[\u0000-\u001f\u007f]/.test(value);
const instant=(value:unknown):value is string=>typeof value==='string'&&/(?:Z|[+-]\d\d:\d\d)$/.test(value)&&Number.isFinite(Date.parse(value));
const account=(value:unknown):value is GoogleAccount=>closed(value,'label,email')&&string(value.label,256)&&!!value.label&&string(value.email,320)&&!!value.email;
export function validGoogleAuthorizationUrl(value:unknown):value is string {
  if(typeof value!=='string')return false;
  try{const params=new URL(value).searchParams;return validGoogleNavigationUrl(value,
    googleNavigationConfig(params.get('client_id')??'',params.get('redirect_uri')??''));}catch{return false;}
}
export function validateGoogleResponse(value:unknown,action:GoogleAction):GoogleStatus|GoogleStart|GoogleView|{state:'disconnected'} {
  if(action==='start'&&closed(value,'authorization_url,expires_at')&&validGoogleAuthorizationUrl(value.authorization_url)&&instant(value.expires_at)&&
    Date.parse(value.expires_at)>Date.now()&&Date.parse(value.expires_at)<=Date.now()+610000)return value as GoogleStart;
  if(action==='disconnect'&&closed(value,'state')&&value.state==='disconnected')return {state:'disconnected'};
  if(action==='status'&&(closed(value,'state,account,connected_at')||closed(value,'state,account,connected_at,capabilities'))&&['connected','sign_in_required','sign_in_pending','completing_sign_in'].includes(String(value.state))&&
    (value.account===null||account(value.account))&&(value.connected_at===null||instant(value.connected_at))&&
    (!('capabilities' in value)||closed(value.capabilities,'mail,calendar')&&typeof value.capabilities.calendar==='boolean'&&
      (value.state==='connected'?value.capabilities.mail===true:value.capabilities.mail===false&&value.capabilities.calendar===false))&&
    (value.state==='connected'?account(value.account)&&instant(value.connected_at):value.account===null))return value as GoogleStatus;
  if(action==='mail'&&closed(value,'kind,account,items,more,observed_at')&&value.kind==='mail'&&account(value.account)&&
    typeof value.more==='boolean'&&instant(value.observed_at)&&Array.isArray(value.items)&&value.items.length<=10&&
    new Set(value.items.map(row=>row?.id)).size===value.items.length&&value.items.every(row=>
      closed(row,'id,subject,sender,received_at,is_read')&&string(row.id,128)&&/^[A-Za-z0-9_-]+$/.test(row.id)&&
      string(row.subject,998)&&string(row.sender,320)&&instant(row.received_at)&&typeof row.is_read==='boolean'))return value as GoogleView;
  if(action==='calendar'&&closed(value,'kind,account,items,more,observed_at')&&value.kind==='calendar'&&account(value.account)&&
    typeof value.more==='boolean'&&instant(value.observed_at)&&Array.isArray(value.items)&&value.items.length<=25&&
    new Set(value.items.map(row=>row?.id)).size===value.items.length&&value.items.every(row=>
      closed(row,'id,subject,starts_at,ends_at,all_day,cancelled')&&string(row.id,1024)&&/^[A-Za-z0-9_-]+$/.test(row.id)&&
      string(row.subject,998)&&typeof row.all_day==='boolean'&&typeof row.cancelled==='boolean'&&
      (row.all_day?[row.starts_at,row.ends_at].every(v=>typeof v==='string'&&/^\d{4}-\d\d-\d\d$/.test(v)&&
        Number.isFinite(Date.parse(v))&&new Date(v).toISOString().slice(0,10)===v):instant(row.starts_at)&&instant(row.ends_at))&&
      Date.parse(String(row.ends_at))>Date.parse(String(row.starts_at))))return value as GoogleView;
  throw new WorkspaceApiError(502);
}

export async function googleConnectionRequest(identity:AuthenticatedWorkspaceIdentity, action:GoogleAction, signal?:AbortSignal):Promise<GoogleStatus|GoogleStart|GoogleView|{state:'disconnected'}>{
  if(!GOOGLE_CONNECTION_BUILD)throw new WorkspaceApiError(404);
  const base=import.meta.env.VITE_API_BASE?.trim().replace(/\/+$/,'')||'http://127.0.0.1:8000';
  const controller=new AbortController();const abort=()=>controller.abort();
  let rejectAbort:()=>void=()=>undefined;
  const interrupted=new Promise<never>((_,reject)=>{rejectAbort=()=>reject(new WorkspaceApiError(503));});
  void interrupted.catch(()=>{}); // An already-aborted caller may exit before the first race.
  controller.signal.addEventListener('abort',rejectAbort,{once:true});
  const timer=setTimeout(abort,50000);signal?.addEventListener('abort',abort,{once:true});
  let response:Response|undefined,reader:ReadableStreamDefaultReader<Uint8Array>|undefined;
  const cancel=(body:{cancel:()=>Promise<unknown>}|null|undefined)=>{try{void body?.cancel().catch(()=>{});}catch{/* canceled */}};
  const check=()=>{controller.signal.throwIfAborted();assertCurrentDesktopSession(identity);if(identity.mode!=='desktop_native'&&identity.nativeSession&&!identity.nativeSession.isCurrent())throw new WorkspaceApiError(401);};
  const wait=<T,>(promise:Promise<T>)=>Promise.race([promise,interrupted]);
  try {
    if(signal?.aborted)abort();check();
    const headers=await wait(workspaceAuthHeaders(identity,base));check();
    headers.set('X-Cosmas-Google-Connection','1');headers.set('Accept','application/json');
    const send=(includeCapabilities:boolean)=>wait(workspaceFetch(identity,base+'/connections/google/session',{method:'POST',headers,body:JSON.stringify({action,...(includeCapabilities?{include_capabilities:true}:{})}),
      signal:controller.signal,cache:'no-store',credentials:'omit',redirect:'error',referrerPolicy:'no-referrer'}).then(value=>{
      if(controller.signal.aborted){cancel(value.body);throw new WorkspaceApiError(503);}return value;
    }));
    response=await send(action==='status');check();
    // Older servers reject the opt-in field. Retry only this read, once, within
    // the original deadline; never replay consent or a provider-content read.
    if(action==='status'&&response.status===422){cancel(response.body);response=await send(false);check();}
    if(!response)throw new WorkspaceApiError(503);
    if([401,403,404].includes(response.status))throw new WorkspaceApiError(response.status);
    if(![200,409].includes(response.status)||response.redirected||response.headers.has('content-encoding')||
      response.headers.get('content-type')?.split(';',1)[0]!=='application/json'||
      !response.headers.get('cache-control')?.split(',').some(v=>v.trim()==='no-store'))throw new WorkspaceApiError(502);
    reader=response.body?.getReader();if(!reader)throw new WorkspaceApiError(502);
    const bytes=new Uint8Array(response.status===409?1024:131072);let size=0;
    for(;;){const part=await wait(reader.read());check();if(part.done)break;if(part.value.byteLength>bytes.length-size)throw new WorkspaceApiError(502);bytes.set(part.value,size);size+=part.value.byteLength;}
    const value:unknown=parseVendorJson(new TextDecoder('utf-8',{fatal:true}).decode(bytes.subarray(0,size)));check();
    if(response.status===409)throw new WorkspaceApiError(409,closed(value,'detail')&&value.detail==='google_calendar_consent_required'?value.detail:undefined);
    return validateGoogleResponse(value, action);
  }finally{
    clearTimeout(timer);signal?.removeEventListener('abort',abort);controller.signal.removeEventListener('abort',rejectAbort);
    cancel(reader??response?.body);try{reader?.releaseLock();}catch{/* released */}controller.abort();
  }
}
