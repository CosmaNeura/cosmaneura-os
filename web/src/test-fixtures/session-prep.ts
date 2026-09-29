import type {SessionPrep} from "../session-prep-api";
export function sessionPrepFixture(state: SessionPrep["state"] = "ready"): SessionPrep {
  const source = "a".repeat(64), date = "2026-09-24T13:00:00Z";
  if (state === "pending" || state === "unavailable") return {state, freshness: "none", completeness: "none", brief_id: null,
    brief_version: null, generated_at: null, current_through: null, prepared_brief: null, sources: [],
    retry_after_seconds: state === "pending" ? 5 : null, reason_code: state === "pending" ? "generation_pending" : "no_eligible_sources"};
  const item = {text: "Invented reviewed visit summary.", source_refs: [source]};
  return {state, freshness: state === "ready" ? "current" : "stale", completeness: "complete", brief_id: "b".repeat(64),
    brief_version: 1, generated_at: date, current_through: date, prepared_brief: {recap: {...item},
      talking_points: [{...item, text: "Discuss the saved concern."}], suggested_outline: [{...item, text: "Review the prior visit."}],
      trajectory_and_material_changes: [], open_threads: [], cautions: [], patient_reported: null},
    sources: [{source_id: source, source_class: "clinician_finalized_note", included: true, source_version: 1, source_at: date,
      author_class: "clinician", reason_code: "eligible_finalized_note"}],
    retry_after_seconds: state === "ready" ? null : 5, reason_code: state === "ready" ? null : "refresh_in_progress"};
}
