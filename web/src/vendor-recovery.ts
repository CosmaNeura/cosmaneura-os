import type {Scope,ReviewedSource,Document,Revision,Summary,ArtifactMetadata} from './vendor-schema';
import {validateVendor,verifyVendorReceipt,vendorBytes,vendorCanonical,vendorObject,vendorUuid,VENDOR_JOURNAL_BYTES,VendorContractError,type VendorReceipt,type VendorRetirementReceipt} from './vendor-contract';
import {validateVendorOperation,verifyOperationReceipt,canRetireVendorOperation,type VendorOperation} from './vendor-operation';

export type VendorComposeDraft={action:string;connection_id:string;correspondence_id:string;recipient_id:string;message:string;due_date:string;expected_outcome:string;share_to_practice:boolean;uploaded_media_operation_id:string;source:ReviewedSource|null;document:Document|null;revises:Revision|null;supersedes:Summary|null;result_evidence:string;result_disposition:string};
export const emptyVendorDraft=():VendorComposeDraft=>({action:'spruce_secure_message',connection_id:'',correspondence_id:'',recipient_id:'',message:'',due_date:'',expected_outcome:'',share_to_practice:false,uploaded_media_operation_id:'',source:null,document:null,revises:null,supersedes:null,result_evidence:'',result_disposition:'reported_success'});
export type VendorRetiredCommand={operation:VendorOperation;receipt:VendorRetirementReceipt};
export type VendorRecoveryRecord={version:1;scope:Scope;draft:VendorComposeDraft;selected_ticket_id:string|null;artifact:ArtifactMetadata|null;artifact_write:VendorOperation|null;pending:VendorOperation|null;receipt:VendorReceipt|null;receipts:VendorReceipt[];retired_commands:VendorRetiredCommand[]};
/** Integration adapts the existing encrypted DraftJournal/CAS. This module supplies no storage backend. */
export type VendorRecoveryAccess={load():Promise<unknown>;persist(value:VendorRecoveryRecord|null):Promise<void>;authorize():Promise<void>;denied?(error:unknown):void};
export const emptyVendorRecovery=(scope:Scope):VendorRecoveryRecord=>({version:1,scope:structuredClone(scope),draft:emptyVendorDraft(),selected_ticket_id:null,artifact:null,artifact_write:null,pending:null,receipt:null,receipts:[],retired_commands:[]});
const fail=():never=>{throw new VendorContractError();};
function compose(value:unknown):VendorComposeDraft {
  if(!vendorObject(value))return fail();
  const baseKeys=(v:object)=>Object.keys(v).filter(k=>!['revises','supersedes'].includes(k)).sort().join(',');if(baseKeys(value)!==baseKeys(emptyVendorDraft()))fail();
  if(Object.hasOwn(value,'supersedes')&&!Object.hasOwn(value,'revises'))fail();
  const d={...value,revises:Object.hasOwn(value,'revises')?value.revises:null,supersedes:Object.hasOwn(value,'supersedes')?value.supersedes:null} as VendorComposeDraft;
  if(!['spruce_secure_message','spruce_media_upload','spruce_fax','srfax_fax','documo_fax','efax_fax'].includes(d.action)||!['reported_success','reported_exception','verified_in_vendor','unable_to_establish'].includes(d.result_disposition)||typeof d.share_to_practice!=='boolean')fail();
  for(const key of ['connection_id','correspondence_id','uploaded_media_operation_id','recipient_id'] as const)if(d[key]!==''&&!vendorUuid(d[key]))fail();
  for(const [key,max] of [['message',4000],['due_date',10],['expected_outcome',500],['result_evidence',2000]] as const)if(typeof d[key]!=='string'||Array.from(d[key]).length>max)fail();
  if(d.source!==null)validateVendor('ReviewedSource',d.source);if(d.document!==null)validateVendor('Document',d.document);if(d.revises!==null)validateVendor('Revision',d.revises);if(d.supersedes!==null){validateVendor('Summary',d.supersedes);if(d.revises!==null||!d.supersedes.submit_claimed)fail();}return structuredClone(d);
}
export async function validateVendorRecovery(value:unknown,scope:Scope):Promise<VendorRecoveryRecord>{
  if(!vendorObject(value)||Object.keys(value).filter(k=>!['receipts','retired_commands'].includes(k)).sort().join(',')!=='artifact,artifact_write,draft,pending,receipt,scope,selected_ticket_id,version'||value.version!==1||vendorBytes(value)>VENDOR_JOURNAL_BYTES)fail();
  const v=value as VendorRecoveryRecord;validateVendor('Scope',v.scope);if(vendorCanonical(v.scope)!==vendorCanonical(scope)||v.selected_ticket_id!==null&&!vendorUuid(v.selected_ticket_id))fail();
  if(!vendorObject(v.draft)||Object.hasOwn(v,'receipts')!==Object.hasOwn(v.draft,'revises'))fail();
  if(Object.hasOwn(v,'retired_commands')&&(!Object.hasOwn(v,'receipts')||!Object.hasOwn(v.draft,'supersedes')))fail();
  const draft=compose(v.draft);
  if(v.artifact!==null){validateVendor('ArtifactMetadata',v.artifact);if(draft.document&&vendorCanonical(draft.document)!==vendorCanonical(v.artifact.document))fail();}
  if(scope.kind==='practice_work'&&(draft.source!==null||draft.document!==null||draft.revises!==null||draft.supersedes!==null||v.artifact!==null||v.artifact_write!==null||draft.message!==''||draft.uploaded_media_operation_id!==''||v.selected_ticket_id!==null&&v.selected_ticket_id!==scope.id))fail();
  if(v.artifact_write!==null){const write=await validateVendorOperation(v.artifact_write,scope);const artifact=v.artifact;if(!artifact)return fail();if(write.kind!=='artifact_content'||write.target_id!==artifact.artifact_id)fail();const r=write.request;if(!('intent_sha256'in r)||r.intent_sha256!==artifact.intent_sha256||r.sha256!==artifact.document.sha256||r.byte_length!==artifact.document.byte_length)fail();}
  const pending=v.pending===null?null:await validateVendorOperation(v.pending,scope);
  const receipt=v.receipt===null?null:pending?await verifyOperationReceipt(pending,v.receipt):fail();
  const history=Object.hasOwn(v,'receipts')?v.receipts:[];if(!Array.isArray(history)||history.length>100)fail();const ids=new Set<string>(),historyKeys=new Set<string>();
  const receipts=[];for(const old of history){if(!vendorObject(old))fail();const checked=await verifyVendorReceipt(old,{scope,kind:old.command_kind as string,key:old.idempotency_key as string,sha256:old.request_sha256 as string},'artifact'in old);const id=vendorReceiptId(checked);if(!isTerminalVendorReceipt(checked)||!id||ids.has(id)||historyKeys.has(checked.idempotency_key))fail();ids.add(id!);historyKeys.add(checked.idempotency_key);receipts.push(checked);
    if(pending?.request.idempotency_key===checked.idempotency_key&&(pending.kind!==checked.command_kind||pending.request_sha256!==checked.request_sha256||receipt&&isTerminalVendorReceipt(receipt)&&vendorReceiptCommitment(receipt)!==vendorReceiptCommitment(checked)))fail();}
  const pairs=Object.hasOwn(v,'retired_commands')?v.retired_commands:[];if(!Array.isArray(pairs)||pairs.length>100||scope.kind!=='workspace'&&pairs.length)fail();const retired_commands:VendorRetiredCommand[]=[],keys=new Set<string>(),retiredIds=new Set<string>();
  for(const pair of pairs){
    if(!vendorObject(pair)||Object.keys(pair).sort().join(',')!=='operation,receipt')fail();const operation=await validateVendorOperation(pair.operation,scope);if(!canRetireVendorOperation(operation)||keys.has(operation.request.idempotency_key))fail();
    const proof=await verifyOperationReceipt(operation,pair.receipt);if(proof.outcome!=='retired')return fail();if(retiredIds.has(proof.retirement.receipt_id))fail();keys.add(operation.request.idempotency_key);retiredIds.add(proof.retirement.receipt_id);retired_commands.push({operation,receipt:proof});
    const historical=receipts.find(r=>r.idempotency_key===operation.request.idempotency_key);if(historical&&vendorReceiptCommitment(historical)!==vendorReceiptCommitment(proof))fail();
    if(pending?.request.idempotency_key===operation.request.idempotency_key){if(receipt?.outcome!=='retired')return fail();if(vendorCanonical(pending)!==vendorCanonical(operation)||vendorCanonical(receipt.retirement)!==vendorCanonical(proof.retirement))fail();}
  }
  const result={...structuredClone(v),draft,pending,receipt,receipts,retired_commands};if(vendorBytes(result)>VENDOR_JOURNAL_BYTES)fail();return result;
}
export const isTerminalVendorReceipt=(receipt:VendorReceipt|null)=>receipt?.outcome==='recorded'||receipt?.outcome==='retired';
export const vendorReceiptId=(receipt:VendorReceipt)=>receipt.outcome==='retired'?receipt.retirement.receipt_id:receipt.effect?.receipt_id;
const vendorReceiptCommitment=(receipt:VendorReceipt)=>vendorCanonical({scope:receipt.scope,command_kind:receipt.command_kind,idempotency_key:receipt.idempotency_key,request_sha256:receipt.request_sha256,outcome:receipt.outcome,...(receipt.outcome==='retired'?{retirement:receipt.retirement}:{effect:receipt.effect,...('summary'in receipt?{summary:receipt.summary}:{})})});
export const hasUnresolvedVendorCommand=(record:VendorRecoveryRecord)=>record.pending!==null&&!isTerminalVendorReceipt(record.receipt);
export function withVendorCommand(record:VendorRecoveryRecord,operation:VendorOperation):VendorRecoveryRecord{
  if(hasUnresolvedVendorCommand(record)&&vendorCanonical(record.pending)!==vendorCanonical(operation))fail();const receipts=[...record.receipts],retired_commands=[...record.retired_commands];const previous=record.receipt;
  if(previous&&isTerminalVendorReceipt(previous)&&record.pending?.request_sha256!==operation.request_sha256){if(!receipts.some(r=>vendorReceiptId(r)===vendorReceiptId(previous)))receipts.push(previous);if(previous.outcome==='retired'&&record.pending&&!retired_commands.some(p=>p.operation.request.idempotency_key===record.pending!.request.idempotency_key))retired_commands.push({operation:record.pending,receipt:previous});}
  return {...record,receipts,retired_commands,pending:operation,receipt:null};
}
export function withVendorReceipt(record:VendorRecoveryRecord,receipt:VendorReceipt):VendorRecoveryRecord{
  const closedWrite=receipt.outcome==='retired'&&record.pending?.kind==='artifact_content'&&record.artifact_write?.request_sha256===record.pending.request_sha256;
  return {...record,receipt,...('artifact'in receipt&&receipt.artifact?{artifact:receipt.artifact}:{}),...(closedWrite?{artifact_write:null}:{})};
}
export async function persistVendorRecovery(access:VendorRecoveryAccess,record:VendorRecoveryRecord,{local=false}:{local?:boolean}={}):Promise<void>{
  const checked=await validateVendorRecovery(record,record.scope);if(!local)await access.authorize();await access.persist(checked);
}
export async function recordVendorCommand(access:VendorRecoveryAccess,record:VendorRecoveryRecord,operation:VendorOperation):Promise<VendorRecoveryRecord>{
  if(hasUnresolvedVendorCommand(record)&&vendorCanonical(record.pending)!==vendorCanonical(operation))fail();
  const next=withVendorCommand(record,await validateVendorOperation(operation,record.scope));await persistVendorRecovery(access,next);return next;
}
export async function recordVendorReceipt(access:VendorRecoveryAccess,record:VendorRecoveryRecord,value:unknown):Promise<VendorRecoveryRecord>{
  if(!record.pending)return fail();const receipt=await verifyOperationReceipt(record.pending,value);
  const next=withVendorReceipt(record,receipt);await persistVendorRecovery(access,next);return next;
}
