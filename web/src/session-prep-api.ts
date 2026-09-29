import {BffResponseError} from "../../clients/capture/src/bff/http-client";
import {request} from "./capture-api";
import type {AuthenticatedWorkspaceIdentity, CaptureBotSelection} from "./workspace-api";

export type CitedText = {text: string; source_refs: string[]};
export type PreparedBrief = {
  recap: CitedText; trajectory_and_material_changes: CitedText[]; talking_points: CitedText[];
  open_threads: CitedText[]; cautions: CitedText[]; suggested_outline: CitedText[];
  patient_reported: {label: "Patient-reported Visit Prep"; summary: string; source_refs: string[]} | null;
};
export type BriefSource = {
  source_id: string | null; source_class: "clinician_finalized_note" | "patient_reported_visit_prep";
  included: boolean; source_version: number | null; source_at: string | null;
  author_class: "clinician" | "patient" | null; reason_code: string;
};
export type SessionPrep = {
  state: "ready" | "refreshing" | "pending" | "unavailable";
  freshness: "current" | "stale" | "none"; completeness: "complete" | "partial" | "none";
  brief_id: string | null; brief_version: number | null; generated_at: string | null;
  current_through: string | null; prepared_brief: PreparedBrief | null; sources: BriefSource[];
  retry_after_seconds: number | null; reason_code: string | null;
};
const closed = (v: unknown, keys: string): v is Record<string, unknown> => !!v && typeof v === "object" &&
  !Array.isArray(v) && Object.keys(v).sort().join(",") === keys.split(",").sort().join(",");
const hash = (v: unknown): v is string => typeof v === "string" && /^[a-f0-9]{64}$/u.test(v);
const stamp = (v: unknown): v is string => typeof v === "string" && /(?:Z|[+-]\d\d:\d\d)$/u.test(v) && Number.isFinite(Date.parse(v));
const version = (v: unknown): v is number => Number.isSafeInteger(v) && Number(v) > 0 && Number(v) <= 2147483647;
const text = (v: unknown, maximum: number) => typeof v === "string" && !!v.trim() && [...v].length <= maximum && !v.includes("\0");
function invalid(): never {throw new BffResponseError(503, "session_prep_receipt_invalid", null);}

export function parseSessionPrep(response: unknown, workspace: string): SessionPrep {
  if (!closed(response, "contract_version,workspace_id,receipt") || response.contract_version !== 1 || response.workspace_id !== workspace ||
      !closed(response.receipt, "state,freshness,completeness,brief_id,brief_version,generated_at,current_through,prepared_brief,sources,retry_after_seconds,reason_code")) invalid();
  const v = response.receipt;
  if (!Array.isArray(v.sources) || v.sources.length > 8) invalid();
  if (v.state === "pending" || v.state === "unavailable") {
    if (v.freshness !== "none" || v.completeness !== "none" || v.sources.length ||
        [v.brief_id, v.brief_version, v.generated_at, v.current_through, v.prepared_brief].some(x => x !== null)) invalid();
    if (v.state === "pending" ? v.reason_code !== "generation_pending" || !Number.isInteger(v.retry_after_seconds) || Number(v.retry_after_seconds) < 1 || Number(v.retry_after_seconds) > 300 :
        !["no_eligible_sources", "context_not_available"].includes(String(v.reason_code)) || v.retry_after_seconds !== null) invalid();
    return v as SessionPrep;
  }
  if (!["ready", "refreshing"].includes(String(v.state)) || !["complete", "partial"].includes(String(v.completeness)) ||
      !hash(v.brief_id) || !version(v.brief_version) || !stamp(v.generated_at) || !stamp(v.current_through) ||
      Date.parse(v.current_through) > Date.parse(v.generated_at) || Date.parse(v.generated_at) > Date.now() + 5000) invalid();
  if (v.state === "ready" ? v.freshness !== "current" || v.reason_code !== null || v.retry_after_seconds !== null :
      v.freshness !== "stale" || v.reason_code !== "refresh_in_progress" || !Number.isInteger(v.retry_after_seconds) || Number(v.retry_after_seconds) < 1 || Number(v.retry_after_seconds) > 300) invalid();
  const included = new Map<string, string>();
  let partial = false;
  for (const source of v.sources) {
    if (!closed(source, "source_id,source_class,included,source_version,source_at,author_class,reason_code") ||
        !["clinician_finalized_note", "patient_reported_visit_prep"].includes(String(source.source_class)) || typeof source.included !== "boolean") invalid();
    if (source.included) {
      if (!hash(source.source_id) || included.has(source.source_id) || !version(source.source_version) || !stamp(source.source_at) || Date.parse(source.source_at) > Date.parse(v.current_through)) invalid();
      const clinical = source.source_class === "clinician_finalized_note";
      if (source.author_class !== (clinical ? "clinician" : "patient") || source.reason_code !== (clinical ? "eligible_finalized_note" : "eligible_patient_visit_prep")) invalid();
      included.set(source.source_id, String(source.source_class));
    } else {
      if (!([source.source_id, source.source_version, source.source_at, source.author_class].every(x => x === null)) ||
          !["no_eligible_source", "source_not_enabled", "selection_limit", "source_temporarily_unavailable"].includes(String(source.reason_code)) ||
          source.source_class === "clinician_finalized_note" && source.reason_code === "source_not_enabled") invalid();
      partial ||= ["selection_limit", "source_temporarily_unavailable"].includes(String(source.reason_code));
    }
  }
  if (!included.size || included.size > 6 || partial !== (v.completeness === "partial")) invalid();
  const refs = (r: unknown, patient = false) => Array.isArray(r) && r.length > 0 && r.length <= 6 && new Set(r).size === r.length && r.every(id =>
    typeof id === "string" && included.has(id) && (!patient || included.get(id) === "patient_reported_visit_prep"));
  const cited = (item: unknown, max = 1000) => closed(item, "text,source_refs") && text(item.text, max) && refs(item.source_refs);
  const b = v.prepared_brief;
  if (!closed(b, "recap,trajectory_and_material_changes,talking_points,open_threads,cautions,suggested_outline,patient_reported") || !cited(b.recap, 4000)) invalid();
  for (const key of ["trajectory_and_material_changes", "talking_points", "open_threads", "cautions", "suggested_outline"]) {
    const items = b[key];
    if (!Array.isArray(items) || items.length > 8 || (["talking_points", "suggested_outline"].includes(key) && !items.length) || !items.every(item => cited(item))) invalid();
  }
  if (b.patient_reported !== null && (!closed(b.patient_reported, "label,summary,source_refs") ||
      b.patient_reported.label !== "Patient-reported Visit Prep" || !text(b.patient_reported.summary, 2000) || !refs(b.patient_reported.source_refs, true))) invalid();
  return v as SessionPrep;
}

export async function readSessionPrep(workspace: string, identity: AuthenticatedWorkspaceIdentity, bot: CaptureBotSelection, signal: AbortSignal): Promise<SessionPrep> {
  return parseSessionPrep(await request(workspace, "prep", identity,
    {view: "brief", idempotency_key: crypto.randomUUID(), bot}, signal, 262144, 90000), workspace);
}
