import {spawnSync} from "node:child_process";
import {existsSync, lstatSync, mkdirSync, readFileSync, writeFileSync} from "node:fs";
import {resolve} from "node:path";
import {fileURLToPath} from "node:url";
import {readVersionDocument} from "../web/scripts/version-json.mjs";

// The only origin this helper knows. It has no host, registry, or subscription argument.
export const STAGING_WEB_ORIGIN = "https://staging.cosmas.ai";

export const PRODUCTION_NAMES = [
  "app.cosmaneura.com",
  "staging-app.cosmaneura.com",
  "chat.cosmaneura.com",
  "staging-chat.cosmaneura.com",
  "bot.cosmas.ai",
  "app.cosmas.ai",
  "api.cosmas.ai",
  "www.cosmas.ai",
];

const REFUSED = /(?:^|[^a-z])(production|terraform|kubectl|azure)(?:[^a-z]|$)|(?:^|\s)az(?:\s|$)/i;

export function assertStagingArguments(argv) {
  if (!Array.isArray(argv) || argv.some(arg => typeof arg !== "string")) {
    throw new Error("staging_web_package_refused");
  }
  if (REFUSED.test(argv.join("\n"))) throw new Error("staging_web_package_refused");
  for (const arg of argv) {
    const lower = arg.toLowerCase();
    if (PRODUCTION_NAMES.some(name => lower.includes(name))) {
      throw new Error("staging_web_package_refused");
    }
    if (/^https?:\/\//i.test(arg)) {
      let url;
      try {
        url = new URL(arg);
      } catch {
        throw new Error("staging_web_package_refused");
      }
      if (url.origin !== STAGING_WEB_ORIGIN) throw new Error("staging_web_package_refused");
    }
  }
}

function regularDirectory(path) {
  const info = lstatSync(path);
  if (!info.isDirectory() || info.isSymbolicLink()) throw new Error("staging_web_dist_required");
}

export function packageStagingWeb({distDir, outputDir, argv = []}) {
  assertStagingArguments(argv);
  const dist = resolve(distDir);
  const output = resolve(outputDir);
  regularDirectory(dist);
  if (existsSync(output)) throw new Error("staging_web_output_must_be_new");
  const versionPath = resolve(dist, "version.json");
  const versionInfo = lstatSync(versionPath);
  if (!versionInfo.isFile() || versionInfo.isSymbolicLink()) throw new Error("staging_web_dist_required");
  const document = readVersionDocument(readFileSync(versionPath, "utf8"));
  const archiveName = `cosmabot-web-${document.commit}.tar.gz`;
  mkdirSync(output, {mode: 0o700});
  const archivePath = resolve(output, archiveName);
  const packed = spawnSync("tar", ["-czf", archivePath, "-C", dist, "."], {stdio: "pipe"});
  if (packed.status !== 0) throw new Error("staging_web_archive_failed");
  const receipt = {
    schema: "cosmabot-staging-web-package/v1",
    target: STAGING_WEB_ORIGIN,
    commit: document.commit,
    built_at: document.built_at,
    archive: archiveName,
    deployed: false,
    pushed: false,
    production: false,
    server: "nginx",
    notes: "Local staging web package only. Does not copy files to a host, reload nginx, push an image, or apply infrastructure.",
  };
  writeFileSync(resolve(output, "receipt.json"), `${JSON.stringify(receipt, null, 2)}\n`, {mode: 0o600});
  return receipt;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2);
  try {
    assertStagingArguments(args);
    if (args.length !== 4 || args[0] !== "--dist" || args[2] !== "--output") {
      throw new Error("staging_web_package_refused");
    }
    const receipt = packageStagingWeb({distDir: args[1], outputDir: args[3], argv: args});
    process.stdout.write(`${JSON.stringify({target: receipt.target, deployed: receipt.deployed, commit: receipt.commit})}\n`);
  } catch {
    process.stderr.write("Staging web package refused.\n");
    process.exitCode = 1;
  }
}
