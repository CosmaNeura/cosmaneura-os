import type {AccountRecoveryAccess} from '../account-recovery';
import type {ConversationSummary} from '../conversations-api';
import {conversationPreferenceKey,emptyConversationPreferences,parseConversationPreferences,type ConversationPreferences} from '../conversation-preferences';
import {accountEditorAddress} from '../draft-journal';
import {workspaceApi,WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from '../workspace-api';

export type InboxPreferencesHost={identity:AuthenticatedWorkspaceIdentity;recovery:AccountRecoveryAccess;current:()=>boolean;denied:(cause:unknown)=>void};
export type InboxRenameTarget={workspaceId:string;title:string;titleRevision:number};
export type InboxPreferencesSnapshot={value:ConversationPreferences;ready:boolean;busy:boolean;error:string;inspecting:boolean;rename:InboxRenameTarget|null;renameError:string};
const address=accountEditorAddress('conversation-preferences');
const initial=():InboxPreferencesSnapshot=>({value:emptyConversationPreferences(),ready:false,busy:false,error:'',inspecting:false,rename:null,renameError:''});

/** Account-scoped organization only. This controller never saves notebook titles. */
export class WorkspaceInboxPreferences {
  private state=initial();
  private host:InboxPreferencesHost|null=null;
  private epoch=0;
  private inspection=0;
  private listeners=new Set<()=>void>();
  constructor(private readonly readWorkspace=workspaceApi.read){}
  getSnapshot=()=>this.state;
  subscribe=(changed:()=>void)=>{this.listeners.add(changed);return()=>{this.listeners.delete(changed);};};
  private publish(patch:Partial<InboxPreferencesSnapshot>){this.state={...this.state,...patch};for(const changed of this.listeners)changed();}
  clear(){this.epoch++;this.inspection++;this.host=null;this.state=initial();for(const changed of this.listeners)changed();}
  private current(host:InboxPreferencesHost,epoch:number){return this.epoch===epoch&&this.host?.identity===host.identity&&this.host.recovery.journal===host.recovery.journal&&this.host.recovery.recoveryScope===host.recovery.recoveryScope&&host.current();}
  async bind(host:InboxPreferencesHost|null,force=false){
    if(!host){if(this.host)this.clear();return;}
    if(!force&&this.host?.identity===host.identity&&this.host.recovery.journal===host.recovery.journal&&this.host.recovery.recoveryScope===host.recovery.recoveryScope){this.host=host;return;}
    this.host=host;const epoch=++this.epoch;this.inspection++;this.publish({...initial(),busy:true});
    try{await host.recovery.authorize();if(!this.current(host,epoch))return;
      const saved=await host.recovery.journal.load(address);if(!this.current(host,epoch))return;
      if(saved&&(saved.kind!=='account-editor'||saved.editor!=='conversation-preferences'||saved.pending!==null))throw new Error();
      const value=saved?parseConversationPreferences(saved.data):emptyConversationPreferences();
      this.publish({value,ready:true});
    }catch(cause){if(this.current(host,epoch)){this.publish({error:'Conversation organization could not be loaded. Your chats are still available.'});host.denied(cause);}}
    finally{if(this.current(host,epoch))this.publish({busy:false});}
  }
  async set(row:Pick<ConversationSummary,'workspace_id'|'bot'>,change:Partial<Pick<ConversationPreferences['items'][number],'pinned'|'hidden'>>):Promise<boolean>{
    const host=this.host,epoch=this.epoch;if(!host||!this.current(host,epoch)||!this.state.ready||this.state.busy)return false;
    const key=conversationPreferenceKey(row.workspace_id,row.bot.address),items=this.state.value.items.filter(item=>conversationPreferenceKey(item.workspace_id,item.bot)!==key);
    const prior=this.state.value.items.find(item=>conversationPreferenceKey(item.workspace_id,item.bot)===key);
    const item={workspace_id:row.workspace_id,bot:row.bot.address,pinned:prior?.pinned??false,hidden:prior?.hidden??false,...change};
    if(item.pinned||item.hidden)items.push(item);
    return this.save({contract:'conversation-preferences.v1',items},host,epoch);
  }
  async restoreAll():Promise<boolean>{
    const host=this.host,epoch=this.epoch;if(!host||!this.current(host,epoch)||!this.state.ready||this.state.busy)return false;
    return this.save({contract:'conversation-preferences.v1',items:this.state.value.items.filter(item=>item.pinned).map(item=>({...item,hidden:false}))},host,epoch);
  }
  private async save(value:ConversationPreferences,host:InboxPreferencesHost,epoch:number):Promise<boolean>{
    this.publish({busy:true,error:''});
    try{parseConversationPreferences(value);await host.recovery.authorize();if(!this.current(host,epoch))return false;
      await host.recovery.journal.persist(address,{kind:'account-editor',editor:'conversation-preferences',pending:null,data:value});
      if(!this.current(host,epoch))return false;this.publish({value});return true;
    }catch(cause){if(this.current(host,epoch)){this.publish({error:value.items.length>500?'The device has 500 organized conversations. Unpin or restore one before adding another.':'This change could not be saved. Your previous conversation organization is retained.'});host.denied(cause);}return false;}
    finally{if(this.current(host,epoch))this.publish({busy:false});}
  }
  closeMenu(){this.inspection++;this.publish({inspecting:false,rename:null,renameError:''});}
  async inspect(row:ConversationSummary){
    const host=this.host,epoch=this.epoch,inspection=++this.inspection;this.publish({inspecting:true,rename:null,renameError:''});
    if(!host||!this.current(host,epoch)){this.publish({inspecting:false});return;}
    const current=()=>this.current(host,epoch)&&this.inspection===inspection;
    try{await host.recovery.authorize();if(!current())return;
      const workspace=await this.readWorkspace(host.identity,row.workspace_id);if(!current())return;
      if(workspace.id!==row.workspace_id)throw new WorkspaceApiError(502);
      this.publish({rename:workspace.notebook?{workspaceId:workspace.id,title:workspace.notebook.title,titleRevision:workspace.notebook.title_revision}:null});
    }catch(cause){if(current()){this.publish({renameError:'Notebook actions could not be checked. Try opening this menu again.'});host.denied(cause);}}
    finally{if(current())this.publish({inspecting:false});}
  }
}

const needsYou=(row:ConversationSummary)=>['needs_review','needs_check'].includes(row.attention);
export function organizedConversations(rows:ConversationSummary[],preferences:ConversationPreferences,query:string,hidden=false){
  const byKey=new Map(preferences.items.map(item=>[conversationPreferenceKey(item.workspace_id,item.bot),item]));
  const preference=(row:ConversationSummary)=>byKey.get(conversationPreferenceKey(row.workspace_id,row.bot.address));
  const search=query.trim().toLocaleLowerCase();
  const selected=rows.filter(row=>!!preference(row)?.hidden===hidden&&(!search||`${row.bot.name} ${row.context_label} ${row.preview}`.toLocaleLowerCase().includes(search)));
  selected.sort((a,b)=>Number(b.bot.role==='chief')-Number(a.bot.role==='chief')||Number(needsYou(b))-Number(needsYou(a))||Number(!!preference(b)?.pinned)-Number(!!preference(a)?.pinned)||Number(b.attention==='working')-Number(a.attention==='working')||Number(b.unread)-Number(a.unread)||Date.parse(b.last_activity_at)-Date.parse(a.last_activity_at)||conversationPreferenceKey(a.workspace_id,a.bot.address).localeCompare(conversationPreferenceKey(b.workspace_id,b.bot.address)));
  return [{title:'Chief',rows:selected.filter(row=>row.bot.role==='chief')},{title:'Needs you',rows:selected.filter(row=>row.bot.role!=='chief'&&needsYou(row))},{title:'Recent',rows:selected.filter(row=>row.bot.role!=='chief'&&!needsYou(row))}].filter(group=>group.rows.length);
}
export function conversationActivityDate(at:string,now=new Date()):string {
  const date=new Date(at),day=(value:Date)=>new Date(value.getFullYear(),value.getMonth(),value.getDate()).getTime();
  if(day(date)===day(now))return date.toLocaleTimeString(undefined,{hour:'numeric',minute:'2-digit'});
  const yesterday=new Date(now);yesterday.setDate(now.getDate()-1);if(day(date)===day(yesterday))return 'Yesterday';
  return date.toLocaleDateString(undefined,{month:'short',day:'numeric',...(date.getFullYear()!==now.getFullYear()?{year:'numeric'}:{})});
}
