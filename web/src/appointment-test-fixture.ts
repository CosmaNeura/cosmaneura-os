import type {Appointment, AppointmentAction, AppointmentCatalog, AppointmentItem} from "./appointment-api";
export const id = (n: number) => "00000000-0000-4000-8000-" + String(n).padStart(12, "0");
export const workspaceId = id(1);
export function linked(): Appointment {
  return {id: id(20), version: 3, practitioner_id: id(5), location_id: id(6), appointment_type_id: id(7),
    patient_id: id(9), client_id: null, starts_at: new Date(Date.now()+86400000).toISOString(),
    ends_at: new Date(Date.now()+88200000).toISOString(), status: "confirmed"};
}
export function item(state: AppointmentItem["state"] = "pending_approval", action: AppointmentAction = "book"): AppointmentItem {
  return {workspace_id: workspaceId, ticket_id: id(10), ticket_version: state === "pending_approval" ? 1 : 2,
    state, revision_id: id(11), payload_hash: "a".repeat(64), owner_id: id(3),
    operation_id: state === "pending_approval" ? null : id(12), operation_status: state === "pending_approval" ? null : state === "approved" ? "pending" : "failed",
    appointment_saved: false, calendar_state: "unconfirmed", dispatch_started: false, execution_error: null, result: null, intent: {action, selection: {
      box_id: id(2), owner_id: id(3), practice_id: id(4), practitioner_id: id(5), location_id: id(6),
      appointment_type_id: id(7), expected_actor_id: id(8), patient_link_id: id(13), patient_id: id(9)},
      expected: action === "book" ? null : linked(),
      slot: action === "cancel" ? null : {starts_at: new Date(Date.now()+172800000).toISOString(), ends_at: new Date(Date.now()+174600000).toISOString()},
      google: action === "cancel" ? null : {provider: "google", calendar_id: "primary", connection_id: id(14),
        connected_at: new Date(Date.now()-86400000).toISOString(), checked_at: new Date().toISOString()},
      expires_at: new Date(Date.now()+180000).toISOString()}};
}
export function catalog(saved: AppointmentItem[] = []): AppointmentCatalog {
  return {workspace_id: workspaceId, items: saved.map(v => ({ticket_id:v.ticket_id, state:v.state,
    action:v.intent.action, appointment_window: {starts_at:(v.intent.slot??v.intent.expected!).starts_at,
      ends_at:(v.intent.slot??v.intent.expected!).ends_at}, expires_at:v.intent.expires_at})), next_cursor:null};
}
export function saved(action: AppointmentAction = "book"): AppointmentItem {
  const value = item("approved", action), before = value.intent.expected, slot = value.intent.slot ?? before!;
  value.state = "sent"; value.operation_status = "succeeded"; value.appointment_saved = true;
  value.dispatch_started = true; value.calendar_state = "pending";
  value.result = {operation_id:value.operation_id!, request_hash:"b".repeat(64), observed_at:new Date().toISOString(), calendar_state:"pending",
    appointment:{...(before ?? linked()), id:before?.id ?? id(30), version:before ? before.version+1 : 1,
      starts_at:slot.starts_at, ends_at:slot.ends_at, status:action === "cancel" ? "cancelled" : before?.status ?? "booked"}};
  return value;
}
