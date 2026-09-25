import type { CaptureDraft } from "./capture-notes-api";
import type { Workspace } from "./workspace-api";
import { captureGapKey } from "./capture-gap-review";
import { notebookSourceKey } from "./notebook-source";

// This is a display of an observed Core mismatch. Server authorization and
// exact current-source checks remain required for every review and action.
export function withObservedCaptureDraft(workspace: Workspace, draft: CaptureDraft | null): Workspace {
  const note = workspace.note?.latest, source = note?.core_source;
  if (!note || !source || !draft || source.session_id !== draft.session_id) return workspace;
  const changed = source.scribe_source_id !== draft.scribe_source_id || source.source_sha256 !== draft.source_sha256 ||
    captureGapKey(source.capture_gap_review) !== captureGapKey(draft.capture_gap_review) ||
    notebookSourceKey(source.notebook_source) !== notebookSourceKey(draft.notebook_source) ||
    JSON.stringify(source.reviewed_source) !== JSON.stringify(draft.reviewed_source) ||
    source.schema_ref === draft.schema_ref && (source.note_ref !== draft.note_ref || source.note_sha256 !== draft.note_sha256 || source.transcript_ref !== draft.transcript_ref);
  if (!changed) return workspace;
  return {...workspace, note:{...workspace.note!,latest:{...note,sources_changed:true},
    history:workspace.note!.history.map(item => item.id === note.id ? {...item,sources_changed:true} : item)},
    follow_ups:workspace.follow_ups?.map(item => item.core_check_required && item.note_version === note.version ? {...item,source_changed:true} : item)};
}
