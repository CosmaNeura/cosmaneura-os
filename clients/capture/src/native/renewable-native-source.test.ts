import { afterEach, expect, it, vi } from "vitest";
import type { CaptureCapabilities } from "../bff/contracts";
import type { CaptureSourceExtension } from "../capture/source";
import type { IOSPCMPlugin, IosPcmConfiguration, IosPcmEvent, IosPcmStopResult } from "../../plugins/ios-pcm/definitions";
import { CapacitorIosNativePcmBridge } from "./capacitor-ios-native-pcm-bridge";
import { IosNativeMicrophoneCaptureSource } from "./ios-native-microphone-source";

const capabilities: CaptureCapabilities = {
  protocol_version: "1.0", media: { media_type: "audio/wav", encoding: "pcm_s16le", channels: 1, sample_rate_hz: 16_000 },
  target_chunk_duration_ms: 1, max_envelope_bytes: 80, max_chunks: 2,
  remaining_aggregate_plaintext_bytes: 640, capture_lease_ttl_seconds: 30,
  reservation_window_seconds: 30, max_reservations_per_batch: 2, upload_concurrency: 1,
};
const authority = () => ({ runId: crypto.randomUUID(), generation: 1, expiresAtMs: Date.now() + 10_000, hardMaximumChunks: 8 });
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(yes => { resolve = yes; });
  return { promise, resolve };
}
function harness() {
  let listener: ((event: IosPcmEvent) => void) | undefined;
  const remove = vi.fn(async () => { listener = undefined; });
  const plugin = {
    getAppState: vi.fn(async () => ({ state: "foreground" as const })),
    getCaptureCapabilities: vi.fn(async () => ({ version: 1 as const, renewableAuthority: true })),
    start: vi.fn(async (_configuration: IosPcmConfiguration) => ({ sessionToken: "1.synthetic" })),
    ready: vi.fn(async () => ({})), heartbeat: vi.fn(async () => ({})),
    extend: vi.fn(async (options: { sessionToken: string; extension: CaptureSourceExtension }) => ({ sessionToken: options.sessionToken, ...options.extension })),
    stop: vi.fn(async (_options: { sessionToken: string; mode: "drain" | "discard" }): Promise<IosPcmStopResult> => ({ finalPcmPacket: null })),
    acknowledge: vi.fn(async () => ({ result: "accepted" as const })),
    replayPendingPacket: vi.fn(async () => ({ result: "stale" as const })),
    addListener: vi.fn(async (_eventName: string, notify: (event: IosPcmEvent) => void) => { listener = notify; return { remove }; }),
  } satisfies IOSPCMPlugin;
  const bridge = new CapacitorIosNativePcmBridge(plugin);
  const source = new IosNativeMicrophoneCaptureSource(bridge);
  const emit = (event: IosPcmEvent) => listener?.(event);
  const packet = (sequenceNumber: number, frames = 16) => ({ sessionToken: "1.synthetic", sequenceNumber,
    pcmBase64: Buffer.from(new Uint8Array(new Int16Array(Array(frames).fill(1234)).buffer)).toString("base64") });
  return { plugin, bridge, source, emit, packet, remove };
}

it.each(["missing", "disabled", "rejected", "wrong-version"])("rejects %s native support before audio Start", async kind => {
  const h = harness();
  if (kind === "missing") (h.plugin as IOSPCMPlugin).getCaptureCapabilities = undefined;
  if (kind === "disabled") h.plugin.getCaptureCapabilities.mockResolvedValue({ version: 1, renewableAuthority: false });
  if (kind === "rejected") h.plugin.getCaptureCapabilities.mockRejectedValue(new Error("native method absent"));
  if (kind === "wrong-version") h.plugin.getCaptureCapabilities.mockResolvedValue({ version: 2, renewableAuthority: true } as never);
  await expect(h.source.start({ capabilities, authority: authority(), onChunk: async () => {} })).rejects.toThrow();
  expect(h.plugin.start).not.toHaveBeenCalled();
  expect(h.plugin.addListener).not.toHaveBeenCalled();
  await h.source.stop();
});

it.each([undefined, { version: 1, idle: false }, { version: 2, idle: true }, { version: 1, idle: true, extra: true }, null])(
  "does not infer closure from an unavailable or invalid native idle proof: %j", async result => {
    const h = harness();
    if (result !== undefined) (h.plugin as IOSPCMPlugin).confirmCaptureIdle = vi.fn().mockResolvedValue(result);
    expect(await h.source.confirmRecoveryClosed()).toBe(false);
    expect(h.plugin.start).not.toHaveBeenCalled();
    expect(h.plugin.stop).not.toHaveBeenCalled();
  });

it("requires exact process-wide native idle proof without starting or stopping audio", async () => {
  const h = harness();
  const proof = vi.fn().mockRejectedValueOnce(new Error("unavailable")).mockResolvedValue({ version: 1, idle: true });
  (h.plugin as IOSPCMPlugin).confirmCaptureIdle = proof;
  expect(await h.source.confirmRecoveryClosed()).toBe(false);
  expect(await h.source.confirmRecoveryClosed()).toBe(true);
  expect(h.plugin.start).not.toHaveBeenCalled(); expect(h.plugin.stop).not.toHaveBeenCalled();
  await h.source.start({ capabilities, authority: authority(), onChunk: async () => {} });
  expect(await h.source.confirmRecoveryClosed()).toBe(false);
  expect(proof).toHaveBeenCalledTimes(2);
  await h.source.stop();
});

it("bounds an unresponsive native idle probe and rejects its late confirmation", async () => {
  vi.useFakeTimers();
  const h = harness(), gate = deferred<{version:1;idle:boolean}>();
  (h.plugin as IOSPCMPlugin).confirmCaptureIdle = () => gate.promise;
  const checking = h.source.confirmRecoveryClosed();
  await vi.advanceTimersByTimeAsync(1_000);
  expect(await checking).toBe(false);
  gate.resolve({version:1,idle:true}); await Promise.resolve();
  expect(h.plugin.start).not.toHaveBeenCalled(); expect(h.plugin.stop).not.toHaveBeenCalled();
});

it("rejects a stale idle reply when a new native run began and closed during the query", async () => {
  const h = harness(), gate = deferred<{version:1;idle:boolean}>();
  (h.plugin as IOSPCMPlugin).confirmCaptureIdle = () => gate.promise;
  const checking = h.source.confirmRecoveryClosed();
  await h.source.start({ capabilities, authority: authority(), onChunk: async () => {} });
  await h.source.stop(); gate.resolve({version:1,idle:true});
  expect(await checking).toBe(false);
});

it("retains the legacy native configuration when no authority was requested", async () => {
  const h = harness();
  (h.plugin as IOSPCMPlugin).getCaptureCapabilities = undefined;
  await h.source.start({ capabilities, onChunk: async () => {} });
  expect(h.plugin.start.mock.calls[0]![0].authority).toBeUndefined();
  await h.source.stop();
});

it("preserves WAV sequence across three native extensions and one recording", async () => {
  const h = harness(), grant = authority(), saved: number[] = [], ended = vi.fn();
  await h.source.start({ capabilities, authority: grant, onWindowClosed: ended,
    onChunk: async chunk => { saved.push(chunk.sequenceNumber); expect(new DataView(chunk.wavBytes.buffer).getInt16(44, true)).toBe(1234); } });
  for (let sequence = 0; sequence < 8; sequence++) {
    if ([1, 3, 5].includes(sequence)) {
      const generation = (sequence + 3) / 2;
      const value = { runId: grant.runId, generation, expiresAtMs: grant.expiresAtMs + generation * 1_000, maximumChunks: sequence + 3 };
      await h.source.extend(value);
      await h.source.extend(value);
    }
    h.emit({ kind: "packet", packet: h.packet(sequence) });
    await vi.waitFor(() => expect(h.plugin.acknowledge).toHaveBeenCalledTimes(sequence + 1));
  }
  h.emit({ kind: "window_closed", sessionToken: "1.synthetic", reason: "frame_limit" });
  await vi.waitFor(() => expect(ended).toHaveBeenCalledWith("frame_limit"));
  expect(saved).toEqual([0, 1, 2, 3, 4, 5, 6, 7]);
  expect(h.plugin.start).toHaveBeenCalledTimes(1);
  expect(h.plugin.start.mock.calls[0]![0].authority).toEqual(grant);
  expect(h.plugin.stop).toHaveBeenCalledWith({ sessionToken: "1.synthetic", mode: "drain" });
  expect(h.remove).toHaveBeenCalledOnce();
  await expect(h.source.extend({ runId: grant.runId, generation: 5, expiresAtMs: grant.expiresAtMs + 5_000, maximumChunks: 8 })).rejects.toThrow();
});

it("waits for exact native acknowledgment and accepts packets already admitted by that extension", async () => {
  const h = harness(), grant = authority(), gate = deferred<{ sessionToken: string } & CaptureSourceExtension>(), saved: number[] = [];
  await h.source.start({ capabilities, authority: grant, onChunk: async chunk => { saved.push(chunk.sequenceNumber); } });
  h.plugin.extend.mockReturnValue(gate.promise);
  const value = { runId: grant.runId, generation: 2, expiresAtMs: grant.expiresAtMs + 1_000, maximumChunks: 4 };
  let confirmed = false;
  const extending = h.source.extend(value).then(() => { confirmed = true; });
  const duplicate = h.source.extend(value);
  await vi.waitFor(() => expect(h.plugin.extend).toHaveBeenCalledOnce());
  value.maximumChunks = 8;
  for (let sequence = 0; sequence < 3; sequence++) {
    h.emit({ kind: "packet", packet: h.packet(sequence) });
    await vi.waitFor(() => expect(h.plugin.acknowledge).toHaveBeenCalledTimes(sequence + 1));
  }
  expect(confirmed).toBe(false);
  gate.resolve({ sessionToken: "1.synthetic", ...value, maximumChunks: 4 });
  await extending; await duplicate;
  expect(saved).toEqual([0, 1, 2]);
  expect(h.plugin.extend.mock.calls[0]![0].extension.maximumChunks).toBe(4);
  await h.source.stop();
});

it.each(["sessionToken", "runId", "generation", "maximumChunks", "expiresAtMs", "extra"])("closes on a mismatched %s acknowledgment", async field => {
  const h = harness(), grant = authority(), onError = vi.fn();
  await h.source.start({ capabilities, authority: grant, onChunk: async () => {}, onError });
  h.plugin.extend.mockImplementation(async options => ({ sessionToken: options.sessionToken, ...options.extension, [field]: "changed" }) as never);
  await expect(h.source.extend({ runId: grant.runId, generation: 2, expiresAtMs: grant.expiresAtMs + 1_000, maximumChunks: 4 })).rejects.toThrow();
  await h.source.stop();
  expect(onError).toHaveBeenCalledWith("capture_source_failed");
  expect(h.plugin.stop).toHaveBeenCalledWith({ sessionToken: "1.synthetic", mode: "discard" });
});

it("Stop cancels pending native acknowledgment and ignores its late reply", async () => {
  const h = harness(), grant = authority(), gate = deferred<{ sessionToken: string } & CaptureSourceExtension>(), onError = vi.fn();
  await h.source.start({ capabilities, authority: grant, onChunk: async () => {}, onError });
  h.plugin.extend.mockReturnValue(gate.promise);
  const value = { runId: grant.runId, generation: 2, expiresAtMs: grant.expiresAtMs + 1_000, maximumChunks: 4 };
  const extending = expect(h.source.extend(value)).rejects.toThrow();
  await vi.waitFor(() => expect(h.plugin.extend).toHaveBeenCalledOnce());
  await h.source.stop(); await extending;
  gate.resolve({ sessionToken: "1.synthetic", ...value });
  await Promise.resolve();
  expect(h.plugin.start).toHaveBeenCalledOnce();
  expect(onError).not.toHaveBeenCalled();
  expect(h.plugin.stop).toHaveBeenCalledWith({ sessionToken: "1.synthetic", mode: "drain" });
});

it("Stop during a support probe settles before its late reply without opening audio", async () => {
  const h = harness(), gate = deferred<{ version: 1; renewableAuthority: boolean }>();
  h.plugin.getCaptureCapabilities.mockReturnValue(gate.promise);
  const starting = expect(h.source.start({ capabilities, authority: authority(), onChunk: async () => {} })).rejects.toThrow();
  await vi.waitFor(() => expect(h.plugin.getCaptureCapabilities).toHaveBeenCalledOnce());
  await h.source.stop(); await starting;
  gate.resolve({ version: 1, renewableAuthority: true });
  await Promise.resolve();
  expect(h.plugin.start).not.toHaveBeenCalled();
});

it("drains and saves the final partial before reporting native expiry", async () => {
  const h = harness(), gate = deferred<void>(), ended = vi.fn(), saved: number[] = [];
  await h.source.start({ capabilities, authority: authority(), onWindowClosed: ended,
    onChunk: async chunk => { await gate.promise; saved.push(chunk.sequenceNumber); } });
  h.plugin.stop.mockResolvedValue({ finalPcmPacket: h.packet(0, 4) });
  h.emit({ kind: "window_closed", sessionToken: "99.foreign", reason: "authority_expired" });
  expect(h.plugin.stop).not.toHaveBeenCalled();
  h.emit({ kind: "window_closed", sessionToken: "1.synthetic", reason: "authority_expired" });
  await vi.waitFor(() => expect(h.plugin.stop).toHaveBeenCalledOnce());
  expect(ended).not.toHaveBeenCalled();
  gate.resolve();
  await vi.waitFor(() => expect(ended).toHaveBeenCalledWith("authority_expired"));
  expect(saved).toEqual([0]);
  expect(h.plugin.acknowledge).not.toHaveBeenCalled();
});

it("times out an unconfirmed native extension and closes capture", async () => {
  const h = harness(), grant = authority(), onError = vi.fn();
  await h.source.start({ capabilities, authority: grant, onChunk: async () => {}, onError });
  vi.useFakeTimers();
  h.plugin.extend.mockReturnValue(new Promise(() => {}));
  const failed = expect(h.source.extend({ runId: grant.runId, generation: 2, expiresAtMs: grant.expiresAtMs + 1_000, maximumChunks: 4 })).rejects.toThrow();
  await vi.advanceTimersByTimeAsync(1_001);
  await failed; await h.source.stop();
  expect(onError).toHaveBeenCalledWith("capture_source_failed");
});
