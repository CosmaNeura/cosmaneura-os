#!/usr/bin/env bash
set -euo pipefail

umask 077

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repository_root="$(cd -- "$script_dir/../.." && pwd -P)"
bootstrap_dir="$script_dir/bootstrap"
# shellcheck source=deployment-guard-lib.sh
source "$script_dir/deployment-guard-lib.sh"

usage() {
  printf '%s\n' \
    "Usage:" \
    "  $0 plan --state PATH --var-file PATH --plan-out PATH --review-out PATH" \
    "  $0 apply --state PATH --var-file PATH --plan PATH --review PATH --approval PATH" \
    "  $0 outputs --state PATH --output PATH" \
    "" \
    "Bootstrap state and artifacts must be in private paths outside the repo." \
    "Plan creates a strict non-secret before/after security review. Apply requires" \
    "a named human approval bound to that review, plan, source, tool, and lock."
}

[[ $# -gt 0 ]] || {
  usage >&2
  exit 1
}
operation="$1"
shift

state_path=""
var_file=""
plan_path=""
review_path=""
approval_path=""
output_path=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --state) state_path="${2:-}"; shift 2 ;;
    --var-file) var_file="${2:-}"; shift 2 ;;
    --plan-out|--plan) plan_path="${2:-}"; shift 2 ;;
    --review-out|--review) review_path="${2:-}"; shift 2 ;;
    --approval) approval_path="${2:-}"; shift 2 ;;
    --output) output_path="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) guard_die "unknown argument: $1" ;;
  esac
done

[[ "$operation" == "plan" || "$operation" == "apply" || "$operation" == "outputs" ]] || guard_die "operation must be plan, apply, or outputs"
[[ -n "$state_path" ]] || guard_die "--state is required"
for command_name in jq stat git; do
  command -v "$command_name" >/dev/null 2>&1 || guard_die "$command_name is required"
done
guard_find_terraform
guard_source_metadata "$repository_root" "$bootstrap_dir"

state_path="$(guard_absolute_path "$state_path")"
guard_outside_repository "$state_path" "$repository_root" "bootstrap state"
guard_private_directory "$(dirname -- "$state_path")" "bootstrap state directory"
[[ ! -L "$state_path" ]] || guard_die "bootstrap state must not be a symlink"
export TF_DATA_DIR="${state_path}.terraform-data"

plan_json=""
sanitized_changes=""
security_posture=""
review_created=false
accepted=false
PRIOR_STATE_EXISTS=false
PRIOR_STATE_LINEAGE=""
PRIOR_STATE_SERIAL="null"
PRIOR_STATE_SHA256=""
cleanup() {
  [[ -z "$plan_json" ]] || rm -f -- "$plan_json"
  [[ -z "$sanitized_changes" ]] || rm -f -- "$sanitized_changes"
  [[ -z "$security_posture" ]] || rm -f -- "$security_posture"
  if [[ "$review_created" == "true" && "$accepted" != "true" ]]; then
    rm -f -- "$review_path"
  fi
}
trap cleanup EXIT

initialize_bootstrap() {
  "$GUARD_TERRAFORM_BIN" -chdir="$bootstrap_dir" init \
    -backend=false \
    -input=false \
    -lockfile=readonly
  [[ "$("$GUARD_TERRAFORM_BIN" -chdir="$bootstrap_dir" workspace show)" == "default" ]] || guard_die "guarded bootstrap requires the default workspace"
}

load_local_state_binding() {
  local inspected_state="$1"
  local inspected_var_file="$2"
  local subscription_id
  local beta_id
  local state_rg
  local workload_rg

  PRIOR_STATE_EXISTS=false
  PRIOR_STATE_LINEAGE=""
  PRIOR_STATE_SERIAL="null"
  PRIOR_STATE_SHA256=""
  [[ -e "$inspected_state" ]] || return 0
  guard_private_file "$inspected_state" "bootstrap state"
  jq -e '
    .version == 4 and
    (.lineage | strings | test("^[0-9a-fA-F-]{36}$")) and
    (.serial | numbers | floor == . and . >= 0) and
    (.resources | type == "array")
  ' "$inspected_state" >/dev/null || guard_die "existing bootstrap state is not a canonical version-4 state"
  subscription_id="$(jq -er '.subscription_id | strings | ascii_downcase' "$inspected_var_file")" || guard_die "bootstrap variable file lacks subscription_id"
  beta_id="$(jq -er '.beta_id | strings' "$inspected_var_file")" || guard_die "bootstrap variable file lacks beta_id"
  [[ "$subscription_id" =~ ^[0-9a-f-]{36}$ && "$beta_id" =~ ^[a-z0-9][a-z0-9-]{1,8}[a-z0-9]$ ]] || guard_die "bootstrap variable file boundary is invalid"
  state_rg="/subscriptions/$subscription_id/resourcegroups/rg-cosmas-os-beta-state-$beta_id"
  workload_rg="/subscriptions/$subscription_id/resourcegroups/rg-cosmas-os-beta-$beta_id"
  jq -e \
    --arg subscription "/subscriptions/$subscription_id" \
    --arg state_rg "$state_rg" \
    --arg workload_rg "$workload_rg" '
      [
        .resources[]?
        | select(.mode == "managed" and (.type | startswith("azurerm_")))
        | .instances[]?.attributes.id?
        | select(type == "string" and startswith("/"))
        | ascii_downcase
      ]
      | all(
          . == $state_rg or . == $workload_rg or
          startswith($state_rg + "/") or startswith($workload_rg + "/") or
          startswith($subscription + "/providers/microsoft.consumption/budgets/budget-cosmas-os-beta-")
        )
    ' "$inspected_state" >/dev/null || guard_die "existing bootstrap state contains an Azure resource outside the exact D3 boundary"
  PRIOR_STATE_EXISTS=true
  PRIOR_STATE_LINEAGE="$(jq -er '.lineage' "$inspected_state")"
  PRIOR_STATE_SERIAL="$(jq -er '.serial' "$inspected_state")"
  PRIOR_STATE_SHA256="$(guard_sha256 "$inspected_state")"
}

inspect_bootstrap_plan() {
  local inspected_plan="$1"
  plan_json="$(mktemp "${TMPDIR:-/tmp}/cosmas-d3-bootstrap-plan.XXXXXX")"
  "$GUARD_TERRAFORM_BIN" -chdir="$bootstrap_dir" show -json "$inspected_plan" >"$plan_json"
  chmod 600 "$plan_json"

  jq -e '
    .planned_values.outputs.box_id.value
      | strings
      | test("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$")
  ' "$plan_json" >/dev/null || guard_die "bootstrap plan does not expose an exact Box UUID"
  jq -e '
    (.planned_values.outputs.deployment_mode.value == "synthetic_lab" and
      .planned_values.outputs.data_classification.value == "synthetic-only") or
    (.planned_values.outputs.deployment_mode.value == "authorized_beta" and
      .planned_values.outputs.data_classification.value == "phi-authorized")
  ' "$plan_json" >/dev/null || guard_die "bootstrap plan has an invalid deployment mode/classification pair"
  jq -e '
    (.planned_values.outputs.subscription_id.value | strings | test("^[0-9a-fA-F-]{36}$")) and
    (.planned_values.outputs.tenant_id.value | strings | test("^[0-9a-fA-F-]{36}$")) and
    (.planned_values.outputs.backend_key.value | strings | test("^early-adopter-beta/[a-z0-9][a-z0-9-]{1,8}[a-z0-9]/terraform\\.tfstate$"))
  ' "$plan_json" >/dev/null || guard_die "bootstrap plan has an invalid subscription, tenant, or backend boundary"
  if ! jq -e '
    [.resource_changes[]?
      | select(.mode == "managed")
      | .change.actions
      | select(. != ["create"] and . != ["update"] and . != ["no-op"])]
    | length == 0
  ' "$plan_json" >/dev/null; then
    guard_die "bootstrap plan contains a delete, replacement, forget, or unsupported managed action"
  fi
  BOOTSTRAP_CREATE_COUNT="$(jq '[.resource_changes[]? | select(.mode == "managed" and .change.actions == ["create"])] | length' "$plan_json")"
  BOOTSTRAP_UPDATE_COUNT="$(jq '[.resource_changes[]? | select(.mode == "managed" and .change.actions == ["update"])] | length' "$plan_json")"
  BOOTSTRAP_NOOP_COUNT="$(jq '[.resource_changes[]? | select(.mode == "managed" and .change.actions == ["no-op"])] | length' "$plan_json")"
  if [[ "$PRIOR_STATE_EXISTS" == "false" ]]; then
    (( BOOTSTRAP_CREATE_COUNT > 0 && BOOTSTRAP_UPDATE_COUNT == 0 && BOOTSTRAP_NOOP_COUNT == 0 )) || guard_die "new bootstrap plan is not create-only"
  fi
}

write_review_manifest() {
  local inspected_var_file="$1"
  local plan_sha256
  local generated_at

  plan_sha256="$(guard_sha256 "$plan_path")"
  generated_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  sanitized_changes="$(mktemp "${TMPDIR:-/tmp}/cosmas-d3-bootstrap-changes.XXXXXX")"
  jq '[.resource_changes[]? | select(.mode == "managed") | {address, type, mode, actions: .change.actions}]' "$plan_json" >"$sanitized_changes"
  chmod 600 "$sanitized_changes"
  security_posture="$(mktemp "${TMPDIR:-/tmp}/cosmas-d3-bootstrap-security-posture.XXXXXX")"
  guard_write_security_posture "$plan_json" "$security_posture"
  review_created=true
  jq -n \
    --arg generated_at "$generated_at" \
    --arg plan_sha256 "$plan_sha256" \
    --arg source_sha "$GUARD_SOURCE_SHA" \
    --arg terraform_version "$GUARD_TERRAFORM_VERSION" \
    --arg provider_lock_sha256 "$GUARD_PROVIDER_LOCK_SHA256" \
    --arg variable_file_sha256 "$(guard_sha256 "$inspected_var_file")" \
    --arg subscription_id "$(jq -er '.planned_values.outputs.subscription_id.value' "$plan_json")" \
    --arg tenant_id "$(jq -er '.planned_values.outputs.tenant_id.value' "$plan_json")" \
    --arg box_id "$(jq -er '.planned_values.outputs.box_id.value' "$plan_json")" \
    --arg deployment_mode "$(jq -er '.planned_values.outputs.deployment_mode.value' "$plan_json")" \
    --arg data_classification "$(jq -er '.planned_values.outputs.data_classification.value' "$plan_json")" \
    --arg backend_key "$(jq -er '.planned_values.outputs.backend_key.value' "$plan_json")" \
    --arg state_resource_group "$(jq -er '.planned_values.outputs.backend_resource_group_name.value' "$plan_json")" \
    --arg workload_resource_group "$(jq -er '.planned_values.outputs.workload_resource_group_name.value' "$plan_json")" \
    --argjson create "$BOOTSTRAP_CREATE_COUNT" \
    --argjson update "$BOOTSTRAP_UPDATE_COUNT" \
    --argjson no_op "$BOOTSTRAP_NOOP_COUNT" \
    --argjson prior_state_exists "$PRIOR_STATE_EXISTS" \
    --arg prior_state_lineage "$PRIOR_STATE_LINEAGE" \
    --argjson prior_state_serial "$PRIOR_STATE_SERIAL" \
    --arg prior_state_sha256 "$PRIOR_STATE_SHA256" \
    --slurpfile managed_actions "$sanitized_changes" \
    --slurpfile security_posture "$security_posture" '
      {
        schema_version: 1,
        phase: "bootstrap",
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
          box_id: $box_id,
          deployment_mode: $deployment_mode,
          data_classification: $data_classification,
          backend_key: $backend_key,
          state_resource_group: $state_resource_group,
          workload_resource_group: $workload_resource_group
        },
        managed_action_counts: {create: $create, update: $update, delete: 0, replace: 0, no_op: $no_op},
        managed_actions: $managed_actions[0],
        security_posture: $security_posture[0]
      }
    ' >"$review_path"
  chmod 600 "$review_path"
}

validate_review_and_approval() {
  local plan_sha256
  local review_sha256

  plan_sha256="$(guard_sha256 "$plan_path")"
  review_sha256="$(guard_sha256 "$review_path")"
  sanitized_changes="$(mktemp "${TMPDIR:-/tmp}/cosmas-d3-bootstrap-apply-changes.XXXXXX")"
  jq '[.resource_changes[]? | select(.mode == "managed") | {address, type, mode, actions: .change.actions}]' "$plan_json" >"$sanitized_changes"
  chmod 600 "$sanitized_changes"
  security_posture="$(mktemp "${TMPDIR:-/tmp}/cosmas-d3-bootstrap-apply-security-posture.XXXXXX")"
  guard_write_security_posture "$plan_json" "$security_posture"
  jq -e \
    --arg plan_sha256 "$plan_sha256" \
    --arg source_sha "$GUARD_SOURCE_SHA" \
    --arg terraform_version "$GUARD_TERRAFORM_VERSION" \
    --arg provider_lock_sha256 "$GUARD_PROVIDER_LOCK_SHA256" \
    --arg variable_file_sha256 "$(guard_sha256 "$var_file")" \
    --arg subscription_id "$(jq -er '.planned_values.outputs.subscription_id.value' "$plan_json")" \
    --arg tenant_id "$(jq -er '.planned_values.outputs.tenant_id.value' "$plan_json")" \
    --arg box_id "$(jq -er '.planned_values.outputs.box_id.value' "$plan_json")" \
    --arg deployment_mode "$(jq -er '.planned_values.outputs.deployment_mode.value' "$plan_json")" \
    --arg data_classification "$(jq -er '.planned_values.outputs.data_classification.value' "$plan_json")" \
    --arg backend_key "$(jq -er '.planned_values.outputs.backend_key.value' "$plan_json")" \
    --arg state_resource_group "$(jq -er '.planned_values.outputs.backend_resource_group_name.value' "$plan_json")" \
    --arg workload_resource_group "$(jq -er '.planned_values.outputs.workload_resource_group_name.value' "$plan_json")" \
    --argjson create "$BOOTSTRAP_CREATE_COUNT" \
    --argjson update "$BOOTSTRAP_UPDATE_COUNT" \
    --argjson no_op "$BOOTSTRAP_NOOP_COUNT" \
    --argjson prior_state_exists "$PRIOR_STATE_EXISTS" \
    --arg prior_state_lineage "$PRIOR_STATE_LINEAGE" \
    --argjson prior_state_serial "$PRIOR_STATE_SERIAL" \
    --arg prior_state_sha256 "$PRIOR_STATE_SHA256" \
    --slurpfile managed_actions "$sanitized_changes" \
    --slurpfile security_posture "$security_posture" '
      .schema_version == 1 and .phase == "bootstrap" and
      .plan_sha256 == $plan_sha256 and .source_sha == $source_sha and
      .terraform_version == $terraform_version and .provider_lock_sha256 == $provider_lock_sha256 and
      .variable_file_sha256 == $variable_file_sha256 and
      .prior_state.exists == $prior_state_exists and
      .prior_state.lineage == (if $prior_state_exists then $prior_state_lineage else null end) and
      .prior_state.serial == (if $prior_state_exists then $prior_state_serial else null end) and
      .prior_state.sha256 == (if $prior_state_exists then $prior_state_sha256 else null end) and
      .boundary.subscription_id == $subscription_id and .boundary.tenant_id == $tenant_id and
      .boundary.box_id == $box_id and .boundary.deployment_mode == $deployment_mode and
      .boundary.data_classification == $data_classification and .boundary.backend_key == $backend_key and
      .boundary.state_resource_group == $state_resource_group and
      .boundary.workload_resource_group == $workload_resource_group and
      .managed_action_counts == {create: $create, update: $update, delete: 0, replace: 0, no_op: $no_op} and
      .managed_actions == $managed_actions[0] and
      .security_posture == $security_posture[0]
    ' "$review_path" >/dev/null || guard_die "bootstrap review does not match the exact plan, source, tool, lock, actions, and boundary"
  jq -e \
    --arg plan_sha256 "$plan_sha256" \
    --arg review_sha256 "$review_sha256" \
    --arg source_sha "$GUARD_SOURCE_SHA" '
      .schema_version == 1 and
      .plan_sha256 == $plan_sha256 and
      .review_sha256 == $review_sha256 and
      .source_sha == $source_sha and
      (.reviewer | strings | length >= 3) and
      (.review_reference | strings | length >= 3)
    ' "$approval_path" >/dev/null || guard_die "bootstrap approval does not bind a named reviewer/reference to the exact review, plan, and source"
}

case "$operation" in
  plan)
    [[ -n "$var_file" ]] || guard_die "plan requires --var-file"
    [[ -n "$plan_path" ]] || guard_die "plan requires --plan-out"
    [[ -n "$review_path" ]] || guard_die "plan requires --review-out"
    var_file="$(guard_absolute_path "$var_file")"
    plan_path="$(guard_absolute_path "$plan_path")"
    review_path="$(guard_absolute_path "$review_path")"
    for artifact in "$var_file" "$plan_path" "$review_path"; do
      guard_outside_repository "$artifact" "$repository_root" "bootstrap artifact"
    done
    guard_private_file "$var_file" "bootstrap variable file"
    jq -e 'type == "object"' "$var_file" >/dev/null || guard_die "bootstrap variable file must be a JSON object"
    guard_new_private_path "$plan_path" "bootstrap plan"
    guard_new_private_path "$review_path" "bootstrap review"
    load_local_state_binding "$state_path" "$var_file"

    initialize_bootstrap
    "$GUARD_TERRAFORM_BIN" -chdir="$bootstrap_dir" plan \
      -input=false \
      -state="$state_path" \
      -var-file="$var_file" \
      -out="$plan_path"
    chmod 600 "$plan_path"
    inspect_bootstrap_plan "$plan_path"
    if [[ "$PRIOR_STATE_EXISTS" == "true" ]]; then
      [[ "$(guard_sha256 "$state_path")" == "$PRIOR_STATE_SHA256" ]] || guard_die "bootstrap state changed while planning"
    else
      [[ ! -e "$state_path" ]] || guard_die "bootstrap state appeared while planning"
    fi
    write_review_manifest "$var_file"
    accepted=true
    printf 'D3 bootstrap plan guard passed: %s creates, %s updates, %s no-op; plan SHA-256 %s; review %s\n' \
      "$BOOTSTRAP_CREATE_COUNT" "$BOOTSTRAP_UPDATE_COUNT" "$BOOTSTRAP_NOOP_COUNT" "$(guard_sha256 "$plan_path")" "$review_path"
    ;;
  apply)
    [[ -n "$plan_path" ]] || guard_die "apply requires --plan"
    [[ -n "$var_file" ]] || guard_die "apply requires --var-file"
    [[ -n "$review_path" ]] || guard_die "apply requires --review"
    [[ -n "$approval_path" ]] || guard_die "apply requires --approval"
    plan_path="$(guard_absolute_path "$plan_path")"
    var_file="$(guard_absolute_path "$var_file")"
    review_path="$(guard_absolute_path "$review_path")"
    approval_path="$(guard_absolute_path "$approval_path")"
    for artifact in "$var_file" "$plan_path" "$review_path" "$approval_path"; do
      guard_outside_repository "$artifact" "$repository_root" "bootstrap artifact"
      guard_private_file "$artifact" "bootstrap apply artifact"
    done
    jq -e 'type == "object"' "$var_file" >/dev/null || guard_die "bootstrap variable file must be a JSON object"
    load_local_state_binding "$state_path" "$var_file"

    initialize_bootstrap
    inspect_bootstrap_plan "$plan_path"
    validate_review_and_approval
    "$GUARD_TERRAFORM_BIN" -chdir="$bootstrap_dir" apply \
      -input=false \
      -state="$state_path" \
      -state-out="$state_path" \
      -backup="${state_path}.backup" \
      "$plan_path"
    guard_private_file "$state_path" "bootstrap state"
    printf 'D3 bootstrap apply completed through explicit private state: %s\n' "$state_path"
    ;;
  outputs)
    [[ -n "$output_path" ]] || guard_die "outputs requires --output"
    output_path="$(guard_absolute_path "$output_path")"
    guard_outside_repository "$output_path" "$repository_root" "bootstrap output JSON"
    guard_private_file "$state_path" "bootstrap state"
    guard_new_private_path "$output_path" "bootstrap output JSON"
    initialize_bootstrap
    "$GUARD_TERRAFORM_BIN" -chdir="$bootstrap_dir" output -state="$state_path" -json >"$output_path"
    chmod 600 "$output_path"
    jq -e '.box_id.value | strings | length > 0' "$output_path" >/dev/null || {
      rm -f -- "$output_path"
      guard_die "bootstrap outputs are missing box_id"
    }
    printf 'D3 bootstrap outputs written to the protected path: %s\n' "$output_path"
    ;;
esac
