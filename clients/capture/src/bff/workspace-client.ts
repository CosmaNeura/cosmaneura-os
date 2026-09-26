import type * as Bff from "./contracts";
import { BffResponseError } from "./http-client";
import { validateRecoveryReceipt, validateRecoveryState,
  type CaptureRecoveryRequest, type CaptureRecoveryBff } from "./recovery-contracts";
import { validateCaptureSource, type CaptureQualifiedSourceBff } from "./source-contracts";
import { validateProfileRequest, validateProfileReceipt, validateProfileCapabilities,
  type CaptureProfileBff, type CaptureProfileRequest, type CaptureProfileReceipt } from "./profile-contracts";

export type WorkspaceCaptureOperation =
  | { kind: "encryption_key" | "transcription_status" | "transcript" | "capture_recovery_state" | "capture_source" | "capture_profile" | "capture_lease_state" }
  | { kind: "capabilities"; profile_receipt_id?: string }
  | { kind: "select_capture_profile"; payload: CaptureProfileRequest }
  | { kind: "recover_capture"; payload: CaptureRecoveryRequest }
  | { kind: "bind_key"; payload: Bff.SessionAudioKeyCreate }
  | { kind: "issue_lease"; payload: Bff.CaptureLeaseIssueRequest }
  | { kind: "renew_lease"; lease_id: string; payload: Bff.CaptureLeaseRenewRequest }
  | { kind: "reserve_chunks"; payload: Bff.ChunkReservationBatchRequest; profile_receipt_id?: string }
  | { kind: "authorize_upload"; object_id: string; payload: Bff.ChunkUploadAuthorizationRequest }
  | { kind: "chunk_receipt"; object_id: string }
  | { kind: "register_chunk"; payload: Bff.AudioChunkRegister }
  | { kind: "complete"; payload: Bff.CaptureCompleteRequest };

export interface WorkspaceCaptureRequest {
  session_id: string;
  idempotency_key: string;
  operation: WorkspaceCaptureOperation;
}

export type WorkspaceCaptureTransport = (request: WorkspaceCaptureRequest,
  signal?: AbortSignal) => Promise<unknown>;

/** First-party adapter. The signed server rechecks Core admission on each call. */
export class WorkspaceCaptureBff implements Bff.CaptureBff, CaptureRecoveryBff, CaptureQualifiedSourceBff, CaptureProfileBff {
  #profile: CaptureProfileReceipt | null = null;
  constructor(private readonly workspaceId: string, private readonly sessionId: string,
    private readonly transport: WorkspaceCaptureTransport) {}

  async #request<T>(operation: WorkspaceCaptureOperation,
    options: Bff.RequestOptions & { idempotencyKey?: string } = {}): Promise<T> {
    const result = await this.transport({ session_id: this.sessionId,
      idempotency_key: options.idempotencyKey ?? `read:${globalThis.crypto.randomUUID()}`, operation }, options.signal);
    if (!isRecord(result) || Object.keys(result).sort().join(",") !== "operation,receipt,session_id,workspace_id" ||
        result.workspace_id !== this.workspaceId || result.session_id !== this.sessionId ||
        result.operation !== operation.kind || !isRecord(result.receipt)) {
      throw new BffResponseError(503, "capture_receipt_invalid", null);
    }
    // The authenticated OS/Core receivers validate the closed operation-specific
    // receipt. The recorder also verifies cryptographic and queue invariants.
    return result.receipt as T;
  }

  #sameSession(sessionId: string): void {
    if (sessionId !== this.sessionId) throw new BffResponseError(409, "capture_session_changed", null);
  }

  async selectCaptureProfile(id: string, payload: CaptureProfileRequest, options: Bff.MutationOptions) {
    this.#sameSession(id);
    const request = validateProfileRequest(payload);
    return validateProfileReceipt(await this.#request({ kind: "select_capture_profile", payload: request }, options),
      id, new Date(), request);
  }
  async getCaptureProfile(id: string, options?: Bff.RequestOptions) {
    this.#sameSession(id);
    return validateProfileReceipt(await this.#request({ kind: "capture_profile" }, options), id);
  }
  async acknowledgeCaptureProfile(receipt: CaptureProfileReceipt): Promise<void> {
    const selected = await validateProfileReceipt(receipt, this.sessionId);
    if (this.#profile && JSON.stringify(this.#profile) !== JSON.stringify(selected)) {
      throw new BffResponseError(409, "capture_profile_changed", null);
    }
    this.#profile = selected;
  }

  getAudioEncryptionKey(options?: Bff.RequestOptions) {
    return this.#request<Bff.AudioEncryptionPublicKey>({ kind: "encryption_key" }, options);
  }
  async getCaptureLeaseState(id: string, options?: Bff.RequestOptions): Promise<Bff.CaptureLeaseState> {
    this.#sameSession(id);
    const result = await this.#request<Bff.CaptureLeaseState>({kind:"capture_lease_state"}, options);
    if (result.session_id !== id || Object.keys(result).sort().join(",") !== "current_lease,lease_closed,session_id,session_status"
      || typeof result.lease_closed !== "boolean"
      || !["created","capturing","uploaded","processing","transcript_ready","handed_off","failed"].includes(result.session_status)
      || result.current_lease !== null && result.current_lease.session_id !== id) {
      throw new BffResponseError(503,"capture_receipt_invalid",null);
    }
    return result;
  }
  async recoverCapture(id: string, payload: CaptureRecoveryRequest, options: Bff.MutationOptions) {
    this.#sameSession(id);
    return validateRecoveryReceipt(await this.#request({ kind: "recover_capture", payload }, options),
      id, new Date(), payload);
  }
  async getCaptureRecoveryState(id: string, options?: Bff.RequestOptions) {
    this.#sameSession(id);
    return validateRecoveryState(await this.#request({ kind: "capture_recovery_state" }, options), id, new Date());
  }
  async getCaptureSource(id: string, options?: Bff.RequestOptions) {
    this.#sameSession(id);
    return validateCaptureSource(await this.#request({ kind: "capture_source" }, options), id);
  }
  async createConsent(_request: Bff.ConsentCreate, _options: Bff.MutationOptions): Promise<Bff.ConsentRecord> {
    throw new BffResponseError(409, "capture_admission_owned_by_core", null);
  }
  async createSession(_request: Bff.SessionCreate, _options: Bff.MutationOptions): Promise<Bff.CaptureSession> {
    throw new BffResponseError(409, "capture_admission_owned_by_core", null);
  }
  bindSessionAudioKey(id: string, payload: Bff.SessionAudioKeyCreate, options: Bff.MutationOptions) {
    this.#sameSession(id);
    return this.#request<Bff.SessionAudioKeyReceipt>({ kind: "bind_key", payload }, options);
  }
  async getCapabilities(id: string, options?: Bff.RequestOptions) {
    this.#sameSession(id);
    const profile = this.#profile;
    return validateProfileCapabilities(await this.#request({ kind: "capabilities",
      ...(profile ? { profile_receipt_id: profile.receipt_id } : {}) }, options), profile);
  }
  issueLease(id: string, payload: Bff.CaptureLeaseIssueRequest, options: Bff.MutationOptions) {
    this.#sameSession(id);
    return this.#request<Bff.CaptureLeaseReceipt>({ kind: "issue_lease", payload }, options);
  }
  renewLease(id: string, leaseId: string, payload: Bff.CaptureLeaseRenewRequest, options: Bff.MutationOptions) {
    this.#sameSession(id);
    return this.#request<Bff.CaptureLeaseReceipt>({ kind: "renew_lease", lease_id: leaseId, payload }, options);
  }
  reserveChunks(id: string, payload: Bff.ChunkReservationBatchRequest, options: Bff.MutationOptions) {
    this.#sameSession(id);
    if (this.#profile && (!this.#profile.request.channels.includes(payload.channel) ||
        payload.first_sequence_number + payload.count > this.#profile.maximum_chunks_per_channel)) {
      throw new BffResponseError(409, "capture_profile_changed", null);
    }
    return this.#request<Bff.ChunkReservationBatchReceipt>({ kind: "reserve_chunks", payload,
      ...(this.#profile ? { profile_receipt_id: this.#profile.receipt_id } : {}) }, options);
  }
  authorizeUpload(id: string, objectId: string, payload: Bff.ChunkUploadAuthorizationRequest, options: Bff.MutationOptions) {
    this.#sameSession(id);
    return this.#request<Bff.ChunkUploadAuthorization>({ kind: "authorize_upload", object_id: objectId, payload }, options);
  }
  getChunkReceipt(id: string, objectId: string, options?: Bff.RequestOptions) {
    this.#sameSession(id);
    return this.#request<Bff.ChunkReceipt>({ kind: "chunk_receipt", object_id: objectId }, options);
  }
  registerChunk(id: string, payload: Bff.AudioChunkRegister, options: Bff.MutationOptions) {
    this.#sameSession(id);
    return this.#request<Bff.AudioChunk>({ kind: "register_chunk", payload }, options);
  }
  completeCapture(id: string, payload: Bff.CaptureCompleteRequest, options: Bff.MutationOptions) {
    this.#sameSession(id);
    return this.#request<Bff.CaptureSession>({ kind: "complete", payload }, options);
  }
  async getTranscriptionStatus(id: string, options?: Bff.RequestOptions): Promise<Bff.CaptureTranscriptionStatus> {
    this.#sameSession(id);
    const result = await this.#request<Bff.CaptureTranscriptionStatus>({ kind: "transcription_status" }, options);
    if (result.session_id !== this.sessionId ||
        !["not_requested", "queued", "processing", "completed", "terminal"].includes(result.status) ||
        result.transcript_available !== (result.status === "completed")) {
      throw new BffResponseError(503, "capture_receipt_invalid", null);
    }
    return result;
  }
  async getTranscript(id: string, options?: Bff.RequestOptions): Promise<Bff.Transcript> {
    this.#sameSession(id);
    const result = await this.#request<Bff.Transcript>({ kind: "transcript" }, options);
    if (result.session_id !== this.sessionId || !Array.isArray(result.segments) || !result.segments.length) {
      throw new BffResponseError(503, "capture_receipt_invalid", null);
    }
    return result;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
