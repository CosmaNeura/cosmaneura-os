import {act} from "react";
import {createRoot,type Root} from "react-dom/client";
import {afterEach,beforeEach,expect,it,vi} from "vitest";
import {AppointmentPanel} from "./AppointmentPanel";
import {appointmentApi,type AppointmentItem} from "./appointment-api";
import {catalog,item,saved,workspaceId} from "./appointment-test-fixture";
import {DraftJournal,editorAddress,type EditorDraft} from "./draft-journal";
import {DraftStoreError,type DraftRecord,type DraftStore} from "./draft-store";
import {EditorRecoveryContext,type EditorRecoveryAccess} from "./editor-recovery";
import {WorkspaceApiError,type CaptureBotSelection,type Workspace} from "./workspace-api";
vi.mock("./appointment-api",()=>({appointmentApi:{catalog:vi.fn(),current:vi.fn(),prepare:vi.fn(),read:vi.fn(),decide:vi.fn(),execute:vi.fn()}}));
const identity={mode:"clerk_jwt" as const,getToken:vi.fn()},address=editorAddress(workspaceId,"appointments");
let root:Root,container:HTMLDivElement,access:EditorRecoveryAccess,records:Map<string,DraftRecord>,failWrites:boolean;
let slot:AppointmentItem["intent"]["slot"],bot:CaptureBotSelection;
const lost=vi.fn();
function makeAccess():EditorRecoveryAccess {
  let closed=false;
  const store:DraftStore={close(){closed=true;},async read(key){if(closed)throw new DraftStoreError("unavailable");
    return structuredClone(records.get(key)??{revision:null,value:null});},async write(key,expected,value){
    if(closed||failWrites)throw new DraftStoreError("unavailable");const prior=records.get(key)??{revision:null,value:null};
    if(prior.revision!==expected)throw new DraftStoreError("conflict");
    const next={revision:String(Number(expected??0)+1),value:structuredClone(value)};records.set(key,next);return next;
  }};
  return {journal:new DraftJournal(store),workspaceId,authorize:vi.fn().mockResolvedValue({id:workspaceId} as Workspace),denied:vi.fn()};
}
async function mount(context:EditorRecoveryAccess|null|undefined=access,who=identity){await act(async()=>root.render(
  <EditorRecoveryContext.Provider value={context}><AppointmentPanel workspaceId={workspaceId} identity={who}
    bot={bot} enabled locked={false} selectedSlot={slot} onAccessLost={lost}/></EditorRecoveryContext.Provider>));}
async function restart(){await act(async()=>root.unmount());access.journal.close();access=makeAccess();root=createRoot(container);await mount();}
function button(text:string){return [...container.querySelectorAll("button")].find(v=>v.textContent===text);}
async function click(text:string){const value=button(text);expect(value,text).toBeTruthy();expect(value!.disabled,text).toBe(false);await act(async()=>value!.click());}
async function share(){const input=container.querySelector<HTMLInputElement>('input[type="checkbox"]')!;expect(input.disabled).toBe(false);await act(async()=>input.click());}
const draft=()=>records.get(address)?.value?.body as EditorDraft|null;
const data=()=>draft()?.data as {pending:unknown;slot:unknown}|undefined;
beforeEach(()=>{
 vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT",true);vi.useFakeTimers();vi.setSystemTime(new Date("2026-09-21T15:00:00Z"));vi.clearAllMocks();
 records=new Map();failWrites=false;access=makeAccess();slot=item().intent.slot;bot={address:"follow_up",team_revision:1};
 vi.mocked(appointmentApi.catalog).mockResolvedValue(catalog());vi.mocked(appointmentApi.read).mockResolvedValue(item());
 vi.mocked(appointmentApi.prepare).mockResolvedValue(item());vi.mocked(appointmentApi.decide).mockResolvedValue(item("approved"));
 container=document.createElement("div");document.body.append(container);root=createRoot(container);
});
afterEach(async()=>{await act(async()=>root.unmount());access.journal.close();container.remove();vi.useRealTimers();vi.unstubAllGlobals();});

it("retains an unsent time after availability expires and restores it without sharing or reserving",async()=>{
 await mount();await share();const original=slot;slot=null;await mount();expect(data()?.slot).toEqual(original);
 await restart();expect(button("Prepare appointment proposal")!.disabled).toBe(true);
 await click("Restore appointment draft");expect(access.authorize).toHaveBeenCalledOnce();expect(container.textContent).toContain("Retained choice");
 expect(container.querySelector<HTMLInputElement>('input[type="checkbox"]')!.checked).toBe(false);
 expect(appointmentApi.prepare).not.toHaveBeenCalled();expect(appointmentApi.decide).not.toHaveBeenCalled();
 await share();expect(button("Prepare appointment proposal")!.disabled).toBe(true);
 slot=structuredClone(original);await mount();expect(container.querySelector<HTMLInputElement>('input[type="checkbox"]')!.checked).toBe(false);
 await share();await click("Prepare appointment proposal");expect(appointmentApi.prepare).toHaveBeenCalledOnce();
});

it("journals before sending and recovers the identical proposal after restart and old availability",async()=>{
 vi.mocked(appointmentApi.prepare).mockImplementationOnce(async(_w,_i,body)=>{
   expect(data()?.pending).toEqual({kind:"prepare",body});throw new WorkspaceApiError(503);
 });
 await mount();await share();await click("Prepare appointment proposal");const first=vi.mocked(appointmentApi.prepare).mock.calls[0][2];
 slot=null;await restart();expect(button("Discard appointment draft")).toBeUndefined();
 expect(appointmentApi.prepare).toHaveBeenCalledOnce();await click("Restore appointment draft");
 expect(appointmentApi.prepare).toHaveBeenCalledOnce();await click("Retry the same save");
 expect(vi.mocked(appointmentApi.prepare).mock.calls[1][2]).toEqual(first);expect(records.get(address)?.value).toBeNull();
 expect(appointmentApi.decide).not.toHaveBeenCalled();
});

it.each(["approve","reject"] as const)("recovers the exact %s decision, reading its ticket outside the first page without repeating automatically",async choice=>{
 await mount();await share();await click("Prepare appointment proposal");
 vi.mocked(appointmentApi.decide).mockRejectedValueOnce(new WorkspaceApiError(503));
 await click(choice==="approve"?"Approve this appointment change":"Withdraw proposal");
 const first=vi.mocked(appointmentApi.decide).mock.calls[0];slot=null;await restart();await click("Restore appointment draft");
 expect(appointmentApi.read).toHaveBeenCalledWith(workspaceId,identity,item().ticket_id);
 expect(appointmentApi.decide).toHaveBeenCalledOnce();expect(data()?.pending).toEqual({kind:"decide",ticket:first[2],body:first[3]});
 await click("Retry the same save");const next=vi.mocked(appointmentApi.decide).mock.calls[1];expect(next.slice(0,4)).toEqual(first.slice(0,4));
 expect(Object.keys(next[3]).sort()).toEqual(["choice","payload_hash","revision_id"]);expect(records.get(address)?.value).toBeNull();
});

it("does not overwrite an uncertain request when switching bots",async()=>{
 vi.mocked(appointmentApi.prepare).mockRejectedValueOnce(new WorkspaceApiError(503));
 await mount();await share();await click("Prepare appointment proposal");const before=structuredClone(records.get(address));
 bot={address:"chief",team_revision:2};await mount();expect(records.get(address)).toEqual(before);
 expect(button("Prepare appointment proposal")!.disabled).toBe(true);await click("Restore appointment draft");
 expect(container.textContent).toContain("earlier bot selection");await click("Retry the same save");
 expect(vi.mocked(appointmentApi.prepare).mock.calls[1][2].bot).toEqual({address:"follow_up",team_revision:1});
});

it("keeps uncertain requests when access is revoked and does not reveal them on denied restore",async()=>{
 vi.mocked(appointmentApi.prepare).mockRejectedValueOnce(new WorkspaceApiError(403));
 await mount();await share();await click("Prepare appointment proposal");expect(lost).toHaveBeenCalledOnce();
 const before=structuredClone(records.get(address));expect(before?.value).toBeTruthy();slot=null;await restart();
 vi.mocked(access.authorize).mockRejectedValue(new WorkspaceApiError(403));await click("Restore appointment draft");
 expect(records.get(address)).toEqual(before);expect(container.textContent).not.toContain("Retained choice");
 expect(access.denied).toHaveBeenCalledOnce();expect(appointmentApi.prepare).toHaveBeenCalledOnce();
});

it("requires a current authorized read before explicitly setting a rejected request aside",async()=>{
 vi.mocked(appointmentApi.prepare).mockRejectedValueOnce(new WorkspaceApiError(409));
 await mount();await share();await click("Prepare appointment proposal");expect(button("Set aside rejected appointment request")).toBeUndefined();
 await click("Check rejected appointment request");expect(access.authorize).toHaveBeenCalledOnce();expect(data()?.pending).toBeTruthy();
 await click("Set aside rejected appointment request");expect(records.get(address)?.value).toBeNull();
 expect(button("Prepare appointment proposal")!.disabled).toBe(true);expect(appointmentApi.prepare).toHaveBeenCalledOnce();
});

it("does not offer set-aside for an unknown response",async()=>{
 vi.mocked(appointmentApi.prepare).mockRejectedValueOnce(new WorkspaceApiError(503));
 await mount();await share();await click("Prepare appointment proposal");
 expect(button("Check rejected appointment request")).toBeUndefined();expect(button("Discard retained appointment choices")).toBeUndefined();expect(data()?.pending).toBeTruthy();
});

it("does not send when journaling fails, and keeps the earlier durable choice",async()=>{
 await mount();const before=structuredClone(records.get(address));failWrites=true;await share();await click("Prepare appointment proposal");
 expect(appointmentApi.prepare).not.toHaveBeenCalled();expect(records.get(address)).toEqual(before);
 expect(button("Retry the same save")!.disabled).toBe(true);expect(container.textContent).toContain("Local editor storage is unavailable");
});

it.each([null,undefined])("fails closed without an authenticated recovery store (%s)",async context=>{
 // undefined must be passed directly, bypassing the helper's default.
 await act(async()=>root.render(<EditorRecoveryContext.Provider value={context}><AppointmentPanel workspaceId={workspaceId}
  identity={identity} bot={bot} enabled locked={false} selectedSlot={slot}/></EditorRecoveryContext.Provider>));
 expect(button("Prepare appointment proposal")!.disabled).toBe(true);expect(appointmentApi.prepare).not.toHaveBeenCalled();
});

it("retains malformed requests without submitting or discarding them",async()=>{
 vi.mocked(appointmentApi.prepare).mockRejectedValueOnce(new WorkspaceApiError(503));
 await mount();await share();await click("Prepare appointment proposal");
 (data()!.pending as {body:Record<string,unknown>}).body.unapprovedExtra=true;
 const before=structuredClone(records.get(address));slot=null;await restart();await click("Restore appointment draft");
 expect(container.textContent).toContain("could not be restored");expect(records.get(address)).toEqual(before);expect(appointmentApi.prepare).toHaveBeenCalledOnce();
});

it("fences an old identity's in-flight restoration without clearing the retained journal",async()=>{
 await mount();slot=null;await restart();let resolve!:(value:ReturnType<typeof catalog>)=>void;
 vi.mocked(appointmentApi.catalog).mockImplementationOnce(()=>new Promise(r=>resolve=r));
 await click("Restore appointment draft");const before=structuredClone(records.get(address));
 await mount(access,{...identity,getToken:vi.fn()});await act(async()=>resolve(catalog()));
 expect(container.textContent).not.toContain("Retained choice");expect(records.get(address)).toEqual(before);expect(appointmentApi.prepare).not.toHaveBeenCalled();
});

it("retains an uncertain decision when its successful reply cannot clear local storage",async()=>{
 await mount();await share();await click("Prepare appointment proposal");
 vi.mocked(appointmentApi.decide).mockImplementationOnce(async()=>{failWrites=true;return item("approved");});
 await click("Approve this appointment change");expect(data()?.pending).toMatchObject({kind:"decide",body:{choice:"approve"}});
 expect(button("Retry the same save")!.disabled).toBe(true);failWrites=false;slot=null;await restart();
 vi.mocked(appointmentApi.read).mockResolvedValue(item("approved"));await click("Restore appointment draft");
 expect(appointmentApi.decide).toHaveBeenCalledOnce();await click("Retry the same save");expect(records.get(address)?.value).toBeNull();
});
it("binds the retained decision description to the reviewed proposal instead of a different form selection",async()=>{
 const saved=item("pending_approval","reschedule");vi.mocked(appointmentApi.catalog).mockResolvedValue(catalog([saved]));vi.mocked(appointmentApi.read).mockResolvedValue(saved);
 await mount();const entry=container.querySelector<HTMLButtonElement>('details li button')!;await act(async()=>entry.click());
 vi.mocked(appointmentApi.decide).mockRejectedValueOnce(new WorkspaceApiError(503));await click("Approve this appointment change");
 expect(data()).toMatchObject({action:"reschedule",slot:saved.intent.slot,pending:{kind:"decide",ticket:saved.ticket_id}});
});
async function openApproved(dispatched=false){
 const value=item("approved");if(dispatched){value.dispatch_started=true;value.operation_status="unknown";value.execution_error="appointment_outcome_unconfirmed";}
 vi.mocked(appointmentApi.catalog).mockResolvedValue(catalog([value]));vi.mocked(appointmentApi.read).mockResolvedValue(value);
 await mount();await act(async()=>container.querySelector<HTMLButtonElement>("details li button")!.click());return value;
}
it.each(["submit","reconcile","retry"] as const)("retains exact %s through a lost response, restart and later expiry without automatic I/O",async mode=>{
 vi.mocked(appointmentApi.execute).mockImplementationOnce(async(_w,_i,ticket,body)=>{
  expect(data()?.pending).toEqual({kind:"execute",ticket,body});throw new WorkspaceApiError(503);
 });
 await openApproved(mode!=="submit");await click(mode==="submit"?"Send approved appointment change":mode==="reconcile"?"Check saved result":"Retry the same appointment change");
 const first=vi.mocked(appointmentApi.execute).mock.calls[0];expect(draft()?.pending).toBe(first[3].operation_id);
 await act(async()=>vi.advanceTimersByTimeAsync(180001));slot=null;await restart();
 expect(appointmentApi.execute).toHaveBeenCalledOnce();await click("Restore appointment draft");
 expect(appointmentApi.execute).toHaveBeenCalledOnce();expect(container.textContent).toContain("Recovering keeps the same operation");
 expect(container.querySelector("article")!.textContent).toContain("Last known proposal status: Approved. The retained request is unconfirmed.");
 expect(container.textContent).toContain("Approval expired while this request was unconfirmed. Recover the same request first");
 expect(container.textContent).not.toContain("expired before sending");expect(button("Withdraw proposal")).toBeUndefined();
 expect(container.querySelector<HTMLInputElement>('input[type="checkbox"]')!.checked).toBe(false);
 vi.mocked(appointmentApi.execute).mockResolvedValue(saved());await click("Recover the same request");
 expect(vi.mocked(appointmentApi.execute).mock.calls[1].slice(0,4)).toEqual(first.slice(0,4));expect(records.get(address)?.value).toBeNull();
 expect(appointmentApi.prepare).not.toHaveBeenCalled();expect(appointmentApi.decide).not.toHaveBeenCalled();
});
it("keeps the exact execution after a durable result cannot clear its journal",async()=>{
 vi.mocked(appointmentApi.execute).mockImplementationOnce(async()=>{failWrites=true;return saved();});
 await openApproved();await click("Send approved appointment change");const first=structuredClone(data()?.pending);
 expect(first).toMatchObject({kind:"execute",body:{mode:"submit"}});expect(button("Recover the same request")!.disabled).toBe(true);
 failWrites=false;slot=null;await restart();vi.mocked(appointmentApi.read).mockResolvedValue(saved());await click("Restore appointment draft");
 expect(appointmentApi.execute).toHaveBeenCalledOnce();expect(data()?.pending).toEqual(first);
 expect(container.textContent).toContain("Last known proposal status: Appointment saved. The retained request is unconfirmed.");
 vi.mocked(appointmentApi.execute).mockResolvedValue(saved());await click("Recover the same request");expect(records.get(address)?.value).toBeNull();
});
it("preserves a denied execution for authorized recovery without showing a private receipt",async()=>{
 vi.mocked(appointmentApi.execute).mockRejectedValueOnce(new WorkspaceApiError(403));await openApproved();await click("Send approved appointment change");
 const before=structuredClone(records.get(address));expect(lost).toHaveBeenCalledOnce();expect(container.querySelector("article")).toBeNull();
 slot=null;await restart();vi.mocked(access.authorize).mockRejectedValue(new WorkspaceApiError(403));await click("Restore appointment draft");
 expect(records.get(address)).toEqual(before);expect(appointmentApi.execute).toHaveBeenCalledOnce();expect(container.textContent).not.toContain("Retained choice");
});
it("does not submit an execution when the exact command cannot be stored",async()=>{
 await openApproved();const before=structuredClone(records.get(address));failWrites=true;await click("Send approved appointment change");
 expect(appointmentApi.execute).not.toHaveBeenCalled();expect(records.get(address)).toEqual(before);
});
it("requires a current ticket read before setting aside a rejected execution and never cancels its operation",async()=>{
 const value=await openApproved(true);vi.mocked(appointmentApi.execute).mockRejectedValueOnce(new WorkspaceApiError(409));
 await click("Retry the same appointment change");const before=structuredClone(data()?.pending);await click("Check rejected appointment request");
 expect(appointmentApi.read).toHaveBeenLastCalledWith(workspaceId,identity,value.ticket_id,expect.any(AbortSignal));expect(data()?.pending).toEqual(before);
 await click("Set aside rejected appointment request");expect(records.get(address)?.value).toBeNull();
 expect(container.textContent).toContain("does not cancel an existing operation");expect(appointmentApi.execute).toHaveBeenCalledOnce();expect(appointmentApi.decide).not.toHaveBeenCalled();
 await share();expect(button("Prepare appointment proposal")!.disabled).toBe(true);
});
it.each(["mode","ticket","extra"])("retains malformed execution %s without attempting recovery I/O",async fault=>{
 vi.mocked(appointmentApi.execute).mockRejectedValueOnce(new WorkspaceApiError(503));await openApproved();await click("Send approved appointment change");
 const pending=data()!.pending as {ticket:string;body:Record<string,unknown>};
 if(fault==="mode")pending.body.mode=["submit"];
 if(fault==="ticket")pending.ticket=workspaceId;
 if(fault==="extra")pending.body.idempotency_key=workspaceId;
 const before=structuredClone(records.get(address));slot=null;await restart();await click("Restore appointment draft");
 expect(container.textContent).toContain("could not be restored");expect(records.get(address)).toEqual(before);expect(appointmentApi.execute).toHaveBeenCalledOnce();
});
