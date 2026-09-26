import { webcrypto } from "node:crypto";
import { IDBFactory } from "fake-indexeddb";
import { expect, it } from "vitest";
import { EncryptedIndexedDbFlowStore } from "./encrypted-store";
import { parseCaptureContinuity } from "../../../../scribe-review/creator-review-api";

const crypto = webcrypto as unknown as Crypto;
const sessionId = "11111111-1111-4111-8111-111111111111";

it("reopens the exact encrypted continuation after 1080 chunks and still rejects an oversized reservation", async () => {
  const options = { indexedDB: new IDBFactory(), databaseName: crypto.randomUUID(), crypto };
  let store = await EncryptedIndexedDbFlowStore.open(options);
  const lease = { protocol_version: "1.0" as const, receipt_id: crypto.randomUUID(),
    lease_id: crypto.randomUUID(), session_id: sessionId, generation: 12,
    issued_at: "2026-09-25T14:45:00.000Z", expires_at: "2026-09-25T15:00:00.000Z" };
  const active = { schemaVersion: 4 as const, sessionId, lease, reviewAfterUpload: true as const,
    captureAuthorizedUntil: lease.expires_at, aggregatePlaintextBudgetBytes: 402653184,
    phase: "paused" as const, completeIdempotencyKey: "long-visit-complete", recordedChunks: 1080,
    recordedPlaintextBytes: 345647520, startedAt: "2026-09-25T12:00:00.000Z",
    continuation: { prepared: false, firstSequenceNumber: 1080, reservationCount: 90,
      previousLease: lease, renewIdempotencyKey: "long-visit-renewal" } };
  await store.putActiveCaptureState(active); store.close();
  store = await EncryptedIndexedDbFlowStore.open(options);
  try {
    expect(await store.getActiveCaptureState()).toEqual(active);
    await expect(store.putActiveCaptureState({ ...active, recordedChunks: 2048,
      continuation: { ...active.continuation, firstSequenceNumber: 2048, reservationCount: 1 } }))
      .rejects.toThrow("invalid_active_capture_state");
  } finally { store.close(); }
});

it("reopens reviewed continuity beyond 1000 without discarding the interruption warning", () => {
  const value = { schema_version: "1.0", continuity: "interrupted_or_unconfirmed", missing_audio: "unknown",
    starts: [{ source_start_id: crypto.randomUUID(), first_sequence_number: 0 },
      { source_start_id: crypto.randomUUID(), first_sequence_number: 1080 }] };
  expect(parseCaptureContinuity(value)).toEqual(value);
  value.starts[1]!.first_sequence_number = 2048;
  expect(() => parseCaptureContinuity(value)).toThrow();
});
