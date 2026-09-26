import {afterEach,beforeEach,expect,it,vi} from "vitest";
import {validateAvailability} from "./scheduling-api";
const workspace="00000000-0000-4000-8000-000000000001";
const window={starts_at:"2026-09-21T00:00:00Z",ends_at:"2026-09-28T00:00:00Z"};
const bot={address:"follow_up",team_revision:2};
const identity={mode:"clerk_jwt" as const,getToken:vi.fn(async()=>"invented.token.value")};
function value():any{return {workspace_id:workspace,label:"Invented follow-up",source:"google_primary",window,checked_at:new Date().toISOString(),
 valid_until:new Date(Date.now()+60000).toISOString(),slots:[{starts_at:"2026-09-21T09:00:00Z",ends_at:"2026-09-21T09:30:00Z"}]};}
beforeEach(()=>{vi.useFakeTimers();vi.setSystemTime(new Date("2026-09-20T22:00:00Z"));vi.clearAllMocks();});
afterEach(()=>{vi.useRealTimers();vi.unstubAllEnvs();vi.unstubAllGlobals();});
it.each(["scope","source","stale","future","expiry","window","extra","duplicate","slot","large"])("rejects %s",fault=>{
 const receipt=value();
 if(fault==="scope")receipt.workspace_id="another";
 if(fault==="source")receipt.source="scheduling_only";
 if(fault==="stale")receipt.checked_at=new Date(Date.now()-31000).toISOString();
 if(fault==="future")receipt.checked_at=new Date(Date.now()+6000).toISOString();
 if(fault==="expiry")receipt.valid_until=new Date(Date.now()+61000).toISOString();
 if(fault==="window")receipt.window={...window,ends_at:"2026-09-29T00:00:00Z"};
 if(fault==="extra")receipt.private_text="PRIVATE";
 if(fault==="duplicate")receipt.slots.push(receipt.slots[0]);
 if(fault==="slot")receipt.slots[0].ends_at="2026-09-29T00:00:00Z";
 if(fault==="large")receipt.slots=Array(4097).fill(receipt.slots[0]);
 expect(()=>validateAvailability(receipt,workspace,window)).toThrow("Availability could not be confirmed");
});
async function module(){
 for(const flag of ["VITE_WORKSPACE_ENABLED","VITE_WORKSPACE_AUTHENTICATED_ENABLED","VITE_WORKSPACE_SCHEDULING_ENABLED"])vi.stubEnv(flag,"true");
 vi.stubEnv("VITE_COSMAS_ENV","synth_os");vi.stubEnv("VITE_API_BASE","http://127.0.0.1:8000");vi.resetModules();return import("./scheduling-api");
}
it("reads using a fresh session and exact private route with no ambient authority",async()=>{
 const api=await module();const fetch=vi.fn(async()=>Response.json(value(),{headers:{"Cache-Control":"no-store"}}));vi.stubGlobal("fetch",fetch);
 expect((await api.readAvailability(workspace,identity,bot,window)).source).toBe("google_primary");
 expect(identity.getToken).toHaveBeenCalledWith({skipCache:true});
 const [url,options]=fetch.mock.calls[0] as unknown as [string,RequestInit];
 expect(url).toBe(`http://127.0.0.1:8000/workspaces/${workspace}/scheduling/availability`);
 expect(options).toMatchObject({method:"POST",credentials:"omit",redirect:"error",cache:"no-store",referrerPolicy:"no-referrer"});
 expect(JSON.parse(options.body as string)).toEqual({bot,window});
});
it.each(["status","cache","oversize","abort","disabled"])("withholds unavailable %s without retry",async fault=>{
 await module();const controller=new AbortController();
 if(fault==="abort")controller.abort();
 if(fault==="disabled"){vi.stubEnv("VITE_WORKSPACE_SCHEDULING_ENABLED","false");vi.resetModules();}
 const fetch=vi.fn(async()=>fault==="oversize"?new Response(" ".repeat(1048577),{headers:{"Content-Type":"application/json","Cache-Control":"no-store"}}):
 Response.json(value(),{status:fault==="status"?503:200,headers:fault==="cache"?{}:{"Cache-Control":"no-store"}}));vi.stubGlobal("fetch",fetch);
 await expect((await import("./scheduling-api")).readAvailability(workspace,identity,bot,window,controller.signal)).rejects.toThrow("Availability could not be confirmed");
 expect(fetch).toHaveBeenCalledTimes(["abort","disabled"].includes(fault)?0:1);
});

it("bounds an unresponsive credential refresh without issuing a calendar request",async()=>{
 const api=await module();const fetch=vi.fn();vi.stubGlobal("fetch",fetch);
 const pending=api.readAvailability(workspace,{mode:"clerk_jwt",getToken:()=>new Promise(()=>{})},bot,window);
 const rejected=expect(pending).rejects.toThrow("Availability could not be confirmed");
 await vi.advanceTimersByTimeAsync(30001);await rejected;expect(fetch).not.toHaveBeenCalled();
});

it.each(["response","body"])("bounds an unresponsive %s even when abort and cancellation are ignored",async phase=>{
 const api=await module(),cancel=vi.fn(()=>new Promise<void>(()=>{})),read=vi.fn(()=>new Promise<ReadableStreamReadResult<Uint8Array>>(()=>{}));
 const response={status:200,headers:new Headers({"Content-Type":"application/json","Cache-Control":"no-store"}),body:{getReader:()=>({read,cancel,releaseLock:vi.fn()})}};
 const fetch=vi.fn(()=>phase==="response"?new Promise<Response>(()=>{}):Promise.resolve(response));vi.stubGlobal("fetch",fetch);
 const rejected=expect(api.readAvailability(workspace,identity,bot,window)).rejects.toThrow("Availability could not be confirmed");
 await vi.advanceTimersByTimeAsync(30001);await rejected;
 expect(fetch).toHaveBeenCalledOnce();expect((fetch.mock.calls[0] as unknown as [string,RequestInit])[1].signal?.aborted).toBe(true);
 expect(vi.getTimerCount()).toBe(0);
});

it("shares one deadline between identity acquisition and response reading",async()=>{
 const api=await module();let token!:(value:string)=>void;
 const session={mode:"clerk_jwt" as const,getToken:()=>new Promise<string>(resolve=>token=resolve)};
 const fetch=vi.fn(()=>new Promise<Response>(()=>{}));vi.stubGlobal("fetch",fetch);
 const rejected=expect(api.readAvailability(workspace,session,bot,window)).rejects.toThrow("Availability could not be confirmed");
 await vi.advanceTimersByTimeAsync(25000);token("invented.token.value");await vi.advanceTimersByTimeAsync(1);expect(fetch).toHaveBeenCalledOnce();
 await vi.advanceTimersByTimeAsync(5000);await rejected;expect(vi.getTimerCount()).toBe(0);
});

it("external cancellation settles an ignored body read without waiting for stream cleanup",async()=>{
 const api=await module(),controller=new AbortController(),cancel=vi.fn(()=>new Promise<void>(()=>{}));
 const read=vi.fn(()=>new Promise<ReadableStreamReadResult<Uint8Array>>(()=>{}));
 vi.stubGlobal("fetch",vi.fn(async()=>({status:200,headers:new Headers({"Content-Type":"application/json","Cache-Control":"no-store"}),
  body:{getReader:()=>({read,cancel,releaseLock:vi.fn()})}})));
 const rejected=expect(api.readAvailability(workspace,identity,bot,window,controller.signal)).rejects.toThrow("Availability could not be confirmed");
 await vi.advanceTimersByTimeAsync(1);expect(read).toHaveBeenCalledOnce();controller.abort();await rejected;
 expect(cancel).toHaveBeenCalled();expect(vi.getTimerCount()).toBe(0);
});

it.each([401,403])("preserves access-denied status %s without reading its private body or awaiting cancellation",async status=>{
 const api=await module(),cancel=vi.fn(()=>new Promise<void>(()=>{})),getReader=vi.fn(()=>{throw Error("PRIVATE");});
 vi.stubGlobal("fetch",vi.fn(async()=>({status,headers:new Headers(),body:{cancel,getReader}})));
 await expect(api.readAvailability(workspace,identity,bot,window)).rejects.toMatchObject({status});
 expect(cancel).toHaveBeenCalled();expect(getReader).not.toHaveBeenCalled();expect(vi.getTimerCount()).toBe(0);
});

it("rejects a bad response immediately even when its cancellation never settles",async()=>{
 const api=await module(),cancel=vi.fn(()=>new Promise<void>(()=>{}));
 vi.stubGlobal("fetch",vi.fn(async()=>({status:503,headers:new Headers(),body:{cancel}})));
 await expect(api.readAvailability(workspace,identity,bot,window)).rejects.toThrow("Availability could not be confirmed");
 expect(cancel).toHaveBeenCalled();expect(vi.getTimerCount()).toBe(0);
});

it("discards a late private response after the request deadline",async()=>{
 const api=await module();let respond!:(response:Response)=>void;
 const cancel=vi.fn(async()=>{}),getReader=vi.fn(()=>{throw Error("PRIVATE");});
 const fetch=vi.fn(()=>new Promise<Response>(resolve=>respond=resolve));vi.stubGlobal("fetch",fetch);
 const rejected=expect(api.readAvailability(workspace,identity,bot,window)).rejects.toThrow("Availability could not be confirmed");
 await vi.advanceTimersByTimeAsync(30001);await rejected;
 respond({body:{cancel,getReader}} as unknown as Response);await vi.advanceTimersByTimeAsync(1);
 expect(cancel).toHaveBeenCalledOnce();expect(getReader).not.toHaveBeenCalled();expect(fetch).toHaveBeenCalledOnce();
});
