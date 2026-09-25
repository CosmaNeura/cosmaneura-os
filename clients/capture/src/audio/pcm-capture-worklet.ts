import {
  PCM_CAPTURE_WORKLET_NAME,
  type PcmCaptureProducerBounds,
  type PcmCaptureProducerExtension,
  type PcmCaptureWindowCloseReason,
} from "./worklet-protocol";
import { encodeWorkletPacket } from "./worklet-packet";

declare abstract class AudioWorkletProcessor {
  constructor(options?: AudioWorkletNodeOptions);
  protected readonly port: MessagePort;
  public abstract process(
    inputs: Float32Array[][],
    outputs: Float32Array[][],
    parameters: Record<string, Float32Array>,
  ): boolean;
}

declare function registerProcessor(
  name: string,
  processorCtor: new (options?: AudioWorkletNodeOptions) => AudioWorkletProcessor,
): void;
declare const currentFrame: number;
declare const sampleRate: number;

export class PcmCaptureProcessor extends AudioWorkletProcessor {
  #sequence = 0;
  #bounds: PcmCaptureProducerBounds;
  #deadlineFrame: number;
  #inputFrames = 0;
  #pendingFrames = 0;
  #pending = new Map<number, number>();
  #closed = false;

  constructor(options?: AudioWorkletNodeOptions) {
    super(options);
    const bounds = options?.processorOptions?.captureBounds as PcmCaptureProducerBounds;
    if (!validBounds(bounds) || !Number.isSafeInteger(sampleRate) || sampleRate < 1 || !liveDeadline(bounds.expiresAtMs)) {
      throw new Error("capture_worklet_invalid_bounds");
    }
    this.#bounds = { ...bounds };
    this.#deadlineFrame = this.#renderDeadline(bounds.expiresAtMs);
    this.port.onmessage = event => this.#control(event.data);
  }

  public process(inputs: Float32Array[][]): boolean {
    if (this.#closed) return false;
    if (Date.now() >= this.#bounds.expiresAtMs || currentFrame >= this.#deadlineFrame) return this.#close("authority_expired");
    const channels = inputs[0];
    const length = channels?.[0]?.length;
    if (!length || length > sampleRate || channels.some(channel => channel.length !== length)) return this.#close("protocol");
    const frames = Math.min(length, this.#bounds.maximumInputFrames - this.#inputFrames, this.#deadlineFrame - currentFrame);
    if (frames < 1) return this.#close("frame_limit");
    // At most one second of transferred PCM may wait for its renderer consumer.
    if (this.#pendingFrames + frames > sampleRate) return this.#close("backpressure");
    let packet: ReturnType<typeof encodeWorkletPacket>;
    try { packet = encodeWorkletPacket(channels.map(channel => channel.subarray(0, frames)), this.#sequence); }
    catch { return this.#close("protocol"); }
    if (packet.message.type !== "pcm") return this.#close("protocol");
    this.#pending.set(this.#sequence, frames);
    this.#pendingFrames += frames;
    this.#inputFrames += frames;
    this.#sequence += 1;
    this.port.postMessage(packet.message, packet.transfer);
    if (this.#inputFrames === this.#bounds.maximumInputFrames) return this.#close("frame_limit");
    if (frames < length) return this.#close("authority_expired");
    return true;
  }

  #control(value: unknown): void {
    if (this.#closed) return;
    if (!record(value) || value.version !== 1 || value.runId !== this.#bounds.runId) { this.#close("protocol"); return; }
    if (value.type === "stop") { this.#closed = true; this.#pending.clear(); return; }
    if (value.type === "pcm_consumed") {
      if (!Number.isSafeInteger(value.sequence) || !this.#pending.has(value.sequence as number) ||
          value.sequence !== this.#pending.keys().next().value) { this.#close("protocol"); return; }
      this.#pendingFrames -= this.#pending.get(value.sequence as number)!;
      this.#pending.delete(value.sequence as number); return;
    }
    if (value.type !== "extend" || !record(value.bounds)) { this.#close("protocol"); return; }
    const extension = value.bounds as unknown as PcmCaptureProducerExtension;
    const next = { ...extension, hardMaximumInputFrames: this.#bounds.hardMaximumInputFrames };
    if (Object.keys(extension).sort().join(",") !== "expiresAtMs,generation,maximumInputFrames,runId" ||
        !validBounds(next) || next.runId !== this.#bounds.runId || !liveDeadline(next.expiresAtMs) ||
        Date.now() >= this.#bounds.expiresAtMs || currentFrame >= this.#deadlineFrame ||
        this.#inputFrames >= this.#bounds.maximumInputFrames || next.maximumInputFrames < this.#bounds.maximumInputFrames) {
      this.#close("protocol"); return;
    }
    if (next.generation === this.#bounds.generation) {
      if (next.maximumInputFrames !== this.#bounds.maximumInputFrames || next.expiresAtMs !== this.#bounds.expiresAtMs) { this.#close("protocol"); return; }
    } else {
      if (next.generation !== this.#bounds.generation + 1 || next.expiresAtMs <= this.#bounds.expiresAtMs) { this.#close("protocol"); return; }
      this.#bounds = next;
      this.#deadlineFrame = this.#renderDeadline(next.expiresAtMs);
    }
    this.port.postMessage({ type: "extended", version: 1, runId: next.runId, bounds: { ...extension } });
  }

  #renderDeadline(expiresAtMs: number): number {
    return currentFrame + Math.floor((expiresAtMs - Date.now()) * sampleRate / 1000);
  }

  #close(reason: PcmCaptureWindowCloseReason): false {
    if (!this.#closed) {
      this.#closed = true;
      this.#pending.clear();
      this.port.postMessage({ type: "window_closed", version: 1, runId: this.#bounds.runId, reason });
    }
    return false;
  }
}

function record(value: unknown): value is Record<string, unknown> { return !!value && typeof value === "object" && !Array.isArray(value); }
function positive(value: unknown): value is number { return Number.isSafeInteger(value) && (value as number) > 0; }
function liveDeadline(value: number): boolean { return positive(value) && value > Date.now() && value - Date.now() <= 905_000; }
function validBounds(value: unknown): value is PcmCaptureProducerBounds {
  return record(value) && Object.keys(value).sort().join(",") === "expiresAtMs,generation,hardMaximumInputFrames,maximumInputFrames,runId" &&
    typeof value.runId === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u.test(value.runId) && positive(value.generation) &&
    positive(value.maximumInputFrames) && positive(value.hardMaximumInputFrames) && value.maximumInputFrames <= value.hardMaximumInputFrames && positive(value.expiresAtMs);
}

registerProcessor(PCM_CAPTURE_WORKLET_NAME, PcmCaptureProcessor);
