import {
  base64UrlDecode,
  base64UrlEncode,
  encodeEnvelope,
  NONCE_BYTES,
  PROTOCOL_VERSION,
} from "@cosmaneura-scribe/capture-protocol";

import type {
  CaptureBff,
  CaptureCapabilities,
  CaptureLeaseReceipt,
  CaptureTranscriptionStatus,
  ChunkReservationBatchReceipt,
  ConsentCreate,
  Transcript,
} from "../bff/contracts";
import { BffResponseError } from "../bff/http-client";
import { validateProfileRequest, validateProfileReceipt, validateProfileCapabilities,
  type CaptureProfileBff, type CaptureProfileRequest, type CaptureProfileReceipt } from "../bff/profile-contracts";
import { canonicalCaptureTimestamp, type CaptureRecoveryBff, type CaptureRecoveryRequest } from "../bff/recovery-contracts";
import { validateCaptureSource, type CaptureSourceEnvelope, type CaptureQualifiedSourceBff } from "../bff/source-contracts";
import { assertRetainedSource } from "./qualified-source";
import { exchangeRecovery } from "./recovery-exchange";
import { reconcileResumeForFinish } from "./recovery-finish";
import { exchangeCaptureRenewal, reconcileInterruptedRenewal, reconcileStoppedRenewal } from "./renewal-exchange";
import { requireRenewal, validateRenewalIntent, type CaptureRenewalRecord, type CaptureRenewalStore } from "./renewal-contract";
import { AudioCaptureError } from "../audio/errors";
import type {
  CapturedWavChunk,
  CaptureSource,
  CaptureSourceErrorCode,
  CaptureSourceInterruptionCode,
} from "../capture";
import { QueueInvariantError } from "../queue/errors";
import type { CaptureQueue } from "../queue/capture-queue";
import type {
  CaptureChunkMetadata,
  CaptureQueueTransport,
  ChunkReservation,
} from "../queue/types";
import { createWrappedSessionKey } from "./session-key";
import {
  acknowledgeRecoveryGap,
  beginRecoverySegment,
  confirmRecoverySourceClosed,
  confirmRecoveryReceipt,
  createCaptureRecoveryState,
  observeRecoveryGap,
  stopRecoverySegment,
} from "./recovery-state";
import {
  FLOW_RECORD_SCHEMA_VERSION,
  type ActiveCapturePhase,
  type ActiveCaptureState,
  type CaptureFlowState,
  type CaptureFlowStore,
  type CaptureGapReasonCode,
  type CapturePreparationState,
  type AdmittedCapturePreparationState,
  type DirectCapturePreparationState,
  type CaptureRecoveryStateV1,
  type ReservationIntent,
  type SessionKeyBindingState,
} from "./types";

export interface SyntheticEncounter {
  readonly appointmentId: string;
  readonly practitionerId: string;
  readonly patientId: string;
  readonly participantRegions: readonly string[];
}

export interface CaptureFlowSnapshot {
  readonly qualifiedSource?: CaptureSourceEnvelope | undefined;
  readonly recoveryDecision?: "resume_capture" | "finish_capture" | undefined;
  readonly state: CaptureFlowState;
  readonly statusCode: string;
  readonly sessionId: string | null;
  readonly recordedChunks: number;
  readonly queuedChunks: number;
  readonly elapsedSeconds: number;
  readonly remainingBudgetSeconds: number | null;
  readonly remainingAuthoritySeconds: number | null;
  readonly transcriptionStatus: CaptureTranscriptionStatus | null;
  readonly transcript: Transcript | null;
}

export interface CaptureFlowControllerOptions {
  /** Old journals may finish retained audio, never acquire a new physical source. */
  readonly recoveryOnly?: boolean;
  readonly renewals?: CaptureRenewalStore;
  readonly profiles?: CaptureProfileBff;
  readonly qualifiedSource?: CaptureQualifiedSourceBff;
  readonly recovery?: CaptureRecoveryBff;
  readonly bff: CaptureBff;
  readonly flowStore: CaptureFlowStore;
  readonly queue: CaptureQueue;
  readonly queueTransport: CaptureQueueTransport;
  readonly source: CaptureSource;
  readonly crypto?: Crypto;
  readonly now?: () => Date;
  readonly idFactory?: () => string;
  readonly scheduleTimeout?: (callback: () => void, delayMs: number) => unknown;
  readonly cancelTimeout?: (handle: unknown) => void;
}

type SnapshotListener = (snapshot: CaptureFlowSnapshot) => void;

interface ContinuousCaptureRun {
  id: string;
  firstSequence: number;
  hardMaximumChunks: number;
  maximumChunks: number;
  admittedMaximumChunks: number;
  generation: number;
  deadline: number;
  readyAt: number;
  stopping: boolean;
  closed: boolean;
}

export class CaptureFlowController {
  readonly #recoveryOnly: boolean;
  readonly #renewals: CaptureRenewalStore | null;
  readonly #profiles: CaptureProfileBff | null;
  #captureProfile: CaptureProfileReceipt | null = null;
  readonly #qualifiedSource: CaptureQualifiedSourceBff | null;
  readonly #recovery: CaptureRecoveryBff | null;
  #recoveryExchange: Promise<void> | null = null;
  readonly #bff: CaptureBff;
  readonly #flowStore: CaptureFlowStore;
  readonly #queue: CaptureQueue;
  readonly #queueTransport: CaptureQueueTransport;
  readonly #source: CaptureSource;
  readonly #crypto: Crypto;
  readonly #now: () => Date;
  readonly #idFactory: () => string;
  readonly #scheduleTimeout: (callback: () => void, delayMs: number) => unknown;
  readonly #cancelTimeout: (handle: unknown) => void;
  readonly #listeners = new Set<SnapshotListener>();
  readonly #reservations = new Map<number, ChunkReservation>();

  #capabilities: CaptureCapabilities | null = null;
  #activeState: ActiveCaptureState | null = null;
  #recoveryState: CaptureRecoveryStateV1 | null = null;
  #lease: CaptureLeaseReceipt | null = null;
  #sessionId: string | null = null;
  #recordedPlaintextBytes = 0;
  #sourcePausedBySignal = false;
  #sourcePausePersistence: Promise<void> | null = null;
  #sourceStarted = false;
  #recoveredUnverifiedClose = false;
  #legacyCompletionEligible = false;
  #recordingAbortController: AbortController | null = null;
  #chunkPersistence: Promise<void> = Promise.resolve();
  #recoveryPersistence: Promise<void> = Promise.resolve();
  #authorityExpiryRequested = false;
  #authorityTimeout: unknown = null;
  #authorityExpiryTask: Promise<void> | null = null;
  #authorityTimerVersion = 0;
  #continuousRun: ContinuousCaptureRun | null = null;
  #renewalTimeout: unknown = null;
  #renewalTask: Promise<void> | null = null;
  #stopTask: Promise<void> | null = null;
  #disposed = false;
  #closeTask: Promise<void> | null = null;
  #snapshot: CaptureFlowSnapshot = {
    state: "idle",
    statusCode: "synthetic_preview_idle",
    sessionId: null,
    recordedChunks: 0,
    queuedChunks: 0,
    elapsedSeconds: 0,
    remainingBudgetSeconds: null,
    remainingAuthoritySeconds: null,
    transcriptionStatus: null,
    transcript: null,
  };

  public constructor(options: CaptureFlowControllerOptions) {
    this.#recoveryOnly = options.recoveryOnly === true;
    this.#renewals = options.renewals ?? null;
    this.#profiles = options.profiles ?? null;
    this.#qualifiedSource = options.qualifiedSource ?? null;
    this.#recovery = options.recovery ?? null;
    this.#bff = options.bff;
    this.#flowStore = options.flowStore;
    this.#queue = options.queue;
    this.#queueTransport = options.queueTransport;
    this.#source = options.source;
    this.#crypto = options.crypto ?? globalThis.crypto;
    this.#now = options.now ?? (() => new Date());
    this.#idFactory = options.idFactory ?? (() => this.#crypto.randomUUID());
    this.#scheduleTimeout = options.scheduleTimeout ?? ((callback, delayMs) =>
      globalThis.setTimeout(callback, delayMs));
    this.#cancelTimeout = options.cancelTimeout ?? ((handle) =>
      globalThis.clearTimeout(handle as ReturnType<typeof globalThis.setTimeout>));
    if (this.#crypto?.subtle === undefined) {
      throw new QueueInvariantError("webcrypto_unavailable");
    }
  }

  public get snapshot(): CaptureFlowSnapshot {
    return structuredClone(this.#snapshot);
  }

  public subscribe(listener: SnapshotListener): () => void {
    this.#listeners.add(listener);
    listener(this.snapshot);
    return () => this.#listeners.delete(listener);
  }

  /** Stop the physical source on workspace exit; keep all queued/recovery data. */
  public close(): Promise<void> {
    if (this.#closeTask !== null) return this.#closeTask;
    this.#disposed = true;
    this.#suppressRenewal();
    this.#clearAuthorityTimeout();
    const hadLiveSource = this.#sourceStarted || this.#recordingAbortController !== null;
    this.#pauseAfterSourceSignal("capture_backgrounded");
    this.#recordingAbortController?.abort();
    this.#closeTask = (async () => {
      await this.#source.stop();
      await this.#sourcePausePersistence;
      await this.#chunkPersistence;
      this.#sourceStarted = false;
      this.#recordingAbortController = null;
      if (hadLiveSource && this.#hasRecoveryGap()) await this.#confirmInterruptedSourceClosed(true);
      this.#clearAuthorityTimeout();
    })().catch(error => {
      this.#closeTask = null;
      throw error;
    });
    return this.#closeTask;
  }

  public async restore(): Promise<boolean> {
    this.#requireState("idle");
    const active = await this.#flowStore.getActiveCaptureState();
    if (active === null) {
      const preparation = await this.#flowStore.getPreparationState();
      if (preparation === null) return false;
      if(this.#recoveryOnly){
        this.#sessionId=preparation.sessionId;
        this.#setSnapshot({state:'ready',statusCode:'capture_saved_preparation',sessionId:preparation.sessionId});
        return true;
      }
      this.#setSnapshot({ state: "preparing", statusCode: "synthetic_preview_restoring" });
      try {
        await this.#continuePreparation(preparation, true);
        return true;
      } catch (error) {
        this.#fail();
        throw error;
      }
    }
    this.#setSnapshot({ state: "preparing", statusCode: "synthetic_preview_restoring" });
    try {
      this.#activeState = active;
      this.#sessionId = active.sessionId;
      this.#reviewAfterUpload = active.reviewAfterUpload === true;
      if (this.#reviewAfterUpload && active.phase === "processing") {
        await this.#purgeRegisteredChunks();
        this.#setSnapshot({sessionId: active.sessionId, state: "processing", statusCode: "capture_creator_review", recordedChunks: active.recordedChunks});
        return true;
      }
      this.#lease = active.lease;
      if (active.captureProfile) await this.#restoreCaptureProfile(active.captureProfile);
      const keyState = await this.#flowStore.getSessionKeyState(active.sessionId);
      if (keyState === null) throw new QueueInvariantError("session_key_missing");
      await this.#bindStoredSessionKey(keyState);
      this.#setCapabilities(await this.#bff.getCapabilities(active.sessionId));
      const storedRecovery = await this.#flowStore.getCaptureRecoveryState(active.sessionId);
      if (!storedRecovery?.gaps.length && this.#canCreateOrRecoverReservations()) {
        await this.#recoverReservationIntents();
      }
      let records = (await this.#queue.listMetadata()).filter(
        (record) => record.reservation.sessionId === active.sessionId,
      );
      if (
        records.length === 0 && active.phase === "ready" &&
        this.#canCreateOrRecoverReservations()
      ) {
        await this.#reserveInitialWindow();
        records = (await this.#queue.listMetadata()).filter(
          (record) => record.reservation.sessionId === active.sessionId,
        );
      }
      for (const record of records) {
        this.#reservations.set(record.reservation.sequenceNumber, record.reservation);
      }
      const recorded = records.filter((record) => record.state !== "reserved");
      const requiresDurableHighWater = active.phase !== "processing";
      const durableRecordedChunks = requiresDurableHighWater
        ? contiguousRecordedChunkCount(recorded)
        : recorded.length;
      if (requiresDurableHighWater && active.recordedChunks > durableRecordedChunks) {
        throw new QueueInvariantError("capture_recovery_sequence_conflict");
      }
      const conservativeBytes = recorded.reduce(
        (total, record) => total + ("byteLength" in record ? record.byteLength : 0),
        0,
      );
      this.#recordedPlaintextBytes = Math.max(
        active.recordedPlaintextBytes,
        conservativeBytes,
      );
      const recordedChunks = requiresDurableHighWater
        ? durableRecordedChunks
        : Math.max(active.recordedChunks, durableRecordedChunks);
      this.#activeState = {
        ...this.#requireActiveState(),
        recordedChunks,
        recordedPlaintextBytes: this.#recordedPlaintextBytes,
      };
      await this.#restoreRecoveryState(active, recordedChunks, storedRecovery);
      await this.#flowStore.putActiveCaptureState(this.#activeState);
      const capturePhase =
        active.phase === "ready" || active.phase === "recording" || active.phase === "paused";
      const authorityExpired = capturePhase && !this.#hasActiveCaptureAuthority();
      if (active.phase === "recording" && this.#recoveryState?.phase === "stopped") {
        await this.#saveActivePhase("uploading");
      } else if (
        active.phase === "recording" || authorityExpired || (capturePhase && this.#hasRecoveryGap())
      ) {
        await this.#saveActivePhase("paused");
      }
      const phase = this.#requireActiveState().phase;
      const recoveryStatusCode = this.#recoveryStatusCode();
      this.#setSnapshot({
        state: restoredSnapshotState(phase),
        ...(this.#recoveryState?.gaps.at(-1)?.acknowledgement ? {
          recoveryDecision: this.#recoveryState.finishChoice || this.#recoveryState.gaps.at(-1)!.acknowledgement!.decision === "finish_capture"
            ? "finish_capture" as const : "resume_capture" as const,
        } : {}),
        statusCode: recoveryStatusCode ??
          (authorityExpired ? "capture_authority_expired" : restoredStatusCode(phase)),
        sessionId: active.sessionId,
        recordedChunks,
        queuedChunks: records.length,
        elapsedSeconds: captureSeconds(this.#requireCapabilities(), recordedChunks),
        remainingBudgetSeconds: this.#remainingAggregateBudgetSeconds(recordedChunks),
        remainingAuthoritySeconds: this.#remainingCaptureSeconds(recordedChunks),
      });
      if (phase === "ready" && !authorityExpired) this.#armAuthorityDeadline();
      return true;
    } catch (error) {
      this.#fail();
      throw error;
    }
  }

  #readingAdmittedResult = false;
  #reviewAfterUpload = false;

  /** Reopen server-owned results after the completed local queue was cleared. */
  public async restoreAdmittedResult(sessionId: string): Promise<boolean> {
    this.#requireState("idle");
    // A retained local capture still owns recovery/gap decisions. Reading a
    // server result must never discard that unfinished state.
    if (await this.#flowStore.getActiveCaptureState() !== null ||
        await this.#flowStore.getPreparationState() !== null) return false;
    const status = await this.#bff.getTranscriptionStatus(sessionId);
    if (status.status === "not_requested") return false;
    this.#sessionId = sessionId;
    this.#readingAdmittedResult = true;
    this.#setSnapshot({ sessionId, state: "processing", statusCode: "capture_transcription_processing" });
    await this.#showTranscriptionStatus(status);
    return true;
  }

  public async prepare(encounter: SyntheticEncounter): Promise<void> {
    this.#requireState("idle");
    this.#setSnapshot({ state: "preparing", statusCode: "synthetic_preview_preparing" });
    try {
      const startedAt = this.#now();
      const preparation: CapturePreparationState = {
        schemaVersion: FLOW_RECORD_SCHEMA_VERSION,
        startedAt: startedAt.toISOString(),
        consentIdempotencyKey: this.#operationKey("consent"),
        completeIdempotencyKey: this.#operationKey("complete"),
        consentRequest: consentRequest(encounter, startedAt),
        consentId: null,
        sessionIdempotencyKey: null,
        sessionRequest: null,
        sessionId: null,
        leaseIdempotencyKey: null,
        leaseRequest: null,
      };
      await this.#flowStore.putPreparationState(preparation);
      await this.#continuePreparation(preparation);
    } catch (error) {
      this.#fail();
      throw error;
    }
  }

  public async prepareAdmitted(sessionId: string, profileRequest?: CaptureProfileRequest, reviewAfterUpload = false): Promise<void> {
    this.#requireState("idle");
    this.#setSnapshot({ state: "preparing", statusCode: "synthetic_preview_preparing" });
    try {
      if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/iu.test(sessionId)) {
        throw new QueueInvariantError("invalid_admitted_session");
      }
      const preparation: AdmittedCapturePreparationState = {
        mode: "core_admitted",
        ...(reviewAfterUpload ? {reviewAfterUpload: true as const} : {}),
        schemaVersion: FLOW_RECORD_SCHEMA_VERSION,
        startedAt: this.#now().toISOString(),
        completeIdempotencyKey: this.#operationKey("complete"),
        sessionId,
        leaseIdempotencyKey: null,
        leaseRequest: null,
        ...(profileRequest === undefined ? {} : { profileSelection: {
          request: this.#microphoneProfileRequest(profileRequest),
          idempotencyKey: this.#operationKey("profile"), receipt: null,
        } }),
      };
      await this.#flowStore.putPreparationState(preparation);
      await this.#continuePreparation(preparation);
    } catch (error) {
      this.#fail();
      throw error;
    }
  }

  async #prepareDirectAdmission(initial: DirectCapturePreparationState): Promise<DirectCapturePreparationState> {
    let preparation = initial;
    const consent = await this.#bff.createConsent(preparation.consentRequest, {
      idempotencyKey: preparation.consentIdempotencyKey,
    });
    if (preparation.consentId !== null && preparation.consentId !== consent.id) {
      throw new QueueInvariantError("consent_receipt_conflict");
    }
    if (preparation.consentId === null) {
      preparation = { ...preparation, consentId: consent.id };
      await this.#flowStore.putPreparationState(preparation);
    }

    if (preparation.sessionRequest === null || preparation.sessionIdempotencyKey === null) {
      preparation = {
        ...preparation,
        sessionIdempotencyKey: this.#operationKey("session"),
        sessionRequest: {
          appointment_id: preparation.consentRequest.appointment_id,
          practitioner_id: preparation.consentRequest.practitioner_id,
          patient_id: preparation.consentRequest.patient_id,
          consent_record_id: consent.id,
          modality: "in_person",
        },
      };
      await this.#flowStore.putPreparationState(preparation);
    }
    const sessionRequest = preparation.sessionRequest;
    const sessionIdempotencyKey = preparation.sessionIdempotencyKey;
    if (sessionRequest === null || sessionIdempotencyKey === null) {
      throw new QueueInvariantError("preparation_state_incomplete");
    }
    const session = await this.#bff.createSession(sessionRequest, {
      idempotencyKey: sessionIdempotencyKey,
    });
    if (preparation.sessionId !== null && preparation.sessionId !== session.id) {
      throw new QueueInvariantError("session_receipt_conflict");
    }
    if (preparation.sessionId === null) {
      preparation = { ...preparation, sessionId: session.id };
      await this.#flowStore.putPreparationState(preparation);
    }
    return preparation;
  }

  #microphoneProfileRequest(value: CaptureProfileRequest): CaptureProfileRequest {
    const request = validateProfileRequest(value);
    // The retained recorder currently produces one microphone track. The
    // receiver's dual-track policy must not imply a second capture source.
    if (!this.#profiles || request.channels.length !== 1 || request.channels[0] !== "microphone") {
      throw new QueueInvariantError("capture_profile_unavailable");
    }
    return request;
  }

  async #restoreCaptureProfile(value: CaptureProfileReceipt): Promise<void> {
    const profile = await validateProfileReceipt(value, this.#requireSessionId(), this.#now(), undefined, this.#crypto);
    this.#microphoneProfileRequest(profile.request);
    await this.#profiles!.acknowledgeCaptureProfile(profile);
    this.#captureProfile = profile;
  }

  async #continuePreparation(initial: CapturePreparationState, recovering = false): Promise<void> {
    let preparation = initial.mode === "core_admitted" ? initial : await this.#prepareDirectAdmission(initial);
    this.#reviewAfterUpload = preparation.mode === "core_admitted" && preparation.reviewAfterUpload === true;
    const sessionId = preparation.sessionId;
    if (sessionId === null) throw new QueueInvariantError("preparation_state_incomplete");
    this.#sessionId = sessionId;
    this.#setSnapshot({ sessionId });

    if (preparation.mode === "core_admitted" && preparation.profileSelection) {
      const selection = preparation.profileSelection;
      this.#microphoneProfileRequest(selection.request);
      if (selection.receipt === null) {
        let receipt: CaptureProfileReceipt | null = null;
        if (recovering) {
          try { receipt = await this.#profiles!.getCaptureProfile(sessionId); }
          catch (error) {
            // The closed Core path maps an unavailable Scribe profile to this
            // conflict. Retry only the saved selection, under current authority.
            // Auth/network/invalid-receipt failures retain the intent unchanged.
            if (!(error instanceof BffResponseError && error.status === 409 &&
                error.code === "capture_source_unavailable")) throw error;
          }
        }
        receipt ??= await this.#profiles!.selectCaptureProfile(sessionId, selection.request,
          { idempotencyKey: selection.idempotencyKey });
        const confirmed = await validateProfileReceipt(receipt, sessionId, this.#now(), selection.request, this.#crypto);
        preparation = { ...preparation, profileSelection: { ...selection, receipt: confirmed } };
        await this.#flowStore.putPreparationState(preparation);
      }
      await this.#restoreCaptureProfile(preparation.profileSelection!.receipt!);
    }
    await this.#bindSessionKey(sessionId);
    this.#setCapabilities(await this.#bff.getCapabilities(sessionId));
    if (preparation.leaseRequest === null || preparation.leaseIdempotencyKey === null) {
      preparation = {
        ...preparation,
        leaseIdempotencyKey: this.#operationKey("lease"),
        leaseRequest: { protocol_version: PROTOCOL_VERSION },
      };
      await this.#flowStore.putPreparationState(preparation);
    }
    const leaseRequest = preparation.leaseRequest;
    const leaseIdempotencyKey = preparation.leaseIdempotencyKey;
    if (leaseRequest === null || leaseIdempotencyKey === null) {
      throw new QueueInvariantError("preparation_state_incomplete");
    }
    this.#lease = await this.#bff.issueLease(
      sessionId,
      leaseRequest,
      { idempotencyKey: leaseIdempotencyKey },
    );
    if (Date.parse(this.#lease.expires_at) <= this.#now().getTime()) {
      throw new QueueInvariantError("capture_lease_expired");
    }
    this.#activeState = {
      ...(this.#reviewAfterUpload ? {reviewAfterUpload: true as const} : {}),
      ...(this.#captureProfile ? { captureProfile: this.#captureProfile } : {}),
      schemaVersion: FLOW_RECORD_SCHEMA_VERSION,
      sessionId,
      lease: this.#lease,
      captureAuthorizedUntil: null,
      aggregatePlaintextBudgetBytes:
        this.#requireCapabilities().remaining_aggregate_plaintext_bytes,
      phase: "ready",
      completeIdempotencyKey: preparation.completeIdempotencyKey,
      recordedChunks: 0,
      recordedPlaintextBytes: 0,
      startedAt: preparation.startedAt,
    };
    await this.#flowStore.putActiveCaptureState(this.#activeState);
    await this.#recoverReservationIntents();
    if (this.#reservations.size === 0) await this.#reserveInitialWindow();
    this.#recoveryState = createCaptureRecoveryState(sessionId);
    await this.#flowStore.putCaptureRecoveryState(this.#recoveryState);
    if (!this.#hasActiveCaptureAuthority()) {
      await this.#pauseForExpiredAuthority();
      throw new QueueInvariantError("capture_authority_expired");
    }
    this.#setSnapshot({
      state: "ready",
      statusCode: "synthetic_preview_ready",
      remainingBudgetSeconds: this.#remainingAggregateBudgetSeconds(0),
      remainingAuthoritySeconds: this.#remainingCaptureSeconds(0),
    });
    this.#armAuthorityDeadline();
  }

  public async startRecording(): Promise<void> {
    if (this.#recoveryOnly) throw new QueueInvariantError("capture_saved_recording_finish_only");
    this.#requireState("ready");
    if (!this.#hasActiveCaptureAuthority()) {
      await this.#pauseForExpiredAuthority();
      throw new QueueInvariantError("capture_authority_expired");
    }
    this.#clearAuthorityTimeout();
    const capabilities = this.#captureCapabilitiesForReservedWindow();
    this.#sourcePausedBySignal = false;
    this.#sourcePausePersistence = null;
    this.#sourceStarted = false;
    this.#authorityExpiryRequested = false;
    this.#recordingAbortController = new AbortController();
    const active = this.#requireActiveState();
    if (active.captureAuthorizedUntil === null) {
      throw new QueueInvariantError("capture_authority_missing");
    }
    const captureAuthorizedUntil = active.captureAuthorizedUntil;
    await this.#updateRecoveryState((state) => beginRecoverySegment(state, {
      segmentId: this.#requireRecoveryState().gaps.at(-1)?.followingSegmentId ?? this.#idFactory(),
      recoveryGapId: this.#idFactory(),
      startedAt: this.#now().toISOString(),
      leaseGeneration: active.lease.generation,
      captureAuthorizedUntil,
    }));
    await this.#saveActivePhase("recording");
    if (this.#authorityExpiryRequested || !this.#hasActiveCaptureAuthority()) {
      await this.#authorityExpiryTask;
      this.#authorityExpiryRequested = true;
      this.#recordingAbortController = null;
      if (this.#snapshot.state !== "paused") await this.#pauseForExpiredAuthority();
      throw new QueueInvariantError("capture_authority_expired");
    }
    this.#setSnapshot({ state: "recording", statusCode: "synthetic_preview_recording", recoveryDecision: undefined });
    const run: ContinuousCaptureRun | null = this.#captureProfile && this.#renewals && this.#recovery &&
      this.#source.kind === "microphone" && this.#source.extend ? {
        id: this.#requireRecoveryState().currentSegmentId!, firstSequence: active.recordedChunks,
        hardMaximumChunks: Math.min(this.#requireCapabilities().max_chunks - active.recordedChunks,
          Math.floor((active.aggregatePlaintextBudgetBytes - this.#recordedPlaintextBytes) / capabilities.max_envelope_bytes)),
        maximumChunks: capabilities.max_chunks, admittedMaximumChunks: capabilities.max_chunks,
        generation: active.lease.generation, deadline: this.#captureAuthorityDeadline()!,
        readyAt: this.#now().getTime(), stopping: false, closed: false,
      } : null;
    this.#continuousRun = run;
    this.#armAuthorityDeadline();
    try {
      const recordingAbortController = this.#recordingAbortController;
      await this.#source.start({
        capabilities,
        // The initial window remains bounded; only confirmed renewals can use
        // the rest of this run's immutable profile budget.
        authority: { runId: this.#requireRecoveryState().currentSegmentId!, generation: active.lease.generation,
          expiresAtMs: Math.min(Date.parse(active.lease.expires_at), Date.parse(captureAuthorizedUntil)),
          hardMaximumChunks: run?.hardMaximumChunks ?? capabilities.max_chunks },
        onChunk: async (chunk) => this.#acceptChunk({ ...chunk,
          sequenceNumber: active.recordedChunks + chunk.sequenceNumber }, run),
        ...(run ? { onWindowClosed: (reason: "authority_expired" | "frame_limit") => this.#sourceWindowClosed(run, reason) } : {}),
        onInterruption: (code) => this.#pauseAfterSourceSignal(code),
        onError: (code) => this.#pauseAfterSourceSignal(code),
        signal: recordingAbortController.signal,
      });
      this.#sourceStarted = true;
      if (recordingAbortController.signal.aborted) {
        await this.#source.stop();
        this.#sourceStarted = false;
      }
      if (run && !run.stopping && !recordingAbortController.signal.aborted) {
        run.readyAt = this.#now().getTime();
        this.#scheduleRenewal(run);
      }
    } catch (error) {
      this.#clearAuthorityTimeout();
      this.#sourceStarted = false;
      if (!this.#sourcePausedBySignal) this.#fail();
      throw error;
    }
  }

  public stopRecording(): Promise<void> {
    if (this.#stopTask) return this.#stopTask;
    this.#suppressRenewal();
    const task = this.#stopRecording();
    this.#stopTask = task;
    void task.finally(() => { if (this.#stopTask === task) this.#stopTask = null; }).catch(() => undefined);
    return task;
  }

  async #stopRecording(): Promise<void> {
    if (this.#snapshot.state !== "recording" && this.#snapshot.state !== "paused") {
      throw new QueueInvariantError("capture_state_conflict");
    }
    try {
      this.#clearAuthorityTimeout();
      await this.#authorityExpiryTask;
      await this.#sourcePausePersistence;
      if (this.#hasRecoveryGap() && this.#recoveredUnverifiedClose) {
        throw new QueueInvariantError("capture_source_close_unverified");
      }
      if (
        this.#recoveryState?.phase === "ack_required" ||
        this.#recoveryState?.phase === "authority_required"
      ) {
        throw new QueueInvariantError("capture_gap_review_required");
      }
      let stopFailure: unknown;
      let stopRejected = false;
      let stopFailureObservedAt: string | null = null;
      try {
        await this.#source.stop();
      } catch (error) {
        stopRejected = true;
        stopFailure = error;
        stopFailureObservedAt = this.#now().toISOString();
      }
      // A terminal callback can replace this promise while stop is in flight.
      await this.#sourcePausePersistence;
      await this.#chunkPersistence;
      if (stopRejected) {
        if (this.#requireRecoveryState().phase === "recording") {
          await this.#recordRecoveryGap(
            "capture_source_failed",
            this.#snapshot.recordedChunks,
            stopFailureObservedAt ?? this.#now().toISOString(),
          );
          await this.#saveActivePhase("paused");
        }
        throw sourceCloseFailure(stopFailure);
      }
      this.#sourceStarted = false;
      this.#recordingAbortController = null;
      if (this.#continuousRun) this.#continuousRun.closed = true;
      if (this.#requireRecoveryState().phase !== "recording") {
        await this.#confirmInterruptedSourceClosed(true);
        this.#setSnapshot({
          state: "paused",
          statusCode: "capture_gap_ack_required",
        });
        throw new QueueInvariantError("capture_gap_review_required");
      }
      await this.#finishStoppedCapture();
    } catch (error) {
      if (isSourceCloseFailure(error)) {
        await this.#sourcePausePersistence;
        this.#setSnapshot({ state: "paused", statusCode: error.code });
      } else if (isRecoveryHold(error)) {
        this.#setSnapshot({ state: "paused", statusCode: error.code });
      } else if (error instanceof QueueInvariantError && error.code === "capture_renewal_unconfirmed") {
        this.#setSnapshot({ state: "error", statusCode: error.code });
      } else {
        this.#fail();
      }
      throw error;
    }
  }

  /** The legacy path stays closed; a qualified receiver can prepare explicit resume. */
  public async acknowledgeGap(): Promise<void> {
    if (this.#recoveryOnly) throw new QueueInvariantError("capture_saved_recording_finish_only");
    if (this.#recovery !== null) return this.recoverInterruptedCapture("resume_capture");
    if (this.#snapshot.state !== "paused") {
      throw new QueueInvariantError("capture_state_conflict");
    }
    await this.#sourcePausePersistence;
    await this.#verifyRecoveredSourceClosed();
    await this.#confirmInterruptedSourceClosed();
    const recovery = this.#requireRecoveryState();
    if (recovery.phase === "authority_required") {
      this.#setSnapshot({ statusCode: "capture_resume_authority_required" });
      return;
    }
    const acknowledgement = {
      acknowledgedAt: this.#now().toISOString(),
      idempotencyKey: this.#operationKey("ack-gap"),
    };
    await this.#updateRecoveryState((state) =>
      acknowledgeRecoveryGap(state, acknowledgement));
    this.#setSnapshot({ statusCode: "capture_resume_authority_required" });
  }

  public async finishInterruptedCapture(): Promise<void> {
    return this.recoverInterruptedCapture("finish_capture");
  }

  private async recoverInterruptedCapture(decision: CaptureRecoveryRequest["decision"]): Promise<void> {
    if (this.#recoveryExchange !== null) throw new QueueInvariantError("capture_recovery_pending");
    const task = this.#recoverInterruptedCapture(decision);
    this.#recoveryExchange = task;
    try { await task; } finally { this.#recoveryExchange = null; }
  }

  async #recoverInterruptedCapture(decision: CaptureRecoveryRequest["decision"]): Promise<void> {
    const receiver = this.#recovery;
    const finishingOldResume = this.#recoveryOnly && decision === "finish_capture" &&
      (this.#recoveryState?.finishChoice !== undefined ||
        this.#recoveryState?.gaps.at(-1)?.acknowledgement?.decision === "continue_with_known_gap");
    if (receiver === null || this.#snapshot.state !== "paused" && !(finishingOldResume && this.#snapshot.state === "ready")) {
      throw new QueueInvariantError("capture_resume_authority_required");
    }
    if (["uploading", "completing", "processing"].includes(this.#requireActiveState().phase)) {
      await this.resumePendingWork();
      return;
    }
    this.#clearAuthorityTimeout();
    await this.#sourcePausePersistence;
    await this.#chunkPersistence;
    await this.#verifyRecoveredSourceClosed();
    await this.#confirmInterruptedSourceClosed();
    const local = this.#requireRecoveryState();
    const savedDecision = local.gaps.at(-1)?.acknowledgement?.decision;
    if (!finishingOldResume && savedDecision && savedDecision !== (decision === "finish_capture" ? "finish_capture" : "continue_with_known_gap")) {
      throw new QueueInvariantError("capture_gap_decision_conflict");
    }
    if (decision === "finish_capture" && this.#snapshot.recordedChunks < 1) {
      throw new QueueInvariantError("capture_has_no_chunks");
    }
    if (decision === "resume_capture" && this.#snapshot.recordedChunks >= this.#requireCapabilities().max_chunks) {
      throw new QueueInvariantError("capture_budget_exhausted");
    }
    if (local.phase === "ack_required") {
      await this.#updateRecoveryState(state => acknowledgeRecoveryGap(state, {
        acknowledgedAt: this.#now().toISOString(), idempotencyKey: this.#operationKey("recover-gap"),
        decision: decision === "finish_capture" ? "finish_capture" : "continue_with_known_gap",
      }));
    }
    this.#setSnapshot({ statusCode: "capture_recovery_pending", recoveryDecision: decision });
    try {
      // Reconcile an already committed ordinary renewal before constructing the
      // gap command, which must reference Scribe's current lease generation.
      const active = this.#requireActiveState();
      const pending = await this.#renewals?.getCaptureRenewal(active.sessionId, active.lease.lease_id, active.lease.generation);
      if (pending && this.#renewals) {
        await reconcileInterruptedRenewal({ intent: pending.intent, store: this.#renewals, bff: {
          recoverCapture: (...args) => receiver.recoverCapture(...args),
          getCaptureRecoveryState: (...args) => receiver.getCaptureRecoveryState(...args),
          renewLease: (...args) => this.#bff.renewLease(...args),
        }, now: this.#now, crypto: this.#crypto });
        const reconciled = await this.#flowStore.getActiveCaptureState();
        if (!reconciled || reconciled.sessionId !== active.sessionId || reconciled.phase !== "paused") {
          throw new QueueInvariantError("capture_recovery_state_conflict");
        }
        this.#activeState = reconciled;
        this.#lease = reconciled.lease;
      }
      if (finishingOldResume) {
        const resolved = await reconcileResumeForFinish({
          store:this.#flowStore,bff:receiver,active:this.#requireActiveState(),local:this.#requireRecoveryState(),
          now:this.#now,crypto:this.#crypto,idempotencyKey:()=>this.#operationKey("finish-saved"),
        });
        this.#activeState=resolved.active; this.#lease=resolved.active.lease; this.#recoveryState=resolved.local;
        if (resolved.finished) {
          await this.#saveActivePhase("uploading");
          this.#setSnapshot({state:"uploading",statusCode:"synthetic_preview_uploading",recoveryDecision:"finish_capture"});
          await this.#drainAndComplete();
          return;
        }
      }
      const remote = await exchangeRecovery({ bff: {
        recoverCapture: (...args) => receiver.recoverCapture(...args),
        getCaptureRecoveryState: (...args) => receiver.getCaptureRecoveryState(...args),
        renewLease: (...args) => this.#bff.renewLease(...args),
      }, store: this.#flowStore, active: this.#requireActiveState(),
      local: this.#requireRecoveryState(), decision, now: this.#now, crypto: this.#crypto });
      this.#activeState = await this.#flowStore.reconcileCaptureLease(remote);
      this.#lease = this.#activeState.lease;
      const receipt = remote.history.recoveries.at(-1)!;
      await this.#updateRecoveryState(state => confirmRecoveryReceipt(state, receipt));
      if (decision === "finish_capture") {
        await this.#saveActivePhase("uploading");
        this.#setSnapshot({ state: "uploading", statusCode: "synthetic_preview_uploading" });
        await this.#drainAndComplete();
        return;
      }
      this.#setCapabilities(await this.#bff.getCapabilities(this.#requireSessionId()));
      await this.#reserveRecoveryWindow();
      if (!this.#hasActiveCaptureAuthority()) throw new QueueInvariantError("capture_authority_expired");
      await this.#saveActivePhase("ready");
      this.#setSnapshot({ state: "ready", statusCode: "capture_resume_ready",
        remainingAuthoritySeconds: this.#remainingCaptureSeconds(this.#snapshot.recordedChunks) });
      this.#armAuthorityDeadline();
    } catch (error) {
      this.#setSnapshot({ state: "paused", statusCode: "capture_recovery_unconfirmed" });
      throw error;
    }
  }

  public async resumePendingWork(): Promise<void> {
    if (this.#readingAdmittedResult) {
      await this.refreshTranscriptionStatus();
      return;
    }
    const active = this.#requireActiveState();
    try {
      if (active.phase === "uploading") {
        this.#setSnapshot({ state: "uploading", statusCode: "synthetic_preview_uploading" });
        await this.#drainAndComplete();
        return;
      }
      if (active.phase === "completing") {
        await this.#completeAndRefresh();
        return;
      }
      if (active.phase === "processing") {
        await this.#purgeRegisteredChunks();
        await this.refreshTranscriptionStatus();
        return;
      }
      throw new QueueInvariantError("capture_state_conflict");
    } catch (error) {
      if (error instanceof QueueInvariantError && error.code === "capture_renewal_unconfirmed") {
        this.#setSnapshot({ state: "error", statusCode: error.code });
      } else this.#fail();
      throw error;
    }
  }

  public async refreshTranscriptionStatus(): Promise<void> {
    if (!this.#readingAdmittedResult) {
      this.#assertCompletionEligible();
      if (this.#requireActiveState().phase !== "processing") {
        throw new QueueInvariantError("capture_state_conflict");
      }
    }
    const sessionId = this.#requireSessionId();
    // The reused Scribe creator-review panel owns configured processing/readiness.
    if (this.#reviewAfterUpload) return;
    const status = await this.#bff.getTranscriptionStatus(sessionId);
    await this.#showTranscriptionStatus(status);
  }

  async #showTranscriptionStatus(status: CaptureTranscriptionStatus): Promise<void> {
    const sessionId = this.#requireSessionId();
    if (status.session_id !== sessionId) throw new QueueInvariantError("capture_session_changed");
    this.#setSnapshot({ transcriptionStatus: status });
    if (status.status === "terminal") {
      this.#setSnapshot({ state: "error", statusCode: "capture_transcription_terminal" });
      return;
    }
    if (status.status === "completed" && status.transcript_available) {
      if (this.#hasRecoveryGap() && !this.#qualifiedSource) {
        this.#setSnapshot({ state: "processing", statusCode: "capture_gap_review_required" });
        return;
      }
      const qualifiedSource = this.#qualifiedSource
        ? await validateCaptureSource(await this.#qualifiedSource.getCaptureSource(sessionId), sessionId, this.#now()) : undefined;
      if (qualifiedSource && !this.#readingAdmittedResult) {
        await assertRetainedSource(qualifiedSource, this.#requireActiveState(), this.#recoveryState, this.#flowStore);
      }
      const transcript = qualifiedSource?.raw_transcript ?? await this.#bff.getTranscript(sessionId);
      if (transcript.session_id !== sessionId) throw new QueueInvariantError("capture_session_changed");
      if (!this.#readingAdmittedResult) {
        await this.#flowStore.clearCompletedCapture(sessionId);
        this.#activeState = null;
      }
      this.#setSnapshot({
        state: "complete",
        statusCode: "synthetic_preview_complete",
        transcript,
        qualifiedSource,
      });
    }
  }

  /** Reused Scribe custody handoff: clear audio only after confirmed upload. */
  public async releaseUploadedCapture(): Promise<void> {
    if (this.#reviewAfterUpload && this.#activeState === null && this.#snapshot.state === "processing") return;
    if (!this.#reviewAfterUpload || this.#activeState?.phase !== "processing") throw new QueueInvariantError("capture_state_conflict");
    await this.#purgeRegisteredChunks();
    await this.#flowStore.clearCompletedCapture(this.#requireSessionId());
    this.#activeState = null;
  }

  /** Reopen an already uploaded configured session after local custody is clear. */
  public async restoreConfiguredResult(sessionId: string): Promise<void> {
    this.#requireState("idle");
    if (await this.#flowStore.getActiveCaptureState() !== null || await this.#flowStore.getPreparationState() !== null) {
      throw new QueueInvariantError("capture_state_conflict");
    }
    this.#sessionId = sessionId; this.#readingAdmittedResult = true; this.#reviewAfterUpload = true;
    this.#setSnapshot({sessionId, state: "processing", statusCode: "capture_creator_review"});
  }

  async #drainAndComplete(): Promise<void> {
    this.#assertCompletionEligible();
    await this.#reconcileStoppedLease();
    const drained = await this.#queue.drainOnce(this.#queueTransport);
    if (drained.items.some((item) => item.outcome !== "registered")) {
      throw new QueueInvariantError("capture_queue_not_drained");
    }
    await this.#saveActivePhase("completing");
    await this.#completeAndRefresh();
  }

  async #completeAndRefresh(): Promise<void> {
    this.#assertCompletionEligible();
    await this.#reconcileStoppedLease();
    const sessionId = this.#requireSessionId();
    const lease = this.#requireLease();
    const active = this.#requireActiveState();
    await this.#bff.completeCapture(sessionId, {
      protocol_version: PROTOCOL_VERSION,
      capture_lease_id: lease.lease_id,
      capture_lease_generation: lease.generation,
      channels: [{
        channel: "microphone",
        final_sequence_number: active.recordedChunks - 1,
      }],
    }, { idempotencyKey: active.completeIdempotencyKey });
    await this.#saveActivePhase("processing");
    await this.#purgeRegisteredChunks();
    this.#setSnapshot({ state: "processing", statusCode: "synthetic_preview_processing" });
    await this.refreshTranscriptionStatus();
  }

  async #purgeRegisteredChunks(): Promise<void> {
    for (const record of await this.#queue.listMetadata()) {
      if (
        record.reservation.sessionId === this.#requireSessionId() &&
        record.state === "registered"
      ) {
        await this.#queue.purge(record.reservation.objectId);
      }
    }
  }

  async #finishStoppedCapture(): Promise<void> {
    if (this.#snapshot.recordedChunks < 1) throw new QueueInvariantError("capture_has_no_chunks");
    await this.#updateRecoveryState(state => stopRecoverySegment(state, this.#now().toISOString(), this.#snapshot.recordedChunks));
    await this.#saveActivePhase("uploading");
    this.#setSnapshot({ state: "uploading", statusCode: "synthetic_preview_uploading" });
    await this.#drainAndComplete();
  }

  async #reconcileStoppedLease(): Promise<void> {
    // Stop never waits on a hung renewal before closing audio. Keep this saved
    // upload retryable until any outstanding response has been journaled.
    if (this.#renewalTask) throw new QueueInvariantError("capture_renewal_unconfirmed");
    const active = this.#requireActiveState();
    if (!this.#renewals || !this.#recovery || this.#recoveryState?.phase !== "stopped") return;
    const record = await this.#renewals.getCaptureRenewal(active.sessionId, active.lease.lease_id, active.lease.generation);
    if (!record) return;
    await reconcileStoppedRenewal({ intent: record.intent, store: this.#renewals, now: this.#now, crypto: this.#crypto,
      bff: { renewLease: (...args) => this.#bff.renewLease(...args),
        getCaptureRecoveryState: (...args) => this.#recovery!.getCaptureRecoveryState(...args),
        recoverCapture: (...args) => this.#recovery!.recoverCapture(...args) } });
    const current = await this.#flowStore.getActiveCaptureState();
    requireRenewal(current && current.sessionId === active.sessionId && ["uploading", "completing"].includes(current.phase));
    this.#activeState = current;
    this.#lease = current.lease;
  }

  #suppressRenewal(): void {
    if (this.#continuousRun) this.#continuousRun.stopping = true;
    if (this.#renewalTimeout !== null) this.#cancelTimeout(this.#renewalTimeout);
    this.#renewalTimeout = null;
  }

  #requireContinuous(run: ContinuousCaptureRun): void {
    requireRenewal(run === this.#continuousRun && !run.stopping && !run.closed && !this.#disposed &&
      !this.#authorityExpiryRequested && this.#snapshot.state === "recording" && this.#now().getTime() < run.deadline);
  }

  #scheduleRenewal(run: ContinuousCaptureRun): void {
    if (run !== this.#continuousRun || run.stopping || run.closed || this.#disposed ||
      !this.#sourceStarted || this.#renewalTask || run.maximumChunks >= run.hardMaximumChunks) return;
    if (this.#renewalTimeout !== null) this.#cancelTimeout(this.#renewalTimeout);
    const duration = this.#requireCapabilities().target_chunk_duration_ms;
    const remaining = run.maximumChunks - (this.#snapshot.recordedChunks - run.firstSequence);
    const lead = Math.min(6, Math.max(1, Math.floor(run.maximumChunks / 4)));
    const now = this.#now().getTime();
    if (remaining <= lead || run.deadline - now <= lead * duration) {
      this.#renewalTimeout = null;
      const task = this.#renewContinuous(run);
      this.#renewalTask = task;
      void task.catch(async () => {
        if (run !== this.#continuousRun || run.stopping || run.closed) return;
        this.#pauseAfterSourceSignal("capture_source_failed");
        this.#recordingAbortController?.abort();
        try {
          await this.#source.stop();
          await this.#sourcePausePersistence;
          await this.#chunkPersistence;
          run.closed = true;
          await this.#confirmInterruptedSourceClosed(true);
        } catch (error) { this.#setSnapshot({ state: "paused", statusCode: sourceCloseFailure(error).code }); }
      }).finally(() => {
        if (this.#renewalTask === task) this.#renewalTask = null;
        this.#scheduleRenewal(run);
      });
      return;
    }
    const estimatedDue = run.readyAt + (run.maximumChunks - lead) * duration;
    const delay = Math.max(1, Math.min(run.deadline - now - lead * duration,
      Math.max(Math.min(1000, duration), estimatedDue - now)));
    this.#renewalTimeout = this.#scheduleTimeout(() => { this.#renewalTimeout = null; this.#scheduleRenewal(run); }, delay);
  }

  /** Serialize durable state changes with audio saves, never with network I/O. */
  #withChunkPersistence<T>(action: () => Promise<T>): Promise<T> {
    const task = this.#chunkPersistence.then(action);
    this.#chunkPersistence = task.then(() => undefined, () => undefined);
    return task;
  }

  async #renewContinuous(run: ContinuousCaptureRun): Promise<void> {
    const intent = await this.#withChunkPersistence(async () => {
      this.#requireContinuous(run);
      const active = this.#requireActiveState(), capabilities = this.#requireCapabilities();
      const existing = await this.#renewals!.getCaptureRenewal(active.sessionId, active.lease.lease_id, active.lease.generation);
      if (existing) return existing.intent;
      const first = active.recordedChunks + 1;
      const count = Math.min(90, capabilities.max_reservations_per_batch,
        run.firstSequence + run.hardMaximumChunks - first,
        Math.floor((active.aggregatePlaintextBudgetBytes - this.#recordedPlaintextBytes) / capabilities.max_envelope_bytes) - 1);
      requireRenewal(count > 0);
      const intent = validateRenewalIntent({ schemaVersion: 1, sessionId: active.sessionId,
        profileReceiptId: this.#captureProfile!.receipt_id, segmentId: run.id,
        segmentOrdinal: this.#requireRecoveryState().segments.at(-1)!.ordinal,
        priorLease: active.lease, priorCaptureAuthorizedUntil: active.captureAuthorizedUntil!,
        firstSequenceNumber: first, count, leaseIdempotencyKey: this.#operationKey("renew-lease"),
        reservationIdempotencyKey: this.#operationKey("renew-reserve"), createdAt: this.#now().toISOString() });
      this.#requireContinuous(run);
      await this.#renewals!.putCaptureRenewal({ intent, lease: null, reservations: null });
      return intent;
    });
    const exchange = () => exchangeCaptureRenewal({ intent, store: this.#renewals!, bff: this.#bff,
      now: this.#now, requireContinuous: () => this.#requireContinuous(run) });
    let record: CaptureRenewalRecord;
    const retriedStages = new Set<string>();
    for (;;) {
      try { record = await exchange(); break; } catch (error) {
        this.#requireContinuous(run);
        if (error instanceof QueueInvariantError || error instanceof BffResponseError && error.status < 500) throw error;
        const saved = await this.#renewals!.getCaptureRenewal(intent.sessionId, intent.priorLease.lease_id, intent.priorLease.generation);
        const stage = saved?.lease ? "reservations" : "lease";
        // A visit can lose one reply at each distinct stage. Allow one exact
        // retry per stage, without repeatedly retrying a failing endpoint.
        if (retriedStages.has(stage)) throw error;
        retriedStages.add(stage);
      }
    }
    const extension = await this.#withChunkPersistence(async () => {
      this.#requireContinuous(run);
      for (const remote of record.reservations!.reservations) {
        const reservation: ChunkReservation = { protocolVersion: remote.protocol_version, objectId: remote.object_id,
          sessionId: remote.session_id, channel: remote.channel, sequenceNumber: remote.sequence_number,
          additionalAuthenticatedData: remote.additional_authenticated_data, createdAt: remote.created_at };
        const prior = this.#reservations.get(reservation.sequenceNumber);
        requireRenewal(!prior || prior.objectId === reservation.objectId && prior.protocolVersion === reservation.protocolVersion &&
          prior.sessionId === reservation.sessionId && prior.channel === reservation.channel &&
          prior.additionalAuthenticatedData === reservation.additionalAuthenticatedData &&
          canonicalCaptureTimestamp(prior.createdAt) === canonicalCaptureTimestamp(reservation.createdAt));
        // Preserve the original timestamp representation and stable queue keys
        // when the server acknowledges a previously reserved future object.
        await this.#queue.reserve(prior ?? reservation, intent.reservationIdempotencyKey);
        this.#reservations.set(reservation.sequenceNumber, prior ?? reservation);
        this.#requireContinuous(run);
      }
      this.#activeState = await this.#renewals!.applyCaptureRenewal(intent, "continuous", this.#now());
      this.#lease = this.#activeState.lease;
      this.#requireContinuous(run);
      let end = this.#activeState.recordedChunks;
      while (this.#reservations.has(end)) end++;
      const maximumChunks = Math.min(run.hardMaximumChunks, end - run.firstSequence,
        this.#activeState.recordedChunks - run.firstSequence + Math.floor(
          (Date.parse(record.lease!.expires_at) - this.#now().getTime()) / this.#requireCapabilities().target_chunk_duration_ms));
      requireRenewal(maximumChunks >= run.maximumChunks);
      run.admittedMaximumChunks = maximumChunks;
      this.#setSnapshot({ queuedChunks: this.#reservations.size });
      return { runId: run.id, generation: record.lease!.generation,
        expiresAtMs: Date.parse(record.lease!.expires_at), maximumChunks };
    });
    this.#requireContinuous(run);
    // The source may await an audio save before confirming. Do not hold the
    // persistence chain while waiting for its acknowledgment.
    await this.#source.extend!(extension);
    this.#requireContinuous(run);
    run.generation = extension.generation;
    run.maximumChunks = extension.maximumChunks;
    run.deadline = extension.expiresAtMs;
    this.#armAuthorityDeadline();
    this.#setSnapshot({ remainingAuthoritySeconds: this.#remainingCaptureSeconds(this.#snapshot.recordedChunks) });
  }

  #sourceWindowClosed(run: ContinuousCaptureRun, _reason: "authority_expired" | "frame_limit"): void {
    if (run !== this.#continuousRun || run.stopping || run.closed || this.#snapshot.state !== "recording") return;
    this.#clearAuthorityTimeout();
    this.#suppressRenewal();
    this.#authorityExpiryRequested = true;
    this.#launchAuthorityExpiry();
  }

  async #bindSessionKey(sessionId: string): Promise<void> {
    const existing = await this.#flowStore.getSessionKeyState(sessionId);
    if (existing !== null) {
      await this.#bindStoredSessionKey(existing);
      return;
    }

    const first = await this.#createSessionKeyCandidate(sessionId);
    await this.#flowStore.putSessionKeyCandidate(first.state, first.key);
    try {
      await this.#bindStoredSessionKey(first.state);
    } catch (error) {
      if (!(error instanceof BffResponseError) || error.status !== 409) throw error;
      const replacement = await this.#createSessionKeyCandidate(sessionId);
      await this.#flowStore.replacePendingSessionKeyCandidate(replacement.state, replacement.key);
      await this.#bindStoredSessionKey(replacement.state);
    }
  }

  async #createSessionKeyCandidate(sessionId: string): Promise<{
    readonly state: SessionKeyBindingState;
    readonly key: CryptoKey;
  }> {
    const published = await this.#bff.getAudioEncryptionKey();
    const wrapped = await createWrappedSessionKey(published, this.#crypto);
    return {
      key: wrapped.key,
      state: {
        schemaVersion: FLOW_RECORD_SCHEMA_VERSION,
        sessionId,
        keyVersion: wrapped.keyVersion,
        wrappedDek: wrapped.wrappedDek,
        idempotencyKey: this.#operationKey("bind-key"),
        state: "pending",
      },
    };
  }

  async #bindStoredSessionKey(state: SessionKeyBindingState): Promise<void> {
    if (state.state === "bound") return;
    await this.#bff.bindSessionAudioKey(state.sessionId, {
      key_version: state.keyVersion,
      wrapped_dek: state.wrappedDek,
    }, { idempotencyKey: state.idempotencyKey });
    await this.#flowStore.markSessionKeyBound(state.sessionId);
  }

  async #reserveInitialWindow(): Promise<void> {
    const capabilities = this.#requireCapabilities();
    const lease = this.#requireLease();
    const sessionId = this.#requireSessionId();
    const budgetCount = Math.floor(
      capabilities.remaining_aggregate_plaintext_bytes / capabilities.max_envelope_bytes,
    );
    const count = Math.min(
      capabilities.max_reservations_per_batch,
      capabilities.max_chunks,
      budgetCount,
    );
    if (!Number.isSafeInteger(count) || count < 1) {
      throw new QueueInvariantError("capture_budget_exhausted");
    }
    const intent: ReservationIntent = {
      schemaVersion: FLOW_RECORD_SCHEMA_VERSION,
      intentId: `${sessionId}:microphone:0:${String(count)}`,
      sessionId,
      idempotencyKey: this.#operationKey("reserve"),
      createdAt: this.#now().toISOString(),
      request: {
        protocol_version: PROTOCOL_VERSION,
        capture_lease_id: lease.lease_id,
        capture_lease_generation: lease.generation,
        channel: "microphone",
        first_sequence_number: 0,
        count,
      },
    };
    await this.#flowStore.putReservationIntent(intent);
    await this.#replayReservationIntent(intent);
  }

  async #recoverReservationIntents(): Promise<void> {
    for (const intent of await this.#flowStore.listReservationIntents()) {
      if (intent.sessionId !== this.#requireSessionId()) continue;
      await this.#replayReservationIntent(intent);
    }
  }

  async #reserveRecoveryWindow(): Promise<void> {
    const active = this.#requireActiveState(), capabilities = this.#requireCapabilities();
    const first = active.recordedChunks;
    const pending = (await this.#flowStore.listReservationIntents()).find(intent =>
      intent.sessionId === active.sessionId && intent.request.capture_lease_generation === active.lease.generation &&
      intent.request.first_sequence_number === first);
    if (pending) return this.#replayReservationIntent(pending);
    const count = Math.min(capabilities.max_reservations_per_batch, capabilities.max_chunks - first,
      Math.floor((active.aggregatePlaintextBudgetBytes - active.recordedPlaintextBytes) / capabilities.max_envelope_bytes));
    if (!Number.isSafeInteger(count) || count < 1) throw new QueueInvariantError("capture_budget_exhausted");
    const intent: ReservationIntent = { schemaVersion: FLOW_RECORD_SCHEMA_VERSION,
      intentId: `${active.sessionId}:recovery:${active.lease.generation}:${first}:${count}`,
      sessionId: active.sessionId, idempotencyKey: this.#operationKey("recover-reserve"),
      createdAt: this.#now().toISOString(), request: { protocol_version: PROTOCOL_VERSION,
        capture_lease_id: active.lease.lease_id, capture_lease_generation: active.lease.generation,
        channel: "microphone", first_sequence_number: first, count } };
    await this.#flowStore.putReservationIntent(intent);
    await this.#replayReservationIntent(intent);
  }

  async #replayReservationIntent(intent: ReservationIntent): Promise<void> {
    const batch = await this.#bff.reserveChunks(
      intent.sessionId,
      intent.request,
      { idempotencyKey: intent.idempotencyKey },
    );
    await this.#persistReservations(batch, intent.idempotencyKey);
    await this.#flowStore.deleteReservationIntent(intent.intentId);
  }

  async #persistReservations(
    batch: ChunkReservationBatchReceipt,
    idempotencyKey: string,
  ): Promise<void> {
    if (
      batch.protocol_version !== PROTOCOL_VERSION ||
      batch.session_id !== this.#requireSessionId() ||
      Number.isNaN(Date.parse(batch.capture_authorized_until))
    ) {
      throw new QueueInvariantError("invalid_capture_authority");
    }
    const active = this.#requireActiveState();
    if (
      active.captureAuthorizedUntil !== null &&
      active.captureAuthorizedUntil !== batch.capture_authorized_until
    ) {
      throw new QueueInvariantError("capture_authority_conflict");
    }
    if (active.captureAuthorizedUntil === null) {
      this.#activeState = {
        ...active,
        captureAuthorizedUntil: batch.capture_authorized_until,
      };
      await this.#flowStore.putActiveCaptureState(this.#activeState);
    }
    for (const remote of batch.reservations) {
      const reservation: ChunkReservation = {
        protocolVersion: remote.protocol_version,
        objectId: remote.object_id,
        sessionId: remote.session_id,
        channel: remote.channel,
        sequenceNumber: remote.sequence_number,
        additionalAuthenticatedData: remote.additional_authenticated_data,
        createdAt: remote.created_at,
      };
      await this.#queue.reserve(reservation, idempotencyKey);
      this.#reservations.set(reservation.sequenceNumber, reservation);
    }
    this.#setSnapshot({ queuedChunks: this.#reservations.size });
  }

  async #acceptChunk(chunk: CapturedWavChunk, run: ContinuousCaptureRun | null = null): Promise<void> {
    const task = this.#chunkPersistence.then(async () => {
      try {
        // Qualified producers enforce the capture deadline themselves. Their
        // accepted final buffer may finish encryption after the wall deadline.
        const boundedDelivery = run !== null && run === this.#continuousRun && !run.closed &&
          chunk.sequenceNumber >= run.firstSequence &&
          chunk.sequenceNumber < run.firstSequence + Math.min(run.admittedMaximumChunks, run.hardMaximumChunks);
        if (run !== null && !boundedDelivery) throw new QueueInvariantError("capture_state_conflict");
        if (this.#authorityExpiryRequested && !boundedDelivery) {
          throw new QueueInvariantError("capture_authority_expired");
        }
        await this.#acceptChunkAndPersist(chunk, boundedDelivery);
      } finally {
        chunk.wavBytes.fill(0);
      }
    });
    this.#chunkPersistence = task.catch(() => undefined);
    void task.then(() => { if (run) this.#scheduleRenewal(run); }).catch(() => undefined);
    return task;
  }

  async #acceptChunkAndPersist(chunk: CapturedWavChunk, boundedDelivery = false): Promise<void> {
    if (this.#snapshot.state !== "recording") {
      throw new QueueInvariantError("capture_state_conflict");
    }
    if (!boundedDelivery && !this.#hasActiveCaptureAuthority()) {
      await this.#pauseForExpiredAuthority();
      throw new QueueInvariantError("capture_authority_expired");
    }
    if (chunk.sequenceNumber !== this.#snapshot.recordedChunks) {
      throw new QueueInvariantError("capture_recovery_sequence_conflict");
    }
    const reservation = this.#reservations.get(chunk.sequenceNumber);
    if (reservation === undefined) throw new QueueInvariantError("chunk_not_reserved");
    const capabilities = this.#requireCapabilities();
    if (chunk.durationMs > capabilities.target_chunk_duration_ms) {
      throw new QueueInvariantError("capture_chunk_duration_exceeded");
    }
    const nextPlaintextBytes = this.#recordedPlaintextBytes + chunk.wavBytes.byteLength;
    if (nextPlaintextBytes > this.#requireActiveState().aggregatePlaintextBudgetBytes) {
      throw new QueueInvariantError("capture_budget_exhausted");
    }
    const key = await this.#flowStore.getSessionKey(this.#requireSessionId());
    if (key === null) throw new QueueInvariantError("session_key_missing");
    const nonce = this.#crypto.getRandomValues(new Uint8Array(new ArrayBuffer(NONCE_BYTES)));
    const decodedAdditionalData = base64UrlDecode(reservation.additionalAuthenticatedData);
    const additionalData = new Uint8Array(new ArrayBuffer(decodedAdditionalData.byteLength));
    additionalData.set(decodedAdditionalData);
    let ciphertext: ArrayBuffer;
    try {
      ciphertext = await this.#crypto.subtle.encrypt(
        { name: "AES-GCM", iv: nonce, additionalData },
        key,
        chunk.wavBytes,
      );
    } finally {
      chunk.wavBytes.fill(0);
    }
    const ciphertextBytes = new Uint8Array(ciphertext);
    let envelope: Uint8Array;
    try {
      envelope = encodeEnvelope({
        schema_version: PROTOCOL_VERSION,
        content_encryption: "A256GCM",
        nonce: base64UrlEncode(nonce),
        media_type: "audio/wav",
      }, ciphertextBytes);
    } finally {
      ciphertextBytes.fill(0);
    }
    if (envelope.byteLength > capabilities.max_envelope_bytes) {
      envelope.fill(0);
      throw new QueueInvariantError("capture_envelope_too_large");
    }
    await this.#queue.encrypt(reservation.objectId, envelope);
    envelope.fill(0);
    this.#recordedPlaintextBytes = nextPlaintextBytes;
    const recordedChunks = this.#snapshot.recordedChunks + 1;
    const active = this.#requireActiveState();
    this.#activeState = {
      ...active,
      recordedChunks,
      recordedPlaintextBytes: this.#recordedPlaintextBytes,
    };
    await this.#flowStore.putActiveCaptureState(this.#activeState);
    this.#setSnapshot({
      recordedChunks,
      elapsedSeconds: captureSeconds(capabilities, recordedChunks),
      remainingBudgetSeconds: this.#remainingAggregateBudgetSeconds(recordedChunks),
      remainingAuthoritySeconds: this.#remainingCaptureSeconds(recordedChunks),
    });
  }

  #setCapabilities(capabilities: CaptureCapabilities): void {
    if (this.#captureProfile) {
      const validated = validateProfileCapabilities(capabilities, this.#captureProfile);
      capabilities = { ...validated, max_chunks: this.#captureProfile.maximum_chunks_per_channel };
    }
    this.#queue.configureUploadConcurrency(capabilities.upload_concurrency);
    this.#capabilities = capabilities;
  }

  #canCreateOrRecoverReservations(): boolean {
    const active = this.#requireActiveState();
    if (Date.parse(active.lease.expires_at) <= this.#now().getTime()) return false;
    return (
      active.captureAuthorizedUntil === null ||
      Date.parse(active.captureAuthorizedUntil) > this.#now().getTime()
    );
  }

  #hasActiveCaptureAuthority(): boolean {
    const deadline = this.#captureAuthorityDeadline();
    return deadline !== null && deadline > this.#now().getTime() && this.#reservations.size > 0;
  }

  #captureAuthorityDeadline(): number | null {
    const active = this.#requireActiveState();
    if (active.captureAuthorizedUntil === null) return null;
    return Math.min(
      Date.parse(active.lease.expires_at),
      Date.parse(active.captureAuthorizedUntil),
    );
  }

  #captureCapabilitiesForReservedWindow(): CaptureCapabilities {
    const capabilities = this.#requireCapabilities();
    const deadline = this.#captureAuthorityDeadline();
    if (deadline === null) throw new QueueInvariantError("capture_authority_missing");
    const windowChunks = Math.floor(
      Math.max(0, deadline - this.#now().getTime()) /
        capabilities.target_chunk_duration_ms,
    );
    const aggregateRemainingBytes = Math.max(
      0,
      this.#requireActiveState().aggregatePlaintextBudgetBytes - this.#recordedPlaintextBytes,
    );
    const budgetChunks = Math.floor(aggregateRemainingBytes / capabilities.max_envelope_bytes);
    const maxChunks = Math.min(
      capabilities.max_chunks,
      this.#reservations.size - this.#requireActiveState().recordedChunks,
      windowChunks,
      budgetChunks,
    );
    if (!Number.isSafeInteger(maxChunks) || maxChunks < 1) {
      throw new QueueInvariantError("capture_authority_expired");
    }
    return {
      ...capabilities,
      max_chunks: maxChunks,
      remaining_aggregate_plaintext_bytes: Math.min(
        aggregateRemainingBytes,
        maxChunks * capabilities.max_envelope_bytes,
      ),
    };
  }

  #remainingCaptureSeconds(recordedChunks: number): number {
    const capabilities = this.#requireCapabilities();
    const deadline = this.#captureAuthorityDeadline();
    if (deadline === null) return 0;
    const remainingReservedChunks = Math.max(0, this.#reservations.size - recordedChunks);
    const reservedSeconds = Math.floor(
      (remainingReservedChunks * capabilities.target_chunk_duration_ms) / 1_000,
    );
    const authoritySeconds = Math.max(
      0,
      Math.floor((deadline - this.#now().getTime()) / 1_000),
    );
    return Math.min(reservedSeconds, authoritySeconds);
  }

  #remainingAggregateBudgetSeconds(recordedChunks: number): number {
    const capabilities = this.#requireCapabilities();
    const budgetChunks = Math.min(
      capabilities.max_chunks,
      Math.floor(
        this.#requireActiveState().aggregatePlaintextBudgetBytes /
          capabilities.max_envelope_bytes,
      ),
    );
    return Math.max(
      0,
      Math.floor(
        ((budgetChunks - recordedChunks) * capabilities.target_chunk_duration_ms) / 1_000,
      ),
    );
  }

  async #pauseForExpiredAuthority(): Promise<void> {
    if (this.#recoveryState?.phase === "recording") {
      await this.#recordRecoveryGap("capture_authority_expired");
    }
    await this.#saveActivePhase("paused");
    this.#setSnapshot({
      state: "paused",
      statusCode: "capture_authority_expired",
      remainingAuthoritySeconds: 0,
    });
  }

  #armAuthorityDeadline(): void {
    this.#clearAuthorityTimeout();
    if (this.#disposed) return;
    // Until the producer confirms, the previous deadline remains in force even
    // if the new server receipt has already been durably applied.
    const deadline = this.#snapshot.state === "recording" && this.#continuousRun
      ? this.#continuousRun.deadline : this.#captureAuthorityDeadline();
    if (deadline === null) return;
    const version = this.#authorityTimerVersion;
    const delayMs = Math.max(0, deadline - this.#now().getTime());
    this.#authorityTimeout = this.#scheduleTimeout(() => {
      if (version !== this.#authorityTimerVersion || this.#continuousRun?.stopping && this.#snapshot.state === "recording") return;
      this.#authorityTimeout = null;
      this.#suppressRenewal();
      this.#authorityExpiryRequested = true;
      this.#launchAuthorityExpiry();
    }, delayMs);
  }

  #launchAuthorityExpiry(): void {
    const task = this.#expireCaptureAuthority();
    this.#authorityExpiryTask = task;
    void task
      .catch((error: unknown) => {
        if (isSourceCloseFailure(error)) {
          if (this.#authorityExpiryTask === task) this.#authorityExpiryTask = null;
          this.#setSnapshot({ state: "paused", statusCode: error.code });
        } else if (error instanceof QueueInvariantError && error.code === "capture_renewal_unconfirmed") {
          this.#setSnapshot({ state: "error", statusCode: error.code });
        } else {
          this.#fail();
        }
      })
      .finally(() => {
        if (this.#authorityExpiryTask === task) this.#authorityExpiryTask = null;
      });
  }

  #clearAuthorityTimeout(): void {
    this.#authorityTimerVersion++;
    if (this.#authorityTimeout === null) return;
    this.#cancelTimeout(this.#authorityTimeout);
    this.#authorityTimeout = null;
  }

  async #expireCaptureAuthority(): Promise<void> {
    if (this.#snapshot.state !== "ready" && this.#snapshot.state !== "recording") return;
    const wasRecording = this.#snapshot.state === "recording";
    const observedAt = this.#now().toISOString();
    const run = this.#continuousRun;
    if (wasRecording && run) {
      // Drain the qualified producer rather than aborting its already accepted
      // partial buffer. New audio is independently bounded by that producer.
      try { await this.#source.stop(); } catch (error) {
        await this.#sourcePausePersistence;
        await this.#chunkPersistence;
        if (this.#requireRecoveryState().phase === "recording") {
          await this.#recordRecoveryGap("capture_source_failed", this.#snapshot.recordedChunks, observedAt);
          await this.#saveActivePhase("paused");
        }
        throw sourceCloseFailure(error);
      }
      await this.#sourcePausePersistence;
      await this.#chunkPersistence;
      run.closed = true;
      this.#sourceStarted = false;
      this.#recordingAbortController = null;
      if (this.#requireRecoveryState().phase !== "recording") {
        await this.#confirmInterruptedSourceClosed(true);
        return;
      }
      if (this.#snapshot.recordedChunks - run.firstSequence === run.hardMaximumChunks) {
        await this.#finishStoppedCapture();
        return;
      }
      await this.#recordRecoveryGap("capture_authority_expired", this.#snapshot.recordedChunks, observedAt);
      await this.#pauseForExpiredAuthority();
      await this.#confirmInterruptedSourceClosed(true);
      return;
    }
    let sourceStop: Promise<void> | null = null;
    if (wasRecording) {
      this.#sourcePausedBySignal = true;
      this.#recordingAbortController?.abort();
      sourceStop = this.#sourceStarted ? this.#source.stop() : null;
      void sourceStop?.catch(() => undefined);
      await this.#chunkPersistence;
      await this.#recordRecoveryGap(
        "capture_authority_expired",
        this.#snapshot.recordedChunks,
        observedAt,
      );
    }
    await this.#pauseForExpiredAuthority();
    if (sourceStop !== null) {
      try {
        await sourceStop;
      } catch (error) {
        throw sourceCloseFailure(error);
      }
      this.#sourceStarted = false;
      await this.#confirmInterruptedSourceClosed(true);
    }
  }

  #pauseAfterSourceSignal(
    code: CaptureSourceErrorCode | CaptureSourceInterruptionCode,
  ): void {
    if (this.#snapshot.state !== "recording" || this.#authorityExpiryRequested && !this.#continuousRun) return;
    this.#suppressRenewal();
    this.#clearAuthorityTimeout();
    this.#sourcePausedBySignal = true;
    const observedAt = this.#now().toISOString();
    this.#setSnapshot({ state: "paused", statusCode: code });
    const persistence = this.#chunkPersistence
      .then(() => this.#recordRecoveryGap(
        code,
        this.#snapshot.recordedChunks,
        observedAt,
      ))
      .then(() => this.#saveActivePhase("paused"));
    this.#sourcePausePersistence = persistence;
    void persistence.catch(() => this.#fail());
  }

  #operationKey(operation: string): string {
    return `${operation}:${this.#idFactory()}`;
  }

  #requireState(expected: CaptureFlowState): void {
    if (this.#disposed || this.#snapshot.state !== expected) throw new QueueInvariantError("capture_state_conflict");
  }

  #requireCapabilities(): CaptureCapabilities {
    if (this.#capabilities === null) throw new QueueInvariantError("capture_capabilities_missing");
    return this.#capabilities;
  }

  #requireLease(): CaptureLeaseReceipt {
    if (this.#lease === null) throw new QueueInvariantError("capture_lease_missing");
    return this.#lease;
  }

  #requireSessionId(): string {
    if (this.#sessionId === null) throw new QueueInvariantError("capture_session_missing");
    return this.#sessionId;
  }

  #requireActiveState(): ActiveCaptureState {
    if (this.#activeState === null) throw new QueueInvariantError("active_capture_missing");
    return this.#activeState;
  }

  async #saveActivePhase(phase: ActiveCapturePhase): Promise<void> {
    this.#activeState = { ...this.#requireActiveState(), phase };
    await this.#flowStore.putActiveCaptureState(this.#activeState);
  }

  async #restoreRecoveryState(
    active: ActiveCaptureState,
    nextSequenceNumber: number,
    storedRecovery: CaptureRecoveryStateV1 | null,
  ): Promise<void> {
    this.#recoveryState = storedRecovery;
    if (this.#recoveryState === null) {
      this.#recoveryState = createCaptureRecoveryState(active.sessionId);
      await this.#flowStore.putCaptureRecoveryState(this.#recoveryState);
      this.#legacyCompletionEligible =
        active.phase === "uploading" || active.phase === "completing" ||
        active.phase === "processing";
    } else {
      this.#legacyCompletionEligible =
        this.#recoveryState.phase === "ready" &&
        this.#recoveryState.segments.length === 0 &&
        (active.phase === "uploading" || active.phase === "completing" ||
          active.phase === "processing");
    }
    if (this.#recoveryState.phase === "interruption_closing") {
      // A fresh JS source cannot prove that an orphaned native token was released.
      this.#recoveredUnverifiedClose = true;
    }
    const shouldRecoverUnknown =
      active.phase === "recording" || this.#recoveryState.phase === "recording" ||
      (active.phase === "paused" && active.recordedChunks > 0 &&
        this.#recoveryState.phase === "ready" && this.#recoveryState.segments.length === 0);
    if (shouldRecoverUnknown && this.#recoveryState.phase === "ready") {
      const authorizedUntil = active.captureAuthorizedUntil;
      if (authorizedUntil === null) {
        throw new QueueInvariantError("capture_authority_missing");
      }
      await this.#updateRecoveryState((state) => beginRecoverySegment(state, {
        segmentId: this.#idFactory(),
        recoveryGapId: this.#idFactory(),
        startedAt: active.startedAt,
        leaseGeneration: active.lease.generation,
        captureAuthorizedUntil: authorizedUntil,
      }));
    }
    if (shouldRecoverUnknown && this.#requireRecoveryState().phase === "recording") {
      await this.#recordRecoveryGap("process_recovery_unknown", nextSequenceNumber);
      this.#recoveredUnverifiedClose = true;
    }
    const recovery = this.#requireRecoveryState();
    const activeIsCapturePhase =
      active.phase === "ready" || active.phase === "recording" || active.phase === "paused";
    if (
      recovery.phase !== "recording" &&
      recovery.phase !== "ready" &&
      (
        recovery.nextSequenceNumber !== this.#requireActiveState().recordedChunks ||
        (activeIsCapturePhase && recovery.nextSequenceNumber !== nextSequenceNumber)
      )
    ) {
      throw new QueueInvariantError("capture_recovery_sequence_conflict");
    }
  }

  async #recordRecoveryGap(
    reasonCode: CaptureGapReasonCode,
    nextSequenceNumber = this.#snapshot.recordedChunks,
    observedAt = this.#now().toISOString(),
  ): Promise<void> {
    await this.#updateRecoveryState((state) => observeRecoveryGap(state, {
      reasonCode,
      observedAt,
      nextSequenceNumber,
    }));
  }

  async #verifyRecoveredSourceClosed(): Promise<void> {
    if (!this.#recoveredUnverifiedClose) return;
    let confirmed = false;
    try { confirmed = await this.#source.confirmRecoveryClosed?.() === true; }
    catch { /* Unavailable native proof retains the same recovery fence. */ }
    if (!confirmed) {
      this.#setSnapshot({ statusCode: "capture_source_close_unverified" });
      throw new QueueInvariantError("capture_source_close_unverified");
    }
    await this.#confirmInterruptedSourceClosed(true);
    this.#recoveredUnverifiedClose = false;
  }

  async #confirmInterruptedSourceClosed(sourceAlreadyClosed = false): Promise<void> {
    const recovery = this.#requireRecoveryState();
    if (recovery.phase !== "interruption_closing") return;
    if (!sourceAlreadyClosed) {
      try {
        await this.#source.stop();
      } catch (error) {
        throw sourceCloseFailure(error);
      }
    }
    this.#sourceStarted = false;
    this.#recordingAbortController = null;
    await this.#updateRecoveryState(confirmRecoverySourceClosed);
  }

  async #updateRecoveryState(
    transition: (state: CaptureRecoveryStateV1) => CaptureRecoveryStateV1,
  ): Promise<void> {
    const task = this.#recoveryPersistence.then(async () => {
      const current = this.#requireRecoveryState();
      const replacement = transition(current);
      if (replacement === current) return;
      await this.#flowStore.putCaptureRecoveryState(replacement);
      this.#recoveryState = replacement;
    });
    this.#recoveryPersistence = task.catch(() => undefined);
    return task;
  }

  #requireRecoveryState(): CaptureRecoveryStateV1 {
    if (this.#recoveryState === null) {
      throw new QueueInvariantError("capture_recovery_state_missing");
    }
    return this.#recoveryState;
  }

  #hasRecoveryGap(): boolean {
    return this.#recoveryState?.noteReadiness === "review_required";
  }

  #assertCompletionEligible(): void {
    const recovery = this.#requireRecoveryState();
    if (
      (recovery.noteReadiness !== "eligible" && (this.#recovery === null ||
        recovery.gaps.some(gap => gap.acknowledgement === null ||
          gap.followingSegmentId === null && gap.acknowledgement.decision !== "finish_capture"))) ||
      (recovery.phase !== "stopped" && !this.#legacyCompletionEligible)
    ) {
      throw new QueueInvariantError("capture_gap_review_required");
    }
  }

  #recoveryStatusCode(): string | null {
    const phase = this.#recoveryState?.phase;
    if (phase === "interruption_closing") return "capture_interruption_closing";
    if (phase === "ack_required") return "capture_gap_ack_required";
    if (phase === "authority_required") return "capture_resume_authority_required";
    return null;
  }

  #fail(): void {
    this.#suppressRenewal();
    this.#clearAuthorityTimeout();
    this.#authorityExpiryRequested = true;
    this.#recordingAbortController?.abort();
    this.#setSnapshot({ state: "error", statusCode: "synthetic_preview_failed" });
  }

  #setSnapshot(patch: Partial<CaptureFlowSnapshot>): void {
    this.#snapshot = { ...this.#snapshot, ...patch };
    for (const listener of this.#listeners) listener(this.snapshot);
  }
}

function isNativeStopFailure(error: unknown): error is AudioCaptureError {
  return error instanceof AudioCaptureError && error.code === "audio_capture_native_stop_failed";
}

function sourceCloseFailure(error: unknown): AudioCaptureError | QueueInvariantError {
  return isNativeStopFailure(error)
    ? error
    : new QueueInvariantError("capture_source_close_failed");
}

function isSourceCloseFailure(
  error: unknown,
): error is AudioCaptureError | QueueInvariantError {
  return isNativeStopFailure(error) ||
    (error instanceof QueueInvariantError && error.code === "capture_source_close_failed");
}

function isRecoveryHold(error: unknown): error is QueueInvariantError {
  return error instanceof QueueInvariantError &&
    (error.code === "capture_gap_review_required" ||
      error.code === "capture_source_close_unverified");
}

function contiguousRecordedChunkCount(
  records: readonly CaptureChunkMetadata[],
): number {
  const sequences = records
    .map((record) => record.reservation.sequenceNumber)
    .sort((left, right) => left - right);
  for (const [expected, actual] of sequences.entries()) {
    if (actual !== expected) {
      throw new QueueInvariantError("capture_recovery_sequence_conflict");
    }
  }
  return sequences.length;
}

function restoredSnapshotState(phase: ActiveCapturePhase): CaptureFlowState {
  if (phase === "ready") return "ready";
  if (phase === "recording" || phase === "paused") return "paused";
  if (phase === "uploading" || phase === "completing") return "uploading";
  return "processing";
}

function consentRequest(encounter: SyntheticEncounter, grantedAt: Date): ConsentCreate {
  return {
    appointment_id: encounter.appointmentId,
    practitioner_id: encounter.practitionerId,
    patient_id: encounter.patientId,
    modality: "in_person",
    method: "verbal_attestation",
    all_parties_consented: true,
    participant_regions: [...encounter.participantRegions],
    granted_at: grantedAt.toISOString(),
    evidence_object_id: null,
  };
}

function restoredStatusCode(phase: ActiveCapturePhase): string {
  if (phase === "ready") return "synthetic_preview_ready";
  if (phase === "recording" || phase === "paused") return "capture_recovered_paused";
  if (phase === "uploading" || phase === "completing") return "capture_recovered_uploading";
  return "capture_recovered_processing";
}

function captureSeconds(capabilities: CaptureCapabilities, recordedChunks: number): number {
  return Math.floor((recordedChunks * capabilities.target_chunk_duration_ms) / 1_000);
}
