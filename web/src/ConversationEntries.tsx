import {BotAvatar} from './BotAvatar';
import {WorkspaceMarkdown} from './WorkspaceMarkdown';
import {clinicalRequestDisplay} from './clinical-team-contract';
import {modelActive,modelStateLabel} from './model-work-request';
import type {WorkspaceEntry} from './workspace-api';
import type {ConversationAction,ConversationProjection} from './session/entries';

/** Stateless history used by both presentations; all effects go through the shared owner. */
export function ConversationEntries({projection,latestSourceRevision,busy,recoveryBlocked,locked,onWork,onSource,onCheck,onAction}:{
  projection:ConversationProjection;latestSourceRevision:number;busy:boolean;recoveryBlocked:boolean;locked:boolean;
  onWork:()=>void;onSource:(id:string)=>void;onCheck:(entry:WorkspaceEntry)=>Promise<void>;onAction:(action:ConversationAction)=>void;
}){return <>
{projection.entries.map(row => {if(row.kind==='review')return <article key={row.id} className="conversation-review-card" aria-label={row.title}><small>{row.author}</small><h3>{row.title}</h3><p role="status">{row.status}</p>{row.actions.map(action=><button key={action.kind} disabled={locked} onClick={()=>onAction(action)}>{action.label}</button>)}</article>;const entry=row.entry;return <div className="team-turn" key={entry.id} id={`turn-${entry.id}`} tabIndex={-1}><article className="team-human-message"><small>{entry.kind === "handoff_result" ? "Brief from Chief" : "You"}</small><p>{clinicalRequestDisplay(entry.content)}</p></article>
              {entry.reply && <article className="team-bot-message"><header><BotAvatar role={entry.reply.role} />
                <strong>{entry.reply.agent_name}</strong><span className="team-pill">{entry.reply.backend === "azure_gpt41_work_status_v1" ? "Saved work status" : entry.reply.backend === "azure_gpt41_unavailable" ? "GPT-4.1 unavailable" : entry.reply.backend.startsWith("azure_gpt41") ? "GPT-4.1" : "Local review"}</span>{(entry.kind === "handoff_result" || entry.model_request?.request.kind==='conversation'&&(entry.model_request.request.inbox_analysis||entry.model_request.request.membership_analysis)) && <span className="team-pill pending">{entry.kind === "handoff_result" ? row.reviewLabel : "Unreviewed draft"}</span>}</header>
                <WorkspaceMarkdown content={entry.reply.content}/><div className="team-citations">{entry.reply.citations.map((citation) => ["membership_work","payment_work"].includes(citation.kind)?<button key={citation.entry_id} onClick={()=>{onWork();}}>{citation.label} · r{citation.revision}</button>:["inbox_message","inbox_triage","session_prep"].includes(citation.kind)?<span key={citation.entry_id}>{citation.label} · r{citation.revision}</span>:<button key={citation.entry_id}
                  onClick={() => { onSource(citation.entry_id); }}>{citation.label}</button>)}</div>
                <details className="team-fine"><summary>{latestSourceRevision > entry.reply.context_revision ? "Newer sources available — ask again to review them" : "Source details"}</summary>Saved context through revision {entry.reply.context_revision}</details>
              </article>}
              {!entry.reply&&entry.model_request&&<article className="team-bot-message"><header><BotAvatar role={entry.model_request.bot.role} active={modelActive(entry)}/>
                <strong>{entry.model_request.bot.name}</strong></header><p>{modelStateLabel(entry.model_request.admission.state)}</p>
                <p className="team-fine">A saved request is not a completed draft or clinical evidence.</p>
                {entry.model_request.request.kind==='conversation'&&<button disabled={busy||recoveryBlocked} onClick={()=>void onCheck(entry)}>Check saved result</button>}</article>}

            </div>;})}
</>;}
