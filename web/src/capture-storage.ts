import { EncryptedIndexedDbQueueStorage } from "../../clients/capture/src/storage/encrypted-indexeddb";
import { NativePluginQueueStorage, type NativeQueuePlugin } from "../../clients/capture/src/storage/native-plugin";
import { QueueInvariantError } from "../../clients/capture/src/queue/errors";
import type { CaptureQueueStorage } from "../../clients/capture/src/queue/types";
import type { EncryptedIndexedDbFlowStore } from "../../clients/capture/src/flow/encrypted-store";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u;
const validId = (id: string) => {
  if (!UUID.test(id)) throw new QueueInvariantError("native_queue_scope_invalid");
  return id;
};

export async function bindCaptureQueueStorage(flow: EncryptedIndexedDbFlowStore, workspaceId: string,
  sessionId: string, native: boolean, hasLegacyFlow: boolean): Promise<void> {
  const desired = native ? "native" : "browser";
  const previous = await flow.getQueueStorageKind(sessionId);
  if (previous && previous !== desired) throw new QueueInvariantError("queue_storage_profile_changed");
  if (native && previous === null) {
    if (hasLegacyFlow) throw new QueueInvariantError("queue_storage_profile_changed");
    const browser = await EncryptedIndexedDbQueueStorage.open({databaseName: `cosmas-capture-queue:${workspaceId}`});
    try {
      if ((await browser.list()).some(record => record.reservation.sessionId === sessionId && record.state !== "purged")) {
        throw new QueueInvariantError("queue_storage_profile_changed");
      }
    } finally { browser.close(); }
  }
  await flow.claimQueueStorageKind(sessionId, desired);
}

/** Select before opening a store. Native failure never falls back to browser custody. */
export async function openCaptureQueueStorage(workspaceId: string, sessionId: string, native: boolean,
  // Capacitor's proxy manufactures a `then` method. Keep it inside a plain
  // object so Promise resolution never mistakes the plugin for a thenable.
  loadNative: () => Promise<{plugin: NativeQueuePlugin}> = async () =>
    ({plugin: (await import("../../clients/capture/plugins/secure-queue")).SecureQueue}),
): Promise<{storage: CaptureQueueStorage; kind: "native" | "browser"; close: () => void}> {
  validId(workspaceId); validId(sessionId);
  if (!native) {
    const storage = await EncryptedIndexedDbQueueStorage.open({databaseName: `cosmas-capture-queue:${workspaceId}`});
    return {storage, kind: "browser", close: () => storage.close()};
  }
  try {
    const {plugin} = await loadNative();
    const storage = new NativePluginQueueStorage(scopedNativePlugin(plugin, workspaceId, sessionId), sessionId);
    await storage.list(); // Verify plugin availability and retained record integrity before capture.
    return {storage, kind: "native", close: () => undefined};
  } catch (error) {
    if (error instanceof QueueInvariantError) throw error;
    throw new QueueInvariantError("native_queue_unavailable");
  }
}

/** Native keys include private workspace/session scope. Foreign records are never fetched. */
export function scopedNativePlugin(plugin: NativeQueuePlugin, workspaceId: string, sessionId: string): NativeQueuePlugin {
  const prefix = `cosmas-queue:v1:${validId(workspaceId)}:${validId(sessionId)}:`;
  const key = (id: string) => prefix + validId(id);
  return {
    create: record => plugin.create({...record, key: key(record.key)}),
    compareAndSwap: record => plugin.compareAndSwap({...record, key: key(record.key)}),
    get: async record => {
      const result = await plugin.get({key: key(record.key)});
      if (result.key !== key(record.key)) throw new QueueInvariantError("native_queue_scope_invalid");
      return {...result, key: record.key};
    },
    list: async () => {
      const result = await plugin.list();
      if (!Array.isArray(result.keys) || result.keys.some(value => typeof value !== "string")) {
        throw new QueueInvariantError("native_queue_scope_invalid");
      }
      const keys = result.keys.filter(value => value.startsWith(prefix)).map(value => validId(value.slice(prefix.length)));
      if (new Set(keys).size !== keys.length) throw new QueueInvariantError("native_queue_scope_invalid");
      return {keys};
    },
  };
}
