#!/bin/bash -p
set +x
_cosmas_wrapper_dir="$(cd -- "$(/usr/bin/dirname -- "${BASH_SOURCE[0]}")" && /bin/pwd -P)" || exit 1
# shellcheck source=local-wrapper-env.sh
. "$_cosmas_wrapper_dir/local-wrapper-env.sh"
cosmas_isolate_local_wrapper_environment "$@"
unset -f cosmas_isolate_local_wrapper_environment
unset _cosmas_wrapper_dir
set -euo pipefail

# Human-side control-plane transport for the no-inbound D3 runner. Secret
# payloads are placed only in an Azure managed Run Command protected parameter
# through an @file ARM request; they never appear in process arguments or
# command output.

umask 077
export GIT_NO_REPLACE_OBJECTS=1

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repository_root="$(cd -- "$script_dir/../.." && pwd -P)"
# shellcheck source=deployment-guard-lib.sh
source "$script_dir/deployment-guard-lib.sh"

usage() {
  printf '%s\n' \
    "Usage:" \
    "  $0 stage-source --bootstrap-outputs PATH --source-sha SHA [--prior-source-sha SHA] --deploy-key PATH --known-hosts PATH" \
    "  $0 probe-network --bootstrap-outputs PATH --source-sha SHA --release-id ID --artifact-out PATH" \
    "  $0 build-push --bootstrap-outputs PATH --source-sha SHA --release-id ID --web-build-config PATH --artifact-out PATH" \
    "  $0 database-prepare --bootstrap-outputs PATH --source-sha SHA --release-id ID --artifact-out PATH" \
    "  $0 workload-verify --bootstrap-outputs PATH --source-sha SHA --release-id ID --artifact-out PATH" \
    "  $0 runtime-acceptance --bootstrap-outputs PATH --source-sha SHA --release-id ID --acceptance-phase runtime|workflow-baseline|workflow-verify|audit-replay|purge-setup|purge-verify [--acceptance-state PATH] --artifact-out PATH" \
    "  $0 domain-verification --bootstrap-outputs PATH --source-sha SHA --release-id ID --artifact-out PATH" \
    "  $0 alert-delivery --bootstrap-outputs PATH --source-sha SHA --release-id ID --alert-phase send|confirm|inspect-intent [--alert-retry-approval PATH | --alert-test-state PATH --delivery-confirmation-reference PATH] --artifact-out PATH" \
    "  $0 pitr-freeze --bootstrap-outputs PATH --source-sha SHA --release-id ID --quiet-window-end-utc TIMESTAMP --artifact-out PATH" \
    "  $0 pitr-manifest --bootstrap-outputs PATH --source-sha SHA --release-id ID --restore-time-utc TIMESTAMP --preparer-reference PATH --artifact-out PATH" \
    "  $0 pitr-start|pitr-complete|pitr-cleanup|pitr-resume --bootstrap-outputs PATH --source-sha SHA --release-id ID --approval PATH --artifact-out PATH" \
    "  $0 release-rollback|release-forward --bootstrap-outputs PATH --source-sha SHA --release-id ID --prior-source-sha SHA --prior-release-id ID --approval PATH --artifact-out PATH" \
    "  $0 inspect-stage --bootstrap-outputs PATH --source-sha SHA --release-id ID --stage foundation|database|workloads --artifact-out PATH" \
    "  $0 stage-generation --bootstrap-outputs PATH --source-sha SHA --release-id ID --stage foundation|database|workloads --stage-transition-mode abandoned_retry|planned_workloads_progression --approval PATH --var-file PATH --artifact-out PATH" \
    "  $0 offboarding-acceptance --bootstrap-outputs PATH --source-sha SHA --release-id ID --offboarding-phase baseline|verify [--offboarding-request PATH | --offboarding-state PATH --offboarding-confirmation PATH] --artifact-out PATH" \
    "  $0 bootstrap-identity --bootstrap-outputs PATH --source-sha SHA --release-id ID --bootstrap-manifest PATH --artifact-out PATH" \
    "  $0 retrieve --bootstrap-outputs PATH --source-sha SHA --release-id ID --stage STAGE --artifact-kind review|result|network|build|database|workload|runtime|domain|alert|pitr|recovery|offboarding|identity [--acceptance-phase PHASE | --alert-phase send|confirm | --pitr-phase PHASE | --recovery-phase rollback|forward | --offboarding-phase baseline|verify] --artifact-out PATH" \
    "  $0 cleanup-commands --bootstrap-outputs PATH --source-sha SHA" \
    "  $0 stage-vars --bootstrap-outputs PATH --source-sha SHA --release-id ID --stage foundation|database|workloads --var-file PATH" \
    "  $0 plan --bootstrap-outputs PATH --source-sha SHA --release-id ID --stage foundation|database|workloads --artifact-out PATH" \
    "  $0 apply --bootstrap-outputs PATH --source-sha SHA --release-id ID --stage foundation|database|workloads --approval PATH --approval-bundle DIR --artifact-out PATH" \
    "" \
    "Source is fixed to ssh://git@ssh.github.com:443/CosmaNeura/cosmaneura-os.git." \
    "stage-source alone requires --deploy-key PATH --known-hosts PATH; later operations execute only the authenticated, remote-free resident source." \
    "Secrets use a temporary Azure managed Run Command protected parameter."
}

[[ $# -gt 0 ]] || { usage >&2; exit 1; }
operation="$1"
shift

bootstrap_outputs=""
source_sha=""
stage=""
release_id=""
deploy_key=""
known_hosts=""
var_file=""
web_build_config=""
bootstrap_manifest=""
approval_file=""
approval_bundle=""
artifact_out=""
artifact_staging=""
artifact_kind=""
acceptance_phase=""
acceptance_state=""
alert_phase=""
alert_test_state=""
alert_retry_approval=""
delivery_confirmation_reference=""
pitr_phase=""
restore_time_utc=""
quiet_window_end_utc=""
pitr_preparer_reference=""
prior_source_sha=""
prior_release_id=""
recovery_phase=""
stage_transition_mode=""
offboarding_phase=""
offboarding_request=""
offboarding_state=""
offboarding_confirmation=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --bootstrap-outputs) bootstrap_outputs="${2:-}"; shift 2 ;;
    --source-sha) source_sha="${2:-}"; shift 2 ;;
    --stage) stage="${2:-}"; shift 2 ;;
    --release-id) release_id="${2:-}"; shift 2 ;;
    --deploy-key) deploy_key="${2:-}"; shift 2 ;;
    --known-hosts) known_hosts="${2:-}"; shift 2 ;;
    --var-file) var_file="${2:-}"; shift 2 ;;
    --web-build-config) web_build_config="${2:-}"; shift 2 ;;
    --bootstrap-manifest) bootstrap_manifest="${2:-}"; shift 2 ;;
    --approval) approval_file="${2:-}"; shift 2 ;;
    --approval-bundle) approval_bundle="${2:-}"; shift 2 ;;
    --artifact-out) artifact_out="${2:-}"; shift 2 ;;
    --artifact-kind) artifact_kind="${2:-}"; shift 2 ;;
    --acceptance-phase) acceptance_phase="${2:-}"; shift 2 ;;
    --acceptance-state) acceptance_state="${2:-}"; shift 2 ;;
    --alert-phase) alert_phase="${2:-}"; shift 2 ;;
    --alert-test-state) alert_test_state="${2:-}"; shift 2 ;;
    --alert-retry-approval) alert_retry_approval="${2:-}"; shift 2 ;;
    --delivery-confirmation-reference) delivery_confirmation_reference="${2:-}"; shift 2 ;;
    --pitr-phase) pitr_phase="${2:-}"; shift 2 ;;
    --restore-time-utc) restore_time_utc="${2:-}"; shift 2 ;;
    --quiet-window-end-utc) quiet_window_end_utc="${2:-}"; shift 2 ;;
    --preparer-reference) pitr_preparer_reference="${2:-}"; shift 2 ;;
    --prior-source-sha) prior_source_sha="${2:-}"; shift 2 ;;
    --prior-release-id) prior_release_id="${2:-}"; shift 2 ;;
    --recovery-phase) recovery_phase="${2:-}"; shift 2 ;;
    --stage-transition-mode) stage_transition_mode="${2:-}"; shift 2 ;;
    --offboarding-phase) offboarding_phase="${2:-}"; shift 2 ;;
    --offboarding-request) offboarding_request="${2:-}"; shift 2 ;;
    --offboarding-state) offboarding_state="${2:-}"; shift 2 ;;
    --offboarding-confirmation) offboarding_confirmation="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) guard_die "unknown argument: $1" ;;
  esac
done

[[ "$operation" == "stage-source" || "$operation" == "probe-network" || "$operation" == "build-push" || "$operation" == "database-prepare" || "$operation" == "workload-verify" || "$operation" == "runtime-acceptance" || "$operation" == "domain-verification" || "$operation" == "alert-delivery" || "$operation" == pitr-* || "$operation" == "release-rollback" || "$operation" == "release-forward" || "$operation" == "inspect-stage" || "$operation" == "stage-generation" || "$operation" == "offboarding-acceptance" || "$operation" == "bootstrap-identity" || "$operation" == "retrieve" || "$operation" == "cleanup-commands" || "$operation" == "stage-vars" || "$operation" == "plan" || "$operation" == "apply" ]] || guard_die "operation is invalid"
if [[ "$operation" == pitr-* ]]; then
  [[ "$operation" == "pitr-freeze" || "$operation" == "pitr-manifest" || "$operation" == "pitr-start" || "$operation" == "pitr-complete" || "$operation" == "pitr-cleanup" || "$operation" == "pitr-resume" ]] || guard_die "PITR operation is invalid"
fi
[[ -n "$bootstrap_outputs" ]] || guard_die "--bootstrap-outputs is required"
[[ "$source_sha" =~ ^[0-9a-f]{40}$ ]] || guard_die "--source-sha must be a full lowercase Git commit"
for command_name in az jq stat base64 bzip2 gzip git ssh-keygen install; do
  command -v "$command_name" >/dev/null 2>&1 || guard_die "$command_name is required"
done

bootstrap_outputs="$(guard_absolute_path "$bootstrap_outputs")"
guard_outside_repository "$bootstrap_outputs" "$repository_root" "bootstrap output JSON"
guard_private_file "$bootstrap_outputs" "bootstrap output JSON"
guard_load_bootstrap_outputs "$bootstrap_outputs"

transport_temp_dir="$(mktemp -d "${TMPDIR:-/tmp}/cosmas-d3-protected-transport.XXXXXX")"
chmod 700 "$transport_temp_dir"
command_script_file="$transport_temp_dir/protected-runner-command.sh"
resident_command_reference_file="$transport_temp_dir/resident-protected-runner-command.sh"
command_script_bzip2_b64_file="$transport_temp_dir/protected-runner-command.sh.bz2.b64"
command_launcher_file="$transport_temp_dir/protected-runner-launcher.sh"
early_cleanup() {
  rm -rf -- "$transport_temp_dir"
}
trap early_cleanup EXIT

managed_run_command_inventory_is_valid() {
  local inventory_file="$1"
  local exact_runner_id="${2,,}"

  jq -e --arg runner "$exact_runner_id" '
    type == "object" and
    (.value | type == "array") and
    ((has("nextLink") | not) or .nextLink == null or .nextLink == "") and
    all(.value[]?;
      (.id | type == "string") and
      ((.id | ascii_downcase) as $id |
        ($runner + "/runcommands/") as $prefix |
        ($id | startswith($prefix)) and
        (($id | ltrimstr($prefix)) | length > 0) and
        (($id | ltrimstr($prefix)) | contains("/") | not)
      )
    )
  ' "$inventory_file" >/dev/null
}

managed_run_command_read_inventory() {
  local exact_runner_id="$1"
  local api_version="$2"
  local inventory_file="$3"

  if ! az rest \
    --method get \
    --url "https://management.azure.com${exact_runner_id}/runCommands?api-version=${api_version}" \
    --only-show-errors \
    --output json >"$inventory_file" 2>/dev/null; then
    return 1
  fi
  chmod 0600 "$inventory_file" || return 1
  managed_run_command_inventory_is_valid "$inventory_file" "$exact_runner_id"
}

managed_run_command_show_instance() {
  local runner_id="$1"
  local command_id="$2"
  local output_file="$3"
  local normalized_runner_id
  local normalized_command_id
  local command_name
  local expected_runner_id

  normalized_runner_id="${runner_id,,}"
  normalized_command_id="${command_id,,}"
  expected_runner_id="/subscriptions/$GUARD_SUBSCRIPTION_ID/resourceGroups/$GUARD_STATE_RESOURCE_GROUP/providers/Microsoft.Compute/virtualMachines/$GUARD_RUNNER_VM_NAME"
  [[ "$normalized_runner_id" == "${expected_runner_id,,}" ]] || return 2
  [[ "$normalized_command_id" == "$normalized_runner_id/runcommands/"* ]] || return 2
  command_name="${command_id##*/}"
  [[ "$command_name" =~ ^cosmas-d3-[a-z0-9-]+$ ]] || return 2
  [[ "$normalized_command_id" == "$normalized_runner_id/runcommands/${command_name,,}" ]] || return 2

  # `az vm run-command show --ids` is not accepted by every Azure CLI release
  # for managed Run Command resources, including the reviewed workstation
  # release. Use the explicit resource selectors that are stable across those
  # versions while retaining the exact, prevalidated runner/name boundary.
  az vm run-command show \
    --subscription "$GUARD_SUBSCRIPTION_ID" \
    --resource-group "$GUARD_STATE_RESOURCE_GROUP" \
    --vm-name "$GUARD_RUNNER_VM_NAME" \
    --run-command-name "$command_name" \
    --instance-view \
    --only-show-errors \
    --output json >"$output_file"
}

managed_run_command_inventory_proves_absent() {
  local inventory_file="$1"
  local exact_runner_id="$2"
  local exact_command_id="${3,,}"

  managed_run_command_inventory_is_valid "$inventory_file" "$exact_runner_id" || return 1
  jq -e --arg command_id "$exact_command_id" '
    [.value[]?.id | ascii_downcase | select(. == $command_id)] | length == 0
  ' "$inventory_file" >/dev/null
}

managed_run_command_delete_and_verify_absent() {
  local exact_runner_id="$1"
  local exact_command_id="$2"
  local api_version="$3"
  local scratch_dir="$4"
  local retry_limit="$5"
  local retry_delay_seconds="$6"
  local require_full_settle_window="$7"
  local normalized_runner_id="${exact_runner_id,,}"
  local normalized_command_id="${exact_command_id,,}"
  local protected_prefix="${normalized_runner_id}/runcommands/cosmas-d3-"
  local command_suffix="${normalized_command_id#"$protected_prefix"}"
  local inventory_file="$scratch_dir/run-command-cleanup-readback.json"
  local attempt
  local consecutive_absent_readbacks=0

  [[ "$normalized_command_id" == "$protected_prefix"* ]] || return 2
  [[ "$command_suffix" =~ ^[a-z0-9][a-z0-9-]*$ ]] || return 2
  [[ "$api_version" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}(-preview)?$ ]] || return 2
  [[ "$retry_limit" =~ ^[1-9][0-9]*$ ]] || return 2
  (( retry_limit >= 2 )) || return 2
  [[ "$retry_delay_seconds" =~ ^[0-9]+$ ]] || return 2
  [[ "$require_full_settle_window" == "true" || "$require_full_settle_window" == "false" ]] || return 2
  [[ -d "$scratch_dir" ]] || return 2

  for ((attempt = 1; attempt <= retry_limit; attempt += 1)); do
    # A failed DELETE can mean that the resource is already absent. Only the
    # subsequent exact-parent inventory readbacks decide whether cleanup passed.
    # DELETE is always attempted first: after an ambiguous PUT failure, an
    # initially empty eventually-consistent inventory is not proof that the
    # server did not accept the command.
    az rest \
      --method delete \
      --url "https://management.azure.com${exact_command_id}?api-version=${api_version}" \
      --only-show-errors \
      --output none >/dev/null 2>&1 || true

    if managed_run_command_read_inventory "$exact_runner_id" "$api_version" "$inventory_file" &&
      managed_run_command_inventory_proves_absent "$inventory_file" "$exact_runner_id" "$exact_command_id"; then
      ((consecutive_absent_readbacks += 1))
      if [[ "$require_full_settle_window" == "false" ]] && (( consecutive_absent_readbacks >= 2 )); then
        return 0
      fi
    else
      consecutive_absent_readbacks=0
    fi
    if (( attempt < retry_limit )); then
      sleep "$retry_delay_seconds"
    fi
  done
  (( consecutive_absent_readbacks >= 2 ))
}

transport_signal_exit() {
  case "$1" in
    HUP) exit 129 ;;
    INT) exit 130 ;;
    TERM) exit 143 ;;
    *) exit 1 ;;
  esac
}

transport_install_signal_traps() {
  trap 'transport_signal_exit HUP' HUP
  trap 'transport_signal_exit INT' INT
  trap 'transport_signal_exit TERM' TERM
}

transport_defer_signal() {
  if [[ -z "${transport_deferred_signal:-}" ]]; then
    transport_deferred_signal="$1"
  fi
}

transport_install_deferred_signal_traps() {
  trap 'transport_defer_signal HUP' HUP
  trap 'transport_defer_signal INT' INT
  trap 'transport_defer_signal TERM' TERM
}

transport_cleanup_managed_command() {
  local require_full_settle_window=false

  if [[ "${command_submission_acknowledged:-false}" != "true" ]]; then
    require_full_settle_window=true
  fi
  command_cleanup_attempted=true
  if managed_run_command_delete_and_verify_absent \
    "$runner_id" \
    "$run_command_id" \
    "$managed_run_command_api_version" \
    "$transport_temp_dir" \
    "$managed_run_command_cleanup_attempts" \
    "$managed_run_command_cleanup_retry_seconds" \
    "$require_full_settle_window"; then
    command_cleanup_required=false
    return 0
  fi
  return 1
}

transport_complete_managed_command_cleanup() {
  local cleanup_succeeded=false

  transport_deferred_signal=""
  transport_install_deferred_signal_traps
  if transport_cleanup_managed_command; then
    cleanup_succeeded=true
  fi
  transport_install_signal_traps
  [[ "$cleanup_succeeded" == "true" ]] || return 1
  if [[ -n "$transport_deferred_signal" ]]; then
    transport_signal_exit "$transport_deferred_signal"
  fi
  return 0
}

transport_remove_local_protected_files() {
  local local_file
  local removal_failed=false

  for local_file in \
    "${payload_file:-}" \
    "${payload_b64_file:-}" \
    "${request_file:-}" \
    "${view_file:-}" \
    "${artifact_staging:-}"; do
    [[ -n "$local_file" ]] || continue
    if ! rm -f -- "$local_file"; then
      removal_failed=true
    fi
  done
  [[ "$removal_failed" == "false" ]]
}

transport_cleanup_on_exit() {
  local original_status=$?
  local managed_cleanup_failed=false
  local local_cleanup_failed=false

  trap - EXIT
  transport_deferred_signal=""
  transport_install_deferred_signal_traps
  if ! transport_remove_local_protected_files; then
    local_cleanup_failed=true
  fi
  if [[ "${command_cleanup_required:-false}" == "true" && "${command_cleanup_attempted:-false}" == "false" ]]; then
    if ! transport_cleanup_managed_command; then
      managed_cleanup_failed=true
    fi
  elif [[ "${command_cleanup_required:-false}" == "true" && "$original_status" -ne "${managed_run_command_cleanup_failure_status:-74}" ]]; then
    managed_cleanup_failed=true
  fi
  if ! rm -rf -- "$transport_temp_dir"; then
    local_cleanup_failed=true
  fi
  if [[ "$managed_cleanup_failed" == "true" ]]; then
    printf '%s\n' 'D3 protected transport cleanup failed closed: the exact managed Run Command could not be proven absent after bounded deletion/readback retries' >&2
    exit "${managed_run_command_cleanup_failure_status:-74}"
  fi
  if [[ "$local_cleanup_failed" == "true" ]]; then
    printf '%s\n' 'D3 protected transport cleanup failed closed: local protected payload files could not be removed' >&2
    exit "${managed_run_command_cleanup_failure_status:-74}"
  fi
  if [[ "$original_status" -eq 0 && -n "$transport_deferred_signal" ]]; then
    case "$transport_deferred_signal" in
      HUP) original_status=129 ;;
      INT) original_status=130 ;;
      TERM) original_status=143 ;;
    esac
  fi
  exit "$original_status"
}
if [[ "$operation" == "stage-source" ]]; then
  [[ -n "$deploy_key" && -n "$known_hosts" ]] || guard_die "stage-source requires --deploy-key and --known-hosts"
  deploy_key="$(guard_absolute_path "$deploy_key")"
  known_hosts="$(guard_absolute_path "$known_hosts")"
  guard_outside_repository "$deploy_key" "$repository_root" "ephemeral deploy private key"
  guard_outside_repository "$known_hosts" "$repository_root" "reviewed GitHub known-hosts file"
  guard_private_file "$deploy_key" "ephemeral deploy private key"
  guard_private_file "$known_hosts" "reviewed GitHub known-hosts file"
  ssh-keygen -y -f "$deploy_key" >/dev/null 2>&1 || guard_die "ephemeral deploy key is not a valid SSH private key"
  [[ "$(grep -cve '^[[:space:]]*$' "$known_hosts")" == "1" ]] || guard_die "known-hosts file must contain exactly one reviewed key"
  grep -Eq '^\[ssh\.github\.com\]:443[[:space:]]+ssh-ed25519[[:space:]]+[A-Za-z0-9+/=]+([[:space:]]|$)' "$known_hosts" || guard_die "known-hosts entry must pin GitHub SSH on port 443 with Ed25519"
  authenticated_deploy_key="$transport_temp_dir/github-deploy-key"
  authenticated_known_hosts="$transport_temp_dir/github-known-hosts"
  install -m 0600 "$deploy_key" "$authenticated_deploy_key"
  install -m 0600 "$known_hosts" "$authenticated_known_hosts"
  deploy_key="$authenticated_deploy_key"
  known_hosts="$authenticated_known_hosts"
  guard_materialize_authenticated_committed_file \
    "$repository_root" \
    "$source_sha" \
    "infra/beta/protected-runner-command.sh" \
    "$command_script_file" \
    "git@github.com:CosmaNeura/cosmaneura-os.git" \
    "$deploy_key" \
    "$known_hosts" \
    "$prior_source_sha"
  resident_command_sha256="$(guard_sha256 "$command_script_file")"
else
  [[ -z "$deploy_key" && -z "$known_hosts" ]] || guard_die "deploy credentials are accepted only by stage-source"
  guard_materialize_local_committed_file \
    "$repository_root" \
    "$source_sha" \
    "infra/beta/protected-runner-command.sh" \
    "$resident_command_reference_file" \
    "git@github.com:CosmaNeura/cosmaneura-os.git"
  resident_command_sha256="$(guard_sha256 "$resident_command_reference_file")"
cat >"$command_script_file" <<'DISPATCHER'
#!/bin/bash -p
set +x
set -euo pipefail
umask 077
export GIT_NO_REPLACE_OBJECTS=1
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
unset BASH_ENV ENV CDPATH PYTHONHOME PYTHONPATH PYTHONSTARTUP
die() { printf 'D3 resident command dispatcher refused: %s\n' "$1" >&2; exit 1; }
[[ "$(id -u)" == "0" ]] || die "dispatcher must execute as root"
source_sha="${COSMAS_SOURCE_SHA:-}"
expected_command_sha256="${COSMAS_RESIDENT_COMMAND_SHA256:-}"
[[ "$source_sha" =~ ^[0-9a-f]{40}$ ]] || die "source SHA is invalid"
[[ "$expected_command_sha256" =~ ^[0-9a-f]{64}$ ]] || die "resident command hash is invalid"
repository="/opt/cosmas-os/releases/$source_sha"
receipt="/var/lib/cosmas-deploy-runner/source-receipts/$source_sha.json"
command_path="$repository/infra/beta/protected-runner-command.sh"
toolchain_manifest="/var/lib/cosmas-deploy-runner/toolchain.json"
/usr/bin/python3 -I -E -s - "$repository" "$receipt" "$command_path" "$toolchain_manifest" "$source_sha" "$expected_command_sha256" <<'PY'
import hashlib
import json
import os
import stat
import sys
from typing import Any

repository, receipt_path, command_path, toolchain_path, source_sha, expected_command_hash = sys.argv[1:]

def refuse(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)

def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        refuse(key not in value, "duplicate receipt key")
        value[key] = item
    return value

for path in (repository, receipt_path, command_path, toolchain_path, "/usr/bin/git"):
    current = path
    while current != "/":
        info = os.lstat(current)
        refuse(not stat.S_ISLNK(info.st_mode) and info.st_uid == 0, "unsafe protected path")
        current = os.path.dirname(current)
with open(receipt_path, "rb") as handle:
    raw = handle.read(16385)
refuse(len(raw) <= 16384, "source receipt is oversized")
receipt = json.loads(raw, object_pairs_hook=unique, parse_constant=lambda value: refuse(False, f"invalid constant {value}"))
keys = {"schema_version", "contract", "status", "source_sha", "source_tree_sha1", "runner_command_sha256", "authenticated_origin", "fetch_mode", "remote_removed", "replace_refs_disabled", "completed_at", "evidence_payload_sha256"}
refuse(isinstance(receipt, dict) and set(receipt) == keys, "source receipt shape is invalid")
refuse(receipt["schema_version"] == 2 and type(receipt["schema_version"]) is int, "source receipt version is invalid")
refuse(receipt["contract"] == "cosmas-os-d3-authenticated-source-staging-v2" and receipt["status"] == "verified", "source receipt contract is invalid")
refuse(receipt["source_sha"] == source_sha and receipt["runner_command_sha256"] == expected_command_hash, "source receipt binding is invalid")
refuse(receipt["authenticated_origin"] == "ssh://git@ssh.github.com:443/CosmaNeura/cosmaneura-os.git" and receipt["fetch_mode"] == "full", "source receipt origin is invalid")
refuse(receipt["remote_removed"] is True and receipt["replace_refs_disabled"] is True, "source receipt isolation is invalid")
refuse(isinstance(receipt["source_tree_sha1"], str) and __import__("re").fullmatch(r"[0-9a-f]{40}", receipt["source_tree_sha1"]) is not None, "source receipt tree is invalid")
refuse(isinstance(receipt["completed_at"], str) and __import__("re").fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", receipt["completed_at"]) is not None, "source receipt timestamp is invalid")
payload = dict(receipt)
expected_hash = payload.pop("evidence_payload_sha256", "")
actual_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
refuse(expected_hash == actual_hash, "source receipt hash is invalid")
with open(command_path, "rb") as handle:
    actual_command_hash = hashlib.sha256(handle.read()).hexdigest()
refuse(actual_command_hash == expected_command_hash, "resident protected command differs from its authenticated receipt")
with open(toolchain_path, "rb") as handle:
    toolchain_raw = handle.read(65537)
refuse(len(toolchain_raw) <= 65536, "toolchain manifest is oversized")
toolchain = json.loads(toolchain_raw, object_pairs_hook=unique, parse_constant=lambda value: refuse(False, f"invalid constant {value}"))
expected_git_hash = toolchain.get("git_binary_sha256")
git_info = os.lstat("/usr/bin/git")
refuse(
    isinstance(expected_git_hash, str)
    and __import__("re").fullmatch(r"[0-9a-f]{64}", expected_git_hash) is not None
    and stat.S_ISREG(git_info.st_mode)
    and git_info.st_uid == 0
    and not git_info.st_mode & 0o022,
    "fixed Git binary is unsafe",
)
with open("/usr/bin/git", "rb") as handle:
    actual_git_hash = hashlib.sha256(handle.read()).hexdigest()
refuse(actual_git_hash == expected_git_hash, "fixed Git binary differs from its protected pin")
PY
safe_git() {
  /usr/bin/env -i \
    PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    HOME=/root LANG=C LC_ALL=C \
    GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null \
    GIT_TERMINAL_PROMPT=0 GIT_NO_REPLACE_OBJECTS=1 \
    /usr/bin/git --no-pager -c protocol.allow=never -c core.fsmonitor=false \
      -c core.hooksPath=/dev/null -c credential.helper= "$@"
}
[[ "$(safe_git -C "$repository" rev-parse --verify HEAD)" == "$source_sha" ]] || die "resident source HEAD differs"
[[ "$(safe_git -C "$repository" rev-parse "$source_sha^{tree}")" == "$(/usr/bin/jq -er '.source_tree_sha1' "$receipt")" ]] || die "resident source tree differs from its authenticated receipt"
[[ -z "$(safe_git -C "$repository" status --porcelain=v1 --untracked-files=all)" ]] || die "resident source is dirty"
[[ -z "$(safe_git -C "$repository" remote)" ]] || die "resident source retained a remote"
[[ -z "$(safe_git -C "$repository" for-each-ref --format='%(refname)' refs/replace)" ]] || die "resident source contains replace refs"
[[ ! -e "$repository/.git/shallow" && ! -e "$repository/.git/objects/info/alternates" ]] || die "resident source is shallow or uses alternates"
if safe_git -C "$repository" config --local --list | awk -F= '{key=tolower($1); if (key == "extensions.partialclone" || key ~ /^remote\..*\.(promisor|partialclonefilter)$/) found=1} END {exit !found}'; then die "resident source has lazy-fetch configuration"; fi
if find "$repository/.git/objects/pack" -type f -name '*.promisor' -print -quit 2>/dev/null | grep -q .; then die "resident source has promisor objects"; fi
safe_git -C "$repository" fsck --full --no-dangling "$source_sha" >/dev/null 2>&1 || die "resident source object graph is incomplete"
exec /usr/bin/env -i \
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  HOME=/root LANG=C.UTF-8 LC_ALL=C.UTF-8 \
  COSMAS_SUBSCRIPTION_ID="${COSMAS_SUBSCRIPTION_ID:-}" \
  COSMAS_DEPLOY_CLIENT_ID="${COSMAS_DEPLOY_CLIENT_ID:-}" \
  COSMAS_OPERATION="${COSMAS_OPERATION:-}" \
  COSMAS_STAGE="${COSMAS_STAGE:-}" \
  COSMAS_RELEASE_ID="${COSMAS_RELEASE_ID:-}" \
  COSMAS_SOURCE_SHA="${COSMAS_SOURCE_SHA:-}" \
  COSMAS_RESIDENT_COMMAND_SHA256="${COSMAS_RESIDENT_COMMAND_SHA256:-}" \
  COSMAS_PROTECTED_PAYLOAD_BASE64="${COSMAS_PROTECTED_PAYLOAD_BASE64:-}" \
  /bin/bash --noprofile --norc -p "$command_path"
DISPATCHER
  chmod 0600 "$command_script_file"
fi
command_script_sha256="$(guard_sha256 "$command_script_file")"
bzip2 -9 -c "$command_script_file" | base64 | tr -d '\n' >"$command_script_bzip2_b64_file"
chmod 0600 "$command_script_bzip2_b64_file"
cat >"$command_launcher_file" <<'LAUNCHER'
#!/bin/bash -p
set +x
set -euo pipefail
umask 077
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
unset BASH_ENV ENV CDPATH PYTHONHOME PYTHONPATH PYTHONSTARTUP
command_file="$(/usr/bin/mktemp /run/cosmas-protected-command.XXXXXX)"
cleanup_launcher() {
  /usr/bin/rm -f -- "$command_file"
}
trap cleanup_launcher EXIT
[[ "${COSMAS_COMMAND_SHA256:-}" =~ ^[0-9a-f]{64}$ ]] || {
  printf '%s\n' 'D3 protected command launcher refused: invalid committed-command hash' >&2
  exit 1
}
[[ "${COSMAS_COMMAND_BZIP2_BASE64:-}" =~ ^[A-Za-z0-9+/=]+$ ]] || {
  printf '%s\n' 'D3 protected command launcher refused: invalid protected command encoding' >&2
  exit 1
}
(( ${#COSMAS_COMMAND_BZIP2_BASE64} <= 65536 )) || {
  printf '%s\n' 'D3 protected command launcher refused: protected command exceeds its bound' >&2
  exit 1
}
printf '%s' "$COSMAS_COMMAND_BZIP2_BASE64" | /usr/bin/base64 --decode | /usr/bin/python3 -I -E -s -c 'import bz2,sys; data=sys.stdin.buffer.read(49153); decoder=bz2.BZ2Decompressor(); decoded=decoder.decompress(data,524289); (len(data) <= 49152 and len(decoded) <= 524288 and decoder.eof and not decoder.unused_data) or sys.exit(1); sys.stdout.buffer.write(decoded)' >"$command_file"
/usr/bin/chmod 0700 "$command_file"
[[ "$(/usr/bin/sha256sum "$command_file" | /usr/bin/awk '{print $1}')" == "$COSMAS_COMMAND_SHA256" ]] || {
  printf '%s\n' 'D3 protected command launcher refused: committed-command hash mismatch' >&2
  exit 1
}
unset COSMAS_COMMAND_BZIP2_BASE64 COSMAS_COMMAND_SHA256
set +e
/usr/bin/env -i \
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  HOME=/root LANG=C.UTF-8 LC_ALL=C.UTF-8 \
  COSMAS_SUBSCRIPTION_ID="${COSMAS_SUBSCRIPTION_ID:-}" \
  COSMAS_DEPLOY_CLIENT_ID="${COSMAS_DEPLOY_CLIENT_ID:-}" \
  COSMAS_OPERATION="${COSMAS_OPERATION:-}" \
  COSMAS_STAGE="${COSMAS_STAGE:-}" \
  COSMAS_RELEASE_ID="${COSMAS_RELEASE_ID:-}" \
  COSMAS_SOURCE_SHA="${COSMAS_SOURCE_SHA:-}" \
  COSMAS_RESIDENT_COMMAND_SHA256="${COSMAS_RESIDENT_COMMAND_SHA256:-}" \
  COSMAS_PROTECTED_PAYLOAD_BASE64="${COSMAS_PROTECTED_PAYLOAD_BASE64:-}" \
  /bin/bash --noprofile --norc -p "$command_file"
status=$?
set -e
exit "$status"
LAUNCHER
chmod 0700 "$command_launcher_file"
(( $(wc -c <"$command_launcher_file") <= 65536 )) || guard_die "managed Run Command launcher exceeds Azure's 64 KiB inline-script limit"
(( $(wc -c <"$command_script_bzip2_b64_file") <= 65536 )) || guard_die "compressed committed runner command exceeds the bounded protected-parameter transport"

case "$operation" in
  stage-source)
    stage="source"
    release_id="source"
    if [[ -n "$prior_source_sha" ]]; then
      [[ "$prior_source_sha" =~ ^[0-9a-f]{40}$ && "$prior_source_sha" != "$source_sha" ]] || guard_die "stage-source --prior-source-sha must be a different full lowercase commit"
      # The command sent to the protected runner is itself read from source_sha.
      # Prove its A->B relationship locally before transporting that candidate
      # command; the runner repeats the proof over its authenticated full fetch.
      guard_validate_git_source_transition "$repository_root" "$prior_source_sha" "$source_sha"
    fi
    ;;
  stage-vars)
    [[ "$stage" == "foundation" || "$stage" == "database" || "$stage" == "workloads" ]] || guard_die "stage-vars requires a valid --stage"
    [[ "$release_id" =~ ^[a-z0-9][a-z0-9-]{2,31}$ ]] || guard_die "stage-vars requires a 3-32 character lowercase --release-id"
    [[ -n "$var_file" ]] || guard_die "stage-vars requires --var-file"
    var_file="$(guard_absolute_path "$var_file")"
    guard_outside_repository "$var_file" "$repository_root" "private environment tfvars JSON"
    guard_private_file "$var_file" "private environment tfvars JSON"
    jq -e 'type == "object"' "$var_file" >/dev/null || guard_die "--var-file must be a JSON object"
    ;;
  probe-network)
    stage="network"
    [[ "$release_id" =~ ^[a-z0-9][a-z0-9-]{2,31}$ ]] || guard_die "probe-network requires a 3-32 character lowercase --release-id"
    [[ -n "$artifact_out" ]] || guard_die "probe-network requires --artifact-out"
    artifact_out="$(guard_absolute_path "$artifact_out")"
    guard_outside_repository "$artifact_out" "$repository_root" "sanitized live network evidence"
    guard_new_private_path "$artifact_out" "sanitized live network evidence"
    ;;
  build-push)
    stage="images"
    [[ "$release_id" =~ ^[a-z0-9][a-z0-9-]{2,31}$ ]] || guard_die "build-push requires a 3-32 character lowercase --release-id"
    [[ -n "$web_build_config" && -n "$artifact_out" ]] || guard_die "build-push requires --web-build-config and --artifact-out"
    web_build_config="$(guard_absolute_path "$web_build_config")"
    artifact_out="$(guard_absolute_path "$artifact_out")"
    guard_outside_repository "$web_build_config" "$repository_root" "public web build configuration"
    guard_outside_repository "$artifact_out" "$repository_root" "sanitized build evidence"
    guard_private_file "$web_build_config" "public web build configuration"
    guard_new_private_path "$artifact_out" "sanitized build evidence"
    jq -e 'type == "object"' "$web_build_config" >/dev/null || guard_die "--web-build-config must be a JSON object"
    ;;
  database-prepare)
    stage="database"
    [[ "$release_id" =~ ^[a-z0-9][a-z0-9-]{2,31}$ ]] || guard_die "database-prepare requires a 3-32 character lowercase --release-id"
    [[ -n "$artifact_out" ]] || guard_die "database-prepare requires --artifact-out"
    artifact_out="$(guard_absolute_path "$artifact_out")"
    guard_outside_repository "$artifact_out" "$repository_root" "sanitized database-preparation attestation"
    guard_new_private_path "$artifact_out" "sanitized database-preparation attestation"
    ;;
  workload-verify)
    stage="workload-verification"
    [[ "$release_id" =~ ^[a-z0-9][a-z0-9-]{2,31}$ ]] || guard_die "workload-verify requires a 3-32 character lowercase --release-id"
    [[ -n "$artifact_out" ]] || guard_die "workload-verify requires --artifact-out"
    artifact_out="$(guard_absolute_path "$artifact_out")"
    guard_outside_repository "$artifact_out" "$repository_root" "sanitized workload-verification attestation"
    guard_new_private_path "$artifact_out" "sanitized workload-verification attestation"
    ;;
  runtime-acceptance)
    stage="acceptance"
    [[ "$release_id" =~ ^[a-z0-9][a-z0-9-]{2,31}$ ]] || guard_die "runtime-acceptance requires a 3-32 character lowercase --release-id"
    [[ "$acceptance_phase" == "runtime" || "$acceptance_phase" == "workflow-baseline" || "$acceptance_phase" == "workflow-verify" || "$acceptance_phase" == "audit-replay" || "$acceptance_phase" == "purge-setup" || "$acceptance_phase" == "purge-verify" ]] || guard_die "runtime-acceptance requires an enumerated --acceptance-phase"
    [[ -n "$artifact_out" ]] || guard_die "runtime-acceptance requires --artifact-out"
    artifact_out="$(guard_absolute_path "$artifact_out")"
    guard_outside_repository "$artifact_out" "$repository_root" "sanitized runtime-acceptance attestation"
    guard_new_private_path "$artifact_out" "sanitized runtime-acceptance attestation"
    if [[ "$acceptance_phase" == "workflow-verify" || "$acceptance_phase" == "purge-verify" ]]; then
      [[ -n "$acceptance_state" ]] || guard_die "$acceptance_phase requires --acceptance-state from its protected baseline/setup execution"
      acceptance_state="$(guard_absolute_path "$acceptance_state")"
      guard_outside_repository "$acceptance_state" "$repository_root" "protected acceptance state"
      guard_private_file "$acceptance_state" "protected acceptance state"
      (( $(wc -c <"$acceptance_state") <= 16384 )) || guard_die "protected acceptance state exceeds 16 KiB"
      jq -e 'type == "object" and .schema_version == 1 and .evidence_type == "protected-runner-runtime-acceptance" and (.acceptance_output | type == "object")' "$acceptance_state" >/dev/null || guard_die "--acceptance-state is not a protected runtime-acceptance artifact"
    else
      [[ -z "$acceptance_state" ]] || guard_die "--acceptance-state is accepted only for workflow-verify or purge-verify"
    fi
    ;;
  domain-verification)
    stage="domain"
    [[ "$release_id" =~ ^[a-z0-9][a-z0-9-]{2,31}$ ]] || guard_die "domain-verification requires a 3-32 character lowercase --release-id"
    [[ -n "$artifact_out" ]] || guard_die "domain-verification requires --artifact-out"
    artifact_out="$(guard_absolute_path "$artifact_out")"
    guard_outside_repository "$artifact_out" "$repository_root" "protected public-DNS verification artifact"
    guard_new_private_path "$artifact_out" "protected public-DNS verification artifact"
    ;;
  alert-delivery)
    stage="alert"
    [[ "$release_id" =~ ^[a-z0-9][a-z0-9-]{2,31}$ ]] || guard_die "alert-delivery requires a 3-32 character lowercase --release-id"
    [[ "$alert_phase" == "send" || "$alert_phase" == "confirm" || "$alert_phase" == "inspect-intent" ]] || guard_die "alert-delivery requires --alert-phase send|confirm|inspect-intent"
    [[ -n "$artifact_out" ]] || guard_die "alert-delivery requires --artifact-out"
    artifact_out="$(guard_absolute_path "$artifact_out")"
    guard_outside_repository "$artifact_out" "$repository_root" "sanitized alert-delivery attestation"
    guard_new_private_path "$artifact_out" "sanitized alert-delivery attestation"
    if [[ "$alert_phase" == "confirm" ]]; then
      [[ -z "$alert_retry_approval" ]] || guard_die "alert confirmation does not accept --alert-retry-approval"
      [[ -n "$alert_test_state" && -n "$delivery_confirmation_reference" ]] || guard_die "alert delivery confirmation requires --alert-test-state and --delivery-confirmation-reference"
      alert_test_state="$(guard_absolute_path "$alert_test_state")"
      delivery_confirmation_reference="$(guard_absolute_path "$delivery_confirmation_reference")"
      guard_outside_repository "$alert_test_state" "$repository_root" "protected alert test state"
      guard_outside_repository "$delivery_confirmation_reference" "$repository_root" "owner delivery confirmation reference"
      guard_private_file "$alert_test_state" "protected alert test state"
      guard_private_file "$delivery_confirmation_reference" "owner delivery confirmation reference"
      (( $(wc -c <"$alert_test_state") <= 16384 )) || guard_die "protected alert test state exceeds 16 KiB"
      jq -e 'type == "object" and .schema_version == 1 and .evidence_type == "protected-runner-alert-delivery" and .alert_phase == "send"' "$alert_test_state" >/dev/null || guard_die "--alert-test-state is not a protected alert send artifact"
      guard_validate_alert_owner_confirmation "$delivery_confirmation_reference" "$alert_test_state"
    elif [[ "$alert_phase" == "inspect-intent" ]]; then
      [[ -z "$alert_test_state" && -z "$delivery_confirmation_reference" && -z "$alert_retry_approval" ]] || guard_die "alert intent inspection does not accept send or confirmation inputs"
    else
      [[ -z "$alert_test_state" && -z "$delivery_confirmation_reference" ]] || guard_die "alert send does not accept confirmation inputs"
      if [[ -n "$alert_retry_approval" ]]; then
        alert_retry_approval="$(guard_absolute_path "$alert_retry_approval")"
        guard_outside_repository "$alert_retry_approval" "$repository_root" "private ambiguous-alert retry approval"
        guard_private_file "$alert_retry_approval" "private ambiguous-alert retry approval"
        (( $(wc -c <"$alert_retry_approval") <= 16384 )) || guard_die "ambiguous-alert retry approval exceeds 16 KiB"
        jq -e '
          type == "object" and .schema_version == 1 and
          .contract == "cosmas-os-d3-alert-ambiguous-retry-approval-v1" and
          (.prior_intent_sha256 | strings | test("^[0-9a-f]{64}$"))
        ' "$alert_retry_approval" >/dev/null || guard_die "--alert-retry-approval is not a D3 ambiguous-alert retry approval"
      fi
    fi
    ;;
  pitr-freeze)
    stage="pitr"
    pitr_phase="freeze"
    [[ "$release_id" =~ ^[a-z0-9][a-z0-9-]{2,31}$ ]] || guard_die "pitr-freeze requires a 3-32 character lowercase --release-id"
    [[ "$quiet_window_end_utc" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]] || guard_die "pitr-freeze requires a whole-second UTC --quiet-window-end-utc"
    [[ -n "$artifact_out" ]] || guard_die "pitr-freeze requires --artifact-out"
    artifact_out="$(guard_absolute_path "$artifact_out")"
    guard_outside_repository "$artifact_out" "$repository_root" "sanitized PITR writer-freeze attestation"
    guard_new_private_path "$artifact_out" "sanitized PITR writer-freeze attestation"
    ;;
  pitr-manifest)
    stage="pitr"
    pitr_phase="manifest"
    [[ "$release_id" =~ ^[a-z0-9][a-z0-9-]{2,31}$ ]] || guard_die "pitr-manifest requires a 3-32 character lowercase --release-id"
    [[ "$restore_time_utc" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]] || guard_die "pitr-manifest requires a whole-second UTC --restore-time-utc"
    [[ -n "$pitr_preparer_reference" && -n "$artifact_out" ]] || guard_die "pitr-manifest requires --preparer-reference and --artifact-out"
    pitr_preparer_reference="$(guard_absolute_path "$pitr_preparer_reference")"
    artifact_out="$(guard_absolute_path "$artifact_out")"
    guard_outside_repository "$pitr_preparer_reference" "$repository_root" "private PITR manifest-preparer reference"
    guard_outside_repository "$artifact_out" "$repository_root" "sanitized PITR manifest evidence"
    guard_private_file "$pitr_preparer_reference" "private PITR manifest-preparer reference"
    guard_new_private_path "$artifact_out" "sanitized PITR manifest evidence"
    (( $(wc -c <"$pitr_preparer_reference") <= 512 )) || guard_die "PITR manifest-preparer reference exceeds 512 bytes"
    jq -Rs -e '
      (if endswith("\n") then rtrimstr("\n") else . end) as $value |
      ($value | contains("\n") | not) and
      ($value | test("^[A-Za-z0-9][A-Za-z0-9._:/ ()-]{2,255}$")) and
      ($value | contains("@") | not)
    ' "$pitr_preparer_reference" >/dev/null || guard_die "PITR manifest-preparer reference must contain one bounded non-email reviewer reference"
    ;;
  pitr-start|pitr-complete|pitr-cleanup|pitr-resume)
    stage="pitr"
    pitr_phase="${operation#pitr-}"
    [[ "$release_id" =~ ^[a-z0-9][a-z0-9-]{2,31}$ ]] || guard_die "$operation requires a 3-32 character lowercase --release-id"
    [[ -n "$approval_file" && -n "$artifact_out" ]] || guard_die "$operation requires --approval and --artifact-out"
    approval_file="$(guard_absolute_path "$approval_file")"
    artifact_out="$(guard_absolute_path "$artifact_out")"
    guard_outside_repository "$approval_file" "$repository_root" "private PITR owner approval"
    guard_outside_repository "$artifact_out" "$repository_root" "sanitized PITR evidence"
    guard_private_file "$approval_file" "private PITR owner approval"
    guard_new_private_path "$artifact_out" "sanitized PITR evidence"
    if [[ "$operation" == "pitr-resume" ]]; then
      jq -e '
        type == "object" and
        (keys | sort) == (["approved_at", "confirmation", "freeze_evidence_sha256", "reviewer_reference", "schema_version"] | sort) and
        .schema_version == 1 and .confirmation == "RESUME D3 WRITERS" and
        (.freeze_evidence_sha256 | strings | test("^[0-9a-f]{64}$")) and
        (.approved_at | strings | test("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")) and
        (.reviewer_reference | strings | test("^[A-Za-z0-9][A-Za-z0-9._:/ -]{2,511}$")) and
        (.reviewer_reference | contains("@") | not)
      ' "$approval_file" >/dev/null || guard_die "PITR resume approval is not the exact bounded owner assertion"
    else
      jq -e '
        type == "object" and
        (keys | sort) == (["approved_at", "confirmation", "manifest_sha256", "reviewer_reference", "schema_version"] | sort) and
        .schema_version == 1 and .confirmation == "AUTHORIZE D3 BILLABLE PITR" and
        (.manifest_sha256 | strings | test("^[0-9a-f]{64}$")) and
        (.approved_at | strings | test("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")) and
        (.reviewer_reference | strings | test("^[A-Za-z0-9][A-Za-z0-9._:/ -]{2,511}$")) and
        (.reviewer_reference | contains("@") | not)
      ' "$approval_file" >/dev/null || guard_die "PITR approval is not the exact manifest-bound owner assertion"
    fi
    ;;
  release-rollback|release-forward)
    stage="recovery"
    recovery_phase="${operation#release-}"
    [[ "$release_id" =~ ^[a-z0-9][a-z0-9-]{2,31}$ ]] || guard_die "$operation requires a valid current --release-id"
    [[ "$prior_source_sha" =~ ^[0-9a-f]{40}$ && "$prior_source_sha" != "$source_sha" ]] || guard_die "$operation requires a distinct full lowercase --prior-source-sha"
    [[ "$prior_release_id" =~ ^[a-z0-9][a-z0-9-]{2,31}$ && "$prior_release_id" != "$release_id" ]] || guard_die "$operation requires a distinct --prior-release-id"
    [[ -n "$approval_file" && -n "$artifact_out" ]] || guard_die "$operation requires --approval and --artifact-out"
    approval_file="$(guard_absolute_path "$approval_file")"
    artifact_out="$(guard_absolute_path "$artifact_out")"
    guard_outside_repository "$approval_file" "$repository_root" "private release-recovery owner approval"
    guard_outside_repository "$artifact_out" "$repository_root" "sanitized release-recovery evidence"
    guard_private_file "$approval_file" "private release-recovery owner approval"
    guard_new_private_path "$artifact_out" "sanitized release-recovery evidence"
    (( $(wc -c <"$approval_file") <= 16384 )) || guard_die "release-recovery approval exceeds 16 KiB"
    jq -e --arg phase "$recovery_phase" --arg source_sha "$source_sha" --arg release_id "$release_id" --arg prior_source_sha "$prior_source_sha" --arg prior_release_id "$prior_release_id" '
      type == "object" and
      (if $phase == "rollback" then
        (keys | sort) == (["approved_at", "confirmation", "contract", "current", "prior", "reviewer_reference", "schema_version"] | sort) and
        .contract == "cosmas-os-d3-release-rollback-approval-v1" and
        .confirmation == "AUTHORIZE D3 IMMUTABLE DIGEST ROLLBACK"
      else
        (keys | sort) == (["approved_at", "confirmation", "contract", "current", "prior", "reviewer_reference", "rollback_evidence_sha256", "rollback_state_sha256", "schema_version"] | sort) and
        .contract == "cosmas-os-d3-release-forward-approval-v1" and
        .confirmation == "AUTHORIZE D3 IMMUTABLE DIGEST FORWARD RESTORATION" and
        (.rollback_evidence_sha256 | strings | test("^[0-9a-f]{64}$")) and
        (.rollback_state_sha256 | strings | test("^[0-9a-f]{64}$"))
      end) and
      .schema_version == 1 and
      (.approved_at | strings | test("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")) and
      (.reviewer_reference | strings | test("^[A-Za-z0-9][A-Za-z0-9._:/ -]{2,511}$")) and
      (.reviewer_reference | contains("@") | not) and
      (.current | keys | sort) == (["api_digest", "release_id", "source_sha", "web_digest"] | sort) and
      (.prior | keys | sort) == (["api_digest", "release_id", "source_sha", "web_digest"] | sort) and
      .current.source_sha == $source_sha and .current.release_id == $release_id and
      .prior.source_sha == $prior_source_sha and .prior.release_id == $prior_release_id and
      (.current.api_digest | strings | test("^sha256:[0-9a-f]{64}$")) and
      (.current.web_digest | strings | test("^sha256:[0-9a-f]{64}$")) and
      (.prior.api_digest | strings | test("^sha256:[0-9a-f]{64}$")) and
      (.prior.web_digest | strings | test("^sha256:[0-9a-f]{64}$")) and
      ([.current.api_digest, .current.web_digest, .prior.api_digest, .prior.web_digest] | unique | length) == 4
    ' "$approval_file" >/dev/null || guard_die "release-recovery approval is not the exact phase-specific two-release owner assertion"
    ;;
  inspect-stage)
    [[ "$stage" == "foundation" || "$stage" == "database" || "$stage" == "workloads" ]] || guard_die "inspect-stage requires a valid --stage"
    [[ "$release_id" =~ ^[a-z0-9][a-z0-9-]{2,31}$ ]] || guard_die "inspect-stage requires a valid --release-id"
    [[ -n "$artifact_out" ]] || guard_die "inspect-stage requires --artifact-out"
    artifact_out="$(guard_absolute_path "$artifact_out")"
    guard_outside_repository "$artifact_out" "$repository_root" "sanitized immutable-stage inventory"
    guard_new_private_path "$artifact_out" "sanitized immutable-stage inventory"
    ;;
  stage-generation)
    [[ "$stage" == "foundation" || "$stage" == "database" || "$stage" == "workloads" ]] || guard_die "stage-generation requires a valid --stage"
    [[ "$release_id" =~ ^[a-z0-9][a-z0-9-]{2,31}$ ]] || guard_die "stage-generation requires a valid --release-id"
    [[ "$stage_transition_mode" == "abandoned_retry" || "$stage_transition_mode" == "planned_workloads_progression" ]] || guard_die "stage-generation requires --stage-transition-mode abandoned_retry|planned_workloads_progression"
    [[ "$stage_transition_mode" != "planned_workloads_progression" || "$stage" == "workloads" ]] || guard_die "planned progression is permitted only for the workloads stage"
    [[ -n "$approval_file" && -n "$var_file" && -n "$artifact_out" ]] || guard_die "stage-generation requires --approval, --var-file, and --artifact-out"
    approval_file="$(guard_absolute_path "$approval_file")"
    var_file="$(guard_absolute_path "$var_file")"
    artifact_out="$(guard_absolute_path "$artifact_out")"
    guard_outside_repository "$approval_file" "$repository_root" "private stage-generation owner approval"
    guard_outside_repository "$var_file" "$repository_root" "private replacement stage tfvars"
    guard_outside_repository "$artifact_out" "$repository_root" "sanitized stage-generation evidence"
    guard_private_file "$approval_file" "private stage-generation owner approval"
    guard_private_file "$var_file" "private replacement stage tfvars"
    guard_new_private_path "$artifact_out" "sanitized stage-generation evidence"
    (( $(wc -c <"$approval_file") <= 16384 )) || guard_die "stage-generation approval exceeds 16 KiB"
    (( $(wc -c <"$var_file") <= 32768 )) || guard_die "replacement stage tfvars exceed the 32 KiB protected transition bound"
    jq -e 'type == "object"' "$var_file" >/dev/null || guard_die "replacement --var-file must be a JSON object"
    replacement_tfvars_sha256="$(guard_sha256 "$var_file")"
    jq -e --arg source_sha "$source_sha" --arg release_id "$release_id" --arg stage "$stage" --arg mode "$stage_transition_mode" --arg replacement "$replacement_tfvars_sha256" '
      type == "object" and
      (keys | sort) == (["approved_at", "confirmation", "contract", "current_artifacts", "reason_reference", "release_id", "replacement_tfvars_sha256", "reviewer_reference", "schema_version", "source_sha", "stage", "transition_mode"] | sort) and
      .schema_version == 1 and .contract == "cosmas-os-d3-stage-generation-approval-v1" and
      .confirmation == "AUTHORIZE D3 IMMUTABLE STAGE GENERATION TRANSITION" and
      .source_sha == $source_sha and .release_id == $release_id and .stage == $stage and
      .transition_mode == $mode and .replacement_tfvars_sha256 == $replacement and
      (.approved_at | strings | test("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")) and
      (.reviewer_reference | strings | test("^[A-Za-z0-9][A-Za-z0-9._:/ -]{2,511}$")) and
      (.reason_reference | strings | test("^[A-Za-z0-9][A-Za-z0-9._:/ -]{2,511}$")) and
      ([.reviewer_reference, .reason_reference] | all(contains("@") | not)) and
      (.current_artifacts | type == "object") and
      (.current_artifacts | keys | sort) == (["approval_sha256", "environment_tfvars_sha256", "plan_sha256", "result_sha256", "review_sha256"] | sort) and
      (.current_artifacts.environment_tfvars_sha256 | strings | test("^[0-9a-f]{64}$")) and
      ([.current_artifacts.plan_sha256, .current_artifacts.review_sha256, .current_artifacts.approval_sha256, .current_artifacts.result_sha256] |
        all(. == null or (strings | test("^[0-9a-f]{64}$")))) and
      (if $mode == "planned_workloads_progression" then
         $stage == "workloads" and (.current_artifacts.result_sha256 | strings | test("^[0-9a-f]{64}$"))
       else true end)
    ' "$approval_file" >/dev/null || guard_die "stage-generation approval is not the exact current/replacement owner assertion"
    ;;
  offboarding-acceptance)
    stage="offboarding"
    [[ "$release_id" =~ ^[a-z0-9][a-z0-9-]{2,31}$ ]] || guard_die "offboarding-acceptance requires a valid --release-id"
    [[ "$offboarding_phase" == "baseline" || "$offboarding_phase" == "verify" ]] || guard_die "offboarding-acceptance requires --offboarding-phase baseline|verify"
    [[ -n "$artifact_out" ]] || guard_die "offboarding-acceptance requires --artifact-out"
    artifact_out="$(guard_absolute_path "$artifact_out")"
    guard_outside_repository "$artifact_out" "$repository_root" "sanitized offboarding evidence"
    guard_new_private_path "$artifact_out" "sanitized offboarding evidence"
    if [[ "$offboarding_phase" == "baseline" ]]; then
      [[ -n "$offboarding_request" && -z "$offboarding_state" && -z "$offboarding_confirmation" ]] || guard_die "offboarding baseline requires only --offboarding-request"
      offboarding_request="$(guard_absolute_path "$offboarding_request")"
      guard_outside_repository "$offboarding_request" "$repository_root" "private reviewed offboarding target"
      guard_private_file "$offboarding_request" "private reviewed offboarding target"
      (( $(wc -c <"$offboarding_request") <= 16384 )) || guard_die "offboarding request exceeds 16 KiB"
      jq -e '
        type == "object" and
        (keys | sort) == (["approved_at", "box_id", "clerk_issuer", "clerk_organization_id", "clerk_subject", "contract", "principal_id", "reviewer_reference", "schema_version"] | sort) and
        .schema_version == 1 and .contract == "cosmas-os-d3-offboarding-request-v1" and
        (.box_id | strings | test("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")) and
        (.clerk_issuer | strings | test("^https://[^/?#]+/?$")) and
        (.clerk_organization_id | strings | test("^org_[^[:space:]]+$")) and
        (.clerk_subject | strings | test("^user_[^[:space:]]+$")) and
        (.principal_id | strings | test("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")) and
        (.approved_at | strings | test("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")) and
        (.reviewer_reference | strings | test("^[A-Za-z0-9][A-Za-z0-9._:/ -]{2,511}$")) and
        (.reviewer_reference | contains("@") | not)
      ' "$offboarding_request" >/dev/null || guard_die "offboarding request is not an exact private synthetic target binding"
    else
      [[ -z "$offboarding_request" && -n "$offboarding_state" && -n "$offboarding_confirmation" ]] || guard_die "offboarding verify requires --offboarding-state and --offboarding-confirmation"
      offboarding_state="$(guard_absolute_path "$offboarding_state")"
      offboarding_confirmation="$(guard_absolute_path "$offboarding_confirmation")"
      guard_outside_repository "$offboarding_state" "$repository_root" "sanitized offboarding baseline state"
      guard_outside_repository "$offboarding_confirmation" "$repository_root" "private human/browser offboarding confirmation"
      guard_private_file "$offboarding_state" "sanitized offboarding baseline state"
      guard_private_file "$offboarding_confirmation" "private human/browser offboarding confirmation"
      (( $(wc -c <"$offboarding_state") <= 16384 && $(wc -c <"$offboarding_confirmation") <= 16384 )) || guard_die "offboarding verification input exceeds 16 KiB"
      jq -e 'type == "object" and .schema_version == 1 and .evidence_type == "protected-runner-offboarding-acceptance" and .offboarding_phase == "baseline" and (.offboarding_output | type == "object")' "$offboarding_state" >/dev/null || guard_die "offboarding state is not a protected baseline artifact"
      jq -e --slurpfile baseline "$offboarding_state" '
        type == "object" and
        (keys | sort) == (["baseline_evidence_sha256", "challenge", "clerk_organization_membership_removed", "clerk_sessions_revoked", "confirmation_reference", "confirmed_at", "live_access_denied", "owner_assertion", "schema_version"] | sort) and
        .schema_version == 1 and .owner_assertion == "I CONFIRM D3 CLERK OFFBOARDING AND LIVE ACCESS DENIAL" and
        .challenge == $baseline[0].offboarding_output.confirmation_challenge and
        .baseline_evidence_sha256 == $baseline[0].offboarding_output.evidence_sha256 and
        .clerk_organization_membership_removed == true and .clerk_sessions_revoked == true and .live_access_denied == true and
        (.confirmed_at | strings | test("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")) and
        (.confirmation_reference | strings | test("^[A-Za-z0-9][A-Za-z0-9._:/ -]{2,511}$")) and
        (.confirmation_reference | contains("@") | not)
      ' "$offboarding_confirmation" >/dev/null || guard_die "offboarding confirmation is not bound to the exact baseline challenge"
    fi
    ;;
  bootstrap-identity)
    stage="identity"
    [[ "$release_id" =~ ^[a-z0-9][a-z0-9-]{2,31}$ ]] || guard_die "bootstrap-identity requires a 3-32 character lowercase --release-id"
    [[ -n "$bootstrap_manifest" && -n "$artifact_out" ]] || guard_die "bootstrap-identity requires --bootstrap-manifest and --artifact-out"
    bootstrap_manifest="$(guard_absolute_path "$bootstrap_manifest")"
    artifact_out="$(guard_absolute_path "$artifact_out")"
    guard_outside_repository "$bootstrap_manifest" "$repository_root" "private reviewed beta bootstrap manifest"
    guard_outside_repository "$artifact_out" "$repository_root" "sanitized identity-bootstrap evidence"
    guard_private_file "$bootstrap_manifest" "private reviewed beta bootstrap manifest"
    guard_new_private_path "$artifact_out" "sanitized identity-bootstrap evidence"
    jq -e 'type == "object" and .schema_version == 1 and (.deployment_binding | type == "object") and (.bootstrap_manifest | type == "object")' "$bootstrap_manifest" >/dev/null || guard_die "bootstrap manifest must be a schema-version-1 protected deployment envelope"
    ;;
  retrieve)
    [[ "$release_id" =~ ^[a-z0-9][a-z0-9-]{2,31}$ ]] || guard_die "retrieve requires a 3-32 character lowercase --release-id"
    [[ "$artifact_kind" == "review" || "$artifact_kind" == "result" || "$artifact_kind" == "network" || "$artifact_kind" == "build" || "$artifact_kind" == "database" || "$artifact_kind" == "workload" || "$artifact_kind" == "runtime" || "$artifact_kind" == "domain" || "$artifact_kind" == "alert" || "$artifact_kind" == "pitr" || "$artifact_kind" == "recovery" || "$artifact_kind" == "offboarding" || "$artifact_kind" == "identity" ]] || guard_die "retrieve requires a valid --artifact-kind"
    if [[ "$artifact_kind" == "review" || "$artifact_kind" == "result" ]]; then
      [[ "$stage" == "foundation" || "$stage" == "database" || "$stage" == "workloads" ]] || guard_die "review/result retrieval requires its exact environment --stage"
    else
      case "$artifact_kind" in
        network) stage="network" ;;
        build) stage="images" ;;
        database) stage="database" ;;
        workload) stage="workload-verification" ;;
        runtime)
          stage="acceptance"
          [[ "$acceptance_phase" == "runtime" || "$acceptance_phase" == "workflow-baseline" || "$acceptance_phase" == "workflow-verify" || "$acceptance_phase" == "audit-replay" || "$acceptance_phase" == "purge-setup" || "$acceptance_phase" == "purge-verify" ]] || guard_die "runtime retrieval requires an enumerated --acceptance-phase"
          ;;
        domain) stage="domain" ;;
        alert)
          stage="alert"
          [[ "$alert_phase" == "send" || "$alert_phase" == "confirm" ]] || guard_die "alert retrieval requires --alert-phase send|confirm"
          ;;
        pitr)
          stage="pitr"
          [[ "$pitr_phase" == "freeze" || "$pitr_phase" == "manifest" || "$pitr_phase" == "start" || "$pitr_phase" == "complete" || "$pitr_phase" == "cleanup" || "$pitr_phase" == "resume" ]] || guard_die "PITR retrieval requires an enumerated --pitr-phase"
          ;;
        recovery)
          stage="recovery"
          [[ "$recovery_phase" == "rollback" || "$recovery_phase" == "forward" ]] || guard_die "release-recovery retrieval requires --recovery-phase rollback|forward"
          ;;
        offboarding)
          stage="offboarding"
          [[ "$offboarding_phase" == "baseline" || "$offboarding_phase" == "verify" ]] || guard_die "offboarding retrieval requires --offboarding-phase baseline|verify"
          ;;
        identity) stage="identity" ;;
      esac
    fi
    [[ -n "$artifact_out" ]] || guard_die "retrieve requires --artifact-out"
    artifact_out="$(guard_absolute_path "$artifact_out")"
    guard_outside_repository "$artifact_out" "$repository_root" "retrieved sanitized artifact"
    guard_new_private_path "$artifact_out" "retrieved sanitized artifact"
    ;;
  cleanup-commands)
    stage="maintenance"
    release_id="cleanup"
    ;;
  plan)
    [[ "$stage" == "foundation" || "$stage" == "database" || "$stage" == "workloads" ]] || guard_die "plan requires a valid --stage"
    [[ "$release_id" =~ ^[a-z0-9][a-z0-9-]{2,31}$ ]] || guard_die "plan requires a 3-32 character lowercase --release-id"
    [[ -n "$artifact_out" ]] || guard_die "plan requires --artifact-out"
    artifact_out="$(guard_absolute_path "$artifact_out")"
    guard_outside_repository "$artifact_out" "$repository_root" "sanitized review artifact"
    guard_new_private_path "$artifact_out" "sanitized review artifact"
    ;;
  apply)
    [[ "$stage" == "foundation" || "$stage" == "database" || "$stage" == "workloads" ]] || guard_die "apply requires a valid --stage"
    [[ "$release_id" =~ ^[a-z0-9][a-z0-9-]{2,31}$ ]] || guard_die "apply requires a 3-32 character lowercase --release-id"
    [[ -n "$approval_file" && -n "$approval_bundle" && -n "$artifact_out" ]] || guard_die "apply requires --approval, --approval-bundle, and --artifact-out"
    approval_file="$(guard_absolute_path "$approval_file")"
    approval_bundle="$(guard_absolute_path "$approval_bundle")"
    artifact_out="$(guard_absolute_path "$artifact_out")"
    guard_outside_repository "$approval_file" "$repository_root" "private approval"
    guard_outside_repository "$approval_bundle" "$repository_root" "private approval bundle"
    guard_outside_repository "$artifact_out" "$repository_root" "sanitized result artifact"
    guard_private_directory "$approval_bundle" "private approval bundle"
    guard_private_file "$approval_file" "private approval"
    [[ "$approval_file" == "$approval_bundle/source-approval.json" ]] || guard_die "--approval must be the fixed source-approval.json inside --approval-bundle"
    for approval_name in approval-request.json owner-authorization.json claim.json source-approval.json manifest.json; do
      guard_private_file "$approval_bundle/$approval_name" "private approval bundle file $approval_name"
    done
    guard_new_private_path "$artifact_out" "sanitized result artifact"
    approval_plan_sha="$(jq -er '.plan_sha256 | strings' "$approval_file")" || guard_die "approval plan hash is unavailable"
    approval_review_sha="$(jq -er '.review_sha256 | strings' "$approval_file")" || guard_die "approval review hash is unavailable"
    approval_var_sha="$(jq -er '.variable_file_sha256 | strings' "$approval_file")" || guard_die "approval variable-file hash is unavailable"
    approval_state_exists="$(jq -er '.state.exists | booleans' "$approval_file")" || guard_die "approval state flag is unavailable"
    approval_state_lineage="$(jq -r 'if .state.lineage == null then "" else .state.lineage end' "$approval_file")"
    approval_state_serial="$(jq -r 'if .state.serial == null then "null" else (.state.serial | tostring) end' "$approval_file")"
    approval_state_sha="$(jq -r 'if .state.sha256 == null then "" else .state.sha256 end' "$approval_file")"
    guard_validate_apply_approval "$approval_file" "$approval_bundle" "$source_sha" "$release_id" "$stage" \
      "$approval_plan_sha" "$approval_review_sha" "$approval_var_sha" "$approval_state_exists" \
      "$approval_state_lineage" "$approval_state_serial" "$approval_state_sha"
    ;;
esac

account_json="$(az account show --only-show-errors --output json)" || guard_die "Azure account context is unavailable"
[[ "$(guard_lower "$(jq -er '.id' <<<"$account_json")")" == "$(guard_lower "$GUARD_SUBSCRIPTION_ID")" ]] || guard_die "active subscription does not match bootstrap output"
[[ "$(guard_lower "$(jq -er '.tenantId' <<<"$account_json")")" == "$(guard_lower "$GUARD_TENANT_ID")" ]] || guard_die "active tenant does not match bootstrap output"

for boundary_group in "$GUARD_STATE_RESOURCE_GROUP" "$GUARD_WORKLOAD_RESOURCE_GROUP"; do
  group_json="$(az group show --subscription "$GUARD_SUBSCRIPTION_ID" --name "$boundary_group" --only-show-errors --output json)" || guard_die "cannot read boundary resource group $boundary_group"
  jq -e \
    --arg group "$(guard_lower "$boundary_group")" \
    --arg subscription "$(guard_lower "$GUARD_SUBSCRIPTION_ID")" \
    --arg location "centralus" \
    --arg mode "$GUARD_DEPLOYMENT_MODE" \
    --arg classification "$GUARD_DATA_CLASSIFICATION" \
    --arg box "$GUARD_BOX_ID" '
      (.id | ascii_downcase) == ("/subscriptions/" + $subscription + "/resourcegroups/" + $group) and
      ((.location // "") | ascii_downcase) == $location and
      .tags.track == "B" and .tags.product == "cosmas-os" and .tags.env == "early_adopter_beta" and
      .tags.deployment_mode == $mode and .tags.data_classification == $classification and
      .tags.box_scope == "dedicated" and .tags.box_id == $box and .tags.managed == "terraform"
    ' <<<"$group_json" >/dev/null || guard_die "resource group $boundary_group drifted outside the exact D3 mode/Box boundary"
done

runner_id="/subscriptions/$GUARD_SUBSCRIPTION_ID/resourceGroups/$GUARD_STATE_RESOURCE_GROUP/providers/Microsoft.Compute/virtualMachines/$GUARD_RUNNER_VM_NAME"
deploy_identity_id="/subscriptions/$GUARD_SUBSCRIPTION_ID/resourceGroups/$GUARD_STATE_RESOURCE_GROUP/providers/Microsoft.ManagedIdentity/userAssignedIdentities/$GUARD_DEPLOY_IDENTITY_NAME"
identity_json="$(az identity show --ids "$deploy_identity_id" --only-show-errors --output json)" || guard_die "cannot read exact deploy identity"
jq -e \
  --arg identity_id "$(guard_lower "$deploy_identity_id")" \
  --arg client_id "$(guard_lower "$GUARD_DEPLOY_CLIENT_ID")" \
  --arg principal_id "$(guard_lower "$GUARD_DEPLOY_PRINCIPAL_ID")" '
    (.id | ascii_downcase) == $identity_id and
    (.clientId | ascii_downcase) == $client_id and
    (.principalId | ascii_downcase) == $principal_id
  ' <<<"$identity_json" >/dev/null || guard_die "deploy identity differs from bootstrap output"

role_json="$(az role assignment list --assignee-object-id "$GUARD_DEPLOY_PRINCIPAL_ID" --all --include-inherited --fill-principal-name false --only-show-errors --output json)" || guard_die "cannot read deploy identity RBAC"
workload_rg_id="/subscriptions/$GUARD_SUBSCRIPTION_ID/resourceGroups/$GUARD_WORKLOAD_RESOURCE_GROUP"
state_rg_id="/subscriptions/$GUARD_SUBSCRIPTION_ID/resourceGroups/$GUARD_STATE_RESOURCE_GROUP"
state_storage_id="$state_rg_id/providers/Microsoft.Storage/storageAccounts/$GUARD_STATE_STORAGE_ACCOUNT"
jq -e \
  --arg workload_rg "$(guard_lower "$workload_rg_id")" \
  --arg state_rg "$(guard_lower "$state_rg_id")" \
  --arg storage "$(guard_lower "$state_storage_id")" \
  --arg state_vnet "$(guard_lower "$GUARD_STATE_VNET_ID")" \
  --arg state_dns "$(guard_lower "$GUARD_STATE_BLOB_PRIVATE_DNS_ZONE_ID")" '
    [ .[] | {scope: (.scope | ascii_downcase), role: .roleDefinitionName} ] as $actual |
    ($actual | all(
      (.scope == $state_rg and .role == "Reader") or
      (.scope == $workload_rg and (.role == "Contributor" or .role == "User Access Administrator")) or
      (.scope == $storage and .role == "Storage Blob Data Contributor") or
      (.scope == $state_vnet and .role == "Network Contributor") or
      (.scope == $state_dns and .role == "Private DNS Zone Contributor") or
      ((.scope | startswith($workload_rg + "/")) and
        (.role == "AcrPush" or .role == "Storage Blob Data Contributor" or .role == "Key Vault Secrets Officer"))
    )) and
    ($actual | any(.scope == $workload_rg and .role == "Contributor")) and
    ($actual | any(.scope == $workload_rg and .role == "User Access Administrator")) and
    ($actual | any(.scope == $state_rg and .role == "Reader")) and
    ($actual | any(.scope == $storage and .role == "Storage Blob Data Contributor")) and
    ($actual | any(.scope == $state_vnet and .role == "Network Contributor")) and
    ($actual | any(.scope == $state_dns and .role == "Private DNS Zone Contributor"))
  ' <<<"$role_json" >/dev/null || guard_die "deploy identity RBAC is missing a required scope or extends beyond the two D3 resource groups"

federated_credentials_json="$(az identity federated-credential list --identity-name "$GUARD_DEPLOY_IDENTITY_NAME" --resource-group "$GUARD_STATE_RESOURCE_GROUP" --only-show-errors --output json)" || guard_die "cannot inspect deploy identity federated credentials"
jq -e 'length == 0' <<<"$federated_credentials_json" >/dev/null || guard_die "deploy identity has a forbidden federated credential; D3 permits VM-attached UAMI only"

vm_json="$(az vm show --ids "$runner_id" --only-show-errors --output json)" || guard_die "cannot read protected runner"
runner_location="$(jq -er '.location' <<<"$vm_json")"
jq -e \
  --arg identity_id "$(guard_lower "$deploy_identity_id")" \
  --arg image_version "$GUARD_RUNNER_IMAGE_VERSION" '
    .securityProfile.securityType == "TrustedLaunch" and
    .securityProfile.uefiSettings.secureBootEnabled == true and
    .securityProfile.uefiSettings.vTpmEnabled == true and
    .hardwareProfile.vmSize == "Standard_B2s" and
    .osProfile.linuxConfiguration.disablePasswordAuthentication == true and
    .storageProfile.imageReference.publisher == "Canonical" and
    .storageProfile.imageReference.offer == "0001-com-ubuntu-server-jammy" and
    .storageProfile.imageReference.sku == "22_04-lts-gen2" and
    ((.storageProfile.imageReference.version // .storageProfile.imageReference.exactVersion) == $image_version) and
    .identity.type == "UserAssigned" and
    ((.identity.userAssignedIdentities | keys | map(ascii_downcase)) == [$identity_id]) and
    ([.networkProfile.networkInterfaces[]?.id] | length == 1)
  ' <<<"$vm_json" >/dev/null || guard_die "runner image, Trusted Launch, or exact UAMI boundary drifted"

nic_id="$(jq -er '.networkProfile.networkInterfaces[0].id' <<<"$vm_json")"
nic_json="$(az network nic show --ids "$nic_id" --only-show-errors --output json)" || guard_die "cannot read runner NIC"
jq -e --arg subnet_id "$(guard_lower "$GUARD_RUNNER_SUBNET_ID")" '
  (.ipConfigurations | length) == 1 and
  ([.ipConfigurations[]? | select(.publicIPAddress != null)] | length == 0) and
  (.ipConfigurations[0].subnet.id | ascii_downcase) == $subnet_id
' <<<"$nic_json" >/dev/null || guard_die "runner NIC is not private-only in the exact subnet"

subnet_json="$(az network vnet subnet show --ids "$GUARD_RUNNER_SUBNET_ID" --only-show-errors --output json)" || guard_die "cannot read runner subnet"
jq -e \
  --arg nsg_id "$(guard_lower "$GUARD_RUNNER_NSG_ID")" \
  --arg nat_id "$(guard_lower "$GUARD_RUNNER_NAT_GATEWAY_ID")" '
    .defaultOutboundAccess == false and
    (.networkSecurityGroup.id | ascii_downcase) == $nsg_id and
    (.natGateway.id | ascii_downcase) == $nat_id
  ' <<<"$subnet_json" >/dev/null || guard_die "runner subnet lost its reviewed NSG/NAT/default-outbound boundary"

nsg_json="$(az network nsg show --ids "$GUARD_RUNNER_NSG_ID" --only-show-errors --output json)" || guard_die "cannot read runner NSG"
jq -e '
  def rule($name): first(.securityRules[] | select(.name == $name));
  (.securityRules | length) == 8 and
  (rule("AllowPrivateDeploymentPorts") | .priority == 100 and .direction == "Outbound" and .access == "Allow" and .protocol == "Tcp" and .sourcePortRange == "*" and .sourceAddressPrefix == "VirtualNetwork" and .destinationAddressPrefix == "VirtualNetwork" and (.destinationPortRanges | sort) == (["10000", "443", "5432"] | sort)) and
  (rule("AllowAzureInstanceMetadata") | .priority == 105 and .direction == "Outbound" and .access == "Allow" and .protocol == "Tcp" and .sourcePortRange == "*" and .destinationPortRange == "80" and .sourceAddressPrefix == "*" and .destinationAddressPrefix == "169.254.169.254") and
  (rule("AllowAzureWireServer") | .priority == 106 and .direction == "Outbound" and .access == "Allow" and .protocol == "Tcp" and .sourcePortRange == "*" and (.destinationPortRanges | sort) == (["80", "32526"] | sort) and .sourceAddressPrefix == "*" and .destinationAddressPrefix == "168.63.129.16") and
  (rule("AllowAzureDnsUdp") | .priority == 110 and .direction == "Outbound" and .access == "Allow" and .protocol == "Udp" and .sourcePortRange == "*" and .destinationPortRange == "53" and .sourceAddressPrefix == "*" and .destinationAddressPrefix == "168.63.129.16") and
  (rule("AllowAzureDnsTcp") | .priority == 120 and .direction == "Outbound" and .access == "Allow" and .protocol == "Tcp" and .sourcePortRange == "*" and .destinationPortRange == "53" and .sourceAddressPrefix == "*" and .destinationAddressPrefix == "168.63.129.16") and
  (rule("AllowHttpsEgress") | .priority == 130 and .direction == "Outbound" and .access == "Allow" and .protocol == "Tcp" and .sourcePortRange == "*" and .destinationPortRange == "443" and .sourceAddressPrefix == "*" and .destinationAddressPrefix == "Internet") and
  (rule("DenyOtherOutbound") | .priority == 4095 and .direction == "Outbound" and .access == "Deny" and .protocol == "*" and .sourcePortRange == "*" and .destinationPortRange == "*" and .sourceAddressPrefix == "*" and .destinationAddressPrefix == "*") and
  (rule("DenyAllInbound") | .priority == 4096 and .direction == "Inbound" and .access == "Deny" and .protocol == "*" and .sourcePortRange == "*" and .destinationPortRange == "*" and .sourceAddressPrefix == "*" and .destinationAddressPrefix == "*")
' <<<"$nsg_json" >/dev/null || guard_die "runner NSG differs from the reviewed no-inbound/HTTPS-only rules"

nat_json="$(az network nat gateway show --ids "$GUARD_RUNNER_NAT_GATEWAY_ID" --only-show-errors --output json)" || guard_die "cannot read runner NAT gateway"
jq -e --arg public_ip_id "$(guard_lower "$GUARD_RUNNER_EGRESS_PUBLIC_IP_ID")" '
  .sku.name == "Standard" and (.publicIpAddresses | length) == 1 and
  (.publicIpAddresses[0].id | ascii_downcase) == $public_ip_id
' <<<"$nat_json" >/dev/null || guard_die "runner NAT gateway differs from the reviewed dedicated egress boundary"

public_ip_json="$(az network public-ip show --ids "$GUARD_RUNNER_EGRESS_PUBLIC_IP_ID" --only-show-errors --output json)" || guard_die "cannot read runner NAT public IP"
jq -e '.sku.name == "Standard" and .publicIPAllocationMethod == "Static" and .publicIPAddressVersion == "IPv4"' <<<"$public_ip_json" >/dev/null || guard_die "runner egress IP is not dedicated Standard/Static IPv4"

storage_json="$(az storage account show --subscription "$GUARD_SUBSCRIPTION_ID" --resource-group "$GUARD_STATE_RESOURCE_GROUP" --name "$GUARD_STATE_STORAGE_ACCOUNT" --only-show-errors --output json)" || guard_die "cannot read private state storage account"
jq -e '
  .publicNetworkAccess == "Disabled" and .allowSharedKeyAccess == false and
  .defaultToOAuthAuthentication == true and .minimumTlsVersion == "TLS1_2"
' <<<"$storage_json" >/dev/null || guard_die "state storage lost its private Azure-AD-only boundary"

managed_run_command_api_version="2024-07-01"
managed_run_command_cleanup_attempts=12
managed_run_command_cleanup_retry_seconds=5
managed_run_command_cleanup_failure_status=74

if [[ "$operation" == "cleanup-commands" ]]; then
  command_list_file="$transport_temp_dir/run-command-list.json"
  stale_command_ids_file="$transport_temp_dir/run-command-ids"
  managed_run_command_read_inventory "$runner_id" "$managed_run_command_api_version" "$command_list_file" || guard_die "cannot enumerate a complete managed Run Command inventory on the exact protected runner"
  jq -r '
    .value[]?.id |
    select((split("/") | last | ascii_downcase) | test("^cosmas-d3-[a-z0-9-]+$"))
  ' "$command_list_file" >"$stale_command_ids_file"
  chmod 0600 "$stale_command_ids_file"
  removed_count=0
  active_count=0
  while IFS= read -r stale_command_id; do
    [[ "${stale_command_id,,}" == "${runner_id,,}/runcommands/cosmas-d3-"* ]] || guard_die "managed Run Command enumeration escaped the exact protected runner/prefix"
    stale_view_file="$transport_temp_dir/stale-view-$removed_count-$active_count.json"
    if ! managed_run_command_show_instance "$runner_id" "$stale_command_id" "$stale_view_file" 2>/dev/null; then
      guard_die "cannot verify terminal state for a stale protected Run Command"
    fi
    provisioning_state="$(jq -r '.provisioningState // .properties.provisioningState // ""' "$stale_view_file")"
    execution_state="$(jq -r '.instanceView.executionState // .properties.instanceView.executionState // ""' "$stale_view_file")"
    rm -f -- "$stale_view_file" || guard_die "cannot remove local stale-command result material"
    if [[ "$execution_state" == "Succeeded" || "$execution_state" == "Failed" || "$execution_state" == "Canceled" || "$execution_state" == "TimedOut" ]]; then
      [[ "$provisioning_state" == "Succeeded" || "$provisioning_state" == "Failed" || "$provisioning_state" == "Canceled" ]] || guard_die "stale command has a terminal execution but nonterminal provisioning state"
      if ! managed_run_command_delete_and_verify_absent \
        "$runner_id" \
        "$stale_command_id" \
        "$managed_run_command_api_version" \
        "$transport_temp_dir" \
        "$managed_run_command_cleanup_attempts" \
        "$managed_run_command_cleanup_retry_seconds" \
        false; then
        printf '%s\n' 'D3 protected transport cleanup failed closed: a terminal managed Run Command could not be proven absent after bounded deletion/readback retries' >&2
        exit "$managed_run_command_cleanup_failure_status"
      fi
      ((removed_count += 1))
    else
      ((active_count += 1))
    fi
  done <"$stale_command_ids_file"
  (( active_count == 0 )) || guard_die "$active_count protected Run Command resource(s) are still active; wait for terminal state before cleanup"
  printf 'Removed %s terminal protected Run Command resource(s); no protected output was read.\n' "$removed_count"
  exit 0
fi

payload_file="$transport_temp_dir/protected-payload"
payload_b64_file="$transport_temp_dir/protected-payload-b64"
request_file="$transport_temp_dir/run-command-request.json"
view_file="$transport_temp_dir/run-command-view.json"
touch "$payload_file" "$payload_b64_file" "$request_file" "$view_file"
run_command_name="cosmas-d3-$(date -u '+%Y%m%d%H%M%S')-$$"
run_command_id="$runner_id/runCommands/$run_command_name"
command_cleanup_required=false
command_cleanup_attempted=false
command_submission_acknowledged=false
trap transport_cleanup_on_exit EXIT
transport_install_signal_traps
chmod 600 "$payload_file" "$payload_b64_file" "$request_file" "$view_file"

case "$operation" in
  stage-source)
    jq -n --arg prior_source_sha "$prior_source_sha" --rawfile deploy_key "$deploy_key" --rawfile known_hosts "$known_hosts" \
      '{deploy_key_base64: ($deploy_key | @base64), known_hosts_base64: ($known_hosts | @base64), prior_source_sha: (if $prior_source_sha == "" then null else $prior_source_sha end)}' >"$payload_file"
    ;;
  stage-vars) install -m 0600 "$var_file" "$payload_file" ;;
  inspect-stage) printf '{}' >"$payload_file" ;;
  stage-generation)
    jq -n --arg transition_mode "$stage_transition_mode" --rawfile replacement_tfvars "$var_file" --slurpfile owner_approval "$approval_file" \
      '{transition_mode: $transition_mode, replacement_tfvars_base64: ($replacement_tfvars | @base64), owner_approval: $owner_approval[0]}' >"$payload_file"
    ;;
  build-push) install -m 0600 "$web_build_config" "$payload_file" ;;
  bootstrap-identity) install -m 0600 "$bootstrap_manifest" "$payload_file" ;;
  retrieve)
    if [[ "$artifact_kind" == "runtime" ]]; then
      jq -n --arg artifact_kind "$artifact_kind" --arg acceptance_phase "$acceptance_phase" '{artifact_kind: $artifact_kind, acceptance_phase: $acceptance_phase}' >"$payload_file"
    elif [[ "$artifact_kind" == "alert" ]]; then
      jq -n --arg artifact_kind "$artifact_kind" --arg alert_phase "$alert_phase" '{artifact_kind: $artifact_kind, alert_phase: $alert_phase}' >"$payload_file"
    elif [[ "$artifact_kind" == "pitr" ]]; then
      jq -n --arg artifact_kind "$artifact_kind" --arg pitr_phase "$pitr_phase" '{artifact_kind: $artifact_kind, pitr_phase: $pitr_phase}' >"$payload_file"
    elif [[ "$artifact_kind" == "recovery" ]]; then
      jq -n --arg artifact_kind "$artifact_kind" --arg recovery_phase "$recovery_phase" '{artifact_kind: $artifact_kind, recovery_phase: $recovery_phase}' >"$payload_file"
    elif [[ "$artifact_kind" == "offboarding" ]]; then
      jq -n --arg artifact_kind "$artifact_kind" --arg offboarding_phase "$offboarding_phase" '{artifact_kind: $artifact_kind, offboarding_phase: $offboarding_phase}' >"$payload_file"
    else
      jq -n --arg artifact_kind "$artifact_kind" '{artifact_kind: $artifact_kind}' >"$payload_file"
    fi
    ;;
  runtime-acceptance)
    if [[ -n "$acceptance_state" ]]; then
      jq -n --arg acceptance_phase "$acceptance_phase" --slurpfile prior_attestation "$acceptance_state" \
        '{acceptance_phase: $acceptance_phase, prior_attestation: $prior_attestation[0]}' >"$payload_file"
    else
      jq -n --arg acceptance_phase "$acceptance_phase" '{acceptance_phase: $acceptance_phase}' >"$payload_file"
    fi
    ;;
  alert-delivery)
    if [[ "$alert_phase" == "confirm" ]]; then
      jq -n --arg alert_phase "$alert_phase" --slurpfile prior_attestation "$alert_test_state" --slurpfile confirmation "$delivery_confirmation_reference" \
        '{alert_phase: $alert_phase, prior_attestation: $prior_attestation[0], confirmation: $confirmation[0]}' >"$payload_file"
    elif [[ -n "$alert_retry_approval" ]]; then
      jq -n --arg alert_phase "$alert_phase" --slurpfile ambiguous_retry_approval "$alert_retry_approval" \
        '{alert_phase: $alert_phase, ambiguous_retry_approval: $ambiguous_retry_approval[0]}' >"$payload_file"
    else
      jq -n --arg alert_phase "$alert_phase" '{alert_phase: $alert_phase}' >"$payload_file"
    fi
    ;;
  pitr-freeze)
    jq -n --arg pitr_phase "$pitr_phase" --arg quiet_window_end_utc "$quiet_window_end_utc" \
      '{pitr_phase: $pitr_phase, quiet_window_end_utc: $quiet_window_end_utc}' >"$payload_file"
    ;;
  pitr-manifest)
    jq -n --arg pitr_phase "$pitr_phase" --arg restore_time_utc "$restore_time_utc" --rawfile preparer_reference "$pitr_preparer_reference" \
      '{pitr_phase: $pitr_phase, restore_time_utc: $restore_time_utc, preparer_reference: ($preparer_reference | rtrimstr("\n"))}' >"$payload_file"
    ;;
  pitr-start|pitr-complete|pitr-cleanup|pitr-resume)
    jq -n --arg pitr_phase "$pitr_phase" --slurpfile owner_approval "$approval_file" \
      '{pitr_phase: $pitr_phase, owner_approval: $owner_approval[0]}' >"$payload_file"
    ;;
  release-rollback|release-forward)
    jq -n --arg recovery_phase "$recovery_phase" --arg prior_source_sha "$prior_source_sha" --arg prior_release_id "$prior_release_id" --slurpfile owner_approval "$approval_file" \
      '{recovery_phase: $recovery_phase, prior_source_sha: $prior_source_sha, prior_release_id: $prior_release_id, owner_approval: $owner_approval[0]}' >"$payload_file"
    ;;
  offboarding-acceptance)
    if [[ "$offboarding_phase" == "baseline" ]]; then
      jq -n --arg offboarding_phase "$offboarding_phase" --slurpfile offboarding_request "$offboarding_request" \
        '{offboarding_phase: $offboarding_phase, offboarding_request: $offboarding_request[0]}' >"$payload_file"
    else
      jq -n --arg offboarding_phase "$offboarding_phase" --slurpfile prior_attestation "$offboarding_state" --slurpfile owner_confirmation "$offboarding_confirmation" \
        '{offboarding_phase: $offboarding_phase, prior_attestation: $prior_attestation[0], owner_confirmation: $owner_confirmation[0]}' >"$payload_file"
    fi
    ;;
  plan|probe-network|database-prepare|workload-verify|domain-verification) printf '{}' >"$payload_file" ;;
  apply)
    jq -n \
      --rawfile approval_request "$approval_bundle/approval-request.json" \
      --rawfile owner_authorization "$approval_bundle/owner-authorization.json" \
      --rawfile authorization_claim "$approval_bundle/claim.json" \
      --rawfile source_approval "$approval_bundle/source-approval.json" \
      --rawfile authorization_manifest "$approval_bundle/manifest.json" '
        {
          contract: "cosmas-os-d3-protected-apply-bundle-transport-v1",
          files: {
            "approval-request.json": ($approval_request | @base64),
            "owner-authorization.json": ($owner_authorization | @base64),
            "claim.json": ($authorization_claim | @base64),
            "source-approval.json": ($source_approval | @base64),
            "manifest.json": ($authorization_manifest | @base64)
          }
        }
      ' >"$payload_file"
    ;;
esac
(( $(wc -c <"$payload_file") <= 393216 )) || guard_die "protected payload exceeds 384 KiB"
base64 <"$payload_file" | tr -d '\n' >"$payload_b64_file"

jq -n \
  --arg location "$runner_location" \
  --rawfile script "$command_launcher_file" \
  --arg subscription_id "$GUARD_SUBSCRIPTION_ID" \
  --arg deploy_client_id "$GUARD_DEPLOY_CLIENT_ID" \
  --arg operation "$operation" \
  --arg stage "$stage" \
  --arg release_id "$release_id" \
  --arg source_sha "$source_sha" \
  --arg command_sha256 "$command_script_sha256" \
  --arg resident_command_sha256 "$resident_command_sha256" \
  --rawfile protected_command "$command_script_bzip2_b64_file" \
  --rawfile protected_payload "$payload_b64_file" '
    {
      location: $location,
      properties: {
        source: {script: $script},
        parameters: [
          {name: "COSMAS_SUBSCRIPTION_ID", value: $subscription_id},
          {name: "COSMAS_DEPLOY_CLIENT_ID", value: $deploy_client_id},
          {name: "COSMAS_OPERATION", value: $operation},
          {name: "COSMAS_STAGE", value: $stage},
          {name: "COSMAS_RELEASE_ID", value: $release_id},
          {name: "COSMAS_SOURCE_SHA", value: $source_sha},
          {name: "COSMAS_COMMAND_SHA256", value: $command_sha256},
          {name: "COSMAS_RESIDENT_COMMAND_SHA256", value: $resident_command_sha256}
        ],
        protectedParameters: [
          {name: "COSMAS_COMMAND_BZIP2_BASE64", value: $protected_command},
          {name: "COSMAS_PROTECTED_PAYLOAD_BASE64", value: $protected_payload}
        ],
        asyncExecution: false,
        timeoutInSeconds: 5400
      }
    }
  ' >"$request_file"

command_cleanup_required=true
if az rest \
  --method put \
  --url "https://management.azure.com${run_command_id}?api-version=${managed_run_command_api_version}" \
  --body @"$request_file" \
  --only-show-errors \
  --output none; then
  command_submission_acknowledged=true
else
  guard_die "Azure rejected the protected managed Run Command"
fi
rm -f -- "$payload_file" "$payload_b64_file" "$request_file" || guard_die "cannot remove local protected Run Command request material"

execution_state=""
provisioning_state=""
for _ in $(seq 1 90); do
  if managed_run_command_show_instance "$runner_id" "$run_command_id" "$view_file" 2>/dev/null; then
    provisioning_state="$(jq -r '.provisioningState // .properties.provisioningState // ""' "$view_file")"
    execution_state="$(jq -r '.instanceView.executionState // .properties.instanceView.executionState // ""' "$view_file")"
    if [[ "$execution_state" == "Succeeded" && "$provisioning_state" == "Succeeded" ]]; then
      break
    fi
    if [[ "$execution_state" == "Failed" || "$execution_state" == "Canceled" || "$execution_state" == "TimedOut" || "$provisioning_state" == "Failed" || "$provisioning_state" == "Canceled" ]]; then
      guard_die "protected runner command failed; no raw output was returned because it may be sensitive"
    fi
  fi
  sleep 60
done
[[ "$execution_state" == "Succeeded" && "$provisioning_state" == "Succeeded" ]] || guard_die "protected runner command did not succeed within 90 minutes"

command_output=""
if [[ "$operation" == "plan" || "$operation" == "apply" || "$operation" == "probe-network" || "$operation" == "build-push" || "$operation" == "database-prepare" || "$operation" == "workload-verify" || "$operation" == "runtime-acceptance" || "$operation" == "domain-verification" || "$operation" == "alert-delivery" || "$operation" == pitr-* || "$operation" == "release-rollback" || "$operation" == "release-forward" || "$operation" == "inspect-stage" || "$operation" == "stage-generation" || "$operation" == "offboarding-acceptance" || "$operation" == "bootstrap-identity" || "$operation" == "retrieve" ]]; then
  command_output="$(jq -r '.instanceView.output // .properties.instanceView.output // ""' "$view_file")"
fi
rm -f -- "$view_file" || guard_die "cannot remove local protected Run Command result material"

# Once any required result has been copied into local protected memory, remove
# the managed Run Command before parsing or reporting success. Signal handlers
# are deferred during this bounded critical section. After absence is proven,
# the first deferred signal is returned with its canonical shell status.
if ! transport_complete_managed_command_cleanup; then
  printf '%s\n' 'D3 protected transport cleanup failed closed: the exact managed Run Command could not be proven absent after bounded deletion/readback retries' >&2
  exit "$managed_run_command_cleanup_failure_status"
fi

if [[ "$operation" == "plan" || "$operation" == "apply" || "$operation" == "probe-network" || "$operation" == "build-push" || "$operation" == "database-prepare" || "$operation" == "workload-verify" || "$operation" == "runtime-acceptance" || "$operation" == "domain-verification" || "$operation" == "alert-delivery" || "$operation" == pitr-* || "$operation" == "release-rollback" || "$operation" == "release-forward" || "$operation" == "inspect-stage" || "$operation" == "stage-generation" || "$operation" == "offboarding-acceptance" || "$operation" == "bootstrap-identity" || "$operation" == "retrieve" ]]; then
  artifact_base64="$(awk -F= '/^COSMAS_SANITIZED_ARTIFACT_B64=/{sub(/^COSMAS_SANITIZED_ARTIFACT_B64=/, ""); print; exit}' <<<"$command_output")"
  [[ "$artifact_base64" =~ ^[A-Za-z0-9+/=]+$ ]] || guard_die "protected runner did not return a complete sanitized artifact"
  artifact_destination="$artifact_out"
  artifact_staging="$(mktemp "$(dirname -- "$artifact_destination")/.$(basename -- "$artifact_destination").partial.XXXXXX")"
  chmod 0600 "$artifact_staging"
  artifact_out="$artifact_staging"
  printf '%s' "$artifact_base64" | base64 --decode | gzip -d >"$artifact_out" || {
    rm -f -- "$artifact_out"
    guard_die "sanitized artifact could not be decoded"
  }
  chmod 600 "$artifact_out"
  jq -e 'type == "object" and .schema_version == 1' "$artifact_out" >/dev/null || {
    rm -f -- "$artifact_out"
    guard_die "returned artifact is not a schema-version-1 sanitized object"
  }
  if guard_operation_returns_hashed_evidence "$operation" "$artifact_kind"; then
    if [[ "$operation" == "inspect-stage" || "$operation" == "stage-generation" || "$operation" == "workload-verify" || ( "$operation" == "retrieve" && "$artifact_kind" == "workload" ) ]]; then
      evidence_hash_valid=false
      if guard_validate_python_sanitized_evidence_hash "$artifact_out"; then
        evidence_hash_valid=true
      fi
    else
      evidence_hash_valid=false
      if guard_validate_sanitized_evidence_hash "$artifact_out"; then
        evidence_hash_valid=true
      fi
    fi
    if [[ "$evidence_hash_valid" != true ]]; then
      rm -f -- "$artifact_out"
      guard_die "returned evidence hash does not match its canonical payload"
    fi
    expected_evidence_hash="$GUARD_EVIDENCE_PAYLOAD_SHA256"
    if [[ "$operation" == "probe-network" || ( "$operation" == "retrieve" && "$artifact_kind" == "network" ) ]]; then
      guard_validate_network_public_configuration "$artifact_out" "$source_sha" "$release_id" "$GUARD_BETA_ID"
    fi
    if [[ "$operation" == "probe-network" ]]; then
      printf 'Use runner_live_network_evidence_reference=runner-network:sha256:%s for this exact release/state; the sanitized artifact contains the foundation-derived public origins.\n' "$expected_evidence_hash"
    elif [[ "$operation" == "build-push" ]]; then
      printf 'Accepted immutable API/web digests are recorded in build evidence sha256:%s.\n' "$expected_evidence_hash"
    elif [[ "$operation" == "database-prepare" ]]; then
      printf 'Structured database_preparation_attestation is recorded in evidence sha256:%s.\n' "$expected_evidence_hash"
    elif [[ "$operation" == "workload-verify" ]]; then
      jq -e '.contract == "cosmas-os-d3-workload-verification-v1" and .status == "verified" and .exact_revisions_and_images_verified == true and .exact_runtime_configuration_verified == true and .managed_environment_verified == true and .single_revision_traffic_verified == true and .api_ready_verified == true and .web_health_verified == true and .worker_probe_configuration_verified == true and .worker_private_and_ready == true and .synthetic_box_id_returned == true and .person_or_patient_identifiers_returned == false and .secrets_returned == false' "$artifact_out" >/dev/null || {
        rm -f -- "$artifact_out"
        guard_die "returned workload-verification artifact is invalid"
      }
      printf 'Exact deployed workload verification is recorded in evidence sha256:%s.\n' "$expected_evidence_hash"
    elif [[ "$operation" == "runtime-acceptance" ]]; then
      jq -e --arg phase "$acceptance_phase" '.evidence_type == "protected-runner-runtime-acceptance" and .acceptance_phase == $phase' "$artifact_out" >/dev/null || {
        rm -f -- "$artifact_out"
        guard_die "returned runtime-acceptance artifact differs from the requested phase"
      }
      printf 'Synthetic runtime-UAMI dependency acceptance is recorded in evidence sha256:%s.\n' "$expected_evidence_hash"
    elif [[ "$operation" == "domain-verification" ]]; then
      guard_validate_domain_verification_artifact "$artifact_out" "$source_sha" "$release_id"
      printf 'State-bound public DNS verification material is recorded in evidence sha256:%s.\n' "$expected_evidence_hash"
    elif [[ "$operation" == "alert-delivery" ]]; then
      jq -e --arg phase "$alert_phase" '
        .alert_phase == $phase and .recipient_address_returned == false and .secrets_returned == false and
        if $phase == "inspect-intent" then
          .evidence_type == "protected-runner-alert-send-intent-inspection" and
          (.intent_sha256 | strings | test("^[0-9a-f]{64}$")) and
          (.client_request_id_sha256 | strings | test("^[0-9a-f]{64}$")) and
          (.intent_resolved | type == "boolean") and (.retry_authorization_required | type == "boolean") and
          .identifiers_returned == false
        else
          .evidence_type == "protected-runner-alert-delivery"
        end
      ' "$artifact_out" >/dev/null || {
        rm -f -- "$artifact_out"
        guard_die "returned alert-delivery artifact differs from the requested PHI-safe phase"
      }
      printf 'PHI-safe alert delivery %s evidence is recorded as sha256:%s.\n' "$alert_phase" "$expected_evidence_hash"
    elif [[ "$operation" == pitr-* ]]; then
      jq -e --arg phase "$pitr_phase" '.evidence_type == "protected-runner-pitr" and .pitr_phase == $phase and .secrets_returned == false' "$artifact_out" >/dev/null || {
        rm -f -- "$artifact_out"
        guard_die "returned PITR artifact differs from the requested protected phase"
      }
      printf 'Protected PITR %s evidence is recorded as sha256:%s.\n' "$pitr_phase" "$expected_evidence_hash"
    elif [[ "$operation" == "release-rollback" || "$operation" == "release-forward" ]]; then
      jq -e --arg phase "$recovery_phase" '.evidence_type == "protected-runner-release-recovery" and .recovery_phase == $phase and .source_relationship.prior_is_ancestor == true and .source_relationship.source_tree_differs == true and (.source_relationship.current_tree_sha1 | strings | test("^[0-9a-f]{40}$")) and (.source_relationship.prior_tree_sha1 | strings | test("^[0-9a-f]{40}$")) and .source_relationship.current_tree_sha1 != .source_relationship.prior_tree_sha1 and .four_release_image_digests_distinct == true and .mutable_tags_used == false and .secrets_returned == false' "$artifact_out" >/dev/null || {
        rm -f -- "$artifact_out"
        guard_die "returned release-recovery artifact differs from the requested exact-digest phase"
      }
      printf 'Immutable-digest release %s evidence is recorded as sha256:%s.\n' "$recovery_phase" "$expected_evidence_hash"
    elif [[ "$operation" == "inspect-stage" ]]; then
      jq -e --arg source_sha "$source_sha" --arg release_id "$release_id" --arg stage "$stage" '
        .evidence_type == "protected-runner-stage-generation-inspection" and
        .source_sha == $source_sha and .release_id == $release_id and .stage == $stage and
        (.current_artifacts | type == "object") and .secrets_returned == false
      ' "$artifact_out" >/dev/null || {
        rm -f -- "$artifact_out"
        guard_die "returned immutable-stage inventory differs from the requested source/release/stage"
      }
      printf 'Immutable %s stage inventory is recorded as sha256:%s.\n' "$stage" "$expected_evidence_hash"
    elif [[ "$operation" == "stage-generation" ]]; then
      jq -e --arg source_sha "$source_sha" --arg release_id "$release_id" --arg stage "$stage" --arg mode "$stage_transition_mode" '
        .evidence_type == "protected-runner-stage-generation-transition" and
        .source_sha == $source_sha and .release_id == $release_id and .stage == $stage and
        .transition_mode == $mode and .history_preserved == true and .secrets_returned == false
      ' "$artifact_out" >/dev/null || {
        rm -f -- "$artifact_out"
        guard_die "returned stage-generation evidence differs from the authorized transition"
      }
      printf 'Append-only %s stage generation transition is recorded as sha256:%s.\n' "$stage" "$expected_evidence_hash"
    elif [[ "$operation" == "offboarding-acceptance" ]]; then
      jq -e --arg phase "$offboarding_phase" '.evidence_type == "protected-runner-offboarding-acceptance" and .offboarding_phase == $phase and .identifiers_returned == false and .secrets_returned == false' "$artifact_out" >/dev/null || {
        rm -f -- "$artifact_out"
        guard_die "returned offboarding artifact differs from the requested privacy-bounded phase"
      }
      printf 'Synthetic Clerk/app offboarding %s evidence is recorded as sha256:%s.\n' "$offboarding_phase" "$expected_evidence_hash"
    else
      printf 'Synthetic beta owner/bootstrap evidence is recorded as sha256:%s.\n' "$expected_evidence_hash"
    fi
  fi
  if [[ "$operation" == "retrieve" && "$artifact_kind" == "domain" ]]; then
    guard_validate_domain_verification_artifact "$artifact_out" "$source_sha" "$release_id"
  fi
  guard_publish_private_file "$artifact_out" "$artifact_destination" "sanitized protected-runner artifact"
  artifact_staging=""
  artifact_out="$artifact_destination"
  printf 'D3 protected runner %s succeeded; sanitized artifact written to %s\n' "$operation" "$artifact_out"
else
  printf 'D3 protected runner %s succeeded without returning protected payload contents\n' "$operation"
fi
