import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { CaptureInputSignal } from "./CaptureInputSignal";
import type { IosInputSignal } from "../../clients/capture/src/native/ios-input-signal";
import type { NativeRecorderSnapshot } from "../../clients/capture/src/native/owned-recorder";

let root: Root, container: HTMLDivElement;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "performance"] });
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount()); container.remove();
  expect(vi.getTimerCount()).toBe(0); vi.useRealTimers();
});
function native(signal: Partial<IosInputSignal> = {}): NativeRecorderSnapshot["native"] {
  return { phase: "recording", busy: false, input: "built_in", signalObservedAtMs: performance.now(),
    signal: { version: 2, signal: { inputBuffers: 12, convertedBuffers: 12, inputEverNonzero: true,
      convertedEverNonzero: true, inputLevel: 0.1, convertedLevel: 0.1, inputAgeMs: 0,
      convertedAgeMs: 0, zeroInputMs: 0, inputMuted: false, route: "built_in", ...signal } } };
}
async function render(value = native(), recording = true) {
  await act(async () => root.render(<CaptureInputSignal native={value} recording={recording} />));
}
const meter = () => container.querySelector("meter")!;

it("shows validated input activity and the selected microphone without transcript claims", async () => {
  await render();
  expect(container.textContent).toContain("iPhone microphone");
  expect(meter().value).toBeCloseTo(2 / 3);
  expect(meter().getAttribute("aria-valuetext")).toBe("Microphone activity");
  expect(container.textContent).not.toMatch(/transcribed|recognized|saved|uploaded/i);
  expect(container.querySelector("button")).toBeNull();
});

it.each([
  [{ inputMuted: true }, "Microphone is muted by iOS."],
  [{ inputAgeMs: null }, "Microphone signal is unavailable."],
  [{ convertedAgeMs: 1501 }, "Microphone signal is unavailable."],
  [{ zeroInputMs: 3000 }, "No input detected."],
  [{ inputLevel: 0, convertedLevel: 0 }, "Quiet input"],
  [{ convertedEverNonzero: false }, "Audio has not reached the recording yet."],
] as const)("shows the existing advisory for %j", async (signal, message) => {
  await render(native(signal));
  expect(container.textContent).toContain(message); expect(meter().value).toBe(0);
});

it("ages a retained activity reading to Waiting without another publication", async () => {
  const retained = native(); await render(retained);
  await act(async () => vi.advanceTimersByTimeAsync(1500));
  expect(meter().value).toBeGreaterThan(0);
  await act(async () => vi.advanceTimersByTimeAsync(250));
  expect(container.textContent).toContain("Waiting for microphone signal…");
  expect(meter().value).toBe(0);
  await render({ ...retained, signalObservedAtMs: performance.now() });
  expect(meter().value).toBeGreaterThan(0);
});

it("includes native buffer age in the freshness check", async () => {
  await render(native({ inputAgeMs: 1200, convertedAgeMs: 1200 }));
  await act(async () => vi.advanceTimersByTimeAsync(500));
  expect(container.textContent).toContain("Microphone signal is unavailable.");
  expect(meter().value).toBe(0);
});

it.each([
  { signal: { version: 2, signal: { token: "private details must not appear" } } },
  { signal: { version: 2, signal: null } },
  { signalObservedAtMs: undefined },
  { signalObservedAtMs: NaN },
  { signalObservedAtMs: 10_000 },
] as const)("does not display an unvalidated or undated reading %j", async update => {
  await render({ ...native(), ...update });
  expect(container.textContent).toContain("Waiting for microphone signal…");
  expect(container.textContent).not.toContain("private details"); expect(meter().value).toBe(0);
});

it.each(["paused", "pausing", "starting", "sealed", "failed"])("masks retained input during %s", async phase => {
  await render(); expect(meter().value).toBeGreaterThan(0);
  await render({ ...native(), phase });
  expect(container.textContent).toBe(""); expect(vi.getTimerCount()).toBe(0);
});

it("masks retained input when the outer recording state has stopped", async () => {
  await render(native(), false);
  expect(container.textContent).toBe(""); expect(vi.getTimerCount()).toBe(0);
});
