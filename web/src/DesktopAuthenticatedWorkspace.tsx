import { useMemo } from "react";
import { NativeAuthenticatedWorkspace } from "./NativeAuthenticatedWorkspace";
import type { WorkspaceAuthPlugin } from "../../clients/capture/src/native/workspace-auth-plugin";
import type { NativeAuthState } from "./native-auth";
import type { AuthenticatedWorkspaceIdentity } from "./workspace-api";

type DesktopAuthPort = {
  version: 1; getState(): Promise<unknown>; signIn(): Promise<unknown>; signOut(): Promise<unknown>;
  onStateChanged(listener: (state: unknown) => void): () => void;
};

declare global { interface Window { cosmasDesktopAuth?: DesktopAuthPort } }

const requestIdentity = (state: NativeAuthState, isCurrent: () => boolean): AuthenticatedWorkspaceIdentity =>
  ({ mode: "desktop_native", revision: state.revision, isCurrent });

export function DesktopAuthenticatedWorkspace() {
  const supplied = window.cosmasDesktopAuth;
  const port = supplied?.version === 1 &&
    Object.keys(supplied).sort().join(",") === "getState,onStateChanged,signIn,signOut,version" &&
    [supplied.getState, supplied.signIn, supplied.signOut, supplied.onStateChanged].every(value => typeof value === "function")
    ? supplied : undefined;
  const plugin = useMemo<WorkspaceAuthPlugin | undefined>(() => port ? {
    getState: () => port.getState(), signIn: () => port.signIn(), signOut: () => port.signOut(),
    getToken: async () => { throw new Error("Credentials stay in the native process"); },
    addListener: async (_event, listener) => {
      const remove = port.onStateChanged(listener); return { remove: async () => { remove(); } };
    },
  } : undefined, [port]);
  return <NativeAuthenticatedWorkspace plugin={plugin} available={!!plugin} createIdentity={requestIdentity} />;
}
