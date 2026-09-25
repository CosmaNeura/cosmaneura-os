import { webcrypto } from "node:crypto";
import { IDBFactory } from "fake-indexeddb";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { encodeChunkAdditionalDataBase64Url } from "@cosmaneura-scribe/capture-protocol";
import { bindCaptureQueueStorage, openCaptureQueueStorage, scopedNativePlugin } from "../../../../web/src/capture-storage";
import { MemoryNativeQueuePlugin } from "../../test-fixtures/native-queue";
import { EncryptedIndexedDbFlowStore } from "../flow/encrypted-store";
import { createReservedRecord } from "../queue/records";
import { encodeCaptureRecord } from "./record-codec";

const workspace = "00000000-0000-4000-8000-000000000001";
const session = "00000000-0000-4000-8000-000000000002";
const objectId = "00000000-0000-4000-8000-000000000003";
const other = "00000000-0000-4000-8000-000000000004";
const crypto = webcrypto as unknown as Crypto;
const closers: (() => void)[] = [];
beforeEach(() => { vi.stubGlobal("indexedDB", new IDBFactory()); vi.stubGlobal("crypto", crypto); });
afterEach(() => { closers.splice(0).forEach(close => close()); vi.unstubAllGlobals(); });

function record(sid = session) {
  return createReservedRecord({protocolVersion:"1.0", objectId, sessionId:sid, channel:"microphone",
    sequenceNumber:0, createdAt:"2026-09-17T00:00:00.000Z",
    additionalAuthenticatedData:encodeChunkAdditionalDataBase64Url({tenantId:workspace, sessionId:sid,
      objectId, channel:"microphone",sequenceNumber:0})},
    {reservation:"reserved-key",uploadAuthorization:"upload-key",uploadAuthorizationGeneration:1,registration:"register-key"});
}
async function flow() {
  const result = await EncryptedIndexedDbFlowStore.open({databaseName:crypto.randomUUID()});
  closers.push(() => result.close()); return result;
}

describe("OS native queue binding", () => {
  it("does not assimilate Capacitor's synthetic then method while loading its proxy", async () => {
    let thenReads=0;
    const plugin=new Proxy(new MemoryNativeQueuePlugin(), {get(target,key,receiver) {
      if (key === "then") { thenReads++; throw new Error("Capacitor plugin must not be awaited"); }
      return Reflect.get(target,key,receiver);
    }});
    const result=await openCaptureQueueStorage(workspace,session,true,async () => ({plugin}));
    expect(result.kind).toBe("native"); expect(thenReads).toBe(0);
  });

  it("isolates workspaces and sessions before fetching or decoding native records", async () => {
    const plugin = new MemoryNativeQueuePlugin();
    const a = await openCaptureQueueStorage(workspace, session, true, async () => ({plugin}));
    const b = await openCaptureQueueStorage(other, session, true, async () => ({plugin}));
    const c = await openCaptureQueueStorage(workspace, other, true, async () => ({plugin}));
    expect(a.kind).toBe("native");
    expect(await a.storage.create(record())).toBe(true);
    expect(await b.storage.create(record())).toBe(true);
    expect(await c.storage.create(record(other))).toBe(true);
    expect(plugin.records.size).toBe(3);
    plugin.reads.length = 0;
    expect(await a.storage.list()).toEqual([record()]);
    expect(plugin.reads).toEqual([`cosmas-queue:v1:${workspace}:${session}:${objectId}`]);
    expect(await a.storage.get(other)).toBeNull();
  });

  it("recovers duplicate creates and allows only one concurrent CAS successor", async () => {
    const plugin = new MemoryNativeQueuePlugin();
    const a = (await openCaptureQueueStorage(workspace, session, true, async () => ({plugin}))).storage;
    await a.create(record());
    const b = (await openCaptureQueueStorage(workspace, session, true, async () => ({plugin}))).storage;
    expect(await b.create(record())).toBe(false);
    const replacement = {...record(), revision:2};
    expect((await Promise.all([a.compareAndSwap(objectId,1,replacement),b.compareAndSwap(objectId,1,replacement)])).sort()).toEqual([false,true]);
    expect((await b.get(objectId))?.revision).toBe(2);
  });

  it("rejects foreign decoded sessions on writes, reads and CAS without replacing the stored record", async () => {
    const plugin = new MemoryNativeQueuePlugin();
    const {storage} = await openCaptureQueueStorage(workspace, session, true, async () => ({plugin}));
    await expect(storage.create(record(other))).rejects.toMatchObject({code:"native_queue_session_mismatch"});
    await storage.create(record());
    const key = [...plugin.records.keys()][0];
    const corrupt = {...plugin.records.get(key)!, data:Buffer.from(encodeCaptureRecord(record(other))).toString("base64")};
    plugin.records.set(key, corrupt);
    await expect(storage.get(objectId)).rejects.toMatchObject({code:"native_queue_session_mismatch"});
    await expect(storage.list()).rejects.toMatchObject({code:"native_queue_session_mismatch"});
    await expect(storage.compareAndSwap(objectId,1,{...record(),revision:2})).rejects.toMatchObject({code:"native_queue_session_mismatch"});
    expect(plugin.records.get(key)).toEqual(corrupt);
  });

  it("does not fall back to IndexedDB when the native plugin is unavailable", async () => {
    await expect(openCaptureQueueStorage(workspace,session,true,async () => { throw new Error("private plugin detail"); }))
      .rejects.toMatchObject({code:"native_queue_unavailable",message:"native_queue_unavailable"});
    expect(await indexedDB.databases()).toEqual([]);
  });

  it("rejects malformed native scope responses", async () => {
    const plugin = new MemoryNativeQueuePlugin();
    const scoped = scopedNativePlugin(plugin,workspace,session);
    plugin.list = async () => ({keys:[`cosmas-queue:v1:${workspace}:${session}:../foreign`]});
    await expect(scoped.list()).rejects.toMatchObject({code:"native_queue_scope_invalid"});
    expect(plugin.reads).toEqual([]);
  });

  it("retains legacy browser records instead of silently switching their custody", async () => {
    const old = await openCaptureQueueStorage(workspace,session,false); closers.push(old.close);
    await old.storage.create(record());
    const state = await flow();
    await expect(bindCaptureQueueStorage(state,workspace,session,true,false)).rejects.toMatchObject({code:"queue_storage_profile_changed"});
    expect(await state.getQueueStorageKind(session)).toBeNull();
    expect(await old.storage.get(objectId)).toEqual(record());
    await bindCaptureQueueStorage(state,workspace,session,false,true);
    expect(await state.getQueueStorageKind(session)).toBe("browser");
  });

  it("refuses native selection when unmarked legacy flow state survives", async () => {
    const state = await flow();
    await expect(bindCaptureQueueStorage(state,workspace,session,true,true)).rejects.toMatchObject({code:"queue_storage_profile_changed"});
    expect(await state.getQueueStorageKind(session)).toBeNull();
  });

  it("persists queue selection across close/reopen and requires the same profile", async () => {
    const name=crypto.randomUUID();
    let state = await EncryptedIndexedDbFlowStore.open({databaseName:name});
    await bindCaptureQueueStorage(state,workspace,session,true,false); state.close();
    state = await EncryptedIndexedDbFlowStore.open({databaseName:name}); closers.push(() => state.close());
    expect(await state.getQueueStorageKind(session)).toBe("native");
    await expect(bindCaptureQueueStorage(state,workspace,session,false,false)).rejects.toMatchObject({code:"queue_storage_profile_changed"});
    await state.releaseQueueStorageKind(session,"browser");
    expect(await state.getQueueStorageKind(session)).toBe("native");
    await state.releaseQueueStorageKind(session,"native");
    expect(await state.getQueueStorageKind(session)).toBeNull();
  });

  it("atomically admits one storage profile across concurrent handles", async () => {
    const name=crypto.randomUUID();
    const a=await EncryptedIndexedDbFlowStore.open({databaseName:name}); closers.push(() => a.close());
    const b=await EncryptedIndexedDbFlowStore.open({databaseName:name}); closers.push(() => b.close());
    const results=await Promise.allSettled([a.claimQueueStorageKind(session,"native"),b.claimQueueStorageKind(session,"browser")]);
    expect(results.map(r => r.status).sort()).toEqual(["fulfilled","rejected"]);
    expect(await a.getQueueStorageKind(session)).toBe(await b.getQueueStorageKind(session));
  });
});
