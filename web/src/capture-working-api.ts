import { request } from "./capture-api";
import { MAX_TRANSCRIPT_TOTAL_CONTENT_CHARS, MAX_CAPTURE_SOURCE_BYTES, MAX_WORKING_BYTES } from "../../clients/capture/src/bff/transcript-limits";
import type { AuthenticatedWorkspaceIdentity } from "./workspace-api";
import { validateCaptureSource, type CaptureSourceEnvelope } from "../../clients/capture/src/bff/source-contracts";
import { characters, closed, invalid, role, uuid, validTranscriptText, validateWorking, type CorrectionRequest, type SegmentEdit, type WorkingReceipt } from "../../clients/capture/src/bff/working-contracts";
export { validTranscriptText, validateWorking, workingHash, type CorrectionRequest, type SegmentEdit, type SpeakerRole, type WorkingReceipt, type WorkingSegment } from "../../clients/capture/src/bff/working-contracts";

async function operation(workspace: string, session: string, rawId: string, identity: AuthenticatedWorkspaceIdentity,
  legacyKind: "working_transcript" | "correct_transcript", key: string, payload?: CorrectionRequest, signal?: AbortSignal,
  qualifiedSource?: CaptureSourceEnvelope) {
  if (!uuid(session) || !uuid(rawId) || !uuid(key)) invalid();
  const kind = qualifiedSource ? (legacyKind === "working_transcript" ? "capture_source" : "correct_capture_source") : legacyKind;
  if (qualifiedSource && (qualifiedSource.session_id !== session || qualifiedSource.raw_transcript.id !== rawId)) invalid();
  const value = await request(workspace, "operations", identity, {session_id:session,idempotency_key:key,
    operation:{kind,...(payload ? {payload} : {})}}, signal, (qualifiedSource ? MAX_CAPTURE_SOURCE_BYTES : MAX_WORKING_BYTES) + 4096);
  if (!closed(value, "workspace_id,session_id,operation,receipt") || value.workspace_id !== workspace || value.session_id !== session || value.operation !== kind) invalid();
  if (qualifiedSource) {
    const result = await validateCaptureSource(value.receipt, session);
    if (result.raw_transcript.id !== rawId || result.recovery_sha256 !== qualifiedSource.recovery_sha256 ||
        result.working_transcript.raw_transcript_sha256 !== qualifiedSource.working_transcript.raw_transcript_sha256) invalid();
    return result.working_transcript;
  }
  return validateWorking(value.receipt, session, rawId);
}
export function readWorking(workspace: string, session: string, rawId: string, identity: AuthenticatedWorkspaceIdentity, signal?: AbortSignal,
  qualifiedSource?: CaptureSourceEnvelope) {
  return operation(workspace, session, rawId, identity, "working_transcript", crypto.randomUUID(), undefined, signal, qualifiedSource);
}
export async function correctWorking(workspace: string, identity: AuthenticatedWorkspaceIdentity, base: WorkingReceipt,
  corrections: SegmentEdit[], key: string, signal?: AbortSignal, qualifiedSource?: CaptureSourceEnvelope): Promise<WorkingReceipt> {
  if (!corrections.length || new Set(corrections.map(e => e.source_segment_id)).size !== corrections.length ||
      corrections.some(e => !closed(e, "source_segment_id,content,speaker_role") || !validTranscriptText(e.content) || !role(e.speaker_role) ||
        !base.working_source.segments.some(s => s.source_segment_id === e.source_segment_id)) ||
      corrections.reduce((sum, e) => sum + characters(e.content), 0) > MAX_TRANSCRIPT_TOTAL_CONTENT_CHARS) invalid();
  const payload = {raw_transcript_id:base.raw_transcript_id,raw_transcript_sha256:base.raw_transcript_sha256,
    expected_working_version:base.working_source.source_transcript_version,expected_working_sha256:base.working_sha256,corrections};
  const result = await operation(workspace, base.session_id, base.raw_transcript_id, identity, "correct_transcript", key, payload, signal, qualifiedSource);
  if (result.raw_transcript_sha256 !== base.raw_transcript_sha256 || result.previous_working_sha256 !== base.working_sha256 ||
      result.working_source.source_transcript_version !== base.working_source.source_transcript_version + 1 ||
      corrections.some(e => !result.working_source.segments.some(s => s.source_segment_id === e.source_segment_id && s.content === e.content && s.speaker_role === e.speaker_role))) invalid();
  return result;
}
