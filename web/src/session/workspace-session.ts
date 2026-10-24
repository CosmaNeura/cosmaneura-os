import {WorkspacePresentationPreference,type PresentationOptions} from './presentation';
import {WorkspaceConversations} from './conversations';
import {WorkspaceInboxPreferences} from './inbox-preferences';
import {WorkspaceComposer} from './composer';
import {WorkspaceActivity,type ActivityDependencies} from './activity';
import {WorkspaceSources,type SourceDependencies} from './sources';
import {WorkspaceObservations} from './observations';
import {WorkspaceReview} from './review';
import {WorkspaceNavigation,type NavigationDependencies} from './navigation';
import {WorkspaceRecording,type RecordingDependencies} from './recording';
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
  readonly recording:WorkspaceRecording;
  readonly navigation:WorkspaceNavigation;
  readonly review:WorkspaceReview;
  readonly observations:WorkspaceObservations;
  readonly sources:WorkspaceSources;
  readonly activity:WorkspaceActivity;
  readonly composer:WorkspaceComposer;
  readonly presentation:WorkspacePresentationPreference;
  readonly conversations:WorkspaceConversations;
  readonly inboxPreferences:WorkspaceInboxPreferences;
  constructor(deps:Partial<LifecycleDependencies>&{presentation?:PresentationOptions;conversations?:ConstructorParameters<typeof WorkspaceConversations>[1];conversationRead?:ConstructorParameters<typeof WorkspaceConversations>[2];recovery?:Partial<RecoveryDependencies>;saves?:SaveDependencies;models?:ModelDependencies;loading?:LoadingDependencies;clinical?:ClinicalDependencies;recording?:RecordingDependencies;navigation?:NavigationDependencies;initialPage?:WorkspaceSessionState['practicePage'];observationRead?:ConstructorParameters<typeof WorkspaceObservations>[1];sources?:SourceDependencies;activity?:ActivityDependencies;teamRead?:ConstructorParameters<typeof WorkspaceTeam>[1]}={}) {
    this.lifecycle=new WorkspaceLifecycle(this,deps);
    this.recovery=new WorkspaceRecovery(this,deps.recovery);
    this.saves=new WorkspaceSaves(this,deps.saves);
    this.models=new WorkspaceModelActions(this,deps.models);
    this.loading=new WorkspaceLoading(this,deps.loading);
    this.team=new WorkspaceTeam(this,deps.teamRead);
    this.clinical=new WorkspaceClinical(this,deps.clinical);
    this.recording=new WorkspaceRecording(this,deps.recording);
    this.navigation=new WorkspaceNavigation(this,deps.navigation);
    this.review=new WorkspaceReview(this);
    this.observations=new WorkspaceObservations(this,deps.observationRead);
    this.sources=new WorkspaceSources(this,deps.sources);
    this.activity=new WorkspaceActivity(this,deps.activity);
    this.composer=new WorkspaceComposer(this);
    this.presentation=new WorkspacePresentationPreference(this,deps.presentation);
    this.conversations=new WorkspaceConversations(this,deps.conversations,deps.conversationRead);
    this.inboxPreferences=new WorkspaceInboxPreferences(deps.conversationRead);
    this.setPracticePage(deps.initialPage??'visits');
  }
  private snapshot: WorkspaceSessionSnapshot = Object.freeze({
    presentationPreference:null,presentationError:'',conversationInbox:null,conversationLoading:false,conversationError:'',conversationBusy:false,recordingTransition:false,researchPending:false,
    activityProof:null,activityBusy:false,activityContextBusy:false,activityContextError:'',activityAttempt:0,
    selectedSource:null,faxSourceOffer:null,providerFaxSourceOffer:null,faxSourceBusy:false,providerFaxSourceBusy:false,
    phoneNoteTask:null,reviewHandoffId:null,handoffReviewPending:false,selectedResult:null,savedResearchChat:false,
    settingsOpen:false,practicePage:'visits',practiceOpen:false,practiceOpened:false,selected:'visit_prep',panel:'Notebook',mobilePanel:'Conversation',stage:'Before',entryIntent:null,researchEntry:false,settingsEntry:'home',inboxSelection:null,
    privateRecordingBusy:false,privateRecordingEntry:null,savedRecordingEntry:null,savedRecordingNotebook:null,privateRecordings:null,privateRecordingListEpoch:0,privateRecordingRequest:0,
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

  readonly setPresentationPreference = this.setter('presentationPreference');
  readonly setPresentationError = this.setter('presentationError');
  readonly setConversationInbox = this.setter('conversationInbox');
  readonly setConversationLoading = this.setter('conversationLoading');
  readonly setConversationError = this.setter('conversationError');
  readonly setConversationBusy = this.setter('conversationBusy');
  readonly setRecordingTransition = this.setter('recordingTransition');
  readonly setResearchPending = this.setter('researchPending');
  readonly setActivityProof = this.setter('activityProof');
  readonly setActivityBusy = this.setter('activityBusy');
  readonly setActivityContextBusy = this.setter('activityContextBusy');
  readonly setActivityContextError = this.setter('activityContextError');
  readonly setActivityAttempt = this.setter('activityAttempt');
  readonly setSelectedSource = this.setter('selectedSource');
  readonly setFaxSourceOffer = this.setter('faxSourceOffer');
  readonly setProviderFaxSourceOffer = this.setter('providerFaxSourceOffer');
  readonly setFaxSourceBusy = this.setter('faxSourceBusy');
  readonly setProviderFaxSourceBusy = this.setter('providerFaxSourceBusy');
  readonly setPhoneNoteTask = this.setter('phoneNoteTask');
  readonly setReviewHandoffId = this.setter('reviewHandoffId');
  readonly setHandoffReviewPending = this.setter('handoffReviewPending');
  readonly setSelectedResult = this.setter('selectedResult');
  readonly setSavedResearchChat = this.setter('savedResearchChat');
  readonly setSettingsOpen = this.setter('settingsOpen');
  readonly setPracticePage = this.setter('practicePage');
  readonly setPracticeOpen = this.setter('practiceOpen');
  readonly setPracticeOpened = this.setter('practiceOpened');
  readonly setSelected = this.setter('selected');
  readonly setPanel = this.setter('panel');
  readonly setMobilePanel = this.setter('mobilePanel');
  readonly setStage = this.setter('stage');
  readonly setEntryIntent = this.setter('entryIntent');
  readonly setResearchEntry = this.setter('researchEntry');
  readonly setSettingsEntry = this.setter('settingsEntry');
  readonly setInboxSelection = this.setter('inboxSelection');
  readonly setPrivateRecordingBusy = this.setter('privateRecordingBusy');
  readonly setPrivateRecordingEntry = this.setter('privateRecordingEntry');
  readonly setSavedRecordingEntry = this.setter('savedRecordingEntry');
  readonly setSavedRecordingNotebook = this.setter('savedRecordingNotebook');
  readonly setPrivateRecordings = this.setter('privateRecordings');
  readonly setPrivateRecordingListEpoch = this.setter('privateRecordingListEpoch');
  readonly setPrivateRecordingRequest = this.setter('privateRecordingRequest');
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
    this.review.returnTarget.current=null;this.review.conversationReturn.current=null;
    this.composer.reset();this.conversations.reset();this.inboxPreferences.clear();
    this.team.exitAction.current=null;this.clinical.preparation.current=null;
    this.invalidate();this.activityNavigation.current?.abort();this.activityNavigation.current=null;
    this.recovery.close();this.recovery.nativeModelSettling.current=false;this.models.reset();
    // The recorder descriptor remains mounted long enough to stop/retain audio.
    // Its generation and journal checks already deny access synchronously.
    this.patch({conversationInbox:null,conversationLoading:false,conversationError:'',conversationBusy:false,researchPending:false,
      activityProof:null,activityBusy:false,activityContextBusy:false,activityContextError:'',
      selectedSource:null,faxSourceOffer:null,providerFaxSourceOffer:null,faxSourceBusy:false,providerFaxSourceBusy:false,
      phoneNoteTask:null,reviewHandoffId:null,handoffReviewPending:false,selectedResult:null,savedResearchChat:false,
      settingsOpen:false,practiceOpen:false,practiceOpened:false,entryIntent:null,researchEntry:false,inboxSelection:null,
      savedRecordingEntry:null,savedRecordingNotebook:null,privateRecordings:null,
      clinicalPreparing:false,homeBusy:false,setupApproval:null,setupProjection:null,confirmTeamExit:false,teamSaveExit:false,identity:null,connectionError:null,workspace:null,encounters:null,team:null,teamDraft:null,
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
