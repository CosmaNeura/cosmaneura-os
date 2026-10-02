import {act} from "react";
import {createRoot,type Root} from "react-dom/client";
import {afterEach,beforeEach,expect,it,vi} from "vitest";
import {AppointmentPanel} from "./AppointmentPanel";
import {appointmentApi, type AppointmentItem} from "./appointment-api";
import {catalog,id,item,linked,saved,workspaceId} from "./appointment-test-fixture";
import {DraftJournal} from "./draft-journal";
import {memoryDraftStorage} from "./draft-test-fixture";
import {EditorRecoveryContext,type EditorRecoveryAccess} from "./editor-recovery";
import {WorkspaceApiError,type Workspace} from "./workspace-api";
vi.mock("./appointment-api",()=>({appointmentApi:{catalog:vi.fn(),current:vi.fn(),prepare:vi.fn(),read:vi.fn(),decide:vi.fn(),execute:vi.fn()}}));
const identity={mode:"clerk_jwt" as const,getToken:vi.fn()};
let root:Root,container:HTMLDivElement,access:EditorRecoveryAccess;
let slot:AppointmentItem["intent"]["slot"];
let selectionExpiresAt:string|undefined;
let onRefreshSelectedTime:(()=>void)|undefined,refreshingSelection:boolean,selectionRefreshStatus:"failed"|"unavailable"|undefined;
const lost=vi.fn();
async function mount(wid=workspaceId){await act(async()=>root.render(<EditorRecoveryContext.Provider value={access}><AppointmentPanel workspaceId={wid} identity={identity}
  bot={{address:"follow_up",team_revision:1}} enabled locked={false} selectedSlot={slot} selectionExpiresAt={selectionExpiresAt}
  onRefreshSelectedTime={onRefreshSelectedTime} refreshingSelection={refreshingSelection} selectionRefreshStatus={selectionRefreshStatus} onAccessLost={lost}/></EditorRecoveryContext.Provider>));}
function button(text:string){const match=[...container.querySelectorAll("button")].find(v=>v.textContent===text);if(!match)throw new Error("Missing button: "+text);return match;}
async function click(text:string){await act(async()=>button(text).click());}
async function share(){await act(async()=>container.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());}
beforeEach(async()=>{
 vi.unstubAllEnvs();
 Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.useFakeTimers();vi.setSystemTime(new Date("2026-09-21T15:00:00Z"));vi.clearAllMocks();
 access={journal:new DraftJournal(await memoryDraftStorage()({scope:"test"})),workspaceId,
   authorize:vi.fn().mockResolvedValue({id:workspaceId} as Workspace),denied:vi.fn()};
 slot=item().intent.slot;selectionExpiresAt=undefined;onRefreshSelectedTime=undefined;refreshingSelection=false;selectionRefreshStatus=undefined;vi.mocked(appointmentApi.catalog).mockResolvedValue(catalog());
 vi.mocked(appointmentApi.current).mockResolvedValue({workspace_id:workspaceId,label:"Invented",appointment:linked(),checked_at:new Date().toISOString()});
 vi.mocked(appointmentApi.prepare).mockResolvedValue(item());vi.mocked(appointmentApi.read).mockResolvedValue(item());
 vi.mocked(appointmentApi.decide).mockImplementation(async(_w,_i,_t,body)=>item(body.choice==="approve"?"approved":"rejected"));
 container=document.createElement("div");document.body.append(container);root=createRoot(container);
});
afterEach(async()=>{await act(async()=>root.unmount());access.journal.close();container.remove();vi.useRealTimers();});
it("requires deliberate sharing and review before a pending approval, then allows withdrawal",async()=>{
 await mount();expect(appointmentApi.prepare).not.toHaveBeenCalled();expect(button("Prepare appointment proposal").disabled).toBe(true);
 await share();await click("Prepare appointment proposal");expect(container.textContent).toContain("Awaiting your review");
 expect(appointmentApi.decide).not.toHaveBeenCalled();await click("Approve this appointment change");
 expect(container.textContent).toContain("Send the approved change");expect(appointmentApi.execute).not.toHaveBeenCalled();await click("Withdraw proposal");
 expect(container.textContent).toContain("Withdrawn.");expect(appointmentApi.decide).toHaveBeenCalledTimes(2);
});
it("hosted users can prepare, approve and withdraw without suggesting the visit was booked",async()=>{
 vi.stubEnv("VITE_WORKSPACE_HOSTED_ENABLED","true");
 await mount();expect(container.textContent).toContain("Booking or changing a visit is not available yet");
 await share();await click("Prepare appointment proposal");await click("Approve this appointment change");
 expect(container.textContent).toContain("Approval saved for this proposal");
 expect(container.textContent).toContain("Scheduling has not booked or changed the visit");
 expect([...container.querySelectorAll("button")].some(b=>b.textContent==="Send approved appointment change")).toBe(false);
 expect(appointmentApi.execute).not.toHaveBeenCalled();await click("Withdraw proposal");
 expect(container.textContent).toContain("Withdrawn.");expect(appointmentApi.decide).toHaveBeenCalledTimes(2);
});
it("hosted mode retains historical receipts without offering operation checks or retries",async()=>{
 vi.stubEnv("VITE_WORKSPACE_HOSTED_ENABLED","true");
 await openExisting(saved());expect(container.textContent).toContain("Last verified");
 expect([...container.querySelectorAll("button")].some(b=>["Check saved result","Retry the same appointment change"].includes(b.textContent??""))).toBe(false);
 await click("Refresh saved proposal");expect(appointmentApi.execute).not.toHaveBeenCalled();
});
it("switching to hosted mode preserves a lost execution request and blocks recovery dispatch",async()=>{
 vi.mocked(appointmentApi.execute).mockRejectedValueOnce(new WorkspaceApiError(503));
 await openExisting(item("approved"));await click("Send approved appointment change");
 vi.stubEnv("VITE_WORKSPACE_HOSTED_ENABLED","true");await mount();
 expect(container.textContent).toContain("its outcome remains unconfirmed");
 expect(button("Recover the same request").disabled).toBe(true);
 await click("Recover the same request");expect(appointmentApi.execute).toHaveBeenCalledOnce();
 expect(container.textContent).not.toContain("Scheduling saved this appointment change.");
 expect([...container.querySelectorAll("button")].some(b=>b.textContent==="Withdraw proposal")).toBe(false);
});
it("retains the selected time and proposal control while expiry disables new preparation",async()=>{
 selectionExpiresAt=new Date(Date.now()+60000).toISOString();await mount();await share();
 const prepare=button("Prepare appointment proposal"),selected=[...container.querySelectorAll("p")].find(p=>p.textContent?.startsWith("Selected time:"))!;
 const selectedText=selected.textContent;expect(prepare.disabled).toBe(false);
 vi.setSystemTime(Date.now()+60000);await mount();
 expect(button("Prepare appointment proposal")).toBe(prepare);expect(prepare.disabled).toBe(true);
 expect(selected.isConnected).toBe(true);expect(selected.textContent).toBe(selectedText);
 expect(container.querySelector<HTMLInputElement>('input[type="checkbox"]')!.checked).toBe(false);
 expect([...container.querySelectorAll('[role="status"] span')].find(v=>v.getAttribute("aria-hidden")==="false")?.textContent).toContain("This check expired");
 expect(appointmentApi.prepare).not.toHaveBeenCalled();
});
it("does not prepare from a click that arrives at the deadline before rerender",async()=>{
 selectionExpiresAt=new Date(Date.now()+60000).toISOString();await mount();await share();
 const prepare=button("Prepare appointment proposal");expect(prepare.disabled).toBe(false);
 vi.setSystemTime(Date.now()+60000);await act(async()=>prepare.click());
 expect(appointmentApi.prepare).not.toHaveBeenCalled();expect(access.journal).toBeDefined();
});
it("keeps the same refresh control fresh, busy and expired while requiring a new share acknowledgement",async()=>{
 const refresh=vi.fn();onRefreshSelectedTime=refresh;selectionExpiresAt=new Date(Date.now()+60000).toISOString();
 await mount();await share();const control=button("Refresh this time"),prepare=button("Prepare appointment proposal"),selected=[...container.querySelectorAll("p")].find(p=>p.textContent?.startsWith("Selected time:"))!;
 expect(prepare.disabled).toBe(false);expect(refresh).not.toHaveBeenCalled();await click("Refresh this time");
 expect(refresh).toHaveBeenCalledTimes(1);expect(prepare.disabled).toBe(true);expect(container.querySelector<HTMLInputElement>('input[type="checkbox"]')!.checked).toBe(false);
 refreshingSelection=true;await mount();expect(button("Refresh this time")).toBe(control);expect(control.disabled).toBe(true);expect(control.getAttribute("aria-busy")).toBe("true");
 expect(selected.isConnected).toBe(true);expect(button("Prepare appointment proposal")).toBe(prepare);
 refreshingSelection=false;slot={...slot!};selectionExpiresAt=new Date(Date.now()+60000).toISOString();await mount();
 expect(control.disabled).toBe(false);expect(prepare.disabled).toBe(true);await share();expect(prepare.disabled).toBe(false);
 vi.setSystemTime(Date.now()+60000);await mount();expect(button("Refresh this time")).toBe(control);expect(control.disabled).toBe(false);expect(prepare.disabled).toBe(true);
 expect(appointmentApi.prepare).not.toHaveBeenCalled();expect(appointmentApi.decide).not.toHaveBeenCalled();expect(appointmentApi.execute).not.toHaveBeenCalled();
});
it.each(["failed","unavailable"] as const)("keeps the retained choice and blocks preparation after refresh is %s",async result=>{
 onRefreshSelectedTime=vi.fn();selectionExpiresAt=new Date(Date.now()+60000).toISOString();await mount();await share();
 const retained=[...container.querySelectorAll("p")].find(p=>p.textContent?.startsWith("Retained choice:"))!.textContent;
 await click("Refresh this time");selectionRefreshStatus=result;if(result==="unavailable")slot=null;await mount();await share();
 expect([...container.querySelectorAll("p")].find(p=>p.textContent?.startsWith("Retained choice:"))!.textContent).toBe(retained);
 expect(button("Prepare appointment proposal").disabled).toBe(true);
 expect(button("Refresh this time").disabled).toBe(result==="unavailable");
 expect([...container.querySelectorAll('[role="status"] span')].find(s=>s.getAttribute("aria-hidden")==="false")?.textContent).toContain(result==="failed"?"could not be confirmed":"no longer available");
 expect(appointmentApi.prepare).not.toHaveBeenCalled();expect(appointmentApi.decide).not.toHaveBeenCalled();expect(appointmentApi.execute).not.toHaveBeenCalled();
});
it("does not refresh or replace an exact unconfirmed proposal request",async()=>{
 onRefreshSelectedTime=vi.fn();vi.mocked(appointmentApi.prepare).mockRejectedValueOnce(new WorkspaceApiError(503));
 await mount();await share();await click("Prepare appointment proposal");const original=vi.mocked(appointmentApi.prepare).mock.calls[0][2];
 expect(button("Refresh this time").disabled).toBe(true);await click("Refresh this time");expect(onRefreshSelectedTime).not.toHaveBeenCalled();
 await click("Retry the same save");expect(vi.mocked(appointmentApi.prepare).mock.calls[1][2]).toEqual(original);
});
it("expired availability does not block a separately reviewed cancellation",async()=>{
 selectionExpiresAt=new Date(Date.now()-1).toISOString();await mount();await click("Refresh linked visit");
 await act(async()=>{const select=container.querySelector("select")!;select.value="cancel";select.dispatchEvent(new Event("change",{bubbles:true}));});
 vi.mocked(appointmentApi.prepare).mockResolvedValue(item("pending_approval","cancel"));await share();await click("Prepare appointment proposal");
 expect(vi.mocked(appointmentApi.prepare).mock.calls[0][2]).toMatchObject({action:"cancel",slot:null,share:true});
});
it("keeps the exact unknown save even when displayed availability expires",async()=>{
 vi.mocked(appointmentApi.prepare).mockRejectedValueOnce(new WorkspaceApiError(503));
 await mount();await share();await click("Prepare appointment proposal");
 const first=vi.mocked(appointmentApi.prepare).mock.calls[0][2];slot=null;await mount();
 expect(button("Prepare appointment proposal").disabled).toBe(true);await click("Retry the same save");
 expect(vi.mocked(appointmentApi.prepare).mock.calls[1][2]).toEqual(first);
 expect(container.textContent).toContain("Proposal saved");
});
it("discards a committed reply after changing workspace without copying private proposal state",async()=>{
 let resolve!:(v:AppointmentItem)=>void;vi.mocked(appointmentApi.prepare).mockImplementation(()=>new Promise(r=>resolve=r));
 await mount();await share();await click("Prepare appointment proposal");await mount(id(99));
 await act(async()=>resolve(item()));expect(container.textContent).not.toContain("Awaiting your review");
 expect(container.querySelector("article")).toBeNull();
});
it("expired proposals remain withdrawable and cannot be approved",async()=>{
 const expired=item();expired.intent.expires_at=new Date(Date.now()-1).toISOString();
 vi.mocked(appointmentApi.catalog).mockResolvedValue(catalog([expired]));vi.mocked(appointmentApi.read).mockResolvedValue(expired);
 await mount();
 const label="Book another visit · "+new Date(expired.intent.slot!.starts_at).toLocaleString([], {dateStyle:"medium",timeStyle:"short"})+" · Awaiting review";
 await click(label);
 expect(button("Approve this appointment change").disabled).toBe(true);expect(button("Withdraw proposal").disabled).toBe(false);
 expect(container.textContent).toContain("This proposal expired");
});
it("keeps appointment persistence, calendar failure and visit completion distinct",async()=>{
 const result=saved();result.calendar_state="failed";result.result!.calendar_state="failed";
 result.execution_error="appointment_outcome_unconfirmed";
 vi.mocked(appointmentApi.catalog).mockResolvedValue(catalog([result]));vi.mocked(appointmentApi.read).mockResolvedValue(result);
 await mount();const entry=container.querySelector<HTMLButtonElement>("details li button")!;
 await act(async()=>entry.click());
 expect(container.textContent).toContain("Scheduling saved this appointment change.");
 expect(container.textContent).toContain("synchronization failed");
 expect(container.textContent).toContain("last verified result");
 expect([...container.querySelectorAll("button")].some(b=>b.textContent==="Withdraw proposal")).toBe(false);
 expect(container.textContent).not.toContain("Visit completed");
 const recovered={...result,calendar_state:"synced" as const,execution_error:null,result:{...result.result!,calendar_state:"synced" as const}};
 vi.mocked(appointmentApi.execute).mockResolvedValue(recovered);
 await click("Check saved result");
 expect(vi.mocked(appointmentApi.execute).mock.calls[0][3]).toEqual({operation_id:result.operation_id,revision_id:result.revision_id,payload_hash:result.payload_hash,mode:"reconcile"});
 expect(container.textContent).toContain("Calendar: synchronized");
 expect(container.textContent).not.toContain("synchronization failed");
});
it("loads the linked visit before offering reschedule or cancellation",async()=>{
 await mount();const select=container.querySelector("select")!;
 expect((select.querySelector('option[value="cancel"]') as HTMLOptionElement).disabled).toBe(true);
 await click("Refresh linked visit");
 expect((select.querySelector('option[value="cancel"]') as HTMLOptionElement).disabled).toBe(false);
 await act(async()=>{select.value="cancel";select.dispatchEvent(new Event("change",{bubbles:true}));});
 vi.mocked(appointmentApi.prepare).mockResolvedValue(item("pending_approval","cancel"));
 await share();await click("Prepare appointment proposal");
 expect(vi.mocked(appointmentApi.prepare).mock.calls[0][2]).toMatchObject({action:"cancel",slot:null,share:true});
});
it("clears proposal detail and tells the parent when access is revoked",async()=>{
 await mount();await share();await click("Prepare appointment proposal");
 vi.mocked(appointmentApi.decide).mockRejectedValue(new WorkspaceApiError(403));await click("Approve this appointment change");
 expect(container.querySelector("article")).toBeNull();expect(lost).toHaveBeenCalledTimes(1);
});
async function openExisting(value:AppointmentItem){
 vi.mocked(appointmentApi.catalog).mockResolvedValue(catalog([value]));vi.mocked(appointmentApi.read).mockResolvedValue(value);
 await mount();await act(async()=>container.querySelector<HTMLButtonElement>("details li button")!.click());
}
it.each(["book","reschedule","cancel"] as const)("requires an explicit send after approval of %s",async action=>{
 const approved=item("approved",action);vi.mocked(appointmentApi.execute).mockResolvedValue(saved(action));
 await openExisting(approved);expect(appointmentApi.execute).not.toHaveBeenCalled();
 expect(button("Send approved appointment change").disabled).toBe(false);await click("Send approved appointment change");
 expect(vi.mocked(appointmentApi.execute).mock.calls[0].slice(0,4)).toEqual([workspaceId,identity,approved.ticket_id,
  {operation_id:approved.operation_id,revision_id:approved.revision_id,payload_hash:approved.payload_hash,mode:"submit"}]);
 expect(container.textContent).toContain("Scheduling saved this appointment change.");expect(container.textContent).toContain("synchronization pending");
 expect(appointmentApi.decide).not.toHaveBeenCalled();expect(appointmentApi.prepare).not.toHaveBeenCalled();
});
it("keeps unknown operations unconfirmed and explicitly retries only the same operation",async()=>{
 const unknown={...item("approved"),operation_status:"unknown" as const,dispatch_started:true,execution_error:"appointment_outcome_unconfirmed" as const};
 vi.mocked(appointmentApi.execute).mockResolvedValue(unknown);await openExisting(unknown);
 expect(container.textContent).toContain("appointment result is unconfirmed");expect(appointmentApi.execute).not.toHaveBeenCalled();
 await share();expect(button("Prepare appointment proposal").disabled).toBe(true);
 await click("Check saved result");await click("Retry the same appointment change");
 expect(vi.mocked(appointmentApi.execute).mock.calls.map(v=>v[3])).toEqual(["reconcile","retry"].map(mode=>({
  operation_id:unknown.operation_id,revision_id:unknown.revision_id,payload_hash:unknown.payload_hash,mode})));
 expect(container.textContent).not.toContain("Scheduling saved this appointment change.");expect(appointmentApi.prepare).not.toHaveBeenCalled();
});
it.each([false,true])("expiry disables dispatch but retains explicit recovery (dispatched=%s)",async dispatched=>{
 const expired=item("approved");expired.intent.expires_at=new Date(Date.now()-1).toISOString();
 if(dispatched){expired.operation_status="unknown";expired.dispatch_started=true;expired.execution_error="appointment_outcome_unconfirmed";}
 await openExisting(expired);
 if(dispatched){expect(button("Check saved result").disabled).toBe(false);expect(button("Retry the same appointment change").disabled).toBe(true);}
 else {expect(button("Send approved appointment change").disabled).toBe(true);expect(button("Withdraw proposal").disabled).toBe(false);
  expect(container.textContent).toContain("Approval expired before sending. Withdraw this proposal before preparing a fresh one.");}
 expect(container.textContent).not.toContain("The retained request is unconfirmed.");
 expect(appointmentApi.execute).not.toHaveBeenCalled();
});
it.each(["submit","retry"] as const)("keeps a lost %s outcome unconfirmed when approval expires",async mode=>{
 const approved=item("approved");
 if(mode==="retry"){approved.dispatch_started=true;approved.operation_status="unknown";approved.execution_error="appointment_outcome_unconfirmed";}
 vi.mocked(appointmentApi.execute).mockRejectedValueOnce(new WorkspaceApiError(503));
 await openExisting(approved);await click(mode==="submit"?"Send approved appointment change":"Retry the same appointment change");
 expect(container.textContent).toContain("Last known proposal status: Approved. The retained request is unconfirmed.");
 await act(async()=>vi.advanceTimersByTimeAsync(180001));
 const card=container.querySelector("article")!;
 expect(card.textContent).toContain("Approval expired while this request was unconfirmed. Recover the same request first");
 expect(card.textContent).not.toContain("expired before sending");
 expect(card.textContent).not.toContain("Approved. Send the approved change");
 expect([...card.querySelectorAll("button")].some(value=>value.textContent==="Withdraw proposal")).toBe(false);
 expect(button("Recover the same request").disabled).toBe(false);
 expect(appointmentApi.execute).toHaveBeenCalledOnce();expect(appointmentApi.decide).not.toHaveBeenCalled();
});
it("refreshing stored history never dispatches or claims a fresh receiver check",async()=>{
 const value=saved();await openExisting(value);await click("Refresh saved proposal");
 expect(appointmentApi.execute).not.toHaveBeenCalled();expect(container.textContent).toContain("Last verified");
});
it("fences a late execution response after workspace change",async()=>{
 let resolve!:(value:AppointmentItem)=>void;vi.mocked(appointmentApi.execute).mockImplementation(()=>new Promise(r=>resolve=r));
 await openExisting(item("approved"));await click("Send approved appointment change");await mount(id(99));
 await act(async()=>resolve(saved()));expect(container.querySelector("article")).toBeNull();
 expect(container.textContent).not.toContain("Scheduling saved this appointment change.");
});
