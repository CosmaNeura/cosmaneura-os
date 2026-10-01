import {VENDOR_SETUP_SCHEMAS,type VendorSetupContractName,type VendorSetupContractTypes} from './vendor-setup-schema';
import {vendorCanonical,vendorBytes,vendorDigest,vendorObject,vendorUuid} from './vendor-contract';
export class VendorSetupContractError extends Error { constructor(){super('The delivery settings could not be verified.');} }
const fail=():never=>{throw new VendorSetupContractError();};
type Obj=Record<string,unknown>;
type Schema={$ref?:string;anyOf?:Schema[];oneOf?:Schema[];type?:string;const?:unknown;enum?:unknown[];properties?:Record<string,Schema>;required?:readonly string[];items?:Schema;minimum?:number;maximum?:number;minLength?:number;maxLength?:number;minItems?:number;maxItems?:number;pattern?:string;'x-rules'?:readonly string[];'x-no-null'?:boolean};
const schemas=VENDOR_SETUP_SCHEMAS as unknown as Record<string,Schema>;
const validString=(value:string)=>{vendorCanonical(value);return value;};
function day(v:unknown):boolean {if(typeof v!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(v)||v.slice(0,4)==='0000')return false;const d=new Date(v+'T00:00:00.000Z');return !Number.isNaN(d.valueOf())&&d.toISOString().slice(0,10)===v;}
function timestamp(v:unknown):boolean {if(typeof v!=='string'||!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$/.test(v)||!day(v.slice(0,10)))return false;const d=new Date(v);return !Number.isNaN(d.valueOf())&&d.toISOString()===v.slice(0,23)+'Z';}
function rule(name:string,v:unknown):unknown {
  if(name==='_text'){if(typeof v!=='string')fail();const t=(v as string).replace(/\r\n?/g,'\n');validString(t);if(/[\x00-\x08\x0b-\x1f\x7f]/.test(t)||!t||/^[\t\n\v\f\r \x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]*$/.test(t))fail();return t;}
  if(name==='_uuid'&&!vendorUuid(v)||name==='_day'&&!day(v)||name==='_timestamp'&&!timestamp(v)||name==='_true'&&v!==true||name==='_version'&&v!==1)fail();return v;
}
function shape(s:Schema,v:unknown,depth=0):unknown {
  if(depth>30)fail();
  if(s.$ref){const name=s.$ref.split('/').pop()!;if(!schemas[name])fail();return model(name,v,depth+1);}
  for(const name of s['x-rules']??[])v=rule(name,v);
  if(s.anyOf||s.oneOf){for(const branch of s.anyOf??s.oneOf!){try{return shape(branch,v,depth+1);}catch(e){if(!(e instanceof VendorSetupContractError))throw e;}}return fail();}
  if(Object.hasOwn(s,'const')&&s.const!==v||s.enum&&!s.enum.includes(v))fail();
  switch(s.type){
    case 'null':if(v!==null)fail();return v;
    case 'boolean':if(typeof v!=='boolean')fail();return v;
    case 'integer':if(typeof v!=='number'||!Number.isInteger(v)||v<(s.minimum??-2147483647)||v>(s.maximum??2147483647))fail();return v;
    case 'string':{if(typeof v!=='string')return fail();validString(v);const count=Array.from(v).length;if(count<(s.minLength??0)||count>(s.maxLength??Infinity)||s.pattern&&new RegExp(s.pattern).exec(v)?.[0]!==v)fail();return v;}
    case 'array':if(!Array.isArray(v)||v.length<(s.minItems??0)||v.length>(s.maxItems??Infinity))return fail();return v.map(c=>shape(s.items!,c,depth+1));
    case 'object':{if(!vendorObject(v))return fail();const p=s.properties??{};if(Object.keys(v).some(k=>!Object.hasOwn(p,k))||(s.required??[]).some(k=>!Object.hasOwn(v,k)))fail();const out:Obj={};for(const [k,c] of Object.entries(v)){if(s['x-no-null']&&c===null)fail();out[k]=shape(p[k],c,depth+1);}return out;}
    default:return fail();
  }
}
export type {Scope as VendorSetupScope,Catalog as VendorSetupCatalog,Detail as VendorSetupDetail,Summary as VendorSetupSummary,AccountProposal,RecipientProposal,Activation,Disable,Revoke,Binding,InstalledAccount} from './vendor-setup-schema';
import type {Scope,Receipt,NotFound,AccountProposal,RecipientProposal,Activation,Disable,Revoke} from './vendor-setup-schema';
export type VendorSetupRequests={propose_account:AccountProposal;propose_recipient:RecipientProposal;activate:Activation;disable:Disable;revoke:Revoke};
export type VendorSetupKind=keyof VendorSetupRequests;
export type VendorSetupReceipt=Receipt|NotFound;
export type VendorSetupOperation<K extends VendorSetupKind=VendorSetupKind>={version:1;scope:Scope;kind:K;request:VendorSetupRequests[K];request_sha256:string};
export const VENDOR_SETUP_RECOVERY_BYTES=131072;
const models={propose_account:'AccountProposal',propose_recipient:'RecipientProposal',activate:'Activation',disable:'Disable',revoke:'Revoke'} as const;
const states={propose_account:'pending_review',propose_recipient:'pending_review',activate:'active',disable:'disabled',revoke:'revoked'} as const;
export const VENDOR_SETUP_ACTIONS={spruce:['spruce_secure_message','spruce_media_upload','spruce_fax'],srfax:['srfax_fax'],documo:['documo_fax'],efax:['efax_fax']} as const;
function model(name:string,value:unknown,depth=0):unknown{
  const v=shape(schemas[name],value,depth) as Obj;
  if('expected_version'in v&&(v.expected_version as number)>100||['Effect','Summary'].includes(name)&&(v.version as number)>100||['AccountReview','RecipientReview'].includes(name)&&(v.revision as number)>20)fail();
  if(name==='Permissions'){const actions=v.actions as string[];if(!v.read_status&&!v.prepare_and_submit||new Set(actions).size!==actions.length||actions.includes('spruce_fax')&&!actions.includes('spruce_media_upload'))fail();}
  if(name==='InstalledAccount'){const actions=v.capabilities as string[],vendor=v.vendor as keyof typeof VENDOR_SETUP_ACTIONS;if(new Set(actions).size!==actions.length||actions.some(a=>!(VENDOR_SETUP_ACTIONS[vendor] as readonly string[]).includes(a))||vendor!=='documo'&&v.environment!=='production')fail();}
  if(name==='AccountReview'){const r=v as VendorSetupContractTypes['AccountReview'];if(r.permissions.actions.some(a=>!r.installed.capabilities.includes(a)))fail();}
  if(name==='RecipientReview'){const r=v as VendorSetupContractTypes['RecipientReview'],action=r.destination.channel==='secure'?'spruce_secure_message':r.installed.vendor+'_fax';if(!r.installed.capabilities.includes(action as typeof r.installed.capabilities[number])||r.destination.channel==='secure'&&r.installed.vendor!=='spruce')fail();}
  if(name==='Activation'){const flags=['reviewed_patient','reviewed_recipient','reviewed_permission'].filter(k=>Object.hasOwn(v,k));if(flags.length!==0&&flags.length!==3)fail();}
  if(name==='Summary'&&(v.target as Obj).kind!==v.kind)fail();
  if(name==='Summary'&&v.usable_locally&&(v.state!=='active'||v.availability!=='available'))fail();
  if(name==='Receipt'&&(v.effect as Obj).state!==states[v.command_kind as VendorSetupKind])fail();
  return v;
}
export function normalizeVendorSetup<N extends VendorSetupContractName>(name:N,value:unknown):VendorSetupContractTypes[N]{vendorCanonical(value);return model(name,value) as VendorSetupContractTypes[N];}
export function validateVendorSetup<N extends VendorSetupContractName>(name:N,value:unknown):VendorSetupContractTypes[N]{const result=normalizeVendorSetup(name,value);if(vendorCanonical(result)!==vendorCanonical(value))fail();return result;}
export async function prepareVendorSetupOperation<K extends VendorSetupKind>(scope:Scope,kind:K,request:VendorSetupRequests[K]):Promise<VendorSetupOperation<K>>{
  validateVendorSetup('Scope',scope);if(!Object.hasOwn(models,kind))fail();const exact=normalizeVendorSetup(models[kind],request) as VendorSetupRequests[K];if(vendorBytes(exact)>8192)fail();
  return {version:1,scope:structuredClone(scope),kind,request:exact,request_sha256:await vendorDigest('cosmas-vendor-setup-request.v1',{scope,command_kind:kind,request:exact})};
}
export async function validateVendorSetupOperation(value:unknown,scope?:Scope):Promise<VendorSetupOperation>{
  if(!vendorObject(value)||Object.keys(value).sort().join(',')!=='kind,request,request_sha256,scope,version'||value.version!==1||typeof value.kind!=='string'||!Object.hasOwn(models,value.kind))fail();
  const v=value as VendorSetupOperation;if(scope&&vendorCanonical(scope)!==vendorCanonical(v.scope))fail();validateVendorSetup(models[v.kind],v.request);const expected=await prepareVendorSetupOperation(v.scope,v.kind,v.request);if(vendorCanonical(expected)!==vendorCanonical(v))fail();return expected;
}
export async function verifyVendorSetupReceipt(value:unknown,operation?:VendorSetupOperation):Promise<VendorSetupReceipt>{
  if(!vendorObject(value))return fail();const r=value.outcome==='recorded'?validateVendorSetup('Receipt',value):validateVendorSetup('NotFound',value);
  if(operation&&(vendorCanonical(r.scope)!==vendorCanonical(operation.scope)||r.command_kind!==operation.kind||r.idempotency_key!==operation.request.idempotency_key||r.request_sha256!==operation.request_sha256))fail();
  if(r.outcome==='recorded'){
    const {receipt_sha256:_,...body}=r;if(await vendorDigest('cosmas-vendor-setup-receipt.v1',body)!==r.receipt_sha256)fail();
    if(operation){const q=operation.request;if(r.effect.setup_id!==q.setup_id||r.effect.version!==q.expected_version+1)fail();if('revision_id'in q&&(r.effect.revision_id!==q.revision_id||r.effect.review_sha256!==q.review_sha256))fail();if(operation.kind==='propose_account'&&r.effect.kind!=='account'||operation.kind==='propose_recipient'&&r.effect.kind!=='recipient'||operation.kind==='activate'&&((r.effect.kind==='recipient')!==('reviewed_patient'in q)))fail();}
  }
  if(vendorBytes(r)>8192)fail();return r;
}
export async function verifyVendorSetupView<N extends 'Catalog'|'Detail'|'History'>(name:N,value:unknown):Promise<VendorSetupContractTypes[N]>{
  const v=validateVendorSetup(name,value);if(vendorBytes(v)>({Detail:32768,Catalog:131072,History:1048576}[name]))fail();
  if(name==='Catalog'){
    const c=v as VendorSetupContractTypes['Catalog'];for(const ids of [c.installed_accounts.map(i=>i.installation_id),c.patients.map(p=>p.patient_link_id),c.setups.map(s=>s.setup_id)])if(new Set(ids).size!==ids.length)fail();
    const accountTargets=c.setups.filter(s=>s.target.kind==='account').map(s=>vendorCanonical(s.target));if(!c.enabled&&c.setups.some(s=>s.usable_locally)||new Set(accountTargets).size!==accountTargets.length)fail();
  }
  if(name==='Detail'){
    const d=v as VendorSetupContractTypes['Detail'],s=d.summary,r=d.review;
    if(s.kind!==r.kind||s.setup_id!==r.setup_id||s.revision_id!==r.revision_id||s.label!==r.label||s.review_sha256!==await vendorDigest('cosmas-vendor-setup-review.v1',r))fail();
    if(r.kind==='account'?(s.target.kind!=='account'||s.target.installation_id!==r.installed.installation_id):(s.target.kind!=='recipient'||s.target.account_setup_id!==r.account.setup_id||s.target.patient_link_id!==r.patient.patient_link_id))fail();
    const receipt=await verifyVendorSetupReceipt(d.last_receipt);if(receipt.outcome!=='recorded'||vendorCanonical(receipt.scope)!==vendorCanonical(d.scope)||(['setup_id','kind','version','revision_id','review_sha256','state'] as const).some(k=>receipt.effect[k]!==s[k]))fail();
  }
  if(name==='History'){
    const h=v as VendorSetupContractTypes['History'],ids=new Set<string>(),keys=new Set<string>(),reviews=new Map<string,VendorSetupContractTypes['AccountReview']|VendorSetupContractTypes['RecipientReview']>();let version=0,revision=0,previous:string|null=null,currentReview:string|null=null,target:string|null=null,kind:string|null=null;
    for(const r of h.reviews){if(r.setup_id!==h.setup_id||r.revision!==reviews.size+1||reviews.has(r.revision_id))fail();const t=vendorCanonical(r.kind==='account'?{kind:r.kind,installation_id:r.installed.installation_id}:{kind:r.kind,account_setup_id:r.account.setup_id,patient_link_id:r.patient.patient_link_id});if(target&&t!==target)fail();target=t;reviews.set(r.revision_id,r);}
    if(!h.items.length||!reviews.size)fail();
    for(const item of h.items){
      const op=await prepareVendorSetupOperation(h.scope,item.receipt.command_kind,item.request),r=await verifyVendorSetupReceipt(item.receipt,op);if(r.outcome!=='recorded')return fail();const review=reviews.get(r.effect.revision_id);
      if(!review||r.effect.setup_id!==h.setup_id||r.effect.version!==++version||ids.has(r.receipt_id)||keys.has(r.idempotency_key)||r.effect.kind!==review.kind||kind&&kind!==r.effect.kind||r.effect.review_sha256!==await vendorDigest('cosmas-vendor-setup-review.v1',review))return fail();
      ids.add(r.receipt_id);keys.add(r.idempotency_key);kind=r.effect.kind;
      if(op.kind==='propose_account'||op.kind==='propose_recipient'){
        if(previous==='revoked'||review.revision!==++revision)fail();currentReview=review.revision_id;
        if(op.kind==='propose_account'){const q=op.request as AccountProposal;if(review.kind!=='account'||q.installation_id!==review.installed.installation_id||q.installation_sha256!==review.installed.installation_sha256||q.label!==review.label||vendorCanonical(q.permissions)!==vendorCanonical(review.permissions))fail();}
        else {const q=op.request as RecipientProposal;if(review.kind!=='recipient'||q.patient_link_id!==review.patient.patient_link_id||q.label!==review.label||q.permission_reference!==review.permission_reference||q.expires_at!==review.expires_at||vendorCanonical(q.account)!==vendorCanonical(review.account)||vendorCanonical(q.destination)!==vendorCanonical(review.destination))fail();}
      }else if(currentReview!==review.revision_id||!previous||previous==='revoked'||op.kind==='activate'&&previous!=='pending_review'||op.kind==='disable'&&previous==='disabled')fail();
      previous=r.effect.state;
    }
    if(revision!==reviews.size)fail();
  }
  return v;
}
