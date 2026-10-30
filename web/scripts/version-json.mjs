import {execFileSync} from "node:child_process";
import {fileURLToPath} from "node:url";

const COMMIT = /^[0-9a-f]{40}$/;
const STAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;
const repoRoot = fileURLToPath(new URL("../..", import.meta.url));

export function utcStamp(date = new Date()) {
  return date.toISOString().replace(/\.\d{3}Z$/, "Z");
}

export function readGitHead(root = repoRoot) {
  try {
    const sha = execFileSync("git", ["rev-parse", "HEAD"], {
      cwd: root,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim().toLowerCase();
    return COMMIT.test(sha) ? sha : "";
  } catch {
    return "";
  }
}

export function resolveCommitSha(env = process.env, gitSha = readGitHead()) {
  const configured = String(env.VITE_BUILD_SHA ?? "").trim().toLowerCase();
  const fromEnv = COMMIT.test(configured) ? configured : "";
  const fromGit = COMMIT.test(gitSha) ? gitSha : "";
  if (fromGit && fromEnv && fromGit !== fromEnv) {
    throw new Error("VITE_BUILD_SHA does not match git HEAD");
  }
  const commit = fromGit || fromEnv;
  if (!commit) throw new Error("version.json requires a 40-character commit SHA");
  return commit;
}

export function versionDocument({commit, builtAt}) {
  if (typeof commit !== "string" || !COMMIT.test(commit)) {
    throw new Error("version.json requires a 40-character commit SHA");
  }
  if (typeof builtAt !== "string" || !STAMP.test(builtAt)) {
    throw new Error("version.json requires a UTC build time");
  }
  return {commit, built_at: builtAt};
}

export function readVersionDocument(raw) {
  const value = typeof raw === "string" ? JSON.parse(raw) : raw;
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("version.json is not an object");
  }
  if (Object.keys(value).sort().join(",") !== "built_at,commit") {
    throw new Error("version.json has an unexpected shape");
  }
  return versionDocument({commit: value.commit, builtAt: value.built_at});
}

export function versionAsset({commit, builtAt}) {
  const document = versionDocument({commit, builtAt});
  return {type: "asset", fileName: "version.json", source: `${JSON.stringify(document, null, 2)}\n`};
}
