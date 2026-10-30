import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import {resolveHostedWorkspace} from "../clients/shared/hosted-workspace-config.mjs";
import {resolveBetaFeatureProfile} from "../clients/shared/beta-feature-profile.mjs";
import {resolveCommitSha, utcStamp, versionAsset} from "./scripts/version-json.mjs";

let hostedBuild: ReturnType<typeof resolveHostedWorkspace> = null;
let featureBuild: ReturnType<typeof resolveBetaFeatureProfile> | null = null;

function resolveBuildSha(env: Record<string, string>) {
  const configured = env.VITE_BUILD_SHA?.trim();
  if (configured && /^[0-9a-f]{7,40}$/i.test(configured)) return configured.slice(0, 40).toLowerCase();
  try {
    return execFileSync("git", ["rev-parse", "--short=7", "HEAD"], {
      cwd: fileURLToPath(new URL("..", import.meta.url)),
      encoding: "utf8",
    }).trim();
  } catch {
    return "dev";
  }
}

export default defineConfig(({mode}) => {
  const env = loadEnv(mode, fileURLToPath(new URL("./", import.meta.url)), "VITE_");
  const buildSha = resolveBuildSha(env);
  return {
  define: {
    "import.meta.env.VITE_BUILD_SHA": JSON.stringify(buildSha),
  },
  plugins: [react(), {
    name: "cosmas-hosted-workspace",
    apply: "build",
    config(config, {mode: buildMode}) {
      const buildEnv = loadEnv(buildMode, config.envDir ?? fileURLToPath(new URL('./', import.meta.url)), "VITE_");
      featureBuild = null;
      hostedBuild = null;
      if (buildEnv.VITE_WORKSPACE_HOSTED_ENABLED === 'true' || buildEnv.VITE_WORKSPACE_FEATURE_PROFILE) {
        featureBuild = resolveBetaFeatureProfile(buildEnv);
        hostedBuild = resolveHostedWorkspace(featureBuild.env);
        return {define: {
          "import.meta.env.VITE_BUILD_SHA": JSON.stringify(resolveBuildSha(buildEnv)),
          ...Object.fromEntries(Object.entries(featureBuild.env).map(([key, value]) =>
            [`import.meta.env.${key}`, JSON.stringify(value)])),
        }};
      }
    },
    configResolved(config) {
      if (featureBuild) for (const [key, value] of Object.entries(featureBuild.env)) {
        if (config.define[`import.meta.env.${key}`] !== JSON.stringify(value)) {
          throw new Error(`Beta feature definition changed: ${key}`);
        }
      }
    },
    generateBundle() {
      this.emitFile(versionAsset({commit: resolveCommitSha(), builtAt: utcStamp()}));
      if (hostedBuild) this.emitFile({type: "asset", fileName: "cosmas-workspace-build.json",
        source: JSON.stringify({version: 1, ...hostedBuild}) + "\n"});
      if (featureBuild) this.emitFile({type: 'asset', fileName: 'cosmas-beta-features.json',
        source: JSON.stringify(featureBuild.manifest) + '\n'});
    },
  }],
  resolve: { alias: {
    "@cosmaneura-scribe/capture-protocol": fileURLToPath(new URL("../clients/capture/protocol/generated.ts", import.meta.url)),
    "@cosmaneura-scribe/capacitor-ios-pcm": fileURLToPath(new URL("../clients/capture/plugins/ios-pcm/index.ts", import.meta.url)),
    "@cosmaneura-scribe/capacitor-secure-queue": fileURLToPath(new URL("../clients/capture/plugins/secure-queue/index.ts", import.meta.url)),
  } },
  server: { port: 5173 },
  test: { alias:{"@cosmaneura-scribe/capture-preview-domain":fileURLToPath(new URL("../clients/capture/test-fixtures/preview-constants.ts",import.meta.url))}, environment: "jsdom", globals: true, setupFiles:['./vitest.setup.ts'] },
};
});
