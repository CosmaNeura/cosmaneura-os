import { StrictMode, act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App, resolveRuntimeMode } from "./App";
import { api, type QueueItem } from "./api";

const seed = {
  box_id: "00000000-0000-4000-8000-000000000001",
  owner_id: "00000000-0000-4000-8000-000000000002",
  agents: { chaser: "00000000-0000-4000-8000-000000000003" },
  ticket_id: "00000000-0000-4000-8000-000000000004",
};

const pendingTicket: QueueItem = {
  id: seed.ticket_id,
  lane: "artifact_chase",
  state: "pending_approval",
  proposed_message: "Please use the secure link to share your insurance card images.",
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

describe("owner queue", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
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

  it("loads one synthetic demo queue under StrictMode with checked identity headers", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse(seed))
      .mockResolvedValueOnce(jsonResponse([pendingTicket]));
    vi.stubGlobal("fetch", fetchMock);

    await act(async () => {
      root.render(
        createElement(StrictMode, null, createElement(App, { runtimeMode: "synth_os" })),
      );
    });
    await settle();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[0]?.[0]).toBe("http://localhost:8000/synth/demo-queue");
    expect(fetchMock.mock.calls[1]?.[0]).toBe("http://localhost:8000/queue");
    expect(requestHeaders(fetchMock, 1).get("X-Box-Id")).toBe(seed.box_id);
    expect(requestHeaders(fetchMock, 1).get("X-Actor-Principal-Id")).toBe(seed.owner_id);
    expect(requestHeaders(fetchMock, 1).has("Authorization")).toBe(false);
    expect(container.textContent).toContain("Northside Synth Clinic");
    expect(container.textContent).toContain("pending approval");
  });

  it("binds approval to the revision displayed to the human", async () => {
    const sentTicket = { ...pendingTicket, state: "sent" };
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse(seed))
      .mockResolvedValueOnce(jsonResponse([pendingTicket]))
      .mockResolvedValueOnce(jsonResponse({ decision: "approved", operation_id: "op-test" }))
      .mockResolvedValueOnce(jsonResponse([sentTicket]));
    vi.stubGlobal("fetch", fetchMock);

    await act(async () => root.render(createElement(App, { runtimeMode: "synth_os" })));
    await settle();
    const approve = [...container.querySelectorAll("button")].find(
      (button) => button.textContent === "Approve",
    );
    expect(approve).toBeDefined();
    await act(async () => approve?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    await settle();

    expect(fetchMock.mock.calls[2]?.[0]).toBe(
      `http://localhost:8000/tickets/${pendingTicket.id}/decide`,
    );
    const decisionInit = fetchMock.mock.calls[2]?.[1];
    expect(JSON.parse(String(decisionInit?.body))).toEqual({
      kind: "approve",
      expected_revision_id: pendingTicket.revision_id,
    });
    expect(requestHeaders(fetchMock, 2).get("X-Box-Id")).toBe(seed.box_id);
    expect(requestHeaders(fetchMock, 2).get("X-Actor-Principal-Id")).toBe(seed.owner_id);
    expect(container.textContent).toContain("sent");
  });

  it("edits, refreshes, approves the refreshed revision, and closes the ticket", async () => {
    const editedBody = "Please upload both synthetic insurance card images through the secure link.";
    const revisedTicket = {
      ...pendingTicket,
      proposed_message: editedBody,
      revision_id: "00000000-0000-4000-8000-000000000007",
    };
    const sentTicket = { ...revisedTicket, state: "sent" };
    const closedTicket = { ...revisedTicket, state: "closed" };
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse(seed))
      .mockResolvedValueOnce(jsonResponse([pendingTicket]))
      .mockResolvedValueOnce(
        jsonResponse({ revision_id: revisedTicket.revision_id, payload_hash: "hash-test" }),
      )
      .mockResolvedValueOnce(jsonResponse([revisedTicket]))
      .mockResolvedValueOnce(jsonResponse({ decision: "approved", operation_id: "op-test" }))
      .mockResolvedValueOnce(jsonResponse([sentTicket]))
      .mockResolvedValueOnce(jsonResponse({ id: pendingTicket.id, state: "closed" }))
      .mockResolvedValueOnce(jsonResponse([closedTicket]));
    vi.stubGlobal("fetch", fetchMock);

    await act(async () => root.render(createElement(App, { runtimeMode: "synth_os" })));
    await settle();

    const textarea = container.querySelector("textarea");
    expect(textarea).not.toBeNull();
    await act(async () => {
      if (!textarea) return;
      const setValue = Object.getOwnPropertyDescriptor(
        HTMLTextAreaElement.prototype,
        "value",
      )?.set;
      setValue?.call(textarea, editedBody);
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
    });
    const saveEdit = [...container.querySelectorAll("button")].find(
      (button) => button.textContent === "Save edit",
    );
    await act(async () => saveEdit?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    await settle();

    expect(fetchMock.mock.calls[2]?.[0]).toBe(
      `http://localhost:8000/tickets/${pendingTicket.id}/edit`,
    );
    expect(JSON.parse(String(fetchMock.mock.calls[2]?.[1]?.body))).toEqual({ body: editedBody });
    expect(container.querySelector(".message")?.textContent).toBe(editedBody);

    const approve = [...container.querySelectorAll("button")].find(
      (button) => button.textContent === "Approve",
    );
    await act(async () => approve?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    await settle();

    expect(JSON.parse(String(fetchMock.mock.calls[4]?.[1]?.body))).toEqual({
      kind: "approve",
      expected_revision_id: revisedTicket.revision_id,
    });
    expect(container.textContent).toContain("sent");

    const close = [...container.querySelectorAll("button")].find(
      (button) => button.textContent === "Close",
    );
    expect(close).toBeDefined();
    await act(async () => close?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    await settle();

    expect(fetchMock.mock.calls[6]?.[0]).toBe(
      `http://localhost:8000/tickets/${pendingTicket.id}/close`,
    );
    expect(container.textContent).toContain("closed");
    expect(fetchMock).toHaveBeenCalledTimes(8);
  });

  it.each([401, 403])("renders a safe API error for HTTP %s", async (status) => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse(seed))
      .mockResolvedValueOnce(
        jsonResponse({ detail: "Access denied", internal: "do-not-render" }, status),
      );
    vi.stubGlobal("fetch", fetchMock);

    await act(async () => root.render(createElement(App, { runtimeMode: "synth_os" })));
    await settle();

    const alert = container.querySelector('[role="alert"]');
    expect(alert?.textContent).toBe("Access denied");
    expect(container.textContent).not.toContain("do-not-render");
  });

  it("makes no request when a beta build has no installed login provider", async () => {
    const fetchMock = vi.fn<typeof fetch>();
    vi.stubGlobal("fetch", fetchMock);

    await act(async () =>
      root.render(createElement(App, { runtimeMode: "early_adopter_beta" })),
    );
    await settle();

    expect(fetchMock).not.toHaveBeenCalled();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      "Beta login is not configured",
    );
  });

  it("obtains a fresh token and uses only bearer auth for each beta API request", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValueOnce(jsonResponse([]));
    vi.stubGlobal("fetch", fetchMock);
    const getToken = vi.fn().mockResolvedValue("offline-test-token");

    await api.queue({ mode: "early_adopter_beta", getToken });

    expect(getToken).toHaveBeenCalledOnce();
    expect(getToken).toHaveBeenCalledWith({ skipCache: true });
    const headers = requestHeaders(fetchMock, 0);
    expect(headers.get("Authorization")).toBe("Bearer offline-test-token");
    expect(headers.has("X-Box-Id")).toBe(false);
    expect(headers.has("X-Actor-Principal-Id")).toBe(false);
    expect(fetchMock.mock.calls[0]?.[1]?.credentials).toBe("omit");
  });

  it.each([
    ["missing", vi.fn().mockResolvedValue(null)],
    ["failed", vi.fn().mockRejectedValue(new Error("sensitive provider detail"))],
  ])("does not call the API when a beta token is %s", async (_case, getToken) => {
    const fetchMock = vi.fn<typeof fetch>();
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.queue({ mode: "early_adopter_beta", getToken })).rejects.toThrow(
      "Secure session is unavailable. Sign in again.",
    );

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("defaults only a development build to synth and blocks missing production mode", () => {
    expect(resolveRuntimeMode(undefined, true)).toBe("synth_os");
    expect(resolveRuntimeMode(undefined, false)).toBe("unconfigured");
    expect(resolveRuntimeMode("unexpected", true)).toBe("unconfigured");
  });
});
