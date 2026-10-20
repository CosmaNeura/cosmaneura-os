import {useEffect,useRef,useState} from 'react';
import type {ProviderTeam,Workspace} from './workspace-api';
import {WorkspaceMarkdown} from './WorkspaceMarkdown';
import {clinicalNoteSnapshotSize,clinicalTeamRequest,currentSharedNote,noteSelection,type ShareSavedNoteInput} from './clinical-team-contract';

export type ClinicalTeamDraftsPanelProps={workspace:Workspace;team:ProviderTeam;locked:boolean;
  onShare:(body:ShareSavedNoteInput)=>Promise<void>;onAskChief:(content:string)=>Promise<void>;onReview:(handoffId:string)=>void};
export function ClinicalTeamDraftsPanel({workspace,team,locked,onShare,onAskChief,onReview}:ClinicalTeamDraftsPanelProps) {
  const [preview,setPreview]=useState(false),[checked,setChecked]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const live=useRef(workspace),inFlight=useRef(false);live.current=workspace;
  const note=workspace.note?.latest,source=currentSharedNote(workspace);
  const tooLarge=note?clinicalNoteSnapshotSize(note,workspace.revision)>20000:false;
  const linked=workspace.appointment_id!==null,historyFull=workspace.revision>=500;
  useEffect(()=>{setPreview(false);setChecked(false);setError('');},[workspace.id,note?.id,note?.version,note?.content_hash]);
  const bots=team.configuration.bots.filter(b=>b.enabled&&!b.retired&&!b.blocked_capabilities?.includes('model_answer'));
  const handoffReady=team.llm.enabled&&['chief','follow_up','research'].every(role=>bots.some(b=>b.role===role&&b.include_evidence&&!b.blocked_capabilities?.includes('private_draft_handoff')));
  const content=source?clinicalTeamRequest(source):null;
  const origin=content?[...workspace.entries].reverse().find(e=>e.kind==='conversation'&&e.content===content&&e.reply):undefined;
  const rows=origin?(workspace.handoffs??[]).filter(h=>h.origin_entry_id===origin.id):[];
  async function run(action:()=>Promise<void>) {
    if(locked||busy||inFlight.current)return;
    const current=workspace;inFlight.current=true;setBusy(true);setError('');
    try{await action();}catch{if(live.current.id===current.id)setError('This step could not be confirmed. Check the retained request before trying again.');}
    finally{inFlight.current=false;if(live.current.id===current.id)setBusy(false);}
  }
  return <section className="clinical-team-drafts" aria-label="Clinical team drafts" aria-busy={busy}>
    <h3>From saved note to next steps</h3>
    <p>Chief uses your shared Scribe material. Follow-up prepares a patient email draft and provider action items. Research prepares drug and treatment questions for provider review.</p>
    {!linked&&<p>Connect this notebook to a visit before sharing a clinical note with this team.</p>}
    {historyFull&&<p>This workspace has reached its saved-history limit. Open a new visit workspace before preparing more team drafts.</p>}
    {!note&&<p>Save a note before sharing it with this team.</p>}
    {note&&<>
      <p>Saved note · version {note.version}{note.review?' · Privately reviewed':' · Draft, awaiting review'}</p>
      {note.sources_changed&&<p role="status">Source material changed. Reconcile and save the note before starting fresh team drafts.</p>}
      {tooLarge&&<p role="status">This saved note is too large for one team snapshot. Keep this saved version and create a shorter note before sharing it.</p>}
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
      <button type="button" disabled={locked||busy||!source||!handoffReady||!!origin||!linked||historyFull}
        onClick={()=>{if(content)void run(()=>onAskChief(content));}}>Ask Chief for follow-up and research drafts</button>
    </>}
    {(['follow_up','research'] as const).map(role=>{
      const row=rows.find(h=>h.recipient_role===role),entry=row?.result_entry_id?workspace.entries.find(e=>e.id===row.result_entry_id):undefined;
      const label=role==='follow_up'?'Follow-up drafts':'Research assessment';
      return <article key={role} aria-label={label}><h4>{label}</h4>
        <p>{role==='follow_up'?'Patient email draft · Provider action items':'Source-supported findings · Drug and treatment questions · Missing evidence'}</p>
        <p role="status">{row?(row.review?.decision==='accepted'&&row.review_status==='current'?'Accepted private draft':row.review_status==='stale'?'Source changed; draft needs fresh review':row.status==='completed'?'Draft ready for provider review':row.status==='queued'?'Draft queued':row.status==='running'?'Preparing private draft…':'Draft needs attention'):'Not requested'}</p>
        {entry?.reply&&<WorkspaceMarkdown content={entry.reply.content}/>}
        {row?.status==='completed'&&<button type="button" disabled={locked||busy} onClick={()=>onReview(row.id)}>Review {role==='follow_up'?'follow-up draft':'research draft'}</button>}
      </article>;
    })}
    <p className="team-fine">These are private drafts. Patient sending, clinical decisions and public searches require their separate reviewed controls.</p>
    {error&&<p role="alert">{error}</p>}
  </section>;
}
