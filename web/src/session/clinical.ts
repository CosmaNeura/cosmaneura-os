import {assertCurrentDesktopSession} from '../workspace-auth-headers';
import {clinicalNoteSnapshotSize,clinicalTeamDirectionsError,clinicalTeamDirectionsSupported,clinicalTeamRequest,clinicalTeamRequestAlreadySaved,parseClinicalTeamRequest,currentSharedNote,validShareSavedNoteInput,verifySharedClinicalNote,type ShareSavedNoteInput,type ClinicalNoteShareReceipt} from '../clinical-team-contract';
import {modelRequestHash,type ModelOperation,type PreviousModelRequest} from '../model-work-request';
import {workspaceApi,WorkspaceApiError,requireRecoveryScope,botAddress,type AuthenticatedWorkspaceIdentity,type WorkspaceIdentity,type Workspace,type ProviderTeam} from '../workspace-api';
import type {WorkspaceSession} from './workspace-session';
import type {PendingSave,ConfirmedClinicalModelContext} from './model';
import type {ModelActionContext} from './model-actions';

type Cell<T>={readonly current:T};
export type ClinicalContext=ModelActionContext&{
  locked:boolean;viewNavigationLocked:boolean;captureNavigationLocked:boolean;captureDraftLocked:boolean;recoveryBlocked:boolean;latestNote:string;
  previousIdentity:Cell<AuthenticatedWorkspaceIdentity|undefined>;
  privateRecordingLive:Cell<{authenticated:AuthenticatedWorkspaceIdentity|undefined}>;
  currentIdentity:Cell<WorkspaceIdentity|null>;
  recoveryView:Cell<{workspace:Workspace|null;note:string;pending:PendingSave|null}>;
  currentTeam:Cell<ProviderTeam|null>;
  failure:(cause:unknown)=>void;
  save:(operation:PendingSave,mode?:'submit'|'resolve',authorityCurrent?:()=>boolean)=>Promise<ClinicalNoteShareReceipt|undefined>;
  saveModel:(operation:ModelOperation,mode:'submit'|'resolve',confirmed?:ConfirmedClinicalModelContext)=>Promise<void>;
  showReplacement:(role:string)=>void;
};
export type ClinicalDependencies=Partial<Pick<typeof workspaceApi,'read'|'team'>>;

/** Exact saved-note preparation retains owner, source, operation and edit guards. */
export class WorkspaceClinical {
  readonly preparation:{current:object|null}={current:null};
  readonly safety:{current:{blocked:boolean;busy:boolean;pending:PendingSave|null}}={current:{blocked:true,busy:true,pending:null}};
  private readonly api:Pick<typeof workspaceApi,'read'|'team'>;
  constructor(private readonly session:WorkspaceSession,deps:ClinicalDependencies={}) {
    this.api={read:(...args)=>workspaceApi.read(...args),team:(...args)=>workspaceApi.team(...args),...deps};
  }
  async prepare(input:ShareSavedNoteInput,context:ClinicalContext){
    const {workspace,identity,team,note,previousModelRequest}=this.session.getSnapshot();
    const {generation,setError,setWorkspace,setMessage,setClinicalPreparing}=this.session;
    const {journal}=this.session.recovery;
    const {currentThought,thoughtEditVersion,modelBusy}=this.session.models;
    const clinicalPreparation=this.preparation,clinicalSafety=this.safety;
    const {authenticated,locked,viewNavigationLocked,captureNavigationLocked,captureDraftLocked,latestNote,previousIdentity,privateRecordingLive,currentIdentity,recoveryView,currentTeam,failure,save,saveModel}=context;
    const checkRecoveryOwner=(value:ProviderTeam)=>this.session.recovery.checkOwner(authenticated,value);
    if(!authenticated||!identity||!workspace||!team||locked||viewNavigationLocked||captureNavigationLocked||captureDraftLocked||clinicalPreparation.current)return;
    const directions=currentThought.current,directionsEdit=thoughtEditVersion.current,directionsError=clinicalTeamDirectionsError(directions);
    if(directionsError){setError(directionsError);return;}
    const original=workspace.note?.latest,store=journal.current,owner=authenticated,access=identity,current=generation.current,episode={};
    if(!original||original.sources_changed||note!==latestNote||!workspace.appointment_id||workspace.revision>=500||clinicalNoteSnapshotSize(original,workspace.revision)>20000||!store||
      store.serverScope!==requireRecoveryScope(team)||!validShareSavedNoteInput(input)||input.expected_revision!==workspace.revision||
      input.note_id!==original.id||input.note_version!==original.version||input.content_hash!==original.content_hash||input.source_fingerprint!==original.source_fingerprint)return;
    const originalText=original.content,teamRevision=team.revision,workspaceId=workspace.id;
    const shareOperation:Extract<PendingSave,{type:'clinicalNoteShare'}>={type:'clinicalNoteShare',body:structuredClone(input)};
    const noteMatches=(value:Workspace)=>{const latest=value.note?.latest;return !!latest&&!latest.sources_changed&&latest.id===input.note_id&&latest.version===input.note_version&&
      latest.content_hash===input.content_hash&&latest.source_fingerprint===input.source_fingerprint&&latest.content===originalText;};
    const isCurrent=()=>{
      if(clinicalPreparation.current!==episode||previousIdentity.current!==owner||privateRecordingLive.current.authenticated!==owner||currentIdentity.current!==access||
        generation.current!==current||recoveryView.current.workspace?.id!==workspaceId||journal.current?.value!==store.value||journal.current.scope!==store.scope||journal.current.serverScope!==store.serverScope)return false;
      try{assertCurrentDesktopSession(owner);return owner.mode!=='clerk_jwt'||!owner.nativeSession||owner.nativeSession.isCurrent();}catch{return false;}
    };
    const ready=(value:ProviderTeam)=>(directions===''||clinicalTeamDirectionsSupported(value))&&value.revision===teamRevision&&value.revision>0&&value.recovery_scope===store.serverScope&&value.llm.enabled&&
      ['chief','follow_up','research'].every(role=>value.configuration.bots.some(item=>item.role===role&&item.enabled&&!item.retired&&item.include_evidence&&
        !item.blocked_capabilities?.includes('model_answer')&&!item.blocked_capabilities?.includes('private_draft_handoff')));
    const canSend=(latest:Workspace)=>{
      const safety=clinicalSafety.current,live=recoveryView.current,currentConfig=currentTeam.current;
      return isCurrent()&&!safety.blocked&&(!safety.busy||modelBusy.current||safety.pending===shareOperation)&&(!safety.pending||safety.pending===shareOperation)&&
        currentThought.current===directions&&thoughtEditVersion.current===directionsEdit&&!!live.workspace&&noteMatches(live.workspace)&&noteMatches(latest)&&latest.revision>=live.workspace.revision&&
        live.note===(latest.entries.filter(entry=>entry.kind==='scratchpad').at(-1)?.content??'')&&!!currentConfig&&ready(currentConfig);
    };
    clinicalPreparation.current=episode;setClinicalPreparing(true);setError('');
    try{
      if(!ready(team)||!canSend(workspace))throw new Error('Team or source unavailable');
      let selectedSource=currentSharedNote(workspace);
      if(!selectedSource){
        const receipt=await save(shareOperation,'submit',isCurrent);
        if(!isCurrent()||!receipt||receipt.outcome!=='saved')return;
        selectedSource=currentSharedNote(receipt.workspace);
        if(!selectedSource||selectedSource.entry.id!==receipt.source_entry_id)throw new Error('Shared note mismatch');
      }
      if(!isCurrent())return;
      const latest=await this.api.read(access,workspaceId);if(!isCurrent())return;
      const latestTeam=await this.api.team(access);if(!isCurrent())return;checkRecoveryOwner(latestTeam);
      const shared=currentSharedNote(latest);
      if(!ready(latestTeam)||!canSend(latest)||!shared||shared.entry.id!==selectedSource.entry.id||!await verifySharedClinicalNote(shared.entry))throw new Error('Current source unavailable');
      if(!isCurrent()||!canSend(latest))return;
      const content=clinicalTeamRequest(shared,directions);
      if(clinicalTeamRequestAlreadySaved(latest,directions)){
        setWorkspace(latest);setMessage('Chief’s request is already saved. Review its current drafts or check the retained result.');return;
      }
      const chief=latestTeam.configuration.bots.find(item=>item.role==='chief'&&item.enabled&&!item.retired)!;
      const operation:ModelOperation={type:'ask',model_contract:1,origin:'durable_admission_v1',...(previousModelRequest?{previous_model_request:previousModelRequest}:{}),body:{expected_revision:latest.revision,team_revision:latestTeam.revision,
        idempotency_key:crypto.randomUUID(),role:botAddress(chief),content}};
      await saveModel(operation,'submit',{workspace:latest,team:latestTeam,identity:access,isCurrent,canSend:()=>canSend(latest),composer:{content:directions,editVersion:directionsEdit},
        onDispatch:()=>{if(isCurrent())setClinicalPreparing(false);}});
    }catch(cause){if(isCurrent()){if(cause instanceof WorkspaceApiError&&[401,403,404,426].includes(cause.status))failure(cause);
      else setError('The exact saved note or current team could not be confirmed. No new Chief request was sent; review the retained share and current source before continuing.');}}
    finally{if(clinicalPreparation.current===episode){clinicalPreparation.current=null;setClinicalPreparing(false);}}
  }
  async prepareReplacement(context:ClinicalContext){
    const {workspace,identity,team,note,busy,pending,modelObservation,replacementDraft,recoveryState,recoveryOffers,conflict,evidence,source}=this.session.getSnapshot();
    const {generation,setMessage,setBusy,setPending,setPreviousModelRequest,setModelObservation,setReplacementDraft}=this.session;
    const {journal}=this.session.recovery;
    const {currentThought,modelBusy}=this.session.models;
    const {authenticated,viewNavigationLocked,captureNavigationLocked,captureDraftLocked,recoveryBlocked,previousIdentity,privateRecordingLive,currentIdentity,recoveryView,notebookDraft,modelFailure}=context;
    if(!authenticated||!identity||!workspace||!team||busy||modelBusy.current||pending?.type!=='ask'||!parseClinicalTeamRequest(pending.body.content)||
      !modelObservation||!replacementDraft?.acknowledged||!['unknown','failed','abandoned','not_found'].includes(modelObservation.receipt.outcome)||
      recoveryBlocked||recoveryState==='failed'||recoveryOffers.length||conflict||captureNavigationLocked||captureDraftLocked||viewNavigationLocked)return;
    const owner=authenticated,access=identity,current=generation.current,id=workspace.id,store=journal.current,old=pending;
    if(!store||store.serverScope!==requireRecoveryScope(team))return;
    const isCurrent=()=>previousIdentity.current===owner&&privateRecordingLive.current.authenticated===owner&&currentIdentity.current===access&&generation.current===current&&
      recoveryView.current.workspace?.id===id&&journal.current?.value===store.value&&journal.current.scope===store.scope&&journal.current.serverScope===store.serverScope;
    modelBusy.current=true;setBusy(true);
    try{
      assertCurrentDesktopSession(owner);if(owner.mode==='clerk_jwt'&&owner.nativeSession&&!owner.nativeSession.isCurrent())return;
      const prior:PreviousModelRequest={workspace_id:id,operation:{type:'ask',body:structuredClone(old.body)},request_sha256:await modelRequestHash(old.body),
        outcome:modelObservation.receipt.outcome,observed_at:modelObservation.observedAt,origin:old.origin??'legacy_unknown',legacy_uncertainty_acknowledged:true};
      if(!isCurrent())return;
      await store.value.persist(`workspace:${id}`,notebookDraft(workspace,note,currentThought.current,evidence,source,null,prior));
      if(!isCurrent())return;
      assertCurrentDesktopSession(owner);if(owner.mode==='clerk_jwt'&&owner.nativeSession&&!owner.nativeSession.isCurrent())return;
      setPending(null);setPreviousModelRequest(prior);setModelObservation(null);setReplacementDraft(null);context.showReplacement(old.body.role);
      setMessage('The previous exact request is retained. Review the current saved note and directions before preparing a new private team request. Nothing has been sent.');
    }catch(cause){if(isCurrent())modelFailure(cause);}finally{if(isCurrent()){modelBusy.current=false;setBusy(false);}}
  }
}
