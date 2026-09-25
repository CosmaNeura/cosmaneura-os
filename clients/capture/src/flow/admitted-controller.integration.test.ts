import { webcrypto } from "node:crypto";
import { readFileSync } from "node:fs";
import type { AddressInfo } from "node:net";
import { IDBFactory } from "fake-indexeddb";
import { afterEach, expect, it, vi } from "vitest";
import { HttpCaptureBff } from "../bff/http-client";
import { BffCaptureQueueTransport } from "../bff/queue-transport";
import { HttpCiphertextUploadTarget } from "../bff/upload-target";
import { encodePcm16MonoWav, pcm16WavProfile } from "../capture";
import type { CaptureSource, CaptureSourceStartOptions } from "../capture";
import { createMockBffServer } from "../mock-bff/server";
import { CaptureQueue } from "../queue/capture-queue";
import { EncryptedIndexedDbQueueStorage } from "../storage/encrypted-indexeddb";
import { CaptureFlowController } from "./controller";
import { EncryptedIndexedDbFlowStore } from "./encrypted-store";
import { NativePluginQueueStorage } from "../storage/native-plugin";
import { MemoryNativeQueuePlugin } from "../../test-fixtures/native-queue";
import { scopedNativePlugin } from "../../../../web/src/capture-storage";
import { FakeIosNativePcmBridge } from "../native/fake-ios-native-pcm-bridge";
import { IosNativeMicrophoneCaptureSource } from "../native/ios-native-microphone-source";
import { recoveryRequestHash, type CaptureRecoveryBff, type CaptureRecoveryReceipt } from "../bff/recovery-contracts";
import { captureRawHash, captureRecoveryHash, type CaptureQualifiedSourceBff, type CaptureSourceEnvelope } from "../bff/source-contracts";
import { workingHash } from "../bff/working-contracts";
import { BffResponseError } from "../bff/http-client";
import { validateProfileReceipt, type CaptureProfileBff, type CaptureProfileReceipt } from "../bff/profile-contracts";
import { validateRenewalIntent } from "./renewal-contract";

const crypto = webcrypto as unknown as Crypto;
const cleanup: (() => void | Promise<void>)[] = [];
afterEach(async () => { for (const close of cleanup.splice(0).reverse()) await close(); });

class SilentChunk implements CaptureSource {
  readonly kind = "synthetic" as const;
  readonly start = vi.fn(async (options: CaptureSourceStartOptions) => {
    const profile = pcm16WavProfile(options.capabilities);
    const samples = new Int16Array(new ArrayBuffer(profile.sampleRateHz * 2));
    await options.onChunk({ sequenceNumber: 0, durationMs: 1000,
      wavBytes: encodePcm16MonoWav(samples, profile) });
  });
  async stop() {}
}

async function fixture(nativeQueue = false) {
  const clock = new Date();
  const server = createMockBffServer({ now: () => clock });
  await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
  cleanup.push(async () => {
    server.closeAllConnections();
    await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
  });
  const origin = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  const localFetch: typeof fetch = (input, init) =>
    fetch(new URL(typeof input === "string" || input instanceof URL ? String(input) : input.url, origin), init);
  const bff = new HttpCaptureBff(localFetch);
  // Fixture-owned admission represents a pre-existing server result. The new
  // controller entry point must never call these creation methods itself.
  const consent = await bff.createConsent({ appointment_id: "synthetic-appointment",
    practitioner_id: "synthetic-practitioner", patient_id: "synthetic-patient",
    modality: "in_person", participant_regions: ["US-NY"], method: "verbal_attestation",
    all_parties_consented: true, granted_at: new Date().toISOString(), evidence_object_id: null,
  }, { idempotencyKey: "fixture-consent-key" });
  const session = await bff.createSession({ appointment_id: consent.appointment_id,
    practitioner_id: consent.practitioner_id, patient_id: consent.patient_id,
    consent_record_id: consent.id, modality: "in_person",
  }, { idempotencyKey: "fixture-session-key" });
  const consentCalls = vi.spyOn(bff, "createConsent");
  const sessionCalls = vi.spyOn(bff, "createSession");
  const indexedDB = new IDBFactory();
  const flowName = crypto.randomUUID();
  let flow = await EncryptedIndexedDbFlowStore.open({ databaseName: flowName, indexedDB, crypto });
  cleanup.push(() => flow.close());
  const browserStorage = nativeQueue ? null : await EncryptedIndexedDbQueueStorage.open({ databaseName: crypto.randomUUID(), indexedDB, crypto });
  if (browserStorage) cleanup.push(() => browserStorage.close());
  const storage = browserStorage ?? new NativePluginQueueStorage(scopedNativePlugin(new MemoryNativeQueuePlugin(),crypto.randomUUID(),session.id),session.id);
  const source = new SilentChunk();
  const controller = (selectedSource: CaptureSource = source, recovery?: CaptureRecoveryBff, qualifiedSource?: CaptureQualifiedSourceBff,
    profiles?: CaptureProfileBff, recoveryOnly = false) => new CaptureFlowController({ bff, flowStore: flow, renewals: flow, recoveryOnly,
    queue: new CaptureQueue(storage, { crypto }),
    queueTransport: new BffCaptureQueueTransport(bff, new HttpCiphertextUploadTarget([origin])),
    source: selectedSource, ...(recovery ? { recovery } : {}), crypto,
    ...(qualifiedSource ? { qualifiedSource } : {}),
    ...(profiles ? { profiles } : {}),
    scheduleTimeout: () => undefined, cancelTimeout: () => undefined });
  return { bff, session, consentCalls, sessionCalls, get flow() { return flow; }, source, controller,
    reopenFlow: async () => { flow.close(); flow = await EncryptedIndexedDbFlowStore.open({ databaseName: flowName, indexedDB, crypto }); } };
}

it('opens an older unfinished preparation without repeating its remote mutations',async()=>{
  const f=await fixture();
  const preparation={schemaVersion:2 as const,mode:'core_admitted' as const,reviewAfterUpload:true as const,
    sessionId:f.session.id,startedAt:new Date().toISOString(),completeIdempotencyKey:'retained-preparation-complete',
    leaseIdempotencyKey:null,leaseRequest:null};
  await f.flow.putPreparationState(preparation);
  const key=vi.spyOn(f.bff,'getAudioEncryptionKey'),lease=vi.spyOn(f.bff,'issueLease'),reserve=vi.spyOn(f.bff,'reserveChunks');
  const controller=f.controller(undefined,undefined,undefined,undefined,true);
  try{
    await controller.restore();expect(controller.snapshot.state).toBe('ready');
    expect(await f.flow.getPreparationState()).toEqual(preparation);
    expect(await f.flow.getActiveCaptureState()).toBeNull();
    expect(key).not.toHaveBeenCalled();expect(lease).not.toHaveBeenCalled();expect(reserve).not.toHaveBeenCalled();
    expect(f.source.start).not.toHaveBeenCalled();
  }finally{await controller.close();}
});

async function profileFixture() {
  const f = await fixture();
  const golden: CaptureProfileReceipt = JSON.parse(readFileSync(new URL("../../../../tests/fixtures/capture_profile.json", import.meta.url), "utf8"));
  const receipt = { ...golden, session_id: f.session.id };
  const order: string[] = [];
  const profiles: CaptureProfileBff = {
    selectCaptureProfile: vi.fn(async (id, request, options) => {
      const saved = await f.flow.getPreparationState();
      expect(saved).toMatchObject({ mode: "core_admitted", sessionId: id,
        profileSelection: { request, idempotencyKey: options.idempotencyKey, receipt: null }, leaseRequest: null });
      order.push("select");
      return receipt;
    }),
    getCaptureProfile: vi.fn(async () => { order.push("read"); return receipt; }),
    acknowledgeCaptureProfile: vi.fn(async value => {
      await validateProfileReceipt(value, f.session.id);
      order.push("acknowledge");
    }),
  };
  const getCapabilities = f.bff.getCapabilities.bind(f.bff);
  vi.spyOn(f.bff, "getCapabilities").mockImplementation(async (...args) => {
    order.push("capabilities");
    return { ...await getCapabilities(...args), max_chunks: 720, remaining_aggregate_plaintext_bytes: 268435456 };
  });
  const issueLease = f.bff.issueLease.bind(f.bff);
  const lease = vi.spyOn(f.bff, "issueLease").mockImplementation(async (...args) => {
    expect(await f.flow.getPreparationState()).toMatchObject({ profileSelection: { receipt } });
    order.push("lease"); return issueLease(...args);
  });
  return { ...f, get flow() { return f.flow; }, receipt, profiles, order, lease,
    profiled: () => f.controller(f.source, undefined, undefined, profiles) };
}

it("persists the exact profile before leasing, recovers it, and bounds the microphone to sixty minutes", async () => {
  const f = await profileFixture();
  const controller = f.profiled();
  await controller.prepareAdmitted(f.session.id, f.receipt.request);
  expect(f.order).toEqual(["select", "acknowledge", "capabilities", "lease"]);
  expect(controller.snapshot.remainingBudgetSeconds).toBe(3600);
  expect(await f.flow.getActiveCaptureState()).toMatchObject({ captureProfile: f.receipt });
  expect(f.source.start).not.toHaveBeenCalled();
  await expect(f.profiled().restore()).resolves.toBe(true);
  expect(f.profiles.selectCaptureProfile).toHaveBeenCalledTimes(1);
  expect(f.source.start).not.toHaveBeenCalled();
});

it("passes the actual server deadline and fixed window to the source before microphone startup", async () => {
  const f = await profileFixture(), controller = f.profiled();
  await controller.prepareAdmitted(f.session.id, f.receipt.request);
  const active = (await f.flow.getActiveCaptureState())!;
  await controller.startRecording();
  const options = f.source.start.mock.calls[0]![0], local = (await f.flow.getCaptureRecoveryState(f.session.id))!;
  expect(options.authority).toEqual({ runId: local.currentSegmentId, generation: active.lease.generation,
    expiresAtMs: Math.min(Date.parse(active.lease.expires_at), Date.parse(active.captureAuthorizedUntil!)),
    hardMaximumChunks: options.capabilities.max_chunks });
  expect(options.capabilities.max_chunks).toBeLessThanOrEqual(90);
  await controller.close();
});

it.each([true, false])("reconciles a pending ordinary renewal before the explicit gap decision (committed=%s)", async committed => {
  const f = await profileFixture();
  let remoteLease: Awaited<ReturnType<typeof f.bff.issueLease>>;
  const recovery: CaptureRecoveryBff = {
    getCaptureRecoveryState: vi.fn(async () => ({ history: { session_id: f.session.id, recoveries: [] },
      current_lease: remoteLease, lease_closed: false, session_status: "capturing" as const })),
    recoverCapture: vi.fn(async (_id, request) => {
      expect(request.capture_lease_generation).toBe(committed ? 2 : 1);
      throw new Error("fixture stops before the gap receiver mutation");
    }),
  };
  const first = f.controller(f.source, recovery, undefined, f.profiles);
  await first.prepareAdmitted(f.session.id, f.receipt.request); await first.startRecording();
  const active = (await f.flow.getActiveCaptureState())!, local = (await f.flow.getCaptureRecoveryState(f.session.id))!;
  const intent = validateRenewalIntent({ schemaVersion: 1, sessionId: f.session.id, profileReceiptId: f.receipt.receipt_id,
    segmentId: local.currentSegmentId!, segmentOrdinal: 0, priorLease: active.lease,
    priorCaptureAuthorizedUntil: active.captureAuthorizedUntil!, firstSequenceNumber: 90, count: 1,
    leaseIdempotencyKey: "synthetic-pending-renewal", reservationIdempotencyKey: "synthetic-pending-reserve", createdAt: new Date().toISOString() });
  await f.flow.putCaptureRenewal({ intent, lease: null, reservations: null });
  const issued = new Date();
  remoteLease = committed ? { ...active.lease, generation: 2, receipt_id: crypto.randomUUID(),
    issued_at: issued.toISOString(), expires_at: new Date(issued.getTime() + 900_000).toISOString() } : active.lease;
  const renew = vi.spyOn(f.bff, "renewLease").mockResolvedValue(remoteLease);
  await first.close(); await f.reopenFlow();
  const reserve = vi.spyOn(f.bff, "reserveChunks");
  const next = f.controller(f.source, recovery, undefined, f.profiles);
  await next.restore(); expect(next.snapshot.state).toBe("paused");
  expect(renew).not.toHaveBeenCalled();
  await expect(next.acknowledgeGap()).rejects.toThrow("fixture stops before the gap receiver mutation");
  expect(renew).toHaveBeenCalledTimes(committed ? 1 : 0);
  if (committed) expect(renew).toHaveBeenCalledWith(f.session.id, active.lease.lease_id,
    { protocol_version: "1.0", expected_generation: 1 }, { idempotencyKey: intent.leaseIdempotencyKey });
  expect(recovery.recoverCapture).toHaveBeenCalledTimes(1); expect(reserve).not.toHaveBeenCalled();
  expect(await f.flow.getActiveCaptureState()).toMatchObject({ phase: "paused", lease: { generation: committed ? 2 : 1 },
    captureAuthorizedUntil: active.captureAuthorizedUntil });
  expect(f.source.start).toHaveBeenCalledTimes(1); await next.close();
});

it("recovers a committed selection with GET after a lost reply without another selection or automatic recording", async () => {
  const f = await profileFixture();
  vi.mocked(f.profiles.selectCaptureProfile).mockRejectedValueOnce(new BffResponseError(503, "capture_request_unconfirmed", null));
  await expect(f.profiled().prepareAdmitted(f.session.id, f.receipt.request)).rejects.toMatchObject({ status: 503 });
  expect(f.lease).not.toHaveBeenCalled();
  expect(await f.flow.getActiveCaptureState()).toBeNull();
  const saved = await f.flow.getPreparationState();
  await f.reopenFlow();
  await expect(f.profiled().restore()).resolves.toBe(true);
  expect(f.profiles.getCaptureProfile).toHaveBeenCalledTimes(1);
  expect(f.profiles.selectCaptureProfile).toHaveBeenCalledTimes(1);
  expect(await f.flow.getPreparationState()).toMatchObject({ sessionId: saved?.sessionId,
    completeIdempotencyKey: saved?.completeIdempotencyKey, profileSelection: {
    ...(saved?.mode === "core_admitted" ? saved.profileSelection : {}), receipt: f.receipt } });
  expect(f.source.start).not.toHaveBeenCalled();
});

it("replays only the saved request/key if the selection never committed", async () => {
  const f = await profileFixture();
  vi.mocked(f.profiles.selectCaptureProfile).mockRejectedValueOnce(new BffResponseError(503, "capture_request_unconfirmed", null));
  await expect(f.profiled().prepareAdmitted(f.session.id, f.receipt.request)).rejects.toThrow();
  vi.mocked(f.profiles.getCaptureProfile).mockRejectedValueOnce(new BffResponseError(409, "capture_source_unavailable", null));
  await expect(f.profiled().restore()).resolves.toBe(true);
  const calls = vi.mocked(f.profiles.selectCaptureProfile).mock.calls;
  expect(calls).toHaveLength(2); expect(calls[1]).toEqual(calls[0]);
  expect(f.source.start).not.toHaveBeenCalled();
});

it("does not obtain a lease if persisting the confirmed profile fails", async () => {
  const f = await profileFixture();
  const put = f.flow.putPreparationState.bind(f.flow);
  vi.spyOn(f.flow, "putPreparationState").mockImplementationOnce(put).mockRejectedValueOnce(new Error("invented storage failure"));
  await expect(f.profiled().prepareAdmitted(f.session.id, f.receipt.request)).rejects.toThrow("invented storage failure");
  expect(await f.flow.getPreparationState()).toMatchObject({ profileSelection: { receipt: null }, leaseRequest: null });
  expect(f.profiles.acknowledgeCaptureProfile).not.toHaveBeenCalled();
  expect(f.lease).not.toHaveBeenCalled();
  await f.reopenFlow();
  await expect(f.profiled().restore()).resolves.toBe(true);
  expect(f.profiles.selectCaptureProfile).toHaveBeenCalledTimes(1);
});

it("replays the same lease after a lost lease reply with the saved profile already confirmed", async () => {
  const f = await profileFixture();
  const issue = f.lease.getMockImplementation()!;
  f.lease.mockImplementationOnce(async (...args) => {
    await issue(...args); throw new BffResponseError(503, "capture_request_unconfirmed", null);
  });
  await expect(f.profiled().prepareAdmitted(f.session.id, f.receipt.request)).rejects.toThrow();
  await f.reopenFlow();
  await expect(f.profiled().restore()).resolves.toBe(true);
  expect(f.lease.mock.calls).toHaveLength(2);
  expect(f.lease.mock.calls[1]).toEqual(f.lease.mock.calls[0]);
  expect(f.profiles.selectCaptureProfile).toHaveBeenCalledTimes(1);
  expect(f.profiles.getCaptureProfile).not.toHaveBeenCalled();
  expect(f.source.start).not.toHaveBeenCalled();
});

it.each(["network", "revoked", "wrong_hash", "foreign_receipt"])("retains pending profile work after %s recovery failure", async fault => {
  const f = await profileFixture();
  vi.mocked(f.profiles.selectCaptureProfile).mockRejectedValueOnce(new BffResponseError(503, "capture_request_unconfirmed", null));
  await expect(f.profiled().prepareAdmitted(f.session.id, f.receipt.request)).rejects.toThrow();
  const before = await f.flow.getPreparationState();
  if (fault === "network" || fault === "revoked") {
    vi.mocked(f.profiles.getCaptureProfile).mockRejectedValueOnce(new BffResponseError(fault === "network" ? 503 : 403, "unavailable", null));
  } else {
    vi.mocked(f.profiles.getCaptureProfile).mockResolvedValueOnce({ ...f.receipt,
      ...(fault === "foreign_receipt" ? { session_id: crypto.randomUUID() } : { request_sha256: "0".repeat(64) }) });
  }
  await expect(f.profiled().restore()).rejects.toThrow();
  expect(await f.flow.getPreparationState()).toEqual(before);
  expect(f.profiles.selectCaptureProfile).toHaveBeenCalledTimes(1);
  expect(f.lease).not.toHaveBeenCalled(); expect(f.source.start).not.toHaveBeenCalled();
});

it("cannot replace the saved profile intent/receipt or retrofit a legacy preparation", async () => {
  const f = await profileFixture();
  await f.profiled().prepareAdmitted(f.session.id, f.receipt.request);
  const state = await f.flow.getPreparationState();
  if (state?.mode !== "core_admitted" || !state.profileSelection) throw new Error("fixture state missing");
  const { profileSelection, ...withoutProfile } = state;
  await expect(f.flow.putPreparationState(withoutProfile)).rejects.toThrow("preparation_state_conflict");
  await expect(f.flow.putPreparationState({ ...state, profileSelection: { ...profileSelection, idempotencyKey: "replacement-key" } })).rejects.toThrow("preparation_state_conflict");
  await expect(f.flow.putPreparationState({ ...state, profileSelection: { ...profileSelection,
    receipt: { ...f.receipt, receipt_id: crypto.randomUUID() } } })).rejects.toThrow("preparation_state_conflict");
  const active = (await f.flow.getActiveCaptureState())!;
  await expect(f.flow.putActiveCaptureState({ ...active, captureProfile: { ...f.receipt, receipt_id: crypto.randomUUID() } })).rejects.toThrow("active_capture_conflict");
  const legacy = await fixture();
  await legacy.controller().prepareAdmitted(legacy.session.id);
  const legacyState = await legacy.flow.getPreparationState();
  if (legacyState?.mode !== "core_admitted") throw new Error("fixture state missing");
  await expect(legacy.flow.putPreparationState({ ...legacyState, profileSelection: { ...profileSelection, receipt: null } })).rejects.toThrow("capture_profile_unconfirmed");
  await expect(legacy.controller(legacy.source, undefined, undefined, f.profiles).restore()).resolves.toBe(true);
  expect((await legacy.flow.getActiveCaptureState())?.captureProfile).toBeUndefined();
});

it("uses the admitted session without recreating consent, silently recording or inventing receipt data", async () => {
  const f = await fixture();
  const first = f.controller();
  await first.prepareAdmitted(f.session.id);
  expect(first.snapshot).toMatchObject({ state: "ready", sessionId: f.session.id, queuedChunks: 90 });
  expect(f.source.start).not.toHaveBeenCalled();
  const saved = await f.flow.getPreparationState();
  expect(saved).toMatchObject({ mode: "core_admitted", sessionId: f.session.id });
  expect(JSON.stringify(saved)).not.toMatch(/consentRequest|patient_id|practitioner_id|context_token/);
  const recovered = f.controller();
  await expect(recovered.restore()).resolves.toBe(true);
  expect(f.source.start).not.toHaveBeenCalled();
  await recovered.startRecording();
  expect(f.source.start).toHaveBeenCalledTimes(1);
  await recovered.stopRecording();
  expect(recovered.snapshot.state).toBe("processing");
  await recovered.refreshTranscriptionStatus();
  expect(recovered.snapshot.state).toBe("complete");
  expect(f.consentCalls).not.toHaveBeenCalled();
  expect(f.sessionCalls).not.toHaveBeenCalled();
});

it("preserves native PCM and its acknowledged gap without inventing resume authority", async () => {
  const f = await fixture(true);
  const bridge = new FakeIosNativePcmBridge();
  const first = f.controller(new IosNativeMicrophoneCaptureSource(bridge));
  await first.prepareAdmitted(f.session.id);
  expect(bridge.startCalls).toBe(0);
  await first.startRecording();
  const frames = bridge.lastConfiguration!.targetFramesPerChunk;
  const pcm = new Uint8Array(new ArrayBuffer(frames*2)); pcm.fill(7);
  await bridge.emitPcmPacket({sequenceNumber:0,pcmBytes:pcm});
  expect(pcm.every(value => value === 0)).toBe(true);
  await first.close();
  expect(first.snapshot.state).toBe("paused");
  const nextBridge = new FakeIosNativePcmBridge();
  const next = f.controller(new IosNativeMicrophoneCaptureSource(nextBridge));
  await next.restore();
  expect(next.snapshot.state).toBe("paused");
  expect(nextBridge.startCalls).toBe(0);
  await next.acknowledgeGap();
  expect(nextBridge.startCalls).toBe(0);
  expect(next.snapshot.statusCode).toBe("capture_resume_authority_required");
  await expect(next.startRecording()).rejects.toThrow("capture_state_conflict");
  await expect(next.stopRecording()).rejects.toThrow("capture_gap_review_required");
  expect(bridge.startCalls).toBe(1); expect(nextBridge.startCalls).toBe(0);
  expect(f.consentCalls).not.toHaveBeenCalled(); expect(f.sessionCalls).not.toHaveBeenCalled();
});

it("encrypts native PCM, completes the scoped upload queue and recovers the resulting transcript", async () => {
  const f = await fixture(true);
  const bridge = new FakeIosNativePcmBridge();
  const controller = f.controller(new IosNativeMicrophoneCaptureSource(bridge));
  await controller.prepareAdmitted(f.session.id);
  expect(bridge.startCalls).toBe(0);
  await controller.startRecording();
  const pcm=new Uint8Array(new ArrayBuffer(bridge.lastConfiguration!.targetFramesPerChunk*2));
  pcm.fill(7);
  await bridge.emitPcmPacket({sequenceNumber:0,pcmBytes:pcm});
  expect(pcm.every(value => value === 0)).toBe(true);
  await controller.stopRecording();
  await controller.refreshTranscriptionStatus();
  expect(controller.snapshot.state).toBe("complete");
  const reader=f.controller(new IosNativeMicrophoneCaptureSource(new FakeIosNativePcmBridge()));
  expect(await reader.restoreAdmittedResult(f.session.id)).toBe(true);
  expect(reader.snapshot.transcript).toEqual(controller.snapshot.transcript);
  expect(bridge.startCalls).toBe(1);
});

it("recovers a lost committed lease response using the saved admission and same lease key", async () => {
  const f = await fixture();
  const issue = f.bff.issueLease.bind(f.bff);
  let lost = true;
  const lease = vi.spyOn(f.bff, "issueLease").mockImplementation(async (...args) => {
    const result = await issue(...args);
    if (lost) { lost = false; throw new Error("synthetic lost committed lease response"); }
    return result;
  });
  await expect(f.controller().prepareAdmitted(f.session.id)).rejects.toThrow("synthetic lost");
  const recovered = f.controller();
  await expect(recovered.restore()).resolves.toBe(true);
  expect(recovered.snapshot).toMatchObject({ state: "ready", sessionId: f.session.id });
  expect(lease).toHaveBeenCalledTimes(2);
  expect(lease.mock.calls[0][2].idempotencyKey).toBe(lease.mock.calls[1][2].idempotencyKey);
  expect(f.source.start).not.toHaveBeenCalled();
  expect(f.consentCalls).not.toHaveBeenCalled();
  expect(f.sessionCalls).not.toHaveBeenCalled();
});

it("retains the admitted session and rejects injected identity or replacement preparation", async () => {
  const f = await fixture();
  await f.controller().prepareAdmitted(f.session.id);
  const state = await f.flow.getPreparationState();
  if (state?.mode !== "core_admitted") throw new Error("fixture preparation missing");
  await expect(f.flow.putPreparationState({ ...state, sessionId: crypto.randomUUID() }))
    .rejects.toThrow("preparation_state_conflict");
  const forged = { ...state, consentRequest: { patient_id: "synthetic-forged" } };
  await expect(f.flow.putPreparationState(forged)).rejects.toThrow("invalid_preparation_state");
  expect(await f.flow.getPreparationState()).toEqual(state);
});

it("closes the source on workspace exit, preserves a reviewable gap and never restarts it", async () => {
  const f = await fixture();
  const controller = f.controller();
  const stop = vi.spyOn(f.source, "stop");
  await controller.prepareAdmitted(f.session.id);
  await controller.startRecording();
  await controller.close();
  await controller.close();
  expect(stop).toHaveBeenCalledTimes(1);
  expect(await f.flow.getActiveCaptureState()).toMatchObject({ phase: "paused", recordedChunks: 1 });
  expect(await f.flow.getCaptureRecoveryState(f.session.id)).toMatchObject({
    phase: "ack_required", noteReadiness: "review_required",
    gaps: [expect.objectContaining({ reasonCode: "capture_backgrounded" })],
  });
  await expect(controller.startRecording()).rejects.toThrow("capture_state_conflict");
  const recovered = f.controller();
  await recovered.restore();
  expect(recovered.snapshot.state).toBe("paused");
  expect(f.source.start).toHaveBeenCalledTimes(1);
});

it("aborts an in-flight source start when the workspace closes", async () => {
  const f = await fixture();
  let started: (() => void) | undefined;
  const waiting = new Promise<void>(resolve => { started = resolve; });
  f.source.start.mockImplementation(async options => {
    started?.();
    await new Promise<void>(resolve => options.signal?.addEventListener("abort", () => resolve(), { once: true }));
  });
  const controller = f.controller();
  await controller.prepareAdmitted(f.session.id);
  const start = controller.startRecording();
  await waiting;
  await controller.close();
  await start;
  expect(controller.snapshot.state).toBe("paused");
  expect(await f.flow.getActiveCaptureState()).toMatchObject({ phase: "paused", recordedChunks: 0 });
});

it("reopens a completed admitted transcript without creating keys, leases or recording again", async () => {
  const f = await fixture();
  const first = f.controller();
  await first.prepareAdmitted(f.session.id);
  await first.startRecording();
  await first.stopRecording();
  await first.refreshTranscriptionStatus();
  expect(first.snapshot.state).toBe("complete");
  const key = vi.spyOn(f.bff, "bindSessionAudioKey");
  const lease = vi.spyOn(f.bff, "issueLease");
  const reopened = f.controller();
  await expect(reopened.restoreAdmittedResult(f.session.id)).resolves.toBe(true);
  expect(reopened.snapshot.transcript).toEqual(first.snapshot.transcript);
  expect(reopened.snapshot.state).toBe("complete");
  expect(key).not.toHaveBeenCalled(); expect(lease).not.toHaveBeenCalled();
  expect(f.source.start).toHaveBeenCalledTimes(1);
  await expect(reopened.startRecording()).rejects.toThrow("capture_state_conflict");
});

it("never bypasses a retained recording gap to load a server result", async () => {
  const f = await fixture();
  const first = f.controller();
  await first.prepareAdmitted(f.session.id);
  await first.startRecording(); await first.close();
  const status = vi.spyOn(f.bff, "getTranscriptionStatus");
  const reopened = f.controller();
  await expect(reopened.restoreAdmittedResult(f.session.id)).resolves.toBe(false);
  expect(status).not.toHaveBeenCalled();
  await reopened.restore();
  expect(reopened.snapshot.state).toBe("paused");
  expect(f.source.start).toHaveBeenCalledTimes(1);
});

it("reads a pending server transcript after local cleanup and reports terminal failure without recording", async () => {
  const f = await fixture();
  const status = vi.spyOn(f.bff, "getTranscriptionStatus").mockResolvedValue({
    session_id: f.session.id, status: "processing", transcript_available: false, updated_at: new Date().toISOString(),
  });
  const reader = f.controller();
  expect(await reader.restoreAdmittedResult(f.session.id)).toBe(true);
  expect(reader.snapshot.state).toBe("processing");
  status.mockResolvedValue({ session_id: f.session.id, status: "terminal", transcript_available: false, updated_at: new Date().toISOString() });
  await reader.resumePendingWork();
  expect(reader.snapshot).toMatchObject({ state: "error", statusCode: "capture_transcription_terminal" });
  expect(f.source.start).not.toHaveBeenCalled();
});

/** Receiver fixture uses the real local mock lease/reservation/upload service. */
async function recoveryFixture(reviewAfterUpload = false) {
  const f = await fixture(true);
  const bridge = new FakeIosNativePcmBridge();
  const source = new IosNativeMicrophoneCaptureSource(bridge);
  let current: Awaited<ReturnType<typeof f.bff.issueLease>> | null = null;
  const history: CaptureRecoveryReceipt[] = [];
  let loseReply = false;
  const recovery: CaptureRecoveryBff = {
    getCaptureRecoveryState: async () => ({ history: { session_id: f.session.id, recoveries: structuredClone(history) },
      current_lease: current ?? (await f.flow.getActiveCaptureState())!.lease, lease_closed: false, session_status: "capturing" }),
    recoverCapture: async (id, request, options) => {
      expect(await f.flow.getCaptureRecoveryIntent(id, request.gap_id,
        (await f.flow.getCaptureRecoveryState(id))?.finishChoice && request.decision === "finish_capture" ? "finish" : undefined)).toMatchObject({ request, idempotencyKey: options.idempotencyKey });
      const existing = history.find(item => item.request.gap_id === request.gap_id);
      if (existing) return structuredClone(existing);
      current = await f.bff.renewLease(id, request.capture_lease_id,
        { protocol_version: "1.0", expected_generation: request.capture_lease_generation }, options);
      const receipt: CaptureRecoveryReceipt = { receipt_id: crypto.randomUUID(), session_id: id,
        request: structuredClone(request), request_sha256: await recoveryRequestHash(request, crypto),
        acknowledged_by_practitioner_id: "synthetic-practitioner",
        following_segment_id: request.decision === "resume_capture" ? crypto.randomUUID() : null,
        lease: current, review_state: "required" };
      history.push(receipt);
      if (loseReply) { loseReply = false; throw new Error("discarded recovery response"); }
      return structuredClone(receipt);
    },
  };
  const controller = f.controller(source, recovery);
  await controller.prepareAdmitted(f.session.id, undefined, reviewAfterUpload);
  const emit = () => {
    const frames = bridge.lastConfiguration?.targetFramesPerChunk;
    if (!frames) throw new Error("native fixture was not started");
    return bridge.emitPcmPacket({ sequenceNumber: 0, pcmBytes: new Uint8Array(frames * 2) });
  };
  const interrupt = async (selected = controller) => {
    bridge.emitInterruption("ios_capture_backgrounded");
    await vi.waitFor(() => expect(selected.snapshot.state).toBe("paused"));
  };
  return { ...f, get flow() {return f.flow;}, bridge, source, recovery, activeController: controller, emit, interrupt, history,
    loseReply: () => { loseReply = true; } };
}

it.each(["resume", "finish"])("requires native closure proof before %s of a process-interrupted visit", async decision => {
  const f = await recoveryFixture();
  await f.activeController.startRecording(); await f.emit();
  // Simulate native process exit without the controller's phase write.
  await f.source.stop(); await f.reopenFlow();
  const proof = vi.fn().mockRejectedValueOnce(new Error("native unavailable")).mockResolvedValue(false);
  const source = Object.assign(new SilentChunk(), { confirmRecoveryClosed: proof });
  const close = vi.spyOn(source, "stop");
  const complete = vi.spyOn(f.bff, "completeCapture");
  const recovered = f.controller(source, f.recovery);
  await recovered.restore();
  expect(recovered.snapshot).toMatchObject({state:"paused",recordedChunks:1,statusCode:"capture_interruption_closing"});
  expect(proof).not.toHaveBeenCalled();
  const act = () => decision === "resume" ? recovered.acknowledgeGap() : recovered.finishInterruptedCapture();
  for (let attempt = 0; attempt < 2; attempt++) {
    await expect(act()).rejects.toThrow("capture_source_close_unverified");
    expect(f.history).toHaveLength(0); expect(complete).not.toHaveBeenCalled();
    expect(source.start).not.toHaveBeenCalled(); expect(close).not.toHaveBeenCalled();
  }
  proof.mockResolvedValue(true);
  await act();
  expect(f.history).toHaveLength(1);
  expect(f.history[0].request.reason_code).toBe("process_recovery_unknown");
  expect(f.history[0].request.decision).toBe(decision === "resume" ? "resume_capture" : "finish_capture");
  expect(source.start).not.toHaveBeenCalled(); expect(close).not.toHaveBeenCalled();
  if (decision === "resume") {
    expect(recovered.snapshot).toMatchObject({state:"ready",recordedChunks:1});
    await recovered.startRecording(); await recovered.stopRecording();
    expect(recovered.snapshot.recordedChunks).toBe(2);
  }
  expect(recovered.snapshot.state).toBe("processing");
  expect(complete).toHaveBeenCalledOnce();
});

it("finishes an older configured journal without a new source or key after losing the finish reply", async () => {
  const f = await recoveryFixture(true);
  const key = await f.flow.getSessionKeyState(f.session.id);
  await f.activeController.startRecording(); await f.emit(); await f.source.stop();
  await f.reopenFlow();
  const proof = vi.fn().mockResolvedValue(false);
  const source = Object.assign(new SilentChunk(), {confirmRecoveryClosed:proof});
  const restored = f.controller(source,f.recovery,undefined,undefined,true);
  await restored.restore();
  await expect(restored.startRecording()).rejects.toThrow("capture_saved_recording_finish_only");
  await expect(restored.acknowledgeGap()).rejects.toThrow("capture_saved_recording_finish_only");
  await expect(restored.finishInterruptedCapture()).rejects.toThrow("capture_source_close_unverified");
  expect(f.history).toHaveLength(0);
  proof.mockResolvedValue(true); f.loseReply();
  await expect(restored.finishInterruptedCapture()).rejects.toThrow("discarded recovery response");
  expect(f.history).toHaveLength(1);
  await f.reopenFlow();
  const retried = f.controller(source,f.recovery,undefined,undefined,true);
  await retried.restore();
  await retried.finishInterruptedCapture();
  expect(retried.snapshot).toMatchObject({state:"processing",recordedChunks:1});
  expect(f.history).toHaveLength(1);
  expect(f.history[0].request.decision).toBe("finish_capture");
  expect(await f.flow.getSessionKeyState(f.session.id)).toEqual(key);
  expect((await f.flow.getCaptureRecoveryState(f.session.id))?.gaps).toHaveLength(1);
  expect(source.start).not.toHaveBeenCalled();
});

it("retains an unrecorded older preparation without starting its source", async () => {
  const f = await fixture();
  await f.controller().prepareAdmitted(f.session.id,undefined,true);
  const active = await f.flow.getActiveCaptureState(), key = await f.flow.getSessionKeyState(f.session.id);
  const restored = f.controller(f.source,undefined,undefined,undefined,true);
  await restored.restore();
  expect(restored.snapshot).toMatchObject({state:"ready",recordedChunks:0});
  await expect(restored.startRecording()).rejects.toThrow("capture_saved_recording_finish_only");
  expect(await f.flow.getActiveCaptureState()).toEqual(active);
  expect(await f.flow.getSessionKeyState(f.session.id)).toEqual(key);
  expect(f.source.start).not.toHaveBeenCalled();
});

it.each(["committed", "uncommitted", "late", "lost_phase"])("finishes an older %s Resume without changing its original intent or adding a recording", async outcome => {
  const f=await recoveryFixture(true);
  await f.activeController.startRecording();await f.emit();await f.interrupt();
  const original=f.recovery.recoverCapture.bind(f.recovery);
  const recover=vi.spyOn(f.recovery,"recoverCapture");
  if(outcome==="committed"||outcome==="lost_phase")f.loseReply();
  else recover.mockRejectedValueOnce(new Error("connection failed before commit"));
  await expect(f.activeController.acknowledgeGap()).rejects.toThrow();
  const old=(await f.flow.getCaptureRecoveryIntent(f.session.id,(await f.flow.getCaptureRecoveryState(f.session.id))!.gaps[0].gapId))!;
  expect(old.request.decision).toBe("resume_capture");
  const key=await f.flow.getSessionKeyState(f.session.id);
  await f.reopenFlow();
  let controller=f.controller(f.source,f.recovery,undefined,undefined,true);
  await controller.restore();
  if(outcome==="lost_phase"){
    const put=f.flow.putActiveCaptureState.bind(f.flow);
    vi.spyOn(f.flow,"putActiveCaptureState").mockImplementation(async state=>{
      if(state.phase==="uploading")throw new Error("phase write unavailable");await put(state);
    });
    await expect(controller.finishInterruptedCapture()).rejects.toThrow("phase write unavailable");
    await f.reopenFlow();controller=f.controller(f.source,f.recovery,undefined,undefined,true);await controller.restore();
  }
  if(outcome==="late"){
    recover.mockImplementationOnce(async(id,_request,_options)=>{
      // The previous request wins the server lock after a read found no receipt.
      return original(id,old.request,{idempotencyKey:old.idempotencyKey});
    });
    await expect(controller.finishInterruptedCapture()).rejects.toThrow("capture_recovery_history_conflict");
    expect((await f.flow.getCaptureRecoveryState(f.session.id))?.finishChoice?.priorResult).toBe("uncommitted");
    await f.reopenFlow();controller=f.controller(f.source,f.recovery,undefined,undefined,true);await controller.restore();
  }
  await controller.finishInterruptedCapture();
  expect(controller.snapshot).toMatchObject({state:"processing",recordedChunks:1});
  const local=(await f.flow.getCaptureRecoveryState(f.session.id))!;
  expect(local).toMatchObject({schemaVersion:2,phase:"stopped",nextSequenceNumber:1,finishChoice:{priorIntent:old,
    priorResult:outcome==="uncommitted"?"uncommitted":"committed"}});
  expect(local.segments).toHaveLength(1);expect(local.gaps).toHaveLength(1);
  expect(await f.flow.getCaptureRecoveryIntent(f.session.id,old.request.gap_id)).toEqual(old);
  expect(await f.flow.getSessionKeyState(f.session.id)).toEqual(key);
  expect(f.history).toHaveLength(1);expect(f.history[0].request.decision).toBe(outcome==="uncommitted"?"finish_capture":"resume_capture");
  expect(f.bridge.startCalls).toBe(1);
  if(outcome==="uncommitted")expect(await f.flow.getCaptureRecoveryIntent(f.session.id,old.request.gap_id,"finish")).toMatchObject({request:{decision:"finish_capture"}});
  const reopened=f.controller(f.source,f.recovery,undefined,undefined,true);await reopened.restore();
  expect(reopened.snapshot.state).toBe("processing");expect(f.bridge.startCalls).toBe(1);
});

it("cannot send Finish when saving the choice over an uncommitted Resume fails", async()=>{
  const f=await recoveryFixture(true);
  await f.activeController.startRecording();await f.emit();await f.interrupt();
  const recover=vi.spyOn(f.recovery,"recoverCapture").mockRejectedValueOnce(new Error("offline"));
  await expect(f.activeController.acknowledgeGap()).rejects.toThrow("offline");
  const before=await f.flow.getCaptureRecoveryState(f.session.id);
  const controller=f.controller(f.source,f.recovery,undefined,undefined,true);await controller.restore();
  const put=f.flow.putCaptureRecoveryState.bind(f.flow);
  vi.spyOn(f.flow,"putCaptureRecoveryState").mockImplementation(async state=>{
    if(state.schemaVersion===2)throw new Error("disk unavailable");await put(state);
  });
  await expect(controller.finishInterruptedCapture()).rejects.toThrow("disk unavailable");
  expect(recover).toHaveBeenCalledTimes(1);expect(f.history).toHaveLength(0);
  expect(await f.flow.getCaptureRecoveryState(f.session.id)).toEqual(before);
  expect(f.bridge.startCalls).toBe(1);
});

async function qualifiedFixtureSource(f: Awaited<ReturnType<typeof recoveryFixture>>): Promise<CaptureSourceEnvelope> {
  const source = (JSON.parse(readFileSync(new URL("../../../../tests/fixtures/capture_source.json", import.meta.url), "utf8")) as
    {base:CaptureSourceEnvelope}).base;
  source.session_id = f.session.id; source.raw_transcript.session_id = f.session.id;
  source.working_transcript.session_id = f.session.id;
  source.raw_transcript.created_at = new Date().toISOString(); source.working_transcript.created_at = source.raw_transcript.created_at;
  source.recovery_history = {session_id:f.session.id,recoveries:structuredClone(f.history)};
  await hashFixtureSource(source);
  return source;
}
async function hashFixtureSource(source: CaptureSourceEnvelope) {
  const working = source.working_transcript;
  working.raw_transcript_sha256 = await captureRawHash(source.raw_transcript);
  working.working_sha256 = await workingHash({raw_transcript_sha256:working.raw_transcript_sha256,working_source:working.working_source});
  for (const row of source.recovery_history.recoveries) row.request_sha256 = await recoveryRequestHash(row.request);
  source.recovery_sha256 = await captureRecoveryHash(source.recovery_history);
  source.capture_incomplete = source.recovery_history.recoveries.length > 0;
  source.source_sha256 = await workingHash({raw_transcript_sha256:working.raw_transcript_sha256,
    working_sha256:working.working_sha256,recovery_sha256:source.recovery_sha256});
}

it("recovers a lost qualified-source reply, releases only matched gaps, and reopens without recording", async () => {
  const f = await recoveryFixture();
  await f.activeController.startRecording(); await f.emit(); await f.interrupt();
  await f.activeController.finishInterruptedCapture(); await f.activeController.refreshTranscriptionStatus();
  const source = await qualifiedFixtureSource(f);
  const raw = vi.spyOn(f.bff, "getTranscript");
  const port = {getCaptureSource:vi.fn().mockRejectedValueOnce(new Error("discarded source reply")).mockResolvedValue(source)};
  const interruptedRead = f.controller(f.source, f.recovery, port);
  await interruptedRead.restore();
  await expect(interruptedRead.refreshTranscriptionStatus()).rejects.toThrow("discarded source reply");
  expect(await f.flow.getActiveCaptureState()).toMatchObject({phase:"processing"});
  expect((await f.flow.getCaptureRecoveryState(f.session.id))?.gaps).toHaveLength(1);
  const restored = f.controller(f.source, f.recovery, port);
  await expect(restored.restore()).resolves.toBe(true);
  await restored.refreshTranscriptionStatus();
  expect(restored.snapshot).toMatchObject({state:"complete",qualifiedSource:{capture_incomplete:true}});
  expect(restored.snapshot.qualifiedSource?.recovery_history.recoveries[0].review_state).toBe("required");
  expect(await f.flow.getActiveCaptureState()).toBeNull();
  expect(await f.flow.getCaptureRecoveryState(f.session.id)).toBeNull();
  const reopened = f.controller(f.source, f.recovery, port);
  await expect(reopened.restoreAdmittedResult(f.session.id)).resolves.toBe(true);
  expect(reopened.snapshot.qualifiedSource).toEqual(source);
  await expect(reopened.startRecording()).rejects.toThrow("capture_state_conflict");
  expect(f.bridge.startCalls).toBe(1); expect(raw).not.toHaveBeenCalled();
});

it.each(["missing_gap", "changed_gap", "missing_intent", "changed_following_segment"])("retains capture state when qualified source has %s", async fault => {
  const f = await recoveryFixture();
  await f.activeController.startRecording(); await f.emit(); await f.interrupt();
  await f.activeController.acknowledgeGap(); await f.activeController.startRecording(); await f.emit();
  await f.activeController.stopRecording(); await f.activeController.refreshTranscriptionStatus();
  const source = await qualifiedFixtureSource(f);
  if (fault === "missing_gap") source.recovery_history.recoveries = [];
  if (fault === "changed_gap") source.recovery_history.recoveries[0].request.reason_code = "audio_route_changed";
  if (fault === "changed_following_segment") source.recovery_history.recoveries[0].following_segment_id = crypto.randomUUID();
  if (fault === "missing_intent") vi.spyOn(f.flow, "getCaptureRecoveryIntent").mockResolvedValue(null);
  await hashFixtureSource(source);
  const reader = f.controller(f.source, f.recovery, {getCaptureSource:async () => source});
  await reader.restore();
  await expect(reader.refreshTranscriptionStatus()).rejects.toThrow("capture_recovery_history_conflict");
  expect(reader.snapshot.transcript).toBeNull();
  expect(await f.flow.getActiveCaptureState()).toMatchObject({phase:"processing",recordedChunks:2});
  expect((await f.flow.getCaptureRecoveryState(f.session.id))?.gaps).toHaveLength(1);
  expect(f.bridge.startCalls).toBe(2);
});

it("resumes native generated PCM only on explicit Start, preserves global sequence and seals finish", async () => {
  const f = await recoveryFixture();
  const controller = f.activeController;
  const reserves = vi.spyOn(f.bff, "reserveChunks");
  const complete = vi.spyOn(f.bff, "completeCapture");
  const transcript = vi.spyOn(f.bff, "getTranscript");
  await controller.startRecording(); await f.emit(); await f.interrupt();
  await controller.acknowledgeGap();
  expect(controller.snapshot).toMatchObject({ state: "ready", recordedChunks: 1, statusCode: "capture_resume_ready" });
  expect(f.bridge.startCalls).toBe(1);
  expect(reserves.mock.calls.at(-1)?.[1]).toMatchObject({ capture_lease_generation: 2, first_sequence_number: 1 });
  await controller.startRecording(); await f.emit();
  expect(controller.snapshot.recordedChunks).toBe(2);
  expect(f.bridge.startCalls).toBe(2);
  await f.interrupt(); await controller.finishInterruptedCapture();
  expect(complete.mock.calls[0]?.[1]).toMatchObject({ capture_lease_generation: 3,
    channels: [{ channel: "microphone", final_sequence_number: 1 }] });
  await controller.refreshTranscriptionStatus();
  expect(controller.snapshot.statusCode).toBe("capture_gap_review_required");
  expect(transcript).not.toHaveBeenCalled();
  const local = await f.flow.getCaptureRecoveryState(f.session.id);
  expect(local).toMatchObject({ phase: "stopped", noteReadiness: "review_required", nextSequenceNumber: 2 });
  expect(local?.segments[1]?.segmentId).toBe(f.history[0]?.following_segment_id);
  expect(local?.gaps).toHaveLength(2);
});

it("recovers a lost recovery reply after controller restoration without starting native capture", async () => {
  const f = await recoveryFixture();
  await f.activeController.startRecording(); await f.emit(); await f.interrupt();
  f.loseReply();
  await expect(f.activeController.acknowledgeGap()).rejects.toThrow("discarded recovery response");
  const restored = f.controller(f.source, f.recovery);
  await expect(restored.restore()).resolves.toBe(true);
  expect(f.bridge.startCalls).toBe(1);
  await restored.acknowledgeGap();
  expect(restored.snapshot.state).toBe("ready");
  expect(f.bridge.startCalls).toBe(1);
  expect(f.history).toHaveLength(1);
  expect((await f.flow.getActiveCaptureState())?.lease.generation).toBe(2);
});

it("replays a durable reservation after its response is lost and keeps capture paused until confirmation", async () => {
  const f = await recoveryFixture();
  await f.activeController.startRecording(); await f.emit(); await f.interrupt();
  const reserve = f.bff.reserveChunks.bind(f.bff);
  const calls = vi.spyOn(f.bff, "reserveChunks");
  calls.mockImplementationOnce(async (...args) => {
    await reserve(...args);
    throw new Error("discarded reservation response");
  });
  await expect(f.activeController.acknowledgeGap()).rejects.toThrow("discarded reservation response");
  expect(f.activeController.snapshot.state).toBe("paused");
  await expect(f.activeController.startRecording()).rejects.toThrow("capture_state_conflict");
  const restored = f.controller(f.source, f.recovery);
  await restored.restore(); await restored.acknowledgeGap();
  expect(restored.snapshot.state).toBe("ready");
  expect(f.bridge.startCalls).toBe(1);
  expect(calls.mock.calls).toHaveLength(2);
  expect(calls.mock.calls[1]).toEqual(calls.mock.calls[0]);
  expect(f.history).toHaveLength(1);
  await restored.startRecording(); await f.emit();
  expect(restored.snapshot.recoveryDecision).toBeUndefined();
  await restored.stopRecording();
  await restored.refreshTranscriptionStatus();
  expect(restored.snapshot.statusCode).toBe("capture_gap_review_required");
  expect((await f.flow.getCaptureRecoveryState(f.session.id))?.gaps).toHaveLength(1);
});


it("hands configured uploads to creator review and reopens without the legacy transcript API", async () => {
  const f = await fixture(), current = f.controller();
  const status = vi.spyOn(f.bff, "getTranscriptionStatus").mockRejectedValue(new Error("legacy API unavailable"));
  const transcript = vi.spyOn(f.bff, "getTranscript").mockRejectedValue(new Error("legacy API unavailable"));
  await current.prepareAdmitted(f.session.id, undefined, true);
  expect(await f.flow.getActiveCaptureState()).toMatchObject({reviewAfterUpload: true});
  await expect(current.releaseUploadedCapture()).rejects.toThrow();
  await current.startRecording(); await current.stopRecording();
  expect(current.snapshot.state).toBe("processing");
  await f.reopenFlow();
  const reopened = f.controller();
  expect(await reopened.restore()).toBe(true);
  expect(reopened.snapshot.state).toBe("processing");
  await reopened.releaseUploadedCapture();
  expect(await f.flow.getActiveCaptureState()).toBeNull();
  await f.controller().restoreConfiguredResult(f.session.id);
  expect(status).not.toHaveBeenCalled(); expect(transcript).not.toHaveBeenCalled();
});
