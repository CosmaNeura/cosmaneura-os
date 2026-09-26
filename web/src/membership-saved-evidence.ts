import type {WorkspaceIdentity} from './workspace-api';
import type {Scope,Document} from './membership-schema';
import type {FinanceDetail,FinanceResponse,FinanceVerify} from './finance-schema';
import type {MembershipReviewBundle} from './membership-operation';
import {MembershipContractError,sameMembershipScope,validateMembership} from './membership-contract';
import {validateFinance} from './finance-contract';
import {prepareFinanceOperation} from './finance-operation';
import {membershipFinanceProof} from './membership-evidence';
import {vendorBytes,vendorCanonical,vendorObject} from './vendor-contract';
import {vendorApi,requirePdf} from './vendor-api';

export type SavedMembershipBinding={ticket_id:string;version:number;revision_id:string;payload_hash:string;result_receipt_id:string;result_receipt_sha256:string};
export type MembershipSavedFinance={contract_version:1;scope:Scope;membership:SavedMembershipBinding;request:FinanceVerify;receipt:FinanceResponse;detail:FinanceDetail};
function fail():never{throw new MembershipContractError();}
export function savedMembershipBinding(bundle:MembershipReviewBundle):SavedMembershipBinding{
 const {summary:s,latest_result:r}=bundle.detail;if(!r?.request.ledger)fail();
 return {ticket_id:s.ticket_id,version:s.version,revision_id:s.revision_id,payload_hash:s.payload_hash,result_receipt_id:r.receipt_id,result_receipt_sha256:r.receipt_sha256};
}
/** Read-only original request from the server receipt; never a reconstructed or executable command. */
export async function verifyMembershipSavedFinance(value:unknown,scope:Scope,bundle:MembershipReviewBundle):Promise<MembershipSavedFinance>{
 if(!vendorObject(value)||Object.keys(value).sort().join(',')!=='contract_version,detail,membership,receipt,request,scope'||value.contract_version!==1||vendorBytes(value)>65536)fail();
 const v=value as MembershipSavedFinance;validateMembership('Scope',v.scope);
 if(!sameMembershipScope(v.scope,scope)||!sameMembershipScope(bundle.detail.scope,scope)||vendorCanonical(v.membership)!==vendorCanonical(savedMembershipBinding(bundle))||bundle.detail.summary.evidence_current==='changed')fail();
 const proof=bundle.detail.latest_result!.request.ledger!.finance;if(!proof)fail();
 const request=validateFinance('FinanceVerify',v.request);
 const operation=await prepareFinanceOperation({kind:'workspace',id:scope.workspace_id},'verify',proof.ticket_id,request);
 if(vendorCanonical(operation.request)!==vendorCanonical(v.request))fail();
 const checked=await membershipFinanceProof({operation,receipt:v.receipt},v.detail,scope);
 if(vendorCanonical(checked.proof)!==vendorCanonical(proof)||!checked.detail.latest_result||request.result_receipt_id!==checked.detail.latest_result.receipt_id||request.result_receipt_sha256!==checked.detail.latest_result.receipt_sha256)fail();
 return structuredClone(v);
}
/** No journal lookup or current-note admission: exact source comes from fresh saved detail/history.
 * The existing artifact route performs two-phase authorization and verifies bytes.
 * The caller must recheck the saved result before publishing the returned bytes. */
export const membershipSavedDocument={
 async preview(identity:WorkspaceIdentity,scope:Scope,bundle:MembershipReviewBundle,signal?:AbortSignal):Promise<{document:Document;bytes:Uint8Array}>{
  if(!sameMembershipScope(bundle.detail.scope,scope)||bundle.detail.summary.evidence_current==='changed')fail();
  const document=validateMembership('Document',bundle.detail.latest_result?.request.ledger?.document);
  const bytes=await vendorApi.preview(identity,scope.workspace_id,document,signal);await requirePdf(document,bytes);
  signal?.throwIfAborted();return {document,bytes};
 },
};
