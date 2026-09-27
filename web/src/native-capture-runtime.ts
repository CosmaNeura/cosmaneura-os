import { connectNativeProviderRecorder } from "../../clients/capture/src/native/owned-recorder";
import type { NativeRecordingPort } from "../../clients/capture/src/native/owned-recorder";
import { NativePluginQueueStorage } from "../../clients/capture/src/storage/native-plugin";
import type { CiphertextUploadTarget } from "../../clients/capture/src/bff/contracts";
import { BffResponseError } from "../../clients/capture/src/bff/http-client";
import { scopedNativeRecordingPlugin } from "./capture-storage";
import { workspaceCaptureBff } from "./capture-api";
import { creatorReviewApi } from "./creator-review-api";
import type { AuthenticatedWorkspaceIdentity } from "./workspace-api";
import type { CaptureRuntime } from "./capture-runtime";

/** A renderer handle to the native owner, never a second microphone or key owner. */
export async function openNativeCaptureRuntime(options: {
  workspaceId: string; sessionId: string; identity: AuthenticatedWorkspaceIdentity;
  upload: CiphertextUploadTarget; abort: AbortController; release: () => Promise<void>;
}): Promise<CaptureRuntime> {
  const { workspaceId, sessionId, identity, abort } = options;
  if (identity.mode !== "clerk_jwt" || !identity.nativeSession?.isCurrent()) throw unavailable();
  const native = identity.nativeSession;
  const current = () => { if (abort.signal.aborted || !native.isCurrent()) throw unavailable(); };
  current();
  const view = await creatorReviewApi(workspaceId, sessionId, identity, abort.signal).read();
  current();
  let closed = false;
  const release = async () => {
    if (closed) return;
    abort.abort(); await options.release(); closed = true;
  };
  // The recorder closes before it submits completion. Reopening an already
  // uploaded visit needs only the existing transcript/translation/note review.
  if (!["created", "capturing"].includes(view.status)) {
    const snapshot = { state: "processing" as const, statusCode: "capture_processing", sessionId,
      recordedChunks: 0, queuedChunks: 0, elapsedSeconds: 0, remainingAuthoritySeconds: null,
      remainingBudgetSeconds: null, transcriptionStatus: null, transcript: null };
    const forbidden = async () => { throw unavailable(); };
    return { sourceKind: "microphone", close: release, releaseUploadedCapture: async () => { current(); },
      controller: { snapshot, subscribe: listener => { listener(snapshot); return () => {}; },
        startRecording: forbidden, stopRecording: forbidden, acknowledgeGap: forbidden,
        finishInterruptedCapture: forbidden, resumePendingWork: async () => {}, refreshTranscriptionStatus: async () => {} } };
  }
  const [{ nativeRecordingPlugin: plugin }, { SecureQueue }] = await Promise.all([
    import("../../clients/capture/src/native/owned-recorder-plugin"),
    import("../../clients/capture/plugins/secure-queue"),
  ]);
  current();
  const port: NativeRecordingPort = {
    open: async (selectedSession, requestId) => {
      current(); if (selectedSession !== sessionId) throw unavailable();
      const result = await plugin.openProviderRecording({ requestId, revision: native.revision, workspaceId, sessionId });
      current(); return result;
    },
    command: async request => {
      if (request.kind !== "close") current();
      const result = await plugin.providerRecordingCommand({ ...request, revision: native.revision });
      if (request.kind !== "close") current();
      return result;
    },
  };
  const recorder = await connectNativeProviderRecorder({ workspaceId, sessionId, port,
    bff: workspaceCaptureBff(workspaceId, sessionId, identity, abort.signal), uploadTarget: options.upload,
    signal: abort.signal, openQueue: async recoveryScope => {
      current();
      return new NativePluginQueueStorage(scopedNativeRecordingPlugin(SecureQueue, recoveryScope, workspaceId, sessionId), sessionId);
    } });
  current();
  return { sourceKind: "microphone", captureMode: "native_microphone", supportsContinuation: true,
    // Remounting reconnects to the same native host. Unmounting must not stop it.
    close: async () => { recorder.detach(); await release(); },
    releaseUploadedCapture: () => recorder.releaseUploadedCapture(),
    controller: {
      get snapshot() { return recorder.controller.snapshot; },
      subscribe: listener => recorder.controller.subscribe(listener),
      startRecording: () => recorder.controller.startRecording(),
      stopRecording: () => recorder.controller.stopRecording(),
      pauseRecording: () => recorder.controller.pauseRecording(),
      acknowledgeGap: () => recorder.controller.prepareContinuation(),
      finishInterruptedCapture: () => recorder.controller.stopRecording(),
      resumePendingWork: () => recorder.resumePendingWork(),
      refreshTranscriptionStatus: () => recorder.controller.refreshTranscriptionStatus(),
      selectMicrophoneInput: input => recorder.controller.selectMicrophoneInput(input),
    } };
}
function unavailable() { return new BffResponseError(409, "capture_source_unavailable", null); }
