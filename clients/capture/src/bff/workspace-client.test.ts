import { expect, it, vi } from "vitest";
import { WorkspaceCaptureBff, type WorkspaceCaptureTransport } from "./workspace-client";

const workspace = "00000000-0000-4000-8000-000000000002";
const session = "00000000-0000-4000-8000-000000000003";
const status = { session_id: session, status: "completed", transcript_available: true, updated_at: new Date().toISOString() };
const transcript = { id: "00000000-0000-4000-8000-000000000004", session_id: session,
  created_at: new Date().toISOString(), language_code: "en", stt_provider: "synthetic",
  segments: [{ content: "Invented source speech.", speaker_id: "one", speaker_role: "clinician", start_ms: 0, end_ms: 1000, confidence: null }] };

it("retrieves scoped status and source text without consent/session creation or identity claims", async () => {
  const transport = vi.fn<WorkspaceCaptureTransport>(async request => ({ workspace_id: workspace,
    session_id: session, operation: request.operation.kind,
    receipt: request.operation.kind === "transcript" ? transcript : status }));
  const bff = new WorkspaceCaptureBff(workspace, session, transport);
  const abort = new AbortController();
  expect(await bff.getTranscriptionStatus(session, { signal: abort.signal })).toEqual(status);
  expect(await bff.getTranscript(session, { signal: abort.signal })).toEqual(transcript);
  for (const [request, signal] of transport.mock.calls) {
    expect(Object.keys(request).sort()).toEqual(["idempotency_key", "operation", "session_id"]);
    expect(request.session_id).toBe(session); expect(signal).toBe(abort.signal);
  }
});

it.each(["status", "transcript"])("rejects a different caller session before the %s transport", async method => {
  const transport = vi.fn<WorkspaceCaptureTransport>();
  const bff = new WorkspaceCaptureBff(workspace, session, transport);
  await expect(method === "status" ? bff.getTranscriptionStatus("other") : bff.getTranscript("other"))
    .rejects.toMatchObject({ code: "capture_session_changed" });
  expect(transport).not.toHaveBeenCalled();
});

it.each(["foreign_status", "foreign_transcript", "false_ready", "empty_transcript"])(
  "does not display invalid transcript readiness/output: %s", async fault => {
    const receipt = fault.endsWith("status") || fault === "false_ready" ? { ...status } : { ...transcript };
    if (fault.startsWith("foreign")) receipt.session_id = "another-session";
    if (fault === "false_ready" && "transcript_available" in receipt) receipt.transcript_available = false;
    if (fault === "empty_transcript" && "segments" in receipt) receipt.segments = [];
    const operation = "segments" in receipt ? "transcript" : "transcription_status";
    const bff = new WorkspaceCaptureBff(workspace, session, async () => ({ workspace_id: workspace,
      session_id: session, operation, receipt }));
    await expect(operation === "transcript" ? bff.getTranscript(session) : bff.getTranscriptionStatus(session))
      .rejects.toMatchObject({ code: "capture_receipt_invalid" });
  });
