import {vendorBytes,vendorCanonical,vendorDigest,vendorObject,vendorUuid,VendorContractError} from './vendor-contract';

export type PortalScope={box_id:string;owner_id:string};
export type PortalCapability='document.upload'|'referral.submit'|'referral.read';
export type PortalKind='propose'|'activate'|'disable'|'revoke';
export type PortalMappings={patient_link_id:string;practice_reference:string;patient_reference:string;recipient_reference:string;practice_label:string;recipient_label:string};
export type PortalProposal={connection_id:string;expected_version:number;idempotency_key:string;installation_id:string;profile_sha256:string;configuration_sha256:string;capabilities:PortalCapability[];mappings:PortalMappings};
export type PortalBound={connection_id:string;expected_version:number;idempotency_key:string;revision_id:string;review_sha256:string};
export type PortalActivation=PortalBound&{reviewed_profile:true;reviewed_practice:true;reviewed_patient:true;reviewed_recipient:true;confirm_local_activation:true};
export type PortalDisable=PortalBound&{confirm_disable:true};
export type PortalRevoke=PortalBound&{confirm_revoke:true};
export type PortalRequest=PortalProposal|PortalActivation|PortalDisable|PortalRevoke;
export type PortalOperation={version:1;scope:PortalScope;kind:PortalKind;request:PortalRequest;request_sha256:string};
export type PortalEffect={version:number;revision_id:string;state:'pending_review'|'active'|'disabled'|'revoked';review_sha256:string};
export type PortalReceipt={contract_version:1;outcome:'recorded'|'not_found';scope:PortalScope;command_kind:PortalKind;idempotency_key:string;request_sha256:string;connection_id?:string;receipt_id?:string;receipt_sha256?:string;recorded_at?:string;effect?:PortalEffect};
export type PortalProfileView={installation_id:string;portal_id:string;label:string;profile_sha256:string;configuration_sha256:string;mode:'synthetic'|'sandbox'|'production';mapping_requirements:string[];capabilities:{capability:PortalCapability;evidence:'documented'|'contract_gap'|'unsupported'}[]};
export type PortalReview={connection_id:string;installation_id:string;portal_id:string;profile_label:string;mode:'synthetic'|'sandbox'|'production';profile_sha256:string;configuration_sha256:string;capabilities:PortalCapability[];mappings:PortalMappings&{patient_label:string};mapping_ids:{practice_mapping_id:string;patient_mapping_id:string;recipient_mapping_id:string};mappings_sha256:string};
export type PortalDetail={connection_id:string;version:number;revision_id:string;revision:number;state:PortalEffect['state'];usable_locally:boolean;availability:string;review:PortalReview;review_sha256:string;last_receipt:PortalReceipt};
export type PortalCatalog={contract_version:1;scope:PortalScope;profiles:PortalProfileView[];patients:{id:string;label:string}[];connections:PortalDetail[];live_portals_configured:boolean};
export const PORTAL_RECOVERY_BYTES=16384;
const portalMode=(mode:unknown,id:unknown)=>typeof id==='string'&&/^[a-z][a-z0-9_-]{1,31}$/.test(id)&&['synthetic','sandbox','production'].includes(String(mode))&&(id.startsWith('synthetic_')===(mode==='synthetic'));
const kinds=['propose','activate','disable','revoke'];
export const portalCapabilities:PortalCapability[]=['document.upload','referral.submit','referral.read'];
const digest=(v:unknown)=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v);
const counter=(v:unknown,max=1000)=>typeof v==='number'&&Number.isInteger(v)&&v>=0&&v<=max;
const fail=():never=>{throw new VendorContractError();};
const keys=(v:unknown,expected:string[])=>{if(!vendorObject(v)||Object.keys(v).sort().join(',')!==[...expected].sort().join(','))fail();};
export function portalScope(value:unknown):PortalScope{keys(value,['box_id','owner_id']);const v=value as PortalScope;if(!vendorUuid(v.box_id)||!vendorUuid(v.owner_id))fail();return v;}
function mappings(value:unknown){keys(value,['patient_link_id','practice_reference','patient_reference','recipient_reference','practice_label','recipient_label']);const v=value as PortalMappings;if(!vendorUuid(v.patient_link_id))fail();for(const key of ['practice_reference','patient_reference','recipient_reference'] as const)if(typeof v[key]!=='string'||!/^[A-Za-z0-9_-]{1,120}$/.test(v[key]))fail();for(const key of ['practice_label','recipient_label'] as const)if(typeof v[key]!=='string'||!v[key].trim()||Array.from(v[key]).length>80)fail();}
function capabilities(value:unknown){if(!Array.isArray(value)||!value.length||value.length>3||new Set(value).size!==value.length||value.some(v=>!portalCapabilities.includes(v)))fail();}
export function portalRequest(kind:PortalKind,value:unknown):PortalRequest{
  const common=['connection_id','expected_version','idempotency_key'];
  const specific={propose:['installation_id','profile_sha256','configuration_sha256','capabilities','mappings'],activate:['revision_id','review_sha256','reviewed_profile','reviewed_practice','reviewed_patient','reviewed_recipient','confirm_local_activation'],disable:['revision_id','review_sha256','confirm_disable'],revoke:['revision_id','review_sha256','confirm_revoke']}[kind];
  if(!specific)fail();keys(value,[...common,...specific]);const v=value as PortalRequest;
  if(!vendorUuid(v.connection_id)||!counter(v.expected_version)||kind!=='propose'&&v.expected_version<1||typeof v.idempotency_key!=='string'||!/^[A-Za-z0-9:_-]{8,100}$/.test(v.idempotency_key))fail();
  if(kind==='propose'){const p=v as PortalProposal;if(!vendorUuid(p.installation_id)||!digest(p.profile_sha256)||!digest(p.configuration_sha256))fail();mappings(p.mappings);capabilities(p.capabilities);}
  else {const p=v as PortalBound;if(!vendorUuid(p.revision_id)||!digest(p.review_sha256))fail();for(const key of specific.filter(k=>k.startsWith('reviewed_')||k.startsWith('confirm_')))if((value as Record<string,unknown>)[key]!==true)fail();}
  if(vendorBytes(v)>8192)fail();return structuredClone(v);
}
export async function preparePortalOperation(scope:PortalScope,kind:PortalKind,request:PortalRequest):Promise<PortalOperation>{portalScope(scope);const checked=portalRequest(kind,request);return {version:1,scope:structuredClone(scope),kind,request:checked,request_sha256:await vendorDigest('cosmas-portal-setup-request.v1',{scope,command_kind:kind,request:checked})};}
export async function validatePortalOperation(value:unknown,scope?:PortalScope):Promise<PortalOperation>{keys(value,['version','scope','kind','request','request_sha256']);const v=value as PortalOperation;if(v.version!==1||!kinds.includes(v.kind)||scope&&vendorCanonical(scope)!==vendorCanonical(v.scope))fail();const expected=await preparePortalOperation(v.scope,v.kind,v.request);if(vendorCanonical(expected)!==vendorCanonical(v))fail();return expected;}
export async function verifyPortalReceipt(value:unknown,operation?:PortalOperation):Promise<PortalReceipt>{
  if(!vendorObject(value))return fail();const common=['contract_version','outcome','scope','command_kind','idempotency_key','request_sha256'];keys(value,value.outcome==='recorded'?[...common,'connection_id','receipt_id','receipt_sha256','recorded_at','effect']:common);const v=value as PortalReceipt;
  portalScope(v.scope);if(v.contract_version!==1||!['recorded','not_found'].includes(v.outcome)||!kinds.includes(v.command_kind)||!digest(v.request_sha256)||!/^[A-Za-z0-9:_-]{8,100}$/.test(v.idempotency_key))fail();
  if(operation&&(vendorCanonical(v.scope)!==vendorCanonical(operation.scope)||v.command_kind!==operation.kind||v.idempotency_key!==operation.request.idempotency_key||v.request_sha256!==operation.request_sha256))fail();
  if(v.outcome==='recorded'){
    const effect=v.effect;if(!effect)return fail();keys(effect,['version','revision_id','state','review_sha256']);
    if(!counter(effect.version)||effect.version<1||!vendorUuid(effect.revision_id)||!digest(effect.review_sha256)||!['pending_review','active','disabled','revoked'].includes(effect.state)||!vendorUuid(v.connection_id)||!vendorUuid(v.receipt_id)||!digest(v.receipt_sha256)||typeof v.recorded_at!=='string')fail();
    const {receipt_sha256:_,...body}=v;if(await vendorDigest('cosmas-portal-setup-receipt.v1',body)!==v.receipt_sha256)fail();
    if(operation&&(v.connection_id!==operation.request.connection_id||effect.version!==operation.request.expected_version+1||'revision_id'in operation.request&&(effect.revision_id!==operation.request.revision_id||effect.review_sha256!==operation.request.review_sha256)))fail();
    if(effect.state!=={propose:'pending_review',activate:'active',disable:'disabled',revoke:'revoked'}[v.command_kind])fail();
  }
  return structuredClone(v);
}
export async function verifyPortalDetail(value:unknown):Promise<PortalDetail>{
  keys(value,['connection_id','version','revision_id','revision','state','usable_locally','availability','review','review_sha256','last_receipt']);const v=value as PortalDetail;
  if(!vendorUuid(v.connection_id)||!vendorUuid(v.revision_id)||!counter(v.version)||v.version<1||!counter(v.revision,100)||v.revision<1||typeof v.usable_locally!=='boolean'||typeof v.availability!=='string')fail();
  keys(v.review,['connection_id','installation_id','portal_id','profile_label','mode','profile_sha256','configuration_sha256','capabilities','mappings','mapping_ids','mappings_sha256']);
  const r=v.review;if(r.connection_id!==v.connection_id||!vendorUuid(r.installation_id)||!portalMode(r.mode,r.portal_id)||typeof r.profile_label!=='string'||!r.profile_label.trim()||Array.from(r.profile_label).length>80||!digest(r.profile_sha256)||!digest(r.configuration_sha256)||!digest(r.mappings_sha256))fail();
  const {patient_label,...mapping}=r.mappings;if(typeof patient_label!=='string')fail();mappings(mapping);capabilities(r.capabilities);keys(r.mapping_ids,['practice_mapping_id','patient_mapping_id','recipient_mapping_id']);if(Object.values(r.mapping_ids).some(id=>!vendorUuid(id)))fail();
  if(await vendorDigest('cosmas-portal-setup-review.v1',r)!==v.review_sha256)fail();const receipt=await verifyPortalReceipt(v.last_receipt);if(receipt.connection_id!==v.connection_id||receipt.effect?.revision_id!==v.revision_id||receipt.effect?.version!==v.version||receipt.effect?.state!==v.state||receipt.effect?.review_sha256!==v.review_sha256)fail();
  if(v.usable_locally&&(v.state!=='active'||v.availability!=='available'))fail();
  if(await vendorDigest('cosmas-portal-setup-mappings.v1',{scope:receipt.scope,installation_id:r.installation_id,profile_sha256:r.profile_sha256,configuration_sha256:r.configuration_sha256,ids:r.mapping_ids,mappings:mapping})!==r.mappings_sha256)fail();return structuredClone(v);
}
export async function verifyPortalCatalog(value:unknown):Promise<PortalCatalog>{
  keys(value,['contract_version','scope','profiles','patients','connections','live_portals_configured']);const v=value as PortalCatalog;portalScope(v.scope);if(v.contract_version!==1||typeof v.live_portals_configured!=='boolean'||!Array.isArray(v.profiles)||v.profiles.length>50||!Array.isArray(v.patients)||v.patients.length>100||!Array.isArray(v.connections)||v.connections.length>50)fail();
  if(v.live_portals_configured!==v.profiles.some(p=>p.mode!=='synthetic'))fail();
  for(const p of v.profiles){keys(p,['installation_id','portal_id','label','profile_sha256','configuration_sha256','capabilities','mode','mapping_requirements']);if(!vendorUuid(p.installation_id)||!portalMode(p.mode,p.portal_id)||!digest(p.profile_sha256)||!digest(p.configuration_sha256)||typeof p.label!=='string'||!Array.isArray(p.capabilities))fail();for(const c of p.capabilities){keys(c,['capability','evidence']);if(!portalCapabilities.includes(c.capability)||!['documented','contract_gap','unsupported'].includes(c.evidence))fail();}}
  for(const p of v.patients){keys(p,['id','label']);if(!vendorUuid(p.id)||typeof p.label!=='string')fail();}
  for(const connection of v.connections){await verifyPortalDetail(connection);if(vendorCanonical(connection.last_receipt.scope)!==vendorCanonical(v.scope))fail();}
  return structuredClone(v);
}
