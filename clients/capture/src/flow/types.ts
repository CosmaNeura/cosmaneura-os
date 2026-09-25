import type {
  CaptureLeaseIssueRequest,
  CaptureLeaseReceipt,
  ChunkReservationBatchRequest,
  ConsentCreate,
  SessionCreate,
} from "../bff/contracts";
import type { CaptureRecoveryIntent } from "./recovery-exchange";
import type { CaptureRecoveryState } from "../bff/recovery-contracts";
import type { CaptureProfileReceipt, CaptureProfileSelection } from "../bff/profile-contracts";

export const FLOW_RECORD_SCHEMA_VERSION = 2 as const;
export const CAPTURE_RECOVERY_SCHEMA_VERSION = 1 as const;

export type ActiveCapturePhase =
  | "ready"
  | "recording"
  | "paused"
  | "uploading"
  | "completing"
  | "processing";

export type CaptureFlowState =
  | "idle"
  | "preparing"
  | "ready"
  | "recording"
  | "paused"
  | "uploading"
  | "processing"
  | "complete"
  | "error";

export type CaptureRecoveryPhase =
  | "ready"
  | "recording"
  | "interruption_closing"
  | "ack_required"
  | "authority_required"
  | "stopped";

export type CaptureGapReasonCode =
  | "audio_context_suspended"
  | "audio_device_disconnected"
  | "audio_route_changed"
  | "audio_session_interrupted"
  | "capture_backgrounded"
  | "capture_source_stalled"
  | "capture_source_failed"
  | "capture_authority_expired"
  | "process_recovery_unknown";

export interface CaptureSegmentV1 {
  readonly segmentId: string;
  /** Stable candidate used if this physical recording run terminates with a gap. */
  readonly recoveryGapId: string;
  readonly ordinal: number;
  readonly firstSequenceNumber: number;
  readonly lastSequenceNumber: number | null;
  readonly state: "recording" | "stopped" | "interrupted" | "uncertain";
  readonly startedAt: string;
  readonly endedAt: string | null;
  readonly leaseGeneration: number;
  readonly captureAuthorizedUntil: string;
}

export interface CaptureGapAcknowledgementV1 {
  readonly decision: "continue_with_known_gap" | "finish_capture";
  readonly acknowledgedAt: string;
  readonly idempotencyKey: string;
}

export interface CaptureGapV1 {
  readonly gapId: string;
  readonly precedingSegmentId: string;
  /** Set only after validation of the receiver's immutable recovery receipt. */
  readonly followingSegmentId: string | null;
  readonly reasonCode: CaptureGapReasonCode;
  readonly observedAt: string;
  readonly lastCommittedSequenceNumber: number | null;
  readonly acknowledgement: CaptureGapAcknowledgementV1 | null;
  readonly reviewState: "required";
}

/**
 * Local, metadata-only recovery evidence. It is not capture authority and it
 * deliberately contains no actor, practice, patient, consent, token, or AAD.
 */
export interface CaptureRecoveryStateV1 {
  readonly schemaVersion: typeof CAPTURE_RECOVERY_SCHEMA_VERSION | 2;
  /** Version 2 retains an explicit Finish choice without erasing an earlier Resume. */
  readonly finishChoice?: CaptureRecoveryFinishChoice;
  readonly sessionId: string;
  readonly localRevision: number;
  readonly phase: CaptureRecoveryPhase;
  readonly nextSegmentOrdinal: number;
  readonly nextSequenceNumber: number;
  readonly currentSegmentId: string | null;
  readonly segments: readonly CaptureSegmentV1[];
  readonly gaps: readonly CaptureGapV1[];
  readonly noteReadiness: "eligible" | "review_required";
}

export interface CaptureRecoveryFinishChoice {
  readonly priorIntent: CaptureRecoveryIntent;
  readonly priorResult: "committed" | "uncommitted";
  readonly acknowledgedAt: string;
  readonly idempotencyKey: string;
}

export interface ReservationIntent {
  readonly schemaVersion: typeof FLOW_RECORD_SCHEMA_VERSION;
  readonly intentId: string;
  readonly sessionId: string;
  readonly idempotencyKey: string;
  readonly request: ChunkReservationBatchRequest;
  readonly createdAt: string;
}

export interface SessionKeyBindingState {
  readonly schemaVersion: typeof FLOW_RECORD_SCHEMA_VERSION;
  readonly sessionId: string;
  readonly keyVersion: string;
  readonly wrappedDek: string;
  readonly idempotencyKey: string;
  readonly state: "pending" | "bound";
}

export interface PreparedCaptureSession {
  readonly sessionId: string;
  readonly lease: CaptureLeaseReceipt;
}

export interface ActiveCaptureState {
  /** Configured Scribe sessions continue through creator review after upload. */
  readonly reviewAfterUpload?: true;
  /** Absent on retained legacy recordings; immutable for this capture. */
  readonly captureProfile?: CaptureProfileReceipt;
  readonly schemaVersion: typeof FLOW_RECORD_SCHEMA_VERSION;
  readonly sessionId: string;
  readonly lease: CaptureLeaseReceipt;
  /** Exact server receipt value. Null only while the first reservation mutation is pending. */
  readonly captureAuthorizedUntil: string | null;
  /** Initial aggregate plaintext budget from the capability bootstrap. */
  readonly aggregatePlaintextBudgetBytes: number;
  readonly phase: ActiveCapturePhase;
  readonly completeIdempotencyKey: string;
  readonly recordedChunks: number;
  readonly recordedPlaintextBytes: number;
  readonly startedAt: string;
}

export interface DirectCapturePreparationState {
  readonly mode?: "direct";
  readonly schemaVersion: typeof FLOW_RECORD_SCHEMA_VERSION;
  readonly startedAt: string;
  readonly consentIdempotencyKey: string;
  readonly completeIdempotencyKey: string;
  readonly consentRequest: ConsentCreate;
  readonly consentId: string | null;
  readonly sessionIdempotencyKey: string | null;
  readonly sessionRequest: SessionCreate | null;
  readonly sessionId: string | null;
  readonly leaseIdempotencyKey: string | null;
  readonly leaseRequest: CaptureLeaseIssueRequest | null;
}

/** Core owns consent/session admission; this stores no fabricated legacy receipt. */
export interface AdmittedCapturePreparationState {
  readonly reviewAfterUpload?: true;
  /** Persisted before selection; the confirmed receipt is saved before a lease. */
  readonly profileSelection?: CaptureProfileSelection;
  readonly mode: "core_admitted";
  readonly schemaVersion: typeof FLOW_RECORD_SCHEMA_VERSION;
  readonly startedAt: string;
  readonly completeIdempotencyKey: string;
  readonly sessionId: string;
  readonly leaseIdempotencyKey: string | null;
  readonly leaseRequest: CaptureLeaseIssueRequest | null;
}

export type CapturePreparationState = DirectCapturePreparationState | AdmittedCapturePreparationState;

export interface CaptureFlowStore {
  reconcileCaptureLease(state: CaptureRecoveryState): Promise<ActiveCaptureState>;
  putCaptureRecoveryIntent(intent: CaptureRecoveryIntent, purpose?: "finish"): Promise<void>;
  getCaptureRecoveryIntent(sessionId: string, gapId: string, purpose?: "finish"): Promise<CaptureRecoveryIntent | null>;
  putPreparationState(state: CapturePreparationState): Promise<void>;
  getPreparationState(): Promise<CapturePreparationState | null>;
  putActiveCaptureState(state: ActiveCaptureState): Promise<void>;
  getActiveCaptureState(): Promise<ActiveCaptureState | null>;
  putCaptureRecoveryState(state: CaptureRecoveryStateV1): Promise<void>;
  getCaptureRecoveryState(sessionId: string): Promise<CaptureRecoveryStateV1 | null>;
  clearCompletedCapture(sessionId: string): Promise<void>;
  putReservationIntent(intent: ReservationIntent): Promise<void>;
  listReservationIntents(): Promise<readonly ReservationIntent[]>;
  deleteReservationIntent(intentId: string): Promise<void>;
  putSessionKeyCandidate(state: SessionKeyBindingState, key: CryptoKey): Promise<void>;
  replacePendingSessionKeyCandidate(
    state: SessionKeyBindingState,
    key: CryptoKey,
  ): Promise<void>;
  getSessionKeyState(sessionId: string): Promise<SessionKeyBindingState | null>;
  getSessionKey(sessionId: string): Promise<CryptoKey | null>;
  markSessionKeyBound(sessionId: string): Promise<void>;
}
