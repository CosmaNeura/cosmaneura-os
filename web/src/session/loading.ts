import {coreConnectionApi} from '../core-connection-api';
import type {CoreConnectionCommand,CoreConnectionResult} from '../core-connection-contract';
import type {InboxDraftSelection} from '../inbox-analysis-contract';
import {teamConfigurationChanged} from '../team-configuration-diff';
import {VisitOpenDeadline} from '../visit-open-deadline';
import {subscribeWorkspaceProtocol,workspaceProtocolPhase} from '../workspace-protocol';
import {workspaceApi,WorkspaceApiError,botAddress,type AuthenticatedWorkspaceIdentity,type WorkspaceIdentity,type ProviderTeam,type Workspace} from '../workspace-api';
import type {WorkspaceSession} from './workspace-session';

type LoadingApi=Pick<typeof workspaceApi,'read'|'team'|'catalog'|'open'|'openExisting'|'openPrivateDraft'>;
type CoreRead=(identity:WorkspaceIdentity,command:CoreConnectionCommand)=>Promise<CoreConnectionResult>;
export type LoadingDependencies=Partial<LoadingApi>&{coreRead?:CoreRead};
export type LoadingContext={
  authenticated?:AuthenticatedWorkspaceIdentity;
  failure:(cause:unknown,retry?:()=>Promise<void>)=>void;
  recoverAfterRead:(team:ProviderTeam,workspace:Workspace|null,generation:number,reload?:boolean)=>Promise<void>;
  prepareRecovery:(team:ProviderTeam,workspace:Workspace|null,generation:number,reload?:boolean)=>Promise<void>;
};
export type RefreshContext=LoadingContext&{
  recordingBlocked:boolean;
  invalidateSetup:()=>void;
  invalidatePrep:()=>void;
};
export type OpenedNotebook={identity:AuthenticatedWorkspaceIdentity;workspace:Workspace;team:ProviderTeam};

export type OpenContext=LoadingContext&{
  locked:boolean;captureNavigationLocked:boolean;captureDraftLocked:boolean;hasUnsavedWork:()=>boolean;
  begin:()=>void;resetCapture:(recordVisit:boolean,useRecording:boolean)=>void;focusChief:(workspaceId:string,generation:number)=>void;focusFax:()=>void;showResearch:()=>void;afterOpen:()=>void;retryRead:()=>Promise<void>;
  setOpeningVisit?:(opening:boolean)=>void;
};

/** Reads publish only inside the initiating workspace and navigation lifetime. */
export class WorkspaceLoading {
  private readonly api:LoadingApi;
  private readonly coreRead:CoreRead;
  constructor(private readonly session:WorkspaceSession,deps:LoadingDependencies={}) {
    this.coreRead=deps.coreRead??((...args)=>coreConnectionApi.read(...args));
    this.api={open:(...args)=>workspaceApi.open(...args),openExisting:(...args)=>workspaceApi.openExisting(...args),openPrivateDraft:(...args)=>workspaceApi.openPrivateDraft(...args),read:(...args)=>workspaceApi.read(...args),team:(...args)=>workspaceApi.team(...args),catalog:(...args)=>workspaceApi.catalog(...args),...deps};
  }

  startup(context:LoadingContext,consume:()=>ProviderTeam|null|undefined):(()=>void)|undefined {
    const {authenticated}=context;if(!authenticated||this.session.getSnapshot().team)return;
    let cancelled=false;const current=this.session.generation.current,controller=new AbortController();
    const startup=consume();
    const live=()=>!cancelled&&current===this.session.generation.current;
    const apply=(value:ProviderTeam)=>{
      if(!live())return;
      this.session.setTeam(value);this.session.setTeamDraft(previous=>previous??structuredClone(value.configuration));
      void context.recoverAfterRead(value,null,current);
    };
    if(startup){apply(startup);return()=>{cancelled=true;controller.abort();};}
    let unsubscribe=()=>{};
    const dispatch=()=>{
      if(!live())return;
      // An ordinary GET is fenced on the admitted protocol. Dispatching before
      // admission is refused, and repeating it repeats the same refusal.
      if(workspaceProtocolPhase(authenticated)!=='ready')return;
      unsubscribe();
      void this.api.team(authenticated,controller.signal).then(apply,applyFault);
    };
    const applyFault=(cause:unknown)=>{if(live())context.failure(cause);};
    unsubscribe=subscribeWorkspaceProtocol(authenticated,dispatch);
    dispatch();
    return()=>{cancelled=true;unsubscribe();controller.abort();};
  }

  async open(context:OpenContext,appointmentId?:string,coreSelection?:CoreConnectionCommand,incoming?:InboxDraftSelection,recordVisit=false){
    const {team,teamDraft,busy,pending,privateRecordingEntry,privateRecordingBusy,entryIntent,researchEntry}=this.session.getSnapshot();
    const {generation,setBusy,setError,setMessage,setReadRetry,setRecoveryState,setInboxSelection,setSelected,setPracticeOpen,setMobilePanel,setIdentity,setWorkspace,setTeam,setPracticePage,setPreviousModelRequest,setThought,setEvidence,setSource,setModelObservation,setReplacementDraft,setModelHashes,setEntryIntent,setStage,setPanel,setTeamDraft,setNote,setSettingsOpen}=this.session;
    const {authenticated,locked,captureNavigationLocked,captureDraftLocked,hasUnsavedWork,recoverAfterRead,failure}=context;
    const checkRecoveryOwner=(value:ProviderTeam)=>this.session.recovery.checkOwner(authenticated,value);
    if (pending || busy || privateRecordingEntry || privateRecordingBusy) {if(privateRecordingEntry)setError('Stop and save your recording before opening another notebook.');return;}
    if ((coreSelection || incoming) && (locked || captureNavigationLocked || captureDraftLocked || hasUnsavedWork())) {
      setError('Save or recover unfinished work before opening a notebook. Your text and requests are retained.'); return;
    }
    recordVisit = recordVisit || !incoming && entryIntent === "record";
    const useRecording = !recordVisit && !incoming && entryIntent === "recording";
    const startChief = !recordVisit && !useRecording && !incoming && entryIntent === "chief";
    const startFax = !recordVisit && !useRecording && !incoming && entryIntent === "fax";
    const catalogVisit = !!appointmentId && !coreSelection && !incoming;
    const deadline = catalogVisit ? new VisitOpenDeadline() : null;
    context.begin();
    const preserveTeamDraft = !!team && !!teamDraft && teamConfigurationChanged(team.configuration,teamDraft);
    const current = ++generation.current; setBusy(true); if(catalogVisit)context.setOpeningVisit?.(true); setError(""); setMessage("");
    let showedVisit = false;
    try {
      let selected: {workspace_id:string;appointment_id:string}|undefined;
      if (coreSelection) {
        if (!authenticated) throw new WorkspaceApiError(401);
        const opened = await this.coreRead(authenticated,coreSelection);
        if (current !== generation.current) return;
        if (!opened.workspace) throw new WorkspaceApiError(502);
        selected = opened.workspace;
      }
      const result = incoming && authenticated ? {identity:authenticated,workspace:await this.api.read(authenticated,incoming.workspace_id),team:await this.api.team(authenticated)} : authenticated ? selected ? await this.api.openExisting(authenticated,selected) : await (deadline ? deadline.limit(this.api.open(authenticated, appointmentId)) : this.api.open(authenticated, appointmentId)) : await this.api.open();
      if (current !== generation.current) return;
      checkRecoveryOwner(result.team);
      if(incoming&&(result.workspace.id!==incoming.workspace_id||result.workspace.revision!==incoming.expected_revision))throw new WorkspaceApiError(409,'source_changed');
      setInboxSelection(incoming??null);
      if(incoming){
        const coworker=result.team.configuration.bots.find(b=>b.role==='custom'&&b.skills?.includes('inbox_review')&&b.enabled&&!b.retired&&!b.blocked_capabilities?.includes('model_answer'));
        if(coworker)setSelected(botAddress(coworker));
        setPracticeOpen(false);setMobilePanel('Conversation');
      }
      setIdentity(result.identity); setWorkspace(result.workspace); setTeam(result.team);setPracticePage("notebook");
      setPreviousModelRequest(null);
      setThought('');setEvidence('');setSource('');setModelObservation(null);setReplacementDraft(null);setModelHashes({});
      context.resetCapture(recordVisit,useRecording);setEntryIntent(null);setStage('Before');setPanel('Notebook');
      if (recordVisit || useRecording) {
        const recorder = result.team.configuration.bots.find(item => item.role === "scribe" && !item.retired && !item.instance_id);
        if (recorder) setSelected(botAddress(recorder));
        setMobilePanel("Notebook");
      }
      if(startChief){
        const chief=result.team.configuration.bots.find(item=>item.role==='chief'&&!item.instance_id&&!item.retired);
        if(chief){setSelected(botAddress(chief));context.focusChief(result.workspace.id,current);}
        else setMessage('Chief is not available on this team. Your notebook is still available.');
        setMobilePanel('Notebook');
      }
      if(startFax){setPanel('Work');setMobilePanel('Work');context.focusFax();}
      if (researchEntry && !recordVisit && !useRecording && !incoming) {
        const researcher=result.team.configuration.bots.find(item=>item.role==='research'&&!item.retired);
        if(researcher){setSelected(botAddress(researcher));setMobilePanel('Conversation');context.showResearch();}
        else setMessage('Research is not on this team yet. Add it in Team settings.');
      }
      if (!preserveTeamDraft) setTeamDraft(structuredClone(result.team.configuration));
      setNote(result.workspace.entries.filter(e => e.kind === "scratchpad").at(-1)?.content ?? "");
      setSettingsOpen(false);
      showedVisit = true;
      const recovery = recoverAfterRead(result.team, result.workspace, current);
      if (deadline) await deadline.limit(recovery);
      else await recovery;
      if(current===generation.current)context.afterOpen();
    } catch (cause) { if (current === generation.current) {
      // A hung catalog read disables the visit list. Stop that within one budget
      // and retry the same open. A general failure still must not repeat a write:
      // opening can seed a demo or create a notebook, so that Retry only rechecks
      // the service or saved history. Exact writes keep their own UI.
      if (deadline?.expired) {
        if (showedVisit) setRecoveryState("failed");
        else {
          setError(cause instanceof Error ? cause.message : "This visit could not be opened.");
          setReadRetry({run: () => this.open(context, appointmentId, coreSelection, incoming, recordVisit), label: "Retry"});
        }
        return;
      }
      failure(cause,context.retryRead);
      if(coreSelection && cause instanceof WorkspaceApiError && cause.code==='core_existing_recording_conflict')
        setError('The Scribe recording does not match this visit\u2019s notebook. Ask your practice administrator to review the match.');
      else if(coreSelection && cause instanceof WorkspaceApiError && cause.code==='core_scribe_encounter_unavailable')
        setError('Scribe encounters could not be loaded. Try again, or open your saved visit from the encounter list.');
      else if (coreSelection && !(cause instanceof WorkspaceApiError && [401,403,404,426].includes(cause.status)))
        setError('The notebook could not be confirmed. View your appointments and select it again; an existing notebook will be reused.');
    } }
    finally { if (current === generation.current) { setBusy(false); context.setOpeningVisit?.(false); } }
  }

  async refresh(context:RefreshContext):Promise<void> {
    const {identity,workspace,busy,pending,recoveryState}=this.session.getSnapshot();
    const access=context.authenticated||identity;
    if(!access||busy||pending||context.recordingBlocked)return;
    const current=this.session.generation.current;
    this.session.setBusy(true);this.session.setError('');this.session.setMessage('');context.invalidateSetup();
    try {
      const [latest,latestTeam]=await Promise.all([workspace?this.api.read(access,workspace.id):Promise.resolve(null),this.api.team(access)]);
      if(current!==this.session.generation.current)return;
      this.session.recovery.checkOwner(context.authenticated,latestTeam);
      this.session.setWorkspace(latest);this.session.setTeam(latestTeam);this.session.setConflict(false);
      context.invalidatePrep();this.session.setSchedulingObservation(value=>value+1);
      this.session.setMessage('Latest saved history and team loaded. Your unsaved text and settings are preserved; compare them before saving.');
      await context.recoverAfterRead(latestTeam,latest,current,recoveryState==='failed');
    }catch(cause){if(current===this.session.generation.current)context.failure(cause,()=>this.refresh(context));}
    finally{if(current===this.session.generation.current)this.session.setBusy(false);}
  }

  async refreshHandoff(context:Pick<LoadingContext,'authenticated'|'failure'>&{blocked:boolean}):Promise<void> {
    const {identity,workspace,busy,pending}=this.session.getSnapshot(),access=context.authenticated||identity;
    if(!access||!workspace||busy||pending||context.blocked)throw new WorkspaceApiError(503);
    const current=this.session.generation.current,wid=workspace.id,revision=workspace.revision;
    this.session.setBusy(true);this.session.setError('');
    try {
      const [latest,latestTeam]=await Promise.all([this.api.read(access,wid),this.api.team(access)]);
      if(current!==this.session.generation.current)throw new WorkspaceApiError(401);
      if(latest.id!==wid||latest.revision<revision)throw new WorkspaceApiError(503);
      this.session.recovery.checkOwner(context.authenticated,latestTeam);
      this.session.setWorkspace(latest);this.session.setTeam(latestTeam);this.session.setConflict(false);
      this.session.setMessage('Current saved draft loaded. Your change request is preserved for review.');
    }catch(cause){if(current===this.session.generation.current)context.failure(cause);throw cause;}
    finally{if(current===this.session.generation.current)this.session.setBusy(false);}
  }

  async recheckRecovery(context:LoadingContext):Promise<void> {
    const {identity,workspace,busy,pending,recoveryState}=this.session.getSnapshot(),access=context.authenticated||identity;
    if(!access||busy)return;
    const current=this.session.generation.current;this.session.setBusy(true);
    try {
      const value=await this.api.team(access);if(current!==this.session.generation.current)return;
      this.session.recovery.checkOwner(context.authenticated,value);
      await context.prepareRecovery(value,workspace,current,!pending&&recoveryState==='failed');
      if(current!==this.session.generation.current)return;
      this.session.setTeam(value);this.session.setTeamDraft(previous=>previous??structuredClone(value.configuration));this.session.setError('');
    }catch(cause){if(current===this.session.generation.current){context.failure(cause);if(current===this.session.generation.current)this.session.setRecoveryState('failed');}}
    finally{if(current===this.session.generation.current)this.session.setBusy(false);}
  }

  async openSavedPrivate(workspaceId:string,context:Pick<LoadingContext,'authenticated'|'failure'>&{opened:(result:OpenedNotebook)=>Promise<void>}):Promise<void> {
    const {privateRecordingEntry,privateRecordingBusy,pending,busy}=this.session.getSnapshot();
    if(!context.authenticated||privateRecordingEntry||privateRecordingBusy||pending||busy)return;
    const current=this.session.generation.current;
    this.session.setBusy(true);
    try {
      const result=await this.api.openPrivateDraft(context.authenticated,workspaceId);
      if(current!==this.session.generation.current)return;
      await context.opened(result);
    }catch(cause){if(current===this.session.generation.current)context.failure(cause);}
    finally{if(current===this.session.generation.current)this.session.setBusy(false);}
  }

  async openPrivate(result:OpenedNotebook,context:Pick<LoadingContext,'authenticated'|'recoverAfterRead'>&{beforeOpen:()=>void;show:(current:number)=>void}):Promise<void> {
    context.beforeOpen();
    if(result.identity!==context.authenticated)throw new WorkspaceApiError(403);
    const {team,teamDraft}=this.session.getSnapshot();
    const preserveTeamDraft=!!team&&!!teamDraft&&teamConfigurationChanged(team.configuration,teamDraft);
    this.session.recovery.checkOwner(context.authenticated,result.team);
    const current=++this.session.generation.current;this.session.setBusy(false);
    this.session.setIdentity(result.identity);this.session.setWorkspace(result.workspace);this.session.setTeam(result.team);
    if(!preserveTeamDraft)this.session.setTeamDraft(structuredClone(result.team.configuration));
    this.session.setNote(result.workspace.entries.filter(entry=>entry.kind==='scratchpad').at(-1)?.content??'');
    this.session.setThought('');this.session.setEvidence('');this.session.setSource('');this.session.setPreviousModelRequest(null);
    this.session.setModelObservation(null);this.session.setReplacementDraft(null);this.session.setModelHashes({});
    context.show(current);await context.recoverAfterRead(result.team,result.workspace,current);
  }

  async catalog(context:Pick<LoadingContext,'authenticated'|'failure'>&{
    begin:()=>number;currentNavigation:()=>number;show:()=>void;refreshRecordings:()=>void;retry:()=>Promise<void>;
  }):Promise<void> {
    const {homeBusy}=this.session.getSnapshot();
    if(!context.authenticated||homeBusy)return;
    const token=context.begin(),current=this.session.generation.current;
    this.session.setHomeBusy(true);this.session.setError('');context.refreshRecordings();context.show();
    try {
      const result=await this.api.catalog(context.authenticated);
      if(current===this.session.generation.current&&token===context.currentNavigation()){this.session.setEncounters(result);context.show();}
    }catch(cause){if(current===this.session.generation.current&&token===context.currentNavigation())context.failure(cause,context.retry);}
    finally{if(current===this.session.generation.current)this.session.setHomeBusy(false);}
  }
}
