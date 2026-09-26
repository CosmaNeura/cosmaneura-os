import { AudioCaptureError } from "../audio/errors";
import type { CaptureSourceAuthority, CaptureSourceExtension } from "./source";

export interface CaptureSourceWindow extends CaptureSourceAuthority { readonly maximumChunks: number }
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u;
const integer = (value: number) => Number.isSafeInteger(value) && value > 0;
function requireWindow(condition: unknown): asserts condition {
  if (!condition) throw new AudioCaptureError("audio_capture_invalid_configuration");
}
function currentExpiry(expiresAtMs: number, now: number): boolean {
  return integer(expiresAtMs) && Number.isFinite(now) && expiresAtMs > now && expiresAtMs - now <= 905_000;
}
export function initialSourceWindow(authority: CaptureSourceAuthority, maximumChunks: number, now: number): CaptureSourceWindow {
  requireWindow(authority && Object.keys(authority).sort().join(",") === "expiresAtMs,generation,hardMaximumChunks,runId" &&
    typeof authority.runId === "string" && uuid.test(authority.runId) && integer(authority.generation) &&
    integer(maximumChunks) && integer(authority.hardMaximumChunks) && maximumChunks <= authority.hardMaximumChunks &&
    authority.hardMaximumChunks <= 360 && currentExpiry(authority.expiresAtMs, now));
  return { runId: authority.runId, generation: authority.generation, expiresAtMs: authority.expiresAtMs,
    hardMaximumChunks: authority.hardMaximumChunks, maximumChunks };
}
export function extendSourceWindow(current: CaptureSourceWindow, extension: CaptureSourceExtension, now: number): CaptureSourceWindow {
  requireWindow(extension && Object.keys(extension).sort().join(",") === "expiresAtMs,generation,maximumChunks,runId" &&
    extension.runId === current.runId && integer(extension.generation) && integer(extension.maximumChunks) &&
    extension.maximumChunks >= current.maximumChunks && extension.maximumChunks <= current.hardMaximumChunks &&
    current.expiresAtMs > now && currentExpiry(extension.expiresAtMs, now));
  if (extension.generation === current.generation) {
    requireWindow(extension.maximumChunks === current.maximumChunks && extension.expiresAtMs === current.expiresAtMs);
    return { ...current };
  }
  requireWindow(extension.generation === current.generation + 1 && extension.expiresAtMs > current.expiresAtMs);
  return { ...current, generation: extension.generation, expiresAtMs: extension.expiresAtMs, maximumChunks: extension.maximumChunks };
}
