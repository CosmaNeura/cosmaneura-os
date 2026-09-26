// @ts-expect-error Vitest supplies Node crypto; production uses browser types.
import { webcrypto } from "node:crypto";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import golden from "../../tests/fixtures/capture_working.json";
import sourceGolden from "../../tests/fixtures/capture_source.json";
import { captureRecoveryHash, type CaptureSourceEnvelope } from "../../clients/capture/src/bff/source-contracts";
import { recoveryRequestHash } from "../../clients/capture/src/bff/recovery-contracts";
import { workingHash } from "./capture-working-api";
import { correctWorking, readWorking, validateWorking, type WorkingReceipt } from "./capture-working-api";
const workspace = "00000000-0000-4000-8000-000000000002", session = golden.raw.session_id, raw = golden.raw.id;
const identity = {mode:"clerk_jwt" as const,getToken:vi.fn().mockResolvedValue("synthetic-token")};
const base = golden.base as WorkingReceipt, second = golden.second as WorkingReceipt;
const envelope = (receipt: unknown, operation = "working_transcript") => ({workspace_id:workspace,session_id:session,operation,receipt});
const json = (value: unknown) => new Response(JSON.stringify(value), {headers:{"Content-Type":"application/json","Cache-Control":"no-store"}});
beforeEach(() => { vi.stubGlobal("crypto",webcrypto); vi.stubEnv("VITE_API_BASE","http://127.0.0.1:8018"); identity.getToken.mockClear(); });
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });
it("validates independent Scribe golden hashes and sends a signed current read", async () => {
  for (const value of [base,second,golden.third]) expect(await validateWorking(value,session,raw)).toEqual(value);
  const fetcher=vi.fn().mockResolvedValue(json(envelope(base))); vi.stubGlobal("fetch",fetcher);
  expect(await readWorking(workspace,session,raw,identity)).toEqual(base);
  expect(identity.getToken).toHaveBeenCalledWith({skipCache:true});
  expect(JSON.parse(fetcher.mock.calls[0][1].body).operation).toEqual({kind:"working_transcript"});
});
it("reuses an exact correction body/key and verifies its returned successor", async () => {
  const fetcher=vi.fn().mockResolvedValueOnce(json(envelope(second,"correct_transcript"))).mockResolvedValueOnce(json(envelope(second,"correct_transcript")));
  vi.stubGlobal("fetch",fetcher); const key=crypto.randomUUID();
  for (let i=0;i<2;i++) expect(await correctWorking(workspace,identity,base,golden.correction.corrections as never,key)).toEqual(second);
  expect(fetcher.mock.calls[0][1].body).toEqual(fetcher.mock.calls[1][1].body);
  expect(JSON.parse(fetcher.mock.calls[0][1].body).operation.payload).toEqual(golden.correction);
});
it("saves a multi-segment Unicode correction above the previous whole-visit limit", async () => {
  const next = structuredClone(second);
  const edits = next.working_source.segments.map(segment => ({source_segment_id:segment.source_segment_id,
    speaker_role:segment.speaker_role,content:"🩺".repeat(100_000)}));
  for (let i = 0; i < edits.length; i++) {
    Object.assign(next.working_source.segments[i], {content:edits[i].content,source_segment_version:2});
    Object.assign(next.working_transcript.segments[i], {content:edits[i].content,source_segment_version:2});
  }
  next.working_sha256 = await workingHash({raw_transcript_sha256:next.raw_transcript_sha256,
    working_source:next.working_source});
  const fetcher=vi.fn().mockResolvedValue(json(envelope(next,"correct_transcript")));
  vi.stubGlobal("fetch",fetcher);
  expect(await correctWorking(workspace,identity,base,edits,crypto.randomUUID())).toEqual(next);
  expect(JSON.parse(fetcher.mock.calls[0][1].body).operation.payload.corrections).toEqual(edits);
});
it.each(["hash","raw","session","projection","origin","blockers","actor","extra","scope"])("rejects malformed or misbound working data: %s", async fault => {
  const packet=structuredClone(envelope(second)); const value=packet.receipt as WorkingReceipt;
  if(fault==="hash") value.working_sha256="a".repeat(64);
  if(fault==="raw") value.raw_transcript_id=workspace;
  if(fault==="session") value.session_id=workspace;
  if(fault==="projection") value.working_transcript.segments[0].content="private_sentinel";
  if(fault==="origin") value.working_transcript.segments[0].speaker_role="patient";
  if(fault==="blockers") value.working_transcript.note_ready=false;
  if(fault==="actor") value.corrected_by_practitioner_id=null;
  if(fault==="extra") Object.assign(value,{private_sentinel:"untrusted"});
  if(fault==="scope") packet.workspace_id=session;
  vi.stubGlobal("fetch",vi.fn().mockResolvedValue(json(packet)));
  await expect(readWorking(workspace,session,raw,identity)).rejects.toMatchObject({code:"capture_receipt_invalid"});
});
it("does not accept a later revision as the receipt for this exact save", async () => {
  vi.stubGlobal("fetch",vi.fn().mockResolvedValue(json(envelope(golden.third,"correct_transcript"))));
  await expect(correctWorking(workspace,identity,base,golden.correction.corrections as never,crypto.randomUUID())).rejects.toMatchObject({code:"capture_receipt_invalid"});
});
it.each(["", "private\0sentinel", "private\ud800sentinel"])("rejects invalid correction text before fetch", async content => {
  const fetcher=vi.fn();vi.stubGlobal("fetch",fetcher);
  await expect(correctWorking(workspace,identity,base,[{...golden.correction.corrections[0],speaker_role:"clinician",content}],crypto.randomUUID())).rejects.toBeDefined();
  expect(fetcher).not.toHaveBeenCalled();
});

it("reads and retries corrections through the qualified source with unchanged raw and gap evidence", async () => {
  const source = sourceGolden.base as CaptureSourceEnvelope, next = sourceGolden.second as CaptureSourceEnvelope;
  const fetcher = vi.fn().mockResolvedValueOnce(json(envelope(source, "capture_source")))
    .mockResolvedValueOnce(json(envelope(next, "correct_capture_source")))
    .mockResolvedValueOnce(json(envelope(next, "correct_capture_source")));
  vi.stubGlobal("fetch", fetcher);
  expect(await readWorking(workspace, session, source.raw_transcript.id, identity, undefined, source)).toEqual(source.working_transcript);
  const key = crypto.randomUUID();
  for (let i = 0; i < 2; i++) expect(await correctWorking(workspace, identity, source.working_transcript,
    sourceGolden.correction.corrections as never, key, undefined, source)).toEqual(next.working_transcript);
  expect(JSON.parse(fetcher.mock.calls[0][1].body).operation.kind).toBe("capture_source");
  expect(fetcher.mock.calls[1][1].body).toEqual(fetcher.mock.calls[2][1].body);
  expect(JSON.parse(fetcher.mock.calls[1][1].body).operation).toEqual({kind:"correct_capture_source",payload:sourceGolden.correction});
});
it("rejects a validly rehashed but changed gap manifest in a qualified read", async () => {
  const source = sourceGolden.base as CaptureSourceEnvelope, changed = structuredClone(source);
  const row = changed.recovery_history.recoveries[0]; row.request.reason_code = "audio_route_changed";
  row.request_sha256 = await recoveryRequestHash(row.request);
  changed.recovery_sha256 = await captureRecoveryHash(changed.recovery_history);
  changed.source_sha256 = await workingHash({raw_transcript_sha256:changed.working_transcript.raw_transcript_sha256,
    working_sha256:changed.working_transcript.working_sha256,recovery_sha256:changed.recovery_sha256});
  vi.stubGlobal("fetch",vi.fn().mockResolvedValue(json(envelope(changed,"capture_source"))));
  await expect(readWorking(workspace,session,source.raw_transcript.id,identity,undefined,source)).rejects.toMatchObject({code:"capture_receipt_invalid"});
});
it("does not fall back to a legacy transcript when qualified access is unavailable", async () => {
  const source = sourceGolden.base as CaptureSourceEnvelope;
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({detail:"capture_source_unavailable"}),
    {status:503,headers:{"Content-Type":"application/json","Cache-Control":"no-store"}}));
  vi.stubGlobal("fetch",fetcher);
  await expect(readWorking(workspace,session,source.raw_transcript.id,identity,undefined,source)).rejects.toBeDefined();
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(JSON.parse(fetcher.mock.calls[0][1].body).operation.kind).toBe("capture_source");
});
