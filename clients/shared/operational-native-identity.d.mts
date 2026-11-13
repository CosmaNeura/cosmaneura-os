export const OPERATIONAL_NATIVE_PROFILE: "operational-beta-v1";
export const STAGING_NATIVE_PROFILE: "operational-staging-v1";
export const PRODUCTION_NATIVE_PROFILE: "operational-production-v1";
export const PRODUCTION_INSTALLATION_PROFILE: "production";
export const BETA_INSTALLATION_PROFILE: "beta";
export const STAGING_INSTALLATION_PROFILE: "staging";
/** Production-review API origin; required when profile is operational-production-v1. */
export const PRODUCTION_API_ORIGIN: "https://api.beta.cosmas.ai";

export type OperationalNativeIdentity = Readonly<{
  version: 1;
  profile: typeof OPERATIONAL_NATIVE_PROFILE | typeof STAGING_NATIVE_PROFILE | typeof PRODUCTION_NATIVE_PROFILE;
  client: "apple" | "desktop";
  apiOrigin: string;
  publishableKey: string;
  frontendOrigin: string;
  organizationId: string;
  audience: string;
}>;

export function dedicatedClerkHostsByProfile(): Readonly<Record<string, readonly string[]>>;
export function isAccountsDevClerkHost(hostname: unknown): boolean;
export function requireProductionInstallationProfile(
  identity: OperationalNativeIdentity | null | undefined,
  installationProfile: string | null | undefined,
): string | null | undefined;
export function validateOperationalNativeDataMode(
  value: unknown,
  identity: OperationalNativeIdentity | null | undefined,
): "synthetic" | "authorized_beta";
export function validateOperationalNativeIdentity(
  value: unknown,
  client: "apple" | "desktop",
  apiOrigin: string,
): OperationalNativeIdentity;
export function loadOperationalNativeIdentity(
  value: unknown,
  client: "apple" | "desktop",
  apiOrigin: string,
  installationProfile: string | null | undefined,
): OperationalNativeIdentity;
export function operationalNativeBundle(client: "apple" | "desktop"): string;
export function operationalNativeAuthSettings(value: unknown): {
  enabled: true;
  profile: OperationalNativeIdentity["profile"];
  publishableKey: string;
  frontendOrigin: string;
  organizationId: string;
  audience: string;
};
