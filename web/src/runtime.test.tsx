import { StrictMode, act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const clerkHarness = vi.hoisted(() => ({
  auth: {
    isLoaded: false,
    isSignedIn: false as boolean | undefined,
    orgId: null as string | null | undefined,
    getToken: vi.fn(),
  },
  providerKeys: [] as string[],
  providerError: null as Error | null,
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
    clerkHarness.providerError = null;
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.unstubAllGlobals();
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
    expect(container.textContent).toContain("Beta login is unavailable");
    expect(container.textContent).not.toContain("sensitive provider failure");
  });
});
