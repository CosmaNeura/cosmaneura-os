import { webcrypto } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { IDBFactory } from "fake-indexeddb";
import { afterEach, describe, expect, it, vi } from "vitest";
import { base64UrlDecode, base64UrlEncode, parseEnvelope } from "@cosmaneura-scribe/capture-protocol";
import { HttpCaptureBff, BffResponseError } from "../../bff/http-client";
import type { CaptureLeaseReceipt, ChunkReservationBatchReceipt } from "../../bff/contracts";
import type { CaptureProfileBff, CaptureProfileReceipt } from "../../bff/profile-contracts";
import { encodePcm16MonoWav, pcm16WavProfile, type CaptureSource, type CaptureSourceExtension, type CaptureSourceStartOptions } from "../capture";
import { MockCaptureService } from "../mock-bff/state";
import { CaptureQueue } from "../../queue/capture-queue";
import { QueueTransportError } from "../../queue/errors";
import type { CaptureQueueTransport } from "../../queue/types";
import { EncryptedIndexedDbQueueStorage } from "../../storage/encrypted-indexeddb";
import { EncryptedIndexedDbFlowStore } from "./encrypted-store";
import { CaptureFlowController } from "./controller";
import { CaptureStopAcknowledgementPending } from "../capture/stop-confirmation";
import { validateRenewalRecord } from "../../flow/renewal-contract";
import { validateConfiguredRenewalRecord } from "./automatic-renewal";

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
  async emit(advance = 10_000, fullDuration = false) {
    expect(this.next).toBeLessThan(this.maximum);
    vi.setSystemTime(Date.now() + advance);
    const profile = pcm16WavProfile(this.options.capabilities);
    const samples = fullDuration ? new Int16Array(profile.sampleRateHz * advance / 1000).fill(1000 + this.next)
      : new Int16Array([1, 2, 3, 4]);
    await this.options.onChunk({ sequenceNumber: this.next++, durationMs: fullDuration ? advance : 1,
      wavBytes: encodePcm16MonoWav(samples, profile) });
  }
  async emitPcm(samples: Int16Array<ArrayBuffer>, durationMs: number) {
    expect(this.next).toBeLessThan(this.maximum);
    vi.setSystemTime(Date.now() + durationMs);
    const wavBytes = encodePcm16MonoWav(samples, pcm16WavProfile(this.options.capabilities));
    const expected = wavBytes.slice();
    await this.options.onChunk({ sequenceNumber: this.next++, durationMs, wavBytes });
    expect(wavBytes.every(byte => byte === 0)).toBe(true);
    return expected;
  }
}

async function fixture(mode: "profile" | "standard" | "legacy" = "profile", recoverWaveform = false) {
  vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(new Date());
  const service = new MockCaptureService();
  const consent = service.createConsent({ appointment_id: "synthetic-visit", practitioner_id: "synthetic-provider",
    patient_id: "synthetic-person", modality: "in_person", participant_regions: ["US-NY"], method: "verbal_attestation",
    all_parties_consented: true, granted_at: new Date().toISOString(), evidence_object_id: null }, "synthetic-consent");
  const session = service.createSession({ appointment_id: consent.appointment_id, practitioner_id: consent.practitioner_id,
    patient_id: consent.patient_id, consent_record_id: consent.id, modality: "in_person" }, "synthetic-session");
  const bff = new HttpCaptureBff(vi.fn().mockRejectedValue(new Error("unconfigured synthetic BFF")));
  // This optional, invented RSA keypair lets the recovery test act as the
  // receiving worker. The controller still creates/binds its real encrypt-only
  // nonextractable session key; no production key or key factory is replaced.
  const recipientKey = recoverWaveform ? await crypto.subtle.generateKey({ name: "RSA-OAEP", modulusLength: 3072,
    publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" }, true, ["wrapKey", "unwrapKey"]) : undefined;
  const recipientJwk = recipientKey ? await crypto.subtle.exportKey("jwk", recipientKey.publicKey) : undefined;
  vi.spyOn(bff, "getAudioEncryptionKey").mockImplementation(async () => {
    const published = service.audioEncryptionKey();
    return recipientJwk ? { ...published, public_jwk: { ...published.public_jwk, n: recipientJwk.n! } } : published;
  });
  vi.spyOn(bff, "bindSessionAudioKey").mockImplementation(async (id, request, options) => service.bindSessionAudioKey(id, request, options.idempotencyKey));
  vi.spyOn(bff, "getCapabilities").mockImplementation(async () => ({ ...service.capabilities(), max_chunks: mode === "profile" ? 720 : 2048,
    remaining_aggregate_plaintext_bytes: mode === "profile" ? 268435456 : 402653184 }));
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
  const queueName = crypto.randomUUID();
  let storage = await EncryptedIndexedDbQueueStorage.open({ indexedDB, databaseName: queueName, crypto });
  cleanup.push(() => storage.close());
  let queue = new CaptureQueue(storage, { crypto });
  const transport: CaptureQueueTransport = {
    getReceipt: vi.fn(async () => ({ state: "reserved" as const })),
    authorizeUpload: vi.fn(async (_id, objectId) => ({ objectId, uploadUrl: "https://synthetic.invalid/ciphertext",
      expiresAtEpochMs: Date.now() + 900_000, additionalAuthenticatedData: [...objects.values()].find(o => o.object_id === objectId)!.additional_authenticated_data })),
    upload: vi.fn(async () => {}), register: vi.fn(async request => ({ chunkId: crypto.randomUUID(), sha256: request.sha256,
      byteLength: request.byteLength, registeredAt: new Date().toISOString() })),
  };
  const source = new ControlledSource();
  const timers: { callback: () => void; due: number; cancelled: boolean }[] = [];
  const create = (standard = mode === "standard") => {
    const controller = new CaptureFlowController({ bff, flowStore: flow, profiles, queue,
      queueTransport: transport, source, crypto, ...(standard ? {standardContinuousCapture:true as const} : {}),
      scheduleTimeout: (callback, delay) => { const timer = { callback, due: Date.now() + delay, cancelled: false }; timers.push(timer); return timer; },
      cancelTimeout: handle => { (handle as typeof timers[number]).cancelled = true; } });
    cleanup.push(() => controller.deactivate()); return controller;
  };
  const controller = create();
  await controller.prepareConfigured(session.id, mode === "profile" ? profile.request : undefined);
  return { controller, create, source, bff, renew, reserve, complete, get queue() { return queue; }, transport, timers, leaseState,
    session, profiles, get flow() { return flow; },
    decryptSessionKey: async () => {
      if (!recipientKey) throw new Error("no synthetic receiving worker key");
      const state = await flow.getSessionKeyState(session.id);
      if (!state) throw new Error("no bound session key");
      return crypto.subtle.unwrapKey("raw", new Uint8Array(base64UrlDecode(state.wrappedDek)), recipientKey.privateKey,
        { name: "RSA-OAEP" }, { name: "AES-GCM", length: 256 }, false, ["decrypt"]);
    },
    reopen: async () => { flow.close(); flow = await EncryptedIndexedDbFlowStore.open({ indexedDB, databaseName: name, crypto }); },
    reopenQueue: async () => { storage.close(); storage = await EncryptedIndexedDbQueueStorage.open({ indexedDB, databaseName: queueName, crypto }); queue = new CaptureQueue(storage, { crypto }); },
    emitTo: async (count: number) => { while (source.next < count) { await source.emit();
      if (source.next >= source.maximum - 6 && source.maximum < 360) await until(() => source.maximum > source.next + 6); } },
  };
}

describe.each(["profile", "standard"] as const)("%s capture", mode => {
it("reopens an uncertain explicit continuation after automatic renewal without replacing old chunks", async () => {
  const f = await fixture(mode);
  await f.controller.startRecording(); await f.emitTo(100);
  const before = await f.queue.listMetadata();
  await f.controller.pauseRecording();
  const original = f.reserve.getMockImplementation()!;
  f.reserve.mockImplementationOnce(async (...args) => {
    await original(...args);
    throw new BffResponseError(503,"capture_request_unconfirmed",null);
  });
  await expect(f.controller.resumeRecording()).rejects.toThrow();
  const uncertain = f.reserve.mock.calls.at(-1);
  await f.controller.deactivate(); await f.reopen();
  const restored = f.create(); await restored.restore();
  expect(f.reserve.mock.calls.at(-1)).toEqual(uncertain);
  expect(f.source.start).toHaveBeenCalledOnce();
  await restored.resumeRecording(); await f.source.emit();
  expect(restored.snapshot.recordedChunks).toBe(101);
  const after = await f.queue.listMetadata();
  for (const row of before) {
    const retained = after.find(r => r.reservation.objectId === row.reservation.objectId)!;
    expect(retained.reservation).toEqual(row.reservation);
    expect(retained.idempotencyKeys).toEqual(row.idempotencyKeys);
  }
  await restored.stopRecording(); expect(f.complete).toHaveBeenCalledOnce();
});

it("explicitly resumes after automatic renewal while preserving earlier reservations and keys", async () => {
  const f = await fixture(mode);
  await f.controller.startRecording(); await f.emitTo(100);
  const before = await f.queue.listMetadata();
  await f.controller.pauseRecording();
  expect(f.source.start).toHaveBeenCalledOnce();
  await f.controller.resumeRecording(); await f.source.emit();
  expect(f.controller.snapshot.recordedChunks).toBe(101);
  expect(f.source.start).toHaveBeenCalledTimes(2);
  const after = await f.queue.listMetadata();
  for (const row of before) {
    const retained = after.find(r => r.reservation.objectId === row.reservation.objectId)!;
    expect(retained.reservation).toEqual(row.reservation);
    expect(retained.idempotencyKeys).toEqual(row.idempotencyKeys);
  }
  await f.controller.stopRecording(); expect(f.complete).toHaveBeenCalledOnce();
});

it("automatically extends twice while preserving one source and every reserved object",async()=>{
  const f=await fixture(mode);await f.controller.startRecording();
  const before=await f.queue.list();await f.emitTo(200);
  expect(f.source.start).toHaveBeenCalledOnce();expect(f.source.extend).toHaveBeenCalledTimes(2);
  expect(f.controller.snapshot.recordedChunks).toBe(200);
  const after=await f.queue.list();
  for(const row of before)expect(after.find(r=>r.reservation.objectId===row.reservation.objectId)?.idempotencyKeys).toEqual(row.idempotencyKeys);
  expect(await f.flow.getActiveCaptureState()).toMatchObject({schemaVersion:mode === "profile" ? 6 : 7,lease:{generation:3},automaticRenewal:{state:"extended"}});
  await f.controller.stopRecording();expect(f.complete).toHaveBeenCalledOnce();
  expect(f.controller.snapshot.state).toBe("processing");
});

it.each([false,true])("Stop reconciles an uncertain renewal, committed=%s, without issuing another one",async committed=>{
  const f=await fixture(mode),blocked=gate(),original=f.renew.getMockImplementation()!;
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
  const f=await fixture(mode),blocked=gate(),original=f.renew.getMockImplementation()!;
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
    const f = await fixture(mode), blocked = gate();
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

});

it("operational recovery: preserves decrypted PCM tail through interruption, offline reopen and lost receipts", async () => {
  const f = await fixture("standard", true);
  const expectedWavs = new Map<number, Uint8Array<ArrayBuffer>>();
  const steps: Record<string, unknown>[] = [];
  const record = async (action: string, controller = f.controller) => {
    const active = await f.flow.getActiveCaptureState();
    steps.push({ action, state: controller.snapshot.state, statusCode: controller.snapshot.statusCode,
      recordedChunks: controller.snapshot.recordedChunks, persistedPhase: active?.phase,
      sourceStarts: f.source.start.mock.calls.length, completeAttempts: f.complete.mock.calls.length });
  };
  await f.controller.startRecording();
  const profile = pcm16WavProfile(f.source.options.capabilities);
  const fullChunks = 86;
  for (let sequence = 0; sequence < fullChunks; sequence++) {
    const samples = new Int16Array(profile.sampleRateHz * 10);
    for (let frame = 0; frame < samples.length; frame++) samples[frame] = (sequence * 97 + frame * 31) % 65536 - 32768;
    expectedWavs.set(sequence, await f.source.emitPcm(samples, 10_000));
    if (f.source.next >= f.source.maximum - 6) await until(() => f.source.maximum > f.source.next + 6);
  }
  const tailDurationMs = 317;
  const tail = new Int16Array(profile.sampleRateHz * tailDurationMs / 1000);
  for (let frame = 0; frame < tail.length; frame++) tail[frame] = (frame * 19) % 65536 - 32768;
  tail[0] = -12345; tail[tail.length - 2] = -32760; tail[tail.length - 1] = 32760;
  expectedWavs.set(fullChunks, await f.source.emitPcm(tail, tailDurationMs));
  expect(f.source.start).toHaveBeenCalledOnce();
  expect(f.source.extend).toHaveBeenCalledOnce();
  expect(f.renew).toHaveBeenCalledOnce();
  const sessionKey = await f.flow.getSessionKeyState(f.session.id);
  expect(await f.flow.getSessionKey(f.session.id)).toMatchObject({ extractable: false, usages: ["encrypt"] });
  const decryptKey = await f.decryptSessionKey();
  const saved = (await f.queue.list()).filter(row => row.state === "encrypted");
  expect(saved).toHaveLength(fullChunks + 1);
  const decrypt = async (envelope: Uint8Array, aad: string) => {
    const parsed = parseEnvelope(envelope);
    return new Uint8Array(await crypto.subtle.decrypt({ name: "AES-GCM", iv: new Uint8Array(base64UrlDecode(parsed.header.nonce)),
      additionalData: new Uint8Array(base64UrlDecode(aad)) }, decryptKey, new Uint8Array(parsed.ciphertext)));
  };
  for (const row of saved) {
    const expected = expectedWavs.get(row.reservation.sequenceNumber)!;
    const restored = await decrypt(row.envelope, row.reservation.additionalAuthenticatedData);
    expect(Buffer.from(restored).equals(Buffer.from(expected))).toBe(true);
    expect(row.byteLength).toBe(row.envelope.byteLength);
  }
  await record("generated_pcm_encrypted_and_tail_decrypted");

  f.source.options.onInterruption?.("audio_device_disconnected");
  await until(async () => (await f.flow.getActiveCaptureState())?.phase === "paused");
  expect(f.controller.snapshot).toMatchObject({ state: "paused", statusCode: "audio_device_disconnected" });
  expect(f.transport.upload).not.toHaveBeenCalled();
  expect(f.complete).not.toHaveBeenCalled();
  await record("device_interruption_preserved_pause_without_upload");
  await f.controller.deactivate(); await f.reopen(); await f.reopenQueue();
  const paused = f.create(); await paused.restore();
  expect(paused.snapshot.state).toBe("paused");
  expect(f.source.start).toHaveBeenCalledOnce();
  expect(await f.flow.getSessionKeyState(f.session.id)).toEqual(sessionKey);
  for (const row of saved) expect(await f.queue.get(row.reservation.objectId)).toEqual(row);
  await record("reopen_both_stores_retained_exact_audio_without_restart", paused);

  f.source.stop.mockRejectedValueOnce(new CaptureStopAcknowledgementPending());
  await expect(paused.stopRecording()).rejects.toThrow();
  expect(paused.snapshot.state).toBe("paused");
  expect(f.transport.upload).not.toHaveBeenCalled();
  expect(f.complete).not.toHaveBeenCalled();
  await record("stop_unconfirmed_kept_human_retry_available", paused);
  vi.mocked(f.transport.upload).mockRejectedValue(new QueueTransportError("retryable", "synthetic_offline"));
  await expect(paused.stopRecording()).rejects.toThrow();
  expect(paused.snapshot).toMatchObject({ state: "uploading", statusCode: "capture_upload_pending" });
  expect(f.complete).not.toHaveBeenCalled();
  await record("explicit_stop_offline_retained_upload_pending", paused);
  await paused.deactivate(); await f.reopen(); await f.reopenQueue();
  const uploading = f.create(); await uploading.restore();
  expect(uploading.snapshot.state).toBe("uploading");
  expect(f.source.start).toHaveBeenCalledOnce();
  for (const row of saved) {
    const retained = await f.queue.get(row.reservation.objectId);
    expect(retained).toMatchObject({ sha256: row.sha256, byteLength: row.byteLength,
      idempotencyKeys: row.idempotencyKeys, reservation: row.reservation });
    expect(retained && "envelope" in retained && Buffer.from(retained.envelope).equals(Buffer.from(row.envelope))).toBe(true);
  }
  await record("offline_reopen_retained_ciphertext_and_registration_keys", uploading);

  const receipts = new Map<string, Awaited<ReturnType<CaptureQueueTransport["register"]>>>();
  const uploaded = new Map<string, Uint8Array>();
  vi.mocked(f.transport.authorizeUpload).mockImplementation(async (_id, objectId) => ({ objectId,
    uploadUrl: `https://synthetic.invalid/ciphertext/${objectId}`, expiresAtEpochMs: Date.now() + 900_000,
    additionalAuthenticatedData: saved.find(row => row.reservation.objectId === objectId)!.reservation.additionalAuthenticatedData }));
  vi.mocked(f.transport.upload).mockImplementation(async (url, envelope) => {
    const objectId = url.slice(url.lastIndexOf("/") + 1);
    expect(uploaded.has(objectId)).toBe(false);
    const expected = saved.find(row => row.reservation.objectId === objectId)!;
    expect(Buffer.from(envelope).equals(Buffer.from(expected.envelope))).toBe(true);
    uploaded.set(objectId, envelope.slice());
  });
  vi.mocked(f.transport.getReceipt).mockImplementation(async reservation => receipts.has(reservation.objectId)
    ? { state: "registered", registration: receipts.get(reservation.objectId)! } : { state: "reserved" });
  vi.mocked(f.transport.register).mockImplementation(async request => {
    expect(receipts.has(request.objectId)).toBe(false);
    const row = saved.find(item => item.reservation.objectId === request.objectId)!;
    expect(request).toMatchObject({ sha256: row.sha256, byteLength: row.byteLength,
      idempotencyKey: row.idempotencyKeys.registration, sequenceNumber: row.reservation.sequenceNumber });
    const receipt = { chunkId: crypto.randomUUID(), sha256: request.sha256, byteLength: request.byteLength,
      registeredAt: new Date().toISOString() };
    receipts.set(request.objectId, receipt);
    if (request.sequenceNumber === fullChunks) throw new QueueTransportError("unknown_success", "synthetic_lost_tail_receipt");
    return receipt;
  });
  vi.setSystemTime(Date.now() + 60_000);
  await expect(uploading.resumePendingWork()).rejects.toThrow();
  expect(uploading.snapshot).toMatchObject({ state: "uploading", statusCode: "capture_upload_pending" });
  expect(receipts.size).toBe(fullChunks + 1); expect(f.complete).not.toHaveBeenCalled();
  await record("tail_registered_remotely_lost_reply_did_not_complete", uploading);
  await uploading.deactivate(); await f.reopen(); await f.reopenQueue();
  const completing = f.create(); await completing.restore();
  const originalComplete = f.complete.getMockImplementation()!;
  const completionReceipts = new Map<string, Awaited<ReturnType<typeof originalComplete>>>();
  f.complete.mockImplementation(async (...args) => {
    const key = args[2].idempotencyKey;
    const receipt = completionReceipts.get(key);
    if (receipt) return structuredClone(receipt);
    completionReceipts.set(key, await originalComplete(...args));
    throw new BffResponseError(503, "capture_request_unconfirmed", null);
  });
  vi.setSystemTime(Date.now() + 60_000);
  await expect(completing.resumePendingWork()).rejects.toThrow();
  expect(completing.snapshot).toMatchObject({ state: "uploading", statusCode: "capture_upload_pending" });
  expect((await f.flow.getActiveCaptureState())?.phase).toBe("completing");
  expect(f.complete).toHaveBeenCalledOnce();
  await record("remote_tail_receipt_reconciled_completion_reply_lost", completing);
  await completing.deactivate(); await f.reopen(); await f.reopenQueue();
  const final = f.create(); await final.restore(); await final.resumePendingWork();
  expect(final.snapshot).toMatchObject({ state: "processing", transcript: null });
  expect(f.complete).toHaveBeenCalledTimes(2);
  expect(completionReceipts.size).toBe(1);
  expect(f.complete.mock.calls[1]).toEqual(f.complete.mock.calls[0]);
  expect(f.complete.mock.calls[0]![1].channels).toEqual([{ channel: "microphone", final_sequence_number: fullChunks }]);
  expect(f.source.start).toHaveBeenCalledOnce();
  expect(f.renew).toHaveBeenCalledOnce();
  expect(uploaded.size).toBe(fullChunks + 1);
  expect(vi.mocked(f.transport.register)).toHaveBeenCalledTimes(fullChunks + 1);
  expect((await f.queue.listMetadata()).filter(row => row.state === "purged")).toHaveLength(fullChunks + 1);
  const tailRow = saved.find(row => row.reservation.sequenceNumber === fullChunks)!;
  const recoveredTail = await decrypt(uploaded.get(tailRow.reservation.objectId)!, tailRow.reservation.additionalAuthenticatedData);
  expect(Buffer.from(recoveredTail).equals(Buffer.from(expectedWavs.get(fullChunks)!))).toBe(true);
  const tailView = new DataView(recoveredTail.buffer);
  expect(tailView.getUint32(40, true)).toBe(tail.length * 2);
  expect(tailView.getInt16(44, true)).toBe(-12345);
  expect(tailView.getInt16(recoveredTail.byteLength - 4, true)).toBe(-32760);
  expect(tailView.getInt16(recoveredTail.byteLength - 2, true)).toBe(32760);
  await record("exact_completion_replay_processing_no_transcript_claim", final);

  // Opt-in machine-readable local evidence; this never writes audio/key bytes.
  const evidenceDirectory = process.env.SCRIBE_RECOVERY_EVIDENCE_DIR
    ?? (process.env.COSMABOT_RECORDING_EVIDENCE_DIR ? join(process.env.COSMABOT_RECORDING_EVIDENCE_DIR, "recovery") : undefined);
  if (evidenceDirectory) {
    mkdirSync(evidenceDirectory, { recursive: true });
    writeFileSync(join(evidenceDirectory, "pcm-recovery-steps.json"), JSON.stringify({
      schema_version: 1, outcome: "passed", synthetic_only: true, network_used: false, physical_microphone_used: false,
      transcription: "not run; any downstream fixture text is not ASR evidence", sample_rate_hz: profile.sampleRateHz,
      full_chunks: fullChunks, tail_frames: tail.length, tail_duration_ms: tailDurationMs,
      generated_pcm_frames: fullChunks * profile.sampleRateHz * 10 + tail.length,
      generated_pcm_duration_ms: fullChunks * 10_000 + tailDurationMs,
      unique_uploaded_objects: uploaded.size, unique_registered_objects: receipts.size,
      completion_attempts: f.complete.mock.calls.length, fixture_completion_commits: completionReceipts.size,
      completion_idempotency_key_reused: true,
      exact_wav_bytes_verified: true, tail_boundary_samples_verified: true, local_envelopes_purged_after_receipts: true,
      steps,
    }, null, 2) + "\n");
  }
}, 120_000);

it.each(["profile", "standard"] as const)("stress: preserves the full one-hour %s PCM limit through repeated lease windows and exact upload", async mode => {
  // The waveform contains a distinct sequence marker in every chunk. Time is
  // accelerated; every advertised audio frame is still encoded and encrypted.
  const f = await fixture(mode);
  await f.controller.startRecording();
  while (f.source.next < 360) {
    await f.source.emit(10_000, true);
    if (f.source.next >= f.source.maximum - 6 && f.source.maximum < 360) {
      await until(() => f.source.maximum > f.source.next + 6);
    }
  }
  const saved = (await f.queue.listMetadata()).filter(row => row.state === "encrypted");
  expect(saved).toHaveLength(360);
  expect(saved.map(row => row.reservation.sequenceNumber).sort((a,b) => a-b)).toEqual(Array.from({length:360}, (_,i)=>i));
  expect(new Set(saved.map(row=>row.sha256)).size).toBe(360);
  expect(f.source.start).toHaveBeenCalledOnce();
  expect(f.source.extend).toHaveBeenCalledTimes(4);
  expect(f.source.maximum).toBe(360);
  await f.controller.stopRecording();
  expect(f.controller.snapshot.state).toBe("processing");
  expect(f.complete).toHaveBeenCalledOnce();
  const registered = vi.mocked(f.transport.register).mock.calls.map(([request])=>request);
  expect(registered).toHaveLength(360);
  for (const row of saved) {
    expect(registered.find(request=>request.objectId===row.reservation.objectId)).toMatchObject({
      sha256:row.sha256,byteLength:row.byteLength,sequenceNumber:row.reservation.sequenceNumber,
      idempotencyKey:row.idempotencyKeys.registration,
    });
  }
  expect((await f.queue.listMetadata()).filter(row=>row.state==="purged")).toHaveLength(360);
}, 180_000);

it("stress: recovers offline upload and a lost registration receipt after reopening both encrypted stores", async () => {
  const f = await fixture("standard");
  await f.controller.startRecording();
  while (f.source.next < 120) {
    await f.source.emit(10_000, true);
    if (f.source.next >= f.source.maximum - 6) await until(()=>f.source.maximum > f.source.next + 6);
  }
  const before = (await f.queue.listMetadata()).filter(row=>row.state==="encrypted");
  vi.mocked(f.transport.upload).mockRejectedValue(new QueueTransportError("retryable", "synthetic_offline"));
  await expect(f.controller.stopRecording()).rejects.toThrow();
  expect(f.complete).not.toHaveBeenCalled();
  await f.controller.deactivate(); await f.reopen(); await f.reopenQueue();
  const first = f.create(); await first.restore();
  expect(f.source.start).toHaveBeenCalledOnce();
  expect((await f.queue.listMetadata()).filter(row=>"sha256" in row).map(row=>[row.reservation.objectId,row.sha256]))
    .toEqual(before.map(row=>[row.reservation.objectId,row.sha256]));
  const receipts = new Map<string, Awaited<ReturnType<CaptureQueueTransport["register"]>>>();
  const register = vi.mocked(f.transport.register).getMockImplementation()!;
  vi.mocked(f.transport.upload).mockResolvedValue();
  vi.mocked(f.transport.getReceipt).mockImplementation(async reservation => receipts.has(reservation.objectId)
    ? {state:"registered",registration:receipts.get(reservation.objectId)!} : {state:"reserved"});
  vi.mocked(f.transport.register).mockImplementation(async request => {
    expect(receipts.has(request.objectId)).toBe(false);
    const receipt = await register(request); receipts.set(request.objectId,receipt);
    if (request.sequenceNumber === 47) throw new QueueTransportError("retryable", "synthetic_lost_receipt");
    return receipt;
  });
  vi.setSystemTime(Date.now()+60_000);
  await expect(first.resumePendingWork()).rejects.toThrow();
  expect(f.complete).not.toHaveBeenCalled();
  await first.deactivate(); await f.reopen(); await f.reopenQueue();
  const second = f.create(); await second.restore(); vi.setSystemTime(Date.now()+60_000);
  await second.resumePendingWork();
  expect(second.snapshot.state).toBe("processing");
  expect(receipts.size).toBe(120); expect(f.complete).toHaveBeenCalledOnce();
  expect(vi.mocked(f.transport.register).mock.calls.filter(([r])=>r.sequenceNumber===47)).toHaveLength(1);
  expect(f.source.start).toHaveBeenCalledOnce();
}, 120_000);

it.each(["missing", "duplicate"])("stress: rejects %s audio positions without marking an incomplete recording uploaded", async fault => {
  const f=await fixture("standard"); await f.controller.startRecording(); await f.source.emit(10_000,true);
  const original=(await f.queue.listMetadata()).filter(row=>row.state==="encrypted");
  const profile=pcm16WavProfile(f.source.options.capabilities);
  await expect(f.source.options.onChunk({sequenceNumber:fault==="missing"?2:0,durationMs:10_000,
    wavBytes:encodePcm16MonoWav(new Int16Array(profile.sampleRateHz*10),profile)})).rejects.toThrow();
  expect(f.complete).not.toHaveBeenCalled();
  expect((await f.queue.listMetadata()).filter(row=>row.state==="encrypted")).toEqual(original);
});

it("standard capture uses no profile operation and cannot reopen under an unaware host", async () => {
  const f = await fixture("standard");
  expect(f.profiles.selectCaptureProfile).not.toHaveBeenCalled();
  expect(f.profiles.acknowledgeCaptureProfile).not.toHaveBeenCalled();
  const saved = await f.flow.getActiveCaptureState();
  expect(saved).toMatchObject({schemaVersion:7,aggregatePlaintextBudgetBytes:360 * 327680});
  expect(saved?.captureProfile).toBeUndefined();
  await f.controller.deactivate();
  const before = f.bff.getCapabilities as ReturnType<typeof vi.fn>;
  const calls = before.mock.calls.length;
  await expect(f.create(false).restore()).rejects.toThrow("capture_policy_unavailable");
  expect(before).toHaveBeenCalledTimes(calls);
  expect(f.source.start).not.toHaveBeenCalled();
});

it.each(["profile", "legacy"] as const)("the new native host preserves an existing %s journal", async mode => {
  const f = await fixture(mode);
  const saved = await f.flow.getActiveCaptureState();
  await f.controller.deactivate();
  const restored = f.create(true);
  await restored.restore();
  const reopened = await f.flow.getActiveCaptureState();
  expect(reopened?.schemaVersion).toBe(saved?.schemaVersion);
  expect(reopened?.captureProfile).toEqual(saved?.captureProfile);
  expect(reopened?.aggregatePlaintextBudgetBytes).toBe(saved?.aggregatePlaintextBudgetBytes);
  expect(reopened?.automaticRenewal).toBeUndefined();
  expect(f.source.start).not.toHaveBeenCalled();
});

it("standard renewal rejects legacy reinterpretation, profile injection and altered durable intent", async () => {
  const f = await fixture("standard");
  await f.controller.startRecording(); await f.emitTo(100);
  const saved = (await f.flow.getActiveCaptureState())!;
  const record = saved.automaticRenewal!.record;
  expect(record.intent.schemaVersion).toBe(2);
  expect(() => validateRenewalRecord(record)).toThrow("capture_renewal_conflict");
  expect(() => validateConfiguredRenewalRecord(null)).toThrow("capture_renewal_conflict");
  expect(() => validateConfiguredRenewalRecord({...record,intent:{...record.intent,profileReceiptId:crypto.randomUUID()}}))
    .toThrow("capture_renewal_conflict");
  await expect(f.flow.putActiveCaptureState({...saved, schemaVersion:4, automaticRenewal:undefined}))
    .rejects.toThrow();
  await expect(f.flow.putActiveCaptureState({...saved, recordedChunks:361})).rejects.toThrow();
  const changed = structuredClone(record);
  changed.intent.leaseIdempotencyKey = "different-renew-key";
  await expect(f.flow.putActiveCaptureState({...saved, automaticRenewal:{...saved.automaticRenewal!,record:changed}}))
    .rejects.toThrow();
  expect((await f.flow.getActiveCaptureState())?.automaticRenewal).toEqual(saved.automaticRenewal);
  await f.controller.pauseRecording();
  const paused = (await f.flow.getActiveCaptureState())!;
  await expect(f.flow.putActiveCaptureState({...paused, schemaVersion:4, automaticRenewal:undefined,
    continuation:{prepared:false,firstSequenceNumber:paused.recordedChunks,reservationCount:90,
      previousLease:paused.lease,renewIdempotencyKey:"legacy-downgrade-key"}})).rejects.toThrow("active_capture_conflict");
  await f.controller.resumeRecording();
  expect((await f.flow.getActiveCaptureState())?.schemaVersion).toBe(7);
});
