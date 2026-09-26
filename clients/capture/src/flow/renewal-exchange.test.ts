import { webcrypto } from "node:crypto";
import { readFileSync } from "node:fs";
import { IDBFactory } from "fake-indexeddb";
import { afterEach, describe, expect, it, vi } from "vitest";
import { base64UrlEncode } from "@cosmaneura-scribe/capture-protocol";
import type { CaptureLeaseReceipt, ChunkReservationBatchReceipt } from "../bff/contracts";
import type { CaptureProfileReceipt } from "../bff/profile-contracts";
import type { CaptureRecoveryState } from "../bff/recovery-contracts";
import { EncryptedIndexedDbFlowStore } from "./encrypted-store";
import { beginRecoverySegment, confirmRecoverySourceClosed, createCaptureRecoveryState, observeRecoveryGap, stopRecoverySegment } from "./recovery-state";
import { validateRenewalIntent, validateRenewalRecord, type CaptureRenewalRecord } from "./renewal-contract";
import { exchangeCaptureRenewal, reconcileInterruptedRenewal, reconcileStoppedRenewal } from "./renewal-exchange";
import type { ActiveCaptureState } from "./types";

const crypto = webcrypto as unknown as Crypto;
const golden: CaptureProfileReceipt = JSON.parse(readFileSync(new URL("../../../../tests/fixtures/capture_profile.json", import.meta.url), "utf8"));
const cleanup: (() => void)[] = [];
afterEach(() => { vi.restoreAllMocks(); cleanup.splice(0).forEach(close => close()); });

// Metadata-only fixture: no audio source, microphone, token or service is used.
async function setup() {
  let now = new Date();
  const indexedDB = new IDBFactory(), databaseName = crypto.randomUUID();
  const open = async () => {
    const store = await EncryptedIndexedDbFlowStore.open({ indexedDB, databaseName, crypto });
    cleanup.push(() => store.close()); return store;
  };
  let store = await open();
  const sessionId = golden.session_id, profile = structuredClone(golden);
  const lease: CaptureLeaseReceipt = { protocol_version: "1.0", session_id: sessionId,
    receipt_id: crypto.randomUUID(), lease_id: crypto.randomUUID(), generation: 1,
    issued_at: new Date(now.getTime() - 600_000).toISOString(), expires_at: new Date(now.getTime() + 300_000).toISOString() };
  await store.putPreparationState({ schemaVersion: 2, mode: "core_admitted", sessionId,
    startedAt: lease.issued_at, completeIdempotencyKey: "synthetic-complete-key",
    leaseRequest: null, leaseIdempotencyKey: null,
    profileSelection: { request: profile.request, receipt: profile, idempotencyKey: "synthetic-profile-key" } });
  const active: ActiveCaptureState = { schemaVersion: 2, sessionId, lease, captureProfile: profile,
    captureAuthorizedUntil: lease.expires_at, aggregatePlaintextBudgetBytes: 268435456,
    phase: "recording", completeIdempotencyKey: "synthetic-complete-key", recordedChunks: 70,
    recordedPlaintextBytes: 22403080, startedAt: lease.issued_at };
  await store.putActiveCaptureState(active);
  let local = createCaptureRecoveryState(sessionId);
  await store.putCaptureRecoveryState(local);
  local = beginRecoverySegment(local, { segmentId: crypto.randomUUID(), recoveryGapId: crypto.randomUUID(),
    startedAt: lease.issued_at, leaseGeneration: 1, captureAuthorizedUntil: lease.expires_at });
  await store.putCaptureRecoveryState(local);
  const intent = validateRenewalIntent({ schemaVersion: 1, sessionId, profileReceiptId: profile.receipt_id,
    segmentId: local.currentSegmentId!, segmentOrdinal: 0, priorLease: lease,
    priorCaptureAuthorizedUntil: lease.expires_at, firstSequenceNumber: 90, count: 90,
    leaseIdempotencyKey: "synthetic-renew-key", reservationIdempotencyKey: "synthetic-reserve-key", createdAt: now.toISOString() });
  const nextLease: CaptureLeaseReceipt = { ...lease, generation: 2, receipt_id: crypto.randomUUID(),
    issued_at: now.toISOString(), expires_at: new Date(now.getTime() + 900_000).toISOString() };
  const tenant = crypto.randomUUID();
  const batch: ChunkReservationBatchReceipt = { protocol_version: "1.0", session_id: sessionId,
    batch_id: crypto.randomUUID(), capture_authorized_until: nextLease.expires_at,
    reservations: Array.from({ length: 90 }, (_, offset) => {
      const object_id = crypto.randomUUID(), sequence_number = 90 + offset;
      return { protocol_version: "1.0", session_id: sessionId, object_id, sequence_number, channel: "microphone",
        created_at: nextLease.issued_at, additional_authenticated_data: base64UrlEncode(new TextEncoder().encode(JSON.stringify({
          tenant_id: tenant, session_id: sessionId, object_id, sequence_number, channel: "microphone" }))) };
    }) };
  const complete = validateRenewalRecord({ intent, lease: nextLease, reservations: batch }, now);
  const remote: CaptureRecoveryState = { current_lease: lease, lease_closed: false, session_status: "capturing",
    history: { session_id: sessionId, recoveries: [] } };
  let continuous = true;
  const saved = () => store.getCaptureRenewal(sessionId, lease.lease_id, 1);
  const renew = vi.fn(async (..._args: unknown[]) => {
    expect(await saved()).toMatchObject({ intent, lease: null, reservations: null });
    remote.current_lease = nextLease; return structuredClone(nextLease);
  });
  const reserve = vi.fn(async (..._args: unknown[]) => {
    expect(await saved()).toEqual({ ...complete, reservations: null });
    return structuredClone(batch);
  });
  const bff = { renewLease: renew, reserveChunks: reserve,
    getCaptureRecoveryState: vi.fn(async () => structuredClone(remote)), recoverCapture: vi.fn() };
  const run = () => exchangeCaptureRenewal({ intent, store, bff, now: () => now,
    requireContinuous: () => { if (!continuous) throw new Error("stopped run"); } });
  const stop = async () => {
    continuous = false;
    const current = (await store.getActiveCaptureState())!;
    local = observeRecoveryGap(local, { reasonCode: "process_recovery_unknown", observedAt: now.toISOString(), nextSequenceNumber: current.recordedChunks });
    await store.putCaptureRecoveryState(local);
    local = confirmRecoverySourceClosed(local); await store.putCaptureRecoveryState(local);
    await store.putActiveCaptureState({ ...current, phase: "paused" });
  };
  return { get store() { return store; }, active, intent, complete, nextLease, batch, remote, bff, renew, reserve, run, saved, stop,
    normalStop: async () => {
      continuous = false;
      const current = (await store.getActiveCaptureState())!;
      local = stopRecoverySegment(local, now.toISOString(), current.recordedChunks);
      await store.putCaptureRecoveryState(local);
      await store.putActiveCaptureState({ ...current, phase: "uploading" });
    },
    reconcileStopped: () => reconcileStoppedRenewal({ intent, store, bff, now: () => now, crypto }),
    now: () => now, expire: () => { now = new Date(Date.parse(lease.expires_at) + 1); },
    reopen: async () => { store.close(); store = await open(); },
    reconcile: () => reconcileInterruptedRenewal({ intent, store, bff, now: () => now, crypto }) };
}

describe("durable continuous-capture renewal", () => {
  it("reconciles a committed lost renewal after normal Stop and restart without a gap or new window", async () => {
    const f = await setup();
    f.renew.mockImplementationOnce(async () => { f.remote.current_lease = f.nextLease; throw new Error("lost response"); });
    await expect(f.run()).rejects.toThrow("lost response");
    await f.normalStop(); await f.reopen();
    expect(await f.reconcileStopped()).toBe(true);
    expect(f.renew.mock.calls[1]).toEqual(f.renew.mock.calls[0]);
    expect(f.reserve).not.toHaveBeenCalled();
    expect(await f.store.getActiveCaptureState()).toMatchObject({ phase: "uploading", lease: f.complete.lease,
      captureAuthorizedUntil: f.active.captureAuthorizedUntil, recordedChunks: 70, completeIdempotencyKey: f.active.completeIdempotencyKey });
    expect(await f.store.getCaptureRecoveryState(f.intent.sessionId)).toMatchObject({ phase: "stopped", gaps: [], currentSegmentId: null });
  });

  it.each([false, true])("does not renew an unchanged lease after normal Stop (completion already committed=%s)", async completed => {
    const f = await setup();
    await f.store.putCaptureRenewal({ intent: f.intent, lease: null, reservations: null }); await f.normalStop();
    if (completed) { f.remote.lease_closed = true; f.remote.session_status = "uploaded"; }
    expect(await f.reconcileStopped()).toBe(false);
    expect(f.renew).not.toHaveBeenCalled(); expect(f.reserve).not.toHaveBeenCalled();
  });

  it("requires terminal local state for stopped reconciliation and rejects foreign closed generations", async () => {
    const f = await setup(); await f.run();
    await expect(f.reconcileStopped()).rejects.toThrow();
    await f.normalStop(); f.remote.lease_closed = true; f.remote.session_status = "uploaded";
    await expect(f.reconcileStopped()).rejects.toThrow();
    expect((await f.store.getActiveCaptureState())?.lease.generation).toBe(1);
  });
  it("persists each stage before the next request and preserves chunks recorded during the exchange", async () => {
    const f = await setup();
    const original = f.reserve.getMockImplementation()!;
    f.reserve.mockImplementationOnce(async (...args) => {
      await f.store.putActiveCaptureState({ ...f.active, recordedChunks: 71, recordedPlaintextBytes: 22723124 });
      return original(...args);
    });
    expect(await f.run()).toEqual(f.complete);
    expect(f.renew).toHaveBeenCalledWith(f.intent.sessionId, f.intent.priorLease.lease_id,
      { protocol_version: "1.0", expected_generation: 1 }, { idempotencyKey: f.intent.leaseIdempotencyKey });
    expect(f.reserve).toHaveBeenCalledWith(f.intent.sessionId,
      { protocol_version: "1.0", channel: "microphone", capture_lease_id: f.intent.priorLease.lease_id,
        capture_lease_generation: 2, first_sequence_number: 90, count: 90 }, { idempotencyKey: f.intent.reservationIdempotencyKey });
    expect(await f.store.applyCaptureRenewal(f.intent, "continuous", f.now())).toMatchObject({
      phase: "recording", lease: f.complete.lease, captureAuthorizedUntil: f.complete.reservations!.capture_authorized_until,
      recordedChunks: 71, recordedPlaintextBytes: 22723124 });
    await expect(f.store.putActiveCaptureState(f.active)).rejects.toThrow("active_capture_conflict");
  });

  it("reopens encrypted stages and never repeats a confirmed lease or reservation", async () => {
    const f = await setup(); await f.run(); await f.reopen();
    expect(await f.run()).toEqual(f.complete);
    expect(f.renew).toHaveBeenCalledTimes(1); expect(f.reserve).toHaveBeenCalledTimes(1);
    await f.store.clearCompletedCapture(f.intent.sessionId);
    expect(await f.saved()).toBeNull(); expect(await f.store.getActiveCaptureState()).toBeNull();
  });

  it.each(["lease", "reservations"] as const)("retries a lost %s response with the identical saved key", async stage => {
    const f = await setup(), method = stage === "lease" ? f.renew : f.reserve;
    const original = method.getMockImplementation()!;
    method.mockImplementationOnce(async (...args) => { await original(...args); throw new Error("lost response"); });
    await expect(f.run()).rejects.toThrow("lost response"); await f.reopen();
    expect(await f.run()).toEqual(f.complete);
    expect(method.mock.calls).toHaveLength(2); expect(method.mock.calls[0]).toEqual(method.mock.calls[1]);
    expect(stage === "lease" ? f.reserve : f.renew).toHaveBeenCalledTimes(1);
  });

  it("retains a lease returned after Stop without reserving or reactivating capture", async () => {
    const f = await setup();
    f.renew.mockImplementationOnce(async () => { f.remote.current_lease = f.nextLease; await f.stop(); return f.nextLease; });
    await expect(f.run()).rejects.toThrow("stopped run");
    expect(await f.saved()).toEqual({ ...f.complete, reservations: null });
    expect(f.reserve).not.toHaveBeenCalled();
    await expect(f.store.applyCaptureRenewal(f.intent, "continuous", f.now())).rejects.toThrow();
    expect(await f.reconcile()).toBe(true);
    expect(await f.store.getActiveCaptureState()).toMatchObject({ phase: "paused", lease: f.complete.lease,
      captureAuthorizedUntil: f.active.captureAuthorizedUntil });
  });

  it("retains reservations returned after Stop but refuses continuous application", async () => {
    const f = await setup(); f.reserve.mockImplementationOnce(async () => { await f.stop(); return f.batch; });
    await expect(f.run()).rejects.toThrow("stopped run"); expect(await f.saved()).toEqual(f.complete);
    await expect(f.store.applyCaptureRenewal(f.intent, "continuous", f.now())).rejects.toThrow();
    expect((await f.store.getActiveCaptureState())?.lease.generation).toBe(1);
  });

  it("does not reserve after the old authority deadline passes during renewal", async () => {
    const f = await setup(); f.renew.mockImplementationOnce(async () => { f.expire(); return f.nextLease; });
    await expect(f.run()).rejects.toThrow("capture_authority_expired");
    expect(f.reserve).not.toHaveBeenCalled(); expect((await f.saved())?.lease?.generation).toBe(2);
  });

  it("recovers a remotely committed lost lease after restart using only the saved request", async () => {
    const f = await setup();
    f.renew.mockImplementationOnce(async () => { f.remote.current_lease = f.nextLease; throw new Error("lost response"); });
    await expect(f.run()).rejects.toThrow("lost response"); await f.stop(); await f.reopen();
    expect(await f.reconcile()).toBe(true);
    expect(f.renew.mock.calls[0]).toEqual(f.renew.mock.calls[1]); expect(f.reserve).not.toHaveBeenCalled();
    expect(await f.store.getActiveCaptureState()).toMatchObject({ phase: "paused", lease: f.complete.lease,
      captureAuthorizedUntil: f.active.captureAuthorizedUntil });
  });

  it("does not create an uncommitted renewal after interruption", async () => {
    const f = await setup(); await f.store.putCaptureRenewal({ intent: f.intent, lease: null, reservations: null });
    await f.stop(); expect(await f.reconcile()).toBe(false);
    expect(f.renew).not.toHaveBeenCalled(); expect(f.reserve).not.toHaveBeenCalled();
  });

  it.each(["generation jump", "foreign lease", "closed lease"])("rejects interrupted reconciliation with %s", async fault => {
    const f = await setup(); await f.store.putCaptureRenewal({ intent: f.intent, lease: null, reservations: null }); await f.stop();
    f.remote.current_lease = { ...f.nextLease };
    if (fault === "generation jump") f.remote.current_lease.generation = 3;
    if (fault === "foreign lease") f.remote.current_lease.lease_id = crypto.randomUUID();
    if (fault === "closed lease") f.remote.lease_closed = true;
    await expect(f.reconcile()).rejects.toThrow(); expect(f.renew).not.toHaveBeenCalled();
  });

  it("cannot create a new intent from paused state or rewrite existing keys or receipts", async () => {
    const f = await setup(); await f.run();
    await expect(f.store.putCaptureRenewal({ ...f.complete, intent: { ...f.intent, leaseIdempotencyKey: "different-key" } })).rejects.toThrow();
    await expect(f.store.putCaptureRenewal({ ...f.complete, lease: { ...f.complete.lease!, receipt_id: crypto.randomUUID() } })).rejects.toThrow();
    const other = await setup(); await other.stop();
    await expect(other.store.putCaptureRenewal({ intent: other.intent, lease: null, reservations: null })).rejects.toThrow();
  });

  it("atomically rejects an extension when Stop changes state while the new state is encrypted", async () => {
    const f = await setup(); await f.run();
    const gate = holdEncryption(value => value.phase === "recording" && value.lease?.generation === 2);
    const applying = f.store.applyCaptureRenewal(f.intent, "continuous", f.now());
    const rejected = expect(applying).rejects.toThrow("active_capture_conflict");
    await gate.entered; await f.stop(); gate.release(); await rejected;
    expect(await f.store.getActiveCaptureState()).toMatchObject({ phase: "paused", lease: f.active.lease });
  });

  it("atomically rejects an old chunk write that would overwrite an applied lease", async () => {
    const f = await setup(); await f.run();
    const gate = holdEncryption(value => value.recordedChunks === 71 && value.lease?.generation === 1);
    const writing = f.store.putActiveCaptureState({ ...f.active, recordedChunks: 71 });
    const rejected = expect(writing).rejects.toThrow("active_capture_conflict");
    await gate.entered; await f.store.applyCaptureRenewal(f.intent, "continuous", f.now()); gate.release(); await rejected;
    expect((await f.store.getActiveCaptureState())?.lease.generation).toBe(2);
  });

  it("rechecks expiry after encryption and before atomically applying an extension", async () => {
    const f = await setup(); await f.run();
    const gate = holdEncryption(value => value.phase === "recording" && value.lease?.generation === 2);
    const applying = f.store.applyCaptureRenewal(f.intent, "continuous", f.now());
    const rejected = expect(applying).rejects.toThrow("capture_renewal_conflict");
    await gate.entered;
    vi.spyOn(Date, "now").mockReturnValue(Date.parse(f.intent.priorCaptureAuthorizedUntil) + 1);
    gate.release(); await rejected;
    expect((await f.store.getActiveCaptureState())?.lease.generation).toBe(1);
  });

  it("does not recreate a late renewal receipt after confirmed-completion cleanup", async () => {
    const f = await setup(); await f.store.putCaptureRenewal({ intent: f.intent, lease: null, reservations: null });
    const gate = holdEncryption(value => (value as unknown as CaptureLeaseReceipt).generation === 2);
    const writing = f.store.putCaptureRenewal({ ...f.complete, reservations: null });
    const rejected = expect(writing).rejects.toThrow("active_capture_conflict");
    await gate.entered; await f.store.clearCompletedCapture(f.intent.sessionId); gate.release(); await rejected;
    expect(await f.saved()).toBeNull(); expect(await f.store.getActiveCaptureState()).toBeNull();
  });

  it("accepts an existing future reservation with its original creation time under the new batch deadline", async () => {
    const f = await setup(), record = structuredClone(f.complete);
    for (const reservation of record.reservations!.reservations) reservation.created_at = f.intent.priorLease.issued_at;
    expect(validateRenewalRecord(record, f.now())).toEqual(record);
  });
});

function holdEncryption(predicate: (value: ActiveCaptureState) => boolean) {
  let entered!: () => void, release!: () => void;
  const didEnter = new Promise<void>(resolve => { entered = resolve; });
  const released = new Promise<void>(resolve => { release = resolve; });
  const encrypt = crypto.subtle.encrypt.bind(crypto.subtle);
  let armed = true;
  vi.spyOn(crypto.subtle, "encrypt").mockImplementation(async (algorithm, key, data) => {
    const value = JSON.parse(new TextDecoder().decode(data)) as ActiveCaptureState;
    if (armed && predicate(value)) { armed = false; entered(); await released; }
    return encrypt(algorithm, key, data);
  });
  return { entered: didEnter, release };
}

describe("renewal response scope", () => {
  const faults: [string, (record: CaptureRenewalRecord) => void][] = [
    ["skipped generation", r => { r.lease!.generation = 3; }],
    ["foreign session", r => { r.lease!.session_id = crypto.randomUUID(); }],
    ["lease exceeding fifteen minutes", r => { r.lease!.expires_at = new Date(Date.parse(r.lease!.issued_at) + 900001).toISOString(); }],
    ["changed reservation deadline", r => { r.reservations!.capture_authorized_until = r.intent.priorCaptureAuthorizedUntil; }],
    ["missing reservation", r => { r.reservations!.reservations.pop(); }],
    ["noncontiguous sequence", r => { r.reservations!.reservations[0]!.sequence_number += 1; }],
    ["duplicate object", r => { r.reservations!.reservations[1]!.object_id = r.reservations!.reservations[0]!.object_id; }],
    ["wrong channel", r => { r.reservations!.reservations[0]!.channel = "system_audio"; }],
    ["foreign AAD", r => { r.reservations!.reservations[0]!.additional_authenticated_data = r.reservations!.reservations[1]!.additional_authenticated_data; }],
    ["beyond profile budget", r => { r.intent.firstSequenceNumber = 350; }],
  ];
  it.each(faults)("rejects %s before granting authority", async (_label, mutate) => {
    const f = await setup(), invalid = structuredClone(f.complete); mutate(invalid);
    expect(() => validateRenewalRecord(invalid, f.now())).toThrow("capture_renewal_conflict");
  });
});
