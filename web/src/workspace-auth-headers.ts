import type { AuthenticatedWorkspaceIdentity } from "./workspace-api";
import { permittedDesktopWorkspaceApi, permittedSignedWorkspaceApi } from "./workspace-origin";
import {hostedWorkspaceConfiguration, hostedWorkspaceRequested} from "./hosted-workspace";

export function assertCurrentDesktopSession(identity: AuthenticatedWorkspaceIdentity): void {
  if (identity.mode === "desktop_native" && !identity.isCurrent()) throw new Error("Secure session unavailable");
}

export async function workspaceAuthHeaders(identity: AuthenticatedWorkspaceIdentity, base: string): Promise<Headers> {
  const headers = new Headers({ "Content-Type": "application/json", "X-Cosmas-Draft-Recovery": "2" });
  if (hostedWorkspaceRequested()) headers.set("X-Cosmas-Workspace-Protocol", "1");
  if (identity.mode === "desktop_native") {
    const hostedDesktop = hostedWorkspaceConfiguration()?.client === "desktop";
    if (import.meta.env.VITE_WORKSPACE_DESKTOP_AUTH_ENABLED !== "true" ||
        (hostedWorkspaceRequested() ? !hostedDesktop :
          import.meta.env.VITE_DESKTOP_SYNTHETIC_ENABLED !== "true" || import.meta.env.VITE_COSMAS_ENV !== "synth_os") ||
        import.meta.env.VITE_WORKSPACE_AUTHENTICATED_ENABLED !== "true" ||
        import.meta.env.VITE_WORKSPACE_ENABLED !== "true" ||
        !permittedDesktopWorkspaceApi(base, window.location.href) ||
        !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(identity.revision)) {
      throw new Error("Secure session unavailable");
    }
    assertCurrentDesktopSession(identity);
    headers.set("X-Cosmas-Desktop-Session", identity.revision);
  } else {
    if (!permittedSignedWorkspaceApi(base, window.location.href,
      import.meta.env.VITE_WORKSPACE_APPLE_LOCAL_TRANSPORT_ENABLED === "true")) throw new Error("Secure session unavailable");
    const token = await identity.getToken({ skipCache: true });
    if (!token || token.length > 8192 || /\s/.test(token)) throw new Error("Secure session unavailable");
    headers.set("Authorization", `Bearer ${token}`);
  }
  return headers;
}
