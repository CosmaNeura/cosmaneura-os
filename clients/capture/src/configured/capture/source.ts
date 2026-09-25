import type { CaptureCapabilities, ChunkReservationBatchRequest } from "../../bff/contracts";

export type CaptureAudioChannel = ChunkReservationBatchRequest["channel"];

export interface CapturedWavChunk {
  readonly sequenceNumber: number;
  readonly durationMs: number;
  readonly wavBytes: Uint8Array<ArrayBuffer>;
}

export interface CaptureSourceStartOptions {
  readonly capabilities: CaptureCapabilities;
  readonly onChunk: (chunk: CapturedWavChunk) => Promise<void>;
  readonly onInterruption?: (code: CaptureSourceInterruptionCode) => void;
  readonly onError?: (code: CaptureSourceErrorCode) => void;
  readonly signal?: AbortSignal;
}

/** Reservation metadata only. The native owner obtains and consumes its grant. */
export interface CaptureSourceExtension {
  readonly leaseReceiptId: string;
  readonly leaseGeneration: number;
  readonly captureAuthorizedUntil: string;
  readonly reservationBatchId: string;
  readonly firstSequenceNumber: number;
  readonly reservationCount: number;
  /** Cumulative chunks in this physical run, whose first packet is sequence zero. */
  readonly maximumChunks: number;
}

export type CaptureSourceInterruptionCode =
  | "audio_context_suspended"
  | "audio_device_disconnected"
  | "audio_route_changed"
  | "audio_session_interrupted"
  | "capture_backgrounded";

export type CaptureSourceErrorCode =
  | "capture_source_stalled"
  | "capture_source_failed";

/**
 * Narrow raw-audio boundary shared by the silent test source and real PWA/native adapters.
 * Implementations must derive runtime media settings and limits from `capabilities`.
 */
export interface CaptureSource {
  readonly kind: "synthetic" | "microphone";
  /** Fixed by the authorized source; omission preserves existing microphone capture. */
  readonly channel?: CaptureAudioChannel;
  start(options: CaptureSourceStartOptions): Promise<void>;
  supportsContinuousCapture?(): Promise<boolean>;
  extend?(value: CaptureSourceExtension): Promise<void>;
  stop(): Promise<void>;
}
