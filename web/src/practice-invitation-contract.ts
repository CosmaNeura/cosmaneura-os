import {accessName,accessObject,invalidAccess} from './practice-access-contract';
import {vendorUuid} from './vendor-contract';
import {WorkspaceApiError} from './workspace-api';

export type PracticeInvitation={invitation_id:string;label:string;created_at:string;expires_at:string;state:'active'|'expired'|'revoked';requests:number};
export type CreateInvitation={idempotency_key:string;label:string;token:string;expires_in_hours:24|72|168};
export type RevokeInvitation={idempotency_key:string;invitation_id:string};
export type InvitationOperation={type:'create';body:CreateInvitation}|{type:'revoke';body:RevokeInvitation};
export type InvitationRecovery={contract:'practice-invitation-recovery.v1';confirmed:{invitation:PracticeInvitation;token:string}|null;pending:InvitationOperation|null};
export const invitationToken=(value:unknown):value is string=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
function timestamp(value:unknown):value is string{return typeof value==='string'&&/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?\+00:00$/.test(value)&&Number.isFinite(Date.parse(value))&&new Date(value).toISOString().slice(0,19)===value.slice(0,19);}
export function validateInvitation(value:unknown):PracticeInvitation{
  if(!accessObject(value,'created_at,expires_at,invitation_id,label,requests,state')||!vendorUuid(value.invitation_id)||!accessName(value.label)||!timestamp(value.created_at)||!timestamp(value.expires_at)||Date.parse(value.expires_at)<=Date.parse(value.created_at)||Date.parse(value.expires_at)-Date.parse(value.created_at)>7*86400000||!['active','expired','revoked'].includes(value.state as string)||!Number.isSafeInteger(value.requests)||Number(value.requests)<0)return invalidAccess();
  return {...value} as PracticeInvitation;
}
export function validateInvitationCommand<T extends CreateInvitation|RevokeInvitation>(value:T,create:boolean):T{
  const body=value as unknown as Record<string,unknown>;
  if(!accessObject(value,create?'expires_in_hours,idempotency_key,label,token':'idempotency_key,invitation_id')||!vendorUuid(value.idempotency_key)||
    (create? !accessName(body.label)||!invitationToken(body.token)||![24,72,168].includes(Number(body.expires_in_hours))||typeof body.expires_in_hours!=='number':!vendorUuid(body.invitation_id)))throw new WorkspaceApiError(422,'invalid_practice_access_request');
  return {...value};
}
export function validateInvitationReceipt(value:unknown,operation:InvitationOperation):PracticeInvitation{
  if(!accessObject(value,'contract_version,invitation')||value.contract_version!==1)return invalidAccess();
  const row=validateInvitation(value.invitation);
  if(operation.type==='create'?row.label!==operation.body.label||Date.parse(row.expires_at)-Date.parse(row.created_at)!==operation.body.expires_in_hours*3600000:row.invitation_id!==operation.body.invitation_id||row.state!=='revoked')return invalidAccess();
  return row;
}
export function validateInvitations(value:unknown):PracticeInvitation[]{
  if(!accessObject(value,'contract_version,invitations')||value.contract_version!==1||!Array.isArray(value.invitations)||value.invitations.length>200)return invalidAccess();
  const rows=value.invitations.map(validateInvitation);if(new Set(rows.map(row=>row.invitation_id)).size!==rows.length)return invalidAccess();return rows;
}
/** Invitation secrets have explicit, bounded custody; authentication tokens remain forbidden in draft storage. */
export function encodeInvitationRecovery(value:InvitationRecovery):unknown{
  const pending=value.pending?.type==='create'?{type:'create',body:{idempotency_key:value.pending.body.idempotency_key,label:value.pending.body.label,expires_in_hours:value.pending.body.expires_in_hours,invitation_secret:value.pending.body.token}}:value.pending;
  return {contract:value.contract,confirmed:value.confirmed?{invitation:value.confirmed.invitation,invitation_secret:value.confirmed.token}:null,pending};
}
export function validateInvitationRecovery(value:unknown):InvitationRecovery{
  if(!accessObject(value,'confirmed,contract,pending')||value.contract!=='practice-invitation-recovery.v1')return invalidAccess();
  let confirmed:InvitationRecovery['confirmed']=null,pending:InvitationOperation|null=null;
  if(value.confirmed!==null){if(!accessObject(value.confirmed,'invitation,invitation_secret')||!invitationToken(value.confirmed.invitation_secret))return invalidAccess();confirmed={invitation:validateInvitation(value.confirmed.invitation),token:value.confirmed.invitation_secret};}
  if(value.pending!==null){if(!accessObject(value.pending,'body,type')||value.pending.type!=='create'&&value.pending.type!=='revoke')return invalidAccess();
    if(value.pending.type==='create'){const body=value.pending.body;if(!accessObject(body,'expires_in_hours,idempotency_key,invitation_secret,label')||!invitationToken(body.invitation_secret))return invalidAccess();pending={type:'create',body:validateInvitationCommand({idempotency_key:body.idempotency_key,label:body.label,expires_in_hours:body.expires_in_hours,token:body.invitation_secret} as CreateInvitation,true)};}
    else pending={type:'revoke',body:validateInvitationCommand(value.pending.body as RevokeInvitation,false)};
  }
  return {contract:'practice-invitation-recovery.v1',confirmed,pending};
}
export function invitationFromHash(hash:string):string|null{const match=/^#cosmas\/invite\/([a-f0-9]{64})$/.exec(hash);return match?.[1]??null;}
export function invitationUrl(token:string):string{if(!invitationToken(token))return invalidAccess();return `${window.location.origin}${window.location.pathname}#cosmas/invite/${token}`;}

export function validateInvitationResolution(value:unknown,operation:InvitationOperation):{outcome:'recorded'|'not_found';invitation:PracticeInvitation|null}{
  if(!accessObject(value,'contract_version,invitation,outcome')||value.contract_version!==1)return invalidAccess();
  if(value.outcome==='not_found'&&value.invitation===null)return {outcome:'not_found',invitation:null};
  if(value.outcome!=='recorded')return invalidAccess();
  return {outcome:'recorded',invitation:validateInvitationReceipt({contract_version:1,invitation:value.invitation},operation)};
}
