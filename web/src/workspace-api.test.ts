import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { teamFixture } from "./team-setup-test-fixture";
import { workspaceApi, WorkspaceApiError, type AuthenticatedWorkspaceIdentity } from "./workspace-api";

const appointment = "00000000-0000-4000-8000-000000000001";
const workspace = "00000000-0000-4000-8000-000000000002";
const json = (value: unknown) => new Response(JSON.stringify(value), {
  headers: { "Content-Type": "application/json", "Cache-Control":"no-store" },
});

describe("signed workspace transport", () => {
  beforeEach(() => vi.stubEnv("VITE_API_BASE", "http://127.0.0.1:8018"));
  afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); vi.useRealTimers(); });
  it('uses operation-neutral copy for unavailable reads and describes a connection pause without inventing a save',()=>{
    const pause=new WorkspaceApiError(503,'workspace_protocol_required');
    expect(pause.message).toContain('workspace connection is paused');
    expect(pause.message).not.toContain('Retry the same save');
    expect(new WorkspaceApiError(503).message).toContain('workspace request');
    expect(new WorkspaceApiError(503).message).not.toContain('same save');
    expect(new WorkspaceApiError(426,'workspace_protocol_required').message).toContain('Update Cosmas');
  });

  it('creates and resolves an exact private draft through the signed bounded contract',async()=>{
    const identity:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>'invented-token'};
    const body={title:'Private note',idempotency_key:'private-create-key'};
    const draft={id:workspace,appointment_id:null,label:body.title,revision:1,entries:[],work_candidates:[],
      private_draft:{title:body.title,state:'unlinked',link_receipt_id:null,linked_at:null}};
    const fetchMock=vi.fn<typeof fetch>((url)=>Promise.resolve(json(String(url).endsWith('/provider-team')?teamFixture():
      String(url).endsWith('/resolve')?{contract_version:1,outcome:'saved',workspace:draft}:draft)));
    vi.stubGlobal('fetch',fetchMock);
    expect((await workspaceApi.createPrivateDraft(identity,body)).workspace).toEqual(draft);
    expect((await workspaceApi.resolvePrivateDraft(identity,body)).workspace).toEqual(draft);
    const create=fetchMock.mock.calls.find(([url])=>String(url).endsWith('/private-drafts'))!,
      resolve=fetchMock.mock.calls.find(([url])=>String(url).endsWith('/private-drafts/resolve'))!;
    expect(create[0]).toBe('http://127.0.0.1:8018/workspaces/private-drafts');
    expect(resolve[0]).toBe('http://127.0.0.1:8018/workspaces/private-drafts/resolve');
    expect(create[1]?.body).toBe(resolve[1]?.body);
    expect(new Headers(create[1]?.headers).get('X-Cosmas-Private-Draft')).toBe('1');
    expect(new Headers(create[1]?.headers).get('Authorization')).toBe('Bearer invented-token');
  });

  it('starts the exact private workspace read while its fresh team response is still pending',async()=>{
    let finishTeam!:(value:Response)=>void;
    const teamResponse=new Promise<Response>(resolve=>{finishTeam=resolve;});
    const draft={id:workspace,appointment_id:null,label:'Private note',revision:1,entries:[],work_candidates:[],
      model_contract_version:1,model_observed_at:'2026-10-21T18:00:00Z',
      private_draft:{title:'Private note',state:'unlinked',link_receipt_id:null,linked_at:null}};
    const fetchMock=vi.fn<typeof fetch>((url)=>String(url).endsWith('/provider-team')?teamResponse:Promise.resolve(json(draft)));
    vi.stubGlobal('fetch',fetchMock);
    let settled=false;
    const result=workspaceApi.openPrivateDraft({mode:'clerk_jwt',getToken:async()=>'invented-token'},workspace).finally(()=>{settled=true;});
    try{
      await vi.waitFor(()=>expect(fetchMock).toHaveBeenCalledTimes(2),{timeout:500});
      expect(settled).toBe(false);
      const read=fetchMock.mock.calls.find(([url])=>String(url).endsWith(`/workspaces/${workspace}`))!;
      expect(read[1]?.method).toBe('GET');
      expect(new Headers(read[1]?.headers).get('X-Cosmas-Model-Contract')).toBe('1');
      expect(new Headers(read[1]?.headers).get('Authorization')).toBe('Bearer invented-token');
    }finally{finishTeam(json(teamFixture()));await result.catch(()=>undefined);}
    await expect(result).resolves.toMatchObject({workspace:draft,team:teamFixture()});
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it.each(['team','workspace'])('withholds the note and cancels its sibling read when the %s read fails',async failed=>{
    const fetchMock=vi.fn<typeof fetch>((url)=>{
      const kind=String(url).endsWith('/provider-team')?'team':'workspace';
      return kind===failed?Promise.resolve(new Response(null,{status:403})):new Promise(()=>{});
    });
    vi.stubGlobal('fetch',fetchMock);
    await expect(workspaceApi.openPrivateDraft({mode:'clerk_jwt',getToken:async()=>'invented-token'},workspace)).rejects.toMatchObject({status:403});
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls.every(([,request])=>request?.signal?.aborted)).toBe(true);
    expect(fetchMock.mock.calls.every(([,request])=>request?.method==='GET')).toBe(true);
  });

  it('withholds concurrent private-note reads when the native owner session changes before completion',async()=>{
    let current=true,finishTeam!:(value:Response)=>void;
    const teamResponse=new Promise<Response>(resolve=>{finishTeam=resolve;});
    const draft={id:workspace,appointment_id:null,label:'Private note',revision:1,entries:[],work_candidates:[],
      model_contract_version:1,model_observed_at:'2026-10-21T18:00:00Z',
      private_draft:{title:'Private note',state:'unlinked',link_receipt_id:null,linked_at:null}};
    const fetchMock=vi.fn<typeof fetch>((url)=>String(url).endsWith('/provider-team')?teamResponse:Promise.resolve(json(draft)));
    vi.stubGlobal('fetch',fetchMock);
    const result=workspaceApi.openPrivateDraft({mode:'clerk_jwt',getToken:async()=>'invented-token',
      nativeSession:{revision:'00000000-0000-4000-8000-000000000010',isCurrent:()=>current}},workspace);
    const rejected=expect(result).rejects.toMatchObject({status:401});
    try{await vi.waitFor(()=>expect(fetchMock).toHaveBeenCalledTimes(2),{timeout:500});}
    finally{current=false;finishTeam(json(teamFixture()));await rejected;}
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('dispatches one exact create without waiting for the independent fresh team response',async()=>{
    let finishTeam!:(value:Response)=>void;
    const teamResponse=new Promise<Response>(resolve=>{finishTeam=resolve;});
    const body={title:'Private note',idempotency_key:'concurrent-create-key'};
    const draft={id:workspace,appointment_id:null,label:body.title,revision:1,entries:[],work_candidates:[],
      private_draft:{title:body.title,state:'unlinked',link_receipt_id:null,linked_at:null}};
    const fetchMock=vi.fn<typeof fetch>((url)=>String(url).endsWith('/provider-team')?teamResponse:Promise.resolve(json(draft)));
    vi.stubGlobal('fetch',fetchMock);
    let settled=false;
    const result=workspaceApi.createPrivateDraft({mode:'clerk_jwt',getToken:async()=>'invented-token'},body).finally(()=>{settled=true;});
    await vi.waitFor(()=>expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(settled).toBe(false);
    const create=fetchMock.mock.calls.find(([,request])=>request?.method==='POST')!;
    expect(create[1]?.body).toBe(JSON.stringify(body));
    finishTeam(json(teamFixture()));
    await expect(result).resolves.toMatchObject({workspace:draft,team:teamFixture()});
    expect(fetchMock.mock.calls.filter(([,request])=>request?.method==='POST')).toHaveLength(1);
  });

  it('settles a possibly committed create after the concurrent team read fails without retrying it',async()=>{
    let finishCreate!:(value:Response)=>void;
    const createResponse=new Promise<Response>(resolve=>{finishCreate=resolve;});
    const body={title:'Private note',idempotency_key:'uncertain-create-key'};
    const draft={id:workspace,appointment_id:null,label:body.title,revision:1,entries:[],work_candidates:[],
      private_draft:{title:body.title,state:'unlinked',link_receipt_id:null,linked_at:null}};
    const fetchMock=vi.fn<typeof fetch>((url)=>String(url).endsWith('/provider-team')?Promise.reject(new Error('unavailable')):createResponse);
    vi.stubGlobal('fetch',fetchMock);
    let settled=false;
    const result=workspaceApi.createPrivateDraft({mode:'clerk_jwt',getToken:async()=>'invented-token'},body);
    const rejected=expect(result.finally(()=>{settled=true;})).rejects.toMatchObject({status:503});
    await vi.waitFor(()=>expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(settled).toBe(false);
    finishCreate(json(draft));await rejected;
    expect(fetchMock.mock.calls.filter(([,request])=>request?.method==='POST')).toHaveLength(1);
    expect(fetchMock.mock.calls.find(([,request])=>request?.method==='POST')![1]?.body).toBe(JSON.stringify(body));
  });

  it('withholds a concurrent create when the native session changes before both reads finish',async()=>{
    let current=true,finishTeam!:(value:Response)=>void;
    const body={title:'Private note',idempotency_key:'changed-session-key'};
    const draft={id:workspace,appointment_id:null,label:body.title,revision:1,entries:[],work_candidates:[],
      private_draft:{title:body.title,state:'unlinked',link_receipt_id:null,linked_at:null}};
    const teamResponse=new Promise<Response>(resolve=>{finishTeam=resolve;});
    const fetchMock=vi.fn<typeof fetch>((url)=>String(url).endsWith('/provider-team')?teamResponse:Promise.resolve(json(draft)));
    vi.stubGlobal('fetch',fetchMock);
    const result=workspaceApi.createPrivateDraft({mode:'clerk_jwt',getToken:async()=>'invented-token',
      nativeSession:{revision:'00000000-0000-4000-8000-000000000010',isCurrent:()=>current}},body);
    const rejected=expect(result).rejects.toMatchObject({status:401});
    await vi.waitFor(()=>expect(fetchMock).toHaveBeenCalledTimes(2));
    current=false;finishTeam(json(teamFixture()));await rejected;
    expect(fetchMock.mock.calls.filter(([,request])=>request?.method==='POST')).toHaveLength(1);
  });

  it('refuses half-linked or foreign private-draft receipts and patient authority on create',async()=>{
    const identity:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>'invented-token'};
    const fetchMock=vi.fn<typeof fetch>().mockResolvedValue(json({contract_version:1,outcome:'saved',workspace:{
      id:workspace,appointment_id:appointment,label:'Private note',revision:1,entries:[],work_candidates:[],
      private_draft:{title:'Private note',state:'unlinked',link_receipt_id:null,linked_at:null}}}));
    vi.stubGlobal('fetch',fetchMock);
    await expect(workspaceApi.resolvePrivateDraft(identity,{title:'Private note',idempotency_key:'private-create-key'})).rejects.toMatchObject({status:503});
    await expect(workspaceApi.createPrivateDraft(identity,{title:'Private note',idempotency_key:'private-create-key',appointment_id:appointment} as never)).rejects.toMatchObject({status:422});
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it('bounds uncertain private-draft responses and never retries them automatically',async()=>{
    vi.useFakeTimers();
    const fetchMock=vi.fn<typeof fetch>(()=>new Promise(()=>{}));vi.stubGlobal('fetch',fetchMock);
    const pending=workspaceApi.resolvePrivateDraft({mode:'clerk_jwt',getToken:async()=>'invented-token'},
      {title:'Private note',idempotency_key:'private-create-key'});
    const rejected=expect(pending).rejects.toMatchObject({status:503});
    await vi.advanceTimersByTimeAsync(15000);await rejected;
    expect(fetchMock).toHaveBeenCalledOnce();expect(fetchMock.mock.calls[0][1]?.signal?.aborted).toBe(true);
  });

  it("bounds a stalled team read and aborts its request", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn<typeof fetch>(() => new Promise(() => {})); vi.stubGlobal("fetch", fetchMock);
    const result = workspaceApi.team({mode:"clerk_jwt",getToken:async()=>"token"});
    const rejected = expect(result).rejects.toMatchObject({status:503});
    await vi.advanceTimersByTimeAsync(30_000); await rejected;
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock.mock.calls[0][1]?.signal?.aborted).toBe(true);
  });

  it('bounds visit credentials and prevents a late request after the deadline',async()=>{
    vi.useFakeTimers();let release!:(token:string)=>void;
    const fetchMock=vi.fn();vi.stubGlobal('fetch',fetchMock);
    const rejected=expect(workspaceApi.catalog({mode:'clerk_jwt',getToken:()=>new Promise(resolve=>{release=resolve;})})).rejects.toMatchObject({status:503});
    await vi.advanceTimersByTimeAsync(20_000);await rejected;
    release('late-synthetic-token');await vi.advanceTimersByTimeAsync(1);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('bounds a stalled notebook response without repeating its request',async()=>{
    vi.useFakeTimers();const fetchMock=vi.fn().mockResolvedValue(new Response(new ReadableStream({start(){}}),{headers:{'Content-Type':'application/json'}}));
    vi.stubGlobal('fetch',fetchMock);
    const rejected=expect(workspaceApi.read({mode:'clerk_jwt',getToken:async()=>'synthetic-token'},workspace)).rejects.toMatchObject({status:503});
    await vi.advanceTimersByTimeAsync(20_000);await rejected;
    expect(fetchMock).toHaveBeenCalledOnce();expect(fetchMock.mock.calls[0][1].signal.aborted).toBe(true);
  });

  it("does not issue a team save after timed-out credentials eventually arrive", async () => {
    vi.useFakeTimers();
    let resolveToken!: (token:string)=>void;
    const fetchMock = vi.fn<typeof fetch>(); vi.stubGlobal("fetch", fetchMock);
    const body = {expected_revision:0,idempotency_key:"same-save",configuration:teamFixture().configuration};
    const result = workspaceApi.saveTeam({mode:"clerk_jwt",getToken:()=>new Promise(resolve=>{resolveToken=resolve;})},body);
    const rejected = expect(result).rejects.toMatchObject({status:503});
    await vi.advanceTimersByTimeAsync(30_000); await rejected;
    resolveToken("token"); await vi.advanceTimersByTimeAsync(1);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("bounds a stalled team response body and keeps retries byte-identical", async () => {
    vi.useFakeTimers();
    const body = {expected_revision:0,idempotency_key:"same-save",configuration:teamFixture().configuration};
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValueOnce(new Response(new ReadableStream({start(){}}),{headers:{"Content-Type":"application/json","Cache-Control":"no-store"}}))
      .mockResolvedValueOnce(json(teamFixture(body.configuration)));
    vi.stubGlobal("fetch",fetchMock);
    const access:AuthenticatedWorkspaceIdentity={mode:"clerk_jwt",getToken:async()=>"token"};
    const rejected=expect(workspaceApi.saveTeam(access,body)).rejects.toMatchObject({status:503});
    await vi.advanceTimersByTimeAsync(30_000);await rejected;
    await expect(workspaceApi.saveTeam(access,body)).resolves.toMatchObject({revision:1});
    expect(fetchMock.mock.calls[0][1]?.body).toBe(fetchMock.mock.calls[1][1]?.body);
  });

  it("sends only an exact Core reference for note linking and explains stale versions safely", async () => {
    const access: AuthenticatedWorkspaceIdentity = {mode: "clerk_jwt", getToken: vi.fn().mockResolvedValue("token")};
    const body = {expected_revision: 1, idempotency_key: "same-key", base_note_id: null, source: {
      session_id: "session", scribe_source_id: "source", source_sha256: "a".repeat(64), schema_ref: "schema",
      transcript_ref: "transcript", note_ref: "note", note_sha256: "b".repeat(64),
    }};
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValueOnce(json({entry_revision: 2, workspace: {id: workspace}}))
      .mockResolvedValueOnce(new Response(JSON.stringify({detail: "core_note_changed", secret: "private upstream sentinel"}), {status: 409}));
    vi.stubGlobal("fetch", fetchMock);
    await workspaceApi.linkCoreNote(access, workspace, body);
    expect(fetchMock.mock.calls[0][0]).toBe(`http://127.0.0.1:8018/workspaces/${workspace}/capture/note-links`);
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual(body);
    await expect(workspaceApi.linkCoreNote(access, workspace, body)).rejects.toMatchObject({
      status: 409, code: "core_note_changed", message: expect.stringContaining("Check its saved draft"),
    });
  });

  it("revalidates the selected encounter and uses fresh tokens without seeding or identity headers", async () => {
    const getToken = vi.fn().mockResolvedValueOnce("token-one").mockResolvedValueOnce("token-two").mockResolvedValueOnce("token-three");
    const access: AuthenticatedWorkspaceIdentity = { mode: "clerk_jwt", getToken };
    const fetchMock = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(json([{ appointment_id: appointment, workspace_id: workspace, label: "Invented" }]))
      .mockResolvedValueOnce(json(teamFixture()))
      .mockResolvedValueOnce(json({id:workspace,revision:1,entries:[],work_candidates:[],model_contract_version:1,model_observed_at:"2026-09-21T22:00:00Z"}));
    vi.stubGlobal("fetch", fetchMock);
    const result = await workspaceApi.open(access, appointment);
    expect(result.identity).toBe(access);
    expect(fetchMock.mock.calls.map(call => call[0])).toEqual([
      "http://127.0.0.1:8018/workspaces", "http://127.0.0.1:8018/provider-team",
      `http://127.0.0.1:8018/workspaces/${workspace}`,
    ]);
    fetchMock.mock.calls.forEach((call, index) => {
      const headers = new Headers(call[1]?.headers);
      expect(headers.get("Authorization")).toBe(`Bearer token-${["one", "two", "three"][index]}`);
      expect(headers.has("X-Box-Id")).toBe(false);
      expect(headers.has("X-Actor-Principal-Id")).toBe(false);
      expect(call[1]).toMatchObject({ cache: "no-store", credentials: "omit", redirect: "error" });
    });
    expect(getToken.mock.calls).toEqual(Array.from({ length: 3 }, () => [{ skipCache: true }]));
    expect(new Headers(fetchMock.mock.calls[2][1]?.headers).get("X-Cosmas-Model-Contract")).toBe("1");
  });

  it("requires explicit selection and never substitutes the first encounter for a missing one", async () => {
    const access: AuthenticatedWorkspaceIdentity = { mode: "clerk_jwt", getToken: vi.fn().mockResolvedValue("token") };
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(json([
      { appointment_id: appointment, workspace_id: workspace, label: "Invented" },
    ]));
    vi.stubGlobal("fetch", fetchMock);
    await expect(workspaceApi.open(access)).rejects.toMatchObject({ status: 400 });
    expect(fetchMock).not.toHaveBeenCalled();
    await expect(workspaceApi.open(access, "no-longer-available")).rejects.toMatchObject({ status: 404 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it.each([undefined, null, "", "a".repeat(63), "A".repeat(64), "g".repeat(64), 123])("rejects absent or invalid recovery identity on authenticated team reads (%s)", async recovery_scope => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValue(json({revision:1,recovery_scope})));
    await expect(workspaceApi.team({mode:"clerk_jwt",getToken:async()=>"token"})).rejects.toMatchObject({status:503,code:"workspace_recovery_unavailable"});
  });

  it("does not create a notebook when an older backend omits private recovery identity", async () => {
    const fetchMock=vi.fn<typeof fetch>().mockResolvedValueOnce(json([{appointment_id:appointment,workspace_id:null,label:"Invented"}]))
      .mockResolvedValueOnce(json({revision:1}));
    vi.stubGlobal("fetch",fetchMock);
    await expect(workspaceApi.open({mode:"clerk_jwt",getToken:async()=>"token"},appointment)).rejects.toMatchObject({code:"workspace_recovery_unavailable"});
    expect(fetchMock.mock.calls.map(call=>call[1]?.method)).toEqual(["GET","GET"]);
  });

  it("keeps a team save unconfirmed if the response omits recovery identity", async () => {
    vi.stubGlobal("fetch",vi.fn<typeof fetch>().mockResolvedValue(json({revision:2})));
    await expect(workspaceApi.saveTeam({mode:"clerk_jwt",getToken:async()=>"token"},
      {expected_revision:1,idempotency_key:"invented-team-save",configuration:teamFixture().configuration}))
      .rejects.toMatchObject({code:"workspace_recovery_unavailable"});
  });

  it.each([null, "", " padded", "line\nbreak", "x".repeat(8193)])("does not send an invalid token", async token => {
    const fetchMock = vi.fn<typeof fetch>(); vi.stubGlobal("fetch", fetchMock);
    const access: AuthenticatedWorkspaceIdentity = { mode: "clerk_jwt", getToken: vi.fn().mockResolvedValue(token) };
    await expect(workspaceApi.catalog(access)).rejects.toMatchObject({ status: 401 });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("sanitizes identity-provider errors and makes no request", async () => {
    const fetchMock = vi.fn<typeof fetch>(); vi.stubGlobal("fetch", fetchMock);
    const access: AuthenticatedWorkspaceIdentity = {
      mode: "clerk_jwt", getToken: vi.fn().mockRejectedValue(new Error("private provider detail")),
    };
    await expect(workspaceApi.catalog(access)).rejects.toBeInstanceOf(WorkspaceApiError);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects an unqualified remote API before obtaining a token", async () => {
    vi.stubEnv("VITE_API_BASE", "https://remote.invalid");
    const getToken = vi.fn(); const fetchMock = vi.fn<typeof fetch>(); vi.stubGlobal("fetch", fetchMock);
    await expect(workspaceApi.catalog({ mode: "clerk_jwt", getToken })).rejects.toThrow();
    expect(getToken).not.toHaveBeenCalled(); expect(fetchMock).not.toHaveBeenCalled();
  });
  it('does not obtain credentials or read when the native account has already closed',async()=>{
    const getToken=vi.fn(),fetchMock=vi.fn<typeof fetch>();vi.stubGlobal('fetch',fetchMock);
    const access:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken,nativeSession:{revision:appointment,isCurrent:()=>false}};
    await expect(workspaceApi.catalog(access)).rejects.toMatchObject({status:401});
    expect(getToken).not.toHaveBeenCalled();expect(fetchMock).not.toHaveBeenCalled();
  });
  it('fences a token resolved after its native account closed before any request is sent',async()=>{
    let current=true,release!:(value:string)=>void;const getToken=vi.fn(()=>new Promise<string>(resolve=>{release=resolve;}));
    const fetchMock=vi.fn<typeof fetch>();vi.stubGlobal('fetch',fetchMock);
    const access:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken,nativeSession:{revision:appointment,isCurrent:()=>current}};
    const result=workspaceApi.catalog(access),rejected=expect(result).rejects.toMatchObject({status:401});
    current=false;release('invented-token');await rejected;expect(fetchMock).not.toHaveBeenCalled();
  });
});
