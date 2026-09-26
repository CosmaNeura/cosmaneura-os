// @ts-expect-error Vitest supplies Node crypto; production uses browser types.
import {webcrypto} from "node:crypto";
import {beforeEach, afterEach, expect, it, vi} from "vitest";
import {request} from "./capture-api";
import {readEncounterPrep} from "./encounter-prep-api";
vi.mock("./capture-api", () => ({request: vi.fn(), CAPTURE_WORKSPACE_BUILD: true}));
const workspace = "00000000-0000-4000-8000-000000000002";
const ref = (type: string) => (type === "appointment" ? "a" : "b").repeat(64);
const identity = {mode: "clerk_jwt" as const, getToken: vi.fn()};
const bot = {address: "visit_prep", team_revision: 2};
function canonical(value: any): string { return Array.isArray(value) ? `[${value.map(canonical).join(",")}]` : value && typeof value === "object" ? `{${Object.keys(value).sort().map(k => `${JSON.stringify(k)}:${canonical(value[k])}`).join(",")}}` : JSON.stringify(value); }
async function value() {
  const receipt = {appointment_ref:ref("appointment"), sources:[{source_id:ref("intake"),appointment_ref:ref("appointment"),kind:"patient_intake_summary",
    label:"Patient intake · AI summary",source_at:"2026-09-19T10:00:00Z",content_sha256:[...new Uint8Array(await crypto.subtle.digest("SHA-256",new TextEncoder().encode("Invented 🩺 intake")))].map(v=>v.toString(16).padStart(2,"0")).join(""),content:"Invented 🩺 intake",truncated:false,content_redacted:false}],additional_notes_available:false,snapshot_sha256:"c".repeat(64)};
  const hash = [...new Uint8Array(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(canonical(receipt))))].map(v=>v.toString(16).padStart(2,"0")).join("");
  return {workspace_id:workspace,receipt:{...receipt,display_sha256:hash}};
}
beforeEach(() => {vi.clearAllMocks(); vi.stubGlobal("crypto",webcrypto);});
afterEach(() => vi.unstubAllGlobals());
it("carries exact bot selection and validates the returned source snapshot",async()=>{
  const result=await value(); vi.mocked(request).mockResolvedValue(result);
  expect(await readEncounterPrep(workspace,identity,bot)).toEqual(result.receipt);
  expect(vi.mocked(request).mock.calls[0][3]).toEqual({idempotency_key:expect.any(String),bot});
});
it.each(["scope","hash","content","source","extra"])("rejects changed %s",async fault=>{
  const result:any=await value();
  if(fault==="scope")result.workspace_id="different";
  if(fault==="hash")result.receipt.snapshot_sha256="0".repeat(64);
  if(fault==="content")result.receipt.sources[0].content="Substituted";
  if(fault==="source")result.receipt.sources[0].kind="clinician_finalized_note";
  if(fault==="extra")result.receipt.authority=true;
  vi.mocked(request).mockResolvedValue(result);
  await expect(readEncounterPrep(workspace,identity,bot)).rejects.toMatchObject({code:"capture_receipt_invalid"});
});
