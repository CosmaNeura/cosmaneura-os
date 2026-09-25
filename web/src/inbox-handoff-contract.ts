import {INBOX_HANDOFF_SCHEMAS,type InboxHandoffContractName,type InboxHandoffContractTypes,type Scope,type Propose,type Decide,type Handoff,type Result,type Verify,type Response,type NotFound,type InboxHandoffReceipt,type InboxHandoffResponse,type Detail,type Summary,type Responsibility} from './inbox-handoff-schema';
import {vendorBytes,vendorCanonical,vendorDigest,vendorObject,vendorUuid} from './vendor-contract';
export type {InboxHandoffReceipt,InboxHandoffResponse,Recorded,Rejected,NotFound} from './inbox-handoff-schema';
export class InboxHandoffContractError extends Error {
  constructor(){super('The internal Inbox handoff response could not be verified.');}
}
const fail=():never=>{throw new InboxHandoffContractError();};
type Obj=Record<string,unknown>;
type Schema={$ref?:string;anyOf?:Schema[];type?:string;const?:unknown;enum?:unknown[];properties?:Record<string,Schema>;required?:readonly string[];items?:Schema;minimum?:number;maximum?:number;minLength?:number;maxLength?:number;minItems?:number;maxItems?:number;pattern?:string;'x-rules'?:readonly string[];'x-no-null'?:boolean};
const schemas=INBOX_HANDOFF_SCHEMAS as unknown as Record<string,Schema>;
const pythonBlank=/^[\t\n\v\f\r \x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]*$/;
function day(v:unknown):boolean {
  if(typeof v!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(v)||v.slice(0,4)==='0000')return false;
  const d=new Date(v+'T00:00:00.000Z');return !Number.isNaN(d.valueOf())&&d.toISOString().slice(0,10)===v;
}
function timestamp(v:unknown):boolean {
  if(typeof v!=='string'||!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$/.test(v)||!day(v.slice(0,10)))return false;
  const d=new Date(v);return !Number.isNaN(d.valueOf())&&d.toISOString()===v.slice(0,23)+'Z';
}
function rule(name:string,v:unknown):unknown {
  if(name==='_text'){
    if(typeof v!=='string')return fail();
    const text=v.replace(/\r\n?/g,'\n');vendorCanonical(text);
    if(/[\x00-\x08\x0b-\x1f\x7f]/.test(text)||pythonBlank.test(text))fail();return text;
  }
  if(name==='_uuid'&&!vendorUuid(v)||name==='_day'&&!day(v)||name==='_timestamp'&&!timestamp(v)||name==='_true'&&v!==true||name==='_version'&&v!==1)fail();
  return v;
}
function shape(s:Schema,v:unknown,depth=0):unknown {
  if(depth>30)fail();
  if(s.$ref){const name=s.$ref.split('/').pop()!;if(!schemas[name])fail();return model(name,v,depth+1);}
  for(const name of s['x-rules']??[])v=rule(name,v);
  if(s.anyOf){for(const branch of s.anyOf){try{return shape(branch,v,depth+1);}catch(e){if(!(e instanceof InboxHandoffContractError))throw e;}}return fail();}
  if(Object.hasOwn(s,'const')&&s.const!==v||s.enum&&!s.enum.includes(v))fail();
  switch(s.type){
    case 'null':if(v!==null)fail();return v;
    case 'boolean':if(typeof v!=='boolean')fail();return v;
    case 'integer':if(typeof v!=='number'||!Number.isInteger(v)||v<(s.minimum??-2147483647)||v>(s.maximum??2147483647))fail();return v;
    case 'string':{
      if(typeof v!=='string')return fail();vendorCanonical(v);const count=Array.from(v).length;
      if(count<(s.minLength??0)||count>(s.maxLength??Infinity)||s.pattern&&new RegExp(s.pattern).exec(v)?.[0]!==v)fail();return v;
    }
    case 'array':if(!Array.isArray(v)||v.length<(s.minItems??0)||v.length>(s.maxItems??Infinity))return fail();return v.map(c=>shape(s.items!,c,depth+1));
    case 'object':{
      if(!vendorObject(v))return fail();const properties=s.properties??{};
      if(Object.keys(v).some(k=>!Object.hasOwn(properties,k))||(s.required??[]).some(k=>!Object.hasOwn(v,k)))fail();
      const result:Obj={};for(const [key,value] of Object.entries(v)){if(s['x-no-null']&&value===null)fail();result[key]=shape(properties[key],value,depth+1);}return result;
    }
    default:return fail();
  }
}
function summaryInvariant(s:Summary){
  if(s.requires_owner_attention!==(s.state==='source_unavailable')||s.publication_active!==Boolean(s.publication_receipt_id&&s.state!=='source_unavailable'))fail();
  if(['pending_approval','rejected'].includes(s.state)&&s.publication_receipt_id!==null||s.state==='closed'&&!s.verified_current||s.verified_current&&(s.state!=='closed'||!s.publication_active)||!s.originator_available&&!s.requires_owner_attention)fail();
  if(['approved','closed'].includes(s.state)&&!s.publication_active)fail();
}
function model(name:string,value:unknown,depth=0):unknown {
  const v=shape(schemas[name],value,depth) as Obj;
  if(name==='Handoff'&&((v.kind==='offer')!==Object.hasOwn(v,'recipient_id')||['accept','decline','recall'].includes(v.kind as string)!==Object.hasOwn(v,'offer_id')))fail();
  if(name==='Response'){
    const r=v as unknown as Response;
    if(r.outcome==='recorded'?r.effect===null||r.rejection!==null:r.effect!==null||r.rejection===null)fail();
    if(r.scope.kind!==(r.command_kind==='propose'?'workspace':'ticket')||['propose','decide','verify'].includes(r.command_kind)&&r.scope.actor_id!==r.scope.owner_id)fail();
    if(r.effect){
      const e=r.effect;
      if(r.command_kind==='propose'?(e.version!==1||e.state!=='pending_approval'||e.effect_id!==e.revision_id):(e.ticket_id!==r.scope.id||e.version<2))fail();
      if(r.command_kind==='decide'&&!['approved','rejected'].includes(e.state)||['handoff','result'].includes(r.command_kind)&&e.state!=='approved'||r.command_kind==='verify'&&e.state!=='closed')fail();
    }
  }
  if(name==='Summary'||name==='Detail')summaryInvariant(v as unknown as Summary);
  if(name==='Responsibility'){
    const h=v as unknown as Responsibility;
    if(h.from_id===h.to_id||(['accept','decline','recall'].includes(h.kind))!==(h.offer_id!==null))fail();
  }
  return v;
}
export function normalizeInboxHandoff<N extends InboxHandoffContractName>(name:N,value:unknown):InboxHandoffContractTypes[N]{vendorCanonical(value);return model(name,value) as InboxHandoffContractTypes[N];}
export function validateInboxHandoff<N extends InboxHandoffContractName>(name:N,value:unknown):InboxHandoffContractTypes[N]{const exact=normalizeInboxHandoff(name,value);if(vendorCanonical(exact)!==vendorCanonical(value))fail();return exact;}
export const sameInboxHandoffScope=(a:Scope,b:Scope)=>vendorCanonical(a)===vendorCanonical(b);
export type InboxHandoffActor={box_id:string;actor_id:string};
export function validateInboxHandoffActor(value:unknown):InboxHandoffActor{
  vendorCanonical(value);if(!vendorObject(value)||Object.keys(value).sort().join(',')!=='actor_id,box_id'||!vendorUuid(value.box_id)||!vendorUuid(value.actor_id))return fail();return {box_id:value.box_id,actor_id:value.actor_id};
}
export type InboxHandoffRequests={propose:Propose;decide:Decide;handoff:Handoff;result:Result;verify:Verify};
export type InboxHandoffKind=keyof InboxHandoffRequests;
export type InboxHandoffOperation<K extends InboxHandoffKind=InboxHandoffKind>={[P in InboxHandoffKind]:{version:1;scope:Scope;kind:P;request:InboxHandoffRequests[P];request_sha256:string}}[K];
export type InboxHandoffSaved={operation:InboxHandoffOperation;receipt:Response};
const models={propose:'Propose',decide:'Decide',handoff:'Handoff',result:'Result',verify:'Verify'} as const;
export async function prepareInboxHandoffOperation<K extends InboxHandoffKind>(scope:Scope,kind:K,request:InboxHandoffRequests[K]):Promise<InboxHandoffOperation<K>>{
  const binding=validateInboxHandoff('Scope',scope);if(!Object.hasOwn(models,kind))fail();
  const exact=normalizeInboxHandoff(models[kind],request);
  if(vendorBytes(exact)>8192||binding.kind!==(kind==='propose'?'workspace':'ticket')||kind!=='propose'&&(!('ticket_id'in exact)||exact.ticket_id!==binding.id)||['propose','decide','verify'].includes(kind)&&binding.actor_id!==binding.owner_id)fail();
  return {version:1,scope:binding,kind,request:exact,request_sha256:await vendorDigest('cosmas-inbox-handoff-request.v1',{scope:binding,command_kind:kind,request:exact})} as InboxHandoffOperation<K>;
}
export async function validateInboxHandoffOperation(value:unknown,scope?:Scope):Promise<InboxHandoffOperation>{
  vendorCanonical(value);if(!vendorObject(value)||Object.keys(value).sort().join(',')!=='kind,request,request_sha256,scope,version'||value.version!==1||typeof value.kind!=='string'||!Object.hasOwn(models,value.kind))fail();
  const op=value as InboxHandoffOperation;if(scope&&!sameInboxHandoffScope(scope,op.scope))fail();validateInboxHandoff(models[op.kind],op.request);
  const exact=await prepareInboxHandoffOperation(op.scope,op.kind,op.request);if(vendorCanonical(exact)!==vendorCanonical(op))fail();return exact;
}
function notFound(value:unknown):NotFound{
  vendorCanonical(value);if(!vendorObject(value)||Object.keys(value).sort().join(',')!=='command_kind,contract_version,effect,idempotency_key,outcome,request_sha256,scope'||value.contract_version!==1||value.outcome!=='not_found'||value.effect!==null||value.scope!==null)fail();
  const {command_kind,idempotency_key,request_sha256}=value as NotFound;
  validateInboxHandoff('Resolve',{command_kind,idempotency_key,request_sha256});return value as NotFound;
}
export async function verifyInboxHandoffReceipt(value:unknown):Promise<InboxHandoffReceipt>{
  if(vendorBytes(value)>16384)fail();if(vendorObject(value)&&value.outcome==='not_found')return notFound(value);
  const r=validateInboxHandoff('Response',value),{receipt_sha256:_,...body}=r;
  if(r.receipt_sha256!==await vendorDigest('cosmas-inbox-handoff-receipt.v1',body))fail();return r as InboxHandoffResponse;
}
export async function inboxHandoffPayloadHash(value:Pick<Propose,'instructions'|'selected_context'|'due_date'|'expected_outcome'>):Promise<string>{
  const payload={action:'incoming_message.internal_publication',channel:'internal_work',body:value.instructions,selected_context:value.selected_context??null,due_date:value.due_date,expected_outcome:value.expected_outcome};
  const ascii=vendorCanonical(payload).replace(/[^\x00-\x7f]/g,c=>'\\u'+c.charCodeAt(0).toString(16).padStart(4,'0'));
  return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(ascii))),b=>b.toString(16).padStart(2,'0')).join('');
}
export async function verifyInboxHandoffOperationReceipt(operation:InboxHandoffOperation,value:unknown):Promise<InboxHandoffReceipt>{
  const op=await validateInboxHandoffOperation(operation),r=await verifyInboxHandoffReceipt(value);
  if(r.command_kind!==op.kind||r.idempotency_key!==op.request.idempotency_key||r.request_sha256!==op.request_sha256||r.outcome!=='not_found'&&!sameInboxHandoffScope(r.scope,op.scope))fail();
  if(r.outcome==='recorded'&&r.effect){
    const e=r.effect;
    if(op.kind==='propose'&&e.payload_hash!==await inboxHandoffPayloadHash(op.request))fail();
    if(op.kind!=='propose'&&(e.ticket_id!==op.request.ticket_id||e.version!==op.request.expected_version+1||e.revision_id!==op.request.revision_id||e.payload_hash!==op.request.payload_hash))fail();
    if(op.kind==='decide'&&e.state!==(op.request.choice==='approve'?'approved':'rejected'))fail();
  }
  return r;
}
export function inboxHandoffOperationPath(op:InboxHandoffOperation):string{
  validateInboxHandoff('Scope',op.scope);if(!Object.hasOwn(models,op.kind)||op.scope.kind!==(op.kind==='propose'?'workspace':'ticket')||op.kind!=='propose'&&op.request.ticket_id!==op.scope.id)fail();
  return op.kind==='propose'?`/workspaces/${op.scope.id}/inbox-handoffs/propose`:`/inbox-handoffs/${op.scope.id}/${op.kind}`;
}
export const inboxHandoffResolvePath=(op:InboxHandoffOperation)=>inboxHandoffOperationPath(op).replace(/\/[^/]+$/,'/resolve');
export const inboxHandoffResolveRequest=(op:InboxHandoffOperation):InboxHandoffContractTypes['Resolve']=>({command_kind:op.kind,idempotency_key:op.request.idempotency_key,request_sha256:op.request_sha256});
function responsibility(d:Detail){
  const ids=new Set<string>();let current=d.originator_id,pending:Responsibility|null=null;
  for(const h of d.handoffs){
    if(ids.has(h.id)||h.from_id!==current)fail();ids.add(h.id);
    if(h.kind==='offer'){if(pending)fail();pending=h;}
    else if(h.kind==='reclaim'){if(h.to_id!==d.originator_id||h.from_id===d.originator_id)fail();current=h.to_id;pending=null;}
    else{if(!pending||h.offer_id!==pending.id||h.to_id!==pending.to_id)fail();if(h.kind==='accept')current=h.to_id;pending=null;}
  }
  if(current!==d.responsible_id||d.handoffs.length&&d.publication_receipt_id===null)fail();
  if(d.result&&d.result.actor_id!==d.originator_id&&!d.handoffs.some(h=>h.kind==='accept'&&h.to_id===d.result!.actor_id))fail();
}
export async function verifyInboxHandoffView<N extends 'Catalog'|'Detail'>(name:N,value:unknown,scope?:Scope):Promise<InboxHandoffContractTypes[N]>{
  const v=validateInboxHandoff(name,value);if(vendorBytes(v)>(name==='Catalog'?131072:65536))fail();
  if(name==='Catalog'){
    const c=v as InboxHandoffContractTypes['Catalog'];if(new Set(c.items.map(s=>s.ticket_id)).size!==c.items.length)fail();
  }else{
    const d=v as Detail;responsibility(d);
    if(scope){validateInboxHandoff('Scope',scope);if(scope.kind!=='ticket'||d.ticket_id!==scope.id||d.originator_id!==scope.owner_id)fail();}
    // The owner alone sees private source bindings; a staff wire response must omit the field entirely.
    const owner=scope?scope.actor_id===d.originator_id:Object.hasOwn(d,'private_source');
    if(owner?!d.private_source:Object.hasOwn(d,'private_source'))fail();
    if((d.publication_active||owner)?d.instructions===null:d.instructions!==null||d.selected_context!==null)fail();
    if((d.due_date===null)!==(d.expected_outcome===null)||d.publication_active&&d.due_date===null||!d.publication_active&&(d.result!==null||!owner&&d.due_date!==null))fail();
    if(d.private_source&&(d.private_source.unavailability!==null)!==d.requires_owner_attention)fail();
    if(d.due_date!==null&&d.expected_outcome!==null&&d.payload_hash!==await inboxHandoffPayloadHash({instructions:d.instructions!,...(d.selected_context===null?{}:{selected_context:d.selected_context}),due_date:d.due_date!,expected_outcome:d.expected_outcome!}))fail();
    if(!d.publication_active&&d.verified_current||d.verified_current&&!d.result)fail();
    if(scope&&!owner&&!d.handoffs.some(h=>h.from_id===scope.actor_id||h.to_id===scope.actor_id))fail();
  }
  return v;
}
