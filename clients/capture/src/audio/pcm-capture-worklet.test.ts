import { afterEach, expect, it, vi } from "vitest";
import type { PcmCaptureProducerBounds } from "./worklet-protocol";

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function fixture(options: Partial<PcmCaptureProducerBounds> = {}) {
  vi.resetModules();
  let wall = Date.now(), frame = 0;
  vi.spyOn(Date, "now").mockImplementation(() => wall);
  vi.stubGlobal("currentFrame", frame); vi.stubGlobal("sampleRate", 48000);
  const messages: any[] = [];
  const port = { onmessage: null as ((event: { data: unknown }) => void) | null,
    postMessage: (message: unknown) => messages.push(structuredClone(message)) };
  vi.stubGlobal("AudioWorkletProcessor", class { protected readonly port = port; });
  const register = vi.fn(); vi.stubGlobal("registerProcessor", register);
  const { PcmCaptureProcessor } = await import("./pcm-capture-worklet");
  const bounds: PcmCaptureProducerBounds = { runId: "00000000-0000-4000-8000-000000000001", generation: 1,
    maximumInputFrames: 4800, hardMaximumInputFrames: 14400, expiresAtMs: wall + 2000, ...options };
  const processor = new PcmCaptureProcessor({ processorOptions: { captureBounds: bounds } });
  expect(register).toHaveBeenCalledWith("cosmaneura-pcm-capture-v1", PcmCaptureProcessor);
  const send = (data: unknown) => port.onmessage?.({ data });
  return { bounds, messages, send,
    extend: (maximumInputFrames: number, generation = 2, expiresAtMs = bounds.expiresAtMs + 1000) => {
      const next = { runId: bounds.runId, generation, maximumInputFrames, expiresAtMs };
      send({ type: "extend", version: 1, runId: bounds.runId, bounds: next }); return next;
    },
    tick: (count = 128, acknowledge = true) => {
      const from = messages.length, alive = processor.process([[new Float32Array(count).fill(0.5)]]);
      frame += count; vi.stubGlobal("currentFrame", frame);
      if (acknowledge) for (const message of messages.slice(from)) {
        if (message.type === "pcm") send({ type: "pcm_consumed", version: 1, runId: bounds.runId, sequence: message.sequence });
      }
      return alive;
    },
    clock: (nextFrame: number, nextWall: number) => { frame = nextFrame; wall = nextWall; vi.stubGlobal("currentFrame", frame); },
    now: () => wall,
  };
}

it("extends the actual producer twice without resetting sequence and stops exactly at the hard frame budget", async () => {
  const f = await fixture();
  for (let n = 0; n < 36; n++) expect(f.tick()).toBe(true);
  f.extend(9600);
  for (let n = 0; n < 36; n++) expect(f.tick()).toBe(true);
  f.extend(14400, 3, f.bounds.expiresAtMs + 2000);
  for (let n = 0; n < 200 && f.tick(); n++) { /* bounded producer terminates below */ }
  const packets = f.messages.filter(message => message.type === "pcm");
  expect(packets.reduce((sum, message) => sum + message.frames.byteLength / 4, 0)).toBe(14400);
  expect(packets.map(message => message.sequence)).toEqual(packets.map((_, index) => index));
  expect(packets.every(message => new Float32Array(message.frames).every(sample => sample === 0.5))).toBe(true);
  expect(f.messages.filter(message => message.type === "extended")).toHaveLength(2);
  expect(f.messages.at(-1)).toMatchObject({ type: "window_closed", reason: "frame_limit" });
  const length = f.messages.length; f.extend(14400, 4, f.bounds.expiresAtMs + 3000);
  expect(f.tick()).toBe(false); expect(f.messages).toHaveLength(length);
});

it("acknowledges an identical extension again without granting extra frames", async () => {
  const f = await fixture(); f.extend(9600); f.extend(9600);
  expect(f.messages.filter(message => message.type === "extended")).toHaveLength(2);
  for (let n = 0; n < 200 && f.tick(); n++) { /* exact cumulative limit */ }
  expect(f.messages.filter(message => message.type === "pcm").reduce((sum, item) => sum + item.frames.byteLength / 4, 0)).toBe(9600);
});

it.each(["changed duplicate", "generation jump", "foreign run", "hard limit", "expired"])("rejects %s without producing more PCM", async fault => {
  const f = await fixture(); f.extend(9600);
  if (fault === "changed duplicate") f.extend(10000, 2);
  if (fault === "generation jump") f.extend(14400, 4);
  if (fault === "foreign run") f.send({ type: "extend", version: 1, runId: "foreign", bounds: {} });
  if (fault === "hard limit") f.extend(14401, 3, f.bounds.expiresAtMs + 2000);
  if (fault === "expired") { f.clock(0, f.bounds.expiresAtMs + 1001); f.extend(14400, 3, f.bounds.expiresAtMs + 2000); }
  expect(f.tick()).toBe(false); expect(f.messages.some(message => message.type === "pcm")).toBe(false);
  expect(f.messages.at(-1)).toMatchObject({ type: "window_closed", reason: "protocol" });
});

it("enforces render-time expiry even when the wall clock moves backward", async () => {
  const f = await fixture({ maximumInputFrames: 480000, hardMaximumInputFrames: 480000 });
  f.clock(96000, f.now() - 10000);
  expect(f.tick()).toBe(false);
  expect(f.messages).toEqual([{ type: "window_closed", version: 1, runId: f.bounds.runId, reason: "authority_expired" }]);
});

it("bounds unconsumed PCM to one second when the renderer stalls", async () => {
  const f = await fixture({ maximumInputFrames: 480000, hardMaximumInputFrames: 480000 });
  for (let n = 0; n < 100; n++) expect(f.tick(480, false)).toBe(true);
  expect(f.tick(480, false)).toBe(false);
  expect(f.messages.filter(message => message.type === "pcm")).toHaveLength(100);
  expect(f.messages.at(-1)).toMatchObject({ type: "window_closed", reason: "backpressure" });
});

it("rejects an acknowledgement without a pending sequence instead of bypassing backpressure", async () => {
  const f = await fixture(); f.send({ type: "pcm_consumed", version: 1, runId: f.bounds.runId });
  expect(f.tick()).toBe(false); expect(f.messages.at(-1)).toMatchObject({ reason: "protocol" });
});

it("cannot extend or emit after an explicit producer Stop", async () => {
  const f = await fixture(); f.send({ type: "stop", version: 1, runId: f.bounds.runId }); f.extend(9600);
  expect(f.tick()).toBe(false); expect(f.messages).toEqual([]);
});
