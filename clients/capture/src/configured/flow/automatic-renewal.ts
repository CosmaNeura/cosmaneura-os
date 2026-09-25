import {canonicalCaptureTimestamp} from "../../bff/recovery-contracts";
import {normalizedLease, requireRenewal, sameRenewalIntent, validateRenewalRecord,
  type CaptureRenewalRecord} from "../../flow/renewal-contract";
import type {ActiveCaptureState} from "./types";

/** Reuses Scribe's immutable intent/lease/batch validation. segmentId identifies
 * this local physical run; it creates no server recovery segment or permission. */
export interface AutomaticCaptureRenewal {
  readonly record: CaptureRenewalRecord;
  readonly state: "pending" | "extended" | "reconciled";
}
const same=(a:unknown,b:unknown):boolean=>JSON.stringify(a)===JSON.stringify(b);
export function sameLease(a:ActiveCaptureState["lease"],b:ActiveCaptureState["lease"]):boolean {
  return same(normalizedLease(a,a.session_id),normalizedLease(b,b.session_id));
}
export function validateAutomaticRenewal(active:ActiveCaptureState):void {
  const value=active.automaticRenewal;
  if(!value)return;
  requireRenewal(active.schemaVersion===6 && active.reviewAfterUpload===true && active.captureProfile
    && Object.keys(value).sort().join(",")==="record,state" && ["pending","extended","reconciled"].includes(value.state));
  const record=validateRenewalRecord(value.record,new Date(),active.channel??"microphone"),intent=record.intent;
  requireRenewal(intent.sessionId===active.sessionId && intent.profileReceiptId===active.captureProfile.receipt_id
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
  if(!before || !sameRenewalIntent(before.record.intent,record.intent)) {
    requireRenewal((!before || before.state==="extended") && existing.phase==="recording" && next.phase==="recording"
      && after.state==="pending" && record.lease===null && record.reservations===null
      && sameLease(existing.lease,record.intent.priorLease) && sameLease(existing.lease,next.lease)
      && existing.captureAuthorizedUntil!==null
      && canonicalCaptureTimestamp(existing.captureAuthorizedUntil)===record.intent.priorCaptureAuthorizedUntil
      && existing.recordedChunks<record.intent.firstSequenceNumber && existing.captureProfile
      && record.intent.profileReceiptId===existing.captureProfile.receipt_id);
    return true;
  }
  requireRenewal(before.state==="pending" &&
    (before.record.lease===null || same(before.record.lease,record.lease)) &&
    (before.record.reservations===null || same(before.record.reservations,record.reservations)));
  return true;
}
