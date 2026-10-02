import type { SecureQueuePlugin } from "../../clients/capture/plugins/secure-queue/definitions";

// Reuse Scribe's device-only SecureQueue on Apple and its AES-GCM/non-exportable
// IndexedDB-key pattern on desktop/browser. Audio records and keys stay separate.
const VERSION = 1, MAX_BYTES = 8 * 1048576, FRAME_ALLOWANCE = 512;
// Inbox's128KiB limit applies to account-editor data. Allow the bounded journal
// envelope as well; native storage adds its independent frame allowance below.
const INBOX_VALUE_BYTES = 131072 + 512;
const RECORDS = "sealed-drafts", META = "metadata", KEY = "draft-key-v1", PROFILE = "custody-v1";
const HEX = /^[a-f0-9]{64}$/;
const ADDRESS = /^(?:team|account:practice-work|account-editor:(?:work-routine|portal_setup|finance-setup|vendor-setup|inbox-work|inbox-handoffs|google-messages|(?:practice-result|vendor-work):[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12})|workspace:[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}|editor:[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}:(?:private-note|core-note|transcript|scribe-source|follow-up-proposal|appointments|prep-work|vendor-work|finance-work|portal-work|membership-work|(?:follow-up-result|research|creator-review):[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}))$/;
// Team drafts retain up to 100 bot records and the exact pending configuration.
// Notebook/account limits and every existing storage identity remain unchanged.
// Scribe source recovery contains only the immutable request and its journal envelope.
const limit = (id: string) => /^editor:[a-f0-9-]{36}:(?:scribe-source|creator-review:[a-f0-9-]{36})$/.test(id) ? 4096 : /^editor:[a-f0-9-]{36}:research:[a-f0-9-]{36}$/.test(id) ? 16384 : id === "account-editor:inbox-handoffs" || id === "account-editor:inbox-work" || id === "account-editor:google-messages" ? INBOX_VALUE_BYTES : id === "account-editor:portal_setup" ? 16384 : id.startsWith("editor:") && id.endsWith(":portal-work") ? 65536 : id === "account-editor:finance-setup" || id === "account-editor:vendor-setup" || id.startsWith("account-editor:vendor-work:") || id.startsWith("editor:") && (id.endsWith(":vendor-work") || id.endsWith(":finance-work") || id.endsWith(":membership-work"))
  ? 131072 : id === "team" || id.startsWith("editor:") ? MAX_BYTES : 524288;
const DECIMAL = /^[1-9][0-9]{0,18}$/;

export class DraftStoreError extends Error {
  constructor(readonly code: "unavailable" | "integrity" | "conflict" | "profile" | "invalid" | "key_missing") {
    super(`Private draft storage ${code}`);
  }
}
export type DraftValue = { schema: 1; updatedAt: string; body: unknown };
export type DraftRecord = { revision: string | null; value: DraftValue | null };
export interface DraftStore {
  read(address: string): Promise<DraftRecord>;
  write(address: string, expected: string | null, value: DraftValue | null): Promise<DraftRecord>;
  close(): void;
}
type Native = Pick<SecureQueuePlugin, "get" | "create" | "compareAndSwap">;
type Options = { scope: string; native: boolean; indexedDB?: IDBFactory; crypto?: Crypto; plugin?: Native };
type Sealed = { address: string; revision: string; nonce: Uint8Array<ArrayBuffer>; ciphertext: ArrayBuffer };

/** Server owner scope is accepted only after a fresh authorized team/workspace read. */
export async function privateDraftScope(serverScope: string, apiBase: string, crypto: Crypto = globalThis.crypto): Promise<string> {
  if (!HEX.test(serverScope) || !apiBase || apiBase.length > 2048) throw new DraftStoreError("invalid");
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(JSON.stringify([
    "cosmas-private-drafts-v1", apiBase.replace(/\/+$/, ""), serverScope,
  ])));
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
}

function json(value: unknown, maximum = MAX_BYTES): string {
  const visit = (item: unknown, depth: number): void => {
    if (depth > 30) throw new DraftStoreError("invalid");
    if (item === null || typeof item === "string" || typeof item === "boolean") return;
    if (typeof item === "number" && Number.isFinite(item)) return;
    if (typeof item !== "object" || !item) throw new DraftStoreError("invalid");
    if (!Array.isArray(item) && Object.getPrototypeOf(item) !== Object.prototype) throw new DraftStoreError("invalid");
    for (const [name, field] of Object.entries(item)) {
      if (/^(?:authorization|cookie|password|token|accessToken|refreshToken|getToken|privateKey|rawDEK)$/i.test(name)) {
        throw new DraftStoreError("invalid");
      }
      visit(field, depth + 1);
    }
  };
  visit(value, 0);
  const result = JSON.stringify(value);
  if (new TextEncoder().encode(result).byteLength > maximum) throw new DraftStoreError("invalid");
  return result;
}
function validBase64(value: string, maximumBytes: number): boolean {
  if (!value.length || value.length % 4 || value.length > 4 * Math.ceil(maximumBytes / 3)) return false;
  const padding = value.endsWith("==") ? 2 : value.endsWith("=") ? 1 : 0;
  if (/[^A-Za-z0-9+/]/.test(value.slice(0, value.length - padding))) return false;
  // Check the unused final sextet bits without a repeated-group expression:
  // native frames may be several MiB, beyond regexp backtracking stack limits.
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  return padding === 2 ? (alphabet.indexOf(value[value.length - 3]) & 15) === 0 :
    padding === 1 ? (alphabet.indexOf(value[value.length - 2]) & 3) === 0 : true;
}
function validValue(value: unknown): asserts value is DraftValue | null {
  if (value === null) return;
  if (typeof value !== "object" || !value || Object.keys(value).sort().join(",") !== "body,schema,updatedAt" ||
      !("schema" in value) || value.schema !== 1 || !("updatedAt" in value) || typeof value.updatedAt !== "string" ||
      !Number.isFinite(Date.parse(value.updatedAt)) || !("body" in value)) throw new DraftStoreError("integrity");
  json(value);
}
function revision(value: unknown): asserts value is string {
  if (typeof value !== "string" || !DECIMAL.test(value)) throw new DraftStoreError("integrity");
}
function address(value: string): void { if (!ADDRESS.test(value)) throw new DraftStoreError("invalid"); }
function result<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.addEventListener("success", () => resolve(request.result));
    request.addEventListener("error", () => reject(new DraftStoreError("unavailable")));
  });
}
function done(tx: IDBTransaction, failure: () => Error | undefined = () => undefined): Promise<void> {
  return new Promise((resolve, reject) => {
    tx.addEventListener("complete", () => resolve());
    tx.addEventListener("abort", () => reject(failure() ?? new DraftStoreError("unavailable")));
    tx.addEventListener("error", () => reject(failure() ?? new DraftStoreError("unavailable")));
  });
}

export async function openDraftStore(options: Options): Promise<DraftStore> {
  if (!HEX.test(options.scope)) throw new DraftStoreError("invalid");
  const factory = options.indexedDB ?? globalThis.indexedDB, crypto = options.crypto ?? globalThis.crypto;
  if (!factory || !crypto?.subtle) throw new DraftStoreError("unavailable");
  const database = await new Promise<IDBDatabase>((resolve, reject) => {
    const request = factory.open(`cosmas-private-drafts:v1:${options.scope}`, VERSION);
    let blocked = false;
    request.addEventListener("upgradeneeded", () => {
      request.result.createObjectStore(RECORDS, { keyPath: "address" });
      request.result.createObjectStore(META);
    });
    request.addEventListener("success", () => {
      if (blocked) request.result.close(); else resolve(request.result);
    });
    request.addEventListener("error", () => reject(new DraftStoreError("unavailable")));
    request.addEventListener("blocked", () => { blocked = true; reject(new DraftStoreError("unavailable")); });
  });
  database.addEventListener("versionchange", () => database.close());
  const close = () => database.close();
  try {
    // This marker prevents a changed build from silently selecting another store.
    const profile = options.native ? "native" : "browser";
    const tx = database.transaction([META, RECORDS], "readwrite");
    let failed: DraftStoreError | undefined;
    const committed = done(tx, () => failed);
    const lookup = tx.objectStore(META).get(PROFILE);
    lookup.addEventListener("success", () => {
      if (lookup.result === undefined) {
        const count = tx.objectStore(RECORDS).count();
        count.addEventListener("success", () => {
          if (count.result) { failed = new DraftStoreError("profile"); tx.abort(); }
          else tx.objectStore(META).add(profile, PROFILE);
        });
      } else if (lookup.result !== profile) { failed = new DraftStoreError("profile"); tx.abort(); }
    });
    await committed;
    if (options.native) {
      const plugin = options.plugin ?? (await import("../../clients/capture/plugins/secure-queue")).SecureQueue;
      return nativeStore(plugin, options.scope, close);
    }
    const candidate = await crypto.subtle.generateKey({ name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
    let key = candidate;
    const keyTx = database.transaction([META, RECORDS], "readwrite");
    failed = undefined;
    const keyCommitted = done(keyTx, () => failed);
    const existing = keyTx.objectStore(META).get(KEY);
    existing.addEventListener("success", () => {
      if (existing.result === undefined) {
        const count = keyTx.objectStore(RECORDS).count();
        count.addEventListener("success", () => {
          if (count.result) { failed = new DraftStoreError("key_missing"); keyTx.abort(); }
          else keyTx.objectStore(META).add(candidate, KEY);
        });
      } else key = existing.result as CryptoKey;
    });
    await keyCommitted;
    if (key?.type !== "secret" || key.extractable || key.algorithm?.name !== "AES-GCM" ||
        (key.algorithm as AesKeyAlgorithm).length !== 256 || key.usages.length !== 2 ||
        !key.usages.includes("encrypt") || !key.usages.includes("decrypt")) throw new DraftStoreError("integrity");
    return browserStore(database, key, crypto, options.scope);
  } catch (error) { close(); throw error; }
}

function browserStore(db: IDBDatabase, key: CryptoKey, crypto: Crypto, scope: string): DraftStore {
  const aad = (id: string, rev: string) => new TextEncoder().encode(JSON.stringify(["cosmas-private-draft:v1", scope, id, rev]));
  const read = async (id: string): Promise<DraftRecord> => {
    address(id);
    const tx = db.transaction(RECORDS, "readonly"), finished = done(tx);
    const record = await result(tx.objectStore(RECORDS).get(id)) as Sealed | undefined;
    await finished;
    if (record === undefined) return { revision: null, value: null };
    revision(record.revision);
    if (record.address !== id || !(record.nonce instanceof Uint8Array) || record.nonce.length !== 12 ||
        !(record.ciphertext instanceof ArrayBuffer) || record.ciphertext.byteLength < 16 ||
        record.ciphertext.byteLength > limit(id) + 16) throw new DraftStoreError("integrity");
    let bytes: Uint8Array | undefined;
    try {
      bytes = new Uint8Array(await crypto.subtle.decrypt({ name: "AES-GCM", iv: record.nonce,
        additionalData: aad(id, record.revision) }, key, record.ciphertext));
      const value: unknown = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
      validValue(value);
      return { revision: record.revision, value };
    } catch { throw new DraftStoreError("integrity"); }
    finally { bytes?.fill(0); }
  };
  return { read, close: () => db.close(), async write(id, expected, value) {
    address(id); if (expected !== null) revision(expected); validValue(value);
    const encoded = json(value), prior = await read(id);
    if (new TextEncoder().encode(encoded).length > limit(id)) throw new DraftStoreError("invalid");
    if (json(prior.value) === encoded) return prior;
    if (prior.revision !== expected) throw new DraftStoreError("conflict");
    const next = String(BigInt(expected ?? "0") + 1n); revision(next);
    const nonce = crypto.getRandomValues(new Uint8Array(new ArrayBuffer(12)));
    const plaintext = new TextEncoder().encode(encoded);
    let ciphertext: ArrayBuffer;
    try { ciphertext = await crypto.subtle.encrypt({ name: "AES-GCM", iv: nonce, additionalData: aad(id, next) }, key, plaintext); }
    finally { plaintext.fill(0); }
    const tx = db.transaction(RECORDS, "readwrite"), store = tx.objectStore(RECORDS);
    let failed: DraftStoreError | undefined;
    const finished = done(tx, () => failed), lookup = store.get(id);
    lookup.addEventListener("success", () => {
      if ((lookup.result?.revision ?? null) !== expected) { failed = new DraftStoreError("conflict"); tx.abort(); }
      else store.put({ address: id, revision: next, nonce, ciphertext });
    });
    await finished;
    return { revision: next, value: JSON.parse(encoded) as DraftValue | null };
  }};
}

function nativeStore(plugin: Native, scope: string, closeDatabase: () => void): DraftStore {
  let closed = false;
  const prefix = `cosmas-private-draft:v1:${scope}:`;
  const live = () => { if (closed) throw new DraftStoreError("unavailable"); };
  const read = async (id: string): Promise<DraftRecord> => {
    live(); address(id);
    try {
      const record = await plugin.get({ key: prefix + id }); live();
      revision(record.revision);
      const frameLimit = limit(id) + FRAME_ALLOWANCE;
      if (record.key !== prefix + id || typeof record.data !== "string" ||
          !validBase64(record.data, frameLimit)) throw new DraftStoreError("integrity");
      const bytes = Uint8Array.from(atob(record.data), char => char.charCodeAt(0));
      try {
        if (bytes.length > frameLimit) throw new DraftStoreError("integrity");
        const frame = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
        if (Object.keys(frame).sort().join(",") !== "address,scope,value,version" ||
            frame.version !== 1 || frame.scope !== scope || frame.address !== id) throw new DraftStoreError("integrity");
        validValue(frame.value);
        if (new TextEncoder().encode(json(frame.value)).length > limit(id)) throw new DraftStoreError("integrity");
        return { revision: record.revision, value: frame.value };
      } finally { bytes.fill(0); }
    } catch (error) {
      if (!closed && code(error) === "SECURE_QUEUE_NOT_FOUND") return { revision: null, value: null };
      throw error instanceof DraftStoreError ? error : new DraftStoreError("unavailable");
    }
  };
  return { read, close() { closed = true; closeDatabase(); }, async write(id, expected, value) {
    live(); address(id); if (expected !== null) revision(expected); validValue(value);
    const encoded = json(value), prior = await read(id);
    if (new TextEncoder().encode(encoded).length > limit(id)) throw new DraftStoreError("invalid");
    if (json(prior.value) === encoded) return prior;
    if (prior.revision !== expected) throw new DraftStoreError("conflict");
    const frame = json({ version: 1, scope, address: id, value }, limit(id) + FRAME_ALLOWANCE);
    const bytes = new TextEncoder().encode(frame);
    let data = "";
    try { for (const byte of bytes) data += String.fromCharCode(byte); data = btoa(data); }
    finally { bytes.fill(0); }
    try {
      const written = expected === null ? await plugin.create({ key: prefix + id, data }) :
        await plugin.compareAndSwap({ key: prefix + id, data, expectedRevision: expected });
      live(); revision(written.revision);
      return { revision: written.revision, value: JSON.parse(encoded) as DraftValue | null };
    } catch (error) {
      // A lost native reply can follow a committed write. Confirm exact contents;
      // never replace a concurrent writer or fall back to another custody profile.
      const current = await read(id);
      if (json(current.value) === encoded) return current;
      if (["SECURE_QUEUE_REVISION_CONFLICT", "SECURE_QUEUE_ALREADY_EXISTS"].includes(code(error) ?? "")) throw new DraftStoreError("conflict");
      throw new DraftStoreError("unavailable");
    }
  }};
}
function code(error: unknown): string | undefined {
  return typeof error === "object" && error !== null && "code" in error && typeof error.code === "string" ? error.code : undefined;
}
