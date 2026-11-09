import {workspaceApiBase} from './workspace-base';
import {workspaceFetch} from './workspace-protocol';
import {permittedWorkspaceApi} from './workspace-origin';
import {workspaceAuthHeaders,assertCurrentDesktopSession} from './workspace-auth-headers';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from './workspace-api';

/** Closed package JSON from GET /api/copy-to-ehr/drafts/{draft_id}. Profiles stay on track A. */
export type CopyToEhrSection={key:string;label:string;text:string};
export type CopyToEhrExtras={patient_instructions?:string;orders?:string};
export type CopyToEhrPackage={
  profile_id:string;
  draft_id:string;
  draft_revision:number;
  payload_hash:string;
  sections:CopyToEhrSection[];
  extras:CopyToEhrExtras;
  created_at:string;
  expires_at:string;
  review_state:string;
  full_note:string;
};

export type CopyToEhrAuditEvent=
  |'copy_to_ehr.opened'
  |'copy_to_ehr.copied'
  |'copy_to_ehr.cleared'
  |'copy_to_ehr.done'
  |'copy_to_ehr.blocked'
  |'copy_to_ehr.fallback_shown';

export type CopyToEhrAuditMetadata={
  event:CopyToEhrAuditEvent;
  profile_id:string;
  outcome:'ok'|'blocked'|'denied'|'stale'|'expired'|'unavailable';
  duration_ms:number;
  correlation_id:string;
};

const HASH=/^[a-f0-9]{64}$/u;
const ISO=/^\d{4}-\d{2}-\d{2}T.+(?:Z|[+-]\d{2}:\d{2})$/u;
const closed=(value:unknown,keys:string):value is Record<string,unknown>=>
  !!value&&typeof value==='object'&&!Array.isArray(value)&&
  Object.keys(value).sort().join(',')===keys.split(',').sort().join(',');
const text=(value:unknown,limit:number):value is string=>
  typeof value==='string'&&value.length>0&&value.length<=limit;

export function validateCopyToEhrPackage(value:unknown):CopyToEhrPackage{
  if(!closed(value,'profile_id,draft_id,draft_revision,payload_hash,sections,extras,created_at,expires_at,review_state,full_note')||
      !text(value.profile_id,64)||!text(value.draft_id,200)||
      !Number.isSafeInteger(value.draft_revision)||Number(value.draft_revision)<1||
      typeof value.payload_hash!=='string'||!HASH.test(value.payload_hash)||
      !Array.isArray(value.sections)||value.sections.length<1||value.sections.length>100||
      !text(value.created_at,64)||!ISO.test(value.created_at)||!Number.isFinite(Date.parse(value.created_at))||
      !text(value.expires_at,64)||!ISO.test(value.expires_at)||!Number.isFinite(Date.parse(value.expires_at))||
      !text(value.review_state,64)||typeof value.full_note!=='string'||value.full_note.length>1048576||
      !value.extras||typeof value.extras!=='object'||Array.isArray(value.extras)){
    throw new WorkspaceApiError(503,'copy_to_ehr_unavailable');
  }
  const extras=value.extras as Record<string,unknown>;
  for(const key of Object.keys(extras)){
    if(key!=='patient_instructions'&&key!=='orders')throw new WorkspaceApiError(503,'copy_to_ehr_unavailable');
    const item=extras[key];
    if(item!==undefined&&(typeof item!=='string'||item.length>262144))throw new WorkspaceApiError(503,'copy_to_ehr_unavailable');
  }
  const seen=new Set<string>();
  const sections:CopyToEhrSection[]=[];
  for(const row of value.sections){
    if(!closed(row,'key,label,text')||!text(row.key,200)||!text(row.label,200)||
        typeof row.text!=='string'||row.text.length>262144||seen.has(row.key)||
        row.text.startsWith('#')||row.label.startsWith('#')){
      throw new WorkspaceApiError(503,'copy_to_ehr_unavailable');
    }
    seen.add(row.key);
    sections.push({key:row.key,label:row.label,text:row.text});
  }
  if(value.full_note.split('\n').some(line=>line.startsWith('#'))){
    throw new WorkspaceApiError(503,'copy_to_ehr_unavailable');
  }
  return {
    profile_id:value.profile_id as string,
    draft_id:value.draft_id as string,
    draft_revision:value.draft_revision as number,
    payload_hash:value.payload_hash as string,
    sections,
    extras:extras as CopyToEhrExtras,
    created_at:value.created_at as string,
    expires_at:value.expires_at as string,
    review_state:value.review_state as string,
    full_note:value.full_note as string,
  };
}

/** Content-free audit only. Callers must never pass note text, labels, chart URLs, or titles. */
export function validateCopyToEhrAuditMetadata(value:unknown):CopyToEhrAuditMetadata{
  const events:CopyToEhrAuditEvent[]=[
    'copy_to_ehr.opened','copy_to_ehr.copied','copy_to_ehr.cleared','copy_to_ehr.done',
    'copy_to_ehr.blocked','copy_to_ehr.fallback_shown',
  ];
  const outcomes=['ok','blocked','denied','stale','expired','unavailable'] as const;
  if(!closed(value,'event,profile_id,outcome,duration_ms,correlation_id')||
      !events.includes(value.event as CopyToEhrAuditEvent)||
      !text(value.profile_id,64)||!outcomes.includes(value.outcome as typeof outcomes[number])||
      !Number.isSafeInteger(value.duration_ms)||Number(value.duration_ms)<0||Number(value.duration_ms)>3_600_000||
      typeof value.correlation_id!=='string'||!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value.correlation_id)){
    throw new WorkspaceApiError(422,'copy_to_ehr_audit_invalid');
  }
  return value as CopyToEhrAuditMetadata;
}

export async function fetchCopyToEhrPackage(
  identity:AuthenticatedWorkspaceIdentity,
  draftId:string,
  profileId='atlas_md',
  revision?:number,
  signal?:AbortSignal,
):Promise<CopyToEhrPackage>{
  if(!text(draftId,200)||!text(profileId,64)||revision!==undefined&&(!Number.isSafeInteger(revision)||revision<1)){
    throw new WorkspaceApiError(422,'copy_to_ehr_request_invalid');
  }
  const controller=new AbortController();
  const abort=()=>controller.abort();
  const timer=setTimeout(abort,20_000);
  signal?.addEventListener('abort',abort,{once:true});
  if(signal?.aborted)abort();
  try{
    const base=workspaceApiBase(identity);
    if(!permittedWorkspaceApi(base,import.meta.env.VITE_DESKTOP_SYNTHETIC_ENABLED==='true',window.location.href)){
      throw new WorkspaceApiError(503,'copy_to_ehr_unavailable');
    }
    const query=new URLSearchParams({profile:profileId});
    if(revision!==undefined)query.set('revision',String(revision));
    const headers=await workspaceAuthHeaders(identity,base);
    assertCurrentDesktopSession(identity);
    const response=await workspaceFetch(identity,`${base}/api/copy-to-ehr/drafts/${encodeURIComponent(draftId)}?${query}`,{
      method:'GET',cache:'no-store',credentials:'omit',redirect:'error',referrerPolicy:'no-referrer',
      headers,signal:controller.signal,
    });
    assertCurrentDesktopSession(identity);
    if(response.status===404)throw new WorkspaceApiError(404,'copy_to_ehr_unavailable');
    if(response.status===409)throw new WorkspaceApiError(409,'copy_to_ehr_revision_mismatch');
    if(!response.ok)throw new WorkspaceApiError(response.status,'copy_to_ehr_unavailable');
    const value:unknown=await response.json();
    return validateCopyToEhrPackage(value);
  }catch(cause){
    if(cause instanceof WorkspaceApiError)throw cause;
    throw new WorkspaceApiError(503,'copy_to_ehr_unavailable');
  }finally{
    clearTimeout(timer);
    signal?.removeEventListener('abort',abort);
    controller.abort();
  }
}

export const CLIPBOARD_CLEAR_TEXT=' ';
