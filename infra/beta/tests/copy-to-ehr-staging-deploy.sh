#!/usr/bin/env bash
# Shell checks for the Copy to EHR staging deploy script. No Azure, no Docker.
# Requires bash 4 or newer, same as the deploy script.
if [[ -z "${BASH_VERSINFO+x}" || "${BASH_VERSINFO[0]}" -lt 4 ]]; then
  printf 'BASH_TOO_OLD\n' >&2
  printf 'copy-to-ehr staging deploy tests refused: bash 4 or newer is required\n' >&2
  exit 1
fi
set -uo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
target="$(cd -- "$script_dir/.." && pwd -P)/copy-to-ehr-staging-deploy.sh"
root_dir="$(mktemp -d "${TMPDIR:-/tmp}/copy-to-ehr-tests.XXXXXX")"
chmod 700 "$root_dir"
export COPY_TO_EHR_MARKER_FILE="$root_dir/cutover-marker"
failures=0

cleanup() {
  rm -rf -- "$root_dir"
}
trap cleanup EXIT

pass() {
  printf 'ok %s\n' "$1"
}

fail() {
  printf 'FAIL %s\n' "$1" >&2
  failures=$((failures + 1))
}

expect_fail() {
  local name="$1"
  shift
  local status=0
  set +e
  "$@" >"$root_dir/expect-fail.out" 2>"$root_dir/expect-fail.err"
  status=$?
  set -e
  if [[ "$status" -eq 0 ]]; then
    fail "$name (expected nonzero)"
    return
  fi
  pass "$name"
}

need() {
  "$@" || exit 1
}

caught=0
(
  need false
) || caught=$?
if [[ "$caught" -ne 0 ]]; then
  pass "a deliberate failing assertion is caught"
else
  fail "a deliberate failing assertion is caught"
fi

staging_account="$root_dir/account.json"
staging_vm="$root_dir/vm.json"
cat >"$staging_account" <<'EOF'
{"id":"bab2a709-1fcb-4c87-a9fc-802f7477ec13","name":"Microsoft Azure Sponsorship","user":{"name":"john@cosmaneura.com"}}
EOF
cat >"$staging_vm" <<'EOF'
{"name":"vm-cosmabot-staging-eus2-lab01","resourceGroup":"rg-cosmas-os-vm-staging-eus2-lab01","publicIps":"20.22.205.132"}
EOF

make_stubs() {
  local dir="$1" account="$2" vm="$3"
  mkdir -p "$dir"
  cat >"$dir/az" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$dir/az.log"
if [[ "\$1" == "account" && "\$2" == "show" ]]; then
  cat "$account"
  exit 0
fi
if [[ "\$1" == "vm" && "\$2" == "show" ]]; then
  cat "$vm"
  exit 0
fi
printf '%s\n' "\$*" >> "$dir/az.mutations"
exit 99
EOF
  cat >"$dir/docker" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$dir/docker.log"
exit 99
EOF
  cat >"$dir/ssh" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$dir/ssh.log"
exit 99
EOF
  chmod 700 "$dir/az" "$dir/docker" "$dir/ssh"
  : >"$dir/az.log"
  : >"$dir/az.mutations"
  : >"$dir/docker.log"
  : >"$dir/ssh.log"
}

run_script() {
  local stubdir="$1"
  shift
  env HOME="$root_dir/home" PATH="$stubdir:$PATH" bash "$target" "$@"
}

if [[ "$(grep -c '^DEFAULT_SOURCE_SHA=' "$target")" -eq 1 ]] \
  && grep -q '^DEFAULT_SOURCE_SHA=e29bf5a2de0eddec1663b1185076472ef172b590$' "$target"; then
  pass "default sha is one constant"
else
  fail "default sha is one constant"
fi

if grep -E -n 'blob download|scp ' "$target"; then
  fail "script contains a dump download or scp"
else
  pass "script does not download the dump"
fi

mkdir -p "$root_dir/home"
stubs="$root_dir/stubs"
make_stubs "$stubs" "$staging_account" "$staging_vm"
workdir="$root_dir/work"

dry_out="$root_dir/dry.out"
dry_err="$root_dir/dry.err"
if run_script "$stubs" --workdir "$workdir" >"$dry_out" 2>"$dry_err"; then
  first=$(head -n 1 "$dry_out")
  if [[ "$first" == "Tonight for existing live users: nothing changes." ]] \
    && [[ ! -s "$stubs/docker.log" && ! -s "$stubs/ssh.log" && ! -s "$stubs/az.mutations" ]] \
    && grep -q 'account show' "$stubs/az.log" \
    && grep -q 'vm show' "$stubs/az.log" \
    && ! grep -q 'run-command' "$stubs/az.log" \
    && grep -q 'e29bf5a2de0eddec1663b1185076472ef172b590' "$dry_out" \
    && grep -q 'stop before cutover: live release-r10 stays on 54110/54112' "$dry_out" \
    && grep -q 'SIDE_PORT_REFUSED_LIVE_DATABASE' "$dry_out" \
    && grep -q '54130' "$dry_out" \
    && grep -q 'stops live staging' "$dry_out" \
    && grep -q 'load the staging VM' "$dry_out"; then
    pass "dry-run prints the plan and runs no mutating command"
  else
    fail "dry-run prints the plan and runs no mutating command"
    cat "$dry_err" >&2 || true
  fi
else
  fail "dry-run prints the plan and runs no mutating command"
  cat "$dry_err" >&2 || true
fi

other_sha="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
other_stubs="$root_dir/stubs-sha"
make_stubs "$other_stubs" "$staging_account" "$staging_vm"
other_out="$root_dir/sha.out"
if run_script "$other_stubs" --sha "$other_sha" --workdir "$workdir" >"$other_out" 2>"$root_dir/sha.err" \
  && grep -q "$other_sha" "$other_out" \
  && ! grep -q 'run-command' "$other_stubs/az.log"; then
  pass "--sha replaces the default"
else
  fail "--sha replaces the default"
fi

prod_account="$root_dir/prod-account.json"
cat >"$prod_account" <<'EOF'
{"id":"aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee","name":"Cosmaneura Production","user":{"name":"john@cosmaneura.com"}}
EOF
prod_stubs="$root_dir/stubs-prod-sub"
make_stubs "$prod_stubs" "$prod_account" "$staging_vm"
expect_fail "prod subscription refused" run_script "$prod_stubs" --workdir "$workdir"
if [[ -s "$prod_stubs/docker.log" || -s "$prod_stubs/ssh.log" || -s "$prod_stubs/az.mutations" ]]; then
  fail "prod subscription ran a mutating command"
else
  pass "prod subscription ran no mutating command"
fi

rg_vm="$root_dir/prod-vm.json"
cat >"$rg_vm" <<'EOF'
{"name":"vm-cosmabot-staging-eus2-lab01","resourceGroup":"cosmaneura-prod-app","publicIps":"20.22.205.132"}
EOF
rg_stubs="$root_dir/stubs-prod-rg"
make_stubs "$rg_stubs" "$staging_account" "$rg_vm"
expect_fail "prod resource group from azure refused" run_script "$rg_stubs" --workdir "$workdir"
flag_stubs="$root_dir/stubs-prod-rg-flag"
make_stubs "$flag_stubs" "$staging_account" "$staging_vm"
expect_fail "prod resource group flag refused" run_script "$flag_stubs" --workdir "$workdir" --resource-group cosmaneura-prod-app
if [[ -s "$flag_stubs/az.log" || -s "$flag_stubs/docker.log" ]]; then
  fail "prod resource group flag reached azure or docker"
else
  pass "prod resource group flag stopped before azure"
fi

host_stubs="$root_dir/stubs-prod-host"
make_stubs "$host_stubs" "$staging_account" "$staging_vm"
expect_fail "prod hostname refused" run_script "$host_stubs" --workdir "$workdir" --web-host app.cosmaneura.com
if [[ -s "$host_stubs/az.log" || -s "$host_stubs/docker.log" || -s "$host_stubs/ssh.log" ]]; then
  fail "prod hostname reached azure, docker, or ssh"
else
  pass "prod hostname stopped before azure"
fi

desktop="$root_dir/home/Desktop/cosmaneura-os"
mkdir -p "$desktop"
desk_stubs="$root_dir/stubs-desktop"
make_stubs "$desk_stubs" "$staging_account" "$staging_vm"
expect_fail "desktop workdir refused" run_script "$desk_stubs" --workdir "$desktop/build"
if [[ -s "$desk_stubs/az.log" ]]; then
  fail "desktop workdir reached azure"
else
  pass "desktop workdir stopped before azure"
fi
pwd_stubs="$root_dir/stubs-desktop-pwd"
make_stubs "$pwd_stubs" "$staging_account" "$staging_vm"
status=0
set +e
(
  cd "$desktop"
  env HOME="$root_dir/home" PATH="$pwd_stubs:$PATH" bash "$target" --workdir "$workdir"
) >/dev/null 2>&1
status=$?
set -e
if [[ "$status" -ne 0 && ! -s "$pwd_stubs/az.log" ]]; then
  pass "desktop cwd refused"
else
  fail "desktop cwd refused"
fi

cut_stubs="$root_dir/stubs-cutover"
make_stubs "$cut_stubs" "$staging_account" "$staging_vm"
expect_fail "cutover requires --expect-prior-sha" run_script "$cut_stubs" --cutover --workdir "$workdir"
if [[ -s "$cut_stubs/az.log" || -s "$cut_stubs/docker.log" ]]; then
  fail "cutover without the flag reached azure or docker"
else
  pass "cutover without the flag stopped before azure"
fi

cut_ok="$root_dir/stubs-cutover-ok"
make_stubs "$cut_ok" "$staging_account" "$staging_vm"
cut_out="$root_dir/cutover.out"
if run_script "$cut_ok" --cutover --expect-prior-sha 9dfd4cfd --workdir "$workdir" >"$cut_out" 2>"$root_dir/cutover.err" \
  && [[ "$(head -n 1 "$cut_out")" == "Tonight for existing live users: nothing changes." ]] \
  && grep -q 'copy_to_ehr_cutover_main' "$cut_out" \
  && grep -q 'release-r10' "$cut_out" \
  && ! grep -q 'run-command' "$cut_ok/az.log" \
  && [[ ! -s "$cut_ok/docker.log" && ! -s "$cut_ok/ssh.log" ]]; then
  pass "cutover dry-run keeps the explicit flag and changes nothing"
else
  fail "cutover dry-run keeps the explicit flag and changes nothing"
  cat "$root_dir/cutover.err" >&2 || true
fi

local_stubs="$root_dir/stubs-local-dump"
make_stubs "$local_stubs" "$staging_account" "$staging_vm"
expect_fail "local dump target refused" run_script "$local_stubs" --workdir "$workdir" --dump-target /Users/john/live.dump
if [[ -s "$local_stubs/az.log" ]]; then
  fail "local dump target reached azure"
else
  pass "local dump target stopped before azure"
fi

(
  # shellcheck disable=SC1090
  source "$target"
  storage_ok="/subscriptions/bab2a709-1fcb-4c87-a9fc-802f7477ec13/resourceGroups/rg-cosmas-os-vm-staging-eus2-lab01/providers/Microsoft.Storage/storageAccounts/stgcbotstaging"
  storage_other="/subscriptions/bab2a709-1fcb-4c87-a9fc-802f7477ec13/resourceGroups/rg-other/providers/Microsoft.Storage/storageAccounts/stgcbotstaging"
  storage_prod="/subscriptions/ffffffff-ffff-ffff-ffff-ffffffffffff/resourceGroups/rg-prod/providers/Microsoft.Storage/storageAccounts/prodbackup"
  vm_dump="${STAGING_DATA_ROOT}/copy-to-ehr-dumps/pre-migrate.dump"
  copy_to_ehr_validate_dump_target "$vm_dump"
  if copy_to_ehr_validate_dump_target "$storage_ok"; then exit 1; fi
  if copy_to_ehr_validate_dump_target "/Users/john/live.dump"; then exit 1; fi
  if copy_to_ehr_validate_dump_target "/home/john/live.dump"; then exit 1; fi
  if copy_to_ehr_validate_dump_target "/tmp/live.dump"; then exit 1; fi
  if copy_to_ehr_validate_dump_target "$storage_other"; then exit 1; fi
  if copy_to_ehr_validate_dump_target "$storage_prod"; then exit 1; fi
  if copy_to_ehr_trial_url_file_allowed /dev/null; then exit 1; fi
)
if [[ $? -eq 0 ]]; then
  pass "storage ids and dump targets outside the staging VM are refused"
else
  fail "storage ids and dump targets outside the staging VM are refused"
fi

trial_url="$root_dir/trial.url"
{
  printf '%s\n' 'postgresql+psycopg://cbpg_e0a414184674:synthetic-trial-password-admin-0001@127.0.0.1:54130/cosmabot_standalone_copy_ehr_trial'
  printf '%s\n' 'postgresql+psycopg://cosmabot_runtime_e0a414184674:synthetic-trial-password-runtime-002@127.0.0.1:54130/cosmabot_standalone_copy_ehr_trial'
} >"$trial_url"
old_trial_url="$root_dir/old-trial.url"
printf '%s\n' 'postgresql+psycopg://cosmabot_copyehr_trial:synthetic-trial-password-admin-0001@127.0.0.1:54130/cosmabot_copy_ehr_trial' >"$old_trial_url"
same_pass_url="$root_dir/same-pass.url"
{
  printf '%s\n' 'postgresql+psycopg://cbpg_e0a414184674:synthetic-trial-password-admin-0001@127.0.0.1:54130/cosmabot_standalone_copy_ehr_trial'
  printf '%s\n' 'postgresql+psycopg://cosmabot_runtime_e0a414184674:synthetic-trial-password-admin-0001@127.0.0.1:54130/cosmabot_standalone_copy_ehr_trial'
} >"$same_pass_url"
live_url="$root_dir/live.url"
printf '%s\n' 'postgresql+psycopg://cosmabot_runtime_e0a414184674:synthetic-live-password-00000001@127.0.0.1:54111/cosmabot_standalone_e0a414184674' >"$live_url"
(
  # shellcheck disable=SC1090
  source "$target"
  copy_to_ehr_trial_url_file_allowed "$trial_url" || exit 1
  if copy_to_ehr_trial_url_file_allowed "$live_url"; then exit 1; fi
  if copy_to_ehr_trial_url_file_allowed "$old_trial_url"; then exit 1; fi
  if copy_to_ehr_trial_url_file_allowed "$same_pass_url"; then exit 1; fi
)
if [[ $? -eq 0 ]]; then
  pass "trial database url cannot be the live database"
else
  fail "trial database url cannot be the live database"
fi

(
  # shellcheck disable=SC1090
  source "$target"
  side=$(copy_to_ehr_render_side_port "e29bf5a2de0eddec1663b1185076472ef172b590")
  printf '%s\n' "$side" >"$root_dir/side.sh"
  grep -q 'SIDE_PORT_REFUSED_LIVE_DATABASE' "$root_dir/side.sh"
  grep -q 'cosmabot_copy_ehr_trial' "$root_dir/side.sh"
  grep -q '54130' "$root_dir/side.sh"
  grep -q 'COPY_TO_EHR_ENABLED' "$root_dir/side.sh"
  if grep -q 'copy_to_ehr_migrate_live' "$root_dir/side.sh"; then exit 1; fi
  if grep -q 'copy_to_ehr_stop_live_listeners' "$root_dir/side.sh"; then exit 1; fi
  if grep -E -q 'docker (stop|rm).*-r10-' "$root_dir/side.sh"; then exit 1; fi
  if grep -E -q 'blob download|scp ' "$root_dir/side.sh"; then exit 1; fi
  awk 'seen && $0 == "COPY_TO_EHR_BASH_BODY" {exit} seen {print} $0 == "exec /bin/bash <<'\''COPY_TO_EHR_BASH_BODY'\''" {seen=1}' "$root_dir/side.sh" >"$root_dir/side-inner.sh"
  bash -n "$root_dir/side-inner.sh"
  body=$(declare -f copy_to_ehr_cutover_sequence)
  printf '%s\n' "$body" >"$root_dir/sequence-body.txt"
  restore=$(awk '/copy_to_ehr_restore_gate/{print NR; exit}' "$root_dir/sequence-body.txt")
  stop=$(awk '/copy_to_ehr_stop_live_listeners/{print NR; exit}' "$root_dir/sequence-body.txt")
  migrate=$(awk '/copy_to_ehr_migrate_live/{print NR; exit}' "$root_dir/sequence-body.txt")
  [[ -n "$restore" && -n "$stop" && -n "$migrate" ]]
  [[ "$restore" -lt "$stop" && "$stop" -lt "$migrate" ]]
  cutover=$(copy_to_ehr_render_cutover "e29bf5a2de0eddec1663b1185076472ef172b590" "9dfd4cfd" "${STAGING_DATA_ROOT}/copy-to-ehr-dumps/pre-migrate.dump")
  printf '%s\n' "$cutover" >"$root_dir/cutover.sh"
  grep -q 'release-r10' "$root_dir/cutover.sh"
  grep -q 'pg_dump -Fc' "$root_dir/cutover.sh"
  grep -q 'copy_to_ehr_confirm_prior_identity' "$root_dir/cutover.sh"
  grep -q 'copy_to_ehr_cutover_trap_rollback' "$root_dir/cutover.sh"
  grep -q 'copy_to_ehr_assert_target_schema' "$root_dir/cutover.sh"
  if grep -E -q 'blob download|scp ' "$root_dir/cutover.sh"; then exit 1; fi
  awk 'seen && $0 == "COPY_TO_EHR_BASH_BODY" {exit} seen {print} $0 == "exec /bin/bash <<'\''COPY_TO_EHR_BASH_BODY'\''" {seen=1}' "$root_dir/cutover.sh" >"$root_dir/cutover-inner.sh"
  bash -n "$root_dir/cutover-inner.sh"
)
if [[ $? -eq 0 ]]; then
  pass "side port does not migrate or stop the live release"
else
  fail "side port does not migrate or stop the live release"
fi

(
  # shellcheck disable=SC1090
  source "$target"
  log="$root_dir/restore.log"
  : >"$log"
  dump_root="$root_dir/vmroot"
  dump="$dump_root/copy-to-ehr-dumps/pre-migrate.dump"
  mkdir -p "$(dirname "$dump")"
  live_db="cosmabot_standalone_e0a414184674"
  copy_to_ehr_pg_dump() { printf 'PGDMP' >"$1"; }
  copy_to_ehr_createdb() { printf 'CREATED\n' >>"$log"; }
  copy_to_ehr_pg_restore() { printf 'RESTORED_SCRATCH\n' >>"$log"; }
  copy_to_ehr_dropdb() { printf 'DROPPED\n' >>"$log"; }
  copy_to_ehr_psql() {
    if [[ "$2" == *version_num* && "$1" == "cosmabot_copy_ehr_scratch" ]]; then
      printf '%s\n' '000000000000'
      return 0
    fi
    if [[ "$2" == *version_num* ]]; then
      printf '%s\n' 'bb57e3d10c964'
      return 0
    fi
    printf '%s\n' '4'
  }
  copy_to_ehr_stop_live_listeners() { printf 'STOP\n' >>"$log"; }
  copy_to_ehr_migrate_live() { printf 'MIGRATE\n' >>"$log"; }
  if copy_to_ehr_cutover_sequence "$dump_root" "$dump" "$live_db"; then exit 1; fi
  [[ ! -s "${dump}.verified" ]]
  grep -q 'CREATED' "$log"
  grep -q 'DROPPED' "$log"
  if grep -q 'STOP' "$log"; then exit 1; fi
  if grep -q 'MIGRATE' "$log"; then exit 1; fi
)
if [[ $? -eq 0 ]]; then
  pass "cutover aborts when the scratch restore check fails"
else
  fail "cutover aborts when the scratch restore check fails"
fi

(
  # shellcheck disable=SC1090
  source "$target"
  log="$root_dir/migrate.log"
  : >"$log"
  dump_root="$root_dir/vmroot-empty"
  dump="$dump_root/copy-to-ehr-dumps/pre-migrate.dump"
  mkdir -p "$(dirname "$dump")"
  printf 'PGDMP' >"$dump"
  copy_to_ehr_run_live_migrate() { printf 'MIGRATED\n' >>"$log"; }
  if copy_to_ehr_migrate_live "$dump"; then exit 1; fi
  : >"$dump"
  if copy_to_ehr_migrate_live "$dump"; then exit 1; fi
  if [[ -s "$log" ]]; then exit 1; fi
)
if [[ $? -eq 0 ]]; then
  pass "cutover refuses to migrate without a verified dump"
else
  fail "cutover refuses to migrate without a verified dump"
fi

(
  # shellcheck disable=SC1090
  source "$target"
  log="$root_dir/rollback.log"
  : >"$log"
  dump_root="$root_dir/vmroot-ok"
  dump="$dump_root/copy-to-ehr-dumps/pre-migrate.dump"
  mkdir -p "$(dirname "$dump")"
  live_db="cosmabot_standalone_e0a414184674"
  copy_to_ehr_pg_dump() { printf 'PGDMP' >"$1"; }
  copy_to_ehr_createdb() { return 0; }
  copy_to_ehr_pg_restore() { return 0; }
  copy_to_ehr_dropdb() { return 0; }
  copy_to_ehr_psql() {
    if [[ "$2" == *datcollate* ]]; then
      printf 'C|C|-1|-\n'
      return 0
    fi
    if [[ "$2" == *pg_db_role_setting* ]]; then
      printf '%s\n' '-'
      return 0
    fi
    if [[ "$2" == *version_num* ]]; then
      printf '%s\n' 'bb57e3d10c964'
    else
      printf '%s\n' '4'
    fi
  }
  if ! copy_to_ehr_restore_gate "$dump_root" "$dump" "$live_db"; then exit 1; fi
  grep -qx 'verified' "${dump}.verified"
  copy_to_ehr_run_live_migrate() { printf 'MIGRATED\n' >>"$log"; return 0; }
  copy_to_ehr_migrate_live "$dump"
  grep -q 'MIGRATED' "$log"
  copy_to_ehr_restore_gate() { return 0; }
  copy_to_ehr_stop_live_listeners() { return 0; }
  copy_to_ehr_migrate_live() { return 0; }
  copy_to_ehr_psql() { printf '%s\n' 'a46f2c09d853'; }
  copy_to_ehr_start_new_listeners() { return 0; }
  copy_to_ehr_ready_for_pointer() { return 0; }
  copy_to_ehr_write_new_pointer() { return 0; }
  copy_to_ehr_post_switch_checks() { return 1; }
  copy_to_ehr_rollback_to_r10() { printf 'ROLLBACK_R10\n' >>"$log"; return 0; }
  if copy_to_ehr_cutover_sequence "$dump_root" "$dump" "$live_db"; then exit 1; fi
  grep -q 'ROLLBACK_R10' "$log"
  declare -f copy_to_ehr_write_prior_pointer | grep -q 'STAGING_PRIOR_RELEASE'
  declare -f copy_to_ehr_restore_dump_over_live | grep -q 'pg_restore'
)
if [[ $? -eq 0 ]]; then
  pass "verified restore can pass and a later failure rolls back to release-r10"
else
  fail "verified restore can pass and a later failure rolls back to release-r10"
fi

env_file="$root_dir/web.env"
umask 077
{
  printf 'VITE_WORKSPACE_FEATURE_PROFILE=operational-beta-v1\n'
  i=1
  while [[ "$i" -le 10 ]]; do
    printf 'VITE_PUBLIC_%s=SUPERSECRETVALUE\n' "$i"
    i=$((i + 1))
  done
} >"$env_file"
chmod 600 "$env_file"
(
  # shellcheck disable=SC1090
  source "$target"
  keys=$(copy_to_ehr_read_web_env_keys "$env_file")
  printf '%s\n' "$keys" | grep -q 'VITE_PUBLIC_10'
  if printf '%s\n' "$keys" | grep -q 'SUPERSECRETVALUE'; then exit 1; fi
  chmod 644 "$env_file"
  if copy_to_ehr_read_web_env_keys "$env_file"; then exit 1; fi
)
if [[ $? -eq 0 ]]; then
  pass "web env values are not printed"
else
  fail "web env values are not printed"
fi

(
  # shellcheck disable=SC1090
  source "$target"
  export COPY_TO_EHR_EXECUTE=0
  sample="$root_dir/sample-web.tar.gz"
  printf 'synthetic-web-archive' >"$sample"
  copy_to_ehr_ship_web "$sample" "${STAGING_DATA_ROOT}/release-copy-ehr-aaaaaaaaaaaa/cosmabot-web-sample.tar.gz" >"$root_dir/chunk.out"
  awk '
    /remote-script web-chunk-0 begin/ {capture=1; next}
    /remote-script web-chunk-0 end/ {capture=0}
    capture {print}
  ' "$root_dir/chunk.out" >"$root_dir/chunk.sh"
  awk 'seen && $0 == "COPY_TO_EHR_BASH_BODY" {exit} seen {print} $0 == "exec /bin/bash <<'\''COPY_TO_EHR_BASH_BODY'\''" {seen=1}' "$root_dir/chunk.sh" >"$root_dir/chunk-inner.sh"
  bash -n "$root_dir/chunk-inner.sh"
  grep -q 'CHUNK_OK' "$root_dir/chunk.sh"
  grep -q 'web archive chunks: 1' "$root_dir/chunk.out"
  chunk_line=$(awk '/web archive chunks:/{print NR; exit}' "$root_dir/chunk.out")
  invoke_line=$(awk '/remote-script web-chunk-0 begin/{print NR; exit}' "$root_dir/chunk.out")
  [[ -n "$chunk_line" && -n "$invoke_line" && "$chunk_line" -lt "$invoke_line" ]]
  if grep -q 'synthetic-web-archive' "$root_dir/chunk.out"; then exit 1; fi
)
if [[ $? -eq 0 ]]; then
  pass "web chunk command stays a script and does not print the archive bytes"
else
  fail "web chunk command stays a script and does not print the archive bytes"
fi

served_commit=9dfd4cfd0123456789abcdef0123456789abcdef
(
  # shellcheck disable=SC1090
  source "$target"
  log="$root_dir/version.log"
  : >"$log"
  curl() {
    if [[ "$*" == *"/version.json"* ]]; then
      printf '%s' "{\"commit\":\"${served_commit}\"}"
      return 0
    fi
    return 1
  }
  copy_to_ehr_stop_live_listeners() { printf 'STOP\n' >>"$log"; }
  copy_to_ehr_pg_dump() { printf 'DUMP\n' >>"$log"; }
  if copy_to_ehr_confirm_prior_identity "9dfd4cfd" \
    "cosmabot-nov1-api:6e65ffc6d892282e9f13cbd16c8a17e7592fa88c" \
    "9dfd4cfd0123456789abcdef0123456789abcdef"; then
    :
  else
    exit 1
  fi
  if copy_to_ehr_confirm_prior_identity "9dfd4cfd" \
    "cosmabot-nov1-api:6e65ffc6d892282e9f13cbd16c8a17e7592fa88c" \
    "6e65ffc6d892282e9f13cbd16c8a17e7592fa88c"; then
    exit 1
  fi
  curl() { return 1; }
  if copy_to_ehr_confirm_prior_identity "9dfd4cfd" \
    "cosmabot-nov1-api:6e65ffc6d892282e9f13cbd16c8a17e7592fa88c" \
    "9dfd4cfd0123456789abcdef0123456789abcdef"; then
    exit 1
  fi
  curl() {
    printf '%s' '{"commit":"6e65ffc6d892282e9f13cbd16c8a17e7592fa88c"}'
    return 0
  }
  if copy_to_ehr_confirm_prior_identity "9dfd4cfd" \
    "cosmabot-nov1-api:6e65ffc6d892282e9f13cbd16c8a17e7592fa88c" \
    "9dfd4cfd0123456789abcdef0123456789abcdef"; then
    exit 1
  fi
  main_body=$(declare -f copy_to_ehr_cutover_main)
  printf '%s\n' "$main_body" >"$root_dir/cutover-main-body.txt"
  version_line=$(awk '/copy_to_ehr_confirm_prior_identity/{print NR; exit}' "$root_dir/cutover-main-body.txt")
  sequence_line=$(awk '/copy_to_ehr_cutover_sequence/{print NR; exit}' "$root_dir/cutover-main-body.txt")
  [[ -n "$version_line" && -n "$sequence_line" && "$version_line" -lt "$sequence_line" ]]
  if [[ -s "$log" ]]; then exit 1; fi
) >"$root_dir/version.out" 2>"$root_dir/version.err"
if [[ $? -eq 0 ]] \
  && grep -q 'PRIOR_SHA_MISMATCH' "$root_dir/version.err" \
  && grep -q 'PRIOR_VERSION_UNREADABLE' "$root_dir/version.err" \
  && grep -q 'PRIOR_VERSION_MISMATCH' "$root_dir/version.err"; then
  pass "version mismatch or an unreadable version.json aborts before the dump"
else
  fail "version mismatch or an unreadable version.json aborts before the dump"
  cat "$root_dir/version.err" >&2 || true
fi

status=0
set +e
(
  # shellcheck disable=SC1090
  source "$target"
  log="$root_dir/trap.log"
  : >"$log"
  copy_to_ehr_rollback_to_r10() { printf 'TRAP_ROLLBACK\n' >>"$log"; return 0; }
  copy_to_ehr_arm_cutover_trap "$root_dir/trap.dump" "cosmabot_standalone_e0a414184674"
  false
) >"$root_dir/trap.out" 2>"$root_dir/trap.err"
status=$?
set -e
if [[ "$status" -ne 0 ]] \
  && grep -q 'TRAP_ROLLBACK' "$root_dir/trap.log" \
  && grep -q 'CUTOVER_ROLLBACK' "$root_dir/trap.err"; then
  pass "a death after listeners stop runs rollback"
else
  fail "a death after listeners stop runs rollback"
  cat "$root_dir/trap.err" >&2 || true
fi

status=0
set +e
(
  # shellcheck disable=SC1090
  source "$target"
  copy_to_ehr_remove_new_listeners() { return 0; }
  copy_to_ehr_restore_dump_over_live() { return 1; }
  copy_to_ehr_start_prior_listeners() { return 0; }
  copy_to_ehr_rollback_to_r10 "$root_dir/missing.dump" "cosmabot_standalone_e0a414184674"
) >"$root_dir/failed-rollback.out" 2>"$root_dir/failed-rollback.err"
status=$?
set -e
if [[ "$status" -ne 0 ]] && grep -q 'CUTOVER_ROLLBACK_FAILED' "$root_dir/failed-rollback.err"; then
  pass "a failed rollback exits non-zero with CUTOVER_ROLLBACK_FAILED"
else
  fail "a failed rollback exits non-zero with CUTOVER_ROLLBACK_FAILED"
  cat "$root_dir/failed-rollback.err" >&2 || true
fi

status=0
set +e
(
  # shellcheck disable=SC1090
  source "$target"
  log="$root_dir/schema.log"
  : >"$log"
  copy_to_ehr_restore_gate() { return 0; }
  copy_to_ehr_stop_live_listeners() { printf 'STOP\n' >>"$log"; return 0; }
  copy_to_ehr_migrate_live() { printf 'MIGRATE\n' >>"$log"; return 0; }
  copy_to_ehr_psql() { printf '%s\n' 'bb57e3d10c964'; }
  copy_to_ehr_start_new_listeners() { printf 'STARTED\n' >>"$log"; return 0; }
  copy_to_ehr_rollback_to_r10() { printf 'SCHEMA_ROLLBACK\n' >>"$log"; return 0; }
  if copy_to_ehr_cutover_sequence "$root_dir/schema-root" "$root_dir/schema.dump" "cosmabot_standalone_e0a414184674"; then
    exit 1
  fi
  grep -q 'STOP' "$log"
  grep -q 'MIGRATE' "$log"
  grep -q 'SCHEMA_ROLLBACK' "$log"
  if grep -q 'STARTED' "$log"; then exit 1; fi
) >"$root_dir/schema.out" 2>"$root_dir/schema.err"
status=$?
set -e
if [[ "$status" -eq 0 ]] && grep -q 'SCHEMA_NOT_TARGET' "$root_dir/schema.err"; then
  pass "a database that is not the target schema rolls back"
else
  fail "a database that is not the target schema rolls back"
  cat "$root_dir/schema.err" >&2 || true
fi

status=0
set +e
(
  # shellcheck disable=SC1090
  source "$target"
  payload=$(python3 -c 'import json,sys; sys.stdout.write(json.dumps({"value":[{"message":"RESTORE_CHECK_OK\nLOOKING\nCOUNT alembic_version=4\nOKAY\nthis line is OK\nAPI_BUILD_FAILED\nWEB_ARCHIVE_MISSING\nLIVE_POINTER_CHANGED\nPG_DUMP_FAILED\nSHA_MISMATCH\nDIRTY_TREE\nACTIVE_RELEASE_NOT_R10\nNFT_TRIAL_RULE_FAILED\nLIVE_POSTGRES_CONTAINER_NOT_FOUND\n"}]}))')
  filtered=$(printf '%s' "$payload" | copy_to_ehr_filter_run_output)
  printf '%s\n' "$filtered" | grep -qx 'RESTORE_CHECK_OK'
  printf '%s\n' "$filtered" | grep -qx 'COUNT alembic_version=4'
  printf '%s\n' "$filtered" | grep -qx 'this line is OK'
  printf '%s\n' "$filtered" | grep -qx 'API_BUILD_FAILED'
  printf '%s\n' "$filtered" | grep -qx 'WEB_ARCHIVE_MISSING'
  printf '%s\n' "$filtered" | grep -qx 'LIVE_POINTER_CHANGED'
  printf '%s\n' "$filtered" | grep -qx 'PG_DUMP_FAILED'
  printf '%s\n' "$filtered" | grep -qx 'SHA_MISMATCH'
  printf '%s\n' "$filtered" | grep -qx 'DIRTY_TREE'
  printf '%s\n' "$filtered" | grep -qx 'ACTIVE_RELEASE_NOT_R10'
  printf '%s\n' "$filtered" | grep -qx 'NFT_TRIAL_RULE_FAILED'
  printf '%s\n' "$filtered" | grep -qx 'LIVE_POSTGRES_CONTAINER_NOT_FOUND'
  if printf '%s\n' "$filtered" | grep -qx 'LOOKING'; then exit 1; fi
  if printf '%s\n' "$filtered" | grep -qx 'OKAY'; then exit 1; fi
)
status=$?
set -e
if [[ "$status" -eq 0 ]]; then
  pass "run-command output keeps whole status tokens"
else
  fail "run-command output keeps whole status tokens"
fi

status=0
set +e
(
  # shellcheck disable=SC1090
  source "$target"
  body=$(declare -f copy_to_ehr_execute)
  printf '%s\n' "$body" >"$root_dir/execute-body.txt"
  install_line=$(awk '/install-client-deps\.sh/{print NR; exit}' "$root_dir/execute-body.txt")
  build_line=$(awk '/copy_to_ehr_run_web_build/{print NR; exit}' "$root_dir/execute-body.txt")
  web_line=$(awk '/cd "\$workdir\/src\/web"/{print NR; exit}' "$root_dir/execute-body.txt")
  [[ -n "$install_line" && -n "$build_line" && -n "$web_line" ]]
  [[ "$install_line" -lt "$build_line" && "$web_line" -lt "$build_line" ]]
  printf '%s\n' "$body" | grep -q '\$workdir/src/scripts/install-client-deps.sh'
  if printf '%s\n' "$body" | grep -q 'pnpm install'; then exit 1; fi
  declare -f copy_to_ehr_run_web_build | grep -q 'corepack pnpm run build'
)
status=$?
set -e
if [[ "$status" -eq 0 ]]; then
  pass "execute installs client deps before the web build"
else
  fail "execute installs client deps before the web build"
fi

status=0
set +e
(
  # shellcheck disable=SC1090
  source "$target"
  work="$root_dir/env-work"
  mkdir -p "$work/src/web"
  independent="$root_dir/independent.env"
  operational="$root_dir/operational.env"
  umask 077
  cat >"$independent" <<'EOF'
VITE_WORKSPACE_FEATURE_PROFILE=independent-beta-v1
VITE_WORKSPACE_ORGANIZATION_ID=org_synthetic_beta
VITE_WORKSPACE_CAPTURE_MODE=disabled
VITE_COSMANEURA_WEB_ORIGIN=https://core.synthetic.example
VITE_CAPTURE_UPLOAD_ORIGINS=https://upload.synthetic.example
VITE_WORKSPACE_DATA_MODE=synthetic
VITE_WORKSPACE_HOSTED_CLIENT=web
VITE_WORKSPACE_HOSTED_API_ORIGIN=https://api.synthetic.example
VITE_API_BASE=https://api.synthetic.example
VITE_WORKSPACE_WEB_ORIGIN=https://app.synthetic.example
VITE_CLERK_PUBLISHABLE_KEY=pk_test_syntheticdummy
EOF
  cat >"$operational" <<'EOF'
VITE_WORKSPACE_FEATURE_PROFILE=operational-beta-v1
VITE_WORKSPACE_HOSTED_ENABLED=true
VITE_WORKSPACE_CAPTURE_MODE=synthetic
VITE_COSMANEURA_WEB_ORIGIN=https://core.synthetic.example
VITE_CAPTURE_UPLOAD_ORIGINS=https://upload.synthetic.example
VITE_WORKSPACE_DATA_MODE=synthetic
VITE_WORKSPACE_HOSTED_CLIENT=web
VITE_WORKSPACE_HOSTED_API_ORIGIN=https://api.synthetic.example
VITE_API_BASE=https://api.synthetic.example
VITE_WORKSPACE_WEB_ORIGIN=https://app.synthetic.example
VITE_CLERK_PUBLISHABLE_KEY=pk_test_syntheticdummy
EOF
  chmod 600 "$independent" "$operational"
  independent_before=$(cksum "$independent")
  operational_before=$(cksum "$operational")
  keys=$(copy_to_ehr_read_web_env_keys "$independent")
  printf '%s\n' "$keys" | grep -qx 'VITE_COSMANEURA_WEB_ORIGIN'
  if printf '%s\n' "$keys" | grep -q 'syntheticdummy\|synthetic.example'; then exit 1; fi
  copy_out="$work/src/web/.env.production"
  stage_out="$root_dir/stage.out"
  copy_to_ehr_stage_web_env "$independent" "$copy_out" >"$stage_out"
  [[ ! -s "$stage_out" ]]
  mode=$(python3 -c 'import os,sys; print(format(os.stat(sys.argv[1]).st_mode & 0o777, "o"))' "$copy_out")
  [[ "$mode" == "600" ]]
  [[ "$(cksum "$independent")" == "$independent_before" ]]
  grep -q '^VITE_WORKSPACE_FEATURE_PROFILE=independent-beta-v1$' "$copy_out"
  grep -q '^VITE_WORKSPACE_ORGANIZATION_ID=org_synthetic_beta$' "$copy_out"
  if grep -q '^VITE_COSMANEURA_WEB_ORIGIN=' "$copy_out"; then exit 1; fi
  if grep -q '^VITE_CAPTURE_UPLOAD_ORIGINS=' "$copy_out"; then exit 1; fi
  operational_out="$work/operational.env"
  copy_to_ehr_stage_web_env "$operational" "$operational_out"
  [[ "$(cksum "$operational")" == "$operational_before" ]]
  cmp -s "$operational" "$operational_out"
  standalone="$root_dir/standalone.env"
  sed 's/^VITE_WORKSPACE_FEATURE_PROFILE=.*/VITE_WORKSPACE_FEATURE_PROFILE=standalone-practice-v1/' "$independent" >"$standalone"
  chmod 600 "$standalone"
  standalone_out="$work/standalone.env"
  copy_to_ehr_stage_web_env "$standalone" "$standalone_out"
  if grep -q '^VITE_COSMANEURA_WEB_ORIGIN=' "$standalone_out"; then exit 1; fi
  if grep -q '^VITE_CAPTURE_UPLOAD_ORIGINS=' "$standalone_out"; then exit 1; fi
  COPY_TO_EHR_WEB_ENV_COPY="$copy_out"
  copy_to_ehr_cleanup_web_env_copy
  [[ ! -e "$copy_out" ]]
  [[ -f "$independent" ]]
  body=$(declare -f copy_to_ehr_execute)
  printf '%s\n' "$body" >"$root_dir/execute-env-body.txt"
  read_line=$(awk '/copy_to_ehr_read_web_env_keys/{print NR; exit}' "$root_dir/execute-env-body.txt")
  stage_line=$(awk '/copy_to_ehr_stage_web_env/{print NR; exit}' "$root_dir/execute-env-body.txt")
  copy_line=$(awk '/COPY_TO_EHR_WEB_ENV_COPY=/{print NR; exit}' "$root_dir/execute-env-body.txt")
  trap_line=$(awk '/trap copy_to_ehr_local_exit/{print NR; exit}' "$root_dir/execute-env-body.txt")
  [[ -n "$read_line" && -n "$stage_line" && -n "$copy_line" && -n "$trap_line" ]]
  [[ "$read_line" -lt "$stage_line" && "$stage_line" -lt "$copy_line" && "$copy_line" -lt "$trap_line" ]]
)
status=$?
set -e
if [[ "$status" -eq 0 ]]; then
  pass "independent profile build copy drops forced-empty origins"
else
  fail "independent profile build copy drops forced-empty origins"
fi

write_profile_env() {
  local path="$1" profile="$2" extra="$3"
  umask 077
  {
    printf 'VITE_WORKSPACE_FEATURE_PROFILE=%s\n' "$profile"
    printf '%s\n' "$extra"
    printf 'VITE_WORKSPACE_HOSTED_ENABLED=true\n'
    printf 'VITE_WORKSPACE_CAPTURE_MODE=synthetic\n'
    printf 'VITE_COSMANEURA_WEB_ORIGIN=https://core.synthetic.example\n'
    printf 'VITE_CAPTURE_UPLOAD_ORIGINS=https://upload.synthetic.example\n'
    printf 'VITE_WORKSPACE_DATA_MODE=synthetic\n'
    printf 'VITE_WORKSPACE_HOSTED_CLIENT=web\n'
    printf 'VITE_WORKSPACE_HOSTED_API_ORIGIN=https://api.synthetic.example\n'
    printf 'VITE_API_BASE=https://api.synthetic.example\n'
    printf 'VITE_WORKSPACE_WEB_ORIGIN=https://app.synthetic.example\n'
  } >"$path"
  chmod 600 "$path"
}

status=0
set +e
(
  # shellcheck disable=SC1090
  source "$target"
  export COPY_TO_EHR_EXECUTE=1
  reached="$root_dir/sentinel.reached"
  : >"$reached"
  az() {
    printf '%s' '{"value":[{"message":"API_BUILD_FAILED\n"}]}'
    return 0
  }
  copy_to_ehr_invoke_remote api-build 'echo remote'
  printf 'REACHED_NEXT\n' >>"$reached"
) >"$root_dir/sentinel.out" 2>"$root_dir/sentinel.err"
status=$?
set -e
if [[ "$status" -ne 0 ]] \
  && grep -qx 'API_BUILD_FAILED' "$root_dir/sentinel.out" \
  && ! grep -q 'REACHED_NEXT' "$root_dir/sentinel.reached"; then
  pass "az exit 0 with a failed remote step stops before the next step"
else
  fail "az exit 0 with a failed remote step stops before the next step"
fi

status=0
set +e
(
  # shellcheck disable=SC1090
  source "$target"
  export COPY_TO_EHR_EXECUTE=1
  az() {
    printf '%s' '{"value":[{"message":"API_IMAGE_OK\n"}]}'
    return 0
  }
  copy_to_ehr_invoke_remote api-build 'echo remote'
  az() {
    printf '%s' '{"value":[{"message":"CHUNK_OK 0\n"}]}'
    return 0
  }
  copy_to_ehr_invoke_remote web-chunk-0 'echo remote'
  COPY_TO_EHR_ARCHIVE_SHA256=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
  az() {
    printf '%s' '{"value":[{"message":"ARCHIVE_SHA256 bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n"}]}'
    return 0
  }
  if copy_to_ehr_invoke_remote web-verify 'echo remote'; then
    exit 1
  fi
) >"$root_dir/sentinel-ok.out" 2>"$root_dir/sentinel-ok.err"
status=$?
set -e
if [[ "$status" -ne 0 ]] && grep -q 'did not report success' "$root_dir/sentinel-ok.err"; then
  pass "a web archive hash mismatch exits non-zero"
else
  fail "a web archive hash mismatch exits non-zero"
fi

status=0
set +e
(
  # shellcheck disable=SC1090
  source "$target"
  secret='SUPERSECRETVALUE'
  bad="$root_dir/bad-env"
  check_refused() {
    local label="$1"
    : >"$root_dir/env-names.out"
    : >"$root_dir/env-names.err"
    if copy_to_ehr_read_web_env_keys "$bad" >"$root_dir/env-names.out" 2>"$root_dir/env-names.err"; then
      printf 'accepted %s\n' "$label" >&2
      exit 1
    fi
    grep -qx 'WEB_ENV_REFUSED' "$root_dir/env-names.err"
    if grep -q "$secret" "$root_dir/env-names.out" "$root_dir/env-names.err"; then
      printf 'echoed %s\n' "$label" >&2
      exit 1
    fi
  }
  umask 077
  printf 'VITE_PUBLIC_1="%s"\n' "$secret" >"$bad"
  chmod 600 "$bad"
  check_refused quoted
  printf 'VITE_PUBLIC_1 = %s\n' "$secret" >"$bad"
  chmod 600 "$bad"
  check_refused spaced
  printf 'VITE_PUBLIC_1=%s # note\n' "$secret" >"$bad"
  chmod 600 "$bad"
  check_refused comment
  printf 'export VITE_PUBLIC_1=%s\n' "$secret" >"$bad"
  chmod 600 "$bad"
  check_refused export
  printf 'VITE_PUBLIC_1=%s\r\n' "$secret" >"$bad"
  chmod 600 "$bad"
  check_refused crlf
  {
    printf 'VITE_WORKSPACE_FEATURE_PROFILE=operational-beta-v1\n'
    printf 'VITE_PUBLIC_1=%s\n' "$secret"
    printf 'VITE_PUBLIC_1=%s\n' "$secret"
    i=2
    while [[ "$i" -le 9 ]]; do
      printf 'VITE_PUBLIC_%s=value\n' "$i"
      i=$((i + 1))
    done
  } >"$bad"
  chmod 600 "$bad"
  check_refused duplicate
  {
    printf 'VITE_PUBLIC_1=%s\n' "$secret"
    i=2
    while [[ "$i" -le 11 ]]; do
      printf 'VITE_PUBLIC_%s=value\n' "$i"
      i=$((i + 1))
    done
  } >"$bad"
  chmod 600 "$bad"
  check_refused 'missing profile'
  write_profile_env "$bad" 'not-a-profile' 'VITE_PUBLIC_1=value'
  check_refused 'unknown profile'
  printf 'VITE_PUBLIC_1=%s$HOME\n' "$secret" >"$bad"
  chmod 600 "$bad"
  check_refused dollar
  printf 'VITE_PUBLIC_1=%s\\path\n' "$secret" >"$bad"
  chmod 600 "$bad"
  check_refused backslash
) >"$root_dir/env-shape.out" 2>"$root_dir/env-shape.err"
status=$?
set -e
if [[ "$status" -eq 0 ]]; then
  pass "quoted spaced commented duplicate and CRLF env lines are refused by name only"
else
  fail "quoted spaced commented duplicate and CRLF env lines are refused by name only"
  cat "$root_dir/env-shape.err" >&2 || true
fi

status=0
set +e
(
  # shellcheck disable=SC1090
  source "$target"
  export VITE_API_BASE='https://evil.synthetic.example'
  export VITE_BUILD_SHA='inherited'
  sha='e29bf5a2de0eddec1663b1185076472ef172b590'
  corepack() {
    if [[ -n "${VITE_API_BASE:-}" ]]; then
      printf 'LEAK\n' >&2
      return 1
    fi
    [[ "${VITE_BUILD_SHA:-}" == "$sha" ]]
  }
  copy_to_ehr_run_web_build "$sha"
) >"$root_dir/build-env.out" 2>"$root_dir/build-env.err"
status=$?
set -e
if [[ "$status" -eq 0 ]] && ! grep -q 'LEAK' "$root_dir/build-env.err"; then
  pass "the web build drops inherited VITE variables except VITE_BUILD_SHA"
else
  fail "the web build drops inherited VITE variables except VITE_BUILD_SHA"
fi

status=0
set +e
(
  # shellcheck disable=SC1090
  source "$target"
  work="$root_dir/trap-env"
  mkdir -p "$work"
  good="$root_dir/trap-good.env"
  write_profile_env "$good" operational-beta-v1 'VITE_PUBLIC_1=value'
  dest="$work/.env.production"
  copy_to_ehr_stage_web_env "$good" "$dest"
  COPY_TO_EHR_WEB_ENV_COPY="$dest"
  trap copy_to_ehr_local_exit EXIT
  trap copy_to_ehr_local_signal INT TERM HUP
  false
) >"$root_dir/exit-trap.out" 2>"$root_dir/exit-trap.err"
status=$?
set -e
if [[ "$status" -ne 0 && ! -e "$root_dir/trap-env/.env.production" ]]; then
  pass "EXIT trap removes the env copy when the build fails"
else
  fail "EXIT trap removes the env copy when the build fails"
fi

status=0
set +e
(
  # shellcheck disable=SC1090
  source "$target"
  work="$root_dir/signal-env"
  mkdir -p "$work"
  good="$root_dir/signal-good.env"
  write_profile_env "$good" operational-beta-v1 'VITE_PUBLIC_1=value'
  dest="$work/.env.production"
  copy_to_ehr_stage_web_env "$good" "$dest"
  COPY_TO_EHR_WEB_ENV_COPY="$dest"
  trap copy_to_ehr_local_exit EXIT
  trap copy_to_ehr_local_signal INT TERM HUP
  sh -c 'kill -TERM "$PPID"'
) >"$root_dir/signal-trap.out" 2>"$root_dir/signal-trap.err"
status=$?
set -e
if [[ "$status" -ne 0 && ! -e "$root_dir/signal-env/.env.production" ]]; then
  pass "TERM trap removes the env copy"
else
  fail "TERM trap removes the env copy"
fi

status=0
set +e
(
  # shellcheck disable=SC1090
  source "$target"
  work="$root_dir/preexisting-env"
  mkdir -p "$work"
  good="$root_dir/preexisting-good.env"
  write_profile_env "$good" operational-beta-v1 'VITE_PUBLIC_1=value'
  dest="$work/.env.production"
  printf 'keep-me\n' >"$dest"
  chmod 600 "$dest"
  if copy_to_ehr_stage_web_env "$good" "$dest"; then
    exit 1
  fi
  grep -qx 'keep-me' "$dest"
  unset COPY_TO_EHR_WEB_ENV_COPY
  copy_to_ehr_cleanup_web_env_copy
  grep -qx 'keep-me' "$dest"
  example="$work/.env.example"
  printf 'VITE_COSMANEURA_WEB_ORIGIN=https://example.synthetic.example\nVITE_CAPTURE_UPLOAD_ORIGINS=https://upload.synthetic.example\n' >"$example"
  shadow="$work/.env.local"
  printf '# VITE_COSMANEURA_WEB_ORIGIN=https://comment.synthetic.example\n' >"$shadow"
  independent="$root_dir/shadow-independent.env"
  cp "$root_dir/independent.env" "$independent" 2>/dev/null || true
  if [[ ! -f "$independent" ]]; then
    cat >"$independent" <<'EOF'
VITE_WORKSPACE_FEATURE_PROFILE=independent-beta-v1
VITE_WORKSPACE_ORGANIZATION_ID=org_synthetic_beta
VITE_WORKSPACE_CAPTURE_MODE=disabled
VITE_COSMANEURA_WEB_ORIGIN=https://core.synthetic.example
VITE_CAPTURE_UPLOAD_ORIGINS=https://upload.synthetic.example
VITE_WORKSPACE_DATA_MODE=synthetic
VITE_WORKSPACE_HOSTED_CLIENT=web
VITE_WORKSPACE_HOSTED_API_ORIGIN=https://api.synthetic.example
VITE_API_BASE=https://api.synthetic.example
VITE_WORKSPACE_WEB_ORIGIN=https://app.synthetic.example
VITE_CLERK_PUBLISHABLE_KEY=pk_test_syntheticdummy
EOF
    chmod 600 "$independent"
  fi
  rm -f -- "$dest"
  copy_to_ehr_stage_web_env "$independent" "$dest" >"$root_dir/shadow-ok.out" 2>"$root_dir/shadow-ok.err"
  [[ -f "$dest" ]]
  if grep -q 'example.synthetic.example' "$root_dir/shadow-ok.out" "$root_dir/shadow-ok.err"; then
    exit 1
  fi
  rm -f -- "$dest"
  printf 'VITE_COSMANEURA_WEB_ORIGIN=https://shadow.synthetic.example\n' >"$shadow"
  chmod 600 "$shadow"
  if copy_to_ehr_stage_web_env "$independent" "$dest" >"$root_dir/shadow.out" 2>"$root_dir/shadow.err"; then
    exit 1
  fi
  [[ ! -e "$dest" ]]
  grep -qx 'WEB_ENV_REFUSED' "$root_dir/shadow.err"
  if grep -q 'shadow.synthetic.example' "$root_dir/shadow.out" "$root_dir/shadow.err"; then
    exit 1
  fi
) >"$root_dir/preexisting.out" 2>"$root_dir/preexisting.err"
status=$?
set -e
if [[ "$status" -eq 0 ]]; then
  pass "cleanup does not delete a pre-existing env file and refuses a shadow key"
else
  fail "cleanup does not delete a pre-existing env file and refuses a shadow key"
  cat "$root_dir/preexisting.err" >&2 || true
fi

status=0
set +e
(
  # shellcheck disable=SC1090
  source "$target"
  export COPY_TO_EHR_READY_TRIES=2
  sleep() { return 0; }
  docker() { return 1; }
  if copy_to_ehr_wait_postgres trial-pg 54130; then
    exit 1
  fi
  curl() { return 1; }
  if copy_to_ehr_wait_listener 54120 54122 e29bf5a2de0eddec1663b1185076472ef172b590; then
    exit 1
  fi
) >"$root_dir/ready.out" 2>"$root_dir/ready.err"
status=$?
set -e
if [[ "$status" -eq 0 ]] \
  && grep -q 'POSTGRES_NOT_READY 54130' "$root_dir/ready.err" \
  && grep -q 'LISTENER_NOT_READY 54120 54122' "$root_dir/ready.err" \
  && ! grep -q 'SIDE_PORT_REFUSED_LIVE_DATABASE' "$root_dir/ready.err"; then
  pass "readiness timeout uses its own token"
else
  fail "readiness timeout uses its own token"
fi

status=0
set +e
(
  # shellcheck disable=SC1090
  source "$target"
  vm="$root_dir/restore-vm"
  STAGING_DATA_ROOT="$vm"
  dump="$vm/copy-to-ehr-dumps/pre-migrate.dump"
  mkdir -p "$(dirname "$dump")"
  printf 'PGDMP' >"$dump"
  printf 'alembic_version 4\naudit_events 4\npractice_owner_reservations 4\n' >"${dump}.counts"
  chmod 600 "$dump" "${dump}.counts"
  COPY_TO_EHR_PG_CONTAINER=pg-stub
  COPY_TO_EHR_DB_TOUCHED=1
  copy_to_ehr_psql() {
    case "$2" in
      *datcollate*) printf 'C|C|-1|-\n' ;;
      *pg_db_role_setting*) printf '%s\n' '-' ;;
      *pg_get_userbyid*) printf 'postgres\n' ;;
      *pg_encoding_to_char*) printf 'UTF8\n' ;;
      *version_num*) printf 'changed000000\n' ;;
      *) printf '9\n' ;;
    esac
  }
  docker() {
    printf '%s\n' "$*" >>"$root_dir/restore-docker.log"
    if [[ "$*" == *pg_restore* ]]; then
      return 1
    fi
    return 0
  }
  if copy_to_ehr_rollback_to_r10 "$dump" cosmabot_standalone_e0a414184674; then
    exit 1
  fi
  grep -q -- '--single-transaction' "$root_dir/restore-docker.log"
  grep -q -- '--exit-on-error' "$root_dir/restore-docker.log"
  grep -q -- '--owner postgres' "$root_dir/restore-docker.log"
  grep -q -- '--encoding UTF8' "$root_dir/restore-docker.log"
  grep -q -- '--template template0' "$root_dir/restore-docker.log"
  grep -q -- '--dbname cosmabot_standalone_e0a414184674_copy_ehr_in' "$root_dir/restore-docker.log"
  if grep -E -q 'dropdb --if-exists --no-password cosmabot_standalone_e0a414184674$' "$root_dir/restore-docker.log"; then
    exit 1
  fi
  if grep -q -- '--no-owner' "$root_dir/restore-docker.log"; then
    exit 1
  fi
  if grep -q -- '--clean' "$root_dir/restore-docker.log"; then
    exit 1
  fi
) >"$root_dir/pg-restore.out" 2>"$root_dir/pg-restore.err"
status=$?
set -e
if [[ "$status" -eq 0 ]] && grep -q 'CUTOVER_ROLLBACK_FAILED' "$root_dir/pg-restore.err"; then
  pass "a failing pg_restore rolls back non-zero without --clean --no-owner"
else
  fail "a failing pg_restore rolls back non-zero without --clean --no-owner"
  cat "$root_dir/pg-restore.err" >&2 || true
fi

status=0
set +e
(
  # shellcheck disable=SC1090
  source "$target"
  vm="$root_dir/restore-vm-count"
  STAGING_DATA_ROOT="$vm"
  dump="$vm/copy-to-ehr-dumps/pre-migrate.dump"
  mkdir -p "$(dirname "$dump")"
  printf 'PGDMP' >"$dump"
  printf 'alembic_version 4\naudit_events 4\npractice_owner_reservations 4\n' >"${dump}.counts"
  chmod 600 "$dump" "${dump}.counts"
  COPY_TO_EHR_PG_CONTAINER=pg-stub
  COPY_TO_EHR_DB_TOUCHED=1
  : >"$root_dir/count-start.log"
  docker() { return 0; }
  copy_to_ehr_psql() {
    case "$2" in
      *datcollate*) printf 'C|C|-1|-\n' ;;
      *pg_db_role_setting*) printf '%s\n' '-' ;;
      *pg_get_userbyid*) printf 'postgres\n' ;;
      *pg_encoding_to_char*) printf 'UTF8\n' ;;
      *) printf 'wrong\n' ;;
    esac
    return 0
  }
  copy_to_ehr_start_prior_listeners() { printf 'STARTED\n' >>"$root_dir/count-start.log"; return 0; }
  if copy_to_ehr_rollback_to_r10 "$dump" cosmabot_standalone_e0a414184674; then
    exit 1
  fi
  if grep -q 'STARTED' "$root_dir/count-start.log"; then
    exit 1
  fi
) >"$root_dir/count-restore.out" 2>"$root_dir/count-restore.err"
status=$?
set -e
if [[ "$status" -eq 0 ]] && grep -q 'PG_RESTORE_FAILED' "$root_dir/count-restore.err"; then
  pass "row-count mismatch blocks release-r10 from starting"
else
  fail "row-count mismatch blocks release-r10 from starting"
fi

status=0
set +e
(
  # shellcheck disable=SC1090
  source "$target"
  COPY_TO_EHR_SHA=e29bf5a2de0eddec1663b1185076472ef172b590
  copy_to_ehr_write_migrate_env() { return 1; }
  if copy_to_ehr_run_live_migrate; then
    exit 1
  fi
  copy_to_ehr_write_migrate_env() { printf 'x\n' >"$2"; return 0; }
  git() { return 1; }
  if copy_to_ehr_run_live_migrate; then
    exit 1
  fi
) >"$root_dir/migrate-check.out" 2>"$root_dir/migrate-check.err"
status=$?
set -e
if [[ "$status" -eq 0 ]]; then
  pass "migrate checks the env writer and the clone before it can succeed"
else
  fail "migrate checks the env writer and the clone before it can succeed"
fi

status=0
set +e
(
  # shellcheck disable=SC1090
  source "$target"
  copy_to_ehr_rollback_to_r10() { return 0; }
  copy_to_ehr_clear_cutover_marker() { return 0; }
  COPY_TO_EHR_TRAP_DUMP="$root_dir/marker.dump"
  COPY_TO_EHR_TRAP_DB=cosmabot_standalone_e0a414184674
  true
  copy_to_ehr_cutover_trap_rollback
) >"$root_dir/int-zero.out" 2>"$root_dir/int-zero.err"
status=$?
set -e
if [[ "$status" -ne 0 ]] && grep -q 'CUTOVER_ROLLBACK' "$root_dir/int-zero.err"; then
  pass "a rollback handler exits non-zero even when the prior status was 0"
else
  fail "a rollback handler exits non-zero even when the prior status was 0"
fi

status=0
set +e
(
  # shellcheck disable=SC1090
  source "$target"
  owned="$root_dir/owned-work"
  mkdir -p "$owned/keep"
  COPY_TO_EHR_OWNED_WORKDIR="$owned"
  copy_to_ehr_local_exit
  [[ ! -e "$owned" ]]
) >"$root_dir/owned.out" 2>"$root_dir/owned.err"
status=$?
set -e
if [[ "$status" -eq 0 ]]; then
  pass "owned build directory cleanup removes the work tree"
else
  fail "owned build directory cleanup removes the work tree"
fi

status=0
set +e
(
  # shellcheck disable=SC1090
  source "$target"
  edge="$root_dir/edge-src"
  mkdir -p "$edge/release-r10" "$edge/release-r6r1"
  printf 'listen 127.0.0.1:54110;\nlisten 172.30.241.1:54112;\n' >"$edge/release-r10/edge-nginx.conf"
  printf 'listen 127.0.0.1:54110;\n' >"$edge/release-r6r1/edge-nginx.conf"
  chosen=$(copy_to_ehr_edge_conf_source "$edge")
  [[ "$chosen" == "$edge/release-r10/edge-nginx.conf" ]]
  copy_to_ehr_write_trial_edge "$chosen" "$edge/trial.conf"
  python3 -c 'import os,sys; mode=os.stat(sys.argv[1]).st_mode & 0o777; raise SystemExit(0 if mode == 0o644 else 1)' "$edge/trial.conf"
  grep -q '127.0.0.1:54120' "$edge/trial.conf"
  grep -q '127.0.0.1:54122' "$edge/trial.conf"
  if grep -q '54110' "$edge/trial.conf"; then exit 1; fi
  if grep -q '54112' "$edge/trial.conf"; then exit 1; fi
  rm -f "$edge/release-r10/edge-nginx.conf"
  chosen=$(copy_to_ehr_edge_conf_source "$edge")
  [[ "$chosen" == "$edge/release-r6r1/edge-nginx.conf" ]]
  side=$(copy_to_ehr_render_side_port e29bf5a2de0eddec1663b1185076472ef172b590)
  cutover=$(copy_to_ehr_render_cutover e29bf5a2de0eddec1663b1185076472ef172b590 9dfd4cfd "${STAGING_DATA_ROOT}/copy-to-ehr-dumps/pre-migrate.dump")
  printf '%s\n' "$side" >"$root_dir/edge-side.sh"
  printf '%s\n' "$cutover" >"$root_dir/edge-cutover.sh"
  grep -q 'copy_to_ehr_edge_conf_source' "$root_dir/edge-side.sh"
  grep -q 'copy_to_ehr_edge_conf_source' "$root_dir/edge-cutover.sh"
  grep -q 'copy_to_ehr_run_migrate_py' "$root_dir/edge-side.sh"
  if grep -q 'copy_to_ehr_migrate_live' "$root_dir/edge-side.sh"; then exit 1; fi
  side_body=$(declare -f copy_to_ehr_side_port_main)
  printf '%s\n' "$side_body" >"$root_dir/side-body.txt"
  pg_line=$(awk '/copy_to_ehr_wait_postgres/{print NR; exit}' "$root_dir/side-body.txt")
  migrate_line=$(awk '/copy_to_ehr_run_migrate_py/{print NR; exit}' "$root_dir/side-body.txt")
  listener_line=$(awk '/copy_to_ehr_wait_listener/{print NR; exit}' "$root_dir/side-body.txt")
  [[ -n "$pg_line" && -n "$migrate_line" && -n "$listener_line" ]]
  [[ "$pg_line" -lt "$migrate_line" && "$migrate_line" -lt "$listener_line" ]]
) >"$root_dir/edge.out" 2>"$root_dir/edge.err"
status=$?
set -e
if [[ "$status" -eq 0 ]]; then
  pass "trial and cutover share the edge source and the trial config drops live ports"
else
  fail "trial and cutover share the edge source and the trial config drops live ports"
  cat "$root_dir/edge.err" >&2 || true
fi

status=0
set +e
(
  # shellcheck disable=SC1090
  source "$target"
  if copy_to_ehr_validate_dump_target "${STAGING_DATA_ROOT}/copy-to-ehr-dumps/bad name.dump"; then
    exit 1
  fi
  if copy_to_ehr_validate_dump_target "${STAGING_DATA_ROOT}/copy-to-ehr-dumps/bad;name.dump"; then
    exit 1
  fi
  copy_to_ehr_validate_dump_target "${STAGING_DATA_ROOT}/copy-to-ehr-dumps/pre-migrate.dump"
  log="$root_dir/nft.log"
  : >"$log"
  nft() {
    printf '%s\n' "$*" >>"$log"
    if [[ "$1" == "-a" ]]; then
      printf '%s\n' 'tcp dport 54120 accept comment "copy-ehr-trial" # handle 9'
    fi
    return 0
  }
  docker() { return 0; }
  copy_to_ehr_remove_trial
  grep -q 'delete rule' "$log"
  grep -q 'handle 9' "$log"
) >"$root_dir/nft.out" 2>"$root_dir/nft.err"
status=$?
set -e
if [[ "$status" -eq 0 ]]; then
  pass "teardown deletes the trial nft rule and dump paths stay on the character whitelist"
else
  fail "teardown deletes the trial nft rule and dump paths stay on the character whitelist"
fi

status=0
set +e
(
  # shellcheck disable=SC1090
  source "$target"
  printf 'in-progress\n' >"$COPY_TO_EHR_MARKER_FILE"
  if copy_to_ehr_refuse_cutover_marker; then
    exit 1
  fi
  copy_to_ehr_clear_cutover_marker
  copy_to_ehr_refuse_cutover_marker
  copy_to_ehr_arm_cutover_trap "$root_dir/marker.dump" cosmabot_standalone_e0a414184674
  [[ -f "$COPY_TO_EHR_MARKER_FILE" ]]
  trap - ERR EXIT INT TERM HUP
  rm -f -- "$COPY_TO_EHR_MARKER_FILE"
) >"$root_dir/marker.out" 2>"$root_dir/marker.err"
status=$?
set -e
if [[ "$status" -eq 0 ]] && grep -q 'CUTOVER_IN_PROGRESS' "$root_dir/marker.err"; then
  pass "an in-progress cutover marker blocks the next run"
else
  fail "an in-progress cutover marker blocks the next run"
fi

status=0
set +e
(
  # shellcheck disable=SC1090
  source "$target"
  storage_id="/subscriptions/bab2a709-1fcb-4c87-a9fc-802f7477ec13/resourceGroups/rg-cosmas-os-vm-staging-eus2-lab01/providers/Microsoft.Storage/storageAccounts/stgcbotstaging"
  if copy_to_ehr_validate_dump_target "$storage_id"; then
    exit 1
  fi
  vm="$root_dir/dump-fail-vm"
  dump="$vm/copy-to-ehr-dumps/pre-migrate.dump"
  mkdir -p "$(dirname "$dump")"
  : >"$root_dir/dump-fail.log"
  copy_to_ehr_pg_dump() { printf 'DUMP\n' >>"$root_dir/dump-fail.log"; return 1; }
  copy_to_ehr_stop_live_listeners() { printf 'STOP\n' >>"$root_dir/dump-fail.log"; return 0; }
  if copy_to_ehr_cutover_sequence "$vm" "$dump" cosmabot_standalone_e0a414184674; then
    exit 1
  fi
  if grep -qx 'STOP' "$root_dir/dump-fail.log"; then
    exit 1
  fi
  grep -qx 'DUMP' "$root_dir/dump-fail.log"
) >"$root_dir/upload.out" 2>"$root_dir/upload.err"
status=$?
set -e
if [[ "$status" -eq 0 ]] && grep -E -q 'DUMP_TARGET_REFUSED|CUTOVER_ABORT_RESTORE_CHECK' "$root_dir/upload.err"; then
  pass "a storage id is refused and a dump failure stops before the listeners"
else
  fail "a storage id is refused and a dump failure stops before the listeners"
  cat "$root_dir/upload.err" >&2 || true
fi

status=0
set +e
(
  # shellcheck disable=SC1090
  source "$target"
  src="$root_dir/migrate-tree"
  mkdir -p "$src/infra/standalone/package"
  chmod 700 "$src" "$src/infra" "$src/infra/standalone" "$src/infra/standalone/package"
  cat >"$src/infra/standalone/package/migrate.py" <<PY
import os, sys
ok = "/app/src" in sys.path and os.environ.get("PYTHONPATH") == "/app/src"
open("$root_dir/migrate-marker", "w").write("yes\\n" if ok else "no\\n")
PY
  chmod 600 "$src/infra/standalone/package/migrate.py"
  envf="$root_dir/migrate.env"
  printf 'STANDALONE_INSTANCE_ID=e0a41418-4674-456e-8512-7d5de7a78670\n' >"$envf"
  chmod 600 "$envf"
  chown() { printf '%s\n' "$*" >"$root_dir/chown.txt"; return 0; }
  docker() {
    python3 - "$root_dir/docker-args" "$src" "$envf" -- "$@" <<'PY'
import pathlib, subprocess, sys
out, src, env = sys.argv[1:4]
args = sys.argv[5:]
pathlib.Path(out).write_bytes("\0".join(args).encode())
if "--userns" not in args or args[args.index("--userns") + 1] != "host":
    raise SystemExit(2)
if "21000:21000" not in args:
    raise SystemExit(3)
script = args[args.index("-c") + 1]
script = script.replace("/opt/copy-to-ehr-src", src).replace("/run/copy-to-ehr-migrate.env", env)
raise SystemExit(subprocess.call([sys.executable, "-c", script]))
PY
  }
  COPY_TO_EHR_SHA=e29bf5a2de0eddec1663b1185076472ef172b590
  copy_to_ehr_run_migrate_py "$envf" "$src"
  python3 -c 'import os,sys; mode=os.stat(sys.argv[1]).st_mode; raise SystemExit(0 if mode & 0o004 else 1)' "$src/infra/standalone/package/migrate.py"
  python3 -c 'import os,sys; mode=os.stat(sys.argv[1]).st_mode; raise SystemExit(0 if (mode & 0o005) == 0o005 else 1)' "$src"
  python3 -c 'import os,sys; mode=os.stat(sys.argv[1]).st_mode & 0o777; raise SystemExit(0 if mode == 0o600 else 1)' "$envf"
  grep -q '21000:21000' "$root_dir/chown.txt" || exit 1
  grep -qx 'yes' "$root_dir/migrate-marker" || exit 1
  python3 -c 'import pathlib,sys; raw=pathlib.Path(sys.argv[1]).read_bytes().split(b"\0"); raise SystemExit(0 if b"PYTHONPATH=/app/src" in raw else 1)' "$root_dir/docker-args" || exit 1
) >"$root_dir/migrate-user.out" 2>"$root_dir/migrate-user.err"
status=$?
set -e
if [[ "$status" -eq 0 ]]; then
  pass "migrate tree is readable by uid 21000 and the launcher exits 0"
else
  fail "migrate tree is readable by uid 21000 and the launcher exits 0"
  cat "$root_dir/migrate-user.err" >&2 || true
fi

status=0
set +e
(
  # shellcheck disable=SC1090
  source "$target"
  packed="$root_dir/web-src"
  archive="$root_dir/web-archive.tar.gz"
  dest="$root_dir/web-out"
  mkdir -p "$packed/nested"
  printf '{"commit":"e29bf5a2de0eddec1663b1185076472ef172b590"}\n' >"$packed/version.json"
  printf 'page\n' >"$packed/nested/app.js"
  chmod 700 "$packed" "$packed/nested"
  chmod 600 "$packed/version.json" "$packed/nested/app.js"
  tar -czf "$archive" -C "$packed" .
  copy_to_ehr_extract_web "$archive" "$dest" e29bf5a2de0eddec1663b1185076472ef172b590
  python3 -c 'import os,sys
root=sys.argv[1]
for dirpath, dirnames, filenames in os.walk(root):
    mode=os.stat(dirpath).st_mode
    if (mode & 0o005) != 0o005:
        raise SystemExit(1)
    for name in filenames:
        fmode=os.stat(os.path.join(dirpath, name)).st_mode
        if (fmode & 0o004) != 0o004:
            raise SystemExit(1)
' "$dest"
) >"$root_dir/web-mode.out" 2>"$root_dir/web-mode.err"
status=$?
set -e
if [[ "$status" -eq 0 ]]; then
  pass "extracted release web is world-readable"
else
  fail "extracted release web is world-readable"
  cat "$root_dir/web-mode.err" >&2 || true
fi

status=0
set +e
(
  # shellcheck disable=SC1090
  source "$target"
  log="$root_dir/quiet.log"
  : >"$log"
  phase=serving
  vm="$root_dir/quiet-vm"
  dump="$vm/copy-to-ehr-dumps/pre-migrate.dump"
  mkdir -p "$(dirname "$dump")"
  copy_to_ehr_pg_dump() { printf 'DUMP %s\n' "$phase" >>"$log"; printf 'PGDMP' >"$1"; }
  copy_to_ehr_createdb() { return 0; }
  copy_to_ehr_pg_restore() { return 0; }
  copy_to_ehr_dropdb() { return 0; }
  copy_to_ehr_psql() {
    if [[ "$2" == *datcollate* ]]; then
      printf 'C|C|-1|-\n'
      return 0
    fi
    if [[ "$2" == *pg_db_role_setting* ]]; then
      printf '%s\n' '-'
      return 0
    fi
    if [[ "$2" == *version_num* ]]; then
      printf 'bb57e3d10c964\n'
      return 0
    fi
    if [[ "$phase" == quiet ]]; then
      printf '9\n'
    else
      printf '2\n'
    fi
  }
  copy_to_ehr_stop_live_listeners() { phase=quiet; printf 'STOP\n' >>"$log"; return 0; }
  copy_to_ehr_migrate_live() { printf 'MIGRATE\n' >>"$log"; return 1; }
  copy_to_ehr_fail_rollback() { copy_to_ehr_disarm_cutover_trap; printf 'ROLLBACK\n' >>"$log"; return 1; }
  copy_to_ehr_cutover_sequence "$vm" "$dump" cosmabot_standalone_e0a414184674 || true
  awk '
    $1 == "DUMP" && $2 == "serving" {serving=NR}
    $1 == "STOP" {stop=NR}
    $1 == "DUMP" && $2 == "quiet" {quiet=NR}
    $1 == "MIGRATE" {migrate=NR}
    END {exit !(serving && stop && quiet && migrate && serving < stop && stop < quiet && quiet < migrate)}
  ' "$log"
  grep -qx 'alembic_version 9' "${dump}.counts"
  if grep -qx 'alembic_version 2' "${dump}.counts"; then exit 1; fi
) >"$root_dir/quiet.out" 2>"$root_dir/quiet.err"
status=$?
set -e
if [[ "$status" -eq 0 ]]; then
  pass "the authoritative dump and its counts are taken after listeners stop"
else
  fail "the authoritative dump and its counts are taken after listeners stop"
  cat "$root_dir/quiet.err" >&2 || true
fi

status=0
set +e
(
  # shellcheck disable=SC1090
  source "$target"
  log="$root_dir/clone-fail.log"
  : >"$log"
  STAGING_DATA_ROOT="$root_dir/clone-vm"
  dump="$STAGING_DATA_ROOT/copy-to-ehr-dumps/pre-migrate.dump"
  mkdir -p "$(dirname "$dump")"
  printf 'PGDMP\n' >"$dump"
  printf 'verified\n' >"${dump}.verified"
  printf 'alembic_version 1\naudit_events 1\npractice_owner_reservations 1\n' >"${dump}.counts"
  chmod 600 "$dump" "${dump}.verified" "${dump}.counts"
  COPY_TO_EHR_SHA=e29bf5a2de0eddec1663b1185076472ef172b590
  copy_to_ehr_restore_gate() { printf 'GATE\n' >>"$log"; return 0; }
  copy_to_ehr_stop_live_listeners() { printf 'STOP\n' >>"$log"; return 0; }
  copy_to_ehr_write_migrate_env() { printf 'X=1\n' >"$2"; return 0; }
  git() { return 1; }
  copy_to_ehr_start_prior_listeners() { printf 'START_R10\n' >>"$log"; return 0; }
  copy_to_ehr_write_prior_pointer() { printf 'POINTER\n' >>"$log"; return 0; }
  copy_to_ehr_rollback_verify_prior() { printf 'SERVING\n' >>"$log"; return 0; }
  docker() { printf 'DOCKER %s\n' "$*" >>"$log"; return 0; }
  if copy_to_ehr_cutover_sequence "$STAGING_DATA_ROOT" "$dump" cosmabot_standalone_e0a414184674; then
    exit 1
  fi
  grep -qx 'START_R10' "$log"
  if grep -q 'dropdb' "$log"; then exit 1; fi
) >"$root_dir/clone-fail.out" 2>"$root_dir/clone-fail.err"
status=$?
set -e
if [[ "$status" -eq 0 ]] && grep -q 'RESTORE_SKIPPED_UNTOUCHED' "$root_dir/clone-fail.out"; then
  pass "a clone failure restarts release-r10 without dropping the live database"
else
  fail "a clone failure restarts release-r10 without dropping the live database"
  cat "$root_dir/clone-fail.err" >&2 || true
fi

status=0
set +e
(
  # shellcheck disable=SC1090
  source "$target"
  log="$root_dir/stop-fail.log"
  : >"$log"
  rm -f -- "$COPY_TO_EHR_MARKER_FILE"
  copy_to_ehr_restore_gate() { return 0; }
  copy_to_ehr_stop_live_listeners() { return 1; }
  copy_to_ehr_start_prior_listeners() { printf 'START\n' >>"$log"; return 0; }
  copy_to_ehr_rollback_verify_prior() { printf 'SERVING\n' >>"$log"; return 0; }
  if copy_to_ehr_cutover_sequence "$root_dir/stop-vm" "$root_dir/stop.dump" cosmabot_standalone_e0a414184674; then
    exit 1
  fi
  [[ ! -e "$COPY_TO_EHR_MARKER_FILE" ]]
  grep -qx 'START' "$log"
  grep -qx 'SERVING' "$log"
  copy_to_ehr_rollback_verify_prior() { return 1; }
  if copy_to_ehr_cutover_sequence "$root_dir/stop-vm" "$root_dir/stop.dump" cosmabot_standalone_e0a414184674; then
    exit 1
  fi
  [[ -f "$COPY_TO_EHR_MARKER_FILE" ]]
) >"$root_dir/stop-fail.out" 2>"$root_dir/stop-fail.err"
status=$?
set -e
if [[ "$status" -eq 0 ]] && grep -q 'CUTOVER_ABORT_STOP' "$root_dir/stop-fail.err" && grep -q 'CUTOVER_ROLLBACK_FAILED' "$root_dir/stop-fail.err"; then
  pass "a failed listener stop clears the marker only after release-r10 is serving"
else
  fail "a failed listener stop clears the marker only after release-r10 is serving"
  cat "$root_dir/stop-fail.err" >&2 || true
fi

status=0
set +e
(
  # shellcheck disable=SC1090
  source "$target"
  printf 'in-progress\n' >"$COPY_TO_EHR_MARKER_FILE"
  if copy_to_ehr_api_build_main; then
    exit 1
  fi
  [[ -s "$COPY_TO_EHR_MARKER_FILE" ]]
  trap - EXIT
) >"$root_dir/build-marker.out" 2>"$root_dir/build-marker.err"
status=$?
set -e
if [[ "$status" -eq 0 ]] && grep -q 'CUTOVER_IN_PROGRESS' "$root_dir/build-marker.err"; then
  pass "the image build refuses a cutover marker without removing it"
else
  fail "the image build refuses a cutover marker without removing it"
fi

record_api_dirs() {
  command mktemp "$@" | tee -a "$root_dir/api-dirs"
}

status=0
set +e
(
  # shellcheck disable=SC1090
  set -euo pipefail
  source "$target"
  rm -f -- "$COPY_TO_EHR_MARKER_FILE"
  COPY_TO_EHR_SHA=e29bf5a2de0eddec1663b1185076472ef172b590
  : >"$root_dir/api-dirs"
  df() {
    printf 'Filesystem 1024-blocks Used Available Capacity Mounted on\n'
    printf 'tmpfs 100 1 99999999 1%% /var/tmp\n'
  }
  mktemp() { record_api_dirs "$@"; }
  copy_to_ehr_clone_at_sha() { return 1; }
  copy_to_ehr_api_build_main
) >"$root_dir/api-fail.out" 2>"$root_dir/api-fail.err"
status=$?
set -e
api_dir=$(head -n 1 "$root_dir/api-dirs")
if [[ "$status" -ne 0 && -n "$api_dir" && ! -e "$api_dir" ]] && ! grep -q 'unbound variable' "$root_dir/api-fail.err"; then
  pass "a failed image build removes its work directory"
else
  fail "a failed image build removes its work directory"
  cat "$root_dir/api-fail.err" >&2 || true
fi

status=0
set +e
(
  # shellcheck disable=SC1090
  set -euo pipefail
  source "$target"
  rm -f -- "$COPY_TO_EHR_MARKER_FILE"
  COPY_TO_EHR_SHA=e29bf5a2de0eddec1663b1185076472ef172b590
  : >"$root_dir/api-dirs"
  df() {
    printf 'Filesystem 1024-blocks Used Available Capacity Mounted on\n'
    printf 'tmpfs 100 1 99999999 1%% /var/tmp\n'
  }
  mktemp() { record_api_dirs "$@"; }
  copy_to_ehr_clone_at_sha() { mkdir -p "$1/infra/standalone/package"; return 0; }
  python3() {
    if [[ "$1" == *prepare_api_recipe.py ]]; then
      mkdir -p "$5"
      printf 'FROM scratch\n' >"$5/Dockerfile"
      printf '\n' >"$5/Dockerfile.dockerignore"
      return 0
    fi
    command python3 "$@"
  }
  docker() { return 0; }
  copy_to_ehr_api_build_main
) >"$root_dir/api-ok.out" 2>"$root_dir/api-ok.err"
status=$?
set -e
api_dir=$(head -n 1 "$root_dir/api-dirs")
if [[ "$status" -eq 0 && -n "$api_dir" && ! -e "$api_dir" ]] && grep -q 'API_IMAGE_OK' "$root_dir/api-ok.out"; then
  pass "a successful image build removes its work directory"
else
  fail "a successful image build removes its work directory"
  cat "$root_dir/api-ok.err" >&2 || true
fi

status=0
set +e
(
  # shellcheck disable=SC1090
  source "$target"
  log="$root_dir/teardown.log"
  : >"$log"
  nft() {
    printf '%s\n' "$*" >>"$log"
    if [[ "$1" == "-a" ]]; then
      printf '%s\n' 'tcp dport 54120 accept comment "copy-ehr-trial" # handle 4'
    fi
    return 0
  }
  docker() { printf '%s\n' "$*" >>"$log"; return 0; }
  copy_to_ehr_teardown_main
  grep -q 'delete rule' "$log"
  grep -q 'handle 4' "$log"
  grep -q 'copyehr-trial-pg-' "$log"
  grep -q 'copyehr-trial-api-' "$log"
  grep -q 'copyehr-trial-edge-' "$log"
  copy_to_ehr_restore_gate() { return 0; }
  copy_to_ehr_stop_live_listeners() { return 0; }
  copy_to_ehr_migrate_live() { return 0; }
  copy_to_ehr_psql() { printf 'a46f2c09d853\n'; }
  copy_to_ehr_start_new_listeners() { return 0; }
  copy_to_ehr_ready_for_pointer() { return 0; }
  copy_to_ehr_write_new_pointer() { return 0; }
  copy_to_ehr_post_switch_checks() { return 0; }
  : >"$log"
  copy_to_ehr_cutover_sequence "$root_dir/cut-vm" "$root_dir/cut.dump" cosmabot_standalone_e0a414184674
  grep -q 'delete rule' "$log"
  grep -q 'copyehr-trial-pg-' "$log"
) >"$root_dir/teardown.out" 2>"$root_dir/teardown.err"
status=$?
set -e
if [[ "$status" -eq 0 ]] && grep -qx 'TEARDOWN_OK' "$root_dir/teardown.out" && grep -qx 'CUTOVER_OK' "$root_dir/teardown.out"; then
  pass "teardown and a successful cutover remove the trial containers and nft rule"
else
  fail "teardown and a successful cutover remove the trial containers and nft rule"
  cat "$root_dir/teardown.err" >&2 || true
fi

status=0
set +e
(
  # shellcheck disable=SC1090
  source "$target"
  log="$root_dir/curl.log"
  : >"$log"
  curl() { printf '%s\n' "$*" >>"$log"; return 1; }
  copy_to_ehr_expect_ready 54110 || true
  copy_to_ehr_expect_version 54112 e29bf5a2de0eddec1663b1185076472ef172b590 || true
  feature_dir="$root_dir/feature-web"
  mkdir -p "$feature_dir"
  printf 'Copy to EHR\n' >"$feature_dir/index.html"
  copy_to_ehr_expect_feature "$feature_dir" 54112 || true
  copy_to_ehr_read_served_commit 54112 || true
  COPY_TO_EHR_READY_TRIES=1
  sleep() { return 0; }
  copy_to_ehr_rollback_verify_prior || true
  [[ "$(grep -c -- '--max-time' "$log")" -ge 5 ]]
  prelude=$(copy_to_ehr_remote_prelude e29bf5a2de0eddec1663b1185076472ef172b590 9dfd4cfd "${STAGING_DATA_ROOT}/copy-to-ehr-dumps/pre-migrate.dump")
  tries=$(bash -c "$prelude"$'\n''printf %s "$COPY_TO_EHR_READY_TRIES"')
  [[ "$tries" -ge 90 ]]
  pointer="$root_dir/pointer-dir/active-release"
  COPY_TO_EHR_POINTER_FILE="$pointer"
  copy_to_ehr_write_pointer "${STAGING_DATA_ROOT}/release-r10" POINTER_R10
  copy_to_ehr_write_pointer "${STAGING_DATA_ROOT}/release-copy-ehr-e29bf5a2de0e" POINTER_NEW
  python3 -c 'import os,sys; mode=os.stat(sys.argv[1]).st_mode & 0o777; raise SystemExit(0 if mode == 0o644 else 1)' "$pointer"
  grep -qx "RELEASE_DIR=${STAGING_DATA_ROOT}/release-copy-ehr-e29bf5a2de0e" "$pointer"
  [[ "$(find "$root_dir/pointer-dir" -name 'active-release.*' | wc -l | tr -d '[:space:]')" -eq 0 ]]
  scratch="$root_dir/scratch.dump"
  printf 'PGDMP' >"$scratch"
  : >"$root_dir/scratch-restore.log"
  COPY_TO_EHR_PG_CONTAINER=pg-stub
  docker() { printf '%s\n' "$*" >>"$root_dir/scratch-restore.log"; return 0; }
  copy_to_ehr_pg_restore cosmabot_copy_ehr_scratch "$scratch"
  grep -q -- '--single-transaction' "$root_dir/scratch-restore.log"
  grep -q -- '--exit-on-error' "$root_dir/scratch-restore.log"
  if grep -q -- '--no-owner' "$root_dir/scratch-restore.log"; then exit 1; fi
) >"$root_dir/curl-pointer.out" 2>"$root_dir/curl-pointer.err"
status=$?
set -e
if [[ "$status" -eq 0 ]]; then
  pass "curls are bounded, listeners wait at least 90s, and the pointer write is atomic"
else
  fail "curls are bounded, listeners wait at least 90s, and the pointer write is atomic"
  cat "$root_dir/curl-pointer.err" >&2 || true
fi

sub_stubs="$root_dir/stubs-storage-id"
make_stubs "$sub_stubs" "$staging_account" "$staging_vm"
expect_fail "subscription dump target refused" run_script "$sub_stubs" --workdir "$workdir" \
  --dump-target "/subscriptions/bab2a709-1fcb-4c87-a9fc-802f7477ec13/resourceGroups/rg-cosmas-os-vm-staging-eus2-lab01/providers/Microsoft.Storage/storageAccounts/stgcbotstaging"
if [[ -s "$sub_stubs/az.log" ]]; then
  fail "subscription dump target reached azure"
else
  pass "subscription dump target stopped before azure"
fi

status=0
set +e
(
  # shellcheck disable=SC1090
  source "$target"
  vm="$root_dir/trial-vm"
  STAGING_DATA_ROOT="$vm"
  release="${vm}/release-copy-ehr-e29bf5a2de0e"
  mkdir -p "$vm/release-r5r1/config" "$release"
  printf '{}\n' >"$vm/release-r5r1/config/api-public.json"
  printf '%s\n' '{"DATABASE_URL":"postgresql+psycopg://old:synthetic-old-password-000000@127.0.0.1:9/old"}' >"$vm/release-r5r1/config/api-private.json"
  printf 'archive\n' >"${release}/cosmabot-web-e29bf5a2de0eddec1663b1185076472ef172b590.tar.gz"
  COPY_TO_EHR_SHA=e29bf5a2de0eddec1663b1185076472ef172b590
  log="$root_dir/trial-order.log"
  : >"$log"
  copy_to_ehr_live_still_serving() { return 0; }
  chown() { return 0; }
  copy_to_ehr_extract_web() { return 0; }
  copy_to_ehr_remove_trial() { return 0; }
  copy_to_ehr_wait_postgres() { printf 'WAIT\n' >>"$log"; return 0; }
  copy_to_ehr_edge_conf_source() { printf '%s\n' "$vm/edge.conf"; }
  printf 'server {}\n' >"$vm/edge.conf"
  copy_to_ehr_write_trial_edge() { return 0; }
  copy_to_ehr_clone_at_sha() { return 0; }
  copy_to_ehr_run_migrate_py() { cp "$1" "$root_dir/trial-migrate.env"; printf 'MIGRATE\n' >>"$log"; return 0; }
  copy_to_ehr_docker_api() { return 0; }
  copy_to_ehr_docker_edge() { return 0; }
  copy_to_ehr_wait_listener() { return 0; }
  copy_to_ehr_expect_feature() { return 0; }
  nft() { return 0; }
  docker() {
    printf '%s\n' "$*" >>"$log"
    if [[ "$1" == "ps" ]]; then
      printf '%s\n' 'abc123 127.0.0.1:54111->5432/tcp'
    elif [[ "$1" == "inspect" ]]; then
      printf '%s\n' 'sha256:synthetic'
    fi
    return 0
  }
  copy_to_ehr_side_port_main || exit 1
  awk '
    $1 == "WAIT" {wait=NR}
    $0 ~ /CREATE ROLE cbpg_e0a414184674 / {role=NR}
    $1 == "MIGRATE" {migrate=NR}
    END {exit !(wait && role && migrate && wait < role && role < migrate)}
  ' "$log" || exit 1
  grep -q 'CREATE ROLE cosmabot_runtime_e0a414184674 ' "$log" || exit 1
  grep -q 'GRANT cosmabot_runtime_e0a414184674 TO cbpg_e0a414184674 WITH ADMIN OPTION' "$log" || exit 1
  grep -q 'CREATE DATABASE cosmabot_standalone_copy_ehr_trial OWNER cbpg_e0a414184674' "$log" || exit 1
  python3 - "$root_dir/trial-migrate.env" <<'PY' || exit 1
import sys
from urllib.parse import urlparse
env = {}
for line in open(sys.argv[1], encoding="utf-8"):
    key, value = line.rstrip("\n").split("=", 1)
    env[key] = value
admin = urlparse(env["DATABASE_ADMIN_URL"].replace("postgresql+psycopg://", "postgresql://", 1))
runtime = urlparse(env["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1))
if admin.username == runtime.username or not admin.password or admin.password == runtime.password:
    raise SystemExit(1)
if admin.username != "cbpg_e0a414184674" or runtime.username != "cosmabot_runtime_e0a414184674":
    raise SystemExit(1)
if admin.username == "cosmabot_runtime_e0a414184674":
    raise SystemExit(1)
if (admin.hostname, admin.port, admin.path) != ("127.0.0.1", 54130, "/cosmabot_standalone_copy_ehr_trial"):
    raise SystemExit(1)
if (runtime.hostname, runtime.port, runtime.path) != (admin.hostname, admin.port, admin.path):
    raise SystemExit(1)
if "54111" in env["DATABASE_ADMIN_URL"] or "54111" in env["DATABASE_URL"]:
    raise SystemExit(1)
if "cosmabot_standalone_e0a414184674" in env["DATABASE_ADMIN_URL"] + env["DATABASE_URL"]:
    raise SystemExit(1)
PY
  python3 -c 'import json,sys; data=json.load(open(sys.argv[1])); url=data["DATABASE_URL"]; raise SystemExit(0 if url.startswith("postgresql+psycopg://cosmabot_runtime_e0a414184674:") and ":54130/" in url else 1)' \
    "${release}/config/api-private.json" || exit 1
) >"$root_dir/trial-roles.out" 2>"$root_dir/trial-roles.err"
status=$?
set -e
if [[ "$status" -eq 0 ]]; then
  pass "trial migrate roles differ, target 54130, and are created before migrate"
else
  fail "trial migrate roles differ, target 54130, and are created before migrate"
  cat "$root_dir/trial-roles.err" >&2 || true
fi

status=0
set +e
(
  # shellcheck disable=SC1090
  source "$target"
  vm="$root_dir/untouched-vm"
  STAGING_DATA_ROOT="$vm"
  dump="$vm/copy-to-ehr-dumps/missing.dump"
  mkdir -p "$(dirname "$dump")"
  COPY_TO_EHR_DB_TOUCHED=0
  log="$root_dir/untouched.log"
  : >"$log"
  copy_to_ehr_remove_new_listeners() { return 0; }
  copy_to_ehr_start_prior_listeners() { printf 'START_R10\n' >>"$log"; return 0; }
  copy_to_ehr_write_prior_pointer() { return 0; }
  copy_to_ehr_rollback_verify_prior() { return 0; }
  docker() { printf '%s\n' "$*" >>"$log"; return 0; }
  copy_to_ehr_rollback_to_r10 "$dump" cosmabot_standalone_e0a414184674 || exit 1
  grep -qx 'START_R10' "$log" || exit 1
  if grep -q 'dropdb' "$log"; then exit 1; fi
) >"$root_dir/untouched.out" 2>"$root_dir/untouched.err"
status=$?
set -e
if [[ "$status" -eq 0 ]] && grep -qx 'RESTORE_SKIPPED_UNTOUCHED' "$root_dir/untouched.out"; then
  pass "an untouched database with a missing dump restarts r10"
else
  fail "an untouched database with a missing dump restarts r10"
  cat "$root_dir/untouched.err" >&2 || true
fi

status=0
set +e
(
  # shellcheck disable=SC1090
  source "$target"
  vm="$root_dir/swap-vm"
  STAGING_DATA_ROOT="$vm"
  dump="$vm/copy-to-ehr-dumps/pre-migrate.dump"
  mkdir -p "$(dirname "$dump")"
  printf 'PGDMP' >"$dump"
  printf 'alembic_version 4\naudit_events 4\npractice_owner_reservations 4\n' >"${dump}.counts"
  chmod 600 "$dump" "${dump}.counts"
  COPY_TO_EHR_PG_CONTAINER=pg-stub
  COPY_TO_EHR_DB_TOUCHED=1
  log="$root_dir/swap.log"
  : >"$log"
  docker() {
    printf '%s\n' "$*" >>"$log"
    case "$*" in
      *datcollate*) printf 'C|C|-1|-\n' ;;
      *pg_db_role_setting*) printf '%s\n' '-' ;;
      *pg_get_userbyid*) printf 'postgres\n' ;;
      *pg_encoding_to_char*) printf 'UTF8\n' ;;
      *version_num*)
        if [[ "$*" == *_copy_ehr_in* ]]; then printf 'bb57e3d10c964\n'; else printf 'changed000000\n'; fi
        ;;
      *'count(*)'*)
        if [[ "$*" == *_copy_ehr_in* ]]; then printf '4\n'; else printf '9\n'; fi
        ;;
    esac
    return 0
  }
  copy_to_ehr_restore_dump_over_live "$dump" cosmabot_standalone_e0a414184674 || exit 1
  awk '
    /createdb / {createdb=NR}
    /pg_restore / {restore=NR}
    /version_num/ {verify=NR}
    /pg_terminate_backend/ && !term {term=NR}
    /RENAME TO "cosmabot_standalone_e0a414184674_copy_ehr_old"/ {old=NR}
    /_copy_ehr_in" RENAME TO "cosmabot_standalone_e0a414184674"/ {live=NR}
    END {exit !(createdb && restore && verify && term && old && live && createdb < restore && restore < verify && verify < term && term < old && old < live)}
  ' "$log" || exit 1
  grep -q -- '--lc-collate C' "$log" || exit 1
  grep -q -- '--lc-ctype C' "$log" || exit 1
  grep -q 'CONNECTION LIMIT -1' "$log" || exit 1
) >"$root_dir/swap.out" 2>"$root_dir/swap.err"
status=$?
set -e
if [[ "$status" -eq 0 ]] && grep -qx 'DUMP_RESTORED' "$root_dir/swap.out"; then
  pass "a restore swap creates, verifies, then renames into place"
else
  fail "a restore swap creates, verifies, then renames into place"
  cat "$root_dir/swap.err" >&2 || true
fi

status=0
set +e
(
  # shellcheck disable=SC1090
  source "$target"
  vm="$root_dir/rename-vm"
  STAGING_DATA_ROOT="$vm"
  dump="$vm/copy-to-ehr-dumps/pre-migrate.dump"
  mkdir -p "$(dirname "$dump")"
  printf 'PGDMP' >"$dump"
  printf 'alembic_version 4\naudit_events 4\npractice_owner_reservations 4\n' >"${dump}.counts"
  chmod 600 "$dump" "${dump}.counts"
  COPY_TO_EHR_PG_CONTAINER=pg-stub
  COPY_TO_EHR_DB_TOUCHED=1
  log="$root_dir/rename.log"
  : >"$log"
  docker() {
    printf '%s\n' "$*" >>"$log"
    case "$*" in
      *datcollate*) printf 'C|C|-1|-\n' ;;
      *pg_db_role_setting*) printf '%s\n' '-' ;;
      *pg_get_userbyid*) printf 'postgres\n' ;;
      *pg_encoding_to_char*) printf 'UTF8\n' ;;
      *version_num*)
        if [[ "$*" == *_copy_ehr_in* ]]; then printf 'bb57e3d10c964\n'; else printf 'changed000000\n'; fi
        ;;
      *'count(*)'*)
        if [[ "$*" == *_copy_ehr_in* ]]; then printf '4\n'; else printf '9\n'; fi
        ;;
      *'_copy_ehr_in" RENAME TO "cosmabot_standalone_e0a414184674"'*) return 1 ;;
    esac
    return 0
  }
  if copy_to_ehr_restore_dump_over_live "$dump" cosmabot_standalone_e0a414184674; then
    exit 1
  fi
  grep -q '_copy_ehr_old" RENAME TO "cosmabot_standalone_e0a414184674"' "$log" || exit 1
) >"$root_dir/rename.out" 2>"$root_dir/rename.err"
status=$?
set -e
if [[ "$status" -eq 0 ]] && grep -qx 'PG_RESTORE_FAILED' "$root_dir/rename.err"; then
  pass "a failed second rename renames the old database back"
else
  fail "a failed second rename renames the old database back"
  cat "$root_dir/rename.err" >&2 || true
fi

status=0
set +e
(
  # shellcheck disable=SC1090
  source "$target"
  vm="$root_dir/rename-back-vm"
  STAGING_DATA_ROOT="$vm"
  dump="$vm/copy-to-ehr-dumps/pre-migrate.dump"
  mkdir -p "$(dirname "$dump")"
  printf 'PGDMP' >"$dump"
  printf 'alembic_version 4\naudit_events 4\npractice_owner_reservations 4\n' >"${dump}.counts"
  chmod 600 "$dump" "${dump}.counts"
  COPY_TO_EHR_PG_CONTAINER=pg-stub
  COPY_TO_EHR_DB_TOUCHED=1
  docker() {
    case "$*" in
      *datcollate*) printf 'C|C|-1|-\n' ;;
      *pg_db_role_setting*) printf '%s\n' '-' ;;
      *pg_get_userbyid*) printf 'postgres\n' ;;
      *pg_encoding_to_char*) printf 'UTF8\n' ;;
      *version_num*)
        if [[ "$*" == *_copy_ehr_in* ]]; then printf 'bb57e3d10c964\n'; else printf 'changed000000\n'; fi
        ;;
      *'count(*)'*)
        if [[ "$*" == *_copy_ehr_in* ]]; then printf '4\n'; else printf '9\n'; fi
        ;;
      *'RENAME TO "cosmabot_standalone_e0a414184674";'*) return 1 ;;
    esac
    return 0
  }
  if copy_to_ehr_restore_dump_over_live "$dump" cosmabot_standalone_e0a414184674; then
    exit 1
  fi
) >"$root_dir/rename-back.out" 2>"$root_dir/rename-back.err"
status=$?
set -e
if [[ "$status" -eq 0 ]] && grep -qx 'RENAME_BACK_FAILED' "$root_dir/rename-back.err"; then
  pass "a failed rename back prints its own token"
else
  fail "a failed rename back prints its own token"
  cat "$root_dir/rename-back.err" >&2 || true
fi

status=0
set +e
(
  # shellcheck disable=SC1090
  source "$target"
  vm="$root_dir/drop-old-vm"
  STAGING_DATA_ROOT="$vm"
  dump="$vm/copy-to-ehr-dumps/pre-migrate.dump"
  mkdir -p "$(dirname "$dump")"
  printf 'PGDMP' >"$dump"
  printf 'alembic_version 4\naudit_events 4\npractice_owner_reservations 4\n' >"${dump}.counts"
  chmod 600 "$dump" "${dump}.counts"
  COPY_TO_EHR_PG_CONTAINER=pg-stub
  COPY_TO_EHR_DB_TOUCHED=1
  log="$root_dir/drop-old.log"
  : >"$log"
  copy_to_ehr_remove_new_listeners() { return 0; }
  copy_to_ehr_start_prior_listeners() { printf 'START_R10\n' >>"$log"; return 0; }
  copy_to_ehr_write_prior_pointer() { return 0; }
  copy_to_ehr_rollback_verify_prior() { return 0; }
  drop_old_count=0
  docker() {
    printf '%s\n' "$*" >>"$log"
    case "$*" in
      *datcollate*) printf 'C|C|-1|-\n' ;;
      *pg_db_role_setting*) printf '%s\n' '-' ;;
      *pg_get_userbyid*) printf 'postgres\n' ;;
      *pg_encoding_to_char*) printf 'UTF8\n' ;;
      *version_num*)
        if [[ "$*" == *_copy_ehr_in* ]]; then printf 'bb57e3d10c964\n'; else printf 'changed000000\n'; fi
        ;;
      *'count(*)'*)
        if [[ "$*" == *_copy_ehr_in* ]]; then printf '4\n'; else printf '9\n'; fi
        ;;
    esac
    if [[ "$*" == *dropdb* && "$*" == *_copy_ehr_old ]]; then
      drop_old_count=$((drop_old_count + 1))
      if [[ "$drop_old_count" -ge 2 ]]; then
        return 1
      fi
    fi
    return 0
  }
  copy_to_ehr_rollback_to_r10 "$dump" cosmabot_standalone_e0a414184674 || exit 1
  grep -qx 'START_R10' "$log" || exit 1
) >"$root_dir/drop-old.out" 2>"$root_dir/drop-old.err"
status=$?
set -e
if [[ "$status" -eq 0 ]] && grep -qx 'OLD_DATABASE_DROP_FAILED' "$root_dir/drop-old.err" && grep -qx 'DUMP_RESTORED' "$root_dir/drop-old.out"; then
  pass "a failed drop of the old database still restarts r10"
else
  fail "a failed drop of the old database still restarts r10"
  cat "$root_dir/drop-old.err" >&2 || true
fi

status=0
set +e
(
  # shellcheck disable=SC1090
  source "$target"
  vm="$root_dir/shape-vm"
  dump="$vm/copy-to-ehr-dumps/pre-migrate.dump"
  mkdir -p "$(dirname "$dump")"
  log="$root_dir/shape.log"
  : >"$log"
  copy_to_ehr_pg_dump() { printf 'DUMP\n' >>"$log"; printf 'PGDMP' >"$1"; }
  copy_to_ehr_createdb() { return 0; }
  copy_to_ehr_pg_restore() { return 0; }
  copy_to_ehr_dropdb() { return 0; }
  copy_to_ehr_psql() {
    if [[ "$2" == *version_num* ]]; then
      printf 'bb57e3d10c964\n'
    elif [[ "$2" == *datcollate* ]]; then
      printf 'C|C|-1|{not-an-acl}\n'
    elif [[ "$2" == *pg_db_role_setting* ]]; then
      printf '%s\n' '-'
    else
      printf '1\n'
    fi
  }
  copy_to_ehr_stop_live_listeners() { printf 'STOP\n' >>"$log"; return 0; }
  if copy_to_ehr_restore_gate "$vm" "$dump" cosmabot_standalone_e0a414184674; then
    exit 1
  fi
  if grep -qx 'STOP' "$log"; then exit 1; fi
) >"$root_dir/shape.out" 2>"$root_dir/shape.err"
status=$?
set -e
if [[ "$status" -eq 0 ]] && grep -qx 'DATABASE_SHAPE_REFUSED' "$root_dir/shape.err"; then
  pass "a database shape the script cannot copy refuses before listeners stop"
else
  fail "a database shape the script cannot copy refuses before listeners stop"
  cat "$root_dir/shape.err" >&2 || true
fi

status=0
set +e
(
  # shellcheck disable=SC1090
  source "$target"
  old=$(umask)
  umask 077
  pointer="$root_dir/umask-pointer/active-release"
  COPY_TO_EHR_POINTER_FILE="$pointer"
  copy_to_ehr_write_pointer "${STAGING_DATA_ROOT}/release-r10" POINTER_R10 || exit 1
  [[ "$(umask)" == "0077" ]] || exit 1
  mv() { return 1; }
  if copy_to_ehr_write_pointer "${STAGING_DATA_ROOT}/release-r10" POINTER_R10; then
    exit 1
  fi
  [[ "$(umask)" == "0077" ]] || exit 1
  umask "$old"
) >"$root_dir/umask.out" 2>"$root_dir/umask.err"
status=$?
set -e
if [[ "$status" -eq 0 ]]; then
  pass "the pointer write restores umask and checks mv"
else
  fail "the pointer write restores umask and checks mv"
  cat "$root_dir/umask.err" >&2 || true
fi

status=0
set +e
(
  # shellcheck disable=SC1090
  source "$target"
  work="$root_dir/web-build"
  mkdir -p "$work"
  env_file="$root_dir/web-build.env"
  cat >"$env_file" <<'EOF'
VITE_PUBLIC_1=one
VITE_PUBLIC_2=two
VITE_PUBLIC_3=three
VITE_PUBLIC_4=four
VITE_PUBLIC_5=five
VITE_PUBLIC_6=six
VITE_PUBLIC_7=seven
VITE_PUBLIC_8=eight
VITE_PUBLIC_9=nine
VITE_PUBLIC_10=ten
VITE_WORKSPACE_FEATURE_PROFILE=independent-beta-v1
EOF
  chmod 600 "$env_file"
  df() { printf 'Filesystem 1024-blocks Used Available Capacity Mounted on\n'; printf 'tmp 99999999 1 99999999 1%% %s\n' "$2"; }
  copy_to_ehr_clone_at_sha() {
    mkdir -p "$1/web" "$1/scripts"
    printf '%s\n' '#!/bin/sh' 'exit 1' >"$1/scripts/install-client-deps.sh"
    chmod 700 "$1/scripts/install-client-deps.sh"
    return 0
  }
  copy_to_ehr_execute e29bf5a2de0eddec1663b1185076472ef172b590 "$work" "$env_file" \
    "${STAGING_DATA_ROOT}/copy-to-ehr-dumps/pre-migrate.dump" 0 9dfd4cfd
) >"$root_dir/web-build.out" 2>"$root_dir/web-build.err"
status=$?
set -e
if [[ "$status" -ne 0 ]] && grep -q 'web build failed' "$root_dir/web-build.err"; then
  pass "a failed web build is caught without relying on set -e"
else
  fail "a failed web build is caught without relying on set -e"
  cat "$root_dir/web-build.err" >&2 || true
fi

if [[ "$failures" -eq 0 ]]; then
  printf 'copy-to-ehr staging deploy tests passed\n'
  exit 0
fi
printf 'copy-to-ehr staging deploy tests failed: %s\n' "$failures" >&2
exit 1
