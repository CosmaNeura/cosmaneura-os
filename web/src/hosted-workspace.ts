import {resolveHostedWorkspace} from "../../clients/shared/hosted-workspace-config.mjs";

export function hostedWorkspaceConfiguration() {
  return resolveHostedWorkspace(import.meta.env);
}

export function hostedWorkspaceRequested() {
  return import.meta.env.VITE_WORKSPACE_HOSTED_ENABLED === "true";
}
