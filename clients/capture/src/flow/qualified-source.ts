import { canonicalCaptureTimestamp as timestamp, canonicalRecoveryRequest } from "../bff/recovery-contracts";
import type { CaptureSourceEnvelope } from "../bff/source-contracts";
import { QueueInvariantError } from "../queue/errors";
import type { ActiveCaptureState, CaptureFlowStore, CaptureRecoveryStateV1 } from "./types";

/** Compare against retained decisions before deleting completed capture state. */
export async function assertRetainedSource(source: CaptureSourceEnvelope, active: ActiveCaptureState,
  local: CaptureRecoveryStateV1 | null, store: CaptureFlowStore): Promise<void> {
  const fail = () => { throw new QueueInvariantError("capture_recovery_history_conflict"); };
  const rows = source.recovery_history.recoveries;
  if (source.session_id !== active.sessionId || rows.length !== (local?.gaps.length ?? 0)) fail();
  if (!local) return;
  if (local.sessionId !== active.sessionId || local.phase !== "stopped" ||
      local.nextSequenceNumber !== active.recordedChunks) fail();
  for (let index = 0; index < rows.length; index++) {
    const receipt = rows[index], gap = local.gaps[index], segment = local.segments[index];
    const acknowledgment = gap?.acknowledgement;
    if (!acknowledgment || !segment) { fail(); return; }
    const intent = await store.getCaptureRecoveryIntent(active.sessionId, gap.gapId);
    if (!intent || intent.sessionId !== active.sessionId || intent.idempotencyKey !== acknowledgment.idempotencyKey ||
        canonicalRecoveryRequest(intent.request) !== canonicalRecoveryRequest(receipt.request)) { fail(); return; }
    const request = receipt.request;
    if (request.capture_lease_id !== active.lease.lease_id || receipt.lease.generation > active.lease.generation ||
        request.gap_id !== gap.gapId || request.segment_id !== gap.precedingSegmentId ||
        request.segment_id !== segment.segmentId || request.segment_ordinal !== segment.ordinal ||
        request.first_sequence_number !== segment.firstSequenceNumber ||
        request.next_sequence_number !== (segment.lastSequenceNumber === null ? segment.firstSequenceNumber : segment.lastSequenceNumber + 1) ||
        request.reason_code !== gap.reasonCode || timestamp(request.segment_started_at) !== timestamp(segment.startedAt) ||
        timestamp(request.observed_at) !== timestamp(gap.observedAt) ||
        timestamp(request.acknowledged_at) !== timestamp(acknowledgment.acknowledgedAt) ||
        request.decision !== (acknowledgment.decision === "finish_capture" ? "finish_capture" : "resume_capture") ||
        receipt.following_segment_id !== gap.followingSegmentId || gap.reviewState !== "required") fail();
  }
}
