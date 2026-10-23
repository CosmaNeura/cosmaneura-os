import {WorkspaceClinical,type ClinicalDependencies} from './clinical';
import {WorkspaceLoading,type LoadingDependencies} from './loading';
import {WorkspaceTeam} from './team';
import type {StateUpdate, WorkspaceSessionSnapshot, WorkspaceSessionState} from './model';
import {WorkspaceLifecycle,type LifecycleDependencies} from './lifecycle';
import {WorkspaceRecovery,type RecoveryDependencies} from './recovery';
import {WorkspaceSaves,type SaveDependencies} from './saves';
import {WorkspaceModelActions,type ModelDependencies} from './model-actions';

/**
 * One owner for session state, shared by every presentation.
 *
 * Feature controllers are extracted into this owner incrementally. The epoch
 * supplements operation, route and authority guards; it does not replace them.
 */
export class WorkspaceSession {
  readonly recovery:WorkspaceRecovery;
  readonly lifecycle:WorkspaceLifecycle;
  readonly saves:WorkspaceSaves;
  readonly models:WorkspaceModelActions;
  readonly loading:WorkspaceLoading;
  readonly team:WorkspaceTeam;
  readonly clinical:WorkspaceClinical;
  constructor(deps:Partial<LifecycleDependencies>&{recovery?:Partial<RecoveryDependencies>;saves?:SaveDependencies;models?:ModelDependencies;loading?:LoadingDependencies;clinical?:ClinicalDependencies;teamRead?:ConstructorParameters<typeof WorkspaceTeam>[1]}={}) {
    this.lifecycle=new WorkspaceLifecycle(this,deps);
    this.recovery=new WorkspaceRecovery(this,deps.recovery);
    this.saves=new WorkspaceSaves(this,deps.saves);
    this.models=new WorkspaceModelActions(this,deps.models);
    this.loading=new WorkspaceLoading(this,deps.loading);
    this.team=new WorkspaceTeam(this,deps.teamRead);
    this.clinical=new WorkspaceClinical(this,deps.clinical);
  }
  private snapshot: WorkspaceSessionSnapshot = Object.freeze({
    clinicalPreparing:false,homeBusy:false,setupApproval:null,setupProjection:null,setupEpoch:0,confirmTeamExit:false,teamSaveExit:false,
    identity:null,connectionError:null,busy:false,pending:null,conflict:false,
    message:'',error:'',readRetry:null,clinicalShareCheck:null,modelObservation:null,replacementDraft:null,modelHashes:{},schedulingObservation:0,
    workspace:null,encounters:null,team:null,teamDraft:null,note:'',thought:'',evidence:'',source:'',previousModelRequest:null,recoveryOffers:[],recoveryState:'',recoveryEpoch:0,
  });
  private readonly listeners = new Set<()=>void>();

  // Kept as one stable cell while existing async closures move out of the view.
  readonly generation = {current:0};
  readonly activityNavigation:{current:AbortController|null}={current:null};

  readonly getSnapshot = ():WorkspaceSessionSnapshot => this.snapshot;
  readonly subscribe = (listener:()=>void):(()=>void) => {
    this.listeners.add(listener);
    return ()=>{this.listeners.delete(listener);};
  };

  readonly setClinicalPreparing = this.setter('clinicalPreparing');
  readonly setHomeBusy = this.setter('homeBusy');
  readonly setSetupApproval = this.setter('setupApproval');
  readonly setSetupProjection = this.setter('setupProjection');
  readonly setSetupEpoch = this.setter('setupEpoch');
  readonly setConfirmTeamExit = this.setter('confirmTeamExit');
  readonly setTeamSaveExit = this.setter('teamSaveExit');
  readonly setWorkspace = this.setter('workspace');
  readonly setEncounters = this.setter('encounters');
  readonly setTeam = this.setter('team');
  readonly setTeamDraft = this.setter('teamDraft');
  readonly setNote = this.setter('note');
  readonly setThought = this.setter('thought');
  readonly setEvidence = this.setter('evidence');
  readonly setSource = this.setter('source');
  readonly setPreviousModelRequest = this.setter('previousModelRequest');
  readonly setClinicalShareCheck = this.setter('clinicalShareCheck');
  readonly setModelObservation = this.setter('modelObservation');
  readonly setReplacementDraft = this.setter('replacementDraft');
  readonly setModelHashes = this.setter('modelHashes');
  readonly setSchedulingObservation = this.setter('schedulingObservation');
  readonly setRecoveryOffers = this.setter('recoveryOffers');
  readonly setRecoveryState = this.setter('recoveryState');
  readonly setRecoveryEpoch = this.setter('recoveryEpoch');
  readonly setIdentity = this.setter('identity');
  readonly setConnectionError = this.setter('connectionError');
  readonly setBusy = this.setter('busy');
  readonly setPending = this.setter('pending');
  readonly setConflict = this.setter('conflict');
  readonly setMessage = this.setter('message');
  readonly setReadRetry = this.setter('readRetry');

  readonly setError = (error:string):void => {
    this.patch({error,readRetry:null});
  };

  readonly invalidate = ():void => {this.generation.current++;};

  /** Withhold private view state; the journal retains exact unconfirmed work. */
  readonly clear = ():void => {
    this.team.exitAction.current=null;this.clinical.preparation.current=null;
    this.invalidate();this.activityNavigation.current?.abort();this.activityNavigation.current=null;
    this.recovery.close();this.recovery.nativeModelSettling.current=false;this.models.reset();
    this.patch({clinicalPreparing:false,homeBusy:false,setupApproval:null,setupProjection:null,confirmTeamExit:false,teamSaveExit:false,identity:null,connectionError:null,workspace:null,encounters:null,team:null,teamDraft:null,
      note:'',thought:'',evidence:'',source:'',previousModelRequest:null,recoveryOffers:[],recoveryState:'',
      pending:null,conflict:false,message:'',error:'',readRetry:null,busy:false,clinicalShareCheck:null,
      modelObservation:null,replacementDraft:null,modelHashes:{}});
  };

  private setter<K extends keyof WorkspaceSessionState>(key:K) {
    return (update:StateUpdate<WorkspaceSessionState[K]>):void => {
      const value=typeof update==='function'
        ? (update as (previous:WorkspaceSessionState[K])=>WorkspaceSessionState[K])(this.snapshot[key])
        : update;
      this.patch({[key]:value} as Pick<WorkspaceSessionState,K>);
    };
  }

  private patch(update:Partial<WorkspaceSessionState>):void {
    const keys=Object.keys(update) as (keyof WorkspaceSessionState)[];
    if(keys.every(key=>Object.is(this.snapshot[key],update[key])))return;
    this.snapshot=Object.freeze({...this.snapshot,...update});
    for(const listener of [...this.listeners])listener();
  }
}
