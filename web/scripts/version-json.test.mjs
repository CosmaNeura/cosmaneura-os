// @vitest-environment node
import assert from "node:assert/strict";
import {readVersionDocument, resolveCommitSha, utcStamp, versionAsset, versionDocument} from "./version-json.mjs";

const {test} = await import(process.env.VITEST ? "vitest" : "node:test");
const commit = "0123456789abcdef0123456789abcdef01234567";

test("version.json carries the full commit and a UTC build time", () => {
  const builtAt = utcStamp(new Date("2026-10-30T17:48:00.123Z"));
  assert.equal(builtAt, "2026-10-30T17:48:00Z");
  const document = versionDocument({commit, builtAt});
  assert.deepEqual(document, {commit, built_at: builtAt});
  const asset = versionAsset({commit, builtAt});
  assert.equal(asset.fileName, "version.json");
  assert.equal(asset.type, "asset");
  assert.deepEqual(readVersionDocument(asset.source), document);
});

test("version.json refuses a short, empty, or mismatched commit", () => {
  assert.throws(() => versionDocument({commit: "0123456", builtAt: "2026-10-30T17:48:00Z"}));
  assert.throws(() => versionDocument({commit, builtAt: "2026-10-30T17:48:00.123Z"}));
  assert.throws(() => readVersionDocument({commit, built_at: "2026-10-30T17:48:00Z", note: "extra"}));
  assert.equal(resolveCommitSha({VITE_BUILD_SHA: commit.toUpperCase()}, ""), commit);
  assert.equal(resolveCommitSha({}, commit), commit);
  assert.throws(() => resolveCommitSha({VITE_BUILD_SHA: "abcdef0"}, ""));
  assert.throws(() => resolveCommitSha({VITE_BUILD_SHA: `${"a".repeat(40)}`}, `${"b".repeat(40)}`));
});
