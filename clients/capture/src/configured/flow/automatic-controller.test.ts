import { webcrypto } from "node:crypto";
import { readFileSync } from "node:fs";
import { IDBFactory } from "fake-indexeddb";
import { afterEach, expect, it, vi } from "vitest";
import { base64UrlEncode } from "@cosmaneura-scribe/capture-protocol";
import { HttpCaptureBff, BffResponseError } from "../../bff/http-client";
import type { CaptureLeaseReceipt, ChunkReservationBatchReceipt } from "../../bff/contracts";
import type { CaptureProfileBff, CaptureProfileReceipt } from "../../bff/profile-contracts";
import { encodePcm16MonoWav, pcm16WavProfile, type CaptureSource, type CaptureSourceExtension, type CaptureSourceStartOptions } from "../capture";
import { MockCaptureService } from "../mock-bff/state";
import { CaptureQueue } from "../../queue/capture-queue";
import type { CaptureQueueTransport } from "../../queue/types";
import { EncryptedIndexedDbQueueStorage } from "../../storage/encrypted-indexeddb";
import { EncryptedIndexedDbFlowStore } from "./encrypted-store";
import { CaptureFlowController } from "./controller";
import { CaptureStopAcknowledgementPending } from "../capture/stop-confirmation";

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
  async supportsContinuousCapture(){return true;}
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
  const leaseState=vi.fn(async()=>({session_id:session.id,current_lease:structuredClone(lease),
    lease_closed:completed,session_status:completed?"uploaded" as const:"capturing" as const}));
  Object.assign(bff,{getCaptureLeaseState:leaseState});
  const golden: CaptureProfileReceipt = JSON.parse(readFileSync(new URL("../../../../../tests/fixtures/capture_profile.json", import.meta.url), "utf8"));
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
    const controller = new CaptureFlowController({ bff, flowStore: flow, profiles, queue,
      queueTransport: transport, source, crypto,
      scheduleTimeout: (callback, delay) => { const timer = { callback, due: Date.now() + delay, cancelled: false }; timers.push(timer); return timer; },
      cancelTimeout: handle => { (handle as typeof timers[number]).cancelled = true; } });
    cleanup.push(() => controller.deactivate()); return controller;
  };
  const controller = create();
  await controller.prepareConfigured(session.id, profile.request);
  return { controller, create, source, bff, renew, reserve, complete, queue, transport, timers, leaseState,
    session, get flow() { return flow; },
    reopen: async () => { flow.close(); flow = await EncryptedIndexedDbFlowStore.open({ indexedDB, databaseName: name, crypto }); },
    emitTo: async (count: number) => { while (source.next < count) { await source.emit();
      if (source.next >= source.maximum - 6 && source.maximum < 360) await until(() => source.maximum > source.next + 6); } },
  };
}

it("automatically extends twice while preserving one source and every reserved object",async()=>{
  const f=await fixture();await f.controller.startRecording();
  const before=await f.queue.list();await f.emitTo(200);
  expect(f.source.start).toHaveBeenCalledOnce();expect(f.source.extend).toHaveBeenCalledTimes(2);
  expect(f.controller.snapshot.recordedChunks).toBe(200);
  const after=await f.queue.list();
  for(const row of before)expect(after.find(r=>r.reservation.objectId===row.reservation.objectId)?.idempotencyKeys).toEqual(row.idempotencyKeys);
  expect(await f.flow.getActiveCaptureState()).toMatchObject({schemaVersion:6,lease:{generation:3},automaticRenewal:{state:"extended"}});
  await f.controller.stopRecording();expect(f.complete).toHaveBeenCalledOnce();
  expect(f.controller.snapshot.state).toBe("processing");
});

it.each([false,true])("Stop reconciles an uncertain renewal, committed=%s, without issuing another one",async committed=>{
  const f=await fixture(),blocked=gate(),original=f.renew.getMockImplementation()!;
  await f.controller.startRecording();
  f.renew.mockImplementationOnce(async(...args)=>{
    if(committed)await original(...args);
    await blocked.pending;throw new BffResponseError(503,"capture_request_unconfirmed",null);
  });
  while(f.source.next<84)await f.source.emit();
  await until(()=>f.renew.mock.calls.length===1);
  const stopped=f.controller.stopRecording();blocked.release();await stopped;
  expect(f.renew).toHaveBeenCalledTimes(committed?2:1);
  if(committed)expect(f.renew.mock.calls[1]).toEqual(f.renew.mock.calls[0]);
  expect(f.leaseState).toHaveBeenCalledOnce();expect(f.reserve).toHaveBeenCalledOnce();
  expect(f.source.extend).not.toHaveBeenCalled();expect(f.source.start).toHaveBeenCalledOnce();
  expect(f.complete).toHaveBeenCalledOnce();expect(f.controller.snapshot.state).toBe("processing");
});

it("reopens a pending committed renewal in the encrypted journal and finishes without starting capture",async()=>{
  const f=await fixture(),blocked=gate(),original=f.renew.getMockImplementation()!;
  await f.controller.startRecording();
  f.renew.mockImplementationOnce(async(...args)=>{await original(...args);await blocked.pending;throw new TypeError("Invented lost reply");});
  while(f.source.next<84)await f.source.emit();await until(()=>f.renew.mock.calls.length===1);
  const closed=f.controller.deactivate();blocked.release();await closed;
  expect((await f.flow.getActiveCaptureState())?.automaticRenewal?.state).toBe("pending");
  await f.reopen();const restored=f.create();await restored.restore();
  expect(restored.snapshot.state).toBe("paused");expect(f.source.start).toHaveBeenCalledOnce();
  expect((await f.flow.getActiveCaptureState())?.lease.generation).toBe(2);
  await restored.stopRecording();expect(f.complete).toHaveBeenCalledOnce();
});

it.each(["stopRecording", "pauseRecording", "deactivate"] as const)(
  "%s settles a busy native extension and retries the same stop without another provider action", async action => {
    const f = await fixture(), blocked = gate();
    let extending = false;
    f.source.extend.mockImplementationOnce(async () => {
      extending = true;
      await blocked.pending;
      extending = false;
    });
    f.source.stop.mockImplementation(async () => {
      if (extending) throw new CaptureStopAcknowledgementPending();
    });
    await f.controller.startRecording();
    while (f.source.next < 84) await f.source.emit();
    await until(() => extending);
    const stopped = f.controller[action]();
    await until(() => f.source.stop.mock.calls.length === 1);
    expect(f.complete).not.toHaveBeenCalled();
    blocked.release();
    await stopped;
    expect(f.source.stop).toHaveBeenCalledTimes(2);
    expect(f.source.start).toHaveBeenCalledOnce();
    expect(f.source.extend).toHaveBeenCalledOnce();
    expect(f.renew).toHaveBeenCalledOnce();
    expect(f.controller.snapshot.state).toBe(action === "stopRecording" ? "processing" : "paused");
    expect(f.complete).toHaveBeenCalledTimes(action === "stopRecording" ? 1 : 0);
  },
);
