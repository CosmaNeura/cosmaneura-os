export type NotebookSource = { kind: "clinician_scratch_notes"; workspace_id: string; entry_id: string; revision: number; content_sha256: string };
export type SavedScratchpad = { id: string; revision: number };

export const notebookSourceKey = (source?: NotebookSource) => source ?
  [source.kind, source.workspace_id, source.entry_id, source.revision, source.content_sha256].join(":") : "";

export function validNotebookSource(value: unknown, workspace: string): value is NotebookSource {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const item = value as Record<string, unknown>;
  return Object.keys(item).sort().join(",") === "content_sha256,entry_id,kind,revision,workspace_id" &&
    item.kind === "clinician_scratch_notes" && item.workspace_id === workspace &&
    typeof item.entry_id === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u.test(item.entry_id) &&
    Number.isInteger(item.revision) && Number(item.revision) >= 1 && Number(item.revision) <= 500 &&
    typeof item.content_sha256 === "string" && /^[a-f0-9]{64}$/u.test(item.content_sha256);
}
