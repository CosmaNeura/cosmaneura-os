import {teamClosed,teamText,teamUuid} from './team-setup-request';
export type NotebookRename={title:string;expected_title_revision:number;idempotency_key:string};
export type NotebookTitleReceipt={contract_version:1;workspace_id:string;title:string;title_revision:number;receipt_id:string};
export type NotebookTitleResolution={contract_version:1;outcome:'saved'|'not_found';receipt:NotebookTitleReceipt|null};
export type NotebookSummary={workspace_id:string;title:string;title_revision:number;revision:number;created_at:string;updated_at:string;
  link_state:'unlinked'|'linked';appointment_id:string|null;patient_label:string|null;visit_at:string|null;
  note_state:'draft'|'needs_review'|'reviewed';duration_seconds:number|null;recording_state:'none'|'finished'|'interrupted'|'unknown'};
export type NotebookSummaries={contract_version:2;drafts:NotebookSummary[];has_more:boolean};
const date=(v:unknown)=>typeof v==='string'&&Number.isFinite(Date.parse(v));
const integer=(v:unknown,min:number)=>Number.isSafeInteger(v)&&(v as number)>=min;
export const validNotebookRename=(v:unknown):v is NotebookRename=>teamClosed(v,'title,expected_title_revision,idempotency_key')&&
  teamText(v.title,160,1)&&v.title===v.title.trim()&&integer(v.expected_title_revision,0)&&typeof v.idempotency_key==='string'&&/^[A-Za-z0-9:_-]{8,100}$/.test(v.idempotency_key);
export const validTitleReceipt=(v:unknown):v is NotebookTitleReceipt=>teamClosed(v,'contract_version,workspace_id,title,title_revision,receipt_id')&&
  v.contract_version===1&&teamUuid(v.workspace_id)&&teamText(v.title,160,1)&&integer(v.title_revision,1)&&teamUuid(v.receipt_id);
export const validTitleResolution=(v:unknown):v is NotebookTitleResolution=>teamClosed(v,'contract_version,outcome,receipt')&&v.contract_version===1&&
  (v.outcome==='not_found'?v.receipt===null:v.outcome==='saved'&&validTitleReceipt(v.receipt));
export const validNotebookSummaries=(v:unknown):v is NotebookSummaries=>teamClosed(v,'contract_version,drafts,has_more')&&v.contract_version===2&&typeof v.has_more==='boolean'&&
  Array.isArray(v.drafts)&&v.drafts.length<=50&&new Set(v.drafts.map(row=>row.workspace_id)).size===v.drafts.length&&v.drafts.every(row=>
    teamClosed(row,'workspace_id,title,title_revision,revision,created_at,updated_at,link_state,appointment_id,patient_label,visit_at,note_state,duration_seconds,recording_state')&&
    teamUuid(row.workspace_id)&&teamText(row.title,160,1)&&integer(row.title_revision,0)&&integer(row.revision,1)&&date(row.created_at)&&date(row.updated_at)&&
    (row.link_state==='unlinked'?row.appointment_id===null&&row.patient_label===null&&row.visit_at===null:
      row.link_state==='linked'&&teamUuid(row.appointment_id)&&(row.patient_label===null||teamText(row.patient_label,200,1))&&(row.visit_at===null||date(row.visit_at)))&&
    typeof row.note_state==='string'&&['draft','needs_review','reviewed'].includes(row.note_state)&&typeof row.recording_state==='string'&&['none','finished','interrupted','unknown'].includes(row.recording_state)&&
    (row.duration_seconds===null||typeof row.duration_seconds==='number'&&Number.isFinite(row.duration_seconds)&&row.duration_seconds>0&&row.duration_seconds<=7200));
export type NotebookTitleRecovery={contract:'notebook-title-recovery.v1';workspace_id:string;pending:NotebookRename};
export function validateTitleRecovery(v:unknown,wid:string):NotebookTitleRecovery{
  if(!teamClosed(v,'contract,workspace_id,pending')||v.contract!=='notebook-title-recovery.v1'||v.workspace_id!==wid||!teamUuid(wid)||!validNotebookRename(v.pending))throw new Error('Invalid notebook title recovery');
  return v as NotebookTitleRecovery;
}
