import {workspaceFetch} from './workspace-protocol';
import type { AuthenticatedWorkspaceIdentity, CaptureBotSelection } from "./workspace-api";
import { WORKSPACE_AUTHENTICATED_BUILD, WORKSPACE_BUILD, WorkspaceApiError } from "./workspace-api";
import { assertCurrentDesktopSession, workspaceAuthHeaders } from "./workspace-auth-headers";

// Founder-owned local qualification; review 2026-10-20. Real calendar activation remains separate.
export const SCHEDULING_BUILD = WORKSPACE_BUILD && WORKSPACE_AUTHENTICATED_BUILD &&
  import.meta.env.VITE_WORKSPACE_SCHEDULING_ENABLED === "true";
export type AvailabilityWindow = { starts_at: string; ends_at: string };
export type Availability = { workspace_id: string; label: string; source: "google_primary";
  window: AvailabilityWindow; checked_at: string; valid_until: string; slots: AvailabilityWindow[] };
const closed = (value: unknown, keys: string): value is Record<string, unknown> =>
  !!value && typeof value === "object" && !Array.isArray(value) &&
  Object.keys(value).sort().join(",") === keys.split(",").sort().join(",");
const instant = (value: unknown): number => typeof value === "string" &&
  /(?:Z|[+-]\d\d:\d\d)$/u.test(value) ? Date.parse(value) : NaN;
function unavailable(): never { throw new Error("Availability could not be confirmed. Refresh to try again."); }

export function validateAvailability(value: unknown, workspace: string, window: AvailabilityWindow): Availability {
  if (!closed(value, "workspace_id,label,source,window,checked_at,valid_until,slots") ||
      value.workspace_id !== workspace || value.source !== "google_primary" ||
      typeof value.label !== "string" || !value.label.trim() || value.label.length > 120 ||
      !closed(value.window, "starts_at,ends_at") ||
      instant(value.window.starts_at) !== instant(window.starts_at) ||
      instant(value.window.ends_at) !== instant(window.ends_at) ||
      !Number.isFinite(instant(value.checked_at)) || instant(value.checked_at) < Date.now() - 30000 ||
      instant(value.checked_at) > Date.now() + 5000 || instant(value.valid_until) !== instant(value.checked_at) + 60000 ||
      !Array.isArray(value.slots) || value.slots.length > 4096) unavailable();
  const seen = new Set<string>();
  for (const slot of value.slots) {
    if (!closed(slot, "starts_at,ends_at") || !Number.isFinite(instant(slot.starts_at)) || !Number.isFinite(instant(slot.ends_at)) ||
        instant(slot.starts_at) < instant(window.starts_at) || instant(slot.ends_at) > instant(window.ends_at) ||
        instant(slot.starts_at) >= instant(slot.ends_at)) unavailable();
    const key = `${instant(slot.starts_at)}/${instant(slot.ends_at)}`;
    if (seen.has(key)) unavailable();
    seen.add(key);
  }
  return value as Availability;
}

export async function readAvailability(workspace: string, identity: AuthenticatedWorkspaceIdentity,
  bot: CaptureBotSelection, window: AvailabilityWindow, signal?: AbortSignal): Promise<Availability> {
  if (!SCHEDULING_BUILD || !/^[0-9a-f-]{36}$/iu.test(workspace) ||
      !Number.isFinite(instant(window.starts_at)) || !Number.isFinite(instant(window.ends_at)) ||
      instant(window.ends_at) <= instant(window.starts_at) ||
      instant(window.ends_at) - instant(window.starts_at) > 31 * 86400000) unavailable();
  const base = import.meta.env.VITE_API_BASE?.trim().replace(/\/+$/, "") || "http://127.0.0.1:8000";
  const controller = new AbortController(), deadline = Date.now() + 30000;
  const abort = () => controller.abort();
  const check = () => {
    if (Date.now() >= deadline) abort();
    controller.signal.throwIfAborted();
  };
  const timer = setTimeout(abort, 30000);
  signal?.addEventListener("abort", abort, {once: true});
  if (signal?.aborted) abort();
  let onAbort: (() => void) | undefined;
  let response: Response | undefined;
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
  const cancel = (stream: {cancel: () => Promise<unknown>} | undefined | null) => {
    try { void stream?.cancel().catch(() => {}); } catch { /* Cleanup cannot hold the request open. */ }
  };
  const stopRead = () => cancel(reader);
  controller.signal.addEventListener("abort", stopRead, {once: true});
  const interrupted = new Promise<never>((_, reject) => {
    onAbort = () => reject(new Error("Availability request interrupted"));
    controller.signal.addEventListener("abort", onAbort, {once: true});
  });
  const wait = <T,>(promise: Promise<T>) => Promise.race([promise, interrupted]);
  try {
    check();
    const headers = await wait(workspaceAuthHeaders(identity, base));
    assertCurrentDesktopSession(identity); check();
    response = await wait(workspaceFetch(identity,`${base}/workspaces/${workspace}/scheduling/availability`, {
      method: "POST", cache: "no-store", credentials: "omit", redirect: "error", referrerPolicy: "no-referrer",
      headers, signal: controller.signal, body: JSON.stringify({bot, window}),
    }).then(result => {
      if (controller.signal.aborted) {cancel(result.body); unavailable();}
      return result;
    }));
    assertCurrentDesktopSession(identity); check();
    if (!response) unavailable();
    if (response.status === 401 || response.status === 403) {
      cancel(response.body); throw new WorkspaceApiError(response.status);
    }
    if (response.status !== 200 || response.headers.get("content-type")?.split(";", 1)[0].trim() !== "application/json" ||
        !response.headers.get("cache-control")?.split(",").some(v => v.trim().toLowerCase() === "no-store")) {
      cancel(response.body); unavailable();
    }
    reader = response.body?.getReader();
    if (!reader) unavailable();
    let length = 0; const chunks: Uint8Array[] = [];
    while (true) {
      check();
      const {done, value} = await wait(reader.read());
      check();
      if (done) break;
      length += value.length;
      if (length > 1048576) { cancel(reader); unavailable(); }
      chunks.push(value);
    }
    const bytes = new Uint8Array(length); let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
    assertCurrentDesktopSession(identity); check();
    const result = validateAvailability(JSON.parse(new TextDecoder("utf-8", {fatal: true}).decode(bytes)), workspace, window);
    check(); return result;
  } catch (cause) {
    if (cause instanceof WorkspaceApiError && [401, 403].includes(cause.status)) throw cause;
    return unavailable();
  }
  finally {
    if (onAbort) controller.signal.removeEventListener("abort", onAbort);
    cancel(reader);
    if (!reader) cancel(response?.body);
    try { reader?.releaseLock(); } catch { /* A discarded read may still settle. */ }
    clearTimeout(timer);
    signal?.removeEventListener("abort", abort); controller.signal.removeEventListener("abort", stopRead);
    controller.abort();
  }
}
