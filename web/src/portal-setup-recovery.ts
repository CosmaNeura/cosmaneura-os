import {vendorBytes,vendorCanonical,vendorObject,vendorUuid,VendorContractError} from './vendor-contract';
import {PORTAL_RECOVERY_BYTES,portalScope,validatePortalOperation,verifyPortalReceipt,type PortalScope,type PortalCapability,type PortalOperation,type PortalReceipt} from './portal-setup-contract';
export type PortalDraft={installation_id:string;connection_id:string;expected_version:number;capabilities:PortalCapability[];patient_link_id:string;practice_reference:string;patient_reference:string;recipient_reference:string;practice_label:string;recipient_label:string};
export const emptyPortalDraft=():PortalDraft=>({installation_id:'',connection_id:'',expected_version:0,capabilities:[],patient_link_id:'',practice_reference:'',patient_reference:'',recipient_reference:'',practice_label:'',recipient_label:''});
export type PortalRecoveryRecord={version:1;scope:PortalScope;draft:PortalDraft;selected_connection_id:string|null;pending:PortalOperation|null;receipt:PortalReceipt|null};
/** Parent adapts the existing encrypted account DraftJournal and CAS. No storage fallback. */
export type PortalRecoveryAccess={load():Promise<unknown>;persist(value:PortalRecoveryRecord|null):Promise<void>;authorize():Promise<void>;denied?(error:unknown):void};
export const emptyPortalRecovery=(scope:PortalScope):PortalRecoveryRecord=>({version:1,scope:structuredClone(scope),draft:emptyPortalDraft(),selected_connection_id:null,pending:null,receipt:null});
export async function validatePortalRecovery(value:unknown,scope?:PortalScope):Promise<PortalRecoveryRecord>{
  const fail=():never=>{throw new VendorContractError();};
  if(!vendorObject(value)||Object.keys(value).sort().join(',')!=='draft,pending,receipt,scope,selected_connection_id,version'||value.version!==1||vendorBytes(value)>PORTAL_RECOVERY_BYTES)fail();
  const v=value as PortalRecoveryRecord;portalScope(v.scope);if(scope&&vendorCanonical(scope)!==vendorCanonical(v.scope))fail();
  if(!vendorObject(v.draft)||Object.keys(v.draft).sort().join(',')!==Object.keys(emptyPortalDraft()).sort().join(','))fail();
  const d=v.draft;for(const key of ['installation_id','connection_id','patient_link_id'] as const)if(d[key]!==''&&!vendorUuid(d[key]))fail();
  if(!Number.isInteger(d.expected_version)||d.expected_version<0||d.expected_version>1000||!Array.isArray(d.capabilities)||d.capabilities.length>3||new Set(d.capabilities).size!==d.capabilities.length||d.capabilities.some(c=>!['document.upload','referral.submit','referral.read'].includes(c)))fail();
  for(const key of ['practice_reference','patient_reference','recipient_reference'] as const)if(typeof d[key]!=='string'||!/^[A-Za-z0-9_-]{0,120}$/.test(d[key]))fail();
  for(const key of ['practice_label','recipient_label'] as const)if(typeof d[key]!=='string'||Array.from(d[key]).length>80)fail();
  if(v.selected_connection_id!==null&&!vendorUuid(v.selected_connection_id))fail();
  if(v.pending!==null)await validatePortalOperation(v.pending,v.scope);
  if(v.receipt!==null){const pending=v.pending;if(pending===null)return fail();await verifyPortalReceipt(v.receipt,pending);}
  return structuredClone(v);
}
