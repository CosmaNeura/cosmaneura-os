import fixture from './__fixtures__/portal-setup.json';
import {preparePortalOperation,portalRequest,verifyPortalCatalog,verifyPortalDetail,verifyPortalReceipt,type PortalOperation} from './portal-setup-contract';
import {vendorDigest} from './vendor-contract';
export const portalFixture=fixture;
export const actualPortalCatalog=()=>verifyPortalCatalog(structuredClone(fixture.catalog_pending));
export const actualPortalDetail=()=>verifyPortalDetail(structuredClone(fixture.detail_pending));
export const actualPortalProposal=()=>preparePortalOperation(fixture.proposal_receipt.scope,'propose',portalRequest('propose',fixture.proposal));
export async function portalReceipt(op:PortalOperation){
  const v=structuredClone(op.kind==='propose'?fixture.proposal_receipt:fixture.activation_receipt);
  Object.assign(v,{scope:op.scope,command_kind:op.kind,idempotency_key:op.request.idempotency_key,request_sha256:op.request_sha256,connection_id:op.request.connection_id});
  v.effect.version=op.request.expected_version+1;
  v.effect.state={propose:'pending_review',activate:'active',disable:'disabled',revoke:'revoked'}[op.kind];
  if('revision_id'in op.request){v.effect.revision_id=op.request.revision_id;v.effect.review_sha256=op.request.review_sha256;}
  const {receipt_sha256:_,...body}=v;v.receipt_sha256=await vendorDigest('cosmas-portal-setup-receipt.v1',body);
  return verifyPortalReceipt(v,op);
}
