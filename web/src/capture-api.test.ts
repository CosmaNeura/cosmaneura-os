import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { prepareCapture, request, workspaceCaptureBff } from "./capture-api";

const workspace = "00000000-0000-4000-8000-000000000002";
const session = "00000000-0000-4000-8000-000000000003";
const consent = "00000000-0000-4000-8000-000000000004";
const legacyCapabilities = { protocol_version: "1.0", media: {
  media_type: "audio/wav", encoding: "pcm_s16le", channels: 1, sample_rate_hz: 16000 },
  target_chunk_duration_ms: 10000, max_envelope_bytes: 327680, max_chunks: 1000,
  remaining_aggregate_plaintext_bytes: 67108864, capture_lease_ttl_seconds: 900,
  reservation_window_seconds: 900, max_reservations_per_batch: 90, upload_concurrency: 2 };
const identity = () => ({ mode: "clerk_jwt" as const, getToken: vi.fn().mockResolvedValue("synthetic-token") });
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
});
beforeEach(() => vi.stubEnv("VITE_API_BASE", "http://127.0.0.1:8018"));
afterEach(() => { vi.useRealTimers(); vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

it("uses fresh signed requests for admission and recorder operations without client identity claims", async () => {
  const access = identity();
  const fetchMock = vi.fn<typeof fetch>()
    .mockResolvedValueOnce(json({ status: "prepared", workspace_id: workspace, session_id: session, consent_record_id: consent }))
    .mockResolvedValueOnce(json({ workspace_id: workspace, session_id: session, operation: "capabilities", receipt: legacyCapabilities }));
  vi.stubGlobal("fetch", fetchMock);
  expect(await prepareCapture(workspace, access, null, "resume-key")).toMatchObject({ session_id: session });
  await workspaceCaptureBff(workspace, session, access).getCapabilities(session);
  expect(access.getToken.mock.calls).toEqual([[{ skipCache: true }], [{ skipCache: true }]]);
  expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
    `http://127.0.0.1:8018/workspaces/${workspace}/capture/admission`,
    `http://127.0.0.1:8018/workspaces/${workspace}/capture/operations`,
  ]);
  for (const [, options] of fetchMock.mock.calls) {
    expect(options).toMatchObject({ cache: "no-store", credentials: "omit", redirect: "error", referrerPolicy: "no-referrer" });
    const headers = new Headers(options?.headers);
    expect(headers.get("Authorization")).toBe("Bearer synthetic-token");
    expect(headers.has("X-Box-Id")).toBe(false);
    expect(String(options?.body)).not.toMatch(/tenant_id|patient_id|practitioner_id|token/);
  }
});

it.each(["https://remote.invalid", "app://cosmas/api", "http://user@127.0.0.1:8018"])(
  "does not fetch a token for an unqualified capture origin %s", async origin => {
    vi.stubEnv("VITE_API_BASE", origin);
    const access = identity();
    const fetchMock = vi.fn(); vi.stubGlobal("fetch", fetchMock);
    await expect(prepareCapture(workspace, access, null, "resume-key")).rejects.toMatchObject({ status: 401 });
    expect(access.getToken).not.toHaveBeenCalled(); expect(fetchMock).not.toHaveBeenCalled();
  });

it.each(["wrong-session", "wrong-workspace", "wrong-operation", "extra", "oversized", "missing-no-store"])(
  "does not release an invalid operation response: %s", async fault => {
    const body: Record<string, unknown> = { session_id: session, workspace_id: workspace, operation: "capabilities", receipt: {} };
    if (fault === "wrong-session") body.session_id = consent;
    if (fault === "wrong-workspace") body.workspace_id = consent;
    if (fault === "wrong-operation") body.operation = "complete";
    if (fault === "extra") body.private_sentinel = "hidden";
    if (fault === "oversized") body.receipt = { private_sentinel: "x".repeat(131073) };
    const response = fault === "missing-no-store" ? new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } }) : json(body);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
    await expect(workspaceCaptureBff(workspace, session, identity()).getCapabilities(session)).rejects.toThrow();
  });

it("preserves known consent/recovery codes and sanitizes unexpected service errors", async () => {
  const fetchMock = vi.fn<typeof fetch>().mockResolvedValueOnce(json({ detail: "capture_consent_required" }, 409))
    .mockResolvedValueOnce(json({ detail: "private upstream detail" }, 503));
  vi.stubGlobal("fetch", fetchMock);
  await expect(prepareCapture(workspace, identity(), null, "resume-key"))
    .rejects.toMatchObject({ code: "capture_consent_required" });
  await expect(prepareCapture(workspace, identity(), null, "resume-key"))
    .rejects.toMatchObject({ code: "capture_request_unconfirmed" });
});

it("permits a bounded source transcript beyond the smaller control-response limit", async () => {
  const transcript = { session_id: session, segments: [{ content: "Invented speech. ".repeat(10000) }] };
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ session_id: session, workspace_id: workspace,
    operation: "transcript", receipt: transcript })));
  expect(await workspaceCaptureBff(workspace, session, identity()).getTranscript(session)).toEqual(transcript);
});

it("bounds transcript streaming independently of control receipts", async () => {
  const transcript = { session_id: session, segments: [{ content: "x".repeat(25 * 1024 * 1024) }] };
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ session_id: session, workspace_id: workspace,
    operation: "transcript", receipt: transcript })));
  await expect(workspaceCaptureBff(workspace, session, identity()).getTranscript(session))
    .rejects.toMatchObject({ code: "capture_receipt_invalid" });
});

it("bounds stalled credentials and never dispatches when they arrive after the deadline", async () => {
  vi.useFakeTimers();
  let release!: (token: string) => void;
  const access = {mode:"clerk_jwt" as const,getToken:vi.fn(()=>new Promise<string>(resolve=>{release=resolve;}))};
  const fetchMock=vi.fn();vi.stubGlobal("fetch",fetchMock);
  const pending=request(workspace,"prep",access,{idempotency_key:"retained-context-key"});
  const rejected=expect(pending).rejects.toMatchObject({status:503,code:"capture_request_unconfirmed"});
  expect(access.getToken).toHaveBeenCalledOnce();
  await vi.advanceTimersByTimeAsync(30000);await rejected;
  expect(fetchMock).not.toHaveBeenCalled();expect(vi.getTimerCount()).toBe(0);
  release("late-synthetic-token");await vi.advanceTimersByTimeAsync(1);
  expect(fetchMock).not.toHaveBeenCalled();expect(access.getToken).toHaveBeenCalledOnce();
});

it("does not acquire credentials for an already-cancelled request",async()=>{
  vi.useFakeTimers();const controller=new AbortController();controller.abort();
  const access=identity(),fetchMock=vi.fn();vi.stubGlobal("fetch",fetchMock);
  await expect(request(workspace,"prep",access,{},controller.signal)).rejects.toMatchObject({status:503,code:"capture_request_unconfirmed"});
  expect(access.getToken).not.toHaveBeenCalled();expect(fetchMock).not.toHaveBeenCalled();expect(vi.getTimerCount()).toBe(0);
});

it("settles cancellation during authentication and ignores a later token",async()=>{
  vi.useFakeTimers();const controller=new AbortController();let release!:(token:string)=>void;
  const access={mode:"clerk_jwt" as const,getToken:vi.fn(()=>new Promise<string>(resolve=>{release=resolve;}))};
  const fetchMock=vi.fn();vi.stubGlobal("fetch",fetchMock);
  const pending=prepareCapture(workspace,access,null,"same-admission-key",controller.signal);
  const rejected=expect(pending).rejects.toMatchObject({status:503,code:"capture_request_unconfirmed"});
  expect(access.getToken).toHaveBeenCalledOnce();controller.abort();await rejected;
  release("late-synthetic-token");await vi.advanceTimersByTimeAsync(1);
  expect(fetchMock).not.toHaveBeenCalled();expect(vi.getTimerCount()).toBe(0);
});

it("preserves access-denied status for a credential failure and exposes no credential error text",async()=>{
  vi.useFakeTimers();const fetchMock=vi.fn();vi.stubGlobal("fetch",fetchMock);
  const access={mode:"clerk_jwt" as const,getToken:vi.fn().mockRejectedValue(new Error("private credential failure"))};
  await expect(request(workspace,"prep",access,{})).rejects.toMatchObject({status:401,code:"capture_access_unavailable",message:"capture BFF request failed"});
  expect(fetchMock).not.toHaveBeenCalled();expect(vi.getTimerCount()).toBe(0);
});

function desktopIdentity(isCurrent:()=>boolean) {
  for(const flag of ["VITE_WORKSPACE_DESKTOP_AUTH_ENABLED","VITE_DESKTOP_SYNTHETIC_ENABLED","VITE_WORKSPACE_AUTHENTICATED_ENABLED","VITE_WORKSPACE_ENABLED"])vi.stubEnv(flag,"true");
  vi.stubEnv("VITE_COSMAS_ENV","synth_os");vi.stubEnv("VITE_API_BASE","app://cosmas/api");
  vi.stubGlobal("window",{location:{href:"app://cosmas/index.html"}});
  return {mode:"desktop_native" as const,revision:session,isCurrent};
}
it("rechecks the desktop session after authentication and before dispatch",async()=>{
  const isCurrent=vi.fn().mockReturnValueOnce(true).mockReturnValue(false),access=desktopIdentity(isCurrent);
  const fetchMock=vi.fn();vi.stubGlobal("fetch",fetchMock);
  await expect(request(workspace,"prep",access,{})).rejects.toMatchObject({status:401,code:"capture_access_unavailable"});
  expect(isCurrent).toHaveBeenCalledTimes(2);expect(fetchMock).not.toHaveBeenCalled();
});

it("still withholds a response when the desktop session changes after dispatch",async()=>{
  let current=true;const access=desktopIdentity(()=>current);
  const fetchMock=vi.fn(async()=>{current=false;return json({private_fixture:"old session"});});vi.stubGlobal("fetch",fetchMock);
  await expect(request(workspace,"prep",access,{})).rejects.toMatchObject({status:503,code:"capture_request_unconfirmed"});
  expect(fetchMock).toHaveBeenCalledOnce();
});

it("uses one deadline across credential acquisition and dispatch",async()=>{
  vi.useFakeTimers();let release!:(token:string)=>void;
  const access={mode:"clerk_jwt" as const,getToken:()=>new Promise<string>(resolve=>{release=resolve;})};
  const fetchMock=vi.fn((_url:string,options:RequestInit)=>new Promise<Response>((_resolve,reject)=>{
    options.signal!.addEventListener("abort",()=>reject(new DOMException("cancelled","AbortError")),{once:true});
  }));vi.stubGlobal("fetch",fetchMock);
  const pending=request(workspace,"prep",access,{});
  const rejected=expect(pending).rejects.toMatchObject({status:503,code:"capture_request_unconfirmed"});
  await vi.advanceTimersByTimeAsync(20000);release("synthetic-token");await vi.advanceTimersByTimeAsync(1);
  expect(fetchMock).toHaveBeenCalledOnce();
  await vi.advanceTimersByTimeAsync(10000);await rejected;
  expect(fetchMock.mock.calls[0][1].signal?.aborted).toBe(true);expect(vi.getTimerCount()).toBe(0);
});
