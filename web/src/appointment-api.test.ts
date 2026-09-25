import {afterEach, beforeEach, expect, it, vi} from "vitest";
import {validateAppointmentItem} from "./appointment-api";
import {catalog, id, item, linked, saved, workspaceId} from "./appointment-test-fixture";
const identity = {mode:"clerk_jwt" as const, getToken:vi.fn(async()=>"invented.token.value")};
const bot = {address:"follow_up", team_revision:1};
beforeEach(()=>{vi.useFakeTimers();vi.setSystemTime(new Date("2026-09-21T15:00:00Z"));vi.clearAllMocks();});
afterEach(()=>{vi.useRealTimers();vi.unstubAllEnvs();vi.unstubAllGlobals();});
async function api() {
  for (const flag of ["VITE_WORKSPACE_ENABLED","VITE_WORKSPACE_AUTHENTICATED_ENABLED","VITE_WORKSPACE_SCHEDULING_ENABLED","VITE_WORKSPACE_APPOINTMENTS_ENABLED"]) vi.stubEnv(flag,"true");
  vi.stubEnv("VITE_COSMAS_ENV","synth_os");vi.stubEnv("VITE_API_BASE","http://127.0.0.1:8000");vi.resetModules();
  return (await import("./appointment-api")).appointmentApi;
}
const response = (body:unknown) => Response.json(body,{headers:{"Cache-Control":"no-store"}});
it.each(["workspace","ticket","owner","hash","state","saved","calendar","scope","slot","extra"])("rejects substituted %s", fault=>{
  const value = item();
  if(fault==="workspace") value.workspace_id=id(99);
  if(fault==="ticket") value.ticket_id=id(99);
  if(fault==="owner") value.owner_id=id(99);
  if(fault==="hash") value.payload_hash="bad";
  if(fault==="state") Object.assign(value,{state:"closed"});
  if(fault==="saved") Object.assign(value,{appointment_saved:true});
  if(fault==="calendar") Object.assign(value,{calendar_state:"synced"});
  if(fault==="scope") value.intent.selection.patient_id="bad";
  if(fault==="slot") value.intent.slot!.ends_at=value.intent.slot!.starts_at;
  if(fault==="extra") Object.assign(value,{private_note:"PRIVATE"});
  expect(()=>validateAppointmentItem(value,workspaceId,id(10))).toThrow();
});
it("uses exact authenticated catalog/current/prepare/review paths and bodies",async()=>{
  const client=await api(), prepared=item();
  const fetch=vi.fn(async(url:string,options:RequestInit)=>{
    if(url.endsWith("/current")) return response({workspace_id:workspaceId,label:"Invented schedule",appointment:linked(),checked_at:new Date().toISOString()});
    if(options.method==="GET" && url.endsWith("/appointments")) return response(catalog([prepared]));
    return response(prepared);
  });vi.stubGlobal("fetch",fetch);
  expect((await client.catalog(workspaceId,identity)).items).toHaveLength(1);
  expect((await client.current(workspaceId,identity,bot)).appointment?.id).toBe(id(20));
  const body={bot,action:"book" as const,slot:prepared.intent.slot,share:true as const,idempotency_key:id(15)};
  expect((await client.prepare(workspaceId,identity,body)).ticket_id).toBe(prepared.ticket_id);
  expect((await client.read(workspaceId,identity,prepared.ticket_id)).ticket_id).toBe(prepared.ticket_id);
  for(const [url,options] of fetch.mock.calls) {
    expect(url).toMatch(new RegExp("/workspaces/"+workspaceId+"/appointments"));
    expect(options).toMatchObject({credentials:"omit",redirect:"error",cache:"no-store",referrerPolicy:"no-referrer"});
    expect((options.headers as Headers).get("Authorization")).toBe("Bearer invented.token.value");
  }
  expect(JSON.parse(fetch.mock.calls[2][1].body as string)).toEqual(body);
  expect(identity.getToken).toHaveBeenCalledTimes(4);
});
it.each([401,403,404,409,422,503])("preserves safe status %s without exposing server text or retry",async status=>{
  const client=await api();const fetch=vi.fn(async()=>new Response("PRIVATE",{status}));vi.stubGlobal("fetch",fetch);
  await expect(client.read(workspaceId,identity,id(10))).rejects.toMatchObject({status});
  expect(fetch).toHaveBeenCalledTimes(1);
});
it.each(["cache","oversize","invalid","wrong_slot"])("withholds an invalid %s response after a possible save",async fault=>{
  const client=await api(), prepared=item(), body={bot,action:"book" as const,slot:{...prepared.intent.slot!},share:true as const,idempotency_key:id(15)};
  if(fault==="wrong_slot") prepared.intent.slot!.ends_at=new Date(Date.now()+175600000).toISOString();
  vi.stubGlobal("fetch",vi.fn(async()=>fault==="oversize"?new Response(" ".repeat(32769),{headers:{"Content-Type":"application/json","Cache-Control":"no-store"}}):
    fault==="invalid"?new Response("PRIVATE",{headers:{"Content-Type":"application/json","Cache-Control":"no-store"}}):
    Response.json(prepared,{headers:fault==="cache"?{}:{"Cache-Control":"no-store"}})));
  await expect(client.prepare(workspaceId,identity,body)).rejects.toMatchObject({status:503});
});
it("bounds stalled credentials and issues no request after timeout",async()=>{
  const client=await api(),fetch=vi.fn();vi.stubGlobal("fetch",fetch);
  const pending=client.catalog(workspaceId,{mode:"clerk_jwt",getToken:()=>new Promise(()=>{})});
  const rejected=expect(pending).rejects.toMatchObject({status:503});
  await vi.advanceTimersByTimeAsync(30001);await rejected;expect(fetch).not.toHaveBeenCalled();
});
it("rejects invalid path selectors and an already cancelled read before identity acquisition",async()=>{
  const client=await api(),fetch=vi.fn();vi.stubGlobal("fetch",fetch);
  const controller=new AbortController();controller.abort();
  await expect(client.catalog(workspaceId,identity,"../private")).rejects.toThrow();
  await expect(client.catalog(workspaceId,identity,undefined,controller.signal)).rejects.toThrow();
  expect(identity.getToken).not.toHaveBeenCalled();expect(fetch).not.toHaveBeenCalled();
});
it("rejects history without an exact appointment window",async()=>{
  const client=await api(),value=catalog([item()]);
  value.items[0].appointment_window.ends_at=value.items[0].appointment_window.starts_at;
  vi.stubGlobal("fetch",vi.fn(async()=>response(value)));
  await expect(client.catalog(workspaceId,identity)).rejects.toMatchObject({status:503});
});
it("releases an aborted body even when its cancellation never settles",async()=>{
  const client=await api(),controller=new AbortController();
  const cancel=vi.fn(()=>new Promise<void>(()=>{}));
  vi.stubGlobal("fetch",vi.fn(async()=>new Response(new ReadableStream({pull(){},cancel}),{
    headers:{"Content-Type":"application/json","Cache-Control":"no-store"}})));
  const pending=client.catalog(workspaceId,identity,undefined,controller.signal);
  const rejected=expect(pending).rejects.toMatchObject({status:503});
  await vi.advanceTimersByTimeAsync(1);controller.abort();await rejected;
  expect(cancel).toHaveBeenCalledTimes(1);
});
it.each(["book", "reschedule", "cancel"] as const)("accepts a saved %s only with its exact effect receipt",action=>{
  expect(validateAppointmentItem(saved(action),workspaceId).appointment_saved).toBe(true);
});
it.each(["missing", "scope", "version", "time", "status", "calendar", "operation", "started"])("rejects saved receipt %s substitution",fault=>{
  const value=saved("reschedule");
  if(fault==="scope") value.result!.appointment.patient_id=id(99);
  if(fault==="version") value.result!.appointment.version++;
  if(fault==="time") value.result!.appointment.starts_at=new Date(Date.now()).toISOString();
  if(fault==="status") value.result!.appointment.status="fulfilled";
  if(fault==="calendar") value.result!.calendar_state="synced";
  if(fault==="operation") value.result!.operation_id=id(99);
  if(fault==="started") value.dispatch_started=false;
  if(fault==="missing") value.result=null;
  expect(()=>validateAppointmentItem(value,workspaceId)).toThrow();
});
it.each(["extra","consent","slot","key","bot"])("blocks malformed recovered proposal %s before credentials or network",async fault=>{
  const client=await api(),fetch=vi.fn();vi.stubGlobal("fetch",fetch);
  const body={bot:{...bot},action:"book" as const,slot:item().intent.slot,share:true as const,idempotency_key:id(15)};
  if(fault==="extra")Object.assign(body,{expected_revision:1});
  if(fault==="consent")Object.assign(body,{share:false});
  if(fault==="slot")body.slot!.ends_at=body.slot!.starts_at;
  if(fault==="key")body.idempotency_key="../unbound";
  if(fault==="bot")body.bot.team_revision=0;
  await expect(client.prepare(workspaceId,identity,body)).rejects.toThrow();
  expect(identity.getToken).not.toHaveBeenCalled();expect(fetch).not.toHaveBeenCalled();
});
it("rejects a notebook-shaped appointment decision without issuing a request",async()=>{
  const client=await api(),fetch=vi.fn();vi.stubGlobal("fetch",fetch);
  const body={revision_id:id(11),payload_hash:"a".repeat(64),choice:"approve" as const,idempotency_key:id(15)};
  await expect(client.decide(workspaceId,identity,id(10),body)).rejects.toThrow();
  expect(identity.getToken).not.toHaveBeenCalled();expect(fetch).not.toHaveBeenCalled();
});
it.each(["submit","reconcile","retry"] as const)("sends exactly one bound %s command",async mode=>{
 const client=await api(),result=saved(),fetch=vi.fn(async()=>response(result));vi.stubGlobal("fetch",fetch);
 const body={operation_id:result.operation_id!,revision_id:result.revision_id,payload_hash:result.payload_hash,mode};
 expect(await client.execute(workspaceId,identity,result.ticket_id,body)).toEqual(result);
 expect(fetch).toHaveBeenCalledOnce();const [url,options]=fetch.mock.calls[0] as unknown as [string,RequestInit];
 expect(url).toBe("http://127.0.0.1:8000/workspaces/"+workspaceId+"/appointments/"+result.ticket_id+"/execute");
 expect(options.method).toBe("POST");expect(options.body).toBe(JSON.stringify(body));
 expect(new TextEncoder().encode(options.body as string).length).toBeLessThanOrEqual(2048);
 expect(options).toMatchObject({credentials:"omit",redirect:"error",cache:"no-store",referrerPolicy:"no-referrer"});
});
it.each(["workspace","ticket","operation","revision","hash"])("withholds an execute receipt with a different %s",async fault=>{
 const client=await api(),result=saved(),body={operation_id:result.operation_id!,revision_id:result.revision_id,payload_hash:result.payload_hash,mode:"submit" as const};
 if(fault==="workspace")result.workspace_id=id(99);
 if(fault==="ticket")result.ticket_id=id(99);
 if(fault==="operation"){result.operation_id=id(99);result.result!.operation_id=id(99);}
 if(fault==="revision")result.revision_id=id(99);
 if(fault==="hash")result.payload_hash="c".repeat(64);
 const fetch=vi.fn(async()=>response(result));vi.stubGlobal("fetch",fetch);
 await expect(client.execute(workspaceId,identity,id(10),body)).rejects.toMatchObject({status:503});expect(fetch).toHaveBeenCalledOnce();
});
it.each(["extra","mode","operation","hash"])("blocks malformed execution %s before authentication",async fault=>{
 const client=await api(),fetch=vi.fn();vi.stubGlobal("fetch",fetch);
 const body={operation_id:id(12),revision_id:id(11),payload_hash:"a".repeat(64),mode:"submit" as const};
 if(fault==="extra")Object.assign(body,{idempotency_key:id(15)});
 if(fault==="mode")Object.assign(body,{mode:["submit"]});
 if(fault==="operation")body.operation_id="";
 if(fault==="hash")body.payload_hash="A".repeat(64);
 await expect(client.execute(workspaceId,identity,id(10),body)).rejects.toThrow();
 expect(identity.getToken).not.toHaveBeenCalled();expect(fetch).not.toHaveBeenCalled();
});
it.each(["state","action","operation_status","calendar_state","appointment_status"])("refuses a coerced %s enum",fault=>{
 const value=saved();
 if(fault==="state")Object.assign(value,{state:["sent"]});
 if(fault==="action")Object.assign(value.intent,{action:["book"]});
 if(fault==="operation_status")Object.assign(value,{operation_status:["succeeded"]});
 if(fault==="calendar_state")Object.assign(value,{calendar_state:["pending"]});
 if(fault==="appointment_status")Object.assign(value.result!.appointment,{status:["booked"]});
 expect(()=>validateAppointmentItem(value,workspaceId)).toThrow();
});
it.each(["fetch","reader"])("bounds an execution even when %s ignores abort",async stage=>{
 const client=await api();let reader:ReadableStreamDefaultReader<Uint8Array>|undefined;
 if(stage==="fetch")vi.stubGlobal("fetch",vi.fn(()=>new Promise(()=>{})));
 else {
  reader={read:vi.fn(()=>new Promise(()=>{})),cancel:vi.fn(()=>new Promise(()=>{})),releaseLock:vi.fn()} as unknown as ReadableStreamDefaultReader<Uint8Array>;
  vi.stubGlobal("fetch",vi.fn(async()=>({status:200,headers:new Headers({"Content-Type":"application/json","Cache-Control":"no-store"}),body:{getReader:()=>reader}})));
 }
 const request=client.execute(workspaceId,identity,id(10),{operation_id:id(12),revision_id:id(11),payload_hash:"a".repeat(64),mode:"submit"});
 const rejected=expect(request).rejects.toMatchObject({status:503});await vi.advanceTimersByTimeAsync(30001);await rejected;
 expect(fetch).toHaveBeenCalledOnce();if(reader)expect(reader.releaseLock).toHaveBeenCalledOnce();
});
