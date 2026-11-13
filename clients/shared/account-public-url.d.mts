export const ACCOUNT_PUBLIC_URL_KEYS: ReadonlyArray<"VITE_PRIVACY_POLICY_URL" | "VITE_SUPPORT_URL">;
export function validAccountPublicUrl(value: unknown): string | null;
export function accountPublicUrlPassThrough(env: Record<string, unknown>): Record<string, string>;
