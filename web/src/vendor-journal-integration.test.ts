import { describe, expect, it } from "vitest";
import { DraftJournal, accountEditorAddress, editorAddress, type EditorDraft, type AccountEditorDraft } from "./draft-journal";
import { memoryDraftStorage } from "./draft-test-fixture";
import { emptyVendorRecovery } from "./vendor-recovery";
import { prepareVendorOperation } from "./vendor-operation";
import actual from "./__fixtures__/vendor-work/actual-http-r2.json";

const wid = actual.options.workspace_id;
const tid = actual.detail_pending.summary.ticket_id;

describe("vendor work in the existing draft journal", () => {
  it("retains an exact approved command across journal loss without creating another request", async () => {
    const scope = {kind:"workspace" as const,id:wid};
    const item = actual.detail_pending;
    const operation = await prepareVendorOperation(scope, "decide", tid, {
      expected_version:item.summary.version, operation_id:item.summary.operation_id,
      revision_id:item.summary.revision_id, payload_hash:item.summary.payload_hash,
      idempotency_key:actual.approval_receipt.idempotency_key, review_sha256:item.review_sha256, choice:"approve",
    });
    expect(operation.request_sha256).toBe(actual.approval_receipt.request_sha256);
    const factory = memoryDraftStorage(), options = {scope:"e".repeat(64)};
    const address = editorAddress(wid, "vendor-work");
    const draft: EditorDraft = {kind:"editor",workspaceId:wid,editor:"vendor-work",pending:null,
      data:{...emptyVendorRecovery(scope),selected_ticket_id:tid,pending:operation}};
    const journal = new DraftJournal(await factory(options)); await journal.load(address);
    await journal.persist(address, draft); journal.close();
    const reopened = new DraftJournal(await factory(options));
    expect(await reopened.load(address)).toEqual(draft);
    const altered = structuredClone(draft);
    (altered.data as {pending:{request:{choice:string}}}).pending.request.choice = "reject";
    await expect(reopened.persist(address, altered)).rejects.toMatchObject({code:"integrity"});
    expect(await reopened.load(address)).toEqual(draft);
    reopened.close();
  });

  it("keeps staff recovery bound to its published ticket and excludes private attachments", async () => {
    const scope = {kind:"practice_work" as const,id:tid};
    const factory = memoryDraftStorage(), journal = new DraftJournal(await factory({scope:"f".repeat(64)}));
    const editor = `vendor-work:${tid}` as const, address = accountEditorAddress(editor);
    await journal.load(address);
    const draft: AccountEditorDraft = {kind:"account-editor",editor,pending:null,data:emptyVendorRecovery(scope)};
    await journal.persist(address, draft);
    const foreign = {...draft,data:{...emptyVendorRecovery(scope),scope:{...scope,id:wid}}};
    await expect(journal.persist(address, foreign)).rejects.toMatchObject({code:"integrity"});
    const attachment = {...draft,data:{...emptyVendorRecovery(scope),raw_pdf:"JVBERi0="}};
    await expect(journal.persist(address, attachment)).rejects.toMatchObject({code:"integrity"});
    await expect(journal.persist(address, {...draft,pending:tid})).rejects.toMatchObject({code:"integrity"});
    expect(await journal.load(address)).toEqual(draft); journal.close();
  });
});
