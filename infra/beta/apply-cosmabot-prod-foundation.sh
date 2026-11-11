#!/usr/bin/env bash
# Apply a previously reviewed CosmaBot production foundation plan.
# Refuses unless --confirm-apply is passed explicitly. Agents must not run this.
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
prod_dir="$(cd -- "$script_dir/vm/prod" && pwd -P)"
confirm=0
private_dir=""

usage() {
  cat <<EOF
Usage: $0 --confirm-apply --private-dir PATH

Applies the encrypted plan at PATH/plans/first.tfplan for
rg-cosmabot-prod-eus2-01. Refuses without --confirm-apply.

Prerequisites:
  - Successful review via infra/beta/review-cosmabot-prod-foundation.sh
  - az login to John's tenant still matching the prepared subscription/tenant
  - John's explicit yes after reading the plan and cost estimate
EOF
}

die() {
  printf 'cosmabot prod apply refused: %s\n' "$1" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --confirm-apply) confirm=1; shift ;;
    --private-dir) private_dir="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

[[ "$confirm" -eq 1 ]] || die "refusing apply without --confirm-apply"
[[ -n "$private_dir" ]] || die "pass --private-dir"
[[ -d "$private_dir" ]] || die "private directory missing"
[[ -f "$private_dir/plans/first.tfplan" ]] || die "missing reviewed plan at plans/first.tfplan"
[[ -f "$private_dir/manifest.json" ]] || die "missing prepare manifest"
[[ -f "$private_dir/encryption.passphrase" ]] || die "missing encryption passphrase file"
[[ -d "$private_dir/module" ]] || die "missing module snapshot"

# Refuse if the prepared profile somehow points at staging names.
python3 - "$private_dir/manifest.json" "$prod_dir" <<'PY'
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[2])
from name_guards import PRODUCTION, STAGING, NameGuardError, refuse_cross_environment
manifest = json.loads(Path(sys.argv[1]).read_text())
rg = manifest.get("resource_group", "")
profile = manifest.get("profile", "")
if rg != PRODUCTION["resource_group"]:
    raise SystemExit(f"manifest resource_group is not production: {rg}")
if profile != PRODUCTION["state_namespace"]:
    raise SystemExit(f"manifest profile is not production namespace: {profile}")
try:
    refuse_cross_environment("production", [rg, profile, json.dumps(manifest)])
except NameGuardError as exc:
    raise SystemExit(str(exc)) from exc
if STAGING["resource_group"] in json.dumps(manifest):
    raise SystemExit("manifest contains staging resource group")
print("Apply precheck: production name guards passed.")
PY

command -v tofu >/dev/null || die "OpenTofu (tofu) required"
command -v az >/dev/null || die "az CLI required"

export TF_DATA_DIR="$private_dir/tofu-data"
export TF_WORKSPACE=default
export TF_INPUT=0
export TF_IN_AUTOMATION=1
export TF_CLI_CONFIG_FILE="$private_dir/tofurc"
export TF_VAR_bootstrap_key_file="$private_dir/encryption.passphrase"
export ARM_USE_CLI=true
export ARM_USE_MSI=false
export ARM_USE_OIDC=false

# Explicit apply of the reviewed encrypted plan only.
tofu -chdir="$private_dir/module" apply -input=false -lock=true -lock-timeout=30s "$private_dir/plans/first.tfplan"
printf 'Apply finished for %s.\n' "rg-cosmabot-prod-eus2-01"
