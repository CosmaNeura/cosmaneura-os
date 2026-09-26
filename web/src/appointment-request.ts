import type {AppointmentChoice,ExecuteAppointment,PrepareAppointment} from "./appointment-api";

export type AppointmentRequest={kind:"prepare";body:PrepareAppointment}|{kind:"decide";ticket:string;body:AppointmentChoice}|
  {kind:"execute";ticket:string;body:ExecuteAppointment};
const closed=(value:unknown,keys:string):value is Record<string,unknown>=>!!value&&typeof value==="object"&&!Array.isArray(value)&&Object.keys(value).sort().join(",")===keys.split(",").sort().join(",");
const uuid=(value:unknown):value is string=>typeof value==="string"&&/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(value);
const instant=(value:unknown):value is string=>typeof value==="string"&&/(?:Z|[+-]\d\d:\d\d)$/.test(value)&&Number.isFinite(Date.parse(value));
export const validAppointmentSlot=(value:unknown)=>closed(value,"starts_at,ends_at")&&instant(value.starts_at)&&instant(value.ends_at)&&Date.parse(value.starts_at)<Date.parse(value.ends_at);
export const validAppointmentBot=(value:unknown)=>closed(value,"address,team_revision")&&typeof value.address==="string"&&
  (["scribe","visit_prep","follow_up","chief"].includes(value.address)||uuid(value.address))&&Number.isSafeInteger(value.team_revision)&&Number(value.team_revision)>0;
export function validAppointmentRequest(value:unknown):value is AppointmentRequest {
  if(closed(value,"kind,body")&&value.kind==="prepare") {
    const body=value.body;
    return closed(body,"bot,action,slot,share,idempotency_key")&&validAppointmentBot(body.bot)&&typeof body.action==="string"&&["book","reschedule","cancel"].includes(body.action)&&
      (body.action==="cancel"?body.slot===null:validAppointmentSlot(body.slot))&&body.share===true&&uuid(body.idempotency_key);
  }
  if(closed(value,"kind,ticket,body")&&value.kind==="decide") {
    const body=value.body;
    return uuid(value.ticket)&&closed(body,"revision_id,payload_hash,choice")&&uuid(body.revision_id)&&typeof body.payload_hash==="string"&&
      /^[a-f0-9]{64}$/.test(body.payload_hash)&&(body.choice==="approve"||body.choice==="reject");
  }
  if(closed(value,"kind,ticket,body")&&value.kind==="execute") {
    const body=value.body;
    return uuid(value.ticket)&&closed(body,"operation_id,revision_id,payload_hash,mode")&&uuid(body.operation_id)&&uuid(body.revision_id)&&
      typeof body.payload_hash==="string"&&/^[a-f0-9]{64}$/.test(body.payload_hash)&&
      (body.mode==="submit"||body.mode==="reconcile"||body.mode==="retry");
  }
  return false;
}
export const appointmentRequestKey=(value:AppointmentRequest)=>value.kind==="prepare"?value.body.idempotency_key:
  value.kind==="execute"?value.body.operation_id:value.body.revision_id;
