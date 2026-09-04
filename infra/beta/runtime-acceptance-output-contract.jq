(.evidence_sha256 | strings | test("^[0-9a-f]{64}$")) and
if $phase == "runtime" then
  .contract == "cosmas-os-d3-runtime-acceptance-v2" and
  .status == "ready" and
  .environment == "early_adopter_beta" and
  .data_mode == "synthetic" and
  .blob_backend == "azure" and
  .sync_worker_disabled == true and
  .user_assigned_managed_identity == true and
  .blob_write_read_sha_match == true and
  .blob_current_representation_absent_after_delete == true and
  .blob_version_representations_absent_after_delete == true and
  .blob_snapshot_representations_absent_after_delete == true and
  .blob_deleted_representations_absent_after_delete == true and
  .blob_recoverable_absence_verified == true and
  .redis_round_trip == true and
  .redis_cleanup_confirmed == true and
  .database_schema_revision == "0002_external_identities" and
  .database_schema_at_expected_head == true and
  .database_insert_read_rolled_back == true
elif $phase == "workflow-baseline" then
  .contract == "cosmas-os-d3-workflow-acceptance-v1" and
  .stage == "baseline" and
  .status == "ready_for_browser" and
  (.state_mac | test("^[0-9a-f]{64}$")) and
  (.ticket_handle | test("^[0-9a-f]{64}$")) and
  .pending_ticket_count == 1 and
  .approval_decision_count == 0 and
  .operation_count == 0 and
  .approval_audit_count == 0 and
  .success_audit_count == 0
elif $phase == "workflow-verify" then
  .contract == "cosmas-os-d3-workflow-acceptance-v1" and
  .stage == "post_browser" and
  .status == "verified" and
  .state_bound == true and
  .async_dispatch_configured == true and
  .current_revision_valid == true and
  .approval_decision_delta == 1 and
  .durable_operation_delta == 1 and
  .worker_attempted == true and
  .operation_succeeded == true and
  .fake_notify_receipt_verified == true and
  .ticket_sent == true and
  .approval_audit_delta == 1 and
  .success_audit_delta == 1 and
  .approval_precedes_worker_success == true
elif $phase == "audit-replay" then
  .contract == "cosmas-os-d3-audit-replay-acceptance-v1" and
  .stage == "live_replay" and
  .status == "verified" and
  .box_scope_enforced == true and
  .cross_box_replay_denied == true and
  .ticket_timeline_replayed == true and
  .operation_events_linked == true and
  .required_event_order_verified == true and
  .no_content_fields_returned == true and
  (.timeline_event_count | numbers | floor == . and . == 3) and
  .identifiers_returned == false and
  .content_returned == false
elif $phase == "purge-setup" then
  .contract == "cosmas-os-d3-physical-purge-acceptance-v1" and
  .stage == "setup" and
  .status == "ready_for_browser" and
  (.state_mac | test("^[0-9a-f]{64}$")) and
  (.artifact_handle | test("^[0-9a-f]{64}$")) and
  .due_unpurged_artifact_count == 1 and
  .purge_audit_count == 0 and
  .blob_current_representation_readable == true
elif $phase == "purge-verify" then
  .contract == "cosmas-os-d3-physical-purge-acceptance-v1" and
  .stage == "post_browser" and
  .status == "verified" and
  .state_bound == true and
  .owner_authorized_purge_observed == true and
  .owner_authority_verified == true and
  .application_tombstone_verified == true and
  .purge_receipt_verified == true and
  .purge_audit_delta == 1 and
  .blob_current_representation_absent == true and
  .blob_version_representations_absent == true and
  .blob_snapshot_representations_absent == true and
  .blob_deleted_representations_absent == true and
  .blob_recoverable_absence_verified == true and
  .due_unpurged_probe_count == 0
else
  false
end
