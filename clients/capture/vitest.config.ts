import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: { alias: {
    "@cosmaneura-scribe/capture-protocol": fileURLToPath(new URL("./protocol/generated.ts", import.meta.url)),
    "@cosmaneura-scribe/capture-preview-domain": fileURLToPath(new URL("./test-fixtures/preview-constants.ts", import.meta.url)),
    "@cosmaneura-scribe/capacitor-ios-pcm": fileURLToPath(new URL("./plugins/ios-pcm/index.ts", import.meta.url)),
    "@cosmaneura-scribe/capacitor-secure-queue": fileURLToPath(new URL("./plugins/secure-queue/index.ts", import.meta.url)),
  } },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
