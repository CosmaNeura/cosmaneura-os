import {spawnSync} from "node:child_process";
import {existsSync, lstatSync, mkdirSync, readFileSync, writeFileSync} from "node:fs";
import {resolve} from "node:path";
import {fileURLToPath} from "node:url";
import {readVersionDocument} from "../web/scripts/version-json.mjs";

// Allowed synthetic web hosts. No registry, subscription, or deploy argument.
export const STAGING_WEB_ORIGIN = "https://staging.cosmas.ai";
const ALLOWED_WEB_HOSTS = ["staging.cosmas.ai", "beta.cosmas.ai"];

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

const REFUSED = /(?:^|[^a-z])(production|terraform|kubectl|azure|authorized_beta)(?:[^a-z]|$)|(?:^|\s)az(?:\s|$)/i;

function allowedWebOrigin(value) {
  let url;
  try {
    url = new URL(value);
  } catch {
    return null;
  }
  if (url.origin !== value || url.protocol !== "https:" || url.username || url.password) return null;
  if (!ALLOWED_WEB_HOSTS.includes(url.hostname)) return null;
  return url.origin;
}

function mentionsForbiddenHost(value) {
  const lower = value.toLowerCase();
  if (PRODUCTION_NAMES.some(name => lower.includes(name))) return true;
  if (lower.includes(".cosmaneura.com") || /(^|[^a-z0-9.])cosmaneura\.com([^a-z0-9.]|$)/.test(lower)) return true;
  // Apex only. staging.cosmas.ai and beta.cosmas.ai contain the suffix and stay allowed.
  return /(^|[^a-z0-9.])cosmas\.ai([^a-z0-9.]|$)/.test(lower);
}

export function assertStagingArguments(argv) {
  if (!Array.isArray(argv) || argv.some(arg => typeof arg !== "string")) {
    throw new Error("staging_web_package_refused");
  }
  if (REFUSED.test(argv.join("\n"))) throw new Error("staging_web_package_refused");
  for (const arg of argv) {
    if (/^https?:\/\//i.test(arg)) {
      if (!allowedWebOrigin(arg)) throw new Error("staging_web_package_refused");
      continue;
    }
    if (mentionsForbiddenHost(arg)) throw new Error("staging_web_package_refused");
  }
}

function selectedWebOrigin(argv) {
  const found = [];
  for (const arg of argv) {
    const origin = /^https?:\/\//i.test(arg) ? allowedWebOrigin(arg) : null;
    if (origin) found.push(origin);
  }
  const unique = [...new Set(found)];
  if (unique.length > 1) throw new Error("staging_web_package_refused");
  return unique[0] ?? STAGING_WEB_ORIGIN;
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
    target: selectedWebOrigin(argv),
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
    const flags = {};
    if (args.length % 2 !== 0) throw new Error("staging_web_package_refused");
    for (let index = 0; index < args.length; index += 2) {
      const name = args[index];
      if (!["--dist", "--output", "--target"].includes(name) || Object.hasOwn(flags, name)) {
        throw new Error("staging_web_package_refused");
      }
      flags[name] = args[index + 1];
    }
    if (!flags["--dist"] || !flags["--output"]) throw new Error("staging_web_package_refused");
    const receipt = packageStagingWeb({distDir: flags["--dist"], outputDir: flags["--output"], argv: args});
    process.stdout.write(`${JSON.stringify({target: receipt.target, deployed: receipt.deployed, commit: receipt.commit})}\n`);
  } catch {
    process.stderr.write("Staging web package refused.\n");
    process.exitCode = 1;
  }
}
