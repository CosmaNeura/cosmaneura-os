import { expect, it } from "vitest";
import { DraftJournal, accountEditorAddress, type AccountEditorDraft } from "./draft-journal";
import { memoryDraftStorage } from "./draft-test-fixture";
import { emptyPortalRecovery, validatePortalRecovery } from "./portal-setup-recovery";
import { preparePortalOperation } from "./portal-setup-contract";

const box = "00000000-0000-4000-8000-000000000021", owner = "00000000-0000-4000-8000-000000000022";
const scope = {box_id:box,owner_id:owner};

it("reopens the exact portal activation request and rejects an altered approval", async () => {
  const factory = memoryDraftStorage(), options = {scope:"d".repeat(64)}, address = accountEditorAddress("portal_setup");
  const pending = await preparePortalOperation(scope,"activate",{
    connection_id:"00000000-0000-4000-8000-000000000023",expected_version:1,idempotency_key:"portal-activation-test",
    revision_id:"00000000-0000-4000-8000-000000000024",review_sha256:"a".repeat(64),
    reviewed_profile:true,reviewed_practice:true,reviewed_patient:true,reviewed_recipient:true,confirm_local_activation:true,
  });
  const draft:AccountEditorDraft = {kind:"account-editor",editor:"portal_setup",pending:null,data:{...emptyPortalRecovery(scope),pending}};
  const journal = new DraftJournal(await factory(options)); await journal.load(address); await journal.persist(address,draft); journal.close();
  const reopened = new DraftJournal(await factory(options)); expect(await reopened.load(address)).toEqual(draft);
  const changed = structuredClone(draft);
  (changed.data as {pending:{request:{review_sha256:string}}}).pending.request.review_sha256 = "b".repeat(64);
  await expect(reopened.persist(address,changed)).rejects.toMatchObject({code:"integrity"});
  await expect(reopened.persist(address,{...draft,pending:owner})).rejects.toMatchObject({code:"integrity"});
  expect(await reopened.load(address)).toEqual(draft); reopened.close();
});

it("keeps setup recovery in its account and refuses a foreign catalog scope or hidden fields", async () => {
  const factory = memoryDraftStorage(), address = accountEditorAddress("portal_setup");
  const journal = new DraftJournal(await factory({scope:"c".repeat(64)})); await journal.load(address);
  const data = emptyPortalRecovery(scope), draft:AccountEditorDraft = {kind:"account-editor",editor:"portal_setup",pending:null,data};
  await journal.persist(address,draft);
  await expect(validatePortalRecovery(data,{...scope,owner_id:box})).rejects.toThrow();
  await expect(journal.persist(address,{...draft,data:{...data,activation_checks:[true]}})).rejects.toMatchObject({code:"integrity"});
  const foreign = new DraftJournal(await factory({scope:"b".repeat(64)})); expect(await foreign.load(address)).toBeNull();
  journal.close(); foreign.close();
});
