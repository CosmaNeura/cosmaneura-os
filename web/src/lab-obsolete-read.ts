/** Test-only proof that a cancelled workspace read has an exact, validated replacement. */
export type LabReadWire = {
  path: string;
  method: string;
  status: number | null;
  mount: number;
  scope: number;
  abort_ms?: number;
  abort?: { caller_aborted: boolean; episode_closed: boolean; retired_mount: boolean; refresh_scope: number | null };
};
export type LabValidatedRead = { workspace_id: string; mount: number; scope: number; revision: number; status: number; observed_ms: number };

export function expectedObsoleteWorkspaceRead(wire: LabReadWire, workspaceId: string, replacement?: LabValidatedRead): boolean {
  if (wire.method !== 'GET' || wire.path !== `/workspaces/${workspaceId}` ||
    wire.status !== null || wire.mount <= 0 || wire.abort?.caller_aborted !== true ||
    wire.abort.episode_closed !== false || !replacement || replacement.workspace_id !== workspaceId ||
    replacement.revision <= 0 || replacement.status !== 200 || !Number.isFinite(wire.abort_ms) ||
    !Number.isFinite(replacement.observed_ms) || replacement.observed_ms <= wire.abort_ms!) return false;
  if (wire.abort.retired_mount) return replacement.mount > wire.mount;
  return Number.isInteger(wire.abort.refresh_scope) && wire.abort.refresh_scope! > wire.scope &&
    replacement.mount === wire.mount && replacement.scope >= wire.abort.refresh_scope!;
}
