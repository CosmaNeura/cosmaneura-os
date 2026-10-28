import {parseConversationDraft} from '../conversation-draft';
import {conversationPreferenceKey} from '../conversation-preferences';
import type {ConversationSummary} from '../conversations-api';
import {editorAddress,type DraftJournal} from '../draft-journal';
import {subscribeNativeWorkspaceForeground} from '../native-workspace-foreground';
import type {AuthenticatedWorkspaceIdentity} from '../workspace-api';
import type {InboxPreferencesHost} from './inbox-preferences';

export type ConversationDraftPresence='text'|'note';
export type ConversationDraftSnapshot={identity:AuthenticatedWorkspaceIdentity|null;journal:DraftJournal|null;scope:string|null;
 rows:ConversationSummary[]|null;items:Readonly<Record<string,ConversationDraftPresence>>;checking:boolean;error:string};
const empty=():ConversationDraftSnapshot=>({identity:null,journal:null,scope:null,rows:null,items:{},checking:false,error:''});

/** Content-free presence from the existing encrypted journal, for authorized
 * inbox rows only. This projection never changes drafts or server read state. */
export class WorkspaceConversationDrafts {
 private state=empty();
 private host:InboxPreferencesHost|null=null;
 private epoch=0;
 private read=0;
 private remove:(()=>void)|null=null;
 private removeNative:(()=>void)|null=null;
 private suspended=false;
 private listeners=new Set<()=>void>();
 getSnapshot=()=>this.state;
 subscribe=(changed:()=>void)=>{this.listeners.add(changed);return()=>{this.listeners.delete(changed);};};
 private publish(patch:Partial<ConversationDraftSnapshot>){this.state={...this.state,...patch};for(const changed of this.listeners)changed();}
 clear(){this.epoch++;this.read++;this.remove?.();this.removeNative?.();this.remove=null;this.removeNative=null;this.suspended=false;this.host=null;this.state=empty();for(const changed of this.listeners)changed();}
 async bind(host:InboxPreferencesHost|null,rows:ConversationSummary[]|null){
  if(!host||!rows){if(this.host)this.clear();return;}
  if(this.host?.identity===host.identity&&this.host.recovery.journal===host.recovery.journal&&this.host.recovery.recoveryScope===host.recovery.recoveryScope&&this.state.rows===rows){this.host=host;return;}
  this.clear();this.host=host;
  this.publish({identity:host.identity,journal:host.recovery.journal,scope:host.recovery.recoveryScope??null,rows});
  const addresses=new Set(rows.map(row=>editorAddress(row.workspace_id,`conversation:${row.bot.address}`)));
  this.remove=host.recovery.journal.subscribe(address=>{if(address===null)this.clear();else if(addresses.has(address))void this.refresh();});
  if(host.identity.mode==='clerk_jwt'&&host.identity.nativeSession){
   const epoch=this.epoch;
   this.removeNative=subscribeNativeWorkspaceForeground(host.identity,()=>{
    if(this.epoch!==epoch)return;this.suspended=false;void this.refresh();
   },()=>{
    if(this.epoch!==epoch)return;this.suspended=true;this.read++;this.publish({items:{},checking:false,error:''});
   });
  }
  await this.refresh();
 }
 async refresh(){
  const host=this.host,rows=this.state.rows,epoch=this.epoch,read=++this.read;
  if(!host||!rows||this.suspended)return;
  const identityCurrent=()=>host.identity.mode==='desktop_native'?host.identity.isCurrent():!host.identity.nativeSession||host.identity.nativeSession.isCurrent();
  const current=()=>!this.suspended&&identityCurrent()&&this.host?.identity===host.identity&&this.host.recovery.journal===host.recovery.journal&&this.host.recovery.recoveryScope===host.recovery.recoveryScope&&this.epoch===epoch&&this.read===read&&this.state.rows===rows&&this.host.current();
  this.publish({items:{},checking:true,error:''});
  try{
   if(!current())return;await host.recovery.authorize();if(!current())return;
   const items:Record<string,ConversationDraftPresence>={};
   // Bound simultaneous local decryptions; no extra inbox pages are fetched.
   for(let offset=0;offset<rows.length;offset+=20){
    const batch=await Promise.all(rows.slice(offset,offset+20).map(async row=>{
     const saved=await host.recovery.journal.load(editorAddress(row.workspace_id,`conversation:${row.bot.address}`));
     if(!saved)return null;
     if(saved.kind!=='editor'||saved.workspaceId!==row.workspace_id||saved.editor!==`conversation:${row.bot.address}`||saved.pending!==null)throw new Error('Invalid conversation draft');
     const draft=parseConversationDraft(saved.data);
     return draft.noteTask?{key:conversationPreferenceKey(row.workspace_id,row.bot.address),kind:'note' as const}:draft.text.trim()?{key:conversationPreferenceKey(row.workspace_id,row.bot.address),kind:'text' as const}:null;
    }));
    if(!current())return;for(const value of batch)if(value)items[value.key]=value.kind;
   }
   await host.recovery.authorize();if(!current())return;
   this.publish({items,checking:false});
  }catch(cause){if(current()){this.publish({items:{},checking:false,error:'Draft status could not be checked. Your saved text is retained.'});host.denied(cause);}}
 }
}
