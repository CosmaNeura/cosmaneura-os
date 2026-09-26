import type {Scope,VendorProposal,BoundCommand,VendorDecision,VendorPublication,VendorResult,VendorStaffResult,VendorVerify,VendorHandoff,VendorArtifactIntent,VendorArtifactContent,ArtifactResponse} from './vendor-schema';
import {normalizeVendor,validateVendor,vendorBytes,vendorCanonical,vendorObject,vendorRequestDigest,vendorUuid,VendorContractError,verifyVendorReceipt,type VendorReceipt} from './vendor-contract';

export type VendorRequests={propose:VendorProposal;decide:VendorDecision;withdraw:BoundCommand;publish:VendorPublication;submit:BoundCommand;reconcile:BoundCommand;result:VendorResult|VendorStaffResult;verify:VendorVerify;handoff:VendorHandoff;artifact_intent:VendorArtifactIntent;artifact_content:VendorArtifactContent};
export type VendorKind=keyof VendorRequests;
export const isVendorPreparationKind=(kind:string)=>['propose','artifact_intent','artifact_content'].includes(kind);
export const canRetireVendorOperation=(op:VendorOperation)=>op.scope.kind==='workspace'&&(isVendorPreparationKind(op.kind)||['decide','submit','verify'].includes(op.kind));
export type VendorOperation<K extends VendorKind=VendorKind>={version:1;scope:Scope;kind:K;target_id:string|null;request:VendorRequests[K];request_sha256:string};
export const vendorRequestModel={propose:'VendorProposal',decide:'VendorDecision',withdraw:'BoundCommand',publish:'VendorPublication',submit:'BoundCommand',reconcile:'BoundCommand',result:'VendorResult',verify:'VendorVerify',handoff:'VendorHandoff',artifact_intent:'VendorArtifactIntent',artifact_content:'VendorArtifactContent'} as const;
export const vendorRequestLimit=(kind:VendorKind)=>kind==='propose'?32768:kind==='result'?16384:2048;
const fail=():never=>{throw new VendorContractError();};
const requestModel=(scope:Scope,kind:VendorKind)=>scope.kind==='practice_work'&&kind==='result'?'VendorStaffResult':vendorRequestModel[kind];
function target(scope:Scope,kind:VendorKind,id:string|null){validateVendor('Scope',scope);if(scope.kind==='practice_work'){if(!['handoff','result'].includes(kind)||id!==scope.id)fail();}else if(kind==='handoff')fail();else if(kind==='propose'||kind==='artifact_intent'){if(id!==null)fail();}else if(!vendorUuid(id))fail();}
export async function prepareVendorOperation<K extends VendorKind>(scope:Scope,kind:K,targetId:string|null,request:VendorRequests[K]):Promise<VendorOperation<K>>{
  target(scope,kind,targetId);const normalized=normalizeVendor(requestModel(scope,kind),request) as VendorRequests[K];if(vendorBytes(normalized)>vendorRequestLimit(kind))fail();
  if(kind==='artifact_content'&&(normalized as VendorArtifactContent).artifact_id!==targetId)fail();
  return {version:1,scope:structuredClone(scope),kind,target_id:targetId,request:normalized,request_sha256:await vendorRequestDigest(kind,scope,normalized)};
}
export async function validateVendorOperation(value:unknown,scope?:Scope):Promise<VendorOperation>{
  if(!vendorObject(value)||Object.keys(value).sort().join(',')!=='kind,request,request_sha256,scope,target_id,version'||value.version!==1||typeof value.kind!=='string'||!Object.hasOwn(vendorRequestModel,value.kind))fail();
  const v=value as VendorOperation;target(v.scope,v.kind,v.target_id);if(scope&&vendorCanonical(scope)!==vendorCanonical(v.scope))fail();
  validateVendor(requestModel(v.scope,v.kind),v.request);const expected=await prepareVendorOperation(v.scope,v.kind,v.target_id,v.request);if(vendorCanonical(expected)!==vendorCanonical(v))fail();return expected;
}
export async function verifyOperationReceipt(operation:VendorOperation,value:unknown):Promise<VendorReceipt>{
  const r=operation.request;const artifact=operation.kind.startsWith('artifact_');
  const expected={scope:operation.scope,kind:operation.kind,key:r.idempotency_key,sha256:operation.request_sha256,
    ...(!artifact&&operation.target_id?{ticketId:operation.target_id}:{}),...('revises'in r&&r.revises?{ticketId:r.revises.ticket_id}:{}),
    ...('operation_id'in r?{operationId:r.operation_id}:{}),...('proposed_operation_id'in r?{operationId:r.proposed_operation_id}:{}),
    ...('revision_id'in r?{revisionId:r.revision_id}:{}),...('payload_hash'in r?{payloadHash:r.payload_hash}:{}),
    ...(artifact?{artifactId:(r as VendorArtifactIntent|VendorArtifactContent).artifact_id}:{})};
  const valueChecked=await verifyVendorReceipt(value,expected,artifact);
  if(operation.kind==='verify'&&valueChecked.outcome==='recorded'&&(!('summary'in valueChecked)||valueChecked.summary?.effect!=='verified'))fail();
  if(artifact){const a=(valueChecked as ArtifactResponse).artifact;const goal=r as VendorArtifactIntent|VendorArtifactContent;
    if(a&&(a.document.sha256!==goal.sha256||a.document.byte_length!==goal.byte_length||a.document.media_type!==goal.media_type||('source'in goal&&vendorCanonical(a.source)!==vendorCanonical(goal.source))||('intent_sha256'in goal&&a.intent_sha256!==goal.intent_sha256)))fail();}
  return valueChecked;
}
export function vendorOperationPath(op:VendorOperation,resolve=false):string {
  if(op.scope.kind==='practice_work')return `/practice-work/${op.scope.id}/${resolve?'vendor-command/resolve':op.kind==='handoff'?'handoffs':'result'}`;
  const root=`/workspaces/${op.scope.id}/${op.kind.startsWith('artifact_')?'vendor-artifacts':'vendor-work'}`;
  if(resolve)return root+'/resolve';if(op.kind==='propose'||op.kind==='artifact_intent')return root;
  return root+`/${op.target_id}/`+(op.kind==='artifact_content'?'content':op.kind);
}
export function vendorResolveRequest(op:VendorOperation){return {command_kind:op.kind,idempotency_key:op.request.idempotency_key,request_sha256:op.request_sha256,...(op.kind.startsWith('artifact_')?{artifact_id:(op.request as VendorArtifactIntent).artifact_id}:{})};}
