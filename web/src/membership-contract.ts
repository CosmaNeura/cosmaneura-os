import {MEMBERSHIP_SCHEMAS,type MembershipContractName,type MembershipContractTypes} from './membership-schema';
import {vendorCanonical,vendorBytes,vendorDigest,vendorObject,vendorUuid} from './vendor-contract';
export class MembershipContractError extends Error { constructor(){super('The membership review could not be verified.');} }
const fail=():never=>{throw new MembershipContractError();};
type Obj=Record<string,unknown>;
type Schema={$ref?:string;anyOf?:Schema[];oneOf?:Schema[];type?:string;const?:unknown;enum?:unknown[];properties?:Record<string,Schema>;required?:readonly string[];items?:Schema;minimum?:number;maximum?:number;minLength?:number;maxLength?:number;minItems?:number;maxItems?:number;pattern?:string;'x-rules'?:readonly string[];'x-no-null'?:boolean};
const schemas=MEMBERSHIP_SCHEMAS as unknown as Record<string,Schema>;
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
  if(s.anyOf||s.oneOf){for(const branch of s.anyOf??s.oneOf!){try{return shape(branch,v,depth+1);}catch(e){if(!(e instanceof MembershipContractError))throw e;}}return fail();}
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
import type {Detail,Result,Scope,Response,MembershipRetirementResponse} from './membership-schema';
export type MembershipResponse=Response|MembershipRetirementResponse;
export const membershipClassification=(r:Result|undefined|null)=>r?.ledger?r.ledger.finance?'manual_ledger_and_finance_review':'manual_ledger_record':'local_unreconciled';
const effects:Record<string,string[]>={propose:['proposed'],decide:['approved','rejected'],result:['result_recorded'],verify:['review_verified'],withdraw:['withdrawn']};
function model(name:string,value:unknown,depth=0):unknown{
 const v=shape(schemas[name],value,depth) as Obj;
 if('expected_version'in v&&(v.expected_version as number)>100||name==='Effect'&&(v.version as number)>100||name==='Summary'&&(v.version as number)>100)fail();
 if(name==='Result'&&((v.disposition==='record_reviewed')!==Object.hasOwn(v,'ledger')))fail();
 if(name==='Review'&&v.patient_link_id!==(v.proposal as Obj).patient_link_id)fail();
 if(name==='Response'&&((v.effect!==null)!==(v.outcome==='recorded')||(v.receipt_sha256!==null)!==(v.outcome==='recorded')||v.effect&&!effects[v.command_kind as string]?.includes((v.effect as Obj).effect as string)))fail();
 if(name==='Summary'){
  if((v.state==='closed')!==(v.verification==='review_verified')||(v.result==='record_reviewed')!==(v.evidence_classification!=='local_unreconciled')||(v.evidence_classification==='local_unreconciled')!==(v.evidence_current==='none'))fail();
  if(v.can_verify&&(!v.source_current||v.state!=='approved'||!['local_preparation_ready','record_reviewed'].includes(v.result as string)||v.evidence_current==='changed'||(v.version as number)>=100))fail();
 }
 return v;
}
export function normalizeMembership<N extends MembershipContractName>(name:N,value:unknown):MembershipContractTypes[N]{vendorCanonical(value);return model(name,value) as MembershipContractTypes[N];}
export function validateMembership<N extends MembershipContractName>(name:N,value:unknown):MembershipContractTypes[N]{const v=normalizeMembership(name,value);if(vendorCanonical(v)!==vendorCanonical(value))fail();return v;}
export const sameMembershipScope=(a:Scope,b:Scope)=>vendorCanonical(a)===vendorCanonical(b);
export async function verifyMembershipReceipt(value:unknown):Promise<MembershipResponse>{
 if(vendorObject(value)&&value.outcome==='retired'){
  const r=validateMembership('MembershipRetirementResponse',value);if(vendorBytes(r)>8192)fail();
  const {receipt_sha256:_,...body}=r;if(r.receipt_sha256!==await vendorDigest('cosmas-membership-retirement.v1',body))fail();return r;
 }
 const r=validateMembership('Response',value);if(vendorBytes(r)>8192)fail();
 if(r.outcome==='recorded'){const {receipt_sha256:_,...body}=r;if(r.receipt_sha256!==await vendorDigest('cosmas-membership-receipt.v1',body))fail();}
 return r;
}
export async function verifyMembershipView<N extends 'Options'|'Catalog'|'Detail'|'History'>(name:N,value:unknown):Promise<MembershipContractTypes[N]>{
 const v=validateMembership(name,value);const limit={Options:8192,Catalog:131072,Detail:32768,History:1048576}[name];if(vendorBytes(v)>limit)fail();
 if(name==='Catalog'){const c=v as MembershipContractTypes['Catalog'];if(new Set(c.items.map(s=>s.ticket_id)).size!==c.items.length)fail();}
 if(name==='Detail'){
  const d=v as Detail,s=d.summary,r=d.review;
  if(d.review_sha256!==await vendorDigest('cosmas-membership-review.v1',r)||s.ticket_id!==r.ticket_id||s.revision_id!==r.revision_id||s.purpose!==r.proposal.purpose||s.due_date!==r.proposal.due_date||(d.latest_result===null)!==(s.result==='none'))fail();
  if(d.latest_result){const q=d.latest_result.request;if(q.ticket_id!==s.ticket_id||q.revision_id!==s.revision_id||q.payload_hash!==s.payload_hash||q.expected_version>=s.version||q.disposition!==s.result||membershipClassification(q)!==s.evidence_classification)fail();}
 }
 return v;
}
