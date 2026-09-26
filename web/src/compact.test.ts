import { afterEach, expect, it, vi } from "vitest";

afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); vi.resetModules(); });

it("uses same-origin API paths only for the explicitly compiled local profile", async () => {
  vi.stubEnv("VITE_COMPACT_LOCAL", "true");
  vi.stubEnv("VITE_COSMAS_ENV", "synth_os");
  vi.resetModules();
  const { api, COMPACT_LOCAL } = await import("./api");
  const fetchMock = vi.fn().mockResolvedValue(new Response("[]"));
  vi.stubGlobal("fetch", fetchMock);
  await api.queue({ mode: "synth_os", boxId: "invented-box", actorId: "invented-owner" });
  expect(COMPACT_LOCAL).toBe(true);
  expect(fetchMock.mock.calls[0][0]).toBe("/queue");
});

it("does not enable the same-origin experiment in beta", async () => {
  vi.stubEnv("VITE_COMPACT_LOCAL", "true");
  vi.stubEnv("VITE_COSMAS_ENV", "early_adopter_beta");
  vi.resetModules();
  const { COMPACT_LOCAL } = await import("./api");
  expect(COMPACT_LOCAL).toBe(false);
});
