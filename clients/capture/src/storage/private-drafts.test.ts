import { webcrypto } from "node:crypto";
import { IDBFactory } from "fake-indexeddb";
import { describe, expect, it } from "vitest";
import { openDraftStore, privateDraftScope, type DraftValue } from "../../../../web/src/draft-store";
import { DraftJournal, accountEditorAddress, editorAddress, type RecoveredDraft } from "../../../../web/src/draft-journal";
import type { BotSettings, TeamConfiguration, TeamSaveInput } from "../../../../web/src/workspace-api";

const crypto = webcrypto as unknown as Crypto;
const scope = "a".repeat(64), other = "b".repeat(64);
const address = "workspace:00000000-0000-4000-8000-000000000021";
const value: DraftValue = { schema: 1, updatedAt: "2026-09-21T12:00:00Z", body: { note: "Invented private draft", pending: { key: "exact-invented-save" } } };
const encodedBytes = (item: unknown) => new TextEncoder().encode(JSON.stringify(item)).byteLength;
const eightMiB = 8 * 1048576;
function maximumTeam(): TeamConfiguration {
  // Six-byte JSON escapes exercise the existing per-field character maxima.
  // Retired instances remain in the same configuration for exact recovery.
  const text = (length: number) => "\u0001".repeat(length);
  const identity = (index: number) => `00000000-0000-4000-8000-${String(index).padStart(12, "0")}`;
  const baseline: BotSettings["role"][] = ["scribe", "visit_prep", "follow_up", "chief"];
  return { practice_context: text(1000), presets: [
    { preset_id: "provider", version: 1, slots: { scribe: "scribe", visit_prep: "visit_prep", follow_up: "follow_up", chief: "chief" } },
    { preset_id: "front_desk", version: 1, slots: { inbox: identity(4), scheduling: identity(5), intake: identity(6) } },
    { preset_id: "practice_manager", version: 1, slots: { operations: identity(7), membership_billing: identity(8), chief: "chief" } },
  ], bots: Array.from({ length: 100 }, (_, index): BotSettings => ({
    role: index < 4 ? baseline[index] : "custom", name: text(40),
    enabled: index < 12, response_style: "detailed", include_notebook: false, include_evidence: false,
    instance_id: index < 4 ? null : identity(index),
    job_focus: text(500), working_preferences: text(2000), retired: index >= 12,
    skills: index < 4 ? [] : ["saved_context", "work_status", "encounter_prep", "calendar_availability"],
    blocked_capabilities: ["model_answer", "private_draft_handoff", "practice_work_brief"],
  })) };
}
function exactValueBytes(bytes: number): DraftValue {
  const empty = { ...value, body: { note: "" } };
  return { ...empty, body: { note: "x".repeat(bytes - encodedBytes(empty)) } };
}
function nativeFixture(dropCreateReply = false) {
  const records = new Map<string, { key: string; data: string; revision: string }>();
  let creates = 0, swaps = 0;
  const plugin = {
    get: async ({ key }: { key: string }) => {
      const record = records.get(key); if (!record) throw { code: "SECURE_QUEUE_NOT_FOUND" };
      return { ...record };
    },
    create: async (record: { key: string; data: string }) => {
      if (records.has(record.key)) throw { code: "SECURE_QUEUE_ALREADY_EXISTS" };
      creates++; records.set(record.key, { ...record, revision: "1" });
      if (dropCreateReply) { dropCreateReply = false; throw Error("Committed native reply lost"); }
      return { revision: "1" };
    },
    compareAndSwap: async (record: { key: string; data: string; expectedRevision: string }) => {
      const old = records.get(record.key);
      if (old?.revision !== record.expectedRevision) throw { code: "SECURE_QUEUE_REVISION_CONFLICT" };
      swaps++; const revision = String(BigInt(old.revision) + 1n);
      records.set(record.key, { key: record.key, data: record.data, revision }); return { revision };
    },
  };
  return { plugin, records, counts: () => ({ creates, swaps }) };
}
async function raw(indexedDB: IDBFactory, edit?: (tx: IDBTransaction) => void) {
  const db = await new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open(`cosmas-private-drafts:v1:${scope}`);request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);
  });
  const result = await new Promise<{records: unknown[]; key: CryptoKey}>((resolve, reject) => {
    const tx=db.transaction(["sealed-drafts","metadata"],edit?"readwrite":"readonly");
    edit?.(tx); const records=tx.objectStore("sealed-drafts").getAll(), key=tx.objectStore("metadata").get("draft-key-v1");
    tx.oncomplete=()=>resolve({records:records.result,key:key.result});tx.onabort=()=>reject(tx.error);
  });db.close();return result;
}

const workspaceId = "00000000-0000-4000-8000-000000000021";
const requestId = "00000000-0000-4000-8000-000000000031";
const newEditors: {address: string; draft: RecoveredDraft}[] = [
  {address: accountEditorAddress("private-draft"), draft: {kind: "account-editor", editor: "private-draft",
    data: {contract: "private-draft-recovery.v1", title: "Invented private note 🩺", pending: {title: "Invented private note 🩺", idempotency_key: requestId}}, pending: requestId}},
  {address: editorAddress(workspaceId, "private-draft-link"), draft: {kind: "editor", workspaceId, editor: "private-draft-link",
    data: {contract: "private-draft-link-recovery.v1", workspace_id: workspaceId, pending: {expected_revision: 1, idempotency_key: requestId,
      appointment_id: "00000000-0000-4000-8000-000000000041", appointment_link_confirmed: true}}, pending: requestId}},
  {address: editorAddress(workspaceId, "agent-research-review"), draft: {kind: "editor", workspaceId, editor: "agent-research-review",
    data: {contract: "agent-research-review-recovery.v1", workspace_id: workspaceId, pending: {ticket_id: requestId,
      revision_id: "00000000-0000-4000-8000-000000000032", payload_hash: "c".repeat(64), public_query_confirmed: true}}, pending: "00000000-0000-4000-8000-000000000032"}},
];

describe("private draft custody", () => {
  it.each([false,true])("round-trips the three registered recovery editors through the production store and journal (native=%s)", async native => {
    const fixture=nativeFixture(true),indexedDB=new IDBFactory();
    const options={scope,native,indexedDB,crypto,...(native?{plugin:fixture.plugin}:{})};
    const journal=new DraftJournal(await openDraftStore(options));
    for(const item of newEditors){expect(await journal.load(item.address)).toBeNull();await journal.persist(item.address,item.draft);}
    journal.close();
    if(!native){
      const sealed=await raw(indexedDB);
      expect(sealed.records).toHaveLength(3);expect(sealed.key.extractable).toBe(false);
      await expect(crypto.subtle.exportKey("raw",sealed.key)).rejects.toThrow();
      for(const row of sealed.records)expect(Object.keys(row as object).sort()).toEqual(["address","ciphertext","nonce","revision"]);
      expect(JSON.stringify(sealed.records)).not.toContain("Invented private note");
      expect(JSON.stringify(sealed.records)).not.toContain(requestId);
    }
    const reopened=new DraftJournal(await openDraftStore(options)),stale=new DraftJournal(await openDraftStore(options));
    for(const item of newEditors){expect(await reopened.load(item.address)).toEqual(item.draft);expect(await stale.load(item.address)).toEqual(item.draft);}
    await reopened.persist(newEditors[0].address,null);
    await expect(stale.persist(newEditors[0].address,{kind:"account-editor",editor:"private-draft",pending:requestId,
      data:{contract:"private-draft-recovery.v1",title:"Different title",pending:{title:"Different title",idempotency_key:requestId}}})).rejects.toMatchObject({code:"conflict"});
    reopened.close();stale.close();
    const foreign=new DraftJournal(await openDraftStore({...options,scope:other}));
    for(const item of newEditors)expect(await foreign.load(item.address)).toBeNull();foreign.close();
    if(native)expect(fixture.counts()).toEqual({creates:3,swaps:1});
    await expect(openDraftStore({...options,native:!native})).rejects.toMatchObject({code:"profile"});
  });
  it.each([false,true])("rejects unregistered recovery aliases before any native IPC or record write (native=%s)", async native => {
    const fixture=nativeFixture(),get=fixture.plugin.get;
    let reads=0;fixture.plugin.get=async input=>{reads++;return get(input);};
    const store=await openDraftStore({scope,native,indexedDB:new IDBFactory(),crypto,...(native?{plugin:fixture.plugin}:{})});
    for(const id of ["account-editor:private-draft:other", "account-editor:private-draft-link", `editor:${workspaceId}:private-draft`,
      `editor:${workspaceId}:private-draft-link:other`, `editor:${workspaceId}:agent-research-review:other`, "editor:not-a-workspace:private-draft-link"]){
      await expect(store.read(id)).rejects.toMatchObject({code:"invalid"});
      await expect(store.write(id,null,value)).rejects.toMatchObject({code:"invalid"});
    }
    expect(reads).toBe(0);expect(fixture.counts()).toEqual({creates:0,swaps:0});store.close();
  });
  it("retains the new encrypted editors when their key is missing and refuses substituted ciphertext addresses", async () => {
    const indexedDB=new IDBFactory(),options={scope,native:false,indexedDB,crypto};
    const journal=new DraftJournal(await openDraftStore(options));
    for(const item of newEditors){await journal.load(item.address);await journal.persist(item.address,item.draft);}
    journal.close();
    await raw(indexedDB,tx=>{const request=tx.objectStore("sealed-drafts").get(newEditors[1].address);request.onsuccess=()=>{
      tx.objectStore("sealed-drafts").put({...request.result,address:newEditors[2].address});
    };});
    const changed=await openDraftStore(options);await expect(changed.read(newEditors[2].address)).rejects.toMatchObject({code:"integrity"});changed.close();
    const before=await raw(indexedDB,tx=>tx.objectStore("metadata").delete("draft-key-v1"));
    await expect(openDraftStore(options)).rejects.toMatchObject({code:"key_missing"});
    expect((await raw(indexedDB)).records).toEqual(before.records);
  });
  it.each([false,true])("bounds portal actions to 64 KiB and preserves them across reopen and stale writers (native=%s)", async native => {
    const fixture=nativeFixture(true),options={scope,native,indexedDB:new IDBFactory(),crypto,...(native?{plugin:fixture.plugin}:{})};
    const id="editor:00000000-0000-4000-8000-000000000021:portal-work",maximum=exactValueBytes(65536),store=await openDraftStore(options);
    await store.write(id,null,maximum);await expect(store.write(id,"1",exactValueBytes(65537))).rejects.toMatchObject({code:"invalid"});store.close();
    const reopened=await openDraftStore(options),stale=await openDraftStore(options);expect((await reopened.read(id)).value).toEqual(maximum);
    await reopened.write(id,"1",value);await expect(stale.write(id,"1",maximum)).rejects.toMatchObject({code:"conflict"});reopened.close();stale.close();
    const foreign=await openDraftStore({...options,scope:other});expect((await foreign.read(id)).value).toBeNull();foreign.close();
  });
  it.each([false,true])("bounds account portal setup to 16 KiB and retains it after reopen (native=%s)", async native => {
    const fixture=nativeFixture(true),options={scope,native,indexedDB:new IDBFactory(),crypto,...(native?{plugin:fixture.plugin}:{})};
    const id="account-editor:portal_setup", maximum=exactValueBytes(16384),store=await openDraftStore(options);
    await store.write(id,null,maximum);
    await expect(store.write(id,"1",exactValueBytes(16385))).rejects.toMatchObject({code:"invalid"});
    await expect(store.write(id+":unbound",null,value)).rejects.toMatchObject({code:"invalid"});
    store.close();const reopened=await openDraftStore(options);expect((await reopened.read(id)).value).toEqual(maximum);reopened.close();
    const foreign=await openDraftStore({...options,scope:other});expect((await foreign.read(id)).value).toBeNull();foreign.close();
  });
  it.each([false,true])("bounds scoped connector drafts to 128 KiB and preserves exact contents/CAS (native=%s)", async native => {
    const fixture=nativeFixture(true),indexedDB=new IDBFactory();
    const options={scope,native,indexedDB,crypto,...(native?{plugin:fixture.plugin}:{})};
    const ids=["editor:00000000-0000-4000-8000-000000000021:vendor-work", "account-editor:vendor-work:00000000-0000-4000-8000-000000000031", "editor:00000000-0000-4000-8000-000000000021:finance-work", "account-editor:finance-setup"];
    const maximum=exactValueBytes(131072),store=await openDraftStore(options);
    for(const id of ids){await store.write(id,null,maximum);await expect(store.write(id,"1",exactValueBytes(131073))).rejects.toMatchObject({code:"invalid"});}
    await expect(store.write("account-editor:vendor-work:unbound",null,value)).rejects.toMatchObject({code:"invalid"});
    store.close();const reopened=await openDraftStore(options),stale=await openDraftStore(options);
    for(const id of ids)expect((await reopened.read(id)).value).toEqual(maximum);
    await reopened.write(ids[0],"1",value);
    await expect(stale.write(ids[0],"1",maximum)).rejects.toMatchObject({code:"conflict"});
    stale.close();reopened.close();
    const foreign=await openDraftStore({...options,scope:other});
    for(const id of ids)expect((await foreign.read(id)).value).toBeNull();foreign.close();
  });
  it("persists ciphertext and a non-exportable key, then reopens exact drafts and pending identifiers", async () => {
    const indexedDB=new IDBFactory(), options={scope,native:false,indexedDB,crypto};
    const store=await openDraftStore(options);const saved=await store.write(address,null,value);store.close();
    const sealed=await raw(indexedDB);
    expect(Object.keys(sealed.records[0] as object).sort()).toEqual(["address","ciphertext","nonce","revision"]);
    expect(sealed.key.extractable).toBe(false);
    await expect(crypto.subtle.exportKey("raw",sealed.key)).rejects.toThrow();
    expect(JSON.stringify(sealed.records)).not.toContain("Invented private draft");
    const reopened=await openDraftStore(options);expect(await reopened.read(address)).toEqual(saved);reopened.close();
    const foreign=await openDraftStore({...options,scope:other});expect((await foreign.read(address)).value).toBeNull();foreign.close();
  });
  it("uses atomic revisions so simultaneous writers cannot overwrite each other, including after discard", async () => {
    const options={scope,native:false,indexedDB:new IDBFactory(),crypto};
    const a=await openDraftStore(options),b=await openDraftStore(options);
    const outcomes=await Promise.allSettled([a.write(address,null,value),b.write(address,null,{...value,body:{note:"Other draft"}})]);
    expect(outcomes.filter(r=>r.status==="fulfilled")).toHaveLength(1);
    expect(outcomes.filter(r=>r.status==="rejected")).toHaveLength(1);
    const current=await a.read(address);const cleared=await a.write(address,current.revision,null);
    expect(cleared.value).toBeNull();expect(cleared.revision).not.toBeNull();
    await expect(b.write(address,current.revision,value)).rejects.toMatchObject({code:"conflict"});a.close();b.close();
  });
  it("refuses missing keys with retained ciphertext and never resets it", async () => {
    const indexedDB=new IDBFactory(),options={scope,native:false,indexedDB,crypto};
    const store=await openDraftStore(options);await store.write(address,null,value);store.close();
    const before=await raw(indexedDB,tx=>tx.objectStore("metadata").delete("draft-key-v1"));
    await expect(openDraftStore(options)).rejects.toMatchObject({code:"key_missing"});
    expect((await raw(indexedDB)).records).toEqual(before.records);
  });
  it("detects ciphertext corruption and refuses custody profile changes", async () => {
    const indexedDB=new IDBFactory(),options={scope,native:false,indexedDB,crypto};
    const store=await openDraftStore(options);await store.write(address,null,value);
    await raw(indexedDB,tx=>{const record=tx.objectStore("sealed-drafts").get(address);record.onsuccess=()=>{
      const saved=record.result;new Uint8Array(saved.ciphertext)[0]^=1;tx.objectStore("sealed-drafts").put(saved);
    };});
    await expect(store.read(address)).rejects.toMatchObject({code:"integrity"});store.close();
    await expect(openDraftStore({...options,native:true})).rejects.toMatchObject({code:"profile"});
  });
  it("binds owner and API namespaces and rejects credentials, oversized and non-JSON values", async () => {
    expect(await privateDraftScope(scope,"http://localhost:8101/",crypto)).toBe(await privateDraftScope(scope,"http://localhost:8101",crypto));
    expect(await privateDraftScope(scope,"http://localhost:8101",crypto)).not.toBe(await privateDraftScope(other,"http://localhost:8101",crypto));
    expect(await privateDraftScope(scope,"http://localhost:8101",crypto)).not.toBe(await privateDraftScope(scope,"http://localhost:8102",crypto));
    const store=await openDraftStore({scope,native:false,indexedDB:new IDBFactory(),crypto});
    for(const body of [{token:"not-for-storage"},{getToken:()=>"never"},{note:"x".repeat(524288)},{note:undefined}]) {
      await expect(store.write(address,null,{...value,body})).rejects.toMatchObject({code:"invalid"});
    }
    expect((await store.read(address)).value).toBeNull();store.close();
  });
  it("recovers a committed native write after a lost reply, fences writers and never uses browser fallback", async () => {
    const records=new Map<string,{key:string;data:string;revision:string}>();let drop=true;
    const plugin={get:async({key}:{key:string})=>{const value=records.get(key);if(!value)throw {code:"SECURE_QUEUE_NOT_FOUND"};return {...value};},
      create:async(record:{key:string;data:string})=>{if(records.has(record.key))throw {code:"SECURE_QUEUE_ALREADY_EXISTS"};records.set(record.key,{...record,revision:"1"});if(drop){drop=false;throw Error("Lost reply");}return {revision:"1"};},
      compareAndSwap:async(record:{key:string;data:string;expectedRevision:string})=>{const old=records.get(record.key);if(old?.revision!==record.expectedRevision)throw {code:"SECURE_QUEUE_REVISION_CONFLICT"};const rev=String(BigInt(old.revision)+1n);records.set(record.key,{key:record.key,data:record.data,revision:rev});return {revision:rev};}};
    const options={scope,native:true,indexedDB:new IDBFactory(),crypto,plugin};
    const a=await openDraftStore(options),b=await openDraftStore(options);
    expect((await a.write(address,null,value)).revision).toBe("1");
    await a.write(address,"1",{...value,body:{note:"Updated"}});
    await expect(b.write(address,"1",value)).rejects.toMatchObject({code:"conflict"});
    a.close();b.close();const reopened=await openDraftStore(options);expect((await reopened.read(address)).value?.body).toEqual({note:"Updated"});reopened.close();
    expect(records.size).toBe(1);
    const foreign=await openDraftStore({...options,scope:other});expect((await foreign.read(address)).value).toBeNull();foreign.close();
    await expect(openDraftStore({...options,native:false})).rejects.toMatchObject({code:"profile"});
  });
  it("retains larger clinical receipts separately while keeping notebook limits", async () => {
    const options={scope,native:false,indexedDB:new IDBFactory(),crypto};
    const id="editor:00000000-0000-4000-8000-000000000022:transcript";
    const large={...value,body:{source:"x".repeat(600000),edits:[{content:"Unfinished invented correction"}]}};
    const store=await openDraftStore(options);await store.write(id,null,large);
    await expect(store.write(address,null,large)).rejects.toMatchObject({code:"invalid"});
    await expect(store.write(id,"1",{...value,body:{content:"x".repeat(8*1048576)}})).rejects.toMatchObject({code:"invalid"});
    store.close();const reopened=await openDraftStore(options);
    expect((await reopened.read(id)).value).toEqual(large);
    expect((await reopened.read(id.replace("transcript","core-note"))).value).toBeNull();
    reopened.close();
  });
  it("encrypts all 100 retained bots with the exact pending team save and reopens the draft", async () => {
    const configuration = maximumTeam();
    const pending: TeamSaveInput = { expected_revision: 99, idempotency_key: "max-team-save-" + "x".repeat(86), configuration,
      setup_review: { catalog_version: 1, configuration_sha256: "c".repeat(64), prerequisites_sha256: "d".repeat(64) } };
    const draft: DraftValue = { ...value, body: { kind: "team", baseRevision: 99, configuration, pending } };
    expect(configuration.bots).toHaveLength(100);
    expect(configuration.bots.filter(bot => !bot.retired)).toHaveLength(12);
    expect(encodedBytes(pending)).toBeLessThan(4 * 1048576);
    expect(encodedBytes(draft)).toBeGreaterThan(2 * 1048576);
    expect(encodedBytes(draft)).toBeLessThan(eightMiB);
    const indexedDB = new IDBFactory(), options = { scope, native: false, indexedDB, crypto };
    const store = await openDraftStore(options);
    expect((await store.read("team")).value).toBeNull(); await store.write("team", null, draft); store.close();
    const sealed = await raw(indexedDB);
    expect(sealed.records).toHaveLength(1); expect(sealed.key.extractable).toBe(false);
    await expect(crypto.subtle.exportKey("raw", sealed.key)).rejects.toThrow();
    expect(JSON.stringify(sealed.records)).not.toContain(pending.idempotency_key);
    const reopened = await openDraftStore(options);
    expect((await reopened.read("team")).value).toEqual(draft); reopened.close();
    const foreign = await openDraftStore({ ...options, scope: other });
    expect((await foreign.read("team")).value).toBeNull(); foreign.close();
  });
  it("preserves the full team body limit through browser encryption without widening notebook or account limits", async () => {
    const indexedDB = new IDBFactory(), options = { scope, native: false, indexedDB, crypto };
    const maximum = exactValueBytes(eightMiB), store = await openDraftStore(options);
    expect(encodedBytes(maximum)).toBe(eightMiB);
    await store.write("team", null, maximum);
    await expect(store.write("team", "1", exactValueBytes(eightMiB + 1))).rejects.toMatchObject({ code: "invalid" });
    for (const id of [address, "account:practice-work", "account-editor:work-routine"])
      await expect(store.write(id, null, exactValueBytes(524289))).rejects.toMatchObject({ code: "invalid" });
    store.close(); const sealed = await raw(indexedDB);
    expect((sealed.records[0] as { ciphertext: ArrayBuffer }).ciphertext.byteLength).toBe(eightMiB + 16);
    const reopened = await openDraftStore(options);
    expect((await reopened.read("team")).value).toEqual(maximum); reopened.close();
  }, 15000);
  it("recovers an exact 8 MiB native team frame after a lost commit reply and preserves CAS", async () => {
    // The transport fixture tests our JS framing/decoder, not native keychain or device acceptance.
    const fixture = nativeFixture(true), indexedDB = new IDBFactory();
    const options = { scope, native: true, indexedDB, crypto, plugin: fixture.plugin };
    const maximum = exactValueBytes(eightMiB), store = await openDraftStore(options);
    expect((await store.write("team", null, maximum)).revision).toBe("1"); store.close();
    const record = [...fixture.records.values()][0], frame = Buffer.from(record.data, "base64");
    expect(Buffer.byteLength(record.key)).toBeLessThanOrEqual(512);
    expect(frame.byteLength).toBeGreaterThan(eightMiB);
    expect(frame.byteLength).toBeLessThanOrEqual(eightMiB + 512);
    expect(record.data.length).toBe(4 * Math.ceil(frame.byteLength / 3));
    expect(frame.toString("base64")).toBe(record.data);
    const reopened = await openDraftStore(options), stale = await openDraftStore(options);
    expect((await reopened.read("team")).value).toEqual(maximum);
    await expect(reopened.write("team", "1", exactValueBytes(eightMiB + 1))).rejects.toMatchObject({ code: "invalid" });
    expect(fixture.counts()).toEqual({ creates: 1, swaps: 0 });
    await reopened.write("team", "1", value);
    await expect(stale.write("team", "1", maximum)).rejects.toMatchObject({ code: "conflict" });
    expect((await reopened.read("team")).value).toEqual(value);
    expect(fixture.counts()).toEqual({ creates: 1, swaps: 1 });
    expect((await raw(indexedDB)).records).toEqual([]);
    reopened.close(); stale.close();
  }, 30000);
  it("rejects noncanonical native base64 and oversized frames without returning draft data", async () => {
    const fixture = nativeFixture(), options = { scope, native: true, indexedDB: new IDBFactory(), crypto, plugin: fixture.plugin };
    const store = await openDraftStore(options); await store.write("team", null, value);
    const record = [...fixture.records.values()][0], canonical = record.data;
    const candidate = JSON.parse(Buffer.from(canonical, "base64").toString("utf8"));
    // Add legal whitespace after JSON so its final byte has one-byte base64 padding.
    let text = JSON.stringify(candidate); while (Buffer.byteLength(text) % 3 !== 1) text += " ";
    const padded = Buffer.from(text).toString("base64"), alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    const noncanonical = padded.slice(0, -3) + alphabet[alphabet.indexOf(padded.at(-3)!) + 1] + "==";
    expect(Buffer.from(noncanonical, "base64")).toEqual(Buffer.from(padded, "base64"));
    for (const data of [canonical + "!", padded.replace(/=+$/, ""), noncanonical,
      Buffer.alloc(eightMiB + 513).toString("base64")]) {
      fixture.records.set(record.key, { ...record, data });
      await expect(store.read("team")).rejects.toMatchObject({ code: "integrity" });
    }
    fixture.records.set(record.key, record); expect((await store.read("team")).value).toEqual(value);
    store.close();
  }, 15000);
  it("encrypts follow-up drafts under distinct encounter/ticket addresses and rejects unbound targets", async () => {
    const indexedDB=new IDBFactory(),options={scope,native:false,indexedDB,crypto};
    const prefix="editor:00000000-0000-4000-8000-000000000021:";
    const ticket="00000000-0000-4000-8000-000000000031";
    const addresses=[prefix+"follow-up-proposal",prefix+"follow-up-result:"+ticket,prefix+"appointments",prefix+"prep-work"];
    const store=await openDraftStore(options);
    for(const id of addresses)await store.write(id,null,value);
    await expect(store.write(prefix+"follow-up-result:unbound",null,value)).rejects.toMatchObject({code:"invalid"});
    await expect(store.write("editor:unbound:appointments",null,value)).rejects.toMatchObject({code:"invalid"});
    await expect(store.write("editor:unbound:prep-work",null,value)).rejects.toMatchObject({code:"invalid"});
    store.close();const sealed=await raw(indexedDB);expect(sealed.records).toHaveLength(4);
    expect(JSON.stringify(sealed.records)).not.toContain("Invented private draft");
    const reopened=await openDraftStore(options);
    for(const id of addresses)expect((await reopened.read(id)).value).toEqual(value);
    expect((await reopened.read(prefix+"follow-up-result:00000000-0000-4000-8000-000000000032")).value).toBeNull();
    reopened.close();
  });
  it("retains account work without an encounter and isolates the same address between owners", async () => {
    const indexedDB=new IDBFactory(),options={scope,native:false,indexedDB,crypto};
    const id="account:practice-work";
    const request={...value,body:{kind:"account-operation",lane:"practice-work",pending:{type:"complete",ticketId:"00000000-0000-4000-8000-000000000031",body:{revision_id:"00000000-0000-4000-8000-000000000032",payload_hash:"c".repeat(64),idempotency_key:"retained-work-result",evidence:"Invented private result"}}}};
    const store=await openDraftStore(options);await store.write(id,null,request);
    const forms=["account-editor:work-routine","account-editor:practice-result:00000000-0000-4000-8000-000000000031"];
    for(const form of forms)await store.write(form,null,value);
    await expect(store.write("account-editor:practice-result:unbound",null,value)).rejects.toMatchObject({code:"invalid"});
    await expect(store.write("account:unknown",null,request)).rejects.toMatchObject({code:"invalid"});
    store.close();const sealed=await raw(indexedDB);
    expect(JSON.stringify(sealed.records)).not.toContain("Invented private result");
    const reopened=await openDraftStore(options);expect((await reopened.read(id)).value).toEqual(request);
    for(const form of forms)expect((await reopened.read(form)).value).toEqual(value);
    expect((await reopened.read(address)).value).toBeNull();reopened.close();
    const foreign=await openDraftStore({...options,scope:other});expect((await foreign.read(id)).value).toBeNull();foreign.close();
  });
});
