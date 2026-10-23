import type {ShareSavedNoteInput} from '../clinical-team-contract';
import type {RecoveryOffer} from '../draft-journal';
import type {ModelOperation,PreviousModelRequest} from '../model-work-request';
import type {
  AppendInput, FollowUpOperation, NoteOperation, TeamSaveInput, WorkspaceIdentity, Workspace, WorkspaceEncounter, ProviderTeam, TeamConfiguration,
} from '../workspace-api';

export type PendingSave = NoteOperation | FollowUpOperation | {type:'entry';body:AppendInput} | ModelOperation |
  {type:'clinicalNoteShare';body:ShareSavedNoteInput} |
  {type:'team';body:TeamSaveInput} |
  {type:'link';body:{expected_revision:number;idempotency_key:string;ticket_id:string}};

export type ConnectionFailure = {identity:WorkspaceIdentity;generation:number;message:string};
export type ReadRetry = {run:()=>Promise<void>};

export type ChiefNoteTask = {
  owner:import('../workspace-api').AuthenticatedWorkspaceIdentity;
  scope:string;generation:number;workspaceId:string;selection:ShareSavedNoteInput;content:string;
};

/** State whose lifetime belongs to the workspace, rather than its presentation. */
export type WorkspaceSessionState = {
  workspace: Workspace|null;
  encounters: WorkspaceEncounter[]|null;
  team: ProviderTeam|null;
  teamDraft: TeamConfiguration|null;
  note: string;
  thought: string;
  evidence: string;
  source: string;
  previousModelRequest: PreviousModelRequest|null;
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
