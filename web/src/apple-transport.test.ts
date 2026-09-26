import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { workspaceApi } from "./workspace-api";
import { prepareCapture } from "./capture-api";

const workspace = "00000000-0000-4000-8000-000000000001";
const session = "00000000-0000-4000-8000-000000000002";
const consent = "00000000-0000-4000-8000-000000000003";
const json = (body: unknown) => new Response(JSON.stringify(body), {
  headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
});

describe("Apple signed workspace and capture clients", () => {
  beforeEach(() => {
    vi.stubEnv("VITE_API_BASE", "http://127.0.0.1:8035");
    vi.stubEnv("VITE_WORKSPACE_APPLE_LOCAL_TRANSPORT_ENABLED", "true");
    vi.stubGlobal("window", { location: { href: "capacitor://localhost/index.html" } });
  });
  afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

  it("uses a fresh token directly for each call without synthetic identity, cookies or referrers", async () => {
    const access = { mode: "clerk_jwt" as const, getToken: vi.fn()
      .mockResolvedValueOnce("first-token").mockResolvedValueOnce("second-token") };
    const fetchMock = vi.fn().mockResolvedValueOnce(json([])).mockResolvedValueOnce(json({
      status: "prepared", workspace_id: workspace, session_id: session, consent_record_id: consent,
    }));
    vi.stubGlobal("fetch", fetchMock);
    await workspaceApi.catalog(access);
    await prepareCapture(workspace, access, null, "same-admission-key");
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "http://127.0.0.1:8035/workspaces", `http://127.0.0.1:8035/workspaces/${workspace}/capture/admission`,
    ]);
    fetchMock.mock.calls.forEach(([, options], index) => {
      expect(options).toMatchObject({ credentials: "omit", cache: "no-store", redirect: "error", referrerPolicy: "no-referrer" });
      const headers = new Headers(options.headers);
      expect(headers.get("Authorization")).toBe(`Bearer ${index ? "second" : "first"}-token`);
      expect(headers.has("X-Box-Id")).toBe(false);
      expect(headers.has("X-Actor-Principal-Id")).toBe(false);
    });
    expect(access.getToken.mock.calls).toEqual([[{skipCache: true}], [{skipCache: true}]]);
  });

  it.each(["gate-off", "desktop-proxy", "foreign-shell", "foreign-api"])("rejects %s before token acquisition", async fault => {
    if (fault === "gate-off") vi.stubEnv("VITE_WORKSPACE_APPLE_LOCAL_TRANSPORT_ENABLED", "false");
    if (fault === "desktop-proxy") {
      vi.stubEnv("VITE_API_BASE", "app://cosmas/api");
      vi.stubEnv("VITE_DESKTOP_SYNTHETIC_ENABLED", "true");
      vi.stubGlobal("window", { location: { href: "app://cosmas/index.html" } });
    }
    if (fault === "foreign-shell") vi.stubGlobal("window", { location: { href: "capacitor://other/index.html" } });
    if (fault === "foreign-api") vi.stubEnv("VITE_API_BASE", "https://outside.invalid");
    const access = { mode: "clerk_jwt" as const, getToken: vi.fn() };
    const fetchMock = vi.fn(); vi.stubGlobal("fetch", fetchMock);
    await expect(workspaceApi.catalog(access)).rejects.toThrow();
    await expect(prepareCapture(workspace, access, null, "same-key")).rejects.toMatchObject({status: 401});
    expect(access.getToken).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
