import type { SecureQueuePlugin } from "@cosmaneura-scribe/capacitor-secure-queue";
import {
  base64UrlDecode,
  base64UrlEncode,
} from "@cosmaneura-scribe/capture-protocol";

import { QueueInvariantError } from "../queue/errors";
import { assertSafeCaptureRecord, captureChunkMetadata } from "../queue/records";
import type {
  CaptureChunkRecord,
  CaptureChunkMetadata,
  CaptureQueueStorage,
  ReservedChunkRecord,
} from "../queue/types";
import { decodeCaptureRecord, encodeCaptureRecord } from "./record-codec";

const ALREADY_EXISTS = "SECURE_QUEUE_ALREADY_EXISTS";
const REVISION_CONFLICT = "SECURE_QUEUE_REVISION_CONFLICT";
const NOT_FOUND = "SECURE_QUEUE_NOT_FOUND";
export type NativeQueuePlugin = Pick<SecureQueuePlugin, "create" | "get" | "list" | "compareAndSwap">;

/**
 * Maps the durable queue contract onto the custom Capacitor secure-queue
 * plugin. Native revisions remain opaque strings; JS record revisions are
 * separately verified before the plugin's atomic compare-and-swap.
 */
export class NativePluginQueueStorage implements CaptureQueueStorage {
  readonly #plugin: NativeQueuePlugin;
  readonly #sessionId: string | undefined;

  constructor(plugin: NativeQueuePlugin, sessionId?: string) {
    this.#plugin = plugin;
    this.#sessionId = sessionId;
  }

  async create(record: ReservedChunkRecord): Promise<boolean> {
    assertSafeCaptureRecord(record);
    this.#assertSession(record);
    try {
      const result = await this.#plugin.create(toNativeRecord(record));
      assertNativeRevision(result.revision);
      return true;
    } catch (error) {
      if (hasPluginCode(error, ALREADY_EXISTS)) return false;
      throw error;
    }
  }

  async get(objectId: string): Promise<CaptureChunkRecord | null> {
    try {
      const value = await this.#plugin.get({ key: objectId });
      const record = fromNativeRecord(objectId, value.key, value.data, value.revision);
      this.#assertSession(record);
      return record;
    } catch (error) {
      if (hasPluginCode(error, NOT_FOUND)) return null;
      throw error;
    }
  }

  async list(): Promise<readonly CaptureChunkRecord[]> {
    const records: CaptureChunkRecord[] = [];
    for await (const record of this.#scan()) records.push(record);
    return records;
  }

  async listMetadata(): Promise<readonly CaptureChunkMetadata[]> {
    const records: CaptureChunkMetadata[] = [];
    for await (const record of this.#scan()) records.push(captureChunkMetadata(record));
    return records;
  }

  async *#scan(): AsyncGenerator<CaptureChunkRecord> {
    const result = await this.#plugin.list();
    for (const objectId of result.keys) {
      const value = await this.#plugin.get({ key: objectId });
      const record = fromNativeRecord(objectId, value.key, value.data, value.revision);
      this.#assertSession(record);
      yield record;
    }
  }

  async compareAndSwap(
    objectId: string,
    expectedRevision: number,
    replacement: CaptureChunkRecord,
  ): Promise<boolean> {
    assertSafeCaptureRecord(replacement);
    this.#assertSession(replacement);
    if (
      replacement.reservation.objectId !== objectId ||
      replacement.revision !== expectedRevision + 1
    ) {
      throw new QueueInvariantError("invalid_compare_and_swap");
    }

    let current;
    try {
      current = await this.#plugin.get({ key: objectId });
    } catch (error) {
      if (hasPluginCode(error, NOT_FOUND)) return false;
      throw error;
    }
    assertNativeRevision(current.revision);
    const decoded = fromNativeRecord(objectId, current.key, current.data, current.revision);
    this.#assertSession(decoded);
    if (decoded.revision !== expectedRevision) return false;

    try {
      const result = await this.#plugin.compareAndSwap({
        ...toNativeRecord(replacement),
        expectedRevision: current.revision,
      });
      assertNativeRevision(result.revision);
      return true;
    } catch (error) {
      if (hasPluginCode(error, REVISION_CONFLICT) || hasPluginCode(error, NOT_FOUND)) {
        return false;
      }
      throw error;
    }
  }

  #assertSession(record: CaptureChunkRecord): void {
    if (this.#sessionId !== undefined && record.reservation.sessionId !== this.#sessionId) {
      throw new QueueInvariantError("native_queue_session_mismatch");
    }
  }
}

function toNativeRecord(record: CaptureChunkRecord): { key: string; data: string } {
  return {
    key: record.reservation.objectId,
    data: encodeStandardBase64(encodeCaptureRecord(record)),
  };
}

function fromNativeRecord(
  expectedObjectId: string,
  actualObjectId: string,
  encoded: string,
  nativeRevision: string,
): CaptureChunkRecord {
  assertNativeRevision(nativeRevision);
  let record: CaptureChunkRecord;
  try {
    record = decodeCaptureRecord(decodeStandardBase64(encoded));
  } catch {
    throw new QueueInvariantError("native_queue_integrity_failure");
  }
  if (actualObjectId !== expectedObjectId || record.reservation.objectId !== expectedObjectId) {
    throw new QueueInvariantError("native_queue_integrity_failure");
  }
  return record;
}

function encodeStandardBase64(value: string): string {
  const base64Url = base64UrlEncode(new TextEncoder().encode(value));
  const padding = "=".repeat((4 - (base64Url.length % 4)) % 4);
  return base64Url.replaceAll("-", "+").replaceAll("_", "/") + padding;
}

function decodeStandardBase64(value: string): string {
  if (!/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/u.test(value)) {
    throw new QueueInvariantError("native_queue_integrity_failure");
  }
  const unpadded = value.replace(/=+$/u, "").replaceAll("+", "-").replaceAll("/", "_");
  return new TextDecoder("utf-8", { fatal: true }).decode(base64UrlDecode(unpadded));
}

function assertNativeRevision(value: string): void {
  if (!/^[1-9][0-9]*$/u.test(value)) {
    throw new QueueInvariantError("native_queue_integrity_failure");
  }
}

function hasPluginCode(error: unknown, code: string): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    (error as { readonly code?: unknown }).code === code
  );
}
