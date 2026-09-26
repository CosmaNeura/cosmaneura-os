import { webcrypto } from "node:crypto";
import { readFileSync } from "node:fs";
import { IDBFactory } from "fake-indexeddb";
import { afterEach, expect, it, vi } from "vitest";
import { base64UrlEncode } from "@cosmaneura-scribe/capture-protocol";
import { HttpCaptureBff, BffResponseError } from "../bff/http-client";
import type { CaptureLeaseReceipt, ChunkReservationBatchReceipt } from "../bff/contracts";
import type { CaptureProfileBff, CaptureProfileReceipt } from "../bff/profile-contracts";
import type { CaptureRecoveryBff } from "../bff/recovery-contracts";
import { encodePcm16MonoWav, pcm16WavProfile, type CaptureSource, type CaptureSourceExtension, type CaptureSourceStartOptions } from "../capture";
import { MockCaptureService } from "../mock-bff/state";
import { CaptureQueue } from "../queue/capture-queue";
import type { CaptureQueueTransport } from "../queue/types";
import { EncryptedIndexedDbQueueStorage } from "../storage/encrypted-indexeddb";
import { EncryptedIndexedDbFlowStore } from "./encrypted-store";
import { CaptureFlowController } from "./controller";

const crypto = webcrypto as unknown as Crypto;
const cleanup: (() => void | Promise<void>)[] = [];
afterEach(async () => {
  for (const close of cleanup.splice(0).reverse()) await close();
  vi.restoreAllMocks(); vi.useRealTimers();
});
function gate() {
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  return { pending, release };
}
async function until(predicate: () => boolean | Promise<boolean>) {
  for (let attempt = 0; attempt < 2000; attempt++) {
    if (await predicate()) return;
    await new Promise(resolve => setTimeout(resolve, 1));
  }
  throw new Error("synthetic condition did not settle");
}

/** Generated tiny WAVs and a simulated clock exercise controller state, not
 * microphone fidelity or a real-time hour. Native source qualification is separate. */
class ControlledSource implements CaptureSource {
  readonly kind = "microphone" as const;
  options!: CaptureSourceStartOptions;
  maximum = 0;
  next = 0;
  readonly start = vi.fn(async (options: CaptureSourceStartOptions) => {
    this.options = options; this.maximum = options.capabilities.max_chunks; this.next = 0;
  });
  readonly stop = vi.fn(async () => {});
  readonly extend = vi.fn(async (extension: CaptureSourceExtension) => { this.maximum = extension.maximumChunks; });
  async emit(advance = 10_000) {
    expect(this.next).toBeLessThan(this.maximum);
    vi.setSystemTime(Date.now() + advance);
    const profile = pcm16WavProfile(this.options.capabilities);
    await this.options.onChunk({ sequenceNumber: this.next++, durationMs: 1,
      wavBytes: encodePcm16MonoWav(new Int16Array([1, 2, 3, 4]), profile) });
  }
}

async function fixture() {
  vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(new Date());
  const service = new MockCaptureService();
  const consent = service.createConsent({ appointment_id: "synthetic-visit", practitioner_id: "synthetic-provider",
    patient_id: "synthetic-person", modality: "in_person", participant_regions: ["US-NY"], method: "verbal_attestation",
    all_parties_consented: true, granted_at: new Date().toISOString(), evidence_object_id: null }, "synthetic-consent");
  const session = service.createSession({ appointment_id: consent.appointment_id, practitioner_id: consent.practitioner_id,
    patient_id: consent.patient_id, consent_record_id: consent.id, modality: "in_person" }, "synthetic-session");
  const bff = new HttpCaptureBff(vi.fn().mockRejectedValue(new Error("unconfigured synthetic BFF")));
  vi.spyOn(bff, "getAudioEncryptionKey").mockImplementation(async () => service.audioEncryptionKey());
  vi.spyOn(bff, "bindSessionAudioKey").mockImplementation(async (id, request, options) => service.bindSessionAudioKey(id, request, options.idempotencyKey));
  vi.spyOn(bff, "getCapabilities").mockImplementation(async () => ({ ...service.capabilities(), max_chunks: 720,
    remaining_aggregate_plaintext_bytes: 268435456 }));
  let lease!: CaptureLeaseReceipt;
  vi.spyOn(bff, "issueLease").mockImplementation(async (id) => {
    lease = { protocol_version: "1.0", session_id: id, lease_id: crypto.randomUUID(), receipt_id: crypto.randomUUID(),
      generation: 1, issued_at: new Date().toISOString(), expires_at: new Date(Date.now() + 900_000).toISOString() };
    return structuredClone(lease);
  });
  const leases = new Map<string, CaptureLeaseReceipt>();
  const renew = vi.spyOn(bff, "renewLease").mockImplementation(async (_id, leaseId, request, options) => {
    const saved = leases.get(options.idempotencyKey); if (saved) return structuredClone(saved);
    expect(request.expected_generation).toBe(lease.generation); expect(leaseId).toBe(lease.lease_id);
    lease = { ...lease, receipt_id: crypto.randomUUID(), generation: lease.generation + 1,
      issued_at: new Date().toISOString(), expires_at: new Date(Date.now() + 900_000).toISOString() };
    leases.set(options.idempotencyKey, structuredClone(lease)); return structuredClone(lease);
  });
  const objects = new Map<number, ChunkReservationBatchReceipt["reservations"][number]>();
  const batches = new Map<string, ChunkReservationBatchReceipt>();
  const tenantId = crypto.randomUUID();
  const reserve = vi.spyOn(bff, "reserveChunks").mockImplementation(async (_id, request, options) => {
    const saved = batches.get(options.idempotencyKey); if (saved) return structuredClone(saved);
    expect(request.capture_lease_generation).toBe(lease.generation);
    const reservations = Array.from({ length: request.count }, (_, offset) => {
      const sequence_number = request.first_sequence_number + offset;
      if (!objects.has(sequence_number)) {
        const object_id = crypto.randomUUID();
        objects.set(sequence_number, { protocol_version: "1.0", session_id: session.id, object_id,
          channel: "microphone", sequence_number, created_at: new Date().toISOString(),
          additional_authenticated_data: base64UrlEncode(new TextEncoder().encode(JSON.stringify({ tenant_id: tenantId,
            session_id: session.id, object_id, sequence_number, channel: "microphone" }))) });
      }
      return objects.get(sequence_number)!;
    });
    const batch: ChunkReservationBatchReceipt = { protocol_version: "1.0", session_id: session.id,
      batch_id: crypto.randomUUID(), capture_authorized_until: lease.expires_at, reservations };
    batches.set(options.idempotencyKey, batch); return structuredClone(batch);
  });
  let completed = false;
  const complete = vi.spyOn(bff, "completeCapture").mockImplementation(async (_id, request) => {
    expect(request.capture_lease_generation).toBe(lease.generation);
    completed = true; return { ...session, status: "uploaded" };
  });
  vi.spyOn(bff, "getTranscriptionStatus").mockImplementation(async () => ({ session_id: session.id,
    status: "processing", transcript_available: false, updated_at: new Date().toISOString() }));
  const recovery: CaptureRecoveryBff = { recoverCapture: vi.fn(), getCaptureRecoveryState: vi.fn(async () => ({
    current_lease: structuredClone(lease), lease_closed: completed, session_status: completed ? "uploaded" as const : "capturing" as const,
    history: { session_id: session.id, recoveries: [] } })) };
  const golden: CaptureProfileReceipt = JSON.parse(readFileSync(new URL("../../../../tests/fixtures/capture_profile.json", import.meta.url), "utf8"));
  const profile = { ...golden, session_id: session.id };
  const profiles: CaptureProfileBff = { selectCaptureProfile: vi.fn(async () => profile),
    getCaptureProfile: vi.fn(async () => profile), acknowledgeCaptureProfile: vi.fn(async () => {}) };
  const indexedDB = new IDBFactory(), name = crypto.randomUUID();
  let flow = await EncryptedIndexedDbFlowStore.open({ indexedDB, databaseName: name, crypto });
  cleanup.push(() => flow.close());
  const storage = await EncryptedIndexedDbQueueStorage.open({ indexedDB, databaseName: crypto.randomUUID(), crypto });
  cleanup.push(() => storage.close());
  const queue = new CaptureQueue(storage, { crypto });
  const transport: CaptureQueueTransport = {
    getReceipt: vi.fn(async () => ({ state: "reserved" as const })),
    authorizeUpload: vi.fn(async (_id, objectId) => ({ objectId, uploadUrl: "https://synthetic.invalid/ciphertext",
      expiresAtEpochMs: Date.now() + 900_000, additionalAuthenticatedData: [...objects.values()].find(o => o.object_id === objectId)!.additional_authenticated_data })),
    upload: vi.fn(async () => {}), register: vi.fn(async request => ({ chunkId: crypto.randomUUID(), sha256: request.sha256,
      byteLength: request.byteLength, registeredAt: new Date().toISOString() })),
  };
  const source = new ControlledSource();
  const timers: { callback: () => void; due: number; cancelled: boolean }[] = [];
  const create = () => {
    const controller = new CaptureFlowController({ bff, flowStore: flow, renewals: flow, profiles, recovery, queue,
      queueTransport: transport, source, crypto,
      scheduleTimeout: (callback, delay) => { const timer = { callback, due: Date.now() + delay, cancelled: false }; timers.push(timer); return timer; },
      cancelTimeout: handle => { (handle as typeof timers[number]).cancelled = true; } });
    cleanup.push(() => controller.close()); return controller;
  };
  const controller = create();
  await controller.prepareAdmitted(session.id, profile.request);
  return { controller, create, source, bff, renew, reserve, complete, queue, transport, timers, recovery,
    session, get flow() { return flow; },
    reopen: async () => { flow.close(); flow = await EncryptedIndexedDbFlowStore.open({ indexedDB, databaseName: name, crypto }); },
    emitTo: async (count: number) => { while (source.next < count) { await source.emit();
      if (source.next >= source.maximum - 6 && source.maximum < 360) await until(() => source.maximum > source.next + 6); } },
  };
}

it("automatically renews two windows in one run and preserves reused objects, queue keys and audio", async () => {
  const f = await fixture(); await f.controller.startRecording();
  const before = await f.queue.list();
  await f.emitTo(200);
  expect(f.source.start).toHaveBeenCalledTimes(1); expect(f.source.extend).toHaveBeenCalledTimes(2);
  expect(f.controller.snapshot.recordedChunks).toBe(200);
  const after = await f.queue.list();
  for (const original of before) expect(after.find(r => r.reservation.objectId === original.reservation.objectId)?.idempotencyKeys).toEqual(original.idempotencyKeys);
  expect(await f.flow.getActiveCaptureState()).toMatchObject({ recordedChunks: 200, lease: { generation: 3 } });
  await f.controller.stopRecording();
  expect(f.complete).toHaveBeenCalledTimes(1);
  expect(await f.flow.getCaptureRecoveryState(f.session.id)).toMatchObject({ phase: "stopped", gaps: [], nextSequenceNumber: 200 });
  expect(f.controller.snapshot.state).toBe("processing");
});

it.each(["lease", "reservation"])("recovers one lost %s reply during uninterrupted recording with identical keys", async stage => {
  const f = await fixture(); await f.controller.startRecording();
  const method = stage === "lease" ? f.renew : f.reserve;
  if (stage === "lease") {
    const original = f.renew.getMockImplementation()!;
    f.renew.mockImplementationOnce(async (...args) => { await original(...args); throw new Error("synthetic lost reply"); });
  } else {
    const original = f.reserve.getMockImplementation()!;
    f.reserve.mockImplementationOnce(async (...args) => { await original(...args); throw new Error("synthetic lost reply"); });
  }
  await f.emitTo(100);
  expect(f.source.extend).toHaveBeenCalledTimes(1);
  const calls = method.mock.calls.slice(stage === "lease" ? 0 : 1);
  expect(calls).toHaveLength(2); expect(calls[1]).toEqual(calls[0]);
  expect(f.controller.snapshot.state).toBe("recording");
});

it("saves chunks during slow renewal, stops promptly, then reconciles a late commit without new reservations", async () => {
  const f = await fixture(); await f.controller.startRecording();
  const gateReply = gate(), entered = gate(), original = f.renew.getMockImplementation()!;
  f.renew.mockImplementationOnce(async (...args) => { const reply = await original(...args); entered.release(); await gateReply.pending; return reply; });
  for (let i = 0; i < 84; i++) await f.source.emit();
  await entered.pending; await f.source.emit();
  expect(f.controller.snapshot.recordedChunks).toBe(85);
  const stopping = f.controller.stopRecording();
  expect(f.controller.stopRecording()).toBe(stopping);
  await expect(stopping).rejects.toThrow("capture_renewal_unconfirmed");
  expect(f.source.stop).toHaveBeenCalledTimes(1); expect(f.transport.upload).not.toHaveBeenCalled();
  expect(await f.flow.getCaptureRecoveryState(f.session.id)).toMatchObject({ phase: "stopped", gaps: [] });
  gateReply.release();
  await until(async () => (await f.flow.getCaptureRenewal(f.session.id, (await f.flow.getActiveCaptureState())!.lease.lease_id, 1))?.lease !== null);
  await until(async () => { try { await f.controller.resumePendingWork(); return true; } catch { return false; } });
  expect(f.reserve).toHaveBeenCalledTimes(1); expect(f.source.extend).not.toHaveBeenCalled();
  expect(f.complete.mock.calls[0]![1].capture_lease_generation).toBe(2);
  expect(f.source.start).toHaveBeenCalledTimes(1);
});

it("recovers successive lost lease and reservation replies with one exact retry per stage", async () => {
  const f = await fixture(); await f.controller.startRecording();
  const renew = f.renew.getMockImplementation()!, reserve = f.reserve.getMockImplementation()!;
  f.renew.mockImplementationOnce(async (...args) => { await renew(...args); throw new Error("lost lease reply"); });
  f.reserve.mockImplementationOnce(async (...args) => { await reserve(...args); throw new Error("lost reservation reply"); });
  await f.emitTo(100);
  expect(f.renew.mock.calls).toHaveLength(2); expect(f.renew.mock.calls[1]).toEqual(f.renew.mock.calls[0]);
  expect(f.reserve.mock.calls).toHaveLength(3); expect(f.reserve.mock.calls[2]).toEqual(f.reserve.mock.calls[1]);
  expect(f.source.extend).toHaveBeenCalledTimes(1); expect(f.controller.snapshot.state).toBe("recording");
});

it("stops after the same renewal stage fails twice", async () => {
  const f = await fixture(); await f.controller.startRecording();
  f.renew.mockRejectedValue(new BffResponseError(503, "capture_request_unconfirmed", null));
  for (let i = 0; i < 84; i++) await f.source.emit();
  await until(async () => (await f.flow.getCaptureRecoveryState(f.session.id))?.phase === "ack_required");
  expect(f.renew).toHaveBeenCalledTimes(2); expect(f.source.extend).not.toHaveBeenCalled();
  expect(f.source.stop).toHaveBeenCalledTimes(1); expect(f.controller.snapshot.state).toBe("paused");
});

it("keeps a normal Stop retryable across restart after a lost committed renewal", async () => {
  const f = await fixture(); await f.controller.startRecording();
  const held = gate(), entered = gate(), original = f.renew.getMockImplementation()!;
  f.renew.mockImplementationOnce(async (...args) => { await original(...args); entered.release(); await held.pending; throw new Error("lost reply"); });
  for (let i = 0; i < 84; i++) await f.source.emit(); await entered.pending;
  await expect(f.controller.stopRecording()).rejects.toThrow("capture_renewal_unconfirmed");
  held.release(); await new Promise(resolve => setTimeout(resolve, 5));
  await f.controller.close(); await f.reopen(); const next = f.create(); await next.restore();
  expect(next.snapshot.state).toBe("uploading"); await next.resumePendingWork();
  expect(f.renew.mock.calls[1]).toEqual(f.renew.mock.calls[0]);
  expect(f.reserve).toHaveBeenCalledTimes(1); expect(f.source.start).toHaveBeenCalledTimes(1);
  expect(await f.flow.getCaptureRecoveryState(f.session.id)).toMatchObject({ phase: "stopped", gaps: [] });
});

it("ignores stale expiry callbacks after producer confirmation", async () => {
  const f = await fixture(); await f.controller.startRecording();
  const deadline = Date.parse((await f.flow.getActiveCaptureState())!.captureAuthorizedUntil!);
  const old = [...f.timers].reverse().find(timer => timer.due === deadline)!;
  await f.emitTo(100); old.callback();
  expect(f.controller.snapshot.state).toBe("recording"); expect(f.source.stop).not.toHaveBeenCalled();
});

it("drains a final accepted partial after expiry and requires explicit gap recovery", async () => {
  const f = await fixture(); await f.controller.startRecording(); await f.source.emit();
  const deadline = Date.parse((await f.flow.getActiveCaptureState())!.captureAuthorizedUntil!);
  f.source.stop.mockImplementationOnce(async () => { await f.source.emit(0); });
  vi.setSystemTime(deadline + 1);
  [...f.timers].reverse().find(timer => timer.due === deadline)!.callback();
  await until(() => f.controller.snapshot.state === "paused");
  await until(async () => (await f.flow.getCaptureRecoveryState(f.session.id))?.phase === "ack_required");
  expect(f.controller.snapshot.recordedChunks).toBe(2); expect(f.complete).not.toHaveBeenCalled();
  expect(f.source.start).toHaveBeenCalledTimes(1);
});

it("completes the full chunk budget on normal producer closure without an artificial gap", async () => {
  const f = await fixture(); await f.controller.startRecording(); await f.emitTo(360);
  f.source.options.onWindowClosed!("frame_limit");
  await until(() => f.controller.snapshot.state === "processing");
  expect(f.complete).toHaveBeenCalledTimes(1); expect(f.source.start).toHaveBeenCalledTimes(1);
  expect(f.complete.mock.calls[0]![1].channels[0]!.final_sequence_number).toBe(359);
  expect(await f.flow.getCaptureRecoveryState(f.session.id)).toMatchObject({ phase: "stopped", gaps: [] });
});

it("stops and pauses on revoked renewal without retrying or restarting recording", async () => {
  const f = await fixture(); await f.controller.startRecording();
  f.renew.mockRejectedValue(new BffResponseError(403, "consent_revoked", null));
  for (let i = 0; i < 84; i++) await f.source.emit();
  await until(() => f.controller.snapshot.state === "paused");
  await until(async () => (await f.flow.getCaptureRecoveryState(f.session.id))?.phase === "ack_required");
  expect(f.renew).toHaveBeenCalledTimes(1); expect(f.source.stop).toHaveBeenCalledTimes(1);
  expect(f.source.extend).not.toHaveBeenCalled(); expect(f.source.start).toHaveBeenCalledTimes(1);
});

it("does not hold audio persistence while awaiting producer confirmation and suppresses its late reply after Stop", async () => {
  const f = await fixture(); await f.controller.startRecording();
  const held = gate(), entered = gate();
  f.source.extend.mockImplementationOnce(async extension => {
    await f.source.emit(0); // producer acknowledgment depends on chunk persistence
    entered.release(); await held.pending; f.source.maximum = extension.maximumChunks;
  });
  for (let i = 0; i < 84; i++) await f.source.emit(); await entered.pending;
  expect(f.controller.snapshot.recordedChunks).toBe(85);
  await expect(f.controller.stopRecording()).rejects.toThrow("capture_renewal_unconfirmed");
  expect(f.source.stop).toHaveBeenCalledTimes(1);
  held.release(); await new Promise(resolve => setTimeout(resolve, 5));
  await f.controller.resumePendingWork();
  expect(f.controller.snapshot.state).toBe("processing"); expect(f.source.start).toHaveBeenCalledTimes(1);
  expect(f.source.extend).toHaveBeenCalledTimes(1); expect(f.renew).toHaveBeenCalledTimes(1);
});

it("retains the old expiry until the producer confirms a durable new lease", async () => {
  const f = await fixture(); await f.controller.startRecording();
  const initial = (await f.flow.getActiveCaptureState())!;
  const timer = [...f.timers].reverse().find(t => t.due === Date.parse(initial.captureAuthorizedUntil!))!;
  const held = gate(), entered = gate();
  f.source.extend.mockImplementationOnce(async () => { entered.release(); await held.pending; });
  for (let i = 0; i < 84; i++) await f.source.emit(); await entered.pending;
  expect((await f.flow.getActiveCaptureState())!.lease.generation).toBe(2);
  expect(timer.cancelled).toBe(false);
  vi.setSystemTime(timer.due + 1); timer.callback();
  await until(() => f.controller.snapshot.state === "paused");
  held.release();
  await until(async () => (await f.flow.getCaptureRecoveryState(f.session.id))?.phase === "ack_required");
  expect(f.source.stop).toHaveBeenCalledTimes(1); expect(f.complete).not.toHaveBeenCalled();
  expect(f.timers.filter(t => !t.cancelled && t.due > timer.due)).toHaveLength(0);
});

it("keeps failed producer confirmation paused with the committed server generation", async () => {
  const f = await fixture(); await f.controller.startRecording();
  f.source.extend.mockRejectedValueOnce(new Error("synthetic producer acknowledgment lost"));
  for (let i = 0; i < 84; i++) await f.source.emit();
  await until(async () => (await f.flow.getCaptureRecoveryState(f.session.id))?.phase === "ack_required");
  expect(await f.flow.getActiveCaptureState()).toMatchObject({ phase: "paused", lease: { generation: 2 } });
  expect(f.source.stop).toHaveBeenCalledTimes(1); expect(f.source.start).toHaveBeenCalledTimes(1);
  expect(f.renew).toHaveBeenCalledTimes(1);
});

it("does not complete the final budget when a physical error is reported during its drain", async () => {
  const f = await fixture(); await f.controller.startRecording(); await f.emitTo(360);
  f.source.stop.mockImplementationOnce(async () => { f.source.options.onError!("capture_source_failed"); });
  f.source.options.onWindowClosed!("frame_limit");
  await until(async () => (await f.flow.getCaptureRecoveryState(f.session.id))?.phase === "ack_required");
  expect(f.complete).not.toHaveBeenCalled(); expect(f.controller.snapshot.state).toBe("paused");
});

it("retains an unconfirmed close as a gap instead of completing it on the next Stop", async () => {
  const f = await fixture(); await f.controller.startRecording(); await f.source.emit();
  f.source.stop.mockRejectedValueOnce(new Error("synthetic native close reply lost"));
  f.source.options.onWindowClosed!("authority_expired");
  await until(() => f.controller.snapshot.statusCode === "capture_source_close_failed");
  expect(await f.flow.getCaptureRecoveryState(f.session.id)).toMatchObject({ phase: "interruption_closing" });
  await expect(f.controller.stopRecording()).rejects.toThrow("capture_gap_review_required");
  expect(f.complete).not.toHaveBeenCalled();
  expect(await f.flow.getCaptureRecoveryState(f.session.id)).toMatchObject({ phase: "ack_required" });
});

it("recovers completion after restart with an already applied continuous lease", async () => {
  const f = await fixture(); await f.controller.startRecording(); await f.emitTo(100);
  f.complete.mockRejectedValueOnce(new Error("synthetic completion reply lost"));
  await expect(f.controller.stopRecording()).rejects.toThrow("synthetic completion reply lost");
  await f.controller.close(); await f.reopen(); const next = f.create(); await next.restore();
  await next.resumePendingWork();
  expect(f.complete.mock.calls[1]).toEqual(f.complete.mock.calls[0]);
  expect(f.source.start).toHaveBeenCalledTimes(1); expect(f.renew).toHaveBeenCalledTimes(1);
  expect(next.snapshot.state).toBe("processing");
});

it("starts the frame estimate after permission resolves and does not renew repeatedly without capture progress", async () => {
  const f = await fixture(), original = f.source.start.getMockImplementation()!;
  f.source.start.mockImplementationOnce(async options => { await original(options); vi.setSystemTime(Date.now() + 600_000); });
  await f.controller.startRecording();
  expect(f.renew).not.toHaveBeenCalled();
  const nextTimer = f.timers.filter(t => !t.cancelled).sort((a, b) => a.due - b.due)[0]!;
  expect(nextTimer.due - Date.now()).toBe(240_000);
  vi.setSystemTime(nextTimer.due); nextTimer.callback();
  await until(() => f.source.extend.mock.calls.length === 1);
  await new Promise(resolve => setTimeout(resolve, 5));
  expect(f.renew).toHaveBeenCalledTimes(1);
  const after = f.timers.filter(t => !t.cancelled && t !== nextTimer).sort((a, b) => a.due - b.due)[0]!;
  expect(after.due).toBeGreaterThan(Date.now());
});
