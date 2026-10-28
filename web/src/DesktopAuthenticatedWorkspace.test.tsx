import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DesktopAuthenticatedWorkspace } from "./DesktopAuthenticatedWorkspace";
import { workspaceAuthHeaders } from "./workspace-auth-headers";
import { request as captureRequest } from "./capture-api";
import {teamFixture} from "./team-setup-test-fixture";
import type { NativeAuthState } from "./native-auth";

const id = "00000000-0000-4000-8000-000000000001";
const ready: NativeAuthState = { phase: "ready", revision: id,
  identity: { userId: "user_one", sessionId: "sess_one", organizationId: "org_one" } };
const signedOut: NativeAuthState = { phase: "signedOut", revision: "00000000-0000-4000-8000-000000000002", identity: null };
function fixture(initial = signedOut) {
  let current = initial;
  const listeners = new Set<(value: unknown) => void>();
  const port = { version: 1 as const, getState: vi.fn(async () => current),
    signIn: vi.fn(async () => { current = ready; return current; }),
    signOut: vi.fn(async () => { current = signedOut; return current; }),
    onStateChanged: (listener: (value: unknown) => void) => { listeners.add(listener); return () => { listeners.delete(listener); }; },
  };
  return { port, emit: (state: NativeAuthState) => { current = state; for (const listener of listeners) listener(state); } };
}
function enableDesktop() {
  for (const name of ["VITE_WORKSPACE_DESKTOP_AUTH_ENABLED", "VITE_DESKTOP_SYNTHETIC_ENABLED", "VITE_WORKSPACE_AUTHENTICATED_ENABLED", "VITE_WORKSPACE_ENABLED"]) vi.stubEnv(name, "true");
  vi.stubEnv("VITE_COSMAS_ENV", "synth_os"); vi.stubEnv("VITE_API_BASE", "app://cosmas/api");
}

describe("desktop native workspace", () => {
  let root: Root, container: HTMLDivElement;
  const originalWindow = window;
  beforeEach(() => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true }); enableDesktop();
    container = document.createElement("div"); document.body.append(container); root = createRoot(container);
    vi.stubGlobal("window", { location: { href: "app://cosmas/index.html" },
      addEventListener: originalWindow.addEventListener.bind(originalWindow), removeEventListener: originalWindow.removeEventListener.bind(originalWindow),
      setInterval: originalWindow.setInterval.bind(originalWindow), clearInterval: originalWindow.clearInterval.bind(originalWindow) });
  });
  afterEach(async () => {
    await act(async () => root.unmount()); container.remove(); vi.unstubAllGlobals(); vi.unstubAllEnvs(); vi.restoreAllMocks();
  });
  async function click(label: string) {
    const button = [...container.querySelectorAll("button")].find(value => value.textContent?.startsWith(label));
    expect(button).toBeDefined(); await act(async () => button!.click());
  }
  it("uses only the native state/session handle for workspace requests and clears labels on logout", async () => {
    const native = fixture(); window.cosmasDesktopAuth = native.port;
    const fetchMock = vi.fn<typeof fetch>().mockImplementation(async url => Response.json(String(url).endsWith("/provider-team")?teamFixture():[
      { appointment_id: "invented", workspace_id: null, label: "Private desktop encounter" },
    ])); vi.stubGlobal("fetch", fetchMock);
    await act(async () => root.render(createElement(DesktopAuthenticatedWorkspace)));
    expect(fetchMock).not.toHaveBeenCalled(); await click("Sign in"); await click("Visits and notes");
    expect(container.textContent).toContain("Private desktop encounter");
    const catalogCall=fetchMock.mock.calls.find(([url])=>url==="app://cosmas/api/workspaces")!;
    const headers = new Headers(catalogCall[1]?.headers);
    expect(headers.get("X-Cosmas-Desktop-Session")).toBe(id);
    expect(headers.has("Authorization")).toBe(false); expect(headers.has("X-Box-Id")).toBe(false);
    expect(catalogCall[0]).toBe("app://cosmas/api/workspaces");
    await click("Log out"); expect(container.textContent).not.toContain("Private desktop encounter");
    expect(container.textContent).toContain("Sign in to CosmaBot");
  });
  it("discards a private response received after account change", async () => {
    const native = fixture(ready); window.cosmasDesktopAuth = native.port;
    let release!: (response: Response) => void;
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(resolve => { release = resolve; })));
    await act(async () => root.render(createElement(DesktopAuthenticatedWorkspace))); await click("Visits and notes");
    await act(async () => native.emit(signedOut));
    await act(async () => release(Response.json([{ appointment_id: "invented", workspace_id: null, label: "Old private label" }])));
    expect(container.textContent).not.toContain("Old private label"); expect(container.textContent).toContain("Sign in to CosmaBot");
  });
  it("requires the narrow preload API and does not accept a credential-bearing port", async () => {
    const fetchMock = vi.fn<typeof fetch>(); vi.stubGlobal("fetch", fetchMock);
    await act(async () => root.render(createElement(DesktopAuthenticatedWorkspace)));
    expect(container.textContent).toContain("Sign-in isn't available");
    window.cosmasDesktopAuth = { ...fixture().port, getToken: () => "forged" } as typeof window.cosmasDesktopAuth;
    await act(async () => root.render(createElement(DesktopAuthenticatedWorkspace)));
    expect(container.textContent).toContain("Sign-in isn't available"); expect(fetchMock).not.toHaveBeenCalled();
  });
  it("carries capture operations through the same revision-only transport", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(Response.json({ ok: true }, { headers: { "Cache-Control": "no-store" } }));
    vi.stubGlobal("fetch", fetchMock);
    await captureRequest(id, "operations", { mode: "desktop_native", revision: id, isCurrent: () => true }, { operation: { kind: "capture_status" } });
    const headers = new Headers(fetchMock.mock.calls[0][1]?.headers);
    expect(headers.get("X-Cosmas-Desktop-Session")).toBe(id); expect(headers.has("Authorization")).toBe(false);
  });
  it.each(["VITE_WORKSPACE_DESKTOP_AUTH_ENABLED", "VITE_DESKTOP_SYNTHETIC_ENABLED", "VITE_WORKSPACE_AUTHENTICATED_ENABLED", "VITE_WORKSPACE_ENABLED"])(
    "rejects direct desktop calls when %s is disabled", async flag => {
      vi.stubEnv(flag, "false");
      await expect(workspaceAuthHeaders({ mode: "desktop_native", revision: id, isCurrent: () => true }, "app://cosmas/api")).rejects.toThrow();
    });
  it("rejects stale state or a remote destination before any transport", async () => {
    await expect(workspaceAuthHeaders({ mode: "desktop_native", revision: id, isCurrent: () => false }, "app://cosmas/api")).rejects.toThrow();
    await expect(workspaceAuthHeaders({ mode: "desktop_native", revision: id, isCurrent: () => true }, "https://outside.invalid")).rejects.toThrow();
  });
});
