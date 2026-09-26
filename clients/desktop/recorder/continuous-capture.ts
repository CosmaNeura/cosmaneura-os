import type { CaptureSourceExtension } from "../../capture/src/configured/capture";
import { exactKeys } from "./native-process-wire";

/** Private auth-helper metadata. Neither this port nor its result is renderer IPC. */
export interface DesktopContinuousOwner {
  readonly runId: string;
  readonly generation: number;
  readonly hardMaximumChunks: number;
}
export interface DesktopContinuousPermit {
  readonly runId: string;
  readonly generation: number;
  readonly expiresAt: number;
  readonly previousCaptureAuthorizedUntil: number;
  readonly captureAuthorizedUntil: number;
  readonly maximumChunks: number;
}
export interface DesktopContinuousAuthority {
  getOwner(): DesktopContinuousOwner;
  authorize(extension: CaptureSourceExtension): Promise<unknown>;
}
export function continuousOwner(value: DesktopContinuousOwner): DesktopContinuousOwner {
  if (!value || !exactKeys({...value}, ["runId", "generation", "hardMaximumChunks"])
    || !uuid(value.runId) || !integer(value.generation, 1, 2_147_483_647)
    || !integer(value.hardMaximumChunks, 1, 360)) throw unavailable();
  return Object.freeze({...value});
}
export function continuousPermit(value: unknown, owner: DesktopContinuousOwner,
  generation: number, deadline: number, maximumChunks: number, request: CaptureSourceExtension,
  now = Date.now()): DesktopContinuousPermit {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw unavailable();
  const p = value as DesktopContinuousPermit;
  if (!exactKeys({...p}, ["runId", "generation", "expiresAt", "previousCaptureAuthorizedUntil", "captureAuthorizedUntil", "maximumChunks"])
    || p.runId !== owner.runId || p.generation !== generation + 1 || p.generation !== request.leaseGeneration
    || !integer(p.expiresAt, now + 1, deadline) || deadline <= now
    || !Number.isSafeInteger(p.previousCaptureAuthorizedUntil) || Math.abs(p.previousCaptureAuthorizedUntil - deadline) > 1
    || !Number.isSafeInteger(p.captureAuthorizedUntil) || p.captureAuthorizedUntil <= deadline
    || Math.abs(p.captureAuthorizedUntil - Date.parse(request.captureAuthorizedUntil)) > 1
    || !integer(p.maximumChunks, maximumChunks + 1, owner.hardMaximumChunks)
    || p.maximumChunks !== request.maximumChunks) throw unavailable();
  return Object.freeze({...p});
}
function uuid(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/u.test(value);
}
function integer(value: unknown, low: number, high: number): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= low && value <= high;
}
function unavailable(): Error { return new Error("desktop_continuation_unavailable"); }
