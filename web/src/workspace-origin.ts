import {permittedHostedWorkspace} from "../../clients/shared/hosted-workspace-config.mjs";
import {hostedWorkspaceConfiguration, hostedWorkspaceRequested} from "./hosted-workspace";

export function permittedWorkspaceApi(base: string, desktopBuild: boolean, page: string): boolean {
  if (hostedWorkspaceRequested()) return permittedHostedWorkspace(hostedWorkspaceConfiguration(), base, page);
  try {
    const api = new URL(base);
    const location = new URL(page);
    if (desktopBuild && base === "app://cosmas/api" && location.protocol === "app:" &&
        location.hostname === "cosmas" && !location.port && !location.username && !location.password) return true;
    return api.protocol === "http:" && ["127.0.0.1", "localhost", "[::1]"].includes(api.hostname) &&
      !api.username && !api.password && !api.search && !api.hash && api.pathname === "/";
  } catch { return false; }
}

/** Direct local transport only. The synthetic Electron proxy never carries tokens. */
export function permittedSignedWorkspaceApi(base: string, page: string, appleLocalTransport = false): boolean {
  if (hostedWorkspaceRequested()) return permittedHostedWorkspace(hostedWorkspaceConfiguration(), base, page, true);
  if (!permittedWorkspaceApi(base, false, page)) return false;
  try {
    const location = new URL(page);
    if (location.username || location.password) return false;
    if (permittedWorkspaceApi(location.origin, false, page)) return true;
    return appleLocalTransport && location.protocol === "capacitor:" && location.hostname === "localhost" &&
      !location.port && !location.username && !location.password;
  } catch { return false; }
}

export function permittedDesktopWorkspaceApi(base: string, page: string): boolean {
  return base === "app://cosmas/api" && page === "app://cosmas/index.html";
}
