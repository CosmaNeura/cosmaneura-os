import {parseConversationDraft,type ConversationDraft} from '../conversation-draft';
import {conversationsApi,type ConversationSummary} from '../conversations-api';
import {DraftStoreError} from '../draft-store';
import {editorAddress,type DraftJournal} from '../draft-journal';
import {workspaceApi,WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from '../workspace-api';
import {teamAddress,teamUuid} from '../team-setup-request';
import type {WorkspaceRoute} from '../workspace-route';
import type {WorkspaceSession} from './workspace-session';

export type ConversationHost={identity:AuthenticatedWorkspaceIdentity;journal:DraftJournal;scope:string;
  current:()=>boolean;blocked:()=>boolean;authorize:()=>Promise<void>;navigate:(route:WorkspaceRoute)=>Promise<void>;failure:(cause:unknown)=>void};
/** Inbox and per-context drafts outlive either presentation; no model dispatch. */
export class WorkspaceConversations {
  private readEpoch=0;
  private opening=false;
  private unreadDisplay:{row:ConversationSummary;identity:AuthenticatedWorkspaceIdentity;journal:DraftJournal;generation:number}|null=null;
  // A workspace reopen clears the composer even when the journal and address
  // are unchanged. Preparation belongs to that composer lifetime, not the store.
  private readonly prepared=new WeakMap<DraftJournal,Map<string,number>>();
  constructor(private readonly session:WorkspaceSession,private readonly api=conversationsApi,private readonly readWorkspace=workspaceApi.read){}
  reset(){this.readEpoch++;this.opening=false;this.unreadDisplay=null;}
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
    const view=this.session.getSnapshot(),wid=view.workspace?.id,bot=view.selected;if(!wid||!host.current()||this.opening)return;
    const address=editorAddress(wid,`conversation:${bot}`),generation=this.session.generation.current,edit=this.session.models.thoughtEditVersion.current,route=this.session.navigation.sequence.current;
    let known=this.prepared.get(host.journal);if(!known){known=new Map();this.prepared.set(host.journal,known);}
    if(known.get(address)!==generation){
      const retained=await host.journal.load(address),live=this.session.getSnapshot();
      if(!host.current()||generation!==this.session.generation.current||route!==this.session.navigation.sequence.current||edit!==this.session.models.thoughtEditVersion.current||live.workspace?.id!==wid||live.selected!==bot||this.opening)return;
      known.set(address,generation);
      if(retained&&retained.kind==='editor'&&!live.thought&&!live.pending&&!live.recoveryOffers.length){const draft=parseConversationDraft(retained.data);this.restore(draft,host,wid,generation);}
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
    let known=this.prepared.get(host.journal);if(!known){known=new Map();this.prepared.set(host.journal,known);}
    const current=()=>{const view=this.session.getSnapshot();return host.current()&&generation===this.session.generation.current&&view.workspace?.id===workspace.id&&view.selected===selected&&view.thought===thought&&this.session.models.thoughtEditVersion.current===edit;};
    if(known.get(address)!==generation){
      const prior=await host.journal.load(address);if(!current())return false;
      // Opening an existing Workspace must not erase a chat draft not yet restored.
      if(prior&&prior.kind==='editor'&&parseConversationDraft(prior.data).text&&!thought)return true;
      known.set(address,generation);
    }
    const task=phoneNoteTask&&phoneNoteTask.workspaceId===workspace.id&&phoneNoteTask.owner===host.identity&&phoneNoteTask.generation===generation?phoneNoteTask:null;
    const data:ConversationDraft={text:thought,...(task?{noteTask:{contract:'chief-note-task.compose.v1',note_id:task.selection.note_id,note_version:task.selection.note_version,content_hash:task.selection.content_hash,source_fingerprint:task.selection.source_fingerprint}}:{})};
    if(!current())return false;
    await host.journal.persist(address,{kind:'editor',workspaceId:workspace.id,editor:`conversation:${selected}`,pending:null,data});
    await this.session.recovery.scheduledDraftSave.current?.run();
    return current();
  }
  async open(workspaceId:string,bot:string,host:ConversationHost,summary?:ConversationSummary){
    if(this.opening||host.blocked()||!host.current()||(!teamAddress(bot)||!teamUuid(workspaceId)))return;
    this.opening=true;this.session.setConversationBusy(true);this.session.setConversationError('');
    const journal=host.journal,originRoute=this.session.navigation.sequence.current;let opened=false;
    const current=()=>host.current()&&this.session.recovery.journal.current?.value===journal;
    try{
      if(!await this.retain(host)||!current()||host.blocked()||originRoute!==this.session.navigation.sequence.current)return;
      const observed=summary??this.session.getSnapshot().conversationInbox?.rows.find(row=>row.workspace_id===workspaceId&&row.bot.address===bot);
      await host.navigate({page:'notebook',workspaceId,helper:bot,material:'Conversation'});
      if(!current())return;
      const generation=this.session.generation.current,view=this.session.getSnapshot(),route=this.session.navigation.sequence.current,edit=this.session.models.thoughtEditVersion.current;
      const destination=()=>{const live=this.session.getSnapshot();return current()&&generation===this.session.generation.current&&this.session.navigation.sequence.current===route&&live.workspace?.id===workspaceId&&live.selected===bot&&live.practicePage==='notebook'&&!live.settingsOpen&&!live.practiceOpen;};
      if(view.workspace?.id!==workspaceId||view.selected!==bot||view.settingsOpen||view.practiceOpen)return;
      const fresh=await this.readWorkspace(host.identity,workspaceId);
      if(!destination())return;if(fresh.id!==workspaceId||fresh.revision<view.workspace!.revision)throw new WorkspaceApiError(409);
      this.session.setWorkspace(fresh);
      const retained=await journal.load(editorAddress(workspaceId,`conversation:${bot}`));
      if(!destination()||this.session.models.thoughtEditVersion.current!==edit)return;
      await host.authorize();if(!destination()||this.session.models.thoughtEditVersion.current!==edit||host.blocked())return;
      let known=this.prepared.get(journal);if(!known){known=new Map();this.prepared.set(journal,known);}known.set(editorAddress(workspaceId,`conversation:${bot}`),generation);
      if(retained){
        if(retained.kind!=='editor'||retained.editor!==`conversation:${bot}`)throw new DraftStoreError('integrity');
        this.restore(parseConversationDraft(retained.data),host,workspaceId,generation);
      }else if(view.workspace?.id===workspaceId){this.session.models.updateThought('');this.session.setPhoneNoteTask(null);}
      opened=true;
      const latest=this.session.getSnapshot(),selectedBot=latest.team?.configuration.bots.find(item=>(item.instance_id||item.role)===bot);
      if(selectedBot?.role==='scribe'){this.session.setPanel('Notebook');this.session.setMobilePanel('Notebook');}
      if(selectedBot?.role==='research')this.session.setSavedResearchChat(false);
      const deferRead=selectedBot?.role==='scribe'||selectedBot?.role==='research'||selectedBot?.role==='visit_prep';
      this.unreadDisplay=deferRead&&observed?{row:observed,identity:host.identity,journal,generation}:null;
      await this.api.mark(host.identity,workspaceId,bot,observed&&!deferRead?{watermark:observed.watermark,manual_unread:false,expected_version:observed.marker_version}:{});
      if(current()&&generation===this.session.generation.current)void this.refresh(host.identity,false,host.failure);
    }catch(cause){if(current()){this.session.setConversationError(opened?'The conversation is open. Its read status could not sync; try refreshing Messages.':'The conversation could not be opened. Your draft is retained.');if(cause instanceof DraftStoreError)this.session.setRecoveryState('failed');else if(cause instanceof WorkspaceApiError&&[401,403].includes(cause.status))host.failure(cause);}}
    finally{this.opening=false;if(current())this.session.setConversationBusy(false);}
  }
  /** A task can open a chat without showing its replies. Acknowledge only the
   * exact summary observed before the fresh workspace read, once history opens. */
  async acknowledgeVisible(host:ConversationHost){
    const retained=this.unreadDisplay,view=this.session.getSnapshot();
    if(!retained||this.opening||!host.current()||host.identity!==retained.identity||host.journal!==retained.journal||this.session.generation.current!==retained.generation||view.workspace?.id!==retained.row.workspace_id||view.selected!==retained.row.bot.address||view.practicePage!=='notebook'||view.settingsOpen||view.practiceOpen||view.reviewHandoffId||view.mobilePanel!=='Conversation')return;
    const bot=view.team?.configuration.bots.find(item=>(item.instance_id||item.role)===view.selected);
    if(bot?.role==='research'&&!view.savedResearchChat)return;
    this.unreadDisplay=null;
    try{await this.api.mark(host.identity,retained.row.workspace_id,retained.row.bot.address,{watermark:retained.row.watermark,manual_unread:false,expected_version:retained.row.marker_version});}
    catch{if(host.current())this.session.setConversationError('Read status could not sync. Your messages and drafts are retained.');}
  }
  async markUnread(row:ConversationSummary,identity:AuthenticatedWorkspaceIdentity){
    const current=this.session.generation.current;
    try{await this.api.mark(identity,row.workspace_id,row.bot.address,{manual_unread:true,expected_version:row.marker_version});
      if(current===this.session.generation.current)await this.refresh(identity);
    }catch{if(current===this.session.generation.current)this.session.setConversationError('Unread status could not be saved. Try again.');}
  }
}
