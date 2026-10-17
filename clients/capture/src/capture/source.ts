import type { CaptureCapabilities } from "../bff/contracts";

export interface CapturedWavChunk {
  readonly sequenceNumber: number;
  readonly durationMs: number;
  readonly wavBytes: Uint8Array<ArrayBuffer>;
}

export type CaptureSourceStartupStage =
  | "native_session"
  | "physical_exclusion"
  | "microphone_permission"
  | "audio_engine";

export interface CaptureSourceStartOptions {
  /** Optional renewable authority, granted only after durable server receipts. */
  readonly authority?: CaptureSourceAuthority;
  readonly capabilities: CaptureCapabilities;
  readonly onChunk: (chunk: CapturedWavChunk) => Promise<void>;
  readonly onInterruption?: (code: CaptureSourceInterruptionCode) => void;
  readonly onError?: (code: CaptureSourceErrorCode) => void;
  /** Transient progress only; observers cannot grant authority or affect capture. */
  readonly onStartupStage?: (stage: CaptureSourceStartupStage) => void;
  /** Transient measured amplitude. No samples or device identity leave the source. */
  readonly onInputLevel?: (level: number) => void;
  readonly signal?: AbortSignal;
  /** Called after accepted audio is drained and the producer has stopped. */
  readonly onWindowClosed?: (reason: "authority_expired" | "frame_limit") => void;
}

export interface CaptureSourceAuthority {
  readonly runId: string;
  readonly generation: number;
  readonly expiresAtMs: number;
  /** Immutable cumulative chunk budget for this explicit Start. */
  readonly hardMaximumChunks: number;
}

export interface CaptureSourceExtension {
  readonly runId: string;
  readonly generation: number;
  readonly expiresAtMs: number;
  /** Cumulative chunk limit from this Start; never a per-extension allowance. */
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
  start(options: CaptureSourceStartOptions): Promise<void>;
  stop(): Promise<void>;
  /** Resolves only after the same active producer confirms the exact extension. */
  extend?(extension: CaptureSourceExtension): Promise<void>;
  /** Read-only proof from the process-wide producer owner after a lost JS run.
   * True means no pending, active or unsuccessfully closed producer remains.
   * A fresh JS adapter or a successful no-op stop alone cannot establish this.
   */
  confirmRecoveryClosed?(): Promise<boolean>;
}
