import {useEffect,useLayoutEffect,useMemo,useRef,useState} from 'react';
import {BotAvatar} from './BotAvatar';
import {WorkspaceMarkdown} from './WorkspaceMarkdown';
import {canFocusWorkspaceControl,WorkspaceDialog} from './WorkspaceDialog';
import {clinicalRequestDisplay} from './clinical-team-contract';
import {MessageRequestStatus,messageRequestStatusId} from './MessageRequestStatus';
import type {WorkspaceEntry} from './workspace-api';
import type {ConversationAction,ConversationProjection} from './session/entries';

const entryTime=(time:Date)=>time.toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'});

/** Both presentations display the same entries and invoke the same actions. */
export function ConversationEntries({presentation='workspace',projection,latestSourceRevision,busy,recoveryBlocked,locked,onWork,onSource,onCheck,onAction,canRestoreFocus}:{
  presentation?:'messages'|'workspace';
  projection:ConversationProjection;latestSourceRevision:number;busy:boolean;recoveryBlocked:boolean;locked:boolean;
  onWork:()=>void;onSource:(id:string)=>void;onCheck:(entry:WorkspaceEntry)=>Promise<void>;onAction:(action:ConversationAction)=>void;
  canRestoreFocus?:()=>boolean;
}){
  const messages=presentation==='messages',[details,setDetails]=useState<string|null>(null);
  const detailEpisode=useMemo(()=>({}),[projection.workspaceId,projection.botAddress,presentation]),currentEpisode=useRef<object|null>(detailEpisode);currentEpisode.current=detailEpisode;
  useLayoutEffect(()=>{currentEpisode.current=detailEpisode;return()=>{if(currentEpisode.current===detailEpisode)currentEpisode.current=null;};},[detailEpisode]);
  const detailOpener=useRef<{element:HTMLButtonElement;episode:object;isCurrent:()=>boolean}|null>(null);
  const canRestoreMessageFocus=()=>currentEpisode.current===detailEpisode&&(!canRestoreFocus||canRestoreFocus());
  const leaveDetails=(next:()=>void)=>{
    if(messages){const opener=detailOpener.current;if(!opener||opener.episode!==currentEpisode.current||!opener.isCurrent())return;
      // The source controller must capture the surviving message button, not
      // a citation button that disappears with this sheet.
      if(canFocusWorkspaceControl(opener.element))opener.element.focus({preventScroll:true});}
    setDetails(null);next();
  };
  useEffect(()=>setDetails(null),[projection.workspaceId,projection.botAddress,presentation]);
  const detailEntry=messages?projection.turns.find(entry=>entry.id===details):undefined;
  const lastSent=projection.turns.filter(entry=>entry.kind==='conversation').at(-1)?.id;
  const citations=(entry:WorkspaceEntry)=><div className="team-citations">{entry.reply?.citations.map(citation=>['membership_work','payment_work'].includes(citation.kind)?<button key={citation.entry_id} onClick={()=>leaveDetails(onWork)}>{citation.label} · r{citation.revision}</button>:['inbox_message','inbox_triage','session_prep'].includes(citation.kind)?<span key={citation.entry_id}>{citation.label} · r{citation.revision}</span>:<button key={citation.entry_id} onClick={()=>leaveDetails(()=>onSource(citation.entry_id))}>{citation.label}</button>)}</div>;
  let previousTime:Date|null=null;
  return <>
{projection.entries.map(row => {if(row.kind==='material'){
  const time=new Date(row.createdAt),valid=Number.isFinite(time.getTime()),labelId=`material-label-${row.sourceId}`,timeId=`material-time-${row.sourceId}`,title=row.sourceKind==='research'?'Saved Research packet':row.sourceKind==='outlook'?'Saved Outlook email':row.sourceKind==='gmail'?'Saved Gmail email':row.sourceKind==='google-calendar'?'Saved Google Calendar summary':row.sourceKind==='calendar-import'?'Saved calendar file summary':row.sourceKind==='efax'?'Saved fax passage':'Saved EHR source',unavailable=row.sourceKind==='google-calendar'?'Unavailable calendar summary':row.sourceKind==='outlook'||row.sourceKind==='gmail'?'Unavailable email source':row.sourceKind==='calendar-import'?'Unavailable calendar file summary':row.sourceKind==='efax'?'Unavailable fax passage':'Unavailable EHR source';
  return <article key={row.id} data-entry-id={row.id} className="conversation-review-card conversation-material-card" aria-label={title}><small>{title}</small><h3 id={labelId}>{row.state==='current'?row.label:unavailable}</h3><p id={timeId}>{valid?<time dateTime={row.createdAt}>Saved {entryTime(time)}</time>:'Save time unavailable'}</p><p>{row.state==='current'?'Saved snapshot available':'Unavailable — check access'}</p>{row.sourceKind==='calendar-import'&&<p>File snapshot only</p>}{row.sourceKind==='google-calendar'&&<p>Event snapshot only</p>}<button data-action="view_source" aria-describedby={`${labelId} ${timeId}`} disabled={locked||busy||recoveryBlocked} onClick={event=>{event.currentTarget.focus({preventScroll:true});onSource(row.sourceId);}}>View saved source</button></article>;
}if(row.kind==='review')return <article key={row.id} data-entry-id={row.id} className="conversation-review-card" aria-label={row.title}><small>{row.author}</small><h3>{row.title}</h3><p role="status">{row.status}</p>{row.actions.map(action=><button key={action.kind} data-action={action.kind} disabled={locked} onClick={()=>onAction(action)}>{action.label}</button>)}</article>;const entry=row.entry;
  const time=new Date(entry.created_at),valid=Number.isFinite(time.getTime());
  const separator=messages&&valid&&(!previousTime||time.toDateString()!==previousTime.toDateString()||time.getTime()-previousTime.getTime()>=15*60*1000);
  if(valid)previousTime=time;
  return <div className="team-turn" data-entry-id={row.id} data-delivery={entry.kind==='conversation'?'delivered':undefined} key={entry.id} id={`turn-${entry.id}`} tabIndex={-1}>
    {separator&&<p className="messages-time-separator"><time dateTime={entry.created_at}>{entryTime(time)}</time></p>}
    <article className="team-human-message"><small>{entry.kind === "handoff_result" ? "Brief from Chief" : "You"}</small><p>{clinicalRequestDisplay(entry.content)}</p></article>
    {messages&&entry.id===lastSent&&<p className="messages-delivery">Delivered</p>}
              {entry.reply && <article className="team-bot-message"><header><BotAvatar role={entry.reply.role} />
                <strong>{entry.reply.agent_name}</strong>{entry.reply.backend.endsWith('unavailable')&&<span className="team-pill pending">AI answer unavailable</span>}{(entry.kind === "handoff_result" || entry.model_request?.request.kind==='conversation'&&(entry.model_request.request.inbox_analysis||entry.model_request.request.membership_analysis)) && <span className="team-pill pending">{entry.kind === "handoff_result" ? row.reviewLabel : "Unreviewed draft"}</span>}</header>
                <WorkspaceMarkdown content={entry.reply.content}/>
                {messages?<button className="messages-source-details" aria-label={`Message details from ${entry.reply.agent_name}`} onClick={event=>{event.currentTarget.focus({preventScroll:true});detailOpener.current={element:event.currentTarget,episode:detailEpisode,isCurrent:canRestoreMessageFocus};setDetails(entry.id);}}>{latestSourceRevision>entry.reply.context_revision?'Newer sources available — review details':'Message details'}</button>:<>{citations(entry)}<details className="team-fine"><summary>{latestSourceRevision > entry.reply.context_revision ? "Newer sources available — ask again to review them" : "Source details"}</summary>Saved context through revision {entry.reply.context_revision}</details></>}
              </article>}
              {!entry.reply&&entry.model_request&&<article className="team-bot-message"><header><BotAvatar role={entry.model_request.bot.role} active={entry.model_request.admission.state==='running'}/>
                <strong>{entry.model_request.bot.name}</strong></header><MessageRequestStatus id={messageRequestStatusId(entry.id)} state={entry.model_request.admission.state}/>
                <p className="team-fine">A saved request is not a completed draft or clinical evidence.</p>
                {entry.model_request.request.kind==='conversation'&&<button data-action="check_request" disabled={busy||recoveryBlocked} onClick={()=>void onCheck(entry)}>Check saved result</button>}</article>}

            </div>;})}
{detailEntry?.reply&&<WorkspaceDialog title="Message details" closeLabel="Close message details" onClose={()=>setDetails(null)} canRestoreFocus={canRestoreMessageFocus}>
  <p>From {detailEntry.reply.agent_name}</p>
  {latestSourceRevision>detailEntry.reply.context_revision&&<p role="status">Newer sources are available. Ask again to include them in a new answer.</p>}
  <h3>Saved sources</h3>{detailEntry.reply.citations.length?citations(detailEntry):<p>No individual source citations were attached to this answer.</p>}
  <p className="team-fine">Saved context through revision {detailEntry.reply.context_revision}</p>
</WorkspaceDialog>}
</>;}
