import { webcrypto } from "node:crypto";
import { readFileSync } from "node:fs";
import { IDBFactory } from "fake-indexeddb";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CaptureBff } from "../bff/contracts";
import { canonicalRecoveryRequest, recoveryRequestHash, validateRecoveryReceipt, validateRecoveryState,
  type CaptureRecoveryBff, type CaptureRecoveryRequest, type CaptureRecoveryState } from "../bff/recovery-contracts";
import { EncryptedIndexedDbFlowStore } from "./encrypted-store";
import { exchangeRecovery } from "./recovery-exchange";
import { acknowledgeRecoveryGap, beginRecoverySegment, confirmRecoverySourceClosed,
  createCaptureRecoveryState, observeRecoveryGap } from "./recovery-state";
import type { ActiveCaptureState } from "./types";

const crypto = webcrypto as unknown as Crypto;
const fixture = JSON.parse(readFileSync(new URL("../../../../tests/fixtures/capture_recovery.json", import.meta.url), "utf8"));
const cleanup: (() => void)[] = [];
afterEach(() => { cleanup.splice(0).forEach(fn => fn()); });
async function setup() {
  const indexedDB = new IDBFactory(), databaseName = crypto.randomUUID();
  const open = async () => {
    const store = await EncryptedIndexedDbFlowStore.open({ indexedDB, databaseName, crypto });
    cleanup.push(() => store.close()); return store;
  };
  const store = await open();
  const request = fixture.request as CaptureRecoveryRequest;
  const receipt = structuredClone(fixture.receipt);
  const sessionId = receipt.session_id;
  let local = createCaptureRecoveryState(sessionId);
  await store.putCaptureRecoveryState(local);
  local = beginRecoverySegment(local, { segmentId: request.segment_id, recoveryGapId: request.gap_id,
    startedAt: request.segment_started_at, leaseGeneration: 1, captureAuthorizedUntil: receipt.lease.expires_at });
  await store.putCaptureRecoveryState(local);
  local = observeRecoveryGap(local, { reasonCode: request.reason_code,
    observedAt: request.observed_at, nextSequenceNumber: request.next_sequence_number });
  await store.putCaptureRecoveryState(local);
  local = confirmRecoverySourceClosed(local);
  await store.putCaptureRecoveryState(local);
  local = acknowledgeRecoveryGap(local, { acknowledgedAt: request.acknowledged_at, idempotencyKey: "synthetic-gap-decision" });
  await store.putCaptureRecoveryState(local);
  const active: ActiveCaptureState = { schemaVersion: 2, sessionId, lease: { ...receipt.lease, generation: 1 },
    captureAuthorizedUntil: receipt.lease.expires_at, aggregatePlaintextBudgetBytes: 100_000_000,
    phase: "paused", completeIdempotencyKey: "synthetic-complete-capture", recordedChunks: 1,
    recordedPlaintextBytes: 100, startedAt: request.segment_started_at };
  const state: CaptureRecoveryState = { history: { session_id: sessionId, recoveries: [] },
    current_lease: structuredClone(active.lease), lease_closed: false, session_status: "capturing" };
  let now = new Date("2026-09-17T00:01:00Z"), loseReply = false, loseRenewal = false;
  const recover = vi.fn(async (_id, command, options) => {
    expect(await store.getCaptureRecoveryIntent(sessionId, command.gap_id)).toMatchObject({
      idempotencyKey: options.idempotencyKey, request: command });
    expect(canonicalRecoveryRequest(command)).toBe(canonicalRecoveryRequest(request));
    state.history.recoveries = [structuredClone(receipt)];
    state.current_lease = structuredClone(receipt.lease);
    if (loseReply) { loseReply = false; throw new Error("discarded response"); }
    return structuredClone(receipt);
  });
  const renew = vi.fn(async (_id, _leaseId, command, options) => {
    expect(options.idempotencyKey).toBe(`recovery-renew:${request.gap_id}:${command.expected_generation}`);
    state.current_lease = { ...receipt.lease, receipt_id: crypto.randomUUID(), generation: command.expected_generation + 1,
      issued_at: now.toISOString(), expires_at: new Date(now.getTime() + 900_000).toISOString() };
    if (loseRenewal) { loseRenewal = false; throw new Error("discarded renewal"); }
    return structuredClone(state.current_lease);
  });
  const bff = { recoverCapture: recover, renewLease: renew,
    getCaptureRecoveryState: vi.fn(async () => structuredClone(state)) } as unknown as CaptureBff & CaptureRecoveryBff;
  const run = (selected = store, selectedLocal = local, decision: CaptureRecoveryRequest["decision"] = "resume_capture") =>
    exchangeRecovery({ bff, store: selected, active, local: selectedLocal, decision, now: () => now, crypto });
  return { store, open, active, local, state, run, bff, recover, renew,
    advance: () => { now = new Date("2026-09-17T01:00:00Z"); },
    loseReply: () => { loseReply = true; }, loseRenewal: () => { loseRenewal = true; } };
}

describe("retained recovery exchange", () => {
  it("agrees with the actual Scribe fixture including UTC microsecond hashes", async () => {
    expect(await recoveryRequestHash(fixture.request, crypto)).toBe(fixture.receipt.request_sha256);
    const now = new Date("2026-09-17T02:00:00Z");
    expect(await validateRecoveryReceipt(fixture.receipt, fixture.receipt.session_id, now, fixture.request, crypto)).toEqual(fixture.receipt);
    expect(await validateRecoveryState(fixture.state, fixture.receipt.session_id, now, crypto)).toEqual(fixture.state);
  });
  it("recovers a committed decision after a discarded response and reopened encrypted store", async () => {
    const f = await setup(); f.loseReply();
    await expect(f.run()).rejects.toThrow("discarded response");
    f.store.close();
    const reopened = await f.open(), saved = await reopened.getCaptureRecoveryState(f.active.sessionId);
    expect(saved).toEqual(f.local);
    const result = await f.run(reopened, saved!);
    expect(result.history.recoveries).toHaveLength(1);
    expect(f.recover).toHaveBeenCalledTimes(1);
    expect(result.current_lease?.generation).toBe(2);
  });
  it("recovers a lost renewal without replaying an expired receipt as fresh authority", async () => {
    const f = await setup(); await f.run(); f.advance(); f.loseRenewal();
    await expect(f.run()).rejects.toThrow("discarded renewal");
    const result = await f.run();
    expect(result.history.recoveries[0]?.lease.generation).toBe(2);
    expect(result.current_lease?.generation).toBe(3);
    expect(f.recover).toHaveBeenCalledTimes(1); expect(f.renew).toHaveBeenCalledTimes(1);
  });
  it("will not change a saved decision or overwrite its encrypted request", async () => {
    const f = await setup(); await f.run();
    await expect(f.run(f.store, f.local, "finish_capture")).rejects.toThrow("capture_gap_decision_conflict");
    const intent = await f.store.getCaptureRecoveryIntent(f.active.sessionId, fixture.request.gap_id);
    await expect(f.store.putCaptureRecoveryIntent({ ...intent!, request: { ...intent!.request, next_sequence_number: 2 } })).rejects.toThrow("flow_record_conflict");
    expect(f.recover).toHaveBeenCalledTimes(1);
  });
  it.each(["closed", "completed", "foreign_lease", "changed_gap", "duplicate", "revoked"])(
    "rejects %s recovery before it can grant client authority", async fault => {
      const f = await setup(); await f.run();
      if (fault === "closed") f.state.lease_closed = true;
      if (fault === "completed") f.state.session_status = "uploaded";
      if (fault === "foreign_lease") f.state.current_lease!.lease_id = crypto.randomUUID();
      if (fault === "changed_gap") f.state.history.recoveries[0]!.request.gap_id = crypto.randomUUID();
      if (fault === "duplicate") f.state.history.recoveries.push(structuredClone(f.state.history.recoveries[0]!));
      if (fault === "revoked") vi.mocked(f.bff.getCaptureRecoveryState).mockRejectedValue(new Error("revoked"));
      await expect(f.run()).rejects.toThrow();
      expect(f.renew).not.toHaveBeenCalled(); expect(f.recover).toHaveBeenCalledTimes(1);
    });
});

it("rejects a different decision before any intent or remote write exists", async () => {
  const f = await setup();
  await expect(f.run(f.store, f.local, "finish_capture")).rejects.toThrow("capture_gap_decision_conflict");
  expect(await f.store.getCaptureRecoveryIntent(f.active.sessionId, fixture.request.gap_id)).toBeNull();
  expect(f.bff.getCaptureRecoveryState).not.toHaveBeenCalled();
  expect(f.recover).not.toHaveBeenCalled();
});
