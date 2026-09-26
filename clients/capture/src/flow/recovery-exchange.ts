import type { CaptureBff } from "../bff/contracts";
import {
  assertCaptureRecoveryRequest, canonicalRecoveryRequest, validateRecoveryState,
  type CaptureRecoveryBff, type CaptureRecoveryRequest, type CaptureRecoveryState,
} from "../bff/recovery-contracts";
import { QueueInvariantError } from "../queue/errors";
import type { ActiveCaptureState, CaptureFlowStore, CaptureRecoveryStateV1 } from "./types";

export interface CaptureRecoveryIntent {
  readonly schemaVersion: 1;
  readonly sessionId: string;
  readonly idempotencyKey: string;
  readonly request: CaptureRecoveryRequest;
}
export function assertRecoveryIntent(value: unknown): asserts value is CaptureRecoveryIntent {
  const item = value as CaptureRecoveryIntent;
  if (typeof item !== "object" || item === null || Array.isArray(item) ||
      Object.keys(item).sort().join(",") !== "idempotencyKey,request,schemaVersion,sessionId" ||
      item.schemaVersion !== 1 || typeof item.sessionId !== "string" ||
      !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u.test(item.sessionId) ||
      typeof item.idempotencyKey !== "string" || !/^[A-Za-z0-9._:-]{8,255}$/u.test(item.idempotencyKey)) {
    throw new QueueInvariantError("capture_recovery_intent_invalid");
  }
  assertCaptureRecoveryRequest(item.request);
}
/** Caller first verifies physical source closure. This function never starts a source. */
export async function exchangeRecovery(options: {
  bff: Pick<CaptureBff, "renewLease"> & CaptureRecoveryBff; store: CaptureFlowStore;
  active: ActiveCaptureState; local: CaptureRecoveryStateV1;
  decision: CaptureRecoveryRequest["decision"]; now: () => Date; crypto: Crypto;
}): Promise<CaptureRecoveryState> {
  const { bff, store, active, local, decision, now, crypto } = options;
  if (local.finishChoice && decision !== "finish_capture") {
    throw new QueueInvariantError("capture_saved_recording_finish_only");
  }
  const gap = local.gaps.at(-1);
  const segment = local.segments.at(-1);
  if (!gap?.acknowledgement || !segment || active.sessionId !== local.sessionId ||
      gap.precedingSegmentId !== segment.segmentId ||
      !["authority_required", "ready", "stopped"].includes(local.phase)) {
    throw new QueueInvariantError("capture_recovery_state_conflict");
  }
  if (gap.acknowledgement.decision !== (decision === "finish_capture" ? "finish_capture" : "continue_with_known_gap")) {
    throw new QueueInvariantError("capture_gap_decision_conflict");
  }
  const purpose = local.finishChoice?.priorResult === "uncommitted" ? "finish" : undefined;
  let intent = await store.getCaptureRecoveryIntent(active.sessionId, gap.gapId, purpose);
  if (!intent) {
    intent = { schemaVersion: 1, sessionId: active.sessionId,
      idempotencyKey: gap.acknowledgement.idempotencyKey,
      request: { protocol_version: "1.0", capture_lease_id: active.lease.lease_id,
        capture_lease_generation: active.lease.generation, channel: "microphone",
        segment_id: segment.segmentId, segment_ordinal: segment.ordinal,
        first_sequence_number: segment.firstSequenceNumber, next_sequence_number: local.nextSequenceNumber,
        segment_started_at: segment.startedAt, gap_id: gap.gapId, reason_code: gap.reasonCode,
        observed_at: gap.observedAt, acknowledged_at: gap.acknowledgement.acknowledgedAt, decision } };
    await store.putCaptureRecoveryIntent(intent, purpose);
  }
  if (intent.request.decision !== decision) throw new QueueInvariantError("capture_gap_decision_conflict");
  const observation: CaptureRecoveryRequest = { ...intent.request,
    capture_lease_id: active.lease.lease_id, segment_id: segment.segmentId,
    segment_ordinal: segment.ordinal, first_sequence_number: segment.firstSequenceNumber,
    next_sequence_number: local.nextSequenceNumber, segment_started_at: segment.startedAt,
    gap_id: gap.gapId, reason_code: gap.reasonCode, observed_at: gap.observedAt,
    acknowledged_at: gap.acknowledgement.acknowledgedAt };
  if (canonicalRecoveryRequest(intent.request) !== canonicalRecoveryRequest(observation)) {
    throw new QueueInvariantError("capture_recovery_history_conflict");
  }
  const read = async () => validateRecoveryState(await bff.getCaptureRecoveryState(active.sessionId), active.sessionId, now(), crypto);
  let current = await read();
  assertHistoryPrefix(current, local, intent, false);
  if (!current.history.recoveries.some(item => item.request.gap_id === gap.gapId)) {
    await bff.recoverCapture(active.sessionId, intent.request, { idempotencyKey: intent.idempotencyKey });
    current = await read();
  }
  assertHistoryPrefix(current, local, intent, true);
  const lease = current.current_lease;
  if (!lease || current.lease_closed || !["created", "capturing"].includes(current.session_status)) {
    throw new QueueInvariantError("capture_recovery_closed");
  }
  if (decision === "resume_capture" && Date.parse(lease.expires_at) <= now().getTime()) {
    // The stable generation key survives a discarded reply. A later read, rather
    // than replaying an expired receipt as authority, recovers the current lease.
    await bff.renewLease(active.sessionId, lease.lease_id,
      { protocol_version: "1.0", expected_generation: lease.generation },
      { idempotencyKey: `recovery-renew:${gap.gapId}:${lease.generation}` });
    current = await read();
    assertHistoryPrefix(current, local, intent, true);
    if (!current.current_lease || current.lease_closed || !["created", "capturing"].includes(current.session_status) ||
        Date.parse(current.current_lease.expires_at) <= now().getTime()) {
      throw new QueueInvariantError("capture_authority_expired");
    }
  }
  return current;
}

export function assertHistoryPrefix(current: CaptureRecoveryState, local: CaptureRecoveryStateV1,
  intent: CaptureRecoveryIntent, requireCurrent: boolean): void {
  const records = current.history.recoveries;
  if (records.length !== local.gaps.length && (requireCurrent || records.length !== local.gaps.length - 1)) {
    throw new QueueInvariantError("capture_recovery_history_conflict");
  }
  records.forEach((receipt, index) => {
    const gap = local.gaps[index];
    const segment = local.segments[index];
    const request = receipt.request;
    if (!gap?.acknowledgement || !segment || request.gap_id !== gap.gapId ||
        request.segment_id !== gap.precedingSegmentId || request.segment_ordinal !== segment.ordinal ||
        request.first_sequence_number !== segment.firstSequenceNumber ||
        request.next_sequence_number !== (segment.lastSequenceNumber === null ? segment.firstSequenceNumber : segment.lastSequenceNumber + 1) ||
        request.reason_code !== gap.reasonCode || Date.parse(request.segment_started_at) !== Date.parse(segment.startedAt) ||
        Date.parse(request.observed_at) !== Date.parse(gap.observedAt) ||
        Date.parse(request.acknowledged_at) !== Date.parse(gap.acknowledgement.acknowledgedAt) ||
        (index < local.gaps.length - 1 && receipt.following_segment_id !== gap.followingSegmentId) ||
        (index === local.gaps.length - 1 && canonicalRecoveryRequest(request) !== canonicalRecoveryRequest(intent.request))) {
      throw new QueueInvariantError("capture_recovery_history_conflict");
    }
  });
}
