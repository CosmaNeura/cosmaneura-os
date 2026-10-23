import {teamConfigurationChanged} from '../team-configuration-diff';
import {normalizeTeamConfiguration,setupChange,validTeamConfiguration,type SetupProjection} from '../team-setup-request';
import {workspaceApi,WorkspaceApiError,requireRecoveryScope,type AuthenticatedWorkspaceIdentity,type ProviderTeam} from '../workspace-api';
import type {WorkspaceSession} from './workspace-session';
import type {SaveContext} from './saves';

export type TeamContext={authenticated?:AuthenticatedWorkspaceIdentity;failure:(cause:unknown)=>void};

/** Team edits and their exact review binding survive presentation changes. */
export class WorkspaceTeam {
  readonly exitAction:{current:(()=>void)|null}={current:null};
  constructor(private readonly session:WorkspaceSession,private readonly read:typeof workspaceApi.team=(...args)=>workspaceApi.team(...args)){}

  async refresh(context:TeamContext):Promise<void> {
    const access=context.authenticated||this.session.getSnapshot().identity;
    if(!access)throw new WorkspaceApiError(401);
    const current=this.session.generation.current;let value:ProviderTeam;
    try {
      value=await this.read(access);
      if(context.authenticated){const scope=requireRecoveryScope(value),journal=this.session.recovery.journal.current;if(journal&&journal.serverScope!==scope)throw new WorkspaceApiError(403);}
    }catch(cause){if(current===this.session.generation.current)context.failure(cause);throw cause;}
    if(current!==this.session.generation.current)throw new WorkspaceApiError(401);
    this.receive(value,context);
  }

  receive(value:ProviderTeam,context:Pick<TeamContext,'authenticated'>,projection?:SetupProjection):void {
    this.session.recovery.checkOwner(context.authenticated,value);
    const {team:previous,teamDraft}=this.session.getSnapshot();
    if(previous&&previous.revision>value.revision)return;
    if(previous&&previous.revision!==value.revision&&teamDraft&&JSON.stringify(teamDraft)!==JSON.stringify(previous.configuration)){
      this.session.setConflict(true);this.session.setError('Your saved team changed. Unsaved settings are preserved; load the latest team and compare before saving.');
    }
    this.session.setTeam(value);if(projection)this.session.setSetupProjection(projection);
    this.session.setTeamDraft(draft=>!draft||JSON.stringify(draft)===JSON.stringify(previous?.configuration)?structuredClone(value.configuration):draft);
  }

  save(context:SaveContext){
    const {team,teamDraft,setupApproval}=this.session.getSnapshot();
    if(!team||!teamDraft||!validTeamConfiguration(teamDraft))return;
    const approval=setupApproval?.revision===team.revision&&setupApproval.configurationKey===JSON.stringify(teamDraft)?setupApproval.review:null;
    if(setupChange(team.configuration,teamDraft)&&!approval){this.session.setError('Run the invented rehearsal and review the current draft before saving these capability changes.');return;}
    return this.session.saves.save({type:'team',body:{expected_revision:team.revision,idempotency_key:crypto.randomUUID(),configuration:normalizeTeamConfiguration(teamDraft),...(approval?{setup_review:approval}:{})}},context);
  }

  leave(settingsOpen:boolean,next:()=>void):void {
    const {team,teamDraft}=this.session.getSnapshot();
    if(settingsOpen&&team&&teamDraft&&teamConfigurationChanged(team.configuration,teamDraft)){
      this.exitAction.current=next;this.session.setConfirmTeamExit(true);return;
    }
    next();
  }
  finishExit():void {
    const next=this.exitAction.current;this.exitAction.current=null;this.session.setConfirmTeamExit(false);this.session.setTeamSaveExit(false);next?.();
  }
  async discardExit():Promise<void> {
    const {team,pending,busy}=this.session.getSnapshot();if(!team||pending?.type==='team'||busy)return;
    try {
      await this.session.recovery.scheduledDraftSave.current?.run();await this.session.recovery.journal.current?.value.persist('team',null);
      this.session.setTeamDraft(structuredClone(team.configuration));this.session.setSetupApproval(null);this.finishExit();
    }catch{this.session.setError('The local team draft could not be discarded. Your edits are retained.');}
  }
}
