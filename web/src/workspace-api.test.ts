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

  it("bounds a stalled team read and aborts its request", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn<typeof fetch>(() => new Promise(() => {})); vi.stubGlobal("fetch", fetchMock);
    const result = workspaceApi.team({mode:"clerk_jwt",getToken:async()=>"token"});
    const rejected = expect(result).rejects.toMatchObject({status:503});
    await vi.advanceTimersByTimeAsync(30_000); await rejected;
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock.mock.calls[0][1]?.signal?.aborted).toBe(true);
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
});
