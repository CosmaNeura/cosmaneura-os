import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { webcrypto } from "node:crypto";
import { coalesceNativeWorkspaceAuth } from "./workspace-auth-requests";
import type { WorkspaceAuthPlugin } from "./workspace-auth-plugin";
import { parseNativeToken, type NativeAuthState } from "../../../../web/src/native-auth";
import { vendorApi } from "../../../../web/src/vendor-api";
import { financeApi } from "../../../../web/src/finance-api";
import { portalSetupApi } from "../../../../web/src/portal-setup-api";
import { portalWorkApi } from "../../../../web/src/portal-work-api";
import { actual as vendor } from "../../../../web/src/vendor-test-fixture";
import { actual as finance } from "../../../../web/src/finance-test-fixture";
import { portalFixture } from "../../../../web/src/portal-setup-test-fixture";
import portal from "../../../../web/src/__fixtures__/portal-work/actual-portal-work.json";

const revision = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const ready = (n = 1): NativeAuthState => ({ phase: "ready", revision: revision(n),
  identity: { userId: "user_one", sessionId: "sess_one", organizationId: "org_one" } });
const token = "invented.native.token";
function deferred<T>() {
  let resolve!: (value: T) => void, reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function provider() {
  let state = ready(), inFlight = 0, peak = 0;
  const held: ReturnType<typeof deferred<unknown>>[] = [], listeners = new Set<(value: unknown) => void>();
  const native = {
    getState: vi.fn(async () => structuredClone(state)),
    getToken: vi.fn(async (_options: { expectedRevision: string }) => {
      if (inFlight >= 8) throw Error("Native eight-task admission limit");
      inFlight++; peak = Math.max(peak, inFlight);
      const next = deferred<unknown>(); held.push(next);
      try { return await next.promise; } finally { inFlight--; }
    }),
    signIn: vi.fn(async () => undefined), signOut: vi.fn(async () => undefined),
    addListener: vi.fn(async (_event: "authStateChanged", listener: (value: unknown) => void) => {
      listeners.add(listener); return { remove: async () => { listeners.delete(listener); } };
    }),
  } satisfies WorkspaceAuthPlugin;
  const wrapper = coalesceNativeWorkspaceAuth(native);
  return { native, wrapper, held, peak: () => peak, inFlight: () => inFlight,
    emit(value: unknown) { state = value as NativeAuthState; for (const listener of listeners) listener(value); },
    async initialize() { await wrapper.addListener("authStateChanged", () => {}); await wrapper.getState(); },
  };
}
const settle = () => new Promise<void>(resolve => queueMicrotask(resolve));
const response = (value: unknown) => new Response(JSON.stringify(value), { headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });
beforeEach(() => { vi.stubGlobal("crypto", webcrypto); vi.stubGlobal("window", { location: { href: "capacitor://localhost/index.html" } });
  vi.stubEnv("VITE_API_BASE", "http://127.0.0.1:8046"); vi.stubEnv("VITE_WORKSPACE_APPLE_LOCAL_TRANSPORT_ENABLED", "true"); });
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); vi.useRealTimers(); });

describe("bounded concurrent native token acquisition", () => {
  it("reproduces the ten-call admission failure without coalescing", async () => {
    const p = provider(), results = Array.from({ length: 10 }, () => p.native.getToken({ expectedRevision: revision(1) }));
    const completed = Promise.allSettled(results); await settle();
    expect(p.held).toHaveLength(8); expect(p.peak()).toBe(8);
    p.held.forEach(value => value.resolve({ token, revision: revision(1) }));
    expect((await completed).filter(result => result.status === "rejected")).toHaveLength(2);
  });

  it("serves all ten same-revision requests from one native acquisition and reacquires sequentially", async () => {
    const p = provider(); await p.initialize();
    const requests = Array.from({ length: 10 }, () => p.wrapper.getToken({ expectedRevision: revision(1) }));
    await settle(); expect(p.native.getToken).toHaveBeenCalledTimes(1); expect(p.peak()).toBe(1);
    p.held[0].resolve({ token, revision: revision(1) });
    const values = await Promise.all(requests); expect(values).toHaveLength(10);
    values.forEach(value => expect(parseNativeToken(value, revision(1))).toBe(token));
    expect(values[0]).not.toBe(values[1]);
    const next = p.wrapper.getToken({ expectedRevision: revision(1) }); await settle();
    expect(p.native.getToken).toHaveBeenCalledTimes(2);
    p.held[1].resolve({ token: "another.native.token", revision: revision(1) });
    expect(parseNativeToken(await next, revision(1))).toBe("another.native.token");
  });

  it("integrates the C1 + finance + portal startup's three authority calls and seven actual read contracts", async () => {
    const p = provider(); await p.initialize();
    const identity = { mode: "clerk_jwt" as const, getToken: async () => parseNativeToken(await p.wrapper.getToken({ expectedRevision: revision(1) }), revision(1)) };
    const byPath = new Map<string, unknown>([
      [`/workspaces/${vendor.options.workspace_id}/vendor-work/options`, vendor.options],
      [`/workspaces/${vendor.options.workspace_id}/vendor-work`, vendor.catalog],
      [`/workspaces/${finance.options.workspace_id}/finance-work/options`, finance.options],
      [`/workspaces/${finance.options.workspace_id}/finance-work`, finance.catalog],
      ["/portal-setup", portalFixture.catalog_pending], [`/workspaces/${portal.workspace_id}/portal-work`, portal.catalog],
    ]);
    const fetcher = vi.fn(async (url: string | URL | Request) => {
      const path = new URL(String(url)).pathname;
      if (!byPath.has(path)) throw Error("Unexpected local read");
      return response(byPath.get(path));
    }); vi.stubGlobal("fetch", fetcher);
    const started = [identity.getToken(), vendorApi.options(identity, vendor.options.workspace_id), vendorApi.catalog(identity, vendor.options.workspace_id),
      identity.getToken(), financeApi.options(identity, finance.options.workspace_id), financeApi.catalog(identity, finance.options.workspace_id),
      identity.getToken(), vendorApi.options(identity, vendor.options.workspace_id), portalSetupApi.catalog(identity), portalWorkApi.catalog(identity, portal.workspace_id)];
    await settle(); await settle(); expect(p.native.getToken).toHaveBeenCalledTimes(1); expect(fetcher).not.toHaveBeenCalled();
    p.held[0].resolve({ token, revision: revision(1) });
    expect(await Promise.all(started)).toHaveLength(10); expect(fetcher).toHaveBeenCalledTimes(7); expect(p.peak()).toBe(1);
  });

  it.each(["revision", "user", "session", "organization", "revoked", "malformed"])("fences every old waiter on %s change", async kind => {
    const p = provider(); await p.initialize();
    const pending = Promise.allSettled(Array.from({ length: 10 }, () => p.wrapper.getToken({ expectedRevision: revision(1) })));
    await settle(); let next: unknown = ready(2);
    if (kind === "user" || kind === "session" || kind === "organization") {
      const changed = ready(); changed.identity![{ user: "userId", session: "sessionId", organization: "organizationId" }[kind] as "userId"] += "_other"; next = changed;
    }
    if (kind === "revoked") next = { phase: "signedOut", revision: revision(2), identity: null };
    if (kind === "malformed") next = { ...ready(), extra: "forbidden" };
    p.emit(next); expect((await pending).every(result => result.status === "rejected")).toBe(true);
    expect(p.inFlight()).toBe(1); p.held[0].resolve({ token, revision: revision(1) }); await settle(); await settle();
    await expect(p.wrapper.getToken({ expectedRevision: revision(1) })).rejects.toThrow("Native session unavailable");
  });

  it.each(["signIn", "signOut"] as const)("synchronously fences held tokens during explicit %s", async action => {
    const p = provider(); await p.initialize(); const mutation = deferred<undefined>(); p.native[action].mockReturnValueOnce(mutation.promise);
    const pending = Promise.allSettled(Array.from({ length: 10 }, () => p.wrapper.getToken({ expectedRevision: revision(1) })));
    await settle(); const command = p.wrapper[action]();
    expect((await pending).every(result => result.status === "rejected")).toBe(true);
    p.emit(ready(2)); await expect(p.wrapper.getToken({ expectedRevision: revision(2) })).rejects.toThrow();
    p.held[0].resolve({ token, revision: revision(1) }); mutation.resolve(undefined); await command;
    await p.wrapper.getState(); const fresh = p.wrapper.getToken({ expectedRevision: revision(2) }); await settle();
    p.held[1].resolve({ token, revision: revision(2) }); await expect(fresh).resolves.toEqual({ token, revision: revision(2) });
  });

  it("starts a distinct fresh acquisition for a valid new user/session while retaining the old native slot", async () => {
    const p = provider(); await p.initialize();
    const old = expect(p.wrapper.getToken({ expectedRevision: revision(1) })).rejects.toThrow(); await settle();
    const next = ready(2); next.identity = { userId: "user_two", sessionId: "sess_two", organizationId: "org_two" }; p.emit(next); await old;
    const fresh = p.wrapper.getToken({ expectedRevision: revision(2) }); await settle();
    expect(p.inFlight()).toBe(2); expect(p.native.getToken.mock.calls).toEqual([[{ expectedRevision: revision(1) }], [{ expectedRevision: revision(2) }]]);
    p.held[1].resolve({ token: "new.session.token", revision: revision(2) }); await expect(fresh).resolves.toEqual({ token: "new.session.token", revision: revision(2) });
    p.held[0].resolve({ token, revision: revision(1) }); await settle();
  });

  it("discards a revoked acquisition before its native dispatch microtask", async () => {
    const p = provider(); await p.initialize();
    const waiting = expect(p.wrapper.getToken({ expectedRevision: revision(1) })).rejects.toThrow();
    p.emit({ phase: "signedOut", revision: revision(2), identity: null }); await waiting;
    expect(p.native.getToken).not.toHaveBeenCalled();
  });

  it.each([{ token, revision: revision(2) }, { token, revision: revision(1), extra: true }, { token: "invalid", revision: revision(1) }])("rejects a corrupt native response for all waiters", async bad => {
    const p = provider(); await p.initialize(); const requests = Promise.allSettled(Array.from({ length: 10 }, () => p.wrapper.getToken({ expectedRevision: revision(1) })));
    await settle(); p.held[0].resolve(bad); expect((await requests).every(result => result.status === "rejected")).toBe(true);
    const fresh = p.wrapper.getToken({ expectedRevision: revision(1) }); await settle(); expect(p.native.getToken).toHaveBeenCalledTimes(2);
    p.held[1].resolve({ token, revision: revision(1) }); await fresh;
  });

  it("bounds waiters without admitting another native call", async () => {
    const p = provider(); await p.initialize();
    const accepted = Array.from({ length: 32 }, () => p.wrapper.getToken({ expectedRevision: revision(1) }));
    await expect(p.wrapper.getToken({ expectedRevision: revision(1) })).rejects.toThrow(); await settle();
    expect(p.native.getToken).toHaveBeenCalledTimes(1); p.held[0].resolve({ token, revision: revision(1) }); await Promise.all(accepted);
  });

  it("retains eight invalidated native slots and releases one only when that native call actually rejects", async () => {
    const p = provider(); await p.initialize();
    for (let index = 1; index <= 8; index++) {
      const request = p.wrapper.getToken({ expectedRevision: revision(index) }), rejected = expect(request).rejects.toThrow();
      await settle(); p.emit(ready(index + 1)); await rejected;
    }
    expect(p.native.getToken).toHaveBeenCalledTimes(8); expect(p.inFlight()).toBe(8);
    await expect(p.wrapper.getToken({ expectedRevision: revision(9) })).rejects.toThrow(); expect(p.native.getToken).toHaveBeenCalledTimes(8);
    p.held[0].reject(Error("Late native rejection")); await settle(); await settle(); await settle();
    const next = p.wrapper.getToken({ expectedRevision: revision(9) }); await settle(); expect(p.native.getToken).toHaveBeenCalledTimes(9); expect(p.peak()).toBe(8);
    p.held[8].resolve({ token, revision: revision(9) }); await next;
    p.held.slice(1, 8).forEach(item => item.reject(Error("Release retained test provider"))); await settle();
  });

  it("keeps each API deadline and cancellation independent while all abandoned waiters remain bounded", async () => {
    vi.useFakeTimers(); const p = provider(); await p.initialize();
    const identity = { mode: "clerk_jwt" as const, getToken: async () => parseNativeToken(await p.wrapper.getToken({ expectedRevision: revision(1) }), revision(1)) };
    const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
    const cancelled = new AbortController();
    const fast = expect(vendorApi.options(identity, vendor.options.workspace_id, cancelled.signal)).rejects.toMatchObject({ status: 503 });
    const short = expect(portalSetupApi.catalog(identity)).rejects.toMatchObject({ status: 503 });
    const longer = expect(financeApi.options(identity, finance.options.workspace_id)).rejects.toMatchObject({ status: 503 });
    await settle(); cancelled.abort(); await fast; expect(p.inFlight()).toBe(1);
    await vi.advanceTimersByTimeAsync(15000); await short; expect(p.inFlight()).toBe(1);
    await vi.advanceTimersByTimeAsync(15000); await longer; expect(p.native.getToken).toHaveBeenCalledTimes(1); expect(fetcher).not.toHaveBeenCalled();
    // Abandonment does not open new native capacity or create automatic retries.
    const retained = Array.from({ length: 29 }, () => p.wrapper.getToken({ expectedRevision: revision(1) }));
    await expect(p.wrapper.getToken({ expectedRevision: revision(1) })).rejects.toThrow();
    p.held[0].resolve({ token, revision: revision(1) }); await Promise.all(retained); await vi.advanceTimersByTimeAsync(1);
    expect(fetcher).not.toHaveBeenCalled(); expect(p.native.getToken).toHaveBeenCalledTimes(1);
  });

  it("lets a still-current caller complete after another caller cancels", async () => {
    const p = provider(); await p.initialize(); const abort = new AbortController();
    const identity = { mode: "clerk_jwt" as const, getToken: async () => parseNativeToken(await p.wrapper.getToken({ expectedRevision: revision(1) }), revision(1)) };
    const fetcher = vi.fn(async () => response(vendor.options)); vi.stubGlobal("fetch", fetcher);
    const stopped = expect(vendorApi.options(identity, vendor.options.workspace_id, abort.signal)).rejects.toMatchObject({ status: 503 });
    const continuing = vendorApi.options(identity, vendor.options.workspace_id); await settle(); abort.abort(); await stopped;
    p.held[0].resolve({ token, revision: revision(1) }); await continuing;
    expect(p.native.getToken).toHaveBeenCalledTimes(1); expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("accepts identical concurrent state reads but rejects stale reads and malformed options", async () => {
    const p = provider(); const values = await Promise.all([p.wrapper.getState(), p.wrapper.getState()]); expect(values).toEqual([ready(), ready()]);
    await p.wrapper.addListener("authStateChanged", () => {}); const stale = deferred<NativeAuthState>(); p.native.getState.mockReturnValueOnce(stale.promise);
    const read = expect(p.wrapper.getState()).rejects.toThrow(); p.emit(ready(2)); stale.resolve(ready()); await read;
    await expect(p.wrapper.getToken({ expectedRevision: revision(2), extra: true } as { expectedRevision: string })).rejects.toThrow();
    await expect(p.wrapper.getToken(Object.assign([], { expectedRevision: revision(2) }))).rejects.toThrow();
    await expect(p.wrapper.getToken({ expectedRevision: revision(1) })).rejects.toThrow(); expect(p.native.getToken).not.toHaveBeenCalled();
  });
});
