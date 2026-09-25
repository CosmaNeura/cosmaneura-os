import { expect, it } from "vitest";
import { DraftJournal, editorAddress, type EditorDraft } from "./draft-journal";
import { memoryDraftStorage } from "./draft-test-fixture";
import { emptyFinanceRecovery } from "./finance-recovery";
import { actualFinanceApproval, actualFinanceOptions } from "./finance-test-fixture";

it("retains an exact payment approval after reopen without confusing it with a processor submission",async()=>{
  const factory=memoryDraftStorage(),options={scope:"9".repeat(64)},wid=actualFinanceOptions().workspace_id;
  const pending=await actualFinanceApproval(),address=editorAddress(wid,"finance-work");
  const data={...emptyFinanceRecovery({kind:"workspace",id:wid}),pending};
  const draft:EditorDraft={kind:"editor",workspaceId:wid,editor:"finance-work",pending:null,data};
  const journal=new DraftJournal(await factory(options));await journal.load(address);await journal.persist(address,draft);journal.close();
  const reopened=new DraftJournal(await factory(options));expect(await reopened.load(address)).toEqual(draft);expect(pending.kind).toBe("decide");
  const altered=structuredClone(draft);(altered.data as {pending:{request:{payload_hash:string}}}).pending.request.payload_hash="f".repeat(64);
  await expect(reopened.persist(address,altered)).rejects.toMatchObject({code:"integrity"});
  await expect(reopened.persist(address,{...draft,data:{...data,scope:{kind:"workspace",id:"00000000-0000-4000-8000-000000000001"}}})).rejects.toMatchObject({code:"integrity"});
  await expect(reopened.persist(address,{...draft,data:{...data,charge_confirmed:true}})).rejects.toMatchObject({code:"integrity"});
  expect(await reopened.load(address)).toEqual(draft);reopened.close();
});
