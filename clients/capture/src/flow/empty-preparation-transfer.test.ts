import { webcrypto } from 'node:crypto';
import { IDBFactory } from 'fake-indexeddb';
import { describe, it, expect, vi } from 'vitest';
import { EncryptedIndexedDbFlowStore as LegacyStore } from './encrypted-store';
import { EncryptedIndexedDbFlowStore as ConfiguredStore } from '../configured/flow/encrypted-store';
import { createCaptureRecoveryState, beginRecoverySegment } from './recovery-state';
import { hasEmptyPreparationTransfer, transferEmptyPreparation, releaseEmptyPreparationTransfer } from './empty-preparation-transfer';
import type { ActiveCaptureState, AdmittedCapturePreparationState } from './types';
import type { CaptureRecoveryState } from '../bff/recovery-contracts';
import type { CaptureQueueStorage } from '../queue/types';
const crypto = webcrypto as unknown as Crypto;
const sessionId = '11111111-1111-4111-8111-111111111111';
async function fixture(activePresent = true) {
    const indexedDB = new IDBFactory(), source = crypto.randomUUID(), destination = crypto.randomUUID();
    const legacy = await LegacyStore.open({ databaseName: source, indexedDB, crypto });
    const preparation: AdmittedCapturePreparationState = { mode: 'core_admitted', schemaVersion: 2, reviewAfterUpload: true, sessionId,
        startedAt: '2026-09-24T12:00:00.000Z', completeIdempotencyKey: 'same-completion-key',
        leaseIdempotencyKey: 'same-lease-key', leaseRequest: { protocol_version: '1.0' } };
    const lease = { protocol_version: '1.0' as const, session_id: sessionId, lease_id: '22222222-2222-4222-8222-222222222222',
        receipt_id: '33333333-3333-4333-8333-333333333333', generation: 1,
        issued_at: preparation.startedAt, expires_at: '2026-09-24T12:15:00.000Z' };
    const active: ActiveCaptureState = { schemaVersion: 2, reviewAfterUpload: true, sessionId, lease, captureAuthorizedUntil: lease.expires_at,
        aggregatePlaintextBudgetBytes: 67108864, phase: 'ready', completeIdempotencyKey: preparation.completeIdempotencyKey,
        recordedChunks: 0, recordedPlaintextBytes: 0, startedAt: preparation.startedAt };
    await legacy.putPreparationState(preparation);
    if (activePresent)
        await legacy.putActiveCaptureState(active);
    await legacy.putCaptureRecoveryState(createCaptureRecoveryState(sessionId));
    await legacy.claimQueueStorageKind(sessionId, 'browser');
    const key = await crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, false, ['encrypt']);
    const keyState = { schemaVersion: 2 as const, sessionId, keyVersion: 'invented-key-v1', wrappedDek: 'a'.repeat(342), idempotencyKey: 'same-key-binding', state: 'bound' as const };
    await legacy.putSessionKeyCandidate(keyState, key);
    const state: CaptureRecoveryState = { session_status: 'created', lease_closed: false, current_lease: lease, history: { session_id: sessionId, recoveries: [] } };
    const queue = { listMetadata: vi.fn().mockResolvedValue([]) } as unknown as CaptureQueueStorage;
    const bff = { getCaptureRecoveryState: vi.fn().mockImplementation(async () => state), recoverCapture: vi.fn() };
    const options = { source, destination, sessionId, kind: 'browser' as const, indexedDB, crypto, queue, bff,
        now: () => new Date('2026-09-24T12:01:00Z') };
    const target = () => ConfiguredStore.open({ databaseName: destination, indexedDB, crypto });
    return { legacy, active, preparation, key, keyState, state, options, target };
}
describe('explicit empty preparation transfer', () => {
    it.each([true, false])('preserves key and exact preparation with active=%s; old readers fail closed', async (present) => {
        const f = await fixture(present);
        await transferEmptyPreparation(f.options);
        const configured = await f.target();
        expect(await configured.getPreparationState()).toEqual({ ...f.preparation, reviewAfterUpload: undefined, mode: 'configured_core' });
        expect(await configured.getActiveCaptureState()).toEqual(present ? f.active : null);
        expect(await configured.getSessionKeyState(sessionId)).toEqual(f.keyState);
        const original = f.key, copied = (await configured.getSessionKey(sessionId))!;
        const iv = new Uint8Array(12), plaintext = new TextEncoder().encode('same retained recording key');
        expect(new Uint8Array(await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, copied, plaintext))).toEqual(new Uint8Array(await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, original, plaintext)));
        await expect(f.legacy.getActiveCaptureState()).rejects.toThrow();
        await expect(f.legacy.getPreparationState()).rejects.toThrow();
        expect(await hasEmptyPreparationTransfer(f.options.source, sessionId, f.options.destination, f.options.indexedDB)).toBe(true);
        expect(f.options.bff.recoverCapture).not.toHaveBeenCalled();
        await transferEmptyPreparation(f.options);
        expect(await configured.getActiveCaptureState()).toEqual(present ? f.active : null);
        configured.close();
        f.legacy.close();
    });
    it('resumes after the fence commits and preserves the imported state after later recording', async () => {
        const f = await fixture();
        await expect(transferEmptyPreparation({ ...f.options, afterFence: async () => { throw Error('interrupted'); } })).rejects.toThrow('interrupted');
        await expect(f.legacy.getActiveCaptureState()).rejects.toThrow();
        await transferEmptyPreparation(f.options);
        const configured = await f.target();
        const later = { ...f.active, phase: 'recording' as const };
        await configured.putActiveCaptureState(later);
        await transferEmptyPreparation(f.options);
        expect(await configured.getActiveCaptureState()).toEqual(later);
        configured.close();
        f.legacy.close();
    });
    it.each(['audio', 'queue', 'segment', 'server', 'lease', 'destination', 'storage'] as const)('rejects %s before fencing the original', async (problem) => {
        const f = await fixture();
        if (problem === 'audio')
            await f.legacy.putActiveCaptureState({ ...f.active, recordedChunks: 1, recordedPlaintextBytes: 10 });
        if (problem === 'queue')
            vi.mocked(f.options.queue.listMetadata).mockResolvedValue([{ state: 'encrypted', reservation: { sessionId } }] as never);
        if (problem === 'segment')
            await f.legacy.putCaptureRecoveryState(beginRecoverySegment(createCaptureRecoveryState(sessionId), {
                segmentId: crypto.randomUUID(), recoveryGapId: crypto.randomUUID(), startedAt: f.active.startedAt,
                leaseGeneration: 1, captureAuthorizedUntil: f.active.lease.expires_at
            }));
        if (problem === 'server')
            f.state.session_status = 'capturing';
        if (problem === 'lease')
            f.state.current_lease = { ...f.active.lease, generation: 2 };
        if (problem === 'destination') {
            const target = await f.target();
            const { reviewAfterUpload: _, ...preparation } = f.preparation;
            await target.putPreparationState({ ...preparation, mode: 'configured_core' });
            target.close();
        }
        const before = await f.legacy.getActiveCaptureState();
        await expect(transferEmptyPreparation({ ...f.options, ...(problem === 'storage' ? { kind: 'native' as const } : {}) })).rejects.toThrow();
        expect(await f.legacy.getActiveCaptureState()).toEqual(before);
        expect(await hasEmptyPreparationTransfer(f.options.source, sessionId, f.options.destination, f.options.indexedDB)).toBe(false);
        f.legacy.close();
    });
    it('releases the old key and fence only after destination work has been cleared', async () => {
        const f = await fixture();
        await transferEmptyPreparation(f.options);
        await expect(releaseEmptyPreparationTransfer(f.options.source, f.options.destination, sessionId, f.options.indexedDB)).rejects.toThrow();
        const configured = await f.target();
        await configured.clearCompletedCapture(sessionId);
        await releaseEmptyPreparationTransfer(f.options.source, f.options.destination, sessionId, f.options.indexedDB);
        expect(await f.legacy.getSessionKey(sessionId)).toBeNull();
        expect(await f.legacy.getActiveCaptureState()).toBeNull();
        expect(await hasEmptyPreparationTransfer(f.options.source, sessionId, f.options.destination, f.options.indexedDB)).toBe(false);
        configured.close();
        f.legacy.close();
    });
    it('retains an uncertain reservation request with its original idempotency key', async () => {
        const f = await fixture();
        const intent = { schemaVersion: 2 as const, intentId: 'retained-reservation-intent', sessionId, idempotencyKey: 'same-reservation-key',
            createdAt: f.active.startedAt, request: { protocol_version: '1.0' as const, capture_lease_id: f.active.lease.lease_id,
                capture_lease_generation: 1, channel: 'microphone' as const, first_sequence_number: 0, count: 2 } };
        await f.legacy.putReservationIntent(intent);
        await transferEmptyPreparation(f.options);
        const configured = await f.target();
        expect(await configured.listReservationIntents()).toEqual([intent]);
        configured.close();
        f.legacy.close();
    });
});
