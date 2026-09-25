import {VENDOR_SCHEMAS, type VendorContractName, type VendorContractTypes, type Scope, type CommandResponse, type ArtifactResponse, type RetirementResponse, type PreparationCommandRetirementResponse, type PreparationArtifactRetirementResponse} from './vendor-schema';
export type VendorRetirementReceipt=RetirementResponse|PreparationCommandRetirementResponse|PreparationArtifactRetirementResponse;
export type VendorReceipt=CommandResponse|ArtifactResponse|VendorRetirementReceipt;

export class VendorContractError extends Error { constructor(){super('The delivery response could not be verified.');} }
const fail=():never=>{throw new VendorContractError();};
export const vendorUuid=(v:unknown):v is string=>typeof v==='string'&&v.length===36&&/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(v);
export const VENDOR_DOCUMENT_BYTES=8388608;
export const VENDOR_JOURNAL_BYTES=131072;
const encoder=new TextEncoder();
type Obj=Record<string,unknown>;
type Schema={$ref?:string;anyOf?:Schema[];type?:string;const?:unknown;enum?:unknown[];properties?:Record<string,Schema>;required?:readonly string[];items?:Schema;minimum?:number;maximum?:number;minLength?:number;maxLength?:number;minItems?:number;maxItems?:number;pattern?:string;'x-rules'?:readonly string[];'x-no-null'?:boolean;title?:string};
const schemas=VENDOR_SCHEMAS as unknown as Record<string,Schema>;
export const vendorObject=(v:unknown):v is Obj=>!!v&&typeof v==='object'&&!Array.isArray(v)&&(Object.getPrototypeOf(v)===Object.prototype||Object.getPrototypeOf(v)===null);
const validString=(v:string)=>{for(let i=0;i<v.length;i++){const n=v.charCodeAt(i);if(n>=0xd800&&n<=0xdbff){const next=v.charCodeAt(++i);if(!(next>=0xdc00&&next<=0xdfff))fail();}else if(n>=0xdc00&&n<=0xdfff)fail();}return v;};
export function vendorCanonical(value:unknown,depth=0):string {
  if(depth>30)fail();
  if(value===null||typeof value==='boolean')return JSON.stringify(value);
  if(typeof value==='string')return JSON.stringify(validString(value));
  if(typeof value==='number'){if(!Number.isInteger(value)||Math.abs(value)>2147483647)fail();return JSON.stringify(value);}
  if(Array.isArray(value)){if(Object.keys(value).length!==value.length||Object.keys(value).some((k,i)=>k!==String(i))||Reflect.ownKeys(value).length!==value.length+1)fail();return '['+Array.from(value,v=>vendorCanonical(v,depth+1)).join(',')+']';}
  if(!vendorObject(value))return fail();
  if(Reflect.ownKeys(value).length!==Object.keys(value).length||Object.values(Object.getOwnPropertyDescriptors(value)).some(p=>!('value'in p)))fail();
  return '{'+Object.keys(value).sort().map(key=>{if(!/^[\x00-\x7f]*$/.test(key))fail();return JSON.stringify(key)+':'+vendorCanonical(value[key],depth+1);}).join(',')+'}';
}
export const vendorBytes=(value:unknown)=>encoder.encode(vendorCanonical(value)).byteLength;
export async function vendorSha256(bytes:Uint8Array):Promise<string>{const copy=new Uint8Array(bytes);return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',copy)),n=>n.toString(16).padStart(2,'0')).join('');}
export const vendorDigest=(domain:string,value:unknown)=>vendorSha256(encoder.encode(vendorCanonical({domain,value})));
export const vendorRequestDigest=(kind:string,scope:Scope,request:unknown)=>vendorDigest('cosmas-vendor-public-request.v1',{command_kind:kind,scope,request});

/** A bounded wire parser: duplicate keys and float/exponent number spellings cannot disappear in JSON.parse. */
export function parseVendorJson(text:string):unknown {
  let at=0;
  const ws=()=>{while(/[\t\n\r ]/.test(text[at]??'!'))at++;};
  const string=()=>{const start=at++;while(at<text.length){const c=text[at++];if(c==='"'){try{return validString(JSON.parse(text.slice(start,at)) as string);}catch{return fail();}}if(c==='\\')at++;}return fail();};
  const value=(depth:number):unknown=>{
    if(depth>30)fail();ws();const c=text[at];
    if(c==='"')return string();
    if(c==='{'){at++;ws();const result:Obj=Object.create(null);if(text[at]==='}'){at++;return result;}while(at<text.length){if(text[at]!=='"')fail();const key=string();if(Object.hasOwn(result,key)||!/^[\x00-\x7f]*$/.test(key))fail();ws();if(text[at++]!==':')fail();result[key]=value(depth+1);ws();if(text[at]==='}'){at++;return result;}if(text[at++]!==',')fail();ws();}return fail();}
    if(c==='['){at++;ws();const result:unknown[]=[];if(text[at]===']'){at++;return result;}while(at<text.length){result.push(value(depth+1));ws();if(text[at]===']'){at++;return result;}if(text[at++]!==',')fail();}return fail();}
    for(const [token,v] of [['true',true],['false',false],['null',null]] as const){if(text.startsWith(token,at)){at+=token.length;return v;}}
    const match=/^-?(?:0|[1-9][0-9]*)/.exec(text.slice(at));if(!match)return fail();at+=match[0].length;const n=Number(match[0]);if(!Number.isInteger(n)||Math.abs(n)>2147483647)fail();return n;
  };
  const parsed=value(0);ws();if(at!==text.length)fail();vendorCanonical(parsed);return parsed;
}

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
  if(s.anyOf){for(const branch of s.anyOf){try{return shape(branch,v,depth+1);}catch(e){if(!(e instanceof VendorContractError))throw e;}}return fail();}
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
const allowedActions:Record<string,string[]>={spruce:['spruce_secure_message','spruce_fax','spruce_media_upload'],srfax:['srfax_fax'],documo:['documo_fax']};
function actionUnion(v:Obj,media:string){const permitted:Record<string,[string[],string[]]>={spruce_secure_message:[['correspondence','message'],[media]],spruce_fax:[['correspondence',media],[]],spruce_media_upload:[['document'],[]],srfax_fax:[['correspondence','document'],[]],documo_fax:[['correspondence','document'],[]]};const [required,optional]=permitted[v.action as string]??fail();if(required.some(k=>v[k]===undefined)||['correspondence','document','message',media].some(k=>v[k]!==undefined&&!required.includes(k)&&!optional.includes(k)))fail();}
function model(name:string,value:unknown,depth=0):unknown {
  const v=shape(schemas[name],value,depth) as Obj;
  if(name==='VendorRetire')model(({decide:'VendorDecision',submit:'BoundCommand',verify:'VendorVerify'} as Record<string,string>)[v.command_kind as string],v.request,depth+1);
  if(name==='VendorPreparationRetire'){
    model(({propose:'VendorProposal',artifact_intent:'VendorArtifactIntent',artifact_content:'VendorArtifactContent'} as Record<string,string>)[v.command_kind as string],v.request,depth+1);
    if(vendorBytes(v.request)>(v.command_kind==='propose'?32768:2048))fail();
  }
  if(name==='VendorProposal'){actionUnion(v,'uploaded_media_operation_id');if((v.supersedes_operation_id!==undefined)!==(v.acknowledge_prior_uncertainty===true)||v.supersedes_operation_id!==undefined&&v.revises!==undefined)fail();}
  if(name==='VendorHandoff'&&((v.kind==='offer')!==(v.recipient_id!==undefined)||(['accept','decline','recall'].includes(v.kind as string))!==(v.offer_id!==undefined)))fail();
  if(name==='ConnectionView'){const acts=v.actions as string[];if(new Set(acts).size!==acts.length||acts.some(a=>!allowedActions[v.vendor as string].includes(a))||v.vendor!=='documo'&&v.environment!=='production')fail();}
  if(name==='Availability'&&v.allowed!==(v.reason==='available'))fail();
  if(name==='Review'){actionUnion(v,'uploaded_media');const c=v.connection as Obj;const to=v.correspondence as Obj|undefined;if(!(c.actions as string[]).includes(v.action as string)||to&&(to.connection_id!==c.id||to.channel!==(v.action==='spruce_secure_message'?'secure':'fax')))fail();}
  if(name==='Observation'){const fields={submission:'acceptance',transport:'transport',dispatch:'dispatch'};if(v[fields[v.kind as keyof typeof fields]]===undefined||Object.values(fields).filter(k=>v[k]!==undefined).length!==1||(v.pages_total===undefined)!==(v.pages_delivered===undefined)||v.pages_total!==undefined&&(v.kind!=='transport'||(v.pages_delivered as number)>(v.pages_total as number)))fail();}
  if(name==='CommandResponse'&&((v.effect!==null)!==(v.outcome==='recorded')||(v.summary!==null)!==(v.outcome==='recorded')))fail();
  if(name==='ArtifactResponse'&&((v.scope as Obj).kind!=='workspace'||(v.effect!==null)!==(v.outcome==='recorded')||v.outcome==='recorded'&&v.artifact===null))fail();
  if(name==='ArtifactMetadata'&&(v.document as Obj).artifact_id!==v.artifact_id)fail();
  const max:Record<string,number>={ConnectionView:2048,CorrespondenceView:2048,Summary:1536,Observation:2048,Options:65536,Catalog:65536,Detail:65536,ObservationPage:65536,CommandResponse:16384,ArtifactResponse:8192,SharedVendorWork:65536,SharedVendorDetail:65536,VendorRetire:4096,RetirementResponse:16384,VendorPreparationRetire:33792,PreparationCommandRetirementResponse:16384,PreparationArtifactRetirementResponse:8192};if(max[name]&&vendorBytes(v)>max[name])fail();return v;
}
export function normalizeVendor<N extends VendorContractName>(name:N,value:unknown):VendorContractTypes[N] {vendorCanonical(value);return model(name,value) as VendorContractTypes[N];}
export function validateVendor<N extends VendorContractName>(name:N,value:unknown):VendorContractTypes[N] {const result=normalizeVendor(name,value);if(vendorCanonical(result)!==vendorCanonical(value))fail();return result;}
const without=(value:Obj,key:string)=>Object.fromEntries(Object.entries(value).filter(([k])=>k!==key));
export async function verifyVendorView<N extends VendorContractName>(name:N,value:unknown):Promise<VendorContractTypes[N]> {
  const v=validateVendor(name,value);
  const walk=async(node:unknown):Promise<void>=>{if(Array.isArray(node)){await Promise.all(node.map(walk));return;}if(!vendorObject(node))return;
    if('public_sha256'in node){if(node.public_sha256!==await vendorDigest('cosmas-vendor-public-selection.v1',without(node,'public_sha256')))fail();}
    if(name==='ObservationPage'&&'sequence'in node&&'kind'in node&&'sha256'in node&&node.kind!=='workspace'){if(node.sha256!==await vendorDigest('cosmas-vendor-public-observation.v1',without(node,'sha256')))fail();}
    await Promise.all(Object.values(node).map(walk));};
  await walk(v);
  if(name==='Detail'){const d=v as VendorContractTypes['Detail'];if(d.review_sha256!==await vendorDigest('cosmas-vendor-public-review.v1',d.review)||d.view_version!==d.summary.version||(['ticket_id','revision_id','operation_id','action'] as const).some(k=>d.summary[k]!==d.review[k])||d.summary.due_date!==d.review.due_date)fail();}
  if(name==='ObservationPage'){const p=v as VendorContractTypes['ObservationPage'];let last=0;for(const row of p.observations){if(row.operation_id!==p.operation_id||row.sequence<=last||row.sequence>p.head.sequence)fail();last=row.sequence;}}
  return v;
}
export type VendorReceiptExpectation={scope:Scope;kind:string;key:string;sha256:string;ticketId?:string;operationId?:string;revisionId?:string;payloadHash?:string;artifactId?:string};
export async function verifyVendorReceipt(value:unknown,expected:VendorReceiptExpectation,artifact=false):Promise<VendorReceipt>{
  if(vendorObject(value)&&value.outcome==='retired'&&(expected.kind==='propose'||['artifact_intent','artifact_content'].includes(expected.kind))){
    if(artifact!==expected.kind.startsWith('artifact_'))fail();
    const v=artifact?validateVendor('PreparationArtifactRetirementResponse',value):validateVendor('PreparationCommandRetirementResponse',value);
    if(vendorCanonical(v.scope)!==vendorCanonical(expected.scope)||v.command_kind!==expected.kind||v.idempotency_key!==expected.key||v.request_sha256!==expected.sha256)fail();
    if(v.retirement.receipt_sha256!==await vendorDigest('cosmas-vendor-public-preparation-retirement.v1',{scope:v.scope,command_kind:v.command_kind,idempotency_key:v.idempotency_key,request_sha256:v.request_sha256,retirement:without(v.retirement,'receipt_sha256')}))fail();
    return v;
  }
  if(!artifact&&vendorObject(value)&&value.outcome==='retired'){
    const v=validateVendor('RetirementResponse',value),r=v.retirement;
    if(vendorCanonical(v.scope)!==vendorCanonical(expected.scope)||v.command_kind!==expected.kind||v.idempotency_key!==expected.key||v.request_sha256!==expected.sha256)fail();
    for(const [key,actual] of [['ticketId','ticket_id'],['operationId','operation_id'],['revisionId','revision_id'],['payloadHash','payload_hash']] as const)if(expected[key]!==undefined&&expected[key]!==r[actual])fail();
    if(r.receipt_sha256!==await vendorDigest('cosmas-vendor-public-retirement.v1',{scope:v.scope,command_kind:v.command_kind,idempotency_key:v.idempotency_key,request_sha256:v.request_sha256,retirement:without(r,'receipt_sha256')}))fail();return v;
  }
  const v=artifact?validateVendor('ArtifactResponse',value):validateVendor('CommandResponse',value);
  if(vendorCanonical(v.scope)!==vendorCanonical(expected.scope)||v.command_kind!==expected.kind||v.idempotency_key!==expected.key||v.request_sha256!==expected.sha256)fail();
  if(v.effect){const effect=v.effect as unknown as Obj;for(const [key,actual] of [['ticketId','ticket_id'],['operationId','operation_id'],['revisionId','revision_id'],['payloadHash','payload_hash'],['artifactId','artifact_id']] as const){if(expected[key]!==undefined&&effect[actual]!==expected[key])fail();}
    const commitment={scope:v.scope,command_kind:v.command_kind,idempotency_key:v.idempotency_key,request_sha256:v.request_sha256,effect:without(effect,'receipt_sha256'),...(!artifact?{summary:(v as CommandResponse).summary}:{})};if(effect.receipt_sha256!==await vendorDigest('cosmas-vendor-public-receipt.v1',commitment))fail();}
  if(artifact){const a=(v as ArtifactResponse).artifact;if(a&&expected.artifactId&&a.artifact_id!==expected.artifactId)fail();}
  return v;
}
