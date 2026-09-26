import { base64UrlEncode, MAX_AGGREGATE_PLAINTEXT_BYTES, NONCE_BYTES } from "@cosmaneura-scribe/capture-protocol";

import { QueueInvariantError } from "../queue/errors";
import type { CaptureLeaseReceipt, ChunkReservationBatchReceipt } from "../bff/contracts";
import { normalizedLease, requireRenewal, renewalUuid, sameRenewalIntent, validateRenewalIntent, validateRenewalRecord,
  type CaptureRenewalIntent, type CaptureRenewalRecord, type CaptureRenewalStore } from "./renewal-contract";
import { validateProfileReceipt, validateProfileSelection, canonicalProfileRequest } from "../bff/profile-contracts";
import { assertRecoveryIntent, type CaptureRecoveryIntent } from "./recovery-exchange";
import { canonicalCaptureTimestamp as canonicalRecoveryTime, canonicalRecoveryRequest, validateRecoveryState,
  type CaptureRecoveryState } from "../bff/recovery-contracts";
import {
  FLOW_RECORD_SCHEMA_VERSION,
  type ActiveCaptureState,
  type CaptureRecoveryStateV1,
  type CaptureFlowStore,
  type CapturePreparationState,
  type ReservationIntent,
  type SessionKeyBindingState,
} from "./types";
import {
  assertCaptureRecoveryProgression,
  assertCaptureRecoveryState,
} from "./recovery-state";

const DATABASE_VERSION = 1;
const FLOW_RECORD_STORE = "encrypted-flow-records";
const METADATA_STORE = "metadata";
const SESSION_KEY_STORE = "session-keys";
const LOCAL_KEY_ID = "flow-state-encryption-key-v1";
const LOCAL_AAD_PREFIX = "cosmaneura-capture-flow-state:v1";
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/iu;
const IDEMPOTENCY_PATTERN = /^[A-Za-z0-9._:-]{8,255}$/u;
export type CaptureQueueStorageKind = "browser" | "native";

type StoredFlowValue =
  | CaptureRenewalIntent
  | CaptureLeaseReceipt
  | ChunkReservationBatchReceipt
  | CaptureRecoveryIntent
  | ActiveCaptureState
  | CaptureRecoveryStateV1
  | CapturePreparationState
  | ReservationIntent
  | SessionKeyBindingState;

interface SealedFlowRecord {
  readonly key: string;
  readonly nonce: Uint8Array<ArrayBuffer>;
  readonly ciphertext: ArrayBuffer;
  /** Present only on recovery records to support atomic optimistic concurrency. */
  readonly recordRevision?: number;
}

export interface EncryptedFlowStoreOptions {
  readonly databaseName?: string;
  readonly indexedDB?: IDBFactory;
  readonly crypto?: Crypto;
}

export class EncryptedIndexedDbFlowStore implements CaptureFlowStore, CaptureRenewalStore {
  readonly #database: IDBDatabase;
  readonly #localKey: CryptoKey;
  readonly #crypto: Crypto;

  private constructor(database: IDBDatabase, localKey: CryptoKey, crypto: Crypto) {
    this.#database = database;
    this.#localKey = localKey;
    this.#crypto = crypto;
  }

  static async open(
    options: EncryptedFlowStoreOptions = {},
  ): Promise<EncryptedIndexedDbFlowStore> {
    const indexedDB = options.indexedDB ?? globalThis.indexedDB;
    const crypto = options.crypto ?? globalThis.crypto;
    if (indexedDB === undefined || crypto?.subtle === undefined) {
      throw new QueueInvariantError("encrypted_flow_store_unavailable");
    }
    const database = await openDatabase(
      indexedDB,
      options.databaseName ?? "cosmaneura-capture-flow",
    );
    try {
      const localKey = await getOrCreateLocalKey(database, crypto);
      assertAesKey(localKey, "invalid_flow_encryption_key");
      return new EncryptedIndexedDbFlowStore(database, localKey, crypto);
    } catch (error) {
      database.close();
      throw error;
    }
  }

  async getQueueStorageKind(sessionId: string): Promise<CaptureQueueStorageKind | null> {
    assertUuid(sessionId, "invalid_session_id");
    const transaction = this.#database.transaction(METADATA_STORE, "readonly");
    const done = transactionDone(transaction);
    const value = await requestResult(transaction.objectStore(METADATA_STORE).get(`queue-storage:${sessionId}`));
    await done;
    if (value === undefined) return null;
    if (value === "configured:browser") return "browser";
    if (value === "configured:native") return "native";
    if (value !== "browser" && value !== "native") throw new QueueInvariantError("queue_storage_profile_invalid");
    return value;
  }

  /** A crash or build-flag change must not silently select a different pending queue. */
  async claimQueueStorageKind(sessionId: string, kind: CaptureQueueStorageKind): Promise<void> {
    assertUuid(sessionId, "invalid_session_id");
    if (kind !== "browser" && kind !== "native") throw new QueueInvariantError("queue_storage_profile_invalid");
    const transaction = this.#database.transaction(METADATA_STORE, "readwrite");
    const metadata = transaction.objectStore(METADATA_STORE);
    const key = `queue-storage:${sessionId}`;
    let failure: QueueInvariantError | undefined;
    const current = metadata.get(key);
    current.addEventListener("success", () => {
      if (current.result === undefined) metadata.put(kind, key);
      else if (current.result !== kind && current.result !== `configured:${kind}`) {
        failure = new QueueInvariantError("queue_storage_profile_changed");
        transaction.abort();
      }
    });
    await transactionDone(transaction, () => failure);
  }

  /** Called only after the controller and queue have no unfinished local work. */
  async releaseQueueStorageKind(sessionId: string, kind: CaptureQueueStorageKind): Promise<void> {
    assertUuid(sessionId, "invalid_session_id");
    const transaction = this.#database.transaction(METADATA_STORE, "readwrite");
    const metadata = transaction.objectStore(METADATA_STORE);
    const key = `queue-storage:${sessionId}`;
    const current = metadata.get(key);
    current.addEventListener("success", () => {
      if (current.result === kind || current.result === `configured:${kind}`) metadata.delete(key);
    });
    await transactionDone(transaction);
  }

  /** Fence older writers before the configured continuation engine owns this queue. */
  async usesDesktopCaptureStorage(sessionId: string): Promise<boolean> {
    assertUuid(sessionId, "invalid_session_id");
    const transaction = this.#database.transaction(METADATA_STORE, "readonly"), done = transactionDone(transaction);
    const value = await requestResult(transaction.objectStore(METADATA_STORE).get(`queue-storage:${sessionId}`));
    await done;
    return value === "configured:desktop";
  }

  /** Never convert browser/native ciphertext into the main-process store. */
  async claimDesktopCaptureStorage(sessionId: string): Promise<void> {
    assertUuid(sessionId, "invalid_session_id");
    const transaction = this.#database.transaction(METADATA_STORE, "readwrite"), metadata = transaction.objectStore(METADATA_STORE);
    const key = `queue-storage:${sessionId}`;
    let failure: QueueInvariantError | undefined;
    const current = metadata.get(key);
    current.addEventListener("success", () => {
      if (current.result === undefined || current.result === "configured:desktop") metadata.put("configured:desktop", key);
      else { failure = new QueueInvariantError("queue_storage_profile_changed"); transaction.abort(); }
    });
    await transactionDone(transaction, () => failure);
  }

  async claimConfiguredCaptureStorage(sessionId: string, kind: CaptureQueueStorageKind): Promise<void> {
    assertUuid(sessionId, "invalid_session_id");
    if (kind !== "browser" && kind !== "native") throw new QueueInvariantError("queue_storage_profile_invalid");
    const transaction = this.#database.transaction(METADATA_STORE, "readwrite");
    const metadata = transaction.objectStore(METADATA_STORE), key = `queue-storage:${sessionId}`;
    let failure: QueueInvariantError | undefined;
    const current = metadata.get(key);
    current.addEventListener("success", () => {
      if (current.result === kind || current.result === `configured:${kind}`) metadata.put(`configured:${kind}`, key);
      else { failure = new QueueInvariantError("queue_storage_profile_changed"); transaction.abort(); }
    });
    await transactionDone(transaction, () => failure);
  }

  async putPreparationState(state: CapturePreparationState): Promise<void> {
    state = structuredClone(state);
    assertPreparationState(state);
    await this.#validatePreparationProfile(state);
    const existing = await this.getPreparationState();
    if (existing !== null) assertPreparationProgression(existing, state);
    const sealed = await this.#seal("preparation", state);
    const transaction = this.#database.transaction(FLOW_RECORD_STORE, "readwrite");
    transaction.objectStore(FLOW_RECORD_STORE).put(sealed);
    await transactionDone(transaction);
  }

  async getPreparationState(): Promise<CapturePreparationState | null> {
    const value = await this.#getRecord("preparation");
    if (value === null) return null;
    assertPreparationState(value);
    await this.#validatePreparationProfile(value);
    return value;
  }

  async #validatePreparationProfile(state: CapturePreparationState): Promise<void> {
    if (state.mode === "core_admitted" && state.profileSelection !== undefined) {
      await validateProfileSelection(state.profileSelection, state.sessionId, this.#crypto);
      if (state.leaseRequest !== null && state.profileSelection.receipt === null) {
        throw new QueueInvariantError("capture_profile_unconfirmed");
      }
    }
  }

  async putActiveCaptureState(state: ActiveCaptureState): Promise<void> {
    state = structuredClone(state);
    assertActiveCaptureState(state);
    if (state.captureProfile !== undefined) await validateProfileReceipt(state.captureProfile, state.sessionId, new Date(), undefined, this.#crypto);
    const previous = await this.#getSealedRecord("active");
    const existing = await this.getActiveCaptureState();
    if (existing === null) {
      const preparation = await this.getPreparationState();
      const selected = preparation?.mode === "core_admitted" ? preparation.profileSelection?.receipt : undefined;
      if ((preparation?.mode === "core_admitted" ? preparation.reviewAfterUpload : undefined) !== state.reviewAfterUpload ||
          selected === null || JSON.stringify(selected) !== JSON.stringify(state.captureProfile)) {
        throw new QueueInvariantError("capture_profile_unconfirmed");
      }
    }
    if (existing !== null && existing.sessionId !== state.sessionId) {
      throw new QueueInvariantError("active_capture_conflict");
    }
    if (existing !== null) assertActiveCaptureProgression(existing, state);
    const sealed = await this.#seal("active", state);
    await this.#compareAndSwapRecords([{ key: "active", previous }], [sealed]);
  }

  async getActiveCaptureState(): Promise<ActiveCaptureState | null> {
    const value = await this.#getRecord("active");
    if (value === null) return null;
    assertActiveCaptureState(value);
    if (value.captureProfile !== undefined) await validateProfileReceipt(value.captureProfile, value.sessionId, new Date(), undefined, this.#crypto);
    return value;
  }

  async putCaptureRecoveryState(state: CaptureRecoveryStateV1): Promise<void> {
    assertCaptureRecoveryState(state);
    const key = await this.#recoveryRecordKey(state.sessionId);
    const existing = await this.getCaptureRecoveryState(state.sessionId);
    if (existing !== null) {
      if (JSON.stringify(existing) === JSON.stringify(state)) return;
      assertCaptureRecoveryProgression(existing, state);
    } else if (
      state.localRevision !== 1 || state.phase !== "ready" ||
      state.nextSegmentOrdinal !== 0 || state.nextSequenceNumber !== 0 ||
      state.currentSegmentId !== null || state.segments.length !== 0 || state.gaps.length !== 0
    ) {
      throw new QueueInvariantError("capture_recovery_state_conflict");
    }
    const sealed = await this.#seal(key, state, state.localRevision);
    const transaction = this.#database.transaction(FLOW_RECORD_STORE, "readwrite");
    const records = transaction.objectStore(FLOW_RECORD_STORE);
    let failure: QueueInvariantError | undefined;
    const current = records.get(key) as IDBRequest<unknown>;
    current.addEventListener("success", () => {
      const value = current.result;
      if (value === undefined) {
        if (existing !== null) {
          failure = new QueueInvariantError("capture_recovery_state_conflict");
          transaction.abort();
          return;
        }
      } else {
        try {
          assertSealedRecord(value);
        } catch {
          failure = new QueueInvariantError("capture_recovery_state_conflict");
          transaction.abort();
          return;
        }
        if (existing === null || value.recordRevision !== existing.localRevision) {
          failure = new QueueInvariantError("capture_recovery_state_conflict");
          transaction.abort();
          return;
        }
      }
      records.put(sealed);
    });
    try {
      await transactionDone(transaction, () => failure);
    } catch (error) {
      if (failure?.code !== "capture_recovery_state_conflict") throw error;
      const converged = await this.getCaptureRecoveryState(state.sessionId);
      if (converged !== null && JSON.stringify(converged) === JSON.stringify(state)) return;
      throw error;
    }
  }

  async getCaptureRecoveryState(sessionId: string): Promise<CaptureRecoveryStateV1 | null> {
    assertUuid(sessionId, "invalid_session_id");
    const value = await this.#getRecord(await this.#recoveryRecordKey(sessionId));
    if (value === null) return null;
    assertCaptureRecoveryState(value);
    if (value.sessionId !== sessionId) {
      throw new QueueInvariantError("capture_recovery_session_conflict");
    }
    return value;
  }

  async putCaptureRecoveryIntent(intent: CaptureRecoveryIntent, purpose?: "finish"): Promise<void> {
    assertRecoveryIntent(intent);
    if (purpose !== undefined && (purpose !== "finish" || intent.request.decision !== "finish_capture")) {
      throw new QueueInvariantError("capture_recovery_intent_invalid");
    }
    const key = `${await this.#recoveryRecordKey(intent.sessionId)}:command:${intent.request.gap_id}${purpose === "finish" ? ":finish" : ""}`;
    await this.#putExact(key, intent);
  }

  async getCaptureRecoveryIntent(sessionId: string, gapId: string, purpose?: "finish"): Promise<CaptureRecoveryIntent | null> {
    assertUuid(sessionId, "invalid_session_id");
    assertUuid(gapId, "invalid_capture_gap_id");
    if (purpose !== undefined && purpose !== "finish") throw new QueueInvariantError("capture_recovery_intent_invalid");
    const value = await this.#getRecord(`${await this.#recoveryRecordKey(sessionId)}:command:${gapId}${purpose === "finish" ? ":finish" : ""}`);
    if (value === null) return null;
    assertRecoveryIntent(value);
    if (value.sessionId !== sessionId || value.request.gap_id !== gapId) {
      throw new QueueInvariantError("capture_recovery_session_conflict");
    }
    return value;
  }

  /** Ordinary state writes cannot rotate a lease or erase its reservation deadline. */
  async reconcileCaptureLease(state: CaptureRecoveryState): Promise<ActiveCaptureState> {
    const previous = await this.#getSealedRecord("active");
    const existing = await this.getActiveCaptureState();
    if (existing === null) throw new QueueInvariantError("active_capture_conflict");
    const current = await validateRecoveryState(state, existing.sessionId, new Date(), this.#crypto);
    const recovery = await this.getCaptureRecoveryState(existing.sessionId);
    const gap = recovery?.gaps.at(-1);
    const receipt = current.history.recoveries.at(-1);
    const intent = gap ? await this.getCaptureRecoveryIntent(existing.sessionId, gap.gapId,
      recovery?.finishChoice?.priorResult === "uncommitted" && receipt?.request.decision === "finish_capture" ? "finish" : undefined) : null;
    if (!gap?.acknowledgement || !receipt || !intent ||
        canonicalRecoveryRequest(receipt.request) !== canonicalRecoveryRequest(intent.request) ||
        receipt.request.gap_id !== gap.gapId || current.history.recoveries.length !== recovery?.gaps.length ||
        !current.current_lease || current.lease_closed || !["created", "capturing"].includes(current.session_status) ||
        !["paused", "ready"].includes(existing.phase) ||
        current.current_lease.lease_id !== existing.lease.lease_id ||
        current.current_lease.generation < existing.lease.generation ||
        (current.current_lease.generation === existing.lease.generation &&
          JSON.stringify(current.current_lease) !== JSON.stringify(existing.lease))) {
      throw new QueueInvariantError("capture_recovery_state_conflict");
    }
    const replacement: ActiveCaptureState = { ...existing, phase: "paused",
      lease: current.current_lease, captureAuthorizedUntil: null };
    assertActiveCaptureState(replacement);
    const sealed = await this.#seal("active", replacement);
    await this.#compareAndSwapRecords([{ key: "active", previous }], [sealed]);
    return replacement;
  }

  async #renewalPrefix(sessionId: string): Promise<string> {
    assertUuid(sessionId, "capture_renewal_conflict");
    return `renewal:${await this.#recoveryRecordKey(sessionId)}:`;
  }

  async #renewalKey(sessionId: string, leaseId: string, generation: number): Promise<string> {
    requireRenewal(renewalUuid(leaseId) && Number.isSafeInteger(generation) && generation >= 1);
    return `${await this.#renewalPrefix(sessionId)}${leaseId}:${generation}`;
  }

  async getCaptureRenewal(sessionId: string, leaseId: string, priorGeneration: number): Promise<CaptureRenewalRecord | null> {
    const key = await this.#renewalKey(sessionId, leaseId, priorGeneration);
    const intent = await this.#getRecord(`${key}:intent`);
    if (intent === null) return null;
    const record = validateRenewalRecord({ intent, lease: await this.#getRecord(`${key}:lease`),
      reservations: await this.#getRecord(`${key}:reservations`) });
    requireRenewal(record.intent.sessionId === sessionId && record.intent.priorLease.lease_id === leaseId &&
      record.intent.priorLease.generation === priorGeneration);
    return record;
  }

  async putCaptureRenewal(value: CaptureRenewalRecord): Promise<void> {
    const record = validateRenewalRecord(structuredClone(value)), intent = record.intent;
    const key = await this.#renewalKey(intent.sessionId, intent.priorLease.lease_id, intent.priorLease.generation);
    const existing = await this.getCaptureRenewal(intent.sessionId, intent.priorLease.lease_id, intent.priorLease.generation);
    if (existing === null) {
      // Only a live run may create an intent. Returned receipts may still be
      // persisted after Stop, so their remote generation can be reconciled.
      requireRenewal(record.lease === null && record.reservations === null);
      const recoveryKey = await this.#recoveryRecordKey(intent.sessionId);
      const priorActive = await this.#getSealedRecord("active"), priorRecovery = await this.#getSealedRecord(recoveryKey);
      const active = await this.getActiveCaptureState(), recovery = await this.getCaptureRecoveryState(intent.sessionId);
      const segment = recovery?.segments.at(-1);
      requireRenewal(active?.phase === "recording" && active.sessionId === intent.sessionId &&
        active.captureProfile?.receipt_id === intent.profileReceiptId &&
        JSON.stringify(normalizedLease(active.lease, intent.sessionId)) === JSON.stringify(intent.priorLease) &&
        active.captureAuthorizedUntil !== null && canonicalRecoveryTime(active.captureAuthorizedUntil) === intent.priorCaptureAuthorizedUntil &&
        active.recordedChunks < intent.firstSequenceNumber && recovery?.phase === "recording" &&
        recovery.currentSegmentId === intent.segmentId && segment?.segmentId === intent.segmentId && segment.ordinal === intent.segmentOrdinal &&
        segment.state === "recording" && Date.now() < Date.parse(intent.priorCaptureAuthorizedUntil));
      const sealed = await this.#seal(`${key}:intent`, intent);
      await this.#compareAndSwapRecords([{ key: "active", previous: priorActive }, { key: recoveryKey, previous: priorRecovery },
        { key: `${key}:intent`, previous: null }], [sealed], () => requireRenewal(Date.now() < Date.parse(intent.priorCaptureAuthorizedUntil)));
    } else {
      requireRenewal(sameRenewalIntent(existing.intent, intent));
    }
    if (record.lease !== null) await this.#putRenewalReceipt(`${key}:lease`, record.lease, `${key}:intent`);
    if (record.reservations !== null) await this.#putRenewalReceipt(`${key}:reservations`, record.reservations, `${key}:intent`);
  }

  async #putRenewalReceipt(key: string, value: CaptureLeaseReceipt | ChunkReservationBatchReceipt, intentKey: string): Promise<void> {
    const intent = await this.#getSealedRecord(intentKey);
    requireRenewal(intent !== null);
    const existing = await this.#getRecord(key);
    if (existing !== null) {
      requireRenewal(JSON.stringify(existing) === JSON.stringify(value));
      return;
    }
    const sealed = await this.#seal(key, value);
    // A reply racing confirmed-completion cleanup must not recreate orphaned
    // receipts after the capture and its renewal intent have been removed.
    await this.#compareAndSwapRecords([{ key: intentKey, previous: intent }, { key, previous: null }], [sealed]);
  }

  async applyCaptureRenewal(value: CaptureRenewalIntent, mode: "continuous" | "interrupted" | "stopped", now: Date): Promise<ActiveCaptureState> {
    const intent = validateRenewalIntent(value);
    requireRenewal(mode === "continuous" || mode === "interrupted" || mode === "stopped");
    const record = await this.getCaptureRenewal(intent.sessionId, intent.priorLease.lease_id, intent.priorLease.generation);
    requireRenewal(record !== null && record.lease !== null && sameRenewalIntent(record.intent, intent));
    const recoveryKey = await this.#recoveryRecordKey(intent.sessionId);
    const priorActive = await this.#getSealedRecord("active"), priorRecovery = await this.#getSealedRecord(recoveryKey);
    const active = await this.getActiveCaptureState(), recovery = await this.getCaptureRecoveryState(intent.sessionId);
    const segment = recovery?.segments.at(-1);
    requireRenewal(active !== null && active.sessionId === intent.sessionId && active.captureProfile?.receipt_id === intent.profileReceiptId &&
      segment?.segmentId === intent.segmentId && segment.ordinal === intent.segmentOrdinal);
    const activeLease = normalizedLease(active.lease, intent.sessionId);
    const alreadyApplied = JSON.stringify(activeLease) === JSON.stringify(record.lease);
    requireRenewal(alreadyApplied || JSON.stringify(activeLease) === JSON.stringify(intent.priorLease));
    if (mode === "continuous") {
      requireRenewal(active.phase === "recording" && recovery?.phase === "recording" && segment.state === "recording" &&
        recovery.currentSegmentId === intent.segmentId && record.reservations !== null &&
        now.getTime() < Date.parse(intent.priorCaptureAuthorizedUntil) &&
        Date.parse(record.lease.issued_at) < Date.parse(intent.priorCaptureAuthorizedUntil) &&
        now.getTime() < Date.parse(record.lease.expires_at) &&
        (alreadyApplied || active.captureAuthorizedUntil !== null &&
          canonicalRecoveryTime(active.captureAuthorizedUntil) === intent.priorCaptureAuthorizedUntil));
    } else if (mode === "stopped") {
      requireRenewal(["uploading", "completing"].includes(active.phase) && recovery?.phase === "stopped" &&
        recovery.currentSegmentId === null && segment.state === "stopped" &&
        recovery.nextSequenceNumber === active.recordedChunks);
    } else {
      requireRenewal(active.phase === "paused" && recovery !== null && recovery.phase !== "recording" &&
        ["interrupted", "uncertain", "stopped"].includes(segment.state));
    }
    // Preserve the latest recorded counters instead of the pre-I/O snapshot.
    // Interrupted reconciliation never widens the old recording window.
    const replacement: ActiveCaptureState = { ...active, lease: record.lease,
      captureAuthorizedUntil: mode === "continuous" ? record.reservations!.capture_authorized_until : active.captureAuthorizedUntil };
    assertActiveCaptureState(replacement);
    const sealed = await this.#seal("active", replacement);
    await this.#compareAndSwapRecords([{ key: "active", previous: priorActive }, { key: recoveryKey, previous: priorRecovery }], [sealed], () => {
      if (mode === "continuous") requireRenewal(Date.now() < Date.parse(intent.priorCaptureAuthorizedUntil) &&
        Date.now() < Date.parse(record.lease!.expires_at));
    });
    return replacement;
  }

  async clearCompletedCapture(sessionId: string): Promise<void> {
    assertUuid(sessionId, "invalid_session_id");
    const recoveryKey = await this.#recoveryRecordKey(sessionId);
    const renewalPrefix = await this.#renewalPrefix(sessionId);
    const existing = await this.getActiveCaptureState();
    if (existing === null) return;
    if (existing.sessionId !== sessionId) {
      throw new QueueInvariantError("active_capture_conflict");
    }
    const transaction = this.#database.transaction(
      [FLOW_RECORD_STORE, SESSION_KEY_STORE],
      "readwrite",
    );
    const records = transaction.objectStore(FLOW_RECORD_STORE);
    records.delete("active");
    records.delete("preparation");
    records.delete(`session:${sessionId}`);
    records.delete(recoveryKey);
    const cursor = records.openCursor();
    cursor.addEventListener("success", () => {
      const item = cursor.result;
      if (!item) return;
      if (typeof item.key === "string" && item.key.startsWith(renewalPrefix)) item.delete();
      item.continue();
    });
    transaction.objectStore(SESSION_KEY_STORE).delete(sessionId);
    await transactionDone(transaction);
  }

  async putReservationIntent(intent: ReservationIntent): Promise<void> {
    assertReservationIntent(intent);
    await this.#putExact(`intent:${intent.intentId}`, intent);
  }

  async listReservationIntents(): Promise<readonly ReservationIntent[]> {
    const transaction = this.#database.transaction(FLOW_RECORD_STORE, "readonly");
    const done = transactionDone(transaction);
    const request = transaction.objectStore(FLOW_RECORD_STORE).getAll() as IDBRequest<unknown>;
    const values = await requestResult(request);
    await done;
    if (!Array.isArray(values)) throw new QueueInvariantError("invalid_flow_store_record");
    const intents: ReservationIntent[] = [];
    for (const value of values) {
      assertSealedRecord(value);
      if (!value.key.startsWith("intent:")) continue;
      const opened = await this.#open(value);
      assertReservationIntent(opened);
      intents.push(opened);
    }
    return intents.sort((left, right) => left.createdAt.localeCompare(right.createdAt));
  }

  async deleteReservationIntent(intentId: string): Promise<void> {
    assertIdentifier(intentId, "invalid_reservation_intent");
    const transaction = this.#database.transaction(FLOW_RECORD_STORE, "readwrite");
    transaction.objectStore(FLOW_RECORD_STORE).delete(`intent:${intentId}`);
    await transactionDone(transaction);
  }

  async putSessionKeyCandidate(
    state: SessionKeyBindingState,
    key: CryptoKey,
  ): Promise<void> {
    assertSessionKeyState(state);
    assertSessionDek(key);
    const storageKey = `session:${state.sessionId}`;
    const sealed = await this.#seal(storageKey, state);
    const transaction = this.#database.transaction(
      [FLOW_RECORD_STORE, SESSION_KEY_STORE],
      "readwrite",
    );
    const records = transaction.objectStore(FLOW_RECORD_STORE);
    const keys = transaction.objectStore(SESSION_KEY_STORE);
    let failure: QueueInvariantError | undefined;
    const existing = records.get(storageKey) as IDBRequest<unknown>;
    existing.addEventListener("success", () => {
      if (existing.result !== undefined) {
        failure = new QueueInvariantError("session_key_already_exists");
        transaction.abort();
        return;
      }
      records.add(sealed);
      keys.add(key, state.sessionId);
    });
    await transactionDone(transaction, () => failure);
  }

  async replacePendingSessionKeyCandidate(
    state: SessionKeyBindingState,
    key: CryptoKey,
  ): Promise<void> {
    assertSessionKeyState(state);
    assertSessionDek(key);
    if (state.state !== "pending") {
      throw new QueueInvariantError("invalid_session_key_state");
    }
    const existing = await this.getSessionKeyState(state.sessionId);
    if (existing?.state !== "pending") {
      throw new QueueInvariantError("session_key_replacement_refused");
    }
    const storageKey = `session:${state.sessionId}`;
    const sealed = await this.#seal(storageKey, state);
    const transaction = this.#database.transaction(
      [FLOW_RECORD_STORE, SESSION_KEY_STORE],
      "readwrite",
    );
    transaction.objectStore(FLOW_RECORD_STORE).put(sealed);
    transaction.objectStore(SESSION_KEY_STORE).put(key, state.sessionId);
    await transactionDone(transaction);
  }

  async getSessionKeyState(sessionId: string): Promise<SessionKeyBindingState | null> {
    assertUuid(sessionId, "invalid_session_id");
    const value = await this.#getRecord(`session:${sessionId}`);
    if (value === null) return null;
    assertSessionKeyState(value);
    return value;
  }

  async getSessionKey(sessionId: string): Promise<CryptoKey | null> {
    assertUuid(sessionId, "invalid_session_id");
    const transaction = this.#database.transaction(SESSION_KEY_STORE, "readonly");
    const done = transactionDone(transaction);
    const request = transaction.objectStore(SESSION_KEY_STORE).get(sessionId) as IDBRequest<unknown>;
    const value = await requestResult(request);
    await done;
    if (value === undefined) return null;
    if (!isCryptoKey(value)) throw new QueueInvariantError("invalid_session_dek");
    assertSessionDek(value);
    return value;
  }

  async markSessionKeyBound(sessionId: string): Promise<void> {
    const state = await this.getSessionKeyState(sessionId);
    if (state === null) throw new QueueInvariantError("session_key_missing");
    if (state.state === "bound") return;
    const storageKey = `session:${sessionId}`;
    const sealed = await this.#seal(storageKey, { ...state, state: "bound" });
    const transaction = this.#database.transaction(FLOW_RECORD_STORE, "readwrite");
    transaction.objectStore(FLOW_RECORD_STORE).put(sealed);
    await transactionDone(transaction);
  }

  close(): void {
    this.#database.close();
  }

  async #recoveryRecordKey(sessionId: string): Promise<string> {
    const input = new TextEncoder().encode(`${LOCAL_AAD_PREFIX}:recovery:${sessionId}`);
    const digest = new Uint8Array(await this.#crypto.subtle.digest("SHA-256", input));
    input.fill(0);
    try {
      return `recovery:${base64UrlEncode(digest)}`;
    } finally {
      digest.fill(0);
    }
  }

  async #putExact(key: string, value: StoredFlowValue): Promise<void> {
    const sealed = await this.#seal(key, value);
    const existing = await this.#getRecord(key);
    if (existing !== null) {
      if (JSON.stringify(existing) !== JSON.stringify(value)) {
        throw new QueueInvariantError("flow_record_conflict");
      }
      return;
    }
    const transaction = this.#database.transaction(FLOW_RECORD_STORE, "readwrite");
    transaction.objectStore(FLOW_RECORD_STORE).add(sealed);
    await transactionDone(transaction);
  }

  async #getRecord(key: string): Promise<StoredFlowValue | null> {
    const transaction = this.#database.transaction(FLOW_RECORD_STORE, "readonly");
    const done = transactionDone(transaction);
    const request = transaction.objectStore(FLOW_RECORD_STORE).get(key) as IDBRequest<unknown>;
    const value = await requestResult(request);
    await done;
    if (value === undefined) return null;
    assertSealedRecord(value);
    return this.#open(value);
  }

  async #getSealedRecord(key: string): Promise<SealedFlowRecord | null> {
    const transaction = this.#database.transaction(FLOW_RECORD_STORE, "readonly"), done = transactionDone(transaction);
    const value = await requestResult(transaction.objectStore(FLOW_RECORD_STORE).get(key));
    await done;
    if (value === undefined) return null;
    assertSealedRecord(value);
    return value;
  }

  async #compareAndSwapRecords(guards: { key: string; previous: SealedFlowRecord | null }[], writes: SealedFlowRecord[], beforeWrite?: () => void): Promise<void> {
    const transaction = this.#database.transaction(FLOW_RECORD_STORE, "readwrite");
    const records = transaction.objectStore(FLOW_RECORD_STORE);
    let remaining = guards.length, failure: QueueInvariantError | undefined;
    for (const guard of guards) {
      const read = records.get(guard.key);
      read.addEventListener("success", () => {
        if (failure) return;
        const current = read.result as SealedFlowRecord | undefined;
        try { if (current !== undefined) assertSealedRecord(current); }
        catch { failure = new QueueInvariantError("active_capture_conflict"); transaction.abort(); return; }
        const same = guard.previous === null ? current === undefined : current !== undefined &&
          sameBytes(current.nonce, guard.previous.nonce) && sameBytes(current.ciphertext, guard.previous.ciphertext);
        if (!same) { failure = new QueueInvariantError("active_capture_conflict"); transaction.abort(); return; }
        if (--remaining === 0) {
          try { beforeWrite?.(); }
          catch (error) { failure = error instanceof QueueInvariantError ? error : new QueueInvariantError("active_capture_conflict"); transaction.abort(); return; }
          for (const value of writes) records.put(value);
        }
      });
    }
    await transactionDone(transaction, () => failure);
  }

  async #seal(
    key: string,
    value: StoredFlowValue,
    recordRevision?: number,
  ): Promise<SealedFlowRecord> {
    const nonce = this.#crypto.getRandomValues(new Uint8Array(new ArrayBuffer(NONCE_BYTES)));
    const plaintext = new TextEncoder().encode(JSON.stringify(value));
    try {
      const ciphertext = await this.#crypto.subtle.encrypt(
        {
          name: "AES-GCM",
          iv: nonce,
          additionalData: localAdditionalData(key, recordRevision),
        },
        this.#localKey,
        plaintext,
      );
      return {
        key,
        nonce,
        ciphertext,
        ...(recordRevision === undefined ? {} : { recordRevision }),
      };
    } finally {
      plaintext.fill(0);
    }
  }

  async #open(sealed: SealedFlowRecord): Promise<StoredFlowValue> {
    let plaintext: ArrayBuffer;
    try {
      plaintext = await this.#crypto.subtle.decrypt(
        {
          name: "AES-GCM",
          iv: sealed.nonce,
          additionalData: localAdditionalData(sealed.key, sealed.recordRevision),
        },
        this.#localKey,
        sealed.ciphertext,
      );
    } catch {
      throw new QueueInvariantError("encrypted_flow_store_integrity_failure");
    }
    const bytes = new Uint8Array(plaintext);
    try {
      const value = JSON.parse(
        new TextDecoder("utf-8", { fatal: true }).decode(bytes),
      ) as StoredFlowValue;
      if (
        sealed.recordRevision !== undefined &&
        (!isRecord(value) || !("localRevision" in value) || value.localRevision !== sealed.recordRevision)
      ) {
        throw new QueueInvariantError("encrypted_flow_store_integrity_failure");
      }
      return value;
    } catch {
      throw new QueueInvariantError("encrypted_flow_store_integrity_failure");
    } finally {
      bytes.fill(0);
    }
  }
}

async function openDatabase(indexedDB: IDBFactory, name: string): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(name, DATABASE_VERSION);
    request.addEventListener("upgradeneeded", () => {
      const database = request.result;
      if (!database.objectStoreNames.contains(FLOW_RECORD_STORE)) {
        database.createObjectStore(FLOW_RECORD_STORE, { keyPath: "key" });
      }
      if (!database.objectStoreNames.contains(METADATA_STORE)) {
        database.createObjectStore(METADATA_STORE);
      }
      if (!database.objectStoreNames.contains(SESSION_KEY_STORE)) {
        database.createObjectStore(SESSION_KEY_STORE);
      }
    });
    request.addEventListener("success", () => resolve(request.result));
    request.addEventListener("error", () => reject(new QueueInvariantError("flow_database_error")));
    request.addEventListener("blocked", () => reject(new QueueInvariantError("flow_database_blocked")));
  });
}

async function getOrCreateLocalKey(database: IDBDatabase, crypto: Crypto): Promise<CryptoKey> {
  const candidate = await crypto.subtle.generateKey(
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"],
  );
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(
      [METADATA_STORE, FLOW_RECORD_STORE, SESSION_KEY_STORE],
      "readwrite",
    );
    const metadata = transaction.objectStore(METADATA_STORE);
    const lookup = metadata.get(LOCAL_KEY_ID) as IDBRequest<unknown>;
    let selected = candidate;
    let failure: QueueInvariantError | undefined;
    lookup.addEventListener("success", () => {
      if (lookup.result === undefined) {
        const records = transaction.objectStore(FLOW_RECORD_STORE).count();
        const sessionKeys = transaction.objectStore(SESSION_KEY_STORE).count();
        let recordCount: number | undefined;
        let sessionKeyCount: number | undefined;
        const finish = (): void => {
          if (recordCount === undefined || sessionKeyCount === undefined) return;
          if (recordCount !== 0 || sessionKeyCount !== 0) {
            failure = new QueueInvariantError("flow_encryption_key_missing");
            transaction.abort();
            return;
          }
          metadata.add(candidate, LOCAL_KEY_ID);
        };
        records.addEventListener("success", () => {
          recordCount = records.result;
          finish();
        });
        sessionKeys.addEventListener("success", () => {
          sessionKeyCount = sessionKeys.result;
          finish();
        });
      } else {
        if (!isCryptoKey(lookup.result)) {
          failure = new QueueInvariantError("invalid_flow_encryption_key");
          transaction.abort();
          return;
        }
        selected = lookup.result;
      }
    });
    transaction.addEventListener("complete", () => resolve(selected));
    transaction.addEventListener("abort", () => reject(failure ?? new QueueInvariantError("flow_database_aborted")));
    transaction.addEventListener("error", () => reject(new QueueInvariantError("flow_database_error")));
  });
}

function assertReservationIntent(value: unknown): asserts value is ReservationIntent {
  if (
    !isRecord(value) ||
    value.schemaVersion !== FLOW_RECORD_SCHEMA_VERSION ||
    typeof value.intentId !== "string" ||
    typeof value.sessionId !== "string" ||
    typeof value.idempotencyKey !== "string" ||
    typeof value.createdAt !== "string" ||
    !isRecord(value.request)
  ) {
    throw new QueueInvariantError("invalid_reservation_intent");
  }
  assertIdentifier(value.intentId, "invalid_reservation_intent");
  assertUuid(value.sessionId, "invalid_reservation_intent");
  assertIdempotencyKey(value.idempotencyKey);
  if (Number.isNaN(Date.parse(value.createdAt))) {
    throw new QueueInvariantError("invalid_reservation_intent");
  }
}

export function assertPreparationState(value: unknown): asserts value is CapturePreparationState {
  if (isRecord(value) && value.mode === "core_admitted") {
    if (Object.keys(value).sort().join(",") !==
        ["completeIdempotencyKey", "leaseIdempotencyKey", "leaseRequest", "mode", "schemaVersion", "sessionId", "startedAt",
          ...(value.profileSelection !== undefined ? ["profileSelection"] : []),
          ...(value.reviewAfterUpload !== undefined ? ["reviewAfterUpload"] : [])].sort().join(",") ||
        (value.reviewAfterUpload !== undefined && value.reviewAfterUpload !== true) ||
        value.schemaVersion !== FLOW_RECORD_SCHEMA_VERSION ||
        typeof value.startedAt !== "string" || Number.isNaN(Date.parse(value.startedAt)) ||
        typeof value.completeIdempotencyKey !== "string" || typeof value.sessionId !== "string" ||
        (value.leaseIdempotencyKey !== null && typeof value.leaseIdempotencyKey !== "string") ||
        (value.leaseRequest !== null && (!isRecord(value.leaseRequest) ||
          Object.keys(value.leaseRequest).join(",") !== "protocol_version" ||
          value.leaseRequest.protocol_version !== "1.0")) ||
        (value.leaseIdempotencyKey === null) !== (value.leaseRequest === null)) {
      throw new QueueInvariantError("invalid_preparation_state");
    }
    assertUuid(value.sessionId, "invalid_preparation_state");
    assertIdempotencyKey(value.completeIdempotencyKey);
    if (value.leaseIdempotencyKey !== null) assertIdempotencyKey(value.leaseIdempotencyKey);
    return;
  }
  if (
    !isRecord(value) ||
    "profileSelection" in value ||
    (value.mode !== undefined && value.mode !== "direct") ||
    value.schemaVersion !== FLOW_RECORD_SCHEMA_VERSION ||
    typeof value.startedAt !== "string" ||
    typeof value.consentIdempotencyKey !== "string" ||
    typeof value.completeIdempotencyKey !== "string" ||
    !isRecord(value.consentRequest) ||
    (value.consentId !== null && typeof value.consentId !== "string") ||
    (value.sessionIdempotencyKey !== null && typeof value.sessionIdempotencyKey !== "string") ||
    (value.sessionRequest !== null && !isRecord(value.sessionRequest)) ||
    (value.sessionId !== null && typeof value.sessionId !== "string") ||
    (value.leaseIdempotencyKey !== null && typeof value.leaseIdempotencyKey !== "string") ||
    (value.leaseRequest !== null && !isRecord(value.leaseRequest))
  ) {
    throw new QueueInvariantError("invalid_preparation_state");
  }
  if (Number.isNaN(Date.parse(value.startedAt))) {
    throw new QueueInvariantError("invalid_preparation_state");
  }
  assertIdempotencyKey(value.consentIdempotencyKey);
  assertIdempotencyKey(value.completeIdempotencyKey);
  if (value.consentId !== null) assertUuid(value.consentId, "invalid_preparation_state");
  if (value.sessionIdempotencyKey !== null) assertIdempotencyKey(value.sessionIdempotencyKey);
  if (value.sessionId !== null) assertUuid(value.sessionId, "invalid_preparation_state");
  if (value.leaseIdempotencyKey !== null) assertIdempotencyKey(value.leaseIdempotencyKey);
  if (
    (value.sessionIdempotencyKey === null) !== (value.sessionRequest === null) ||
    (value.leaseIdempotencyKey === null) !== (value.leaseRequest === null)
  ) {
    throw new QueueInvariantError("invalid_preparation_state");
  }
}

function assertPreparationProgression(
  existing: CapturePreparationState,
  replacement: CapturePreparationState,
): void {
  if (existing.mode === "core_admitted" || replacement.mode === "core_admitted") {
    if (existing.mode !== "core_admitted" || replacement.mode !== "core_admitted" ||
        existing.reviewAfterUpload !== replacement.reviewAfterUpload ||
        existing.startedAt !== replacement.startedAt ||
        existing.completeIdempotencyKey !== replacement.completeIdempotencyKey ||
        existing.sessionId !== replacement.sessionId ||
        (existing.profileSelection === undefined) !== (replacement.profileSelection === undefined) ||
        !nullableStable(existing.leaseIdempotencyKey, replacement.leaseIdempotencyKey) ||
        !nullableStableJson(existing.leaseRequest, replacement.leaseRequest)) {
      throw new QueueInvariantError("preparation_state_conflict");
    }
    if (existing.profileSelection && replacement.profileSelection && (
        existing.profileSelection.idempotencyKey !== replacement.profileSelection.idempotencyKey ||
        canonicalProfileRequest(existing.profileSelection.request) !== canonicalProfileRequest(replacement.profileSelection.request) ||
        existing.profileSelection.receipt !== null &&
          JSON.stringify(existing.profileSelection.receipt) !== JSON.stringify(replacement.profileSelection.receipt))) {
      throw new QueueInvariantError("preparation_state_conflict");
    }
    return;
  }
  if (
    existing.startedAt !== replacement.startedAt ||
    existing.consentIdempotencyKey !== replacement.consentIdempotencyKey ||
    existing.completeIdempotencyKey !== replacement.completeIdempotencyKey ||
    JSON.stringify(existing.consentRequest) !== JSON.stringify(replacement.consentRequest) ||
    !nullableStable(existing.consentId, replacement.consentId) ||
    !nullableStable(existing.sessionIdempotencyKey, replacement.sessionIdempotencyKey) ||
    !nullableStableJson(existing.sessionRequest, replacement.sessionRequest) ||
    !nullableStable(existing.sessionId, replacement.sessionId) ||
    !nullableStable(existing.leaseIdempotencyKey, replacement.leaseIdempotencyKey) ||
    !nullableStableJson(existing.leaseRequest, replacement.leaseRequest)
  ) {
    throw new QueueInvariantError("preparation_state_conflict");
  }
}

function nullableStable(existing: string | null, replacement: string | null): boolean {
  return existing === null || existing === replacement;
}

function nullableStableJson(
  existing: Record<string, unknown> | null,
  replacement: Record<string, unknown> | null,
): boolean {
  return existing === null || JSON.stringify(existing) === JSON.stringify(replacement);
}

export function assertActiveCaptureState(value: unknown): asserts value is ActiveCaptureState {
  if (
    !isRecord(value) ||
    (value.reviewAfterUpload !== undefined && value.reviewAfterUpload !== true) ||
    value.schemaVersion !== FLOW_RECORD_SCHEMA_VERSION ||
    typeof value.sessionId !== "string" ||
    !isRecord(value.lease) ||
    (value.captureAuthorizedUntil !== null &&
      typeof value.captureAuthorizedUntil !== "string") ||
    !Number.isSafeInteger(value.aggregatePlaintextBudgetBytes) ||
    (value.aggregatePlaintextBudgetBytes as number) < 1 ||
    (value.aggregatePlaintextBudgetBytes as number) > (value.captureProfile === undefined ? MAX_AGGREGATE_PLAINTEXT_BYTES : 268435456) ||
    !isActiveCapturePhase(value.phase) ||
    typeof value.completeIdempotencyKey !== "string" ||
    !Number.isSafeInteger(value.recordedChunks) ||
    (value.recordedChunks as number) < 0 ||
    !Number.isSafeInteger(value.recordedPlaintextBytes) ||
    (value.recordedPlaintextBytes as number) < 0 ||
    typeof value.startedAt !== "string"
  ) {
    throw new QueueInvariantError("invalid_active_capture_state");
  }
  assertUuid(value.sessionId, "invalid_active_capture_state");
  assertIdempotencyKey(value.completeIdempotencyKey);
  if (Number.isNaN(Date.parse(value.startedAt))) {
    throw new QueueInvariantError("invalid_active_capture_state");
  }
  if (
    value.captureAuthorizedUntil !== null &&
    Number.isNaN(Date.parse(value.captureAuthorizedUntil))
  ) {
    throw new QueueInvariantError("invalid_active_capture_state");
  }
  assertLease(value.lease, value.sessionId);
}

function assertActiveCaptureProgression(
  existing: ActiveCaptureState,
  replacement: ActiveCaptureState,
): void {
  if (
    existing.reviewAfterUpload !== replacement.reviewAfterUpload ||
    JSON.stringify(existing.lease) !== JSON.stringify(replacement.lease) ||
    existing.completeIdempotencyKey !== replacement.completeIdempotencyKey ||
    existing.startedAt !== replacement.startedAt ||
    existing.aggregatePlaintextBudgetBytes !== replacement.aggregatePlaintextBudgetBytes ||
    JSON.stringify(existing.captureProfile) !== JSON.stringify(replacement.captureProfile) ||
    !nullableStable(existing.captureAuthorizedUntil, replacement.captureAuthorizedUntil) ||
    replacement.recordedChunks < existing.recordedChunks ||
    replacement.recordedPlaintextBytes < existing.recordedPlaintextBytes
  ) {
    throw new QueueInvariantError("active_capture_conflict");
  }
}

function assertLease(value: Record<string, unknown>, sessionId: string): void {
  if (
    value.protocol_version !== "1.0" ||
    typeof value.receipt_id !== "string" ||
    typeof value.lease_id !== "string" ||
    value.session_id !== sessionId ||
    !Number.isSafeInteger(value.generation) ||
    (value.generation as number) < 1 ||
    typeof value.issued_at !== "string" ||
    typeof value.expires_at !== "string"
  ) {
    throw new QueueInvariantError("invalid_active_capture_state");
  }
  assertUuid(value.receipt_id, "invalid_active_capture_state");
  assertUuid(value.lease_id, "invalid_active_capture_state");
  if (Number.isNaN(Date.parse(value.issued_at)) || Number.isNaN(Date.parse(value.expires_at))) {
    throw new QueueInvariantError("invalid_active_capture_state");
  }
}

function isActiveCapturePhase(value: unknown): value is ActiveCaptureState["phase"] {
  return (
    value === "ready" ||
    value === "recording" ||
    value === "paused" ||
    value === "uploading" ||
    value === "completing" ||
    value === "processing"
  );
}

function assertSessionKeyState(value: unknown): asserts value is SessionKeyBindingState {
  if (
    !isRecord(value) ||
    value.schemaVersion !== FLOW_RECORD_SCHEMA_VERSION ||
    typeof value.sessionId !== "string" ||
    typeof value.keyVersion !== "string" ||
    typeof value.wrappedDek !== "string" ||
    typeof value.idempotencyKey !== "string" ||
    (value.state !== "pending" && value.state !== "bound")
  ) {
    throw new QueueInvariantError("invalid_session_key_state");
  }
  assertUuid(value.sessionId, "invalid_session_key_state");
  assertIdempotencyKey(value.idempotencyKey);
  if (!/^[A-Za-z0-9_-]{64,1024}$/u.test(value.wrappedDek)) {
    throw new QueueInvariantError("invalid_session_key_state");
  }
}

function assertAesKey(key: CryptoKey, code: string): void {
  const algorithm = key.algorithm as AesKeyAlgorithm;
  if (
    key.type !== "secret" ||
    key.extractable ||
    algorithm.name !== "AES-GCM" ||
    algorithm.length !== 256 ||
    !key.usages.includes("encrypt") ||
    !key.usages.includes("decrypt")
  ) {
    throw new QueueInvariantError(code);
  }
}

function assertSessionDek(key: CryptoKey): void {
  const algorithm = key.algorithm as AesKeyAlgorithm;
  if (
    key.type !== "secret" ||
    key.extractable ||
    algorithm.name !== "AES-GCM" ||
    algorithm.length !== 256 ||
    key.usages.length !== 1 ||
    key.usages[0] !== "encrypt"
  ) {
    throw new QueueInvariantError("invalid_session_dek");
  }
}

function isCryptoKey(value: unknown): value is CryptoKey {
  return (
    typeof value === "object" &&
    value !== null &&
    "type" in value &&
    "extractable" in value &&
    "algorithm" in value &&
    "usages" in value &&
    Array.isArray(value.usages)
  );
}

function assertSealedRecord(value: unknown): asserts value is SealedFlowRecord {
  if (
    !isRecord(value) ||
    typeof value.key !== "string" ||
    !(value.nonce instanceof Uint8Array) ||
    value.nonce.byteLength !== NONCE_BYTES ||
    !(value.ciphertext instanceof ArrayBuffer) ||
    (value.recordRevision !== undefined &&
      (!Number.isSafeInteger(value.recordRevision) || (value.recordRevision as number) < 1)) ||
    value.ciphertext.byteLength < 16
  ) {
    throw new QueueInvariantError("invalid_flow_store_record");
  }
}

function assertIdentifier(value: string, code: string): void {
  if (!/^[A-Za-z0-9._:-]{1,255}$/u.test(value)) throw new QueueInvariantError(code);
}

function assertUuid(value: string, code: string): void {
  if (!UUID_PATTERN.test(value)) throw new QueueInvariantError(code);
}

function assertIdempotencyKey(value: string): void {
  if (!IDEMPOTENCY_PATTERN.test(value)) {
    throw new QueueInvariantError("invalid_idempotency_key");
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function sameBytes(left: ArrayBuffer | Uint8Array, right: ArrayBuffer | Uint8Array): boolean {
  const a = left instanceof ArrayBuffer ? new Uint8Array(left) : left;
  const b = right instanceof ArrayBuffer ? new Uint8Array(right) : right;
  return a.byteLength === b.byteLength && a.every((byte, index) => byte === b[index]);
}

function localAdditionalData(
  key: string,
  recordRevision?: number,
): Uint8Array<ArrayBuffer> {
  const suffix = recordRevision === undefined ? "" : `:${String(recordRevision)}`;
  return new TextEncoder().encode(`${LOCAL_AAD_PREFIX}:${key}${suffix}`);
}

function requestResult<Result>(request: IDBRequest<Result>): Promise<Result> {
  return new Promise((resolve, reject) => {
    request.addEventListener("success", () => resolve(request.result));
    request.addEventListener("error", () => reject(new QueueInvariantError("flow_database_error")));
  });
}

function transactionDone(
  transaction: IDBTransaction,
  failure?: () => Error | undefined,
): Promise<void> {
  return new Promise((resolve, reject) => {
    transaction.addEventListener("complete", () => resolve());
    transaction.addEventListener("abort", () => reject(failure?.() ?? new QueueInvariantError("flow_database_aborted")));
    transaction.addEventListener("error", () => reject(failure?.() ?? new QueueInvariantError("flow_database_error")));
  });
}
