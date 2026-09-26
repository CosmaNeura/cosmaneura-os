import type {Scope,Proposal,Decision,Result,Verify,Withdraw,Detail,History} from './membership-schema';
import type {MembershipResponse as Response} from './membership-contract';
import {MembershipContractError,normalizeMembership,validateMembership,verifyMembershipReceipt,verifyMembershipView,sameMembershipScope,membershipClassification} from './membership-contract';
import {vendorBytes,vendorCanonical,vendorDigest,vendorObject,vendorUuid} from './vendor-contract';
export type MembershipRequests={propose:Proposal;decide:Decision;result:Result;verify:Verify;withdraw:Withdraw};
export type MembershipKind=keyof MembershipRequests;
export type MembershipOperation<K extends MembershipKind=MembershipKind>={version:1;scope:Scope;kind:K;request:MembershipRequests[K];request_sha256:string};
export type MembershipSaved={operation:MembershipOperation;receipt:Response};
export type MembershipReviewBundle={detail:Detail;history:History};
const models={propose:'Proposal',decide:'Decision',result:'Result',verify:'Verify',withdraw:'Withdraw'} as const;
const fail=():never=>{throw new MembershipContractError();};
export async function prepareMembershipOperation<K extends MembershipKind>(scope:Scope,kind:K,request:MembershipRequests[K]):Promise<MembershipOperation<K>>{
 validateMembership('Scope',scope);if(!Object.hasOwn(models,kind))fail();const exact=normalizeMembership(models[kind],request) as MembershipRequests[K];if(vendorBytes(exact)>8192)fail();
 return {version:1,scope:structuredClone(scope),kind,request:exact,request_sha256:await vendorDigest('cosmas-membership-request.v1',{scope,command_kind:kind,request:exact})};
}
export async function validateMembershipOperation(value:unknown,scope?:Scope):Promise<MembershipOperation>{
 if(!vendorObject(value)||Object.keys(value).sort().join(',')!=='kind,request,request_sha256,scope,version'||value.version!==1||typeof value.kind!=='string'||!Object.hasOwn(models,value.kind))fail();
 const v=value as MembershipOperation;if(scope&&!sameMembershipScope(scope,v.scope))fail();validateMembership(models[v.kind],v.request);const expected=await prepareMembershipOperation(v.scope,v.kind,v.request);if(vendorCanonical(expected)!==vendorCanonical(v))fail();return expected;
}
export async function verifyMembershipOperationReceipt(op:MembershipOperation,value:unknown):Promise<Response>{
 await validateMembershipOperation(op);
 const r=await verifyMembershipReceipt(value);if(!sameMembershipScope(op.scope,r.scope)||r.command_kind!==op.kind||r.idempotency_key!==op.request.idempotency_key||r.request_sha256!==op.request_sha256)fail();
 const e=r.effect,q=op.request;if(e){
  if('ticket_id'in q&&(e.ticket_id!==q.ticket_id||e.version!==q.expected_version+1||e.revision_id!==q.revision_id||e.payload_hash!==q.payload_hash))fail();
  if(op.kind==='propose'&&(e.version!==1||e.state!=='pending_approval'||e.evidence_classification!=='local_unreconciled'))fail();
  if(op.kind==='decide'&&(e.effect!==((q as Decision).choice==='approve'?'approved':'rejected')||e.state!==((q as Decision).choice==='approve'?'approved':'rejected')))fail();
  if(op.kind==='result'&&(e.state!=='approved'||e.evidence_classification!==membershipClassification(q as Result)))fail();
  if(op.kind==='verify'&&(e.state!=='closed'||e.evidence_classification!==(q as Verify).evidence_classification))fail();
  if(op.kind==='withdraw'&&e.state!=='withdrawn')fail();
 }
 return r;
}
/** Exact complete immutable history validates private result text before the panel receives it. */
export async function verifyMembershipBundle(detailValue:unknown,historyValue:unknown,scope?:Scope):Promise<MembershipReviewBundle>{
 const d=await verifyMembershipView('Detail',detailValue),h=await verifyMembershipView('History',historyValue),s=d.summary;
 if(!sameMembershipScope(d.scope,h.scope)||scope&&!sameMembershipScope(scope,d.scope)||h.ticket_id!==s.ticket_id||h.items.length!==s.version||!h.items.length)fail();
 const keys=new Set<string>(),ids=new Set<string>();let previous:string|null=null,latest:MembershipSaved|null=null;
 for(let index=0;index<h.items.length;index++){
  const item=h.items[index],op=await prepareMembershipOperation(h.scope,item.receipt.command_kind,item.request),receipt=await verifyMembershipOperationReceipt(op,item.receipt),e=receipt.effect;
  if(!e||e.ticket_id!==s.ticket_id||e.revision_id!==s.revision_id||e.payload_hash!==s.payload_hash||e.version!==index+1||keys.has(receipt.idempotency_key)||ids.has(e.receipt_id))fail();
  keys.add(receipt.idempotency_key);ids.add(e!.receipt_id);
  if(index===0){if(op.kind!=='propose'||vendorCanonical(op.request)!==vendorCanonical(d.review.proposal))fail();}
  else if(op.kind==='propose'||op.kind==='decide'&&previous!=='pending_approval'||op.kind==='result'&&(previous!=='approved'||index>=98)||op.kind==='withdraw'&&!['pending_approval','approved'].includes(previous??'')||op.kind==='verify'&&previous!=='approved')fail();
  if(op.kind==='decide'&&(op.request as Decision).review_sha256!==d.review_sha256)fail();
  if(op.kind==='result')latest={operation:op,receipt};
  if(op.kind==='verify'){
   const q=op.request as Verify,prior=latest?.operation.request as Result|undefined;
   if(!latest?.receipt.effect||!prior||prior.disposition==='needs_human'||q.result_receipt_id!==latest.receipt.effect.receipt_id||q.result_receipt_sha256!==latest.receipt.receipt_sha256||q.evidence_classification!==membershipClassification(prior))fail();
  }
  if(e!.evidence_classification!==membershipClassification(latest?.operation.request as Result|undefined))fail();previous=e!.state;
 }
 if(previous!==s.state)fail();
 if(latest){if(!d.latest_result||d.latest_result.receipt_id!==latest.receipt.effect!.receipt_id||d.latest_result.receipt_sha256!==latest.receipt.receipt_sha256||vendorCanonical(d.latest_result.request)!==vendorCanonical(latest.operation.request))fail();}
 else if(d.latest_result!==null)fail();
 return {detail:d,history:h};
}
export const membershipRoot=(workspaceId:string)=>{if(!vendorUuid(workspaceId))return fail();return `/workspaces/${workspaceId}/membership-work`;};
export const membershipOperationPath=(op:MembershipOperation)=>membershipRoot(op.scope.workspace_id)+(op.kind==='propose'?'':`/${(op.request as Exclude<MembershipRequests[MembershipKind],Proposal>).ticket_id}/${op.kind}`);
export const membershipResolveRequest=(op:MembershipOperation)=>({command_kind:op.kind,idempotency_key:op.request.idempotency_key,request_sha256:op.request_sha256});
