import type {AccountRecoveryAccess} from './account-recovery';
import {accountEditorAddress} from './draft-journal';
import type {AuthenticatedWorkspaceIdentity} from './workspace-api';

export type PrivateDraftCreate = {title:string;idempotency_key:string};
export type PrivateDraftLink = {expected_revision:number;idempotency_key:string;appointment_id:string;appointment_link_confirmed:true};
export type PrivateDraftRecovery = {contract:'private-draft-recovery.v1';title:string;pending:PrivateDraftCreate|null};
export type PrivateDraftLinkRecovery = {contract:'private-draft-link-recovery.v1';workspace_id:string;pending:PrivateDraftLink|null};
const uuid=(value:unknown):value is string=>typeof value==='string'&&/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(value);
const text=(value:unknown,max:number):value is string=>typeof value==='string'&&value===value.trim()&&!!value&&value.length<=max&&!/[\u0000-\u001f\u007f]/.test(value);
const row=(value:unknown):value is Record<string,unknown>=>!!value&&typeof value==='object'&&!Array.isArray(value);
export function validatePrivateDraftRecovery(value:unknown):PrivateDraftRecovery{
  if(!row(value)||Object.keys(value).sort().join(',')!=='contract,pending,title'||value.contract!=='private-draft-recovery.v1'||!text(value.title,160))throw new Error('Invalid private draft recovery');
  if(value.pending!==null&&(!row(value.pending)||Object.keys(value.pending).sort().join(',')!=='idempotency_key,title'||!uuid(value.pending.idempotency_key)||value.pending.title!==value.title))throw new Error('Invalid private draft request');
  return value as PrivateDraftRecovery;
}
export function validatePrivateDraftLinkRecovery(value:unknown,workspaceId:string):PrivateDraftLinkRecovery{
  if(!row(value)||Object.keys(value).sort().join(',')!=='contract,pending,workspace_id'||value.contract!=='private-draft-link-recovery.v1'||!uuid(workspaceId)||value.workspace_id!==workspaceId)throw new Error('Invalid private visit link recovery');
  const p=value.pending;
  if(p!==null&&(!row(p)||Object.keys(p).sort().join(',')!=='appointment_id,appointment_link_confirmed,expected_revision,idempotency_key'||!uuid(p.idempotency_key)||!uuid(p.appointment_id)||p.appointment_link_confirmed!==true||!Number.isSafeInteger(p.expected_revision)||Number(p.expected_revision)<1))throw new Error('Invalid private visit link request');
  return value as PrivateDraftLinkRecovery;
}
export type PrivateDraftAccess={identity:AuthenticatedWorkspaceIdentity;recovery:AccountRecoveryAccess};
export async function loadPrivateDraftRecovery(access:AccountRecoveryAccess):Promise<PrivateDraftRecovery|null>{
  await access.authorize();const value=await access.journal.load(accountEditorAddress('private-draft'));
  if(value===null)return null;
  if(value.kind!=='account-editor'||value.editor!=='private-draft')throw new Error('Invalid private draft editor');
  return validatePrivateDraftRecovery(value.data);
}
export async function persistPrivateDraftRecovery(access:AccountRecoveryAccess,value:PrivateDraftRecovery|null):Promise<void>{
  await access.journal.persist(accountEditorAddress('private-draft'),value?{kind:'account-editor',editor:'private-draft',data:value,pending:value.pending?.idempotency_key??null}:null);
}
