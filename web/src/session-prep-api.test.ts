import {afterEach, expect, it, vi} from "vitest";
import {request} from "./capture-api";
import {parseSessionPrep, readSessionPrep} from "./session-prep-api";
import {sessionPrepFixture} from "./test-fixtures/session-prep";
vi.mock("./capture-api", () => ({request: vi.fn()}));
const response = (receipt = sessionPrepFixture()) => ({contract_version: 1, workspace_id: "workspace-invented", receipt});
afterEach(() => vi.clearAllMocks());
it.each(["ready", "pending", "refreshing", "unavailable"] as const)("preserves the %s state without automatically opening another action", async state => {
  const value = sessionPrepFixture(state); vi.mocked(request).mockResolvedValue(response(value));
  const identity = {mode: "clerk_jwt" as const, getToken: vi.fn()}, bot = {address: "visit_prep", team_revision: 1}, signal = new AbortController().signal;
  expect(await readSessionPrep("workspace-invented", identity, bot, signal)).toEqual(value);
  expect(request).toHaveBeenCalledExactlyOnceWith("workspace-invented", "prep", identity,
    {view: "brief", bot, idempotency_key: expect.any(String)}, signal, 262144, 90000);
});
it.each(["workspace", "citation", "raw_id", "patient_source", "partial", "pending_text", "unknown", "future"]) (
  "withholds a receipt with an invalid %s binding", fault => {
    const r = response(sessionPrepFixture(fault === "pending_text" ? "pending" : "ready"));
    if (fault === "workspace") r.workspace_id = "different-workspace";
    else if (fault === "citation") r.receipt.prepared_brief!.recap.source_refs = ["c".repeat(64)];
    else if (fault === "raw_id") r.receipt.sources[0].source_id = "source_private_reference";
    else if (fault === "patient_source") r.receipt.prepared_brief!.patient_reported = {label: "Patient-reported Visit Prep", summary: "Private sentinel", source_refs: ["a".repeat(64)]};
    else if (fault === "partial") r.receipt.completeness = "partial";
    else if (fault === "pending_text") r.receipt.prepared_brief = sessionPrepFixture().prepared_brief;
    else if (fault === "future") r.receipt.generated_at = "2099-01-01T00:00:00Z";
    else Object.assign(r.receipt, {mount_context: "Private sentinel"});
    expect(() => parseSessionPrep(r, "workspace-invented")).toThrow(expect.objectContaining({status: 503, code: "session_prep_receipt_invalid"}));
});
