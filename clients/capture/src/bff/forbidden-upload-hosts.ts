/** Capture ciphertext must never upload to these vendor hosts. */
const FORBIDDEN_UPLOAD_HOST_SUFFIXES = ["assemblyai.com", "recall.ai"] as const;

export function isForbiddenCaptureUploadHost(hostname: string): boolean {
  const host = hostname.trim().toLowerCase();
  if (!host) return false;
  return FORBIDDEN_UPLOAD_HOST_SUFFIXES.some(
    (suffix) => host === suffix || host.endsWith(`.${suffix}`),
  );
}
