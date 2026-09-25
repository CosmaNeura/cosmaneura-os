import { expect, it, vi } from "vitest";
import type { CaptureCapabilities } from "../../bff/contracts";
import { IosNativeMicrophoneCaptureSource } from "./ios-native-microphone-source";

it("drains a native full packet before delivering the final partial packet", async () => {
  const capabilities: CaptureCapabilities = {
    protocol_version: "1.0",
    media: { media_type: "audio/wav", encoding: "pcm_s16le", channels: 1, sample_rate_hz: 16_000 },
    target_chunk_duration_ms: 20, max_envelope_bytes: 684, max_chunks: 3,
    remaining_aggregate_plaintext_bytes: 1_368, capture_lease_ttl_seconds: 30,
    reservation_window_seconds: 30, max_reservations_per_batch: 2, upload_concurrency: 1,
  };
  const fullPcmBytes = new Uint8Array(640);
  const fullSamples = new DataView(fullPcmBytes.buffer);
  for (let offset = 0; offset < fullPcmBytes.length; offset += 2) fullSamples.setInt16(offset, 4_660, true);
  const expectedFullPcm = fullPcmBytes.slice();
  const finalPcmBytes = Uint8Array.from([52, 18, 120, 86]);
  const delivered: Array<{ sequenceNumber: number; durationMs: number; wavBytes: Uint8Array }> = [];
  const stopModes: string[] = [];
  const onError = vi.fn();
  const source = new IosNativeMicrophoneCaptureSource({
    getAppState: async () => "foreground",
    supportsContinuousCapture: async () => true,
    start: (_configuration, sink) => ({
      ready: Promise.resolve(),
      stop: async ({ mode }) => {
        stopModes.push(mode);
        if (mode === "discard") return { finalPcmPacket: null };
        await sink.onPcmPacket({ sequenceNumber: 0, pcmBytes: fullPcmBytes });
        return { finalPcmPacket: { sequenceNumber: 1, pcmBytes: finalPcmBytes } };
      },
    }),
  });
  expect(await source.supportsContinuousCapture()).toBe(true);
  await source.start({
    capabilities,
    onChunk: async chunk => { delivered.push({ ...chunk, wavBytes: chunk.wavBytes.slice() }); },
    onError,
  });

  await source.stop();

  expect(stopModes).toEqual(["drain"]);
  expect(onError).not.toHaveBeenCalled();
  expect(delivered.map(({ sequenceNumber, durationMs }) => ({ sequenceNumber, durationMs }))).toEqual([
    { sequenceNumber: 0, durationMs: 20 },
    { sequenceNumber: 1, durationMs: 0.125 },
  ]);
  expect(delivered[0]?.wavBytes).toHaveLength(684);
  expect(delivered[0]?.wavBytes.subarray(44)).toEqual(expectedFullPcm);
  expect(delivered[1]?.wavBytes.subarray(44)).toEqual(Uint8Array.from([52, 18, 120, 86]));
  expect(fullPcmBytes.every(value => value === 0)).toBe(true);
  expect(finalPcmBytes.every(value => value === 0)).toBe(true);
});
