import { readFileSync } from "node:fs";
import { MAX_CHUNKS } from "@cosmaneura-scribe/capture-protocol";
import { describe, expect, it } from "vitest";
import { assertCaptureRecoveryRequest, recoveryRequestHash, validateRecoveryReceipt, validateRecoveryState,
  type CaptureRecoveryReceipt, type CaptureRecoveryRequest } from "./recovery-contracts";
import { captureRecoveryHash, validateCaptureSource, type CaptureSourceEnvelope } from "./source-contracts";
import { workingHash } from "./working-contracts";

const fixture = JSON.parse(readFileSync(new URL("../../../../tests/fixtures/capture_recovery.json", import.meta.url), "utf8")) as {
  request: CaptureRecoveryRequest; receipt: CaptureRecoveryReceipt;
};
const sourceFixture = JSON.parse(readFileSync(new URL("../../../../tests/fixtures/capture_source.json", import.meta.url), "utf8")) as {
  base: CaptureSourceEnvelope;
};
const now = new Date("2026-09-17T20:00:00Z");

async function longSource() {
  const source = structuredClone(sourceFixture.base);
  const first = source.recovery_history.recoveries[0]!;
  first.request.next_sequence_number = 1080;
  const second = structuredClone(first);
  second.receipt_id = crypto.randomUUID();
  second.request = { ...first.request, segment_id: first.following_segment_id!, gap_id: crypto.randomUUID(),
    segment_ordinal: 1, first_sequence_number: 1080, next_sequence_number: MAX_CHUNKS,
    segment_started_at: first.request.acknowledged_at, capture_lease_generation: first.lease.generation,
    decision: "finish_capture" };
  second.following_segment_id = null;
  second.lease = { ...first.lease, receipt_id: crypto.randomUUID(), generation: first.lease.generation + 1 };
  source.recovery_history.recoveries.push(second);
  await sealHistory(source);
  return source;
}
async function sealHistory(source: CaptureSourceEnvelope) {
  for (const receipt of source.recovery_history.recoveries) receipt.request_sha256 = await recoveryRequestHash(receipt.request);
  source.recovery_sha256 = await captureRecoveryHash(source.recovery_history);
  source.source_sha256 = await workingHash({ raw_transcript_sha256: source.working_transcript.raw_transcript_sha256,
    working_sha256: source.working_transcript.working_sha256, recovery_sha256: source.recovery_sha256 });
}

describe("current Scribe recovery sequence boundaries", () => {
  it.each([
    [0, 1001, "resume_capture"],
    [1000, 1080, "resume_capture"],
    [MAX_CHUNKS - 1, MAX_CHUNKS - 1, "resume_capture"],
    [MAX_CHUNKS - 1, MAX_CHUNKS, "finish_capture"],
  ] as const)("accepts first %s / next %s / %s without changing the segment bound", (first, next, decision) => {
    const request = { ...fixture.request, first_sequence_number: first, next_sequence_number: next,
      decision, segment_ordinal: 999 };
    expect(() => assertCaptureRecoveryRequest(request)).not.toThrow();
  });
  it.each([
    { next_sequence_number: MAX_CHUNKS + 1 },
    { first_sequence_number: MAX_CHUNKS, next_sequence_number: MAX_CHUNKS, decision: "finish_capture" },
    { next_sequence_number: MAX_CHUNKS, decision: "resume_capture" },
    { next_sequence_number: 0, decision: "finish_capture" },
    { first_sequence_number: 1000, next_sequence_number: 999 },
    { segment_ordinal: 1000 },
    { next_sequence_number: true },
    { first_sequence_number: -1 },
  ])("rejects out-of-range, unordered or noninteger request %j", changes => {
    expect(() => assertCaptureRecoveryRequest({ ...fixture.request, ...changes })).toThrow();
  });
  it("accepts a long receipt and history while preserving exact request binding", async () => {
    const receipt = structuredClone(fixture.receipt);
    receipt.request.next_sequence_number = 1080;
    receipt.request_sha256 = await recoveryRequestHash(receipt.request);
    expect(await validateRecoveryReceipt(receipt, receipt.session_id, now, receipt.request)).toEqual(receipt);
    const state = { history: { session_id: receipt.session_id, recoveries: [receipt] },
      current_lease: receipt.lease, lease_closed: false, session_status: "capturing" };
    expect(await validateRecoveryState(state, receipt.session_id, now)).toEqual(state);
    await expect(validateRecoveryReceipt(receipt, receipt.session_id, now,
      { ...receipt.request, next_sequence_number: 1081 })).rejects.toThrow();
  });
  it("opens a long qualified source with a later segment and retains gap review at the final boundary", async () => {
    const source = await longSource();
    expect(await validateCaptureSource(source, source.session_id, now)).toEqual(source);
    expect(source.recovery_history.recoveries[1]!.request.first_sequence_number).toBe(1080);
    expect(source.recovery_history.recoveries[1]!.request.next_sequence_number).toBe(MAX_CHUNKS);
    expect(source.capture_incomplete).toBe(true);
    expect(source.recovery_history.recoveries.map(receipt => receipt.review_state)).toEqual(["required", "required"]);
  });
  it.each(["predecessor", "actor", "session"] as const)("rejects rehashed long-source %s scope changes", async fault => {
    const source = await longSource(), second = source.recovery_history.recoveries[1]!;
    if (fault === "predecessor") second.request.first_sequence_number = 1079;
    if (fault === "actor") second.acknowledged_by_practitioner_id = "invented_other_practitioner";
    if (fault === "session") second.session_id = crypto.randomUUID();
    await sealHistory(source);
    await expect(validateCaptureSource(source, source.session_id, now)).rejects.toThrow();
  });
});
