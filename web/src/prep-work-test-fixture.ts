import type {PrepWorkItem} from "./prep-work-api";
import type {EncounterPrep} from "./encounter-prep-api";
export const prepWorkspace="00000000-0000-4000-8000-000000000001";
export const prepTicket="00000000-0000-4000-8000-000000000002";
export const prepRevision="00000000-0000-4000-8000-000000000003";
export const prepPerson={id:"00000000-0000-4000-8000-000000000004",name:"Invented provider",available:true};
export const prepBot={address:"visit_prep",team_revision:1};
export const prepReceipt:EncounterPrep={appointment_ref:"a".repeat(64),snapshot_sha256:"b".repeat(64),display_sha256:"c".repeat(64),additional_notes_available:false,
  sources:[{source_id:"d".repeat(64),appointment_ref:"a".repeat(64),kind:"patient_intake_summary",label:"Saved intake summary",
    source_at:"2026-09-21T10:00:00Z",content_sha256:"e".repeat(64),content:"Invented saved summary",truncated:false,content_redacted:false}]};
export function prepItem(state="pending_approval",ready=false):PrepWorkItem {
  return {ticket_id:prepTicket,version:1,revision_id:prepRevision,payload_hash:"f".repeat(64),state,
    body:"Review the saved intake summary before the visit",due_date:"2026-09-25",expected_outcome:"A saved summary for provider review",viewer_id:prepPerson.id,
    originator:{...prepPerson},responsible:{...prepPerson},pending_offer:null,handoffs:[],work_kind:"visit_preparation",ready_for_review:ready,
    proposed_snapshot_sha256:prepReceipt.snapshot_sha256,receipts:ready?[{id:"00000000-0000-4000-8000-000000000005",kind:"ready_for_review",content:"Summary is saved for provider review",actor:{...prepPerson},created_at:"2026-09-21T12:00:00Z"}]:[]};
}
