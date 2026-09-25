/** Additive Scribe visit policy. A receipt never grants recording authority. */
import type { CaptureCapabilities, MutationOptions, RequestOptions } from "./contracts";
import { canonicalCaptureTimestamp } from "./recovery-contracts";
import { QueueInvariantError } from "../queue/errors";

export interface CaptureProfileRequest {
  schema_version: "1.0";
  profile_id: "visit-60m-v1";
  channels: ("microphone" | "system_audio" | "mixed")[];
}
export interface CaptureProfileReceipt {
  schema_version: "1.0";
  receipt_id: string;
  session_id: string;
  request: CaptureProfileRequest;
  request_sha256: string;
  created_at: string;
  maximum_aggregate_plaintext_bytes: 268435456;
  maximum_chunks: 720;
  maximum_chunks_per_channel: 360;
  maximum_track_duration_ms: 3600000;
}
export interface CaptureProfileBff {
  selectCaptureProfile(sessionId: string, request: CaptureProfileRequest, options: MutationOptions): Promise<CaptureProfileReceipt>;
  getCaptureProfile(sessionId: string, options?: RequestOptions): Promise<CaptureProfileReceipt>;
  /** Bind the validated, persisted receipt before capability/reservation calls. */
  acknowledgeCaptureProfile(receipt: CaptureProfileReceipt): Promise<void>;
}
export interface CaptureProfileSelection {
  request: CaptureProfileRequest;
  idempotencyKey: string;
  receipt: CaptureProfileReceipt | null;
}
function requireValue(condition: unknown): asserts condition {
  if (!condition) throw new QueueInvariantError("capture_profile_invalid");
}
function keys(value: unknown, names: readonly string[]): asserts value is Record<string, unknown> {
  requireValue(value !== null && typeof value === "object" && !Array.isArray(value) &&
    Object.keys(value).sort().join(",") === [...names].sort().join(","));
}
const uuid = (value: unknown): value is string => typeof value === "string" &&
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u.test(value);

export function validateProfileRequest(value: unknown): CaptureProfileRequest {
  keys(value, ["schema_version", "profile_id", "channels"]);
  requireValue(value.schema_version === "1.0" && value.profile_id === "visit-60m-v1" &&
    Array.isArray(value.channels) && value.channels.length >= 1 && value.channels.length <= 2 &&
    value.channels.every(channel => ["microphone", "system_audio", "mixed"].includes(channel)) &&
    new Set(value.channels).size === value.channels.length &&
    (!value.channels.includes("mixed") || value.channels.length === 1));
  return { schema_version: "1.0", profile_id: "visit-60m-v1", channels: [...value.channels].sort() };
}
export function canonicalProfileRequest(value: CaptureProfileRequest): string {
  const request = validateProfileRequest(value);
  return JSON.stringify({ channels: request.channels, profile_id: request.profile_id, schema_version: request.schema_version });
}
export async function profileRequestHash(value: CaptureProfileRequest, crypto = globalThis.crypto): Promise<string> {
  const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(canonicalProfileRequest(value)));
  return Array.from(new Uint8Array(hash), byte => byte.toString(16).padStart(2, "0")).join("");
}
export async function validateProfileReceipt(value: unknown, sessionId: string, now = new Date(),
  expected?: CaptureProfileRequest, crypto = globalThis.crypto): Promise<CaptureProfileReceipt> {
  value = structuredClone(value);
  const expectedRequest = expected ? canonicalProfileRequest(expected) : null;
  keys(value, ["schema_version", "receipt_id", "session_id", "request", "request_sha256", "created_at",
    "maximum_aggregate_plaintext_bytes", "maximum_chunks", "maximum_chunks_per_channel", "maximum_track_duration_ms"]);
  requireValue(value.schema_version === "1.0" && uuid(value.receipt_id) && uuid(sessionId) &&
    value.session_id === sessionId && value.maximum_aggregate_plaintext_bytes === 268435456 &&
    value.maximum_chunks === 720 && value.maximum_chunks_per_channel === 360 && value.maximum_track_duration_ms === 3600000);
  const request = validateProfileRequest(value.request);
  const created = canonicalCaptureTimestamp(value.created_at);
  requireValue(Date.parse(created) <= now.getTime() + 5000 &&
    value.request_sha256 === await profileRequestHash(request, crypto) &&
    (expectedRequest === null || expectedRequest === canonicalProfileRequest(request)));
  return { schema_version: "1.0", receipt_id: value.receipt_id, session_id: sessionId,
    request, request_sha256: value.request_sha256 as string, created_at: created,
    maximum_aggregate_plaintext_bytes: 268435456, maximum_chunks: 720,
    maximum_chunks_per_channel: 360, maximum_track_duration_ms: 3600000 };
}
export async function validateProfileSelection(value: unknown, sessionId: string, crypto = globalThis.crypto): Promise<void> {
  keys(value, ["request", "idempotencyKey", "receipt"]);
  const request = validateProfileRequest(value.request);
  requireValue(typeof value.idempotencyKey === "string" && /^[A-Za-z0-9._:-]{8,100}$/u.test(value.idempotencyKey));
  if (value.receipt !== null) await validateProfileReceipt(value.receipt, sessionId, new Date(), request, crypto);
}
export function validateProfileCapabilities(value: unknown, profile: CaptureProfileReceipt | null): CaptureCapabilities {
  keys(value, ["protocol_version", "media", "target_chunk_duration_ms", "max_envelope_bytes", "max_chunks",
    "remaining_aggregate_plaintext_bytes", "capture_lease_ttl_seconds", "reservation_window_seconds",
    "max_reservations_per_batch", "upload_concurrency"]);
  keys(value.media, ["media_type", "encoding", "channels", "sample_rate_hz"]);
  requireValue(value.protocol_version === "1.0" && value.media.media_type === "audio/wav" &&
    value.media.encoding === "pcm_s16le" && value.media.channels === 1 && value.media.sample_rate_hz === 16000 &&
    value.target_chunk_duration_ms === 10000 && value.max_envelope_bytes === 327680 &&
    value.max_chunks === (profile?.maximum_chunks ?? 1000) && value.capture_lease_ttl_seconds === 900 &&
    value.reservation_window_seconds === 900 && value.max_reservations_per_batch === 90 && value.upload_concurrency === 2 &&
    Number.isSafeInteger(value.remaining_aggregate_plaintext_bytes) && (value.remaining_aggregate_plaintext_bytes as number) >= 0 &&
    (value.remaining_aggregate_plaintext_bytes as number) <= (profile?.maximum_aggregate_plaintext_bytes ?? 67108864));
  return structuredClone(value) as unknown as CaptureCapabilities;
}
