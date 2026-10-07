import {WorkspaceApiError} from './workspace-api';
import {vendorObject, vendorUuid} from './vendor-contract';

export type AccessRequest = {
  request_id:string; display_name:string; review_sha256:string;
  state:'pending'|'approved'|'declined'|'cancelled'|'expired'; created_at:string; expires_at:string;
};
export type AccessStatus = {contract_version:1; state:'connected'|'request_required'|AccessRequest['state']; role:'owner'|'member'|null; request:AccessRequest|null};
export type AccessReview = {request_id:string; review_sha256:string; confirm:true};
export type AccessDecision = AccessReview & {decision:'approve'|'decline'};
export type PracticeSetupStatus = {contract_version:1;state:'owner_setup'|'owner_ready'|'member_ready'|'join_existing'|'solo_setup_available';practice:{display_name:string;specialty:string|null}|null;display_name:string|null;can_start_practice:boolean};
export type CompletePracticeSetup = {idempotency_key:string;display_name:string;practice_name:string;specialty:string|null;confirm:true};
export const invalidAccess = ():never => {throw new WorkspaceApiError(502);};
export function accessObject(value:unknown, keys:string):value is Record<string,unknown> {
  return vendorObject(value) && Object.keys(value).sort().join(',')===keys &&
    Reflect.ownKeys(value).length===Object.keys(value).length &&
    Object.values(Object.getOwnPropertyDescriptors(value)).every(p=>'value' in p && p.enumerable);
}
export const accessName = (value:unknown):value is string => typeof value==='string' && value.length>0 &&
  [...value].length<=120 && value===value.trim() && !/[\u0000-\u001f\u007f]/.test(value) &&
  new TextDecoder().decode(new TextEncoder().encode(value))===value;
export function validatePracticeSetup(value:unknown):PracticeSetupStatus {
  if(!accessObject(value,'can_start_practice,contract_version,display_name,practice,state')||value.contract_version!==1||
    !['owner_setup','owner_ready','member_ready','join_existing','solo_setup_available'].includes(value.state as string)||
    typeof value.can_start_practice!=='boolean'||value.can_start_practice!==(value.state==='solo_setup_available'))return invalidAccess();
  const hasPractice=['owner_setup','owner_ready','member_ready'].includes(value.state as string);
  if(hasPractice?typeof value.display_name!=='string'||!value.display_name.trim()||value.display_name.length>200:value.display_name!==null)return invalidAccess();
  if(hasPractice? !accessObject(value.practice,'display_name,specialty')||typeof value.practice.display_name!=='string'||
    !value.practice.display_name.trim()||value.practice.display_name.length>200||
    value.practice.specialty!==null&&!accessName(value.practice.specialty):value.practice!==null)return invalidAccess();
  return value as PracticeSetupStatus;
}
export function validateCompletePracticeSetup(value:unknown):CompletePracticeSetup {
  if(!accessObject(value,'confirm,display_name,idempotency_key,practice_name,specialty')||
    !vendorUuid(value.idempotency_key)||!accessName(value.display_name)||!accessName(value.practice_name)||
    value.specialty!==null&&!accessName(value.specialty)||value.confirm!==true)throw new WorkspaceApiError(422,'invalid_practice_access_request');
  return {...value} as CompletePracticeSetup;
}
const digest = (value:unknown):value is string => typeof value==='string' && /^[a-f0-9]{64}$/.test(value);
function timestamp(value:unknown):value is string {
  if(typeof value!=='string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?\+00:00$/.test(value))return false;
  const date=new Date(value);
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0,19)===value.slice(0,19);
}
export function validateAccessRequest(value:unknown):AccessRequest {
  if(!accessObject(value,'created_at,display_name,expires_at,request_id,review_sha256,state') ||
    !vendorUuid(value.request_id) || !accessName(value.display_name) || !digest(value.review_sha256) ||
    !['pending','approved','declined','cancelled','expired'].includes(value.state as string) ||
    !timestamp(value.created_at) || !timestamp(value.expires_at) || Date.parse(value.created_at)>=Date.parse(value.expires_at))return invalidAccess();
  return {...value} as AccessRequest;
}
export function validateAccessStatus(value:unknown):AccessStatus {
  if(!accessObject(value,'contract_version,request,role,state') || value.contract_version!==1)return invalidAccess();
  if(value.state==='connected' && (value.role==='owner'||value.role==='member') && value.request===null)
    return {contract_version:1,state:'connected',role:value.role,request:null};
  if(value.role!==null)return invalidAccess();
  if(value.state==='request_required' && value.request===null)return {contract_version:1,state:'request_required',role:null,request:null};
  const request=validateAccessRequest(value.request);
  if(value.state!==request.state)return invalidAccess();
  return {contract_version:1,state:request.state,role:null,request};
}
export function validateAccessList(value:unknown):AccessRequest[] {
  if(!accessObject(value,'contract_version,requests') || value.contract_version!==1 || !Array.isArray(value.requests) || value.requests.length>100)return invalidAccess();
  const rows=value.requests.map(validateAccessRequest);
  if(rows.some(row=>row.state!=='pending') || new Set(rows.map(row=>row.request_id)).size!==rows.length)return invalidAccess();
  return rows;
}
export function validateAccessDecision(value:unknown, command:AccessDecision):AccessRequest {
  if(!accessObject(value,'contract_version,request') || value.contract_version!==1)return invalidAccess();
  const row=validateAccessRequest(value.request);
  if(row.request_id!==command.request_id || row.review_sha256!==command.review_sha256 ||
    row.state!==(command.decision==='approve'?'approved':'declined'))return invalidAccess();
  return row;
}
export function validateAccessReview(value:unknown, decision=false):AccessReview|AccessDecision {
  if(!accessObject(value,decision?'confirm,decision,request_id,review_sha256':'confirm,request_id,review_sha256') ||
    !vendorUuid(value.request_id) || !digest(value.review_sha256) || value.confirm!==true ||
    decision && value.decision!=='approve' && value.decision!=='decline')throw new WorkspaceApiError(422,'invalid_practice_access_request');
  return {...value} as AccessReview|AccessDecision;
}
// A human matching aid, never a credential or an authorization token.
export const accessCode = (row:AccessRequest) => row.request_id.replaceAll('-','').slice(0,12).toUpperCase().match(/.{4}/g)!.join('–');
