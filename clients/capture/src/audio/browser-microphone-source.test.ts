import { afterEach, describe, expect, it, vi } from "vitest";

import type { CaptureCapabilities } from "../bff/contracts";
import {
  BrowserMicrophoneCaptureSource,
  type BrowserMicrophoneDependencies,
} from "./browser-microphone-source";

const capabilities: CaptureCapabilities = {
  protocol_version: "1.0",
  media: {
    media_type: "audio/wav",
    encoding: "pcm_s16le",
    channels: 1,
    sample_rate_hz: 16_000,
  },
  target_chunk_duration_ms: 1,
  max_envelope_bytes: 80,
  max_chunks: 2,
  remaining_aggregate_plaintext_bytes: 160,
  capture_lease_ttl_seconds: 30,
  reservation_window_seconds: 30,
  max_reservations_per_batch: 2,
  upload_concurrency: 1,
};
afterEach(() => vi.restoreAllMocks());

function authority() { return { runId: globalThis.crypto.randomUUID(), generation: 1, expiresAtMs: Date.now() + 50000, hardMaximumChunks: 4 }; }

it("extends the same browser stream after producer confirmation, retaining partial audio and sequence", async () => {
  const h = createHarness(), source = new BrowserMicrophoneCaptureSource(h.dependencies), grant = authority();
  const chunks: { sequence: number; pcm: readonly number[] }[] = [];
  vi.mocked(h.worklet.port.postMessage).mockImplementation(message => {
    if (message.type === "extend") queueMicrotask(() => h.worklet.control({ type: "extended", version: 1, runId: message.runId, bounds: message.bounds }));
  });
  await source.start({ capabilities, authority: grant, onChunk: async chunk => { chunks.push({ sequence: chunk.sequenceNumber, pcm: readPcm16(chunk.wavBytes) }); } });
  for (let n = 0; n < 3; n++) { h.worklet.dispatch(n, Array(16).fill(0.5)); await Promise.resolve(); await Promise.resolve(); }
  const command = { runId: grant.runId, generation: 2, expiresAtMs: grant.expiresAtMs + 50000, maximumChunks: 4 };
  await source.extend(command); await source.extend(command);
  for (let n = 3; n < 8; n++) { h.worklet.dispatch(n, Array(16).fill(0.5)); await Promise.resolve(); await Promise.resolve(); }
  await source.stop();
  expect(chunks.map(chunk => chunk.sequence)).toEqual([0, 1, 2, 3]);
  expect(chunks.every(chunk => chunk.pcm.length === 16 && chunk.pcm.every(value => value === 16384))).toBe(true);
  expect(h.getUserMedia).toHaveBeenCalledTimes(1);
  expect(vi.mocked(h.worklet.port.postMessage).mock.calls.filter(([message]) => message.type === "extend")).toHaveLength(1);
  expect(h.worklet.options?.processorOptions?.captureBounds).toMatchObject({ runId: grant.runId, maximumInputFrames: 64, hardMaximumInputFrames: 128 });
  await expect(source.extend({ ...command, generation: 3 })).rejects.toThrow("audio_capture_unavailable");
});

it("keeps an extension pending until the producer acknowledges the exact bounds", async () => {
  const h = createHarness(), source = new BrowserMicrophoneCaptureSource(h.dependencies), grant = authority();
  await source.start({ capabilities, authority: grant, onChunk: async () => {} });
  const command = { runId: grant.runId, generation: 2, expiresAtMs: grant.expiresAtMs + 50000, maximumChunks: 4 };
  let confirmed = false;
  const pending = source.extend(command).then(() => { confirmed = true; });
  await Promise.resolve(); expect(confirmed).toBe(false);
  const sent = vi.mocked(h.worklet.port.postMessage).mock.calls.find(([message]) => message.type === "extend")![0];
  h.worklet.control({ type: "extended", version: 1, runId: grant.runId, bounds: sent.bounds });
  await pending; expect(confirmed).toBe(true); await source.stop();
});

it("rejects a pending extension immediately on Stop and ignores its late acknowledgment", async () => {
  const h = createHarness(), source = new BrowserMicrophoneCaptureSource(h.dependencies), grant = authority();
  await source.start({ capabilities, authority: grant, onChunk: async () => {} });
  const extending = source.extend({ runId: grant.runId, generation: 2, expiresAtMs: grant.expiresAtMs + 50000, maximumChunks: 4 });
  const rejected = expect(extending).rejects.toThrow("audio_capture_unavailable");
  const sent = vi.mocked(h.worklet.port.postMessage).mock.calls.find(([message]) => message.type === "extend")![0];
  await source.stop(); await rejected;
  h.worklet.control({ type: "extended", version: 1, runId: grant.runId, bounds: sent.bounds });
  expect(h.track.stopped).toBe(true); expect(h.getUserMedia).toHaveBeenCalledTimes(1);
});

it("closes input when producer confirmation is missing", async () => {
  const h = createHarness(), source = new BrowserMicrophoneCaptureSource(h.dependencies), grant = authority(), onError = vi.fn();
  await source.start({ capabilities, authority: grant, onChunk: async () => {}, onError });
  await expect(source.extend({ runId: grant.runId, generation: 2, expiresAtMs: grant.expiresAtMs + 50000, maximumChunks: 4 })).rejects.toThrow("audio_capture_unavailable");
  expect(h.track.stopped).toBe(true); expect(onError).toHaveBeenCalledWith("capture_source_failed"); await source.stop();
});

it("drains fully accepted chunks before reporting a producer window close", async () => {
  const h = createHarness(), source = new BrowserMicrophoneCaptureSource(h.dependencies), grant = authority(), gate = deferred();
  const onWindowClosed = vi.fn(), saved: Uint8Array[] = [];
  await source.start({ capabilities, authority: grant, onWindowClosed,
    onChunk: async chunk => { await gate.promise; saved.push(chunk.wavBytes.slice()); } });
  for (let n = 0; n < 4; n++) h.worklet.dispatch(n, Array(16).fill(0.5));
  h.worklet.control({ type: "window_closed", version: 1, runId: grant.runId, reason: "frame_limit" });
  expect(h.track.stopped).toBe(true); expect(onWindowClosed).not.toHaveBeenCalled();
  gate.resolve(); await vi.waitFor(() => expect(onWindowClosed).toHaveBeenCalledWith("frame_limit"));
  expect(saved).toHaveLength(2); expect(saved.every(wav => readPcm16(wav).every(value => value === 16384))).toBe(true);
  await expect(source.extend({ runId: grant.runId, generation: 2, expiresAtMs: grant.expiresAtMs + 50000, maximumChunks: 4 })).rejects.toThrow();
});

it("rejects source authority beyond the hard budget before requesting a microphone", async () => {
  const h = createHarness(), source = new BrowserMicrophoneCaptureSource(h.dependencies);
  await expect(source.start({ capabilities, authority: { ...authority(), hardMaximumChunks: 1 }, onChunk: async () => {} })).rejects.toThrow();
  expect(h.getUserMedia).not.toHaveBeenCalled();
});

it("cannot reuse a stopped run identifier for a new microphone Start", async () => {
  const h = createHarness(), source = new BrowserMicrophoneCaptureSource(h.dependencies), grant = authority();
  await source.start({ capabilities, authority: grant, onChunk: async () => {} }); await source.stop();
  await expect(source.start({ capabilities, authority: grant, onChunk: async () => {} })).rejects.toThrow("audio_capture_stale_generation");
  expect(h.getUserMedia).toHaveBeenCalledTimes(1);
});

it("clears rejected and late transferred PCM without reviving the source", async () => {
  const h = createHarness(), source = new BrowserMicrophoneCaptureSource(h.dependencies), onError = vi.fn();
  await source.start({ capabilities, onError, onChunk: async () => {} });
  const receive = h.worklet.port.onmessage!;
  const invalid = new Float32Array([0.5, 0.5]);
  h.worklet.control({ type: "pcm", version: 1, sequence: 1, frames: invalid.buffer });
  expect(invalid.every(value => value === 0)).toBe(true); await source.stop();
  const late = new Float32Array([0.25, 0.25]);
  receive.call(h.worklet.port, { data: { type: "pcm", version: 1, sequence: 0, frames: late.buffer } } as MessageEvent);
  expect(late.every(value => value === 0)).toBe(true); expect(onError).toHaveBeenCalledTimes(1);
});

it("retains shutdown ownership until an in-flight chunk settles even if flushing exceeds backpressure", async () => {
  const h = createHarness(), source = new BrowserMicrophoneCaptureSource(h.dependencies), grant = authority(), gate = deferred();
  const onError = vi.fn();
  await source.start({ capabilities: { ...capabilities, max_chunks: 3, remaining_aggregate_plaintext_bytes: 240 },
    authority: grant, onError, onChunk: async () => gate.promise });
  for (let n = 0; n < 5; n++) h.worklet.dispatch(n, Array(16).fill(0.5));
  await Promise.resolve();
  h.worklet.control({ type: "window_closed", version: 1, runId: grant.runId, reason: "authority_expired" });
  await Promise.resolve(); await Promise.resolve();
  await expect(source.start({ capabilities, onChunk: async () => {} })).rejects.toThrow("audio_capture_already_active");
  const stopping = source.stop(), rejected = expect(stopping).rejects.toThrow("audio_capture_callback_failed");
  gate.resolve(); await rejected;
  expect(h.track.stopped).toBe(true); expect(h.context.state).toBe("closed");
});

describe("BrowserMicrophoneCaptureSource", () => {
  it("runs getUserMedia through AudioWorklet and emits capability-shaped PCM16 WAV", async () => {
    const harness = createHarness();
    const chunks: Array<{
      readonly sequenceNumber: number;
      readonly durationMs: number;
      readonly wavBytes: Uint8Array;
    }> = [];
    let deliveredBytes: Uint8Array | undefined;
    const source = new BrowserMicrophoneCaptureSource(harness.dependencies);

    await source.start({
      capabilities,
      onChunk: async (chunk) => {
        deliveredBytes = chunk.wavBytes;
        chunks.push({ ...chunk, wavBytes: chunk.wavBytes.slice() });
      },
    });
    harness.worklet.dispatch(
      0,
      [0, 0, 0.25, 0.25, 0.5, 0.5, 0.75, 0.75, 0, 0, 0.25, 0.25, 0.5, 0.5, 0.75, 0.75],
    );
    harness.worklet.dispatch(
      1,
      [1, 1, 0.75, 0.75, 0.5, 0.5, 0.25, 0.25, 1, 1, 0.75, 0.75, 0.5, 0.5, 0.25, 0.25],
    );
    await source.stop();

    expect(harness.getUserMedia).toHaveBeenCalledWith({
      audio: {
        autoGainControl: false,
        channelCount: { ideal: capabilities.media.channels },
        echoCancellation: false,
        noiseSuppression: false,
        sampleRate: { ideal: capabilities.media.sample_rate_hz },
      },
      video: false,
    });
    expect(harness.addModule).toHaveBeenCalledWith(
      expect.stringContaining("pcm-capture-worklet.ts"),
    );
    expect(chunks).toHaveLength(1);
    expect(chunks[0]).toMatchObject({ sequenceNumber: 0, durationMs: 1 });
    const wav = chunks[0]?.wavBytes;
    expect(new TextDecoder().decode(wav?.subarray(0, 4))).toBe("RIFF");
    expect(new TextDecoder().decode(wav?.subarray(8, 12))).toBe("WAVE");
    const view = new DataView(wav?.buffer ?? new ArrayBuffer(0));
    expect(view.getUint32(24, true)).toBe(capabilities.media.sample_rate_hz);
    expect(wav?.byteLength).toBe(76);
    expect(readPcm16(wav)).toEqual([
      0, 8_192, 16_384, 24_575, 0, 8_192, 16_384, 24_575,
      32_767, 24_575, 16_384, 8_192, 32_767, 24_575, 16_384, 8_192,
    ]);
    expect(deliveredBytes?.every((value) => value === 0)).toBe(true);
    expect(harness.track.stopped).toBe(true);
    expect(harness.context.state).toBe("closed");
  });

  it("flushes a final short WAV without silence padding", async () => {
    const harness = createHarness();
    const chunks: Array<{ readonly durationMs: number; readonly wavBytes: Uint8Array }> = [];
    const source = new BrowserMicrophoneCaptureSource(harness.dependencies);
    await source.start({
      capabilities,
      onChunk: async (chunk) => {
        chunks.push({ ...chunk, wavBytes: chunk.wavBytes.slice() });
      },
    });
    harness.worklet.dispatch(0, [0.5, 0.5]);
    await source.stop();

    expect(chunks).toHaveLength(1);
    expect(chunks[0]?.durationMs).toBe(0.0625);
    expect(chunks[0]?.wavBytes.byteLength).toBe(46);
    expect(readPcm16(chunks[0]?.wavBytes)).toEqual([16_384]);
  });

  it("stops input immediately when browser cleanup is delayed and rejects late audio", async () => {
    const harness = createHarness();
    const cleanup = deferred();
    const suspension = deferred();
    harness.context.suspend = () => suspension.promise;
    harness.context.close = async () => { await cleanup.promise; harness.context.state = "closed"; };
    const chunks: Uint8Array[] = [];
    const source = new BrowserMicrophoneCaptureSource(harness.dependencies);
    await source.start({capabilities, onChunk: async chunk => { chunks.push(chunk.wavBytes.slice()); }});
    harness.worklet.dispatch(0, [0.5, 0.5]);
    const stopping = source.stop();
    expect(harness.track.stopped).toBe(true);
    harness.worklet.dispatch(1, [1, 1]);
    cleanup.resolve(); suspension.resolve();
    await stopping;
    expect(chunks).toHaveLength(1);
    expect(readPcm16(chunks[0])).toEqual([16_384]);
  });

  it("fails closed when AudioWorklet continuity is broken", async () => {
    const harness = createHarness();
    const onError = vi.fn();
    const source = new BrowserMicrophoneCaptureSource(harness.dependencies);
    await source.start({
      capabilities,
      onChunk: async () => undefined,
      onError,
    });
    harness.worklet.dispatch(1, [0, 0]);
    expect(onError).toHaveBeenCalledOnce();
    expect(onError).toHaveBeenCalledWith("capture_source_stalled");
    await Promise.resolve();
    await expect(source.stop()).resolves.toBeUndefined();
  });

  it("reports device and route interruptions immediately with fixed codes", async () => {
    const disconnected = createHarness();
    const disconnectedCallback = vi.fn();
    const disconnectedSource = new BrowserMicrophoneCaptureSource(disconnected.dependencies);
    await disconnectedSource.start({
      capabilities,
      onChunk: async () => undefined,
      onInterruption: disconnectedCallback,
    });
    disconnected.track.dispatchEvent(new Event("ended"));
    expect(disconnectedCallback).toHaveBeenCalledWith("audio_device_disconnected");
    await expect(disconnectedSource.stop()).resolves.toBeUndefined();

    const routeChanged = createHarness();
    const routeChangedCallback = vi.fn();
    const routeChangedSource = new BrowserMicrophoneCaptureSource(routeChanged.dependencies);
    await routeChangedSource.start({
      capabilities,
      onChunk: async () => undefined,
      onInterruption: routeChangedCallback,
    });
    routeChanged.track.dispatchEvent(new Event("mute"));
    expect(routeChangedCallback).toHaveBeenCalledWith("audio_route_changed");
    await expect(routeChangedSource.stop()).resolves.toBeUndefined();
  });

  it("reports an unexpected AudioContext suspension before cleanup", async () => {
    const harness = createHarness();
    const onInterruption = vi.fn();
    const source = new BrowserMicrophoneCaptureSource(harness.dependencies);
    await source.start({
      capabilities,
      onChunk: async () => undefined,
      onInterruption,
    });
    harness.context.interrupt();
    expect(onInterruption).toHaveBeenCalledWith("audio_context_suspended");
    await expect(source.stop()).resolves.toBeUndefined();
  });

  it("stops foreground capture on visibility loss or page hide", async () => {
    const hidden = createHarness();
    const hiddenCallback = vi.fn();
    const hiddenSource = new BrowserMicrophoneCaptureSource(hidden.dependencies);
    await hiddenSource.start({
      capabilities,
      onChunk: async () => undefined,
      onInterruption: hiddenCallback,
    });
    hidden.visibilityDocument.hide();
    expect(hiddenCallback).toHaveBeenCalledWith("capture_backgrounded");
    await expect(hiddenSource.stop()).resolves.toBeUndefined();
    expect(hidden.track.stopped).toBe(true);

    const pageHidden = createHarness();
    const pageHiddenCallback = vi.fn();
    const pageHiddenSource = new BrowserMicrophoneCaptureSource(pageHidden.dependencies);
    await pageHiddenSource.start({
      capabilities,
      onChunk: async () => undefined,
      onInterruption: pageHiddenCallback,
    });
    pageHidden.pageLifecycleWindow.dispatchEvent(new Event("pagehide"));
    expect(pageHiddenCallback).toHaveBeenCalledWith("capture_backgrounded");
    await expect(pageHiddenSource.stop()).resolves.toBeUndefined();
    expect(pageHidden.track.stopped).toBe(true);
  });

  it("refuses microphone access when the page is already hidden", async () => {
    const harness = createHarness();
    harness.visibilityDocument.hide();
    const source = new BrowserMicrophoneCaptureSource(harness.dependencies);
    await expect(
      source.start({ capabilities, onChunk: async () => undefined }),
    ).rejects.toThrow(
      expect.objectContaining({ code: "audio_capture_unavailable" }),
    );
    expect(harness.getUserMedia).not.toHaveBeenCalled();
  });

  it("closes a stream if the page is hidden while permission is pending", async () => {
    const harness = createHarness();
    let resolveStream: ((stream: MediaStream) => void) | undefined;
    harness.getUserMedia.mockReturnValueOnce(new Promise((resolve) => {
      resolveStream = resolve;
    }));
    const source = new BrowserMicrophoneCaptureSource(harness.dependencies);
    const start = source.start({ capabilities, onChunk: async () => undefined });
    harness.visibilityDocument.hide();
    resolveStream?.(harness.stream);

    await expect(start).rejects.toThrow(
      expect.objectContaining({ code: "audio_capture_unavailable" }),
    );
    expect(harness.track.stopped).toBe(true);
    await expect(source.stop()).resolves.toBeUndefined();
  });

  it("reports real permission and worklet waits without letting a throwing observer interrupt capture", async () => {
    const harness = createHarness();
    let resolveStream!: (stream: MediaStream) => void, resolveModule!: () => void;
    harness.getUserMedia.mockReturnValueOnce(new Promise(resolve => { resolveStream = resolve; }));
    harness.addModule.mockReturnValueOnce(new Promise<void>(resolve => { resolveModule = resolve; }));
    const source = new BrowserMicrophoneCaptureSource(harness.dependencies), stages:string[]=[];
    const starting = source.start({capabilities,onChunk:async()=>{},onStartupStage:stage=>{stages.push(stage);throw Error("Synthetic observer failure");}});
    expect(stages).toEqual(["microphone_permission"]);expect(harness.addModule).not.toHaveBeenCalled();
    resolveStream(harness.stream);await vi.waitFor(()=>expect(harness.addModule).toHaveBeenCalledOnce());
    expect(stages).toEqual(["microphone_permission","audio_engine"]);expect(harness.context.state).toBe('suspended');
    resolveModule();await starting;expect(harness.track.stopped).toBe(false);await source.stop();expect(harness.track.stopped).toBe(true);
  });

  it.each([false, true])("stops a late permission result after shutdown (authority revoked: %s)", async (revoke) => {
    const harness = createHarness();
    let resolveStream!: (stream: MediaStream) => void;
    harness.getUserMedia.mockReturnValueOnce(new Promise(resolve => { resolveStream = resolve; }));
    const controller = new AbortController();
    const source = new BrowserMicrophoneCaptureSource(harness.dependencies);
    const onChunk = vi.fn();
    const start = source.start({ capabilities, onChunk, signal: controller.signal });
    if (revoke) controller.abort();
    await source.stop();
    const rejected = expect(start).rejects.toMatchObject(revoke
      ? { name: "AbortError" } : { code: "audio_capture_unavailable" });
    resolveStream(harness.stream);
    await rejected;
    expect(harness.track.stopped).toBe(true);
    expect(harness.addModule).not.toHaveBeenCalled();
    expect(onChunk).not.toHaveBeenCalled();
  });

  it("does not overlap a new start with a stopped permission request still in flight", async () => {
    const harness = createHarness();
    let resolveStream!: (stream: MediaStream) => void;
    harness.getUserMedia.mockReturnValueOnce(new Promise(resolve => { resolveStream = resolve; }));
    const source = new BrowserMicrophoneCaptureSource(harness.dependencies);
    const options = { capabilities, onChunk: async () => undefined };
    const start = source.start(options);
    await source.stop();
    await expect(source.start(options)).rejects.toMatchObject({ code: "audio_capture_already_active" });
    expect(harness.getUserMedia).toHaveBeenCalledTimes(1);
    const rejected = expect(start).rejects.toMatchObject({ code: "audio_capture_unavailable" });
    resolveStream(harness.stream);
    await rejected;
    expect(harness.track.stopped).toBe(true);
    const next = createHarness();
    harness.getUserMedia.mockResolvedValueOnce(next.stream);
    await source.start(options);
    expect(next.track.stopped).toBe(false);
    await source.stop();
    expect(next.track.stopped).toBe(true);
  });

  it.each([false, true])("does not report a late audio-context resume as a new recording (authority revoked: %s)", async (revoke) => {
    const harness = createHarness();
    const resumed = deferred();
    const resume = vi.fn(async () => { await resumed.promise; harness.context.state = "running"; });
    harness.context.resume = resume;
    const controller = new AbortController();
    const source = new BrowserMicrophoneCaptureSource(harness.dependencies);
    const start = source.start({ capabilities, onChunk: async () => undefined, signal: controller.signal });
    await vi.waitFor(() => expect(resume).toHaveBeenCalledOnce());
    const rejected = expect(start).rejects.toMatchObject(revoke
      ? { name: "AbortError" } : { code: "audio_capture_unavailable" });
    if (revoke) controller.abort();
    await source.stop();
    expect(harness.track.stopped).toBe(true);
    resumed.resolve();
    await rejected;
  });

  it("closes a stream when authority is aborted while the worklet module is pending", async () => {
    const harness = createHarness();
    const workletModule = deferred();
    harness.addModule.mockReturnValueOnce(workletModule.promise);
    const controller = new AbortController();
    const source = new BrowserMicrophoneCaptureSource(harness.dependencies);
    const start = source.start({
      capabilities,
      onChunk: async () => undefined,
      signal: controller.signal,
    });
    await vi.waitFor(() => expect(harness.addModule).toHaveBeenCalledOnce());
    const rejected = expect(start).rejects.toMatchObject({ name: "AbortError" });

    controller.abort();
    await vi.waitFor(() => expect(harness.track.stopped).toBe(true));
    expect(harness.context.state).toBe("closed");
    workletModule.resolve();
    await rejected;
  });

  it("closes a stream when the page hides while the worklet module is pending", async () => {
    const harness = createHarness();
    const workletModule = deferred();
    harness.addModule.mockReturnValueOnce(workletModule.promise);
    const onInterruption = vi.fn();
    const source = new BrowserMicrophoneCaptureSource(harness.dependencies);
    const start = source.start({
      capabilities,
      onChunk: async () => undefined,
      onInterruption,
    });
    await vi.waitFor(() => expect(harness.addModule).toHaveBeenCalledOnce());
    const rejected = expect(start).rejects.toThrow(
      expect.objectContaining({ code: "audio_capture_unavailable" }),
    );

    harness.visibilityDocument.hide();
    expect(onInterruption).toHaveBeenCalledWith("capture_backgrounded");
    await vi.waitFor(() => expect(harness.track.stopped).toBe(true));
    expect(harness.context.state).toBe("closed");
    workletModule.resolve();
    await rejected;
  });

  it("maps microphone denial to a fixed error without exposing browser details", async () => {
    const harness = createHarness();
    harness.getUserMedia.mockRejectedValueOnce(
      Object.assign(new Error("device-specific detail"), { name: "NotAllowedError" }),
    );
    const source = new BrowserMicrophoneCaptureSource(harness.dependencies);
    await expect(
      source.start({ capabilities, onChunk: async () => undefined }),
    ).rejects.toThrow(
      expect.objectContaining({
        code: "audio_capture_permission_denied",
        message: "audio_capture_permission_denied",
      }),
    );
    expect(harness.track.stopped).toBe(false);
  });
});

function createHarness(): {
  readonly dependencies: BrowserMicrophoneDependencies;
  readonly getUserMedia: ReturnType<typeof vi.fn<() => Promise<MediaStream>>>;
  readonly addModule: ReturnType<typeof vi.fn<(url: string) => Promise<void>>>;
  readonly context: FakeAudioContext;
  readonly visibilityDocument: FakeVisibilityDocument;
  readonly pageLifecycleWindow: EventTarget;
  readonly stream: MediaStream;
  readonly track: FakeTrack;
  readonly worklet: FakeWorkletNode;
} {
  const track = new FakeTrack();
  const stream = {
    getAudioTracks: () => [track as unknown as MediaStreamTrack],
    getTracks: () => [track as unknown as MediaStreamTrack],
  } as MediaStream;
  const getUserMedia = vi.fn<() => Promise<MediaStream>>().mockResolvedValue(stream);
  const addModule = vi.fn<(url: string) => Promise<void>>().mockResolvedValue(undefined);
  const context = new FakeAudioContext(addModule);
  const worklet = new FakeWorkletNode();
  const visibilityDocument = new FakeVisibilityDocument();
  const pageLifecycleWindow = new EventTarget();
  return {
    dependencies: {
      mediaDevices: { getUserMedia },
      createAudioContext: () => context as unknown as AudioContext,
      createAudioWorkletNode: (_context, _name, options) => { worklet.options = options; return worklet as unknown as AudioWorkletNode; },
      workletModuleUrl: new URL("./pcm-capture-worklet.ts", import.meta.url),
      visibilityDocument,
      pageLifecycleWindow,
    },
    getUserMedia,
    addModule,
    context,
    visibilityDocument,
    pageLifecycleWindow,
    stream,
    track,
    worklet,
  };
}

class FakeVisibilityDocument extends EventTarget {
  public visibilityState: DocumentVisibilityState = "visible";

  public hide(): void {
    this.visibilityState = "hidden";
    this.dispatchEvent(new Event("visibilitychange"));
  }
}

class FakeTrack extends EventTarget {
  public stopped = false;

  public stop(): void {
    this.stopped = true;
  }
}

class FakeAudioNode {
  public readonly connect = vi.fn((_destination: unknown) => _destination);
  public readonly disconnect = vi.fn();
}

class FakeWorkletNode extends FakeAudioNode {
  public options: AudioWorkletNodeOptions | undefined;
  public onprocessorerror: ((event: Event) => void) | null = null;
  public readonly port = { onmessage: null, postMessage: vi.fn() } as unknown as MessagePort;

  public control(data: unknown): void { this.port.onmessage?.({ data } as MessageEvent); }

  public dispatch(sequence: number, samples: readonly number[]): void {
    this.port.onmessage?.({
      data: {
        type: "pcm",
        version: 1,
        sequence,
        frames: Float32Array.from(samples).buffer,
      },
    } as MessageEvent);
  }
}

class FakeAudioContext extends EventTarget {
  public readonly sampleRate = 32_000;
  public state: AudioContextState = "suspended";
  public readonly destination = new FakeAudioNode() as unknown as AudioDestinationNode;
  public readonly audioWorklet: AudioWorklet;
  readonly #mediaSource = new FakeAudioNode();
  readonly #gain = Object.assign(new FakeAudioNode(), { gain: { value: 1 } });

  public constructor(addModule: (url: string) => Promise<void>) {
    super();
    this.audioWorklet = { addModule };
  }

  public createMediaStreamSource(): MediaStreamAudioSourceNode {
    return this.#mediaSource as unknown as MediaStreamAudioSourceNode;
  }

  public createGain(): GainNode {
    return this.#gain as unknown as GainNode;
  }

  public async resume(): Promise<void> {
    this.state = "running";
    this.dispatchEvent(new Event("statechange"));
  }

  public async suspend(): Promise<void> {
    this.state = "suspended";
    this.dispatchEvent(new Event("statechange"));
  }

  public async close(): Promise<void> {
    this.state = "closed";
    this.dispatchEvent(new Event("statechange"));
  }

  public interrupt(): void {
    this.state = "suspended";
    this.dispatchEvent(new Event("statechange"));
  }
}

function readPcm16(wav: Uint8Array | undefined): readonly number[] {
  if (wav === undefined) return [];
  const view = new DataView(wav.buffer, wav.byteOffset, wav.byteLength);
  const samples: number[] = [];
  for (let offset = 44; offset < wav.byteLength; offset += 2) {
    samples.push(view.getInt16(offset, true));
  }
  return samples;
}

function deferred(): { readonly promise: Promise<void>; readonly resolve: () => void } {
  let resolvePromise: () => void = () => undefined;
  const promise = new Promise<void>((resolve) => {
    resolvePromise = resolve;
  });
  return { promise, resolve: resolvePromise };
}
