import {afterEach,beforeEach,expect,it,vi} from "vitest";
import {parseRoutine,parseWorkBrief,validSchedule} from "./routine-api";
import {brief,routine,routineId,schedule} from "./routine-test-fixture";
const identity={mode:"clerk_jwt" as const,getToken:vi.fn(async()=>"invented.token.value")};
const response=(value:unknown)=>Response.json(value,{headers:{"Cache-Control":"no-store"}});
beforeEach(()=>{vi.clearAllMocks();vi.useFakeTimers();});
afterEach(()=>{vi.useRealTimers();vi.unstubAllEnvs();vi.unstubAllGlobals();});
async function api(){for(const flag of ["VITE_WORKSPACE_ENABLED","VITE_WORKSPACE_AUTHENTICATED_ENABLED","VITE_WORKSPACE_ROUTINES_ENABLED"])vi.stubEnv(flag,"true");
  vi.stubEnv("VITE_COSMAS_ENV","synth_os");vi.stubEnv("VITE_API_BASE","http://127.0.0.1:8000");vi.resetModules();return(await import("./routine-api")).routineApi;}
it("accepts only bounded schedules and source-backed reports",()=>{
  expect(parseRoutine(routine(),"chief").revision).toBe(1);expect(parseWorkBrief(brief(),routineId(1)).counts.overdue).toBe(1);
  expect(validSchedule(schedule())).toBe(true);
  for(const change of [{weekdays:[1,1]},{weekdays:[true]},{at:"18:30"},{timezone:"Invalid/Zone"},{max_runs_per_seven_days:8},{quiet_end:null},{send_messages:true}])expect(validSchedule({...schedule(),...change})).toBe(false);
});
it.each(["bot","scope","extra","revision","schedule","run"])("withholds invalid configuration %s",fault=>{
  const value=routine();if(fault==="bot")value.bot="scribe";if(fault==="scope")value.agent_id="bad";if(fault==="extra")Object.assign(value,{secret:"PRIVATE"});
  if(fault==="revision")value.revision=-1;if(fault==="schedule")value.configuration!.weekdays=[8];if(fault==="run")value.runs[0].id="bad";
  expect(()=>parseRoutine(value,"chief")).toThrow();
});
it.each(["id","count","duplicate","model","complete","body","extra"])("withholds invalid brief %s",fault=>{
  const value=brief();if(fault==="id")value.id=routineId(9);if(fault==="count")value.counts.overdue=2;
  if(fault==="duplicate"){value.matching_items=2;value.items.push(value.items[0]);}if(fault==="model")Object.assign(value,{model_used:true});
  if(fault==="complete")value.items[0].human_completion=true;if(fault==="body")value.items[0].body="x".repeat(181);if(fault==="extra")Object.assign(value,{private_notebook:"PRIVATE"});
  expect(()=>parseWorkBrief(value,routineId(1))).toThrow();
});
it("uses exact signed paths, omits credentials and does not automatically retry a save",async()=>{
  const client=await api(),fetch=vi.fn(async(url:string,options:RequestInit)=>url.includes("/runs/")?response(brief()):
    response(options.method==="POST"?{...routine(),revision:2}:routine()));vi.stubGlobal("fetch",fetch);
  const body={expected_revision:1,team_revision:1,idempotency_key:routineId(8),configuration:schedule()};
  await client.read(identity,"chief");await client.run(identity,"chief",routineId(1));await client.save(identity,"chief",body);
  expect(fetch.mock.calls.map(([url])=>url)).toEqual(["http://127.0.0.1:8000/provider-team/routines/chief","http://127.0.0.1:8000/provider-team/routines/chief/runs/"+routineId(1),"http://127.0.0.1:8000/provider-team/routines/chief"]);
  for(const [,options]of fetch.mock.calls){expect(options).toMatchObject({credentials:"omit",redirect:"error",cache:"no-store",referrerPolicy:"no-referrer"});expect((options.headers as Headers).get("Authorization")).toBe("Bearer invented.token.value");}
  expect(JSON.parse(fetch.mock.calls[2][1].body as string)).toEqual(body);expect(identity.getToken).toHaveBeenCalledTimes(3);
});
it.each([401,403,404,409,422,503])("preserves safe status %s without exposing response text",async status=>{
  const client=await api(),fetch=vi.fn(async()=>new Response("PRIVATE",{status}));vi.stubGlobal("fetch",fetch);
  await expect(client.read(identity,"chief")).rejects.toMatchObject({status});expect(fetch).toHaveBeenCalledOnce();
});
it.each(["cache","size","changed_save"])("rejects %s after a possible save",async fault=>{
  const client=await api();vi.stubGlobal("fetch",vi.fn(async()=>fault==="size"?new Response(" ".repeat(32769),{headers:{"Content-Type":"application/json","Cache-Control":"no-store"}}):
    Response.json({...routine(),revision:2,configuration:{...schedule(),at:fault==="changed_save"?"09:00":"08:00"}},{headers:fault==="cache"?{}:{"Cache-Control":"no-store"}})));
  await expect(client.save(identity,"chief",{expected_revision:1,team_revision:1,idempotency_key:routineId(8),configuration:schedule()})).rejects.toMatchObject({status:503});
});
it("bounds stalled credentials before network I/O",async()=>{
  const client=await api(),fetch=vi.fn();vi.stubGlobal("fetch",fetch);
  const pending=client.read({mode:"clerk_jwt",getToken:()=>new Promise(()=>{})},"chief");const rejected=expect(pending).rejects.toMatchObject({status:503});
  await vi.advanceTimersByTimeAsync(30001);await rejected;expect(fetch).not.toHaveBeenCalled();
});
it("cancels a stalled body without waiting on broken transport cleanup",async()=>{
  const client=await api(),controller=new AbortController(),cancel=vi.fn(()=>new Promise<void>(()=>{}));
  vi.stubGlobal("fetch",vi.fn(async()=>new Response(new ReadableStream({pull(){},cancel}),{headers:{"Content-Type":"application/json","Cache-Control":"no-store"}})));
  const pending=client.read(identity,"chief",controller.signal),rejected=expect(pending).rejects.toMatchObject({status:503});
  await vi.advanceTimersByTimeAsync(1);controller.abort();await rejected;expect(cancel).toHaveBeenCalledOnce();
});
it("rejects a forged selector or disabled build before identity acquisition",async()=>{
  const client=await api();await expect(client.read(identity,"../private")).rejects.toThrow();expect(identity.getToken).not.toHaveBeenCalled();
  vi.stubEnv("VITE_WORKSPACE_ROUTINES_ENABLED","false");vi.resetModules();const disabled=(await import("./routine-api")).routineApi;
  await expect(disabled.read(identity,"chief")).rejects.toThrow();expect(identity.getToken).not.toHaveBeenCalled();
});

it("accepts a restricted saved routine without removing its schedule or history",async()=>{
  const client=await api(),value={...routine(),status:"restricted"};vi.stubGlobal("fetch",vi.fn(async()=>Response.json(value,{headers:{"Cache-Control":"no-store"}})));
  await expect(client.read(identity,"chief")).resolves.toEqual(value);
});
