import { BffResponseError } from "./http-client";
import { MAX_TRANSCRIPT_TOTAL_CONTENT_CHARS, MAX_TRANSCRIPT_SEGMENT_CONTENT_CHARS } from "./transcript-limits";

export type SpeakerRole = "clinician" | "patient" | "other" | "unknown";
export type WorkingSegment = { source_segment_id: string; source_segment_version: number;
  source_locale: "en-US" | "es-US" | "unknown"; speaker_id: string; speaker_role: SpeakerRole;
  start_ms: number; end_ms: number; content: string; locale_confidence: null };
export type WorkingReceipt = {
  receipt_id: string; session_id: string; raw_transcript_id: string; raw_transcript_sha256: string;
  previous_working_sha256: string | null; working_sha256: string; created_at: string;
  corrected_by_practitioner_id: string | null;
  working_source: { schema_version: "1.0"; source_transcript_version: number;
    language_mode: "en-US" | "en-US+es-US"; transcription_adapter_id: "captured_raw_transcript_v1";
    transcription_model_profile_id: "persisted_capture"; normalization_profile_id: "capture_corrections_v1";
    duration_ms: number; segments: WorkingSegment[] };
  working_transcript: { schema_version: "1.0"; working_transcript_id: string;
    working_transcript_version: number; source_transcript_version: number;
    segments: (Omit<WorkingSegment, "content" | "locale_confidence"> & { content: string | null;
      resolution: "english_source" | "unresolved"; translation_id: null; translation_version: null; translation_review_id: null })[];
    blockers: { source_segment_id: string; code: "source_overlap" | "translation_missing" | "source_locale_unknown" }[];
    note_ready: boolean };
};
export type SegmentEdit = { source_segment_id: string; content: string; speaker_role: SpeakerRole };
export type CorrectionRequest = { raw_transcript_id: string; raw_transcript_sha256: string;
  expected_working_version: number; expected_working_sha256: string; corrections: SegmentEdit[] };
export const uuid = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/u.test(v);
const hash = (v: unknown): v is string => typeof v === "string" && /^[a-f0-9]{64}$/u.test(v);
const integer = (v: unknown, min: number, max = Number.MAX_SAFE_INTEGER): v is number => Number.isSafeInteger(v) && (v as number) >= min && (v as number) <= max;
const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
export const closed = (v: unknown, keys: string): v is Record<string, unknown> => record(v) && Object.keys(v).sort().join(",") === keys.split(",").sort().join(",");
export const role = (v: unknown): v is SpeakerRole => ["clinician", "patient", "other", "unknown"].includes(v as string);
export const characters = (v: string) => [...v].length;
export const validTranscriptText = (v: unknown): v is string => typeof v === "string" && !!v.trim() &&
  !v.includes("\0") && characters(v) <= MAX_TRANSCRIPT_SEGMENT_CONTENT_CHARS && new TextDecoder().decode(new TextEncoder().encode(v)) === v;
export function invalid(): never { throw new BffResponseError(503, "capture_receipt_invalid", null); }
const originKeys = "source_segment_id,source_segment_version,source_locale,speaker_id,speaker_role,start_ms,end_ms";

export async function workingHash(value: unknown): Promise<string> {
  function sorted(v: unknown): unknown {
    if (Array.isArray(v)) return v.map(sorted);
    if (record(v)) return Object.fromEntries(Object.keys(v).sort().map(key => [key, sorted(v[key])]));
    return v;
  }
  const result = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(JSON.stringify(sorted(value))));
  return [...new Uint8Array(result)].map(v => v.toString(16).padStart(2, "0")).join("");
}

export async function validateWorking(value: unknown, session: string, rawId: string): Promise<WorkingReceipt> {
  if (!closed(value, "receipt_id,session_id,raw_transcript_id,raw_transcript_sha256,previous_working_sha256,working_sha256,working_source,working_transcript,corrected_by_practitioner_id,created_at") ||
      !uuid(value.receipt_id) || value.session_id !== session || value.raw_transcript_id !== rawId ||
      !hash(value.raw_transcript_sha256) || !hash(value.working_sha256) ||
      typeof value.created_at !== "string" || !/T.*(?:Z|[+-]\d{2}:\d{2})$/u.test(value.created_at) || !Number.isFinite(Date.parse(value.created_at))) invalid();
  const s = value.working_source, w = value.working_transcript;
  if (!closed(s, "schema_version,source_transcript_version,language_mode,transcription_adapter_id,transcription_model_profile_id,normalization_profile_id,duration_ms,segments") ||
      s.schema_version !== "1.0" || !integer(s.source_transcript_version, 1) ||
      !["en-US", "en-US+es-US"].includes(s.language_mode as string) || s.transcription_adapter_id !== "captured_raw_transcript_v1" ||
      s.transcription_model_profile_id !== "persisted_capture" || s.normalization_profile_id !== "capture_corrections_v1" ||
      !integer(s.duration_ms, 1, 86400000) || !Array.isArray(s.segments) || !s.segments.length || s.segments.length > 10000 ||
      !closed(w, "schema_version,working_transcript_id,working_transcript_version,source_transcript_version,segments,blockers,note_ready") ||
      w.schema_version !== "1.0" || !uuid(w.working_transcript_id) || w.working_transcript_version !== s.source_transcript_version ||
      w.source_transcript_version !== s.source_transcript_version || !Array.isArray(w.segments) || w.segments.length !== s.segments.length ||
      !Array.isArray(w.blockers) || w.blockers.length > 20000 || typeof w.note_ready !== "boolean") invalid();
  if (s.source_transcript_version === 1 ? value.previous_working_sha256 !== null || value.corrected_by_practitioner_id !== null
    : !hash(value.previous_working_sha256) || typeof value.corrected_by_practitioner_id !== "string" ||
      !/^doctor_[0-7][0-9a-hjkmnp-tv-z]{25}$/u.test(value.corrected_by_practitioner_id)) invalid();
  let end = 0, count = 0, previous: WorkingSegment | null = null;
  const ids = new Set<string>(), expected = new Set<string>();
  for (let i = 0; i < s.segments.length; i++) {
    const original: unknown = s.segments[i], projected: unknown = w.segments[i];
    if (!closed(original, originKeys + ",content,locale_confidence") || !uuid(original.source_segment_id) ||
        !integer(original.source_segment_version, 1, s.source_transcript_version) || !uuid(original.speaker_id) ||
        !role(original.speaker_role) || !["en-US", "es-US", "unknown"].includes(original.source_locale as string) ||
        !integer(original.start_ms, 0, 86399999) || !integer(original.end_ms, original.start_ms + 1, 86400000) ||
        !validTranscriptText(original.content) || original.locale_confidence !== null || ids.has(original.source_segment_id) ||
        !closed(projected, originKeys + ",resolution,content,translation_id,translation_version,translation_review_id") ||
        originKeys.split(",").some(key => original[key] !== projected[key]) ||
        projected.translation_id !== null || projected.translation_version !== null || projected.translation_review_id !== null) invalid();
    const segment = original as WorkingSegment;
    if (previous && (segment.start_ms < previous.start_ms || segment.start_ms === previous.start_ms &&
        (segment.end_ms < previous.end_ms || segment.end_ms === previous.end_ms && segment.source_segment_id < previous.source_segment_id))) invalid();
    previous = segment; ids.add(segment.source_segment_id); count += characters(segment.content);
    if (segment.start_ms < end) expected.add(segment.source_segment_id + ":source_overlap");
    end = Math.max(end, segment.end_ms);
    const english = segment.source_locale === "en-US";
    if (projected.resolution !== (english ? "english_source" : "unresolved") || projected.content !== (english ? segment.content : null)) invalid();
    if (!english) expected.add(segment.source_segment_id + (segment.source_locale === "es-US" ? ":translation_missing" : ":source_locale_unknown"));
  }
  if (count > MAX_TRANSCRIPT_TOTAL_CONTENT_CHARS || end !== s.duration_ms || w.note_ready !== (expected.size === 0) || w.blockers.length !== expected.size) invalid();
  for (const b of w.blockers) if (!closed(b, "source_segment_id,code") || !expected.delete(b.source_segment_id + ":" + b.code)) invalid();
  if (await workingHash({raw_transcript_sha256:value.raw_transcript_sha256,working_source:s}) !== value.working_sha256) invalid();
  return value as WorkingReceipt;
}
