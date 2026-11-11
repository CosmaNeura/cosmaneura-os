#!/usr/bin/env bash
# Review CosmaBot production foundation: name guards, monthly cost estimate, OpenTofu plan.
# Does not apply. Requires John's az login for the plan portion.
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
prod_dir="$(cd -- "$script_dir/vm/prod" && pwd -P)"
foundation_dir="$prod_dir/foundation"
price_file="$prod_dir/prices/monthly-estimate.json"
inputs=""
private_dir=""
subscription_id=""
tofu_bin="${TOFU_BIN:-tofu}"
provider_mirror="${PROVIDER_MIRROR:-}"
skip_plan=0

usage() {
  cat <<EOF
Usage: $0 --subscription-id UUID --inputs PATH [--private-dir PATH]
          [--tofu PATH] [--provider-mirror PATH] [--cost-only]

Prints the checked-in monthly cost estimate (labeled with price date), refuses
staging names, then runs the encrypted local OpenTofu plan for
rg-cosmabot-prod-eus2-01 (same prepare/plan pattern as staging).

Prerequisites for the plan portion:
  - az login to John's tenant
  - subscription id passed explicitly
  - pinned OpenTofu 1.12.5 and a verified azurerm provider mirror

--cost-only skips Azure/OpenTofu and only prints the estimate + name guards.
EOF
}

die() {
  printf 'cosmabot prod review refused: %s\n' "$1" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --subscription-id) subscription_id="${2:-}"; shift 2 ;;
    --inputs) inputs="${2:-}"; shift 2 ;;
    --private-dir) private_dir="${2:-}"; shift 2 ;;
    --tofu) tofu_bin="${2:-}"; shift 2 ;;
    --provider-mirror) provider_mirror="${2:-}"; shift 2 ;;
    --cost-only) skip_plan=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

[[ -f "$price_file" ]] || die "missing price table"
[[ -f "$prod_dir/name_guards.py" ]] || die "missing name guards"

python3 - "$price_file" "$prod_dir" <<'PY'
import json, sys
from pathlib import Path
price_path = Path(sys.argv[1])
prod_dir = Path(sys.argv[2])
sys.path.insert(0, str(prod_dir))
from name_guards import PRODUCTION, STAGING, assert_production_inputs, assert_staging_inputs, NameGuardError

prices = json.loads(price_path.read_text())
if prices.get("label") != "estimate" or not prices.get("price_date"):
    raise SystemExit("price table must be labeled estimate with price_date")
total = round(sum(float(item["monthly_usd"]) for item in prices["line_items"]), 2)
print("=== CosmaBot production hosting monthly cost estimate ===")
print(f"label: {prices['label']}")
print(f"price_date: {prices['price_date']}")
print(f"currency: {prices.get('currency', 'USD')}")
print("")
for item in prices["line_items"]:
    print(f"- {item['component']}: ${float(item['monthly_usd']):.2f}  ({item['quantity']})")
print("")
print(f"ESTIMATED MONTHLY TOTAL: ${total:.2f}")
threshold = float(prices.get("warning_threshold_usd", 300))
if total > threshold:
    print("")
    print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
    print(f"WARNING: estimate ${total:.2f}/month EXCEEDS ${threshold:.0f}/month")
    print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
else:
    print(f"(under ${threshold:.0f}/month warning threshold)")
print("")
print("Azure OpenAI module: OFF by default (excluded from this estimate).")
print("This is an estimate, not an Azure invoice.")
print("")

# Bidirectional name refusal proof during review.
try:
    assert_production_inputs({
        "resource_group": PRODUCTION["resource_group"],
        "vm_name": PRODUCTION["vm_name"],
        "web_host": PRODUCTION["web_host"],
        "api_host": PRODUCTION["api_host"],
        "acr_prefix": PRODUCTION["acr_prefix"],
        "key_vault_prefix": PRODUCTION["key_vault_prefix"],
        "storage_0": PRODUCTION["storage_prefixes"][0],
        "storage_1": PRODUCTION["storage_prefixes"][1],
        "state_namespace": PRODUCTION["state_namespace"],
    })
except NameGuardError as exc:
    raise SystemExit(f"production profile self-check failed: {exc}") from exc
for bad in (
    {"resource_group": STAGING["resource_group"]},
    {"web_host": STAGING["web_host"]},
    {"acr_prefix": STAGING["acr_prefix"]},
    {"key_vault_prefix": STAGING["key_vault_prefix"]},
):
    try:
        assert_production_inputs(bad)
    except NameGuardError:
        pass
    else:
        raise SystemExit(f"production profile failed to refuse staging name: {bad}")
for bad in (
    {"resource_group": PRODUCTION["resource_group"]},
    {"web_host": PRODUCTION["web_host"]},
    {"acr_prefix": PRODUCTION["acr_prefix"]},
    {"key_vault_prefix": PRODUCTION["key_vault_prefix"]},
):
    try:
        assert_staging_inputs(bad)
    except NameGuardError:
        pass
    else:
        raise SystemExit(f"staging profile failed to refuse production name: {bad}")
print("Name guards: production refuses staging names; staging refuses production names.")
PY

if [[ "$skip_plan" -eq 1 ]]; then
  printf '\n--cost-only: skipped OpenTofu plan (no Azure calls).\n'
  exit 0
fi

[[ -n "$subscription_id" ]] || die "pass --subscription-id"
[[ -n "$inputs" && -f "$inputs" ]] || die "pass --inputs PATH to reviewed public inputs JSON"
[[ -n "$private_dir" ]] || die "pass --private-dir to a fresh absolute directory outside the repo"
[[ -n "$provider_mirror" && -d "$provider_mirror" ]] || die "pass --provider-mirror to the verified azurerm mirror"
command -v "$tofu_bin" >/dev/null || die "OpenTofu not found; pass --tofu"
command -v az >/dev/null || die "az CLI required; run az login to John's tenant first"

# Refuse staging coordinates in the inputs file before any Azure mutation.
python3 - "$inputs" "$prod_dir" <<'PY'
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[2])
from name_guards import assert_production_inputs, NameGuardError
inputs = json.loads(Path(sys.argv[1]).read_text())
try:
    assert_production_inputs(inputs)
except NameGuardError as exc:
    raise SystemExit(str(exc)) from exc
print("Reviewed inputs cleared production name guards.")
PY

fingerprint="$(python3 "$foundation_dir/bootstrap_local.py" fingerprint)"
source_sha="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["source_sha256"])' <<<"$fingerprint")"
lock_sha="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["lock_sha256"])' <<<"$fingerprint")"

if [[ ! -d "$private_dir" ]]; then
  python3 "$foundation_dir/bootstrap_local.py" prepare \
    --private-dir "$private_dir" \
    --inputs "$inputs" \
    --source-sha256 "$source_sha" \
    --lock-sha256 "$lock_sha" \
    --tofu "$tofu_bin" \
    --provider-mirror "$provider_mirror"
fi

python3 "$foundation_dir/bootstrap_local.py" plan --private-dir "$private_dir"
printf '\nReview complete. Plan saved under the private directory. Nothing was applied.\n'
printf 'To apply after explicit yes:\n'
printf '  bash infra/beta/apply-cosmabot-prod-foundation.sh --confirm-apply --private-dir %q\n' "$private_dir"
