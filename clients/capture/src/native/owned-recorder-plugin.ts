import { registerPlugin } from "@capacitor/core";
import type { NativeRecordingCommand } from "./owned-recorder";
import type { MicrophoneInput } from "./microphone-input";

interface NativeRecordingPlugin {
  openProviderRecording(request: { requestId: string; revision: string; workspaceId: string; sessionId: string }): Promise<unknown>;
  providerRecordingCommand(request: { requestId: string; revision: string; recorderId: string;
    kind: NativeRecordingCommand; input?: MicrophoneInput }): Promise<unknown>;
}
export const nativeRecordingPlugin = registerPlugin<NativeRecordingPlugin>("CosmasWorkspaceAuth");
