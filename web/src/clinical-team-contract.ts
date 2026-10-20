import type {PrivateNote, Workspace, WorkspaceEntry} from './workspace-api';
import {modelCanonical} from './model-work-request';
import {vendorSha256} from './vendor-contract';

export const CLINICAL_NOTE_LABEL = 'Human-shared saved note';
export type ShareSavedNoteInput = {expected_revision:number;idempotency_key:string;note_id:string;
  note_version:number;content_hash:string;source_fingerprint:string;share_with_team:true};
export type SharedClinicalNote = {contract:'clinical-note-team-source.v1';request:ShareSavedNoteInput;
  note:{id:string;version:number;content_hash:string;source_fingerprint:string;content:string}};
export type ClinicalNoteShareReceipt = {contract:'clinical-note-share.v1';outcome:'saved'|'not_found';
  source_entry_id:string|null;source_entry_revision:number|null;workspace:Workspace};
const uuid=(v:unknown):v is string=>typeof v==='string'&&/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(v);
const hash=(v:unknown):v is string=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v);
const record=(v:unknown):v is Record<string,unknown>=>!!v&&typeof v==='object'&&!Array.isArray(v);
const keys=(v:unknown,names:string):v is Record<string,unknown>=>record(v)&&Object.keys(v).sort().join(',')===names.split(',').sort().join(',');
export function validShareSavedNoteInput(v:unknown):v is ShareSavedNoteInput {
  return keys(v,'expected_revision,idempotency_key,note_id,note_version,content_hash,source_fingerprint,share_with_team')&&
    Number.isSafeInteger(v.expected_revision)&&(v.expected_revision as number)>0&&uuid(v.note_id)&&
    typeof v.idempotency_key==='string'&&/^[A-Za-z0-9:_-]{8,100}$/.test(v.idempotency_key)&&
    Number.isSafeInteger(v.note_version)&&(v.note_version as number)>=1&&(v.note_version as number)<=50&&
    hash(v.content_hash)&&hash(v.source_fingerprint)&&v.share_with_team===true;
}
export function parseSharedClinicalNote(entry:WorkspaceEntry):SharedClinicalNote|null {
  if(entry.kind!=='conversation'||entry.source_label!==CLINICAL_NOTE_LABEL||entry.reply)return null;
  try {
    const v:unknown=JSON.parse(entry.content);
    if(!keys(v,'contract,request,note')||v.contract!=='clinical-note-team-source.v1'||!validShareSavedNoteInput(v.request)||
      !keys(v.note,'id,version,content_hash,source_fingerprint,content')||v.note.id!==v.request.note_id||
      v.note.version!==v.request.note_version||v.note.content_hash!==v.request.content_hash||
      v.note.source_fingerprint!==v.request.source_fingerprint||typeof v.note.content!=='string'||
      !v.note.content.trim()||Array.from(v.note.content).length>20000)return null;
    return v as SharedClinicalNote;
  }catch{return null;}
}
export async function verifySharedClinicalNote(entry:WorkspaceEntry):Promise<SharedClinicalNote|null> {
  const value=parseSharedClinicalNote(entry);
  return value&&await vendorSha256(new TextEncoder().encode(modelCanonical({content:value.note.content})))===value.note.content_hash?value:null;
}
export function noteSelection(note:PrivateNote,revision:number,key:string=crypto.randomUUID()):ShareSavedNoteInput {
  const value={expected_revision:revision,idempotency_key:key,note_id:note.id,note_version:note.version,
    content_hash:note.content_hash,source_fingerprint:note.source_fingerprint,share_with_team:true as const};
  if(!validShareSavedNoteInput(value))throw new Error('The saved note selection could not be verified.');
  return value;
}
export function clinicalNoteSnapshotSize(note:PrivateNote,revision:number):number {
  const request=noteSelection(note,revision,'00000000-0000-4000-8000-000000000000');
  return modelCanonical({contract:'clinical-note-team-source.v1',request,note:{id:note.id,version:note.version,
    content_hash:note.content_hash,source_fingerprint:note.source_fingerprint,content:note.content}}).length;
}
export function currentSharedNote(workspace:Workspace):{entry:WorkspaceEntry;snapshot:SharedClinicalNote}|null {
  const latest=workspace.note?.latest;
  if(!latest||latest.sources_changed)return null;
  for(const entry of [...workspace.entries].reverse()) {
    const snapshot=parseSharedClinicalNote(entry);
    if(snapshot&&snapshot.note.id===latest.id&&snapshot.note.version===latest.version&&
      snapshot.note.content_hash===latest.content_hash&&snapshot.note.content===latest.content&&
      snapshot.note.source_fingerprint===latest.source_fingerprint)return {entry,snapshot};
  }
  return null;
}
export function clinicalTeamRequest(source:{entry:WorkspaceEntry;snapshot:SharedClinicalNote}):string {
  return JSON.stringify({contract:'clinical-team-drafts.request.v1',source_entry_id:source.entry.id,
    note_id:source.snapshot.note.id,note_version:source.snapshot.note.version,content_hash:source.snapshot.note.content_hash});
}
export function clinicalRequestDisplay(content:string):string {
  try {
    const value:unknown=JSON.parse(content);
    if(keys(value,'contract,source_entry_id,note_id,note_version,content_hash')&&value.contract==='clinical-team-drafts.request.v1'&&
      uuid(value.source_entry_id)&&uuid(value.note_id)&&Number.isSafeInteger(value.note_version)&&(value.note_version as number)>=1&&
      (value.note_version as number)<=50&&hash(value.content_hash))
      return `Prepare a patient email draft, provider action items, and a drug and treatment assessment from shared saved note version ${value.note_version}.`;
  }catch{/* Ordinary conversation text retains its original display. */}
  return content;
}
export async function verifyClinicalNoteShareReceipt(v:unknown,workspaceId:string,body:ShareSavedNoteInput):Promise<ClinicalNoteShareReceipt> {
  if(!validShareSavedNoteInput(body)||!keys(v,'contract,outcome,source_entry_id,source_entry_revision,workspace')||
    v.contract!=='clinical-note-share.v1'||!record(v.workspace)||v.workspace.id!==workspaceId||
    !Number.isSafeInteger(v.workspace.revision)||(v.workspace.revision as number)<body.expected_revision||!Array.isArray(v.workspace.entries)||!Array.isArray(v.workspace.work_candidates))throw new Error('The note sharing receipt could not be verified.');
  const receipt=v as unknown as ClinicalNoteShareReceipt;
  if(receipt.outcome==='not_found') {
    if(receipt.source_entry_id!==null||receipt.source_entry_revision!==null)throw new Error('The note sharing receipt could not be verified.');
    return receipt;
  }
  if(receipt.outcome!=='saved'||!uuid(receipt.source_entry_id)||receipt.source_entry_revision!==body.expected_revision+1||receipt.workspace.revision<receipt.source_entry_revision)throw new Error('The note sharing receipt could not be verified.');
  const entry=receipt.workspace.entries.find(e=>e.id===receipt.source_entry_id&&e.revision===receipt.source_entry_revision);
  const snapshot=entry&&await verifySharedClinicalNote(entry);
  if(!snapshot||modelCanonical(snapshot.request)!==modelCanonical(body))throw new Error('The note sharing receipt could not be verified.');
  return receipt;
}
