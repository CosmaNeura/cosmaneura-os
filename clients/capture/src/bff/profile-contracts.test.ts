import { readFileSync } from "node:fs";
import { expect, it, vi } from "vitest";
import { WorkspaceCaptureBff, type WorkspaceCaptureTransport } from "./workspace-client";
import { validateProfileRequest, validateProfileReceipt, profileRequestHash,
  type CaptureProfileReceipt, type CaptureProfileRequest } from "./profile-contracts";

const golden: CaptureProfileReceipt = JSON.parse(readFileSync(new URL("../../../../tests/fixtures/capture_profile.json", import.meta.url), "utf8"));
const session = golden.session_id, workspace = "00000000-0000-4000-8000-000000000002";
const now = new Date("2026-09-20T12:00:00Z");
const capabilities = { protocol_version: "1.0", media: { media_type: "audio/wav", encoding: "pcm_s16le", channels: 1, sample_rate_hz: 16000 },
  target_chunk_duration_ms: 10000, max_envelope_bytes: 327680, max_chunks: 720, remaining_aggregate_plaintext_bytes: 268435456,
  capture_lease_ttl_seconds: 900, reservation_window_seconds: 900, max_reservations_per_batch: 90, upload_concurrency: 2 };

it("matches the Python/Core canonical profile hash and retains exact fixed budgets", async () => {
  expect(await profileRequestHash(golden.request)).toBe(golden.request_sha256);
  expect(await validateProfileReceipt(golden, session, now, golden.request)).toEqual(golden);
});
it.each([[], ["microphone", "microphone"], ["microphone", "mixed"], ["unknown"], ["microphone", "mixed", "system_audio"]].map(channels => ({ channels })))(
  "rejects invalid track selection $channels", ({ channels }) => {
    expect(() => validateProfileRequest({ ...golden.request, channels })).toThrow("capture_profile_invalid");
  });
it.each(["scope", "hash", "future", "budget", "chunks", "duration", "missing", "extra", "request"])(
  "rejects an invalid profile receipt: %s", async fault => {
    const value: Record<string, unknown> = structuredClone(golden) as unknown as Record<string, unknown>;
    if (fault === "scope") value.session_id = workspace;
    if (fault === "hash") value.request_sha256 = "0".repeat(64);
    if (fault === "future") value.created_at = "2026-09-20T12:00:06Z";
    if (fault === "budget") value.maximum_aggregate_plaintext_bytes = 268435457;
    if (fault === "chunks") value.maximum_chunks_per_channel = 361;
    if (fault === "duration") value.maximum_track_duration_ms = 3600001;
    if (fault === "missing") delete value.maximum_chunks;
    if (fault === "extra") value.untrusted = "PRIVATE_SENTINEL";
    if (fault === "request") {
      value.request = { ...golden.request, channels: ["system_audio"] };
      value.request_sha256 = await profileRequestHash(value.request as CaptureProfileRequest);
    }
    await expect(validateProfileReceipt(value, session, now, golden.request)).rejects.toThrow("capture_profile_invalid");
  });

it("selects and recovers without acknowledgment until the receipt is explicitly bound", async () => {
  const transport = vi.fn<WorkspaceCaptureTransport>(async ({ operation }) => ({ workspace_id: workspace, session_id: session,
    operation: operation.kind, receipt: operation.kind === "capabilities" ? capabilities : golden }));
  const bff = new WorkspaceCaptureBff(workspace, session, transport);
  const selected = await bff.selectCaptureProfile(session, golden.request, { idempotencyKey: "saved-profile-key" });
  expect(await bff.getCaptureProfile(session)).toEqual(selected);
  await expect(bff.getCapabilities(session)).rejects.toThrow("capture_profile_invalid");
  expect(transport.mock.calls.at(-1)?.[0].operation).toEqual({ kind: "capabilities" });
  await bff.acknowledgeCaptureProfile(selected);
  selected.receipt_id = workspace; // The bound receipt must be a private snapshot.
  expect(await bff.getCapabilities(session)).toEqual(capabilities);
  expect(transport.mock.calls.at(-1)?.[0].operation).toEqual({ kind: "capabilities", profile_receipt_id: golden.receipt_id });
  await bff.reserveChunks(session, { protocol_version: "1.0", capture_lease_id: workspace,
    capture_lease_generation: 1, channel: "microphone", first_sequence_number: 270, count: 90 }, { idempotencyKey: "reserve-final-window" });
  expect(transport.mock.calls.at(-1)?.[0].operation).toMatchObject({ kind: "reserve_chunks", profile_receipt_id: golden.receipt_id });
  const calls = transport.mock.calls.length;
  expect(() => bff.reserveChunks(session, { protocol_version: "1.0", capture_lease_id: workspace,
    capture_lease_generation: 1, channel: "microphone", first_sequence_number: 271, count: 90 }, { idempotencyKey: "over-window" })).toThrow();
  await expect(bff.acknowledgeCaptureProfile({ ...golden, receipt_id: workspace })).rejects.toMatchObject({ code: "capture_profile_changed" });
  expect(transport).toHaveBeenCalledTimes(calls);
});

it("rejects foreign selection/recovery before transport and preserves strict legacy capabilities", async () => {
  const legacy = { ...capabilities, max_chunks: 1000, remaining_aggregate_plaintext_bytes: 67108864 };
  const transport = vi.fn<WorkspaceCaptureTransport>(async ({ operation }) => ({ workspace_id: workspace,
    session_id: session, operation: operation.kind, receipt: legacy }));
  const bff = new WorkspaceCaptureBff(workspace, session, transport);
  await expect(bff.selectCaptureProfile(workspace, golden.request, { idempotencyKey: "wrong-session" })).rejects.toMatchObject({ code: "capture_session_changed" });
  await expect(bff.getCaptureProfile(workspace)).rejects.toMatchObject({ code: "capture_session_changed" });
  expect(transport).not.toHaveBeenCalled();
  expect(await bff.getCapabilities(session)).toEqual(legacy);
  await bff.acknowledgeCaptureProfile(golden);
  await expect(bff.getCapabilities(session)).rejects.toThrow("capture_profile_invalid");
});


it("receives current Scribe capacity while keeping legacy and acknowledged profile budgets exact", async () => {
  let receipt = { ...capabilities, max_chunks: 2048, remaining_aggregate_plaintext_bytes: 402653184 };
  const transport = vi.fn<WorkspaceCaptureTransport>(async ({ operation }) => ({ workspace_id: workspace,
    session_id: session, operation: operation.kind, receipt }));
  const bff = new WorkspaceCaptureBff(workspace, session, transport);
  expect(await bff.getCapabilities(session)).toEqual(receipt);
  receipt = { ...receipt, max_chunks: 1000, remaining_aggregate_plaintext_bytes: 67108864 };
  expect(await bff.getCapabilities(session)).toEqual(receipt);
  for (const [max_chunks, remaining_aggregate_plaintext_bytes] of [
    [1000, 67108865], [2048, 402653185], [2049, 402653184], [720, 268435456],
  ]) {
    receipt = { ...receipt, max_chunks, remaining_aggregate_plaintext_bytes };
    await expect(bff.getCapabilities(session)).rejects.toThrow("capture_profile_invalid");
  }
  await bff.acknowledgeCaptureProfile(golden);
  receipt = { ...capabilities, max_chunks: 2048, remaining_aggregate_plaintext_bytes: 402653184 };
  await expect(bff.getCapabilities(session)).rejects.toThrow("capture_profile_invalid");
});
