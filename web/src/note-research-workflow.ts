import type {Workspace} from './workspace-api';
import {currentSharedNote, parseClinicalTeamRequest, verifySharedClinicalNote} from './clinical-team-contract';
import {clinicalDraftEntry, clinicalDraftLineage, clinicalDraftSections} from './clinical-team-workflow';
import {vendorSha256} from './vendor-contract';
import {teamClosed, teamHash, teamNatural, teamUuid} from './team-setup-request';

/** Local provenance only. None of these identifiers or private words enter a public query. */
export type NoteResearchSelection = {
  contract:'research-note-question.v1'; workspace_id:string; note_id:string; note_version:number;
  content_hash:string; source_fingerprint:string; source_entry_id:string; source_entry_revision:number;
  chief_entry_id:string; chief_entry_revision:number; handoff_id:string; result_entry_id:string;
  result_sha256:string; question_index:number;
};
export type NoteResearchQuestion={content:string;proposedQuery:string|null};
export type NoteResearchPlan={selection:Omit<NoteResearchSelection,'question_index'>;
  directions:string;findings:string;questions:NoteResearchQuestion[];nextChecks:string};

export function validNoteResearchSelection(value:unknown):value is NoteResearchSelection {
  return teamClosed(value,'contract,workspace_id,note_id,note_version,content_hash,source_fingerprint,source_entry_id,source_entry_revision,chief_entry_id,chief_entry_revision,handoff_id,result_entry_id,result_sha256,question_index')&&
    value.contract==='research-note-question.v1'&&
    ['workspace_id','note_id','source_entry_id','chief_entry_id','handoff_id','result_entry_id'].every(key=>teamUuid(value[key]))&&
    ['content_hash','source_fingerprint','result_sha256'].every(key=>teamHash(value[key]))&&
    teamNatural(value.note_version)&&value.note_version>=1&&value.note_version<=50&&
    ['source_entry_revision','chief_entry_revision'].every(key=>teamNatural(value[key])&&(value[key] as number)>=1&&(value[key] as number)<=500)&&
    teamNatural(value.question_index)&&value.question_index<=11;
}

function candidate(workspace:Workspace,bot:string) {
  const shared=currentSharedNote(workspace);
  if(!shared)return null;
  const chief=[...workspace.entries].reverse().find(entry=>{
    const request=parseClinicalTeamRequest(entry.content);
    return entry.kind==='conversation'&&(entry.reply?.role==='chief'||entry.model_request?.bot.role==='chief')&&!!request&&
      request.source_entry_id===shared.entry.id&&request.note_id===shared.snapshot.note.id&&
      request.note_version===shared.snapshot.note.version&&request.content_hash===shared.snapshot.note.content_hash;
  });
  if(!chief)return null;
  const handoff=clinicalDraftLineage(workspace,chief.id,'research').at(-1);
  if(!handoff||handoff.review_status==='stale'||handoff.task_brief_unavailable||!handoff.task_brief||
    handoff.recipient_agent_id!==bot||handoff.recipient_key!==undefined&&handoff.recipient_key!==bot)return null;
  const entry=clinicalDraftEntry(workspace,handoff);
  if(!entry?.reply||entry.reply.agent_id!==bot||!teamHash(handoff.result_sha256))return null;
  const sections=clinicalDraftSections('research',entry.reply.content);
  return sections?{shared,chief,handoff,entry,sections}:null;
}

/** Synchronous render fence, including changed bytes before passive effects run. */
export function noteResearchProofKey(workspace:Workspace,bot:string):string {
  const value=candidate(workspace,bot);
  return JSON.stringify([workspace.id,workspace.note?.latest,value]);
}

function questions(content:string):NoteResearchQuestion[]|null {
  const chunks:string[]=[];
  for(const line of content.split('\n')) {
    if(/^\s*(?:[-*]|\d+[.)])\s+/.test(line)||!chunks.length)chunks.push(line);
    else chunks[chunks.length-1]+='\n'+line;
  }
  const values=chunks.map(chunk=>chunk.trim()).filter(Boolean);
  if(!values.length||values.length>12)return null;
  return values.map(content=>{
    const proposals=content.split('\n').flatMap(line=>{
      const match=line.replace(/\*\*/g,'').match(/^\s*(?:General public query|Proposed general public query|Proposed public query|Public query)\s*:\s*(.+?)\s*$/i);
      return match&&match[1].length<=500&&!/[\u0000-\u001f\u007f]/.test(match[1])?[match[1]]:[];
    });
    return {content,proposedQuery:proposals.length===1?proposals[0]:null};
  });
}

/** Verify the exact note snapshot, assignment source version and saved draft before displaying it. */
export async function verifyNoteResearchPlan(workspace:Workspace,bot:string):Promise<NoteResearchPlan|null> {
  const value=candidate(workspace,bot);
  if(!value)return null;
  const {shared,chief,handoff,entry,sections}=structuredClone(value);
  const snapshot=await verifySharedClinicalNote(shared.entry);
  if(!snapshot)return null;
  const sourceText=`Human-shared saved note · version ${snapshot.note.version}\nSaved private note snapshot; not clinical sign-off or a current chart read.\n\n${snapshot.note.content}`;
  const sourceHash=await vendorSha256(new TextEncoder().encode(sourceText));
  const versions=handoff.task_brief!.source_versions.filter(source=>source.entry_id===shared.entry.id);
  if(handoff.task_brief!.depends_on.entry_id!==chief.id||handoff.task_brief!.depends_on.revision!==chief.revision||
    versions.length!==1||versions[0].revision!==shared.entry.revision||versions[0].sha256!==sourceHash||
    versions[0].label!=='Human-shared saved note'||versions[0].kind!=='evidence'||
    await vendorSha256(new TextEncoder().encode(entry.reply!.content))!==handoff.result_sha256)return null;
  const request=parseClinicalTeamRequest(chief.content),items=questions(sections[1].content);
  if(!request||!items)return null;
  return {selection:{contract:'research-note-question.v1',workspace_id:workspace.id,note_id:snapshot.note.id,
    note_version:snapshot.note.version,content_hash:snapshot.note.content_hash,source_fingerprint:snapshot.note.source_fingerprint,
    source_entry_id:shared.entry.id,source_entry_revision:shared.entry.revision,chief_entry_id:chief.id,
    chief_entry_revision:chief.revision,handoff_id:handoff.id,result_entry_id:entry.id,result_sha256:handoff.result_sha256!},
    directions:request.contract==='clinical-team-drafts.request.v2'?request.owner_directions:'',
    findings:sections[0].content,questions:items,nextChecks:sections[2].content};
}

export function noteResearchQuestionSelection(plan:NoteResearchPlan,index:number):NoteResearchSelection|null {
  const value={...plan.selection,question_index:index};
  return index<plan.questions.length&&validNoteResearchSelection(value)?value:null;
}
export function noteResearchSelectionMatches(plan:NoteResearchPlan|null,selection:NoteResearchSelection|undefined):boolean {
  return !!plan&&!!selection&&JSON.stringify(noteResearchQuestionSelection(plan,selection.question_index))===JSON.stringify(selection);
}
