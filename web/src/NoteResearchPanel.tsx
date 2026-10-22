import {useEffect,useRef,useState} from 'react';
import type {AuthenticatedWorkspaceIdentity,Workspace} from './workspace-api';
import {WorkspaceMarkdown} from './WorkspaceMarkdown';
import {noteResearchProofKey,noteResearchQuestionSelection,noteResearchSelectionMatches,verifyNoteResearchPlan,
  type NoteResearchPlan,type NoteResearchSelection} from './note-research-workflow';

function currentIdentity(identity:AuthenticatedWorkspaceIdentity):boolean {
  return identity.mode==='desktop_native'?identity.isCurrent():identity.nativeSession?.isCurrent()??true;
}
export function useNoteResearchPlan(workspace:Workspace|undefined,bot:string,identity:AuthenticatedWorkspaceIdentity):NoteResearchPlan|null {
  const owner=useRef({identity,workspace});
  const sameOwner=owner.current.identity===identity||owner.current.workspace!==workspace;
  if(sameOwner)owner.current={identity,workspace};
  const signature=workspace?noteResearchProofKey(workspace,bot):'',
    [proof,setProof]=useState<{identity:AuthenticatedWorkspaceIdentity;signature:string;plan:NoteResearchPlan|null}|null>(null);
  useEffect(()=>{
    let cancelled=false;
    if(sameOwner&&workspace&&currentIdentity(identity))void verifyNoteResearchPlan(workspace,bot).then(plan=>{
      if(!cancelled&&currentIdentity(identity))setProof({identity,signature,plan});
    }).catch(()=>{if(!cancelled)setProof({identity,signature,plan:null});});
    return()=>{cancelled=true;};
  },[identity,signature,bot,sameOwner]);
  return sameOwner&&currentIdentity(identity)&&proof?.identity===identity&&proof.signature===signature?proof.plan:null;
}

export function NoteResearchPanel({plan,selection,locked,onChoose}:{plan:NoteResearchPlan;
  selection?:NoteResearchSelection;locked:boolean;onChoose:(selection:NoteResearchSelection,proposedQuery:string|null)=>void}) {
  return <section className="note-research-plan" aria-label="Research from saved note">
    <h3>Questions from your saved note</h3>
    <p>Saved note · version {plan.selection.note_version}. These are the private Research assessment’s questions for provider review.</p>
    <details><summary>Source-supported findings</summary><WorkspaceMarkdown content={plan.findings}/></details>
    {plan.directions&&<details><summary>Chief directions used for this assessment</summary><p style={{whiteSpace:'pre-wrap'}}>{plan.directions}</p></details>}
    <ol>{plan.questions.map((question,index)=>{
      const selected=noteResearchQuestionSelection(plan,index)!;
      return <li key={index}><WorkspaceMarkdown content={question.content}/>
        <button type="button" disabled={locked} aria-pressed={noteResearchSelectionMatches(plan,selection)&&selection?.question_index===index}
          onClick={()=>onChoose(selected,question.proposedQuery)}>{question.proposedQuery?'Prepare proposed public query':'Write a public query for this question'}</button>
      </li>;
    })}</ol>
    <p className="team-fine">Choosing a question prepares the editor only. A proposed query has not been checked for privacy. Edit it to remove patient details, then review its wording and selected sources before any public lookup.</p>
    <details><summary>Missing evidence and next checks</summary><WorkspaceMarkdown content={plan.nextChecks}/></details>
    <details><summary>Exact saved-source provenance</summary><p>Note version {plan.selection.note_version} · shared source revision {plan.selection.source_entry_revision} · Chief request revision {plan.selection.chief_entry_revision}</p>
      <p>Note fingerprint <code>{plan.selection.content_hash}</code></p><p>Source fingerprint <code>{plan.selection.source_fingerprint}</code></p>
      <p>Assessment fingerprint <code>{plan.selection.result_sha256}</code></p></details>
  </section>;
}
