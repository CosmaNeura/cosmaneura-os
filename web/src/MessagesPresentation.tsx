import {BotAvatar} from './BotAvatar';
import {useEffect,useRef,useState} from 'react';
import {WorkspaceDialog} from './WorkspaceDialog';
import {botAddress,type ProviderTeam,type BotRole,type AuthenticatedWorkspaceIdentity} from './workspace-api';
import type {ConversationInbox,ConversationSummary} from './conversations-api';
import type {Presentation} from './session/presentation';
import type {ConversationDraftSnapshot} from './session/conversation-drafts';
import {conversationPreferenceKey} from './conversation-preferences';
import {conversationActivityDate,organizedConversations,type InboxPreferencesSnapshot,type InboxRenameTarget} from './session/inbox-preferences';
import {useInboxPullRefresh} from './use-inbox-pull-refresh';
import {useInboxSearch} from './use-inbox-search';
import './messages-presentation.css';

const attention={idle:'',working:'Working',needs_review:'Needs you',needs_check:'Check status'};
export function MessagesInbox({identity,inbox,team,loading,error,locked,organization,drafts,onRefreshDrafts,onOpen,onNew,onChief,onRefresh,onMore,onUnread,onSettings,onOrganize,onRestoreAll,onInspect,onCloseMenu,onRename,onReloadOrganization,canRestoreFocus}:{
  identity?:AuthenticatedWorkspaceIdentity;
  inbox:ConversationInbox|null;team:ProviderTeam|null;loading:boolean;error:string;locked:boolean;
  onOpen:(row:ConversationSummary)=>void;onNew:()=>void;onChief:(address:string)=>void;onRefresh:()=>void|Promise<void>;onMore:()=>void;onUnread:(row:ConversationSummary)=>void;onSettings:()=>void;
  organization:InboxPreferencesSnapshot;onOrganize:(row:ConversationSummary,change:{pinned?:boolean;hidden?:boolean})=>Promise<boolean>;onRestoreAll:()=>Promise<boolean>;
  drafts?:ConversationDraftSnapshot|null;onRefreshDrafts?:()=>void;
  onInspect:(row:ConversationSummary)=>void;onCloseMenu:()=>void;onRename:(target:InboxRenameTarget)=>void;onReloadOrganization:()=>void;
  canRestoreFocus?:()=>boolean;
}){
  const [hidden,setHidden]=useState(false),[menu,setMenu]=useState<ConversationSummary|null>(null),heading=useRef<HTMLHeadingElement>(null);
  const pull=useInboxPullRefresh({disabled:locked||loading||!!menu,scope:team?.recovery_scope??'',onRefresh,identity});
  const searchControl=useInboxSearch({container:pull.ref,identity,scope:team?.recovery_scope??''}),{search,setSearch}=searchControl;
  const activeMenu=useRef(menu),alive=useRef(true);activeMenu.current=menu;useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
  const chief=team?.configuration.bots.find(bot=>bot.role==='chief'&&!bot.retired);
  const chiefReady=!!chief?.enabled;
  const chiefRows=inbox?.rows.filter(row=>row.bot.role==='chief')??[];
  const groups=organizedConversations(inbox?.rows??[],organization.value,search,hidden),count=groups.reduce((total,group)=>total+group.rows.length,0);
  const hiddenCount=organization.value.items.filter(item=>item.hidden).length;
  const preference=(row:ConversationSummary)=>organization.value.items.find(item=>conversationPreferenceKey(item.workspace_id,item.bot)===conversationPreferenceKey(row.workspace_id,row.bot.address));
  const organizationLocked=locked||organization.busy||!organization.ready;
  const closeMenu=()=>{setMenu(null);onCloseMenu();};
  useEffect(()=>{setMenu(null);setHidden(false);onCloseMenu();},[team?.recovery_scope]);
  useEffect(()=>{if(menu&&!inbox?.rows.some(row=>row.workspace_id===menu.workspace_id&&row.bot.address===menu.bot.address))closeMenu();},[inbox]);
  async function organize(change:{pinned?:boolean;hidden?:boolean}){if(!menu||organizationLocked)return;const selected=menu;if(await onOrganize(menu,change)&&alive.current&&activeMenu.current===selected){closeMenu();if(change.hidden!==undefined)queueMicrotask(()=>heading.current?.focus());}}
  return <section ref={pull.ref} className="messages-inbox" aria-labelledby="messages-title">
    <div className="messages-pull-refresh" style={{height:pull.distance}} role="status" aria-live="polite">{pull.distance>0&&(pull.ready?'Release to refresh':'Pull to refresh')}</div>
    <header><h1 id="messages-title" ref={heading} tabIndex={-1}>{hidden?'Hidden conversations':'Messages'}</h1><button className="team-primary" disabled={locked} onClick={onNew}>New message</button></header>
    {error&&<p role="alert">{error}</p>}
    {drafts?.error&&<p role="status">{drafts.error} <button disabled={locked||drafts.checking} onClick={onRefreshDrafts}>Check saved drafts</button></p>}
    {organization.error&&!menu&&<p role="alert">{organization.error} <button disabled={organization.busy||locked} onClick={onReloadOrganization}>Retry organization</button></p>}
    <div className="messages-inbox-tools" data-search-compact={searchControl.compact}>
      <label hidden={searchControl.compact}>Search conversations<input ref={searchControl.input} id={searchControl.id} type="search" maxLength={200} value={search} onFocus={searchControl.onFocus} onBlur={searchControl.onBlur} onChange={event=>setSearch(event.target.value)} placeholder="Bot, note or message"/></label>
      {searchControl.compact&&<button type="button" aria-label="Search conversations" aria-expanded={false} aria-controls={searchControl.id} onClick={searchControl.open}>Search</button>}
      {(hiddenCount>0||hidden)&&<button disabled={locked} onClick={()=>setHidden(!hidden)}>{hidden?'Back to conversations':`Hidden conversations (${hiddenCount})`}</button>}
      {search.trim()&&<p className="team-fine messages-search-summary" role="status">{count} {count===1?'match':'matches'} among {inbox?.rows.length??0} loaded conversations.{inbox?.next_cursor?' Load earlier conversations to search more.':''}</p>}
    </div>
    {hidden&&<p className="team-fine">Hidden on this device. Open a row’s actions to restore it.{hiddenCount>0&&<> <button disabled={organizationLocked} onClick={()=>void onRestoreAll().then(saved=>{if(saved){setHidden(false);queueMicrotask(()=>heading.current?.focus());}})}>Restore all hidden conversations</button></>}</p>}
    {!hidden&&!search.trim()&&!chiefRows.length&&<section className="messages-chief-start"><BotAvatar role="chief"/><div><h2>{chief?.name??'Chief'}</h2>
      <p>{chiefReady?'A private conversation to plan your next step. Choose a visit or a private note.':'Chief is unavailable. Your saved conversations remain here.'}</p>
      {chiefReady?<button disabled={locked} onClick={()=>onChief(botAddress(chief!))}>Chat with {chief!.name}</button>:<button disabled={locked} onClick={onSettings}>Review team settings</button>}</div></section>}
    {!organization.ready&&organization.busy?<p role="status">Loading conversation organization…</p>:groups.map(group=><section className="messages-inbox-group" key={group.title}><h2>{group.title}</h2><ul className="messages-list" aria-label={`${group.title} conversations`}>{group.rows.map(row=><li key={`${row.workspace_id}:${row.bot.address}`}>
      <button className="messages-row" disabled={locked} onClick={()=>onOpen(row)}><BotAvatar role={row.bot.role}/><span className="messages-row-copy"><strong>{row.bot.name}{row.unread&&<><span className="messages-unread" aria-hidden="true"/><span className="team-sr-only">Unread</span></>}</strong><span className="messages-context">{row.context_label}</span><span className="messages-preview">{row.preview||'No messages yet'}</span>
        {drafts?.items[conversationPreferenceKey(row.workspace_id,row.bot.address)]&&<span className="messages-status" data-draft-presence={drafts.items[conversationPreferenceKey(row.workspace_id,row.bot.address)]}>{drafts.items[conversationPreferenceKey(row.workspace_id,row.bot.address)]==='note'?'Saved-note draft':'Draft'}</span>}
        <span className="messages-status">{[preference(row)?.pinned?'Pinned':'',!row.bot.available?'Unavailable · history retained':'',attention[row.attention],row.manual_unread?'Marked unread':''].filter(Boolean).join(' · ')}</span></span>
        <time dateTime={row.last_activity_at} title={new Date(row.last_activity_at).toLocaleString()}>{conversationActivityDate(row.last_activity_at)}</time></button>
      <button className="messages-row-menu" aria-label={`Conversation actions for ${row.bot.name}, ${row.context_label}`} disabled={locked||organization.busy} onClick={()=>{setMenu(row);onInspect(row);}}>•••</button>
    </li>)}</ul></section>)}
    {loading&&<p role="status">Loading conversations…</p>}
    {!loading&&inbox&&!count&&!search.trim()&&<p className="team-fine">{hidden?'No hidden conversations are in the loaded results.':'Chats you open will appear here.'}{inbox.next_cursor?' Load earlier conversations to see more.':''}</p>}
    <footer><button disabled={loading||locked} onClick={onRefresh}>Refresh conversations</button>{inbox?.next_cursor&&<button disabled={loading||locked} onClick={onMore}>Load earlier conversations</button>}</footer>
    {menu&&<WorkspaceDialog title="Conversation actions" closeLabel="Close conversation actions" onClose={closeMenu} canRestoreFocus={canRestoreFocus}><p><strong>{menu.bot.name}</strong><br/>{menu.context_label}</p><div className="messages-conversation-actions">
      <button disabled={organizationLocked} onClick={()=>void organize({pinned:!preference(menu)?.pinned})}>{preference(menu)?.pinned?'Unpin conversation':'Pin conversation'}</button>
      <button disabled={organizationLocked} onClick={()=>void organize({hidden:!preference(menu)?.hidden})}>{preference(menu)?.hidden?'Restore conversation':'Hide conversation'}</button>
      {!menu.manual_unread&&<button disabled={locked||loading} onClick={()=>{onUnread(menu);closeMenu();}}>Mark unread</button>}
      {organization.inspecting?<p role="status">Checking notebook actions…</p>:organization.rename?.workspaceId===menu.workspace_id?<button disabled={locked||organization.busy} onClick={()=>{const target=organization.rename!;closeMenu();onRename(target);}}>Rename notebook</button>:!organization.renameError&&<p className="team-fine">This conversation uses its visit label.</p>}
      {organization.renameError&&<p role="status">{organization.renameError}</p>}
      {attention[menu.attention]&&<p className="team-fine">{attention[menu.attention]}. Hiding this conversation keeps it available in Hidden conversations.</p>}
      {organization.error&&<p role="alert">{organization.error}</p>}
    </div></WorkspaceDialog>}
  </section>;
}
export function NewMessagePicker({team,locked,onChoose,onClose,canRestoreFocus}:{team:ProviderTeam;locked:boolean;onChoose:(address:string)=>void;onClose:()=>void;canRestoreFocus?:()=>boolean}){
  return <WorkspaceDialog title="New message" onClose={onClose} closeLabel="Close new message" canRestoreFocus={canRestoreFocus}><p>Choose who can help. You’ll choose the visit or private note next.</p><div className="messages-bot-choices">
    {[...team.configuration.bots].filter(bot=>!bot.retired).sort((a,b)=>Number(b.role==='chief')-Number(a.role==='chief')).map(bot=><button key={botAddress(bot)} disabled={locked||!bot.enabled} onClick={()=>onChoose(botAddress(bot))}><BotAvatar role={bot.role}/><span><strong>{bot.name}</strong><small>{!bot.enabled?'Paused in Settings':bot.role==='scribe'?'Notes and recording':bot.role==='research'?'Choose a visit, query and sources':'Private conversation'}</small></span></button>)}
  </div><button onClick={onClose} disabled={locked}>Cancel</button></WorkspaceDialog>;
}
export function MessagesThreadHeader({name,role,context,contextKind,task,locked,onBack,onContext,onDetails,onReturn,returnLabel}:{name:string;role:BotRole;context:string;contextKind:string;task:string|null;locked:boolean;onBack:()=>void;onContext:()=>void;onDetails:()=>void;onReturn:()=>void;returnLabel?:string}){
  return <header className="messages-thread-header"><button className="messages-back" aria-label={task?`‹ ${returnLabel??`Back to ${name}`}`:'‹ Messages'} disabled={locked} onClick={task?onReturn:onBack}><span aria-hidden="true">‹</span>{' '}<span className="messages-back-label">{task?(returnLabel??`Back to ${name}`):'Messages'}</span></button><BotAvatar role={role}/><div><h1 tabIndex={-1} title={task??name}>{task??name}</h1><button className="messages-context-button" disabled={locked} onClick={onContext} aria-label={`Change conversation context: ${context}`}><span className="messages-context-label">{context} <span aria-hidden="true">⌄</span></span><small>{contextKind}</small></button></div>{!task&&<button disabled={locked} onClick={event=>{event.currentTarget.focus({preventScroll:true});onDetails();}}>Details</button>}</header>;
}
export function ConversationDetails({name,context,contextKind,locked,onClose,onTask,onReviewAppointment,onImportCalendar,onFindAthena,onReviewOutlook,onReviewGoogle,onReviewReceivedFax,canRestoreFocus}:{name:string;context:string;contextKind:string;locked:boolean;onClose:()=>void;onReviewAppointment?:()=>void;onImportCalendar?:()=>void;onFindAthena?:()=>void;onReviewOutlook?:()=>void;onReviewGoogle?:()=>void;onReviewReceivedFax?:()=>void;onTask:(task:'Review'|'Notebook'|'Sources'|'Work'|'Activity'|'Tools')=>void;canRestoreFocus?:()=>boolean}){
  return <WorkspaceDialog title="Conversation details" onClose={onClose} closeLabel="Close conversation details" canRestoreFocus={canRestoreFocus}><p>{context}<br/>{contextKind}</p><div className="messages-details">
    <section><h2>Review</h2><button disabled={locked} onClick={()=>onTask('Review')}>Visit note</button><button disabled={locked} onClick={()=>onTask('Work')}>Follow-up and linked work</button></section>
    <section><h2>Notes and sources</h2>{onReviewReceivedFax&&<button disabled={locked} onClick={onReviewReceivedFax}>Review received fax</button>}{onReviewGoogle&&<button disabled={locked} onClick={onReviewGoogle}>Review Gmail email</button>}{onReviewOutlook&&<button disabled={locked} onClick={onReviewOutlook}>Review Outlook email</button>}{onFindAthena&&<button disabled={locked} onClick={onFindAthena}>Find or connect an Athena visit</button>}{onImportCalendar&&<button disabled={locked} onClick={onImportCalendar}>Import calendar file</button>}{onReviewAppointment&&<button disabled={locked} onClick={onReviewAppointment}>Review EHR records</button>}<button disabled={locked} onClick={()=>onTask('Notebook')}>Notebook and recording</button><button disabled={locked} onClick={()=>onTask('Sources')}>Saved sources</button><button disabled={locked} onClick={()=>onTask('Tools')}>Tools for this conversation</button></section>
    <section><h2>Activity</h2><button disabled={locked} onClick={()=>onTask('Activity')}>Team activity and drafts</button></section>
  </div><button className="messages-details-return" disabled={locked} onClick={onClose}>Back to {name}</button></WorkspaceDialog>;
}
export function LayoutSetting({value,blocked,error,onChoose}:{value:Presentation;blocked:boolean;error:string;onChoose:(value:Presentation)=>void}){
  return <fieldset className="messages-layout-setting" disabled={blocked}><legend>Layout on this device</legend><div>{(['messages','workspace'] as const).map(mode=><label key={mode}><input type="radio" name="cosmas-layout" checked={value===mode} onChange={()=>onChoose(mode)}/>{mode==='messages'?'Messages':'Workspace'}</label>)}</div><p>{blocked?'Finish or check the current request before changing layouts.':'Your conversations, drafts and recording stay in place.'}</p>{error&&<p role="alert">{error}</p>}</fieldset>;
}
