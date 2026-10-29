import type {Presentation} from './presentation';
import type {ConversationInbox} from '../conversations-api';
import type {ActivityProof} from './activity';
import type {EFaxSourceOffer} from '../efax-inbound-source-api';
import type {FaxSourceOffer} from '../fax-inbound-source-api';
import type {EFaxPending} from '../efax-inbound-api';
import type {FaxPending} from '../fax-inbound-api';
import type {InboxDraftSelection} from '../inbox-analysis-contract';
import type {PrivateRecordingEntry,SessionSavedRecording,RecordingCatalog} from './recording-model';
import type {SetupProjection,SetupReview} from '../team-setup-request';
import type {ClinicalNoteShareReceipt,ShareSavedNoteInput} from '../clinical-team-contract';
import type {RecoveryOffer} from '../draft-journal';
import type {ModelOperation,PreviousModelRequest,ModelRequestObservation,HandoffRetryObservation} from '../model-work-request';
import type {
  AuthenticatedWorkspaceIdentity, AppendInput, FollowUpOperation, NoteOperation, TeamSaveInput, WorkspaceIdentity, Workspace, WorkspaceEncounter, ProviderTeam, TeamConfiguration,
} from '../workspace-api';

export type PendingSave = NoteOperation | FollowUpOperation | {type:'entry';body:AppendInput} | ModelOperation |
  {type:'clinicalNoteShare';body:ShareSavedNoteInput} |
  {type:'team';body:TeamSaveInput} |
  {type:'link';body:{expected_revision:number;idempotency_key:string;ticket_id:string}};

export type ConnectionFailure = {identity:WorkspaceIdentity;generation:number;message:string};
export type ReadRetry = {run:()=>Promise<void>;label?:string};
export type ClinicalShareCheck={operation:Extract<PendingSave,{type:'clinicalNoteShare'}>;receipt:ClinicalNoteShareReceipt;owner:WorkspaceIdentity;generation:number};

export type ChiefNoteTask = {
  owner:import('../workspace-api').AuthenticatedWorkspaceIdentity;
  scope:string;generation:number;workspaceId:string;selection:ShareSavedNoteInput;content:string;
};

/** State whose lifetime belongs to the workspace, rather than its presentation. */
export type ReviewedTeamDraft={review:SetupReview;configurationKey:string;revision:number};

export type WorkspaceSessionState = {
  presentationPreference:Presentation|null;
  presentationError:string;
  conversationInbox:ConversationInbox|null;
  conversationLoading:boolean;
  conversationError:string;
  conversationBusy:boolean;
  recordingTransition:boolean;
  researchPending:boolean;
  activityProof:ActivityProof|null;
  activityBusy:boolean;
  activityContextBusy:boolean;
  activityContextError:string;
  activityAttempt:number;
  selectedSource:string|null;
  faxSourceOffer:{identity:AuthenticatedWorkspaceIdentity;generation:number;workspaceId:string;document:EFaxSourceOffer;request:Extract<EFaxPending,{kind:'acquire'}>}|null;
  providerFaxSourceOffer:{identity:AuthenticatedWorkspaceIdentity;generation:number;workspaceId:string;document:FaxSourceOffer;request:Extract<FaxPending,{kind:'acquire'}>}|null;
  calendarImportReview:{identity:AuthenticatedWorkspaceIdentity;generation:number;workspaceId:string;open:boolean;origin:'conversation'|'sources'|'connections'}|null;
  ehrReview:{identity:AuthenticatedWorkspaceIdentity;generation:number;workspaceId:string;open:boolean;origin:'conversation'|'sources'|'connections'}|null;
  faxSourceBusy:boolean;
  providerFaxSourceBusy:boolean;
  phoneNoteTask:ChiefNoteTask|null;
  reviewHandoffId:string|null;
  handoffReviewPending:boolean;
  selectedResult:string|null;
  savedResearchChat:boolean;
  settingsOpen:boolean;
  practicePage:'home'|'visits'|'notebook';
  practiceOpen:boolean;
  practiceOpened:boolean;
  selected:string;
  panel:string;
  mobilePanel:string;
  stage:string;
  entryIntent:'record'|'recording'|'chief'|'fax'|null;
  researchEntry:boolean;
  settingsEntry:'home'|'connections'|'core'|'scheduling'|'microsoft'|'google'|'ehr';
  inboxSelection:InboxDraftSelection|null;
  privateRecordingBusy:boolean;
  privateRecordingEntry:PrivateRecordingEntry|null;
  savedRecordingEntry:SessionSavedRecording|null;
  savedRecordingNotebook:SessionSavedRecording|null;
  privateRecordings:RecordingCatalog|null;
  privateRecordingListEpoch:number;
  privateRecordingRequest:number;
  clinicalPreparing:boolean;
  homeBusy:boolean;
  setupApproval:ReviewedTeamDraft|null;
  setupProjection:SetupProjection|null;
  setupEpoch:number;
  confirmTeamExit:boolean;
  teamSaveExit:boolean;
  workspace: Workspace|null;
  encounters: WorkspaceEncounter[]|null;
  team: ProviderTeam|null;
  teamDraft: TeamConfiguration|null;
  note: string;
  thought: string;
  evidence: string;
  source: string;
  previousModelRequest: PreviousModelRequest|null;
  clinicalShareCheck:ClinicalShareCheck|null;
  modelObservation:{receipt:ModelRequestObservation|HandoffRetryObservation;observedAt:string}|null;
  replacementDraft:{content:string;role:string;acknowledged:boolean}|null;
  modelHashes:Record<string,string>;
  schedulingObservation:number;
  recoveryOffers: RecoveryOffer[];
  recoveryState: ''|'saving'|'saved'|'failed';
  recoveryEpoch: number;
  identity: WorkspaceIdentity|null;
  connectionError: ConnectionFailure|null;
  busy: boolean;
  pending: PendingSave|null;
  conflict: boolean;
  message: string;
  error: string;
  readRetry: ReadRetry|null;
};

export type WorkspaceSessionSnapshot = Readonly<WorkspaceSessionState>;
export type StateUpdate<T> = T|((previous:T)=>T);

export type ConfirmedClinicalModelContext={workspace:Workspace;team:ProviderTeam;identity:WorkspaceIdentity;
  isCurrent:()=>boolean;canSend:()=>boolean;composer?:{content:string;editVersion:number};onDispatch?:()=>void};
