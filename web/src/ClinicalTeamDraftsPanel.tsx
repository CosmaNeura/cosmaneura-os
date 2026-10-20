import {useEffect,useRef,useState} from 'react';
import type {DraftHandoff,ProviderTeam,Workspace} from './workspace-api';
import {WorkspaceMarkdown} from './WorkspaceMarkdown';
import {clinicalNoteSnapshotSize,clinicalTeamRequest,currentSharedNote,noteSelection,type ShareSavedNoteInput} from './clinical-team-contract';
import {clinicalDraftAccepted,clinicalDraftEntry,clinicalDraftLineage,clinicalDraftRetryable,clinicalDraftSections} from './clinical-team-workflow';

export type ClinicalTeamDraftsPanelProps={workspace:Workspace;team:ProviderTeam;locked:boolean;
  onShare:(body:ShareSavedNoteInput)=>Promise<void>;onAskChief:(content:string)=>Promise<void>;onReview:(handoffId:string)=>void;
  onRetry?:(handoff:DraftHandoff)=>void;onPrepare?:(body:ShareSavedNoteInput)=>Promise<void>;authority?:object};
export function ClinicalTeamDraftsPanel({workspace,team,locked,onShare,onAskChief,onReview,onRetry,onPrepare,authority}:ClinicalTeamDraftsPanelProps) {
  const [preview,setPreview]=useState(false),[checked,setChecked]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const live=useRef({workspace,authority}),inFlight=useRef<object|null>(null);live.current={workspace,authority};
  const note=workspace.note?.latest,source=currentSharedNote(workspace);
  const tooLarge=note?clinicalNoteSnapshotSize(note,workspace.revision)>20000:false;
  const linked=workspace.appointment_id!==null,historyFull=workspace.revision>=500;
  useEffect(()=>{inFlight.current=null;setBusy(false);setPreview(false);setChecked(false);setError('');},[authority,team.recovery_scope,workspace.id,note?.id,note?.version,note?.content_hash]);
  const bots=team.configuration.bots.filter(b=>b.enabled&&!b.retired&&!b.blocked_capabilities?.includes('model_answer'));
  const handoffReady=team.llm.enabled&&['chief','follow_up','research'].every(role=>bots.some(b=>b.role===role&&b.include_evidence&&!b.blocked_capabilities?.includes('private_draft_handoff')));
  const content=source?clinicalTeamRequest(source):null;
  const origin=content?[...workspace.entries].reverse().find(e=>e.kind==='conversation'&&e.content===content&&
    (e.reply?.role==='chief'||e.model_request?.bot.role==='chief')):undefined;
  const chiefWithoutAssignments=!!origin?.reply&&(!origin.model_request||origin.model_request.admission.state==='completed')&&
    !(workspace.handoffs??[]).some(h=>h.origin_entry_id===origin.id);
  async function run(action:()=>Promise<void>) {
    if(locked||busy||inFlight.current)return;
    const current=workspace,owner=authority,episode={};inFlight.current=episode;setBusy(true);setError('');
    try{await action();}catch{if(inFlight.current===episode&&live.current.workspace.id===current.id&&live.current.authority===owner)setError('This step could not be confirmed. Check the retained request before trying again.');}
    finally{if(inFlight.current===episode){inFlight.current=null;if(live.current.workspace.id===current.id&&live.current.authority===owner)setBusy(false);}}
  }
  return <section className="clinical-team-drafts" aria-label="Clinical team drafts" aria-busy={busy}>
    <h3 tabIndex={-1}>From saved note to next steps</h3>
    <p>Chief uses your shared Scribe material. Follow-up prepares a patient email draft and provider action items. Research prepares drug and treatment questions for provider review.</p>
    <ol aria-label="Team draft steps">
      <li>{note?`Saved note · version ${note.version}`:'Save your Scribe note'}</li>
      <li>{source?'Exact saved note shared':onPrepare?'Prepare both specialist drafts from this saved note':'Preview and share the exact saved note'}</li>
      <li>{origin?'Chief request saved':onPrepare?'Chief coordinates Follow-up and Research':'Ask Chief to prepare both specialist drafts'}</li>
      <li>Review the email, provider actions and treatment assessment</li>
    </ol>
    {!linked&&<p>Connect this notebook to a visit before sharing a clinical note with this team.</p>}
    {historyFull&&<p>This workspace has reached its saved-history limit. Open a new visit workspace before preparing more team drafts.</p>}
    {!note&&<p>Save a note before sharing it with this team.</p>}
    {note&&<>
      <p>Saved note · version {note.version}{note.review?' · Privately reviewed':' · Draft, awaiting review'}</p>
      {note.sources_changed&&<p role="status">Source material changed. Reconcile and save the note before starting fresh team drafts.</p>}
      {tooLarge&&<p role="status">This saved note is too large for one team snapshot. Keep this saved version and create a shorter note before sharing it.</p>}
      {onPrepare&&<>
        <div role="group" aria-label="Saved note for Follow-up and Research"><pre style={{whiteSpace:'pre-wrap'}}>{note.content}</pre></div>
        <p>Choosing Prepare Follow-up and Research shares this exact saved note, version {note.version}, with your private team and asks Chief to prepare both sets of drafts. It does not edit or sign the note, send a patient email, or run a public search.</p>
        <button type="button" className="team-primary" disabled={locked||busy||note.sources_changed||tooLarge||!linked||historyFull||!handoffReady||!!origin&&!chiefWithoutAssignments}
          onClick={()=>void run(()=>onPrepare(noteSelection(note,workspace.revision)))}>Prepare Follow-up and Research</button>
        {busy&&<p role="status">Confirming the exact saved note and preparing your private team request…</p>}
      </>}
      <details open={onPrepare?undefined:true}><summary hidden={!onPrepare}>Separate sharing and request controls</summary>
      <button type="button" disabled={locked||busy} aria-expanded={preview} onClick={()=>setPreview(v=>!v)}>Preview saved note for team</button>
      {preview&&<div role="group" aria-label="Exact saved note to share"><pre style={{whiteSpace:'pre-wrap'}}>{note.content}</pre>
        <p>The saved note text is shared with your private team. This does not edit or sign the clinical note.</p>
        {!source&&<label><input type="checkbox" checked={checked} disabled={locked||busy||note.sources_changed||tooLarge||!linked||historyFull}
          onChange={event=>setChecked(event.target.checked)}/>Share this exact saved note with my private team</label>}
      </div>}
      {!source&&<button type="button" disabled={locked||busy||!preview||!checked||note.sources_changed||tooLarge||!linked||historyFull}
        onClick={()=>void run(()=>onShare(noteSelection(note,workspace.revision)))}>Share saved note with team</button>}
      {source&&<p role="status">Saved note version {source.snapshot.note.version} is shared with this private team.</p>}
      {!handoffReady&&<p>Enable Chief, Follow-up and Research with private draft handoffs to prepare this set of drafts.</p>}
      <button type="button" disabled={locked||busy||!source||!handoffReady||!!origin&&!chiefWithoutAssignments||!linked||historyFull}
        onClick={()=>{if(content)void run(()=>onAskChief(content));}}>{chiefWithoutAssignments?'Ask Chief again for both drafts':'Ask Chief for follow-up and research drafts'}</button>
      </details>
      {origin&&!origin.reply&&<p role="status">Chief’s request is saved. Its outcome is still being checked; no second request is needed.</p>}
      {chiefWithoutAssignments&&<p role="status">Chief’s reply did not save any team assignments. You can ask again using this exact shared note.</p>}
    </>}
    {(['follow_up','research'] as const).map(role=>{
      const chain=origin?clinicalDraftLineage(workspace,origin.id,role):[],row=chain.at(-1),entry=row?clinicalDraftEntry(workspace,row):undefined;
      const sections=entry?.reply?clinicalDraftSections(role,entry.reply.content):null;
      const changes=row?.review?.decision==='changes_requested'&&row.review_status==='current';
      const label=role==='follow_up'?'Follow-up drafts':'Research assessment';
      return <article key={role} aria-label={label}><h4>{label}</h4>
        <p>{role==='follow_up'?'Patient email draft · Provider action items':'Source-supported findings · Drug and treatment questions · Missing evidence'}</p>
        {chain.length>1&&<p>Revised draft · revision {chain.length}</p>}
        <p role="status">{row?(clinicalDraftAccepted(row)&&entry?'Accepted private draft':row.review_status==='stale'?'Source changed; draft needs fresh review':changes?'Changes requested; prepare a revised draft':row.status==='completed'?entry?'Draft ready for provider review':'Saved result is not available; refresh before review':row.status==='queued'?'Draft queued':row.status==='running'?'Preparing private draft…':'Draft needs attention'):origin?.reply?'No saved assignment for this specialist':origin?'Waiting for Chief’s assignment':'Not requested'}</p>
        {row?.revision_request?.feedback&&<details><summary>Changes used for this revision</summary><p style={{whiteSpace:'pre-wrap'}}>{row.revision_request.feedback}</p></details>}
        {changes&&<p style={{whiteSpace:'pre-wrap'}}>{row.review!.feedback}</p>}
        {sections? <>
          {sections.map(section=><section key={section.label} aria-label={section.label}><h5>{section.label}</h5><WorkspaceMarkdown content={section.content}/></section>)}
          <details><summary>Complete saved draft</summary><WorkspaceMarkdown content={entry!.reply!.content}/></details>
        </>:entry?.reply&&<WorkspaceMarkdown content={entry.reply.content}/>}
        {row?.status==='completed'&&<button type="button" disabled={locked||busy||!entry} onClick={()=>onReview(row.id)}>{changes?`Continue ${role==='follow_up'?'follow-up':'research'} changes`:`Review ${role==='follow_up'?'follow-up draft':'research draft'}`}</button>}
        {row&&onRetry&&clinicalDraftRetryable(row)&&<button type="button" disabled={locked||busy} onClick={()=>onRetry(row)}>Retry {role==='follow_up'?'follow-up':'research'} draft</button>}
        {row&&['failed','interrupted'].includes(row.status)&&<p>{clinicalDraftRetryable(row)?'Your saved assignment is retained. Retry reuses its current sources and brief.':'Open Team drafts to inspect the saved assignment and resolve its source or access issue before fresh work.'}</p>}
        {chain.length>1&&<details><summary>Earlier reviewed drafts ({chain.length-1})</summary>{chain.slice(0,-1).map(previous=><div key={previous.id}><p>{previous.review?.decision==='changes_requested'?'Changes requested':'Earlier draft'}</p>
          {previous.review?.feedback&&<p style={{whiteSpace:'pre-wrap'}}>{previous.review.feedback}</p>}
          <button type="button" disabled={locked||busy||!clinicalDraftEntry(workspace,previous)} onClick={()=>onReview(previous.id)}>Open earlier {role==='follow_up'?'follow-up':'research'} review</button></div>)}</details>}
      </article>;
    })}
    <p className="team-fine">These are private drafts. Patient sending, clinical decisions and public searches require their separate reviewed controls.</p>
    {error&&<p role="alert">{error}</p>}
  </section>;
}
