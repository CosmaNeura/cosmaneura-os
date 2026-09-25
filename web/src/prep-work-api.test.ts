import {afterEach,beforeEach,expect,it,vi} from "vitest";
import {prepWorkspace,prepTicket,prepRevision,prepBot,prepItem,prepReceipt} from "./prep-work-test-fixture";
import type {PrepWorkRequest} from "./prep-work-request";
const identity={mode:"clerk_jwt" as const,getToken:vi.fn(async()=>"invented.token.value")};
const create=():PrepWorkRequest=>({kind:"create",body:{bot:{...prepBot},expected_entry_revision:7,snapshot_sha256:prepReceipt.snapshot_sha256,
  body:prepItem().body,due_date:prepItem().due_date,expected_outcome:prepItem().expected_outcome,share_context:true,idempotency_key:"00000000-0000-4000-8000-000000000009"}});
beforeEach(()=>{vi.clearAllMocks();vi.useFakeTimers();});
afterEach(()=>{vi.useRealTimers();vi.unstubAllEnvs();vi.unstubAllGlobals();});
async function api(enabled=true){for(const flag of ["VITE_WORKSPACE_ENABLED","VITE_WORKSPACE_AUTHENTICATED_ENABLED","VITE_WORKSPACE_PREP_ENABLED"])vi.stubEnv(flag,"true");
  vi.stubEnv("VITE_WORKSPACE_PREP_WORK_ENABLED",String(enabled));vi.stubEnv("VITE_COSMAS_ENV","synth_os");vi.stubEnv("VITE_API_BASE","http://127.0.0.1:8000");vi.resetModules();
  return(await import("./prep-work-api")).prepWorkApi;}
const response=(value:unknown)=>Response.json(value,{headers:{"Cache-Control":"no-store"}});
it("uses exact private workspace routes, obtains fresh credentials and validates the shared result",async()=>{
  const client=await api(),fetch=vi.fn(async(url:string,options:RequestInit)=>response(options.method==="GET"&&url.endsWith("/prep-work")?
    {entry_revision:7,items:[prepItem()]}:{entry_revision:8,item:prepItem()}));vi.stubGlobal("fetch",fetch);
  expect((await client.catalog(prepWorkspace,identity)).items).toHaveLength(1);await client.read(prepWorkspace,identity,prepTicket);await client.save(prepWorkspace,identity,create());
  for(const [url,options] of fetch.mock.calls){expect(url).toContain(`/workspaces/${prepWorkspace}/prep-work`);expect(options).toMatchObject({credentials:"omit",redirect:"error",cache:"no-store",referrerPolicy:"no-referrer"});
    expect((options.headers as Headers).get("Authorization")).toBe("Bearer invented.token.value");}
  expect(JSON.parse(fetch.mock.calls[2][1].body as string)).toEqual(create().body);expect(identity.getToken).toHaveBeenCalledTimes(3);
});
it("admits the bounded encoded form of an otherwise valid shared brief",async()=>{
  const client=await api(),command=create(),value=prepItem();if(command.kind!=="create")throw new Error("fixture");
  command.body.body="x"+"\u0001".repeat(3999);value.body=command.body.body;
  const fetch=vi.fn(async(_url:string,options:RequestInit)=>{
    const size=new TextEncoder().encode(options.body as string).length;expect(size).toBeGreaterThan(16384);expect(size).toBeLessThan(32768);
    return response({entry_revision:8,item:value});
  });vi.stubGlobal("fetch",fetch);await client.save(prepWorkspace,identity,command);expect(fetch).toHaveBeenCalledOnce();
});
it.each(["private","kind","ticket","hash","source","state","ready","completion","duplicate","person"])("withholds a substituted %s response",async fault=>{
  const client=await api(),value=prepItem();
  if(fault==="private")Object.assign(value,{source_ref:"PRIVATE"});if(fault==="kind")Object.assign(value,{work_kind:"follow_up"});
  if(fault==="ticket")value.ticket_id=prepRevision;if(fault==="hash")value.payload_hash="bad";if(fault==="source")value.proposed_snapshot_sha256="bad";
  if(fault==="state")value.state="sent";if(fault==="ready")value.ready_for_review=true;if(fault==="completion")value.state="closed";
  if(fault==="duplicate")value.receipts=[...prepItem("approved",true).receipts,...prepItem("approved",true).receipts];
  if(fault==="person")Object.assign(value.originator,{credential:"PRIVATE"});
  vi.stubGlobal("fetch",vi.fn(async()=>response({entry_revision:7,item:value})));await expect(client.read(prepWorkspace,identity,prepTicket)).rejects.toMatchObject({status:503});
});
it.each(["share","extra","hash","version","date","outcome","bot"])("rejects recovered request %s before credentials or transport",async fault=>{
  const client=await api(),command=create(),fetch=vi.fn();vi.stubGlobal("fetch",fetch);
  if(command.kind!=="create")throw new Error("fixture");
  if(fault==="share")Object.assign(command.body,{share_context:false});if(fault==="extra")Object.assign(command.body,{source_ref:"PRIVATE"});
  if(fault==="hash")command.body.snapshot_sha256="bad";if(fault==="version")command.body.expected_entry_revision=0;
  if(fault==="date")command.body.due_date="2026-02-30";if(fault==="outcome")command.body.expected_outcome="a".repeat(501);
  if(fault==="bot")command.body.bot.team_revision=0;
  await expect(client.save(prepWorkspace,identity,command)).rejects.toThrow();expect(identity.getToken).not.toHaveBeenCalled();expect(fetch).not.toHaveBeenCalled();
});
it.each([401,403,404,409,422,503])("preserves safe status %s without showing private server text or retrying",async status=>{
  const client=await api(),fetch=vi.fn(async()=>new Response("PRIVATE_SENTINEL",{status}));vi.stubGlobal("fetch",fetch);
  await expect(client.catalog(prepWorkspace,identity)).rejects.toMatchObject({status});expect(fetch).toHaveBeenCalledOnce();
});
it.each(["cache","oversize","different_body","duplicate_catalog"])("rejects an invalid %s result",async fault=>{
  const client=await api(),value=prepItem();if(fault==="different_body")value.body="Substituted";
  vi.stubGlobal("fetch",vi.fn(async()=>fault==="oversize"?new Response(" ".repeat(1048577),{headers:{"Content-Type":"application/json","Cache-Control":"no-store"}}):
    Response.json(fault==="duplicate_catalog"?{entry_revision:7,items:[value,value]}:{entry_revision:8,item:value},{headers:fault==="cache"?{}:{"Cache-Control":"no-store"}})));
  await expect(fault==="duplicate_catalog"?client.catalog(prepWorkspace,identity):client.save(prepWorkspace,identity,create())).rejects.toMatchObject({status:503});
});
it("requires the opt-in gate and valid path selectors before acquiring credentials",async()=>{
  const disabled=await api(false),fetch=vi.fn();vi.stubGlobal("fetch",fetch);await expect(disabled.catalog(prepWorkspace,identity)).rejects.toThrow();
  const client=await api();await expect(client.read(prepWorkspace,identity,"../outside")).rejects.toThrow();await expect(client.catalog("../outside",identity)).rejects.toThrow();
  expect(identity.getToken).not.toHaveBeenCalled();expect(fetch).not.toHaveBeenCalled();
});
it("bounds stalled authentication and cancels an unresponsive body",async()=>{
  const client=await api(),fetch=vi.fn();vi.stubGlobal("fetch",fetch);
  const stalled=client.catalog(prepWorkspace,{mode:"clerk_jwt",getToken:()=>new Promise(()=>{})});const rejected=expect(stalled).rejects.toMatchObject({status:503});
  await vi.advanceTimersByTimeAsync(30001);await rejected;expect(fetch).not.toHaveBeenCalled();
  const cancel=vi.fn(()=>new Promise<void>(()=>{}));fetch.mockResolvedValue(new Response(new ReadableStream({pull(){},cancel}),{headers:{"Content-Type":"application/json","Cache-Control":"no-store"}}));
  const controller=new AbortController(),reading=client.catalog(prepWorkspace,identity,controller.signal),aborted=expect(reading).rejects.toMatchObject({status:503});
  await vi.advanceTimersByTimeAsync(1);controller.abort();await aborted;expect(cancel).toHaveBeenCalledOnce();
});
it.each(["approve","reject","verify"] as const)("does not confirm %s from an unchanged or unproved result",async kind=>{
  const client=await api(),base={expected_version:1,revision_id:prepRevision,payload_hash:prepItem().payload_hash};
  const command:PrepWorkRequest=kind==="verify"?{kind,ticket:prepTicket,body:{...base,bot:prepBot,current_snapshot_sha256:prepReceipt.snapshot_sha256,reviewed_summary:true,idempotency_key:prepRevision}}:
    {kind:"decide",ticket:prepTicket,body:kind==="approve"?{...base,choice:kind,bot:prepBot,expected_snapshot_sha256:prepReceipt.snapshot_sha256}:{...base,choice:kind}};
  vi.stubGlobal("fetch",vi.fn(async()=>response({entry_revision:8,item:prepItem()})));
  await expect(client.save(prepWorkspace,identity,command)).rejects.toMatchObject({status:503});
});
it("accepts approval replay after later provider verification using the retained publication receipt",async()=>{
  const client=await api(),value=prepItem("closed"),actor=value.originator;
  value.receipts=[{id:"00000000-0000-4000-8000-000000000006",kind:"internal_publication",content:"Shared internally",actor,created_at:"2026-09-21T12:00:00Z"},
    {id:"00000000-0000-4000-8000-000000000007",kind:"provider_verification",content:"Reviewed saved summary",actor,created_at:"2026-09-21T13:00:00Z"}];
  vi.stubGlobal("fetch",vi.fn(async()=>response({entry_revision:8,item:value})));
  const command:PrepWorkRequest={kind:"decide",ticket:prepTicket,body:{expected_version:1,revision_id:prepRevision,payload_hash:value.payload_hash,choice:"approve",bot:prepBot,expected_snapshot_sha256:prepReceipt.snapshot_sha256}};
  expect((await client.save(prepWorkspace,identity,command)).item.state).toBe("closed");
});
