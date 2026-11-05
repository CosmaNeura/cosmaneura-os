import {registeredNativeWorkspaceConfiguration} from './workspace-base';

type DataMode = string | undefined;
function registeredNativeDataMode(): DataMode {
  try { return registeredNativeWorkspaceConfiguration()?.dataMode; } catch { return undefined; }
}

/** Demo and synthetic-data labels stay visible unless this is a hosted build, or a registered
 * native practice, holding real practice data. Any unknown or failed lookup keeps the labels. */
export function showDemoLabels(env: Record<string, string | boolean | undefined> = import.meta.env,
                               nativeDataMode: () => DataMode = registeredNativeDataMode): boolean {
  if (nativeDataMode() === 'authorized_beta') return false;
  return !(env.VITE_WORKSPACE_HOSTED_ENABLED === 'true' && env.VITE_WORKSPACE_DATA_MODE === 'authorized_beta');
}
