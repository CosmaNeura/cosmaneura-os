import {teamClosed,teamHash,teamNatural,teamUuid} from './team-setup-request';
import type {InboxBundle} from './inbox-contract';

export type InboxAnalysis={version:1;consented:true;item_id:string;item_version:number;source_id:string;source_sha256:string;
  review_receipt_id:string;review_receipt_sha256:string;triage_receipt_id:string;triage_receipt_sha256:string};
export type InboxDraftSelection={workspace_id:string;expected_revision:number;patient_link_id:string;label:string;
  message:string;instructions:string;analysis:Omit<InboxAnalysis,'consented'>};
export const INBOX_DRAFT_QUESTION='Draft an administrative reply to this reviewed incoming message using the human triage instructions. Keep it ready for human review. If the message needs clinical judgment, urgent attention or missing information, explain the human review needed.';

export function validInboxAnalysis(value:unknown):value is InboxAnalysis {
  return teamClosed(value,'version,consented,item_id,item_version,source_id,source_sha256,review_receipt_id,review_receipt_sha256,triage_receipt_id,triage_receipt_sha256')&&
    value.version===1&&value.consented===true&&teamNatural(value.item_version)&&value.item_version>=1&&value.item_version<=2147483647&&
    ['item_id','source_id','review_receipt_id','triage_receipt_id'].every(key=>teamUuid(value[key]))&&
    ['source_sha256','review_receipt_sha256','triage_receipt_sha256'].every(key=>teamHash(value[key]));
}

/** Selection conveys no consent or authority. Admission rechecks all saved anchors. */
export function inboxDraftSelection(bundle:InboxBundle):InboxDraftSelection|null {
  const d=bundle.detail,s=d.summary,r=d.latest_review,t=d.latest_triage;
  if(s.state!=='triaged'||s.classification!=='administrative_review'||!s.binding_current||!s.workspace_current||
    s.source_conflict||s.read_issue||s.incomplete_content||!s.source_id||!s.source_sha256||!s.workspace_id||!r||!t||d.latest_result||d.latest_verification)return null;
  const review=bundle.history.commands.find(c=>c.receipt.receipt_id===r.receipt_id&&c.receipt.receipt_sha256===r.receipt_sha256)?.request;
  const triage=bundle.history.commands.find(c=>c.receipt.receipt_id===t.receipt_id&&c.receipt.receipt_sha256===t.receipt_sha256)?.request;
  const message=d.source?.text;
  if(!review||!('workspace_id' in review)||review.workspace_id!==s.workspace_id||review.patient_link_id!==s.patient_link_id||
    !triage||!('instructions' in triage)||triage.classification!=='administrative_review'||!message||[...message].length>5000||new TextEncoder().encode(message).length>20000)return null;
  const analysis={version:1 as const,item_id:s.item_id,item_version:s.version,source_id:s.source_id,source_sha256:s.source_sha256,
    review_receipt_id:r.receipt_id!,review_receipt_sha256:r.receipt_sha256!,triage_receipt_id:t.receipt_id!,triage_receipt_sha256:t.receipt_sha256!};
  if(!validInboxAnalysis({...analysis,consented:true}))return null;
  return {workspace_id:s.workspace_id,expected_revision:review.expected_workspace_revision,patient_link_id:s.patient_link_id,
    label:s.label,message,instructions:triage.instructions,analysis};
}
