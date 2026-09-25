import { BffResponseError } from "../../clients/capture/src/bff/http-client";
import { CAPTURE_WORKSPACE_BUILD, request } from "./capture-api";
import type { AuthenticatedWorkspaceIdentity, CaptureBotSelection } from "./workspace-api";

export const ENCOUNTER_PREP_BUILD = CAPTURE_WORKSPACE_BUILD && import.meta.env.VITE_WORKSPACE_PREP_ENABLED === "true";
export type PrepSource = { source_id: string; appointment_ref: string; kind: "generated_visit_note" | "patient_intake_summary";
  label: string; source_at: string; content_sha256: string; content: string; truncated: boolean; content_redacted: boolean };
export type EncounterPrep = { appointment_ref: string; sources: PrepSource[]; additional_notes_available: boolean; snapshot_sha256: string; display_sha256: string };
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const closed = (value: unknown, keys: string): value is Record<string, unknown> => object(value) && Object.keys(value).sort().join(",") === keys.split(",").sort().join(",");
const digest = (value: unknown) => typeof value === "string" && /^[a-f0-9]{64}$/u.test(value);
function invalid(): never { throw new BffResponseError(503, "capture_receipt_invalid", null); }
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (object(value)) return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(",")}}`;
  return JSON.stringify(value);
}

export async function readEncounterPrep(workspace: string, identity: AuthenticatedWorkspaceIdentity,
  bot: CaptureBotSelection, signal?: AbortSignal): Promise<EncounterPrep> {
  const response = await request(workspace, "prep", identity, {idempotency_key: crypto.randomUUID(), bot}, signal, 262144);
  if (!closed(response, "workspace_id,receipt") || response.workspace_id !== workspace ||
      !closed(response.receipt, "appointment_ref,sources,additional_notes_available,snapshot_sha256,display_sha256")) invalid();
  const value = response.receipt;
  if (!digest(value.appointment_ref) || !Array.isArray(value.sources) || value.sources.length > 6 ||
      typeof value.additional_notes_available !== "boolean" || !digest(value.snapshot_sha256) || !digest(value.display_sha256)) invalid();
  const seen = new Set();
  for (const source of value.sources) {
    if (!closed(source, "source_id,appointment_ref,kind,label,source_at,content_sha256,content,truncated,content_redacted") ||
        !["generated_visit_note", "patient_intake_summary"].includes(String(source.kind)) ||
        !digest(source.source_id) ||
        !digest(source.appointment_ref) || !digest(source.content_sha256) ||
        typeof source.label !== "string" || !source.label || source.label.length > 200 ||
        typeof source.content !== "string" || [...source.content].length > 8000 || source.content.includes("\0") ||
        typeof source.source_at !== "string" || !/(?:Z|[+-]\d\d:\d\d)$/u.test(source.source_at) || !Number.isFinite(Date.parse(source.source_at)) ||
        typeof source.content_redacted !== "boolean" || typeof source.truncated !== "boolean" || seen.has(source.source_id) ||
        (source.kind === "patient_intake_summary") !== (source.appointment_ref === value.appointment_ref)) invalid();
    seen.add(source.source_id);
    const contentHash = [...new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(source.content as string)))].map(x => x.toString(16).padStart(2, "0")).join("");
    if (contentHash !== source.content_sha256) invalid();
  }
  const priorCount = value.sources.filter(source => source.kind === "generated_visit_note").length;
  if (priorCount > 5 || value.sources.length - priorCount > 1 || value.additional_notes_available && priorCount !== 5) invalid();
  const {display_sha256, ...snapshot} = value;
  const calculated = [...new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(canonical(snapshot))))].map(x => x.toString(16).padStart(2, "0")).join("");
  if (calculated !== display_sha256) invalid();
  return value as EncounterPrep;
}
