import type {FinanceScope,FinanceResponse,ReviewedSource,Revision} from './finance-schema';
import {FinanceContractError,validateFinance,verifyFinanceReceipt} from './finance-contract';
import {vendorBytes,vendorCanonical,vendorObject,vendorUuid} from './vendor-contract';
import {validateFinanceOperation,verifyFinanceOperationReceipt,type FinanceOperation} from './finance-operation';

export type FinanceDraft={connection_id:string;customer_id:string;amount:string;due_date:string;expected_outcome:string;source:ReviewedSource|null;revises:Revision|null;result_disposition:string;result_evidence:string};
export const emptyFinanceDraft=():FinanceDraft=>({connection_id:'',customer_id:'',amount:'',due_date:'',expected_outcome:'',source:null,revises:null,result_disposition:'reported_unpaid',result_evidence:''});
export type FinanceRecoveryRecord={version:1;scope:FinanceScope;draft:FinanceDraft;selected_ticket_id:string|null;pending:FinanceOperation|null;receipt:FinanceResponse|null;receipts:FinanceResponse[]};
/** The mount supplies the existing identity-scoped encrypted journal and CAS, not a new storage backend. */
export type FinanceRecoveryAccess={load():Promise<unknown>;persist(value:FinanceRecoveryRecord|null):Promise<void>;authorize():Promise<void>;denied?(error:unknown):void};
export const emptyFinanceRecovery=(scope:FinanceScope):FinanceRecoveryRecord=>({version:1,scope:structuredClone(scope),draft:emptyFinanceDraft(),selected_ticket_id:null,pending:null,receipt:null,receipts:[]});
const fail=():never=>{throw new FinanceContractError();};
export async function validateFinanceRecovery(value:unknown,scope:FinanceScope):Promise<FinanceRecoveryRecord>{
  if(!vendorObject(value)||Object.keys(value).sort().join(',')!=='draft,pending,receipt,receipts,scope,selected_ticket_id,version'||value.version!==1||vendorBytes(value)>131072)fail();
  const v=value as FinanceRecoveryRecord;validateFinance('FinanceScope',v.scope);if(vendorCanonical(scope)!==vendorCanonical(v.scope)||v.selected_ticket_id!==null&&!vendorUuid(v.selected_ticket_id))fail();
  const baseKeys=(value:object)=>Object.keys(value).filter(k=>k!=='revises').sort().join(',');if(!vendorObject(v.draft)||baseKeys(v.draft)!==baseKeys(emptyFinanceDraft()))fail();
  // The exact old R1 editable shape receives only this known default. Pending requests remain byte-identical.
  const d={...v.draft,revises:Object.hasOwn(v.draft,'revises')?v.draft.revises:null};if(d.revises!==null)validateFinance('Revision',d.revises);
  for(const key of ['connection_id','customer_id'] as const)if(d[key]!==''&&!vendorUuid(d[key]))fail();
  for(const [key,max] of [['amount',32],['due_date',10],['expected_outcome',500],['result_evidence',2000]] as const)if(typeof d[key]!=='string'||Array.from(d[key]).length>max)fail();
  if(!['reported_paid','reported_unpaid','verified_in_processor','unable_to_establish'].includes(d.result_disposition))fail();if(d.source!==null)validateFinance('ReviewedSource',d.source);
  const pending=v.pending===null?null:await validateFinanceOperation(v.pending,scope);const receipt=v.receipt===null?null:pending?await verifyFinanceOperationReceipt(pending,v.receipt):fail();
  if(!Array.isArray(v.receipts)||v.receipts.length>100)fail();const ids=new Set<string>();const receipts=[];
  for(const old of v.receipts){if(!vendorObject(old))fail();const r=await verifyFinanceReceipt(old,{scope,kind:old.command_kind,key:old.idempotency_key,sha256:old.request_sha256});if(r.outcome!=='recorded'||!r.effect||ids.has(r.effect.receipt_id))fail();ids.add(r.effect!.receipt_id);receipts.push(r);}
  return {...structuredClone(v),draft:structuredClone(d),pending,receipt,receipts};
}
export const hasUnresolvedFinanceCommand=(r:FinanceRecoveryRecord)=>r.pending!==null&&r.receipt?.outcome!=='recorded';
export function withFinanceCommand(record:FinanceRecoveryRecord,operation:FinanceOperation):FinanceRecoveryRecord{
  if(hasUnresolvedFinanceCommand(record)&&vendorCanonical(record.pending)!==vendorCanonical(operation))fail();const receipts=[...record.receipts],old=record.receipt;
  if(old?.outcome==='recorded'&&old.effect&&record.pending?.request_sha256!==operation.request_sha256&&!receipts.some(r=>r.effect?.receipt_id===old.effect!.receipt_id))receipts.push(old);
  return {...record,receipts,pending:operation,receipt:null};
}
export async function persistFinanceRecovery(access:FinanceRecoveryAccess,record:FinanceRecoveryRecord,{local=false}:{local?:boolean}={}):Promise<void>{const exact=await validateFinanceRecovery(record,record.scope);if(!local)await access.authorize();await access.persist(exact);}
