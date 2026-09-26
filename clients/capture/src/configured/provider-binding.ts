import type { CaptureFlowSnapshot } from "./flow/controller";

/** Plain recorder state/commands shared by native hosts and the provider view.
 * Desktop implementations keep the flow, keys, audio and storage in main. */
export interface ProviderRecorderSnapshot extends CaptureFlowSnapshot {
  readonly desktop?: {
    readonly phase: "ready" | "permission_required" | "starting" | "recording" | "stopping"
      | "interrupted" | "stop_unconfirmed" | "stopped";
    readonly coverage: "not_started" | "aligned" | "complete" | "incomplete";
    readonly trimmedStartMs: number;
    readonly trimmedEndMs: number | null;
  };
}
export interface ProviderRecorderController {
  readonly snapshot: ProviderRecorderSnapshot;
  subscribe(listener: (snapshot: ProviderRecorderSnapshot) => void): () => void;
  startRecording(): Promise<void>;
  stopRecording(): Promise<void>;
  pauseRecording?(): Promise<void>;
  resumeRecording?(): Promise<void>;
  refreshTranscriptionStatus(): Promise<void>;
  refreshPermissions?(): Promise<void>;
}
/** Already authorized, restored/prepared and exclusively owned by a native host. */
export interface PreparedProviderRecorder {
  readonly controller: ProviderRecorderController;
  readonly sourceKind: "microphone";
  readonly captureMode: "desktop_meeting";
  deactivate(): Promise<void>;
  resumePendingWork(): Promise<void>;
  releaseUploadedCapture(): Promise<void>;
}

