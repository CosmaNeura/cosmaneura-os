#!/usr/bin/env bash
# Apply a previously reviewed CosmaBot production foundation plan.
# First-apply-only by default. Pass --recover for the separately reviewed
# partial-apply recovery path. Requires --confirm-apply and --approval PATH.
# Agents must not run this.
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
foundation_dir="$(cd -- "$script_dir/vm/prod/foundation" && pwd -P)"
confirm=0
private_dir=""
approval=""
recover=0

usage() {
  cat <<EOF
Usage: $0 --confirm-apply --approval PATH --private-dir PATH [--recover]

First-apply-only by default. Applies the encrypted plan at PATH/plans/first.tfplan
for rg-cosmabot-prod-eus2-01 after John binds an approval file to that plan's
sha256 (and the sanitised plan-summary sha256).

With --recover, applies PATH/plans/recover-<UTC>.tfplan after the same four-key
approval binding to that recover plan's hashes. Never overwrites or reapplies
plans/first.tfplan. On failure: stop, keep artifacts, do not retry.

Requires both --confirm-apply and --approval. The approval file must be a
private 0600 JSON outside the repo with reviewer, review_reference,
plan_sha256, and summary_sha256.

OpenAI opt-in must be in this first apply's inputs or wait for a separately
reviewed day-2 tool. Do not run raw tofu by hand.

Partial-apply recovery: keep the private directory intact, do not delete
encrypted state/plans, and use --recover on the reviewed recovery tooling.
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
    --approval) approval="${2:-}"; shift 2 ;;
    --recover) recover=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

[[ "$confirm" -eq 1 ]] || die "refusing apply without --confirm-apply"
[[ -n "$private_dir" ]] || die "pass --private-dir"
[[ -n "$approval" ]] || die "pass --approval PATH"
[[ -d "$private_dir" ]] || die "private directory missing"

args=(apply --private-dir "$private_dir" --approval "$approval")
if [[ "$confirm" -eq 1 ]]; then
  args+=(--confirm-apply)
fi
if [[ "$recover" -eq 1 ]]; then
  args+=(--recover)
fi
python3 "$foundation_dir/bootstrap_local.py" "${args[@]}"
printf 'Apply finished for %s.\n' "rg-cosmabot-prod-eus2-01"
