// @ts-expect-error Vitest supplies Node crypto; the production tsconfig uses browser types.
import { createHash, webcrypto } from "node:crypto";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { captureDraft, captureNoteTemplates, resolveCaptureSave, saveCaptureDraft, type CaptureDraft, type CaptureNoteEdit, type CaptureSaveResolution } from "./capture-notes-api";
import gapFixture from "../../tests/fixtures/capture_gap_draft.json";
import resolutionFixture from "../../tests/fixtures/capture_note_save_resolution.json";
const resolutionCases=resolutionFixture.cases as unknown as Array<{name:string;workspace_id:string;base:CaptureDraft;
  fields:Record<string,string>;edit:CaptureNoteEdit;receipt:CaptureSaveResolution}>;

const workspace = "00000000-0000-4000-8000-000000000002";
const session = "00000000-0000-4000-8000-000000000003";
const source = "00000000-0000-4000-8000-000000000004";
const ref = (kind: string) => `${kind}_${"0".repeat(25)}1`;
const access = { mode: "clerk_jwt" as const, getToken: vi.fn().mockResolvedValue("synthetic-token") };
const json = (body: unknown) => new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });
function draft() {
  const fields = { "1": "First numeric field", "2": "Second numeric field", "Plan": "Invented sleep discussion — follow-up." };
  const field_order = ["2", "1", "Plan"];
  return { session_id: session, scribe_source_id: source, source_sha256: "a".repeat(64), schema_ref: ref("doctor_note_schema"),
    transcript_ref: ref("ai_visit_transcript"), note_ref: ref("visit_note"), status: "draft", note_type: "Visit note", fields, field_order,
    note_sha256: createHash("sha256").update(JSON.stringify(field_order.map(key => [key, fields[key as keyof typeof fields]]))).digest("hex"),
    created_at: "2026-09-17T09:00:00Z", review_required: true };
}
function envelope(receipt: unknown, action = "read") { return { workspace_id: workspace, session_id: session, action, receipt }; }
beforeEach(() => { vi.stubEnv("VITE_API_BASE", "http://127.0.0.1:8018"); vi.stubGlobal("crypto", webcrypto); access.getToken.mockClear(); });
afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

it.each(resolutionCases)("validates Core's exact $name resolution hash and original request",async test=>{
  for (const status of ["saved","closed"]) {
    const receipt={...test.receipt,status,...(status==="closed"?{result_note_ref:null,result_sha256:null}:{})};
    const fetch=vi.fn().mockImplementation(async()=>json(envelope(receipt,"resolve")));vi.stubGlobal("fetch",fetch);
    expect(await resolveCaptureSave(test.workspace_id,access,test.base,test.fields,test.edit.client_key)).toEqual(receipt);
    const request=JSON.parse(fetch.mock.calls[0][1].body);
    expect(request.note).toEqual({action:"resolve",schema_ref:test.base.schema_ref,edit:test.edit});
    expect(request.idempotency_key).toBe(test.edit.client_key);
  }
});

it.each(["key","request","result_hash","result_ref","extra","status","closed_with_result"])("withholds a substituted save resolution: %s",async fault=>{
  const test=resolutionCases[0],receipt:Record<string,unknown>={...test.receipt};
  if(fault==="key")receipt.client_key=workspace;
  else if(fault==="request")receipt.request_sha256="f".repeat(64);
  else if(fault==="result_hash")receipt.result_sha256="f".repeat(64);
  else if(fault==="result_ref")receipt.result_note_ref=test.base.note_ref;
  else if(fault==="extra")receipt.reviewed=true;
  else receipt.status=fault==="status"?"reviewed":"closed";
  vi.stubGlobal("fetch",vi.fn().mockResolvedValue(json(envelope(receipt,"resolve"))));
  await expect(resolveCaptureSave(test.workspace_id,access,test.base,test.fields,test.edit.client_key)).rejects.toMatchObject({code:"capture_receipt_invalid"});
});

it("preserves actual Core gap review evidence in the exact draft", async () => {
  const value = gapFixture.draft;
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(envelope(value))));
  expect(await captureDraft(workspace, value.session_id, value.scribe_source_id, access, value.schema_ref, "read")).toEqual(value);
});

it.each(["null", "empty", "duplicate", "extra", "boolean", "time"])("rejects invalid gap evidence: %s", async fault => {
  const value = structuredClone(gapFixture.draft);
  if (fault === "null") Object.assign(value, {capture_gap_review: null});
  if (fault === "empty") value.capture_gap_review.observations = [];
  if (fault === "duplicate") value.capture_gap_review.observations.push({...value.capture_gap_review.observations[0]});
  if (fault === "extra") Object.assign(value.capture_gap_review, {missing_minutes: 4});
  if (fault === "boolean") Object.assign(value.capture_gap_review, {review_required: 1});
  if (fault === "time") value.capture_gap_review.observations[0].observed_at = "2100-01-01T00:00:00Z";
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(envelope(value))));
  await expect(captureDraft(workspace, value.session_id, value.scribe_source_id, access, value.schema_ref, "read"))
    .rejects.toMatchObject({code: "capture_receipt_invalid"});
});

it("checks exact content and preserves numeric field ordering", async () => {
  const receipt = draft();
  const fetchMock = vi.fn().mockResolvedValue(json(envelope(receipt)));
  vi.stubGlobal("fetch", fetchMock);
  expect(await captureDraft(workspace, session, source, access, ref("doctor_note_schema"), "read")).toEqual(receipt);
  const body = JSON.parse(fetchMock.mock.calls[0][1].body);
  expect(body.note).toEqual({ action: "read", schema_ref: ref("doctor_note_schema") });
  expect(body.session_id).toBe(session);
  expect(body).not.toHaveProperty("fields");
  expect(access.getToken).toHaveBeenCalledWith({ skipCache: true });
});

it("sends only the saved notebook reference and verifies Core's returned source identity", async () => {
  const notebook_source = {kind: "clinician_scratch_notes", workspace_id: workspace,
    entry_id: "00000000-0000-4000-8000-000000000005", revision: 4, content_sha256: "c".repeat(64)};
  const value = {...draft(), notebook_source};
  const fetchMock = vi.fn().mockResolvedValueOnce(json(envelope(value, "prepare")));
  vi.stubGlobal("fetch", fetchMock);
  const bot = {address: "scribe", team_revision: 2};
  expect(await captureDraft(workspace, session, source, access, ref("doctor_note_schema"), "prepare", undefined,
    notebook_source.entry_id, bot)).toEqual(value);
  const body = JSON.parse(fetchMock.mock.calls[0][1].body);
  expect(body.scratchpad_entry_id).toBe(notebook_source.entry_id);
  expect(body.bot).toEqual(bot);
  expect(body.note).toEqual({action: "prepare", schema_ref: ref("doctor_note_schema")});
  fetchMock.mockResolvedValueOnce(json(envelope({...value, notebook_source: {...notebook_source, workspace_id: session}})));
  await expect(captureDraft(workspace, session, source, access, ref("doctor_note_schema"), "read"))
    .rejects.toMatchObject({code: "capture_receipt_invalid"});
  fetchMock.mockResolvedValueOnce(json(envelope(draft(), "prepare")));
  await expect(captureDraft(workspace, session, source, access, ref("doctor_note_schema"), "prepare", undefined, notebook_source.entry_id))
    .rejects.toMatchObject({code: "capture_receipt_invalid"});
});

it("loads bounded choices for the same admitted recording", async () => {
  const templates = [{ schema_ref: ref("doctor_note_schema"), note_type: "Visit note", field_names: ["CC", "Plan"] }];
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(envelope({ session_id: session, templates }, "templates"))));
  expect(await captureNoteTemplates(workspace, session, access)).toEqual(templates);
});

it.each(["source", "session", "schema", "hash", "content", "order", "extra", "reviewed", "unprepared", "scope"])(
  "rejects invalid draft content or scope: %s", async fault => {
    const receipt = draft(); const value = envelope(receipt);
    if (fault === "source") receipt.scribe_source_id = workspace;
    if (fault === "session") receipt.session_id = workspace;
    if (fault === "schema") receipt.schema_ref = ref("doctor_note_schema").slice(0, -1) + "2";
    if (fault === "hash") receipt.note_sha256 = "b".repeat(64);
    if (fault === "content") receipt.fields.Plan = "Changed private sentinel";
    if (fault === "order") receipt.field_order.reverse();
    if (fault === "extra") Object.assign(receipt, { private_sentinel: "Not allowed" });
    if (fault === "reviewed") receipt.review_required = false;
    if (fault === "unprepared") receipt.status = "not_prepared";
    if (fault === "scope") value.workspace_id = session;
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(value)));
    await expect(captureDraft(workspace, session, source, access, ref("doctor_note_schema"), "read"))
      .rejects.toMatchObject({ code: "capture_receipt_invalid" });
  });

it("rejects duplicate templates", async () => {
  const item = { schema_ref: ref("doctor_note_schema"), note_type: "Visit", field_names: ["CC"] };
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(envelope({ session_id: session, templates: [item, item] }, "templates"))));
  await expect(captureNoteTemplates(workspace, session, access)).rejects.toMatchObject({ code: "capture_receipt_invalid" });
});

it("retries the same complete edit request bound to the opened note and source hashes", async () => {
  const base = draft() as CaptureDraft;
  const fields = {...base.fields, Plan:"An explicit synthetic correction"};
  const updated = {...base, fields, note_ref:ref("visit_note").slice(0,-1)+"2",
    note_sha256:createHash("sha256").update(JSON.stringify(base.field_order!.map(key => [key,fields[key as keyof typeof fields]]))).digest("hex")};
  const key = "00000000-0000-4000-8000-000000000009";
  const fetchMock=vi.fn().mockImplementation(async () => json(envelope(updated,"save"))); vi.stubGlobal("fetch",fetchMock);
  expect(await saveCaptureDraft(workspace,access,base,fields,key)).toEqual(updated);
  expect(await saveCaptureDraft(workspace,access,base,fields,key)).toEqual(updated);
  expect(fetchMock.mock.calls[1][1].body).toBe(fetchMock.mock.calls[0][1].body);
  const body=JSON.parse(fetchMock.mock.calls[0][1].body);
  expect(body.idempotency_key).toBe(key);
  expect(body.note.edit).toEqual({client_key:key, expected_note_ref:base.note_ref,
    expected_note_sha256:base.note_sha256, expected_source_sha256:base.source_sha256,fields});
  expect(body.note.action).toBe("save");
});

it("does not accept a validly hashed receipt for a different edit", async () => {
  const base=draft() as CaptureDraft;
  vi.stubGlobal("fetch",vi.fn().mockResolvedValue(json(envelope({...base,note_ref:ref("visit_note").slice(0,-1)+"2"},"save"))));
  await expect(saveCaptureDraft(workspace,access,base,{...base.fields,Plan:"My correction"},"00000000-0000-4000-8000-000000000009"))
    .rejects.toMatchObject({code:"capture_receipt_invalid"});
});
