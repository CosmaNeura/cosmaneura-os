import type {CaptureBotSelection} from "./workspace-api";
import {validAppointmentBot} from "./appointment-request";

export type PrepWorkCreate = {bot:CaptureBotSelection;expected_entry_revision:number;snapshot_sha256:string;
  body:string;due_date:string;expected_outcome:string;share_context:true;idempotency_key:string};
export type PrepWorkDecision = {expected_version:number;revision_id:string;payload_hash:string} &
  ({choice:"approve";bot:CaptureBotSelection;expected_snapshot_sha256:string}|{choice:"reject"});
export type PrepWorkVerification = {bot:CaptureBotSelection;expected_version:number;revision_id:string;payload_hash:string;
  current_snapshot_sha256:string;reviewed_summary:true;idempotency_key:string};
export type PrepWorkRequest = {kind:"create";body:PrepWorkCreate}|{kind:"decide";ticket:string;body:PrepWorkDecision}|
  {kind:"verify";ticket:string;body:PrepWorkVerification};
export const prepClosed=(value:unknown,keys:string):value is Record<string,unknown>=>!!value&&typeof value==="object"&&!Array.isArray(value)&&
  Object.keys(value).sort().join(",")===keys.split(",").sort().join(",");
export const prepUuid=(value:unknown):value is string=>typeof value==="string"&&/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(value);
export const prepHash=(value:unknown):value is string=>typeof value==="string"&&/^[a-f0-9]{64}$/.test(value);
export const prepText=(value:unknown,max:number):value is string=>typeof value==="string"&&!!value.trim()&&value.length<=max&&!value.includes("\0");
export const prepDate=(value:unknown):value is string=>typeof value==="string"&&/^\d{4}-\d\d-\d\d$/.test(value)&&
  Number.isFinite(Date.parse(value))&&new Date(value).toISOString().slice(0,10)===value;
const positive=(value:unknown)=>Number.isSafeInteger(value)&&Number(value)>0;
export function validPrepWorkRequest(value:unknown):value is PrepWorkRequest {
  if(prepClosed(value,"kind,body")&&value.kind==="create") {
    const b=value.body;
    return prepClosed(b,"bot,expected_entry_revision,snapshot_sha256,body,due_date,expected_outcome,share_context,idempotency_key")&&
      validAppointmentBot(b.bot)&&Number.isSafeInteger(b.expected_entry_revision)&&Number(b.expected_entry_revision)>=1&&
      prepHash(b.snapshot_sha256)&&prepText(b.body,4000)&&prepDate(b.due_date)&&prepText(b.expected_outcome,500)&&
      b.share_context===true&&prepUuid(b.idempotency_key);
  }
  if(!prepClosed(value,"kind,ticket,body")||!prepUuid(value.ticket))return false;
  const b=value.body;
  if(!b||typeof b!=="object"||Array.isArray(b))return false;
  const body=b as Record<string,unknown>;
  if(!positive(body.expected_version)||!prepUuid(body.revision_id)||!prepHash(body.payload_hash))return false;
  if(value.kind==="decide")return body.choice==="reject"?prepClosed(b,"expected_version,revision_id,payload_hash,choice"):
    body.choice==="approve"&&prepClosed(b,"expected_version,revision_id,payload_hash,choice,bot,expected_snapshot_sha256")&&
      validAppointmentBot(body.bot)&&prepHash(body.expected_snapshot_sha256);
  return value.kind==="verify"&&prepClosed(b,"bot,expected_version,revision_id,payload_hash,current_snapshot_sha256,reviewed_summary,idempotency_key")&&
    validAppointmentBot(body.bot)&&prepHash(body.current_snapshot_sha256)&&body.reviewed_summary===true&&prepUuid(body.idempotency_key);
}
export const prepWorkRequestKey=(value:PrepWorkRequest)=>value.kind==="decide"?value.body.revision_id:value.body.idempotency_key;
