#!/usr/bin/env bash
# Review CosmaBot production foundation: name guards, monthly cost estimate, OpenTofu plan.
# First-apply-only by default. Pass --recover for the separately reviewed partial-apply
# recovery path. Pass --recheck for a print-only post-apply re-check (0 add/change/
# destroy/replace). Does not apply. Requires John's az login for the plan portion.
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
source_sha256=""
lock_sha256=""
skip_plan=0
recover=0
recheck=0

usage() {
  cat <<EOF
Usage: $0 --subscription-id UUID --inputs PATH --private-dir PATH
          --source-sha256 HEX --lock-sha256 HEX
          [--tofu PATH] [--provider-mirror PATH] [--cost-only] [--recover | --recheck]

First-apply-only review by default. Prints the checked-in monthly cost estimate
(labeled with price dates), refuses staging names, then runs the encrypted local
OpenTofu plan for rg-cosmabot-prod-eus2-01.

--private-dir must be a fresh absolute directory outside the repo (first apply).
With --recover, --private-dir must already exist and hold the encrypted state
plus passphrase from the partial first apply; the plan is written to
plans/recover-<UTC>.tfplan and never overwrites plans/first.tfplan.
With --recheck, --private-dir must already exist with post-apply encrypted state;
the plan is written to plans/recheck-<UTC>.tfplan only. Recheck never applies,
never refreshes/writes state (-refresh=false), and fails unless the plan is
0 add / 0 change / 0 destroy / 0 replace (and no import/move/deposed).
--recover and --recheck are mutually exclusive.
--source-sha256 / --lock-sha256 must be operator-supplied (from a prior
fingerprint review), not self-trusted.
--subscription-id must equal inputs.subscription_id.

OpenAI opt-in must be in the first apply's inputs or wait for a separately
reviewed day-2 tool. Do not run raw tofu by hand.

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
    --source-sha256) source_sha256="${2:-}"; shift 2 ;;
    --lock-sha256) lock_sha256="${2:-}"; shift 2 ;;
    --cost-only) skip_plan=1; shift ;;
    --recover) recover=1; shift ;;
    --recheck) recheck=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

[[ -f "$price_file" ]] || die "missing price table"
[[ -f "$prod_dir/name_guards.py" ]] || die "missing name guards"

if [[ "$recover" -eq 1 && "$recheck" -eq 1 ]]; then
  die "--recover and --recheck are mutually exclusive"
fi

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

def total_for(require_openai: bool) -> float:
    amount = 0.0
    for item in prices["line_items"]:
        requires = item.get("requires")
        if require_openai:
            amount += float(item["monthly_usd"])
        elif requires != "enable_azure_openai":
            amount += float(item["monthly_usd"])
    return round(amount, 2)

default_total = total_for(False)
optin_total = total_for(True)
print("=== CosmaBot production hosting monthly cost estimate ===")
print(f"label: {prices['label']}")
print(f"price_date: {prices['price_date']}")
print(f"envelope_price_date: {prices.get('envelope_price_date', prices['price_date'])}")
print(f"openai_price_date: {prices.get('openai_price_date', prices['price_date'])}")
print(f"currency: {prices.get('currency', 'USD')}")
print("")
for item in prices["line_items"]:
    priced = item.get("priced_on", prices["price_date"])
    req = item.get("requires")
    suffix = f" [requires={req}]" if req else ""
    print(f"- {item['component']}: ${float(item['monthly_usd']):.2f}  ({item['quantity']}; priced_on {priced}){suffix}")
print("")
for note in prices.get("notes", []):
    print(f"note: {note}")
print("")
print(f"DEFAULT PLAN (enable_azure_openai=false): ${default_total:.2f}")
delta = round(optin_total - default_total, 2)
print(f"WITH AZURE OPENAI OPT-IN: ${optin_total:.2f} (+${delta:.2f} standing, token usage excluded)")
threshold = float(prices.get("warning_threshold_usd", 300))
larger = max(default_total, optin_total)
if larger > threshold:
    print("")
    print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
    print(f"WARNING: larger standing estimate ${larger:.2f}/month EXCEEDS ${threshold:.0f}/month")
    print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
else:
    print(
        f"Standing costs only (token usage not included) are under ${threshold:.0f}/month. "
        + prices.get(
            "illustrative_token_assumption",
            "Capacity-bounded token spend is operator-estimated and excluded from these totals.",
        )
    )
print("This is an estimate, not an Azure invoice.")
print("")

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
[[ -n "$source_sha256" ]] || die "pass operator-supplied --source-sha256"
[[ -n "$lock_sha256" ]] || die "pass operator-supplied --lock-sha256"
[[ -n "$provider_mirror" && -d "$provider_mirror" ]] || die "pass --provider-mirror to the verified azurerm mirror"
command -v "$tofu_bin" >/dev/null || die "OpenTofu not found; pass --tofu"
command -v az >/dev/null || die "az CLI required; run az login to John's tenant first"
if [[ "$recheck" -eq 1 ]]; then
  [[ -d "$private_dir" ]] || die "recheck --private-dir must already exist with encrypted state"
elif [[ "$recover" -eq 1 ]]; then
  [[ -d "$private_dir" ]] || die "recovery --private-dir must already exist with encrypted state"
else
  [[ ! -e "$private_dir" ]] || die "private directory must be fresh (path must not exist yet)"
fi

python3 - "$inputs" "$prod_dir" "$subscription_id" <<'PY'
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[2])
from name_guards import assert_production_inputs, NameGuardError
inputs = json.loads(Path(sys.argv[1]).read_text())
try:
    assert_production_inputs(inputs)
except NameGuardError as exc:
    raise SystemExit(str(exc)) from exc
sub = str(inputs.get("subscription_id", ""))
if sub.lower() != sys.argv[3].lower():
    raise SystemExit("--subscription-id must equal inputs.subscription_id")
print("Reviewed inputs cleared production name guards; subscription id matches.")
PY

prepare_args=(
  prepare
  --private-dir "$private_dir"
  --inputs "$inputs"
  --source-sha256 "$source_sha256"
  --lock-sha256 "$lock_sha256"
  --tofu "$tofu_bin"
  --provider-mirror "$provider_mirror"
)
plan_args=(plan --private-dir "$private_dir")
if [[ "$recover" -eq 1 ]]; then
  prepare_args+=(--recover)
  plan_args+=(--recover)
fi
if [[ "$recheck" -eq 1 ]]; then
  prepare_args+=(--recheck)
  plan_args+=(--recheck)
fi

python3 "$foundation_dir/bootstrap_local.py" "${prepare_args[@]}"

plan_json="$(python3 "$foundation_dir/bootstrap_local.py" "${plan_args[@]}")"
python3 - "$plan_json" "$private_dir" "$recover" "$recheck" <<'PY'
import json, sys
from pathlib import Path
result = json.loads(sys.argv[1])
private_dir = Path(sys.argv[2])
recover = sys.argv[3] == "1"
recheck = sys.argv[4] == "1"
if recover or recheck:
    summary_path = Path(result["summary_path"])
else:
    summary_path = private_dir / "plan-summary.json"
summary = json.loads(summary_path.read_text())
print("")
print("=== Sanitised plan summary ===")
print(json.dumps(summary, sort_keys=True, indent=2))
print("")
print(f"enable_azure_openai (effective): {summary.get('enable_azure_openai')}")
print(f"plan_sha256: {result['plan_sha256']}")
print(f"summary_sha256: {result['summary_sha256']}")
if recheck:
    print("Post-apply re-check PASS: 0 add, 0 change, 0 destroy, 0 replace.")
    print(f"Plan saved under plans/recheck-<UTC>.tfplan ({Path(result['plan']).name}).")
    print(f"Summary/result: {summary_path.name} / {Path(result['result_path']).name}")
    print("Nothing was applied. State, manifests, first.tfplan, and recover artifacts were not overwritten.")
    print("This mode never applies and never prints the state passphrase or secrets.")
elif recover:
    print("Recovery review complete. Plan saved under plans/recover-<UTC>.tfplan.")
    print(f"Summary/result: {summary_path.name} / {Path(result['result_path']).name}")
    print("Nothing was applied. plans/first.tfplan was not overwritten.")
    print("After John's yes on this recovery plan hash, bind an approval file (0600, outside the repo) to:")
    print(f"  plan_sha256={result['plan_sha256']}")
    print(f"  summary_sha256={result['summary_sha256']}")
    print("Then follow the Apply section in infra/beta/vm/prod/README.md.")
else:
    print("Review complete. Plan saved under the private directory. Nothing was applied.")
    print("First-apply-only. After John's yes, bind an approval file (0600, outside the repo) to:")
    print(f"  plan_sha256={result['plan_sha256']}")
    print(f"  summary_sha256={result['summary_sha256']}")
    print("Then follow the Apply section in infra/beta/vm/prod/README.md.")
PY
