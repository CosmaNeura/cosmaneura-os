import {act} from "react";
import {createRoot,type Root} from "react-dom/client";
import {afterEach,beforeEach,expect,it,vi} from "vitest";
import {SchedulingPanel} from "./SchedulingPanel";
import {readAvailability,type Availability} from "./scheduling-api";
import {WorkspaceApiError} from "./workspace-api";
vi.mock("./scheduling-api",()=>({readAvailability:vi.fn()}));
vi.mock("./appointment-api",()=>({APPOINTMENTS_BUILD:true}));
vi.mock("./AppointmentPanel",()=>({AppointmentPanel:({selectedSlot,selectionExpiresAt,onRefreshSelectedTime,locked,refreshingSelection,selectionRefreshStatus}:{
 selectedSlot:Availability["slots"][number]|null;selectionExpiresAt?:string;onRefreshSelectedTime?:()=>void;locked:boolean;refreshingSelection?:boolean;selectionRefreshStatus?:string})=>
 <><output data-selected={selectedSlot?.starts_at??""} data-end={selectedSlot?.ends_at??""} data-expires={selectionExpiresAt} data-status={selectionRefreshStatus} data-busy={refreshingSelection}/>
 <button disabled={locked||!selectedSlot} onClick={onRefreshSelectedTime}>Refresh this time</button></> }));
const identity={mode:"clerk_jwt" as const,getToken:vi.fn()};
let root:Root,container:HTMLDivElement;
const value=():Availability=>({workspace_id:"w",label:"Invented follow-up",source:"google_primary",window:{starts_at:"2026-09-21T00:00:00Z",ends_at:"2026-09-28T00:00:00Z"},
 checked_at:new Date().toISOString(),valid_until:new Date(Date.now()+60000).toISOString(),slots:[{starts_at:"2026-09-21T09:00:00Z",ends_at:"2026-09-21T09:30:00Z"}]});
const accessLost=vi.fn();
async function mount(address="follow_up",enabled=true,revision=1){await act(async()=>root.render(<SchedulingPanel workspaceId="w" identity={identity} bot={{address,team_revision:revision}} name="Follow-up" enabled={enabled} locked={false} onAccessLost={accessLost}/>));}
async function click(){await act(async()=>container.querySelector("button")!.click());}
const refreshSelected=()=>[...container.querySelectorAll("button")].find(button=>button.textContent==="Refresh this time")!;
beforeEach(()=>{Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.useFakeTimers();vi.clearAllMocks();vi.mocked(readAvailability).mockReset().mockResolvedValue(value());container=document.createElement("div");document.body.append(container);root=createRoot(container);});
afterEach(async()=>{await act(async()=>root.unmount());container.remove();vi.useRealTimers();});
it("expires checked slots without removing controls or the selected time",async()=>{
 await mount();expect(readAvailability).not.toHaveBeenCalled();await click();expect(container.textContent).toContain("Google Calendar checked");expect(container.textContent).toContain("Nothing has been reserved");
 const row=container.querySelector("li"),choose=container.querySelector<HTMLButtonElement>("li button")!;
 await act(async()=>choose.click());const selected=container.querySelector("output")!.dataset.selected;
 await act(async()=>vi.advanceTimersByTime(60001));
 expect(container.querySelector("li")).toBe(row);expect(choose.disabled).toBe(true);expect(choose.getAttribute("aria-pressed")).toBe("true");
 expect(container.querySelector("output")!.dataset.selected).toBe(selected);expect(selected).not.toBe("");
 expect([...container.querySelectorAll('[role="status"] span')].find(v=>v.getAttribute("aria-hidden")==="false")?.textContent).toContain("Availability expired");
 expect(readAvailability).toHaveBeenCalledTimes(1);
});
it("refuses a slot click at expiry even before the timer renders",async()=>{
 await mount();await click();const choose=container.querySelector<HTMLButtonElement>("li button")!;
 vi.setSystemTime(Date.now()+60000);await act(async()=>choose.click());
 expect(container.querySelector("output")!.dataset.selected).toBe("");expect(choose.disabled).toBe(true);
});
it.each(["bot","revision","pause"])("clears results when %s changes",async fault=>{
 await mount();await click();await mount(fault==="bot"?"another":"follow_up",fault!=="pause",fault==="revision"?2:1);
 expect(container.textContent).not.toContain("Google Calendar checked");
});
it("discards a reply after leaving the bot",async()=>{
 let resolve!:(v:Availability)=>void;vi.mocked(readAvailability).mockImplementation(()=>new Promise(r=>resolve=r));
 await mount();await click();await mount("another");await act(async()=>resolve(value()));expect(container.textContent).not.toContain("Google Calendar checked");
});
it("failure clears prior slots and cannot report an empty calendar",async()=>{
 await mount();await click();vi.mocked(readAvailability).mockRejectedValue(new Error("PRIVATE"));await click();
 expect(container.textContent).toContain("could not be confirmed");expect(container.textContent).not.toContain("No available times");expect(container.querySelectorAll("li")).toHaveLength(0);
});
it("refreshes the exact selected interval in place without clearing the expanded list while waiting",async()=>{
 const initial=value();initial.slots=Array.from({length:25},(_,n)=>({starts_at:new Date(Date.parse(initial.slots[0].starts_at)+n*1800000).toISOString(),ends_at:new Date(Date.parse(initial.slots[0].ends_at)+n*1800000).toISOString()}));
 vi.mocked(readAvailability).mockResolvedValueOnce(initial);await mount();await click();
 await act(async()=>[...container.querySelectorAll("button")].find(b=>b.textContent==="Show more times")!.click());
 await act(async()=>container.querySelectorAll<HTMLButtonElement>("li button")[17].click());
 const rows=[...container.querySelectorAll("li")],selected={...container.querySelector("output")!.dataset},refresh=refreshSelected();
 await act(async()=>vi.advanceTimersByTime(60001));
 let resolve!:(result:Availability)=>void;vi.mocked(readAvailability).mockImplementationOnce(()=>new Promise(r=>resolve=r));
 await act(async()=>refresh.click());
 expect([...container.querySelectorAll("li")]).toEqual(rows);expect(container.querySelector("output")!.dataset.selected).toBe(selected.selected);
 expect(refreshSelected()).toBe(refresh);expect(refresh.disabled).toBe(true);expect(container.querySelector("output")!.dataset.busy).toBe("true");
 const fresh={...value(),slots:[...initial.slots].reverse()};await act(async()=>resolve(fresh));
 expect(container.querySelector("output")!.dataset).toMatchObject({selected:selected.selected,end:selected.end,expires:fresh.valid_until,busy:"false"});
 expect(container.querySelectorAll("li")).toHaveLength(24);expect(refreshSelected()).toBe(refresh);expect(refresh.disabled).toBe(false);
 expect(readAvailability).toHaveBeenCalledTimes(2);expect(vi.mocked(readAvailability).mock.calls[1][3]).toEqual(vi.mocked(readAvailability).mock.calls[0][3]);
 await act(async()=>vi.advanceTimersByTime(60001));expect(readAvailability).toHaveBeenCalledTimes(2);
});
it("clears the current selection when the fresh result changes only its end time",async()=>{
 await mount();await click();await act(async()=>container.querySelector<HTMLButtonElement>("li button")!.click());
 const fresh=value();fresh.slots[0].ends_at="2026-09-21T10:00:00Z";vi.mocked(readAvailability).mockResolvedValueOnce(fresh);
 await act(async()=>refreshSelected().click());
 expect(container.querySelector("output")!.dataset).toMatchObject({selected:"",end:"",status:"unavailable"});
 expect(refreshSelected().disabled).toBe(true);expect(readAvailability).toHaveBeenCalledTimes(2);
});
it.each(["failure","expired"])("retains but invalidates the selected time after a %s refresh result",async fault=>{
 await mount();await click();await act(async()=>container.querySelector<HTMLButtonElement>("li button")!.click());
 const row=container.querySelector("li"),selected=container.querySelector("output")!.dataset.selected;
 if(fault==="failure")vi.mocked(readAvailability).mockRejectedValueOnce(new Error("PRIVATE"));
 else vi.mocked(readAvailability).mockResolvedValueOnce({...value(),valid_until:new Date(Date.now()-1).toISOString()});
 await act(async()=>refreshSelected().click());
 expect(container.querySelector("li")).toBe(row);expect(container.querySelector("output")!.dataset).toMatchObject({selected,status:"failed",busy:"false"});
 expect(Date.parse(container.querySelector("output")!.dataset.expires!)).toBeLessThan(Date.now());
 expect(container.querySelector<HTMLButtonElement>("li button")!.disabled).toBe(true);expect(refreshSelected().disabled).toBe(false);
 expect(container.textContent).not.toContain("PRIVATE");expect(readAvailability).toHaveBeenCalledTimes(2);
});
it("does not apply an in-place refresh after the bot selection changes",async()=>{
 await mount();await click();await act(async()=>container.querySelector<HTMLButtonElement>("li button")!.click());
 let resolve!:(result:Availability)=>void;vi.mocked(readAvailability).mockImplementationOnce(()=>new Promise(r=>resolve=r));
 await act(async()=>refreshSelected().click());await mount("another");await act(async()=>resolve(value()));
 expect(container.querySelector("output")!.dataset.selected).toBe("");expect(container.querySelectorAll("li")).toHaveLength(0);
 expect(readAvailability).toHaveBeenCalledTimes(2);
});

it.each([401,403])("removes previously checked slots and selected time on %s during in-place refresh",async status=>{
 await mount();await click();await act(async()=>container.querySelector<HTMLButtonElement>("li button")!.click());
 const error=new WorkspaceApiError(status);vi.mocked(readAvailability).mockRejectedValueOnce(error);
 await act(async()=>refreshSelected().click());
 expect(container.querySelector("output")!.dataset.selected).toBe("");expect(container.querySelectorAll("li")).toHaveLength(0);
 expect(container.textContent).not.toContain("Google Calendar checked");expect(container.textContent).toContain("Scheduling access is unavailable.");
 expect(accessLost).toHaveBeenCalledExactlyOnceWith(error);expect(readAvailability).toHaveBeenCalledTimes(2);
});

it("does not apply an old access denial after changing bots",async()=>{
 let reject!:(error:unknown)=>void;vi.mocked(readAvailability).mockImplementationOnce(()=>new Promise((_resolve,r)=>reject=r));
 await mount();await click();await mount("another");await act(async()=>reject(new WorkspaceApiError(403)));
 expect(accessLost).not.toHaveBeenCalled();expect(container.textContent).not.toContain("Scheduling access is unavailable.");
});
