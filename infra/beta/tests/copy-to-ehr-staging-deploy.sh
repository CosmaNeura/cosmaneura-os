#!/usr/bin/env bash
# Shell checks for the Copy to EHR staging deploy script. No Azure, no Docker.
set -uo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
target="$(cd -- "$script_dir/.." && pwd -P)/copy-to-ehr-staging-deploy.sh"
root_dir="$(mktemp -d "${TMPDIR:-/tmp}/copy-to-ehr-tests.XXXXXX")"
chmod 700 "$root_dir"
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
  "$@" >/tmp/copy-to-ehr-test-out 2>/tmp/copy-to-ehr-test-err
  status=$?
  set -e
  if [[ "$status" -eq 0 ]]; then
    fail "$name (expected nonzero)"
    return
  fi
  pass "$name"
}

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
    && grep -q '54130' "$dry_out"; then
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
  copy_to_ehr_validate_dump_target "$storage_ok"
  if copy_to_ehr_validate_dump_target "/Users/john/live.dump"; then exit 1; fi
  if copy_to_ehr_validate_dump_target "/home/john/live.dump"; then exit 1; fi
  if copy_to_ehr_validate_dump_target "/tmp/live.dump"; then exit 1; fi
  if copy_to_ehr_validate_dump_target "$storage_other"; then exit 1; fi
  if copy_to_ehr_validate_dump_target "$storage_prod"; then exit 1; fi
  if copy_to_ehr_trial_url_file_allowed /dev/null; then exit 1; fi
)
if [[ $? -eq 0 ]]; then
  pass "dump target outside the resource group or on this Mac is refused"
else
  fail "dump target outside the resource group or on this Mac is refused"
fi

trial_url="$root_dir/trial.url"
printf '%s\n' 'postgresql+psycopg://cosmabot_copyehr_trial:synthetic-trial-password@127.0.0.1:54130/cosmabot_copy_ehr_trial' >"$trial_url"
live_url="$root_dir/live.url"
printf '%s\n' 'postgresql+psycopg://cosmabot_runtime_e0a414184674:synthetic@127.0.0.1:54111/cosmabot_standalone_e0a414184674' >"$live_url"
(
  # shellcheck disable=SC1090
  source "$target"
  copy_to_ehr_trial_url_file_allowed "$trial_url"
  if copy_to_ehr_trial_url_file_allowed "$live_url"; then exit 1; fi
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
  printf '%s\n' "$side" | grep -q 'SIDE_PORT_REFUSED_LIVE_DATABASE'
  printf '%s\n' "$side" | grep -q 'cosmabot_copy_ehr_trial'
  printf '%s\n' "$side" | grep -q '54130'
  printf '%s\n' "$side" | grep -q 'COPY_TO_EHR_ENABLED'
  if printf '%s\n' "$side" | grep -q 'copy_to_ehr_migrate_live'; then exit 1; fi
  if printf '%s\n' "$side" | grep -q 'copy_to_ehr_stop_live_listeners'; then exit 1; fi
  if printf '%s\n' "$side" | grep -E 'docker (stop|rm).*-r10-'; then exit 1; fi
  if printf '%s\n' "$side" | grep -E 'blob download|scp '; then exit 1; fi
  printf '%s\n' "$side" >"$root_dir/side.sh"
  awk 'seen && $0 == "COPY_TO_EHR_BASH_BODY" {exit} seen {print} $0 == "exec /bin/bash <<'\''COPY_TO_EHR_BASH_BODY'\''" {seen=1}' "$root_dir/side.sh" >"$root_dir/side-inner.sh"
  bash -n "$root_dir/side-inner.sh"
  body=$(declare -f copy_to_ehr_cutover_sequence)
  restore=$(printf '%s\n' "$body" | awk '/copy_to_ehr_restore_gate/{print NR; exit}')
  stop=$(printf '%s\n' "$body" | awk '/copy_to_ehr_stop_live_listeners/{print NR; exit}')
  migrate=$(printf '%s\n' "$body" | awk '/copy_to_ehr_migrate_live/{print NR; exit}')
  [[ -n "$restore" && -n "$stop" && -n "$migrate" ]]
  [[ "$restore" -lt "$stop" && "$stop" -lt "$migrate" ]]
  cutover=$(copy_to_ehr_render_cutover "e29bf5a2de0eddec1663b1185076472ef172b590" "9dfd4cfd" "${STAGING_DATA_ROOT}/copy-to-ehr-dumps/pre-migrate.dump")
  printf '%s\n' "$cutover" | grep -q 'release-r10'
  printf '%s\n' "$cutover" | grep -q 'pg_dump -Fc'
  printf '%s\n' "$cutover" | grep -q 'copy_to_ehr_confirm_prior_identity'
  printf '%s\n' "$cutover" | grep -q 'copy_to_ehr_cutover_trap_rollback'
  printf '%s\n' "$cutover" | grep -q 'copy_to_ehr_assert_target_schema'
  if printf '%s\n' "$cutover" | grep -E 'blob download|scp '; then exit 1; fi
  printf '%s\n' "$cutover" >"$root_dir/cutover.sh"
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
  i=1
  while [[ "$i" -le 11 ]]; do
    printf 'VITE_PUBLIC_%s=SUPERSECRETVALUE\n' "$i"
    i=$((i + 1))
  done
} >"$env_file"
chmod 600 "$env_file"
(
  # shellcheck disable=SC1090
  source "$target"
  keys=$(copy_to_ehr_read_web_env_keys "$env_file")
  printf '%s\n' "$keys" | grep -q 'VITE_PUBLIC_11'
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
  version_line=$(printf '%s\n' "$main_body" | awk '/copy_to_ehr_confirm_prior_identity/{print NR; exit}')
  sequence_line=$(printf '%s\n' "$main_body" | awk '/copy_to_ehr_cutover_sequence/{print NR; exit}')
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
  payload=$(python3 -c 'import json,sys; sys.stdout.write(json.dumps({"value":[{"message":"RESTORE_CHECK_OK\nLOOKING\nCOUNT alembic_version=4\nOKAY\nthis line is OK\n"}]}))')
  filtered=$(printf '%s' "$payload" | copy_to_ehr_filter_run_output)
  printf '%s\n' "$filtered" | grep -qx 'RESTORE_CHECK_OK'
  printf '%s\n' "$filtered" | grep -qx 'COUNT alembic_version=4'
  printf '%s\n' "$filtered" | grep -qx 'this line is OK'
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
  install_line=$(printf '%s\n' "$body" | awk '/install-client-deps\.sh/{print NR; exit}')
  build_line=$(printf '%s\n' "$body" | awk '/corepack pnpm run build/{print NR; exit}')
  web_line=$(printf '%s\n' "$body" | awk '/cd "\$workdir\/src\/web"/{print NR; exit}')
  [[ -n "$install_line" && -n "$build_line" && -n "$web_line" ]]
  [[ "$install_line" -lt "$build_line" && "$web_line" -lt "$build_line" ]]
  printf '%s\n' "$body" | grep -q '\$workdir/src/scripts/install-client-deps.sh'
  if printf '%s\n' "$body" | grep -q 'pnpm install'; then exit 1; fi
)
status=$?
set -e
if [[ "$status" -eq 0 ]]; then
  pass "execute installs client deps before the web build"
else
  fail "execute installs client deps before the web build"
fi

if [[ "$failures" -eq 0 ]]; then
  printf 'copy-to-ehr staging deploy tests passed\n'
  exit 0
fi
printf 'copy-to-ehr staging deploy tests failed: %s\n' "$failures" >&2
exit 1
