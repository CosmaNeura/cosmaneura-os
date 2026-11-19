import { webcrypto } from "node:crypto";
import { realpathSync } from "node:fs";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, expect, it } from "vitest";
import {
  clearPrivateRecordingScopeKeys,
  desktopAudioRetentionEnabled,
  normalizeDesktopAudioRetentionPolicy,
  sweepDurablePrivateRecordingAudio,
} from "./durable-provider-records";
import { DurableDesktopRecordStore, type DesktopRecordNamespace } from "./durable-record-store";
import { DesktopProviderRecorderIpc } from "./provider-recorder-ipc";
import type { DesktopProviderRecorder } from "./provider-recorder";

const crypto = webcrypto as unknown as Crypto;
const recoveryScope = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const workspaceId = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const otherWorkspace = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
const id = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const RETENTION_MS = 48 * 60 * 60 * 1000;
const enabledAt = "2026-10-01T00:00:00.000Z";
const on = { enabled: true as const, enabledAt };
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
  expect(normalizeDesktopAudioRetentionPolicy(undefined)).toBeNull();
  expect(normalizeDesktopAudioRetentionPolicy({ enabled: "yes" })).toEqual({ enabled: false });
  expect(desktopAudioRetentionEnabled(undefined)).toBe(false);
  expect(desktopAudioRetentionEnabled({ enabled: true })).toBe(true);
  const { store, records } = await openStore();
  const ended = "2026-11-01T00:00:00.000Z";
  await seed(records, id(1), ended);
  expect((await sweepDurablePrivateRecordingAudio({
    records, policy: { enabled: true }, now: () => Date.parse(ended) + RETENTION_MS,
  })).deleted).toEqual([]); // enabled without enabledAt → OFF
  expect(await records.get(`manifest:${id(1)}`)).not.toBeNull();
  store.close();
});

it("keeps Mac durable audio at 47:59:59 and deletes at 48:00:00", async () => {
  const { store, records } = await openStore();
  const ended = "2026-11-01T00:00:00.000Z", start = Date.parse(ended);
  await seed(records, id(2), ended, 2);
  expect((await sweepDurablePrivateRecordingAudio({
    records, policy: { ...on, hours: 1 }, now: () => start + RETENTION_MS - 1,
  })).deleted).toEqual([]); // renderer hours ignored
  expect((await sweepDurablePrivateRecordingAudio({
    records, policy: on, now: () => start + RETENTION_MS,
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
    records, policy: on, now: () => start + RETENTION_MS,
  });
  expect(await records.get(`manifest:${id(3)}`)).toBeNull();
  expect(await records.get(`chunk:${id(3)}:1`)).toBeNull();
  await sweepDurablePrivateRecordingAudio({
    records, policy: on, now: () => start + RETENTION_MS,
  });
  store.close();
});

it("seals in-progress at deadline then deletes; skips when seal fails", async () => {
  const { store, records } = await openStore();
  const ended = "2026-11-01T00:00:00.000Z", start = Date.parse(ended);
  await seed(records, id(4), ended, 1, "recording");
  expect((await sweepDurablePrivateRecordingAudio({
    records, policy: on, now: () => start + RETENTION_MS, sealInProgress: async () => null,
  })).deleted).toEqual([]);
  let sealed = false;
  const result = await sweepDurablePrivateRecordingAudio({
    records, policy: on, now: () => start + RETENTION_MS,
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
    records: a.records, policy: on, now: () => start + RETENTION_MS,
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
    records, policy: on, now: () => start + RETENTION_MS,
  });
  const ledger = await records.get(`ledger:${id(7)}`);
  expect(ledger).not.toBeNull();
  expect(JSON.parse(new TextDecoder().decode(ledger!.data))).toEqual({ kept: true, title: "Synthetic visit A" });
  ledger!.data.fill(0);
  store.close();
});

function ipcHarness(recorder: DesktopProviderRecorder) {
  let handler: (e: unknown, v: unknown) => Promise<unknown> = async () => { throw new Error("unset"); };
  const frame = { url: "app://cosmas/index.html" };
  const bridge = new DesktopProviderRecorderIpc(
    { handle(_c: string, h: typeof handler) { handler = h; }, removeHandler() {} } as never,
    { id: 1, mainFrame: frame, isDestroyed: () => false, send() {}, on() {}, removeListener() {} } as never,
    recorder,
  );
  bridge.install();
  const event = { sender: { id: 1, mainFrame: frame }, senderFrame: frame };
  const request = (value: unknown) => handler(event, value);
  const read = (extra: Record<string, unknown> = {}) =>
    request({ kind: "read", requestId: id(91), recorderId: null, ...extra });
  return {
    bridge,
    read,
    request,
    async deactivateRequest() {
      const state = (await read()) as { state: { recorderId: string } };
      return request({ kind: "deactivate", requestId: id(92), recorderId: state.state.recorderId });
    },
  };
}

const idleSnapshot = {
  state: "ready", statusCode: "ready", sessionId: id(90), recordedChunks: 0, queuedChunks: 0,
  elapsedSeconds: 0, remainingBudgetSeconds: null, remainingAuthoritySeconds: null,
  transcriptionStatus: null, transcript: null,
  desktop: { phase: "ready", coverage: "not_started", trimmedStartMs: 0, trimmedEndMs: null },
};

it("poison/cutover/wipe + IPC fetch authority (ok=true when sweep throws)", async () => {
  const { store, records } = await openStore();
  const ended = "2026-11-01T00:00:00.000Z", start = Date.parse(ended), flip = "2026-11-01T00:00:00.000Z";
  await put(records, `manifest:${id(19)}`, { recordingId: id(19), updatedAt: "bad", phase: "sealed", chunks: [] });
  await seed(records, id(20), ended);
  const failures: string[] = [];
  await sweepDurablePrivateRecordingAudio({
    records, policy: on, now: () => start + RETENTION_MS,
    recordFailure: (rid) => { failures.push(rid); },
  });
  expect(failures).toEqual([id(19)]);
  await seed(records, id(21), "2026-10-15T00:00:00.000Z");
  const cutover = { enabled: true as const, enabledAt: flip };
  expect((await sweepDurablePrivateRecordingAudio({
    records, policy: cutover, now: () => Date.parse(flip) + RETENTION_MS - 1,
  })).deleted).toEqual([]);
  await sweepDurablePrivateRecordingAudio({
    records, policy: cutover, now: () => Date.parse(flip) + RETENTION_MS,
  });
  expect(await records.get(`manifest:${id(21)}`)).toBeNull();
  await put(records, `ledger:${id(20)}`, { kept: true });
  await put(records, `private-transcript:${id(20)}`, { working: "Synthetic notes" });
  await put(records, `audio-tombstone:${id(20)}`, { outcome: "deleted" });
  await put(records, `display-title:${id(20)}`, { title: "Synthetic visit" });
  await put(records, `visit-binding:${id(20)}`, { kept: true });
  await clearPrivateRecordingScopeKeys(records);
  expect((await records.list()).length).toBe(0);

  await seed(records, id(8), ended);
  const fetchSweep = async (fetch: () => Promise<unknown>) => {
    let policy;
    try { policy = normalizeDesktopAudioRetentionPolicy(await fetch()); }
    catch { policy = { enabled: false }; }
    return sweepDurablePrivateRecordingAudio({ records, policy, now: () => start + RETENTION_MS });
  };
  expect((await fetchSweep(async () => null)).deleted).toEqual([]);
  let fetchPolicy: () => Promise<unknown> = async () => ({ enabled: false }), sweepThrows = false;
  const recorder = {
    availableForView: true, get snapshot() { return idleSnapshot; },
    subscribe(l: (v: unknown) => void) { l(idleSnapshot); return () => undefined; },
    async sweepExpiredAudio() {
      if (sweepThrows) throw new Error("sweep failed");
      return fetchSweep(fetchPolicy);
    },
    async deactivate() {},
  } as unknown as DesktopProviderRecorder;
  const { bridge, read } = ipcHarness(recorder);
  expect(((await read({ audioRetention: { enabled: true, hours: 1, enabledAt } })) as { ok: boolean }).ok).toBe(true);
  expect(await records.get(`manifest:${id(8)}`)).not.toBeNull();
  fetchPolicy = async () => on;
  expect(((await read()) as { ok: boolean }).ok).toBe(true);
  expect(await records.get(`manifest:${id(8)}`)).toBeNull();
  await seed(records, id(10), ended); sweepThrows = true;
  // Sweep failure must never set ok=false on read.
  expect(((await read()) as { ok: boolean }).ok).toBe(true);
  await bridge.dispose(); store.close();
});

it("deactivate calls deactivate before sweep", async () => {
  const order: string[] = [];
  const recorder = {
    availableForView: true, get snapshot() { return idleSnapshot; },
    subscribe(l: (v: unknown) => void) { l(idleSnapshot); return () => undefined; },
    async sweepExpiredAudio() { order.push("sweep"); return { deleted: [], inspected: 0 }; },
    async deactivate() { order.push("deactivate"); },
  } as unknown as DesktopProviderRecorder;
  const { bridge, read, request } = ipcHarness(recorder);
  const state = (await read()) as { state: { recorderId: string } };
  order.length = 0; // ignore preliminary read sweep
  expect(((await request({
    kind: "deactivate", requestId: id(93), recorderId: state.state.recorderId,
  })) as { ok: boolean }).ok).toBe(true);
  expect(order).toEqual(["deactivate", "sweep"]);
  await bridge.dispose();
});

it("deactivate succeeds (ok true) even when sweep throws", async () => {
  let deactivated = false;
  const recorder = {
    availableForView: true, get snapshot() { return idleSnapshot; },
    subscribe(l: (v: unknown) => void) { l(idleSnapshot); return () => undefined; },
    async sweepExpiredAudio() { throw new Error("sweep failed"); },
    async deactivate() { deactivated = true; },
  } as unknown as DesktopProviderRecorder;
  const { bridge, deactivateRequest } = ipcHarness(recorder);
  const result = await deactivateRequest() as { ok: boolean };
  expect(deactivated).toBe(true);
  expect(result.ok).toBe(true);
  await bridge.dispose();
});

it("read ok true when sweep throws", async () => {
  const recorder = {
    availableForView: true, get snapshot() { return idleSnapshot; },
    subscribe(l: (v: unknown) => void) { l(idleSnapshot); return () => undefined; },
    async sweepExpiredAudio() { throw new Error("sweep failed"); },
    async deactivate() {},
  } as unknown as DesktopProviderRecorder;
  const { bridge, read } = ipcHarness(recorder);
  expect(((await read()) as { ok: boolean }).ok).toBe(true);
  await bridge.dispose();
});

it("with policy off, deactivate behaves (ok true, deactivate called)", async () => {
  let deactivated = false;
  let swept = false;
  const recorder = {
    availableForView: true, get snapshot() { return idleSnapshot; },
    subscribe(l: (v: unknown) => void) { l(idleSnapshot); return () => undefined; },
    async sweepExpiredAudio() {
      swept = true;
      return { deleted: [], inspected: 0 };
    },
    async deactivate() { deactivated = true; },
  } as unknown as DesktopProviderRecorder;
  const { bridge, deactivateRequest } = ipcHarness(recorder);
  const result = await deactivateRequest() as { ok: boolean };
  expect(deactivated).toBe(true);
  expect(swept).toBe(true);
  expect(result.ok).toBe(true);
  await bridge.dispose();
});
