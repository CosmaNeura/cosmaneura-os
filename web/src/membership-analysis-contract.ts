import {teamClosed,teamHash,teamNatural,teamUuid} from './team-setup-request';
import {vendorCanonical,vendorDigest} from './vendor-contract';
import type {Detail as MembershipDetail} from './membership-schema';
import type {FinanceDetail} from './finance-schema';

export type MembershipAnalysis={version:1;consented:true;kind:'membership'|'payment';ticket_id:string;ticket_version:number;revision_id:string;payload_hash:string;snapshot_sha256:string};
export type MembershipReviewSelection={workspace_id:string;expected_revision:number;label:string;data:Record<string,unknown>;analysis:Omit<MembershipAnalysis,'consented'>};
export class MembershipSelectionTooLargeError extends Error {}
export const MEMBERSHIP_REVIEW_QUESTION='Review this selected membership or payment work record. Explain its current status, evidence limits, reconciliation gaps and concrete next steps for human review. Distinguish manual claims from processor observations; do not assume payment establishes membership or that any external action has occurred.';
export function validMembershipAnalysis(v:unknown):v is MembershipAnalysis {
  return teamClosed(v,'version,consented,kind,ticket_id,ticket_version,revision_id,payload_hash,snapshot_sha256')&&v.version===1&&v.consented===true&&
    (v.kind==='membership'||v.kind==='payment')&&teamUuid(v.ticket_id)&&teamUuid(v.revision_id)&&teamNatural(v.ticket_version)&&v.ticket_version>=1&&v.ticket_version<=500&&teamHash(v.payload_hash)&&teamHash(v.snapshot_sha256);
}
const pick=(value:object,keys:string[])=>Object.fromEntries(keys.map(key=>[key,(value as Record<string,unknown>)[key]]));

/** Input must be a detail already validated by the corresponding private reader. */
export function membershipSnapshot(detail:MembershipDetail) {
  const s=detail.summary,r=detail.review.proposal,result=detail.latest_result,ledger=result?.request.ledger;
  return {kind:'membership',data:{
    status:pick(s,['purpose','due_date','state','evidence_classification','evidence_current','result','verification','external_service_verified','membership_authority','source_current']),
    expected_outcome:r.expected_outcome,instructions:r.instructions,human_evidence:result?.request.evidence??null,
    ledger_observation:ledger?{observed_at:ledger.observed_at,membership_state:ledger.observed_membership_state,billing_state:ledger.observed_billing_state,linked_finance_review:!!ledger.finance,authority:'human_recorded_not_independent_service_verification'}:null,
  },review_sha256:detail.review_sha256,result_receipt:result?{id:result.receipt_id,sha256:result.receipt_sha256}:null,finance_evidence:null};
}
export function paymentSnapshot(detail:FinanceDetail) {
  const s=detail.summary,r=detail.review,result=detail.latest_result;
  return {kind:'payment',data:{
    status:pick(s,['state','amount','currency','creation','payment_state','amount_received','submit_claimed','conflicting_evidence','result','verification']),
    due_date:r.due_date,expected_outcome:r.expected_outcome,human_evidence:result?.evidence??null,amount_unit:'minor_currency_unit',membership_authority:'not_established_by_payment',
  },review_sha256:detail.review_sha256,result_receipt:result?{id:result.receipt_id,sha256:result.receipt_sha256}:null,finance_evidence:{observation_head:s.observation_head,evidence_sha256:s.evidence_sha256}};
}
export async function membershipReviewSelection(kind:'membership'|'payment',detail:MembershipDetail|FinanceDetail,workspaceId:string,expectedRevision:number):Promise<MembershipReviewSelection> {
  const snapshot=kind==='membership'?membershipSnapshot(detail as MembershipDetail):paymentSnapshot(detail as FinanceDetail),s=detail.summary;
  if(kind==='membership'?(detail as MembershipDetail).scope.workspace_id!==workspaceId:(detail as FinanceDetail).workspace_id!==workspaceId)throw new Error('Work scope changed');
  // Exact same selected, allow-listed data is displayed and sent. No silent clipping.
  const serialized=JSON.stringify(snapshot.data,null,2);
  if([...serialized].length>5000||new TextEncoder().encode(serialized).length>20000)throw new MembershipSelectionTooLargeError('The selected evidence is too large for one review');
  const analysis={version:1 as const,kind,ticket_id:s.ticket_id,ticket_version:s.version,revision_id:s.revision_id,payload_hash:s.payload_hash,snapshot_sha256:await vendorDigest('cosmas-membership-analysis.v1',snapshot)};
  if(!validMembershipAnalysis({...analysis,consented:true})||!teamNatural(expectedRevision)||expectedRevision<1)throw new Error('Invalid work selection');
  vendorCanonical(snapshot);
  return {workspace_id:workspaceId,expected_revision:expectedRevision,label:kind==='membership'?'Selected membership work':'Selected payment work',data:snapshot.data,analysis};
}
