import { HttpCreatorReviewApi } from "../../clients/scribe-review/creator-review-api";
import { BffResponseError } from "../../clients/capture/src/bff/http-client";
import { request } from "./capture-api";
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
      }, signal, 8 * 1024 * 1024 + 4096);
      if (!value || typeof value !== "object" || Array.isArray(value) ||
          Object.keys(value).sort().join(",") !== "operation,receipt,session_id,workspace_id") throw new Error("Invalid review response");
      const result = value as Record<string, unknown>;
      if (result.session_id !== sessionId || result.workspace_id !== workspaceId || result.operation !== kind) throw new Error("Review scope changed");
      return Response.json(result.receipt);
    } catch (error) {
      if (error instanceof BffResponseError && error.status === 409) return new Response(null, {status: 409});
      throw error;
    }
  });
}
