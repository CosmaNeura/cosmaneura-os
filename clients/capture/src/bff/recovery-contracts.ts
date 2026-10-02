/** Closed Scribe recovery projection. Historical receipts never grant capture. */
import { MAX_CHUNKS } from "@cosmaneura-scribe/capture-protocol";
import type { CaptureLeaseReceipt, MutationOptions, RequestOptions } from "./contracts";
import type { CaptureGapReasonCode } from "../flow/types";
import { QueueInvariantError } from "../queue/errors";

export interface CaptureRecoveryRequest {
  protocol_version: "1.0";
  capture_lease_id: string;
  capture_lease_generation: number;
  channel: "microphone";
  segment_id: string;
  segment_ordinal: number;
  first_sequence_number: number;
  next_sequence_number: number;
  segment_started_at: string;
  gap_id: string;
  reason_code: CaptureGapReasonCode;
  observed_at: string;
  acknowledged_at: string;
  decision: "resume_capture" | "finish_capture";
}
export interface CaptureRecoveryReceipt {
  receipt_id: string;
  session_id: string;
  request: CaptureRecoveryRequest;
  request_sha256: string;
  acknowledged_by_practitioner_id: string;
  following_segment_id: string | null;
  lease: CaptureLeaseReceipt;
  review_state: "required";
}
export interface CaptureRecoveryHistory {
  session_id: string;
  recoveries: CaptureRecoveryReceipt[];
}
export interface CaptureRecoveryState {
  history: CaptureRecoveryHistory;
  current_lease: CaptureLeaseReceipt | null;
  lease_closed: boolean;
  session_status: "created" | "capturing" | "uploaded" | "processing" | "transcript_ready" | "handed_off" | "failed";
}
export interface CaptureRecoveryBff {
  recoverCapture(sessionId: string, request: CaptureRecoveryRequest, options: MutationOptions): Promise<CaptureRecoveryReceipt>;
  getCaptureRecoveryState(sessionId: string, options?: RequestOptions): Promise<CaptureRecoveryState>;
}

const reasons = new Set(["audio_context_suspended", "audio_device_disconnected", "audio_route_changed",
  "audio_session_interrupted", "capture_backgrounded", "capture_source_stalled", "capture_source_failed",
  "capture_authority_expired", "process_recovery_unknown"]);
const requestKeys = ["protocol_version", "capture_lease_id", "capture_lease_generation", "channel",
  "segment_id", "segment_ordinal", "first_sequence_number", "next_sequence_number", "segment_started_at",
  "gap_id", "reason_code", "observed_at", "acknowledged_at", "decision"];
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u;
function requireValue(condition: unknown): asserts condition {
  if (!condition) throw new QueueInvariantError("capture_recovery_receipt_invalid");
}
function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
function keys(value: unknown, names: readonly string[]): asserts value is Record<string, unknown> {
  requireValue(record(value) && Object.keys(value).sort().join(",") === [...names].sort().join(","));
}
function uuid(value: unknown): value is string { return typeof value === "string" && UUID.test(value); }
function integer(value: unknown, min: number, max = Number.MAX_SAFE_INTEGER): value is number {
  return Number.isSafeInteger(value) && (value as number) >= min && (value as number) <= max;
}
/** Scribe canonical hashes normalize UTC timestamps to exactly six fractional digits. */
export function canonicalCaptureTimestamp(value: unknown): string {
  requireValue(typeof value === "string");
  const match = /^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d{1,6}))?(Z|[+-]\d\d:\d\d)$/u.exec(value);
  requireValue(match && Number.isFinite(Date.parse(value)));
  requireValue(new Date(`${match[1]}Z`).toISOString().slice(0, 19) === match[1]);
  const second = new Date(`${match[1]}${match[3]}`).toISOString().slice(0, 19);
  return `${second}.${(match[2] ?? "").padEnd(6, "0")}Z`;
}
const timestamp = canonicalCaptureTimestamp;
export function assertCaptureRecoveryRequest(value: unknown): asserts value is CaptureRecoveryRequest {
  keys(value, requestKeys);
  requireValue(value.protocol_version === "1.0" && value.channel === "microphone" &&
    uuid(value.capture_lease_id) && integer(value.capture_lease_generation, 1) &&
    uuid(value.segment_id) && uuid(value.gap_id) && value.segment_id !== value.gap_id &&
    integer(value.segment_ordinal, 0, 999) && integer(value.first_sequence_number, 0, MAX_CHUNKS - 1) &&
    integer(value.next_sequence_number, value.first_sequence_number, MAX_CHUNKS) &&
    typeof value.reason_code === "string" && reasons.has(value.reason_code) &&
    (value.decision === "resume_capture" || value.decision === "finish_capture") &&
    (value.decision !== "resume_capture" || value.next_sequence_number < MAX_CHUNKS) &&
    (value.decision !== "finish_capture" || value.next_sequence_number > 0));
  requireValue(timestamp(value.segment_started_at) <= timestamp(value.observed_at) &&
    timestamp(value.observed_at) <= timestamp(value.acknowledged_at));
}
export function canonicalRecoveryRequest(value: CaptureRecoveryRequest): string {
  assertCaptureRecoveryRequest(value);
  const normalized = { ...value, segment_started_at: timestamp(value.segment_started_at),
    observed_at: timestamp(value.observed_at), acknowledged_at: timestamp(value.acknowledged_at) };
  return JSON.stringify(Object.fromEntries(Object.entries(normalized).sort(([a], [b]) => a.localeCompare(b))));
}
export async function recoveryRequestHash(value: CaptureRecoveryRequest, crypto = globalThis.crypto): Promise<string> {
  const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(canonicalRecoveryRequest(value)));
  return Array.from(new Uint8Array(hash), byte => byte.toString(16).padStart(2, "0")).join("");
}
function lease(value: unknown, sessionId: string, now: Date): asserts value is CaptureLeaseReceipt {
  keys(value, ["protocol_version", "receipt_id", "lease_id", "session_id", "generation", "issued_at", "expires_at"]);
  requireValue(value.protocol_version === "1.0" && uuid(value.receipt_id) && uuid(value.lease_id) &&
    value.session_id === sessionId && integer(value.generation, 1));
  timestamp(value.issued_at); timestamp(value.expires_at);
  const issued = Date.parse(value.issued_at as string), expires = Date.parse(value.expires_at as string);
  requireValue(expires > issued && expires - issued <= 900_000 && issued <= now.getTime() + 5000);
}
export async function validateRecoveryReceipt(value: unknown, sessionId: string, now: Date,
  expected?: CaptureRecoveryRequest, crypto = globalThis.crypto): Promise<CaptureRecoveryReceipt> {
  keys(value, ["receipt_id", "session_id", "request", "request_sha256", "acknowledged_by_practitioner_id",
    "following_segment_id", "lease", "review_state"]);
  requireValue(uuid(value.receipt_id) && value.session_id === sessionId && value.review_state === "required" &&
    typeof value.acknowledged_by_practitioner_id === "string" && value.acknowledged_by_practitioner_id.length > 0 &&
    value.acknowledged_by_practitioner_id.length <= 128);
  assertCaptureRecoveryRequest(value.request);
  lease(value.lease, sessionId, now);
  const request = value.request;
  requireValue(value.request_sha256 === await recoveryRequestHash(request, crypto) &&
    (!expected || canonicalRecoveryRequest(request) === canonicalRecoveryRequest(expected)) &&
    value.lease.lease_id === request.capture_lease_id && value.lease.generation === request.capture_lease_generation + 1 &&
    (request.decision === "resume_capture" ? uuid(value.following_segment_id) : value.following_segment_id === null) &&
    value.following_segment_id !== request.segment_id && value.following_segment_id !== request.gap_id);
  return value as unknown as CaptureRecoveryReceipt;
}
export async function validateRecoveryHistory(value: unknown, sessionId: string, now: Date,
  crypto = globalThis.crypto): Promise<CaptureRecoveryHistory> {
  keys(value, ["session_id", "recoveries"]);
  requireValue(value.session_id === sessionId && Array.isArray(value.recoveries) && value.recoveries.length <= 1000);
  let previous: CaptureRecoveryReceipt | undefined;
  const receipts = new Set<string>(), segments = new Set<string>(), gaps = new Set<string>();
  for (const raw of value.recoveries) {
    const item = await validateRecoveryReceipt(raw, sessionId, now, undefined, crypto);
    const command = item.request;
    requireValue(!receipts.has(item.receipt_id) &&
      !segments.has(command.segment_id) && !gaps.has(command.segment_id) &&
      !gaps.has(command.gap_id) && !segments.has(command.gap_id) &&
      (item.following_segment_id === null || !segments.has(item.following_segment_id) && !gaps.has(item.following_segment_id)));
    if (!previous) requireValue(command.segment_ordinal === 0 && command.first_sequence_number === 0);
    else requireValue(command.segment_id === previous.following_segment_id &&
      command.segment_ordinal === previous.request.segment_ordinal + 1 &&
      command.first_sequence_number === previous.request.next_sequence_number &&
      command.capture_lease_id === previous.lease.lease_id && command.capture_lease_generation >= previous.lease.generation &&
      timestamp(command.segment_started_at) >= timestamp(previous.request.acknowledged_at) &&
      item.acknowledged_by_practitioner_id === previous.acknowledged_by_practitioner_id);
    receipts.add(item.receipt_id); segments.add(command.segment_id); gaps.add(command.gap_id); previous = item;
  }
  return value as unknown as CaptureRecoveryHistory;
}
export async function validateRecoveryState(value: unknown, sessionId: string, now: Date,
  crypto = globalThis.crypto): Promise<CaptureRecoveryState> {
  keys(value, ["history", "current_lease", "lease_closed", "session_status"]);
  const history = await validateRecoveryHistory(value.history, sessionId, now, crypto);
  requireValue(typeof value.lease_closed === "boolean" &&
    ["created", "capturing", "uploaded", "processing", "transcript_ready", "handed_off", "failed"].includes(value.session_status as string));
  if (value.current_lease === null) requireValue(history.recoveries.length === 0 && !value.lease_closed);
  else {
    lease(value.current_lease, sessionId, now);
    const current = value.current_lease;
    requireValue(history.recoveries.every(item => item.lease.lease_id === current.lease_id &&
      item.lease.generation <= current.generation));
  }
  return value as unknown as CaptureRecoveryState;
}
