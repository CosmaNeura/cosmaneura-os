import {WorkspaceApiError} from './workspace-api';
import {accessObject,invalidAccess} from './practice-access-contract';
import {vendorUuid} from './vendor-contract';

export type PracticeMember={member_id:string;display_name:string;role:'owner'|'member';state:'active'|'inactive'|'unavailable';action:'deactivate'|'reactivate'|null;reviewed_at:string;expires_at:string;review_sha256:string};
export type MembersPage={contract_version:1;members:PracticeMember[];next_after_id:string|null};
export type MemberChange={idempotency_key:string;member_id:string;action:'deactivate'|'reactivate';reviewed_at:string;review_sha256:string;confirm:true};
export type MemberChangeResult={contract_version:1;replayed:boolean;receipt:{receipt_id:string;member_id:string;action:'deactivate'|'reactivate';recorded_state:'active'|'inactive';review_sha256:string;recorded_at:string}};
const hash=(value:unknown):value is string=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
function timestamp(value:unknown):value is string{
  if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?\+00:00$/.test(value))return false;
  const date=new Date(value);return Number.isFinite(date.getTime())&&date.toISOString().slice(0,19)===value.slice(0,19);
}
function member(value:unknown):PracticeMember{
  if(!accessObject(value,'action,display_name,expires_at,member_id,review_sha256,reviewed_at,role,state')||
    !vendorUuid(value.member_id)||typeof value.display_name!=='string'||!value.display_name.trim()||[...value.display_name].length>200||
    !['owner','member'].includes(value.role as string)||!['active','inactive','unavailable'].includes(value.state as string)||
    !timestamp(value.reviewed_at)||!timestamp(value.expires_at)||Date.parse(value.expires_at)-Date.parse(value.reviewed_at)!==600000||!hash(value.review_sha256))return invalidAccess();
  const expected=value.role==='owner'||value.state==='unavailable'?null:value.state==='active'?'deactivate':'reactivate';
  if(value.action!==expected)return invalidAccess();
  return {...value} as PracticeMember;
}
export function validateMembersPage(value:unknown,after:string|null):MembersPage{
  if(!accessObject(value,'contract_version,members,next_after_id')||value.contract_version!==1||!Array.isArray(value.members)||value.members.length>100)return invalidAccess();
  const members=value.members.map(member);
  for(let i=0;i<members.length;i++)if((i>0&&members[i-1].member_id>=members[i].member_id)||(after!==null&&members[i].member_id<=after))return invalidAccess();
  if(value.next_after_id!==null&&(members.length!==100||value.next_after_id!==members.at(-1)?.member_id))return invalidAccess();
  return {contract_version:1,members,next_after_id:value.next_after_id as string|null};
}
export function validateMemberChange(value:unknown):MemberChange{
  if(!accessObject(value,'action,confirm,idempotency_key,member_id,review_sha256,reviewed_at')||!vendorUuid(value.idempotency_key)||!vendorUuid(value.member_id)||
    !['deactivate','reactivate'].includes(value.action as string)||value.confirm!==true||!timestamp(value.reviewed_at)||!hash(value.review_sha256))throw new WorkspaceApiError(422,'invalid_practice_access_request');
  return {...value} as MemberChange;
}
export function validateMemberChangeResult(value:unknown,command:MemberChange):MemberChangeResult{
  if(!accessObject(value,'contract_version,receipt,replayed')||value.contract_version!==1||typeof value.replayed!=='boolean'||
    !accessObject(value.receipt,'action,member_id,receipt_id,recorded_at,recorded_state,review_sha256'))return invalidAccess();
  const receipt=value.receipt;
  if(receipt.receipt_id!==command.idempotency_key||receipt.member_id!==command.member_id||receipt.action!==command.action||receipt.review_sha256!==command.review_sha256||
    receipt.recorded_state!==(command.action==='deactivate'?'inactive':'active')||!timestamp(receipt.recorded_at))return invalidAccess();
  return {contract_version:1,replayed:value.replayed,receipt:{...receipt} as MemberChangeResult['receipt']};
}
export const memberCode=(value:Pick<PracticeMember,'member_id'>)=>value.member_id.replaceAll('-','').slice(0,12).toUpperCase().match(/.{4}/g)!.join('–');
