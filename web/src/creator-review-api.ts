import { CreatorReviewError, HttpCreatorReviewApi } from "../../clients/scribe-review/creator-review-api";
import { MAX_CREATOR_REVIEW_BYTES } from "../../clients/capture/src/bff/transcript-limits";
import { BffResponseError } from "../../clients/capture/src/bff/http-client";
import { request,captureFailureObservation } from "./capture-api";
import type { AuthenticatedWorkspaceIdentity } from "./workspace-api";

/** Scribe's review component uses the same authenticated workspace boundary as recording. */
export function creatorReviewApi(workspaceId: string, sessionId: string,
  identity: AuthenticatedWorkspaceIdentity, signal?: AbortSignal) {
  return new HttpCreatorReviewApi(sessionId, async (path, operation) => {
    if (path !== `/v1/captured-sessions/${sessionId}/review`) throw new Error("Invalid review scope");
    const kind = operation.method === "GET" ? "creator_review" : "decide_translation";
    try {
      const value = await request(workspaceId, "operations", identity, {
        session_id: sessionId, idempotency_key: operation.key ?? crypto.randomUUID(),
        operation: {kind, ...(operation.body ? {payload: operation.body} : {})},
      }, signal, MAX_CREATOR_REVIEW_BYTES + 4096);
      if (!value || typeof value !== "object" || Array.isArray(value) ||
          Object.keys(value).sort().join(",") !== "operation,receipt,session_id,workspace_id") throw new CreatorReviewError("invalid_response");
      const result = value as Record<string, unknown>;
      if (result.session_id !== sessionId || result.workspace_id !== workspaceId || result.operation !== kind) throw new CreatorReviewError("invalid_response");
      return Response.json(result.receipt);
    } catch (error) {
      if (error instanceof BffResponseError) {
        const observation=captureFailureObservation(error);
        const invalidResponse = error.code === "capture_receipt_invalid"
          || error.status === 200 && error.code === "capture_request_unconfirmed";
        const clientReason=error.code==="capture_request_unconfirmed"?observation?.origin==="client_timeout"?"client_timeout":
          observation?.origin==="client_cancelled"?"client_cancelled":observation?.origin==="client_transport"?"client_transport_unavailable":
          observation?.origin==="workspace_paused"?"workspace_connection_paused":null:null;
        const reason = error.code === "capture_access_unavailable" ? "access_unavailable"
          : error.code === "core_capture_access_unavailable" ? "core_access_unavailable"
          : error.status===503&&error.code === "core_capture_identity_unavailable" ? "core_identity_unavailable"
          : error.status===503&&error.code === "core_capture_context_invalid" ? "core_context_invalid"
          : error.status===503&&error.code === "core_capture_receipt_invalid" ? "core_receipt_invalid"
          : error.status===503&&error.code === "core_capture_request_unconfirmed" ? "core_request_unconfirmed"
          : error.code === "capture_connection_required" ? "connection_required"
          : ["capture_session_changed", "capture_context_changed", "capture_saved_recording_changed"].includes(error.code ?? "") ? "source_changed"
          : invalidResponse ? "invalid_response" : clientReason??"request_unavailable";
        const phase = invalidResponse ? "response"
          : error.code === "capture_access_unavailable" ? "authorization" : "read";
        throw new CreatorReviewError(phase === "response" ? "invalid_response" : error.status === 409 ? "conflict" : "unavailable",
          {phase, reason, status: error.code === "capture_receipt_invalid"||clientReason ? null : error.status,...(observation?.corePhase?{corePhase:observation.corePhase}:{})});
      }
      throw error;
    }
  });
}
