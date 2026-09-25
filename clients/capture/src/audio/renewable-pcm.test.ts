import { expect, it } from "vitest";
import { Pcm16Chunker } from "./pcm-chunker";
import { AreaWeightedPcm16Resampler } from "./resampler";
import { initialSourceWindow, extendSourceWindow } from "../capture/source-authority";

it("preserves rational resampling phase and partial chunks through repeated extensions", () => {
  const input = Float32Array.from({ length: 4410 }, (_, index) => Math.sin(index / 7));
  const resampler = new AreaWeightedPcm16Resampler({ sourceSampleRateHz: 44100, targetSampleRateHz: 16000, maximumInputFrames: 882, maximumOutputFrames: 320 });
  const chunks = new Pcm16Chunker({ targetFramesPerChunk: 160, maximumChunks: 2 });
  const actual: number[] = []; let limit = 882;
  for (let offset = 0; offset < input.length; offset += 113) {
    const next = input.subarray(offset, offset + 113);
    if (offset + next.length > limit) {
      limit = limit === 882 ? 2646 : 4410;
      const maximumChunks = limit === 2646 ? 6 : 10;
      resampler.extendLimits(limit, maximumChunks * 160); chunks.extendMaximumChunks(maximumChunks);
    }
    for (const chunk of chunks.push(resampler.push(next))) actual.push(...chunk);
  }
  expect(resampler.finish()).toHaveLength(0); expect(chunks.finish()).toBeNull();
  const baseline = new AreaWeightedPcm16Resampler({ sourceSampleRateHz: 44100, targetSampleRateHz: 16000, maximumInputFrames: 4410, maximumOutputFrames: 1600 });
  expect(actual).toEqual(Array.from(baseline.push(input))); expect(actual).toHaveLength(1600);
  expect(() => resampler.extendLimits(5000, 2000)).toThrow("audio_capture_already_closed");
  expect(() => chunks.extendMaximumChunks(11)).toThrow("audio_capture_already_closed");
});

it("rejects shrinking or inconsistent PCM limits without changing the existing stream", () => {
  const resampler = new AreaWeightedPcm16Resampler({ sourceSampleRateHz: 32000, targetSampleRateHz: 16000, maximumInputFrames: 32, maximumOutputFrames: 16 });
  const chunks = new Pcm16Chunker({ targetFramesPerChunk: 16, maximumChunks: 1 });
  expect(() => resampler.extendLimits(31, 16)).toThrow(); expect(() => resampler.extendLimits(34, 16)).toThrow();
  expect(() => chunks.extendMaximumChunks(0)).toThrow();
  expect(chunks.push(resampler.push(new Float32Array(32).fill(0.5)))[0]).toEqual(new Int16Array(16).fill(16384));
});

it("binds source extension to one live run, generation, deadline and immutable hard budget", () => {
  const now = Date.now(), initial = initialSourceWindow({ runId: "00000000-0000-4000-8000-000000000001", generation: 2,
    expiresAtMs: now + 1000, hardMaximumChunks: 360 }, 90, now);
  const command = { runId: initial.runId, generation: 3, expiresAtMs: now + 900000, maximumChunks: 175 };
  const next = extendSourceWindow(initial, command, now);
  expect(extendSourceWindow(next, command, now)).toEqual(next);
  for (const change of [{ runId: "foreign" }, { generation: 4 }, { maximumChunks: 361 }, { maximumChunks: 89 }, { expiresAtMs: now + 999 }]) {
    expect(() => extendSourceWindow(initial, { ...command, ...change }, now)).toThrow();
  }
  expect(() => extendSourceWindow(initial, command, now + 1000)).toThrow();
});
