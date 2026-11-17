import {workspaceApiBase} from './workspace-base';
import {workspaceFetch} from './workspace-protocol';
import {permittedWorkspaceApi} from './workspace-origin';
import {assertCurrentDesktopSession,workspaceAuthHeaders} from './workspace-auth-headers';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from './workspace-api';

export const COPY_TO_EHR_REMOTE_BUILD=false;
const DEADLINE_MS=15_000;
const RESPONSE_BYTES=16_384;
const ERROR_BYTES=2_048;
const CONTRACT='X-Cosmas-Copy-To-Ehr';

export type CopyToEhrRemoteSession={
  session_id:string;
  status:'open'|'ended'|'expired';
  draft_id:string;
  draft_revision:number;
  section_keys:string[];
  visit_key:string;
  created_at:string;
  last_activity_at:string;
  ended_at:string|null;
  end_reason:string|null;
};
export type CopyToEhrRemoteHighlight={
  seq:number;
  section_key:string;
  draft_revision:number;
  at:string;
};
export type CopyToEhrRemoteEvents=CopyToEhrRemoteSession&{
  events:CopyToEhrRemoteHighlight[];
  next_after:number;
};
export type CreateCopyToEhrRemoteSession={
  draft_id:string;
  draft_revision:number;
  section_keys:string[];
  visit_key:string;
};

const sectionKey=(v:unknown):v is string=>typeof v==='string'&&/^[a-z][a-z0-9_]{0,63}$/.test(v);
const uuid=(v:unknown):v is string=>typeof v==='string'&&/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(v);
const time=(v:unknown):v is string=>typeof v==='string'&&!Number.isNaN(Date.parse(v));
const closed=(v:unknown,keys:string,optional=''):v is Record<string,unknown>=>{
  if(!v||typeof v!=='object'||Array.isArray(v))return false;
  const required=keys.split(',');
  const allowed=new Set([...required,...(optional?optional.split(','):[])]);
  const own=Object.keys(v);
  return required.every(key=>own.includes(key))&&own.every(key=>allowed.has(key));
};

export function validCopyToEhrRemoteSession(v:unknown):v is CopyToEhrRemoteSession{
  if(!closed(v,'session_id,status,draft_id,draft_revision,section_keys,visit_key,created_at,last_activity_at,ended_at,end_reason'))return false;
  if(!uuid(v.session_id)||!uuid(v.draft_id))return false;
  if(v.status!=='open'&&v.status!=='ended'&&v.status!=='expired')return false;
  if(!Number.isInteger(v.draft_revision)||Number(v.draft_revision)<1)return false;
  if(!Array.isArray(v.section_keys)||v.section_keys.length<1||v.section_keys.length>32||!v.section_keys.every(sectionKey))return false;
  if(typeof v.visit_key!=='string'||!/^[A-Za-z0-9:_-]{1,100}$/.test(v.visit_key))return false;
  if(!time(v.created_at)||!time(v.last_activity_at))return false;
  if(v.ended_at!==null&&!time(v.ended_at))return false;
  if(v.end_reason!==null&&typeof v.end_reason!=='string')return false;
  return true;
}

export function validCopyToEhrRemoteHighlight(v:unknown):v is CopyToEhrRemoteHighlight{
  return closed(v,'seq,section_key,draft_revision,at')
    &&Number.isInteger(v.seq)&&Number(v.seq)>=1
    &&sectionKey(v.section_key)
    &&Number.isInteger(v.draft_revision)&&Number(v.draft_revision)>=1
    &&time(v.at);
}

export function validCopyToEhrRemoteEvents(v:unknown):v is CopyToEhrRemoteEvents{
  if(!validCopyToEhrRemoteSession(v)||!('events' in v)||!('next_after' in v))return false;
  const body=v as CopyToEhrRemoteSession&{events:unknown;next_after:unknown};
  return Array.isArray(body.events)&&body.events.every(validCopyToEhrRemoteHighlight)
    &&Number.isInteger(body.next_after)&&Number(body.next_after)>=0;
}

function hasNoteText(value:unknown):boolean{
  if(Array.isArray(value))return value.some(hasNoteText);
  if(!value||typeof value!=='object')return false;
  for(const [key,child] of Object.entries(value)){
    if(['text','note','note_text','full_note','content','body','clipboard','patient','chart_url','page_title','label','labels'].includes(key))return true;
    if(hasNoteText(child))return true;
  }
  return false;
}

const errorCodes:Readonly<Record<number,readonly string[]>>={
  401:['workspace_access_denied','access_required','admission_unavailable'],
  403:['workspace_access_denied'],
  404:['copy_to_ehr_remote_unavailable','copy_to_ehr_remote_session_unavailable'],
  409:['copy_to_ehr_remote_session_ended','copy_to_ehr_remote_revision_mismatch'],
  422:['invalid_copy_to_ehr_remote_request'],
};

async function call<T>(
  identity:AuthenticatedWorkspaceIdentity,
  path:string,
  init:RequestInit,
  validate:(value:unknown)=>value is T,
  signal?:AbortSignal,
):Promise<T>{
  const deadline=performance.now()+DEADLINE_MS;
  const controller=new AbortController();
  let interruption:WorkspaceApiError|undefined;
  const interrupt=(error:WorkspaceApiError)=>{if(!controller.signal.aborted){interruption=error;controller.abort();}};
  const expire=()=>interrupt(new WorkspaceApiError(504,'copy_to_ehr_remote_timeout'));
  const abort=()=>interrupt(new WorkspaceApiError(503,'copy_to_ehr_remote_unavailable'));
  signal?.addEventListener('abort',abort,{once:true});
  if(signal?.aborted)abort();
  const timer=setTimeout(expire,DEADLINE_MS);
  try{
    assertCurrentDesktopSession(identity);
    const base=workspaceApiBase(identity);
    if(base.includes('?')||base.includes('#')||!permittedWorkspaceApi(base,import.meta.env.VITE_DESKTOP_SYNTHETIC_ENABLED==='true',window.location.href)){
      throw new WorkspaceApiError(503,'copy_to_ehr_remote_unavailable');
    }
    const headers=await workspaceAuthHeaders(identity,base);
    if(performance.now()>=deadline)expire();
    assertCurrentDesktopSession(identity);
    headers.set(CONTRACT,'1');
    headers.set('Accept','application/json');
    if(init.body)headers.set('Content-Type','application/json');
    const url=base+path;
    const response=await workspaceFetch(identity,url,{
      ...init,
      headers,
      signal:controller.signal,
      credentials:'omit',
      redirect:'error',
      cache:'no-store',
      referrerPolicy:'no-referrer',
    });
    if(performance.now()>=deadline)expire();
    const maximum=response.status>=200&&response.status<300?RESPONSE_BYTES:ERROR_BYTES;
    const length=response.headers.get('content-length');
    if(response.redirected||response.type==='opaque'||response.type==='opaqueredirect'
      ||response.headers.get('content-type')?.split(';',1)[0].trim().toLowerCase()!=='application/json'
      ||response.headers.has('content-encoding')
      ||!response.headers.get('cache-control')?.split(',').some(v=>v.trim().toLowerCase()==='no-store')
      ||length!==null&&(!/^(?:0|[1-9][0-9]*)$/.test(length)||Number(length)>maximum)){
      throw new WorkspaceApiError(502);
    }
    const text=await response.text();
    if(text.length>maximum)throw new WorkspaceApiError(502);
    let value:unknown;
    try{value=JSON.parse(text);}catch{throw new WorkspaceApiError(502);}
    if(hasNoteText(value))throw new WorkspaceApiError(502,'copy_to_ehr_remote_payload_rejected');
    if(response.status>=200&&response.status<300){
      if(!validate(value))throw new WorkspaceApiError(502);
      return value;
    }
    const detail=value&&typeof value==='object'&&'detail' in value?(value as {detail:unknown}).detail:undefined;
    if(typeof detail==='string'&&errorCodes[response.status]?.includes(detail))throw new WorkspaceApiError(response.status,detail);
    throw new WorkspaceApiError(response.status);
  }catch(error){
    if(interruption)throw interruption;
    if(error instanceof WorkspaceApiError)throw error;
    throw new WorkspaceApiError(503,'copy_to_ehr_remote_unavailable');
  }finally{
    clearTimeout(timer);
  }
}

export const copyToEhrRemoteApi={
  create(identity:AuthenticatedWorkspaceIdentity,body:CreateCopyToEhrRemoteSession,signal?:AbortSignal){
    return call(identity,'/api/copy-to-ehr/sessions',{method:'POST',body:JSON.stringify(body)},validCopyToEhrRemoteSession,signal);
  },
  current(identity:AuthenticatedWorkspaceIdentity,signal?:AbortSignal){
    return call(identity,'/api/copy-to-ehr/sessions/current',{method:'GET'},validCopyToEhrRemoteSession,signal);
  },
  highlight(identity:AuthenticatedWorkspaceIdentity,sessionId:string,body:{draft_revision:number;section_key:string},signal?:AbortSignal){
    return call(identity,`/api/copy-to-ehr/sessions/${sessionId}/highlight`,{method:'POST',body:JSON.stringify(body)},validCopyToEhrRemoteHighlight,signal);
  },
  events(identity:AuthenticatedWorkspaceIdentity,sessionId:string,after:number,signal?:AbortSignal){
    return call(identity,`/api/copy-to-ehr/sessions/${sessionId}/events?after=${after}`,{method:'GET'},validCopyToEhrRemoteEvents,signal);
  },
  end(identity:AuthenticatedWorkspaceIdentity,sessionId:string,reason:'end'|'logout'|'visit_change'='end',signal?:AbortSignal){
    return call(identity,`/api/copy-to-ehr/sessions/${sessionId}/end`,{method:'POST',body:JSON.stringify({reason})},validCopyToEhrRemoteSession,signal);
  },
};
