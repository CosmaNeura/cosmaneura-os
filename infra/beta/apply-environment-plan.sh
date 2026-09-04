#!/bin/bash -p
set +x
_cosmas_wrapper_dir="$(cd -- "$(/usr/bin/dirname -- "${BASH_SOURCE[0]}")" && /bin/pwd -P)" || exit 1
# shellcheck source=local-wrapper-env.sh
. "$_cosmas_wrapper_dir/local-wrapper-env.sh"
cosmas_isolate_local_wrapper_environment "$@"
unset -f cosmas_isolate_local_wrapper_environment
unset _cosmas_wrapper_dir
set -euo pipefail

umask 077

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repository_root="$(cd -- "$script_dir/../.." && pwd -P)"
GUARD_ENVIRONMENT_DIR="$script_dir/environment"
# shellcheck source=deployment-guard-lib.sh
source "$script_dir/deployment-guard-lib.sh"

usage() {
  printf '%s\n' \
    "Usage: $0 --bootstrap-outputs PATH --var-file PATH --plan PATH --review PATH --approval PATH --approval-bundle DIR --attempt-claim PATH --source-sha SHA --release-id ID --stage foundation|database|workloads --result-out PATH" \
    "" \
    "Applies one plan emitted by subsequent-environment-plan.sh. The approval" \
    "JSON must bind a named reviewer/reference to the exact plan hash and prior" \
    "state lineage/serial recorded in the sanitized review manifest."
}

bootstrap_outputs=""
plan_path=""
var_file=""
review_path=""
approval_path=""
approval_bundle=""
result_out=""
approved_source_sha=""
release_id=""
stage=""
attempt_claim=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --bootstrap-outputs)
      [[ $# -ge 2 ]] || guard_die "--bootstrap-outputs requires a path"
      bootstrap_outputs="$2"
      shift 2
      ;;
    --plan)
      [[ $# -ge 2 ]] || guard_die "--plan requires a path"
      plan_path="$2"
      shift 2
      ;;
    --var-file)
      [[ $# -ge 2 ]] || guard_die "--var-file requires a path"
      var_file="$2"
      shift 2
      ;;
    --review)
      [[ $# -ge 2 ]] || guard_die "--review requires a path"
      review_path="$2"
      shift 2
      ;;
    --approval)
      [[ $# -ge 2 ]] || guard_die "--approval requires a path"
      approval_path="$2"
      shift 2
      ;;
    --approval-bundle)
      [[ $# -ge 2 ]] || guard_die "--approval-bundle requires a path"
      approval_bundle="$2"
      shift 2
      ;;
    --source-sha)
      [[ $# -ge 2 ]] || guard_die "--source-sha requires a value"
      approved_source_sha="$2"
      shift 2
      ;;
    --release-id)
      [[ $# -ge 2 ]] || guard_die "--release-id requires a value"
      release_id="$2"
      shift 2
      ;;
    --stage)
      [[ $# -ge 2 ]] || guard_die "--stage requires a value"
      stage="$2"
      shift 2
      ;;
    --attempt-claim)
      [[ $# -ge 2 ]] || guard_die "--attempt-claim requires a path"
      attempt_claim="$2"
      shift 2
      ;;
    --result-out)
      [[ $# -ge 2 ]] || guard_die "--result-out requires a path"
      result_out="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      guard_die "unknown argument: $1"
      ;;
  esac
done

[[ -n "$bootstrap_outputs" ]] || guard_die "--bootstrap-outputs is required"
[[ -n "$plan_path" ]] || guard_die "--plan is required"
[[ -n "$var_file" ]] || guard_die "--var-file is required"
[[ -n "$review_path" ]] || guard_die "--review is required"
[[ -n "$approval_path" ]] || guard_die "--approval is required"
[[ -n "$approval_bundle" ]] || guard_die "--approval-bundle is required"
[[ "$approved_source_sha" =~ ^[0-9a-f]{40}$ ]] || guard_die "--source-sha must be a lowercase commit SHA"
[[ "$release_id" =~ ^[a-z0-9][a-z0-9-]{2,31}$ ]] || guard_die "--release-id is invalid"
[[ "$stage" == "foundation" || "$stage" == "database" || "$stage" == "workloads" ]] || guard_die "--stage is invalid"
[[ -n "$attempt_claim" ]] || guard_die "--attempt-claim is required"
[[ -n "$result_out" ]] || guard_die "--result-out is required"

for command_name in az jq stat; do
  command -v "$command_name" >/dev/null 2>&1 || guard_die "$command_name is required"
done
guard_find_terraform

bootstrap_outputs="$(guard_absolute_path "$bootstrap_outputs")"
plan_path="$(guard_absolute_path "$plan_path")"
var_file="$(guard_absolute_path "$var_file")"
review_path="$(guard_absolute_path "$review_path")"
approval_path="$(guard_absolute_path "$approval_path")"
approval_bundle="$(guard_absolute_path "$approval_bundle")"
attempt_claim="$(guard_absolute_path "$attempt_claim")"
result_out="$(guard_absolute_path "$result_out")"
guard_outside_repository "$bootstrap_outputs" "$repository_root" "bootstrap output JSON"
guard_outside_repository "$plan_path" "$repository_root" "plan"
guard_outside_repository "$var_file" "$repository_root" "environment variable file"
guard_outside_repository "$review_path" "$repository_root" "review manifest"
guard_outside_repository "$approval_path" "$repository_root" "approval record"
guard_outside_repository "$approval_bundle" "$repository_root" "approval bundle"
guard_outside_repository "$attempt_claim" "$repository_root" "apply-attempt claim"
guard_outside_repository "$result_out" "$repository_root" "apply result"
guard_private_file "$bootstrap_outputs" "bootstrap output JSON"
guard_private_file "$plan_path" "plan"
guard_private_file "$var_file" "environment variable file"
guard_private_file "$review_path" "review manifest"
guard_private_file "$approval_path" "approval record"
guard_private_directory "$approval_bundle" "approval bundle"
[[ "$approval_path" == "$approval_bundle/source-approval.json" ]] || guard_die "--approval must be the fixed source-approval.json inside --approval-bundle"
guard_new_private_path "$result_out" "apply result"

pre_state=""
post_state=""
plan_json=""
sanitized_changes=""
critical_values=""
security_posture=""
result_created=false
completed=false
cleanup() {
  [[ -z "$pre_state" ]] || rm -f -- "$pre_state"
  [[ -z "$post_state" ]] || rm -f -- "$post_state"
  [[ -z "$plan_json" ]] || rm -f -- "$plan_json"
  [[ -z "$sanitized_changes" ]] || rm -f -- "$sanitized_changes"
  [[ -z "$critical_values" ]] || rm -f -- "$critical_values"
  [[ -z "$security_posture" ]] || rm -f -- "$security_posture"
  if [[ "$result_created" == "true" && "$completed" != "true" ]]; then
    rm -f -- "$result_out"
  fi
}
trap cleanup EXIT

guard_load_bootstrap_outputs "$bootstrap_outputs"
guard_source_metadata "$repository_root"
[[ "$GUARD_SOURCE_SHA" == "$approved_source_sha" ]] || guard_die "approved source SHA does not match the checked-out source"
guard_verify_azure_context_and_boundary
guard_state_exists || guard_die "remote state does not exist; a subsequent plan cannot be applied"
review_phase="$(jq -er '.phase | strings' "$review_path")"
[[ "$review_phase" == "subsequent" || "$review_phase" == "foundation_reconcile" ]] || guard_die "review phase is not a guarded subsequent/reconciliation plan"
export TF_DATA_DIR="${plan_path}.terraform-data"
guard_backend_init

pre_state="$(mktemp "${TMPDIR:-/tmp}/cosmas-d3-pre-apply-state.XXXXXX")"
guard_pull_state "$pre_state"
if [[ "$review_phase" == "foundation_reconcile" ]]; then
  guard_validate_environment_state "$pre_state" partial_foundation
else
  guard_validate_environment_state "$pre_state"
fi
pre_lineage="$GUARD_STATE_LINEAGE"
pre_serial="$GUARD_STATE_SERIAL"
pre_state_sha256="$GUARD_STATE_SHA256"
plan_sha256="$(guard_sha256 "$plan_path")"
review_sha256="$(guard_sha256 "$review_path")"
variable_file_sha256="$(guard_sha256 "$var_file")"

jq -e \
  --arg plan_sha256 "$plan_sha256" \
  --arg source_sha "$GUARD_SOURCE_SHA" \
  --arg terraform_version "$GUARD_TERRAFORM_VERSION" \
  --arg provider_lock_sha256 "$GUARD_PROVIDER_LOCK_SHA256" \
  --arg variable_file_sha256 "$(guard_sha256 "$var_file")" \
  --arg lineage "$pre_lineage" \
  --argjson serial "$pre_serial" \
  --arg state_sha256 "$pre_state_sha256" \
  --arg subscription_id "$GUARD_SUBSCRIPTION_ID" \
  --arg tenant_id "$GUARD_TENANT_ID" \
  --arg deploy_identity_client_id "$GUARD_DEPLOY_CLIENT_ID" \
  --arg beta_id "$GUARD_BETA_ID" \
  --arg box_id "$GUARD_BOX_ID" \
  --arg state_resource_group "$GUARD_STATE_RESOURCE_GROUP" \
  --arg workload_resource_group "$GUARD_WORKLOAD_RESOURCE_GROUP" \
  --arg state_vnet_id "$GUARD_STATE_VNET_ID" \
  --arg state_blob_private_dns_zone_id "$GUARD_STATE_BLOB_PRIVATE_DNS_ZONE_ID" \
  --arg deployment_mode "$GUARD_DEPLOYMENT_MODE" \
  --arg data_classification "$GUARD_DATA_CLASSIFICATION" \
  --arg review_phase "$review_phase" '
    .schema_version == 1 and
    .phase == $review_phase and
    .plan_sha256 == $plan_sha256 and
    .source_sha == $source_sha and
    .terraform_version == $terraform_version and
    .provider_lock_sha256 == $provider_lock_sha256 and
    .variable_file_sha256 == $variable_file_sha256 and
    .prior_state.lineage == $lineage and
    .prior_state.serial == $serial and
    .prior_state.sha256 == $state_sha256 and
    .boundary.subscription_id == $subscription_id and
    .boundary.tenant_id == $tenant_id and
    .boundary.deploy_identity_client_id == $deploy_identity_client_id and
    .boundary.beta_id == $beta_id and
    .boundary.box_id == $box_id and
    .boundary.state_resource_group == $state_resource_group and
    .boundary.workload_resource_group == $workload_resource_group and
    .boundary.state_vnet_id == $state_vnet_id and
    .boundary.state_blob_private_dns_zone_id == $state_blob_private_dns_zone_id and
    .boundary.deployment_mode == $deployment_mode and
    .boundary.data_classification == $data_classification and
    .managed_action_counts.delete == 0 and
    .managed_action_counts.replace == 0
  ' "$review_path" >/dev/null || guard_die "review manifest does not match the exact plan, state, identity, mode, and Box boundary"

guard_validate_apply_approval "$approval_path" "$approval_bundle" "$GUARD_SOURCE_SHA" "$release_id" "$stage" \
  "$plan_sha256" "$review_sha256" "$variable_file_sha256" true \
  "$pre_lineage" "$pre_serial" "$pre_state_sha256"

plan_json="$(mktemp "${TMPDIR:-/tmp}/cosmas-d3-apply-plan.XXXXXX")"
"$GUARD_TERRAFORM_BIN" -chdir="$GUARD_ENVIRONMENT_DIR" show -json "$plan_path" >"$plan_json"
chmod 600 "$plan_json"
guard_validate_planned_boundary "$plan_json"
guard_validate_safe_plan_actions "$plan_json" true
sanitized_changes="$(mktemp "${TMPDIR:-/tmp}/cosmas-d3-apply-changes.XXXXXX")"
jq '[.resource_changes[]? | {address, type, mode, actions: .change.actions}]' "$plan_json" >"$sanitized_changes"
chmod 600 "$sanitized_changes"
critical_values="$(mktemp "${TMPDIR:-/tmp}/cosmas-d3-apply-critical-values.XXXXXX")"
guard_write_critical_planned_values "$plan_json" "$critical_values"
security_posture="$(mktemp "${TMPDIR:-/tmp}/cosmas-d3-apply-security-posture.XXXXXX")"
guard_write_security_posture "$plan_json" "$security_posture"
jq -e \
  --argjson create "$GUARD_CREATE_COUNT" \
  --argjson update "$GUARD_UPDATE_COUNT" \
  --argjson no_op "$GUARD_NOOP_COUNT" \
  --slurpfile managed_actions "$sanitized_changes" \
  --slurpfile critical_planned_values "$critical_values" \
  --slurpfile security_posture "$security_posture" '
    .managed_action_counts.create == $create and
    .managed_action_counts.update == $update and
    .managed_action_counts.no_op == $no_op and
    .managed_action_counts.delete == 0 and
    .managed_action_counts.replace == 0 and
    .managed_actions == $managed_actions[0] and
    .critical_planned_values == $critical_planned_values[0] and
    .security_posture == $security_posture[0]
  ' "$review_path" >/dev/null || guard_die "review manifest action counts do not match the saved plan"

no_changes=false
if (( GUARD_CREATE_COUNT == 0 && GUARD_UPDATE_COUNT == 0 )) && [[ "$review_phase" == "subsequent" ]]; then
  # A reviewed no-op is the guarded drift check. Do not invoke apply merely to
  # manufacture a serial change; bind the result to the unchanged state.
  no_changes=true
  post_lineage="$pre_lineage"
  post_serial="$pre_serial"
  post_state_sha256="$pre_state_sha256"
else
  # OpenTofu performs its own saved-plan state snapshot check while it acquires
  # the remote backend lock. A concurrent state change therefore fails even
  # after the explicit pre-apply lineage/serial check above.
  # Re-read the live centralus boundary and all authorization expiries at the
  # last possible point before OpenTofu can mutate anything.
  guard_verify_azure_context_and_boundary
  guard_validate_apply_approval "$approval_path" "$approval_bundle" "$GUARD_SOURCE_SHA" "$release_id" "$stage" \
    "$plan_sha256" "$review_sha256" "$variable_file_sha256" true \
    "$pre_lineage" "$pre_serial" "$pre_state_sha256"
  guard_claim_apply_attempt "$attempt_claim" "$GUARD_SOURCE_SHA" "$release_id" "$stage" \
    "$plan_sha256" "$(guard_sha256 "$approval_path")" "$(jq -er '.authorization_claim_sha256' "$approval_path")" \
    "causal-bundle-claim"
  guard_validate_apply_approval "$approval_path" "$approval_bundle" "$GUARD_SOURCE_SHA" "$release_id" "$stage" \
    "$plan_sha256" "$review_sha256" "$variable_file_sha256" true \
    "$pre_lineage" "$pre_serial" "$pre_state_sha256"
  "$GUARD_TERRAFORM_BIN" -chdir="$GUARD_ENVIRONMENT_DIR" apply \
    -input=false \
    "$plan_path"

  post_state="$(mktemp "${TMPDIR:-/tmp}/cosmas-d3-post-apply-state.XXXXXX")"
  guard_pull_state "$post_state"
  guard_validate_environment_state "$post_state"
  post_lineage="$GUARD_STATE_LINEAGE"
  post_serial="$GUARD_STATE_SERIAL"
  post_state_sha256="$GUARD_STATE_SHA256"
  [[ "$post_lineage" == "$pre_lineage" ]] || guard_die "remote state lineage changed during apply"
  (( post_serial > pre_serial )) || guard_die "remote state serial did not advance after a changing plan"
fi
guard_verify_azure_context_and_boundary

reviewer="$(jq -er '.reviewer' "$approval_path")"
review_reference="$(jq -er '.review_reference' "$approval_path")"
applied_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
jq -n \
  --arg applied_at "$applied_at" \
  --arg plan_sha256 "$plan_sha256" \
  --arg lineage "$pre_lineage" \
  --argjson pre_serial "$pre_serial" \
  --argjson post_serial "$post_serial" \
  --arg pre_state_sha256 "$pre_state_sha256" \
  --arg post_state_sha256 "$post_state_sha256" \
  --arg reviewer "$reviewer" \
  --arg review_reference "$review_reference" \
  --arg box_id "$GUARD_BOX_ID" \
  --arg deployment_mode "$GUARD_DEPLOYMENT_MODE" '
    {
      schema_version: 1,
      applied_at: $applied_at,
      plan_sha256: $plan_sha256,
      state: {
        lineage: $lineage,
        pre_serial: $pre_serial,
        post_serial: $post_serial,
        pre_sha256: $pre_state_sha256,
        post_sha256: $post_state_sha256
      },
      approval: {
        reviewer: $reviewer,
        review_reference: $review_reference
      },
      boundary: {
        box_id: $box_id,
        deployment_mode: $deployment_mode
      },
      no_changes: false
    }
  ' >"$result_out"
if [[ "$no_changes" == "true" ]]; then
  result_tmp="$(mktemp "${TMPDIR:-/tmp}/cosmas-d3-noop-result.XXXXXX")"
  jq '.no_changes = true' "$result_out" >"$result_tmp"
  mv -f -- "$result_tmp" "$result_out"
fi
chmod 600 "$result_out"
result_created=true
completed=true

printf 'D3 guarded apply completed: plan SHA-256 %s; state %s serial %s -> %s; no_changes=%s\n' \
  "$plan_sha256" "$pre_lineage" "$pre_serial" "$post_serial" "$no_changes"
