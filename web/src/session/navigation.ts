import {teamConfigurationChanged} from '../team-configuration-diff';
import {workspaceApi,WorkspaceApiError,botAddress,type ProviderTeam} from '../workspace-api';
import type {WorkspaceRoute} from '../workspace-route';
import type {WorkspaceSession} from './workspace-session';
import type {ConversationHost} from './conversations';
import type {LoadingContext,OpenedNotebook} from './loading';
export type NavigationDependencies={initialRoute?:WorkspaceRoute|null;read?:typeof workspaceApi.read;team?:typeof workspaceApi.team};
export type NavigationContext=LoadingContext&{
  viewNavigationLocked:boolean;connectionNavigationLocked:boolean;captureNavigationLocked:boolean;captureDraftLocked:boolean;
  minimizeRecording:()=>void;hasUnsavedWork:()=>boolean;
  replaceRoute:(route:WorkspaceRoute)=>void;
  openPrivateNotebook:(result:OpenedNotebook)=>Promise<void>;loadEncounters:()=>Promise<void>;
  currentTeam:{readonly current:ProviderTeam|null};
};

/** One route and action owner for every presentation; history is a host adapter. */
export class WorkspaceNavigation {
  readonly ready:{current:boolean};readonly applying={current:false};readonly sequence={current:0};
  private readonly read:typeof workspaceApi.read;private readonly readTeam:typeof workspaceApi.team;
  constructor(private readonly session:WorkspaceSession,deps:NavigationDependencies={}){
    this.ready={current:!deps.initialRoute};this.read=deps.read??((...args)=>workspaceApi.read(...args));this.readTeam=deps.team??((...args)=>workspaceApi.team(...args));
  }
  readonly route=():WorkspaceRoute=>{
    const {practiceOpen,settingsOpen,practicePage,workspace,selected,mobilePanel}=this.session.getSnapshot();
    return {page:practiceOpen?'work':settingsOpen?'settings':practicePage,...(practicePage==='notebook'&&workspace?{workspaceId:workspace.id,helper:selected,material:mobilePanel}:{})};
  };
  goHome(context:NavigationContext){
    const {settingsOpen,pending}=this.session.getSnapshot();
    if(pending){this.session.setError('Finish or check the current action before going back. Your text is retained.');return;}
    const {setPracticeOpen,setSettingsOpen,setPracticePage}=this.session;
    const {scheduledDraftSave}=this.session.recovery;
    const {viewNavigationLocked,captureNavigationLocked,captureDraftLocked}=context;
    this.sequence.current++;this.applying.current=false;this.ready.current=true;
    if(viewNavigationLocked||captureNavigationLocked||captureDraftLocked)return;
    context.minimizeRecording();
    void scheduledDraftSave.current?.run().catch(()=>{});
    this.session.team.leave(settingsOpen,()=>{this.clearPageError(context);setSettingsOpen(false);setPracticeOpen(false);setPracticePage('home');});
  }
  clearPageError(context:Pick<NavigationContext,'hasUnsavedWork'>){
    const {pending,conflict,recoveryState}=this.session.getSnapshot();
    const {setError}=this.session;
    const {hasUnsavedWork}=context;
    if(!pending&&!conflict&&recoveryState!=='failed'&&!hasUnsavedWork())setError('');
  }
  goNotebook(context:NavigationContext){
    const {settingsOpen}=this.session.getSnapshot();
    const {setPracticeOpen,setSettingsOpen,setPracticePage}=this.session;
    this.session.team.leave(settingsOpen,()=>{this.sequence.current++;this.applying.current=false;this.ready.current=true;this.clearPageError(context);context.minimizeRecording();setSettingsOpen(false);setPracticeOpen(false);setPracticePage('notebook');});
  }
  async openSettings(context:NavigationContext,entry:'home'|'connections'|'core'='home'){
    const {team,teamDraft,settingsOpen,settingsEntry,identity}=this.session.getSnapshot();
    const {generation,setError,setBusy,setTeam,setTeamDraft,setSettingsEntry,setPracticeOpen,setSettingsOpen}=this.session;
    const {authenticated,viewNavigationLocked,recoverAfterRead,failure}=context;
    if (viewNavigationLocked) return;
    this.clearPageError(context);
    this.sequence.current++;this.applying.current=false;this.ready.current=true;
    if(settingsOpen&&entry!==settingsEntry&&team&&teamDraft&&teamConfigurationChanged(team.configuration,teamDraft)){this.session.team.leave(settingsOpen,()=>{setSettingsEntry(entry);setPracticeOpen(false);setSettingsOpen(true);});return;}
    context.minimizeRecording();
    setSettingsEntry(entry); setPracticeOpen(false); setSettingsOpen(true);
    if (team && teamDraft) return;
    const access = authenticated || identity;
    if (!access) return;
    const current = generation.current; setBusy(true); setError("");
    try {
      const value = await this.readTeam(access);
      if (current !== generation.current) return;
      setTeam(value); setTeamDraft(structuredClone(value.configuration));
      await recoverAfterRead(value, null, current);
    } catch (cause) { if (current === generation.current) failure(cause,()=>this.openSettings(context,entry)); }
    finally { if (current === generation.current) setBusy(false); }
  }
  /** Browser and native history are user navigation, never a draft-restore bypass. */
  async followHistory(target:WorkspaceRoute,context:NavigationContext,conversation:ConversationHost|null):Promise<boolean>{
    const state=this.session.getSnapshot();
    const reject=()=>{this.session.setError('Finish or check the current action before going back. Your text is retained.');context.replaceRoute(this.route());return false;};
    if(state.busy||state.pending||state.conversationBusy||state.conflict||state.clinicalPreparing||state.recordingTransition||state.researchPending||state.handoffReviewPending||state.recoveryState==='failed'||state.recoveryState==='saving'||state.recoveryOffers.length||
      context.viewNavigationLocked||context.captureNavigationLocked||context.captureDraftLocked)return reject();
    if(state.settingsOpen&&target.page!=='settings'&&state.team&&state.teamDraft&&teamConfigurationChanged(state.team.configuration,state.teamDraft)){
      context.replaceRoute(this.route());
      this.session.team.leave(true,()=>void this.followHistory(target,context,conversation));
      return false;
    }
    const bot=target.helper??state.selected;
    const changesConversation=target.page==='notebook'&&(target.workspaceId!==state.workspace?.id||bot!==state.selected);
    if(changesConversation&&this.session.presentation.enabled){
      if(!target.workspaceId||!conversation||!conversation.current()||conversation.blocked())return reject();
      const opened=await this.session.conversations.open(target.workspaceId,bot,{...conversation,restoreRejectedNavigation:()=>context.replaceRoute(this.route())});
      const live=this.session.getSnapshot();
      if(!opened){context.replaceRoute(this.route());return false;}
      if(!conversation.current()||live.workspace?.id!==target.workspaceId||live.selected!==bot||live.practicePage!=='notebook'||live.settingsOpen||live.practiceOpen){context.replaceRoute(this.route());return false;}
      if(target.material)await this.applyRoute({...target,helper:bot},context);
      return true;
    }
    await this.applyRoute(target,context);
    // A guarded legacy route may intentionally leave the current screen in place.
    context.replaceRoute(this.route());
    return true;
  }
  async applyRoute(target:WorkspaceRoute,context:NavigationContext){
    const {workspace,team,teamDraft,settingsOpen,busy,pending}=this.session.getSnapshot();
    const {generation,setError,setPracticeOpen,setSettingsOpen,setPracticePage,setPracticeOpened,setSelected,setMobilePanel,setPanel}=this.session;
    const {scheduledDraftSave}=this.session.recovery;
    const {authenticated,connectionNavigationLocked,captureNavigationLocked,captureDraftLocked,failure,openPrivateNotebook,loadEncounters,currentTeam}=context;
    if(settingsOpen&&target.page!=='settings'&&team&&teamDraft&&teamConfigurationChanged(team.configuration,teamDraft)){context.replaceRoute(this.route());this.session.team.leave(settingsOpen,()=>void this.applyRoute(target,context));return;}
    const routeToken=++this.sequence.current;this.applying.current=true;let current=generation.current;
    try{
      if(target.page==='notebook'&&target.workspaceId!==workspace?.id){
        if(!authenticated||busy||pending||connectionNavigationLocked||captureNavigationLocked||captureDraftLocked)throw new Error('Retained operation');
        await scheduledDraftSave.current?.run();
        if(current!==generation.current||routeToken!==this.sequence.current)return;
        const latest=await this.read(authenticated,target.workspaceId!);
        if(current!==generation.current||routeToken!==this.sequence.current)return;
        const latestTeam=await this.readTeam(authenticated);if(current!==generation.current||routeToken!==this.sequence.current)return;
        // Opening installs its workspace generation synchronously, then waits
        // for draft recovery. A later account or navigation must still win.
        const opening=openPrivateNotebook({identity:authenticated,workspace:latest,team:latestTeam});
        current=generation.current;await opening;
        if(current!==generation.current||routeToken!==this.sequence.current)return;
      }
      if(target.page==='home')this.goHome(context);
      else if(target.page==='visits')await loadEncounters();
      else if(target.page==='settings')await this.openSettings(context);
      else if(target.page==='work'){setSettingsOpen(false);setPracticeOpen(true);setPracticeOpened(true);}
      else if(target.page==='notebook'){
        setPracticePage('notebook');setPracticeOpen(false);setSettingsOpen(false);
        if(target.helper&&(currentTeam.current??team)?.configuration.bots.some(bot=>botAddress(bot)===target.helper))setSelected(target.helper);
        if(target.material){setMobilePanel(target.material);if(target.material!=='Conversation')setPanel(target.material);}
      }
    }catch(cause){if(current!==generation.current||routeToken!==this.sequence.current)return;setError('Finish or recover the current action before opening another notebook. Your text is retained.');
      if(cause instanceof WorkspaceApiError)failure(cause);context.replaceRoute(this.route());}
    finally{if(routeToken===this.sequence.current){this.applying.current=false;this.ready.current=true;}}
  }
}
