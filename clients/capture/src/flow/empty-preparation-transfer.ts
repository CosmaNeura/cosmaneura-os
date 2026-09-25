import { QueueInvariantError } from '../queue/errors';
import type { CaptureQueueStorage } from '../queue/types';
import { validateRecoveryState, type CaptureRecoveryBff } from '../bff/recovery-contracts';
import { EncryptedIndexedDbFlowStore as LegacyStore, assertActiveCaptureState as assertLegacyActive, assertPreparationState as assertLegacyPreparation } from './encrypted-store';
import { EncryptedIndexedDbFlowStore as ConfiguredStore, assertActiveCaptureState, assertPreparationState } from '../configured/flow/encrypted-store';
import type { ActiveCaptureState, ConfiguredCapturePreparationState } from '../configured/flow/types';
const RECORDS = 'encrypted-flow-records', META = 'metadata', KEYS = 'session-keys';
const LOCAL_KEY = 'flow-state-encryption-key-v1', TRANSFER = 'configured-empty-transfer-v1';
const IMPORT = 'configured-empty-import-v1';
interface Sealed {
    key: string;
    nonce: Uint8Array<ArrayBuffer>;
    ciphertext: ArrayBuffer;
    recordRevision?: number;
}
interface Transfer {
    version: 1;
    id: string;
    sessionId: string;
    destination: string;
    kind: 'browser' | 'native';
    records: Sealed[];
}
const conflict = () => new QueueInvariantError('capture_preparation_transfer_conflict');
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
function fingerprint(records: Sealed[]): string {
    return JSON.stringify(records.map(row => ({ ...row, nonce: Array.from(row.nonce),
        ciphertext: Array.from(new Uint8Array(row.ciphertext)) })).sort((a, b) => a.key.localeCompare(b.key)));
}
function request<T>(value: IDBRequest<T>): Promise<T> {
    return new Promise((resolve, reject) => { value.onsuccess = () => resolve(value.result); value.onerror = () => reject(value.error); });
}
function done(tx: IDBTransaction): Promise<void> {
    return new Promise((resolve, reject) => { tx.oncomplete = () => resolve(); tx.onabort = () => reject(conflict()); tx.onerror = () => reject(tx.error); });
}
async function open(name: string, indexedDB: IDBFactory): Promise<IDBDatabase> {
    return request(indexedDB.open(name, 1));
}
async function get<T>(db: IDBDatabase, store: string, key: string): Promise<T | undefined> {
    const tx = db.transaction(store, 'readonly'), settled = done(tx);
    const value = await request(tx.objectStore(store).get(key));
    await settled;
    return value as T | undefined;
}
async function all(db: IDBDatabase): Promise<Sealed[]> {
    const tx = db.transaction(RECORDS, 'readonly'), settled = done(tx);
    const values = await request(tx.objectStore(RECORDS).getAll());
    await settled;
    return values as Sealed[];
}
function aad(key: string): Uint8Array<ArrayBuffer> {
    return new TextEncoder().encode(`cosmaneura-capture-flow-state:v1:${key}`);
}
async function seal(key: string, value: unknown, local: CryptoKey, crypto: Crypto): Promise<Sealed> {
    const nonce = crypto.getRandomValues(new Uint8Array(12)), bytes = new TextEncoder().encode(JSON.stringify(value));
    try {
        return { key, nonce, ciphertext: await crypto.subtle.encrypt({ name: 'AES-GCM', iv: nonce, additionalData: aad(key) }, local, bytes) };
    }
    finally {
        bytes.fill(0);
    }
}
async function decode(row: Sealed, local: CryptoKey, crypto: Crypto): Promise<unknown> {
    const bytes = new Uint8Array(await crypto.subtle.decrypt({ name: 'AES-GCM', iv: row.nonce, additionalData: aad(row.key) }, local, row.ciphertext));
    try {
        return JSON.parse(new TextDecoder('utf8', { fatal: true }).decode(bytes));
    }
    finally {
        bytes.fill(0);
    }
}
function assertTransfer(value: unknown, sessionId: string, destination: string): asserts value is Transfer {
    const item = value as Transfer | undefined;
    if (!item || item.version !== 1 || item.sessionId !== sessionId || item.destination !== destination ||
        typeof item.id !== 'string' || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u.test(item.id) || !['browser', 'native'].includes(item.kind) ||
        !Array.isArray(item.records) || !item.records.length || item.records.length > 1024 ||
        new Set(item.records.map(row => row.key)).size !== item.records.length || item.records.some(row => typeof row.key !== 'string' || !(row.nonce instanceof Uint8Array) || row.nonce.byteLength !== 12 ||
        !(row.ciphertext instanceof ArrayBuffer)))
        throw conflict();
}
/** Read before legacy active/preparation records: a transfer fences all old readers. */
export async function hasEmptyPreparationTransfer(source: string, sessionId: string, destination: string, indexedDB = globalThis.indexedDB): Promise<boolean> {
    const db = await open(source, indexedDB);
    try {
        const value = await get(db, META, TRANSFER);
        if (value === undefined)
            return false;
        assertTransfer(value, sessionId, destination);
        return true;
    }
    finally {
        db.close();
    }
}
/** Caller holds the origin capture lock and has closed the old controller.
 * The original encrypted records and key remain in the source. An atomic fence
 * precedes destination writes; exact replay finishes an interrupted transfer.
 * This operation never starts a source, renews a lease, or replaces a session key.
 */
export async function transferEmptyPreparation(options: {
    source: string;
    destination: string;
    sessionId: string;
    kind: 'browser' | 'native';
    queue: CaptureQueueStorage;
    bff: CaptureRecoveryBff;
    indexedDB?: IDBFactory;
    crypto?: Crypto;
    now?: () => Date;
    afterFence?: () => Promise<void>;
}): Promise<void> {
    const { source, destination, sessionId, kind } = options;
    if (source === destination)
        throw conflict();
    const indexedDB = options.indexedDB ?? globalThis.indexedDB, crypto = options.crypto ?? globalThis.crypto;
    const sourceDb = await open(source, indexedDB);
    let destinationDb: IDBDatabase | undefined;
    try {
        const configured = await ConfiguredStore.open({ databaseName: destination, indexedDB, crypto });
        configured.close();
        destinationDb = await open(destination, indexedDB);
        let transfer = await get<Transfer>(sourceDb, META, TRANSFER);
        if (!transfer) {
            if ((await all(destinationDb)).length)
                throw conflict();
            const keyTx = destinationDb.transaction(KEYS, 'readonly'), keyDone = done(keyTx);
            const keyCount = await request(keyTx.objectStore(KEYS).count());
            await keyDone;
            if (keyCount)
                throw conflict();
            // A crash after source cleanup may leave only the old import receipt.
            // Empty destination data/key stores make that receipt safe to retire.
            const retire = destinationDb.transaction(META, 'readwrite'), retired = done(retire);
            retire.objectStore(META).delete(IMPORT);
            await retired;
            const legacy = await LegacyStore.open({ databaseName: source, indexedDB, crypto });
            try {
                const before = await all(sourceDb);
                const active = await legacy.getActiveCaptureState(), preparation = await legacy.getPreparationState();
                const recovery = await legacy.getCaptureRecoveryState(sessionId);
                const keyState = await legacy.getSessionKeyState(sessionId), sessionKey = await legacy.getSessionKey(sessionId);
                if (!preparation || preparation.mode !== 'core_admitted' || preparation.sessionId !== sessionId || preparation.reviewAfterUpload !== true ||
                    active && (active.sessionId !== sessionId || active.reviewAfterUpload !== true || !['ready', 'paused'].includes(active.phase) ||
                        active.recordedChunks !== 0 || active.recordedPlaintextBytes !== 0) ||
                    recovery && (recovery.phase !== 'ready' || recovery.nextSequenceNumber !== 0 || recovery.nextSegmentOrdinal !== 0 ||
                        recovery.currentSegmentId !== null || recovery.segments.length !== 0 || recovery.gaps.length !== 0) ||
                    Boolean(keyState) !== Boolean(sessionKey) || active && keyState?.state !== 'bound' ||
                    (await legacy.listReservationIntents()).some(intent => intent.sessionId !== sessionId) ||
                    (await legacy.getQueueStorageKind(sessionId)) !== kind ||
                    (await options.queue.list()).some(row => row.reservation.sessionId === sessionId ? row.state !== 'reserved' : row.state !== 'purged') ||
                    before.some(row => !['active', 'preparation', `session:${sessionId}`].includes(row.key) &&
                        !row.key.startsWith('intent:') && !/^recovery:[A-Za-z0-9_-]+$/u.test(row.key)))
                    throw conflict();
                const state = await validateRecoveryState(await options.bff.getCaptureRecoveryState(sessionId), sessionId, options.now?.() ?? new Date(), crypto);
                if (state.session_status !== 'created' || state.lease_closed || state.history.recoveries.length ||
                    active && !same(state.current_lease, active.lease) || !active && state.current_lease && preparation.leaseRequest === null)
                    throw conflict();
                // Capture the exact sealed source, then compare it again inside the fence transaction.
                transfer = { version: 1, id: crypto.randomUUID(), sessionId, destination, kind, records: before };
                const local = await get<CryptoKey>(sourceDb, META, LOCAL_KEY);
                if (!local)
                    throw conflict();
                const fence = { schemaVersion: 99, sessionId, transferId: transfer.id };
                const writes = await Promise.all(['active', 'preparation'].map(key => seal(key, fence, local, crypto)));
                const tx = sourceDb.transaction([RECORDS, META], 'readwrite'), settled = done(tx);
                const records = tx.objectStore(RECORDS), meta = tx.objectStore(META);
                const current = records.getAll();
                current.onsuccess = () => {
                    if (fingerprint(current.result as Sealed[]) !== fingerprint(before)) {
                        tx.abort();
                        return;
                    }
                    meta.add(transfer, TRANSFER);
                    meta.put(`configured:${kind}`, `queue-storage:${sessionId}`);
                    for (const row of writes)
                        records.put(row);
                };
                await settled;
            }
            finally {
                legacy.close();
            }
        }
        assertTransfer(transfer, sessionId, destination);
        if (transfer.kind !== kind)
            throw conflict();
        await options.afterFence?.();
        // Initialize only the standard schema. No capture preparation runs here.
        const imported = await get<{
            id: string;
            sessionId: string;
        }>(destinationDb, META, IMPORT);
        if (imported) {
            if (imported.id !== transfer.id || imported.sessionId !== sessionId)
                throw conflict();
            return;
        }
        const local = await get<CryptoKey>(sourceDb, META, LOCAL_KEY);
        if (!local)
            throw conflict();
        const originals = transfer.records, prepared = originals.find(row => row.key === 'preparation');
        if (!prepared)
            throw conflict();
        const originalPreparation = await decode(prepared, local, crypto);
        assertLegacyPreparation(originalPreparation);
        if (originalPreparation.mode !== 'core_admitted' || originalPreparation.reviewAfterUpload !== true || originalPreparation.sessionId !== sessionId)
            throw conflict();
        const { reviewAfterUpload: _, ...rest } = originalPreparation;
        const preparation: ConfiguredCapturePreparationState = { ...rest, mode: 'configured_core',
            schemaVersion: originalPreparation.profileSelection ? 5 : 2 };
        assertPreparationState(preparation);
        const replacements = new Map<string, Sealed>([['preparation', await seal('preparation', preparation, local, crypto)]]);
        const oldActive = originals.find(row => row.key === 'active');
        if (oldActive) {
            const value = await decode(oldActive, local, crypto);
            assertLegacyActive(value);
            if (value.sessionId !== sessionId || value.reviewAfterUpload !== true || !['ready', 'paused'].includes(value.phase) ||
                value.recordedChunks !== 0 || value.recordedPlaintextBytes !== 0)
                throw conflict();
            const active: ActiveCaptureState = { ...value, schemaVersion: value.captureProfile ? 5 : 2 };
            assertActiveCaptureState(active);
            replacements.set('active', await seal('active', active, local, crypto));
        }
        const key = await get<CryptoKey>(sourceDb, KEYS, sessionId);
        if (originals.some(row => row.key === `session:${sessionId}`) !== Boolean(key))
            throw conflict();
        const tx = destinationDb.transaction([RECORDS, META, KEYS], 'readwrite'), settled = done(tx);
        const records = tx.objectStore(RECORDS), meta = tx.objectStore(META), keys = tx.objectStore(KEYS);
        let pending = 3, empty = true;
        const checked = () => {
            if (--pending)
                return;
            if (!empty) {
                tx.abort();
                return;
            }
            meta.put(local, LOCAL_KEY);
            meta.add({ id: transfer!.id, sessionId }, IMPORT);
            for (const row of originals)
                if (!row.key.startsWith('recovery:'))
                    records.add(replacements.get(row.key) ?? row);
            if (key)
                keys.add(key, sessionId);
        };
        const rows = records.count();
        rows.onsuccess = () => { empty &&= rows.result === 0; checked(); };
        const keyCount = keys.count();
        keyCount.onsuccess = () => { empty &&= keyCount.result === 0; checked(); };
        const marker = meta.get(IMPORT);
        marker.onsuccess = () => { empty &&= marker.result === undefined; checked(); };
        await settled;
    }
    finally {
        destinationDb?.close();
        sourceDb.close();
    }
}
/** After confirmed upload and local release, retire the old key and transfer fence. */
export async function releaseEmptyPreparationTransfer(source: string, destination: string, sessionId: string, indexedDB = globalThis.indexedDB): Promise<void> {
    const original = await open(source, indexedDB), target = await open(destination, indexedDB);
    try {
        const transfer = await get<Transfer>(original, META, TRANSFER);
        if (!transfer)
            return;
        assertTransfer(transfer, sessionId, destination);
        const imported = await get<{
            id: string;
            sessionId: string;
        }>(target, META, IMPORT);
        if (imported?.id !== transfer.id || imported.sessionId !== sessionId || (await all(target)).length)
            throw conflict();
        const tx = original.transaction([RECORDS, META, KEYS], 'readwrite'), settled = done(tx);
        const marker = tx.objectStore(META).get(TRANSFER);
        marker.onsuccess = () => {
            if ((marker.result as Transfer | undefined)?.id !== transfer.id) {
                tx.abort();
                return;
            }
            for (const row of transfer.records)
                tx.objectStore(RECORDS).delete(row.key);
            tx.objectStore(RECORDS).delete('active');
            tx.objectStore(RECORDS).delete('preparation');
            tx.objectStore(KEYS).delete(sessionId);
            tx.objectStore(META).delete(TRANSFER);
        };
        await settled;
        const clear = target.transaction(META, 'readwrite'), cleared = done(clear);
        clear.objectStore(META).delete(IMPORT);
        await cleared;
    }
    finally {
        original.close();
        target.close();
    }
}
