import actual from './__fixtures__/vendor-work/actual-http-r1.json';
import artifact from './__fixtures__/vendor-work/actual-artifact-r2.json';
import shared from './__fixtures__/vendor-work/actual-shared-r2.json';
import retirement from './__fixtures__/vendor-work/actual-retirement-r1.json';
import {validateVendor} from './vendor-contract';
import {prepareVendorOperation} from './vendor-operation';
export {actual,artifact,shared,retirement};
export const actualOptions=()=>validateVendor('Options',actual.options);
export const actualDetail=()=>validateVendor('Detail',actual.detail_pending);
export const actualShared=()=>validateVendor('SharedVendorDetail',shared.shared_offered_detail);
export function actualProposal(){const o=actualOptions(),r=actualDetail().review;return prepareVendorOperation({kind:'workspace',id:o.workspace_id},'propose',null,{expected_workspace_revision:o.entry_revision,idempotency_key:actual.proposal_receipt.idempotency_key,proposed_operation_id:r.operation_id,action:r.action,connection:{id:r.connection.id,revision:r.connection.revision,public_sha256:r.connection.public_sha256},source:r.source,correspondence:{id:r.correspondence!.id,revision:r.correspondence!.revision,public_sha256:r.correspondence!.public_sha256},message:r.message!,due_date:r.due_date,expected_outcome:r.expected_outcome,share_to_practice:r.share_to_practice});}
export function actualContent(){const a=validateVendor('ArtifactResponse',artifact.artifact_content_receipt),r=a.artifact!;return prepareVendorOperation(a.scope,'artifact_content',r.artifact_id,{artifact_id:r.artifact_id,intent_sha256:r.intent_sha256,idempotency_key:a.idempotency_key,sha256:r.document.sha256,byte_length:r.document.byte_length,media_type:'application/pdf'});}
export function actualAcceptance(){const d=actualShared();return prepareVendorOperation({kind:'practice_work',id:d.ticket_id},'handoff',d.ticket_id,{expected_version:d.version,revision_id:d.revision_id,payload_hash:d.payload_hash,idempotency_key:shared.shared_accept_receipt.idempotency_key,kind:'accept',offer_id:d.pending_offer!.id});}
export function actualRetiredVerification(){return prepareVendorOperation({kind:'workspace',id:retirement.retired.scope.id},'verify',retirement.retired.retirement.ticket_id,validateVendor('VendorVerify',retirement.request.request));}
export function actualCompletedVerification(){const d=validateVendor('Detail',retirement.manual_detail),r=d.latest_result!,s=d.summary;return prepareVendorOperation({kind:'workspace',id:d.workspace_id},'verify',s.ticket_id,{expected_version:s.version,operation_id:s.operation_id,revision_id:s.revision_id,payload_hash:s.payload_hash,idempotency_key:retirement.completed.idempotency_key,result_receipt_id:r.receipt_id,result_receipt_sha256:r.receipt_sha256,observation_head:s.observation_head,evidence_sha256:s.evidence_sha256,reviewed_result:true,reviewed_observations:true,outcome_confirmed:true,reviewed_conflicting_evidence:false});}
