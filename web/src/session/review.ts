import type {DraftJournal} from '../draft-journal';
import {currentSharedNote} from '../clinical-team-contract';
import {botAddress,type AuthenticatedWorkspaceIdentity,type DraftHandoff} from '../workspace-api';
import type {ChiefNoteTask} from './model';
import type {WorkspaceSession} from './workspace-session';
import type {SaveContext} from './saves';
export type ChiefReviewReturn={owner:AuthenticatedWorkspaceIdentity;scope:string;serverScope:string;journal:DraftJournal;generation:number;workspaceId:string;address:string;
  task:ChiefNoteTask|null;toolsOpen:boolean;sourceEntryId:string;note:{id:string;version:number;content_hash:string;source_fingerprint:string;content:string}};
export type ReviewContext={
  authenticated?:AuthenticatedWorkspaceIdentity;previousIdentity:{readonly current:AuthenticatedWorkspaceIdentity|undefined};
  actionLocked:boolean;viewNavigationLocked:boolean;captureNavigationLocked:boolean;captureDraftLocked:boolean;recoveryBlocked:boolean;
  phoneChatToolsOpen:boolean;setPhoneChatToolsOpen:(value:boolean)=>void;setClinicalTeamExpanded:(value:boolean)=>void;focusQuestion:()=>void;
  returnFocus:{current:ChiefReviewReturn|null};
};

/** Reviews return to the exact owner, note and chat that initiated them. */
export class WorkspaceReview {
  readonly conversationReturn:{current:{owner:AuthenticatedWorkspaceIdentity;workspaceId:string;generation:number;address:string;journal:DraftJournal}|null}={current:null};
  readonly returnTarget:{current:ChiefReviewReturn|null}={current:null};
  constructor(private readonly session:WorkspaceSession){}
  retry(handoff:DraftHandoff,context:SaveContext){
    const {workspace}=this.session.getSnapshot();
    if(workspace)void this.session.saves.save({type:"retry",model_contract:1,origin:"durable_admission_v1",handoffId:handoff.id,
      body:{expected_revision:workspace.revision,previous_attempt_id:handoff.attempt_id,idempotency_key:crypto.randomUUID()}},context);
  }
  currentReturn(context:ReviewContext,target=this.returnTarget.current){
    const {workspace,team,identity,phoneNoteTask}=this.session.getSnapshot();
    const {generation}=this.session;
    const {journal}=this.session.recovery;
    const {authenticated,previousIdentity}=context;
    const store=journal.current,currentNote=workspace?.note?.latest;
    if(!target||authenticated!==target.owner||identity!==target.owner||previousIdentity.current!==target.owner||generation.current!==target.generation||
      workspace?.id!==target.workspaceId||store?.scope!==target.scope||store.serverScope!==target.serverScope||store.value!==target.journal||
      team?.recovery_scope!==target.serverScope||phoneNoteTask!==target.task||!currentNote||currentNote.sources_changed||currentSharedNote(workspace)?.entry.id!==target.sourceEntryId||
      currentNote.id!==target.note.id||currentNote.version!==target.note.version||currentNote.content_hash!==target.note.content_hash||
      currentNote.source_fingerprint!==target.note.source_fingerprint||currentNote.content!==target.note.content||
      !team.configuration.bots.some(item=>item.role==='chief'&&botAddress(item)===target.address&&item.enabled&&!item.retired)||
      (target.owner.mode==='desktop_native'?!target.owner.isCurrent():!!target.owner.nativeSession&&!target.owner.nativeSession.isCurrent()))return null;
    return target;
  }
  currentConversationReturn(context:ReviewContext){
    if(this.returnTarget.current)return null;
    const target=this.conversationReturn.current,view=this.session.getSnapshot();
    return target&&target.owner===context.authenticated&&target.owner===context.previousIdentity.current&&target.workspaceId===view.workspace?.id&&target.generation===this.session.generation.current&&target.journal===this.session.recovery.journal.current?.value?target:null;
  }
  close(context:ReviewContext){
    const {handoffReviewPending}=this.session.getSnapshot();
    const {setReviewHandoffId,setSelected,setSelectedResult,setSavedResearchChat,setSettingsOpen,setPracticeOpen,setMobilePanel}=this.session;
    const {actionLocked,viewNavigationLocked,captureNavigationLocked,captureDraftLocked,setPhoneChatToolsOpen,setClinicalTeamExpanded}=context;
    if(handoffReviewPending)return;
    const target=this.currentReturn(context),conversation=this.currentConversationReturn(context);
    if((target||conversation)&&(actionLocked||viewNavigationLocked||captureNavigationLocked||captureDraftLocked))return;
    this.returnTarget.current=null;setReviewHandoffId(null);
    this.conversationReturn.current=null;
    if(!target){if(conversation){setSelected(conversation.address);setSelectedResult(null);setSavedResearchChat(false);setMobilePanel('Conversation');setPhoneChatToolsOpen(false);context.focusQuestion();}return;}
    context.returnFocus.current=target;
    setSelected(target.address);setSelectedResult(null);setSavedResearchChat(false);
    setSettingsOpen(false);setPracticeOpen(false);setMobilePanel('Conversation');
    setPhoneChatToolsOpen(target.toolsOpen);setClinicalTeamExpanded(true);
  }
  open(handoff:DraftHandoff,context:ReviewContext,fromChiefPlan=false){
    const {workspace,team,identity,phoneNoteTask,handoffReviewPending,selected}=this.session.getSnapshot();
    const {generation,setReviewHandoffId,setSelected,setSelectedResult,setSavedResearchChat,setSettingsOpen,setPracticeOpen,setMobilePanel}=this.session;
    const {journal}=this.session.recovery;
    const {authenticated,previousIdentity,phoneChatToolsOpen,setPhoneChatToolsOpen}=context;
    const bot=team?.configuration.bots.find(value=>botAddress(value)===selected);
    if(handoffReviewPending||!handoff.result_entry_id)return;
    const reviewable=typeof handoff.result_sha256==='string'&&/^[0-9a-f]{64}$/.test(handoff.result_sha256);
    this.returnTarget.current=null;this.conversationReturn.current=null;context.returnFocus.current=null;
    if(fromChiefPlan&&reviewable&&authenticated&&identity===authenticated&&previousIdentity.current===authenticated&&workspace&&journal.current)this.conversationReturn.current={owner:authenticated,workspaceId:workspace.id,generation:generation.current,address:selected,journal:journal.current.value};
    const store=journal.current,savedNote=workspace?.note?.latest,shared=workspace?currentSharedNote(workspace):null;
    if(fromChiefPlan&&reviewable&&authenticated&&identity===authenticated&&previousIdentity.current===authenticated&&bot?.role==='chief'&&workspace&&store&&savedNote&&shared&&!savedNote.sources_changed)
      this.returnTarget.current={owner:authenticated,scope:store.scope,serverScope:store.serverScope,journal:store.value,generation:generation.current,
        workspaceId:workspace.id,address:botAddress(bot),task:phoneNoteTask,toolsOpen:phoneChatToolsOpen,sourceEntryId:shared.entry.id,
        note:{id:savedNote.id,version:savedNote.version,content_hash:savedNote.content_hash,source_fingerprint:savedNote.source_fingerprint,content:savedNote.content}};
    setReviewHandoffId(reviewable?handoff.id:null);
    setPhoneChatToolsOpen(false);
    setSettingsOpen(false);setPracticeOpen(false);setMobilePanel("Conversation");
    setSelected(handoff.recipient_key??handoff.recipient_role);
    if(handoff.recipient_role==='research')setSavedResearchChat(true);
    setSelectedResult(reviewable?null:handoff.result_entry_id);
  }
  prepareFresh(feedback:string,context:ReviewContext){
    const {workspace,team,busy,pending}=this.session.getSnapshot();
    const {setReviewHandoffId,setSelected,setSelectedResult,setSettingsOpen,setPracticeOpen,setMobilePanel,setPhoneNoteTask,setThought,setHandoffReviewPending,setError}=this.session;
    const {captureNavigationLocked,captureDraftLocked,recoveryBlocked}=context;
    if(!workspace||busy||pending||captureNavigationLocked||captureDraftLocked||recoveryBlocked)return;
    const chief=team?.configuration.bots.find(item=>item.role==='chief'&&item.enabled&&!item.retired);
    if(!chief){setError('Enable Chief in Team settings before starting fresh work. Your change request is retained.');return;}
    const fresh='Prepare fresh assignments using the current saved encounter sources.'+(feedback?'\nPlease preserve these requested changes: '+feedback:'');
    this.returnTarget.current=null;context.returnFocus.current=null;
    setPhoneNoteTask(null);setThought(previous=>previous.trim()?previous+'\n\n'+fresh:fresh);
    setSelected(botAddress(chief));setReviewHandoffId(null);setHandoffReviewPending(false);
    setSettingsOpen(false);setPracticeOpen(false);setSelectedResult(null);setMobilePanel('Conversation');
    context.focusQuestion();
  }
}
