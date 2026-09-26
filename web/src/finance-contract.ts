import {FINANCE_SCHEMAS,type FinanceContractName,type FinanceContractTypes,type FinanceResponse,type FinanceScope} from './finance-schema';
import {vendorCanonical,vendorBytes,vendorDigest,vendorObject,vendorUuid} from './vendor-contract';
export class FinanceContractError extends Error { constructor(){super('The payment request could not be verified.');} }
const fail=():never=>{throw new FinanceContractError();};
type Obj=Record<string,unknown>;
type Schema={$ref?:string;anyOf?:Schema[];oneOf?:Schema[];type?:string;const?:unknown;enum?:unknown[];properties?:Record<string,Schema>;required?:readonly string[];items?:Schema;minimum?:number;maximum?:number;minLength?:number;maxLength?:number;minItems?:number;maxItems?:number;pattern?:string;'x-rules'?:readonly string[];'x-no-null'?:boolean};
const schemas=FINANCE_SCHEMAS as unknown as Record<string,Schema>;
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
  if(s.anyOf||s.oneOf){for(const branch of s.anyOf??s.oneOf!){try{return shape(branch,v,depth+1);}catch(e){if(!(e instanceof FinanceContractError))throw e;}}return fail();}
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
const effects:Record<string,string[]>={propose:['proposed'],decide:['approved','rejected'],withdraw:['withdrawn'],submit:['submit_claimed'],reconcile:['read_claimed'],result:['result_recorded'],verify:['verified']};
function model(name:string,value:unknown,depth=0):unknown{
  const v=shape(schemas[name],value,depth) as Obj;
  if(name==='FinanceResponse'&&((v.effect!==null)!==(v.outcome==='recorded')||(v.receipt_sha256!==null)!==(v.outcome==='recorded')||v.effect&&!effects[v.command_kind as string]?.includes((v.effect as Obj).effect as string)))fail();
  if(name==='FinancePayment'&&((v.amount_received as number)>(v.amount as number)||v.payment_state==='succeeded'&&v.amount_received!==v.amount))fail();
  if(name==='FinanceReview'&&(v.customer as Obj).connection_id!==(v.connection as Obj).id)fail();
  if(name==='FinanceSummary'&&((v.amount_received as number)>(v.amount as number)||v.payment_state==='succeeded'&&v.amount_received!==v.amount||(v.verification==='verified')!==(v.state==='closed')))fail();
  const maximum=name==='FinanceResponse'?16384:name.startsWith('Finance')?65536:0;if(maximum&&vendorBytes(v)>maximum)fail();return v;
}
export function normalizeFinance<N extends FinanceContractName>(name:N,value:unknown):FinanceContractTypes[N]{vendorCanonical(value);return model(name,value) as FinanceContractTypes[N];}
export function validateFinance<N extends FinanceContractName>(name:N,value:unknown):FinanceContractTypes[N]{const v=normalizeFinance(name,value);if(vendorCanonical(v)!==vendorCanonical(value))fail();return v;}
const without=(v:Obj,key:string)=>Object.fromEntries(Object.entries(v).filter(([k])=>k!==key));
export async function verifyFinanceView<N extends FinanceContractName>(name:N,value:unknown):Promise<FinanceContractTypes[N]>{
  const v=validateFinance(name,value);
  const walk=async(node:unknown):Promise<void>=>{if(Array.isArray(node)){await Promise.all(node.map(walk));return;}if(!vendorObject(node))return;
    if('public_sha256'in node&&node.public_sha256!==await vendorDigest('cosmas-finance-public-selection.v1',without(node,'public_sha256')))fail();
    if(name==='FinanceObservations'&&'kind'in node&&'sequence'in node&&'sha256'in node&&node.sha256!==await vendorDigest('cosmas-finance-public-observation.v1',without(node,'sha256')))fail();
    await Promise.all(Object.values(node).map(walk));};await walk(v);
  if(name==='FinanceOptions'){const o=v as FinanceContractTypes['FinanceOptions'];if(new Set(o.connections.map(c=>c.id)).size!==o.connections.length||new Set(o.customers.map(c=>c.id)).size!==o.customers.length||o.customers.some(c=>!o.connections.some(x=>x.id===c.connection_id)))fail();}
  if(name==='FinanceCatalog'){const c=v as FinanceContractTypes['FinanceCatalog'];if(new Set(c.items.map(r=>r.ticket_id)).size!==c.items.length)fail();}
  if(name==='FinanceDetail'){
    const d=v as FinanceContractTypes['FinanceDetail'];
    if(d.review_sha256!==await vendorDigest('cosmas-finance-review.v1',d.review)||(['ticket_id','revision_id','operation_id','amount','currency'] as const).some(k=>d.summary[k]!==d.review[k])||(d.latest_result===null)!==(d.summary.result==='none')||d.latest_result&&d.latest_result.disposition!==d.summary.result)fail();
    if(d.summary.evidence_sha256!==await vendorDigest('cosmas-finance-evidence.v1',{operation_id:d.summary.operation_id,observation_head:d.summary.observation_head,result_receipt_id:d.latest_result?.receipt_id??null,result_receipt_sha256:d.latest_result?.receipt_sha256??null}))fail();
  }
  if(name==='FinanceObservations'){const p=v as FinanceContractTypes['FinanceObservations'];let last=0;const ids=new Set<string>();for(const row of p.observations){if(row.operation_id!==p.operation_id||row.sequence<=last||row.sequence>p.observation_head.sequence||ids.has(row.id))fail();last=row.sequence;ids.add(row.id);}}
  return v;
}
export type FinanceReceiptExpectation={scope:FinanceScope;kind:string;key:string;sha256:string;ticketId?:string;operationId?:string;revisionId?:string;payloadHash?:string};
export async function verifyFinanceReceipt(value:unknown,expected:FinanceReceiptExpectation):Promise<FinanceResponse>{
  const v=validateFinance('FinanceResponse',value);
  if(vendorCanonical(v.scope)!==vendorCanonical(expected.scope)||v.command_kind!==expected.kind||v.idempotency_key!==expected.key||v.request_sha256!==expected.sha256)fail();
  if(v.effect){for(const [key,field] of [['ticketId','ticket_id'],['operationId','operation_id'],['revisionId','revision_id'],['payloadHash','payload_hash']] as const)if(expected[key]!==undefined&&expected[key]!==v.effect[field])fail();
    if(v.receipt_sha256!==await vendorDigest('cosmas-finance-public-receipt.v1',{scope:v.scope,command_kind:v.command_kind,idempotency_key:v.idempotency_key,request_sha256:v.request_sha256,effect:v.effect}))fail();}
  return v;
}
