/** Demo and synthetic-data labels stay visible unless this is a hosted build for real practice data. */
export function showDemoLabels(env: Record<string, string | boolean | undefined> = import.meta.env): boolean {
  return !(env.VITE_WORKSPACE_HOSTED_ENABLED === 'true' && env.VITE_WORKSPACE_DATA_MODE === 'authorized_beta');
}
