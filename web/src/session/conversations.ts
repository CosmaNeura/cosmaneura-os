import {parseConversationDraft,type ConversationDraft} from '../conversation-draft';
import {conversationsApi,type ConversationSummary} from '../conversations-api';
import {DraftStoreError} from '../draft-store';
import {editorAddress,type DraftJournal} from '../draft-journal';
import {workspaceApi,WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from '../workspace-api';
import {teamAddress,teamUuid} from '../team-setup-request';
import type {WorkspaceRoute} from '../workspace-route';
import type {WorkspaceSession} from './workspace-session';
import {projectConversation} from './entries';
import {WorkspaceConversationDrafts} from './conversation-drafts';
const READ_SYNC_ERROR='Read status could not sync. Your messages and drafts are retained.';

export type ConversationHost={identity:AuthenticatedWorkspaceIdentity;journal:DraftJournal;scope:string;
  current:()=>boolean;blocked:()=>boolean;authorize:()=>Promise<void>;navigate:(route:WorkspaceRoute)=>Promise<void>;failure:(cause:unknown)=>void;restoreRejectedNavigation?:()=>void};
/** Inbox and per-context drafts outlive either presentation; no model dispatch. */
export class WorkspaceConversations {
  readonly drafts=new WorkspaceConversationDrafts();
  private readEpoch=0;
  private opening=false;
  private unreadDisplay:{row:ConversationSummary;identity:AuthenticatedWorkspaceIdentity;journal:DraftJournal;generation:number}|null=null;
  private displayed:{journal:DraftJournal;generation:number;key:string}|null=null;
  private displayRead:{key:string;journal:DraftJournal;generation:number;route:number;promise:Promise<void>}|null=null;
  private visibleAcknowledgment:{retained:object;promise:Promise<void>}|null=null;
  // A workspace reopen clears the composer even when the journal and address
  // are unchanged. Preparation belongs to that composer lifetime, not the store.
  private readonly prepared=new WeakMap<DraftJournal,Map<string,number>>();
  constructor(private readonly session:WorkspaceSession,private readonly api=conversationsApi,private readonly readWorkspace=workspaceApi.read){}
  reset(){this.readEpoch++;this.opening=false;this.unreadDisplay=null;this.displayed=null;this.displayRead=null;this.visibleAcknowledgment=null;this.drafts.clear();}
  async refresh(identity:AuthenticatedWorkspaceIdentity,more=false,failure?:(cause:unknown)=>void){
    const current=this.session.generation.current,epoch=++this.readEpoch,prior=this.session.getSnapshot().conversationInbox;
    this.session.setConversationLoading(true);this.session.setConversationError('');
    try{
      const value=await this.api.read(identity,more?prior?.next_cursor??null:null);
      if(current!==this.session.generation.current||epoch!==this.readEpoch)return;
      const rows=more&&prior?[...prior.rows,...value.rows.filter(row=>!prior.rows.some(old=>old.workspace_id===row.workspace_id&&old.bot.address===row.bot.address))]:value.rows;
      this.session.setConversationInbox({...value,rows});
    }catch(cause){if(current===this.session.generation.current&&epoch===this.readEpoch){this.session.setConversationError('Conversations could not be loaded. Your saved chats and drafts are retained. Try again.');if(cause instanceof WorkspaceApiError&&[401,403].includes(cause.status))failure?.(cause);}}
    finally{if(current===this.session.generation.current&&epoch===this.readEpoch)this.session.setConversationLoading(false);}
  }
  async observe(host:ConversationHost){
    const view=this.session.getSnapshot(),wid=view.workspace?.id,bot=view.selected,noteTask=view.phoneNoteTask;if(!wid||!host.current()||this.opening)return;
    const address=editorAddress(wid,`conversation:${bot}`),generation=this.session.generation.current,edit=this.session.models.thoughtEditVersion.current,route=this.session.navigation.sequence.current;
    let known=this.prepared.get(host.journal);if(!known){known=new Map();this.prepared.set(host.journal,known);}
    if(known.get(address)!==generation){
      const retained=await host.journal.load(address),live=this.session.getSnapshot();
      if(!host.current()||generation!==this.session.generation.current||route!==this.session.navigation.sequence.current||edit!==this.session.models.thoughtEditVersion.current||live.workspace?.id!==wid||live.selected!==bot||live.phoneNoteTask!==noteTask||this.opening)return;
      known.set(address,generation);
      const selectedTask=noteTask&&noteTask.workspaceId===wid&&noteTask.owner===host.identity&&noteTask.scope===host.scope&&noteTask.generation===generation;
      if(retained&&retained.kind==='editor'&&!live.thought&&!selectedTask&&!live.pending&&!live.recoveryOffers.length){const draft=parseConversationDraft(retained.data);this.restore(draft,host,wid,generation);}
    }
    await this.retain(host);
  }
  private restore(draft:ConversationDraft,host:ConversationHost,workspaceId:string,generation:number){
    this.session.models.updateThought(draft.text);this.session.setPhoneNoteTask(null);
    if(draft.noteTask){const saved=this.session.getSnapshot().workspace?.note?.latest,task=draft.noteTask;
      this.session.setPhoneNoteTask({owner:host.identity,scope:host.scope,generation,workspaceId,
        selection:{share_with_team:true,expected_revision:this.session.getSnapshot().workspace!.revision,idempotency_key:crypto.randomUUID(),note_id:task.note_id,note_version:task.note_version,content_hash:task.content_hash,source_fingerprint:task.source_fingerprint},
        content:saved&&saved.id===task.note_id&&saved.version===task.note_version&&saved.content_hash===task.content_hash&&saved.source_fingerprint===task.source_fingerprint?saved.content:''});}
  }
  async retain(host:ConversationHost):Promise<boolean>{
    const {workspace,selected,thought,phoneNoteTask}=this.session.getSnapshot();
    if(!workspace||!teamAddress(selected))return true;if(!host.current())return false;
    const generation=this.session.generation.current,edit=this.session.models.thoughtEditVersion.current;
    const address=editorAddress(workspace.id,`conversation:${selected}`);
    const task=phoneNoteTask&&phoneNoteTask.workspaceId===workspace.id&&phoneNoteTask.owner===host.identity&&phoneNoteTask.scope===host.scope&&phoneNoteTask.generation===generation?phoneNoteTask:null;
    let known=this.prepared.get(host.journal);if(!known){known=new Map();this.prepared.set(host.journal,known);}
    const current=()=>{const view=this.session.getSnapshot();return host.current()&&generation===this.session.generation.current&&view.workspace?.id===workspace.id&&view.selected===selected&&view.thought===thought&&view.phoneNoteTask===phoneNoteTask&&this.session.models.thoughtEditVersion.current===edit;};
    if(known.get(address)!==generation){
      const prior=await host.journal.load(address);if(!current())return false;
      // A selected saved note is a draft even when its optional directions
      // are empty. Preserve it until restored or replaced by a current choice.
      if(prior&&prior.kind==='editor'&&!thought&&!task){const retained=parseConversationDraft(prior.data);if(retained.text||retained.noteTask)return true;}
      known.set(address,generation);
    }
    const data:ConversationDraft={text:thought,...(task?{noteTask:{contract:'chief-note-task.compose.v1',note_id:task.selection.note_id,note_version:task.selection.note_version,content_hash:task.selection.content_hash,source_fingerprint:task.selection.source_fingerprint}}:{})};
    if(!current())return false;
    await host.journal.persist(address,{kind:'editor',workspaceId:workspace.id,editor:`conversation:${selected}`,pending:null,data});
    await this.session.recovery.scheduledDraftSave.current?.run();
    return current();
  }
  /** Prepare the destination composer using the same encrypted per-bot drafts as
   * ordinary navigation. Source callers append only after their own fresh read. */
  async prepareSourceDraft(workspaceId:string,bot:string,host:ConversationHost):Promise<boolean>{
    if(!host.current()||host.blocked()||this.opening)return false;
    const view=this.session.getSnapshot();
    if(view.workspace?.id!==workspaceId)return false;
    if(view.selected!==bot)return this.open(workspaceId,bot,host);
    const generation=this.session.generation.current,route=this.session.navigation.sequence.current;
    await this.observe(host);
    if(!host.current()||host.blocked()||generation!==this.session.generation.current||route!==this.session.navigation.sequence.current||this.session.getSnapshot().selected!==bot)return false;
    return this.retain(host);
  }
  async open(workspaceId:string,bot:string,host:ConversationHost,summary?:ConversationSummary):Promise<boolean>{
    if(this.opening||host.blocked()||!host.current()||(!teamAddress(bot)||!teamUuid(workspaceId)))return false;
    const origin=this.session.getSnapshot(),originGeneration=this.session.generation.current,originEdit=this.session.models.thoughtEditVersion.current;
    this.opening=true;this.session.setConversationBusy(true);this.session.setConversationError('');
    const journal=host.journal,originRoute=this.session.navigation.sequence.current;let opened=false,destinationRoute:number|null=null;
    const current=()=>host.current()&&this.session.recovery.journal.current?.value===journal;
    let destinationCurrent=()=>current()&&originGeneration===this.session.generation.current&&originRoute===this.session.navigation.sequence.current;
    const restoreOrigin=()=>{
      const live=this.session.getSnapshot();
      // A failed same-notebook switch has not restored the destination draft.
      // Put unchanged outgoing text back under its original bot before Send can
      // become available. A later route, lifetime or user edit always wins.
      if(current()&&destinationRoute===this.session.navigation.sequence.current&&originGeneration===this.session.generation.current&&live.workspace?.id===origin.workspace?.id&&live.selected===bot&&live.practicePage==='notebook'&&!live.settingsOpen&&!live.practiceOpen&&live.thought===origin.thought&&originEdit===this.session.models.thoughtEditVersion.current){
        this.session.setSelected(origin.selected);this.session.setPanel(origin.panel);this.session.setMobilePanel(origin.mobilePanel);
        this.session.setPracticePage(origin.practicePage);this.session.setSettingsOpen(origin.settingsOpen);this.session.setPracticeOpen(origin.practiceOpen);
      }
    };
    try{
      if(!await this.retain(host)||!current()||host.blocked()||originRoute!==this.session.navigation.sequence.current)return false;
      const observed=summary??this.session.getSnapshot().conversationInbox?.rows.find(row=>row.workspace_id===workspaceId&&row.bot.address===bot);
      await host.navigate({page:'notebook',workspaceId,helper:bot,material:'Conversation'});
      destinationRoute=this.session.navigation.sequence.current;
      if(!current())return false;
      const generation=this.session.generation.current,view=this.session.getSnapshot(),route=this.session.navigation.sequence.current,edit=this.session.models.thoughtEditVersion.current;
      const destination=()=>{const live=this.session.getSnapshot();return current()&&generation===this.session.generation.current&&this.session.navigation.sequence.current===route&&live.workspace?.id===workspaceId&&live.selected===bot&&live.practicePage==='notebook'&&!live.settingsOpen&&!live.practiceOpen;};
      destinationCurrent=destination;
      if(!destination())return false;
      const fresh=await this.readWorkspace(host.identity,workspaceId);
      if(!destination())return false;if(fresh.id!==workspaceId||fresh.revision<view.workspace!.revision)throw new WorkspaceApiError(409);
      this.session.setWorkspace(fresh);
      const retained=await journal.load(editorAddress(workspaceId,`conversation:${bot}`));
      if(!destination()||this.session.models.thoughtEditVersion.current!==edit)return false;
      await host.authorize();if(!destination()||this.session.models.thoughtEditVersion.current!==edit||host.blocked())return false;
      let known=this.prepared.get(journal);if(!known){known=new Map();this.prepared.set(journal,known);}known.set(editorAddress(workspaceId,`conversation:${bot}`),generation);
      if(retained){
        if(retained.kind!=='editor'||retained.editor!==`conversation:${bot}`)throw new DraftStoreError('integrity');
        this.restore(parseConversationDraft(retained.data),host,workspaceId,generation);
      }else if(view.workspace?.id===workspaceId){this.session.models.updateThought('');this.session.setPhoneNoteTask(null);}
      opened=true;
      const latest=this.session.getSnapshot(),selectedBot=latest.team?.configuration.bots.find(item=>(item.instance_id||item.role)===bot);
      if(selectedBot?.role==='scribe'){this.session.setPanel('Notebook');this.session.setMobilePanel('Notebook');}
      if(selectedBot?.role==='research')this.session.setSavedResearchChat(false);
      this.unreadDisplay=observed?{row:observed,identity:host.identity,journal,generation}:null;
      // Opening records the human's chat choice. Read status waits for the
      // actual history to be visible, including ordinary Chief conversations.
      const marker=await this.api.mark(host.identity,workspaceId,bot,{});
      if(observed&&this.unreadDisplay?.row===observed&&marker.marker_version===observed.marker_version+1)
        this.unreadDisplay.row={...observed,marker_version:marker.marker_version};
      if(current()&&generation===this.session.generation.current)void this.refresh(host.identity,false,host.failure);
    }catch(cause){if(destinationCurrent()){this.session.setConversationError(opened?'The conversation is open. Its read status could not sync; try refreshing Messages.':'The conversation could not be opened. Your draft is retained.');if(cause instanceof DraftStoreError)this.session.setRecoveryState('failed');else if(cause instanceof WorkspaceApiError&&[401,403].includes(cause.status))host.failure(cause);}}
    finally{this.opening=false;if(current()){if(!opened){restoreOrigin();host.restoreRejectedNavigation?.();}this.session.setConversationBusy(false);}}
    return opened&&destinationCurrent();
  }
  /** A task can open a chat without showing its replies. Acknowledge only the
   * exact summary observed before the fresh workspace read, once history opens. */
  async acknowledgeVisible(host:ConversationHost,isVisible:()=>boolean){
    const retained=this.unreadDisplay;
    if(retained&&this.visibleAcknowledgment?.retained===retained)return this.visibleAcknowledgment.promise;
    const view=this.session.getSnapshot();
    if(!retained||this.opening||!isVisible()||!host.current()||host.identity!==retained.identity||host.journal!==retained.journal||this.session.generation.current!==retained.generation||view.workspace?.id!==retained.row.workspace_id||view.selected!==retained.row.bot.address||view.practicePage!=='notebook'||view.settingsOpen||view.practiceOpen||view.reviewHandoffId||view.mobilePanel!=='Conversation')return;
    const bot=view.team?.configuration.bots.find(item=>(item.instance_id||item.role)===view.selected);
    if(bot?.role==='research'&&!view.savedResearchChat)return;
    const current=()=>this.unreadDisplay===retained&&host.current()&&this.session.generation.current===retained.generation;
    const acknowledgment=(async()=>{try{
      // Retain this exact watermark/version until confirmed. A lost response
      // can be retried without clearing a newer explicit Mark unread change.
      await this.api.mark(host.identity,retained.row.workspace_id,retained.row.bot.address,{watermark:retained.row.watermark,manual_unread:false,expected_version:retained.row.marker_version});
      if(current()){this.unreadDisplay=null;if(this.session.getSnapshot().conversationError===READ_SYNC_ERROR)this.session.setConversationError('');}
    }catch(cause){if(current()){this.session.setConversationError(READ_SYNC_ERROR);if(cause instanceof WorkspaceApiError&&[401,403].includes(cause.status))host.failure(cause);}}})();
    this.visibleAcknowledgment={retained,promise:acknowledgment};
    try{await acknowledgment;}finally{if(this.visibleAcknowledgment?.promise===acknowledgment)this.visibleAcknowledgment=null;}
  }
  /** A visible new reply needs a fresh server watermark, not the one captured
   * when the chat opened. A later workspace read must match what is on screen
   * before that exact watermark is acknowledged. Never clear manual unread. */
  async acknowledgeDisplayed(host:ConversationHost,isVisible:()=>boolean):Promise<void>{
    const view=this.session.getSnapshot(),workspace=view.workspace,generation=this.session.generation.current;
    if(!workspace||!view.team||this.opening||!host.current()||!isVisible())return;
    const bot=view.selected,route=this.session.navigation.sequence.current,opened=this.unreadDisplay;
    // Finish the explicit opened-chat acknowledgment first. Advancing the
    // automatic watermark would change the marker version needed by its retry.
    if(opened?.journal===host.journal&&opened.generation===generation&&opened.row.workspace_id===workspace.id&&opened.row.bot.address===bot)return;
    const projection=()=>JSON.stringify(projectConversation(this.session.getSnapshot().workspace,this.session.getSnapshot().team,bot).entries);
    const content=projection(),key=`${workspace.id}:${bot}:${content}`;
    if(this.displayed?.journal===host.journal&&this.displayed.generation===generation&&this.displayed.key===key)return;
    if(this.displayRead?.key===key&&this.displayRead.journal===host.journal&&this.displayRead.generation===generation&&this.displayRead.route===route)return this.displayRead.promise;
    const current=()=>{
      const live=this.session.getSnapshot(),selected=live.team?.configuration.bots.find(item=>(item.instance_id||item.role)===bot);
      return host.current()&&isVisible()&&!this.opening&&this.session.recovery.journal.current?.value===host.journal&&this.session.generation.current===generation&&this.session.navigation.sequence.current===route&&
        live.workspace?.id===workspace.id&&live.selected===bot&&live.practicePage==='notebook'&&!live.settingsOpen&&!live.practiceOpen&&!live.reviewHandoffId&&live.mobilePanel==='Conversation'&&
        (selected?.role!=='research'||live.savedResearchChat)&&projection()===content;
    };
    const read={key,journal:host.journal,generation,route,promise:Promise.resolve()};this.displayRead=read;
    read.promise=(async()=>{
      try{
        if(!current())return;
        let page:string|null=null,row:ConversationSummary|undefined;const visited=new Set<string>();
        // A displayed chat normally moved to the first page on reply arrival.
        // Follow older pages sequentially, with a hard 100-row work ceiling.
        for(let pages=0;pages<5;pages++){
          const inbox=await this.api.read(host.identity,page);if(!current())return;
          row=inbox.rows.find(item=>item.workspace_id===workspace.id&&item.bot.address===bot);
          if(row||!inbox.next_cursor)break;
          if(visited.has(inbox.next_cursor))throw new WorkspaceApiError(503);
          visited.add(inbox.next_cursor);page=inbox.next_cursor;
        }
        if(!row)throw new WorkspaceApiError(503);
        const fresh=await this.readWorkspace(host.identity,workspace.id);
        if(!current()||fresh.id!==workspace.id||fresh.revision<workspace.revision||fresh.entries.some(entry=>[entry.google_source_state,entry.microsoft_source_state,entry.calendar_source_state,entry.fax_source_state,entry.practice_fax_source_state,entry.ehr_source_state,entry.calendar_import_source_state].includes('unavailable'))||JSON.stringify(projectConversation(fresh,this.session.getSnapshot().team,bot).entries)!==content)return;
        await host.authorize();if(!current())return;
        await this.api.mark(host.identity,workspace.id,bot,{watermark:row.watermark});
        if(current()){this.displayed={journal:host.journal,generation,key};if(this.session.getSnapshot().conversationError===READ_SYNC_ERROR)this.session.setConversationError('');}
      }catch(cause){if(current()){this.session.setConversationError(READ_SYNC_ERROR);if(cause instanceof WorkspaceApiError&&[401,403].includes(cause.status))host.failure(cause);}}
      finally{if(this.displayRead===read)this.displayRead=null;}
    })();
    return read.promise;
  }
  async markUnread(row:ConversationSummary,identity:AuthenticatedWorkspaceIdentity,failure?:(cause:unknown)=>void){
    const current=this.session.generation.current;
    try{await this.api.mark(identity,row.workspace_id,row.bot.address,{manual_unread:true,expected_version:row.marker_version});
      if(current===this.session.generation.current)await this.refresh(identity,false,failure);
    }catch(cause){if(current===this.session.generation.current){this.session.setConversationError('Unread status could not be saved. Try again.');if(cause instanceof WorkspaceApiError&&[401,403].includes(cause.status))failure?.(cause);}}
  }
}
