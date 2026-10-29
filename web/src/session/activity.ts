import {assertCurrentDesktopSession} from '../workspace-auth-headers';
import {accountIdentityApi} from '../account-identity-api';
import {validActivityContext,type AiActivityContext,type AiActivitySelection} from '../model-activity-contract';
import {DraftStoreError} from '../draft-store';
import {editorAddress,type DraftJournal,type RecoveryOffer} from '../draft-journal';
import {workspaceApi,WorkspaceApiError,requireRecoveryScope,validRecoveryScope,botAddress,type AuthenticatedWorkspaceIdentity,type Workspace,type ProviderTeam,type TeamConfiguration} from '../workspace-api';
import type {WorkspaceSession} from './workspace-session';
export type ActivityProof={identity:AuthenticatedWorkspaceIdentity;journal:DraftJournal;generation:number;context:AiActivityContext};
export type ActivityLive={authenticated:AuthenticatedWorkspaceIdentity|undefined;editorJournal:DraftJournal|undefined;editorScope:string|null|undefined;
  settingsOpen:boolean;practiceOpen:boolean;activityContext:AiActivityContext|null;activityBlocked:boolean;workspace:Workspace|null;note:string};
export type ActivityContext={authenticated?:AuthenticatedWorkspaceIdentity;activityContext:AiActivityContext|null;activityEnabled:boolean;
  accountAccess:{authorize:()=>Promise<void>}|null|undefined;editorJournal:DraftJournal|undefined;editorScope:string|null|undefined;
  currentTeam:{current:ProviderTeam|null};currentTeamDraft:{current:TeamConfiguration|null};hasUnsavedWork:()=>boolean;
  failure:(cause:unknown)=>void;resetCapture:()=>void};
export type ActivityDependencies={read?:typeof workspaceApi.read;team?:typeof workspaceApi.team;accountRead?:typeof accountIdentityApi.read};

/** Optional activity navigation remains a read-only, freshly authorized path. */
export class WorkspaceActivity {
  readonly live:{current:ActivityLive}={current:{authenticated:undefined,editorJournal:undefined,editorScope:undefined,settingsOpen:false,practiceOpen:false,activityContext:null,activityBlocked:true,workspace:null,note:''}};
  private readonly read:typeof workspaceApi.read;private readonly team:typeof workspaceApi.team;private readonly accountRead:typeof accountIdentityApi.read;
  constructor(private readonly session:WorkspaceSession,deps:ActivityDependencies={}){
    this.read=deps.read??((...args)=>workspaceApi.read(...args));this.team=deps.team??((...args)=>workspaceApi.team(...args));this.accountRead=deps.accountRead??((...args)=>accountIdentityApi.read(...args));
  }
  watch(host:ActivityContext){
    const {settingsOpen,practiceOpen}=this.session.getSnapshot();
    const {generation,setActivityProof,setActivityContextError,setActivityContextBusy}=this.session;
    const activityLive=this.live;
    const {authenticated,activityEnabled,accountAccess,editorJournal,editorScope,failure}=host;
    let cancelled=false;const current=generation.current,controller=new AbortController();
    setActivityProof(null);setActivityContextError('');setActivityContextBusy(false);
    const isCurrent=()=>!cancelled && current===generation.current && activityLive.current.authenticated===authenticated &&
      activityLive.current.editorJournal===editorJournal && activityLive.current.editorScope===editorScope;
    if(activityEnabled && authenticated && accountAccess && editorJournal && validRecoveryScope(editorScope) && settingsOpen && !practiceOpen){
      setActivityContextBusy(true);
      void(async()=>{
        await accountAccess.authorize();if(!isCurrent())return;
        const account=await this.accountRead(authenticated,controller.signal);if(!isCurrent())return;
        if(account.recovery_scope!==editorScope)throw new WorkspaceApiError(403);
        const context={box_id:account.box_id,owner_id:account.actor_id,recovery_scope:account.recovery_scope};
        if(!validActivityContext(context))throw new WorkspaceApiError(503);
        setActivityProof({identity:authenticated,journal:editorJournal,generation:current,context});
      })().catch(cause=>{if(!isCurrent())return;
        setActivityContextError('AI activity access could not be checked. Your current drafts are retained.');
        if(cause instanceof WorkspaceApiError && [401,403,404,426].includes(cause.status))failure(cause);
      }).finally(()=>{if(isCurrent())setActivityContextBusy(false);});
    }
    return()=>{cancelled=true;controller.abort();};
  }
  async open(selection:AiActivitySelection,host:ActivityContext){
    const activityLive=this.live;
    const {workspace}=this.session.getSnapshot();
    const {generation,activityNavigation,setError,setConflict,setTeam,setTeamDraft,setIdentity,setNote,setThought,setEvidence,setSource,setPreviousModelRequest,setModelObservation,setReplacementDraft,setModelHashes,setSelectedSource,setStage,setPanel,setRecoveryOffers,setRecoveryEpoch,setWorkspace,setSelected,setSavedResearchChat,setSelectedResult,setMobilePanel,setSettingsOpen,setPracticeOpen,setPracticePage,setRecoveryState}=this.session;
    const {authenticated,activityContext,editorJournal,currentTeam,currentTeamDraft,hasUnsavedWork,failure}=host;
    const auth=authenticated,context=activityContext,active=editorJournal,current=generation.current;
    const origin=workspace?.id;
    if(!auth || !context || !active)throw new WorkspaceApiError(403);
    const navigation=new AbortController();activityNavigation.current?.abort();activityNavigation.current=navigation;
    const sameAccount=()=>current===generation.current && activityLive.current.authenticated===auth &&
      activityLive.current.editorJournal===active && activityLive.current.editorScope===context.recovery_scope;
    const check=()=>{
      if(navigation.signal.aborted)throw new WorkspaceApiError(503);
      if(!sameAccount() || activityLive.current.activityContext!==context)throw new WorkspaceApiError(403);
      try{assertCurrentDesktopSession(auth);}catch{throw new WorkspaceApiError(401);}
      const view=activityLive.current;
      if(!view.settingsOpen || view.practiceOpen || view.activityBlocked || view.workspace?.id!==origin)throw new WorkspaceApiError(503);
      if(selection.workspace_id!==origin && hasUnsavedWork()){
        setError('Save or recover unfinished work before opening another encounter. Your current text and requests are retained.');
        throw new WorkspaceApiError(503);
      }
    };
    const authorize=async()=>{
      check();const latestTeam=await this.team(auth,navigation.signal);check();
      if(requireRecoveryScope(latestTeam)!==context.recovery_scope)throw new WorkspaceApiError(403);
      const account=await this.accountRead(auth,navigation.signal);check();
      if(account.box_id!==context.box_id || account.actor_id!==context.owner_id || account.recovery_scope!==context.recovery_scope)throw new WorkspaceApiError(403);
      return latestTeam;
    };
    const existingEntry=(value:Workspace)=>{
      if(value.id!==selection.workspace_id || value.appointment_id!==selection.appointment_id)throw new WorkspaceApiError(403);
      const entry=value.entries.find(item=>item.id===selection.entry_id);
      if(!entry || !['conversation','handoff_result'].includes(entry.kind))throw new WorkspaceApiError(503);
      return entry;
    };
    try{
      let latestTeam=await authorize();
      let latest=await this.read(auth,selection.workspace_id,navigation.signal);check();existingEntry(latest);
      const offers:RecoveryOffer[]=[];
      if(selection.workspace_id!==origin){
        const addresses=[`workspace:${latest.id}`,editorAddress(latest.id,'private-note'),editorAddress(latest.id,'core-note'),editorAddress(latest.id,'transcript')];
        for(const address of addresses){
          const draft=await active.load(address);check();
          if(draft && (draft.kind==='team'||draft.kind==='workspace'))offers.push({address,draft});
        }
        // Device reads confer no authority. Recheck the account and source after them.
        latestTeam=await authorize();latest=await this.read(auth,selection.workspace_id,navigation.signal);check();
      }
      const entry=existingEntry(latest);
      const finalAccount=await this.accountRead(auth,navigation.signal);check();
      if(finalAccount.box_id!==context.box_id || finalAccount.actor_id!==context.owner_id || finalAccount.recovery_scope!==context.recovery_scope)throw new WorkspaceApiError(403);
      const before=currentTeam.current,draft=currentTeamDraft.current;
      if(before && latestTeam.revision<before.revision)throw new WorkspaceApiError(503);
      if(before && draft && latestTeam.revision!==before.revision && JSON.stringify(draft)!==JSON.stringify(before.configuration)){
        setConflict(true);setError('Your saved team changed. Unsaved settings are retained; load the latest team and compare before opening activity.');
        throw new WorkspaceApiError(503);
      }
      const member=latestTeam.members.find(item=>entry.reply?.agent_id
        ? item.agent_id===entry.reply.agent_id && item.role===entry.reply.role
        : !item.instance_id && item.role===entry.reply?.role);
      const address=entry.model_request?.bot.address ?? (member ? botAddress(member) : undefined);
      if(!address || !latestTeam.configuration.bots.some(bot=>botAddress(bot)===address))throw new WorkspaceApiError(503);
      if(selection.workspace_id===origin && latest.revision<(activityLive.current.workspace?.revision??0))throw new WorkspaceApiError(503);
      check();currentTeam.current=latestTeam;setTeam(latestTeam);
      if(!draft || JSON.stringify(draft)===JSON.stringify(before?.configuration)){
        currentTeamDraft.current=structuredClone(latestTeam.configuration);setTeamDraft(currentTeamDraft.current);
      }
      if(selection.workspace_id!==origin){
        setIdentity(auth);setNote(latest.entries.filter(item=>item.kind==='scratchpad').at(-1)?.content??'');
        setThought('');setEvidence('');setSource('');setPreviousModelRequest(null);setModelObservation(null);setReplacementDraft(null);setModelHashes({});
        host.resetCapture();setSelectedSource(null);setStage('Before');setPanel('Notebook');
        setRecoveryOffers(previous=>[...previous,...offers]);setRecoveryEpoch(value=>value+1);
      }else{
        const savedBefore=activityLive.current.workspace?.entries.filter(item=>item.kind==='scratchpad').at(-1)?.content??'';
        const savedAfter=latest.entries.filter(item=>item.kind==='scratchpad').at(-1)?.content??'';
        if(savedBefore!==savedAfter && activityLive.current.note!==savedBefore)setConflict(true);
        else if(activityLive.current.note===savedBefore)setNote(savedAfter);
      }
      setWorkspace(latest);setSelected(address);if(entry.reply?.role==='research'||entry.model_request?.bot.role==='research')setSavedResearchChat(true);setSelectedResult(entry.id);setMobilePanel('Conversation');setSettingsOpen(false);setPracticeOpen(false);setPracticePage('notebook');setError('');
    }catch(cause){
      if(sameAccount() && cause instanceof WorkspaceApiError && [401,403,404,426].includes(cause.status))failure(cause);
      else if(sameAccount() && cause instanceof DraftStoreError)setRecoveryState('failed');
      throw cause;
    }finally{navigation.abort();if(activityNavigation.current===navigation)activityNavigation.current=null;}
  }
}
