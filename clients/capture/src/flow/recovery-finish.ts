import { canonicalRecoveryRequest, validateRecoveryState, type CaptureRecoveryBff } from '../bff/recovery-contracts';
import { QueueInvariantError } from '../queue/errors';
import { assertHistoryPrefix, type CaptureRecoveryIntent } from './recovery-exchange';
import { chooseRecoveryFinish, acceptLateResumeForFinish } from './recovery-finish-state';
import { confirmRecoveryReceipt } from './recovery-state';
import type { ActiveCaptureState, CaptureFlowStore, CaptureRecoveryStateV1 } from './types';
/** Read an old Resume outcome without replaying it, renewing authority or starting audio. */
export async function reconcileResumeForFinish(options: {
    store: CaptureFlowStore;
    bff: CaptureRecoveryBff;
    active: ActiveCaptureState;
    local: CaptureRecoveryStateV1;
    now: () => Date;
    crypto: Crypto;
    idempotencyKey: () => string;
}): Promise<{
    active: ActiveCaptureState;
    local: CaptureRecoveryStateV1;
    finished: boolean;
}> {
    const { store, bff, now, crypto } = options;
    let { active, local } = options;
    const gap = local.gaps.at(-1), segment = local.segments.at(-1);
    if (!gap?.acknowledgement || !segment || local.nextSequenceNumber < 1)
        throw new QueueInvariantError('capture_recovery_finish_conflict');
    let intent = local.finishChoice?.priorIntent ?? await store.getCaptureRecoveryIntent(active.sessionId, gap.gapId);
    if (!intent) {
        intent = { schemaVersion: 1, sessionId: active.sessionId, idempotencyKey: gap.acknowledgement.idempotencyKey,
            request: { protocol_version: '1.0', capture_lease_id: active.lease.lease_id, capture_lease_generation: active.lease.generation,
                channel: 'microphone', segment_id: segment.segmentId, segment_ordinal: segment.ordinal,
                first_sequence_number: segment.firstSequenceNumber, next_sequence_number: local.nextSequenceNumber,
                segment_started_at: segment.startedAt, gap_id: gap.gapId, reason_code: gap.reasonCode, observed_at: gap.observedAt,
                acknowledged_at: gap.acknowledgement.acknowledgedAt, decision: 'resume_capture' } } satisfies CaptureRecoveryIntent;
        await store.putCaptureRecoveryIntent(intent);
    }
    if (intent.request.decision !== 'resume_capture')
        throw new QueueInvariantError('capture_recovery_finish_conflict');
    const current = await validateRecoveryState(await bff.getCaptureRecoveryState(active.sessionId), active.sessionId, now(), crypto);
    const observed = current.history.recoveries.find(row => row.request.gap_id === gap.gapId);
    // A Finish may already have committed after the last read. The ordinary exact
    // finish exchange validates its separate intent and recovers that receipt.
    if (local.finishChoice?.priorResult === 'uncommitted' && observed?.request.decision === 'finish_capture') {
        return { active, local, finished: false };
    }
    const originalLocal = local.finishChoice ? { ...local, gaps: [...local.gaps.slice(0, -1), { ...gap,
                acknowledgement: { decision: 'continue_with_known_gap' as const, acknowledgedAt: intent.request.acknowledged_at, idempotencyKey: intent.idempotencyKey } }] } : local;
    assertHistoryPrefix(current, originalLocal, intent, Boolean(observed));
    const lease = current.current_lease;
    if (!lease || current.lease_closed || !['created', 'capturing'].includes(current.session_status) ||
        lease.lease_id !== active.lease.lease_id || lease.generation < active.lease.generation)
        throw new QueueInvariantError('capture_recovery_closed');
    if (observed) {
        if (canonicalRecoveryRequest(observed.request) !== canonicalRecoveryRequest(intent.request))
            throw new QueueInvariantError('capture_recovery_history_conflict');
        active = await store.reconcileCaptureLease(current);
        if (local.finishChoice?.priorResult === 'uncommitted') {
            local = acceptLateResumeForFinish(local, observed.following_segment_id!);
            await store.putCaptureRecoveryState(local);
        }
        else if (!local.finishChoice) {
            local = confirmRecoveryReceipt(local, observed);
            await store.putCaptureRecoveryState(local);
            local = chooseRecoveryFinish(local, { priorIntent: intent, priorResult: 'committed', acknowledgedAt: now().toISOString(), idempotencyKey: options.idempotencyKey() });
            await store.putCaptureRecoveryState(local);
        }
        return { active, local, finished: true };
    }
    if (local.finishChoice?.priorResult === 'committed' || JSON.stringify(lease) !== JSON.stringify(active.lease)) {
        throw new QueueInvariantError('capture_recovery_history_conflict');
    }
    if (!local.finishChoice) {
        local = chooseRecoveryFinish(local, { priorIntent: intent, priorResult: 'uncommitted', acknowledgedAt: now().toISOString(), idempotencyKey: options.idempotencyKey() });
        await store.putCaptureRecoveryState(local);
    }
    return { active, local, finished: false };
}
