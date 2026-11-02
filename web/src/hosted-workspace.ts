import {resolveHostedWorkspace} from "../../clients/shared/hosted-workspace-config.mjs";
import {registeredNativeWorkspaceConfiguration} from './workspace-base';

export function hostedWorkspaceConfiguration() {
  return registeredNativeWorkspaceConfiguration() ?? resolveHostedWorkspace(import.meta.env);
}

export function hostedWorkspaceRequested() {
  return import.meta.env.VITE_WORKSPACE_HOSTED_ENABLED === "true";
}
