import {workspaceFetch} from './workspace-protocol';
import { WorkspaceCaptureBff } from "../../clients/capture/src/bff/workspace-client";
import { MAX_CAPTURE_SOURCE_BYTES } from "../../clients/capture/src/bff/transcript-limits";
import { BffResponseError } from "../../clients/capture/src/bff/http-client";
import type { AuthenticatedWorkspaceIdentity, CaptureBotSelection } from "./workspace-api";
import { assertCurrentDesktopSession, workspaceAuthHeaders } from "./workspace-auth-headers";
import { WORKSPACE_AUTHENTICATED_BUILD, WORKSPACE_BUILD } from "./workspace-api";

export const CAPTURE_WORKSPACE_BUILD = WORKSPACE_BUILD && WORKSPACE_AUTHENTICATED_BUILD &&
  import.meta.env.VITE_WORKSPACE_CAPTURE_ENABLED === "true";
export const CAPTURE_NOTES_BUILD = CAPTURE_WORKSPACE_BUILD &&
  import.meta.env.VITE_WORKSPACE_CAPTURE_NOTES_ENABLED === "true";
export const CAPTURE_CORRECTIONS_BUILD = CAPTURE_NOTES_BUILD &&
  import.meta.env.VITE_WORKSPACE_CAPTURE_CORRECTIONS_ENABLED === "true";
// Owner: founder; no released cohort; review 2026-09-30. Independent local qualification.
export const CAPTURE_RECOVERY_BUILD = CAPTURE_WORKSPACE_BUILD &&
  import.meta.env.VITE_WORKSPACE_CAPTURE_RECOVERY_ENABLED === "true";
export const CAPTURE_SOURCE_BUILD = CAPTURE_CORRECTIONS_BUILD &&
  import.meta.env.VITE_WORKSPACE_CAPTURE_SOURCE_ENABLED === "true";
// Founder-owned local cohort; review 2026-10-20. Disabling preserves selected profiles.
export const CAPTURE_LONG_VISITS_BUILD = CAPTURE_WORKSPACE_BUILD &&
  import.meta.env.VITE_WORKSPACE_CAPTURE_LONG_VISITS_ENABLED === "true";

export type CaptureAttestation = {
  modality: "in_person" | "virtual" | "phone";
  participant_regions: string[];
  method: "verbal_attestation";
  all_parties_consented: true;
  granted_at: string;
};
export type CaptureLanguage = "en-US" | "en-US+es-US";
export type PreparedCapture = {
  configured_capture?: {schema_version: "1.0"; language_mode: CaptureLanguage};
  status: "prepared"; workspace_id: string; session_id: string; consent_record_id: string;
};
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/iu;
const SAFE_CODES = new Set(["capture_consent_required", "capture_consent_unavailable",
  "capture_request_conflict", "capture_in_progress", "capture_session_changed",
  "capture_context_changed", "capture_connection_required", "core_capture_access_unavailable",
  "capture_note_conflict", "capture_source_unavailable", "capture_notes_unavailable", "capture_notebook_changed",
  "bot_paused", "team_revision_conflict", "bot_source_unavailable"]);

export async function request(workspaceId: string, action: "admission" | "operations" | "notes" | "prep",
  identity: AuthenticatedWorkspaceIdentity, body: unknown, signal?: AbortSignal,
  maxBytes = 131072, timeoutMs = 30000): Promise<unknown> {
  const base = import.meta.env.VITE_API_BASE?.trim().replace(/\/+$/, "") || "http://127.0.0.1:8000";
  if (!UUID.test(workspaceId)) {
    throw new BffResponseError(401, "capture_access_unavailable", null);
  }
  const controller = new AbortController();
  const abort = () => controller.abort();
  const timer = setTimeout(abort, timeoutMs);
  signal?.addEventListener("abort", abort, { once: true });
  if (signal?.aborted) abort();
  let cancelAuth: (() => void) | undefined;
  try {
    controller.signal.throwIfAborted();
    // The request deadline also covers credentials. A late token never resumes
    // a cancelled request; desktop credentials remain inside the main proxy.
    let headers: Headers;
    try {
      headers = await Promise.race([workspaceAuthHeaders(identity, base), new Promise<never>((_, reject) => {
        cancelAuth = () => reject(new Error("capture request cancelled"));
        controller.signal.addEventListener("abort", cancelAuth, {once: true});
        if (controller.signal.aborted) cancelAuth();
      })]);
      controller.signal.throwIfAborted();
      assertCurrentDesktopSession(identity);
    } catch {
      if (controller.signal.aborted) throw new BffResponseError(503, "capture_request_unconfirmed", null);
      throw new BffResponseError(401, "capture_access_unavailable", null);
    }
    const response = await workspaceFetch(identity,`${base}/workspaces/${workspaceId}/capture/${action}`, {
      method: "POST", cache: "no-store", credentials: "omit", redirect: "error",
      referrerPolicy: "no-referrer", signal: controller.signal,
      headers,
      body: JSON.stringify(body),
    });
    if (response.headers.get("content-type")?.split(";", 1)[0].trim() !== "application/json" ||
        !response.headers.get("cache-control")?.split(",").some(value => value.trim().toLowerCase() === "no-store")) {
      throw new BffResponseError(response.status, "capture_request_unconfirmed", null);
    }
    const reader = response.body?.getReader();
    if (!reader) throw new BffResponseError(503, "capture_request_unconfirmed", null);
    const chunks: Uint8Array[] = [];
    let bytes = 0;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      bytes += value.byteLength;
      if (bytes > maxBytes) {
        await reader.cancel();
        throw new BffResponseError(503, "capture_receipt_invalid", null);
      }
      chunks.push(value);
    }
    const contents = new Uint8Array(bytes);
    let offset = 0;
    for (const chunk of chunks) { contents.set(chunk, offset); offset += chunk.byteLength; }
    const value: unknown = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(contents));
    assertCurrentDesktopSession(identity);
    if (!response.ok || response.status === 202) {
      const code = isRecord(value) && typeof value.detail === "string" && SAFE_CODES.has(value.detail)
        ? value.detail : "capture_request_unconfirmed";
      throw new BffResponseError(response.status, code, null);
    }
    return value;
  } catch (error) {
    if (error instanceof BffResponseError) throw error;
    throw new BffResponseError(503, "capture_request_unconfirmed", null);
  } finally {
    if (cancelAuth) controller.signal.removeEventListener("abort", cancelAuth);
    clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
  }
}

export async function prepareCapture(workspaceId: string, identity: AuthenticatedWorkspaceIdentity,
  attestation: CaptureAttestation | null, idempotencyKey: string, signal?: AbortSignal, bot?: CaptureBotSelection, language?: CaptureLanguage): Promise<PreparedCapture> {
  const result = await request(workspaceId, "admission", identity,
    { attestation, idempotency_key: idempotencyKey, ...(bot ? {bot} : {}),
      ...(attestation && language ? {configured_capture: {schema_version: "1.0", language_mode: language}} : {}) }, signal);
  if (!isRecord(result) || Object.keys(result).sort().join(",") !== (("configured_capture" in result ? "configured_capture," : "") + "consent_record_id,session_id,status,workspace_id") ||
      result.status !== "prepared" || result.workspace_id !== workspaceId ||
      typeof result.session_id !== "string" || !UUID.test(result.session_id) ||
      typeof result.consent_record_id !== "string" || !UUID.test(result.consent_record_id)) {
    throw new BffResponseError(503, "capture_receipt_invalid", null);
  }
  if ("configured_capture" in result && (!isRecord(result.configured_capture) ||
      Object.keys(result.configured_capture).sort().join(",") !== "language_mode,schema_version" ||
      result.configured_capture.schema_version !== "1.0" || !["en-US","en-US+es-US"].includes(String(result.configured_capture.language_mode)))) {
    throw new BffResponseError(503, "capture_receipt_invalid", null);
  }
  if (attestation && language && (!isRecord(result.configured_capture) || result.configured_capture.language_mode !== language)) {
    throw new BffResponseError(503, "capture_receipt_invalid", null);
  }
  return result as PreparedCapture;
}

export function workspaceCaptureBff(workspaceId: string, sessionId: string, identity: AuthenticatedWorkspaceIdentity,
  scopeSignal?: AbortSignal) {
  return new WorkspaceCaptureBff(workspaceId, sessionId,
    (body, signal) => request(workspaceId, "operations", identity, body,
      signal && scopeSignal ? AbortSignal.any([signal, scopeSignal]) : signal ?? scopeSignal,
      ["transcript", "capture_source"].includes(body.operation.kind) ? MAX_CAPTURE_SOURCE_BYTES + 4096 :
        body.operation.kind === "capture_recovery_state" ? 2_004_096 : 131072));
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
