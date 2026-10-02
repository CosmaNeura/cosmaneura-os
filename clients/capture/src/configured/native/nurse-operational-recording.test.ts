import {createHash, webcrypto} from "node:crypto";
import {mkdir, writeFile} from "node:fs/promises";
import type {Server} from "node:http";
import type {AddressInfo} from "node:net";

import {IDBFactory} from "fake-indexeddb";
import {expect, it, vi} from "vitest";
import {base64UrlDecode, parseEnvelope} from "@cosmaneura-scribe/capture-protocol";
import {HttpCaptureBff} from "../../bff/http-client";
import {BffCaptureQueueTransport} from "../../bff/queue-transport";
import {HttpCiphertextUploadTarget} from "../../bff/upload-target";
import {CaptureQueue} from "../../queue/capture-queue";
import type {EncryptedChunkRecord} from "../../queue/types";
import {EncryptedIndexedDbQueueStorage} from "../../storage/encrypted-indexeddb";
import {CaptureFlowController} from "../flow/controller";
import {EncryptedIndexedDbFlowStore} from "../flow/encrypted-store";
import {createMockBffServer} from "../mock-bff/server";
import type {IOSPCMPlugin, IosPcmEvent, IosPcmEncodedPacket} from "./capacitor-pcm";
import {CapacitorIosNativePcmBridge} from "./capacitor-ios-native-pcm-bridge";
import {IosNativeMicrophoneCaptureSource} from "./ios-native-microphone-source";

const crypto = webcrypto as unknown as Crypto;
const scenarios = ["manual-pause", "route-change", "background"] as const;

/** Generated audio replaces the microphone; the app's plugin transport, WAV
 * adapter, controller, encryption, durable queue and HTTP receiver are real.
 * This is not physical AVAudioSession or mounted-screen testing. */
class SyntheticPhone {
  public state: "foreground" | "background" = "foreground";
  public active = false;
  public starts = 0;
  public stops = 0;
  public listeners = 0;
  public token = "";
  public final: IosPcmEncodedPacket | null = null;
  public readonly acknowledged: string[] = [];
  public readonly stopModes: string[] = [];
  private callback: (event: IosPcmEvent) => void = () => {};
  private readonly retired: Array<(event: IosPcmEvent) => void> = [];
  public readonly plugin: IOSPCMPlugin = {
    getAppState: async () => ({state: this.state}),
    start: vi.fn(async () => {
      expect(this.active).toBe(false);
      this.active = true;
      this.token = String(++this.starts) + ".synthetic_nurse";
      return {sessionToken: this.token};
    }),
    ready: async () => ({}),
    heartbeat: async () => ({}),
    acknowledge: async ({sessionToken, sequenceNumber}) => {
      this.acknowledged.push(sessionToken + ":" + sequenceNumber);
      return {result: "accepted"};
    },
    replayPendingPacket: async () => ({result: "already_acknowledged"}),
    stop: async ({mode}) => {
      this.stops += 1;
      this.stopModes.push(mode);
      this.active = false;
      const finalPcmPacket = mode === "drain" ? this.final : null;
      this.final = null;
      return {finalPcmPacket};
    },
    addListener: async (_name, callback) => {
      this.callback = callback;
      this.listeners += 1;
      this.retired.push(callback);
      return {remove: async () => { this.listeners -= 1; }};
    },
  };
  public async offer(sequenceNumber: number, bytes: Uint8Array): Promise<void> {
    expect(this.active).toBe(true);
    const expected = this.token + ":" + sequenceNumber;
    this.callback({kind: "packet", packet: {
      sessionToken: this.token, sequenceNumber, pcmBase64: Buffer.from(bytes).toString("base64"),
    }});
    await vi.waitFor(() => expect(this.acknowledged).toContain(expected));
  }
  public interrupt(code: "ios_audio_route_changed" | "ios_capture_backgrounded"): void {
    this.callback({kind: "interruption", sessionToken: this.token, code});
  }
  public offerRetiredPacket(): void {
    this.retired[0]?.({kind: "packet", packet: {
      sessionToken: "1.synthetic_nurse", sequenceNumber: 1,
      pcmBase64: Buffer.from(pcm(160, 99)).toString("base64"),
    }});
  }
  public source(): IosNativeMicrophoneCaptureSource {
    return new IosNativeMicrophoneCaptureSource(new CapacitorIosNativePcmBridge(this.plugin, 60_000));
  }
}

it.each(scenarios.flatMap(scenario => [1, 2].map(repeat => ({scenario, repeat}))))(
  "nurse walk-in recording $scenario run $repeat preserves exact audio through control, relaunch and upload",
  async ({scenario, repeat}) => {
    const server = createMockBffServer(), origin = await listen(server);
    const indexedDB = new IDBFactory();
    const flowName = crypto.randomUUID(), queueName = crypto.randomUUID();
    let flowStore = await EncryptedIndexedDbFlowStore.open({databaseName: flowName, indexedDB, crypto});
    let queueStorage = await EncryptedIndexedDbQueueStorage.open({databaseName: queueName, indexedDB, crypto});
    let now = Date.now();
    const sameOriginFetch: typeof fetch = (input, init) => {
      const target = typeof input === "string" ? new URL(input, origin) : input;
      const url = target instanceof Request ? new URL(target.url) : new URL(target.toString());
      if (url.origin !== origin) throw new Error("virtual_recording_network_forbidden");
      return fetch(target, init);
    };
    const bff = new HttpCaptureBff(sameOriginFetch), phone = new SyntheticPhone(), source = phone.source();
    // The real client keeps an encrypt-only DEK. A synthetic receiving service
    // owns this ephemeral RSA private key so fidelity checks can unwrap its
    // server-bound copy without relaxing the product's key restrictions.
    const receiverKey = await crypto.subtle.generateKey({name: "RSA-OAEP", modulusLength: 3072,
      publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256"}, true, ["wrapKey", "unwrapKey"]);
    const receiverPublic = await crypto.subtle.exportKey("jwk", receiverKey.publicKey);
    const published = bff.getAudioEncryptionKey.bind(bff);
    vi.spyOn(bff, "getAudioEncryptionKey").mockImplementation(async () => ({
      ...await published(), public_jwk: {...receiverPublic, kty: "RSA", n: receiverPublic.n!, e: "AQAB",
        alg: "RSA-OAEP-256", ext: true, key_ops: ["wrapKey"]},
    }));
    const controllers: CaptureFlowController[] = [];
    const create = () => {
      const controller = new CaptureFlowController({
        bff, flowStore, queue: new CaptureQueue(queueStorage, {crypto, now: () => now}),
        queueTransport: new BffCaptureQueueTransport(bff, new HttpCiphertextUploadTarget([origin])),
        source, crypto, now: () => new Date(now),
      });
      controllers.push(controller); return controller;
    };
    const steps: Array<{action: string; state: string; chunks: number}> = [];
    const step = (action: string, controller: CaptureFlowController) => {
      steps.push({action, state: controller.snapshot.state, chunks: controller.snapshot.recordedChunks});
    };
    const expected: Uint8Array[] = [];
    const encrypted = async () => (await queueStorage.list()).filter(
      (row): row is EncryptedChunkRecord => row.state === "encrypted",
    ).sort((a, b) => a.reservation.sequenceNumber - b.reservation.sequenceNumber);
    try {
      const first = create();
      // An impromptu invented encounter has no DOB. Only synthetic identity and
      // explicit recording consent are admitted at this controlled boundary.
      const identity = {appointment_id: "invented-walk-in", practitioner_id: "invented-nurse", patient_id: "invented-shawn"};
      const consent = await bff.createConsent({...identity, participant_regions: ["US-NY"],
        modality: "in_person", method: "verbal_attestation", all_parties_consented: true,
        granted_at: new Date(now).toISOString()}, {idempotencyKey: "nurse-virtual-consent"});
      const session = await bff.createSession({...identity, consent_record_id: consent.id, modality: "in_person"},
        {idempotencyKey: "nurse-virtual-session"});
      const complete = vi.spyOn(bff, "completeCapture"), register = vi.spyOn(bff, "registerChunk");
      const upload = vi.spyOn(bff, "authorizeUpload");
      await first.prepareConfigured(session.id);
      expect(phone.starts).toBe(0);
      step("Consent confirmed; visit ready without DOB", first);
      await first.startRecording();
      expected.push(pcm(160_000, 1));
      await phone.offer(0, expected[0]!);
      expect(first.snapshot).toMatchObject({state: "recording", recordedChunks: 1});
      step("Tap Record; speak first invented segment", first);
      if (scenario === "manual-pause") {
        const tail = pcm(2_400, 2); expected.push(tail);
        phone.final = {sessionToken: phone.token, sequenceNumber: 1, pcmBase64: Buffer.from(tail).toString("base64")};
        await first.pauseRecording();
        expect(first.snapshot).toMatchObject({state: "paused", recordedChunks: 2});
        expect(phone.stopModes).toEqual(["drain"]);
        step("Tap Pause; final 150ms is saved", first);
      } else {
        if (scenario === "background") phone.state = "background";
        phone.interrupt(scenario === "background" ? "ios_capture_backgrounded" : "ios_audio_route_changed");
        await vi.waitFor(() => expect(first.snapshot).toMatchObject({state: "paused", recordedChunks: 1}));
        await first.pauseRecording(); // Confirm the previous native owner stopped.
        expect(phone.stopModes).toEqual(["discard"]);
        step(scenario === "background" ? "Phone backgrounds; recording pauses" : "Input route changes; recording pauses", first);
      }
      expect(phone.active).toBe(false); expect(phone.listeners).toBe(0);
      expect(complete).not.toHaveBeenCalled(); expect(upload).not.toHaveBeenCalled();
      const beforeRelaunch = await encrypted(), clientKey = await flowStore.getSessionKey(session.id);
      expect(clientKey?.usages).toEqual(["encrypt"]);
      expect(clientKey?.extractable).toBe(false);
      const binding = await flowStore.getSessionKeyState(session.id);
      const key = await crypto.subtle.unwrapKey("raw", Uint8Array.from(base64UrlDecode(binding!.wrappedDek)),
        receiverKey.privateKey, {name: "RSA-OAEP"}, {name: "AES-GCM", length: 256}, false, ["decrypt"]);
      await verifyAudio(beforeRelaunch, key, expected);
      await first.deactivate(); flowStore.close(); queueStorage.close();
      flowStore = await EncryptedIndexedDbFlowStore.open({databaseName: flowName, indexedDB, crypto});
      queueStorage = await EncryptedIndexedDbQueueStorage.open({databaseName: queueName, indexedDB, crypto});
      const recovered = create();
      expect(await recovered.restore()).toBe(true); expect(recovered.snapshot.state).toBe("paused");
      expect(phone.starts).toBe(1); expect(await encrypted()).toEqual(beforeRelaunch);
      phone.offerRetiredPacket(); await new Promise<void>(resolve => setImmediate(resolve));
      expect(recovered.snapshot.recordedChunks).toBe(expected.length);
      step("Reopen app; saved visit stays paused and obsolete audio is ignored", recovered);
      if (scenario === "background") {
        await expect(recovered.resumeRecording()).rejects.toMatchObject({code: "audio_capture_unavailable"});
        expect(phone.starts).toBe(1); expect(recovered.snapshot.state).toBe("paused");
        phone.state = "foreground";
        step("Resume is blocked while phone remains backgrounded", recovered);
      }
      await recovered.resumeRecording(); expect(phone.starts).toBe(2);
      expected.push(pcm(160_000, 3)); await phone.offer(0, expected.at(-1)!);
      const final = pcm(4_000, 4); expected.push(final);
      phone.final = {sessionToken: phone.token, sequenceNumber: 1, pcmBase64: Buffer.from(final).toString("base64")};
      step("Tap Resume; speak second invented segment", recovered);
      upload.mockRejectedValueOnce(new Error("invented offline upload"));
      await expect(recovered.stopRecording()).rejects.toThrow();
      expect(recovered.snapshot).toMatchObject({state: "uploading", statusCode: "capture_upload_pending", recordedChunks: expected.length});
      expect(phone.active).toBe(false); expect(phone.listeners).toBe(0); expect(complete).not.toHaveBeenCalled();
      const pending = await flowStore.getActiveCaptureState();
      const retained = (await queueStorage.list()).filter(row => "envelope" in row);
      expect(retained).toHaveLength(expected.length);
      const all = retained.map(row => row as EncryptedChunkRecord).sort((a, b) => a.reservation.sequenceNumber - b.reservation.sequenceNumber);
      await verifyAudio(all, key, expected);
      step("Tap Stop; final 250ms is saved and offline upload remains recoverable", recovered);
      now += 120_000; // Retry clock only, no user dwell or wall-clock sleep.
      await recovered.resumePendingWork();
      expect(recovered.snapshot).toMatchObject({state: "processing", recordedChunks: expected.length});
      expect(complete).toHaveBeenCalledTimes(1); expect(register).toHaveBeenCalledTimes(expected.length);
      expect(new Set(register.mock.calls.map(call => call[1].object_id)).size).toBe(expected.length);
      expect(complete.mock.calls[0]?.[1].channels).toEqual([{channel: "microphone", final_sequence_number: expected.length - 1}]);
      expect((await queueStorage.list()).filter(row => row.state === "purged")).toHaveLength(expected.length);
      expect((await flowStore.getActiveCaptureState())?.completeIdempotencyKey).toBe(pending?.completeIdempotencyKey);
      expect(phone.starts).toBe(2);
      step("Retry saved work; all chunks have receipts and one completion enters review", recovered);
      const evidenceRoot = process.env.COSMABOT_RECORDING_EVIDENCE_DIR;
      const output = evidenceRoot ? evidenceRoot + "/native" : undefined;
      if (output) {
        // Metadata only: no waveforms, wrapped keys or authorization values.
        await mkdir(output, {recursive: true});
        await writeFile(output + "/nurse-" + scenario + "-r" + repeat + ".json", JSON.stringify({
          scenario, repeat, status: "pass", syntheticAudio: true, mountedUI: false,
          optionalDOB: "no DOB in admission payload", steps, chunks: expected.length,
          pcmFrames: expected.reduce((sum, bytes) => sum + bytes.length / 2, 0),
          pcmSha256: expected.map(bytes => createHash("sha256").update(bytes).digest("hex")),
          starts: phone.starts, stops: phone.stops, activeListenersAtCompletion: phone.listeners,
          completeRequests: complete.mock.calls.length, registrationRequests: register.mock.calls.length,
          limits: ["Generated plugin audio is not a physical iPhone microphone/route test", "HTTP receiver is synthetic", "Transcript generation and speech recognition are not evaluated"],
        }, null, 2) + "\n");
      }
    } finally {
      for (const controller of controllers) await controller.deactivate().catch(() => undefined);
      await source.stop().catch(() => undefined); flowStore.close(); queueStorage.close();
      await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
    }
  }, 20_000,
);

function pcm(frames: number, segment: number): Uint8Array {
  const bytes = new Uint8Array(new ArrayBuffer(frames * 2)), view = new DataView(bytes.buffer);
  for (let frame = 0; frame < frames; frame += 1) {
    // Deterministic signed varying samples catch truncation and stale segments.
    view.setInt16(frame * 2, ((frame * 17 + segment * 3_001) % 24_001) - 12_000, true);
  }
  return bytes;
}

async function verifyAudio(records: readonly EncryptedChunkRecord[], key: CryptoKey, expected: readonly Uint8Array[]): Promise<void> {
  expect(records).toHaveLength(expected.length);
  for (const [index, row] of records.entries()) {
    expect(row.reservation.sequenceNumber).toBe(index);
    const {header, ciphertext} = parseEnvelope(row.envelope);
    const wav = new Uint8Array(await crypto.subtle.decrypt({name: "AES-GCM",
      iv: Uint8Array.from(base64UrlDecode(header.nonce)),
      additionalData: Uint8Array.from(base64UrlDecode(row.reservation.additionalAuthenticatedData))}, key, Uint8Array.from(ciphertext)));
    try {
      expect(new TextDecoder().decode(wav.subarray(0, 4))).toBe("RIFF");
      expect(new DataView(wav.buffer).getUint32(24, true)).toBe(16_000);
      expect(new DataView(wav.buffer).getUint32(40, true)).toBe(expected[index]!.length);
      expect(wav.subarray(44)).toEqual(expected[index]);
    } finally { wav.fill(0); }
  }
}

async function listen(server: Server): Promise<string> {
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => { server.off("error", reject); resolve(); });
  });
  return "http://127.0.0.1:" + (server.address() as AddressInfo).port;
}
