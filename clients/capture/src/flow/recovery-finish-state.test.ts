import { readFileSync } from 'node:fs';
import { describe, it, expect } from 'vitest';
import { acknowledgeRecoveryGap, assertCaptureRecoveryProgression, assertCaptureRecoveryState, beginRecoverySegment, confirmRecoverySourceClosed, createCaptureRecoveryState, observeRecoveryGap } from './recovery-state';
import { acceptLateResumeForFinish, chooseRecoveryFinish } from './recovery-finish-state';
import type { CaptureRecoveryIntent } from './recovery-exchange';
function fixture() {
    const wire = JSON.parse(readFileSync(new URL('../../../../tests/fixtures/capture_recovery.json', import.meta.url), 'utf8'));
    const request = wire.request;
    let local = createCaptureRecoveryState(wire.receipt.session_id);
    local = beginRecoverySegment(local, { segmentId: request.segment_id, recoveryGapId: request.gap_id,
        startedAt: request.segment_started_at, leaseGeneration: request.capture_lease_generation, captureAuthorizedUntil: wire.receipt.lease.expires_at });
    local = observeRecoveryGap(local, { reasonCode: request.reason_code, observedAt: request.observed_at, nextSequenceNumber: request.next_sequence_number });
    local = acknowledgeRecoveryGap(confirmRecoverySourceClosed(local), { acknowledgedAt: request.acknowledged_at, idempotencyKey: 'original-resume-key' });
    const priorIntent: CaptureRecoveryIntent = { schemaVersion: 1, sessionId: local.sessionId, idempotencyKey: 'original-resume-key', request };
    const finish = chooseRecoveryFinish(local, { priorIntent, priorResult: 'uncommitted', acknowledgedAt: request.acknowledged_at, idempotencyKey: 'later-finish-key' });
    return { local, finish, wire };
}
describe('durable later Finish choice', () => {
    it('preserves the original Resume and changes no audio/segment evidence', () => {
        const { local, finish } = fixture();
        expect(() => assertCaptureRecoveryState(finish)).not.toThrow();
        expect(() => assertCaptureRecoveryProgression(local, finish)).not.toThrow();
        expect(finish.schemaVersion).toBe(2);
        expect(finish.segments).toEqual(local.segments);
        expect(finish.finishChoice?.priorIntent.request.decision).toBe('resume_capture');
        expect(finish.gaps[0].acknowledgement?.decision).toBe('finish_capture');
    });
    it.each(['choice', 'prior_request', 'audio', 'rollback', 'new_segment'])('rejects %s mutation', kind => {
        const { finish } = fixture();
        const changed: any = structuredClone(finish);
        changed.localRevision++;
        if (kind === 'choice')
            changed.finishChoice.idempotencyKey = 'replacement-finish-key';
        if (kind === 'prior_request')
            changed.finishChoice.priorIntent.idempotencyKey = 'replacement-resume-key';
        if (kind === 'audio')
            changed.nextSequenceNumber++;
        if (kind === 'rollback') {
            changed.schemaVersion = 1;
            delete changed.finishChoice;
        }
        if (kind === 'new_segment') {
            changed.phase = 'recording';
            changed.currentSegmentId = changed.segments[0].segmentId;
        }
        expect(() => { assertCaptureRecoveryState(changed); assertCaptureRecoveryProgression(finish, changed); }).toThrow();
    });
    it('settles a late Resume receipt without changing the later Finish choice', () => {
        const { finish, wire } = fixture();
        const settled = acceptLateResumeForFinish(finish, wire.receipt.following_segment_id);
        expect(() => assertCaptureRecoveryState(settled)).not.toThrow();
        expect(() => assertCaptureRecoveryProgression(finish, settled)).not.toThrow();
        expect(settled.phase).toBe('stopped');
        expect(settled.segments).toEqual(finish.segments);
        expect(settled.finishChoice?.idempotencyKey).toBe(finish.finishChoice?.idempotencyKey);
        expect(settled.gaps[0].acknowledgement?.decision).toBe('continue_with_known_gap');
        expect(() => beginRecoverySegment(settled, { segmentId: wire.receipt.following_segment_id, recoveryGapId: crypto.randomUUID(),
            startedAt: wire.request.acknowledged_at, leaseGeneration: 2, captureAuthorizedUntil: wire.receipt.lease.expires_at })).toThrow();
    });
    it('rejects a one-microsecond mutation of a committed Resume acknowledgement', () => {
        const { finish, wire } = fixture();
        const settled = acceptLateResumeForFinish(finish, wire.receipt.following_segment_id);
        const gap = settled.gaps.at(-1)!, acknowledgement = gap.acknowledgement!;
        const changed = { ...settled, gaps: [...settled.gaps.slice(0, -1), {
            ...gap, acknowledgement: { ...acknowledgement,
                acknowledgedAt: new Date(acknowledgement.acknowledgedAt).toISOString().replace('Z', '001Z') }
        }] };
        expect(() => assertCaptureRecoveryState(changed)).toThrow();
    });
    it('rejects a Finish choice one microsecond before the preserved Resume', () => {
        const { local, finish } = fixture();
        const previous = finish.finishChoice!, gap = local.gaps.at(-1)!;
        const earlier = new Date(previous.acknowledgedAt).toISOString();
        const later = earlier.replace('Z', '001Z');
        const original = { ...local, gaps: [...local.gaps.slice(0, -1), {
            ...gap, acknowledgement: { ...gap.acknowledgement!, acknowledgedAt: later }
        }] };
        const choice = { ...previous, acknowledgedAt: earlier, priorIntent: {
            ...previous.priorIntent, request: { ...previous.priorIntent.request, acknowledged_at: later }
        } };
        expect(() => chooseRecoveryFinish(original, choice)).toThrow();
    });
});
