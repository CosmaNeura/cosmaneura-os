import { StrictMode, act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import {teamFixture} from "./team-setup-test-fixture";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const clerkHarness = vi.hoisted(() => ({
  nativeMounts: 0,
  desktopMounts: 0,
  auth: {
    isLoaded: false,
    isSignedIn: false as boolean | undefined,
    orgId: null as string | null | undefined,
    getToken: vi.fn(),
  } as {
    isLoaded: boolean; isSignedIn: boolean | undefined; orgId: string | null | undefined;
    userId?: string; sessionId?: string; getToken: ReturnType<typeof vi.fn>;
  },
  providerKeys: [] as string[],
  providerError: null as Error | null,
}));

vi.mock("./NativeAuthenticatedWorkspace", () => ({
  NativeAuthenticatedWorkspace: () => { clerkHarness.nativeMounts++; return "Native workspace entry"; },
}));
vi.mock("./DesktopAuthenticatedWorkspace", () => ({
  DesktopAuthenticatedWorkspace: () => { clerkHarness.desktopMounts++; return "Desktop workspace entry"; },
}));

vi.mock("@clerk/react", () => ({
  ClerkProvider: ({
    children,
    publishableKey,
  }: {
    children: unknown;
    publishableKey: string;
  }) => {
    clerkHarness.providerKeys.push(publishableKey);
    if (clerkHarness.providerError) throw clerkHarness.providerError;
    return children;
  },
  OrganizationSwitcher: () => "Organization switcher",
  SignIn: () => "Clerk sign in",
  UserButton: () => "User menu",
  useAuth: () => clerkHarness.auth,
}));

import { type QueueItem } from "./api";
import { ClerkBetaApp } from "./App";
import { RuntimeApp, resolveBetaFrontendConfiguration } from "./runtime";

const pendingTicket: QueueItem = {
  id: "00000000-0000-4000-8000-000000000004",
  lane: "artifact_chase",
  state: "pending_approval",
  proposed_message: "Please share the invented insurance card images.",
  revision_id: "00000000-0000-4000-8000-000000000005",
  patient_link_id: "00000000-0000-4000-8000-000000000006",
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

async function settle(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

function requestHeaders(fetchMock: ReturnType<typeof vi.fn<typeof fetch>>, index: number): Headers {
  return new Headers(fetchMock.mock.calls[index]?.[1]?.headers);
}

function betaApp() {
  return createElement(RuntimeApp, {
    runtimeMode: "early_adopter_beta",
    clerkPublishableKey: "pk_test_offline_example",
    apiBase: "https://api.example.invalid",
  });
}

describe("beta runtime", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    clerkHarness.auth = {
      isLoaded: false,
      isSignedIn: false,
      orgId: null,
      getToken: vi.fn(),
    };
    clerkHarness.providerKeys = [];
    clerkHarness.nativeMounts = 0;
    clerkHarness.desktopMounts = 0;
    clerkHarness.providerError = null;
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  it.each([
    [undefined, "https://api.example.invalid"],
    ["", "https://api.example.invalid"],
    ["not-a-publishable-key", "https://api.example.invalid"],
    ["pk_test_offline_example", undefined],
    ["pk_test_offline_example", "http://api.example.invalid"],
  ])("fails closed for incomplete beta configuration", async (key, apiBase) => {
    const fetchMock = vi.fn<typeof fetch>();
    vi.stubGlobal("fetch", fetchMock);

    await act(async () => {
      root.render(
        createElement(RuntimeApp, {
          runtimeMode: "early_adopter_beta",
          clerkPublishableKey: key,
          apiBase,
        }),
      );
    });
    await settle();

    expect(fetchMock).not.toHaveBeenCalled();
    expect(clerkHarness.providerKeys).toHaveLength(0);
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      "Beta login is not configured",
    );
  });

  it("accepts only a non-empty Clerk key and HTTPS API URL", () => {
    expect(
      resolveBetaFrontendConfiguration(
        " pk_live_offline_example ",
        "https://api.example.invalid/v1",
      ),
    ).toEqual({ configured: true, publishableKey: "pk_live_offline_example" });
    expect(
      resolveBetaFrontendConfiguration(
        "pk_live_offline_example",
        "https://user:password@api.example.invalid",
      ),
    ).toEqual({ configured: false, reason: "invalid_api_base" });
  });

  it.each([
    [false, false, null, "Checking your session"],
    [true, false, null, "Clerk sign in"],
    [true, true, null, "Choose an organization"],
    [true, true, "personal", "Choose an organization"],
  ])(
    "does not call the API while Clerk or organization state is incomplete",
    async (isLoaded, isSignedIn, orgId, expectedCopy) => {
      const fetchMock = vi.fn<typeof fetch>();
      vi.stubGlobal("fetch", fetchMock);
      clerkHarness.auth = {
        isLoaded,
        isSignedIn,
        orgId,
        getToken: vi.fn(),
      };

      await act(async () => root.render(betaApp()));
      await settle();

      expect(fetchMock).not.toHaveBeenCalled();
      expect(clerkHarness.auth.getToken).not.toHaveBeenCalled();
      expect(container.textContent).toContain(expectedCopy);
    },
  );

  it("offers an account switch when the signed-in user has no organization", async () => {
    const fetchMock = vi.fn<typeof fetch>(); vi.stubGlobal("fetch", fetchMock);
    clerkHarness.auth.isLoaded = true; clerkHarness.auth.isSignedIn = true;
    await act(async () => root.render(betaApp()));
    const controls = container.querySelector('[aria-label="Account and organization"]');
    expect(controls?.textContent).toContain("Organization switcher");
    expect(controls?.textContent).toContain("User menu");
    expect(container.textContent).toContain("accept your invitation");
    expect(clerkHarness.auth.getToken).not.toHaveBeenCalled(); expect(fetchMock).not.toHaveBeenCalled();
    clerkHarness.auth.isSignedIn = false; await act(async () => root.render(betaApp()));
    expect(container.textContent).toContain("Clerk sign in");
    expect(container.textContent).not.toContain("Organization switcher");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each(["token getter", "user", "session"])("offers account recovery when the %s is missing", async missing => {
    const fetchMock = vi.fn<typeof fetch>(); vi.stubGlobal("fetch", fetchMock);
    clerkHarness.auth = { isLoaded: true, isSignedIn: true, orgId: "org_offlineBetaLab",
      userId: "user_test", sessionId: "sess_test", getToken: vi.fn() };
    if (missing === "token getter") Object.assign(clerkHarness.auth, { getToken: undefined });
    if (missing === "user") delete clerkHarness.auth.userId;
    if (missing === "session") delete clerkHarness.auth.sessionId;
    await act(async () => root.render(createElement(ClerkBetaApp, { workspace: true })));
    expect(container.textContent).toContain("Secure session unavailable");
    expect(container.querySelector('[aria-label="Account and organization"]')?.textContent).toContain("User menu");
    expect(fetchMock).not.toHaveBeenCalled();
    if (clerkHarness.auth.getToken) expect(clerkHarness.auth.getToken).not.toHaveBeenCalled();
  });

  it("gets a new uncached token for the initial queue, action, and refresh", async () => {
    const sentTicket = { ...pendingTicket, state: "sent" };
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse([pendingTicket]))
      .mockResolvedValueOnce(jsonResponse({ decision: "approved", operation_id: "op-test" }))
      .mockResolvedValueOnce(jsonResponse([sentTicket]));
    vi.stubGlobal("fetch", fetchMock);
    const getToken = vi
      .fn()
      .mockResolvedValueOnce("beta-token-one")
      .mockResolvedValueOnce("beta-token-two")
      .mockResolvedValueOnce("beta-token-three");
    clerkHarness.auth = {
      isLoaded: true,
      isSignedIn: true,
      orgId: "org_offlineBetaLab",
      getToken,
    };

    await act(async () => root.render(createElement(StrictMode, null, betaApp())));
    await settle();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[0]).toBe("http://localhost:8000/queue");
    expect(container.textContent).toContain("Cosmas Beta Lab");

    const approve = [...container.querySelectorAll("button")].find(
      (button) => button.textContent === "Approve",
    );
    await act(async () => approve?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    await settle();

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(getToken).toHaveBeenCalledTimes(3);
    for (const call of getToken.mock.calls) expect(call).toEqual([{ skipCache: true }]);
    expect(fetchMock.mock.calls.map((call) => String(call[0]))).not.toContain(
      "http://localhost:8000/synth/demo-queue",
    );
    for (const [index, token] of [
      "beta-token-one",
      "beta-token-two",
      "beta-token-three",
    ].entries()) {
      const headers = requestHeaders(fetchMock, index);
      expect(headers.get("Authorization")).toBe(`Bearer ${token}`);
      expect(headers.has("X-Box-Id")).toBe(false);
      expect(headers.has("X-Actor-Principal-Id")).toBe(false);
      expect(fetchMock.mock.calls[index]?.[1]?.credentials).toBe("omit");
    }
  });

  it.each([
    [vi.fn().mockResolvedValue(null), ""],
    [vi.fn().mockRejectedValue(new Error("sensitive Clerk detail")), "sensitive Clerk detail"],
  ])("does not call the API when token acquisition fails", async (getToken, hiddenDetail) => {
    const fetchMock = vi.fn<typeof fetch>();
    vi.stubGlobal("fetch", fetchMock);
    clerkHarness.auth = {
      isLoaded: true,
      isSignedIn: true,
      orgId: "org_offlineBetaLab",
      getToken,
    };

    await act(async () => root.render(betaApp()));
    await settle();

    expect(fetchMock).not.toHaveBeenCalled();
    expect(container.querySelector('[role="alert"]')?.textContent).toBe(
      "Secure session is unavailable. Sign in again.",
    );
    if (hiddenDetail) expect(container.textContent).not.toContain(hiddenDetail);
  });

  it("restarts with a fresh token after the active organization changes", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(jsonResponse([]));
    vi.stubGlobal("fetch", fetchMock);
    const getToken = vi
      .fn()
      .mockResolvedValueOnce("first-org-token")
      .mockResolvedValueOnce("second-org-token");
    clerkHarness.auth = {
      isLoaded: true,
      isSignedIn: true,
      orgId: "org_first",
      getToken,
    };

    await act(async () => root.render(betaApp()));
    await settle();
    clerkHarness.auth = { ...clerkHarness.auth, orgId: "org_second" };
    await act(async () => root.render(betaApp()));
    await settle();

    expect(getToken).toHaveBeenCalledTimes(2);
    expect(requestHeaders(fetchMock, 0).get("Authorization")).toBe("Bearer first-org-token");
    expect(requestHeaders(fetchMock, 1).get("Authorization")).toBe("Bearer second-org-token");
  });

  it("renders a safe fallback if Clerk initialization throws", async () => {
    const fetchMock = vi.fn<typeof fetch>();
    vi.stubGlobal("fetch", fetchMock);
    clerkHarness.providerError = new Error("sensitive provider failure");
    vi.spyOn(console, "error").mockImplementation(() => undefined);

    await act(async () => root.render(betaApp()));

    expect(fetchMock).not.toHaveBeenCalled();
    expect(container.textContent).toContain("Your workspace could not continue");
    expect(container.textContent).toContain("unconfirmed requests before retrying");
    expect(container.textContent).not.toContain("No work has been loaded");
    expect(container.textContent).not.toContain("sensitive provider failure");
  });

  function workspaceApp() {
    return createElement(RuntimeApp, {
      runtimeMode: "synth_os", authenticatedWorkspace: true, workspaceEnabled: true,
      clerkPublishableKey: "pk_test_offline_example", apiBase: "http://127.0.0.1:8018",
    });
  }

  it("does not mistake the Apple transport flag for a qualified native login provider", async () => {
    vi.stubEnv("VITE_WORKSPACE_APPLE_LOCAL_TRANSPORT_ENABLED", "true");
    vi.stubGlobal("window", {location: {href: "capacitor://localhost/index.html"}});
    const fetchMock = vi.fn<typeof fetch>(); vi.stubGlobal("fetch", fetchMock);
    await act(async () => root.render(workspaceApp()));
    expect(container.textContent).toContain("Workspace login is not configured");
    expect(clerkHarness.providerKeys).toHaveLength(0);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("selects native authentication only in its explicit signed Apple profile", async () => {
    vi.stubEnv("VITE_WORKSPACE_NATIVE_AUTH_ENABLED", "true");
    vi.stubEnv("VITE_WORKSPACE_APPLE_LOCAL_TRANSPORT_ENABLED", "true");
    vi.stubGlobal("window", { location: { href: "capacitor://localhost/index.html" } });
    const fetchMock = vi.fn<typeof fetch>(); vi.stubGlobal("fetch", fetchMock);
    await act(async () => root.render(workspaceApp()));
    expect(container.textContent).toContain("Native workspace entry");
    expect(clerkHarness.nativeMounts).toBe(1);
    expect(clerkHarness.providerKeys).toHaveLength(0); expect(fetchMock).not.toHaveBeenCalled();
  });

  it("selects the desktop native entry without initializing browser Clerk", async () => {
    vi.stubEnv("VITE_WORKSPACE_DESKTOP_AUTH_ENABLED", "true");
    vi.stubEnv("VITE_DESKTOP_SYNTHETIC_ENABLED", "true");
    vi.stubGlobal("window", { location: { href: "app://cosmas/index.html" } });
    await act(async () => root.render(createElement(RuntimeApp, {
      runtimeMode: "synth_os", authenticatedWorkspace: true, workspaceEnabled: true, apiBase: "app://cosmas/api",
    })));
    expect(container.textContent).toContain("Desktop workspace entry");
    expect(clerkHarness.providerKeys).toHaveLength(0); expect(clerkHarness.nativeMounts).toBe(0);
  });

  it.each([
    { page: "http://localhost:5173/" }, { page: "app://other/index.html" },
    { page: "app://cosmas/index.html?redirect=true" }, { apiBase: "http://127.0.0.1:8046" },
    { desktop: "false" }, { apple: "true" }, { authenticatedWorkspace: false }, { workspaceEnabled: false },
  ])("rejects mixed or incomplete desktop native profiles: %j", async override => {
    vi.stubEnv("VITE_WORKSPACE_DESKTOP_AUTH_ENABLED", "true");
    vi.stubEnv("VITE_DESKTOP_SYNTHETIC_ENABLED", override.desktop ?? "true");
    vi.stubEnv("VITE_WORKSPACE_NATIVE_AUTH_ENABLED", override.apple ?? "false");
    vi.stubGlobal("window", { location: { href: override.page ?? "app://cosmas/index.html" } });
    await act(async () => root.render(createElement(RuntimeApp, {
      runtimeMode: "synth_os", authenticatedWorkspace: override.authenticatedWorkspace ?? true,
      workspaceEnabled: override.workspaceEnabled ?? true, apiBase: override.apiBase ?? "app://cosmas/api",
    })));
    expect(container.textContent).toContain("Workspace login is not configured");
    expect(clerkHarness.desktopMounts).toBe(0); expect(clerkHarness.nativeMounts).toBe(0);
    expect(clerkHarness.providerKeys).toHaveLength(0);
  });

  it.each([
    { page: "http://localhost:5173/" }, { page: "capacitor://other/index.html" },
    { page: "capacitor://localhost:80/index.html" }, { page: "capacitor://user@localhost/index.html" },
    { transport: "false" }, { desktop: "true" }, { authenticatedWorkspace: false },
    { workspaceEnabled: false }, { runtimeMode: "early_adopter_beta" as const },
    { apiBase: "https://unqualified.invalid" },
  ])("fails closed for mismatched native configuration: %j", async override => {
    vi.stubEnv("VITE_WORKSPACE_NATIVE_AUTH_ENABLED", "true");
    vi.stubEnv("VITE_WORKSPACE_APPLE_LOCAL_TRANSPORT_ENABLED", override.transport ?? "true");
    vi.stubEnv("VITE_DESKTOP_SYNTHETIC_ENABLED", override.desktop ?? "false");
    vi.stubGlobal("window", { location: { href: override.page ?? "capacitor://localhost/index.html" } });
    const fetchMock = vi.fn<typeof fetch>(); vi.stubGlobal("fetch", fetchMock);
    await act(async () => root.render(createElement(RuntimeApp, {
      runtimeMode: override.runtimeMode ?? "synth_os", authenticatedWorkspace: override.authenticatedWorkspace ?? true,
      workspaceEnabled: override.workspaceEnabled ?? true, apiBase: override.apiBase ?? "http://127.0.0.1:8018",
    })));
    expect(container.textContent).toContain("Workspace login is not configured");
    expect(clerkHarness.nativeMounts).toBe(0); expect(clerkHarness.providerKeys).toHaveLength(0);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each(["https://unqualified.invalid", "app://cosmas/api", "http://user@localhost:8018"])(
    "rejects unqualified authenticated workspace origins before initializing Clerk", async apiBase => {
      const fetchMock = vi.fn<typeof fetch>(); vi.stubGlobal("fetch", fetchMock);
      await act(async () => root.render(createElement(RuntimeApp, {
        runtimeMode: "synth_os", authenticatedWorkspace: true, workspaceEnabled: true,
        clerkPublishableKey: "pk_test_offline_example", apiBase,
      })));
      expect(clerkHarness.providerKeys).toHaveLength(0);
      expect(fetchMock).not.toHaveBeenCalled();
      expect(container.textContent).toContain("Workspace login is not configured");
    },
  );

  it("opens Home after sign-in, selects visits explicitly and clears private labels on sign-out", async () => {
    vi.stubEnv("VITE_API_BASE", "http://127.0.0.1:8018");
    const fetchMock = vi.fn<typeof fetch>().mockImplementation(async url=>jsonResponse(String(url).endsWith("/provider-team")?teamFixture():[
      { appointment_id: "invented-appointment", workspace_id: null, label: "Private invented label" },
    ]));
    vi.stubGlobal("fetch", fetchMock);
    clerkHarness.auth = { isLoaded: true, isSignedIn: true, orgId: "org_invented",
      userId: "user_invented", sessionId: "session_invented", getToken: vi.fn().mockResolvedValue("fresh-token") };
    await act(async () => root.render(workspaceApp()));
    expect(fetchMock.mock.calls.map(([url])=>url)).toEqual(["http://127.0.0.1:8018/provider-team"]);
    const choose = [...container.querySelectorAll("button")].find(button => button.textContent?.startsWith("Visits and notes"));
    await act(async () => choose!.click());
    expect(container.textContent).toContain("Private invented label");
    expect(fetchMock.mock.calls[1][0]).toBe("http://127.0.0.1:8018/workspaces");
    expect(requestHeaders(fetchMock, 1).get("Authorization")).toBe("Bearer fresh-token");
    clerkHarness.auth = { ...clerkHarness.auth, getToken: vi.fn().mockResolvedValue("refreshed-token") };
    await act(async () => root.render(workspaceApp()));
    expect(container.textContent).toContain("Private invented label");
    const refresh = [...container.querySelectorAll("button")].find(button => button.textContent?.startsWith("Visits and notes"));
    await act(async () => refresh!.click());
    expect(requestHeaders(fetchMock, 2).get("Authorization")).toBe("Bearer refreshed-token");
    clerkHarness.auth = { ...clerkHarness.auth, isSignedIn: false };
    await act(async () => root.render(workspaceApp()));
    expect(container.textContent).not.toContain("Private invented label");
    expect(container.textContent).toContain("Clerk sign in");
  });

  it("does not fall back to demo seeding when authenticated mode is missing its workspace flag", async () => {
    const fetchMock = vi.fn<typeof fetch>(); vi.stubGlobal("fetch", fetchMock);
    await act(async () => root.render(createElement(RuntimeApp, {
      runtimeMode: "synth_os", authenticatedWorkspace: true, workspaceEnabled: false,
      clerkPublishableKey: "pk_test_offline_example", apiBase: "http://127.0.0.1:8018",
    })));
    expect(fetchMock).not.toHaveBeenCalled();
    expect(clerkHarness.providerKeys).toHaveLength(0);
    expect(container.textContent).toContain("Workspace login is not configured");
  });

  it.each(["orgId", "userId", "sessionId"] as const)("discards a pending token when %s changes", async field => {
    let resolveToken!: (value: string) => void;
    const getToken = vi.fn().mockImplementation(() => new Promise<string>(resolve => { resolveToken = resolve; }));
    const fetchMock = vi.fn<typeof fetch>(); vi.stubGlobal("fetch", fetchMock);
    clerkHarness.auth = { isLoaded: true, isSignedIn: true, orgId: "org_invented",
      userId: "user_invented", sessionId: "session_invented", getToken };
    await act(async () => root.render(workspaceApp()));
    const choose = [...container.querySelectorAll("button")].find(button => button.textContent?.startsWith("Visits and notes"));
    await act(async () => choose!.click());
    expect(getToken).toHaveBeenCalledTimes(2);
    const resolveOldToken=resolveToken;
    clerkHarness.auth = { ...clerkHarness.auth, [field]: `${field === "orgId" ? "org" : field}_changed` };
    await act(async () => root.render(workspaceApp()));
    await act(async () => resolveOldToken("obsolete-token"));
    expect(fetchMock).not.toHaveBeenCalled();
    expect(container.textContent).toContain("Choose an encounter");
    expect(container.textContent).not.toContain("Workspace access is unavailable");
  });
});
