import {workspaceApi,WorkspaceApiError,botAddress,type Workspace,type WorkspaceEntry,type AuthenticatedWorkspaceIdentity} from '../workspace-api';
import type {GoogleMessageSaved} from '../google-message-recovery';
import type {GoogleCalendarSaved} from '../google-calendar-recovery';
import {EFAX_INBOUND_SOURCE_BUILD,validEFaxSourceOffer,type EFaxSourceOffer,type EFaxSourceReceipt} from '../efax-inbound-source-api';
import {FAX_INBOUND_SOURCE_BUILD,validFaxSourceOffer,type FaxSourceOffer,type FaxSourceReceipt} from '../fax-inbound-source-api';
import {efaxInboundApi,efaxMissing,type EFaxPending} from '../efax-inbound-api';
import {faxInboundApi,type FaxPending} from '../fax-inbound-api';
import {accountIdentityApi} from '../account-identity-api';
import {vendorCanonical,vendorSha256} from '../vendor-contract';
import type {EhrReadSaved} from '../ehr-read-recovery';
import type {ConversationHost} from './conversations';
import type {WorkspaceSession} from './workspace-session';
export type SourceContext={authenticated?:AuthenticatedWorkspaceIdentity;locked:boolean;connectionNavigationLocked:boolean;captureNavigationLocked:boolean;captureDraftLocked:boolean;
  connectionEditorsLocked:boolean;activityBusy:boolean;accessBusy:boolean;scribeSourceBusy:boolean;schedulingPatientBusy:boolean;
  conversationHost?:ConversationHost|null;accountAccess:{authorize:()=>Promise<void>}|null|undefined;failure:(cause:unknown)=>void;focusQuestion:()=>void};
export type SourceDependencies={read?:typeof workspaceApi.read;hash?:typeof vendorSha256;accountRead?:typeof accountIdentityApi.read;resolveEFax?:typeof efaxInboundApi.resolve;resolveFax?:typeof faxInboundApi.resolve};

type DraftSourceKind='google_message'|'google_calendar'|'ehr_read_source'|'efax_inbound_source'|'fax_inbound_source';
type DraftSourceProof={workspace_id:string;entry_id:string;entry_revision:number;content_sha256:string;source_withheld:boolean};
const sourceCurrent=(entry:WorkspaceEntry,kind:DraftSourceKind)=>entry.kind===kind&&(kind==='google_message'?entry.google_source_state==='current':kind==='google_calendar'?entry.calendar_source_state==='current':kind==='ehr_read_source'?entry.ehr_source_state==='current':kind==='efax_inbound_source'?entry.fax_source_state==='current':entry.practice_fax_source_state==='current');
const sourceFailure=(kind:DraftSourceKind)=>kind==='ehr_read_source'?'ehr_read_source_changed':kind==='efax_inbound_source'?'efax_inbound_source_unavailable':kind==='fax_inbound_source'?'fax_inbound_source_unavailable':kind+'_source_changed';
const sourceDescription=(kind:DraftSourceKind)=>kind==='google_message'?'email':kind==='google_calendar'?'calendar summary':kind==='ehr_read_source'?'EHR appointment':'received fax';
function sourceDirections(kind:DraftSourceKind,id:string):string{
  if(kind==='google_message')return 'Review the human-selected email source '+id+' and prepare appropriate private assignments. Preserve the existing clinical note; ask me about missing details before proposing outside actions.';
  if(kind==='google_calendar')return 'Review the human-selected calendar summary '+id+' as an untrusted event snapshot and prepare appropriate private assignments. Preserve the existing clinical note and email sources. Ask me about missing details; do not treat the summary as current availability or a booking.';
  if(kind==='ehr_read_source')return 'Review the human-selected EHR appointment source '+id+' as an untrusted frozen patient and visit snapshot. Prepare appropriate private assignments, preserve the existing clinical note, and ask me about missing details. This source does not establish current availability or a complete chart, and does not authorize EHR changes.';
  return 'Review the human-selected received-fax passage '+id+' and prepare appropriate private assignments. This is manually entered selected text, without OCR or full-document coverage. Preserve the existing clinical note, email and calendar sources; ask me about missing information before proposing outside actions.';
}

/** Selected sources are re-read and hash-checked before becoming editable instructions. */
export class WorkspaceSources {
  private preparingSource=false;
  private readonly read:typeof workspaceApi.read;private readonly hash:typeof vendorSha256;
  private readonly accountRead:typeof accountIdentityApi.read;private readonly resolveEFax:typeof efaxInboundApi.resolve;private readonly resolveFax:typeof faxInboundApi.resolve;
  constructor(private readonly session:WorkspaceSession,deps:SourceDependencies={}){
    this.read=deps.read??((...args)=>workspaceApi.read(...args));this.hash=deps.hash??vendorSha256;
    this.accountRead=deps.accountRead??((...args)=>accountIdentityApi.read(...args));this.resolveEFax=deps.resolveEFax??((...args)=>efaxInboundApi.resolve(...args));this.resolveFax=deps.resolveFax??((...args)=>faxInboundApi.resolve(...args));
  }
  receive(latest:Workspace){
    const {setConflict,setNote,setWorkspace}=this.session;
    const current=this.session.getSnapshot();
    if(current.workspace?.id!==latest.id||current.workspace.revision>latest.revision)return;
    const before=current.workspace.entries.filter(entry=>entry.kind==='scratchpad').at(-1)?.content??'';
    const after=latest.entries.filter(entry=>entry.kind==='scratchpad').at(-1)?.content??'';
    if(before!==after&&current.note!==before)setConflict(true);
    else if(current.note===before)setNote(after);
    setWorkspace(latest);
  }
  async refresh(context:SourceContext){
    const {workspace}=this.session.getSnapshot();
    const {generation}=this.session;
    const {authenticated}=context;
    if(!authenticated||!workspace)throw new WorkspaceApiError(403);
    const current=generation.current,id=workspace.id;
    const latest=await this.read(authenticated,id);
    if(current!==generation.current||this.session.getSnapshot().workspace?.id!==id)throw new WorkspaceApiError(403);
    this.receive(latest);
  }
  prepareGoogle(context:SourceContext,source:GoogleMessageSaved|GoogleCalendarSaved,kind:'google_message'|'google_calendar'='google_message'){
    return this.prepareSourceDraft(context,source,kind);
  }
  /** Every selected source uses the same per-bot journal and current-page fences.
   * The provider-specific wrappers retain their exact source custody checks. */
  private async prepareSourceDraft(context:SourceContext,source:DraftSourceProof,kind:DraftSourceKind){
    const view=this.session.getSnapshot(),host=context.conversationHost;
    if(this.preparingSource||!context.authenticated||!view.workspace||context.locked||context.connectionNavigationLocked||context.captureNavigationLocked||context.captureDraftLocked||context.connectionEditorsLocked||context.activityBusy||context.accessBusy||context.scribeSourceBusy||view.handoffReviewPending||context.schedulingPatientBusy)return;
    this.preparingSource=true;let busyGeneration:number|null=null;
    let reportCurrent=()=>!host||host.current();
    try{
      if(!host||host.identity!==context.authenticated||!host.current())throw new WorkspaceApiError(403);
      const chief=view.team?.configuration.bots.find(bot=>bot.role==='chief'&&bot.enabled&&!bot.retired);
      if(!chief)throw new WorkspaceApiError(409,'bot_unavailable');
      const id=view.workspace.id,address=botAddress(chief);
      if(source.workspace_id!==id||source.source_withheld)throw new WorkspaceApiError(409,sourceFailure(kind));
      if(!await this.session.conversations.prepareSourceDraft(id,address,host))return;
      if(this.session.getSnapshot().phoneNoteTask){this.session.setError('Finish or close the saved-note draft in Chief before preparing this '+sourceDescription(kind)+'. Your saved-note directions are retained.');return;}
      const generation=this.session.generation.current,edit=this.session.models.thoughtEditVersion.current,route=this.session.navigation.sequence.current;
      const current=(version=edit)=>host.current()&&generation===this.session.generation.current&&version===this.session.models.thoughtEditVersion.current&&route===this.session.navigation.sequence.current&&this.session.getSnapshot().workspace?.id===id&&this.session.getSnapshot().selected===address;
      reportCurrent=current;busyGeneration=generation;this.session.setBusy(true);
      const latest=await this.read(context.authenticated,id);if(!current())return;this.receive(latest);
      const entry=latest.entries.find(item=>item.id===source.entry_id&&item.revision===source.entry_revision&&sourceCurrent(item,kind));
      if(!entry||await this.hash(new TextEncoder().encode(entry.content))!==source.content_sha256)throw new WorkspaceApiError(409,sourceFailure(kind));
      await host.authorize();if(!current())return;
      const live=this.session.getSnapshot();
      if(!live.team?.configuration.bots.some(bot=>botAddress(bot)===address&&bot.role==='chief'&&bot.enabled&&!bot.retired))throw new WorkspaceApiError(409,'bot_unavailable');
      const prompt=sourceDirections(kind,source.entry_id);
      this.session.models.updateThought(live.thought.trim()?live.thought+'\n\n'+prompt:prompt);
      if(kind==='ehr_read_source')this.session.setEhrReview(previous=>previous&&previous.workspaceId===id?{...previous,open:false}:previous);
      this.session.setSelectedResult(null);this.session.setSelectedSource(entry.id);this.session.setSettingsOpen(false);this.session.setPracticeOpen(false);this.session.setMobilePanel('Conversation');
      const appended=this.session.models.thoughtEditVersion.current;reportCurrent=()=>current(appended);
      if(await this.session.conversations.retain(host)&&current(appended))context.focusQuestion();
    }catch(cause){if(reportCurrent())context.failure(cause);}
    finally{this.preparingSource=false;if(busyGeneration!==null&&busyGeneration===this.session.generation.current)this.session.setBusy(false);}
  }
  async openEhr(context:SourceContext,origin:'conversation'|'sources'|'connections'):Promise<boolean>{
    const view=this.session.getSnapshot(),host=context.conversationHost,owner=context.authenticated;
    if(!owner||!host||host.identity!==owner||!view.workspace?.appointment_id||context.locked||context.connectionNavigationLocked||context.captureNavigationLocked||context.captureDraftLocked||context.connectionEditorsLocked||context.accessBusy||view.handoffReviewPending||view.privateRecordingEntry||view.privateRecordingBusy)return false;
    const generation=this.session.generation.current,route=this.session.navigation.sequence.current,edit=this.session.models.thoughtEditVersion.current,id=view.workspace.id,selected=view.selected;
    const current=()=>host.current()&&generation===this.session.generation.current&&route===this.session.navigation.sequence.current&&edit===this.session.models.thoughtEditVersion.current&&this.session.getSnapshot().workspace?.id===id&&this.session.getSnapshot().selected===selected;
    try{
      if(!await this.session.conversations.retain(host)||!current())return false;
      await host.authorize();if(!current()||host.blocked())return false;
      this.session.setEhrReview({identity:owner,generation,workspaceId:id,open:true,origin});
      this.session.setSettingsOpen(false);this.session.setPracticeOpen(false);this.session.setPracticePage('notebook');
      return true;
    }catch(cause){if(current())context.failure(cause);return false;}
  }
  closeEhr(context:SourceContext):boolean{
    const view=this.session.getSnapshot(),task=view.ehrReview;
    if(!task||!task.open||task.identity!==context.authenticated||task.generation!==this.session.generation.current||task.workspaceId!==view.workspace?.id||context.locked||context.connectionNavigationLocked||context.captureNavigationLocked||context.captureDraftLocked)return false;
    this.session.setEhrReview({...task,open:false});
    if(task.origin==='connections'){this.session.setSettingsEntry('connections');this.session.setSettingsOpen(true);}
    else if(task.origin==='sources'){this.session.setPanel('Sources');this.session.setMobilePanel('Sources');}
    else this.session.setMobilePanel('Conversation');
    return true;
  }
  prepareEhr(context:SourceContext,source:EhrReadSaved){return this.prepareSourceDraft(context,source,'ehr_read_source');}
  receiveFax(context:SourceContext,document:EFaxSourceOffer,request:Extract<EFaxPending,{kind:'acquire'}>){
    const {workspace}=this.session.getSnapshot();
    const {generation,setSettingsOpen,setPracticeOpen,setMobilePanel,setPanel,setFaxSourceOffer}=this.session;
    const {authenticated,locked,captureNavigationLocked,captureDraftLocked}=context;
    if(!EFAX_INBOUND_SOURCE_BUILD||!authenticated||!workspace||!validEFaxSourceOffer(document)||locked||captureNavigationLocked||captureDraftLocked)return;
    setFaxSourceOffer({identity:authenticated,generation:generation.current,workspaceId:workspace.id,document:structuredClone(document),request:structuredClone(request)});
    setSettingsOpen(false);setPracticeOpen(false);setPanel('Sources');setMobilePanel('Sources');
  }
  async refreshFax(context:SourceContext):Promise<EFaxSourceOffer|null>{
    const {faxSourceOffer}=this.session.getSnapshot();
    const {generation}=this.session;
    const {authenticated,accountAccess}=context;
    const offer=faxSourceOffer;if(!offer||offer.identity!==authenticated||offer.generation!==generation.current||offer.workspaceId!==this.session.getSnapshot().workspace?.id||!accountAccess)return null;
    await accountAccess.authorize();const account=await this.accountRead(offer.identity);
    if(offer.generation!==generation.current||offer.workspaceId!==this.session.getSnapshot().workspace?.id)return null;
    const receipt=await this.resolveEFax(offer.identity,{box_id:account.box_id,owner_id:account.actor_id},offer.request);
    if(offer.generation!==generation.current||offer.workspaceId!==this.session.getSnapshot().workspace?.id||efaxMissing(receipt)||receipt.state!=='acquired'||!receipt.content_available||receipt.source_withheld||!receipt.document||!receipt.operation_id)return null;
    const document={operation_id:receipt.operation_id,document_sha256:receipt.document.sha256,pages:receipt.document.pages};
    return vendorCanonical(document)===vendorCanonical(offer.document)?document:null;
  }
  prepareFax(context:SourceContext,source:{receipt:EFaxSourceReceipt;workspace:Workspace;entry:WorkspaceEntry}){
    const receipt=source.receipt;
    return this.prepareSourceDraft(context,{workspace_id:receipt.scope.workspace_id,entry_id:receipt.entry_id,entry_revision:receipt.entry_revision,content_sha256:receipt.content_sha256,source_withheld:receipt.source_withheld},'efax_inbound_source');
  }
  receiveProviderFax(context:SourceContext,document:FaxSourceOffer,request:Extract<FaxPending,{kind:'acquire'}>){
    const {workspace}=this.session.getSnapshot();
    const {generation,setSettingsOpen,setPracticeOpen,setMobilePanel,setPanel,setProviderFaxSourceOffer}=this.session;
    const {authenticated,locked,captureNavigationLocked,captureDraftLocked}=context;
    if(!FAX_INBOUND_SOURCE_BUILD||!authenticated||!workspace||!validFaxSourceOffer(document)||locked||captureNavigationLocked||captureDraftLocked)return;
    setProviderFaxSourceOffer({identity:authenticated,generation:generation.current,workspaceId:workspace.id,document:structuredClone(document),request:structuredClone(request)});
    setSettingsOpen(false);setPracticeOpen(false);setPanel('Sources');setMobilePanel('Sources');
  }
  async refreshProviderFax(context:SourceContext):Promise<FaxSourceOffer|null>{
    const {providerFaxSourceOffer}=this.session.getSnapshot();
    const {generation}=this.session;
    const {authenticated,accountAccess}=context;
    const offer=providerFaxSourceOffer;if(!offer||offer.identity!==authenticated||offer.generation!==generation.current||offer.workspaceId!==this.session.getSnapshot().workspace?.id||!accountAccess)return null;
    await accountAccess.authorize();const account=await this.accountRead(offer.identity);
    if(offer.generation!==generation.current||offer.workspaceId!==this.session.getSnapshot().workspace?.id)return null;
    const receipt=await this.resolveFax(offer.identity,{box_id:account.box_id,owner_id:account.actor_id},offer.request);
    if(offer.generation!==generation.current||offer.workspaceId!==this.session.getSnapshot().workspace?.id||receipt.state!=='acquired'||receipt.source_withheld||!receipt.document_sha256||!receipt.pages||!receipt.operation_id)return null;
    const document={operation_id:receipt.operation_id,document_sha256:receipt.document_sha256,pages:receipt.pages};
    return vendorCanonical(document)===vendorCanonical(offer.document)?document:null;
  }
  prepareProviderFax(context:SourceContext,source:{receipt:FaxSourceReceipt;workspace:Workspace;entry:WorkspaceEntry}){
    const receipt=source.receipt;
    return this.prepareSourceDraft(context,{workspace_id:receipt.scope.workspace_id,entry_id:receipt.entry_id,entry_revision:receipt.entry_revision,content_sha256:receipt.content_sha256,source_withheld:receipt.source_withheld},'fax_inbound_source');
  }
}
