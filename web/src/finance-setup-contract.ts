import {FINANCE_SETUP_SCHEMAS,type FinanceSetupContractName,type FinanceSetupContractTypes} from './finance-setup-schema';
import {vendorCanonical,vendorBytes,vendorDigest,vendorObject,vendorUuid} from './vendor-contract';
export class FinanceSetupContractError extends Error { constructor(){super('The payment settings could not be verified.');} }
const fail=():never=>{throw new FinanceSetupContractError();};
type Obj=Record<string,unknown>;
type Schema={$ref?:string;anyOf?:Schema[];oneOf?:Schema[];type?:string;const?:unknown;enum?:unknown[];properties?:Record<string,Schema>;required?:readonly string[];items?:Schema;minimum?:number;maximum?:number;minLength?:number;maxLength?:number;minItems?:number;maxItems?:number;pattern?:string;'x-rules'?:readonly string[];'x-no-null'?:boolean};
const schemas=FINANCE_SETUP_SCHEMAS as unknown as Record<string,Schema>;
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
  if(s.anyOf||s.oneOf){for(const branch of s.anyOf??s.oneOf!){try{return shape(branch,v,depth+1);}catch(e){if(!(e instanceof FinanceSetupContractError))throw e;}}return fail();}
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
export type {Scope as FinanceSetupScope,Catalog as FinanceSetupCatalog,Detail as FinanceSetupDetail,Summary as FinanceSetupSummary,AccountProposal,CustomerProposal,Activation,Disable,Revoke,Binding,InstalledAccount} from './finance-setup-schema';
import type {Scope,Receipt,NotFound,AccountProposal,CustomerProposal,Activation,Disable,Revoke} from './finance-setup-schema';
export type FinanceSetupRequests={propose_account:AccountProposal;propose_customer:CustomerProposal;activate:Activation;disable:Disable;revoke:Revoke};
export type FinanceSetupKind=keyof FinanceSetupRequests;
export type FinanceSetupReceipt=Receipt|NotFound;
export type FinanceSetupOperation<K extends FinanceSetupKind=FinanceSetupKind>={version:1;scope:Scope;kind:K;request:FinanceSetupRequests[K];request_sha256:string};
export const FINANCE_SETUP_RECOVERY_BYTES=131072;
const models={propose_account:'AccountProposal',propose_customer:'CustomerProposal',activate:'Activation',disable:'Disable',revoke:'Revoke'} as const;
const states={propose_account:'pending_review',propose_customer:'pending_review',activate:'active',disable:'disabled',revoke:'revoked'} as const;
function model(name:string,value:unknown,depth=0):unknown{
  const v=shape(schemas[name],value,depth) as Obj;
  if(name==='Permissions'&&!v.read_status&&!v.create_unconfirmed_intents)fail();
  if(name==='Summary'&&(v.target as Obj).kind!==v.kind)fail();
  if(name==='Summary'&&v.usable_locally&&(v.state!=='active'||v.availability!=='available'))fail();
  if(name==='Receipt'&&(v.effect as Obj).state!==states[v.command_kind as FinanceSetupKind])fail();
  return v;
}
export function normalizeFinanceSetup<N extends FinanceSetupContractName>(name:N,value:unknown):FinanceSetupContractTypes[N]{vendorCanonical(value);return model(name,value) as FinanceSetupContractTypes[N];}
export function validateFinanceSetup<N extends FinanceSetupContractName>(name:N,value:unknown):FinanceSetupContractTypes[N]{const result=normalizeFinanceSetup(name,value);if(vendorCanonical(result)!==vendorCanonical(value))fail();return result;}
export async function prepareFinanceSetupOperation<K extends FinanceSetupKind>(scope:Scope,kind:K,request:FinanceSetupRequests[K]):Promise<FinanceSetupOperation<K>>{
  validateFinanceSetup('Scope',scope);if(!Object.hasOwn(models,kind))fail();const exact=normalizeFinanceSetup(models[kind],request) as FinanceSetupRequests[K];if(vendorBytes(exact)>8192)fail();
  return {version:1,scope:structuredClone(scope),kind,request:exact,request_sha256:await vendorDigest('cosmas-finance-setup-request.v1',{scope,command_kind:kind,request:exact})};
}
export async function validateFinanceSetupOperation(value:unknown,scope?:Scope):Promise<FinanceSetupOperation>{
  if(!vendorObject(value)||Object.keys(value).sort().join(',')!=='kind,request,request_sha256,scope,version'||value.version!==1||typeof value.kind!=='string'||!Object.hasOwn(models,value.kind))fail();
  const v=value as FinanceSetupOperation;if(scope&&vendorCanonical(scope)!==vendorCanonical(v.scope))fail();validateFinanceSetup(models[v.kind],v.request);const expected=await prepareFinanceSetupOperation(v.scope,v.kind,v.request);if(vendorCanonical(expected)!==vendorCanonical(v))fail();return expected;
}
export async function verifyFinanceSetupReceipt(value:unknown,operation?:FinanceSetupOperation):Promise<FinanceSetupReceipt>{
  if(!vendorObject(value))return fail();const r=value.outcome==='recorded'?validateFinanceSetup('Receipt',value):validateFinanceSetup('NotFound',value);
  if(operation&&(vendorCanonical(r.scope)!==vendorCanonical(operation.scope)||r.command_kind!==operation.kind||r.idempotency_key!==operation.request.idempotency_key||r.request_sha256!==operation.request_sha256))fail();
  if(r.outcome==='recorded'){
    const {receipt_sha256:_,...body}=r;if(await vendorDigest('cosmas-finance-setup-receipt.v1',body)!==r.receipt_sha256)fail();
    if(operation){const q=operation.request;if(r.effect.setup_id!==q.setup_id||r.effect.version!==q.expected_version+1)fail();if('revision_id'in q&&(r.effect.revision_id!==q.revision_id||r.effect.review_sha256!==q.review_sha256))fail();if(operation.kind==='propose_account'&&r.effect.kind!=='account'||operation.kind==='propose_customer'&&r.effect.kind!=='customer')fail();}
  }
  if(vendorBytes(r)>8192)fail();return r;
}
export async function verifyFinanceSetupView<N extends 'Catalog'|'Detail'|'History'>(name:N,value:unknown):Promise<FinanceSetupContractTypes[N]>{
  const v=validateFinanceSetup(name,value);if(vendorBytes(v)>(name==='Detail'?32768:131072))fail();
  if(name==='Catalog'){
    const c=v as FinanceSetupContractTypes['Catalog'];for(const ids of [c.installed_accounts.map(i=>i.installation_id),c.patients.map(p=>p.patient_link_id),c.setups.map(s=>s.setup_id)])if(new Set(ids).size!==ids.length)fail();
    if(!c.enabled&&c.setups.some(s=>s.usable_locally)||new Set(c.setups.map(s=>vendorCanonical(s.target))).size!==c.setups.length)fail();
  }
  if(name==='Detail'){
    const d=v as FinanceSetupContractTypes['Detail'],s=d.summary,r=d.review;
    if(s.kind!==r.kind||s.setup_id!==r.setup_id||s.revision_id!==r.revision_id||s.label!==r.label||s.review_sha256!==await vendorDigest('cosmas-finance-setup-review.v1',r))fail();
    if(r.kind==='account'?(s.target.kind!=='account'||s.target.installation_id!==r.installed.installation_id):(s.target.kind!=='customer'||s.target.account_setup_id!==r.account.setup_id||s.target.patient_link_id!==r.patient.patient_link_id))fail();
    const receipt=await verifyFinanceSetupReceipt(d.last_receipt);if(receipt.outcome!=='recorded'||vendorCanonical(receipt.scope)!==vendorCanonical(d.scope)||(['setup_id','kind','version','revision_id','review_sha256','state'] as const).some(k=>receipt.effect[k]!==s[k]))fail();
  }
  if(name==='History'){
    const h=v as FinanceSetupContractTypes['History'];const ids=new Set<string>(),keys=new Set<string>();let version=0;
    for(const item of h.receipts){const r=await verifyFinanceSetupReceipt(item);if(r.outcome!=='recorded')return fail();if(r.effect.setup_id!==h.setup_id||vendorCanonical(r.scope)!==vendorCanonical(h.scope)||r.effect.version<=version||ids.has(r.receipt_id)||keys.has(r.idempotency_key))fail();version=r.effect.version;ids.add(r.receipt_id);keys.add(r.idempotency_key);}
  }
  return v;
}
