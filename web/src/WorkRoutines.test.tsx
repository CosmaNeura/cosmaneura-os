import {act} from "react";
import {createRoot,type Root} from "react-dom/client";
import {afterEach,beforeEach,expect,it,vi} from "vitest";
import {WorkRoutines} from "./WorkRoutines";
import {routineApi} from "./routine-api";
import {brief,routine,routineId,schedule} from "./routine-test-fixture";
import {WorkspaceApiError,type ProviderTeam} from "./workspace-api";
import {AccountRecoveryContext,type AccountRecoveryAccess} from "./account-recovery";
import {DraftJournal,type AccountEditorDraft} from "./draft-journal";
import {memoryDraftStorage} from "./draft-test-fixture";
import {DraftStoreError} from "./draft-store";
vi.mock("./routine-api",async original=>({...await original<typeof import("./routine-api")>(),routineApi:{read:vi.fn(),save:vi.fn(),run:vi.fn()}}));
const identity={mode:"clerk_jwt" as const,getToken:async()=>"invented.token.value"};
const team:ProviderTeam={revision:1,template_version:"test",configuration:{practice_context:"Invented practice",bots:[
  {role:"chief",name:"Chief",enabled:true,response_style:"brief",include_notebook:true,include_evidence:true},
  {role:"custom",name:"My coordinator",instance_id:routineId(9),skills:["work_status"],enabled:true,response_style:"brief",include_notebook:false,include_evidence:false}]},members:[],llm:{enabled:false,model:"none"}};
let container:HTMLDivElement,root:Root,access:AccountRecoveryAccess,storage:ReturnType<typeof memoryDraftStorage>,failWrite:boolean;const lost=vi.fn();
async function makeAccess():Promise<AccountRecoveryAccess>{const store=await storage({scope:"routine-test"});return {journal:new DraftJournal({...store,async write(...args){if(failWrite)throw new DraftStoreError("unavailable");return store.write(...args);}}),authorize:vi.fn().mockResolvedValue(undefined)};}
beforeEach(async()=>{Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.clearAllMocks();container=document.createElement("div");document.body.append(container);root=createRoot(container);
  storage=memoryDraftStorage();failWrite=false;access=await makeAccess();
  vi.mocked(routineApi.read).mockImplementation(async(_,bot)=>routine(bot));vi.mocked(routineApi.run).mockResolvedValue(brief());
  vi.mocked(routineApi.save).mockResolvedValue({...routine(),revision:2});});
afterEach(async()=>{await act(async()=>root.unmount());access.journal.close();container.remove();});
async function render(currentTeam=team,currentIdentity=identity){await act(async()=>root.render(<AccountRecoveryContext.Provider value={access}><WorkRoutines identity={currentIdentity} team={currentTeam} onAccessLost={lost}/></AccountRecoveryContext.Provider>));}
async function restart(currentTeam=team){await act(async()=>root.unmount());access.journal.close();access=await makeAccess();root=createRoot(container);await render(currentTeam);}
const savedDraft=async()=>await access.journal.load("account-editor:work-routine") as AccountEditorDraft|null;
async function openEditor(){const edit=[...container.querySelectorAll("button")].find(b=>b.textContent==="Edit schedule");
  if(edit&&!edit.closest("[hidden]"))await act(async()=>edit.click());}
async function click(label:string){if(["Save schedule","Pause routine"].includes(label))await openEditor();const button=[...container.querySelectorAll("button")].find(b=>b.textContent===label);expect(button,label).toBeTruthy();await act(async()=>button!.click());}
async function input(label:string,value:string){if(label!=="Coworker")await openEditor();const el=[...container.querySelectorAll("label")].find(l=>l.textContent?.startsWith(label))!.querySelector("input,select") as HTMLInputElement|HTMLSelectElement;
  await act(async()=>{Object.getOwnPropertyDescriptor(el.tagName==="SELECT"?HTMLSelectElement.prototype:HTMLInputElement.prototype,"value")!.set!.call(el,value);
    el.dispatchEvent(new Event(el.tagName==="SELECT"?"change":"input",{bubbles:true}));});}
it("fills new schedules from the device without a timezone control or automatic save",async()=>{
  vi.mocked(routineApi.read).mockResolvedValue({...routine(),revision:0,configuration:null,status:"not_configured",next_scheduled_at:null,runs:[]});
  await render();await openEditor();
  expect([...container.querySelectorAll("label")].some(label=>/time.?zone/i.test(label.textContent??""))).toBe(false);
  expect(routineApi.save).not.toHaveBeenCalled();
  await click("Save schedule");expect(vi.mocked(routineApi.save).mock.calls[0][2]).toMatchObject({expected_revision:0,
    configuration:{timezone:Intl.DateTimeFormat().resolvedOptions().timeZone,enabled:false,at:"08:00"}});
});
it("keeps the saved schedule's timezone while editing from a device in another region",async()=>{
  const zone=Intl.DateTimeFormat().resolvedOptions().timeZone==="Pacific/Auckland"?"America/New_York":"Pacific/Auckland";
  vi.mocked(routineApi.read).mockResolvedValue({...routine(),configuration:{...schedule(),timezone:zone}});
  await render();await input("Brief time","09:00");await click("Save schedule");
  expect(vi.mocked(routineApi.save).mock.calls[0][2].configuration).toEqual({...schedule(),timezone:zone,at:"09:00"});
});
it.each([true,false])("repairs only an invalid unsent legacy zone using saved timing when available (%s)",async configured=>{
  const saved={...routine(),...(configured?{configuration:{...schedule(),timezone:"Pacific/Auckland"}}:
    {revision:0,configuration:null,status:"not_configured" as const,next_scheduled_at:null,runs:[]})};
  vi.mocked(routineApi.read).mockResolvedValue(saved);
  await access.journal.load("account-editor:work-routine");
  await access.journal.persist("account-editor:work-routine",{kind:"account-editor",editor:"work-routine",pending:null,data:{
    selected:"chief",configuration:{...schedule(),timezone:"America/",at:""},baseRevision:saved.revision,teamRevision:1,pending:null}});
  await render();await click("Restore work routine draft");
  const zone=configured?"Pacific/Auckland":Intl.DateTimeFormat().resolvedOptions().timeZone;
  expect((await savedDraft())?.data).toMatchObject({configuration:{timezone:zone,at:""},pending:null});
  expect(container.textContent).toContain("filled in automatically");expect(routineApi.save).not.toHaveBeenCalled();
  await input("Brief time","09:00");await click("Save schedule");
  expect(vi.mocked(routineApi.save).mock.calls[0][2].configuration).toEqual({...schedule(),timezone:zone,at:"09:00"});
});
it("preserves a valid legacy draft and its exact pending timezone across restart and retry",async()=>{
  const body={expected_revision:1,team_revision:1,idempotency_key:routineId(44),configuration:{...schedule(),timezone:"Pacific/Auckland",at:"09:00"}};
  await access.journal.load("account-editor:work-routine");
  await access.journal.persist("account-editor:work-routine",{kind:"account-editor",editor:"work-routine",pending:body.idempotency_key,data:{
    selected:"chief",configuration:body.configuration,baseRevision:1,teamRevision:1,pending:body}});
  await render();await click("Restore work routine draft");
  expect((await savedDraft())?.data).toMatchObject({configuration:body.configuration,pending:body});expect(routineApi.save).not.toHaveBeenCalled();
  await click("Retry same schedule save");expect(vi.mocked(routineApi.save).mock.calls[0][2]).toEqual(body);
});
it("shows a dated brief and keeps completion attached to its existing work",async()=>{
  await render();expect(container.textContent).toContain("Work observed on 2026-09-21");expect(container.textContent).toContain("Confirm invented appointment");
  expect(container.textContent).toContain("Awaiting result");expect(container.textContent).not.toContain("Record completion");expect(routineApi.save).not.toHaveBeenCalled();
});
it("guards a changed or unconfirmed schedule and releases the guard on exact recovery or account change",async()=>{
  const blocked=()=>!window.dispatchEvent(new Event("beforeunload",{cancelable:true}));
  await render();expect(blocked()).toBe(false);
  await input("Brief time","09:00");expect(blocked()).toBe(true);
  await input("Brief time","08:00");expect(blocked()).toBe(false);
  await input("Brief time","09:00");vi.mocked(routineApi.save).mockRejectedValueOnce(new Error("lost reply"));
  await click("Save schedule");expect(blocked()).toBe(true);
  await click("Retry same schedule save");expect(blocked()).toBe(false);
  await input("Brief time","10:00");expect(blocked()).toBe(true);
  await render(team,{...identity});expect(blocked()).toBe(true);expect(container.textContent).toContain("Restore work routine draft");
});
it("retries the exact unconfirmed save and locks schedule edits and coworker switching",async()=>{
  vi.mocked(routineApi.save).mockRejectedValueOnce(new Error("lost reply")).mockResolvedValueOnce({...routine(),revision:2});
  await render();await input("Brief time","09:00");await click("Save schedule");
  const first=vi.mocked(routineApi.save).mock.calls[0];expect(first[2]).toMatchObject({expected_revision:1,team_revision:1,configuration:{at:"09:00"}});
  expect(container.querySelector("select")!.disabled).toBe(true);expect(container.querySelector("fieldset")!.disabled).toBe(true);
  await click("Retry same schedule save");expect(vi.mocked(routineApi.save).mock.calls[1]).toEqual(first);
  expect(container.textContent).toContain("Schedule saved");
});
it("pauses the saved schedule even if there are unsaved edits",async()=>{
  await render();await input("Brief time","09:00");await click("Pause routine");
  expect(vi.mocked(routineApi.save).mock.calls[0][2]).toMatchObject({configuration:{enabled:false,at:"08:00"}});
  expect(container.textContent).toContain("Routine paused");
  expect(container.querySelector<HTMLInputElement>('input[type="time"]')!.value).toBe("09:00");
});
it("requires reload after revision conflict and retains unsaved fields for review",async()=>{
  vi.mocked(routineApi.save).mockRejectedValue(new WorkspaceApiError(409));await render();await input("Brief time","09:00");await click("Save schedule");
  expect(container.querySelector<HTMLInputElement>('input[type="time"]')!.value).toBe("09:00");expect(container.querySelector("fieldset")!.disabled).toBe(true);
  expect(container.textContent).not.toContain("Retry same schedule save");await click("Check current schedule");await click("Set aside rejected schedule request");await click("Reload saved schedule");
  expect(container.querySelector<HTMLInputElement>('input[type="time"]')!.value).toBe("08:00");expect(container.querySelector("fieldset")!.disabled).toBe(false);
});
it("withholds revoked content and discards a response from the previous account",async()=>{
  await render();vi.mocked(routineApi.read).mockRejectedValueOnce(new WorkspaceApiError(403));await click("Refresh briefs");
  expect(container.textContent).not.toContain("Confirm invented appointment");expect(lost).toHaveBeenCalledOnce();
  let release!:(value:ReturnType<typeof brief>)=>void;vi.mocked(routineApi.run).mockImplementationOnce(()=>new Promise(resolve=>{release=resolve;}));
  await act(async()=>{root.render(<AccountRecoveryContext.Provider value={access}><WorkRoutines identity={{...identity}} team={team} onAccessLost={lost}/></AccountRecoveryContext.Provider>);});
  vi.mocked(routineApi.read).mockResolvedValueOnce({...routine(),runs:[]});await render(team,{...identity});
  await act(async()=>release(brief()));expect(container.textContent).not.toContain("Confirm invented appointment");
});
it("allows a saved custom coworker to own an independent routine",async()=>{
  await render();await input("Coworker",routineId(9));expect(vi.mocked(routineApi.read).mock.calls.at(-1)?.[1]).toBe(routineId(9));
  await click("Save schedule");expect(vi.mocked(routineApi.save).mock.calls[0][1]).toBe(routineId(9));
});
it("prevents enabling a paused bot and saving against a stale team",async()=>{
  const changed=structuredClone(team);changed.revision=2;changed.configuration.bots[0].enabled=false;await render(changed);await openEditor();
  expect(container.querySelector<HTMLInputElement>('input[type="checkbox"]')!.disabled).toBe(true);
  await click("Save schedule");expect(routineApi.save).not.toHaveBeenCalled();
  expect(container.textContent).toContain("Refresh the workspace team");
});
it("shows partial and withheld history without restoring removed source text",async()=>{
  vi.mocked(routineApi.run).mockResolvedValue({...brief(),items:[],matching_items:0,withheld_sources:true,truncated:true,counts:{open:0,overdue:0,awaiting_acceptance:0,responsible_unavailable:0,verified_complete:0}});
  await render();expect(container.textContent).toContain("have been withheld");expect(container.textContent).toContain("first 200");expect(container.textContent).not.toContain("Confirm invented appointment");
});

it("recovers incomplete settings for a custom bot without enabling or submitting its routine",async()=>{
  await render();await input("Coworker",routineId(9));await input("Brief time","");
  expect((await savedDraft())?.data).toMatchObject({selected:routineId(9),configuration:{timezone:"UTC",at:""},pending:null});
  await restart();expect(container.querySelector<HTMLSelectElement>("select")!.value).toBe("chief");
  await click("Restore work routine draft");expect(access.authorize).toHaveBeenCalledOnce();
  expect(container.querySelector<HTMLSelectElement>("select")!.value).toBe(routineId(9));
  expect(container.querySelector<HTMLInputElement>('input[type="time"]')!.value).toBe("");
  expect(container.textContent).toContain("a valid time outside quiet hours");expect(routineApi.save).not.toHaveBeenCalled();
});

it("journals before dispatch and restores the exact custom-bot schedule after a lost reply",async()=>{
  vi.mocked(routineApi.save).mockImplementationOnce(async(_identity,bot,body)=>{
    expect((await savedDraft())?.data).toMatchObject({selected:bot,pending:body});throw new WorkspaceApiError(503);
  });
  await render();await input("Coworker",routineId(9));await input("Brief time","09:00");await click("Save schedule");
  const original=vi.mocked(routineApi.save).mock.calls[0];await restart();expect(routineApi.save).toHaveBeenCalledTimes(1);
  await click("Restore work routine draft");expect(routineApi.save).toHaveBeenCalledTimes(1);
  vi.mocked(routineApi.save).mockResolvedValue({...routine(routineId(9)),revision:2,configuration:original[2].configuration});
  await click("Retry same schedule save");const retry=vi.mocked(routineApi.save).mock.calls[1];
  expect(retry.slice(0,3)).toEqual(original.slice(0,3));expect(await savedDraft()).toBeNull();
});

it("requires explicit comparison when another save changes the restored routine",async()=>{
  await render();await input("Brief time","09:00");vi.mocked(routineApi.read).mockImplementation(async(_,bot)=>({...routine(bot),revision:2}));
  await restart();await click("Restore work routine draft");expect(container.textContent).toContain("earlier saved version");
  expect([...container.querySelectorAll("button")].find(b=>b.textContent==="Save schedule")!.disabled).toBe(true);
  await click("Use these settings with the current schedule");await click("Save schedule");
  expect(vi.mocked(routineApi.save).mock.calls[0][2]).toMatchObject({expected_revision:2,configuration:{at:"09:00"}});
});

it("withholds a routine draft after revoked authority and retains the original local record",async()=>{
  await render();await input("Brief time","09:45");const before=await savedDraft();
  await restart();vi.mocked(access.authorize).mockRejectedValue(new WorkspaceApiError(403));await click("Restore work routine draft");
  expect(container.querySelector<HTMLInputElement>('input[type="time"]')?.value).not.toBe("09:45");expect(await savedDraft()).toEqual(before);
  expect(routineApi.save).not.toHaveBeenCalled();expect(lost).toHaveBeenCalledOnce();
});

it("keeps the exact pending request until a rejected save is checked and explicitly set aside",async()=>{
  vi.mocked(routineApi.save).mockRejectedValue(new WorkspaceApiError(409));await render();await input("Brief time","09:00");await click("Save schedule");
  const pending=await savedDraft();expect(pending?.pending).toBeTruthy();expect(container.textContent).not.toContain("Set aside rejected schedule request");
  await click("Check current schedule");expect(await savedDraft()).toEqual(pending);await click("Set aside rejected schedule request");
  expect((await savedDraft())?.pending).toBeNull();expect((await savedDraft())?.data).toMatchObject({configuration:{at:"09:00"},pending:null});
});

it("blocks schedule submission after a failed draft write and recovers the last durable settings",async()=>{
  await render();await input("Brief time","09:00");failWrite=true;await input("Brief time","10:00");
  expect([...container.querySelectorAll("button")].find(b=>b.textContent==="Save schedule")!.disabled).toBe(true);expect(routineApi.save).not.toHaveBeenCalled();
  failWrite=false;await restart();await click("Restore work routine draft");expect(container.querySelector<HTMLInputElement>('input[type="time"]')!.value).toBe("09:00");
});

it("does not bypass private form recovery when the signed account context is absent",async()=>{
  await act(async()=>root.render(<WorkRoutines identity={identity} team={team} onAccessLost={lost}/>));
  await openEditor();expect([...container.querySelectorAll("button")].find(b=>b.textContent==="Save schedule")!.disabled).toBe(true);expect(routineApi.save).not.toHaveBeenCalled();
});

it("shows a restricted schedule without promising another run and keeps history and explicit pause available",async()=>{
  vi.mocked(routineApi.read).mockResolvedValue({...routine(),status:"restricted"});const denied=structuredClone(team);denied.configuration.bots[0].blocked_capabilities=["practice_work_brief"];
  await render(denied);await openEditor();expect(container.textContent).toContain("Blocked by your team settings");expect(container.textContent).not.toContain("Next scheduled:");
  expect(container.textContent).toContain("Work observed on 2026-09-21");
  const enabled=[...container.querySelectorAll('label')].find(l=>l.textContent==='Prepare scheduled briefs')!.querySelector<HTMLInputElement>('input')!;
  expect(enabled.checked).toBe(true);expect(enabled.disabled).toBe(false);await act(async()=>enabled.click());expect(enabled.checked).toBe(false);expect(enabled.disabled).toBe(true);
  expect(routineApi.save).not.toHaveBeenCalled();
});
