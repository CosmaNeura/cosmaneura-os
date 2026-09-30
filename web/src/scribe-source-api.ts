import {BffResponseError} from '../../clients/capture/src/bff/http-client';
import {MAX_CREATOR_REVIEW_BYTES} from '../../clients/capture/src/bff/transcript-limits';
import {parseCreatorReview,type CreatorReviewView} from '../../clients/scribe-review/creator-review-api';
import {request} from './capture-api';
import {validScribeSourceRequest as validSourceWireRequest} from '../../clients/desktop/scribe-source-requests.mjs';
import {assertCurrentDesktopSession} from './workspace-auth-headers';
import {MODEL_WORKSPACE_BYTES,validModelWorkspace} from './model-work-request';
import type {AuthenticatedWorkspaceIdentity,Workspace} from './workspace-api';

export type ScribeSourceSelection={version:1;session_id:string;source_transcript_version:number;
  working_transcript_id:string;working_transcript_version:number;snapshot_sha256:string};
export type ExistingScribeSource={contract_version:1;workspace_id:string;status:'available'|'not_prepared';
  review:CreatorReviewView|null;selection:ScribeSourceSelection|null};
export type ScribeSourceRequest={idempotency_key:string;expected_revision:number;selection:ScribeSourceSelection;reviewed:true;share_with_team:true};
export type ScribeSourcePacket={entry_id:string;entry_revision:number;entries:{entry_id:string;entry_revision:number;content_sha256:string}[];
  snapshot_sha256:string;workspace:Workspace};
const uuid=(value:unknown):value is string=>typeof value==='string'&&/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(value);
const positive=(value:unknown)=>Number.isSafeInteger(value)&&Number(value)>0;
const hash=(value:unknown):value is string=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
const object=(value:unknown):value is Record<string,unknown>=>!!value&&typeof value==='object'&&!Array.isArray(value);
const closed=(value:unknown,keys:string):value is Record<string,unknown>=>object(value)&&Object.keys(value).sort().join(',')===keys.split(',').sort().join(',');
function invalid():never{throw new BffResponseError(503,'scribe_source_receipt_invalid',null);}
async function sha256(value:string):Promise<string>{
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(value)))].map(byte=>byte.toString(16).padStart(2,'0')).join('');
}
export function validScribeSourceSelection(value:unknown):value is ScribeSourceSelection{
  return validSourceWireRequest('source-packets',{idempotency_key:'selection-check',expected_revision:1,selection:value,reviewed:true,share_with_team:true});
}
export function validScribeSourceRequest(value:unknown):value is ScribeSourceRequest{
  return validSourceWireRequest('source-packets',value)&&object(value)&&uuid(value.idempotency_key);
}
export async function parseExistingScribeSource(value:unknown,workspaceId:string):Promise<ExistingScribeSource>{
  if(!closed(value,'contract_version,workspace_id,status,review,selection')||value.contract_version!==1||value.workspace_id!==workspaceId)invalid();
  if(value.status==='not_prepared'){
    if(value.review!==null||value.selection!==null)invalid();
  }else if(value.status==='available'&&object(value.review)&&uuid(value.review.session_id)){
    let view:CreatorReviewView;
    try{view=parseCreatorReview(value.review,value.review.session_id);}catch{invalid();}
    const ready=view.status==='transcript_ready'&&view.working?.note_ready===true;
    if(ready){
      if(!validScribeSourceSelection(value.selection)||value.selection.session_id!==view.session_id||
        value.selection.source_transcript_version!==view.source?.source_transcript_version||
        value.selection.working_transcript_id!==view.working?.working_transcript_id||
        value.selection.working_transcript_version!==view.working?.working_transcript_version)invalid();
    }else if(value.selection!==null)invalid();
  }else invalid();
  return value as ExistingScribeSource;
}
export async function parseScribeSourcePacket(value:unknown,workspaceId:string,body:ScribeSourceRequest):Promise<ScribeSourcePacket>{
  if(!closed(value,'entry_id,entry_revision,entries,snapshot_sha256,workspace')||value.snapshot_sha256!==body.selection.snapshot_sha256||
    !uuid(value.entry_id)||!positive(value.entry_revision)||!Array.isArray(value.entries)||value.entries.length<1||value.entries.length>12||
    !await validModelWorkspace(value.workspace,workspaceId))invalid();
  const workspace=value.workspace as Workspace;
  if(workspace.revision!==value.entry_revision||value.entry_revision!==body.expected_revision+value.entries.length)invalid();
  const ids=new Set<string>();
  let characters=0;
  for(const [index,part] of value.entries.entries()){
    if(!closed(part,'entry_id,entry_revision,content_sha256')||!uuid(part.entry_id)||ids.has(part.entry_id)||!hash(part.content_sha256)||
      part.entry_revision!==body.expected_revision+index+1||index===0&&part.entry_id!==value.entry_id)invalid();
    ids.add(part.entry_id);
    const entry=workspace.entries.find(item=>item.id===part.entry_id);
    if(!entry||entry.kind!=='evidence'||entry.revision!==part.entry_revision||typeof entry.content!=='string'||
      [...entry.content].length>5000||await sha256(entry.content)!==part.content_sha256)invalid();
    characters+=[...entry.content].length;if(characters>30000)invalid();
  }
  return value as ScribeSourcePacket;
}
export async function readExistingScribeSource(workspaceId:string,identity:AuthenticatedWorkspaceIdentity,signal?:AbortSignal):Promise<ExistingScribeSource>{
  const result=await parseExistingScribeSource(await request(workspaceId,'existing',identity,{idempotency_key:crypto.randomUUID()},signal,MAX_CREATOR_REVIEW_BYTES+4096),workspaceId);
  checkCurrent(identity,signal);return result;
}
export async function saveScribeSourcePacket(workspaceId:string,identity:AuthenticatedWorkspaceIdentity,body:ScribeSourceRequest,signal?:AbortSignal):Promise<ScribeSourcePacket>{
  if(!validScribeSourceRequest(body))invalid();
  const result=await parseScribeSourcePacket(await request(workspaceId,'source-packets',identity,body,signal,MODEL_WORKSPACE_BYTES+8192),workspaceId,body);
  checkCurrent(identity,signal);return result;
}
function checkCurrent(identity:AuthenticatedWorkspaceIdentity,signal?:AbortSignal){
  if(signal?.aborted)throw new BffResponseError(503,'capture_request_unconfirmed',null);
  try{assertCurrentDesktopSession(identity);if(identity.mode!=='desktop_native'&&identity.nativeSession&&!identity.nativeSession.isCurrent())throw new Error();}
  catch{throw new BffResponseError(401,'capture_access_unavailable',null);}
}
