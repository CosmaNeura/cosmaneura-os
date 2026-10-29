import {useEffect,useState} from 'react';
import {workspaceApi,type AuthenticatedWorkspaceIdentity,type WorkspaceEncounter} from './workspace-api';
import type {NotebookSummaries} from './notebook-metadata-contract';
import './visit-catalog.css';

export const VISIT_CATALOG_VIEWS=['All','Today','Upcoming','Past','Unlinked notes'] as const;

export function VisitCatalog({identity,visits,locked,recordingActive,onOpen,onRecord,onPrivateNote,onConnections,visitsOnly=false}: {
  identity:AuthenticatedWorkspaceIdentity;visits:WorkspaceEncounter[];locked:boolean;recordingActive:boolean;visitsOnly?:boolean;
  onOpen:(appointmentId:string)=>void;onRecord?:(appointmentId:string)=>void;onPrivateNote:(workspaceId:string)=>void;onConnections:()=>void;
}){
  const [view,setView]=useState('All'),[search,setSearch]=useState(''),[notes,setNotes]=useState<NotebookSummaries|null>(null),[error,setError]=useState('');
  useEffect(()=>{if(view!=='Unlinked notes')return;let alive=true;setError('');void workspaceApi.privateDraftSummaries(identity).then(value=>{if(alive)setNotes(value);}).catch(()=>{if(alive)setError('Unlinked notes could not be loaded. Your saved notes are retained.');});return()=>{alive=false;};},[identity,view]);
  const today=new Date();today.setHours(0,0,0,0);const tomorrow=new Date(today);tomorrow.setDate(tomorrow.getDate()+1);
  const query=search.trim().toLocaleLowerCase(),filtered=visits.filter(visit=>{
    if(query&&!visit.label.toLocaleLowerCase().includes(query))return false;
    if(view==='All')return true;
    if(!visit.start_at)return false;const time=Date.parse(visit.start_at);
    return view==='Today'?time>=+today&&time<+tomorrow:view==='Upcoming'?time>=+tomorrow:view==='Past'?time<+today:false;
  });
  return <section aria-label="Available encounters" className="team-encounter-picker">
    <nav className="team-material-tabs visit-catalog-tabs" aria-label="Visit views">{(visitsOnly?VISIT_CATALOG_VIEWS.filter(label=>label!=='Unlinked notes'):VISIT_CATALOG_VIEWS).map(label=><button key={label} aria-pressed={view===label} onClick={()=>setView(label)}>{label}</button>)}</nav>
    <label className="visit-search">Search visits and notes<input type="search" value={search} onChange={event=>setSearch(event.target.value)} placeholder="Patient or title"/></label>
    {view==='Unlinked notes'?<>{notes?.drafts.filter(note=>note.link_state==='unlinked'&&(!query||note.title.toLocaleLowerCase().includes(query))).map(note=><article className="team-encounter-row" key={note.workspace_id}><button className="team-encounter-option" disabled={locked||recordingActive} onClick={()=>onPrivateNote(note.workspace_id)}><strong>{note.title}</strong><span>No patient yet · {note.note_state==='needs_review'?'Needs review':'Draft note'}</span><time dateTime={note.updated_at}>{new Date(note.updated_at).toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'})}</time><span>Open or link this note to a visit</span></button></article>)}{error&&<p role="status">{error}</p>}{notes&&!notes.drafts.some(note=>note.link_state==='unlinked')&&<p>No unlinked notes yet.</p>}</>:
      <>{filtered.map(visit=><article className="team-encounter-row" key={visit.appointment_id}><button className="team-encounter-option" disabled={locked||recordingActive} onClick={()=>onOpen(visit.appointment_id)}><strong>{visit.label}</strong><span>{visit.start_at?new Date(visit.start_at).toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'}):'Visit time not available'}{visit.source==='synthetic'?' · Synthetic visit':''}</span><span>{visit.workspace_id?'Open saved notes':'Open visit'}</span></button>
        {onRecord&&<button className="team-primary team-record-visit" disabled={locked||recordingActive} aria-label={`Record ${visit.label}`} onClick={()=>onRecord(visit.appointment_id)}>Record visit</button>}</article>)}
        {!filtered.length&&<p>{visits.length?'No visits match this view. Undated visits are available under All.':'No confirmed visits are available. You can record or write a private note from Home.'}</p>}
        <button className="team-subtle" onClick={onConnections}>Find another visit</button></>}
    {recordingActive&&<p>Recording continues while you browse. Stop and save before opening another notebook.</p>}
  </section>;
}
