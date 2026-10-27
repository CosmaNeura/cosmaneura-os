export const BETA_FEATURE_PROFILE: "operational-beta-v1";
export const NATIVE_STAGING_FEATURE_PROFILE: "first-owner-staging-v1";
export const STANDALONE_FEATURE_PROFILE: "standalone-practice-v1";
export const BETA_FEATURE_FLAGS: readonly string[];
export const STANDALONE_FEATURE_FLAGS: readonly string[];
export type BetaFeatureManifest = {
  version: 1; profile: typeof BETA_FEATURE_PROFILE | typeof NATIVE_STAGING_FEATURE_PROFILE | typeof STANDALONE_FEATURE_PROFILE; client: "web" | "desktop" | "apple";
  dataMode: "synthetic" | "authorized_beta"; apiOrigin: string; apiBase: string; pageOrigin: string;
  enabledFlags: string[]; captureMode: "synthetic" | "browser_microphone" | "ios_native" | "disabled";
  captureUploadOrigins: string[]; coreWebOrigin: string; athenaAccess: "read_only" | "disabled";
  disabledFlags?: string[]; authentication?: "verified_hosted_identity"; platformAccess?: "disabled";
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
