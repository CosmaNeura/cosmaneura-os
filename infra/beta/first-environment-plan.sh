#!/usr/bin/env bash
set -euo pipefail

umask 077

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repository_root="$(cd -- "$script_dir/../.." && pwd -P)"
GUARD_ENVIRONMENT_DIR="$script_dir/environment"
# shellcheck source=deployment-guard-lib.sh
source "$script_dir/deployment-guard-lib.sh"

usage() {
  printf '%s\n' \
    "Usage: $0 --bootstrap-outputs PATH --var-file PATH --plan-out PATH --review-out PATH" \
    "" \
    "Creates the first D3 environment plan only. It derives the backend, mode," \
    "and exact Box UUID from protected bootstrap outputs; verifies the Azure" \
    "identity and resource-group boundary; and refuses existing remote state."
}

bootstrap_outputs=""
var_file=""
plan_out=""
review_out=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --bootstrap-outputs)
      [[ $# -ge 2 ]] || guard_die "--bootstrap-outputs requires a path"
      bootstrap_outputs="$2"
      shift 2
      ;;
    --var-file)
      [[ $# -ge 2 ]] || guard_die "--var-file requires a path"
      var_file="$2"
      shift 2
      ;;
    --plan-out)
      [[ $# -ge 2 ]] || guard_die "--plan-out requires a path"
      plan_out="$2"
      shift 2
      ;;
    --review-out)
      [[ $# -ge 2 ]] || guard_die "--review-out requires a path"
      review_out="$2"
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
[[ -n "$var_file" ]] || guard_die "--var-file is required"
[[ -n "$plan_out" ]] || guard_die "--plan-out is required"
[[ -n "$review_out" ]] || guard_die "--review-out is required"

for command_name in az jq stat; do
  command -v "$command_name" >/dev/null 2>&1 || guard_die "$command_name is required"
done
guard_find_terraform

bootstrap_outputs="$(guard_absolute_path "$bootstrap_outputs")"
var_file="$(guard_absolute_path "$var_file")"
plan_out="$(guard_absolute_path "$plan_out")"
review_out="$(guard_absolute_path "$review_out")"
guard_outside_repository "$bootstrap_outputs" "$repository_root" "bootstrap output JSON"
guard_outside_repository "$var_file" "$repository_root" "environment variable file"
guard_outside_repository "$plan_out" "$repository_root" "plan output"
guard_outside_repository "$review_out" "$repository_root" "review manifest"
guard_private_file "$bootstrap_outputs" "bootstrap output JSON"
guard_private_file "$var_file" "environment variable file"
guard_new_private_path "$plan_out" "plan output"
guard_new_private_path "$review_out" "review manifest"

plan_json=""
initial_state=""
sanitized_changes=""
critical_values=""
security_posture=""
plan_created=false
plan_accepted=false
review_created=false
cleanup() {
  [[ -z "$plan_json" ]] || rm -f -- "$plan_json"
  [[ -z "$initial_state" ]] || rm -f -- "$initial_state"
  [[ -z "$sanitized_changes" ]] || rm -f -- "$sanitized_changes"
  [[ -z "$critical_values" ]] || rm -f -- "$critical_values"
  [[ -z "$security_posture" ]] || rm -f -- "$security_posture"
  if [[ "$plan_created" == "true" && "$plan_accepted" != "true" ]]; then
    rm -f -- "$plan_out"
  fi
  if [[ "$review_created" == "true" && "$plan_accepted" != "true" ]]; then
    rm -f -- "$review_out"
  fi
}
trap cleanup EXIT

guard_load_bootstrap_outputs "$bootstrap_outputs"
guard_source_metadata "$repository_root"
guard_verify_azure_context_and_boundary
guard_verify_first_state_history
if guard_state_exists; then
  guard_remove_zero_length_unlocked_state_stub
fi

# Keep backend metadata and provider scratch data alongside the protected plan,
# never in the source checkout.
export TF_DATA_DIR="${plan_out}.terraform-data"
guard_backend_init
if guard_state_exists; then
  guard_die "remote state appeared during initialization; refusing to plan"
fi

plan_created=true
"$GUARD_TERRAFORM_BIN" -chdir="$GUARD_ENVIRONMENT_DIR" plan \
  -input=false \
  -var-file="$var_file" \
  -var="subscription_id=$GUARD_SUBSCRIPTION_ID" \
  -var="tenant_id=$GUARD_TENANT_ID" \
  -var="beta_id=$GUARD_BETA_ID" \
  -var="box_id=$GUARD_BOX_ID" \
  -var="state_vnet_id=$GUARD_STATE_VNET_ID" \
  -var="state_blob_private_dns_zone_id=$GUARD_STATE_BLOB_PRIVATE_DNS_ZONE_ID" \
  -var="deployment_mode=$GUARD_DEPLOYMENT_MODE" \
  -var="enable_database_preparation_job=false" \
  -var="deploy_workloads=false" \
  -out="$plan_out"
chmod 600 "$plan_out"

plan_json="$(mktemp "${TMPDIR:-/tmp}/cosmas-d3-first-plan.XXXXXX")"
"$GUARD_TERRAFORM_BIN" -chdir="$GUARD_ENVIRONMENT_DIR" show -json "$plan_out" >"$plan_json"
chmod 600 "$plan_json"

if ! jq -e '
  def module_resources(node):
    (node.resources // []) +
    ([node.child_modules[]? | module_resources(.)] | add // []);
  (module_resources(.prior_state.values.root_module) | length) == 0
' "$plan_json" >/dev/null; then
  guard_die "saved first plan contains prior managed state"
fi
guard_validate_planned_boundary "$plan_json"
guard_validate_safe_plan_actions "$plan_json"
(( GUARD_UPDATE_COUNT == 0 && GUARD_NOOP_COUNT == 0 )) || guard_die "first environment plan contains a managed action other than create"

if guard_state_exists; then
  # AzureRM backend locking creates a zero-byte blob on the first plan but does
  # not persist canonical state. Delete only that exact unlocked ETag so apply
  # can still bind to a truly absent prior state.
  guard_remove_zero_length_unlocked_state_stub
fi
guard_verify_first_state_history
prior_state_exists=false
prior_state_lineage=""
prior_state_serial="null"
prior_state_sha256=""

plan_hash="$(guard_sha256 "$plan_out")"
generated_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
sanitized_changes="$(mktemp "${TMPDIR:-/tmp}/cosmas-d3-first-changes.XXXXXX")"
jq '[.resource_changes[]? | {address, type, mode, actions: .change.actions}]' "$plan_json" >"$sanitized_changes"
chmod 600 "$sanitized_changes"
critical_values="$(mktemp "${TMPDIR:-/tmp}/cosmas-d3-first-critical-values.XXXXXX")"
guard_write_critical_planned_values "$plan_json" "$critical_values"
security_posture="$(mktemp "${TMPDIR:-/tmp}/cosmas-d3-first-security-posture.XXXXXX")"
guard_write_security_posture "$plan_json" "$security_posture"
review_created=true
jq -n \
  --arg generated_at "$generated_at" \
  --arg plan_sha256 "$plan_hash" \
  --arg source_sha "$GUARD_SOURCE_SHA" \
  --arg terraform_version "$GUARD_TERRAFORM_VERSION" \
  --arg provider_lock_sha256 "$GUARD_PROVIDER_LOCK_SHA256" \
  --arg variable_file_sha256 "$(guard_sha256 "$var_file")" \
  --slurpfile managed_actions "$sanitized_changes" \
  --slurpfile critical_planned_values "$critical_values" \
  --slurpfile security_posture "$security_posture" \
  --argjson prior_state_exists "$prior_state_exists" \
  --arg prior_state_lineage "$prior_state_lineage" \
  --argjson prior_state_serial "$prior_state_serial" \
  --arg prior_state_sha256 "$prior_state_sha256" \
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
  --argjson create "$GUARD_CREATE_COUNT" '
    {
      schema_version: 1,
      phase: "first",
      generated_at: $generated_at,
      plan_sha256: $plan_sha256,
      source_sha: $source_sha,
      terraform_version: $terraform_version,
      provider_lock_sha256: $provider_lock_sha256,
      variable_file_sha256: $variable_file_sha256,
      prior_state: {
        exists: $prior_state_exists,
        lineage: (if $prior_state_exists then $prior_state_lineage else null end),
        serial: (if $prior_state_exists then $prior_state_serial else null end),
        sha256: (if $prior_state_exists then $prior_state_sha256 else null end)
      },
      boundary: {
        subscription_id: $subscription_id,
        tenant_id: $tenant_id,
        deploy_identity_client_id: $deploy_identity_client_id,
        beta_id: $beta_id,
        box_id: $box_id,
        state_resource_group: $state_resource_group,
        workload_resource_group: $workload_resource_group,
        state_vnet_id: $state_vnet_id,
        state_blob_private_dns_zone_id: $state_blob_private_dns_zone_id,
        deployment_mode: $deployment_mode,
        data_classification: $data_classification
      },
      managed_action_counts: {
        create: $create,
        update: 0,
        delete: 0,
        replace: 0,
        no_op: 0
      },
      managed_actions: $managed_actions[0],
      critical_planned_values: $critical_planned_values[0],
      security_posture: $security_posture[0]
    }
  ' >"$review_out"
chmod 600 "$review_out"
plan_accepted=true
printf 'D3 first-plan guard passed: %s managed creates; plan SHA-256 %s\n' "$GUARD_CREATE_COUNT" "$plan_hash"
