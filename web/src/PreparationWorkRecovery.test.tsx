import {act} from "react";
import {createRoot,type Root} from "react-dom/client";
import {afterEach,beforeEach,expect,it,vi} from "vitest";
import {PreparationWorkPanel} from "./PreparationWorkPanel";
import {prepWorkApi} from "./prep-work-api";
import {prepWorkspace,prepTicket,prepBot,prepItem,prepReceipt} from "./prep-work-test-fixture";
import {DraftJournal,editorAddress,type EditorDraft} from "./draft-journal";
import {DraftStoreError,type DraftRecord,type DraftStore} from "./draft-store";
import {EditorRecoveryContext,type EditorRecoveryAccess} from "./editor-recovery";
import {WorkspaceApiError,type Workspace,type CaptureBotSelection} from "./workspace-api";
import type {EncounterPrep} from "./encounter-prep-api";
import type {PrepWorkRequest} from "./prep-work-request";
vi.mock("./prep-work-api",()=>({prepWorkApi:{catalog:vi.fn(),read:vi.fn(),save:vi.fn()}}));
const identity={mode:"clerk_jwt" as const,getToken:vi.fn()},address=editorAddress(prepWorkspace,"prep-work");
const lost=vi.fn(),changed=vi.fn();
let root:Root,container:HTMLDivElement,access:EditorRecoveryAccess,records:Map<string,DraftRecord>,failWrites:boolean;
let receipt:EncounterPrep|null,bot:CaptureBotSelection;
function makeAccess():EditorRecoveryAccess {
  let closed=false;
  const store:DraftStore={close(){closed=true;},async read(key){if(closed)throw new DraftStoreError("unavailable");return structuredClone(records.get(key)??{revision:null,value:null});},
    async write(key,expected,value){if(closed||failWrites)throw new DraftStoreError("unavailable");const prior=records.get(key)??{revision:null,value:null};
      if(prior.revision!==expected)throw new DraftStoreError("conflict");const next={revision:String(Number(expected??0)+1),value:structuredClone(value)};records.set(key,next);return next;}};
  return {journal:new DraftJournal(store),workspaceId:prepWorkspace,authorize:vi.fn().mockResolvedValue({id:prepWorkspace} as Workspace),denied:vi.fn()};
}
async function mount(context:EditorRecoveryAccess|null|undefined=access,who=identity){await act(async()=>root.render(
  <EditorRecoveryContext.Provider value={context}><PreparationWorkPanel workspaceId={prepWorkspace} identity={who} bot={bot}
    entryRevision={7} receipt={receipt} enabled locked={false} onChanged={changed} onAccessLost={lost}/></EditorRecoveryContext.Provider>));}
async function restart(){await act(async()=>root.unmount());access.journal.close();access=makeAccess();root=createRoot(container);receipt=null;await mount();}
const button=(text:string)=>[...container.querySelectorAll("button")].find(b=>b.textContent===text);
async function click(text:string){const b=button(text);expect(b,text).toBeTruthy();expect(b!.disabled,text).toBe(false);await act(async()=>b!.click());}
async function check(index=0){const input=container.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')[index];expect(input.disabled).toBe(false);await act(async()=>input.click());}
async function fill(selector:string,value:string){const input=container.querySelector(selector)!;const prototype=input instanceof HTMLTextAreaElement?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;
  await act(async()=>{Object.getOwnPropertyDescriptor(prototype,"value")!.set!.call(input,value);input.dispatchEvent(new Event("input",{bubbles:true}));input.dispatchEvent(new Event("change",{bubbles:true}));});}
async function form(){await fill("textarea",prepItem().body);await fill('input[type="date"]',"2026-09-25");await fill("label:nth-child(3) textarea",prepItem().expected_outcome);await check();}
const draft=()=>records.get(address)?.value?.body as EditorDraft|null;
const pending=()=>(draft()?.data as {pending:PrepWorkRequest})?.pending;
beforeEach(()=>{vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT",true);vi.clearAllMocks();records=new Map();failWrites=false;access=makeAccess();receipt=structuredClone(prepReceipt);bot={...prepBot};
  vi.mocked(prepWorkApi.catalog).mockResolvedValue({entry_revision:7,items:[]});vi.mocked(prepWorkApi.read).mockResolvedValue({entry_revision:7,item:prepItem()});
  vi.mocked(prepWorkApi.save).mockResolvedValue({entry_revision:8,item:prepItem()});container=document.createElement("div");document.body.append(container);root=createRoot(container);});
afterEach(async()=>{await act(async()=>root.unmount());access.journal.close();container.remove();vi.unstubAllGlobals();});

it("retains an unsent brief but never restores sharing or submits it",async()=>{
  await mount();await form();expect(draft()).toBeTruthy();await restart();expect(button("Create preparation proposal")!.disabled).toBe(true);
  await click("Restore preparation work draft");expect(access.authorize).toHaveBeenCalledOnce();expect(container.querySelector("textarea")!.value).toBe(prepItem().body);
  expect(container.querySelector<HTMLInputElement>('input[type="checkbox"]')!.checked).toBe(false);expect(prepWorkApi.save).not.toHaveBeenCalled();
  receipt=structuredClone(prepReceipt);await mount();await check();expect(button("Create preparation proposal")!.disabled).toBe(false);
});
it("journals the exact proposal before transport, retaining it across restart and source changes",async()=>{
  vi.mocked(prepWorkApi.save).mockImplementationOnce(async(_w,_i,command)=>{expect(pending()).toEqual(command);throw new WorkspaceApiError(503);});
  await mount();await form();await click("Create preparation proposal");const first=vi.mocked(prepWorkApi.save).mock.calls[0][2];
  await restart();await click("Restore preparation work draft");expect(prepWorkApi.save).toHaveBeenCalledOnce();expect(button("Discard preparation draft")).toBeUndefined();
  receipt={...prepReceipt,snapshot_sha256:"a".repeat(64)};await mount();await click("Retry same preparation request");
  expect(vi.mocked(prepWorkApi.save).mock.calls[1][2]).toEqual(first);expect(records.get(address)?.value).toBeNull();
});
it.each(["approve","reject"] as const)("retains the exact %s decision and reads its ticket outside the catalog",async choice=>{
  await mount();await form();await click("Create preparation proposal");vi.mocked(prepWorkApi.save).mockRejectedValueOnce(new WorkspaceApiError(503));
  await click(choice==="approve"?"Approve shared preparation brief":"Withdraw preparation proposal");const first=vi.mocked(prepWorkApi.save).mock.calls[1][2];
  await restart();await click("Restore preparation work draft");expect(prepWorkApi.read).toHaveBeenCalledWith(prepWorkspace,identity,prepTicket);
  expect(prepWorkApi.save).toHaveBeenCalledTimes(2);await click("Retry same preparation request");expect(vi.mocked(prepWorkApi.save).mock.calls[2][2]).toEqual(first);
});
it("requires a fresh context after staff readiness and retains exact provider verification on lost reply",async()=>{
  const ready=prepItem("approved",true);vi.mocked(prepWorkApi.catalog).mockResolvedValue({entry_revision:7,items:[ready]});vi.mocked(prepWorkApi.read).mockResolvedValue({entry_revision:7,item:ready});
  await mount();await click(`${ready.body} · Ready for provider review`);expect(button("Verify preparation and close")!.disabled).toBe(true);
  receipt=structuredClone(prepReceipt);await mount();await check(1);vi.mocked(prepWorkApi.save).mockRejectedValueOnce(new WorkspaceApiError(503));
  await click("Verify preparation and close");const first=vi.mocked(prepWorkApi.save).mock.calls[0][2];await restart();await click("Restore preparation work draft");
  expect(container.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')[1].checked).toBe(false);expect(prepWorkApi.save).toHaveBeenCalledOnce();
  await click("Retry same preparation request");expect(vi.mocked(prepWorkApi.save).mock.calls[1][2]).toEqual(first);
});
it.each(["missing","truncated","redacted"])("does not close preparation from a %s summary",async kind=>{
  const ready=prepItem("approved",true);vi.mocked(prepWorkApi.catalog).mockResolvedValue({entry_revision:7,items:[ready]});vi.mocked(prepWorkApi.read).mockResolvedValue({entry_revision:7,item:ready});
  await mount();await click(`${ready.body} · Ready for provider review`);receipt=structuredClone(prepReceipt);if(kind==="missing")receipt.sources=[];else if(kind==="truncated")receipt.sources[0].truncated=true;else receipt.sources[0].content_redacted=true;await mount();
  expect(container.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')[1].disabled).toBe(true);expect(button("Verify preparation and close")!.disabled).toBe(true);
});
it("keeps the old exact request when switching bots",async()=>{
  vi.mocked(prepWorkApi.save).mockRejectedValueOnce(new WorkspaceApiError(503));await mount();await form();await click("Create preparation proposal");const before=structuredClone(records.get(address));
  bot={address:"scribe",team_revision:2};await mount();expect(records.get(address)).toEqual(before);await click("Restore preparation work draft");expect(container.textContent).toContain("earlier bot selection");
  await click("Retry same preparation request");expect(vi.mocked(prepWorkApi.save).mock.calls[1][2]).toEqual(vi.mocked(prepWorkApi.save).mock.calls[0][2]);
});
it("retains denied work without revealing it on a rejected restore",async()=>{
  vi.mocked(prepWorkApi.save).mockRejectedValueOnce(new WorkspaceApiError(403));await mount();await form();await click("Create preparation proposal");expect(lost).toHaveBeenCalledOnce();
  const before=structuredClone(records.get(address));await restart();vi.mocked(access.authorize).mockRejectedValue(new WorkspaceApiError(403));await click("Restore preparation work draft");
  expect(records.get(address)).toEqual(before);expect(container.querySelector("textarea")!.value).toBe("");expect(prepWorkApi.save).toHaveBeenCalledOnce();
});
it("only sets aside a definite rejection after a fresh authorized read, preserving unsent text",async()=>{
  vi.mocked(prepWorkApi.save).mockRejectedValueOnce(new WorkspaceApiError(409));await mount();await form();await click("Create preparation proposal");
  expect(button("Set aside rejected preparation request")).toBeUndefined();await click("Check rejected preparation request");expect(access.authorize).toHaveBeenCalledOnce();
  await click("Set aside rejected preparation request");expect(pending()).toBeNull();expect(container.querySelector("textarea")!.value).toBe(prepItem().body);
  expect(container.querySelector<HTMLInputElement>('input[type="checkbox"]')!.checked).toBe(false);
});
it("does not offer set-aside for uncertain transport or send before a failed local write",async()=>{
  await mount();await form();failWrites=true;await click("Create preparation proposal");expect(prepWorkApi.save).not.toHaveBeenCalled();expect(button("Check rejected preparation request")).toBeUndefined();
  expect(records.get(address)?.value).toBeTruthy();
});
it.each([null,undefined])("requires authenticated editor recovery even when the context is %s",async context=>{
  await mount(context);expect(button("Create preparation proposal")!.disabled).toBe(true);expect(prepWorkApi.save).not.toHaveBeenCalled();
});
