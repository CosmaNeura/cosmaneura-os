import type {Scope,ReviewedSource,Proposal,Result,LedgerProof} from './membership-schema';
import type {MembershipResponse as Response} from './membership-contract';
import {MembershipContractError,validateMembership,sameMembershipScope} from './membership-contract';
import {validateMembershipOperation,verifyMembershipOperationReceipt,type MembershipOperation,type MembershipSaved} from './membership-operation';
import {vendorBytes,vendorCanonical,vendorObject,vendorUuid} from './vendor-contract';
export const MEMBERSHIP_RECOVERY_BYTES=131072;
export type MembershipDraft={purpose:Proposal['purpose'];due_date:string;expected_outcome:string;instructions:string;source:ReviewedSource|null;result_disposition:Result['disposition'];result_evidence:string;ledger_source_label:string;ledger_system_kind:LedgerProof['system_kind'];ledger_record_reference:string;ledger_observed_at:string;ledger_membership_state:LedgerProof['observed_membership_state'];ledger_billing_state:LedgerProof['observed_billing_state'];artifact_id:string;finance_receipt_id:string};
export const emptyMembershipDraft=():MembershipDraft=>({purpose:'enrollment_assistance',due_date:'',expected_outcome:'',instructions:'',source:null,result_disposition:'local_preparation_ready',result_evidence:'',ledger_source_label:'',ledger_system_kind:'practice_owned_ledger',ledger_record_reference:'',ledger_observed_at:'',ledger_membership_state:'unknown',ledger_billing_state:'unknown',artifact_id:'',finance_receipt_id:''});
export type MembershipRecoveryRecord={version:1;scope:Scope;draft:MembershipDraft;selected_ticket_id:string|null;pending:MembershipOperation|null;receipt:Response|null;history:MembershipSaved[]};
/** Existing encrypted workspace editor + CAS; no alternative storage backend. */
export type MembershipRecoveryAccess={load():Promise<unknown>;persist(value:MembershipRecoveryRecord|null):Promise<void>;authorize():Promise<void>;denied?(error:unknown):void};
export const emptyMembershipRecovery=(scope:Scope):MembershipRecoveryRecord=>({version:1,scope:structuredClone(scope),draft:emptyMembershipDraft(),selected_ticket_id:null,pending:null,receipt:null,history:[]});
const fail=():never=>{throw new MembershipContractError();};
export function validateMembershipDraft(value:unknown):MembershipDraft{
 if(!vendorObject(value)||Object.keys(value).sort().join(',')!==Object.keys(emptyMembershipDraft()).sort().join(','))fail();const d=value as MembershipDraft;
 for(const [field,max] of [['due_date',10],['expected_outcome',500],['instructions',2000],['result_evidence',2000],['ledger_source_label',120],['ledger_record_reference',120],['ledger_observed_at',32]] as const)if(typeof d[field]!=='string'||Array.from(d[field]).length>max||/[\x00-\x08\x0b-\x1f\x7f]/.test(d[field]))fail();
 if(!['enrollment_assistance','membership_status_review','failed_payment_follow_up'].includes(d.purpose)||!['local_preparation_ready','record_reviewed','needs_human'].includes(d.result_disposition)||!['hint','atlas_md','practice_owned_ledger','other'].includes(d.ledger_system_kind)||!['unknown','not_enrolled','pending_enrollment','active','paused','ended'].includes(d.ledger_membership_state)||!['unknown','current','past_due','payment_failed'].includes(d.ledger_billing_state))fail();
 for(const key of ['artifact_id','finance_receipt_id'] as const)if(d[key]!==''&&!vendorUuid(d[key]))fail();if(d.source!==null)validateMembership('ReviewedSource',d.source);vendorCanonical(d);return structuredClone(d);
}
export async function validateMembershipRecovery(value:unknown,scope:Scope):Promise<MembershipRecoveryRecord>{
 if(!vendorObject(value)||Object.keys(value).sort().join(',')!=='draft,history,pending,receipt,scope,selected_ticket_id,version'||value.version!==1||vendorBytes(value)>MEMBERSHIP_RECOVERY_BYTES)fail();
 const v=value as MembershipRecoveryRecord;validateMembership('Scope',v.scope);if(!sameMembershipScope(scope,v.scope)||v.selected_ticket_id!==null&&!vendorUuid(v.selected_ticket_id)||!Array.isArray(v.history)||v.history.length>100)fail();
 const draft=validateMembershipDraft(v.draft),pending=v.pending===null?null:await validateMembershipOperation(v.pending,scope),receipt=v.receipt===null?null:pending?await verifyMembershipOperationReceipt(pending,v.receipt):fail();
 const ids=new Set<string>(),keys=new Set<string>(),history:MembershipSaved[]=[];
 for(const item of v.history){if(!vendorObject(item)||Object.keys(item).sort().join(',')!=='operation,receipt')fail();const operation=await validateMembershipOperation(item.operation,scope),r=await verifyMembershipOperationReceipt(operation,item.receipt);if(r.outcome==='not_found')fail();const id=r.outcome==='retired'?r.retirement.receipt_id:r.effect?.receipt_id;if(!id)return fail();if(ids.has(id)||keys.has(operation.request.idempotency_key))fail();ids.add(id);keys.add(operation.request.idempotency_key);history.push({operation,receipt:r});}
 const currentId=receipt?.outcome==='retired'?receipt.retirement.receipt_id:receipt?.effect?.receipt_id;
 if(pending&&keys.has(pending.request.idempotency_key)||currentId&&ids.has(currentId))fail();
 return {version:1,scope:structuredClone(scope),draft,selected_ticket_id:v.selected_ticket_id,pending,receipt,history};
}
export const hasUnresolvedMembershipCommand=(v:MembershipRecoveryRecord)=>v.pending!==null&&!['recorded','retired'].includes(v.receipt?.outcome??'');
export function withMembershipCommand(record:MembershipRecoveryRecord,operation:MembershipOperation):MembershipRecoveryRecord{
 if(hasUnresolvedMembershipCommand(record)&&vendorCanonical(record.pending)!==vendorCanonical(operation))fail();
 const history=[...record.history];if(record.pending&&record.receipt&&record.receipt.outcome!=='not_found'&&record.pending.request_sha256!==operation.request_sha256)history.push({operation:record.pending,receipt:record.receipt});
 const next={...record,history,pending:operation,receipt:null};if(history.length>100||vendorBytes(next)>MEMBERSHIP_RECOVERY_BYTES)fail();return next;
}
export async function persistMembershipRecovery(access:MembershipRecoveryAccess,value:MembershipRecoveryRecord,{local=false}:{local?:boolean}={}){const checked=await validateMembershipRecovery(value,value.scope);if(!local)await access.authorize();await access.persist(checked);}
