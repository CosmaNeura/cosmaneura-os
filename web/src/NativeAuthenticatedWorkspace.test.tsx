import { StrictMode, act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NativeAuthenticatedWorkspace } from "./NativeAuthenticatedWorkspace";
import { parseNativeAuthState, parseNativeToken, type NativeAuthState } from "./native-auth";

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
    fetchMock = vi.fn<typeof fetch>().mockImplementation(async () => new Response(JSON.stringify([
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
    fetchMock.mockImplementation(async()=>new Response(JSON.stringify({contract_version:1,state:"pending",role:null,
      request:{request_id:"873c4f63-2c89-4a51-a834-41574da371a9",display_name:"Ada Beta",review_sha256:"a".repeat(64),state:"pending",
        created_at:"2026-09-24T09:00:00+00:00",expires_at:"2026-10-01T09:00:00+00:00"}}),{headers:{"Content-Type":"application/json","Cache-Control":"no-store"}}));
    const native=harness();await render(native);expect(container.textContent).toContain("Waiting for your practice owner");
    expect(container.textContent).not.toContain("Choose an encounter");expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe("https://api.example.invalid/practice-access");
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
    await click("Sign in"); await click("Choose an encounter"); await click("Refresh encounters");
    expect(native.plugin.signIn).toHaveBeenCalledTimes(1); expect(native.plugin.getToken).toHaveBeenCalledTimes(2);
    expect(native.plugin.getToken.mock.calls).toEqual([[{ expectedRevision: first.revision }], [{ expectedRevision: first.revision }]]);
    for (const [, options] of fetchMock.mock.calls) {
      expect(new Headers(options?.headers).get("Authorization")).toBe(`Bearer ${token}`);
      expect(options?.credentials).toBe("omit");
    }
    expect(container.textContent).toContain("Private invented label");
  });
  it("discards private labels and a pending token when identity changes", async () => {
    const native = harness(); await render(native); await click("Choose an encounter");
    const late = deferred<unknown>(); native.plugin.getToken.mockReturnValueOnce(late.promise);
    await click("Refresh encounters"); await act(async () => native.emit(second));
    expect(container.textContent).not.toContain("Private invented label");
    await act(async () => late.resolve({ token, revision: first.revision }));
    expect(fetchMock).toHaveBeenCalledTimes(1); expect(container.textContent).toContain("Choose an encounter");
  });
  it("keeps the current workspace through same-account parent renders and native checks", async () => {
    vi.useFakeTimers();
    const native = harness(); await render(native); await click("Choose an encounter");
    await render(native); await act(async()=>native.emit({...first}));
    await act(async()=>vi.advanceTimersByTimeAsync(5_000));
    expect(container.textContent).toContain("Private invented label");
    expect(fetchMock).toHaveBeenCalledOnce();
    await click("Refresh encounters");
    expect(native.plugin.getToken).toHaveBeenCalledTimes(2);
  });
  it("closes on logout, rejects late tokens, and offers a safe retry after failure", async () => {
    const native = harness(); await render(native); await click("Choose an encounter");
    const late = deferred<unknown>(); native.plugin.getToken.mockReturnValueOnce(late.promise);
    await click("Refresh encounters"); const logout = deferred<void>(); native.plugin.signOut.mockReturnValueOnce(logout.promise);
    await click("Sign out"); expect(container.textContent).not.toContain("Private invented label");
    await act(async () => { native.emit(first); late.resolve({ token, revision: first.revision }); });
    expect(container.textContent).not.toContain("Choose an encounter"); expect(fetchMock).toHaveBeenCalledTimes(1);
    native.set(pending); await act(async () => logout.reject(new Error("secret provider detail")));
    expect(container.textContent).toContain("Retry sign-out"); expect(container.textContent).not.toContain("secret provider detail");
    await click("Retry sign-out"); expect(container.textContent).toContain("Sign in to Cosmas");
  });
  it("does not let an old state read undo a newer event", async () => {
    const native = harness(); const read = deferred<unknown>(); native.plugin.getState.mockReturnValueOnce(read.promise);
    await render(native); await act(async () => native.emit(pending));
    await act(async () => read.resolve(first)); expect(container.textContent).toContain("Retry sign-out");
    expect(container.textContent).not.toContain("Choose an encounter");
  });
  it("preserves private UI on an unchanged poll and closes it on malformed state", async () => {
    vi.useFakeTimers(); const native = harness(); await render(native); await click("Choose an encounter");
    await act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
    expect(container.textContent).toContain("Private invented label");
    await act(async () => native.emit({ ...first, identity: second.identity }));
    expect(container.textContent).not.toContain("Private invented label");
    expect(container.textContent).toContain("Secure session is unavailable");
  });
  it("ignores pending actions and tokens from a replaced adapter", async () => {
    const old = harness(); await render(old); const late = deferred<unknown>(); old.plugin.getToken.mockReturnValueOnce(late.promise);
    await click("Choose an encounter"); const logout = deferred<void>(); old.plugin.signOut.mockReturnValueOnce(logout.promise);
    await click("Sign out"); const fresh = harness(second); await render(fresh); await click("Choose an encounter");
    await act(async () => { logout.resolve(); late.resolve({ token, revision: first.revision }); old.emit(pending); });
    expect(fetchMock).toHaveBeenCalledTimes(1); expect(container.textContent).toContain("Private invented label");
    expect(fresh.plugin.getState).toHaveBeenCalledTimes(1); expect(old.listeners.size).toBe(0);
  });
  it("cleans up strict-mode subscriptions and denies tokens after unmount", async () => {
    const native = harness(); await act(async () => root.render(createElement(StrictMode, null,
      createElement(NativeAuthenticatedWorkspace, { plugin: native.plugin, available: true }))));
    expect(native.listeners.size).toBe(1); const late = deferred<unknown>(); native.plugin.getToken.mockReturnValueOnce(late.promise);
    await click("Choose an encounter"); await act(async () => root.render(null));
    await act(async () => late.resolve({ token, revision: first.revision }));
    expect(fetchMock).not.toHaveBeenCalled(); expect(native.listeners.size).toBe(0);
  });
  it.each([null, { token, revision: second.revision }, { token: "opaque-capture-grant", revision: first.revision }])(
    "never submits malformed or mismatched token replies", async reply => {
      const native = harness(); native.plugin.getToken.mockResolvedValue(reply); await render(native); await click("Choose an encounter");
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
