import { canonicalCaptureTimestamp, canonicalRecoveryRequest } from '../bff/recovery-contracts';
import { QueueInvariantError } from '../queue/errors';
import { assertRecoveryIntent } from './recovery-exchange';
import type { CaptureRecoveryFinishChoice, CaptureRecoveryStateV1 } from './types';
const invalid = () => new QueueInvariantError('capture_recovery_finish_conflict');
/** No new segment or recording authority: preserve the old Resume as evidence. */
export function chooseRecoveryFinish(state: CaptureRecoveryStateV1, choice: CaptureRecoveryFinishChoice): CaptureRecoveryStateV1 {
    assertFinishChoice(choice);
    const gap = state.gaps.at(-1);
    if (state.schemaVersion !== 1 || state.finishChoice || state.currentSegmentId !== null ||
        !gap?.acknowledgement || gap.acknowledgement.decision !== 'continue_with_known_gap' ||
        state.nextSequenceNumber < 1 || choice.idempotencyKey === gap.acknowledgement.idempotencyKey ||
        canonicalCaptureTimestamp(choice.acknowledgedAt) < canonicalCaptureTimestamp(gap.acknowledgement.acknowledgedAt) ||
        (choice.priorResult === 'committed' ? state.phase !== 'ready' || !gap.followingSegmentId
            : state.phase !== 'authority_required' || gap.followingSegmentId !== null))
        throw invalid();
    assertPriorObservation(state, choice);
    return { ...state, schemaVersion: 2, localRevision: state.localRevision + 1, finishChoice: choice,
        phase: choice.priorResult === 'committed' ? 'stopped' : 'authority_required',
        gaps: choice.priorResult === 'committed' ? state.gaps : [...state.gaps.slice(0, -1), { ...gap,
                acknowledgement: { decision: 'finish_capture', acknowledgedAt: choice.acknowledgedAt, idempotencyKey: choice.idempotencyKey } }] };
}
export function assertFinishState(state: CaptureRecoveryStateV1): void {
    if (state.schemaVersion === 1) {
        if (state.finishChoice !== undefined)
            throw invalid();
        return;
    }
    const choice = state.finishChoice;
    assertFinishChoice(choice);
    const gap = state.gaps.at(-1);
    if (!gap?.acknowledgement || state.currentSegmentId !== null || state.nextSequenceNumber < 1 ||
        (choice.priorResult === 'committed' ? state.phase !== 'stopped' || !gap.followingSegmentId || gap.acknowledgement.decision !== 'continue_with_known_gap'
            : !['authority_required', 'stopped'].includes(state.phase) || gap.followingSegmentId !== null || gap.acknowledgement.decision !== 'finish_capture'))
        throw invalid();
    const original = { decision: 'continue_with_known_gap' as const, acknowledgedAt: choice.priorIntent.request.acknowledged_at, idempotencyKey: choice.priorIntent.idempotencyKey };
    if (choice.priorResult === 'committed' && (gap.acknowledgement.idempotencyKey !== original.idempotencyKey ||
        canonicalCaptureTimestamp(gap.acknowledgement.acknowledgedAt) !== canonicalCaptureTimestamp(original.acknowledgedAt)))
        throw invalid();
    if (choice.idempotencyKey === original.idempotencyKey || canonicalCaptureTimestamp(choice.acknowledgedAt) < canonicalCaptureTimestamp(original.acknowledgedAt))
        throw invalid();
    if (choice.priorResult === 'uncommitted' && (gap.acknowledgement.idempotencyKey !== choice.idempotencyKey ||
        gap.acknowledgement.acknowledgedAt !== choice.acknowledgedAt))
        throw invalid();
    assertPriorObservation({ ...state, gaps: [...state.gaps.slice(0, -1), { ...gap, acknowledgement: original }] }, choice);
}
/** A late receipt may settle an unknown outcome; it cannot change the Finish choice. */
export function acceptLateResumeForFinish(state: CaptureRecoveryStateV1, followingSegmentId: string): CaptureRecoveryStateV1 {
    const choice = state.finishChoice, gap = state.gaps.at(-1);
    if (state.schemaVersion !== 2 || choice?.priorResult !== 'uncommitted' || state.phase !== 'authority_required' ||
        !gap || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/iu.test(followingSegmentId))
        throw invalid();
    return { ...state, localRevision: state.localRevision + 1, phase: 'stopped', finishChoice: { ...choice, priorResult: 'committed' },
        gaps: [...state.gaps.slice(0, -1), { ...gap, followingSegmentId, acknowledgement: {
                    decision: 'continue_with_known_gap', acknowledgedAt: choice.priorIntent.request.acknowledged_at,
                    idempotencyKey: choice.priorIntent.idempotencyKey
                } }] };
}
function assertFinishChoice(value: unknown): asserts value is CaptureRecoveryFinishChoice {
    if (typeof value !== 'object' || value === null || Array.isArray(value))
        throw invalid();
    const choice = value as CaptureRecoveryFinishChoice;
    if (Object.keys(choice).sort().join(',') !== 'acknowledgedAt,idempotencyKey,priorIntent,priorResult' ||
        !['committed', 'uncommitted'].includes(choice.priorResult) || typeof choice.acknowledgedAt !== 'string' ||
        typeof choice.idempotencyKey !== 'string' ||
        !/^[A-Za-z0-9._:-]{8,255}$/u.test(choice.idempotencyKey))
        throw invalid();
    assertRecoveryIntent(choice.priorIntent);
    canonicalCaptureTimestamp(choice.acknowledgedAt);
    if (choice.priorIntent.request.decision !== 'resume_capture')
        throw invalid();
}
function assertPriorObservation(state: CaptureRecoveryStateV1, choice: CaptureRecoveryFinishChoice): void {
    const { priorIntent: intent } = choice, gap = state.gaps.at(-1), segment = state.segments.at(-1);
    if (!gap?.acknowledgement || !segment || intent.sessionId !== state.sessionId ||
        intent.idempotencyKey !== gap.acknowledgement.idempotencyKey)
        throw invalid();
    const expected = { ...intent.request, segment_id: segment.segmentId, segment_ordinal: segment.ordinal,
        first_sequence_number: segment.firstSequenceNumber, next_sequence_number: state.nextSequenceNumber,
        segment_started_at: segment.startedAt, gap_id: gap.gapId, reason_code: gap.reasonCode,
        observed_at: gap.observedAt, acknowledged_at: gap.acknowledgement.acknowledgedAt };
    if (canonicalRecoveryRequest(expected) !== canonicalRecoveryRequest(intent.request))
        throw invalid();
}
