import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BetaIdentityAdmin } from "./BetaIdentityAdmin";

const owner = {
  clerk_subject: "user_test_owner",
  display_name: "Taylor Owner",
  active: true,
  principal_state: "active",
  is_owner: true,
};

const member = {
  clerk_subject: "user_test_member",
  display_name: "Morgan Tester",
  active: true,
  principal_state: "active",
  is_owner: false,
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

function setInput(container: HTMLElement, label: string, value: string): void {
  const input = container.querySelector<HTMLInputElement>(`input[aria-label="${label}"]`);
  expect(input).not.toBeNull();
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  setter?.call(input, value);
  input?.dispatchEvent(new Event("input", { bubbles: true }));
}

function button(container: HTMLElement, text: string): HTMLButtonElement {
  const match = [...container.querySelectorAll("button")].find(
    (candidate) => candidate.textContent === text,
  );
  expect(match).toBeDefined();
  return match as HTMLButtonElement;
}

describe("BetaIdentityAdmin", () => {
  let container: HTMLDivElement;
  let root: Root;
  const getToken = vi.fn().mockResolvedValue("fresh-owner-token");

  beforeEach(() => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    getToken.mockResolvedValue("fresh-owner-token");
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    getToken.mockClear();
  });

  it("loads the privacy-minimized roster only when an owner opens the controls", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValueOnce(jsonResponse([owner, member]));
    vi.stubGlobal("fetch", fetchMock);

    await act(async () =>
      root.render(
        createElement(BetaIdentityAdmin, {
          identity: { mode: "early_adopter_beta", getToken },
        }),
      ),
    );
    expect(fetchMock).not.toHaveBeenCalled();

    await act(async () => button(container, "Manage access").click());
    await settle();

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock.mock.calls[0]?.[0]).toBe("http://localhost:8000/admin/identities");
    const headers = new Headers(fetchMock.mock.calls[0]?.[1]?.headers);
    expect(headers.get("Authorization")).toBe("Bearer fresh-owner-token");
    expect(headers.has("X-Box-Id")).toBe(false);
    expect(container.textContent).toContain("Taylor Owner");
    expect(container.textContent).toContain("Morgan Tester");
  });

  it("fails closed without rendering mutation controls when owner access is denied", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ detail: "active Box owner authority is required" }, 403));
    vi.stubGlobal("fetch", fetchMock);

    await act(async () =>
      root.render(
        createElement(BetaIdentityAdmin, {
          identity: { mode: "early_adopter_beta", getToken },
        }),
      ),
    );
    await act(async () => button(container, "Manage access").click());
    await settle();

    expect(container.querySelector('[role="alert"]')?.textContent).toBe(
      "active Box owner authority is required",
    );
    expect(container.querySelector("form")).toBeNull();
    expect(container.textContent).not.toContain("Bind invited tester");
    expect(container.textContent).not.toContain("Transfer ownership");
  });

  it("binds only the reviewed subject, display name, and opaque evidence reference", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse([owner]))
      .mockResolvedValueOnce(jsonResponse({ status: "bound" }))
      .mockResolvedValueOnce(jsonResponse([owner, member]));
    vi.stubGlobal("fetch", fetchMock);

    await act(async () =>
      root.render(
        createElement(BetaIdentityAdmin, {
          identity: { mode: "early_adopter_beta", getToken },
        }),
      ),
    );
    await act(async () => button(container, "Manage access").click());
    await settle();
    await act(async () => {
      setInput(container, "Clerk user ID", member.clerk_subject);
      setInput(container, "Display name", member.display_name);
      setInput(container, "Opaque evidence reference", "review:beta-member-1");
    });
    await act(async () =>
      container.querySelector("form")?.dispatchEvent(new Event("submit", { bubbles: true })),
    );
    await settle();

    expect(fetchMock.mock.calls[1]?.[0]).toBe(
      "http://localhost:8000/admin/identities/bind",
    );
    expect(JSON.parse(String(fetchMock.mock.calls[1]?.[1]?.body))).toEqual({
      clerk_subject: member.clerk_subject,
      display_name: member.display_name,
      evidence_ref: "review:beta-member-1",
    });
    expect(container.textContent).toContain("Tester bound to this Cosmas Beta Lab.");
    expect(container.textContent).toContain("Morgan Tester");
  });

  it("requires confirmation and evidence before deactivating a tester", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse([owner, member]))
      .mockResolvedValueOnce(jsonResponse({ status: "deactivated" }))
      .mockResolvedValueOnce(jsonResponse([owner, { ...member, active: false }]))
      .mockResolvedValueOnce(jsonResponse({ status: "transferred" }));
    const confirmMock = vi.fn().mockReturnValueOnce(false).mockReturnValueOnce(true);
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("confirm", confirmMock);

    await act(async () =>
      root.render(
        createElement(BetaIdentityAdmin, {
          identity: { mode: "early_adopter_beta", getToken },
        }),
      ),
    );
    await act(async () => button(container, "Manage access").click());
    await settle();
    await act(async () =>
      setInput(container, "Opaque evidence reference", "review:offboard-1"),
    );

    await act(async () => button(container, "Deactivate").click());
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await act(async () => button(container, "Deactivate").click());
    await settle();

    expect(fetchMock.mock.calls[1]?.[0]).toBe(
      "http://localhost:8000/admin/identities/deactivate",
    );
    expect(JSON.parse(String(fetchMock.mock.calls[1]?.[1]?.body))).toEqual({
      clerk_subject: member.clerk_subject,
      evidence_ref: "review:offboard-1",
    });
    expect(container.textContent).toContain("Tester deactivated.");
    expect(button(container, "Reactivate")).toBeDefined();
  });

  it("clears owner-only controls immediately after ownership transfer", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse([owner, member]))
      .mockResolvedValueOnce(jsonResponse({ status: "transferred" }));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("confirm", vi.fn().mockReturnValue(true));

    await act(async () =>
      root.render(
        createElement(BetaIdentityAdmin, {
          identity: { mode: "early_adopter_beta", getToken },
        }),
      ),
    );
    await act(async () => button(container, "Manage access").click());
    await settle();
    await act(async () => setInput(container, "Opaque evidence reference", "review:transfer-1"));
    await act(async () => button(container, "Transfer ownership").click());
    await settle();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(container.querySelector('[role="status"]')?.textContent).toContain(
      "Ownership transferred",
    );
    expect(container.querySelector("form")).toBeNull();
    expect(container.textContent).not.toContain(member.clerk_subject);
    expect(container.textContent).not.toContain("Transfer ownership");
  });

  it("runs owner-only retention through the normal authenticated API after confirmation", async () => {
    const returnedArtifactId = "00000000-0000-4000-8000-000000000099";
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse([owner]))
      .mockResolvedValueOnce(
        jsonResponse({ receipts: [{ artifact_id: returnedArtifactId }] }),
      );
    const confirmMock = vi.fn().mockReturnValue(true);
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("confirm", confirmMock);

    await act(async () =>
      root.render(
        createElement(BetaIdentityAdmin, {
          identity: { mode: "early_adopter_beta", getToken },
        }),
      ),
    );
    await act(async () => button(container, "Manage access").click());
    await settle();
    await act(async () => button(container, "Run retention purge").click());
    await settle();

    expect(confirmMock).toHaveBeenCalledOnce();
    expect(confirmMock).toHaveBeenCalledWith(
      "Run the owner-only physical purge for every due synthetic artifact in this Box? " +
        "This removes application references and requires no recoverable Blob object, " +
        "version, or snapshot to remain through Azure APIs. It cannot be undone.",
    );
    expect(fetchMock.mock.calls[1]?.[0]).toBe("http://localhost:8000/retention/purge");
    expect(fetchMock.mock.calls[1]?.[1]?.method).toBe("POST");
    const headers = new Headers(fetchMock.mock.calls[1]?.[1]?.headers);
    expect(headers.get("Authorization")).toBe("Bearer fresh-owner-token");
    expect(headers.has("X-Box-Id")).toBe(false);
    expect(headers.has("X-Actor-Principal-Id")).toBe(false);
    expect(container.textContent).toContain("Retention purge complete. 1 due artifact purged.");
    expect(container.textContent).toContain("Never use PHI here");
    expect(container.textContent).not.toContain(returnedArtifactId);
  });

  it("does not run retention when the owner cancels confirmation", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValueOnce(jsonResponse([owner]));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("confirm", vi.fn().mockReturnValue(false));

    await act(async () =>
      root.render(
        createElement(BetaIdentityAdmin, {
          identity: { mode: "early_adopter_beta", getToken },
        }),
      ),
    );
    await act(async () => button(container, "Manage access").click());
    await settle();
    await act(async () => button(container, "Run retention purge").click());

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
