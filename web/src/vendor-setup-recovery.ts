import {vendorBytes,vendorCanonical,vendorObject,vendorUuid} from './vendor-contract';
import {VENDOR_SETUP_RECOVERY_BYTES,VendorSetupContractError,validateVendorSetup,validateVendorSetupOperation,verifyVendorSetupReceipt,type VendorSetupScope,type VendorSetupOperation,type VendorSetupReceipt,type Binding} from './vendor-setup-contract';

export type VendorSetupDraft={kind:'account'|'recipient';setup_id:string;expected_version:number;installation_id:string;label:string;read_status:boolean;prepare_and_submit:boolean;actions:import('./vendor-setup-schema').Permissions['actions'];account:Binding|null;patient_link_id:string;channel:'secure'|'fax';contact_id:string;fax_number:string;permission_reference:string;expires_at:string};
export const emptyVendorSetupDraft=():VendorSetupDraft=>({kind:'account',setup_id:'',expected_version:0,installation_id:'',label:'',read_status:false,prepare_and_submit:false,actions:[],account:null,patient_link_id:'',channel:'secure',contact_id:'',fax_number:'',permission_reference:'',expires_at:''});
export type VendorSetupHistory={operation:VendorSetupOperation;receipt:Extract<VendorSetupReceipt,{outcome:'recorded'}>};
export type VendorSetupRecoveryRecord={version:1;scope:VendorSetupScope;draft:VendorSetupDraft;selected_setup_id:string|null;pending:VendorSetupOperation|null;receipt:VendorSetupReceipt|null;commands:VendorSetupHistory[]};
export type VendorSetupRecoveryAccess={load():Promise<unknown>;persist(value:VendorSetupRecoveryRecord|null):Promise<void>;authorize():Promise<void>;denied?(error:unknown):void};
export const emptyVendorSetupRecovery=(scope:VendorSetupScope):VendorSetupRecoveryRecord=>({version:1,scope:structuredClone(scope),draft:emptyVendorSetupDraft(),selected_setup_id:null,pending:null,receipt:null,commands:[]});
const fail=():never=>{throw new VendorSetupContractError();};
export async function validateVendorSetupRecovery(value:unknown,scope?:VendorSetupScope):Promise<VendorSetupRecoveryRecord>{
  if(!vendorObject(value)||Object.keys(value).sort().join(',')!=='commands,draft,pending,receipt,scope,selected_setup_id,version'||value.version!==1||vendorBytes(value)>VENDOR_SETUP_RECOVERY_BYTES)fail();
  const v=value as VendorSetupRecoveryRecord;validateVendorSetup('Scope',v.scope);if(scope&&vendorCanonical(v.scope)!==vendorCanonical(scope)||v.selected_setup_id!==null&&!vendorUuid(v.selected_setup_id))fail();
  const d=v.draft;if(!vendorObject(d)||Object.keys(d).sort().join(',')!==Object.keys(emptyVendorSetupDraft()).sort().join(',')||!['account','recipient'].includes(d.kind)||!Number.isInteger(d.expected_version)||d.expected_version<0||d.expected_version>100)fail();
  for(const key of ['setup_id','installation_id','patient_link_id'] as const)if(d[key]!==''&&!vendorUuid(d[key]))fail();
  for(const [field,max]of [['label',80],['contact_id',100],['fax_number',32],['permission_reference',80],['expires_at',32]]as const)if(typeof d[field]!=='string'||Array.from(d[field]).length>max||/[\x00-\x08\x0b-\x1f\x7f]/.test(d[field]))fail();
  if(!['secure','fax'].includes(d.channel)||typeof d.read_status!=='boolean'||typeof d.prepare_and_submit!=='boolean'||!Array.isArray(d.actions)||d.actions.length>3||new Set(d.actions).size!==d.actions.length||d.actions.some(a=>!['spruce_secure_message','spruce_fax','spruce_media_upload','srfax_fax','documo_fax'].includes(a)))fail();
  if(d.account!==null)validateVendorSetup('Binding',d.account);const pending=v.pending===null?null:await validateVendorSetupOperation(v.pending,v.scope);const receipt=v.receipt===null?null:pending?await verifyVendorSetupReceipt(v.receipt,pending):fail();
  if(!Array.isArray(v.commands)||v.commands.length>100)fail();const keys=new Set<string>(),ids=new Set<string>();const commands:VendorSetupHistory[]=[];
  for(const item of v.commands){if(!vendorObject(item)||Object.keys(item).sort().join(',')!=='operation,receipt')fail();const op=await validateVendorSetupOperation(item.operation,v.scope),r=await verifyVendorSetupReceipt(item.receipt,op);if(r.outcome!=='recorded'||keys.has(op.request.idempotency_key)||ids.has(r.receipt_id))return fail();keys.add(op.request.idempotency_key);ids.add(r.receipt_id);commands.push({operation:op,receipt:r});}
  if(pending&&keys.has(pending.request.idempotency_key)||receipt?.outcome==='recorded'&&ids.has(receipt.receipt_id))fail();return {...structuredClone(v),pending,receipt,commands};
}
export const unresolvedVendorSetup=(record:VendorSetupRecoveryRecord)=>!!record.pending&&record.receipt?.outcome!=='recorded';
export function continueVendorSetup(record:VendorSetupRecoveryRecord):VendorSetupRecoveryRecord{
  if(!record.pending||record.receipt?.outcome!=='recorded')return fail();
  const next={...record,pending:null,receipt:null,commands:[...record.commands,{operation:record.pending,receipt:record.receipt}]};if(next.commands.length>100||vendorBytes(next)>VENDOR_SETUP_RECOVERY_BYTES)fail();return next;
}
