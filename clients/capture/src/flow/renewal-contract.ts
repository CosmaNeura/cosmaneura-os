import { base64UrlDecode } from "@cosmaneura-scribe/capture-protocol";
import type { CaptureLeaseReceipt, ChunkReservationBatchReceipt } from "../bff/contracts";
import { canonicalCaptureTimestamp } from "../bff/recovery-contracts";
import { QueueInvariantError } from "../queue/errors";
import type { ActiveCaptureState } from "./types";

/** Immutable intent for extending one uninterrupted microphone run. */
export interface CaptureRenewalIntent {
  schemaVersion: 1;
  sessionId: string;
  profileReceiptId: string;
  segmentId: string;
  segmentOrdinal: number;
  priorLease: CaptureLeaseReceipt;
  priorCaptureAuthorizedUntil: string;
  firstSequenceNumber: number;
  count: number;
  leaseIdempotencyKey: string;
  reservationIdempotencyKey: string;
  createdAt: string;
}
export interface CaptureRenewalRecord {
  intent: CaptureRenewalIntent;
  lease: CaptureLeaseReceipt | null;
  reservations: ChunkReservationBatchReceipt | null;
}
export interface CaptureRenewalStore {
  putCaptureRenewal(record: CaptureRenewalRecord): Promise<void>;
  getCaptureRenewal(sessionId: string, leaseId: string, priorGeneration: number): Promise<CaptureRenewalRecord | null>;
  /** Non-continuous reconciliation changes lease metadata only; it cannot restart capture. */
  applyCaptureRenewal(intent: CaptureRenewalIntent, mode: "continuous" | "interrupted" | "stopped", now: Date): Promise<ActiveCaptureState>;
}
export function requireRenewal(condition: unknown): asserts condition {
  if (!condition) throw new QueueInvariantError("capture_renewal_conflict");
}
function keys(value: unknown, names: string[]): asserts value is Record<string, unknown> {
  requireRenewal(value !== null && typeof value === "object" && !Array.isArray(value) &&
    Object.keys(value).sort().join(",") === names.sort().join(","));
}
export const renewalUuid = (value: unknown): value is string => typeof value === "string" &&
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u.test(value);
function integer(value: unknown, min: number, max: number): value is number {
  return Number.isSafeInteger(value) && (value as number) >= min && (value as number) <= max;
}
function operationKey(value: unknown): value is string {
  return typeof value === "string" && /^[A-Za-z0-9._:-]{8,100}$/u.test(value);
}
export function normalizedLease(value: unknown, sessionId: string): CaptureLeaseReceipt {
  keys(value, ["protocol_version", "receipt_id", "lease_id", "session_id", "generation", "issued_at", "expires_at"]);
  requireRenewal(value.protocol_version === "1.0" && value.session_id === sessionId && renewalUuid(sessionId) &&
    renewalUuid(value.receipt_id) && renewalUuid(value.lease_id) && integer(value.generation, 1, Number.MAX_SAFE_INTEGER - 1));
  const issued = canonicalCaptureTimestamp(value.issued_at), expires = canonicalCaptureTimestamp(value.expires_at);
  requireRenewal(Date.parse(expires) > Date.parse(issued) && Date.parse(expires) - Date.parse(issued) <= 900_000);
  return { protocol_version: "1.0", receipt_id: value.receipt_id, lease_id: value.lease_id,
    session_id: sessionId, generation: value.generation, issued_at: issued, expires_at: expires };
}
export function validateRenewalIntent(value: unknown): CaptureRenewalIntent {
  keys(value, ["schemaVersion", "sessionId", "profileReceiptId", "segmentId", "segmentOrdinal", "priorLease",
    "priorCaptureAuthorizedUntil", "firstSequenceNumber", "count", "leaseIdempotencyKey", "reservationIdempotencyKey", "createdAt"]);
  requireRenewal(value.schemaVersion === 1 && renewalUuid(value.sessionId) && renewalUuid(value.profileReceiptId) &&
    renewalUuid(value.segmentId) && integer(value.segmentOrdinal, 0, 999) && integer(value.firstSequenceNumber, 1, 359) &&
    integer(value.count, 1, 90) && value.firstSequenceNumber + value.count <= 360 && operationKey(value.leaseIdempotencyKey) &&
    operationKey(value.reservationIdempotencyKey) && value.leaseIdempotencyKey !== value.reservationIdempotencyKey);
  const priorLease = normalizedLease(value.priorLease, value.sessionId);
  const until = canonicalCaptureTimestamp(value.priorCaptureAuthorizedUntil), created = canonicalCaptureTimestamp(value.createdAt);
  requireRenewal(Date.parse(created) >= Date.parse(priorLease.issued_at) && Date.parse(created) < Date.parse(until) &&
    Date.parse(until) <= Date.parse(priorLease.expires_at));
  return { schemaVersion: 1, sessionId: value.sessionId, profileReceiptId: value.profileReceiptId,
    segmentId: value.segmentId, segmentOrdinal: value.segmentOrdinal, priorLease, priorCaptureAuthorizedUntil: until,
    firstSequenceNumber: value.firstSequenceNumber, count: value.count, leaseIdempotencyKey: value.leaseIdempotencyKey,
    reservationIdempotencyKey: value.reservationIdempotencyKey, createdAt: created };
}
export function sameRenewalIntent(left: CaptureRenewalIntent, right: CaptureRenewalIntent): boolean {
  return JSON.stringify(validateRenewalIntent(left)) === JSON.stringify(validateRenewalIntent(right));
}
export function validateRenewedLease(value: unknown, intent: CaptureRenewalIntent, now: Date): CaptureLeaseReceipt {
  const lease = normalizedLease(value, intent.sessionId);
  requireRenewal(lease.lease_id === intent.priorLease.lease_id && lease.generation === intent.priorLease.generation + 1 &&
    lease.receipt_id !== intent.priorLease.receipt_id && Date.parse(lease.issued_at) >= Date.parse(intent.priorLease.issued_at) &&
    Date.parse(lease.issued_at) >= Date.parse(intent.createdAt) - 5000 && Date.parse(lease.issued_at) <= now.getTime() + 5000 &&
    Date.parse(lease.expires_at) > Date.parse(intent.priorLease.expires_at));
  return lease;
}
function normalizedReservations(value: unknown, intent: CaptureRenewalIntent, lease: CaptureLeaseReceipt, now: Date,
  channel: "microphone" | "mixed" | "system_audio"): ChunkReservationBatchReceipt {
  keys(value, ["protocol_version", "batch_id", "session_id", "capture_authorized_until", "reservations"]);
  requireRenewal(value.protocol_version === "1.0" && renewalUuid(value.batch_id) && value.session_id === intent.sessionId &&
    Array.isArray(value.reservations) && value.reservations.length === intent.count &&
    canonicalCaptureTimestamp(value.capture_authorized_until) === lease.expires_at);
  const objects = new Set<string>(); let tenant: string | null = null;
  const reservations = value.reservations.map((raw, offset) => {
    keys(raw, ["protocol_version", "object_id", "session_id", "channel", "sequence_number", "additional_authenticated_data", "created_at"]);
    requireRenewal(raw.protocol_version === "1.0" && renewalUuid(raw.object_id) && !objects.has(raw.object_id) &&
      raw.session_id === intent.sessionId && raw.channel === channel && raw.sequence_number === intent.firstSequenceNumber + offset &&
      typeof raw.additional_authenticated_data === "string" && /^[A-Za-z0-9_-]{1,1024}$/u.test(raw.additional_authenticated_data));
    const aad = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(base64UrlDecode(raw.additional_authenticated_data)));
    keys(aad, ["tenant_id", "session_id", "object_id", "sequence_number", "channel"]);
    requireRenewal(renewalUuid(aad.tenant_id) && (tenant === null || tenant === aad.tenant_id) && aad.session_id === intent.sessionId &&
      aad.object_id === raw.object_id && aad.sequence_number === raw.sequence_number && aad.channel === raw.channel);
    tenant = aad.tenant_id; objects.add(raw.object_id);
    const created = canonicalCaptureTimestamp(raw.created_at);
    // Scribe preserves the creation time of a previously reserved object when
    // an unused future window is acknowledged under a renewed lease. The batch
    // deadline, not object creation time, binds this window to current authority.
    requireRenewal(Date.parse(created) <= now.getTime() + 5000 &&
      Date.parse(created) < Date.parse(lease.expires_at));
    return { protocol_version: "1.0" as const, object_id: raw.object_id, session_id: intent.sessionId, channel,
      sequence_number: intent.firstSequenceNumber + offset, additional_authenticated_data: raw.additional_authenticated_data, created_at: created };
  });
  return { protocol_version: "1.0", batch_id: value.batch_id, session_id: intent.sessionId,
    capture_authorized_until: lease.expires_at, reservations };
}
export function validateRenewalRecord(value: unknown, now = new Date(),
  channel: "microphone" | "mixed" | "system_audio" = "microphone"): CaptureRenewalRecord {
  try {
    keys(value, ["intent", "lease", "reservations"]);
    const intent = validateRenewalIntent(value.intent);
    requireRenewal(Date.parse(intent.createdAt) <= now.getTime() + 5000);
    const lease = value.lease === null ? null : validateRenewedLease(value.lease, intent, now);
    requireRenewal(value.reservations === null || lease !== null);
    return { intent, lease, reservations: value.reservations === null ? null : normalizedReservations(value.reservations, intent, lease!, now, channel) };
  } catch { throw new QueueInvariantError("capture_renewal_conflict"); }
}
