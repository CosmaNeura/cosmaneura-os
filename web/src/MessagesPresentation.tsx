import {BotAvatar} from './BotAvatar';
import {WorkspaceDialog} from './WorkspaceDialog';
import {botAddress,type ProviderTeam,type BotRole} from './workspace-api';
import type {ConversationInbox,ConversationSummary} from './conversations-api';
import type {Presentation} from './session/presentation';
import './messages-presentation.css';

const attention={idle:'',working:'Working',needs_review:'Needs you',needs_check:'Check status'};
export function MessagesInbox({inbox,team,loading,error,locked,onOpen,onNew,onChief,onRefresh,onMore,onUnread,onSettings}:{
  inbox:ConversationInbox|null;team:ProviderTeam|null;loading:boolean;error:string;locked:boolean;
  onOpen:(row:ConversationSummary)=>void;onNew:()=>void;onChief:(address:string)=>void;onRefresh:()=>void;onMore:()=>void;onUnread:(row:ConversationSummary)=>void;onSettings:()=>void;
}){
  const chief=team?.configuration.bots.find(bot=>bot.role==='chief'&&!bot.retired);
  const chiefReady=!!chief?.enabled;
  const chiefRows=inbox?.rows.filter(row=>row.bot.role==='chief')??[];
  const rows=[...chiefRows,...inbox?.rows.filter(row=>row.bot.role!=='chief')??[]];
  return <section className="messages-inbox" aria-labelledby="messages-title">
    <header><h1 id="messages-title">Messages</h1><button className="team-primary" disabled={locked} onClick={onNew}>New message</button></header>
    {error&&<p role="alert">{error}</p>}
    {!chiefRows.length&&<section className="messages-chief-start"><BotAvatar role="chief"/><div><h2>{chief?.name??'Chief'}</h2>
      <p>{chiefReady?'A private conversation to plan your next step. Choose a visit or a private note.':'Chief is unavailable. Your saved conversations remain here.'}</p>
      {chiefReady?<button disabled={locked} onClick={()=>onChief(botAddress(chief!))}>Chat with {chief!.name}</button>:<button disabled={locked} onClick={onSettings}>Review team settings</button>}</div></section>}
    <ul className="messages-list" aria-label="Your conversations">{rows.map(row=><li key={`${row.workspace_id}:${row.bot.address}`}>
      <button className="messages-row" disabled={locked} onClick={()=>onOpen(row)}><BotAvatar role={row.bot.role}/><span className="messages-row-copy"><strong>{row.bot.name}{row.unread&&<><span className="messages-unread" aria-hidden="true"/><span className="team-sr-only">Unread</span></>}</strong><span className="messages-context">{row.context_label}</span><span className="messages-preview">{row.preview||'No messages yet'}</span>
        <span className="messages-status">{[!row.bot.available?'Unavailable · history retained':'',attention[row.attention]].filter(Boolean).join(' · ')}{row.manual_unread?' · Marked unread':''}</span></span>
        <time dateTime={row.last_activity_at}>{new Date(row.last_activity_at).toLocaleDateString(undefined,{month:'short',day:'numeric'})}</time></button>
      {!row.manual_unread&&<button className="messages-mark-unread" aria-label={`Mark ${row.bot.name}, ${row.context_label} unread`} disabled={locked||loading} onClick={()=>onUnread(row)}>Mark unread</button>}
    </li>)}</ul>
    {loading&&<p role="status">Loading conversations…</p>}
    {!loading&&inbox&&!rows.length&&<p className="team-fine">Chats you open will appear here.</p>}
    <footer><button disabled={loading||locked} onClick={onRefresh}>Refresh conversations</button>{inbox?.next_cursor&&<button disabled={loading||locked} onClick={onMore}>Earlier conversations</button>}</footer>
  </section>;
}
export function NewMessagePicker({team,locked,onChoose,onClose}:{team:ProviderTeam;locked:boolean;onChoose:(address:string)=>void;onClose:()=>void}){
  return <WorkspaceDialog title="New message" onClose={onClose} closeLabel="Close new message"><p>Choose who can help. You’ll choose the visit or private note next.</p><div className="messages-bot-choices">
    {[...team.configuration.bots].filter(bot=>!bot.retired).sort((a,b)=>Number(b.role==='chief')-Number(a.role==='chief')).map(bot=><button key={botAddress(bot)} disabled={locked||!bot.enabled} onClick={()=>onChoose(botAddress(bot))}><BotAvatar role={bot.role}/><span><strong>{bot.name}</strong><small>{!bot.enabled?'Paused in Settings':bot.role==='scribe'?'Notes and recording':bot.role==='research'?'Choose a visit, query and sources':'Private conversation'}</small></span></button>)}
  </div><button onClick={onClose} disabled={locked}>Cancel</button></WorkspaceDialog>;
}
export function MessagesThreadHeader({name,role,context,contextKind,task,locked,onBack,onContext,onDetails,onReturn}:{name:string;role:BotRole;context:string;contextKind:string;task:string|null;locked:boolean;onBack:()=>void;onContext:()=>void;onDetails:()=>void;onReturn:()=>void}){
  return <header className="messages-thread-header"><button className="messages-back" aria-label={task?'‹ Back to chat':'‹ Messages'} disabled={locked} onClick={task?onReturn:onBack}><span aria-hidden="true">‹</span>{' '}<span className="messages-back-label">{task?'Back to chat':'Messages'}</span></button><BotAvatar role={role}/><div><h1 tabIndex={-1} title={task??name}>{task??name}</h1><button className="messages-context-button" disabled={locked} onClick={onContext} aria-label={`Change conversation context: ${context}`}><span className="messages-context-label">{context} <span aria-hidden="true">⌄</span></span><small>{contextKind}</small></button></div>{!task&&<button disabled={locked} onClick={onDetails}>Details</button>}</header>;
}
export function ConversationDetails({context,contextKind,locked,onClose,onTask}:{context:string;contextKind:string;locked:boolean;onClose:()=>void;onTask:(task:'Review'|'Notebook'|'Sources'|'Work'|'Activity'|'Tools')=>void}){
  return <WorkspaceDialog title="Conversation details" onClose={onClose} closeLabel="Close conversation details"><p>{context}<br/>{contextKind}</p><div className="messages-details">
    <section><h2>Review</h2><button disabled={locked} onClick={()=>onTask('Review')}>Visit note</button><button disabled={locked} onClick={()=>onTask('Work')}>Follow-up and linked work</button></section>
    <section><h2>Notes and sources</h2><button disabled={locked} onClick={()=>onTask('Notebook')}>Notebook and recording</button><button disabled={locked} onClick={()=>onTask('Sources')}>Saved sources</button><button disabled={locked} onClick={()=>onTask('Tools')}>Tools for this conversation</button></section>
    <section><h2>Activity</h2><button disabled={locked} onClick={()=>onTask('Activity')}>Team activity and drafts</button></section>
  </div><button disabled={locked} onClick={onClose}>Back to chat</button></WorkspaceDialog>;
}
export function LayoutSetting({value,blocked,error,onChoose}:{value:Presentation;blocked:boolean;error:string;onChoose:(value:Presentation)=>void}){
  return <fieldset className="messages-layout-setting" disabled={blocked}><legend>Layout on this device</legend><div>{(['messages','workspace'] as const).map(mode=><label key={mode}><input type="radio" name="cosmas-layout" checked={value===mode} onChange={()=>onChoose(mode)}/>{mode==='messages'?'Messages':'Workspace'}</label>)}</div><p>{blocked?'Finish or check the current request before changing layouts.':'Your conversations, drafts and recording stay in place.'}</p>{error&&<p role="alert">{error}</p>}</fieldset>;
}
