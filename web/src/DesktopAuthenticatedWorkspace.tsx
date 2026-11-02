import { useMemo } from "react";
import { NativeAuthenticatedWorkspace } from "./NativeAuthenticatedWorkspace";
import type { WorkspaceAuthPlugin } from "../../clients/capture/src/native/workspace-auth-plugin";
import {desktopPracticeConnectionPort} from "../../clients/capture/src/native/practice-connection-plugin";
import type { NativeAuthState } from "./native-auth";
import type { AuthenticatedWorkspaceIdentity } from "./workspace-api";

type DesktopAuthPort = {
  version: 1; getState(): Promise<unknown>; signIn(): Promise<unknown>; signOut(): Promise<unknown>;
  clearAccountCredentials?: () => Promise<unknown>;
  onStateChanged(listener: (state: unknown) => void): () => void;
};

declare global { interface Window { cosmasDesktopAuth?: DesktopAuthPort } }

const requestIdentity = (state: NativeAuthState, isCurrent: () => boolean): AuthenticatedWorkspaceIdentity =>
  ({ mode: "desktop_native", revision: state.revision, isCurrent });

function desktopPort(supplied: DesktopAuthPort | undefined): DesktopAuthPort | undefined {
  if (supplied?.version !== 1) return undefined;
  const keys = Object.keys(supplied).sort().join(",");
  const base = keys === "getState,onStateChanged,signIn,signOut,version";
  const withClear = keys === "clearAccountCredentials,getState,onStateChanged,signIn,signOut,version";
  if (!base && !withClear) return undefined;
  if (![supplied.getState, supplied.signIn, supplied.signOut, supplied.onStateChanged].every(value => typeof value === "function")) {
    return undefined;
  }
  if (withClear && typeof supplied.clearAccountCredentials !== "function") return undefined;
  return supplied;
}

export function DesktopAuthenticatedWorkspace() {
  const port = desktopPort(window.cosmasDesktopAuth);
  const plugin = useMemo<WorkspaceAuthPlugin | undefined>(() => port ? {
    getState: () => port.getState(), signIn: () => port.signIn(), signOut: () => port.signOut(),
    clearAccountCredentials: port.clearAccountCredentials
      ? () => port.clearAccountCredentials!()
      : undefined,
    getToken: async () => { throw new Error("Credentials stay in the native process"); },
    addListener: async (_event, listener) => {
      const remove = port.onStateChanged(listener); return { remove: async () => { remove(); } };
    },
  } : undefined, [port]);
  // Contract Mac host: Origin app://cosmas via CosmasDesktopPractice when the signed helper exposes it.
  // Until that helper ships, capabilities stay dark and Connect practice is not offered.
  const practicePlugin = useMemo(() => desktopPracticeConnectionPort() ?? undefined, []);
  return <NativeAuthenticatedWorkspace plugin={plugin} available={!!plugin} createIdentity={requestIdentity}
    practicePlugin={practicePlugin} practiceConnectionAvailable={!!practicePlugin} />;
}
