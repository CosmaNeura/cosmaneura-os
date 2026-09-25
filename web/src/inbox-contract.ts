import {INBOX_SCHEMAS, type InboxContractName, type InboxContractTypes, type Scope, type Review, type Triage, type Result, type Verify, type Receipt, type Source, type SourceMetadata, type Detail, type History, type ReadHistory} from './inbox-schema';
import {vendorBytes, vendorCanonical, vendorDigest, vendorObject, vendorUuid} from './vendor-contract';

export class InboxContractError extends Error {
  constructor(){super('The private Inbox response could not be verified.');}
}
const fail=():never=>{throw new InboxContractError();};
type Obj=Record<string,unknown>;
type Schema={$ref?:string;anyOf?:Schema[];type?:string;const?:unknown;enum?:unknown[];properties?:Record<string,Schema>;required?:readonly string[];items?:Schema;minimum?:number;maximum?:number;minLength?:number;maxLength?:number;minItems?:number;maxItems?:number;pattern?:string;'x-rules'?:readonly string[];'x-no-null'?:boolean};
const schemas=INBOX_SCHEMAS as unknown as Record<string,Schema>;
const pythonBlank=/^[\t\n\v\f\r \x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]*$/;
const bytes=(v:string)=>new TextEncoder().encode(v).byteLength;
function day(v:unknown):boolean {
  if(typeof v!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(v)||v.slice(0,4)==='0000')return false;
  const d=new Date(v+'T00:00:00.000Z');return !Number.isNaN(d.valueOf())&&d.toISOString().slice(0,10)===v;
}
export {day as isInboxCalendarDate};
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
  if(s.anyOf){for(const branch of s.anyOf){try{return shape(branch,v,depth+1);}catch(e){if(!(e instanceof InboxContractError))throw e;}}return fail();}
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
function model(name:string,value:unknown,depth=0):unknown {
  const v=shape(schemas[name],value,depth) as Obj;
  if(['Bound','Review','Triage','Result','Verify'].includes(name)&&(Object.hasOwn(v,'source_id')!==Object.hasOwn(v,'source_sha256')))fail();
  if(['Effect','Summary','ReadHistory'].includes(name)&&(v.version as number)>100||['Source','SourceMetadata'].includes(name)&&(v.sequence as number)>50)fail();
  if(name==='ReviewOptions'&&(v.item_version as number)>=96)fail();
  if(['Effect','Summary','ReadHistory'].includes(name)&&(v.source_id===null)!==(v.source_sha256===null))fail();
  if(['Source','SourceMetadata'].includes(name)&&(v.modified_at as string)<(v.created_at as string))fail();
  if(name==='Source'){
    const source=v as unknown as Source;
    if([source.contact_id,source.conversation_id,source.item_reference].some(id=>!/^[A-Za-z0-9_-]{1,255}$/.test(id))||bytes(source.text)>16384||/[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(source.text))fail();
    if(vendorCanonical(source.attachment_types)!==vendorCanonical([...new Set(source.attachment_types)].sort())||source.attachments!==(source.attachment_types.length>0))fail();
    if(source.incomplete_content!==Boolean(source.attachments||source.pages||source.buttons||source.event||pythonBlank.test(source.text)))fail();
  }
  if(name==='Receipt'){
    const r=v as unknown as Receipt,proof=[r.receipt_id,r.recorded_at,r.receipt_sha256];
    if(r.outcome==='not_found'){if([...proof,r.effect,r.rejection].some(x=>x!==null))fail();}
    else if(proof.some(x=>x===null)||(r.outcome==='recorded'?r.effect===null||r.rejection!==null:r.effect!==null||r.rejection===null))fail();
    if(r.effect){const states={review:['reviewed'],triage:['triaged','needs_human'],result:['result_recorded','needs_human'],verify:['closed_local_review']};if(!states[r.command_kind].includes(r.effect.state))fail();}
  }
  if(name==='ReadHistory'){
    const r=v as unknown as ReadHistory,source=[r.source_id,r.source_sha256,r.observed_at,r.item_response_sha256,r.conversation_response_sha256];
    if(r.outcome==='failure'?r.safe_error===null||source.some(x=>x!==null):r.safe_error!==null||source.some(x=>x===null))fail();
  }
  if(name==='Summary'){
    const s=v as unknown as InboxContractTypes['Summary'];
    if(s.source_id===null&&!s.incomplete_content||s.workspace_current&&s.workspace_id===null)fail();
    if(['reviewed','triaged','result_recorded','closed_local_review'].includes(s.state)&&(!s.binding_current||!s.workspace_current||s.incomplete_content||s.source_conflict||s.read_issue!==null||s.source_id===null))fail();
    if(['triaged','result_recorded','closed_local_review'].includes(s.state)&&s.classification!=='administrative_review')fail();
    if((!s.binding_current||s.source_conflict||s.read_issue!==null)&&s.state!=='needs_human')fail();
  }
  return v;
}
export function normalizeInbox<N extends InboxContractName>(name:N,value:unknown):InboxContractTypes[N]{vendorCanonical(value);return model(name,value) as InboxContractTypes[N];}
export function validateInbox<N extends InboxContractName>(name:N,value:unknown):InboxContractTypes[N]{const exact=normalizeInbox(name,value);if(vendorCanonical(exact)!==vendorCanonical(value))fail();return exact;}
export const sameInboxScope=(a:Scope,b:Scope)=>vendorCanonical(a)===vendorCanonical(b);
export type InboxRequests={review:Review;triage:Triage;result:Result;verify:Verify};
export type InboxKind=keyof InboxRequests;
export type InboxOperation<K extends InboxKind=InboxKind>={[P in InboxKind]:{version:1;scope:Scope;kind:P;request:InboxRequests[P];request_sha256:string}}[K];
export type InboxSaved={operation:InboxOperation;receipt:Receipt};
export type InboxBundle={detail:Detail;history:History};
const models={review:'Review',triage:'Triage',result:'Result',verify:'Verify'} as const;
export async function prepareInboxOperation<K extends InboxKind>(scope:Scope,kind:K,request:InboxRequests[K]):Promise<InboxOperation<K>> {
  validateInbox('Scope',scope);if(!Object.hasOwn(models,kind))fail();
  const exact=normalizeInbox(models[kind],request);if(vendorBytes(exact)>8192)fail();
  return {version:1,scope:structuredClone(scope),kind,request:exact,request_sha256:await vendorDigest('cosmas-inbox-request.v1',{scope,command_kind:kind,request:exact})} as InboxOperation<K>;
}
export async function validateInboxOperation(value:unknown,scope?:Scope):Promise<InboxOperation>{
  vendorCanonical(value);
  if(!vendorObject(value)||Object.keys(value).sort().join(',')!=='kind,request,request_sha256,scope,version'||value.version!==1||typeof value.kind!=='string'||!Object.hasOwn(models,value.kind))fail();
  const op=value as InboxOperation;if(scope&&!sameInboxScope(scope,op.scope))fail();validateInbox(models[op.kind],op.request);
  const exact=await prepareInboxOperation(op.scope,op.kind,op.request);if(vendorCanonical(exact)!==vendorCanonical(op))fail();return exact;
}
export async function verifyInboxReceipt(value:unknown):Promise<Receipt>{
  const r=validateInbox('Receipt',value);if(vendorBytes(r)>8192)fail();
  if(r.outcome!=='not_found'){const {receipt_sha256:_,...body}=r;if(r.receipt_sha256!==await vendorDigest('cosmas-inbox-receipt.v1',body))fail();}return r;
}
export async function verifyInboxOperationReceipt(operation:InboxOperation,value:unknown):Promise<Receipt>{
  const op=await validateInboxOperation(operation),r=await verifyInboxReceipt(value);
  if(!sameInboxScope(op.scope,r.scope)||r.command_kind!==op.kind||r.idempotency_key!==op.request.idempotency_key||r.request_sha256!==op.request_sha256)fail();
  if(r.effect){
    const e=r.effect,q=op.request;
    if(e.item_id!==q.item_id||e.version!==q.expected_version+1||e.source_id!==(q.source_id??null)||e.source_sha256!==(q.source_sha256??null))fail();
    if(op.kind==='triage'&&e.state!==(op.request.classification==='administrative_review'?'triaged':'needs_human'))fail();
    if(op.kind==='result'&&e.state!==(op.request.disposition==='local_review_complete'?'result_recorded':'needs_human'))fail();
    if(['review','verify'].includes(op.kind)&&e.source_id===null)fail();
  }
  return r;
}
export const inboxOperationPath=(op:InboxOperation)=>{if(!vendorUuid(op.request.item_id)||!Object.hasOwn(models,op.kind))return fail();return `/inbox/${op.request.item_id}/${op.kind}`;};
export const inboxResolveRequest=(op:InboxOperation):InboxContractTypes['Resolve']=>({item_id:op.request.item_id,command_kind:op.kind,idempotency_key:op.request.idempotency_key,request_sha256:op.request_sha256});

const sourceFields=['source_id','sequence','source_sha256','created_at','modified_at','observed_at','incomplete_content'] as const;
export const inboxSourceMetadata=(source:Source):SourceMetadata=>Object.fromEntries(sourceFields.map(k=>[k,source[k]])) as SourceMetadata;
async function verifySource(value:unknown):Promise<Source>{
  const source=validateInbox('Source',value);if(vendorBytes(source)>65536)fail();
  const {projection_sha256:_,...body}=source;if(source.projection_sha256!==await vendorDigest('cosmas-inbox-source-view.v1',body))fail();return source;
}
type Entry={version:number;read:ReadHistory}|{version:number;command:InboxSaved};
type Evidence={history:History;head:SourceMetadata|null;conflict:boolean;issue:ReadHistory['safe_error'];commands:InboxSaved[]};
function currentChain(commands:InboxSaved[],sourceId:string|null){
  const latest=(kind:InboxKind)=>[...commands].reverse().find(c=>c.operation.kind===kind&&c.receipt.outcome==='recorded'&&c.receipt.effect?.source_id===sourceId)??null;
  const raw={review:latest('review'),triage:latest('triage'),result:latest('result'),verify:latest('verify')};
  let {review,triage,result,verify}=raw;
  if(triage?.operation.kind==='triage'&&triage.operation.request.classification==='administrative_review'&&(!review||triage.receipt.effect!.version<=review.receipt.effect!.version))triage=null;
  if(result?.operation.kind==='result'&&(!triage||result.operation.request.triage_receipt_id!==triage.receipt.receipt_id||result.receipt.effect!.version<=triage.receipt.effect!.version))result=null;
  if(verify?.operation.kind==='verify'&&(!result||verify.operation.request.result_receipt_id!==result.receipt.receipt_id||verify.receipt.effect!.version<=result.receipt.effect!.version))verify=null;
  return {raw,review,triage,result,verify};
}
async function historyEvidence(value:unknown):Promise<Evidence>{
  const h=validateInbox('History',value);if(vendorBytes(h)>2097152)fail();
  const total=h.reads.length+h.commands.length;if(total<1||total>100||!h.reads.length)fail();
  const sources=new Map<string,SourceMetadata>(),sourceHashes=new Set<string>();
  for(const [index,source] of h.sources.entries()){
    if(source.sequence!==index+1||sources.has(source.source_id)||sourceHashes.has(source.source_sha256))fail();sources.set(source.source_id,source);sourceHashes.add(source.source_sha256);
  }
  const entries=new Map<number,Entry>(),ids=new Set<string>(),keys=new Set<string>();let previousRead=0;
  for(const read of h.reads){
    const {receipt_sha256:_,...body}=read;
    if(read.item_id!==h.item_id||read.version<=previousRead||read.version>total||ids.has(read.id)||read.grant_sha256!==h.reads[0].grant_sha256||read.receipt_sha256!==await vendorDigest('cosmas-inbox-read-receipt.v1',body))fail();
    ids.add(read.id);entries.set(read.version,{version:read.version,read});previousRead=read.version;
    if(read.source_id){const source=sources.get(read.source_id);if(!source||source.source_sha256!==read.source_sha256)fail();}
  }
  const saved:InboxSaved[]=[];
  for(const item of h.commands){
    const op=await prepareInboxOperation(h.scope,item.receipt.command_kind,item.request),receipt=await verifyInboxOperationReceipt(op,item.receipt);
    if(op.request.item_id!==h.item_id||receipt.outcome==='not_found'||!receipt.receipt_id||ids.has(receipt.receipt_id)||keys.has(receipt.idempotency_key))fail();
    ids.add(receipt.receipt_id!);keys.add(receipt.idempotency_key);saved.push({operation:op,receipt});
    if(op.request.source_id){const source=sources.get(op.request.source_id);if(!source||source.source_sha256!==op.request.source_sha256)fail();}
    if(receipt.effect){const version=receipt.effect.version;if(version>total||entries.has(version))fail();entries.set(version,{version,command:saved.at(-1)!});}
  }
  // Rejected receipts deliberately carry no effect/version. Their ordered
  // positions are exactly the unoccupied slots in the complete event history.
  const missing=Array.from({length:total},(_,i)=>i+1).filter(v=>!entries.has(v));let previousCommand=0;
  for(const command of saved){const version=command.receipt.effect?.version??missing.shift()??fail();if(version<=previousCommand)fail();previousCommand=version;entries.set(version,{version,command});}
  if(missing.length||entries.size!==total||!('read'in entries.get(1)!))fail();
  let head:SourceMetadata|null=null,conflict=false,issue:ReadHistory['safe_error']=null;
  const observed=new Set<string>(),commands:InboxSaved[]=[];
  for(let version=1;version<=total;version++){
    const entry=entries.get(version)??fail();
    if('read'in entry){
      const r=entry.read,source=r.source_id?sources.get(r.source_id)!:null;
      if(source&&!observed.has(source.source_id)){
        if(source.sequence!==observed.size+1||source.observed_at!==r.observed_at)fail();observed.add(source.source_id);
      }
      if(r.outcome==='new'){if(head||!source)fail();head=source;conflict=false;}
      if(r.outcome==='newer'){if(!head||!source||source.created_at!==head.created_at||source.modified_at<=head.modified_at)fail();head=source;conflict=false;}
      if(r.outcome==='same'&&(!head||source?.source_id!==head.source_id))fail();
      if(r.outcome==='older'&&(!head||!source||source.created_at!==head.created_at||source.modified_at>=head.modified_at))fail();
      if(r.outcome==='conflict'){if(!head||!source||source.source_id===head.source_id)fail();conflict=true;}
      if(r.outcome==='failure')issue=r.safe_error;else if(['new','newer','same'].includes(r.outcome))issue=null;
    }else{
      const {operation:op,receipt:r}=entry.command;
      if(r.outcome==='recorded'){
        if((op.request.source_id??null)!==(head?.source_id??null))fail();
        const chain=currentChain(commands,head?.source_id??null),blocked=!head||head.incomplete_content||conflict||issue!==null;
        if(op.kind==='review'&&(!head||conflict||issue!==null))fail();
        if(op.kind==='triage'&&op.request.classification==='administrative_review'&&(blocked||!chain.review))fail();
        if(op.kind==='result'){
          const triage=chain.triage??fail();
          if(op.request.triage_receipt_id!==triage.receipt.receipt_id||op.request.triage_receipt_sha256!==triage.receipt.receipt_sha256)fail();
          if(op.request.disposition==='local_review_complete'&&(blocked||triage.operation.kind!=='triage'||triage.operation.request.classification!=='administrative_review'||!chain.review))fail();
        }
        if(op.kind==='verify'&&(!chain.result||op.request.result_receipt_id!==chain.result.receipt.receipt_id||op.request.result_receipt_sha256!==chain.result.receipt.receipt_sha256||chain.result.operation.kind!=='result'||chain.result.operation.request.disposition!=='local_review_complete'||blocked))fail();
      }
      commands.push(entry.command);
    }
  }
  if(observed.size!==sources.size)fail();return {history:h,head,conflict,issue,commands};
}
export async function verifyInboxView<N extends 'Catalog'|'Detail'|'History'|'Source'|'ReviewOptions'>(name:N,value:unknown):Promise<InboxContractTypes[N]>{
  if(name==='Source')return await verifySource(value) as InboxContractTypes[N];
  if(name==='History')return (await historyEvidence(value)).history as InboxContractTypes[N];
  if(name==='ReviewOptions'){
    const options=validateInbox('ReviewOptions',value);if(vendorBytes(options)>131072)fail();
    if(new Set(options.choices.map(c=>c.workspace_id)).size!==options.choices.length||new Set(options.choices.map(c=>c.appointment_id)).size!==options.choices.length)fail();
    const {options_sha256:_,...body}=options;if(options.options_sha256!==await vendorDigest('cosmas-inbox-review-options.v1',body))fail();return options as InboxContractTypes[N];
  }
  const v=validateInbox(name,value);if(vendorBytes(v)>(name==='Catalog'?131072:65536))fail();
  if(name==='Catalog'){const c=v as InboxContractTypes['Catalog'];if(new Set(c.items.map(s=>s.item_id)).size!==c.items.length)fail();}
  else{
    const d=v as Detail,s=d.summary;
    if((d.source===null)!==(s.source_id===null)||d.availability.history_capacity_remaining!==100-s.version)fail();
    if(d.source){const source=await verifySource(d.source);if(source.source_id!==s.source_id||source.source_sha256!==s.source_sha256||source.patient_link_id!==s.patient_link_id||source.incomplete_content!==s.incomplete_content)fail();}
    for(const [kind,receipt] of [['review',d.latest_review],['triage',d.latest_triage],['result',d.latest_result],['verify',d.latest_verification]] as const){
      if(!receipt)continue;const r=await verifyInboxReceipt(receipt),e=r.effect;
      if(r.outcome!=='recorded'||!e||!sameInboxScope(r.scope,d.scope)||r.command_kind!==kind||e.item_id!==s.item_id||e.source_id!==s.source_id||e.source_sha256!==s.source_sha256||e.version>s.version)fail();
    }
    const a=d.availability;
    if(Object.entries(a).some(([key,on])=>key!=='history_capacity_remaining'&&on&&!s.binding_current)||a.review&&(s.version>=96||!d.source||s.source_conflict||s.read_issue!==null)||a.triage&&s.version>=96||a.result&&(s.version>=98||!d.latest_triage)||a.verify&&(s.version>=98||s.state!=='result_recorded'||s.incomplete_content))fail();
  }
  return v;
}
/** Source text remains literal untrusted evidence; history validates human intent separately. */
export async function verifyInboxBundle(detailValue:unknown,historyValue:unknown,scope?:Scope):Promise<InboxBundle>{
  const d=await verifyInboxView('Detail',detailValue),e=await historyEvidence(historyValue),h=e.history,s=d.summary;
  if(!sameInboxScope(d.scope,h.scope)||scope&&!sameInboxScope(scope,d.scope)||h.item_id!==s.item_id||h.reads.length+h.commands.length!==s.version||s.source_id!==(e.head?.source_id??null)||s.source_conflict!==e.conflict||s.read_issue!==e.issue)fail();
  if(d.source&&vendorCanonical(inboxSourceMetadata(d.source))!==vendorCanonical(e.head))fail();
  const chain=currentChain(e.commands,s.source_id);
  for(const [kind,value] of [['review',d.latest_review],['triage',d.latest_triage],['result',d.latest_result],['verify',d.latest_verification]] as const){if(vendorCanonical(value)!==vendorCanonical(chain.raw[kind]?.receipt??null))fail();}
  for(const c of e.commands){if(c.receipt.outcome==='recorded'&&c.operation.kind==='review'&&c.operation.request.patient_link_id!==s.patient_link_id)fail();}
  const review=chain.review?.operation.kind==='review'?chain.review.operation.request:null;
  const triage=chain.triage?.operation.kind==='triage'?chain.triage.operation.request:null;
  const result=chain.result?.operation.kind==='result'?chain.result.operation.request:null;
  if(s.workspace_id!==(review?.workspace_id??null)||s.classification!==(triage?.classification??null)||s.workspace_current&&!review)fail();
  let state:InboxContractTypes['Summary']['state']='needs_review';
  if(s.read_issue||s.source_conflict||d.source?.incomplete_content)state='needs_human';else if(review&&s.workspace_current)state='reviewed';
  if(triage)state=triage.classification==='administrative_review'&&s.workspace_current?'triaged':'needs_human';
  if(result&&triage){state=result.disposition==='local_review_complete'&&s.workspace_current?'result_recorded':'needs_human';if(chain.verify&&state==='result_recorded')state='closed_local_review';}
  if(!s.binding_current||s.read_issue||s.source_conflict)state='needs_human';else if(review&&!s.workspace_current)state='needs_review';
  if(s.state!==state)fail();return {detail:d,history:h};
}
