import {workspaceFetch} from './workspace-protocol';
import type {AuthenticatedWorkspaceIdentity, CaptureBotSelection} from "./workspace-api";
import {WORKSPACE_AUTHENTICATED_BUILD, WORKSPACE_BUILD, WorkspaceApiError} from "./workspace-api";
import {assertCurrentDesktopSession, workspaceAuthHeaders} from "./workspace-auth-headers";
import type {AvailabilityWindow} from "./scheduling-api";
import {validAppointmentRequest} from "./appointment-request";

export const APPOINTMENTS_BUILD = WORKSPACE_BUILD && WORKSPACE_AUTHENTICATED_BUILD &&
  import.meta.env.VITE_WORKSPACE_SCHEDULING_ENABLED === "true" && import.meta.env.VITE_WORKSPACE_APPOINTMENTS_ENABLED === "true";
export type AppointmentAction = "book" | "reschedule" | "cancel";
export type Appointment = AvailabilityWindow & {id: string; version: number; practitioner_id: string;
  location_id: string; appointment_type_id: string; patient_id: string; client_id: string | null;
  status: "booked" | "confirmed" | "arrived" | "fulfilled" | "cancelled" | "no_show"};
export type AppointmentItem = {workspace_id: string; ticket_id: string; ticket_version: number;
  state: "pending_approval" | "approved" | "rejected" | "sent"; revision_id: string; payload_hash: string;
  owner_id: string; operation_id: string | null; operation_status: "pending" | "running" | "unknown" | "succeeded" | "failed" | null;
  appointment_saved: boolean; calendar_state: "unconfirmed" | "pending" | "synced" | "failed" | "disconnected";
  dispatch_started: boolean; execution_error: "appointment_outcome_unconfirmed" | "withdrawn_before_dispatch" | null;
  result: null | {operation_id: string; request_hash: string; appointment: Appointment; observed_at: string; calendar_state: "pending" | "synced" | "failed" | "disconnected"};
  intent: {action: AppointmentAction; selection: Record<string, string>; expected: Appointment | null;
    slot: AvailabilityWindow | null; expires_at: string; google: null | {
      provider: "google"; calendar_id: "primary"; connection_id: string; connected_at: string; checked_at: string}}};
export type AppointmentSummary = {ticket_id: string; state: AppointmentItem["state"]; action: AppointmentAction; appointment_window: AvailabilityWindow; expires_at: string};
export type AppointmentCatalog = {workspace_id: string; items: AppointmentSummary[]; next_cursor: string | null};
export type CurrentAppointment = {workspace_id: string; label: string; appointment: Appointment | null; checked_at: string | null};
export type PrepareAppointment = {bot: CaptureBotSelection; action: AppointmentAction; slot: AvailabilityWindow | null; share: true; idempotency_key: string};
export type AppointmentChoice = {revision_id: string; payload_hash: string; choice: "approve" | "reject"};
export type ExecuteAppointment = {operation_id: string; revision_id: string; payload_hash: string; mode: "submit" | "reconcile" | "retry"};
const uuid = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/iu.test(v);
const closed = (v: unknown, names: string): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v) &&
  Object.keys(v).sort().join(",") === names.split(",").sort().join(",");
const instant = (v: unknown): v is string => typeof v === "string" && /(?:Z|[+-]\d\d:\d\d)$/u.test(v) && Number.isFinite(Date.parse(v));
const member = (v: unknown, values: string[]) => typeof v === "string" && values.includes(v);
const state = (v: unknown) => member(v, ["pending_approval", "approved", "rejected", "sent"]);
const action = (v: unknown) => member(v, ["book", "reschedule", "cancel"]);
const slot = (v: unknown): v is AvailabilityWindow => closed(v, "starts_at,ends_at") && instant(v.starts_at) && instant(v.ends_at) && Date.parse(v.starts_at) < Date.parse(v.ends_at);
function invalid(): never {throw new WorkspaceApiError(503);}
function appointment(v: unknown): v is Appointment {
  if (!closed(v, "id,version,practitioner_id,location_id,appointment_type_id,patient_id,client_id,starts_at,ends_at,status")) return false;
  return ["id", "practitioner_id", "location_id", "appointment_type_id", "patient_id"].every(k => uuid(v[k])) &&
    (v.client_id === null || uuid(v.client_id)) && Number.isSafeInteger(v.version) && Number(v.version) > 0 &&
    instant(v.starts_at) && instant(v.ends_at) && Date.parse(v.starts_at) < Date.parse(v.ends_at) &&
    member(v.status, ["booked", "confirmed", "arrived", "fulfilled", "cancelled", "no_show"]);
}
export function validateAppointmentItem(value: unknown, workspace: string, ticket?: string): AppointmentItem {
  if (!closed(value, "workspace_id,ticket_id,ticket_version,state,revision_id,payload_hash,intent,owner_id,operation_id,operation_status,appointment_saved,calendar_state,dispatch_started,execution_error,result") ||
    value.workspace_id !== workspace || !uuid(value.ticket_id) || (ticket && value.ticket_id !== ticket) ||
    !uuid(value.revision_id) || !uuid(value.owner_id) || !Number.isSafeInteger(value.ticket_version) || Number(value.ticket_version) < 1 ||
    !state(value.state) || typeof value.payload_hash !== "string" || !/^[0-9a-f]{64}$/u.test(value.payload_hash) ||
    typeof value.appointment_saved !== "boolean" || typeof value.dispatch_started !== "boolean" ||
    !member(value.calendar_state, ["unconfirmed", "pending", "synced", "failed", "disconnected"]) ||
    !(value.execution_error === null || value.execution_error === "appointment_outcome_unconfirmed" || value.execution_error === "withdrawn_before_dispatch") ||
    !(value.operation_id === null || uuid(value.operation_id)) ||
    !(value.operation_status === null || member(value.operation_status, ["pending", "running", "unknown", "succeeded", "failed"])) ||
    !closed(value.intent, "action,selection,expected,slot,google,expires_at")) invalid();
  const i = value.intent;
  if (!action(i.action) || !instant(i.expires_at) ||
    !closed(i.selection, "box_id,owner_id,practice_id,practitioner_id,location_id,appointment_type_id,expected_actor_id,patient_link_id,patient_id") ||
    !Object.values(i.selection).every(uuid) || i.selection.owner_id !== value.owner_id ||
    !(i.expected === null || appointment(i.expected)) || !(i.slot === null || slot(i.slot))) invalid();
  if (i.action === "book" ? i.expected !== null : i.expected === null) invalid();
  if (i.action === "cancel") {if (i.slot !== null || i.google !== null) invalid();}
  else if (!slot(i.slot) || !closed(i.google, "provider,calendar_id,connection_id,connected_at,checked_at") ||
    i.google.provider !== "google" || i.google.calendar_id !== "primary" || !uuid(i.google.connection_id) ||
    !instant(i.google.connected_at) || !instant(i.google.checked_at)) invalid();
  if (i.expected && ["patient_id", "practitioner_id", "location_id", "appointment_type_id"].some(k =>
    (i.expected as unknown as Record<string, unknown>)[k] !== (i.selection as Record<string, unknown>)[k])) invalid();
  if (value.state === "pending_approval" && (value.operation_id !== null || value.operation_status !== null || value.dispatch_started)) invalid();
  if (value.state === "approved" && (!uuid(value.operation_id) || !member(value.operation_status, ["pending", "running", "unknown"]) ||
      value.dispatch_started !== (value.operation_status !== "pending"))) invalid();
  if (value.state === "rejected" && (value.operation_id === null ? value.operation_status !== null : value.operation_status !== "failed")) invalid();
  if (value.state === "rejected" && value.dispatch_started) invalid();
  if (value.state === "sent") {
    const r = value.result;
    if (!value.appointment_saved || !value.dispatch_started || value.operation_status !== "succeeded" || !uuid(value.operation_id) ||
      !closed(r, "operation_id,request_hash,appointment,observed_at,calendar_state") || r.operation_id !== value.operation_id ||
      typeof r.request_hash !== "string" || !/^[0-9a-f]{64}$/u.test(r.request_hash) || !appointment(r.appointment) ||
      !instant(r.observed_at) || !member(r.calendar_state, ["pending", "synced", "failed", "disconnected"]) ||
      r.calendar_state !== value.calendar_state) invalid();
    const actual = r.appointment, before = i.expected as Appointment | null, window = (i.slot ?? i.expected) as AvailabilityWindow;
    if (["patient_id", "practitioner_id", "location_id", "appointment_type_id"].some(k =>
      (actual as unknown as Record<string, unknown>)[k] !== (i.selection as Record<string, unknown>)[k]) ||
      Date.parse(actual.starts_at) !== Date.parse(window.starts_at) || Date.parse(actual.ends_at) !== Date.parse(window.ends_at)) invalid();
    if (before ? actual.id !== before.id || actual.version !== before.version + 1 || actual.client_id !== before.client_id ||
      actual.status !== (i.action === "cancel" ? "cancelled" : before.status) :
      actual.version !== 1 || actual.status !== "booked" || actual.client_id !== null) invalid();
  } else if (value.appointment_saved || value.calendar_state !== "unconfirmed" || value.result !== null) invalid();
  if (value.execution_error === "withdrawn_before_dispatch" && value.state !== "rejected") invalid();
  if (value.execution_error === "appointment_outcome_unconfirmed" && !member(value.operation_status, ["unknown", "succeeded"])) invalid();
  return value as AppointmentItem;
}
function catalog(value: unknown, workspace: string): AppointmentCatalog {
  if (!closed(value, "workspace_id,items,next_cursor") || value.workspace_id !== workspace ||
      !Array.isArray(value.items) || value.items.length > 20 || !(value.next_cursor === null || uuid(value.next_cursor))) invalid();
  const seen = new Set<string>();
  for (const item of value.items) {
    if (!closed(item, "ticket_id,state,action,appointment_window,expires_at") || !uuid(item.ticket_id) || seen.has(item.ticket_id) ||
      !state(item.state) || !action(item.action) || !slot(item.appointment_window) || !instant(item.expires_at)) invalid();
    seen.add(item.ticket_id);
  }
  if (value.next_cursor !== null && (value.items.length !== 20 || value.items[19].ticket_id !== value.next_cursor)) invalid();
  return value as AppointmentCatalog;
}
async function request(workspace: string, identity: AuthenticatedWorkspaceIdentity, suffix: string,
  body?: unknown, signal?: AbortSignal): Promise<unknown> {
  if (!APPOINTMENTS_BUILD || !uuid(workspace)) invalid();
  const base = import.meta.env.VITE_API_BASE?.trim().replace(/\/+$/, "") || "http://127.0.0.1:8000";
  const controller = new AbortController(), abort = () => controller.abort();
  const timer = setTimeout(abort, 30000);
  signal?.addEventListener("abort", abort, {once: true}); if (signal?.aborted) abort();
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
  const cancel = () => {void reader?.cancel().catch(() => {});};
  controller.signal.addEventListener("abort", cancel, {once: true});
  let cancelWait: (() => void) | undefined;
  const stopped = new Promise<never>((_, reject) => {
    cancelWait = () => reject(new Error("cancelled"));
    controller.signal.addEventListener("abort", cancelWait, {once:true});
  });
  try {
    controller.signal.throwIfAborted();
    const headers = await Promise.race([workspaceAuthHeaders(identity, base), stopped]);
    controller.signal.throwIfAborted();
    const encoded = body === undefined ? undefined : JSON.stringify(body);
    if (encoded && new TextEncoder().encode(encoded).length > 2048) invalid();
    const response = await Promise.race([workspaceFetch(identity,base + "/workspaces/" + workspace + "/appointments" + suffix, {
      method: body === undefined ? "GET" : "POST", body: encoded, headers, signal: controller.signal,
      credentials: "omit", redirect: "error", cache: "no-store", referrerPolicy: "no-referrer"}).then(value => {
        if (controller.signal.aborted) {void value.body?.cancel().catch(() => {}); invalid();}
        return value;
      }), stopped]);
    if (response.status !== 200) {void response.body?.cancel().catch(() => {}); throw new WorkspaceApiError(response.status);}
    if (response.headers.get("content-type")?.split(";", 1)[0].trim() !== "application/json" ||
      !response.headers.get("cache-control")?.split(",").some(v => v.trim().toLowerCase() === "no-store")) {
      void response.body?.cancel().catch(() => {}); invalid();
    }
    reader = response.body?.getReader(); if (!reader) invalid();
    let size = 0; const chunks: Uint8Array[] = [];
    while (true) {
      controller.signal.throwIfAborted(); const next = await Promise.race([reader.read(), stopped]); controller.signal.throwIfAborted();
      if (next.done) break; size += next.value.length;
      if (size > 32768) {void reader.cancel().catch(() => {}); invalid();} chunks.push(next.value);
    }
    const bytes = new Uint8Array(size); let offset = 0;
    for (const part of chunks) {bytes.set(part, offset); offset += part.length;}
    assertCurrentDesktopSession(identity);
    return JSON.parse(new TextDecoder("utf-8", {fatal: true}).decode(bytes));
  } catch (cause) {if (cause instanceof WorkspaceApiError) throw cause; return invalid();}
  finally {
    if (cancelWait) controller.signal.removeEventListener("abort", cancelWait);
    void reader?.cancel().catch(() => {}); reader?.releaseLock(); clearTimeout(timer);
    signal?.removeEventListener("abort", abort); controller.signal.removeEventListener("abort", cancel);
  }
}
export const appointmentApi = {
  async catalog(workspace: string, identity: AuthenticatedWorkspaceIdentity, cursor?: string, signal?: AbortSignal) {
    if (cursor && !uuid(cursor)) invalid();
    return catalog(await request(workspace, identity, cursor ? "/pages/" + cursor : "", undefined, signal), workspace);
  },
  async current(workspace: string, identity: AuthenticatedWorkspaceIdentity, bot: CaptureBotSelection, signal?: AbortSignal): Promise<CurrentAppointment> {
    const result = await request(workspace, identity, "/current", {bot}, signal);
    if (!closed(result, "workspace_id,label,appointment,checked_at") || result.workspace_id !== workspace ||
      typeof result.label !== "string" || !result.label || result.label.length > 120 ||
      !(result.appointment === null || appointment(result.appointment)) ||
      (result.appointment === null ? result.checked_at !== null : !instant(result.checked_at) ||
        Date.parse(result.checked_at) < Date.now() - 30000 || Date.parse(result.checked_at) > Date.now() + 5000)) invalid();
    return result as CurrentAppointment;
  },
  async prepare(workspace: string, identity: AuthenticatedWorkspaceIdentity, body: PrepareAppointment, signal?: AbortSignal) {
    if (!validAppointmentRequest({kind:"prepare",body})) invalid();
    const result = validateAppointmentItem(await request(workspace, identity, "", body, signal), workspace);
    if (result.intent.action !== body.action || (body.slot && (!result.intent.slot ||
      Date.parse(body.slot.starts_at) !== Date.parse(result.intent.slot.starts_at) ||
      Date.parse(body.slot.ends_at) !== Date.parse(result.intent.slot.ends_at)))) invalid();
    return result;
  },
  async read(workspace: string, identity: AuthenticatedWorkspaceIdentity, ticket: string, signal?: AbortSignal) {
    if (!uuid(ticket)) invalid();
    return validateAppointmentItem(await request(workspace, identity, "/" + ticket, undefined, signal), workspace, ticket);
  },
  async decide(workspace: string, identity: AuthenticatedWorkspaceIdentity, ticket: string, body: AppointmentChoice, signal?: AbortSignal) {
    if (!validAppointmentRequest({kind:"decide",ticket,body})) invalid();
    const result = validateAppointmentItem(await request(workspace, identity, "/" + ticket + "/decide", body, signal), workspace, ticket);
    if (result.revision_id !== body.revision_id || result.payload_hash !== body.payload_hash) invalid();
    return result;
  },
  async execute(workspace: string, identity: AuthenticatedWorkspaceIdentity, ticket: string, body: ExecuteAppointment, signal?: AbortSignal) {
    if (!validAppointmentRequest({kind:"execute",ticket,body})) invalid();
    const result = validateAppointmentItem(await request(workspace, identity, "/" + ticket + "/execute", body, signal), workspace, ticket);
    if (result.operation_id !== body.operation_id || result.revision_id !== body.revision_id || result.payload_hash !== body.payload_hash) invalid();
    return result;
  },
};
