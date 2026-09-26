import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { captureRawHash, captureRecoveryHash, validateCaptureSource, type CaptureSourceEnvelope } from "./source-contracts";
import { workingHash } from "./working-contracts";
import { recoveryRequestHash } from "./recovery-contracts";

const fixture = JSON.parse(readFileSync(new URL("../../../../tests/fixtures/capture_source.json", import.meta.url), "utf8")) as
  { base: CaptureSourceEnvelope; second: CaptureSourceEnvelope };
const now = new Date("2026-09-17T20:00:00Z");
const validate = (source: unknown) => validateCaptureSource(source, fixture.base.session_id, now);
async function rehash(source: CaptureSourceEnvelope) {
  const working = source.working_transcript;
  working.raw_transcript_sha256 = await captureRawHash(source.raw_transcript);
  working.working_sha256 = await workingHash({raw_transcript_sha256:working.raw_transcript_sha256,working_source:working.working_source});
  for (const row of source.recovery_history.recoveries) row.request_sha256 = await recoveryRequestHash(row.request);
  source.recovery_sha256 = await captureRecoveryHash(source.recovery_history);
  source.source_sha256 = await workingHash({raw_transcript_sha256:working.raw_transcript_sha256,
    working_sha256:working.working_sha256,recovery_sha256:source.recovery_sha256});
}
describe("Scribe qualified source fixture", () => {
  it("opens a complete long Unicode visit and keeps the per-segment limit", async () => {
    const source = structuredClone(fixture.base);
    const text = "🩺".repeat(100_000);
    for (const s of source.raw_transcript.segments) s.content = text;
    for (const s of source.working_transcript.working_source.segments) s.content = text;
    for (const s of source.working_transcript.working_transcript.segments) s.content = text;
    await rehash(source);
    expect((await validate(source)).raw_transcript.segments).toHaveLength(2);
    source.raw_transcript.segments[0].content += "x";
    source.working_transcript.working_source.segments[0].content += "x";
    source.working_transcript.working_transcript.segments[0].content += "x";
    await rehash(source);
    await expect(validate(source)).rejects.toThrow();
  });
  it.each([
    [0, "df87ec8a91e59d3f1f1578fced53b8f139d229cbd989056a7d950a70ed0ba626"],
    [1, "24d0d2b4c165a194c5c4c3f3e0416373b19d9e5167ea8b19b291d68e698dc505"],
    [-0, "c417f893b80bb02414d45594e1311e38a5c7ae06c0687e0b2c6cd2322efe1c35"],
    [0.00001, "8d3ece23166e12b4459999734115faa07a14bf5f585c85b48c4a4dbfba4982c5"],
    [0.0001, "57b19327054caa22ed2a5c380d22b17af10cf2faeea423be185b5d601c397a5d"],
    [0.12345678901234566, "58c722b101003b0478b28086ef1f6149dc47d951bf79fec32993ce51659a9300"],
    [1.234567890123456e-15, "4ffccbddf60fa4cdd9327fa18c0b6bfb924b523978321e59728df3ed058a00ca"],
  ] as const)("matches Python's canonical confidence float %s", async (confidence, expected) => {
    const raw = structuredClone(fixture.base.raw_transcript); raw.segments[0].confidence = confidence;
    expect(await captureRawHash(raw)).toBe(expected);
  });
  it.each(["base", "second"] as const)("accepts the actual producer's %s receipt without changing gap review", async key => {
    const value = await validate(fixture[key]);
    expect(value).toEqual(fixture[key]);
    expect(value.capture_incomplete).toBe(true);
    expect(value.recovery_history.recoveries[0].review_state).toBe("required");
  });
  it("accepts a sealed source without gaps and the same raw origin", async () => {
    const source = structuredClone(fixture.base);
    source.recovery_history.recoveries = []; source.capture_incomplete = false;
    await rehash(source);
    expect((await validate(source)).raw_transcript).toEqual(fixture.base.raw_transcript);
  });
  it.each([
    (s: CaptureSourceEnvelope) => { s.source_sha256 = "0".repeat(64); },
    (s: CaptureSourceEnvelope) => { s.recovery_sha256 = "0".repeat(64); },
    (s: CaptureSourceEnvelope) => { s.capture_incomplete = false; },
    (s: CaptureSourceEnvelope) => { s.raw_transcript.segments[0].content = "Changed raw text"; },
    (s: CaptureSourceEnvelope) => { s.recovery_history.recoveries[0].request.decision = "finish_capture"; },
    (s: CaptureSourceEnvelope) => { Object.assign(s, { extra: true }); },
    (s: CaptureSourceEnvelope) => { Object.assign(s, { capture_incomplete: 1 }); },
    (s: CaptureSourceEnvelope) => { s.raw_transcript.created_at = "2026-02-31T10:00:00Z"; },
  ])("rejects changed or malformed evidence", async mutate => {
    const source = structuredClone(fixture.base); mutate(source);
    await expect(validate(source)).rejects.toThrow();
  });
  it.each(["time", "speaker", "segment", "working_id", "version_one_text"])("rejects rehashed %s origin forgery", async kind => {
    const source = structuredClone(fixture.base), working = source.working_transcript;
    const segment = working.working_source.segments[0], projected = working.working_transcript.segments[0];
    if (kind === "time") { segment.start_ms = 1; projected.start_ms = 1; }
    if (kind === "speaker") { segment.speaker_id = crypto.randomUUID(); projected.speaker_id = segment.speaker_id; }
    if (kind === "segment") { segment.source_segment_id = crypto.randomUUID(); projected.source_segment_id = segment.source_segment_id; }
    if (kind === "working_id") working.working_transcript.working_transcript_id = crypto.randomUUID();
    if (kind === "version_one_text") { segment.content = "Forged version one"; projected.content = segment.content; }
    await rehash(source); await expect(validate(source)).rejects.toThrow();
  });
  it("rejects rehashed duplicate recovery records", async () => {
    const source = structuredClone(fixture.base);
    source.recovery_history.recoveries.push(structuredClone(source.recovery_history.recoveries[0]));
    await rehash(source); await expect(validate(source)).rejects.toThrow();
  });
  it("normalizes equivalent microsecond timestamps but rejects changed microseconds", async () => {
    const source = structuredClone(fixture.base);
    source.raw_transcript.created_at = "2026-09-17T06:00:00.000000-04:00";
    source.recovery_history.recoveries[0].request.observed_at = "2026-09-16T20:00:00.000000-04:00";
    await expect(validate(source)).resolves.toEqual(source);
    source.raw_transcript.created_at = "2026-09-17T10:00:00.000001Z";
    await expect(validate(source)).rejects.toThrow();
  });
  it("retains language blockers and rejects a false note-ready projection", async () => {
    const source = structuredClone(fixture.base), working = source.working_transcript;
    source.raw_transcript.language_code = "es-US";
    working.working_source.language_mode = "en-US+es-US";
    for (const item of working.working_source.segments) item.source_locale = "es-US";
    for (const item of working.working_transcript.segments) { item.source_locale = "es-US"; item.content = null; item.resolution = "unresolved"; }
    working.working_transcript.blockers = working.working_source.segments.map(s => ({source_segment_id:s.source_segment_id,code:"translation_missing"}));
    working.working_transcript.note_ready = false;
    await rehash(source); expect((await validate(source)).working_transcript.working_transcript.note_ready).toBe(false);
    working.working_transcript.note_ready = true;
    await expect(validate(source)).rejects.toThrow();
  });
});
