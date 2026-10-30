// @vitest-environment node
import assert from "node:assert/strict";
import {execFileSync} from "node:child_process";
import {mkdtempSync, mkdirSync, readFileSync, writeFileSync} from "node:fs";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {packageStagingWeb, STAGING_WEB_ORIGIN} from "../../scripts/package-staging-web.mjs";

const {test} = await import(process.env.VITEST ? "vitest" : "node:test");
const commit = "0123456789abcdef0123456789abcdef01234567";

function distWithVersion() {
  const root = mkdtempSync(join(tmpdir(), "staging-web-"));
  const dist = join(root, "dist");
  mkdirSync(dist);
  writeFileSync(join(dist, "index.html"), "<!doctype html><title>invented</title>\n");
  writeFileSync(join(dist, "version.json"), `${JSON.stringify({
    commit,
    built_at: "2026-10-30T17:48:00Z",
  }, null, 2)}\n`);
  return {root, dist};
}

test("the packager writes a local nginx bundle and does not deploy it", () => {
  const {root, dist} = distWithVersion();
  const output = join(root, "out");
  const receipt = packageStagingWeb({distDir: dist, outputDir: output, argv: ["--dist", dist, "--output", output]});
  assert.equal(receipt.target, STAGING_WEB_ORIGIN);
  assert.equal(receipt.deployed, false);
  assert.equal(receipt.pushed, false);
  assert.equal(receipt.production, false);
  assert.equal(receipt.server, "nginx");
  assert.equal(receipt.commit, commit);
  const listing = execFileSync("tar", ["-tzf", join(output, receipt.archive)], {encoding: "utf8"});
  assert.match(listing, /(^|\n)\.\/version\.json\n|(^|\n)version\.json\n/);
  const packed = execFileSync("tar", ["-xOzf", join(output, receipt.archive), "./version.json"], {encoding: "utf8"});
  assert.equal(JSON.parse(packed).commit, commit);
  assert.equal(JSON.parse(readFileSync(join(output, "receipt.json"), "utf8")).deployed, false);
});

test("the packager refuses production names and has no other origin or remote command", () => {
  const {root, dist} = distWithVersion();
  const refused = [
    ["--target", "https://app.cosmaneura.com"],
    ["--target", "https://staging-app.cosmaneura.com"],
    ["--target", "https://bot.cosmas.ai"],
    ["--target", "https://app.cosmas.ai"],
    ["https://api.cosmas.ai"],
    ["terraform", "apply"],
    ["azure", "containerapp"],
    ["production"],
  ];
  for (const argv of refused) {
    assert.throws(() => packageStagingWeb({distDir: dist, outputDir: join(root, argv.join("-")), argv}), /staging_web_package_refused/);
  }
  const source = readFileSync(new URL("../../scripts/package-staging-web.mjs", import.meta.url), "utf8");
  assert.deepEqual([...source.matchAll(/https:\/\/[a-z0-9.-]+/g)].map(match => match[0]), [STAGING_WEB_ORIGIN]);
  assert.equal(source.split("spawnSync(").length, 2);
  assert.match(source, /spawnSync\("tar"/);
  assert.doesNotMatch(source, /spawnSync\(\s*"(?!tar")/);
});
