import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AccountRecoveryContext, type AccountRecoveryAccess } from "./account-recovery";
import { DraftJournal, accountEditorAddress, type AccountEditorDraft } from "./draft-journal";
import { DraftStoreError, type DraftRecord, type DraftStore } from "./draft-store";
import { PracticeWork } from "./PracticeWork";
import { workspaceApi, WorkspaceApiError, type PracticeWorkItem } from "./workspace-api";
import { validPracticeOperation } from "./practice-work-request";

vi.mock("./workspace-api",async original=>({...await original<object>(),workspaceApi:{practiceWork:vi.fn(),practiceWorkItem:vi.fn(),workHandoff:vi.fn(),completeWork:vi.fn()}}));
const identity={mode:"clerk_jwt" as const,getToken:async()=>"invented-token-never-journaled"};
const id=(last:string)=>`00000000-0000-4000-8000-0000000000${last}`;
const owner={id:id("11"),name:"Invented provider",available:true},staff={id:id("12"),name:"Invented colleague",available:true};
const item:PracticeWorkItem={ticket_id:id("21"),revision_id:id("22"),payload_hash:"c".repeat(64),version:4,state:"sent",
  body:"Invented follow-up",due_date:"2026-10-01",expected_outcome:"Invented result",viewer_id:owner.id,originator:owner,responsible:owner,pending_offer:null,handoffs:[],receipts:[]};
const offered={...item,version:5,pending_offer:{id:id("31"),from:owner,to:staff}};
const address="account:practice-work";
let root:Root,element:HTMLDivElement,records:Map<string,DraftRecord>,access:AccountRecoveryAccess,failWrite:boolean,failClear:boolean;
const changed=vi.fn(),lost=vi.fn();
function makeAccess():AccountRecoveryAccess {
  let closed=false;
  const store:DraftStore={close(){closed=true;},async read(key){if(closed)throw new DraftStoreError("unavailable");return structuredClone(records.get(key)??{revision:null,value:null});},
    async write(key,expected,value){
      if(closed || failWrite || failClear && value===null)throw new DraftStoreError("unavailable");
      const previous=records.get(key)??{revision:null,value:null};if(previous.revision!==expected)throw new DraftStoreError("conflict");
      const saved={revision:String(Number(expected??0)+1),value:structuredClone(value)};records.set(key,saved);return saved;
    }};
  return {journal:new DraftJournal(store),authorize:vi.fn().mockResolvedValue(undefined)};
}
async function render(context:AccountRecoveryAccess|null|undefined=access){
  await act(async()=>root.render(<AccountRecoveryContext.Provider value={context}><PracticeWork identity={identity} onChanged={changed} onAccessLost={lost}/></AccountRecoveryContext.Provider>));
}
async function restart(){await act(async()=>root.unmount());access.journal.close();access=makeAccess();root=createRoot(element);await render();}
const button=(name:string)=>[...element.querySelectorAll("button")].find(b=>b.textContent===name)!;
async function click(name:string){expect(button(name),name).toBeTruthy();expect(button(name).disabled,name).toBe(false);await act(async()=>button(name).click());}
async function input(selector:string,value:string){const target=element.querySelector(selector) as HTMLSelectElement|HTMLTextAreaElement;expect(target.disabled).toBe(false);
  await act(async()=>{Object.getOwnPropertyDescriptor(target.tagName==="SELECT"?HTMLSelectElement.prototype:HTMLTextAreaElement.prototype,"value")!.set!.call(target,value);
    target.dispatchEvent(new Event(target.tagName==="SELECT"?"change":"input",{bubbles:true}));});}
async function check(){await act(async()=>element.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());}
const pending=()=> (records.get(address)?.value?.body as {pending:unknown}|undefined)?.pending;
beforeEach(()=>{
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT",true);vi.clearAllMocks();records=new Map();access=makeAccess();failWrite=false;failClear=false;
  element=document.createElement("div");document.body.append(element);root=createRoot(element);
  vi.mocked(workspaceApi.practiceWork).mockResolvedValue({items:[item],people:[owner,staff],next_cursor:null});
  vi.mocked(workspaceApi.practiceWorkItem).mockResolvedValue(offered);
  vi.mocked(workspaceApi.workHandoff).mockResolvedValue(offered);
});
afterEach(async()=>{await act(async()=>root.unmount());access.journal.close();element.remove();vi.unstubAllGlobals();});

it("journals the exact offer before dispatch, then restores with fresh access without accepting work",async()=>{
  vi.mocked(workspaceApi.workHandoff).mockImplementationOnce(async(_identity,ticketId,body)=>{
    expect(pending()).toEqual({type:"handoff",ticketId,body});throw new WorkspaceApiError(503);
  });
  await render();await input(".practice-work-card select",staff.id);await click("Send responsibility offer");
  const original=vi.mocked(workspaceApi.workHandoff).mock.calls[0];expect(pending()).toBeTruthy();
  expect(JSON.stringify([...records.values()])).not.toContain("invented-token");
  await restart();expect(workspaceApi.workHandoff).toHaveBeenCalledTimes(1);expect(button("Set aside rejected request")).toBeUndefined();
  await click("Restore practice-work request");expect(access.authorize).toHaveBeenCalledOnce();expect(workspaceApi.practiceWorkItem).toHaveBeenCalledWith(identity,item.ticket_id);
  expect(workspaceApi.workHandoff).toHaveBeenCalledTimes(1);expect(element.textContent).toContain("remains responsible until acceptance");
  await click("Retry same action");expect(vi.mocked(workspaceApi.workHandoff).mock.calls[1]).toEqual(original);expect(records.get(address)?.value).toBeNull();
});

it("restores unsent work text and colleague choice without restoring the result check",async()=>{
  vi.mocked(workspaceApi.practiceWorkItem).mockResolvedValue(item);
  await render();await input(".practice-work-card select",staff.id);await input("textarea","Unsent invented result");await check();
  const key=accountEditorAddress(`practice-result:${item.ticket_id}`);
  expect((records.get(key)?.value?.body as AccountEditorDraft).data).toMatchObject({recipient:staff.id,evidence:"Unsent invented result",version:item.version});
  await restart();expect(element.querySelector<HTMLTextAreaElement>("textarea")!.value).toBe("");
  expect(button("Record completion").disabled).toBe(true);await click("Restore practice work form draft");
  expect(element.querySelector<HTMLTextAreaElement>("textarea")!.value).toBe("Unsent invented result");
  expect(element.querySelector<HTMLSelectElement>(".practice-work-card select")!.value).toBe(staff.id);
  expect(element.querySelector<HTMLInputElement>('input[type="checkbox"]')!.checked).toBe(false);
  expect(workspaceApi.workHandoff).not.toHaveBeenCalled();expect(workspaceApi.completeWork).not.toHaveBeenCalled();
});

it("retains an earlier work form across responsibility changes and requires explicit comparison",async()=>{
  await render();await input(".practice-work-card select",staff.id);await input("textarea","Earlier invented evidence");
  const latest={...item,version:item.version+2};vi.mocked(workspaceApi.practiceWork).mockResolvedValue({items:[latest],people:[owner,staff],next_cursor:null});
  vi.mocked(workspaceApi.practiceWorkItem).mockResolvedValue(latest);await restart();await click("Restore practice work form draft");
  expect(element.textContent).toContain("earlier responsibility or work version");expect(button("Record completion").disabled).toBe(true);
  await click("Use this text for current work");expect(element.querySelector<HTMLSelectElement>(".practice-work-card select")!.value).toBe("");
  expect(element.querySelector<HTMLInputElement>('input[type="checkbox"]')!.checked).toBe(false);
  expect(element.querySelector<HTMLTextAreaElement>("textarea")!.value).toBe("Earlier invented evidence");expect(workspaceApi.completeWork).not.toHaveBeenCalled();
});

it("withholds form text when current access is revoked and keeps its encrypted-journal input",async()=>{
  await render();await input("textarea","Retained private result");const key=accountEditorAddress(`practice-result:${item.ticket_id}`);
  const before=structuredClone(records.get(key));await restart();vi.mocked(access.authorize).mockRejectedValue(new WorkspaceApiError(403));
  await click("Restore practice work form draft");expect(element.textContent).not.toContain("Retained private result");expect(records.get(key)).toEqual(before);
  expect(lost).toHaveBeenCalledOnce();expect(workspaceApi.completeWork).not.toHaveBeenCalled();
});

it("keeps a closed item's unfinished result until the user discards it",async()=>{
  await render();await input("textarea","My unfinished result");const latest={...item,state:"closed",version:5};
  vi.mocked(workspaceApi.practiceWork).mockResolvedValue({items:[latest],people:[owner,staff],next_cursor:null});vi.mocked(workspaceApi.practiceWorkItem).mockResolvedValue(latest);
  await restart();await click("Restore practice work form draft");expect(element.querySelector<HTMLTextAreaElement>("textarea")!.value).toBe("My unfinished result");
  expect(button("Record completion")).toBeUndefined();await click("Discard earlier work form");
  expect(records.get(accountEditorAddress(`practice-result:${item.ticket_id}`))?.value).toBeNull();
});

it("clears redundant result text only for the same revision and the same human's exact receipt",async()=>{
  await render();await input("textarea","Exact verified result");
  const latest={...item,state:"closed",version:5,receipts:[{id:id("41"),kind:"human_completion" as const,content:"Exact verified result",actor:owner,created_at:"2026-09-21T12:00:00Z"}]};
  vi.mocked(workspaceApi.practiceWork).mockResolvedValue({items:[latest],people:[owner,staff],next_cursor:null});vi.mocked(workspaceApi.practiceWorkItem).mockResolvedValue(latest);
  await restart();await click("Restore practice work form draft");expect(records.get(accountEditorAddress(`practice-result:${item.ticket_id}`))?.value).toBeNull();
  expect(workspaceApi.completeWork).not.toHaveBeenCalled();
});

it("rejects added consent fields in a saved work form without overwriting it",async()=>{
  await render();await input("textarea","Keep malformed record for review");const key=accountEditorAddress(`practice-result:${item.ticket_id}`);
  const draft=records.get(key)!.value!.body as AccountEditorDraft;draft.data={...draft.data as object,checked:true};
  const before=structuredClone(records.get(key));await restart();await click("Restore practice work form draft");
  expect(element.textContent).toContain("could not be restored");expect(records.get(key)).toEqual(before);expect(workspaceApi.completeWork).not.toHaveBeenCalled();
});

it("recovers completion evidence and its key even when the item is outside the first page",async()=>{
  vi.mocked(workspaceApi.completeWork).mockRejectedValueOnce(new WorkspaceApiError(503));
  await render();await input("textarea","Invented checked evidence");await check();await click("Record completion");
  const original=vi.mocked(workspaceApi.completeWork).mock.calls[0];
  const completed={...item,state:"closed",version:5};
  vi.mocked(workspaceApi.practiceWork).mockResolvedValue({items:[],people:[owner,staff],next_cursor:null});
  vi.mocked(workspaceApi.practiceWorkItem).mockResolvedValue(completed);await restart();
  await click("Restore practice-work request");expect(workspaceApi.completeWork).toHaveBeenCalledTimes(1);
  expect(element.textContent).toContain("Completed · human recorded");vi.mocked(workspaceApi.completeWork).mockResolvedValue(completed);
  await click("Retry same action");expect(vi.mocked(workspaceApi.completeWork).mock.calls[1]).toEqual(original);expect(records.get(address)?.value).toBeNull();
});

it("retains an unconfirmed request when access is revoked before Restore",async()=>{
  vi.mocked(workspaceApi.workHandoff).mockRejectedValue(new WorkspaceApiError(503));
  await render();await input(".practice-work-card select",staff.id);await click("Send responsibility offer");const saved=structuredClone(records.get(address));
  await restart();vi.mocked(access.authorize).mockRejectedValue(new WorkspaceApiError(403));await click("Restore practice-work request");
  expect(lost).toHaveBeenCalledOnce();expect(element.textContent).not.toContain(item.body);expect(records.get(address)).toEqual(saved);
  expect(workspaceApi.workHandoff).toHaveBeenCalledTimes(1);
});

it("sends nothing if the operation cannot be journaled locally",async()=>{
  await render();await input(".practice-work-card select",staff.id);failWrite=true;await click("Send responsibility offer");
  expect(workspaceApi.workHandoff).not.toHaveBeenCalled();expect(element.textContent).toContain("request was not sent");
  failWrite=false;await click("Recheck practice-work recovery");await click("Send responsibility offer");expect(workspaceApi.workHandoff).toHaveBeenCalledOnce();
});

it("retains the original key when the service replies but clearing its journal fails",async()=>{
  await render();await input(".practice-work-card select",staff.id);failClear=true;await click("Send responsibility offer");
  const original=vi.mocked(workspaceApi.workHandoff).mock.calls[0];expect(pending()).toBeTruthy();expect(button("Retry same action").disabled).toBe(true);
  failClear=false;await click("Recheck practice-work recovery");await click("Restore practice-work request");await click("Retry same action");
  expect(vi.mocked(workspaceApi.workHandoff).mock.calls[1]).toEqual(original);expect(records.get(address)?.value).toBeNull();
});

it("keeps a rejected request until the user checks current work and explicitly sets it aside",async()=>{
  vi.mocked(workspaceApi.workHandoff).mockRejectedValue(new WorkspaceApiError(409));
  await render();await input(".practice-work-card select",staff.id);await click("Send responsibility offer");expect(pending()).toBeTruthy();
  expect(button("Set aside rejected request")).toBeUndefined();await click("Check current work");
  expect(workspaceApi.practiceWorkItem).toHaveBeenCalledOnce();await click("Set aside rejected request");
  expect(records.get(address)?.value).toBeNull();expect(workspaceApi.workHandoff).toHaveBeenCalledOnce();
});

it.each([null,undefined])("fails closed when signed practice work has no private recovery context (%j)",async context=>{
  await act(async()=>root.render(<AccountRecoveryContext.Provider value={context}><PracticeWork identity={identity} onChanged={changed} onAccessLost={lost}/></AccountRecoveryContext.Provider>));
  expect(element.querySelector<HTMLSelectElement>(".practice-work-card select")!.disabled).toBe(true);expect(workspaceApi.workHandoff).not.toHaveBeenCalled();
});

const request={type:"handoff",ticketId:item.ticket_id,body:{expected_version:4,revision_id:item.revision_id,payload_hash:item.payload_hash,idempotency_key:"exact-invented-key",kind:"offer",recipient_id:staff.id}};
it.each([
  {...request,ticketId:"wrong"},
  {...request,body:{...request.body,expected_version:0}},
  {...request,body:{...request.body,recipient_id:undefined}},
  {...request,body:{...request.body,offer_id:id("31")}},
  {...request,body:{...request.body,kind:"accept"}},
  {...request,body:{...request.body,idempotency_key:"short"}},
  {...request,body:{...request.body,payload_hash:"wrong"}},
])("rejects a malformed operation without persisting it",async value=>{
  expect(validPracticeOperation(value)).toBe(false);await access.journal.load(address);
  await expect(access.journal.persist(address,{kind:"account-operation",lane:"practice-work",pending:value as never})).rejects.toMatchObject({code:"integrity"});
  expect(records.get(address)?.value).toBeUndefined();
});

const preparation:PracticeWorkItem={...item,work_kind:"visit_preparation",ready_for_review:false,state:"approved",body:"Invented visit preparation"};
const prepPage=(value:PracticeWorkItem=preparation)=>({items:[value],people:[owner,staff],next_cursor:null});

it("journals and restores the exact preparation readiness request after a lost reply without completing the work",async()=>{
  vi.mocked(workspaceApi.practiceWork).mockResolvedValue(prepPage());
  vi.mocked(workspaceApi.completeWork).mockImplementationOnce(async(_identity,ticketId,body)=>{
    expect(pending()).toEqual({type:"complete",ticketId,body});expect(body.expected_version).toBe(4);
    throw new WorkspaceApiError(503);
  });
  await render();await input("textarea","Intake checked; question retained for provider.");await check();await click("Mark ready for review");
  const original=vi.mocked(workspaceApi.completeWork).mock.calls[0];
  const ready:PracticeWorkItem={...preparation,ready_for_review:true,version:5,
    receipts:[{id:id("41"),kind:"ready_for_review",content:original[2].evidence,actor:owner,created_at:"2026-09-21T12:00:00Z"}]};
  vi.mocked(workspaceApi.practiceWork).mockResolvedValue({items:[],people:[owner,staff],next_cursor:null});
  vi.mocked(workspaceApi.practiceWorkItem).mockResolvedValue(ready);
  await restart();expect(workspaceApi.completeWork).toHaveBeenCalledTimes(1);
  await click("Restore practice-work request");expect(access.authorize).toHaveBeenCalledOnce();
  expect(element.textContent).toContain("Ready for provider review");expect(element.textContent).not.toContain("Completed");
  expect(button("Mark ready for review")).toBeUndefined();expect(workspaceApi.completeWork).toHaveBeenCalledTimes(1);
  vi.mocked(workspaceApi.completeWork).mockResolvedValue(ready);await click("Retry same action");
  expect(vi.mocked(workspaceApi.completeWork).mock.calls[1]).toEqual(original);
  expect(original[2].expected_version).toBe(4);expect(records.get(address)?.value).toBeNull();
});

it("restores unsent preparation evidence without restoring readiness confirmation",async()=>{
  vi.mocked(workspaceApi.practiceWork).mockResolvedValue(prepPage());vi.mocked(workspaceApi.practiceWorkItem).mockResolvedValue(preparation);
  await render();await input("textarea","Unsent preparation findings");await check();
  await restart();await click("Restore practice work form draft");
  expect(element.querySelector<HTMLTextAreaElement>("textarea")!.value).toBe("Unsent preparation findings");
  expect(element.querySelector<HTMLInputElement>('input[type="checkbox"]')!.checked).toBe(false);
  expect(button("Mark ready for review").disabled).toBe(true);expect(workspaceApi.completeWork).not.toHaveBeenCalled();
});

it("withholds a restored preparation request without a work version and preserves the saved request",async()=>{
  const legacyComplete={type:"complete" as const,ticketId:item.ticket_id,body:{revision_id:item.revision_id,payload_hash:item.payload_hash,idempotency_key:"unversioned-invented-key",evidence:"Retained evidence"}};
  await access.journal.load(address);await access.journal.persist(address,{kind:"account-operation",lane:"practice-work",pending:legacyComplete});
  const before=structuredClone(records.get(address));
  vi.mocked(workspaceApi.practiceWork).mockResolvedValue(prepPage());vi.mocked(workspaceApi.practiceWorkItem).mockResolvedValue(preparation);
  await render();await click("Restore practice-work request");
  expect(element.textContent).toContain("Existing requests are retained");
  expect(records.get(address)).toEqual(before);expect(button("Retry same action")).toBeUndefined();
  expect(workspaceApi.completeWork).not.toHaveBeenCalled();
});

it("retains a stale preparation request until current work is checked and the rejected request is explicitly set aside",async()=>{
  vi.mocked(workspaceApi.practiceWork).mockResolvedValue(prepPage());
  vi.mocked(workspaceApi.completeWork).mockRejectedValue(new WorkspaceApiError(409));
  vi.mocked(workspaceApi.practiceWorkItem).mockResolvedValue({...preparation,version:6,responsible:staff});
  await render();await input("textarea","Prepared before responsibility changed");await check();await click("Mark ready for review");
  expect(pending()).toMatchObject({type:"complete",body:{expected_version:4}});
  expect(button("Set aside rejected request")).toBeUndefined();await click("Check current work");
  expect(element.textContent).toContain("earlier responsibility or work version");await click("Set aside rejected request");
  expect(records.get(address)?.value).toBeNull();expect(workspaceApi.completeWork).toHaveBeenCalledOnce();
  expect(element.querySelector<HTMLTextAreaElement>("textarea")!.value).toBe("Prepared before responsibility changed");
});

it.each(["matching_ready","other_actor","wrong_kind"] as const)("clears redundant preparation evidence only for its own readiness receipt (%s)",async scenario=>{
  vi.mocked(workspaceApi.practiceWork).mockResolvedValue(prepPage());await render();await input("textarea","Exact preparation evidence");
  const latest:PracticeWorkItem={...preparation,ready_for_review:true,version:5,
    receipts:[{id:id("41"),kind:scenario==="wrong_kind"?"human_completion":"ready_for_review",actor:scenario==="other_actor"?staff:owner,content:"Exact preparation evidence",created_at:"2026-09-21T12:00:00Z"}]};
  vi.mocked(workspaceApi.practiceWork).mockResolvedValue(prepPage(latest));vi.mocked(workspaceApi.practiceWorkItem).mockResolvedValue(latest);
  await restart();await click("Restore practice work form draft");
  const saved=records.get(accountEditorAddress(`practice-result:${item.ticket_id}`))?.value;
  if(scenario==="matching_ready")expect(saved).toBeNull();else {
    expect(saved).not.toBeNull();expect(element.querySelector<HTMLTextAreaElement>("textarea")!.value).toBe("Exact preparation evidence");
  }
  expect(workspaceApi.completeWork).not.toHaveBeenCalled();expect(element.textContent).not.toContain("Completed");
});

const completeRequest={type:"complete",ticketId:item.ticket_id,body:{revision_id:item.revision_id,payload_hash:item.payload_hash,idempotency_key:"exact-preparation-key",evidence:"Invented preparation",expected_version:4}};
it("accepts only closed legacy or versioned completion requests",()=>{
  expect(validPracticeOperation(completeRequest)).toBe(true);
  const {expected_version:_,...legacy}=completeRequest.body;
  expect(validPracticeOperation({...completeRequest,body:legacy})).toBe(true);
  expect(validPracticeOperation({...completeRequest,body:{...completeRequest.body,checked:true}})).toBe(false);
});
it.each([undefined,null,0,-1,1.5,"4",Number.MAX_SAFE_INTEGER+1])("rejects malformed saved preparation versions (%j)",async version=>{
  const value={...completeRequest,body:{...completeRequest.body,expected_version:version}};
  expect(validPracticeOperation(value)).toBe(false);await access.journal.load(address);
  await expect(access.journal.persist(address,{kind:"account-operation",lane:"practice-work",pending:value as never})).rejects.toMatchObject({code:"integrity"});
  expect(records.get(address)?.value).toBeUndefined();
});
