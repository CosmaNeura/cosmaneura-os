import type {FinanceScope,FinanceProposal,FinanceDecision,FinanceResult,FinanceVerify,FinanceResponse,BoundCommand} from './finance-schema';
import {FinanceContractError,normalizeFinance,validateFinance,verifyFinanceReceipt} from './finance-contract';
import {vendorBytes,vendorCanonical,vendorDigest,vendorObject,vendorUuid} from './vendor-contract';

export type FinanceRequests={propose:FinanceProposal;decide:FinanceDecision;withdraw:BoundCommand;submit:BoundCommand;reconcile:BoundCommand;result:FinanceResult;verify:FinanceVerify};
export type FinanceKind=keyof FinanceRequests;
export type FinanceOperation<K extends FinanceKind=FinanceKind>={version:1;scope:FinanceScope;kind:K;target_id:string|null;request:FinanceRequests[K];request_sha256:string};
export const financeRequestModel={propose:'FinanceProposal',decide:'FinanceDecision',withdraw:'BoundCommand',submit:'BoundCommand',reconcile:'BoundCommand',result:'FinanceResult',verify:'FinanceVerify'} as const;
export const financeRequestLimit=(kind:FinanceKind)=>kind==='propose'||kind==='result'?16384:2048;
const fail=():never=>{throw new FinanceContractError();};
export async function prepareFinanceOperation<K extends FinanceKind>(scope:FinanceScope,kind:K,targetId:string|null,request:FinanceRequests[K]):Promise<FinanceOperation<K>>{
  validateFinance('FinanceScope',scope);if(!Object.hasOwn(financeRequestModel,kind)||(kind==='propose'?targetId!==null:!vendorUuid(targetId)))fail();
  const normalized=normalizeFinance(financeRequestModel[kind],request) as FinanceRequests[K];if(vendorBytes(normalized)>financeRequestLimit(kind))fail();
  return {version:1,scope:structuredClone(scope),kind,target_id:targetId,request:normalized,request_sha256:await vendorDigest('cosmas-finance-public-request.v1',{command_kind:kind,scope,request:normalized})};
}
export async function validateFinanceOperation(value:unknown,scope?:FinanceScope):Promise<FinanceOperation>{
  if(!vendorObject(value)||Object.keys(value).sort().join(',')!=='kind,request,request_sha256,scope,target_id,version'||value.version!==1||typeof value.kind!=='string'||!Object.hasOwn(financeRequestModel,value.kind))fail();
  const v=value as FinanceOperation;if(scope&&vendorCanonical(scope)!==vendorCanonical(v.scope))fail();
  validateFinance(financeRequestModel[v.kind],v.request);const expected=await prepareFinanceOperation(v.scope,v.kind,v.target_id,v.request);if(vendorCanonical(expected)!==vendorCanonical(v))fail();return expected;
}
export async function verifyFinanceOperationReceipt(op:FinanceOperation,value:unknown):Promise<FinanceResponse>{
  const r=op.request;const revision='revises'in r&&vendorObject(r.revises)?r.revises:null;const checked=await verifyFinanceReceipt(value,{scope:op.scope,kind:op.kind,key:r.idempotency_key,sha256:op.request_sha256,...(op.target_id?{ticketId:op.target_id}:{}),...(revision?{ticketId:revision.ticket_id as string}:{}),...('operation_id'in r?{operationId:r.operation_id}:{}),...('proposed_operation_id'in r?{operationId:r.proposed_operation_id}:{}),...('revision_id'in r?{revisionId:r.revision_id}:{}),...('payload_hash'in r?{payloadHash:r.payload_hash}:{})});
  if(checked.effect&&op.kind==='decide'&&checked.effect.effect!==((r as FinanceDecision).choice==='approve'?'approved':'rejected'))fail();
  if(checked.effect&&revision&&(checked.effect.revision_id===revision.revision_id||checked.effect.payload_hash===revision.payload_hash||checked.effect.effect_version!==(revision.expected_version as number)+1))fail();return checked;
}
export function financeOperationPath(op:FinanceOperation,resolve=false){const root=`/workspaces/${op.scope.id}/finance-work`;return resolve?root+'/resolve':op.kind==='propose'?root:`${root}/${op.target_id}/${op.kind}`;}
export const financeResolveRequest=(op:FinanceOperation)=>({command_kind:op.kind,idempotency_key:op.request.idempotency_key,request_sha256:op.request_sha256});
