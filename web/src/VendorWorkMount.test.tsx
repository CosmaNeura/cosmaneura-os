// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { VendorWorkspaceMount, VendorPracticeMount } from "./VendorWorkMount";
import { EditorRecoveryContext } from "./editor-recovery";
import { AccountRecoveryContext } from "./account-recovery";
import { DraftJournal, editorAddress, accountEditorAddress } from "./draft-journal";
import { memoryDraftStorage } from "./draft-test-fixture";
import { vendorApi } from "./vendor-api";
import { actualOptions, actualDetail, actualShared } from "./vendor-test-fixture";
import { emptyVendorRecovery } from "./vendor-recovery";
import { prepareVendorOperation } from "./vendor-operation";

Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});
const identity={mode:"clerk_jwt" as const,getToken:async()=>"invented-test-token"};
const containers:HTMLDivElement[]=[],roots:ReturnType<typeof createRoot>[]=[],journals:DraftJournal[]=[];
afterEach(async()=>{for(const root of roots.splice(0))await act(async()=>root.unmount());for(const container of containers.splice(0))container.remove();for(const journal of journals.splice(0))journal.close();vi.restoreAllMocks();});
async function setup(){
  const container=document.createElement("div");document.body.append(container);containers.push(container);
  const root=createRoot(container);roots.push(root);
  const journal=new DraftJournal(await memoryDraftStorage()({scope:"e".repeat(64)}));journals.push(journal);
  return {root,container,journal};
}
async function until(test:()=>void){let error:unknown;for(let i=0;i<100;i++){try{test();return;}catch(e){error=e;}await act(async()=>{await new Promise(resolve=>setTimeout(resolve,5));});}throw error;}
const button=(container:HTMLElement,label:string)=>Array.from(container.querySelectorAll("button")).find(b=>b.textContent===label)!;

it("restores an exact pending owner command through the real workspace journal without sending it",async()=>{
  const {root,container,journal}=await setup(),options=actualOptions(),detail=actualDetail(),wid=options.workspace_id;
  vi.spyOn(vendorApi,"options").mockResolvedValue(options);vi.spyOn(vendorApi,"catalog").mockResolvedValue({contract_version:1,observed_at:options.observed_at,workspace_id:wid,items:[],next_cursor:null});
  const execute=vi.spyOn(vendorApi,"execute"),recover=vi.spyOn(vendorApi,"recover");
  const scope={kind:"workspace" as const,id:wid},pending=await prepareVendorOperation(scope,"submit",detail.summary.ticket_id,{
    expected_version:detail.summary.version,operation_id:detail.summary.operation_id,revision_id:detail.summary.revision_id,payload_hash:detail.summary.payload_hash,idempotency_key:"mount-saved-submit"});
  const address=editorAddress(wid,"vendor-work");await journal.load(address);
  await journal.persist(address,{kind:"editor",editor:"vendor-work",workspaceId:wid,pending:null,data:{...emptyVendorRecovery(scope),pending}});
  const authorize=vi.fn(async()=>({id:wid,appointment_id:wid,label:"Invented workspace",revision:options.entry_revision,entries:[],work_candidates:[]})),denied=vi.fn();
  await act(async()=>root.render(<EditorRecoveryContext.Provider value={{workspaceId:wid,journal,authorize,denied}}><VendorWorkspaceMount identity={identity} workspaceId={wid}/></EditorRecoveryContext.Provider>));
  await until(()=>expect(button(container,"Restore delivery draft")).toBeDefined());
  await act(async()=>button(container,"Restore delivery draft").click());
  await until(()=>expect(container.textContent).toContain("Private draft restored"));
  const loaded=await journal.load(address);expect(loaded?.kind==="editor"&&loaded.data).toMatchObject({pending});
  expect(authorize.mock.calls.length).toBeGreaterThanOrEqual(2);expect(execute).not.toHaveBeenCalled();expect(recover).not.toHaveBeenCalled();
});

it("uses the independent account journal for staff work and exposes no private delivery controls",async()=>{
  const {root,container,journal}=await setup(),item=actualShared();
  vi.spyOn(vendorApi,"shared").mockResolvedValue(item);const execute=vi.spyOn(vendorApi,"execute");
  const editor=`vendor-work:${item.ticket_id}` as const,address=accountEditorAddress(editor);await journal.load(address);
  await journal.persist(address,{kind:"account-editor",editor,pending:null,data:emptyVendorRecovery({kind:"practice_work",id:item.ticket_id})});
  await act(async()=>root.render(<AccountRecoveryContext.Provider value={{journal,authorize:vi.fn(async()=>{})}}><VendorPracticeMount identity={identity} item={item} people={[item.originator,item.responsible]} onDenied={vi.fn()}/></AccountRecoveryContext.Provider>));
  await until(()=>expect(button(container,"Restore delivery draft")).toBeDefined());
  await act(async()=>button(container,"Restore delivery draft").click());
  await until(()=>expect(container.textContent).toContain("Private draft restored"));
  expect(container.querySelector('input[type="file"]')).toBeNull();expect(button(container,"Approve reviewed delivery")).toBeUndefined();expect(button(container,"Send approved delivery")).toBeUndefined();
  expect(execute).not.toHaveBeenCalled();expect((await journal.load(address))?.kind).toBe("account-editor");
});
