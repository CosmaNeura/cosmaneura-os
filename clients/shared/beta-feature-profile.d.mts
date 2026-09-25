export const BETA_FEATURE_PROFILE: "operational-beta-v1";
export const BETA_FEATURE_FLAGS: readonly string[];
export type BetaFeatureManifest = {
  version: 1; profile: typeof BETA_FEATURE_PROFILE; client: "web" | "desktop" | "apple";
  dataMode: "synthetic" | "authorized_beta"; apiOrigin: string; apiBase: string; pageOrigin: string;
  enabledFlags: string[]; captureMode: "synthetic" | "browser_microphone" | "ios_native";
  captureUploadOrigins: string[]; coreWebOrigin: string; athenaAccess: "read_only";
};
export function resolveBetaFeatureProfile(env: Record<string, string | undefined>): {
  env: Readonly<Record<string, string>>; manifest: BetaFeatureManifest;
};
export function validateNativeBetaProfile(manifest: unknown, expected: {
  client: "desktop" | "apple"; apiOrigin: string; coreWebOrigin: string;
  captureUploadOrigins: string[]; microphoneCapture?: boolean;
  renewableNativeCapture?: boolean; nativeRendererRecovery?: boolean; simulatorCustody?: boolean; deviceCustody?: boolean;
}): BetaFeatureManifest;

export function validateBetaFeatureManifest(manifest: unknown): BetaFeatureManifest;
