#!/usr/bin/env bash
set -euo pipefail
umask 077

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
beta_dir="$(cd -- "$script_dir/.." && pwd -P)"
# shellcheck source=../deployment-guard-lib.sh
source "$beta_dir/deployment-guard-lib.sh"
test_dir="$(mktemp -d "${TMPDIR:-/tmp}/cosmas-workload-orchestration.XXXXXX")"
trap 'rm -rf -- "$test_dir"' EXIT

# Exercise the actual resident functions without executing the cloud-facing
# script entrypoint. Only Azure/tofu calls, root ownership and helper internals
# are substituted; receipt parsing, projection comparison and storage are real.
for name in die fsync_path workload_private_file workload_private_directory validate_workload_request \
  prepare_workload_verification_context run_workload_binding verify_workload_state_unchanged \
  resolve_workload_generation publish_workload_generation execute_workload_verification; do
  sed -n "/^$name() {$/,/^}$/p" "$beta_dir/protected-runner-command.sh" >>"$test_dir/functions.sh"
done
sed -n '/^transport_validate_workload_arguments() {$/,/^}$/p' "$beta_dir/transport-to-protected-runner.sh" >>"$test_dir/functions.sh"
# shellcheck source=/dev/null
source "$test_dir/functions.sh"
operation_temp_dir=''

stat() {
  [[ "$1" == -c ]] || return 1
  if [[ "$2" == %u ]]; then
    printf '0\n' # The actual fixture is owned by this test user, never root.
  else
    python3 - "$3" <<'PYMODE'
import os, stat, sys
print(oct(stat.S_IMODE(os.stat(sys.argv[1]).st_mode))[2:])
PYMODE
  fi
}
install() {
  local args=()
  while (( $# )); do
    case "$1" in
      -o|-g) shift 2 ;;
      *) args+=("$1"); shift ;;
    esac
  done
  command install "${args[@]}"
}
mv() {
  [[ "${1:-}" != -T ]] || shift
  command mv "$@"
}
fixture_tofu() {
  [[ "$1" == "-chdir=$GUARD_ENVIRONMENT_DIR" && "$2" == show && "$3" == -json && "$4" == "$release_root/stages/workloads/plan.tfplan" ]] || return 1
  printf 'show\n' >>"$FIXTURE_CALLS"
  cat "$fixture_root/plan.json"
}
prepare_live_acceptance_context() {
  printf 'context\n' >>"$FIXTURE_CALLS"
  GUARD_ENVIRONMENT_DIR="$repository_root/infra/beta/environment"
  export GUARD_TERRAFORM_BIN=fixture_tofu
  GUARD_STATE_SHA256="$(guard_sha256 "$probe_state")"
  export GUARD_STATE_SHA256
}
guard_validate_planned_boundary() { printf 'boundary\n' >>"$FIXTURE_CALLS"; }
guard_validate_safe_plan_actions() {
  [[ "$2" == true ]]
  export GUARD_CREATE_COUNT=0 GUARD_UPDATE_COUNT=1 GUARD_NOOP_COUNT=0
  printf 'actions\n' >>"$FIXTURE_CALLS"
}
guard_write_critical_planned_values() { jq '.fixture_critical' "$1" >"$2"; }
guard_write_security_posture() { jq '.fixture_security' "$1" >"$2"; }
guard_pull_state() {
  cp "$probe_state" "$1"
  if [[ "${CHANGE_STATE:-false}" == true ]]; then
    printf '\n' >>"$1"
  fi
  printf 'state\n' >>"$FIXTURE_CALLS"
}
guard_validate_environment_state() { GUARD_STATE_SHA256="$(guard_sha256 "$1")"; }

make_fixture() {
  fixture_root="$test_dir/$1"
  mkdir -m 700 "$fixture_root"
  repository_root="$fixture_root/source"
  release_root="$fixture_root/release"
  build_root="$fixture_root/build"
  mkdir -p "$repository_root/infra/beta/environment" "$release_root/stages/workloads" "$build_root"
  chmod 700 "$release_root" "$release_root/stages" "$release_root/stages/workloads"
  source_sha=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
  release_id=release-001
  GUARD_BOX_ID=00000000-0000-4000-8000-000000000004
  operation=workload-verify stage=workloads
  payload_file="$fixture_root/payload.json"
  printf '{}' >"$payload_file"
  probe_state="$fixture_root/state.json"
  printf '{"serial":7,"lineage":"fixture"}' >"$probe_state"
  bootstrap_outputs="$fixture_root/bootstrap.json"
  printf '{}' >"$bootstrap_outputs"
  printf '{}' >"$build_root/build-evidence.json"
  printf 'lock' >"$repository_root/infra/beta/environment/.terraform.lock.hcl"
  printf 'binary-plan' >"$release_root/stages/workloads/plan.tfplan"
  printf '{}' >"$release_root/stages/workloads/environment.tfvars.json"
  printf '{}' >"$release_root/stages/workloads/result.json"
  cat >"$fixture_root/plan.json" <<'PLAN'
{"resource_changes":[{"address":"app","type":"app","mode":"managed","change":{"actions":["update"]}}],"fixture_critical":{"location":"eastus2","api_max_replicas":1},"fixture_security":{"ingress":"private"}}
PLAN
  jq '{phase:"subsequent",managed_action_counts:{create:0,update:1,no_op:0,delete:0,replace:0},managed_actions:[.resource_changes[]|{address,type,mode,actions:.change.actions}],critical_planned_values:.fixture_critical,security_posture:.fixture_security}' "$fixture_root/plan.json" >"$release_root/stages/workloads/review.json"
  FIXTURE_CALLS="$fixture_root/calls"
  export FIXTURE_CALLS
  : >"$FIXTURE_CALLS"
  export FAIL_MODE='' CHANGE_STATE=false
  cat >"$repository_root/infra/beta/workload_plan_binding.py" <<'PYHELPER'
import argparse, hashlib, json, os
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument("mode", choices=("verify", "validate"))
for name in ("plan", "plan-json", "review", "var-file", "apply-result", "state", "bootstrap-outputs", "build-evidence", "provider-lock", "source-sha", "release-id"):
    p.add_argument("--" + name, required=True)
p.add_argument("--output")
p.add_argument("--artifact")
a = p.parse_args()
with open(os.environ["FIXTURE_CALLS"], "a") as f:
    f.write(a.mode + "\n")
if os.environ.get("FAIL_MODE") == a.mode:
    raise SystemExit(1)
assert Path(a.plan).name == "plan.tfplan" and Path(a.review).parent == Path(a.plan).parent
assert Path(a.var_file).parent == Path(a.plan).parent and Path(a.apply_result).parent == Path(a.plan).parent
assert Path(a.plan_json).parent.name.startswith(".operation.")
assert Path(a.state).name == "state.json"
if a.mode == "validate":
    assert a.artifact and not a.output
    assert json.loads(Path(a.artifact).read_text())["source_sha"] == a.source_sha
else:
    assert a.output and not a.artifact and not Path(a.output).exists()
    payload = dict(schema_version=2, contract="cosmas-os-d3-workload-verification-v2", status="verified",
        completed_at="2026-09-25T12:00:00Z", source_sha=a.source_sha, release_id=a.release_id,
        box_id="00000000-0000-4000-8000-000000000004", location="eastus2", api_max_replicas=1,
        state={"exists":True,"lineage":"00000000-0000-4000-8000-000000000009","serial":7,"sha256":"1"*64},
        images={"api":"sha256:"+"2"*64,"worker":"sha256:"+"2"*64,"web":"sha256:"+"3"*64},
        revision_id_sha256={kind:"4"*64 for kind in ("api","worker","web")},
        plan_sha256="5"*64,review_sha256="6"*64,runtime_contract_sha256="7"*64,
        secrets_returned=False,person_or_patient_identifiers_returned=False)
    for key in ("exact_revisions_and_images_verified", "single_revision_traffic_verified", "api_ready_verified",
                "web_health_verified", "worker_probe_configuration_verified", "exact_runtime_configuration_verified",
                "managed_environment_verified", "worker_private_and_ready", "synthetic_box_id_returned"):
        payload[key] = True
    payload["evidence_payload_sha256"] = hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    Path(a.output).write_text(json.dumps(payload,indent=2)+"\n")
PYHELPER
}

checks=0
pass() { checks=$((checks + 1)); printf 'ok %s - %s\n' "$checks" "$1"; }
refuse() {
  local label="$1"
  shift
  # A separate shell keeps errexit active inside the tested orchestration.
  set +e
  (set -e; "$@") >"$test_dir/refusal.log" 2>&1
  local result=$?
  set -e
  [[ "$result" != 0 ]] || { printf 'unexpected acceptance: %s\n' "$label" >&2; exit 1; }
  pass "$label"
}

make_fixture success
execute_workload_verification
[[ -f "$WORKLOAD_ARTIFACT" && "$(cat "$WORKLOAD_EVIDENCE_DIR/current")" == "$(basename "$WORKLOAD_ARTIFACT")" ]]
[[ "$(cat "$FIXTURE_CALLS")" == $'context\nshow\nboundary\nactions\nverify\nvalidate\nstate' ]]
first_artifact="$WORKLOAD_ARTIFACT"
pass 'verify validates saved projection and candidate before immutable publication'

operation=retrieve
printf '{"artifact_kind":"workload"}' >"$payload_file"
: >"$FIXTURE_CALLS"
execute_workload_verification
[[ "$WORKLOAD_ARTIFACT" == "$first_artifact" && "$(cat "$FIXTURE_CALLS")" == $'context\nshow\nboundary\nactions\nvalidate\nstate' ]]
pass 'retrieve revalidates current binding without running live verification'

operation=workload-verify
printf '{}' >"$payload_file"
execute_workload_verification
[[ "$WORKLOAD_ARTIFACT" == "$first_artifact" ]]
pass 'identical immutable receipt can be republished without overwrite'

for failure in verify validate; do
  make_fixture "fail-$failure"
  export FAIL_MODE="$failure"
  refuse "$failure failure prevents publication" execute_workload_verification
  [[ ! -e "$release_root/workload-verification/current" ]]
done
make_fixture state-change
export CHANGE_STATE=true
refuse 'state changes before publication fail closed' execute_workload_verification
[[ ! -e "$release_root/workload-verification/current" ]]

make_fixture stale-retrieval
execute_workload_verification
prior_hash="$(guard_sha256 "$WORKLOAD_ARTIFACT")"
operation=retrieve
printf '{"artifact_kind":"workload"}' >"$payload_file"
: >"$FIXTURE_CALLS"
export FAIL_MODE=validate
refuse 'stale retrieval fails without replacing stored evidence' execute_workload_verification
[[ "$(guard_sha256 "$WORKLOAD_ARTIFACT")" == "$prior_hash" ]]
if rg -q '^verify$' "$FIXTURE_CALLS"; then exit 1; fi

make_fixture linked-input
rm "$release_root/stages/workloads/result.json"
ln -s "$payload_file" "$release_root/stages/workloads/result.json"
refuse 'symlink saved apply result is refused before verification' execute_workload_verification

make_fixture unsafe-directory
mkdir -m 777 "$release_root/workload-verification"
chmod 777 "$release_root/workload-verification"
refuse 'non-private evidence directory is refused' execute_workload_verification

for projection in critical_planned_values security_posture managed_action_counts managed_actions; do
  make_fixture "changed-$projection"
  jq --arg key "$projection" '.[$key] = {}' "$release_root/stages/workloads/review.json" >"$fixture_root/changed.json"
  cp "$fixture_root/changed.json" "$release_root/stages/workloads/review.json"
  refuse "changed complete $projection refuses before verification" execute_workload_verification
  if rg -q '^verify$' "$FIXTURE_CALLS"; then
    printf 'verifier ran despite changed review projection\n' >&2
    exit 1
  fi
done

make_fixture unsafe
prepare_workload_verification_context
run_workload_binding verify "$operation_temp_dir/candidate.json"
ln -s "$fixture_root/payload.json" "$WORKLOAD_EVIDENCE_DIR/current"
refuse 'symlink current pointer cannot be replaced' publish_workload_generation "$operation_temp_dir/candidate.json"
rm "$WORKLOAD_EVIDENCE_DIR/current"
guard_validate_workload_evidence "$operation_temp_dir/candidate.json" "$source_sha" "$release_id" "$GUARD_BOX_ID"
printf 'conflict' >"$WORKLOAD_EVIDENCE_DIR/$GUARD_EVIDENCE_PAYLOAD_SHA256.json"
refuse 'existing conflicting generation is never overwritten' publish_workload_generation "$operation_temp_dir/candidate.json"
[[ "$(cat "$WORKLOAD_EVIDENCE_DIR/$GUARD_EVIDENCE_PAYLOAD_SHA256.json")" == conflict ]]

make_fixture receipt
execute_workload_verification
refuse 'transport rejects source mismatch' guard_validate_workload_evidence "$WORKLOAD_ARTIFACT" bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb "$release_id" "$GUARD_BOX_ID"
refuse 'transport rejects release mismatch' guard_validate_workload_evidence "$WORKLOAD_ARTIFACT" "$source_sha" other-release "$GUARD_BOX_ID"
refuse 'transport rejects Box mismatch' guard_validate_workload_evidence "$WORKLOAD_ARTIFACT" "$source_sha" "$release_id" 00000000-0000-4000-8000-000000000005
for alteration in legacy extra nested-extra malformed-profile failed-assertion tampered duplicate jq-newline; do
  python3 - "$WORKLOAD_ARTIFACT" "$fixture_root/altered.json" "$alteration" <<'PYALTER'
import hashlib, json, sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text())
kind = sys.argv[3]
payload.pop("evidence_payload_sha256")
if kind == "legacy": payload["schema_version"] = 1
if kind == "extra": payload["unreviewed"] = "input"
if kind == "nested-extra": payload["state"]["unreviewed"] = "input"
if kind == "malformed-profile": payload["api_max_replicas"] = True
if kind == "failed-assertion": payload["exact_runtime_configuration_verified"] = False
encoded = json.dumps(payload,sort_keys=True,separators=(",",":"))
payload["evidence_payload_sha256"] = hashlib.sha256((encoded + ("\n" if kind == "jq-newline" else "")).encode()).hexdigest()
if kind == "tampered": payload["runtime_contract_sha256"] = "8"*64
text = json.dumps(payload)
if kind == "duplicate": text = '{"schema_version":2,' + text[1:]
Path(sys.argv[2]).write_text(text)
PYALTER
  refuse "transport rejects $alteration receipt" guard_validate_workload_evidence "$fixture_root/altered.json" "$source_sha" "$release_id" "$GUARD_BOX_ID"
done

operation=retrieve
printf '{"artifact_kind":"workload","acceptance_phase":"runtime"}' >"$payload_file"
refuse 'runner refuses extra retrieval payload fields' validate_workload_request
operation=workload-verify
printf '{"config":{}}' >"$payload_file"
refuse 'runner refuses ambient/manual payload configuration' validate_workload_request
printf '{}' >"$payload_file"
stage=database
refuse 'runner refuses wrong stage' validate_workload_request

for name in deploy_key known_hosts var_file web_build_config bootstrap_manifest approval_file \
  acceptance_phase acceptance_state alert_phase alert_test_state alert_retry_approval delivery_confirmation_reference \
  pitr_phase restore_time_utc quiet_window_end_utc pitr_preparer_reference prior_source_sha prior_release_id \
  recovery_phase stage_transition_mode offboarding_phase offboarding_request offboarding_state offboarding_confirmation; do
  printf -v "$name" '%s' ''
done
stage='' artifact_kind=''
transport_validate_workload_arguments
[[ "$stage" == workloads ]]
pass 'transport selects only workload stage'
stage=database
refuse 'transport refuses wrong explicit stage' transport_validate_workload_arguments
stage=workloads var_file=/invented/vars.json
refuse 'transport refuses manual variables' transport_validate_workload_arguments
export var_file='' operation=retrieve artifact_kind=workload
transport_validate_workload_arguments
pass 'transport accepts exact workload retrieval'
export acceptance_phase=runtime
refuse 'transport refuses mixed retrieval phases' transport_validate_workload_arguments

# Run the real payload dispatch independently of Azure transport. This catches
# an operation admitted by argument validation but omitted from payload creation.
python3 - "$beta_dir/transport-to-protected-runner.sh" "$test_dir/payload-dispatch.sh" <<'PYPAYLOAD'
from pathlib import Path
import sys
source = Path(sys.argv[1]).read_text()
body = source.rsplit('case "$operation" in\n', 1)[1].split('\nesac\n', 1)[0]
Path(sys.argv[2]).write_text('case "$operation" in\n' + body + '\nesac\n')
PYPAYLOAD
operation=workload-verify
: >"$payload_file"
# shellcheck source=/dev/null
source "$test_dir/payload-dispatch.sh"
[[ "$(cat "$payload_file")" == '{}' ]]
pass 'transport creates an explicit empty workload verification payload'
operation=retrieve artifact_kind=workload
# shellcheck source=/dev/null
source "$test_dir/payload-dispatch.sh"
jq -e '. == {artifact_kind:"workload"}' "$payload_file" >/dev/null
pass 'transport retrieval payload contains only the selected workload artifact'

printf 'PASS: %s focused workload orchestration checks; no cloud calls\n' "$checks"
