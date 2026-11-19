import { webcrypto } from "node:crypto";
import { realpathSync } from "node:fs";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, expect, it } from "vitest";
import {
  desktopAudioRetentionEnabled,
  sweepDurablePrivateRecordingAudio,
} from "./durable-provider-records";
import { DurableDesktopRecordStore, type DesktopRecordNamespace } from "./durable-record-store";

const crypto = webcrypto as unknown as Crypto;
const recoveryScope = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const workspaceId = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const otherWorkspace = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
const id = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const RETENTION_MS = 48 * 60 * 60 * 1000;
const dirs: string[] = [];

afterEach(async () => {
  while (dirs.length) await rm(dirs.pop()!, { recursive: true, force: true });
});

async function openStore(workspace = workspaceId) {
  const directory = await mkdtemp(join(realpathSync(tmpdir()), "cosmas-audio-retention-"));
  dirs.push(directory);
  const key = await crypto.subtle.generateKey({ name: "AES-GCM", length: 256 }, false,
    ["encrypt", "decrypt", "wrapKey", "unwrapKey"]);
  const store = await DurableDesktopRecordStore.open({ directory, recoveryScope, workspaceId: workspace, key });
  return { store, records: store.namespace("private-recording") };
}

async function put(records: DesktopRecordNamespace, key: string, value: unknown) {
  const bytes = new TextEncoder().encode(JSON.stringify(value));
  try { await records.save(key, null, bytes); }
  finally { bytes.fill(0); }
}

function manifest(recordingId: string, endedAt: string, phase = "sealed", chunks = 1) {
  return {
    contract: "cosmabot.private-recording.v1",
    recordingId,
    phase,
    endedAt,
    updatedAt: endedAt,
    chunks: Array.from({ length: chunks }, (_, sequence) => ({ sequence })),
  };
}

async function seed(records: DesktopRecordNamespace, recordingId: string, endedAt: string, chunks = 1, phase = "sealed") {
  await put(records, `manifest:${recordingId}`, manifest(recordingId, endedAt, phase, chunks));
  for (let sequence = 0; sequence < chunks; sequence++) {
    await put(records, `chunk:${recordingId}:${sequence}`, { sequence, pcm: "synthetic-zero" });
  }
}

it("absent or unknown policy means no deletion", async () => {
  expect(desktopAudioRetentionEnabled(undefined)).toBe(false);
  expect(desktopAudioRetentionEnabled(null)).toBe(false);
  expect(desktopAudioRetentionEnabled({})).toBe(false);
  expect(desktopAudioRetentionEnabled({ enabled: "yes" })).toBe(false);
  expect(desktopAudioRetentionEnabled({ enabled: true })).toBe(true);
  const { store, records } = await openStore();
  const ended = "2026-11-01T00:00:00.000Z";
  await seed(records, id(1), ended);
  const result = await sweepDurablePrivateRecordingAudio({
    records, policy: { enabled: false }, now: () => Date.parse(ended) + RETENTION_MS,
  });
  expect(result.deleted).toEqual([]);
  expect(await records.get(`manifest:${id(1)}`)).not.toBeNull();
  store.close();
});

it("keeps Mac durable audio at 47:59:59 and deletes at 48:00:00", async () => {
  const { store, records } = await openStore();
  const ended = "2026-11-01T00:00:00.000Z", start = Date.parse(ended);
  await seed(records, id(2), ended, 2);
  const policy = { enabled: true, hours: 48 };
  expect((await sweepDurablePrivateRecordingAudio({
    records, policy, now: () => start + RETENTION_MS - 1,
  })).deleted).toEqual([]);
  expect((await sweepDurablePrivateRecordingAudio({
    records, policy, now: () => start + RETENTION_MS,
  })).deleted).toEqual([id(2)]);
  expect(await records.get(`manifest:${id(2)}`)).toBeNull();
  expect(await records.get(`chunk:${id(2)}:0`)).toBeNull();
  expect(await records.get(`chunk:${id(2)}:1`)).toBeNull();
  store.close();
});

it("finishes crash mid-delete on retry", async () => {
  const { store, records } = await openStore();
  const ended = "2026-11-01T00:00:00.000Z", start = Date.parse(ended);
  await seed(records, id(3), ended, 2);
  const first = await records.get(`chunk:${id(3)}:0`);
  expect(first).not.toBeNull();
  records.delete(`chunk:${id(3)}:0`, first!.revision);
  first!.data.fill(0);
  await sweepDurablePrivateRecordingAudio({
    records, policy: { enabled: true }, now: () => start + RETENTION_MS,
  });
  expect(await records.get(`manifest:${id(3)}`)).toBeNull();
  expect(await records.get(`chunk:${id(3)}:1`)).toBeNull();
  await sweepDurablePrivateRecordingAudio({
    records, policy: { enabled: true }, now: () => start + RETENTION_MS,
  });
  store.close();
});

it("seals in-progress at deadline then deletes", async () => {
  const { store, records } = await openStore();
  const ended = "2026-11-01T00:00:00.000Z", start = Date.parse(ended);
  await seed(records, id(4), ended, 1, "recording");
  let sealed = false;
  const result = await sweepDurablePrivateRecordingAudio({
    records, policy: { enabled: true }, now: () => start + RETENTION_MS,
    sealInProgress: async (recordingId) => {
      sealed = true;
      const next = manifest(recordingId, ended, "sealed", 1);
      const prior = await records.get(`manifest:${recordingId}`);
      const bytes = new TextEncoder().encode(JSON.stringify(next));
      try { await records.save(`manifest:${recordingId}`, prior!.revision, bytes); }
      finally { bytes.fill(0); prior?.data.fill(0); }
      return next;
    },
  });
  expect(sealed).toBe(true);
  expect(result.deleted).toEqual([id(4)]);
  store.close();
});

it("cross-scope isolation across durable workspaces", async () => {
  const a = await openStore(workspaceId);
  const b = await openStore(otherWorkspace);
  const ended = "2026-11-01T00:00:00.000Z", start = Date.parse(ended);
  await seed(a.records, id(5), ended);
  await seed(b.records, id(6), ended);
  await sweepDurablePrivateRecordingAudio({
    records: a.records, policy: { enabled: true }, now: () => start + RETENTION_MS,
  });
  expect(await a.records.get(`manifest:${id(5)}`)).toBeNull();
  expect(await b.records.get(`manifest:${id(6)}`)).not.toBeNull();
  a.store.close(); b.store.close();
});

it("ledger-like non-audio keys are not deleted", async () => {
  const { store, records } = await openStore();
  const ended = "2026-11-01T00:00:00.000Z", start = Date.parse(ended);
  await seed(records, id(7), ended);
  await put(records, `ledger:${id(7)}`, { kept: true, title: "Synthetic visit A" });
  await sweepDurablePrivateRecordingAudio({
    records, policy: { enabled: true }, now: () => start + RETENTION_MS,
  });
  const ledger = await records.get(`ledger:${id(7)}`);
  expect(ledger).not.toBeNull();
  expect(JSON.parse(new TextDecoder().decode(ledger!.data))).toEqual({ kept: true, title: "Synthetic visit A" });
  ledger!.data.fill(0);
  store.close();
});
