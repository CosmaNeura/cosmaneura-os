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
    "Usage: $0 --bootstrap-outputs PATH --var-file PATH --plan-out PATH --review-out PATH [--allow-partial-foundation]" \
    "" \
    "Creates a non-initial D3 plan and a sanitized review manifest. The exact" \
    "remote-state lineage/serial, Box, mode, resource groups, subscription," \
    "tenant, and dedicated deploy identity are verified before planning."
}

bootstrap_outputs=""
var_file=""
plan_out=""
review_out=""
allow_partial_foundation=false

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
    --allow-partial-foundation)
      allow_partial_foundation=true
      shift
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

pre_state=""
post_plan_state=""
plan_json=""
sanitized_changes=""
critical_values=""
security_posture=""
plan_created=false
review_created=false
accepted=false
cleanup() {
  [[ -z "$pre_state" ]] || rm -f -- "$pre_state"
  [[ -z "$post_plan_state" ]] || rm -f -- "$post_plan_state"
  [[ -z "$plan_json" ]] || rm -f -- "$plan_json"
  [[ -z "$sanitized_changes" ]] || rm -f -- "$sanitized_changes"
  [[ -z "$critical_values" ]] || rm -f -- "$critical_values"
  [[ -z "$security_posture" ]] || rm -f -- "$security_posture"
  if [[ "$accepted" != "true" ]]; then
    [[ "$plan_created" != "true" ]] || rm -f -- "$plan_out"
    [[ "$review_created" != "true" ]] || rm -f -- "$review_out"
  fi
}
trap cleanup EXIT

guard_load_bootstrap_outputs "$bootstrap_outputs"
guard_source_metadata "$repository_root"
guard_verify_azure_context_and_boundary
guard_state_exists || guard_die "remote state does not exist; use the first-environment plan path"

export TF_DATA_DIR="${plan_out}.terraform-data"
guard_backend_init

pre_state="$(mktemp "${TMPDIR:-/tmp}/cosmas-d3-pre-plan-state.XXXXXX")"
guard_pull_state "$pre_state"
if [[ "$allow_partial_foundation" == "true" ]]; then
  guard_validate_environment_state "$pre_state" partial_foundation
  review_phase="foundation_reconcile"
else
  guard_validate_environment_state "$pre_state"
  review_phase="subsequent"
fi
pre_lineage="$GUARD_STATE_LINEAGE"
pre_serial="$GUARD_STATE_SERIAL"
pre_state_sha256="$GUARD_STATE_SHA256"

plan_created=true
plan_arguments=(
  -input=false
  -var-file="$var_file"
  -var="subscription_id=$GUARD_SUBSCRIPTION_ID"
  -var="tenant_id=$GUARD_TENANT_ID"
  -var="beta_id=$GUARD_BETA_ID"
  -var="box_id=$GUARD_BOX_ID"
  -var="state_vnet_id=$GUARD_STATE_VNET_ID"
  -var="state_blob_private_dns_zone_id=$GUARD_STATE_BLOB_PRIVATE_DNS_ZONE_ID"
  -var="deployment_mode=$GUARD_DEPLOYMENT_MODE"
  -out="$plan_out"
)
if [[ "$allow_partial_foundation" == "true" ]]; then
  plan_arguments+=(
    -var="enable_database_preparation_job=false"
    -var="deploy_workloads=false"
  )
fi
"$GUARD_TERRAFORM_BIN" -chdir="$GUARD_ENVIRONMENT_DIR" plan "${plan_arguments[@]}"
chmod 600 "$plan_out"

plan_json="$(mktemp "${TMPDIR:-/tmp}/cosmas-d3-subsequent-plan.XXXXXX")"
"$GUARD_TERRAFORM_BIN" -chdir="$GUARD_ENVIRONMENT_DIR" show -json "$plan_out" >"$plan_json"
chmod 600 "$plan_json"
guard_validate_planned_boundary "$plan_json"
guard_validate_safe_plan_actions "$plan_json" true
if [[ "$allow_partial_foundation" == "true" ]]; then
  jq -e \
    --arg box "$GUARD_BOX_ID" \
    --arg mode "$GUARD_DEPLOYMENT_MODE" \
    --arg classification "$GUARD_DATA_CLASSIFICATION" \
    --arg resource_group "$GUARD_WORKLOAD_RESOURCE_GROUP" \
    --arg state_vnet_id "$GUARD_STATE_VNET_ID" \
    --arg state_blob_private_dns_zone_id "$GUARD_STATE_BLOB_PRIVATE_DNS_ZONE_ID" '
      (.prior_state.values.outputs // {}) as $outputs |
      ((($outputs | has("box_id")) | not) or $outputs.box_id.value == $box) and
      ((($outputs | has("environment")) | not) or $outputs.environment.value == "early_adopter_beta") and
      ((($outputs | has("deployment_mode")) | not) or $outputs.deployment_mode.value == $mode) and
      ((($outputs | has("data_classification")) | not) or $outputs.data_classification.value == $classification) and
      ((($outputs | has("resource_group_name")) | not) or $outputs.resource_group_name.value == $resource_group) and
      ((($outputs | has("state_vnet_id")) | not) or $outputs.state_vnet_id.value == $state_vnet_id) and
      ((($outputs | has("state_blob_private_dns_zone_id")) | not) or $outputs.state_blob_private_dns_zone_id.value == $state_blob_private_dns_zone_id)
    ' "$plan_json" >/dev/null || guard_die "saved partial foundation state contains a conflicting D3 boundary output"
else
  jq -e \
    --arg box "$GUARD_BOX_ID" \
    --arg mode "$GUARD_DEPLOYMENT_MODE" \
    --arg classification "$GUARD_DATA_CLASSIFICATION" \
    --arg resource_group "$GUARD_WORKLOAD_RESOURCE_GROUP" \
    --arg state_vnet_id "$GUARD_STATE_VNET_ID" \
    --arg state_blob_private_dns_zone_id "$GUARD_STATE_BLOB_PRIVATE_DNS_ZONE_ID" '
      .prior_state.values.outputs.box_id.value == $box and
      .prior_state.values.outputs.environment.value == "early_adopter_beta" and
      .prior_state.values.outputs.deployment_mode.value == $mode and
      .prior_state.values.outputs.data_classification.value == $classification and
      .prior_state.values.outputs.resource_group_name.value == $resource_group and
      .prior_state.values.outputs.state_vnet_id.value == $state_vnet_id and
      .prior_state.values.outputs.state_blob_private_dns_zone_id.value == $state_blob_private_dns_zone_id
    ' "$plan_json" >/dev/null || guard_die "saved plan prior state does not match the exact D3 mode/Box boundary"
fi

# A plan does not mutate state. Re-pull after planning and discard the saved
# plan if another actor changed lineage or serial while the wrapper was open.
post_plan_state="$(mktemp "${TMPDIR:-/tmp}/cosmas-d3-post-plan-state.XXXXXX")"
guard_pull_state "$post_plan_state"
if [[ "$allow_partial_foundation" == "true" ]]; then
  guard_validate_environment_state "$post_plan_state" partial_foundation
else
  guard_validate_environment_state "$post_plan_state"
fi
[[ "$GUARD_STATE_LINEAGE" == "$pre_lineage" && "$GUARD_STATE_SERIAL" == "$pre_serial" ]] || guard_die "remote state changed while planning; discard this stale plan"

plan_sha256="$(guard_sha256 "$plan_out")"
generated_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
sanitized_changes="$(mktemp "${TMPDIR:-/tmp}/cosmas-d3-subsequent-changes.XXXXXX")"
jq '[.resource_changes[]? | {address, type, mode, actions: .change.actions}]' "$plan_json" >"$sanitized_changes"
chmod 600 "$sanitized_changes"
critical_values="$(mktemp "${TMPDIR:-/tmp}/cosmas-d3-subsequent-critical-values.XXXXXX")"
guard_write_critical_planned_values "$plan_json" "$critical_values"
security_posture="$(mktemp "${TMPDIR:-/tmp}/cosmas-d3-subsequent-security-posture.XXXXXX")"
guard_write_security_posture "$plan_json" "$security_posture"
review_created=true
jq -n \
  --arg generated_at "$generated_at" \
  --arg plan_sha256 "$plan_sha256" \
  --arg source_sha "$GUARD_SOURCE_SHA" \
  --arg terraform_version "$GUARD_TERRAFORM_VERSION" \
  --arg provider_lock_sha256 "$GUARD_PROVIDER_LOCK_SHA256" \
  --arg variable_file_sha256 "$(guard_sha256 "$var_file")" \
  --slurpfile managed_actions "$sanitized_changes" \
  --slurpfile critical_planned_values "$critical_values" \
  --slurpfile security_posture "$security_posture" \
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
  --arg review_phase "$review_phase" \
  --argjson create "$GUARD_CREATE_COUNT" \
  --argjson update "$GUARD_UPDATE_COUNT" \
  --argjson no_op "$GUARD_NOOP_COUNT" '
    {
      schema_version: 1,
      phase: $review_phase,
      generated_at: $generated_at,
      plan_sha256: $plan_sha256,
      source_sha: $source_sha,
      terraform_version: $terraform_version,
      provider_lock_sha256: $provider_lock_sha256,
      variable_file_sha256: $variable_file_sha256,
      prior_state: {
        lineage: $lineage,
        serial: $serial,
        sha256: $state_sha256
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
        update: $update,
        delete: 0,
        replace: 0,
        no_op: $no_op
      },
      managed_actions: $managed_actions[0],
      critical_planned_values: $critical_planned_values[0],
      security_posture: $security_posture[0]
    }
  ' >"$review_out"
chmod 600 "$review_out"
accepted=true

printf 'D3 subsequent-plan guard passed: %s create, %s update, 0 delete/replace; plan SHA-256 %s; prior state %s/%s\n' \
  "$GUARD_CREATE_COUNT" "$GUARD_UPDATE_COUNT" "$plan_sha256" "$pre_lineage" "$pre_serial"
