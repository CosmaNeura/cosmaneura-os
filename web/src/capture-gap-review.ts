import type { CaptureGapReasonCode } from "../../clients/capture/src/flow/types";
import { BffResponseError } from "../../clients/capture/src/bff/http-client";
import type { CaptureSourceEnvelope } from "../../clients/capture/src/bff/source-contracts";

export type CaptureGapObservation = { gap_id: string; reason_code: CaptureGapReasonCode;
  observed_at: string; acknowledged_at: string; decision: "resume_capture" | "finish_capture" };
export type CaptureGapReview = { recovery_sha256: string; observations: CaptureGapObservation[]; review_required: true };

/** Caller supplies the recorder's already validated source; review stays required. */
export function sourceGapReview(source: CaptureSourceEnvelope | undefined): CaptureGapReview | null {
  if (!source?.capture_incomplete) return null;
  return { recovery_sha256:source.recovery_sha256, review_required:true,
    observations:source.recovery_history.recoveries.map(({request}) => ({gap_id:request.gap_id,
      reason_code:request.reason_code,observed_at:request.observed_at,acknowledged_at:request.acknowledged_at,decision:request.decision})) };
}

export const gapReasons: Record<CaptureGapReasonCode, string> = {
  audio_context_suspended: "Audio capture paused",
  audio_device_disconnected: "Microphone disconnected",
  audio_route_changed: "Audio input changed",
  audio_session_interrupted: "Audio session interrupted",
  capture_backgrounded: "Recording moved to the background",
  capture_source_stalled: "Audio stopped arriving",
  capture_source_failed: "Audio capture failed",
  capture_authority_expired: "Recording permission expired",
  process_recovery_unknown: "Recording state was uncertain after reopening",
};
const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const closed = (v: unknown, keys: string): v is Record<string, unknown> => record(v) && Object.keys(v).sort().join(",") === keys.split(",").sort().join(",");
const instant = (v: unknown): v is string => typeof v === "string" && /T.*(?:Z|[+-]\d{2}:\d{2})$/u.test(v) && Number.isFinite(Date.parse(v));
function invalid(): never { throw new BffResponseError(503, "capture_receipt_invalid", null); }

export function validateCaptureGapReview(value: unknown): CaptureGapReview {
  if (!closed(value, "recovery_sha256,observations,review_required") || value.review_required !== true ||
      typeof value.recovery_sha256 !== "string" || !/^[a-f0-9]{64}$/u.test(value.recovery_sha256) ||
      !Array.isArray(value.observations) || !value.observations.length || value.observations.length > 1000) invalid();
  const ids = new Set<string>(); let prior = -Infinity;
  for (const item of value.observations) {
    if (!closed(item, "gap_id,reason_code,observed_at,acknowledged_at,decision") ||
        typeof item.gap_id !== "string" || !/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/u.test(item.gap_id) || ids.has(item.gap_id) ||
        typeof item.reason_code !== "string" || !Object.hasOwn(gapReasons, item.reason_code) ||
        !instant(item.observed_at) || !instant(item.acknowledged_at) ||
        Date.parse(item.observed_at) < prior || Date.parse(item.observed_at) > Date.parse(item.acknowledged_at) ||
        !["resume_capture", "finish_capture"].includes(item.decision as string)) invalid();
    ids.add(item.gap_id); prior = Date.parse(item.acknowledged_at);
  }
  return value as CaptureGapReview;
}

export function captureGapKey(value: CaptureGapReview | undefined): string {
  return value ? JSON.stringify([value.recovery_sha256, value.observations.map(gap =>
    [gap.gap_id, gap.reason_code, gap.observed_at, gap.acknowledged_at, gap.decision])]) : "";
}
