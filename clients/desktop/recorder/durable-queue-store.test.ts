import { createHash, webcrypto } from "node:crypto";
import { realpathSync } from "node:fs";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, it, vi } from "vitest";
import { MAX_ENVELOPE_BYTES, base64UrlEncode, encodeChunkAdditionalDataBase64Url, encodeEnvelope } from "@cosmaneura-scribe/capture-protocol";
import { attachEncryptedEnvelope, captureChunkMetadata, createReservedRecord } from "../../capture/src/queue/records";
import type { CaptureChunkMetadata } from "../../capture/src/queue/types";
import { DurableDesktopQueueStorage } from "./durable-queue-store";
import { DurableDesktopRecordStore } from "./durable-record-store";

const crypto = webcrypto as unknown as Crypto;
const recoveryScope = "11111111-1111-4111-8111-111111111111";
const workspaceId = "22222222-2222-4222-8222-222222222222";
const sessionId = "33333333-3333-4333-8333-333333333333";

it("reopens encrypted queue metadata without bulk payloads and clears scan buffers on early exit", async () => {
  const directory = await mkdtemp(join(realpathSync(tmpdir()), "cosmas-bounded-queue-"));
  const key = await crypto.subtle.generateKey({ name: "AES-GCM", length: 256 }, false,
    ["encrypt", "decrypt", "wrapKey", "unwrapKey"]);
  const options = { directory, recoveryScope, workspaceId, key };
  let store = await DurableDesktopRecordStore.open(options);
  try {
    let records = store.namespace("queue"), storage = new DurableDesktopQueueStorage(records, sessionId);
    const header = { schema_version: "1.0" as const, content_encryption: "A256GCM" as const,
      nonce: base64UrlEncode(new Uint8Array(12)), media_type: "audio/wav" as const };
    const overhead = encodeEnvelope(header, new Uint8Array(16)).length - 16;
    const envelope = encodeEnvelope(header, new Uint8Array(MAX_ENVELOPE_BYTES - overhead).fill(9));
    const sha256 = createHash("sha256").update(envelope).digest("hex");
    const expected: CaptureChunkMetadata[] = [];
    for (const sequenceNumber of [2, 0, 1]) {
      const objectId = crypto.randomUUID();
      const reserved = createReservedRecord({ protocolVersion: "1.0", objectId, sessionId,
        channel: "microphone", sequenceNumber, createdAt: "2026-09-25T12:00:00.000Z",
        additionalAuthenticatedData: encodeChunkAdditionalDataBase64Url({ tenantId: workspaceId,
          sessionId, objectId, sequenceNumber, channel: "microphone" }) },
      { reservation: "synthetic-reserve", uploadAuthorization: "synthetic-upload",
        uploadAuthorizationGeneration: 1, registration: "synthetic-register" });
      await storage.create(reserved);
      const encrypted = attachEncryptedEnvelope(reserved, envelope, sha256);
      await storage.compareAndSwap(objectId, 1, encrypted);
      expected.push(captureChunkMetadata(encrypted));
    }
    store.close(); store = await DurableDesktopRecordStore.open(options);
    records = store.namespace("queue"); storage = new DurableDesktopQueueStorage(records, sessionId);
    const bulk = vi.spyOn(records, "list").mockRejectedValue(new Error("bulk audio enumeration forbidden"));
    expect(await storage.listMetadata()).toEqual(expected.sort((a, b) => a.reservation.sequenceNumber - b.reservation.sequenceNumber));
    expect(bulk).not.toHaveBeenCalled();
    const scan = records.scan(), first = await scan.next();
    if (first.done) throw new Error("missing retained record");
    const buffer = first.value.data;
    expect(buffer.some(byte => byte !== 0)).toBe(true);
    await scan.return(undefined);
    expect(buffer.every(byte => byte === 0)).toBe(true);
    const retained = await storage.get(expected[0]!.reservation.objectId);
    if (!retained || !("envelope" in retained)) throw new Error("missing retained envelope");
    expect(retained.envelope).toEqual(envelope);
    const interrupted = records.scan(), opened = await interrupted.next();
    if (opened.done) throw new Error("missing retained record");
    store.close();
    await expect(interrupted.next()).rejects.toThrow("desktop_storage_unavailable");
    expect(opened.value.data.every(byte => byte === 0)).toBe(true);
  } finally { store.close(); await rm(directory, { recursive: true, force: true }); }
});
