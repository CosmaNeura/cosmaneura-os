import {
  base64UrlDecode,
  base64UrlEncode,
  encodeEnvelope,
  NONCE_BYTES,
  PROTOCOL_VERSION,
} from "@cosmaneura-scribe/capture-protocol";

import type {
  CaptureBff,
  AudioEncryptionPublicKey,
  CaptureCapabilities,
  CaptureLeaseReceipt,
  CaptureTranscriptionStatus,
  ChunkReservationBatchReceipt,
  ConsentCreate,
  Transcript,
} from "../../bff/contracts";
import { BffResponseError } from "../../bff/http-client";
import { validateProfileRequest, validateProfileReceipt, validateProfileCapabilities,
  type CaptureProfileBff, type CaptureProfileReceipt, type CaptureProfileRequest } from "../../bff/profile-contracts";
import { AudioCaptureError } from "../../audio/errors";
import {canonicalCaptureTimestamp} from "../../bff/recovery-contracts";
import {normalizedLease, requireRenewal, validateRenewalIntent, validateStandardRenewalIntent} from "../../flow/renewal-contract";
import {sameLease, validateConfiguredRenewalRecord,
  type AutomaticCaptureRenewal} from "./automatic-renewal";
import { CaptureStopAcknowledgementPending } from "../capture/stop-confirmation";
import type {
  CapturedWavChunk,
  CaptureAudioChannel,
  CaptureSource,
  CaptureSourceErrorCode,
  CaptureSourceInterruptionCode,
} from "../capture";
import { QueueInvariantError } from "../../queue/errors";
import type { CaptureQueue } from "../../queue/capture-queue";
import type { CaptureQueueTransport, ChunkReservation } from "../../queue/types";
import { createWrappedSessionKey, type WrappedSessionKey } from "./session-key";
import {
  FLOW_RECORD_SCHEMA_VERSION,
  CHANNEL_FLOW_RECORD_SCHEMA_VERSION,
  CONTINUATION_FLOW_RECORD_SCHEMA_VERSION,
  PROFILE_FLOW_RECORD_SCHEMA_VERSION,
  AUTOMATIC_FLOW_RECORD_SCHEMA_VERSION,
  STANDARD_NATIVE_FLOW_RECORD_SCHEMA_VERSION,
  STANDARD_NATIVE_MAXIMUM_CHUNKS,
  type ActiveCapturePhase,
  type ActiveCaptureState,
  type CaptureFlowState,
  type CaptureFlowStore,
  type CapturePreparationState,
  type DirectCapturePreparationState,
  type ConfiguredCapturePreparationState,
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
  readonly bff: CaptureBff;
  readonly profiles?: CaptureProfileBff;
  /** Trusted native host only; no remote profile is selected or fabricated. */
  readonly standardContinuousCapture?: true;
  readonly flowStore: CaptureFlowStore;
  readonly queue: CaptureQueue;
  readonly queueTransport: CaptureQueueTransport;
  readonly source: CaptureSource;
  readonly crypto?: Crypto;
  /** Trusted host key custody; the default browser/iOS key path is unchanged. */
  readonly createSessionKey?: CaptureSessionKeyFactory;
  readonly now?: () => Date;
  readonly idFactory?: () => string;
  readonly scheduleTimeout?: (callback: () => void, delayMs: number) => unknown;
  readonly cancelTimeout?: (handle: unknown) => void;
}

export type CaptureSessionKeyFactory = (sessionId: string, published: AudioEncryptionPublicKey,
  crypto: Crypto) => Promise<WrappedSessionKey>;

type SnapshotListener = (snapshot: CaptureFlowSnapshot) => void;
interface ContinuousRun {
  readonly id: string;
  readonly first: number;
  readonly readyAt: number;
  maximumChunks: number;
  deadline: number;
  stopping: boolean;
}

export class CaptureFlowController {
  readonly #bff: CaptureBff;
  readonly #profiles: CaptureProfileBff | undefined;
  readonly #standardContinuousCapture: boolean;
  #standardNativeCapture = false;
  #captureProfile: CaptureProfileReceipt | null = null;
  readonly #flowStore: CaptureFlowStore;
  readonly #queue: CaptureQueue;
  readonly #queueTransport: CaptureQueueTransport;
  readonly #source: CaptureSource;
  readonly #channel: CaptureAudioChannel;
  readonly #crypto: Crypto;
  readonly #createSessionKey: CaptureSessionKeyFactory;
  readonly #now: () => Date;
  readonly #idFactory: () => string;
  readonly #scheduleTimeout: (callback: () => void, delayMs: number) => unknown;
  readonly #cancelTimeout: (handle: unknown) => void;
  readonly #listeners = new Set<SnapshotListener>();
  readonly #reservations = new Map<number, ChunkReservation>();

  #capabilities: CaptureCapabilities | null = null;
  #activeState: ActiveCaptureState | null = null;
  #lease: CaptureLeaseReceipt | null = null;
  #sessionId: string | null = null;
  #recordedPlaintextBytes = 0;
  #sourcePausedBySignal = false;
  #sourcePausePersistence: Promise<void> | null = null;
  #sourceStarted = false;
  #runFirstSequenceNumber = 0;
  #reviewAfterUpload = false;
  #recordingAbortController: AbortController | null = null;
  #chunkPersistence: Promise<void> = Promise.resolve();
  #authorityExpiryRequested = false;
  #authorityTimeout: unknown = null;
  #authorityExpiryTask: Promise<void> | null = null;
  #continuousRun: ContinuousRun | null = null;
  #renewalTimeout: unknown = null;
  #renewalTask: Promise<void> | null = null;
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
    this.#bff = options.bff;
    this.#profiles = options.profiles;
    this.#standardContinuousCapture = options.standardContinuousCapture === true;
    this.#flowStore = options.flowStore;
    this.#queue = options.queue;
    this.#queueTransport = options.queueTransport;
    this.#source = options.source;
    this.#channel = options.source.channel ?? "microphone";
    if (!["microphone", "mixed", "system_audio"].includes(this.#channel)) {
      throw new QueueInvariantError("capture_channel_invalid");
    }
    this.#crypto = options.crypto ?? globalThis.crypto;
    this.#createSessionKey = options.createSessionKey ?? ((_sessionId, published, crypto) => createWrappedSessionKey(published, crypto));
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

  public async restore(): Promise<boolean> {
    this.#requireState("idle");
    const active = await this.#flowStore.getActiveCaptureState();
    if (active === null) {
      const preparation = await this.#flowStore.getPreparationState();
      if (preparation === null) return false;
      this.#setSnapshot({ state: "preparing", statusCode: "synthetic_preview_restoring" });
      try {
        await this.#continuePreparation(preparation);
        return true;
      } catch (error) {
        this.#fail();
        throw error;
      }
    }
    this.#setSnapshot({ state: "preparing", statusCode: "synthetic_preview_restoring" });
    try {
      this.#restoreCapturePolicy(active.schemaVersion);
      if (!(active.reviewAfterUpload && active.phase === "processing")) this.#requireChannel(active.channel);
      this.#activeState = active;
      this.#reviewAfterUpload = active.reviewAfterUpload === true;
      this.#sessionId = active.sessionId;
      this.#lease = active.lease;
      if (active.reviewAfterUpload && active.phase === "processing") {
        // Upload was confirmed durably. Review reauthorizes through Core; no
        // expired recorder lease, audio key or legacy transcript is needed.
        this.#setSnapshot({ state: "processing", statusCode: "capture_processing",
          sessionId: active.sessionId, recordedChunks: active.recordedChunks });
        return true;
      }
      if (active.automaticRenewal?.state === "pending") await this.#reconcileAutomaticRenewal();
      const keyState = await this.#flowStore.getSessionKeyState(active.sessionId);
      if (keyState === null) throw new QueueInvariantError("session_key_missing");
      if (active.captureProfile) await this.#restoreCaptureProfile(active.captureProfile);
      await this.#bindStoredSessionKey(keyState);
      this.#setCapabilities(await this.#bff.getCapabilities(active.sessionId));
      if (this.#canCreateOrRecoverReservations()) {
        await this.#recoverReservationIntents();
      }
      let records = (await this.#queue.listMetadata()).filter(
        (record) => record.reservation.sessionId === active.sessionId,
      );
      if (records.length === 0 && this.#canCreateOrRecoverReservations()) {
        await this.#reserveInitialWindow();
        records = (await this.#queue.listMetadata()).filter(
          (record) => record.reservation.sessionId === active.sessionId,
        );
      }
      for (const record of records) {
        this.#requireChannel(record.reservation.channel);
        this.#reservations.set(record.reservation.sequenceNumber, record.reservation);
      }
      const recorded = records.filter((record) => record.state !== "reserved");
      const conservativeBytes = recorded.reduce(
        (total, record) => total + ("byteLength" in record ? record.byteLength : 0),
        0,
      );
      this.#recordedPlaintextBytes = Math.max(
        active.recordedPlaintextBytes,
        conservativeBytes,
      );
      const recordedChunks = Math.max(active.recordedChunks, recorded.length);
      this.#activeState = {
        ...this.#requireActiveState(),
        recordedChunks,
        recordedPlaintextBytes: this.#recordedPlaintextBytes,
      };
      await this.#flowStore.putActiveCaptureState(this.#activeState);
      const capturePhase =
        active.phase === "ready" || active.phase === "recording" || active.phase === "paused";
      const authorityExpired = capturePhase && !this.#hasActiveCaptureAuthority();
      if (active.phase === "recording" || authorityExpired) {
        await this.#saveActivePhase("paused");
      }
      const phase = this.#requireActiveState().phase;
      this.#setSnapshot({
        state: restoredSnapshotState(phase),
        statusCode: authorityExpired ? "capture_authority_expired" : restoredStatusCode(phase),
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

  public async prepare(encounter: SyntheticEncounter): Promise<void> {
    this.#requireState("idle");
    if (this.#channel !== "microphone") throw new QueueInvariantError("configured_capture_required");
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

  /** Core has already reserved consent, creator, language and the session. */
  public async prepareConfigured(sessionId: string, profile?: CaptureProfileRequest): Promise<void> {
    this.#requireState("idle");
    this.#setSnapshot({ state: "preparing", statusCode: "capture_preparing" });
    try {
      if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/iu.test(sessionId)) {
        throw new QueueInvariantError("invalid_admitted_session");
      }
      const preparation: ConfiguredCapturePreparationState = {
        mode: "configured_core",
        ...this.#channelState(),
        ...(profile ? {schemaVersion: PROFILE_FLOW_RECORD_SCHEMA_VERSION,
          profileSelection: {request: this.#profileRequest(profile), idempotencyKey: this.#operationKey("profile"), receipt: null}} : {}),
        sessionId,
        startedAt: this.#now().toISOString(),
        completeIdempotencyKey: this.#operationKey("complete"),
        leaseIdempotencyKey: null,
        leaseRequest: null,
      };
      // Persist before key binding, lease issuance or any audio access.
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

  #profileRequest(value: CaptureProfileRequest): CaptureProfileRequest {
    const request = validateProfileRequest(value);
    if (!this.#profiles || request.channels.length !== 1 || request.channels[0] !== this.#channel) {
      throw new QueueInvariantError("capture_profile_unavailable");
    }
    return request;
  }

  async #restoreCaptureProfile(value: CaptureProfileReceipt): Promise<void> {
    const profile = await validateProfileReceipt(value, this.#requireSessionId(), this.#now(), undefined, this.#crypto);
    this.#profileRequest(profile.request);
    await this.#profiles!.acknowledgeCaptureProfile(profile);
    this.#captureProfile = profile;
  }

  async #continuePreparation(initial: CapturePreparationState): Promise<void> {
    this.#restoreCapturePolicy(initial.schemaVersion);
    this.#requireChannel(initial.mode === "configured_core" ? initial.channel : undefined);
    let preparation = initial.mode === "configured_core" ? initial : await this.#prepareDirectAdmission(initial);
    const sessionId = preparation.sessionId;
    if (sessionId === null) throw new QueueInvariantError("preparation_state_incomplete");
    this.#reviewAfterUpload = preparation.mode === "configured_core";
    this.#sessionId = sessionId;
    this.#setSnapshot({ sessionId });

    if (preparation.mode === "configured_core" && preparation.profileSelection) {
      const selection = preparation.profileSelection;
      this.#profileRequest(selection.request);
      if (selection.receipt === null) {
        const receipt = await this.#profiles!.selectCaptureProfile(sessionId, selection.request,
          {idempotencyKey: selection.idempotencyKey});
        const confirmed = await validateProfileReceipt(receipt, sessionId, this.#now(), selection.request, this.#crypto);
        preparation = {...preparation, profileSelection: {...selection, receipt: confirmed}};
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
    this.#activeState = {
      schemaVersion: preparation.schemaVersion,
      ...(preparation.mode === "configured_core" && preparation.channel ? {channel: preparation.channel} : {}),
      ...(this.#captureProfile ? {schemaVersion: PROFILE_FLOW_RECORD_SCHEMA_VERSION, captureProfile: this.#captureProfile} : {}),
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
      ...(this.#reviewAfterUpload ? { reviewAfterUpload: true as const } : {}),
    };
    await this.#flowStore.putActiveCaptureState(this.#activeState);
    if (Date.parse(this.#lease.expires_at) <= this.#now().getTime()) {
      // Preserve a preparation whose exact lease reply expired while offline.
      // Explicit continuation can renew this lease without replacing its key.
      await this.#pauseForExpiredAuthority();
      return;
    }
    await this.#recoverReservationIntents();
    if (this.#reservations.size === 0) await this.#reserveInitialWindow();
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
    this.#requireState("ready");
    if (!this.#hasActiveCaptureAuthority()) {
      await this.#pauseForExpiredAuthority();
      throw new QueueInvariantError("capture_authority_expired");
    }
    this.#clearAuthorityTimeout();
    const capabilities = this.#captureCapabilitiesForReservedWindow();
    const continuous = (!!this.#captureProfile || this.#standardNativeCapture) && !!this.#bff.getCaptureLeaseState && !!this.#source.extend
      && await this.#source.supportsContinuousCapture?.() === true;
    this.#requireState("ready");
    this.#runFirstSequenceNumber = this.#requireActiveState().continuation?.firstSequenceNumber ?? 0;
    if (this.#runFirstSequenceNumber !== this.#snapshot.recordedChunks) {
      throw new QueueInvariantError("capture_interval_position_conflict");
    }
    this.#sourcePausedBySignal = false;
    this.#sourcePausePersistence = null;
    this.#sourceStarted = false;
    this.#authorityExpiryRequested = false;
    this.#recordingAbortController = new AbortController();
    this.#continuousRun = continuous ? {id:this.#idFactory(), first:this.#runFirstSequenceNumber,
      readyAt:this.#now().getTime(), maximumChunks:capabilities.max_chunks,
      deadline:this.#captureAuthorityDeadline()!, stopping:false} : null;
    await this.#saveActivePhase("recording");
    if (this.#authorityExpiryRequested || !this.#hasActiveCaptureAuthority()) {
      await this.#authorityExpiryTask;
      this.#authorityExpiryRequested = true;
      this.#recordingAbortController = null;
      if (this.#snapshot.state !== "paused") await this.#pauseForExpiredAuthority();
      throw new QueueInvariantError("capture_authority_expired");
    }
    this.#setSnapshot({ state: "recording", statusCode: "synthetic_preview_recording" });
    this.#armAuthorityDeadline();
    try {
      await this.#source.start({
        capabilities,
        onChunk: async (chunk) => this.#acceptChunk(chunk),
        onInterruption: (code) => this.#pauseAfterSourceSignal(code),
        onError: (code) => this.#pauseAfterSourceSignal(code),
        signal: this.#recordingAbortController.signal,
      });
      this.#sourceStarted = true;
      if (this.#recordingAbortController.signal.aborted) {
        await this.#source.stop();
        this.#sourceStarted = false;
      }
      if (this.#continuousRun) this.#scheduleRenewal(this.#continuousRun);
    } catch (error) {
      this.#clearAuthorityTimeout();
      this.#sourceStarted = false;
      if (!this.#sourcePausedBySignal) {
        if (this.#reviewAfterUpload) {
          this.#recordingAbortController?.abort();
          await this.#saveActivePhase("paused");
          this.#setSnapshot({ state: "paused", statusCode: "capture_start_unconfirmed" });
        } else this.#fail();
      }
      throw error;
    }
  }

  /** Explicit physical pause. It retains the key/chunks and never uploads. */
  public async pauseRecording(): Promise<void> {
    if (!this.#reviewAfterUpload || !["ready", "recording", "paused"].includes(this.#snapshot.state)) {
      throw new QueueInvariantError("capture_state_conflict");
    }
    this.#clearAuthorityTimeout();
    this.#suppressRenewal();
    try {
      await this.#authorityExpiryTask;
      await this.#stopSourceWithRenewal(); // Native wrapper also confirms server retirement.
      await this.#renewalTask?.catch(() => undefined);
      await this.#chunkPersistence;
      await this.#sourcePausePersistence;
      this.#sourceStarted = false;
      this.#recordingAbortController = null;
      await this.#saveActivePhase("paused");
      await this.#reconcileAutomaticRenewal();
      this.#setSnapshot({ state: "paused", statusCode: "capture_paused" });
    } catch (error) {
      await this.#saveActivePhase("paused");
      this.#setSnapshot({ state: "paused", statusCode: isUnconfirmedCaptureStop(error)
        ? error.code : "capture_pause_unconfirmed" });
      throw error;
    }
  }

  /** Called only after a deliberate Resume and confirmed old-owner stop.
   * A lost renewal response replays its durable key and previous generation. */
  public async prepareContinuation(): Promise<void> {
    if (!this.#reviewAfterUpload || this.#snapshot.state !== "paused") {
      throw new QueueInvariantError("capture_state_conflict");
    }
    await this.pauseRecording();
    try {
      let active = this.#requireActiveState();
      // An interrupted preparation reuses the same renewal/reservation intent.
      if (!active.continuation || active.continuation.prepared
        || active.lease.generation > active.continuation.previousLease.generation
          && Date.parse(active.lease.expires_at) <= this.#now().getTime()) {
        this.#setCapabilities(await this.#bff.getCapabilities(active.sessionId));
        const capabilities = this.#requireCapabilities();
        const first = active.recordedChunks;
        const unused = [...this.#reservations.keys()].filter(sequence => sequence >= first).length;
        const count = Math.min(capabilities.max_reservations_per_batch, capabilities.max_chunks - first,
          unused + Math.floor(capabilities.remaining_aggregate_plaintext_bytes / capabilities.max_envelope_bytes));
        if (!Number.isSafeInteger(count) || count < 1) throw new QueueInvariantError("capture_budget_exhausted");
        active = { ...active, automaticRenewal: undefined,
          schemaVersion: active.schemaVersion === STANDARD_NATIVE_FLOW_RECORD_SCHEMA_VERSION ? STANDARD_NATIVE_FLOW_RECORD_SCHEMA_VERSION
            : active.schemaVersion === AUTOMATIC_FLOW_RECORD_SCHEMA_VERSION ? AUTOMATIC_FLOW_RECORD_SCHEMA_VERSION
            : active.captureProfile ? PROFILE_FLOW_RECORD_SCHEMA_VERSION : CONTINUATION_FLOW_RECORD_SCHEMA_VERSION,
          continuation: { prepared: false, firstSequenceNumber: first, reservationCount: count, previousLease: active.lease,
            renewIdempotencyKey: this.#operationKey("renew") } };
        await this.#flowStore.putActiveCaptureState(active);
        this.#activeState = active;
      }
      const continuation = active.continuation!;
      if (active.lease.generation === continuation.previousLease.generation) {
        const lease = await this.#bff.renewLease(active.sessionId, continuation.previousLease.lease_id,
          { protocol_version: PROTOCOL_VERSION, expected_generation: continuation.previousLease.generation },
          { idempotencyKey: continuation.renewIdempotencyKey });
        if (lease.session_id !== active.sessionId || lease.lease_id !== active.lease.lease_id
          || lease.generation !== active.lease.generation + 1) throw new QueueInvariantError("capture_lease_conflict");
        active = { ...active, lease, captureAuthorizedUntil: null };
        await this.#flowStore.putActiveCaptureState(active);
        this.#activeState = active; this.#lease = lease;
      }
      await this.#recoverReservationIntents();
      if (this.#requireActiveState().captureAuthorizedUntil === null) {
        await this.#reserveWindow(continuation.firstSequenceNumber, continuation.reservationCount);
      }
      if (!this.#hasActiveCaptureAuthority()) throw new QueueInvariantError("capture_authority_expired");
      this.#authorityExpiryRequested = false;
      const ready = { ...this.#requireActiveState(), phase: "ready" as const,
        continuation: { ...continuation, prepared: true } };
      await this.#flowStore.putActiveCaptureState(ready); this.#activeState = ready;
      this.#setSnapshot({ state: "ready", statusCode: "capture_continuation_ready",
        remainingAuthoritySeconds: this.#remainingCaptureSeconds(active.recordedChunks) });
      this.#armAuthorityDeadline();
    } catch (error) {
      this.#setSnapshot({ state: "paused", statusCode: "capture_resume_pending" });
      throw error;
    }
  }

  public async resumeRecording(): Promise<void> {
    await this.prepareContinuation();
    await this.startRecording();
  }

  public async stopRecording(): Promise<void> {
    if (this.#snapshot.state !== "recording" && this.#snapshot.state !== "paused") {
      throw new QueueInvariantError("capture_state_conflict");
    }
    try {
      this.#clearAuthorityTimeout();
      this.#suppressRenewal();
      await this.#authorityExpiryTask;
      try {
        await this.#stopSourceWithRenewal();
      } catch (error) {
        if (isUnconfirmedCaptureStop(error)) {
          // An interruption proves neither physical closure nor server retirement.
          // Keep the same source, encrypted queue and stop action available.
          await this.#sourcePausePersistence;
          await this.#saveActivePhase("paused");
          this.#setSnapshot({ state: "paused", statusCode: error.code });
          throw error;
        }
        if (!this.#sourcePausedBySignal) throw error;
      }
      this.#sourceStarted = false;
      await this.#renewalTask?.catch(() => undefined);
      await this.#chunkPersistence;
      if (this.#activeState?.automaticRenewal?.state === "pending") {
        await this.#saveActivePhase("paused");
        await this.#reconcileAutomaticRenewal();
      }
      this.#recordingAbortController = null;
      await this.#sourcePausePersistence;
      if (this.#snapshot.recordedChunks < 1) {
        throw new QueueInvariantError("capture_has_no_chunks");
      }
      if (this.#activeState?.continuation?.prepared === false) {
        // Resolve a committed-but-lost renewal before completing with its current generation.
        await this.prepareContinuation();
        this.#clearAuthorityTimeout();
      }
      await this.#saveActivePhase("uploading");
      this.#setSnapshot({ state: "uploading", statusCode: "synthetic_preview_uploading" });
      await this.#drainAndComplete();
    } catch (error) {
      if (!isUnconfirmedCaptureStop(error) || this.#snapshot.state !== "paused") this.#failOrRetainUpload(error);
      throw error;
    }
  }

  /** Host teardown stops acquisition and retains recoverable work without upload. */
  public async deactivate(): Promise<void> {
    this.#clearAuthorityTimeout();
    this.#suppressRenewal();
    this.#recordingAbortController?.abort();
    await this.#stopSourceWithRenewal();
    await this.#renewalTask?.catch(() => undefined);
    await this.#chunkPersistence;
    await this.#sourcePausePersistence;
    this.#sourceStarted = false;
    if (this.#activeState?.phase === "recording") {
      await this.#saveActivePhase("paused");
      this.#setSnapshot({ state: "paused", statusCode: "capture_recovered_paused" });
    }
  }

  public async resumePendingWork(): Promise<void> {
    const active = this.#requireActiveState();
    try {
      if (active.phase === "uploading") {
        this.#setSnapshot({ state: "uploading", statusCode: "synthetic_preview_uploading" });
        await this.#drainAndComplete();
        return;
      }
      if (active.phase === "completing") {
        this.#setSnapshot({ state: "uploading", statusCode: "synthetic_preview_uploading" });
        await this.#completeAndRefresh();
        return;
      }
      if (active.phase === "processing") {
        await this.refreshTranscriptionStatus();
        return;
      }
      throw new QueueInvariantError("capture_state_conflict");
    } catch (error) {
      this.#failOrRetainUpload(error);
      throw error;
    }
  }

  public async refreshTranscriptionStatus(): Promise<void> {
    // The mounted creator-review panel owns configured processing/readiness.
    // Do not project accepted English into a fabricated legacy transcript.
    if (this.#reviewAfterUpload) return;
    const sessionId = this.#requireSessionId();
    const status = await this.#bff.getTranscriptionStatus(sessionId);
    this.#setSnapshot({ transcriptionStatus: status });
    if (status.status === "completed" && status.transcript_available) {
      const transcript = await this.#bff.getTranscript(sessionId);
      this.#setSnapshot({
        state: "complete",
        statusCode: "synthetic_preview_complete",
        transcript,
      });
      await this.#flowStore.clearCompletedCapture(sessionId);
      this.#activeState = null;
    }
  }

  /** The confirmed upload no longer needs local audio custody. */
  public async releaseUploadedCapture(): Promise<void> {
    if (this.#reviewAfterUpload && this.#activeState === null && this.#snapshot.state === "processing") return;
    if (!this.#reviewAfterUpload || this.#activeState?.phase !== "processing") {
      throw new QueueInvariantError("capture_state_conflict");
    }
    await this.#flowStore.clearCompletedCapture(this.#requireSessionId());
    this.#activeState = null;
  }

  async #drainAndComplete(): Promise<void> {
    const drained = await this.#queue.drainOnce(this.#queueTransport);
    const records = await this.#queue.listMetadata();
    if (drained.items.some(item => item.outcome === "terminal") || records.some(record =>
      record.reservation.sessionId === this.#requireSessionId()
      && (record.retry.upload.terminalCode !== null || record.retry.registration.terminalCode !== null))) {
      throw new QueueInvariantError("capture_queue_blocked");
    }
    if (drained.items.some((item) => item.outcome !== "registered")) {
      throw new QueueInvariantError("capture_queue_not_drained");
    }
    for (const record of records) {
      if (
        record.reservation.sessionId === this.#requireSessionId() &&
        record.state === "registered"
      ) {
        await this.#queue.purge(record.reservation.objectId);
      }
    }
    await this.#saveActivePhase("completing");
    await this.#completeAndRefresh();
  }

  async #completeAndRefresh(): Promise<void> {
    const sessionId = this.#requireSessionId();
    const lease = this.#requireLease();
    const active = this.#requireActiveState();
    await this.#bff.completeCapture(sessionId, {
      protocol_version: PROTOCOL_VERSION,
      capture_lease_id: lease.lease_id,
      capture_lease_generation: lease.generation,
      channels: [{
        channel: this.#channel,
        final_sequence_number: active.recordedChunks - 1,
      }],
    }, { idempotencyKey: active.completeIdempotencyKey });
    await this.#saveActivePhase("processing");
    this.#setSnapshot({ state: "processing", statusCode: "synthetic_preview_processing" });
    await this.refreshTranscriptionStatus();
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
    const wrapped = await this.#createSessionKey(sessionId, published, this.#crypto);
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
    await this.#reserveWindow(0, count);
  }

  async #reserveWindow(firstSequence: number, count: number): Promise<void> {
    const lease = this.#requireLease(), sessionId = this.#requireSessionId();
    const intent: ReservationIntent = {
      schemaVersion: FLOW_RECORD_SCHEMA_VERSION,
      intentId: `${sessionId}:${this.#channel}:${String(firstSequence)}:${String(count)}:${String(lease.generation)}`,
      sessionId,
      idempotencyKey: this.#operationKey("reserve"),
      createdAt: this.#now().toISOString(),
      request: {
        protocol_version: PROTOCOL_VERSION,
        capture_lease_id: lease.lease_id,
        capture_lease_generation: lease.generation,
        channel: this.#channel,
        first_sequence_number: firstSequence,
        count,
      },
    };
    await this.#flowStore.putReservationIntent(intent);
    await this.#replayReservationIntent(intent);
  }

  async #recoverReservationIntents(): Promise<void> {
    for (const intent of await this.#flowStore.listReservationIntents()) {
      if (intent.sessionId !== this.#requireSessionId()) continue;
      // A prior expired interval's request cannot create new authority. Retain
      // its exact intent; the fresh batch reconciles canonical object identities.
      if (intent.request.capture_lease_id === this.#requireLease().lease_id
        && intent.request.capture_lease_generation < this.#requireLease().generation) continue;
      if (intent.request.capture_lease_id !== this.#requireLease().lease_id
        || intent.request.capture_lease_generation !== this.#requireLease().generation) {
        throw new QueueInvariantError("capture_reservation_generation_conflict");
      }
      await this.#replayReservationIntent(intent);
    }
  }

  async #replayReservationIntent(intent: ReservationIntent): Promise<void> {
    this.#requireChannel(intent.request.channel);
    const batch = await this.#bff.reserveChunks(
      intent.sessionId,
      intent.request,
      { idempotencyKey: intent.idempotencyKey },
    );
    await this.#persistReservations(batch, intent);
    await this.#flowStore.deleteReservationIntent(intent.intentId);
  }

  async #persistReservations(
    batch: ChunkReservationBatchReceipt,
    intent: ReservationIntent,
  ): Promise<void> {
    if (
      batch.protocol_version !== PROTOCOL_VERSION ||
      batch.session_id !== this.#requireSessionId() ||
      batch.capture_authorized_until !== this.#requireLease().expires_at ||
      batch.reservations.length !== intent.request.count ||
      batch.reservations.some((row, index) => row.sequence_number !== intent.request.first_sequence_number + index) ||
      batch.reservations.some(row => row.channel !== this.#channel || row.session_id !== batch.session_id) ||
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
      // Automatic renewal stores canonical timestamps. Explicit continuation
      // can return the same server object with a different timestamp spelling.
      // Keep its original queue identity/keys after proving semantic identity.
      const prior = this.#reservations.get(reservation.sequenceNumber);
      if (prior && (prior.objectId !== reservation.objectId
        || prior.additionalAuthenticatedData !== reservation.additionalAuthenticatedData
        || canonicalCaptureTimestamp(prior.createdAt) !== canonicalCaptureTimestamp(reservation.createdAt))) {
        throw new QueueInvariantError("reservation_identity_conflict");
      }
      await this.#queue.reserve(prior ?? reservation, intent.idempotencyKey);
      this.#reservations.set(reservation.sequenceNumber, prior ?? reservation);
    }
    this.#setSnapshot({ queuedChunks: this.#reservations.size });
  }

  async #acceptChunk(chunk: CapturedWavChunk): Promise<void> {
    const task = this.#chunkPersistence.then(async () => {
      try {
        if (this.#authorityExpiryRequested) {
          throw new QueueInvariantError("capture_authority_expired");
        }
        await this.#acceptChunkAndPersist(chunk);
      } finally {
        chunk.wavBytes.fill(0);
      }
    });
    this.#chunkPersistence = task.catch(() => undefined);
    void task.then(() => { if(this.#continuousRun) this.#scheduleRenewal(this.#continuousRun); }).catch(() => undefined);
    return task;
  }

  #suppressRenewal(): void {
    if(this.#continuousRun)this.#continuousRun.stopping=true;
    if(this.#renewalTimeout!==null)this.#cancelTimeout(this.#renewalTimeout);
    this.#renewalTimeout=null;
  }

  async #stopSourceWithRenewal():Promise<void> {
    try{await this.#source.stop();}
    catch(error){
      // This specific error proves physical closure. A native renewal can
      // briefly own the server-acknowledgment gate; settle it, then retry the
      // original owner's stop once without requiring another provider action.
      if(!(error instanceof CaptureStopAcknowledgementPending) || !this.#renewalTask)throw error;
      await this.#renewalTask.catch(()=>undefined);
      await this.#source.stop();
    }
  }

  #requireContinuous(run:ContinuousRun): void {
    requireRenewal(this.#continuousRun===run && !run.stopping && this.#sourceStarted
      && this.#snapshot.state==="recording" && !this.#authorityExpiryRequested
      && this.#now().getTime()<run.deadline);
  }

  #withChunkPersistence<T>(operation:()=>Promise<T>):Promise<T> {
    const task=this.#chunkPersistence.then(operation);
    this.#chunkPersistence=task.then(()=>undefined,()=>undefined);
    return task;
  }

  #scheduleRenewal(run:ContinuousRun):void {
    if(this.#continuousRun!==run || run.stopping || !this.#sourceStarted || this.#renewalTask
      || run.first+run.maximumChunks>=360)return;
    if(this.#renewalTimeout!==null)this.#cancelTimeout(this.#renewalTimeout);
    const duration=this.#requireCapabilities().target_chunk_duration_ms;
    const lead=Math.min(6,Math.max(1,Math.floor(run.maximumChunks/4)));
    const remaining=run.first+run.maximumChunks-this.#snapshot.recordedChunks, now=this.#now().getTime();
    if(remaining<=lead || run.deadline-now<=lead*duration){
      this.#renewalTimeout=null;
      const task=this.#renewContinuous(run);this.#renewalTask=task;
      void task.catch(async()=>{
        if(this.#continuousRun!==run || run.stopping)return;
        this.#pauseAfterSourceSignal("capture_source_failed");
        this.#recordingAbortController?.abort();
        try{
          await this.#source.stop();await this.#sourcePausePersistence;await this.#chunkPersistence;
          this.#sourceStarted=false;
        }catch(error){this.#setSnapshot({state:"paused",statusCode:isUnconfirmedCaptureStop(error)?error.code:"capture_pause_unconfirmed"});}
      }).finally(()=>{
        if(this.#renewalTask===task)this.#renewalTask=null;
        this.#scheduleRenewal(run);
      });
      return;
    }
    const due=run.readyAt+(run.maximumChunks-lead)*duration;
    const delay=Math.max(1,Math.min(run.deadline-now-lead*duration,Math.max(Math.min(1000,duration),due-now)));
    this.#renewalTimeout=this.#scheduleTimeout(()=>{this.#renewalTimeout=null;this.#scheduleRenewal(run);},delay);
  }

  async #saveAutomatic(value:AutomaticCaptureRenewal):Promise<void> {
    const active=this.#requireActiveState(),record=value.record;
    const next:ActiveCaptureState={...active,schemaVersion:active.captureProfile?AUTOMATIC_FLOW_RECORD_SCHEMA_VERSION:STANDARD_NATIVE_FLOW_RECORD_SCHEMA_VERSION,automaticRenewal:value,
      lease:record.lease??record.intent.priorLease,
      captureAuthorizedUntil:value.state==="reconciled"?null:value.state==="extended"?record.lease!.expires_at:record.intent.priorCaptureAuthorizedUntil,
      ...(value.state==="reconciled"?{phase:"paused" as const}:{})};
    await this.#flowStore.putActiveCaptureState(next);
    this.#activeState=next;this.#lease=next.lease;
  }

  async #renewContinuous(run:ContinuousRun):Promise<void> {
    let record=await this.#withChunkPersistence(async()=>{
      this.#requireContinuous(run);
      const active=this.#requireActiveState(),caps=this.#requireCapabilities();
      const first=active.recordedChunks+1;
      const count=Math.min(90,caps.max_reservations_per_batch,360-first,
        Math.floor((active.aggregatePlaintextBudgetBytes-this.#recordedPlaintextBytes)/caps.max_envelope_bytes)-1);
      requireRenewal(count>0 && first+count>run.first+run.maximumChunks);
      const fields={sessionId:active.sessionId,segmentId:run.id,segmentOrdinal:run.first,
        priorLease:active.lease,priorCaptureAuthorizedUntil:active.captureAuthorizedUntil!,firstSequenceNumber:first,count,
        leaseIdempotencyKey:this.#operationKey("renew-lease"),reservationIdempotencyKey:this.#operationKey("renew-reserve"),
        createdAt:this.#now().toISOString()};
      const intent=this.#captureProfile
        ? validateRenewalIntent({schemaVersion:1,profileReceiptId:this.#captureProfile.receipt_id,...fields})
        : validateStandardRenewalIntent({schemaVersion:2,...fields});
      const next=validateConfiguredRenewalRecord({intent,lease:null,reservations:null},this.#now(),this.#channel);
      await this.#saveAutomatic({record:next,state:"pending"});return next;
    });
    const intent=record.intent;
    const exactRetry=async<T>(operation:()=>Promise<T>):Promise<T>=>{
      try{return await operation();}catch(error){
        this.#requireContinuous(run);
        if(error instanceof QueueInvariantError || error instanceof BffResponseError && error.status<500)throw error;
        return operation();
      }
    };
    this.#requireContinuous(run);
    const lease=await exactRetry(()=>this.#bff.renewLease(intent.sessionId,intent.priorLease.lease_id,
      {protocol_version:PROTOCOL_VERSION,expected_generation:intent.priorLease.generation},{idempotencyKey:intent.leaseIdempotencyKey}));
    record=validateConfiguredRenewalRecord({...record,lease},this.#now(),this.#channel);
    // Keep a returned lease even when Stop raced the request. Completion waits
    // for this journal write; no later network phase can cross the stop fence.
    await this.#withChunkPersistence(()=>this.#saveAutomatic({record,state:"pending"}));
    this.#requireContinuous(run);
    const reservations=await exactRetry(()=>this.#bff.reserveChunks(intent.sessionId,
      {protocol_version:PROTOCOL_VERSION,capture_lease_id:record.lease!.lease_id,capture_lease_generation:record.lease!.generation,
        channel:this.#channel,first_sequence_number:intent.firstSequenceNumber,count:intent.count},
      {idempotencyKey:intent.reservationIdempotencyKey}));
    record=validateConfiguredRenewalRecord({...record,reservations},this.#now(),this.#channel);
    await this.#withChunkPersistence(async()=>{
      await this.#saveAutomatic({record,state:"pending"});
      for(const remote of record.reservations!.reservations){
        const reservation:ChunkReservation={protocolVersion:remote.protocol_version,objectId:remote.object_id,
          sessionId:remote.session_id,channel:remote.channel,sequenceNumber:remote.sequence_number,
          additionalAuthenticatedData:remote.additional_authenticated_data,createdAt:remote.created_at};
        const prior=this.#reservations.get(reservation.sequenceNumber);
        requireRenewal(!prior || prior.objectId===reservation.objectId && prior.additionalAuthenticatedData===reservation.additionalAuthenticatedData
          && canonicalCaptureTimestamp(prior.createdAt)===canonicalCaptureTimestamp(reservation.createdAt));
        await this.#queue.reserve(prior??reservation,intent.reservationIdempotencyKey);
        this.#reservations.set(reservation.sequenceNumber,prior??reservation);
      }
      this.#setSnapshot({queuedChunks:this.#reservations.size});
    });
    this.#requireContinuous(run);
    const extension={leaseReceiptId:record.lease!.receipt_id,leaseGeneration:record.lease!.generation,
      captureAuthorizedUntil:record.lease!.expires_at,reservationBatchId:record.reservations!.batch_id,
      firstSequenceNumber:intent.firstSequenceNumber,reservationCount:intent.count,
      maximumChunks:intent.firstSequenceNumber+intent.count-run.first};
    await this.#source.extend!(extension);
    await this.#withChunkPersistence(async()=>{
      this.#requireContinuous(run);
      await this.#saveAutomatic({record,state:"extended"});
      run.maximumChunks=extension.maximumChunks;run.deadline=Date.parse(extension.captureAuthorizedUntil);
      this.#armAuthorityDeadline();
      this.#setSnapshot({remainingAuthoritySeconds:this.#remainingCaptureSeconds(this.#snapshot.recordedChunks)});
    });
  }

  async #reconcileAutomaticRenewal():Promise<void> {
    const pending=this.#activeState?.automaticRenewal;
    if(!pending || pending.state!=="pending")return;
    requireRenewal(!this.#sourceStarted && this.#bff.getCaptureLeaseState);
    const intent=pending.record.intent;
    const observed=await this.#bff.getCaptureLeaseState(intent.sessionId);
    requireRenewal(observed.session_id===intent.sessionId && observed.current_lease && !observed.lease_closed
      && ["created","capturing"].includes(observed.session_status));
    const lease=normalizedLease(observed.current_lease,intent.sessionId);
    requireRenewal(lease.lease_id===intent.priorLease.lease_id);
    let record=pending.record;
    if(lease.generation===intent.priorLease.generation){
      requireRenewal(record.lease===null && sameLease(lease,intent.priorLease));
    }else{
      requireRenewal(lease.generation===intent.priorLease.generation+1);
      if(record.lease===null){
        // Observing the advanced generation ensures this exact old key can
        // recover its receipt but cannot issue a further renewal.
        const receipt=await this.#bff.renewLease(intent.sessionId,intent.priorLease.lease_id,
          {protocol_version:PROTOCOL_VERSION,expected_generation:intent.priorLease.generation},{idempotencyKey:intent.leaseIdempotencyKey});
        record=validateConfiguredRenewalRecord({...record,lease:receipt},this.#now(),this.#channel);
      }
      requireRenewal(sameLease(record.lease!,lease));
    }
    await this.#withChunkPersistence(()=>this.#saveAutomatic({record,state:"reconciled"}));
  }

  async #acceptChunkAndPersist(chunk: CapturedWavChunk): Promise<void> {
    if (this.#snapshot.state !== "recording") {
      throw new QueueInvariantError("capture_state_conflict");
    }
    if (!this.#hasActiveCaptureAuthority()) {
      await this.#pauseForExpiredAuthority();
      throw new QueueInvariantError("capture_authority_expired");
    }
    const sequence = this.#runFirstSequenceNumber + chunk.sequenceNumber;
    if (sequence !== this.#snapshot.recordedChunks) throw new QueueInvariantError("capture_chunk_position_conflict");
    const reservation = this.#reservations.get(sequence);
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
      capabilities = {...validated, max_chunks: this.#captureProfile.maximum_chunks_per_channel};
    } else if (this.#standardNativeCapture) {
      const validated=validateProfileCapabilities(capabilities,null);
      capabilities={...validated,max_chunks:Math.min(validated.max_chunks,STANDARD_NATIVE_MAXIMUM_CHUNKS),
        remaining_aggregate_plaintext_bytes:Math.min(validated.remaining_aggregate_plaintext_bytes,
          STANDARD_NATIVE_MAXIMUM_CHUNKS*validated.max_envelope_bytes)};
    }
    this.#queue.configureUploadConcurrency(capabilities.upload_concurrency);
    this.#capabilities = capabilities;
  }

  #requireChannel(channel: CaptureAudioChannel | undefined): void {
    if ((channel ?? "microphone") !== this.#channel) throw new QueueInvariantError("capture_channel_conflict");
  }

  #restoreCapturePolicy(schemaVersion: number): void {
    this.#standardNativeCapture = schemaVersion === STANDARD_NATIVE_FLOW_RECORD_SCHEMA_VERSION;
    if (this.#standardNativeCapture && !this.#standardContinuousCapture) {
      throw new QueueInvariantError("capture_policy_unavailable");
    }
  }

  #channelState(): Pick<ConfiguredCapturePreparationState, "schemaVersion" | "channel"> {
    if(this.#standardContinuousCapture) return {schemaVersion:STANDARD_NATIVE_FLOW_RECORD_SCHEMA_VERSION,
      ...(this.#channel==="microphone"?{}:{channel:this.#channel})};
    return this.#channel === "microphone" ? { schemaVersion: FLOW_RECORD_SCHEMA_VERSION }
      : { schemaVersion: CHANNEL_FLOW_RECORD_SCHEMA_VERSION, channel: this.#channel };
  }

  #canCreateOrRecoverReservations(): boolean {
    const active = this.#requireActiveState();
    if (active.continuation && active.lease.generation === active.continuation.previousLease.generation) return false;
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
      capabilities.max_chunks - this.#snapshot.recordedChunks,
      this.#reservations.size - this.#snapshot.recordedChunks,
      this.#requireActiveState().continuation?.reservationCount ?? capabilities.max_chunks,
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
    await this.#saveActivePhase("paused");
    this.#setSnapshot({
      state: "paused",
      statusCode: "capture_authority_expired",
      remainingAuthoritySeconds: 0,
    });
  }

  #armAuthorityDeadline(): void {
    this.#clearAuthorityTimeout();
    const deadline = this.#captureAuthorityDeadline();
    if (deadline === null) return;
    const delayMs = Math.max(0, deadline - this.#now().getTime());
    this.#authorityTimeout = this.#scheduleTimeout(() => {
      this.#authorityTimeout = null;
      this.#authorityExpiryRequested = true;
      const task = this.#expireCaptureAuthority();
      this.#authorityExpiryTask = task;
      void task
        .catch(error => {
          if (isUnconfirmedCaptureStop(error) && this.#snapshot.state === "paused") {
            this.#setSnapshot({ statusCode: error.code });
          } else this.#fail();
        })
        .finally(() => {
          if (this.#authorityExpiryTask === task) this.#authorityExpiryTask = null;
        });
    }, delayMs);
  }

  #clearAuthorityTimeout(): void {
    if (this.#authorityTimeout === null) return;
    this.#cancelTimeout(this.#authorityTimeout);
    this.#authorityTimeout = null;
  }

  async #expireCaptureAuthority(): Promise<void> {
    if (this.#snapshot.state !== "ready" && this.#snapshot.state !== "recording") return;
    const wasRecording = this.#snapshot.state === "recording";
    this.#suppressRenewal();
    if (wasRecording) {
      this.#sourcePausedBySignal = true;
      this.#recordingAbortController?.abort();
      await this.#chunkPersistence;
    }
    await this.#pauseForExpiredAuthority();
    if (wasRecording && this.#sourceStarted) {
      await this.#source.stop();
      this.#sourceStarted = false;
    }
  }

  #pauseAfterSourceSignal(
    code: CaptureSourceErrorCode | CaptureSourceInterruptionCode,
  ): void {
    if (this.#snapshot.state !== "recording" || this.#authorityExpiryRequested) return;
    this.#clearAuthorityTimeout();
    this.#suppressRenewal();
    this.#sourcePausedBySignal = true;
    this.#setSnapshot({ state: "paused", statusCode: code });
    const persistence = this.#withChunkPersistence(()=>this.#saveActivePhase("paused"));
    this.#sourcePausePersistence = persistence;
    void persistence.catch(() => this.#fail());
  }

  #operationKey(operation: string): string {
    return `${operation}:${this.#idFactory()}`;
  }

  #requireState(expected: CaptureFlowState): void {
    if (this.#snapshot.state !== expected) throw new QueueInvariantError("capture_state_conflict");
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

  #fail(): void {
    this.#clearAuthorityTimeout();
    this.#suppressRenewal();
    this.#authorityExpiryRequested = true;
    this.#recordingAbortController?.abort();
    this.#setSnapshot({ state: "error", statusCode: "synthetic_preview_failed" });
  }

  #failOrRetainUpload(error: unknown): void {
    // These durable phases are entered only after source stop has confirmed.
    // Retry the retained queue/completion key; never acquire new recording authority.
    const denied = error instanceof BffResponseError && error.status >= 400 && error.status < 500
      && error.status !== 408 && error.status !== 429;
    const invariant = error instanceof QueueInvariantError && error.code !== "capture_queue_not_drained";
    if (!denied && !invariant && this.#reviewAfterUpload && (this.#activeState?.phase === "uploading"
      || this.#activeState?.phase === "completing")) {
      this.#clearAuthorityTimeout();
      this.#setSnapshot({ state: "uploading", statusCode: "capture_upload_pending", remainingAuthoritySeconds: 0 });
    } else this.#fail();
  }

  #setSnapshot(patch: Partial<CaptureFlowSnapshot>): void {
    this.#snapshot = { ...this.#snapshot, ...patch };
    for (const listener of this.#listeners) listener(this.snapshot);
  }
}

function isUnconfirmedCaptureStop(error: unknown): error is AudioCaptureError | CaptureStopAcknowledgementPending {
  return error instanceof CaptureStopAcknowledgementPending
    || error instanceof AudioCaptureError && error.code === "audio_capture_native_stop_failed";
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
