import type { NativeQueuePlugin } from "../src/storage/native-plugin";

/** Test-only API double; native at-rest encryption is verified in the simulator. */
export class MemoryNativeQueuePlugin implements NativeQueuePlugin {
  readonly records = new Map<string, {key: string; data: string; revision: string}>();
  readonly reads: string[] = [];
  async create(value: {key: string; data: string}) {
    if (this.records.has(value.key)) throw {code: "SECURE_QUEUE_ALREADY_EXISTS"};
    this.records.set(value.key, {...value, revision: "1"});
    return {revision: "1"};
  }
  async get({key}: {key: string}) {
    this.reads.push(key);
    const value = this.records.get(key);
    if (!value) throw {code: "SECURE_QUEUE_NOT_FOUND"};
    return {...value};
  }
  async list() { return {keys: [...this.records.keys()]}; }
  async compareAndSwap(value: {key: string; data: string; expectedRevision: string}) {
    const current = this.records.get(value.key);
    if (!current) throw {code: "SECURE_QUEUE_NOT_FOUND"};
    if (current.revision !== value.expectedRevision) throw {code: "SECURE_QUEUE_REVISION_CONFLICT"};
    const revision = String(BigInt(current.revision) + 1n);
    this.records.set(value.key, {key: value.key, data: value.data, revision});
    return {revision};
  }
}
