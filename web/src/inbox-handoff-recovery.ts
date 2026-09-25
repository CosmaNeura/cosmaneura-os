import type {InboxHandoffOperation, InboxHandoffReceipt} from './inbox-handoff-contract';
import {InboxHandoffContractError,validateInboxHandoffOperation,verifyInboxHandoffOperationReceipt} from './inbox-handoff-contract';
import {vendorBytes,vendorCanonical,vendorObject,vendorUuid} from './vendor-contract';

export type InboxHandoffActor={box_id:string;actor_id:string};
export type InboxHandoffProposalBasis={item_id:string;source_id:string;source_sha256:string;review_receipt_id:string;review_receipt_sha256:string;workspace_id:string;expected_workspace_revision:number;label:string};
export type InboxHandoffDraft=
  | {kind:'proposal';basis:InboxHandoffProposalBasis;instructions:string;selected_context:string;due_date:string;expected_outcome:string}
  | {kind:'ticket';ticket_id:string;owner_id:string;source_item_id:string|null;recipient_id:string;evidence:string};
export type InboxHandoffSaved={operation:InboxHandoffOperation;receipt:InboxHandoffReceipt};
export type InboxHandoffRecoveryRecord={version:1;actor:InboxHandoffActor;drafts:InboxHandoffDraft[];selected:string|null;pending:InboxHandoffOperation|null;receipt:InboxHandoffReceipt|null;history:InboxHandoffSaved[];parked:{operation:InboxHandoffOperation;receipt:InboxHandoffReceipt|null}[]};
export type InboxHandoffRecoveryAccess={authorize():Promise<void>;load():Promise<unknown>;persist(record:InboxHandoffRecoveryRecord|null):Promise<void>;denied?(error:unknown):void};
export const INBOX_HANDOFF_RECOVERY_BYTES=131072;
// A closed receipt has only fixed-size identifiers, hashes and enumerated reasons.
// Reserve space before admission so an outcome can be retained even at the journal bound.
const PROOF_RESERVE=4096;
const fail=():never=>{throw new InboxHandoffContractError();};
export const validInboxHandoffActor=(v:unknown):v is InboxHandoffActor=>vendorObject(v)&&Object.keys(v).sort().join(',')==='actor_id,box_id'&&vendorUuid(v.box_id)&&vendorUuid(v.actor_id);
export const emptyInboxHandoffRecovery=(actor:InboxHandoffActor):InboxHandoffRecoveryRecord=>({version:1,actor:structuredClone(actor),drafts:[],selected:null,pending:null,receipt:null,history:[],parked:[]});
export const inboxHandoffDraftKey=(d:InboxHandoffDraft)=>d.kind==='ticket'?`ticket:${d.ticket_id}`:`proposal:${vendorCanonical(d.basis)}`;
export const inboxHandoffTarget=(op:InboxHandoffOperation)=>op.kind==='propose'?`item:${op.request.item_id}`:`ticket:${op.scope.id}`;
const key=(op:InboxHandoffOperation)=>vendorCanonical([op.scope,op.kind,op.request.idempotency_key]);
const exact=(v:unknown,keys:string)=>vendorObject(v)&&Object.keys(v).sort().join(',')===keys;
const text=(v:unknown,max:number)=>typeof v==='string'&&Array.from(v).length<=max&&!/[\x00-\x08\x0b-\x1f\x7f]/.test(v);
export function validateInboxHandoffDraft(value:unknown):InboxHandoffDraft{
  if(!vendorObject(value))return fail();
  if(value.kind==='proposal'){
    if(!exact(value,'basis,due_date,expected_outcome,instructions,kind,selected_context')||!exact(value.basis,'expected_workspace_revision,item_id,label,review_receipt_id,review_receipt_sha256,source_id,source_sha256,workspace_id'))return fail();
    const b=value.basis as InboxHandoffProposalBasis;
    if(![b.item_id,b.source_id,b.review_receipt_id,b.workspace_id].every(vendorUuid)||![b.source_sha256,b.review_receipt_sha256].every(x=>typeof x==='string'&&/^[a-f0-9]{64}$/.test(x))||!Number.isInteger(b.expected_workspace_revision)||b.expected_workspace_revision<1||b.expected_workspace_revision>2147483647||!text(b.label,200)||!text(value.instructions,4000)||!text(value.selected_context,2000)||!text(value.due_date,10)||!text(value.expected_outcome,500))return fail();
  }else if(value.kind==='ticket'){
    if(!exact(value,'evidence,kind,owner_id,recipient_id,source_item_id,ticket_id')||!vendorUuid(value.ticket_id)||!vendorUuid(value.owner_id)||value.source_item_id!==null&&!vendorUuid(value.source_item_id)||value.recipient_id!==''&&!vendorUuid(value.recipient_id)||!text(value.evidence,2000))return fail();
  }else return fail();
  vendorCanonical(value);return structuredClone(value) as InboxHandoffDraft;
}
function actorOperation(op:InboxHandoffOperation,actor:InboxHandoffActor){if(op.scope.box_id!==actor.box_id||op.scope.actor_id!==actor.actor_id)fail();}
function capacity(r:InboxHandoffRecoveryRecord){
  const count=r.history.length+r.parked.length+(r.pending?1:0);
  const unresolved=[...r.parked,...(r.pending&&!['recorded','rejected'].includes(r.receipt?.outcome??'')?[{operation:r.pending,receipt:r.receipt}]:[])];
  const reserve=unresolved.reduce((n,p)=>n+Math.max(0,PROOF_RESERVE-vendorBytes(p.receipt)),0);
  if(count>100||r.drafts.length>100||vendorBytes(r)+reserve+128*(r.parked.length+(r.pending?1:0))>INBOX_HANDOFF_RECOVERY_BYTES)fail();
}
export async function validateInboxHandoffRecovery(value:unknown,actor:InboxHandoffActor):Promise<InboxHandoffRecoveryRecord>{
  if(!validInboxHandoffActor(actor)||!exact(value,'actor,drafts,history,parked,pending,receipt,selected,version')||vendorBytes(value)>INBOX_HANDOFF_RECOVERY_BYTES)return fail();
  const r=value as InboxHandoffRecoveryRecord;
  if(r.version!==1||!validInboxHandoffActor(r.actor)||vendorCanonical(r.actor)!==vendorCanonical(actor)||!Array.isArray(r.drafts)||!Array.isArray(r.history)||!Array.isArray(r.parked)||r.drafts.length>100||r.history.length+r.parked.length+(r.pending?1:0)>100)return fail();
  const drafts=r.drafts.map(validateInboxHandoffDraft),draftKeys=drafts.map(inboxHandoffDraftKey);
  if(new Set(draftKeys).size!==draftKeys.length||r.selected!==null&&!draftKeys.includes(r.selected))fail();
  const pending=r.pending===null?null:await validateInboxHandoffOperation(r.pending);if(pending)actorOperation(pending,actor);
  const receipt=r.receipt===null?null:pending?await verifyInboxHandoffOperationReceipt(pending,r.receipt):fail();
  const keys=new Set<string>(),ids=new Set<string>(),targets=new Set<string>(),history:InboxHandoffSaved[]=[],parked:InboxHandoffRecoveryRecord['parked']=[];
  const pair=async(entry:unknown,terminal:boolean)=>{
    if(!exact(entry,'operation,receipt'))return fail();const e=entry as InboxHandoffSaved;
    const operation=await validateInboxHandoffOperation(e.operation);actorOperation(operation,actor);
    const proof=e.receipt===null?null:await verifyInboxHandoffOperationReceipt(operation,e.receipt);
    if(terminal?proof===null||proof.outcome==='not_found':proof!==null&&proof.outcome!=='not_found')fail();
    if(keys.has(key(operation)))fail();keys.add(key(operation));
    if(proof&&proof.outcome!=='not_found'){if(ids.has(proof.receipt_id))fail();ids.add(proof.receipt_id);}
    return {operation,receipt:proof};
  };
  for(const e of r.history){const p=await pair(e,true);history.push({operation:p.operation,receipt:p.receipt!});}
  for(const e of r.parked){const p=await pair(e,false),target=inboxHandoffTarget(p.operation);if(targets.has(target))fail();targets.add(target);parked.push(p);}
  if(pending){if(keys.has(key(pending))||targets.has(inboxHandoffTarget(pending))||receipt&&receipt.outcome!=='not_found'&&ids.has(receipt.receipt_id))fail();}
  const checked:InboxHandoffRecoveryRecord={version:1,actor:structuredClone(actor),drafts,selected:r.selected,pending,receipt,history,parked};
  const unresolved=[...parked.map(p=>p.operation),...(pending?[pending]:[])];
  for(let i=0;i<unresolved.length;i++)for(let j=0;j<i;j++)if(collides(checked,unresolved[i],unresolved[j]))fail();
  capacity(checked);return checked;
}
export function withInboxHandoffDraft(record:InboxHandoffRecoveryRecord,value:InboxHandoffDraft):InboxHandoffRecoveryRecord{
  const draft=validateInboxHandoffDraft(value),k=inboxHandoffDraftKey(draft),drafts=[...record.drafts],at=drafts.findIndex(x=>inboxHandoffDraftKey(x)===k);
  if(at<0)drafts.push(draft);else drafts[at]=draft;
  const next={...record,drafts,selected:k};capacity(next);return next;
}
function aliases(record:InboxHandoffRecoveryRecord,op:InboxHandoffOperation,relatedItemId?:string){
  const ids=new Set([inboxHandoffTarget(op)]);
  if(op.kind!=='propose'){const d=record.drafts.find(x=>x.kind==='ticket'&&x.ticket_id===op.scope.id);if(d?.kind==='ticket'&&d.source_item_id)ids.add(`item:${d.source_item_id}`);if(relatedItemId)ids.add(`item:${relatedItemId}`);}
  return ids;
}
export function unknownOwnedHandoffSource(record:InboxHandoffRecoveryRecord,op:InboxHandoffOperation){return op.kind!=='propose'&&op.scope.owner_id===record.actor.actor_id&&!record.drafts.some(d=>d.kind==='ticket'&&d.ticket_id===op.scope.id&&d.source_item_id!==null);}
function collides(record:InboxHandoffRecoveryRecord,a:InboxHandoffOperation,b:InboxHandoffOperation,relatedItemId?:string){
  if(a.kind==='propose'&&unknownOwnedHandoffSource(record,b)||b.kind==='propose'&&unknownOwnedHandoffSource(record,a)&&!relatedItemId)return true;
  const ids=aliases(record,a,relatedItemId);return [...aliases(record,b)].some(k=>ids.has(k));
}
export function withInboxHandoffCommand(record:InboxHandoffRecoveryRecord,operation:InboxHandoffOperation,relatedItemId?:string):InboxHandoffRecoveryRecord{
  if(relatedItemId&&!vendorUuid(relatedItemId))fail();
  actorOperation(operation,record.actor);if(record.pending||record.parked.some(x=>collides(record,operation,x.operation,relatedItemId))||record.history.some(x=>key(x.operation)===key(operation)))fail();
  const next={...record,pending:operation,receipt:null};capacity(next);return next;
}
export function keepInboxHandoffProof(record:InboxHandoffRecoveryRecord):InboxHandoffRecoveryRecord{
  if(!record.pending||!record.receipt||record.receipt.outcome==='not_found')return fail();
  const next={...record,pending:null,receipt:null,history:[...record.history,{operation:record.pending,receipt:record.receipt}]};capacity(next);return next;
}
export function parkInboxHandoffCommand(record:InboxHandoffRecoveryRecord):InboxHandoffRecoveryRecord{
  if(!record.pending||record.receipt&&record.receipt.outcome!=='not_found'||record.parked.some(p=>inboxHandoffTarget(p.operation)===inboxHandoffTarget(record.pending!)))return fail();
  const next={...record,pending:null,receipt:null,parked:[...record.parked,{operation:record.pending,receipt:record.receipt}]};capacity(next);return next;
}
export function resumeInboxHandoffCommand(record:InboxHandoffRecoveryRecord,target:string):InboxHandoffRecoveryRecord{
  const entry=record.parked.find(x=>inboxHandoffTarget(x.operation)===target);if(record.pending||!entry)return fail();
  return {...record,pending:entry.operation,receipt:entry.receipt,parked:record.parked.filter(x=>x!==entry)};
}
