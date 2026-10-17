import type {
  CapturedWavChunk,
  CaptureSource,
  CaptureSourceErrorCode,
  CaptureSourceInterruptionCode,
  CaptureSourceStartOptions,
  CaptureSourceExtension,
  Pcm16WavProfile,
} from "../capture";
import {
  encodePcm16MonoWav,
  pcm16WavProfile,
  targetFrameCount,
} from "../capture";
import { AudioCaptureError } from "./errors";
import { Pcm16Chunker } from "./pcm-chunker";
import { AreaWeightedPcm16Resampler } from "./resampler";
import { initialSourceWindow, extendSourceWindow, type CaptureSourceWindow } from "../capture/source-authority";
import {
  PCM_CAPTURE_WORKLET_NAME,
  PcmCaptureWorkletDecoder,
  type PcmCaptureProducerBounds,
  type PcmCaptureProducerExtension,
} from "./worklet-protocol";
import pcmCaptureWorkletModuleUrl from "./pcm-capture-worklet.ts?worker&url";

export interface BrowserMicrophoneDependencies {
  readonly mediaDevices: Pick<MediaDevices, "getUserMedia">;
  readonly createAudioContext: (options: AudioContextOptions) => AudioContext;
  readonly createAudioWorkletNode: (
    context: AudioContext,
    name: string,
    options: AudioWorkletNodeOptions,
  ) => AudioWorkletNode;
  readonly workletModuleUrl: URL;
  readonly visibilityDocument:
    | Pick<Document, "visibilityState" | "addEventListener" | "removeEventListener">
    | undefined;
  readonly pageLifecycleWindow:
    | Pick<Window, "addEventListener" | "removeEventListener">
    | undefined;
}

/** Foreground PWA microphone source: getUserMedia -> AudioWorklet -> PCM16 WAV. */
export class BrowserMicrophoneCaptureSource implements CaptureSource {
  public readonly kind = "microphone" as const;

  readonly #dependencies: BrowserMicrophoneDependencies;
  #state: "idle" | "starting" | "active" | "stopping" = "idle";
  #startPending = false;
  #stopRequested = false;
  #acceptMessages = false;
  #abortHandler: (() => void) | undefined;
  #abortSignal: AbortSignal | undefined;
  #audioContext: AudioContext | undefined;
  #chunker: Pcm16Chunker | undefined;
  #decoder: PcmCaptureWorkletDecoder | undefined;
  #mediaSource: MediaStreamAudioSourceNode | undefined;
  #onChunk: ((chunk: CapturedWavChunk) => Promise<void>) | undefined;
  #onInputLevel: CaptureSourceStartOptions["onInputLevel"];
  #lastLevelAt = 0;
  #onError: ((code: CaptureSourceErrorCode) => void) | undefined;
  #onInterruption: ((code: CaptureSourceInterruptionCode) => void) | undefined;
  #pendingChunkDelivery: Promise<void> = Promise.resolve();
  #profile: Pcm16WavProfile | undefined;
  #resampler: AreaWeightedPcm16Resampler | undefined;
  #sequenceNumber = 0;
  #shutdownPromise: Promise<void> | undefined;
  #silentGain: GainNode | undefined;
  #stream: MediaStream | undefined;
  #terminalError: AudioCaptureError | undefined;
  #workletNode: AudioWorkletNode | undefined;
  #runId = "";
  readonly #usedRunIds = new Set<string>();
  #sourceWindow: CaptureSourceWindow | undefined;
  #producerBounds: PcmCaptureProducerBounds | undefined;
  #onWindowClosed: CaptureSourceStartOptions["onWindowClosed"];
  #pendingChunkCount = 0;
  #extensionPending: { runId: string; bounds: PcmCaptureProducerExtension; promise: Promise<void>;
    resolve: () => void; reject: (error: Error) => void; timeout: ReturnType<typeof setTimeout> } | undefined;

  public constructor(dependencies: Partial<BrowserMicrophoneDependencies> = {}) {
    this.#dependencies = {
      mediaDevices: dependencies.mediaDevices ?? navigator.mediaDevices,
      createAudioContext:
        dependencies.createAudioContext ?? ((options) => new AudioContext(options)),
      createAudioWorkletNode:
        dependencies.createAudioWorkletNode ??
        ((context, name, options) => new AudioWorkletNode(context, name, options)),
      workletModuleUrl:
        dependencies.workletModuleUrl ??
        new URL(pcmCaptureWorkletModuleUrl, import.meta.url),
      visibilityDocument:
        dependencies.visibilityDocument ?? globalThis.document,
      pageLifecycleWindow:
        dependencies.pageLifecycleWindow ?? globalThis.window,
    };
  }

  public async start(options: CaptureSourceStartOptions): Promise<void> {
    if (this.#state !== "idle" || this.#startPending) {
      throw new AudioCaptureError("audio_capture_already_active");
    }
    if (isAborted(options.signal)) throw abortError();
    this.#resetForStart();
    this.#state = "starting";
    this.#startPending = true;
    this.#stopRequested = false;

    try {
      const profile = pcm16WavProfile(options.capabilities);
      const framesPerChunk = targetFrameCount(profile);
      const maximumChunks = capabilityChunkLimit(options.capabilities);
      this.#sourceWindow = options.authority ? initialSourceWindow(options.authority, maximumChunks, Date.now()) : undefined;
      this.#runId = this.#sourceWindow?.runId ?? globalThis.crypto.randomUUID();
      if (this.#usedRunIds.has(this.#runId)) throw new AudioCaptureError("audio_capture_stale_generation");
      this.#usedRunIds.add(this.#runId);
      this.#onWindowClosed = options.onWindowClosed;
      const maximumOutputFrames = safeProduct(framesPerChunk, maximumChunks);
      if (maximumOutputFrames < 1) {
        throw new AudioCaptureError("audio_capture_invalid_configuration");
      }
      if (
        this.#dependencies.visibilityDocument !== undefined &&
        this.#dependencies.visibilityDocument.visibilityState !== "visible"
      ) {
        throw new AudioCaptureError("audio_capture_unavailable");
      }

      try { options.onStartupStage?.("microphone_permission"); } catch { /* Progress observer isolation. */ }
      const stream = await this.#requestMicrophone(profile);
      // Permission may finish after Stop/sign-out has already completed cleanup.
      // Dispose that late stream before attaching it to this source's state.
      if (this.#stopRequested || isAborted(options.signal)) {
        for (const track of stream.getTracks()) track.stop();
        if (isAborted(options.signal)) throw abortError();
        throw new AudioCaptureError("audio_capture_unavailable");
      }
      this.#stream = stream;
      if (this.#sourceWindow && this.#sourceWindow.expiresAtMs <= Date.now()) throw new AudioCaptureError("audio_capture_unavailable");
      if (isAborted(options.signal)) throw abortError();
      if (
        this.#dependencies.visibilityDocument !== undefined &&
        this.#dependencies.visibilityDocument.visibilityState !== "visible"
      ) {
        throw new AudioCaptureError("audio_capture_unavailable");
      }
      const audioTracks = stream.getAudioTracks();
      if (audioTracks.length !== 1) {
        throw new AudioCaptureError("audio_capture_device_unavailable");
      }

      this.#onInputLevel = options.onInputLevel;
      this.#onError = options.onError;
      this.#onInterruption = options.onInterruption;
      audioTracks[0]?.addEventListener("ended", this.#handleTrackEnded, { once: true });
      audioTracks[0]?.addEventListener("mute", this.#handleTrackMuted, { once: true });
      this.#dependencies.visibilityDocument?.addEventListener(
        "visibilitychange",
        this.#handleVisibilityChange,
      );
      this.#dependencies.pageLifecycleWindow?.addEventListener(
        "pagehide",
        this.#handlePageHide,
      );
      if (options.signal !== undefined) {
        this.#abortSignal = options.signal;
        this.#abortHandler = () => {
          void this.#shutdown(false).catch(() => undefined);
        };
        options.signal.addEventListener("abort", this.#abortHandler, { once: true });
      }
      if (isAborted(options.signal)) throw abortError();
      if (
        this.#dependencies.visibilityDocument !== undefined &&
        this.#dependencies.visibilityDocument.visibilityState !== "visible"
      ) {
        throw new AudioCaptureError("audio_capture_unavailable");
      }

      try { options.onStartupStage?.("audio_engine"); } catch { /* Progress observer isolation. */ }
      const context = this.#dependencies.createAudioContext({
        latencyHint: "interactive",
        sampleRate: profile.sampleRateHz,
      });
      this.#audioContext = context;
      if (!Number.isSafeInteger(context.sampleRate) || context.sampleRate < 1) {
        throw new AudioCaptureError("audio_capture_unavailable");
      }
      const maximumInputFrames = rationalFloor(
        maximumOutputFrames,
        context.sampleRate,
        profile.sampleRateHz,
      );
      if (maximumInputFrames < 1) {
        throw new AudioCaptureError("audio_capture_invalid_configuration");
      }

      await context.audioWorklet.addModule(this.#dependencies.workletModuleUrl.toString());
      if (isAborted(options.signal)) throw abortError();
      if (this.#terminalError !== undefined) throw this.#terminalError;
      if (this.#state !== "starting") {
        throw new AudioCaptureError("audio_capture_unavailable");
      }
      if (
        this.#dependencies.visibilityDocument !== undefined &&
        this.#dependencies.visibilityDocument.visibilityState !== "visible"
      ) {
        throw new AudioCaptureError("audio_capture_unavailable");
      }

      this.#profile = profile;
      this.#onChunk = options.onChunk;
      this.#decoder = new PcmCaptureWorkletDecoder(framesPerChunk);
      this.#resampler = new AreaWeightedPcm16Resampler({
        sourceSampleRateHz: context.sampleRate,
        targetSampleRateHz: profile.sampleRateHz,
        maximumInputFrames,
        maximumOutputFrames,
      });
      this.#chunker = new Pcm16Chunker({
        targetFramesPerChunk: framesPerChunk,
        maximumChunks,
      });

      const mediaSource = context.createMediaStreamSource(stream);
      const legacySeconds = Math.min(900, options.capabilities.capture_lease_ttl_seconds, options.capabilities.reservation_window_seconds);
      if (!Number.isSafeInteger(legacySeconds) || legacySeconds < 1) throw new AudioCaptureError("audio_capture_invalid_configuration");
      this.#producerBounds = { runId: this.#runId, generation: this.#sourceWindow?.generation ?? 1,
        maximumInputFrames, hardMaximumInputFrames: rationalFloor(safeProduct(framesPerChunk, this.#sourceWindow?.hardMaximumChunks ?? maximumChunks),
          context.sampleRate, profile.sampleRateHz), expiresAtMs: this.#sourceWindow?.expiresAtMs ?? Date.now() + legacySeconds * 1000 };
      const workletNode = this.#dependencies.createAudioWorkletNode(
        context,
        PCM_CAPTURE_WORKLET_NAME,
        {
          channelCount: 1,
          channelCountMode: "explicit",
          channelInterpretation: "speakers",
          numberOfInputs: 1,
          numberOfOutputs: 1,
          outputChannelCount: [1],
          processorOptions: { captureBounds: this.#producerBounds },
        },
      );
      const silentGain = context.createGain();
      silentGain.gain.value = 0;
      this.#mediaSource = mediaSource;
      this.#workletNode = workletNode;
      this.#silentGain = silentGain;
      workletNode.port.onmessage = (event: MessageEvent<unknown>) => {
        this.#handleWorkletMessage(event.data);
      };
      workletNode.onprocessorerror = () => {
        this.#failWithError(
          new AudioCaptureError("audio_capture_worklet_protocol_error"),
          "capture_source_failed",
        );
      };
      context.addEventListener("statechange", this.#handleContextStateChange);
      mediaSource.connect(workletNode);
      workletNode.connect(silentGain);
      silentGain.connect(context.destination);

      this.#acceptMessages = true;
      this.#state = "active";
      await context.resume();
      if (isAborted(options.signal)) throw abortError();
      if (this.#stopRequested || this.#state !== "active" || context.state !== "running") {
        throw new AudioCaptureError("audio_capture_unavailable");
      }
    } catch (error) {
      const failure = sanitizeStartFailure(error);
      this.#terminalError = failure;
      await this.#shutdown(false).catch(() => undefined);
      if (isAbortError(error)) throw error;
      throw failure;
    } finally {
      this.#startPending = false;
    }
  }

  public async stop(): Promise<void> {
    this.#stopRequested = true;
    await this.#shutdown(this.#state === "active");
  }

  public async extend(extension: CaptureSourceExtension): Promise<void> {
    if (this.#state !== "active" || this.#stopRequested || !this.#sourceWindow || !this.#producerBounds || !this.#workletNode) {
      throw new AudioCaptureError("audio_capture_unavailable");
    }
    const previous = this.#sourceWindow, next = extendSourceWindow(previous, extension, Date.now());
    const profile = this.#requireProfile(), output = safeProduct(targetFrameCount(profile), next.maximumChunks);
    const input = rationalFloor(output, this.#audioContext!.sampleRate, profile.sampleRateHz);
    const bounds: PcmCaptureProducerExtension = { runId: next.runId, generation: next.generation, maximumInputFrames: input, expiresAtMs: next.expiresAtMs };
    if (this.#extensionPending) {
      if (!sameExtension(this.#extensionPending.bounds, bounds)) throw new AudioCaptureError("audio_capture_stale_generation");
      await this.#extensionPending.promise;
      if (this.#runId !== next.runId || this.#state !== "active" || this.#stopRequested ||
          this.#sourceWindow?.generation !== next.generation || Date.now() >= previous.expiresAtMs) {
        throw new AudioCaptureError("audio_capture_unavailable");
      }
      return;
    }
    if (next.generation === previous.generation) return;
    this.#requireResampler().extendLimits(input, output);
    this.#requireChunker().extendMaximumChunks(next.maximumChunks);
    let resolve!: () => void, reject!: (error: Error) => void;
    const promise = new Promise<void>((yes, no) => { resolve = yes; reject = no; });
    const pending = { runId: next.runId, bounds, promise, resolve, reject,
      timeout: setTimeout(() => reject(new AudioCaptureError("audio_capture_unavailable")), Math.min(1000, previous.expiresAtMs - Date.now())) };
    this.#extensionPending = pending;
    try {
      this.#workletNode.port.postMessage({ type: "extend", version: 1, runId: next.runId, bounds });
      await promise;
      if (this.#runId !== next.runId || this.#state !== "active" || this.#stopRequested || Date.now() >= previous.expiresAtMs) {
        throw new AudioCaptureError("audio_capture_unavailable");
      }
      this.#sourceWindow = next;
      this.#producerBounds = { ...this.#producerBounds, ...bounds };
    } catch {
      if (this.#runId === next.runId && this.#state === "active") {
        this.#failWithError(new AudioCaptureError("audio_capture_unavailable"), "capture_source_failed");
      }
      throw new AudioCaptureError("audio_capture_unavailable");
    } finally {
      clearTimeout(pending.timeout);
      if (this.#extensionPending === pending) this.#extensionPending = undefined;
    }
  }

  readonly #handleTrackEnded = (): void => {
    if (this.#state === "starting" || this.#state === "active") {
      this.#failWithInterruption(
        new AudioCaptureError("audio_capture_unavailable"),
        "audio_device_disconnected",
      );
    }
  };

  readonly #handleTrackMuted = (): void => {
    if (this.#state === "starting" || this.#state === "active") {
      this.#failWithInterruption(
        new AudioCaptureError("audio_capture_unavailable"),
        "audio_route_changed",
      );
    }
  };

  readonly #handleContextStateChange = (): void => {
    if (this.#state === "active" && this.#audioContext?.state !== "running") {
      const state = this.#audioContext?.state as string | undefined;
      if (state === "suspended" || state === "interrupted") {
        this.#failWithInterruption(
          new AudioCaptureError("audio_capture_unavailable"),
          "audio_context_suspended",
        );
      } else {
        this.#failWithError(
          new AudioCaptureError("audio_capture_unavailable"),
          "capture_source_failed",
        );
      }
    }
  };

  readonly #handleVisibilityChange = (): void => {
    if (
      (this.#state === "starting" || this.#state === "active") &&
      this.#dependencies.visibilityDocument?.visibilityState !== "visible"
    ) {
      this.#failWithInterruption(
        new AudioCaptureError("audio_capture_unavailable"),
        "capture_backgrounded",
      );
    }
  };

  readonly #handlePageHide = (): void => {
    if (this.#state === "starting" || this.#state === "active") {
      this.#failWithInterruption(
        new AudioCaptureError("audio_capture_unavailable"),
        "capture_backgrounded",
      );
    }
  };

  async #requestMicrophone(profile: Pcm16WavProfile): Promise<MediaStream> {
    try {
      return await this.#dependencies.mediaDevices.getUserMedia({
        audio: {
          autoGainControl: false,
          channelCount: { ideal: profile.channels },
          echoCancellation: false,
          noiseSuppression: false,
          sampleRate: { ideal: profile.sampleRateHz },
        },
        video: false,
      });
    } catch (error) {
      if (isNamedDomError(error, "NotAllowedError")) {
        throw new AudioCaptureError("audio_capture_permission_denied");
      }
      if (isNamedDomError(error, "NotFoundError")) {
        throw new AudioCaptureError("audio_capture_device_unavailable");
      }
      throw new AudioCaptureError("audio_capture_unavailable");
    }
  }

  #handleWorkletMessage(value: unknown): void {
    if (!this.#acceptMessages) { clearTransferredFrames(value); return; }
    try {
      if (isRecord(value) && value.type === "extended") {
        const pending = this.#extensionPending;
        if (value.runId !== this.#runId) return;
        if (value.version !== 1 || !pending || !sameExtension(value.bounds, pending.bounds)) throw new AudioCaptureError("audio_capture_worklet_protocol_error");
        pending.resolve(); return;
      }
      if (isRecord(value) && value.type === "window_closed") {
        if (value.runId !== this.#runId) return;
        if (value.version !== 1 || !["frame_limit", "authority_expired"].includes(value.reason as string)) {
          throw new AudioCaptureError("audio_capture_worklet_protocol_error");
        }
        const runId = this.#runId, callback = this.#onWindowClosed, failure = this.#onError;
        const reason = value.reason as "frame_limit" | "authority_expired";
        void this.#shutdown(true).then(() => {
          if (runId !== this.#runId || this.#stopRequested) return;
          if (callback) callback(reason); else failure?.("capture_source_stalled");
        }).catch(() => { if (runId === this.#runId) failure?.("capture_source_failed"); });
        return;
      }
      const frames = this.#requireDecoder().decode(value);
      if (Date.now() - this.#lastLevelAt >= 100) {
        this.#lastLevelAt = Date.now();
        let squared = 0;
        for (const sample of frames) squared += sample * sample;
        const level = frames.length ? Math.min(1, Math.sqrt(squared / frames.length) * 4) : 0;
        try { this.#onInputLevel?.(level); } catch { /* Observer isolation. */ }
      }
      let samples: Int16Array;
      try {
        samples = this.#requireResampler().push(frames);
      } finally {
        frames.fill(0);
      }
      try {
        this.#queueCompletedChunks(this.#requireChunker().push(samples));
      } finally {
        samples.fill(0);
      }
      this.#workletNode!.port.postMessage({ type: "pcm_consumed", version: 1, runId: this.#runId, sequence: (value as { sequence: number }).sequence });
    } catch (error) {
      clearTransferredFrames(value);
      const failure =
        error instanceof AudioCaptureError
          ? error
          : new AudioCaptureError("audio_capture_worklet_protocol_error");
      this.#failWithError(
        failure,
        failure.code === "audio_capture_worklet_protocol_error"
          ? "capture_source_stalled"
          : "capture_source_failed",
      );
    }
  }

  #queueCompletedChunks(chunks: readonly Int16Array<ArrayBuffer>[]): void {
    for (const samples of chunks) this.#queueChunk(samples);
  }

  #queueChunk(samples: Int16Array<ArrayBuffer>): void {
    if (this.#pendingChunkCount >= 2) {
      samples.fill(0);
      throw new AudioCaptureError("audio_capture_callback_failed");
    }
    const profile = this.#requireProfile();
    const onChunk = this.#requireOnChunk();
    let wavBytes: Uint8Array<ArrayBuffer>;
    try {
      wavBytes = encodePcm16MonoWav(samples, profile);
    } finally {
      samples.fill(0);
    }
    const chunk: CapturedWavChunk = {
      sequenceNumber: this.#sequenceNumber,
      durationMs: samples.length * 1_000 / profile.sampleRateHz,
      wavBytes,
    };
    this.#sequenceNumber += 1;
    this.#pendingChunkCount += 1;
    this.#pendingChunkDelivery = this.#pendingChunkDelivery.then(async () => {
      try {
        if (this.#terminalError !== undefined) return;
        await onChunk(chunk);
      } catch {
        this.#failWithError(
          new AudioCaptureError("audio_capture_callback_failed"),
          "capture_source_failed",
        );
      } finally {
        chunk.wavBytes.fill(0);
        this.#pendingChunkCount -= 1;
      }
    });
  }

  #failWithInterruption(
    error: AudioCaptureError,
    code: CaptureSourceInterruptionCode,
  ): void {
    this.#fail(error, () => this.#onInterruption?.(code));
  }

  #failWithError(error: AudioCaptureError, code: CaptureSourceErrorCode): void {
    this.#fail(error, () => this.#onError?.(code));
  }

  #fail(error: AudioCaptureError, notify: () => void): void {
    if (this.#terminalError !== undefined) return;
    this.#terminalError = error;
    try {
      notify();
    } catch {
      // The source is already terminal; notification code cannot reopen audio input.
    }
    void this.#shutdown(false).catch(() => undefined);
  }

  #shutdown(flush: boolean): Promise<void> {
    if (this.#shutdownPromise !== undefined) return this.#shutdownPromise;
    if (this.#state === "idle") return Promise.resolve();
    this.#shutdownPromise = this.#performShutdown(flush).finally(() => {
      this.#state = "idle";
      this.#shutdownPromise = undefined;
    });
    return this.#shutdownPromise;
  }

  async #performShutdown(flush: boolean): Promise<void> {
    this.#state = "stopping";
    const extension = this.#extensionPending;
    if (extension) {
      clearTimeout(extension.timeout);
      extension.reject(new AudioCaptureError("audio_capture_unavailable"));
      this.#extensionPending = undefined;
    }
    const context = this.#audioContext;
    // Stop physical input before awaiting browser audio cleanup. Suspension can
    // remain pending after device loss or while the app is being backgrounded.
    this.#acceptMessages = false;
    const audioTrack = this.#stream?.getAudioTracks()[0];
    audioTrack?.removeEventListener("ended", this.#handleTrackEnded);
    audioTrack?.removeEventListener("mute", this.#handleTrackMuted);
    for (const track of this.#stream?.getTracks() ?? []) track.stop();
    if (this.#workletNode !== undefined) {
      // The physical tracks are already stopped. A detached port must not skip
      // the rest of cleanup or leave an old callback alive for another Start.
      try { this.#workletNode.port.postMessage({ type: "stop", version: 1, runId: this.#runId }); } catch { /* continue cleanup */ }
      this.#workletNode.port.onmessage = null;
      this.#workletNode.onprocessorerror = null;
    }
    this.#mediaSource?.disconnect();
    this.#workletNode?.disconnect();
    this.#silentGain?.disconnect();
    context?.removeEventListener("statechange", this.#handleContextStateChange);
    this.#dependencies.visibilityDocument?.removeEventListener(
      "visibilitychange",
      this.#handleVisibilityChange,
    );
    this.#dependencies.pageLifecycleWindow?.removeEventListener(
      "pagehide",
      this.#handlePageHide,
    );
    if (context !== undefined && context.state !== "closed") {
      await context.close().catch(() => undefined);
    }

    let flushFailure: AudioCaptureError | undefined;
    try {
      if (flush && this.#terminalError === undefined) {
        const finalSamples = this.#requireResampler().finish();
        try {
          this.#queueCompletedChunks(this.#requireChunker().push(finalSamples));
        } finally {
          finalSamples.fill(0);
        }
        const finalChunk = this.#requireChunker().finish();
        if (finalChunk !== null) this.#queueChunk(finalChunk);
      } else {
        this.#chunker?.discard();
      }
    } catch (error) {
      flushFailure = error instanceof AudioCaptureError ? error : new AudioCaptureError("audio_capture_callback_failed");
      this.#terminalError = flushFailure;
      this.#chunker?.discard();
    }
    await this.#pendingChunkDelivery;
    this.#removeAbortHandler();
    this.#audioContext = undefined;
    this.#chunker = undefined;
    this.#decoder = undefined;
    this.#mediaSource = undefined;
    this.#onChunk = undefined;
    this.#onError = undefined;
    this.#onInterruption = undefined;
    this.#profile = undefined;
    this.#resampler = undefined;
    this.#silentGain = undefined;
    this.#stream = undefined;
    this.#workletNode = undefined;
    this.#sourceWindow = undefined;
    this.#producerBounds = undefined;
    this.#onWindowClosed = undefined;
    if (flushFailure) throw flushFailure;
  }

  #resetForStart(): void {
    this.#acceptMessages = false;
    this.#onInputLevel = undefined;this.#lastLevelAt = 0;
    this.#pendingChunkDelivery = Promise.resolve();
    this.#sequenceNumber = 0;
    this.#shutdownPromise = undefined;
    this.#terminalError = undefined;
    this.#pendingChunkCount = 0;
  }

  #removeAbortHandler(): void {
    if (this.#abortSignal !== undefined && this.#abortHandler !== undefined) {
      this.#abortSignal.removeEventListener("abort", this.#abortHandler);
    }
    this.#abortHandler = undefined;
    this.#abortSignal = undefined;
  }

  #requireChunker(): Pcm16Chunker {
    if (this.#chunker === undefined) {
      throw new AudioCaptureError("audio_capture_unavailable");
    }
    return this.#chunker;
  }

  #requireDecoder(): PcmCaptureWorkletDecoder {
    if (this.#decoder === undefined) {
      throw new AudioCaptureError("audio_capture_unavailable");
    }
    return this.#decoder;
  }

  #requireOnChunk(): (chunk: CapturedWavChunk) => Promise<void> {
    if (this.#onChunk === undefined) {
      throw new AudioCaptureError("audio_capture_unavailable");
    }
    return this.#onChunk;
  }

  #requireProfile(): Pcm16WavProfile {
    if (this.#profile === undefined) {
      throw new AudioCaptureError("audio_capture_unavailable");
    }
    return this.#profile;
  }

  #requireResampler(): AreaWeightedPcm16Resampler {
    if (this.#resampler === undefined) {
      throw new AudioCaptureError("audio_capture_unavailable");
    }
    return this.#resampler;
  }
}

function capabilityChunkLimit(
  capabilities: CaptureSourceStartOptions["capabilities"],
): number {
  if (
    !Number.isSafeInteger(capabilities.max_chunks) ||
    capabilities.max_chunks < 1 ||
    !Number.isSafeInteger(capabilities.remaining_aggregate_plaintext_bytes) ||
    capabilities.remaining_aggregate_plaintext_bytes < 0 ||
    !Number.isSafeInteger(capabilities.max_envelope_bytes) ||
    capabilities.max_envelope_bytes < 1
  ) {
    throw new AudioCaptureError("audio_capture_invalid_configuration");
  }
  return Math.min(
    capabilities.max_chunks,
    Math.floor(
      capabilities.remaining_aggregate_plaintext_bytes /
        capabilities.max_envelope_bytes,
    ),
  );
}

function safeProduct(left: number, right: number): number {
  const value = left * right;
  if (!Number.isSafeInteger(value)) {
    throw new AudioCaptureError("audio_capture_invalid_configuration");
  }
  return value;
}

function rationalFloor(value: number, numerator: number, denominator: number): number {
  return Number((BigInt(value) * BigInt(numerator)) / BigInt(denominator));
}

function sanitizeStartFailure(error: unknown): AudioCaptureError {
  if (error instanceof AudioCaptureError) return error;
  return new AudioCaptureError("audio_capture_unavailable");
}

function isNamedDomError(error: unknown, name: string): boolean {
  return typeof error === "object" && error !== null && "name" in error && error.name === name;
}

function isAbortError(error: unknown): boolean {
  return isNamedDomError(error, "AbortError");
}

function isAborted(signal: AbortSignal | undefined): boolean {
  return signal?.aborted === true;
}

function abortError(): DOMException {
  return new DOMException("capture start was cancelled", "AbortError");
}

function isRecord(value: unknown): value is Record<string, unknown> { return !!value && typeof value === "object" && !Array.isArray(value); }
function sameExtension(value: unknown, expected: PcmCaptureProducerExtension): boolean {
  return isRecord(value) && Object.keys(value).sort().join(",") === "expiresAtMs,generation,maximumInputFrames,runId" &&
    value.runId === expected.runId && value.generation === expected.generation && value.maximumInputFrames === expected.maximumInputFrames && value.expiresAtMs === expected.expiresAtMs;
}
function clearTransferredFrames(value: unknown): void {
  if (isRecord(value) && value.frames instanceof ArrayBuffer && value.frames.byteLength > 0) new Uint8Array(value.frames).fill(0);
}
