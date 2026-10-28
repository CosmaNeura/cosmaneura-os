import { StrictMode, act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NativeAuthenticatedWorkspace } from "./NativeAuthenticatedWorkspace";
import { parseNativeAuthState, parseNativeToken, type NativeAuthState } from "./native-auth";
import { accessPending } from "./practice-access-test-fixture";
import {teamFixture} from "./team-setup-test-fixture";
import { REQUIRED_WORKSPACE_CONTRACTS } from "./workspace-protocol";

const first: NativeAuthState = { phase: "ready", revision: "00000000-0000-4000-8000-000000000001",
  identity: { userId: "user_first", sessionId: "sess_first", organizationId: "org_test" } };
const second: NativeAuthState = { phase: "ready", revision: "00000000-0000-4000-8000-000000000002",
  identity: { userId: "user_second", sessionId: "sess_second", organizationId: "org_test" } };
const signedOut: NativeAuthState = { phase: "signedOut", revision: "00000000-0000-4000-8000-000000000003", identity: null };
const pending: NativeAuthState = { phase: "signOutPending", revision: "00000000-0000-4000-8000-000000000004", identity: null };
const token = "local.binding.fixture";
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function harness(initial = first) {
  let current = initial;
  const listeners = new Set<(value: unknown) => void>();
  const plugin = {
    getState: vi.fn(async () => current as unknown),
    getToken: vi.fn(async ({ expectedRevision }: { expectedRevision: string }) => ({ token, revision: expectedRevision } as unknown)),
    signIn: vi.fn(async () => { current = first; }),
    signOut: vi.fn(async () => { current = signedOut; }),
    addListener: vi.fn(async (_event: "authStateChanged", listener: (value: unknown) => void) => {
      listeners.add(listener); return { remove: async () => { listeners.delete(listener); } };
    }),
  };
  return { plugin, set: (state: NativeAuthState) => { current = state; },
    emit: (value: unknown) => { for (const listener of listeners) listener(value); }, listeners };
}

describe("native workspace session", () => {
  let container: HTMLDivElement;
  let root: Root;
  let fetchMock: ReturnType<typeof vi.fn<typeof fetch>>;
  beforeEach(() => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    vi.stubEnv("VITE_API_BASE", "http://127.0.0.1:8018");
    fetchMock = vi.fn<typeof fetch>().mockImplementation(async url => new Response(JSON.stringify(String(url).endsWith("/provider-team")?teamFixture():[
      { appointment_id: "invented_visit", workspace_id: null, label: "Private invented label" },
    ]), { headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    container = document.createElement("div"); document.body.append(container); root = createRoot(container);
  });
  afterEach(async () => {
    await act(async () => root.unmount()); container.remove();
    vi.unstubAllGlobals(); vi.unstubAllEnvs(); vi.restoreAllMocks(); vi.useRealTimers();
  });
  async function render(native: ReturnType<typeof harness>, available = true) {
    await act(async () => root.render(createElement(NativeAuthenticatedWorkspace, { plugin: native.plugin, available })));
  }
  async function click(label: string) {
    const button = [...container.querySelectorAll("button")].find(item => item.textContent?.startsWith(label));
    expect(button, label).toBeDefined(); await act(async () => button!.click());
  }
  it("holds the hosted iPhone workspace at practice access and clears it on sign-out", async () => {
    for (const [key,value] of Object.entries({VITE_API_BASE:"https://api.example.invalid",VITE_COSMAS_ENV:"early_adopter_beta",
      VITE_WORKSPACE_ENABLED:"true",VITE_WORKSPACE_AUTHENTICATED_ENABLED:"true",VITE_WORKSPACE_HOSTED_ENABLED:"true",
      VITE_WORKSPACE_HOSTED_CLIENT:"apple",VITE_WORKSPACE_DATA_MODE:"synthetic",VITE_WORKSPACE_NATIVE_AUTH_ENABLED:"true",
      VITE_WORKSPACE_HOSTED_API_ORIGIN:"https://api.example.invalid"})) vi.stubEnv(key,value);
    vi.stubGlobal("window",{location:{href:"capacitor://localhost/index.html"},setInterval:globalThis.setInterval,clearInterval:globalThis.clearInterval});
    fetchMock.mockImplementation(async url=>{
      const body=url==="https://api.example.invalid/practice-access/compatibility"
        ? {contract_version:1,workspace_protocol:1,requests_require_protocol:true,contracts:{...REQUIRED_WORKSPACE_CONTRACTS}}
        : url==="https://api.example.invalid/practice-access"?accessPending
        : url==="https://api.example.invalid/practice-access/setup"?{contract_version:1,state:"join_existing",practice:null,display_name:null,can_start_practice:false}:null;
      if(!body)throw new Error("Unexpected hosted workspace request");
      return new Response(JSON.stringify(body),{headers:{"Content-Type":"application/json","Cache-Control":"no-store","X-Cosmas-Workspace-Protocol":"1"}});
    });
    const native=harness();await render(native);expect(container.textContent).toContain("Waiting for your practice owner");
    expect(container.textContent).not.toContain("Choose an encounter");
    expect(fetchMock.mock.calls.map(([url])=>url)).toEqual(["https://api.example.invalid/practice-access/compatibility","https://api.example.invalid/practice-access","https://api.example.invalid/practice-access/setup"]);
    expect(native.plugin.getToken).toHaveBeenCalledTimes(3);
    for(const [,options] of fetchMock.mock.calls){
      expect(new Headers(options?.headers).get("X-Cosmas-Workspace-Protocol")).toBe("1");
      expect(new Headers(options?.headers).get("Authorization")).toBe(`Bearer ${token}`);
    }
    await click("Sign out");expect(container.textContent).not.toContain("Ada Beta");expect(native.plugin.signOut).toHaveBeenCalledOnce();
  });
  it("keeps missing or disabled native adapters offline", async () => {
    const native = harness(); await render(native, false);
    expect(native.plugin.addListener).not.toHaveBeenCalled(); expect(native.plugin.getState).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled(); expect(container.textContent).toContain("Sign-in isn't available");
    native.set({ ...signedOut, phase: "disabled" }); await render(native);
    expect(container.textContent).toContain("Sign-in isn't available"); expect(native.plugin.signIn).not.toHaveBeenCalled();
  });
  it("signs in explicitly and acquires a fresh token for every request", async () => {
    const native = harness(signedOut); await render(native); expect(fetchMock).not.toHaveBeenCalled();
    expect(container.textContent).toContain("Sign in to CosmaBot");
    expect(container.textContent).not.toContain("Cosmas OS");
    expect(container.textContent).not.toContain("Sign-in needs attention");
    expect(container.querySelector(".apple-hosted-card")?.getAttribute("role")).toBe("status");
    await click("Sign in"); await click("Visits and notes"); await click("Visits and notes");
    expect(native.plugin.signIn).toHaveBeenCalledTimes(1); expect(native.plugin.getToken).toHaveBeenCalledTimes(5);
    expect(native.plugin.getToken.mock.calls).toEqual(Array.from({length:5},()=>[{ expectedRevision: first.revision }]));
    for (const [, options] of fetchMock.mock.calls) {
      expect(new Headers(options?.headers).get("Authorization")).toBe(`Bearer ${token}`);
      expect(options?.credentials).toBe("omit");
    }
    expect(container.textContent).toContain("Private invented label");
  });
  it("recovers an unavailable session without admitting events during sign-in", async () => {
    const native = harness({ ...signedOut, phase: "unavailable" });
    const signin = deferred<void>(); native.plugin.signIn.mockReturnValueOnce(signin.promise);
    await render(native); await click("Sign in again");
    await act(async () => native.emit(first));
    expect(container.textContent).toContain("Updating your secure session");
    expect(container.textContent).not.toContain("Choose an encounter");
    expect(native.plugin.getToken).not.toHaveBeenCalled(); expect(fetchMock).not.toHaveBeenCalled();
    native.set(second); await act(async () => signin.resolve());
    await click("Visits and notes");
    expect(native.plugin.signIn).toHaveBeenCalledOnce();
    expect(native.plugin.getToken.mock.calls).toEqual(Array.from({length:4},()=>[{ expectedRevision: second.revision }]));
    expect(container.textContent).toContain("Private invented label");
  });
  it("keeps a failed recovery closed and allows sign-out when session reads recover", async () => {
    const native = harness(); native.plugin.getState.mockRejectedValue(new Error("private provider detail"));
    native.plugin.signIn.mockRejectedValue(new Error("private provider detail"));
    await render(native); await click("Sign in again");
    expect(container.textContent).toContain("Sign-in needs attention");
    expect(container.textContent).not.toContain("private provider detail");
    expect(container.textContent).not.toContain("Choose an encounter");
    expect(native.plugin.getToken).not.toHaveBeenCalled(); expect(fetchMock).not.toHaveBeenCalled();
    native.plugin.getState.mockResolvedValue(signedOut); await click("Sign out");
    expect(native.plugin.signOut).toHaveBeenCalledOnce();
    expect(container.textContent).toContain("Sign in to CosmaBot");
    expect(fetchMock).not.toHaveBeenCalled();
  });
  it.each(["failed", "cancelled"])("keeps %s sign-in recovery through native pending polls and retries via sign-in", async outcome => {
    vi.useFakeTimers();
    const native = harness(signedOut);
    native.plugin.signIn.mockImplementationOnce(async () => {
      native.set(pending);
      throw outcome === "cancelled" ? new DOMException("private provider detail", "AbortError") : new Error("private provider detail");
    });
    await render(native); await click("Sign in");
    expect(container.textContent).toContain("Sign-in didn’t finish");
    expect(container.textContent).not.toContain("Finish signing out");
    expect(container.textContent).not.toContain("expired");
    expect(container.textContent).not.toContain("private provider detail");
    expect(native.plugin.getToken).not.toHaveBeenCalled(); expect(fetchMock).not.toHaveBeenCalled();
    const reads = native.plugin.getState.mock.calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
    expect(native.plugin.getState.mock.calls.length).toBeGreaterThan(reads);
    expect(container.textContent).toContain("Sign-in didn’t finish");
    vi.useRealTimers();
    const retry = deferred<void>();
    native.plugin.signIn.mockImplementationOnce(() => retry.promise);
    await click("Try signing in again");
    expect(native.plugin.signIn).toHaveBeenCalledTimes(2);
    expect(native.plugin.signOut).not.toHaveBeenCalled();
    expect(container.textContent).toContain("Updating your secure session");
    await act(async () => native.emit(first));
    expect(native.plugin.getToken).not.toHaveBeenCalled(); expect(fetchMock).not.toHaveBeenCalled();
    native.set(first); await act(async () => retry.resolve());
    expect(container.textContent).not.toContain("Sign-in didn’t finish");
    expect(container.textContent).toContain("Sign out");
  });
  it("keeps unknown restored pending state on the existing sign-out recovery path", async () => {
    const native = harness(pending); await render(native);
    expect(container.textContent).toContain("Finish signing out");
    expect(container.textContent).not.toContain("Sign-in didn’t finish");
    await click("Retry sign-out");
    expect(native.plugin.signOut).toHaveBeenCalledOnce(); expect(native.plugin.signIn).not.toHaveBeenCalled();
    expect(container.textContent).toContain("Sign in to CosmaBot");
  });
  it("uses explicit sign-out wording after a recovered sign-in", async () => {
    const native = harness(signedOut);
    native.plugin.signIn.mockImplementationOnce(async () => { native.set(pending); throw new Error("private detail"); });
    await render(native); await click("Sign in");
    await click("Try signing in again");
    native.plugin.signOut.mockImplementationOnce(async () => { native.set(pending); throw new Error("private detail"); });
    await click("Sign out");
    expect(container.textContent).toContain("Finish signing out");
    expect(container.textContent).not.toContain("Sign-in didn’t finish");
    await click("Retry sign-out");
    expect(native.plugin.signOut).toHaveBeenCalledTimes(2);
    expect(container.textContent).toContain("Sign in to CosmaBot");
  });
  it("does not carry sign-in recovery or late replies into a replacement adapter", async () => {
    const old = harness(signedOut), delayed = deferred<void>();
    old.plugin.signIn.mockImplementationOnce(() => delayed.promise);
    await render(old); await click("Sign in");
    const replacement = harness(pending); await render(replacement);
    expect(container.textContent).toContain("Finish signing out");
    old.set(pending); await act(async () => delayed.reject(new Error("private old-adapter detail")));
    await act(async () => old.emit(first));
    expect(container.textContent).toContain("Finish signing out");
    expect(container.textContent).not.toContain("Sign-in didn’t finish");
    expect(replacement.plugin.getToken).not.toHaveBeenCalled(); expect(fetchMock).not.toHaveBeenCalled();
    await click("Retry sign-out");
    expect(replacement.plugin.signOut).toHaveBeenCalledOnce();
    expect(old.plugin.signOut).not.toHaveBeenCalled();
  });
  it("discards private labels and a pending token when identity changes", async () => {
    const native = harness(); await render(native); await click("Visits and notes");
    const late = deferred<unknown>(); native.plugin.getToken.mockReturnValueOnce(late.promise);
    await click("Visits and notes"); await act(async () => native.emit(second));
    expect(container.textContent).not.toContain("Private invented label");
    const beforeLate=fetchMock.mock.calls.length;
    await act(async () => late.resolve({ token, revision: first.revision }));
    expect(fetchMock).toHaveBeenCalledTimes(beforeLate); expect(container.textContent).toContain("Choose an encounter");
  });
  it("keeps the current workspace through same-account parent renders and native checks", async () => {
    vi.useFakeTimers();
    const native = harness(); await render(native); await click("Visits and notes");
    await render(native); await act(async()=>native.emit({...first}));
    await act(async()=>vi.advanceTimersByTimeAsync(5_000));
    expect(container.textContent).toContain("Private invented label");
    expect(fetchMock).toHaveBeenCalledTimes(4);
    await click("Visits and notes");
    expect(native.plugin.getToken).toHaveBeenCalledTimes(5);
  });
  it("closes on logout, rejects late tokens, and offers a safe retry after failure", async () => {
    const native = harness(); await render(native); await click("Visits and notes");
    const late = deferred<unknown>(); native.plugin.getToken.mockReturnValueOnce(late.promise);
    await click("Visits and notes"); const logout = deferred<void>(); native.plugin.signOut.mockReturnValueOnce(logout.promise);
    await click("Sign out"); expect(container.textContent).not.toContain("Private invented label");
    await act(async () => { native.emit(first); late.resolve({ token, revision: first.revision }); });
    expect(container.textContent).not.toContain("Choose an encounter"); expect(fetchMock).toHaveBeenCalledTimes(4);
    native.set(pending); await act(async () => logout.reject(new Error("secret provider detail")));
    expect(container.textContent).toContain("Retry sign-out"); expect(container.textContent).not.toContain("secret provider detail");
    await click("Retry sign-out"); expect(container.textContent).toContain("Sign in to CosmaBot");
  });
  it("does not let an old state read undo a newer event", async () => {
    const native = harness(); const read = deferred<unknown>(); native.plugin.getState.mockReturnValueOnce(read.promise);
    await render(native); await act(async () => native.emit(pending));
    await act(async () => read.resolve(first)); expect(container.textContent).toContain("Retry sign-out");
    expect(container.textContent).not.toContain("Choose an encounter");
  });
  it("preserves private UI on an unchanged poll and closes it on malformed state", async () => {
    vi.useFakeTimers(); const native = harness(); await render(native); await click("Visits and notes");
    await act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
    expect(container.textContent).toContain("Private invented label");
    await act(async () => native.emit({ ...first, identity: second.identity }));
    expect(container.textContent).not.toContain("Private invented label");
    expect(container.textContent).toContain("Sign-in needs attention");
  });
  it("ignores pending actions and tokens from a replaced adapter", async () => {
    const old = harness(); await render(old); const late = deferred<unknown>(); old.plugin.getToken.mockReturnValueOnce(late.promise);
    await click("Visits and notes"); const logout = deferred<void>(); old.plugin.signOut.mockReturnValueOnce(logout.promise);
    await click("Sign out"); const fresh = harness(second); await render(fresh); await click("Visits and notes");
    await act(async () => { logout.resolve(); late.resolve({ token, revision: first.revision }); old.emit(pending); });
    expect(fetchMock).toHaveBeenCalledTimes(7); expect(container.textContent).toContain("Private invented label");
    expect(fresh.plugin.getState).toHaveBeenCalledTimes(1); expect(old.listeners.size).toBe(0);
  });
  it("cleans up strict-mode subscriptions and denies tokens after unmount", async () => {
    const native = harness(); await act(async () => root.render(createElement(StrictMode, null,
      createElement(NativeAuthenticatedWorkspace, { plugin: native.plugin, available: true }))));
    expect(native.listeners.size).toBe(1); const late = deferred<unknown>(); native.plugin.getToken.mockReturnValueOnce(late.promise);
    await click("Visits and notes"); const beforeUnmount=fetchMock.mock.calls.length; await act(async () => root.render(null));
    await act(async () => late.resolve({ token, revision: first.revision }));
    expect(fetchMock).toHaveBeenCalledTimes(beforeUnmount); expect(native.listeners.size).toBe(0);
  });
  it.each([null, { token, revision: second.revision }, { token: "opaque-capture-grant", revision: first.revision }])(
    "never submits malformed or mismatched token replies", async reply => {
      const native = harness(); native.plugin.getToken.mockResolvedValue(reply); await render(native); await click("Visits and notes");
      expect(fetchMock).not.toHaveBeenCalled();
    });
});

describe("native envelope boundary", () => {
  it.each([null, [], { ...first, extra: "secret" }, { ...first, revision: "invalid" },
    { ...first, identity: { ...first.identity, userId: "user_" } }, { ...signedOut, identity: first.identity },
    { ...first, identity: { ...first.identity, secret: "never accepted" } }])("rejects malformed session data", value => {
      expect(() => parseNativeAuthState(value)).toThrow("Native session unavailable");
    });
  it("copies accepted identity data and bounds token size", () => {
    const supplied = { ...first, identity: { ...first.identity! } };
    const accepted = parseNativeAuthState(supplied); supplied.identity.userId = "user_changed";
    expect(accepted.identity?.userId).toBe("user_first");
    expect(() => parseNativeToken({ token: "a".repeat(8193) + ".b.c", revision: first.revision }, first.revision)).toThrow();
  });
});
