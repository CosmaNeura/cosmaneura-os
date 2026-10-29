import {HandoffCard} from './HandoffCard';
import type {DraftHandoff,WorkspaceEntry} from './workspace-api';
import './team-work.css';

export function TeamWorkPanel({handoffs,entries,locked,onRetry,onReview}:{
  handoffs:DraftHandoff[];entries:WorkspaceEntry[];locked:boolean;
  onRetry:(handoff:DraftHandoff)=>void;onReview:(handoff:DraftHandoff)=>void;
}) {
  if(!handoffs.length)return null;
  const active=(handoff:DraftHandoff)=>handoff.status==='queued'||handoff.status==='running';
  const recent=[...handoffs].reverse(),working=handoffs.filter(active).length;
  const visible=recent.filter((handoff,index)=>index<3||active(handoff));
  const earlier=recent.filter((handoff,index)=>index>=3&&!active(handoff));
  const ready=handoffs.filter(h=>h.status==='completed').length,attention=handoffs.filter(h=>['failed','interrupted'].includes(h.status)).length;
  const card=(handoff:DraftHandoff)=><HandoffCard key={handoff.id} handoff={handoff} locked={locked}
    resultAvailable={entries.some(entry=>entry.id===handoff.result_entry_id&&entry.kind==='handoff_result'&&entry.reply&&
      (entry.reply.agent_id?entry.reply.agent_id===handoff.recipient_agent_id:entry.reply.role===handoff.recipient_role))}
    maskedResultAvailable={entries.some(entry=>entry.id===handoff.result_entry_id&&entry.kind==='handoff_result'&&entry.content===''&&entry.reply==null&&
      [entry.google_source_state,entry.microsoft_source_state,entry.calendar_source_state,entry.fax_source_state,entry.practice_fax_source_state,entry.ehr_source_state,entry.calendar_import_source_state].includes('unavailable'))}
    onRetry={()=>onRetry(handoff)} onShow={()=>onReview(handoff)}/>;
  return <section className="team-work-overview" aria-label="Team work for this visit">
    <header><div><h2>Team work</h2><p>{working} working or queued · {ready} drafts saved{attention?` · ${attention} need attention`:''}</p></div>
      <span className="team-pill">For your review</span></header>
    <div className="team-task-grid">{visible.map(card)}</div>
    {earlier.length>0&&<details className="team-earlier-tasks"><summary>Earlier assignments ({earlier.length})</summary><div className="team-task-grid">{earlier.map(card)}</div></details>}
  </section>;
}
