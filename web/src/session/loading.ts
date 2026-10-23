import {teamConfigurationChanged} from '../team-configuration-diff';
import {workspaceApi,WorkspaceApiError,type AuthenticatedWorkspaceIdentity,type ProviderTeam,type Workspace} from '../workspace-api';
import type {WorkspaceSession} from './workspace-session';

type LoadingApi=Pick<typeof workspaceApi,'read'|'team'|'catalog'>;
export type LoadingDependencies=Partial<LoadingApi>;
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

/** Reads publish only inside the initiating workspace and navigation lifetime. */
export class WorkspaceLoading {
  private readonly api:LoadingApi;
  constructor(private readonly session:WorkspaceSession,deps:LoadingDependencies={}) {
    this.api={read:(...args)=>workspaceApi.read(...args),team:(...args)=>workspaceApi.team(...args),catalog:(...args)=>workspaceApi.catalog(...args),...deps};
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

  async openPrivate(result:OpenedNotebook,context:Pick<LoadingContext,'authenticated'|'recoverAfterRead'>&{beforeOpen:()=>void;show:(current:number)=>void}):Promise<void> {
    context.beforeOpen();
    if(result.identity!==context.authenticated)throw new WorkspaceApiError(403);
    const {team,teamDraft}=this.session.getSnapshot();
    const preserveTeamDraft=!!team&&!!teamDraft&&teamConfigurationChanged(team.configuration,teamDraft);
    const current=++this.session.generation.current;this.session.recovery.checkOwner(context.authenticated,result.team);
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
