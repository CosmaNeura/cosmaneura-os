import type {SessionPrepAnalysis} from '../session-prep-analysis-contract';
import {teamConfigurationChanged} from '../team-configuration-diff';
import {clinicalTeamDirectionsSupported,clinicalTeamUsesDirections,parseClinicalTeamRequest} from '../clinical-team-contract';
import {modelWorkApi} from '../model-work-api';
import {conversationFromEntry,exactModelObservation,modelRequestHash,validModelOperation,type ModelOperation,type PreviousModelRequest} from '../model-work-request';
import type {notebookDraft} from '../draft-journal';
import {workspaceApi,WorkspaceApiError,requireRecoveryScope,botAddress,type AuthenticatedWorkspaceIdentity,type Workspace,type WorkspaceEntry,type ProviderTeam} from '../workspace-api';
import type {ConfirmedClinicalModelContext,WorkspaceSessionSnapshot} from './model';
import type {WorkspaceSession} from './workspace-session';

type ModelApi=Pick<typeof workspaceApi,'ask'|'retryHandoff'|'read'|'team'>;
export type ModelDependencies={workspace?:Partial<ModelApi>;resolve?:typeof modelWorkApi.resolve};
export type ModelActionContext={authenticated?:AuthenticatedWorkspaceIdentity;notebookDraft:typeof notebookDraft;modelFailure:(cause:unknown)=>void};

/** One immutable request owner for submit, status checks and explicit replacement. */
export class WorkspaceModelActions {
  readonly modelBusy={current:false};
  readonly currentThought={current:''};
  readonly thoughtEditVersion={current:0};
  private readonly api:ModelApi;
  private readonly resolve:typeof modelWorkApi.resolve;
  constructor(private readonly session:WorkspaceSession,deps:ModelDependencies={}) {
    this.api=deps.workspace?{...workspaceApi,...deps.workspace}:workspaceApi;
    this.resolve=deps.resolve??((...args)=>modelWorkApi.resolve(...args));
  }
  updateThought(value:string):void {this.thoughtEditVersion.current++;this.currentThought.current=value;this.session.setThought(value);}
  reset():void {this.modelBusy.current=false;this.currentThought.current='';}
  observePendingHash():()=>void {
    const pending=this.session.getSnapshot().pending;let cancelled=false;
    if(pending?.type==='ask')void modelRequestHash(pending.body).then(hash=>{
      if(!cancelled)this.session.setModelHashes({[pending.body.idempotency_key]:hash});
    }).catch(()=>{if(!cancelled)this.session.setModelHashes({});});
    else this.session.setModelHashes({});
    return()=>{cancelled=true;};
  }
  save(operation:ModelOperation,mode:'submit'|'resolve',context:ModelActionContext,confirmed?:ConfirmedClinicalModelContext){
    return this.executeSave(this.session.getSnapshot(),operation,mode,context,confirmed);
  }
  mergeRead(latest:Workspace,latestTeam:ProviderTeam,base=this.session.getSnapshot()){
    const {workspace,team,teamDraft,note}=base;
    const {setWorkspace,setTeam,setTeamDraft,setSchedulingObservation,setConflict,setError}=this.session;
    const savedNote=(value:Workspace|null)=>value?.entries.filter(e=>e.kind==='scratchpad').at(-1)?.content??'';
    const noteChanged=savedNote(latest)!==savedNote(workspace)&&note!==savedNote(latest);
    const editedTeam=!!team&&!!teamDraft&&teamConfigurationChanged(team.configuration,teamDraft);
    const teamChanged=!!team&&latestTeam.revision!==team.revision&&editedTeam;
    setWorkspace(latest);setTeam(latestTeam);setSchedulingObservation(value=>value+1);
    if(!editedTeam)setTeamDraft(structuredClone(latestTeam.configuration));
    if(noteChanged||teamChanged){setConflict(true);setError('The saved notebook or team changed. Your unsaved text and settings are retained; load the latest version and compare before saving.');}
  }
  private async executeSave(base:WorkspaceSessionSnapshot,operation:ModelOperation,mode:'submit'|'resolve',context:ModelActionContext,confirmed?:ConfirmedClinicalModelContext){
    const {workspace,team,identity,busy,pending,recoveryOffers,recoveryState,note,thought,evidence,source,previousModelRequest}=base;
    const {setError,setBusy,setMessage,setPending,setModelObservation,setReplacementDraft,setThought,setPreviousModelRequest,setRecoveryState,generation}=this.session;
    const {modelBusy,currentThought,thoughtEditVersion}=this;
    const {journal,scheduledDraftSave,nativeModelSettling}=this.session.recovery;
    const {authenticated,notebookDraft,modelFailure}=context;
    const checkRecoveryOwner=(value:ProviderTeam)=>this.session.recovery.checkOwner(authenticated,value);
    const requestWorkspace=confirmed?.workspace??workspace,requestTeam=confirmed?.team??team,requestIdentity=confirmed?.identity??identity;
    // Navigation selects the next bot before its retained composer is restored.
    // Neither presentation may submit that temporary previous-bot text.
    if(!requestWorkspace||!requestIdentity||busy||this.session.getSnapshot().conversationBusy||modelBusy.current||!validModelOperation(operation)||confirmed&&(!confirmed.isCurrent()||!confirmed.canSend()))return;
    const currentRequest=()=>current===generation.current&&(!confirmed||confirmed.isCurrent());
    modelBusy.current=true;
    const current=generation.current,id=requestWorkspace.id,active=journal.current?.value;
    const native=authenticated?.mode==='clerk_jwt'&&!!authenticated.nativeSession;
    const submittedComposer=confirmed?.composer;
    const submittedThought=submittedComposer?.content??thought;
    const submittedThoughtEdit=submittedComposer?.editVersion??thoughtEditVersion.current;
    const sameSubmittedComposer=()=>currentThought.current===submittedThought&&thoughtEditVersion.current===submittedThoughtEdit;
    const clearNativeSubmission=native&&mode==='submit'&&operation.type==='ask'&&!pending&&
      (submittedComposer?sameSubmittedComposer():submittedThought===operation.body.content);
    setBusy(true);setError('');setMessage('');let transmitted=false;
    try{
      if(authenticated){
        if(!active||journal.current?.serverScope!==requireRecoveryScope(requestTeam)||recoveryOffers.some(offer=>offer.address===`workspace:${id}`)||recoveryState==='failed')throw new Error('Private draft storage unavailable');
        // Retire the pre-submit snapshot before recording the immutable request.
        // A background flush must not enqueue its empty pending body afterward.
        const queued=scheduledDraftSave.current;queued?.cancel();
        if(scheduledDraftSave.current===queued)scheduledDraftSave.current=null;
        await queued?.drain();if(!currentRequest())return;
        // The immutable pending body retains the outgoing message. Store its
        // separate empty composer before clearing the visible native field.
        await active.persist(`workspace:${id}`,notebookDraft(requestWorkspace,note,clearNativeSubmission?'':thought,evidence,source,operation));
        if(!currentRequest())return;
        if(confirmed&&!confirmed.canSend()){
          setPending(operation);setError('Your text or sources changed before Chief was asked. The prepared request is retained; check its saved result before continuing.');return;
        }
      }
      if(mode==='submit'&&operation.type==='ask'&&clinicalTeamUsesDirections(operation.body.content)){
        try {
          const advertised=await this.api.team(requestIdentity);
          if(!currentRequest())return;checkRecoveryOwner(advertised);
          if(!clinicalTeamDirectionsSupported(advertised)){
            setPending(operation);setError('The practice service cannot confirm saved-note directions support. Your text and exact request are kept. Check the saved result or retry after the service is updated.');return;
          }
        }catch(cause){if(currentRequest()){setPending(operation);modelFailure(cause);}return;}
      }
      if(confirmed&&!confirmed.canSend()){
        setPending(operation);setError('Your text or sources changed before Chief was asked. The prepared request is retained; check its saved result before continuing.');return;
      }
      setPending(operation);setModelObservation(null);setReplacementDraft(null);transmitted=true;
      if(clearNativeSubmission){
        if(thoughtEditVersion.current===submittedThoughtEdit&&currentThought.current===submittedThought)currentThought.current='';
        setThought(previous=>thoughtEditVersion.current===submittedThoughtEdit&&previous===submittedThought?'':previous);
      }
      if(operation.previous_model_request)setPreviousModelRequest(operation.previous_model_request);
      confirmed?.onDispatch?.();
      const receipt=mode==='resolve'?await this.resolve(requestIdentity,id,operation):operation.type==='ask'?await this.api.ask(requestIdentity,id,operation.body):await this.api.retryHandoff(requestIdentity,id,operation.handoffId,operation.body);
      if(!currentRequest())return;
      if(!await exactModelObservation(receipt,id,operation))throw new WorkspaceApiError(503);
      if(!currentRequest())return;
      const latest=await this.api.read(requestIdentity,id);
      if(!currentRequest())return;
      const latestTeam=await this.api.team(requestIdentity);if(!currentRequest())return;checkRecoveryOwner(latestTeam);
      const anchor='saved_entry' in receipt?receipt.saved_entry?.revision:receipt.recorded?Math.max(receipt.recorded.workspace_revision,receipt.recorded.result_entry?.revision??0):null;
      if(latest.id!==id||latest.revision<requestWorkspace.revision||anchor!==null&&anchor!==undefined&&latest.revision<anchor)throw new WorkspaceApiError(503);
      const settled=receipt.outcome==='saved'||receipt.outcome==='recorded';
      if(settled&&active&&native){
        // Finish any edit carrying the exact pending body before the settled
        // receipt removes it. Later typing is saved once busy clears.
        nativeModelSettling.current=true;
        const queued=scheduledDraftSave.current;queued?.cancel();
        if(scheduledDraftSave.current===queued)scheduledDraftSave.current=null;
        await queued?.drain();if(!currentRequest())return;
      }
      const workingThought=native||submittedComposer?currentThought.current:thought;
      const nextThought=settled&&!native&&operation.type==='ask'&&(submittedComposer?sameSubmittedComposer():workingThought===operation.body.content)?'':workingThought;
      if(settled&&active){await active.persist(`workspace:${id}`,notebookDraft(latest,note,nextThought,evidence,source,null,operation.previous_model_request??previousModelRequest));if(!currentRequest())return;}
      this.mergeRead(latest,latestTeam,base);
      if(settled){setPending(null);setThought(previous=>native?previous:submittedComposer?thoughtEditVersion.current===submittedThoughtEdit&&previous===submittedThought?'':previous:nextThought);setModelObservation(null);setMessage(receipt.outcome==='saved'?'Conversation saved.':'Draft request recorded. Its current lifecycle is shown separately.');}
      else {setModelObservation({receipt,observedAt:latest.model_observed_at??new Date().toISOString()});setMessage('The exact request is retained. Checking a result does not start model work.');}
    }catch(cause){if(currentRequest()){if(!transmitted){setRecoveryState('failed');setError('No new request was sent. The previous request and your forms are retained. Recheck private draft storage.');}else modelFailure(cause);}}
    finally{if(currentRequest()){nativeModelSettling.current=false;modelBusy.current=false;setBusy(false);}}
  }
  async replace(context:ModelActionContext){
    const base=this.session.getSnapshot();
    const {workspace,team,identity,busy,pending,replacementDraft,modelObservation}=base;
    const {setBusy,generation}=this.session;
    const {modelBusy}=this;
    const {authenticated,modelFailure}=context;
    const checkRecoveryOwner=(value:ProviderTeam)=>this.session.recovery.checkOwner(authenticated,value);
    if(!workspace||!team||!replacementDraft||!modelObservation||(pending?.type!=='ask'&&pending?.type!=='retry')||busy||modelBusy.current)return;
    const old=pending,receipt=modelObservation.receipt;
    if(old.type==='ask'&&(old.body.research_analysis||old.body.inbox_analysis||old.body.membership_analysis||old.body.session_prep_analysis||parseClinicalTeamRequest(old.body.content)))return; // A new selected-source request requires its own source review.
    if(receipt.outcome!=='not_found'&&!['unknown','failed','abandoned'].includes(receipt.outcome))return;
    if(old.origin!=='durable_admission_v1'&&!replacementDraft.acknowledged)return;
    const current=generation.current;
    modelBusy.current=true;setBusy(true);
    try{
      const latestTeam=await this.api.team(identity!);if(current!==generation.current)return;checkRecoveryOwner(latestTeam);
      const latest=await this.api.read(identity!,workspace.id);if(current!==generation.current)return;
      const prior:PreviousModelRequest={workspace_id:workspace.id,operation:old.type==='ask'?{type:'ask',body:structuredClone(old.body)}:{type:'retry',handoffId:old.handoffId,body:structuredClone(old.body)},
        request_sha256:await modelRequestHash(old.body),outcome:receipt.outcome,observed_at:modelObservation.observedAt,origin:old.origin??'legacy_unknown',legacy_uncertainty_acknowledged:replacementDraft.acknowledged};
      let next:ModelOperation;
      if(old.type==='ask'){
        const bot=latestTeam.configuration.bots.find(b=>botAddress(b)===replacementDraft.role);if(!bot?.enabled||bot.retired)throw new WorkspaceApiError(409,'bot_unavailable');
        next={type:'ask',model_contract:1,origin:'durable_admission_v1',previous_model_request:prior,body:{expected_revision:latest.revision,team_revision:latestTeam.revision,
          idempotency_key:crypto.randomUUID(),role:replacementDraft.role,content:replacementDraft.content}};
      }else{
        const handoff=latest.handoffs?.find(h=>h.id===old.handoffId);if(!handoff||handoff.attempt_count>=3)throw new WorkspaceApiError(409);
        next={type:'retry',handoffId:old.handoffId,model_contract:1,origin:'durable_admission_v1',previous_model_request:prior,
          body:{expected_revision:latest.revision,previous_attempt_id:handoff.attempt_id,idempotency_key:crypto.randomUUID()}};
      }
      if(current!==generation.current||!validModelOperation(next))return;
      // saveModel keeps the old pending request until this replacement CAS succeeds.
      modelBusy.current=false;
      await this.executeSave(base,next,'submit',context);
    }catch(cause){if(current===generation.current)modelFailure(cause);}
    finally{if(current===generation.current){modelBusy.current=false;setBusy(false);}}
  }
  ask(selected:string,selectedPrep:SessionPrepAnalysis|null,context:ModelActionContext,content=this.session.getSnapshot().thought){
    const {workspace,team,pending,conflict}=this.session.getSnapshot();
    if (!workspace || !team?.revision || !content.trim() || pending || conflict || !team.configuration.bots.find(b => botAddress(b) === selected)?.enabled) return;
    return this.save({ type: "ask", model_contract:1,origin:'durable_admission_v1',body: { expected_revision: workspace.revision, team_revision: team.revision,
      idempotency_key: crypto.randomUUID(), role: selected, content, ...(selectedPrep?{session_prep_analysis:structuredClone(selectedPrep)}:{}) } },'submit',context);
  }
  async prepareSelectedAnalysis(context:ModelActionContext&{recoveryBlocked:boolean;show:(target:{role:string;kind:'prep'|'membership'|'inbox'|'research'})=>void}){
    const {workspace,identity,busy,pending,modelObservation,replacementDraft,note,thought,evidence,source}=this.session.getSnapshot();
    const {setBusy,setPending,setPreviousModelRequest,setModelObservation,setReplacementDraft,setMessage,generation}=this.session;
    const {modelBusy}=this,{journal}=this.session.recovery,{recoveryBlocked,notebookDraft,modelFailure}=context;
    if(!workspace||!identity||busy||modelBusy.current||pending?.type!=='ask'||!(pending.body.research_analysis||pending.body.inbox_analysis||pending.body.membership_analysis||pending.body.session_prep_analysis)||!modelObservation||!replacementDraft?.acknowledged||!['unknown','failed','abandoned','not_found'].includes(modelObservation.receipt.outcome))return;
    const old=pending,current=generation.current,active=journal.current?.value;if(!active||recoveryBlocked)return;
    modelBusy.current=true;setBusy(true);
    try{
      const prior:PreviousModelRequest={workspace_id:workspace.id,operation:{type:'ask',body:structuredClone(old.body)},request_sha256:await modelRequestHash(old.body),outcome:modelObservation.receipt.outcome,observed_at:modelObservation.observedAt,origin:old.origin??'legacy_unknown',legacy_uncertainty_acknowledged:true};
      await active.persist(`workspace:${workspace.id}`,notebookDraft(workspace,note,thought,evidence,source,null,prior));if(current!==generation.current)return;
      setPending(null);setPreviousModelRequest(prior);setModelObservation(null);setReplacementDraft(null);context.show({role:old.body.role,kind:old.body.session_prep_analysis?'prep':old.body.membership_analysis?'membership':old.body.inbox_analysis?'inbox':'research'});
      setMessage(old.body.session_prep_analysis?'Previous request retained. Open the current Session Prep brief and include it in chat before sending a new question. Nothing has been sent.':old.body.membership_analysis?'Previous Membership/Billing request retained. Review the current record and consent to a new review from this coworker.':old.body.inbox_analysis?'Previous Inbox request retained. Review the current message and encounter in Incoming messages, then consent to a new draft.':'Previous analysis request retained. Review a saved source packet and question, then consent to a new model request. Nothing has been sent.');
    }catch(cause){if(current===generation.current)modelFailure(cause);}finally{if(current===generation.current){modelBusy.current=false;setBusy(false);}}
  }
  async checkEntryResult(entry:WorkspaceEntry,context:ModelActionContext){
    const base=this.session.getSnapshot();
    const {workspace,identity,busy}=base;
    const {setError,setBusy,setMessage,generation}=this.session;
    const {modelBusy}=this;
    const {authenticated,modelFailure}=context;
    const checkRecoveryOwner=(value:ProviderTeam)=>this.session.recovery.checkOwner(authenticated,value);
    if(!workspace||!identity||busy||modelBusy.current||entry.model_request?.request.kind!=='conversation')return;
    const metadata=entry.model_request,request=metadata.request;
    if(request.kind!=='conversation')return;
    const body=conversationFromEntry(entry);if(!body)return;const operation:ModelOperation={type:'ask',body};
    const current=generation.current;modelBusy.current=true;setBusy(true);setError('');
    try{
      if(!validModelOperation(operation)||await modelRequestHash(operation.body)!==metadata.request_sha256)throw new WorkspaceApiError(503);
      const receipt=await this.resolve(identity,workspace.id,operation);
      if(current!==generation.current)return;
      const latest=await this.api.read(identity,workspace.id),latestTeam=await this.api.team(identity);
      if(current!==generation.current)return;checkRecoveryOwner(latestTeam);
      if(latest.id!==workspace.id||latest.revision<workspace.revision||'saved_entry' in receipt&&receipt.saved_entry&&latest.revision<receipt.saved_entry.revision)throw new WorkspaceApiError(503);
      this.mergeRead(latest,latestTeam,base);setMessage(receipt.outcome==='saved'?'The exact saved response was verified.':'Saved request state checked. No model work was started.');
    }catch(cause){if(current===generation.current)modelFailure(cause);}
    finally{if(current===generation.current){modelBusy.current=false;setBusy(false);}}
  }
}
