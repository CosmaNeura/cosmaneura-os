/** Synthetic build identity for Settings/footer. Never include secrets or PHI. */

const SHA = /^[0-9a-f]{7,40}$/i;

export function buildShortSha(raw = import.meta.env.VITE_BUILD_SHA): string {
  const value = raw?.trim() ?? "";
  if (!SHA.test(value)) return "dev";
  return value.slice(0, 7).toLowerCase();
}

export function buildVersionLabel(raw = import.meta.env.VITE_BUILD_SHA): string {
  return `Build ${buildShortSha(raw)}`;
}
