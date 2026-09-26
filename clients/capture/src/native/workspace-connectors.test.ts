import { webcrypto } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { vendorApi } from "../../../../web/src/vendor-api";
import { financeApi } from "../../../../web/src/finance-api";
import { portalSetupApi } from "../../../../web/src/portal-setup-api";
import { portalWorkApi } from "../../../../web/src/portal-work-api";
import { financeSetupApi } from "../../../../web/src/finance-setup-api";
import { actual as vendor, actualContent, artifact } from "../../../../web/src/vendor-test-fixture";
import { actual as finance } from "../../../../web/src/finance-test-fixture";
import { portalFixture } from "../../../../web/src/portal-setup-test-fixture";
import portal from "../../../../web/src/__fixtures__/portal-work/actual-portal-work.json";
import settings from "../../../../web/src/__fixtures__/finance-setup/actual-finance-setup-fixtures.json";
import { vendorSha256 } from "../../../../web/src/vendor-contract";
import type { AuthenticatedWorkspaceIdentity } from "../../../../web/src/workspace-api";

const api = "http://127.0.0.1:8046";
const json = (value: unknown) => new Response(JSON.stringify(value), {
  headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
});
const readCases = [
  { header: "X-Cosmas-Vendor-Contract", path: `/workspaces/${vendor.options.workspace_id}/vendor-work/options`,
    response: vendor.options, read: (id: AuthenticatedWorkspaceIdentity) => vendorApi.options(id, vendor.options.workspace_id) },
  { header: "X-Cosmas-Finance-Contract", path: `/workspaces/${finance.options.workspace_id}/finance-work/options`,
    response: finance.options, read: (id: AuthenticatedWorkspaceIdentity) => financeApi.options(id, finance.options.workspace_id) },
  { header: "X-Cosmas-Portal-Contract", path: "/portal-setup", response: portalFixture.catalog_pending,
    read: (id: AuthenticatedWorkspaceIdentity) => portalSetupApi.catalog(id) },
  { header: "X-Cosmas-Portal-Work-Contract", path: `/workspaces/${portal.workspace_id}/portal-work`, response: portal.catalog,
    read: (id: AuthenticatedWorkspaceIdentity) => portalWorkApi.catalog(id, portal.workspace_id) },
  { header: "X-Cosmas-Finance-Setup-Contract", path: "/finance-setup", response: settings.active_catalog,
    read: (id: AuthenticatedWorkspaceIdentity) => financeSetupApi.catalog(id) },
];

beforeEach(() => {
  vi.stubGlobal("crypto", webcrypto);
  vi.stubGlobal("window", { location: { href: "capacitor://localhost/index.html" } });
  vi.stubEnv("VITE_API_BASE", api);
  vi.stubEnv("VITE_WORKSPACE_APPLE_LOCAL_TRANSPORT_ENABLED", "true");
});
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

describe("Apple direct-fetch connector integration (source contract, not WebKit acceptance)", () => {
  it.each(readCases)("carries the closed $header read with a fresh native-derived token", async entry => {
    const getToken = vi.fn(async () => "invented-native-token");
    const fetcher = vi.fn(async () => json(entry.response));
    vi.stubGlobal("fetch", fetcher);
    await entry.read({ mode: "clerk_jwt", getToken });
    expect(getToken).toHaveBeenCalledExactlyOnceWith({ skipCache: true });
    expect(fetcher).toHaveBeenCalledTimes(1);
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe(api + entry.path);
    const headers = new Headers(init?.headers);
    expect(headers.get(entry.header)).toBe("1");
    expect(headers.get("Authorization")).toBe("Bearer invented-native-token");
    expect(headers.get("X-Cosmas-Draft-Recovery")).toBe("2");
    expect(headers.has("X-Box-Id")).toBe(false);
    expect(headers.has("X-Cosmas-Desktop-Session")).toBe(false);
    expect(init).toMatchObject({ method: "GET", credentials: "omit", redirect: "error", cache: "no-store", referrerPolicy: "no-referrer" });
  });

  it.each(readCases)("never dispatches $header when native token acquisition rejects a changed session", async entry => {
    const getToken = vi.fn(async () => { throw Error("Native session unavailable"); });
    const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
    await expect(entry.read({ mode: "clerk_jwt", getToken })).rejects.toThrow();
    expect(getToken).toHaveBeenCalledTimes(1);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it.each(readCases)("keeps $header unavailable without the explicit Apple-origin gate", async entry => {
    vi.stubEnv("VITE_WORKSPACE_APPLE_LOCAL_TRANSPORT_ENABLED", "false");
    const getToken = vi.fn(async () => "invented-native-token");
    const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
    await expect(entry.read({ mode: "clerk_jwt", getToken })).rejects.toThrow();
    expect(getToken).not.toHaveBeenCalled(); expect(fetcher).not.toHaveBeenCalled();
  });

  it("retains raw PDF PUT and its exact write key on Apple without a native HTTP translation", async () => {
    const op = await actualContent(), bytes = new TextEncoder().encode("%PDF-1.7\nInvented raw HTTP custody\n%%EOF");
    const fetcher = vi.fn(async () => json(artifact.artifact_content_receipt)); vi.stubGlobal("fetch", fetcher);
    const getToken = vi.fn(async () => "invented-native-token");
    await vendorApi.upload({ mode: "clerk_jwt", getToken }, op, new Blob([bytes]));
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe(`${api}/workspaces/${op.scope.id}/vendor-artifacts/${op.target_id}/content`);
    expect(init?.method).toBe("PUT"); expect(init?.body).toEqual(bytes);
    expect(new Headers(init?.headers).get("Content-Type")).toBe("application/pdf");
    expect(new Headers(init?.headers).get("X-Cosmas-Artifact-Write-Key")).toBe(op.request.idempotency_key);
  });

  it("verifies an exact 8 MiB PDF and rejects oversize or altered content before preview", async () => {
    const bytes = new Uint8Array(8 * 1048576); bytes.set(new TextEncoder().encode("%PDF-1.7\n"));
    const doc = { artifact_id: vendor.options.source.note_id, sha256: await vendorSha256(bytes),
      byte_length: bytes.length, media_type: "application/pdf" as const };
    const fetcher = vi.fn(async () => new Response(bytes, {
      headers: { "Content-Type": "application/pdf", "Cache-Control": "no-store", "Content-Length": String(bytes.length) },
    })); vi.stubGlobal("fetch", fetcher);
    const identity = { mode: "clerk_jwt" as const, getToken: vi.fn(async () => "invented-native-token") };
    const preview = await vendorApi.preview(identity, vendor.options.workspace_id, doc);
    expect(preview.byteLength).toBe(bytes.length);
    expect(await vendorSha256(preview)).toBe(doc.sha256);
    await expect(vendorApi.preview(identity, vendor.options.workspace_id, { ...doc, byte_length: bytes.length + 1 })).rejects.toThrow();
    expect(fetcher).toHaveBeenCalledTimes(1); expect(identity.getToken).toHaveBeenCalledTimes(1);
    bytes[bytes.length - 1] = 1;
    await expect(vendorApi.preview(identity, vendor.options.workspace_id, doc)).rejects.toThrow();
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
});
