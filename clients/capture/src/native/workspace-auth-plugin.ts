import { Capacitor, registerPlugin, type PluginListenerHandle } from "@capacitor/core";
import { coalesceNativeWorkspaceAuth } from "./workspace-auth-requests";

export interface WorkspaceAuthPlugin {
  getState(): Promise<unknown>;
  signIn(): Promise<unknown>;
  signOut(): Promise<unknown>;
  getToken(options: { expectedRevision: string }): Promise<unknown>;
  addListener(event: "authStateChanged", listener: (state: unknown) => void): Promise<PluginListenerHandle>;
}

export const WorkspaceAuth = coalesceNativeWorkspaceAuth(registerPlugin<WorkspaceAuthPlugin>("CosmasWorkspaceAuth"));
export const nativeWorkspaceAuthAvailable = () => Capacitor.getPlatform() === "ios" &&
  Capacitor.isPluginAvailable("CosmasWorkspaceAuth");
