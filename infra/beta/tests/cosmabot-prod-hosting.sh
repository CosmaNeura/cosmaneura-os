#!/usr/bin/env bash
# Shell checks for CosmaBot production hosting review/apply scripts.
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
beta_dir="$(cd -- "$script_dir/.." && pwd -P)"
repo_dir="$(cd -- "$beta_dir/../.." && pwd -P)"
tmp_root="$(mktemp -d /tmp/cosmabot-prod-shell-XXXXXX)"
trap 'rm -rf "$tmp_root"' EXIT

stub_bin="$tmp_root/bin"
mkdir -p "$stub_bin"
for name in az tofu terraform; do
  cat >"$stub_bin/$name" <<'EOF'
#!/usr/bin/env bash
printf 'stub-called\n' >>"${COSMABOT_STUB_MARKER:?}"
exit 97
EOF
  chmod +x "$stub_bin/$name"
done
export COSMABOT_STUB_MARKER="$tmp_root/marker"
: >"$COSMABOT_STUB_MARKER"
# Strip ambient Azure/TF overrides for these checks.
for key in $(env | awk -F= '/^(ARM_|TF_)/ {print $1}'); do
  unset "$key" || true
done
unset AZURE_CONFIG_DIR || true
export PATH="$stub_bin:/usr/bin:/bin"

bash -n "$beta_dir/review-cosmabot-prod-foundation.sh"
bash -n "$beta_dir/apply-cosmabot-prod-foundation.sh"
bash -n "$script_dir/cosmabot-prod-hosting.sh"

# Apply must refuse without the confirm flag (shell gate; stubs must not run).
if bash "$beta_dir/apply-cosmabot-prod-foundation.sh" \
  --private-dir "$tmp_root/never" \
  --approval "$tmp_root/approval.json" 2>"$tmp_root/apply.err"; then
  echo "expected apply to refuse without --confirm-apply" >&2
  exit 1
fi
grep -F "refusing apply without --confirm-apply" "$tmp_root/apply.err" >/dev/null
[[ ! -s "$COSMABOT_STUB_MARKER" ]] || { echo "stub az/tofu was invoked" >&2; exit 1; }

# Review script must never print or contain an apply confirm line.
if grep -F -- "--confirm-apply" "$beta_dir/review-cosmabot-prod-foundation.sh" >/dev/null; then
  echo "review script must not contain --confirm-apply" >&2
  exit 1
fi

# Cost-only review is offline and must not call stubs.
bash "$beta_dir/review-cosmabot-prod-foundation.sh" --cost-only >"$tmp_root/review.out"
grep -F "DEFAULT PLAN (enable_azure_openai=false): \$180.27" "$tmp_root/review.out" >/dev/null
grep -F "WITH AZURE OPENAI OPT-IN: \$188.07 (+\$7.80 standing, token usage excluded)" "$tmp_root/review.out" >/dev/null
grep -F "price_date:" "$tmp_root/review.out" >/dev/null
grep -F "Name guards:" "$tmp_root/review.out" >/dev/null
if grep -F -- "--confirm-apply" "$tmp_root/review.out" >/dev/null; then
  echo "cost-only review output must not contain --confirm-apply" >&2
  exit 1
fi
[[ ! -s "$COSMABOT_STUB_MARKER" ]] || { echo "stub az/tofu was invoked during cost-only" >&2; exit 1; }

# Offline dry-run (real interpreter PATH; stubs stay unused).
PATH="/usr/bin:/bin" python3 "$beta_dir/vm/prod/dry_run.py" --allow-no-provider >"$tmp_root/dry-run.out"
grep -F '"dry_run": true' "$tmp_root/dry-run.out" >/dev/null
grep -F '"azure_calls": false' "$tmp_root/dry-run.out" >/dev/null
[[ ! -s "$COSMABOT_STUB_MARKER" ]] || { echo "stub az/tofu was invoked during dry-run" >&2; exit 1; }

# Staging foundation content must not gain production names (files stay untouched).
python3 - "$repo_dir" <<'PY'
from pathlib import Path
import sys
repo = Path(sys.argv[1])
sys.path.insert(0, str(repo / "infra/beta/vm/prod"))
from name_guards import PRODUCTION
text = "\n".join(
    path.read_text()
    for path in sorted((repo / "infra/beta/vm/foundation").rglob("*"))
    if path.is_file() and path.suffix in {".tf", ".py", ".hcl", ".md"}
)
for needle in (
    PRODUCTION["resource_group"],
    PRODUCTION["vm_name"],
    PRODUCTION["web_host"],
    PRODUCTION["acr_prefix"],
    PRODUCTION["key_vault_prefix"],
    PRODUCTION["state_namespace"],
    *PRODUCTION["storage_prefixes"],
):
    if needle in text:
        raise SystemExit(f"staging foundation contains production name: {needle}")
print("staging foundation has no production names")
PY

# Prod README/profile/scripts must not contain DNS-record change steps.
python3 - "$repo_dir" <<'PY'
from pathlib import Path
import sys
repo = Path(sys.argv[1])
paths = [
    repo / "infra/beta/vm/prod/README.md",
    repo / "infra/beta/vm/prod/profile/runtime-public.json",
    repo / "infra/beta/review-cosmabot-prod-foundation.sh",
    repo / "infra/beta/apply-cosmabot-prod-foundation.sh",
]
needles = (
    "az network dns",
    "nsupdate",
    "dns record set",
    "cloudflare api",
    "update the beta.cosmas.ai",
    "A records at the DNS provider",
)
for path in paths:
    text = path.read_text().lower()
    for needle in needles:
        if needle.lower() in text:
            raise SystemExit(f"{path} contains DNS mutation step: {needle}")
profile = (repo / "infra/beta/vm/prod/profile/runtime-public.json").read_text()
if '"dns"' in profile or "dns.records" in profile:
    raise SystemExit("profile must not declare dns.records")
print("no DNS-record change steps in prod README/profile/scripts")
PY

[[ ! -s "$COSMABOT_STUB_MARKER" ]] || { echo "stub marker written unexpectedly" >&2; exit 1; }
echo "cosmabot-prod-hosting shell checks passed"
