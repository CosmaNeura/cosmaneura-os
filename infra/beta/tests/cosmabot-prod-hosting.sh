#!/usr/bin/env bash
# Shell checks for CosmaBot production hosting review/apply scripts.
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
beta_dir="$(cd -- "$script_dir/.." && pwd -P)"
repo_dir="$(cd -- "$beta_dir/../.." && pwd -P)"

bash -n "$beta_dir/review-cosmabot-prod-foundation.sh"
bash -n "$beta_dir/apply-cosmabot-prod-foundation.sh"
bash -n "$script_dir/cosmabot-prod-hosting.sh"

# Apply must refuse without the confirm flag.
if bash "$beta_dir/apply-cosmabot-prod-foundation.sh" --private-dir /tmp/cosmabot-prod-never 2>/tmp/cosmabot-prod-apply.err; then
  echo "expected apply to refuse without --confirm-apply" >&2
  exit 1
fi
grep -F "refusing apply without --confirm-apply" /tmp/cosmabot-prod-apply.err >/dev/null

# Cost-only review is offline.
bash "$beta_dir/review-cosmabot-prod-foundation.sh" --cost-only >/tmp/cosmabot-prod-review.out
grep -F "ESTIMATED MONTHLY TOTAL" /tmp/cosmabot-prod-review.out >/dev/null
grep -F "price_date:" /tmp/cosmabot-prod-review.out >/dev/null
grep -F "Name guards:" /tmp/cosmabot-prod-review.out >/dev/null

# Offline dry-run.
python3 "$beta_dir/vm/prod/dry_run.py" >/tmp/cosmabot-prod-dry-run.out
grep -F '"dry_run": true' /tmp/cosmabot-prod-dry-run.out >/dev/null
grep -F '"azure_calls": false' /tmp/cosmabot-prod-dry-run.out >/dev/null

# Staging foundation content must not gain production names (files stay untouched).
if ! python3 - "$repo_dir" <<'PY'
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
then
  exit 1
fi

echo "cosmabot-prod-hosting shell checks passed"
