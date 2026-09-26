/** Qualified transcript evidence. It grants neither capture nor clinical review. */
import type { RequestOptions, Transcript } from "./contracts";
import { MAX_TRANSCRIPT_TOTAL_CONTENT_CHARS } from "./transcript-limits";
import { canonicalCaptureTimestamp as timestamp, canonicalRecoveryRequest,
  validateRecoveryHistory, type CaptureRecoveryHistory } from "./recovery-contracts";
import { closed, invalid, role, uuid, validTranscriptText, validateWorking, workingHash,
  type WorkingReceipt } from "./working-contracts";

export interface CaptureSourceEnvelope {
  protocol_version: "1.0";
  session_id: string;
  raw_transcript: Transcript;
  working_transcript: WorkingReceipt;
  recovery_history: CaptureRecoveryHistory;
  recovery_sha256: string;
  source_sha256: string;
  capture_incomplete: boolean;
}
export interface CaptureQualifiedSourceBff {
  getCaptureSource(sessionId: string, options?: RequestOptions): Promise<CaptureSourceEnvelope>;
}
const integer = (v: unknown, min: number, max: number): v is number =>
  Number.isSafeInteger(v) && (v as number) >= min && (v as number) <= max;
const bounded = (v: unknown, min: number, max: number): v is string =>
  typeof v === "string" && [...v].length >= min && [...v].length <= max &&
  new TextDecoder().decode(new TextEncoder().encode(v)) === v;

async function digest(text: string, algorithm = "SHA-256"): Promise<Uint8Array> {
  return new Uint8Array(await crypto.subtle.digest(algorithm, new TextEncoder().encode(text)));
}
const hex = (bytes: Uint8Array) => [...bytes].map(byte => byte.toString(16).padStart(2, "0")).join("");
async function uuid5(namespace: string, name: string): Promise<string> {
  const prefix = Uint8Array.from(namespace.replaceAll("-", "").match(/../gu)!, value => parseInt(value, 16));
  const bytes = new Uint8Array(prefix.length + new TextEncoder().encode(name).length);
  bytes.set(prefix); bytes.set(new TextEncoder().encode(name), prefix.length);
  const hash = new Uint8Array(await crypto.subtle.digest("SHA-1", bytes)).slice(0, 16);
  hash[6] = (hash[6] & 15) | 80; hash[8] = (hash[8] & 63) | 128;
  const s = hex(hash);
  return `${s.slice(0,8)}-${s.slice(8,12)}-${s.slice(12,16)}-${s.slice(16,20)}-${s.slice(20)}`;
}
// The producer's confidence field is a Python float, including 0.0 and 1.0.
// Preserve its canonical numeric representation rather than hashing JS's 0/1.
function confidenceFloat(value: number): string {
  if (Object.is(value, -0)) return "-0.0";
  if (Number.isInteger(value)) return `${value}.0`;
  if (value < 0.0001) return value.toExponential().replace(/e-(\d)$/u, "e-0$1");
  return JSON.stringify(value);
}
function rawDocument(value: unknown, key = ""): string {
  if (key === "confidence" && typeof value === "number") return confidenceFloat(value);
  if (Array.isArray(value)) return `[${value.map(item => rawDocument(item)).join(",")}]`;
  if (value !== null && typeof value === "object") return `{${Object.entries(value).sort(([a],[b]) => a < b ? -1 : a > b ? 1 : 0)
    .map(([name, item]) => `${JSON.stringify(name)}:${rawDocument(item, name)}`).join(",")}}`;
  return JSON.stringify(value);
}
export async function captureRawHash(raw: Transcript): Promise<string> {
  return hex(await digest(rawDocument({...raw, created_at:timestamp(raw.created_at)})));
}
export async function captureRecoveryHash(history: CaptureRecoveryHistory): Promise<string> {
  return workingHash({...history, recoveries:history.recoveries.map(item => ({...item,
    request:JSON.parse(canonicalRecoveryRequest(item.request)) as unknown,
    lease:{...item.lease, issued_at:timestamp(item.lease.issued_at), expires_at:timestamp(item.lease.expires_at)},
  }))});
}
function validateRaw(value: unknown, sessionId: string, now: Date): Transcript {
  if (!closed(value, "id,session_id,created_at,language_code,stt_provider,segments") || !uuid(value.id) ||
      value.session_id !== sessionId || !bounded(value.language_code, 2, 16) || !bounded(value.stt_provider, 1, 40) ||
      !Array.isArray(value.segments) || !value.segments.length || value.segments.length > 10000) invalid();
  timestamp(value.created_at);
  if (Date.parse(value.created_at as string) > now.getTime() + 5000) invalid();
  let previousStart = 0, characters = 0;
  for (const segment of value.segments) {
    if (!closed(segment, "content,start_ms,end_ms,speaker_id,speaker_role,confidence") ||
        !validTranscriptText(segment.content) || !integer(segment.start_ms, previousStart, 86399999) ||
        !integer(segment.end_ms, segment.start_ms + 1, 86400000) || !bounded(segment.speaker_id, 1, 80) ||
        !role(segment.speaker_role) || !(segment.confidence === null || typeof segment.confidence === "number" &&
          Number.isFinite(segment.confidence) && segment.confidence >= 0 && segment.confidence <= 1)) invalid();
    previousStart = segment.start_ms; characters += [...segment.content].length;
  }
  if (characters > MAX_TRANSCRIPT_TOTAL_CONTENT_CHARS) invalid();
  return value as unknown as Transcript;
}
export async function validateCaptureSource(value: unknown, sessionId: string, now = new Date()): Promise<CaptureSourceEnvelope> {
  if (!uuid(sessionId) || !Number.isFinite(now.getTime()) ||
      !closed(value, "protocol_version,session_id,raw_transcript,working_transcript,recovery_history,recovery_sha256,source_sha256,capture_incomplete") ||
      value.protocol_version !== "1.0" || value.session_id !== sessionId || typeof value.capture_incomplete !== "boolean") invalid();
  const raw = validateRaw(value.raw_transcript, sessionId, now);
  const working = await validateWorking(value.working_transcript, sessionId, raw.id);
  timestamp(working.created_at);
  if (Date.parse(working.created_at) > now.getTime() + 5000 ||
      working.raw_transcript_sha256 !== await captureRawHash(raw) ||
      working.working_transcript.working_transcript_id !== await uuid5(raw.id, "capture-working-transcript-v1")) invalid();
  const history = await validateRecoveryHistory(value.recovery_history, sessionId, now);
  if (value.recovery_sha256 !== await captureRecoveryHash(history) ||
      value.capture_incomplete !== (history.recoveries.length > 0) ||
      value.source_sha256 !== await workingHash({raw_transcript_sha256:working.raw_transcript_sha256,
        working_sha256:working.working_sha256,recovery_sha256:value.recovery_sha256})) invalid();
  const locale = ({en:"en-US","en-us":"en-US",es:"es-US","es-us":"es-US"} as Record<string,string>)[raw.language_code.toLowerCase()] ?? "unknown";
  if (working.working_source.language_mode !== (locale === "es-US" ? "en-US+es-US" : "en-US") ||
      working.working_source.segments.length !== raw.segments.length) invalid();
  const originals = new Map(await Promise.all(raw.segments.map(async (segment,index) => [await uuid5(raw.id, `segment:${index}`),segment] as const)));
  for (const segment of working.working_source.segments) {
    const original = originals.get(segment.source_segment_id);
    if (!original || segment.start_ms !== original.start_ms || segment.end_ms !== original.end_ms ||
        segment.source_locale !== locale || segment.speaker_id !== await uuid5(raw.id, `speaker:${original.speaker_id}`) ||
        (working.working_source.source_transcript_version === 1 && (segment.content !== original.content ||
          segment.speaker_role !== original.speaker_role || segment.source_segment_version !== 1))) invalid();
  }
  return value as unknown as CaptureSourceEnvelope;
}
