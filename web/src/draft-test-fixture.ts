import { DraftStoreError, type DraftRecord, type DraftStore } from "./draft-store";

/** Component-only storage. Native/encrypted storage has separate integration trials. */
export function memoryDraftStorage() {
  const records = new Map<string, DraftRecord>();
  return async ({scope}: {scope: string}): Promise<DraftStore> => {
    let closed = false;
    return {
      close() { closed = true; },
      async read(address) {
        if (closed) throw new DraftStoreError("unavailable");
        return structuredClone(records.get(`${scope}:${address}`) ?? {revision:null,value:null});
      },
      async write(address, expected, value) {
        if (closed) throw new DraftStoreError("unavailable");
        const key = `${scope}:${address}`, prior = records.get(key) ?? {revision:null,value:null};
        if (prior.revision !== expected) throw new DraftStoreError("conflict");
        const saved = {revision:String(Number(expected ?? 0) + 1),value:structuredClone(value)};
        records.set(key,saved);
        return saved;
      },
    };
  };
}
