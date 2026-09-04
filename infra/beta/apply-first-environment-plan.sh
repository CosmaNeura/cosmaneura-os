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
    "Usage: $0 --bootstrap-outputs PATH --var-file PATH --plan PATH --review PATH --approval PATH --approval-bundle DIR --attempt-claim PATH --source-sha SHA --release-id ID --stage foundation --result-out PATH" \
    "" \
    "Applies the exact create-only first environment plan after a human approval" \
    "record binds the plan hash. It refuses any existing remote state."
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
    --bootstrap-outputs) bootstrap_outputs="${2:-}"; shift 2 ;;
    --plan) plan_path="${2:-}"; shift 2 ;;
    --var-file) var_file="${2:-}"; shift 2 ;;
    --review) review_path="${2:-}"; shift 2 ;;
    --approval) approval_path="${2:-}"; shift 2 ;;
    --approval-bundle) approval_bundle="${2:-}"; shift 2 ;;
    --source-sha) approved_source_sha="${2:-}"; shift 2 ;;
    --release-id) release_id="${2:-}"; shift 2 ;;
    --stage) stage="${2:-}"; shift 2 ;;
    --attempt-claim) attempt_claim="${2:-}"; shift 2 ;;
    --result-out) result_out="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) guard_die "unknown argument: $1" ;;
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
[[ "$stage" == "foundation" ]] || guard_die "first apply requires --stage foundation"
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
for guarded_path in "$bootstrap_outputs" "$var_file" "$plan_path" "$review_path" "$approval_path" "$approval_bundle" "$attempt_claim" "$result_out"; do
  guard_outside_repository "$guarded_path" "$repository_root" "deployment artifact"
done
guard_private_file "$bootstrap_outputs" "bootstrap output JSON"
guard_private_file "$var_file" "environment variable file"
guard_private_file "$plan_path" "first environment plan"
guard_private_file "$review_path" "first-plan review manifest"
guard_private_file "$approval_path" "first-plan approval record"
guard_private_directory "$approval_bundle" "first-plan approval bundle"
[[ "$approval_path" == "$approval_bundle/source-approval.json" ]] || guard_die "--approval must be the fixed source-approval.json inside --approval-bundle"
guard_new_private_path "$result_out" "first apply result"

plan_json=""
sanitized_changes=""
critical_values=""
security_posture=""
pre_state=""
post_state=""
result_created=false
completed=false
cleanup() {
  [[ -z "$plan_json" ]] || rm -f -- "$plan_json"
  [[ -z "$sanitized_changes" ]] || rm -f -- "$sanitized_changes"
  [[ -z "$critical_values" ]] || rm -f -- "$critical_values"
  [[ -z "$security_posture" ]] || rm -f -- "$security_posture"
  [[ -z "$pre_state" ]] || rm -f -- "$pre_state"
  [[ -z "$post_state" ]] || rm -f -- "$post_state"
  if [[ "$result_created" == "true" && "$completed" != "true" ]]; then
    rm -f -- "$result_out"
  fi
}
trap cleanup EXIT

guard_load_bootstrap_outputs "$bootstrap_outputs"
guard_source_metadata "$repository_root"
[[ "$GUARD_SOURCE_SHA" == "$approved_source_sha" ]] || guard_die "approved source SHA does not match the checked-out source"
guard_verify_azure_context_and_boundary
guard_verify_first_state_history
expected_state_exists="$(jq -er '.prior_state.exists | booleans' "$review_path")" || guard_die "first-plan review manifest has no valid prior-state existence flag"
if [[ "$expected_state_exists" == "true" ]]; then
  guard_state_exists || guard_die "the empty remote state recorded during first planning disappeared"
else
  guard_state_exists && guard_die "remote state appeared after the first plan was reviewed"
fi
export TF_DATA_DIR="${plan_path}.terraform-data"
guard_backend_init

pre_lineage=""
pre_serial="null"
pre_state_sha256=""
if guard_state_exists; then
  [[ "$expected_state_exists" == "true" ]] || guard_die "remote state appeared during first-apply preflight"
  pre_state="$(mktemp "${TMPDIR:-/tmp}/cosmas-d3-first-pre-state.XXXXXX")"
  guard_pull_state "$pre_state"
  guard_validate_empty_environment_state "$pre_state"
  pre_lineage="$GUARD_STATE_LINEAGE"
  pre_serial="$GUARD_STATE_SERIAL"
  pre_state_sha256="$GUARD_STATE_SHA256"
else
  [[ "$expected_state_exists" == "false" ]] || guard_die "the recorded initial remote state is missing"
fi

plan_sha256="$(guard_sha256 "$plan_path")"
review_sha256="$(guard_sha256 "$review_path")"
variable_file_sha256="$(guard_sha256 "$var_file")"
jq -e \
  --arg plan_sha256 "$plan_sha256" \
  --arg source_sha "$GUARD_SOURCE_SHA" \
  --arg terraform_version "$GUARD_TERRAFORM_VERSION" \
  --arg provider_lock_sha256 "$GUARD_PROVIDER_LOCK_SHA256" \
  --arg variable_file_sha256 "$(guard_sha256 "$var_file")" \
  --argjson prior_state_exists "$expected_state_exists" \
  --arg prior_state_lineage "$pre_lineage" \
  --argjson prior_state_serial "$pre_serial" \
  --arg prior_state_sha256 "$pre_state_sha256" \
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
  --arg data_classification "$GUARD_DATA_CLASSIFICATION" '
    .schema_version == 1 and
    .phase == "first" and
    .plan_sha256 == $plan_sha256 and
    .source_sha == $source_sha and
    .terraform_version == $terraform_version and
    .provider_lock_sha256 == $provider_lock_sha256 and
    .variable_file_sha256 == $variable_file_sha256 and
    .prior_state.exists == $prior_state_exists and
    .prior_state.lineage == (if $prior_state_exists then $prior_state_lineage else null end) and
    .prior_state.serial == (if $prior_state_exists then $prior_state_serial else null end) and
    .prior_state.sha256 == (if $prior_state_exists then $prior_state_sha256 else null end) and
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
    .managed_action_counts.update == 0 and
    .managed_action_counts.delete == 0 and
    .managed_action_counts.replace == 0 and
    .managed_action_counts.no_op == 0
  ' "$review_path" >/dev/null || guard_die "first-plan review manifest does not match the exact plan and D3 boundary"

guard_validate_apply_approval "$approval_path" "$approval_bundle" "$GUARD_SOURCE_SHA" "$release_id" "$stage" \
  "$plan_sha256" "$review_sha256" "$variable_file_sha256" "$expected_state_exists" \
  "$pre_lineage" "$pre_serial" "$pre_state_sha256"

plan_json="$(mktemp "${TMPDIR:-/tmp}/cosmas-d3-first-apply-plan.XXXXXX")"
"$GUARD_TERRAFORM_BIN" -chdir="$GUARD_ENVIRONMENT_DIR" show -json "$plan_path" >"$plan_json"
chmod 600 "$plan_json"
guard_validate_planned_boundary "$plan_json"
guard_validate_safe_plan_actions "$plan_json"
(( GUARD_UPDATE_COUNT == 0 && GUARD_NOOP_COUNT == 0 )) || guard_die "first environment plan is no longer create-only"
sanitized_changes="$(mktemp "${TMPDIR:-/tmp}/cosmas-d3-first-apply-changes.XXXXXX")"
jq '[.resource_changes[]? | {address, type, mode, actions: .change.actions}]' "$plan_json" >"$sanitized_changes"
chmod 600 "$sanitized_changes"
critical_values="$(mktemp "${TMPDIR:-/tmp}/cosmas-d3-first-apply-critical-values.XXXXXX")"
guard_write_critical_planned_values "$plan_json" "$critical_values"
security_posture="$(mktemp "${TMPDIR:-/tmp}/cosmas-d3-first-apply-security-posture.XXXXXX")"
guard_write_security_posture "$plan_json" "$security_posture"
jq -e \
  --argjson create "$GUARD_CREATE_COUNT" \
  --slurpfile managed_actions "$sanitized_changes" \
  --slurpfile critical_planned_values "$critical_values" \
  --slurpfile security_posture "$security_posture" '
  .managed_action_counts.create == $create and
  .managed_action_counts.update == 0 and
  .managed_action_counts.delete == 0 and
  .managed_action_counts.replace == 0 and
  .managed_action_counts.no_op == 0 and
  .managed_actions == $managed_actions[0] and
  .critical_planned_values == $critical_planned_values[0] and
  .security_posture == $security_posture[0]
' "$review_path" >/dev/null || guard_die "first-plan review action count does not match the saved plan"
if ! jq -e '
  def module_resources(node):
    (node.resources // []) +
    ([node.child_modules[]? | module_resources(.)] | add // []);
  (module_resources(.prior_state.values.root_module) | length) == 0
' "$plan_json" >/dev/null; then
  guard_die "first plan unexpectedly contains prior managed state"
fi

# Re-read the live region/boundary and every authorization expiry at the last
# possible point before the only mutation in this wrapper.
guard_verify_azure_context_and_boundary
guard_validate_apply_approval "$approval_path" "$approval_bundle" "$GUARD_SOURCE_SHA" "$release_id" "$stage" \
  "$plan_sha256" "$review_sha256" "$variable_file_sha256" "$expected_state_exists" \
  "$pre_lineage" "$pre_serial" "$pre_state_sha256"
guard_claim_apply_attempt "$attempt_claim" "$GUARD_SOURCE_SHA" "$release_id" "$stage" \
  "$plan_sha256" "$(guard_sha256 "$approval_path")" "$(jq -er '.authorization_claim_sha256' "$approval_path")" \
  "causal-bundle-claim"
guard_validate_apply_approval "$approval_path" "$approval_bundle" "$GUARD_SOURCE_SHA" "$release_id" "$stage" \
  "$plan_sha256" "$review_sha256" "$variable_file_sha256" "$expected_state_exists" \
  "$pre_lineage" "$pre_serial" "$pre_state_sha256"
"$GUARD_TERRAFORM_BIN" -chdir="$GUARD_ENVIRONMENT_DIR" apply -input=false "$plan_path"

post_state="$(mktemp "${TMPDIR:-/tmp}/cosmas-d3-first-post-state.XXXXXX")"
guard_pull_state "$post_state"
guard_validate_environment_state "$post_state"
post_lineage="$GUARD_STATE_LINEAGE"
post_serial="$GUARD_STATE_SERIAL"
post_state_sha256="$GUARD_STATE_SHA256"
if [[ "$expected_state_exists" == "true" ]]; then
  [[ "$post_lineage" == "$pre_lineage" ]] || guard_die "remote state lineage changed during first apply"
  (( post_serial > pre_serial )) || guard_die "remote state serial did not advance after the first changing plan"
else
  (( post_serial > 0 )) || guard_die "first environment apply did not create a positive state serial"
fi
guard_verify_azure_context_and_boundary

reviewer="$(jq -er '.reviewer' "$approval_path")"
review_reference="$(jq -er '.review_reference' "$approval_path")"
result_created=true
jq -n \
  --arg applied_at "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
  --arg plan_sha256 "$plan_sha256" \
  --arg lineage "$post_lineage" \
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
      phase: "first",
      applied_at: $applied_at,
      plan_sha256: $plan_sha256,
      state: {
        lineage: $lineage,
        pre_serial: $pre_serial,
        post_serial: $post_serial,
        pre_sha256: (if $pre_serial == null then null else $pre_state_sha256 end),
        post_sha256: $post_state_sha256
      },
      approval: {reviewer: $reviewer, review_reference: $review_reference},
      boundary: {box_id: $box_id, deployment_mode: $deployment_mode}
    }
  ' >"$result_out"
chmod 600 "$result_out"
completed=true

printf 'D3 guarded first apply completed: plan SHA-256 %s; state %s serial %s\n' \
  "$plan_sha256" "$post_lineage" "$post_serial"
