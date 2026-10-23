import type {PrivateRecordingEntry,SessionSavedRecording,RecordingCatalog} from './recording-model';
import type {SetupProjection,SetupReview} from '../team-setup-request';
import type {ClinicalNoteShareReceipt,ShareSavedNoteInput} from '../clinical-team-contract';
import type {RecoveryOffer} from '../draft-journal';
import type {ModelOperation,PreviousModelRequest,ModelRequestObservation,HandoffRetryObservation} from '../model-work-request';
import type {
  AppendInput, FollowUpOperation, NoteOperation, TeamSaveInput, WorkspaceIdentity, Workspace, WorkspaceEncounter, ProviderTeam, TeamConfiguration,
} from '../workspace-api';

export type PendingSave = NoteOperation | FollowUpOperation | {type:'entry';body:AppendInput} | ModelOperation |
  {type:'clinicalNoteShare';body:ShareSavedNoteInput} |
  {type:'team';body:TeamSaveInput} |
  {type:'link';body:{expected_revision:number;idempotency_key:string;ticket_id:string}};

export type ConnectionFailure = {identity:WorkspaceIdentity;generation:number;message:string};
export type ReadRetry = {run:()=>Promise<void>};
export type ClinicalShareCheck={operation:Extract<PendingSave,{type:'clinicalNoteShare'}>;receipt:ClinicalNoteShareReceipt;owner:WorkspaceIdentity;generation:number};

export type ChiefNoteTask = {
  owner:import('../workspace-api').AuthenticatedWorkspaceIdentity;
  scope:string;generation:number;workspaceId:string;selection:ShareSavedNoteInput;content:string;
};

/** State whose lifetime belongs to the workspace, rather than its presentation. */
export type ReviewedTeamDraft={review:SetupReview;configurationKey:string;revision:number};

export type WorkspaceSessionState = {
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
