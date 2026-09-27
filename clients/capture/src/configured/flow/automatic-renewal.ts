import {canonicalCaptureTimestamp} from "../../bff/recovery-contracts";
import {normalizedLease, requireRenewal, validateRenewalRecord, validateStandardRenewalRecord,
  type CaptureRenewalRecord, type StandardCaptureRenewalRecord} from "../../flow/renewal-contract";
import {STANDARD_NATIVE_FLOW_RECORD_SCHEMA_VERSION, type ActiveCaptureState} from "./types";
export type ConfiguredRenewalRecord = CaptureRenewalRecord | StandardCaptureRenewalRecord;

/** Reuses Scribe's immutable intent/lease/batch validation. segmentId identifies
 * this local physical run; it creates no server recovery segment or permission. */
export interface AutomaticCaptureRenewal {
  readonly record: ConfiguredRenewalRecord;
  readonly state: "pending" | "extended" | "reconciled";
}
const same=(a:unknown,b:unknown):boolean=>JSON.stringify(a)===JSON.stringify(b);
export function validateConfiguredRenewalRecord(record: unknown, now = new Date(),
  channel: "microphone" | "mixed" | "system_audio" = "microphone"): ConfiguredRenewalRecord {
  const version = (record as ConfiguredRenewalRecord | null)?.intent?.schemaVersion;
  return version === 2 ? validateStandardRenewalRecord(record, now, channel)
    : validateRenewalRecord(record, now, channel);
}
function matchesPolicy(active: ActiveCaptureState, record: ConfiguredRenewalRecord): boolean {
  return active.schemaVersion === STANDARD_NATIVE_FLOW_RECORD_SCHEMA_VERSION
    ? active.captureProfile === undefined && record.intent.schemaVersion === 2
    : !!active.captureProfile && record.intent.schemaVersion === 1
      && record.intent.profileReceiptId === active.captureProfile.receipt_id;
}
export function sameLease(a:ActiveCaptureState["lease"],b:ActiveCaptureState["lease"]):boolean {
  return same(normalizedLease(a,a.session_id),normalizedLease(b,b.session_id));
}
export function validateAutomaticRenewal(active:ActiveCaptureState):void {
  const value=active.automaticRenewal;
  if(!value)return;
  requireRenewal([6,STANDARD_NATIVE_FLOW_RECORD_SCHEMA_VERSION].includes(active.schemaVersion) && active.reviewAfterUpload===true
    && Object.keys(value).sort().join(",")==="record,state" && ["pending","extended","reconciled"].includes(value.state));
  const record=validateConfiguredRenewalRecord(value.record,new Date(),active.channel??"microphone"),intent=record.intent;
  requireRenewal(intent.sessionId===active.sessionId && matchesPolicy(active,record)
    && sameLease(active.lease,record.lease??intent.priorLease));
  if(value.state==="pending") {
    requireRenewal(active.captureAuthorizedUntil!==null
      && canonicalCaptureTimestamp(active.captureAuthorizedUntil)===intent.priorCaptureAuthorizedUntil);
  } else if(value.state==="extended") {
    requireRenewal(record.lease && record.reservations && active.captureAuthorizedUntil!==null
      && canonicalCaptureTimestamp(active.captureAuthorizedUntil)===record.lease.expires_at);
  } else requireRenewal(active.captureAuthorizedUntil===null && active.phase!=="ready" && active.phase!=="recording");
}

/** Returns the narrowly allowed lease/deadline transition for the parent store. */
export function automaticRenewalProgression(existing:ActiveCaptureState,next:ActiveCaptureState):boolean {
  const before=existing.automaticRenewal,after=next.automaticRenewal;
  if(same(before,after))return false;
  if(!after){
    requireRenewal(before && before.state!=="pending" && existing.phase==="paused" && next.phase==="paused"
      && sameLease(existing.lease,next.lease));
    return false;
  }
  const record=after.record;
  if(!before || !same(validateConfiguredRenewalRecord(before.record,new Date(),existing.channel??"microphone").intent,
    validateConfiguredRenewalRecord(record,new Date(),next.channel??"microphone").intent)) {
    requireRenewal((!before || before.state==="extended") && existing.phase==="recording" && next.phase==="recording"
      && after.state==="pending" && record.lease===null && record.reservations===null
      && sameLease(existing.lease,record.intent.priorLease) && sameLease(existing.lease,next.lease)
      && existing.captureAuthorizedUntil!==null
      && canonicalCaptureTimestamp(existing.captureAuthorizedUntil)===record.intent.priorCaptureAuthorizedUntil
      && existing.recordedChunks<record.intent.firstSequenceNumber && matchesPolicy(existing,record));
    return true;
  }
  requireRenewal(before.state==="pending" &&
    (before.record.lease===null || same(before.record.lease,record.lease)) &&
    (before.record.reservations===null || same(before.record.reservations,record.reservations)));
  return true;
}
