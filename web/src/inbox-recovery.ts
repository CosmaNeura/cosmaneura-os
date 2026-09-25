import type {Scope, Receipt, Triage, Result} from './inbox-schema';
import {InboxContractError, sameInboxScope, validateInbox, validateInboxOperation, verifyInboxOperationReceipt, type InboxOperation, type InboxSaved} from './inbox-contract';
import {vendorBytes, vendorCanonical, vendorObject, vendorUuid} from './vendor-contract';

export const INBOX_RECOVERY_BYTES = 131072;
// Closed Receipt fields fit within this reserve, including the eventual history wrapper.
export const INBOX_PROOF_RESERVE_BYTES = 2048;
export type InboxDraft = {
  item_id: string;
  source_id: string | null;
  source_sha256: string | null;
  workspace_id: string;
  classification: Triage['classification'];
  due_date: string;
  instructions: string;
  result_disposition: Result['disposition'];
  result_evidence: string;
};
export const emptyInboxDraft = (item_id:string, source_id:string|null, source_sha256:string|null):InboxDraft => ({
  item_id, source_id, source_sha256, workspace_id:'', classification:'administrative_review',
  due_date:'', instructions:'', result_disposition:'needs_human', result_evidence:'',
});
export type InboxRecoveryRecord = {
  version:1; scope:Scope; drafts:InboxDraft[]; selected_item_id:string|null;
  pending:InboxOperation|null; receipt:Receipt|null; history:InboxSaved[];
  parked:{operation:InboxOperation;receipt:Receipt|null}[];
};
export type InboxRecoveryAccess = {
  load():Promise<unknown>;
  persist(value:InboxRecoveryRecord|null):Promise<void>;
  authorize():Promise<void>;
  denied?(error:unknown):void;
};
export const emptyInboxRecovery = (scope:Scope):InboxRecoveryRecord => ({
  version:1, scope:structuredClone(scope), drafts:[], selected_item_id:null, pending:null, receipt:null, history:[], parked:[],
});
const fail=():never=>{throw new InboxContractError();};
const admissionCapacity=(record:InboxRecoveryRecord)=>{
  const unresolved=[...record.parked,...(record.pending&&!["recorded","rejected"].includes(record.receipt?.outcome??'')?[{operation:record.pending,receipt:record.receipt}]:[])];
  const remaining=unresolved.reduce((total,entry)=>total+Math.max(0,INBOX_PROOF_RESERVE_BYTES-vendorBytes(entry.receipt)),0);
  const wrapperReserve=64*(record.parked.length+(record.pending?1:0));
  if(vendorBytes(record)+remaining+wrapperReserve>INBOX_RECOVERY_BYTES)fail();
};
export const inboxDraftKey = (v:Pick<InboxDraft,'item_id'|'source_id'|'source_sha256'>) => vendorCanonical([v.item_id,v.source_id,v.source_sha256]);
export function validateInboxDraft(value:unknown):InboxDraft {
  if(!vendorObject(value)||Object.keys(value).sort().join(',')!==Object.keys(emptyInboxDraft('x',null,null)).sort().join(','))fail();
  const d=value as InboxDraft;
  if(!vendorUuid(d.item_id)||(d.source_id===null)!==(d.source_sha256===null)||d.source_id!==null&&!vendorUuid(d.source_id)||d.source_sha256!==null&&!/^[a-f0-9]{64}$/.test(d.source_sha256)||d.workspace_id!==''&&!vendorUuid(d.workspace_id))fail();
  for(const [field,max] of [['due_date',10],['instructions',2000],['result_evidence',2000]] as const){
    if(typeof d[field]!=='string'||Array.from(d[field]).length>max||/[\x00-\x08\x0b-\x1f\x7f]/.test(d[field]))fail();
  }
  if(!['administrative_review','clinical_human_review','urgent_human_review','source_exception'].includes(d.classification)||!['local_review_complete','needs_human'].includes(d.result_disposition))fail();
  vendorCanonical(d);return structuredClone(d);
}
export async function validateInboxRecovery(value:unknown,scope:Scope):Promise<InboxRecoveryRecord>{
  if(vendorObject(value)&&value.version===1&&Object.keys(value).sort().join(',')==='drafts,history,pending,receipt,scope,selected_item_id,version')value={...value,parked:[]};
  if(!vendorObject(value)||Object.keys(value).sort().join(',')!=='drafts,history,parked,pending,receipt,scope,selected_item_id,version'||value.version!==1||vendorBytes(value)>INBOX_RECOVERY_BYTES)fail();
  const v=value as InboxRecoveryRecord;
  validateInbox('Scope',v.scope);
  if(!sameInboxScope(v.scope,scope)||v.selected_item_id!==null&&!vendorUuid(v.selected_item_id)||!Array.isArray(v.drafts)||v.drafts.length>100||!Array.isArray(v.history)||!Array.isArray(v.parked)||v.history.length+v.parked.length+(v.pending?1:0)>100)fail();
  const drafts=v.drafts.map(validateInboxDraft),draftKeys=drafts.map(inboxDraftKey);
  if(new Set(draftKeys).size!==draftKeys.length)fail();
  const pending=v.pending===null?null:await validateInboxOperation(v.pending,scope);
  const receipt=v.receipt===null?null:pending?await verifyInboxOperationReceipt(pending,v.receipt):fail();
  const history:InboxSaved[]=[],keys=new Set<string>(),ids=new Set<string>();
  for(const entry of v.history){
    if(!vendorObject(entry)||Object.keys(entry).sort().join(',')!=='operation,receipt')fail();
    const operation=await validateInboxOperation(entry.operation,scope),proof=await verifyInboxOperationReceipt(operation,entry.receipt);
    const receiptId=proof.receipt_id;
    if(proof.outcome==='not_found'||receiptId===null)return fail();
    const key=vendorCanonical([operation.request.item_id,operation.request.idempotency_key]);
    if(keys.has(key)||ids.has(receiptId))fail();
    keys.add(key);ids.add(receiptId);history.push({operation,receipt:proof});
  }
  if(pending&&keys.has(vendorCanonical([pending.request.item_id,pending.request.idempotency_key]))||receipt?.receipt_id&&ids.has(receipt.receipt_id))fail();
  const parked:InboxRecoveryRecord['parked']=[],items=new Set<string>();
  for(const entry of v.parked){
    if(!vendorObject(entry)||Object.keys(entry).sort().join(',')!=='operation,receipt')fail();
    const operation=await validateInboxOperation(entry.operation,scope),proof=entry.receipt===null?null:await verifyInboxOperationReceipt(operation,entry.receipt);
    const key=vendorCanonical([operation.request.item_id,operation.request.idempotency_key]);
    if(proof!==null&&proof.outcome!=='not_found'||keys.has(key)||items.has(operation.request.item_id)||pending?.request.item_id===operation.request.item_id)fail();
    keys.add(key);items.add(operation.request.item_id);parked.push({operation,receipt:proof});
  }
  const checked:InboxRecoveryRecord={version:1,scope:structuredClone(scope),drafts,selected_item_id:v.selected_item_id,pending,receipt,history,parked};
  admissionCapacity(checked);return checked;
}
export const unresolvedInboxCommand = (record:InboxRecoveryRecord) => record.pending!==null&&!['recorded','rejected'].includes(record.receipt?.outcome??'');
export function withInboxDraft(record:InboxRecoveryRecord,draft:InboxDraft):InboxRecoveryRecord{
  const checked=validateInboxDraft(draft),key=inboxDraftKey(checked),drafts=[...record.drafts],index=drafts.findIndex(d=>inboxDraftKey(d)===key);
  if(index<0)drafts.push(checked);else drafts[index]=checked;
  const next={...record,drafts};if(drafts.length>100)fail();admissionCapacity(next);return next;
}
export function withInboxCommand(record:InboxRecoveryRecord,operation:InboxOperation):InboxRecoveryRecord{
  if(record.pending!==null||record.history.length+record.parked.length>=100||record.parked.some(p=>p.operation.request.item_id===operation.request.item_id)||!sameInboxScope(record.scope,operation.scope))fail();
  const next={...record,pending:operation,receipt:null};admissionCapacity(next);return next;
}
export function continueInboxReview(record:InboxRecoveryRecord):InboxRecoveryRecord{
  if(!record.pending||!record.receipt||record.receipt.outcome==='not_found')return fail();
  const next={...record,pending:null,receipt:null,history:[...record.history,{operation:record.pending,receipt:record.receipt}]};
  if(next.history.length+next.parked.length>100||vendorBytes(next)>INBOX_RECOVERY_BYTES)fail();return next;
}
export function parkInboxCommand(record:InboxRecoveryRecord):InboxRecoveryRecord{
  if(!record.pending||!unresolvedInboxCommand(record)||record.parked.some(p=>p.operation.request.item_id===record.pending!.request.item_id))return fail();
  const next={...record,parked:[...record.parked,{operation:record.pending,receipt:record.receipt}],pending:null,receipt:null};
  if(next.history.length+next.parked.length>100)fail();admissionCapacity(next);return next;
}
export function resumeInboxCommand(record:InboxRecoveryRecord,itemId:string):InboxRecoveryRecord{
  if(record.pending!==null)return fail();const entry=record.parked.find(p=>p.operation.request.item_id===itemId);if(!entry)return fail();
  return {...record,pending:entry.operation,receipt:entry.receipt,parked:record.parked.filter(p=>p!==entry)};
}
