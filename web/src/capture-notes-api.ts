import { parseCaptureContinuity, type CaptureContinuity } from "../../clients/scribe-review/creator-review-api";
import { BffResponseError } from "../../clients/capture/src/bff/http-client";
import { request } from "./capture-api";
import type { AuthenticatedWorkspaceIdentity, CaptureBotSelection } from "./workspace-api";
import { captureGapKey, validateCaptureGapReview, type CaptureGapReview } from "./capture-gap-review";
import { notebookSourceKey, validNotebookSource, type NotebookSource } from "./notebook-source";

export type ReviewedSource = {kind: "reviewed_english"; source_version: number; working_transcript_id: string; working_version: number; capture_continuity?: CaptureContinuity};
export type CaptureNoteTemplate = { schema_ref: string; note_type: string; field_names: string[] };
export type CaptureDraft = {
  session_id: string; scribe_source_id: string; source_sha256: string; schema_ref: string;
  transcript_ref: string | null; note_ref: string | null; status: "draft" | "not_prepared";
  note_type: string; fields: Record<string, string> | null; field_order: string[] | null;
  note_sha256: string | null; created_at: string | null; review_required: true;
  capture_gap_review?: CaptureGapReview;
  notebook_source?: NotebookSource;
  reviewed_source?: ReviewedSource;
};
export type CaptureNoteEdit = { client_key: string; expected_note_ref: string; expected_note_sha256: string;
  expected_source_sha256: string; fields: Record<string, string> };
export type CaptureSaveResolution = { session_id: string; schema_ref: string; client_key: string; request_sha256: string;
  status: "saved" | "closed"; result_note_ref: string | null; result_sha256: string | null };
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/iu;
const digest = /^[a-f0-9]{64}$/u;
const ref = (value: unknown, kind: string) => typeof value === "string" &&
  new RegExp(`^${kind}_[0-7][0-9a-hjkmnp-tv-z]{25}$`, "u").test(value);
const record = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const closed = (value: unknown, keys: string): value is Record<string, unknown> =>
  record(value) && Object.keys(value).sort().join(",") === keys.split(",").sort().join(",");
const text = (value: unknown, limit: number): value is string => typeof value === "string" && value.length > 0 && value.length <= limit;
function invalid(): never { throw new BffResponseError(503, "capture_receipt_invalid", null); }

async function noteRequest(workspace: string, session: string, identity: AuthenticatedWorkspaceIdentity,
  action: "templates" | "read" | "prepare" | "save" | "resolve", schema?: string, signal?: AbortSignal, edit?: CaptureNoteEdit, scratchpadEntryId?: string, bot?: CaptureBotSelection) {
  if (!UUID.test(session) || action !== "templates" && !ref(schema, "doctor_note_schema")) invalid();
  const value = await request(workspace, "notes", identity, { session_id: session,
    idempotency_key: edit?.client_key ?? crypto.randomUUID(), ...(scratchpadEntryId ? {scratchpad_entry_id: scratchpadEntryId} : {}),
    ...(bot ? {bot} : {}),
    note: { action, ...(schema ? { schema_ref: schema } : {}), ...(edit ? {edit} : {}) } },
    signal, 1052672, action === "prepare" ? 105000 : 30000);
  if (!closed(value, "workspace_id,session_id,action,receipt") || value.workspace_id !== workspace ||
      value.session_id !== session || value.action !== action || !record(value.receipt)) invalid();
  return value.receipt;
}

export async function captureNoteTemplates(workspace: string, session: string,
  identity: AuthenticatedWorkspaceIdentity, signal?: AbortSignal): Promise<CaptureNoteTemplate[]> {
  const value = await noteRequest(workspace, session, identity, "templates", undefined, signal);
  if (!closed(value, "session_id,templates") || value.session_id !== session ||
      !Array.isArray(value.templates) || value.templates.length > 100) invalid();
  const seen = new Set<string>();
  for (const item of value.templates) {
    if (!closed(item, "schema_ref,note_type,field_names") || !ref(item.schema_ref, "doctor_note_schema") ||
        !text(item.note_type, 160) || !Array.isArray(item.field_names) ||
        item.field_names.length < 1 || item.field_names.length > 100 ||
        item.field_names.some(name => !text(name, 200)) || new Set(item.field_names).size !== item.field_names.length ||
        seen.has(item.schema_ref as string)) invalid();
    seen.add(item.schema_ref as string);
  }
  return value.templates as CaptureNoteTemplate[];
}

export async function captureDraft(workspace: string, session: string, sourceId: string,
  identity: AuthenticatedWorkspaceIdentity, schema: string, action: "read" | "prepare",
  signal?: AbortSignal, scratchpadEntryId?: string, bot?: CaptureBotSelection): Promise<CaptureDraft> {
  if (!UUID.test(sourceId)) invalid();
  const value = await noteRequest(workspace, session, identity, action, schema, signal, undefined, scratchpadEntryId, bot);
  const result = await validateDraft(value, session, sourceId, schema, workspace);
  if (scratchpadEntryId && result.status === "draft" && result.notebook_source?.entry_id !== scratchpadEntryId) invalid();
  return result;
}

export async function validateDraft(value: Record<string, unknown>, session: string, sourceId: string, schema: string, workspace: string): Promise<CaptureDraft> {
  if (!closed(value, "session_id,scribe_source_id,source_sha256,schema_ref,transcript_ref,note_ref,status,note_type,fields,field_order,note_sha256,created_at,review_required" + ("capture_gap_review" in value ? ",capture_gap_review" : "") + ("notebook_source" in value ? ",notebook_source" : "") + ("reviewed_source" in value ? ",reviewed_source" : "")) ||
      value.session_id !== session || value.scribe_source_id !== sourceId || value.schema_ref !== schema ||
      typeof value.source_sha256 !== "string" || !digest.test(value.source_sha256) ||
      value.review_required !== true || !text(value.note_type, 160) ||
      value.transcript_ref !== null && !ref(value.transcript_ref, "ai_visit_transcript")) invalid();
  if (value.status === "not_prepared") {
    if ([value.note_ref, value.fields, value.field_order, value.note_sha256, value.created_at].some(item => item !== null)) invalid();
  } else if (value.status === "draft") {
    if (!ref(value.note_ref, "visit_note") || !ref(value.transcript_ref, "ai_visit_transcript") ||
        !record(value.fields) || !Array.isArray(value.field_order) ||
        value.field_order.length < 1 || value.field_order.length > 100 ||
        new Set(value.field_order).size !== value.field_order.length ||
        value.field_order.length !== Object.keys(value.fields).length ||
        typeof value.note_sha256 !== "string" || !digest.test(value.note_sha256) ||
        typeof value.created_at !== "string" || !/T.*(?:Z|[+-]\d{2}:\d{2})$/u.test(value.created_at) ||
        !Number.isFinite(Date.parse(value.created_at))) invalid();
    const fields = value.fields;
    const ordered: string[][] = [];
    for (const key of value.field_order) {
      if (!text(key, 200) || !Object.prototype.hasOwnProperty.call(fields, key) ||
          typeof fields[key] !== "string" || key.includes("\0") || (fields[key] as string).includes("\0")) invalid();
      ordered.push([key, fields[key] as string]);
    }
    const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(JSON.stringify(ordered)));
    const actual = [...new Uint8Array(bytes)].map(value => value.toString(16).padStart(2, "0")).join("");
    if (actual !== value.note_sha256) invalid();
  } else invalid();
  if ("reviewed_source" in value) {
    const source = value.reviewed_source;
    if (!closed(source, "kind,source_version,working_transcript_id,working_version" + (record(source) && "capture_continuity" in source ? ",capture_continuity" : "")) ||
        source.kind !== "reviewed_english" || source.working_transcript_id !== sourceId ||
        !Number.isSafeInteger(source.source_version) || Number(source.source_version) < 1 ||
        !Number.isSafeInteger(source.working_version) || Number(source.working_version) < 1) invalid();
    if ("capture_continuity" in source) parseCaptureContinuity(source.capture_continuity);
  }
  if ("capture_gap_review" in value) validateCaptureGapReview(value.capture_gap_review);
  if ("notebook_source" in value && !validNotebookSource(value.notebook_source, workspace)) invalid();
  if (new TextEncoder().encode(JSON.stringify(value)).length > 1048576) invalid();
  return value as CaptureDraft;
}

function noteEdit(base: CaptureDraft, fields: Record<string,string>, clientKey: string): CaptureNoteEdit {
  if (base.status !== "draft" || !base.note_ref || !base.note_sha256 || !base.field_order || !UUID.test(clientKey) ||
      Object.keys(fields).length !== base.field_order.length ||
      base.field_order.some(key => typeof fields[key] !== "string" || fields[key].includes("\0")) ||
      new TextEncoder().encode(JSON.stringify(fields)).length > 262144) invalid();
  return { client_key: clientKey.toLowerCase(), expected_note_ref: base.note_ref, expected_note_sha256: base.note_sha256,
    expected_source_sha256: base.source_sha256, fields };
}

// Core sorts object keys by UTF-8 bytes. JavaScript's UTF-16 sort differs for
// some valid Unicode template fields; use the wire contract's ordering.
function canonical(value: unknown): string {
  if (record(value)) {
    const keys = Object.keys(value).sort((left,right)=>{
      const a=new TextEncoder().encode(left), b=new TextEncoder().encode(right);
      for (let i=0;i<Math.min(a.length,b.length);i++) if(a[i]!==b[i]) return a[i]-b[i];
      return a.length-b.length;
    });
    return "{"+keys.map(key=>JSON.stringify(key)+":"+canonical(value[key])).join(",")+"}";
  }
  if (Array.isArray(value)) return "["+value.map(canonical).join(",")+"]";
  return JSON.stringify(value);
}
async function sha256(value: string): Promise<string> {
  const bytes=await crypto.subtle.digest("SHA-256",new TextEncoder().encode(value));
  return [...new Uint8Array(bytes)].map(byte=>byte.toString(16).padStart(2,"0")).join("");
}

export async function resolveCaptureSave(workspace: string, identity: AuthenticatedWorkspaceIdentity,
  base: CaptureDraft, fields: Record<string,string>, clientKey: string, signal?: AbortSignal): Promise<CaptureSaveResolution> {
  const edit=noteEdit(base,fields,clientKey);
  const value=await noteRequest(workspace,base.session_id,identity,"resolve",base.schema_ref,signal,edit);
  const expected=await sha256(canonical({edit,schema:base.schema_ref,session:base.session_id.toLowerCase(),workspace:workspace.toLowerCase()}));
  if (!closed(value,"session_id,schema_ref,client_key,request_sha256,status,result_note_ref,result_sha256") ||
      value.session_id!==base.session_id || value.schema_ref!==base.schema_ref || value.client_key!==edit.client_key || value.request_sha256!==expected) invalid();
  if (value.status==="closed") {
    if (value.result_note_ref!==null || value.result_sha256!==null) invalid();
  } else if (value.status==="saved") {
    if (!ref(value.result_note_ref,"visit_note") || value.result_note_ref===base.note_ref ||
        value.result_sha256!==await sha256(JSON.stringify(base.field_order!.map(key=>[key,fields[key]])))) invalid();
  } else invalid();
  return value as CaptureSaveResolution;
}

export async function saveCaptureDraft(workspace: string, identity: AuthenticatedWorkspaceIdentity,
  base: CaptureDraft, fields: Record<string, string>, clientKey: string, signal?: AbortSignal): Promise<CaptureDraft> {
  const edit=noteEdit(base,fields,clientKey);
  const value = await noteRequest(workspace, base.session_id, identity, "save", base.schema_ref, signal, edit);
  const result = await validateDraft(value, base.session_id, base.scribe_source_id, base.schema_ref, workspace);
  if (result.status !== "draft" || result.note_ref === base.note_ref || result.source_sha256 !== base.source_sha256 ||
      captureGapKey(result.capture_gap_review) !== captureGapKey(base.capture_gap_review) ||
      notebookSourceKey(result.notebook_source) !== notebookSourceKey(base.notebook_source) ||
      !result.fields || result.field_order?.join("\0") !== base.field_order!.join("\0") ||
      base.field_order!.some(key => result.fields![key] !== fields[key])) invalid();
  return result;
}
