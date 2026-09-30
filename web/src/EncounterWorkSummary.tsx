import {useEffect, useMemo, useRef, useState} from 'react';
import {workspaceApi, WorkspaceApiError, type Workspace, type WorkspaceIdentity, type PracticeWorkItem} from './workspace-api';

/** Read only work already linked to this encounter; never infer assignment from a bot draft. */
export function EncounterWorkSummary({workspace,identity,locked,onReview,onPracticeWork,onAccessLost}:{
  workspace:Workspace;identity?:WorkspaceIdentity;locked:boolean;onReview:()=>void;onPracticeWork:()=>void;onAccessLost:(error:WorkspaceApiError)=>void;
}) {
  const ids=JSON.stringify([...new Set([...(workspace.follow_ups??[]).map(item=>item.ticket_id),
    ...workspace.entries.flatMap(entry=>entry.ticket?[entry.ticket.id]:[])])]);
  const scope=useMemo(()=>Symbol(),[identity,workspace.id,workspace.revision,ids]);
  const [state,setState]=useState<{scope:symbol;rows:Record<string,PracticeWorkItem|null>}>({scope,rows:{}});
  const denied=useRef(onAccessLost);denied.current=onAccessLost;
  const tickets=JSON.parse(ids) as string[];
  const rows=state.scope===scope?state.rows:{};
  useEffect(()=>{
    if(!identity)return;
    let current=true;const controllers:AbortController[]=[];
    for(const id of (JSON.parse(ids) as string[]).slice(0,20)){
      const controller=new AbortController();controllers.push(controller);
      const timer=setTimeout(()=>controller.abort(),15000);
      void workspaceApi.practiceWorkItem(identity,id,controller.signal).then(item=>{
        if(item.ticket_id!==id||typeof item.body!=='string'||typeof item.state!=='string'||typeof item.due_date!=='string'||typeof item.responsible?.name!=='string'||!item.responsible.name.trim()||typeof item.responsible.available!=='boolean'||item.pending_offer&&typeof item.pending_offer.to?.name!=='string')throw new WorkspaceApiError(502);
        if(current)setState(previous=>({scope,rows:{...(previous.scope===scope?previous.rows:{}),[id]:item}}));
      }).catch(error=>{
        if(!current)return;
        setState(previous=>({scope,rows:{...(previous.scope===scope?previous.rows:{}),[id]:null}}));
        if(error instanceof WorkspaceApiError&&[401,403].includes(error.status))denied.current(error);
      }).finally(()=>clearTimeout(timer));
    }
    return()=>{current=false;controllers.forEach(controller=>controller.abort());};
  },[scope,identity,ids]);
  const reviewed=workspace.note?.latest?.review&&!workspace.note.latest.sources_changed;
  return <section className="team-human-work" aria-label="Human follow-up responsibility">
    <div className="team-notebook-title"><h2>Human follow-up</h2><span className="team-pill">{tickets.length?`${tickets.length} linked`:'No linked assignment'}</span></div>
    {!tickets.length?<><p><strong>{workspace.follow_ups===undefined?"Assignment information unavailable.":"Unassigned in this notebook."}</strong> {workspace.follow_ups===undefined?"Open Practice work to confirm who owns the next action.":"No human follow-up task is linked to this notebook."} A ready bot draft does not assign work to a colleague.</p>
      <p><strong>Next:</strong> {reviewed?'Prepare a follow-up below, or link existing practice work. Choose its owner before treating it as assigned.':'Review the note, then prepare a follow-up and confirm its owner.'}</p>
      {!reviewed&&<button className="team-primary" disabled={locked} onClick={onReview}>Review note before follow-up</button>}</>:
      <ul>{tickets.slice(0,20).map(id=>{const item=rows[id];return <li key={id}>
        {item?<><strong>{item.body}</strong><p>Responsible: <strong>{item.responsible.name}</strong>{!item.responsible.available?' · Account unavailable':''} · Due {item.due_date}</p>
          <p>Status: {item.state.replaceAll('_',' ')}. {item.state==='closed'?'Open the work record to check completion evidence.':'Next: open the work record to review its next action.'}</p>
          {item.pending_offer&&<p>Handoff offered to {item.pending_offer.to.name}; awaiting acceptance. {item.responsible.name} remains responsible.</p>}</>:
          <p>{item===null||!identity?'Owner and current status could not be checked. Open Practice work to confirm.':'Checking the assigned person and current status…'}</p>}
      </li>;})}</ul>}
    <p className="team-fine">This summary covers work linked to the notebook. Messages, referrals and other practice work keep their own assignment records.</p>
    {tickets.length>20&&<p>Showing the first 20 linked tasks. Open Practice work for more.</p>}
    <button className="team-subtle" disabled={locked} onClick={onPracticeWork}>Open Practice work</button>
  </section>;
}
