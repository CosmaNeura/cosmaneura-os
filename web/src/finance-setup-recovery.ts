import {vendorBytes,vendorCanonical,vendorObject,vendorUuid} from './vendor-contract';
import {FINANCE_SETUP_RECOVERY_BYTES,FinanceSetupContractError,validateFinanceSetup,validateFinanceSetupOperation,verifyFinanceSetupReceipt,type FinanceSetupScope,type FinanceSetupOperation,type FinanceSetupReceipt,type Binding} from './finance-setup-contract';

export type FinanceSetupDraft={kind:'account'|'customer';setup_id:string;expected_version:number;installation_id:string;label:string;read_status:boolean;create_unconfirmed_intents:boolean;account:Binding|null;patient_link_id:string;customer_id:string};
export const emptyFinanceSetupDraft=():FinanceSetupDraft=>({kind:'account',setup_id:'',expected_version:0,installation_id:'',label:'',read_status:false,create_unconfirmed_intents:false,account:null,patient_link_id:'',customer_id:''});
export type FinanceSetupHistory={operation:FinanceSetupOperation;receipt:Extract<FinanceSetupReceipt,{outcome:'recorded'}>};
export type FinanceSetupRecoveryRecord={version:1;scope:FinanceSetupScope;draft:FinanceSetupDraft;selected_setup_id:string|null;pending:FinanceSetupOperation|null;receipt:FinanceSetupReceipt|null;commands:FinanceSetupHistory[]};
export type FinanceSetupRecoveryAccess={load():Promise<unknown>;persist(value:FinanceSetupRecoveryRecord|null):Promise<void>;authorize():Promise<void>;denied?(error:unknown):void};
export const emptyFinanceSetupRecovery=(scope:FinanceSetupScope):FinanceSetupRecoveryRecord=>({version:1,scope:structuredClone(scope),draft:emptyFinanceSetupDraft(),selected_setup_id:null,pending:null,receipt:null,commands:[]});
const fail=():never=>{throw new FinanceSetupContractError();};
export async function validateFinanceSetupRecovery(value:unknown,scope?:FinanceSetupScope):Promise<FinanceSetupRecoveryRecord>{
  if(!vendorObject(value)||Object.keys(value).sort().join(',')!=='commands,draft,pending,receipt,scope,selected_setup_id,version'||value.version!==1||vendorBytes(value)>FINANCE_SETUP_RECOVERY_BYTES)fail();
  const v=value as FinanceSetupRecoveryRecord;validateFinanceSetup('Scope',v.scope);if(scope&&vendorCanonical(v.scope)!==vendorCanonical(scope)||v.selected_setup_id!==null&&!vendorUuid(v.selected_setup_id))fail();
  const d=v.draft;if(!vendorObject(d)||Object.keys(d).sort().join(',')!==Object.keys(emptyFinanceSetupDraft()).sort().join(',')||!['account','customer'].includes(d.kind)||!Number.isInteger(d.expected_version)||d.expected_version<0||d.expected_version>100)fail();
  for(const key of ['setup_id','installation_id','patient_link_id'] as const)if(d[key]!==''&&!vendorUuid(d[key]))fail();
  if(typeof d.label!=='string'||Array.from(d.label).length>80||typeof d.customer_id!=='string'||! /^(?:c|cu|cus|cus_[A-Za-z0-9]{0,240})?$/.test(d.customer_id)||typeof d.read_status!=='boolean'||typeof d.create_unconfirmed_intents!=='boolean')fail();
  if(d.account!==null)validateFinanceSetup('Binding',d.account);const pending=v.pending===null?null:await validateFinanceSetupOperation(v.pending,v.scope);const receipt=v.receipt===null?null:pending?await verifyFinanceSetupReceipt(v.receipt,pending):fail();
  if(!Array.isArray(v.commands)||v.commands.length>100)fail();const keys=new Set<string>(),ids=new Set<string>();const commands:FinanceSetupHistory[]=[];
  for(const item of v.commands){if(!vendorObject(item)||Object.keys(item).sort().join(',')!=='operation,receipt')fail();const op=await validateFinanceSetupOperation(item.operation,v.scope),r=await verifyFinanceSetupReceipt(item.receipt,op);if(r.outcome!=='recorded'||keys.has(op.request.idempotency_key)||ids.has(r.receipt_id))return fail();keys.add(op.request.idempotency_key);ids.add(r.receipt_id);commands.push({operation:op,receipt:r});}
  if(pending&&keys.has(pending.request.idempotency_key)||receipt?.outcome==='recorded'&&ids.has(receipt.receipt_id))fail();return {...structuredClone(v),pending,receipt,commands};
}
export const unresolvedFinanceSetup=(record:FinanceSetupRecoveryRecord)=>!!record.pending&&record.receipt?.outcome!=='recorded';
export function continueFinanceSetup(record:FinanceSetupRecoveryRecord):FinanceSetupRecoveryRecord{
  if(!record.pending||record.receipt?.outcome!=='recorded')return fail();
  return {...record,pending:null,receipt:null,commands:[...record.commands,{operation:record.pending,receipt:record.receipt}]};
}
