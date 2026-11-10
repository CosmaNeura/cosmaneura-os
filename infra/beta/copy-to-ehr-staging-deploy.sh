#!/usr/bin/env bash
# Copy to EHR staging deploy for John's Mac.
#
# Dry-run unless --execute. Refuses every target except the staging allowlist.
# Transport is `az vm run-command invoke` (RunShellScript). This is the Oct 31
# pointer-switch path. It does not use the section 9 compose/ACR/render.py path.
#
# The pre-cutover pg_dump stays on the staging VM, inside
# rg-cosmas-os-vm-staging-eus2-lab01. This script never downloads it and never
# copies it to the operator Mac.
set -euo pipefail

# DEFAULT_SOURCE_SHA is the only default candidate. When PR 341 moves, change
# this one line or pass --sha. Do not add a second default.
DEFAULT_SOURCE_SHA=e29bf5a2de0eddec1663b1185076472ef172b590

STAGING_SUBSCRIPTION_ID=bab2a709-1fcb-4c87-a9fc-802f7477ec13
STAGING_SUBSCRIPTION_NAME="Microsoft Azure Sponsorship"
STAGING_ACCOUNT_USER=john@cosmaneura.com
STAGING_RESOURCE_GROUP=rg-cosmas-os-vm-staging-eus2-lab01
STAGING_VM_NAME=vm-cosmabot-staging-eus2-lab01
STAGING_PUBLIC_IP=20.22.205.132
STAGING_WEB_HOST=staging.cosmas.ai
STAGING_API_HOST=api.staging.cosmas.ai
STAGING_DATA_ROOT=/var/lib/cosmabot/standalone/e0a41418-4674-456e-8512-7d5de7a78670
STAGING_INSTANCE_ID=e0a41418-4674-456e-8512-7d5de7a78670
STAGING_SHORT=e0a414184674
STAGING_PRIOR_RELEASE=release-r10
STAGING_EDGE_IMAGE=sha256:4ab0dc24a8dc9df23e90f54756b65ebce5c4a0680201189af233927739410ff5
STAGING_API_REPOSITORY=cosmabot-nov1-api
STAGING_LIVE_SCHEMA=bb57e3d10c964
STAGING_TARGET_SCHEMA=a46f2c09d853
LIVE_API_PORT=54110
LIVE_EDGE_PORT=54112
LIVE_POSTGRES_PORT=54111
TRIAL_API_PORT=54120
TRIAL_EDGE_PORT=54122
TRIAL_POSTGRES_PORT=54130
MIN_FREE_KIB=4194304
PUBLIC_GIT_URL=https://github.com/CosmaNeura/cosmaneura-os.git
WEB_ENV_KEY_COUNT=11
CHUNK_BYTES=24000

copy_to_ehr_die() {
  printf 'copy-to-ehr staging deploy refused: %s\n' "$1" >&2
  exit 1
}

copy_to_ehr_usage() {
  cat <<EOF
Usage: $0 [--execute] [--cutover --expect-prior-sha SHA] [--sha SHA]
          [--workdir PATH] [--web-env PATH] [--dump-target PATH|STORAGE_ID]

Dry-run is the default. --execute builds the trial on side ports and stops
before cutover. --cutover also requires --expect-prior-sha.
EOF
}

copy_to_ehr_explicitly_production() {
  local value
  value=$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')
  case "$value" in
    *app.cosmaneura.com*|*cosmaneura-prod-app*|*northcentralus*|*prod*) return 0 ;;
  esac
  return 1
}

copy_to_ehr_expand_path() {
  local path="$1"
  case "$path" in
    "~") path="${HOME:-}" ;;
    "~/"*) path="${HOME:-}/${path#"~/"}" ;;
  esac
  case "$path" in
    /*) printf '%s\n' "$path" ;;
    *) printf '%s\n' "${PWD}/$path" ;;
  esac
}

copy_to_ehr_path_is_desktop_checkout() {
  local path="$1" home="${HOME:-}"
  [[ -n "$path" && -n "$home" ]] || return 1
  case "$path" in
    "$home/Desktop/cosmaneura-os"|"$home/Desktop/cosmaneura-os"/*) return 0 ;;
  esac
  return 1
}

copy_to_ehr_require_sha() {
  local value="$1" label="$2" length
  length=${#value}
  [[ "$value" =~ ^[0-9a-f]+$ ]] || return 1
  if [[ "$label" == "source" ]]; then
    [[ "$length" -eq 40 ]] || return 1
  else
    [[ "$length" -ge 8 && "$length" -le 40 ]] || return 1
  fi
  copy_to_ehr_explicitly_production "$value" && return 1
  return 0
}

copy_to_ehr_validate_storage_id() {
  local id="$1" prefix name
  prefix="/subscriptions/${STAGING_SUBSCRIPTION_ID}/resourceGroups/${STAGING_RESOURCE_GROUP}/providers/Microsoft.Storage/storageAccounts/"
  case "$id" in
    "$prefix"[a-z0-9]*) ;;
    *) printf 'DUMP_TARGET_REFUSED\n' >&2; return 1 ;;
  esac
  name="${id#"$prefix"}"
  case "$name" in
    ""|*/*|*[!a-z0-9]*) printf 'DUMP_TARGET_REFUSED\n' >&2; return 1 ;;
  esac
  if copy_to_ehr_explicitly_production "$name"; then
    printf 'DUMP_TARGET_REFUSED\n' >&2
    return 1
  fi
  return 0
}

copy_to_ehr_validate_dump_target() {
  local target="$1"
  [[ -n "$target" ]] || { printf 'DUMP_TARGET_REFUSED\n' >&2; return 1; }
  if copy_to_ehr_explicitly_production "$target"; then
    printf 'DUMP_TARGET_REFUSED\n' >&2
    return 1
  fi
  if copy_to_ehr_path_is_desktop_checkout "$target"; then
    printf 'DUMP_TARGET_REFUSED\n' >&2
    return 1
  fi
  case "$target" in
    /subscriptions/*)
      copy_to_ehr_validate_storage_id "$target"
      return $?
      ;;
  esac
  case "$target" in
    "~"*|"./"*|".."*|/Users/*|/home/*|/tmp/*|/var/tmp/*|/private/tmp/*|/private/var/folders/*)
      printf 'DUMP_TARGET_REFUSED\n' >&2
      return 1
      ;;
  esac
  if [[ -n "${HOME:-}" ]]; then
    case "$target" in
      "$HOME"|"$HOME"/*) printf 'DUMP_TARGET_REFUSED\n' >&2; return 1 ;;
    esac
  fi
  case "$target" in
    "$STAGING_DATA_ROOT"/*) ;;
    *) printf 'DUMP_TARGET_REFUSED\n' >&2; return 1 ;;
  esac
  case "$target" in
    *..*) printf 'DUMP_TARGET_REFUSED\n' >&2; return 1 ;;
  esac
  return 0
}

copy_to_ehr_dump_file_on_staging_vm() {
  local dump="$1" root="$2"
  [[ -n "$dump" && -n "$root" ]] || return 1
  case "$dump" in
    "$root"/*) ;;
    *) return 1 ;;
  esac
  case "$dump" in
    *..*|*prod*|*PROD*) return 1 ;;
  esac
  return 0
}

copy_to_ehr_release_dir() {
  local sha="$1" root="$2"
  printf '%s/release-copy-ehr-%s\n' "$root" "$(printf '%s' "$sha" | cut -c1-12)"
}

copy_to_ehr_prior_matches() {
  local expected="$1" observed="$2" tag="$2"
  case "$observed" in
    *:*) tag="${observed##*:}" ;;
  esac
  [[ "$tag" == "$expected" ]] && return 0
  [[ ${#expected} -ge 8 && "$tag" == "$expected"* ]] && return 0
  return 1
}

copy_to_ehr_trial_url_file_allowed() {
  local file="$1" url
  [[ -f "$file" && ! -L "$file" ]] || return 1
  url=$(tr -d '[:space:]' <"$file")
  case "$url" in
    *54111*|*5432*|*54329*|*cosmabot_standalone_*|*cosmabot_copy_ehr_scratch*) return 1 ;;
  esac
  case "$url" in
    postgresql+psycopg://cosmabot_copyehr_trial:*@127.0.0.1:54130/cosmabot_copy_ehr_trial) return 0 ;;
  esac
  return 1
}

copy_to_ehr_assert_account_json() {
  python3 -c '
import json, sys
allowed_id, allowed_name, allowed_user = sys.argv[1:]
try:
    data = json.load(sys.stdin)
except Exception:
    sys.stderr.write("subscription json refused\n")
    sys.exit(1)
ident = str(data.get("id") or "")
name = str(data.get("name") or "")
user = data.get("user") if isinstance(data.get("user"), dict) else {}
user_name = str(user.get("name") or "")
haystack = (ident + " " + name).lower()
if "prod" in haystack or "northcentralus" in haystack:
    sys.stderr.write("subscription looks like production\n")
    sys.exit(1)
if ident != allowed_id or name != allowed_name:
    sys.stderr.write("subscription is not the staging allowlist\n")
    sys.exit(1)
if user_name != allowed_user:
    sys.stderr.write("az account user is not the staging operator\n")
    sys.exit(1)
sys.stdout.write("account_ok\n")
' "$STAGING_SUBSCRIPTION_ID" "$STAGING_SUBSCRIPTION_NAME" "$STAGING_ACCOUNT_USER"
}

copy_to_ehr_assert_vm_json() {
  python3 -c '
import json, sys
allowed_name, allowed_group, allowed_ip = sys.argv[1:]
try:
    data = json.load(sys.stdin)
except Exception:
    sys.stderr.write("vm json refused\n")
    sys.exit(1)
name = str(data.get("name") or "")
group = str(data.get("resourceGroup") or "")
ip = str(data.get("publicIps") or "")
haystack = (name + " " + group + " " + ip).lower()
if "prod" in haystack or "app.cosmaneura.com" in haystack or "cosmaneura-prod-app" in haystack or "northcentralus" in haystack:
    sys.stderr.write("resource group or host looks like production\n")
    sys.exit(1)
if name != allowed_name or group != allowed_group or ip != allowed_ip:
    sys.stderr.write("vm is not the staging allowlist\n")
    sys.exit(1)
sys.stdout.write("vm_ok\n")
' "$STAGING_VM_NAME" "$STAGING_RESOURCE_GROUP" "$STAGING_PUBLIC_IP"
}

copy_to_ehr_read_web_env_keys() {
  local file="$1"
  python3 - "$file" "$WEB_ENV_KEY_COUNT" <<'PY'
import os, stat, sys
path, expected = sys.argv[1], int(sys.argv[2])
info = os.lstat(path)
if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
    sys.stderr.write("WEB_ENV_REFUSED\n")
    sys.exit(1)
if stat.S_IMODE(info.st_mode) & 0o077:
    sys.stderr.write("WEB_ENV_REFUSED\n")
    sys.exit(1)
keys = []
with open(path, "r", encoding="utf-8") as handle:
    for raw in handle:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            sys.stderr.write("WEB_ENV_REFUSED\n")
            sys.exit(1)
        key, value = line.split("=", 1)
        if not key.startswith("VITE_") or value == "":
            sys.stderr.write("WEB_ENV_REFUSED\n")
            sys.exit(1)
        keys.append(key)
if len(keys) != expected:
    sys.stderr.write("WEB_ENV_KEY_COUNT=%s\n" % len(keys))
    sys.exit(1)
sys.stdout.write("\n".join(keys) + "\n")
PY
}

copy_to_ehr_pg_dump() {
  local dump_file="$1" database="$2" err="${1}.err"
  if ! docker exec -u postgres "$COPY_TO_EHR_PG_CONTAINER" \
    pg_dump -Fc --no-password --dbname "$database" >"$dump_file" 2>"$err"; then
    printf 'PG_DUMP_FAILED\n' >&2
    return 1
  fi
  rm -f -- "$err"
}

copy_to_ehr_pg_restore() {
  local database="$1" dump="$2"
  [[ "$database" == "cosmabot_copy_ehr_scratch" ]] || return 1
  docker exec -i -u postgres "$COPY_TO_EHR_PG_CONTAINER" \
    pg_restore --no-password --dbname "$database" <"$dump" >/dev/null
}

copy_to_ehr_psql() {
  local database="$1" sql="$2"
  docker exec -u postgres "$COPY_TO_EHR_PG_CONTAINER" \
    psql -d "$database" -v ON_ERROR_STOP=1 -Atqc "$sql" | tr -d '[:space:]'
}

copy_to_ehr_createdb() {
  [[ "$1" == "cosmabot_copy_ehr_scratch" ]] || return 1
  docker exec -u postgres "$COPY_TO_EHR_PG_CONTAINER" createdb --no-password "$1" >/dev/null
}

copy_to_ehr_dropdb() {
  [[ "$1" == "cosmabot_copy_ehr_scratch" ]] || return 1
  docker exec -u postgres "$COPY_TO_EHR_PG_CONTAINER" dropdb --if-exists --no-password "$1" >/dev/null
}

copy_to_ehr_restore_gate() {
  local root="$1" dump="$2" live_db="$3"
  local scratch="cosmabot_copy_ehr_scratch"
  local live_version="" scratch_version="" table="" sql="" live_count="" scratch_count="" bytes=""
  copy_to_ehr_dump_file_on_staging_vm "$dump" "$root" || {
    printf 'DUMP_PATH_REFUSED\n' >&2
    return 1
  }
  case "$live_db" in
    cosmabot_standalone_[a-z0-9_]*) ;;
    *) printf 'LIVE_DATABASE_NAME_REFUSED\n' >&2; return 1 ;;
  esac
  if [[ "$live_db" == "$scratch" || "$live_db" == "cosmabot_copy_ehr_trial" ]]; then
    printf 'LIVE_DATABASE_NAME_REFUSED\n' >&2
    return 1
  fi
  mkdir -p -- "$(dirname -- "$dump")"
  chmod 700 "$(dirname -- "$dump")" || true
  rm -f -- "$dump" "${dump}.verified"
  copy_to_ehr_pg_dump "$dump" "$live_db" || return 1
  if [[ ! -s "$dump" ]]; then
    printf 'CUTOVER_REFUSED_NO_DUMP\n' >&2
    return 1
  fi
  chmod 600 "$dump" || true
  bytes=$(wc -c <"$dump" | tr -d '[:space:]')
  printf 'DUMP_BYTES=%s\n' "$bytes"
  if ! copy_to_ehr_createdb "$scratch"; then
    printf 'CUTOVER_ABORT_RESTORE_CHECK\n' >&2
    return 1
  fi
  if ! copy_to_ehr_pg_restore "$scratch" "$dump"; then
    copy_to_ehr_dropdb "$scratch" || true
    printf 'CUTOVER_ABORT_RESTORE_CHECK\n' >&2
    return 1
  fi
  live_version=$(copy_to_ehr_psql "$live_db" "SELECT version_num FROM public.alembic_version")
  scratch_version=$(copy_to_ehr_psql "$scratch" "SELECT version_num FROM public.alembic_version")
  if [[ "$live_version" != "$scratch_version" || "$live_version" != "$STAGING_LIVE_SCHEMA" ]]; then
    copy_to_ehr_dropdb "$scratch" || true
    printf 'CUTOVER_ABORT_RESTORE_CHECK\n' >&2
    return 1
  fi
  for table in alembic_version audit_events practice_owner_reservations; do
    case "$table" in
      alembic_version) sql="SELECT count(*) FROM public.alembic_version" ;;
      audit_events) sql="SELECT count(*) FROM public.audit_events" ;;
      practice_owner_reservations) sql="SELECT count(*) FROM public.practice_owner_reservations" ;;
      *) printf 'CUTOVER_ABORT_RESTORE_CHECK\n' >&2; return 1 ;;
    esac
    live_count=$(copy_to_ehr_psql "$live_db" "$sql")
    scratch_count=$(copy_to_ehr_psql "$scratch" "$sql")
    if [[ "$live_count" != "$scratch_count" || ! "$live_count" =~ ^[0-9]+$ ]]; then
      copy_to_ehr_dropdb "$scratch" || true
      printf 'CUTOVER_ABORT_RESTORE_CHECK\n' >&2
      return 1
    fi
    printf 'COUNT %s=%s\n' "$table" "$live_count"
  done
  if ! copy_to_ehr_dropdb "$scratch"; then
    printf 'CUTOVER_ABORT_RESTORE_CHECK\n' >&2
    return 1
  fi
  umask 077
  printf 'verified\n' >"${dump}.verified"
  chmod 600 "${dump}.verified" || true
  printf 'RESTORE_CHECK_OK\n'
}

copy_to_ehr_run_live_migrate() {
  local env_file clone status=0
  umask 077
  env_file=$(mktemp /tmp/copy-to-ehr-migrate-env.XXXXXX)
  chmod 600 "$env_file"
  python3 - "$STAGING_DATA_ROOT/release-r5r1/config/api-private.json" "$env_file" "$STAGING_INSTANCE_ID" <<'PY'
import json, sys
from urllib.parse import urlparse
private_path, env_path, instance = sys.argv[1:]
try:
    raw = json.loads(open(private_path, "r", encoding="utf-8").read())["DATABASE_URL"]
    normalized = raw.replace("postgresql+psycopg://", "postgresql://", 1)
    parsed = urlparse(normalized)
    database = parsed.path.lstrip("/").split("?", 1)[0]
    if parsed.port != 54111 or not database.startswith("cosmabot_standalone_"):
        raise RuntimeError("refused")
    short = instance.replace("-", "")[:12]
    admin = "postgresql+psycopg://cbpg_%s@/%s?host=/var/run/postgresql&port=54111" % (short, database)
    with open(env_path, "w", encoding="utf-8") as handle:
        handle.write("STANDALONE_INSTANCE_ID=%s\n" % instance)
        handle.write("DATABASE_ADMIN_URL=%s\n" % admin)
        handle.write("DATABASE_URL=%s\n" % raw)
except Exception:
    sys.stderr.write("LIVE_DATABASE_REFUSED\n")
    sys.exit(1)
PY
  clone=$(mktemp -d /var/tmp/copy-to-ehr-migrate-src.XXXXXX)
  chmod 700 "$clone"
  git clone --quiet "$PUBLIC_GIT_URL" "$clone/src"
  git -C "$clone/src" checkout --detach --quiet "$COPY_TO_EHR_SHA"
  if ! docker run --rm --network host \
    --entrypoint /usr/local/bin/python \
    -v "$clone/src:/opt/copy-to-ehr-src:ro" \
    -v "$env_file:/run/copy-to-ehr-migrate.env:ro" \
    -v /var/run/postgresql:/var/run/postgresql \
    "${STAGING_API_REPOSITORY}:${COPY_TO_EHR_SHA}" \
    -c 'import os, runpy, sys
from pathlib import Path
for line in Path("/run/copy-to-ehr-migrate.env").read_text().splitlines():
    if "=" not in line:
        continue
    key, value = line.split("=", 1)
    os.environ[key] = value
os.environ["PYTHONPATH"] = "/app/src"
sys.exit(runpy.run_path("/opt/copy-to-ehr-src/infra/standalone/package/migrate.py", run_name="__main__"))'
  then
    status=1
  fi
  rm -f -- "$env_file"
  rm -rf -- "$clone"
  return "$status"
}

copy_to_ehr_migrate_live() {
  local dump="$1"
  if [[ ! -s "$dump" || ! -s "${dump}.verified" ]]; then
    printf 'CUTOVER_REFUSED_UNVERIFIED_DUMP\n' >&2
    return 1
  fi
  if ! grep -qx 'verified' "${dump}.verified"; then
    printf 'CUTOVER_REFUSED_UNVERIFIED_DUMP\n' >&2
    return 1
  fi
  copy_to_ehr_run_live_migrate
}

copy_to_ehr_stop_live_listeners() {
  docker stop \
    "cosmabot-standalone-r10-api-${STAGING_SHORT}" \
    "cosmabot-standalone-r10-edge-${STAGING_SHORT}" >/dev/null
}

copy_to_ehr_start_prior_listeners() {
  docker start \
    "cosmabot-standalone-r10-api-${STAGING_SHORT}" \
    "cosmabot-standalone-r10-edge-${STAGING_SHORT}" >/dev/null
}

copy_to_ehr_write_prior_pointer() {
  local tmp
  umask 022
  tmp=$(mktemp /tmp/copy-to-ehr-pointer.XXXXXX)
  printf 'RELEASE_DIR=%s\n' "${STAGING_DATA_ROOT}/${STAGING_PRIOR_RELEASE}" >"$tmp"
  cat "$tmp" >/etc/cosmabot/active-release
  rm -f -- "$tmp"
  printf 'POINTER_R10\n'
}

copy_to_ehr_write_new_pointer() {
  local tmp
  umask 022
  tmp=$(mktemp /tmp/copy-to-ehr-pointer.XXXXXX)
  printf 'RELEASE_DIR=%s\n' "$COPY_TO_EHR_RELEASE" >"$tmp"
  cat "$tmp" >/etc/cosmabot/active-release
  rm -f -- "$tmp"
  printf 'POINTER_NEW\n'
}

copy_to_ehr_restore_dump_over_live() {
  local dump="$1" live_db="$2"
  copy_to_ehr_dump_file_on_staging_vm "$dump" "$STAGING_DATA_ROOT" || return 1
  [[ -s "$dump" ]] || return 1
  docker exec -i -u postgres "$COPY_TO_EHR_PG_CONTAINER" \
    pg_restore --clean --if-exists --no-owner --no-password --dbname "$live_db" <"$dump" >/dev/null
  printf 'DUMP_RESTORED\n'
}

copy_to_ehr_remove_new_listeners() {
  docker rm -f \
    "cosmabot-standalone-copyehr-api-${STAGING_SHORT}" \
    "cosmabot-standalone-copyehr-edge-${STAGING_SHORT}" >/dev/null 2>&1 || true
}

copy_to_ehr_remove_trial() {
  docker rm -f \
    "cosmabot-standalone-copyehr-trial-pg-${STAGING_SHORT}" \
    "cosmabot-standalone-copyehr-trial-api-${STAGING_SHORT}" \
    "cosmabot-standalone-copyehr-trial-edge-${STAGING_SHORT}" >/dev/null 2>&1 || true
}

copy_to_ehr_expect_ready() {
  local port="$1" body
  body=$(curl -sf "http://127.0.0.1:${port}/ready") || return 1
  printf '%s' "$body" | grep -F '"status":"ready"' >/dev/null || return 1
  printf '%s' "$body" | grep -F 'standalone_clerk_synthetic' >/dev/null || return 1
  printf 'READY_OK %s\n' "$port"
}

copy_to_ehr_expect_version() {
  local port="$1" sha="$2" body commit
  body=$(curl -sf -H "Host: ${STAGING_WEB_HOST}" "http://127.0.0.1:${port}/version.json") || return 1
  commit=$(printf '%s' "$body" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("commit",""))')
  [[ "$commit" == "$sha" ]] || return 1
  printf 'VERSION_OK\n'
}

copy_to_ehr_expect_feature() {
  local web_dir="$1" html_port="$2"
  grep -R -F -q -- 'Copy to EHR' "$web_dir" || return 1
  curl -sf -H "Host: ${STAGING_WEB_HOST}" "http://127.0.0.1:${html_port}/" | grep -F -q 'id="root"' || return 1
  printf 'COPY_TO_EHR_PRESENT\n'
}

copy_to_ehr_live_still_serving() {
  local active
  active=$(tr -d '[:space:]' </etc/cosmabot/active-release)
  case "$active" in
    *"RELEASE_DIR=${STAGING_DATA_ROOT}/${STAGING_PRIOR_RELEASE}") ;;
    *) printf 'LIVE_POINTER_CHANGED\n' >&2; return 1 ;;
  esac
  [[ "$(docker inspect --format '{{.State.Running}}' "cosmabot-standalone-r10-api-${STAGING_SHORT}")" == "true" ]] || return 1
  [[ "$(docker inspect --format '{{.State.Running}}' "cosmabot-standalone-r10-edge-${STAGING_SHORT}")" == "true" ]] || return 1
}

copy_to_ehr_start_new_listeners() {
  local edge_conf="${STAGING_DATA_ROOT}/release-r6r1/edge-nginx.conf"
  [[ -f "$edge_conf" ]] || edge_conf="${STAGING_DATA_ROOT}/release-r10/edge-nginx.conf"
  [[ -f "$edge_conf" ]] || return 1
  docker run -d --name "cosmabot-standalone-copyehr-api-${STAGING_SHORT}" \
    --network host --userns host --user 21000:21000 --read-only \
    --security-opt no-new-privileges:true --restart=on-failure:3 \
    --cap-drop ALL --pids-limit 128 --memory 1536m --cpus 1.25 --dns 127.0.0.53 \
    --entrypoint /usr/local/bin/python \
    -v "${STAGING_DATA_ROOT}/app:${STAGING_DATA_ROOT}/app" \
    -v "${COPY_TO_EHR_RELEASE}/config/api-public.json:/run/cosmabot-standalone/api-public.json:ro" \
    -v "${STAGING_DATA_ROOT}/release-r5r1/config/api-private.json:/run/cosmabot-standalone/api-private.json:ro" \
    "${STAGING_API_REPOSITORY}:${COPY_TO_EHR_SHA}" \
    -I /app/standalone-entrypoint.py "$LIVE_API_PORT" >/dev/null
  docker run -d --name "cosmabot-standalone-copyehr-edge-${STAGING_SHORT}" \
    --network host --user 21002:21002 --read-only \
    --security-opt no-new-privileges:true --restart=on-failure:3 \
    --cap-drop ALL --tmpfs /tmp:rw,noexec,nosuid,size=32m \
    -v "${edge_conf}:/run/cosmabot-edge/nginx.conf:ro" \
    -v "${COPY_TO_EHR_RELEASE}/web:/usr/share/nginx/html:ro" \
    --entrypoint /usr/sbin/nginx \
    "$STAGING_EDGE_IMAGE" \
    -c /run/cosmabot-edge/nginx.conf -g 'daemon off;' >/dev/null
}

copy_to_ehr_ready_for_pointer() {
  copy_to_ehr_expect_ready "$LIVE_API_PORT" || return 1
  copy_to_ehr_expect_version "$LIVE_EDGE_PORT" "$COPY_TO_EHR_SHA" || return 1
  copy_to_ehr_expect_feature "${COPY_TO_EHR_RELEASE}/web" "$LIVE_EDGE_PORT"
}

copy_to_ehr_post_switch_checks() {
  local active
  copy_to_ehr_ready_for_pointer || return 1
  active=$(tr -d '[:space:]' </etc/cosmabot/active-release)
  case "$active" in
    *"RELEASE_DIR=${COPY_TO_EHR_RELEASE}") ;;
    *) return 1 ;;
  esac
  printf 'POST_SWITCH_OK\n'
}

copy_to_ehr_read_served_commit() {
  local port="$1" body commit
  body=$(curl -sf -H "Host: ${STAGING_WEB_HOST}" "http://127.0.0.1:${port}/version.json") || return 1
  commit=$(printf '%s' "$body" | python3 -c 'import json, sys
raw = sys.stdin.read()
try:
    value = json.loads(raw).get("commit", "")
except Exception:
    value = ""
if not isinstance(value, str):
    value = ""
sys.stdout.write(value)
') || return 1
  [[ "$commit" =~ ^[0-9a-f]{8,40}$ ]] || return 1
  printf '%s\n' "$commit"
}

copy_to_ehr_confirm_prior_identity() {
  local expected="$1" image_ref="$2" source_text="$3" served=""
  [[ ${#expected} -ge 8 ]] || {
    printf 'PRIOR_SHA_MISMATCH\n' >&2
    return 1
  }
  if ! served=$(copy_to_ehr_read_served_commit "$LIVE_EDGE_PORT"); then
    printf 'PRIOR_VERSION_UNREADABLE\n' >&2
    return 1
  fi
  if ! copy_to_ehr_prior_matches "$expected" "$served"; then
    printf 'PRIOR_VERSION_MISMATCH\n' >&2
    return 1
  fi
  COPY_TO_EHR_SERVED_PRIOR="$served"
  if [[ -n "$source_text" ]] && copy_to_ehr_prior_matches "$expected" "$source_text"; then
    return 0
  fi
  if copy_to_ehr_prior_matches "$expected" "$image_ref"; then
    return 0
  fi
  printf 'PRIOR_SHA_MISMATCH\n' >&2
  return 1
}

copy_to_ehr_assert_target_schema() {
  local live_db="$1" version=""
  version=$(copy_to_ehr_psql "$live_db" "SELECT version_num FROM public.alembic_version") || return 1
  [[ "$version" == "$STAGING_TARGET_SCHEMA" ]]
}

copy_to_ehr_disarm_cutover_trap() {
  trap - ERR EXIT INT
}

copy_to_ehr_cutover_trap_rollback() {
  local status=$?
  copy_to_ehr_disarm_cutover_trap
  if ! copy_to_ehr_rollback_to_r10 "$COPY_TO_EHR_TRAP_DUMP" "$COPY_TO_EHR_TRAP_DB"; then
    exit 1
  fi
  printf 'CUTOVER_ROLLBACK\n' >&2
  exit "$status"
}

copy_to_ehr_arm_cutover_trap() {
  COPY_TO_EHR_TRAP_DUMP="$1"
  COPY_TO_EHR_TRAP_DB="$2"
  trap copy_to_ehr_cutover_trap_rollback ERR EXIT INT
}

copy_to_ehr_rollback_verify_prior() {
  local ready_body="" ready_code="" version_commit=""
  ready_body=$(mktemp /tmp/copy-to-ehr-ready.XXXXXX)
  ready_code=$(curl -s -o "$ready_body" -w '%{http_code}' "http://127.0.0.1:${LIVE_API_PORT}/ready") || {
    rm -f -- "$ready_body"
    return 1
  }
  if [[ "$ready_code" != "200" ]] || ! grep -F -q '"status":"ready"' "$ready_body"; then
    rm -f -- "$ready_body"
    return 1
  fi
  rm -f -- "$ready_body"
  version_commit=$(copy_to_ehr_read_served_commit "$LIVE_EDGE_PORT") || return 1
  if [[ -n "${COPY_TO_EHR_SERVED_PRIOR:-}" ]]; then
    [[ "$version_commit" == "$COPY_TO_EHR_SERVED_PRIOR" ]] || return 1
  fi
  copy_to_ehr_prior_matches "${COPY_TO_EHR_PRIOR:-}" "$version_commit"
}

copy_to_ehr_rollback_to_r10() {
  local dump="$1" live_db="$2"
  if ! copy_to_ehr_remove_new_listeners; then
    printf 'CUTOVER_ROLLBACK_FAILED\n' >&2
    return 1
  fi
  if ! copy_to_ehr_restore_dump_over_live "$dump" "$live_db"; then
    printf 'CUTOVER_ROLLBACK_FAILED\n' >&2
    return 1
  fi
  if ! copy_to_ehr_start_prior_listeners; then
    printf 'CUTOVER_ROLLBACK_FAILED\n' >&2
    return 1
  fi
  if ! copy_to_ehr_write_prior_pointer; then
    printf 'CUTOVER_ROLLBACK_FAILED\n' >&2
    return 1
  fi
  if ! copy_to_ehr_rollback_verify_prior; then
    printf 'CUTOVER_ROLLBACK_FAILED\n' >&2
    return 1
  fi
  printf 'ROLLBACK_OK\n'
}

copy_to_ehr_fail_rollback() {
  local dump="$1" live_db="$2"
  copy_to_ehr_disarm_cutover_trap
  if ! copy_to_ehr_rollback_to_r10 "$dump" "$live_db"; then
    return 1
  fi
  printf 'CUTOVER_ROLLBACK\n' >&2
  return 1
}

copy_to_ehr_cutover_sequence() {
  local root="$1" dump="$2" live_db="$3"
  if ! copy_to_ehr_restore_gate "$root" "$dump" "$live_db"; then
    printf 'CUTOVER_ABORT_RESTORE_CHECK\n' >&2
    return 1
  fi
  copy_to_ehr_arm_cutover_trap "$dump" "$live_db"
  if ! copy_to_ehr_stop_live_listeners; then
    copy_to_ehr_disarm_cutover_trap
    if ! copy_to_ehr_start_prior_listeners; then
      printf 'CUTOVER_ROLLBACK_FAILED\n' >&2
      return 1
    fi
    printf 'CUTOVER_ABORT_STOP\n' >&2
    return 1
  fi
  if ! copy_to_ehr_migrate_live "$dump"; then
    copy_to_ehr_fail_rollback "$dump" "$live_db" || return 1
  fi
  if ! copy_to_ehr_assert_target_schema "$live_db"; then
    printf 'SCHEMA_NOT_TARGET\n' >&2
    copy_to_ehr_fail_rollback "$dump" "$live_db" || return 1
  fi
  if ! copy_to_ehr_start_new_listeners; then
    copy_to_ehr_fail_rollback "$dump" "$live_db" || return 1
  fi
  if ! copy_to_ehr_ready_for_pointer; then
    copy_to_ehr_fail_rollback "$dump" "$live_db" || return 1
  fi
  if ! copy_to_ehr_write_new_pointer; then
    copy_to_ehr_fail_rollback "$dump" "$live_db" || return 1
  fi
  if ! copy_to_ehr_post_switch_checks; then
    copy_to_ehr_fail_rollback "$dump" "$live_db" || return 1
  fi
  copy_to_ehr_disarm_cutover_trap
  printf 'CUTOVER_OK\n'
}

copy_to_ehr_cutover_main() {
  local live_port="" live_db="" meta_file image_ref="" source_file observed=""
  local active=""
  set +x
  umask 077
  active=$(tr -d '[:space:]' </etc/cosmabot/active-release)
  case "$active" in
    *"RELEASE_DIR=${STAGING_DATA_ROOT}/${STAGING_PRIOR_RELEASE}") ;;
    *) printf 'ACTIVE_RELEASE_NOT_R10\n' >&2; return 1 ;;
  esac
  image_ref=$(docker inspect --format '{{.Config.Image}}' "cosmabot-standalone-r10-api-${STAGING_SHORT}")
  source_file="${STAGING_DATA_ROOT}/${STAGING_PRIOR_RELEASE}/source-sha"
  observed=""
  if [[ -f "$source_file" ]]; then
    observed=$(tr -d '[:space:]' <"$source_file")
  fi
  copy_to_ehr_confirm_prior_identity "$COPY_TO_EHR_PRIOR" "$image_ref" "$observed" || return 1
  COPY_TO_EHR_PG_CONTAINER=$(docker ps --format '{{.ID}} {{.Ports}}' | awk '/(^|[^0-9])54111([^0-9]|$)/ {print $1; exit}')
  if [[ -z "${COPY_TO_EHR_PG_CONTAINER:-}" ]]; then
    printf 'LIVE_POSTGRES_CONTAINER_NOT_FOUND\n' >&2
    return 1
  fi
  meta_file=$(mktemp /tmp/copy-to-ehr-db-meta.XXXXXX)
  chmod 600 "$meta_file"
  python3 - "${STAGING_DATA_ROOT}/release-r5r1/config/api-private.json" "$meta_file" <<'PY'
import json, sys
from urllib.parse import urlparse
private_path, out_path = sys.argv[1:]
try:
    raw = json.loads(open(private_path, "r", encoding="utf-8").read())["DATABASE_URL"]
    parsed = urlparse(raw.replace("postgresql+psycopg://", "postgresql://", 1))
    database = parsed.path.lstrip("/").split("?", 1)[0]
    if parsed.port != 54111 or not database.startswith("cosmabot_standalone_"):
        raise RuntimeError("refused")
    with open(out_path, "w", encoding="utf-8") as handle:
        handle.write("%s\n%s\n" % (parsed.port, database))
except Exception:
    sys.stderr.write("LIVE_DATABASE_REFUSED\n")
    sys.exit(1)
PY
  live_port=$(sed -n '1p' "$meta_file")
  live_db=$(sed -n '2p' "$meta_file")
  rm -f -- "$meta_file"
  [[ "$live_port" == "54111" ]] || { printf 'LIVE_DATABASE_PORT_REFUSED\n' >&2; return 1; }
  COPY_TO_EHR_RELEASE=$(copy_to_ehr_release_dir "$COPY_TO_EHR_SHA" "$STAGING_DATA_ROOT")
  copy_to_ehr_cutover_sequence "$STAGING_DATA_ROOT" "$COPY_TO_EHR_DUMP" "$live_db"
}

copy_to_ehr_api_build_main() {
  local work="" free_kib="" head=""
  set +x
  umask 077
  free_kib=$(df -Pk /var/tmp | awk 'NR==2 {print $4}')
  if [[ -z "$free_kib" || "$free_kib" -lt "$MIN_FREE_KIB" ]]; then
    printf 'DISK_REFUSED\n' >&2
    return 1
  fi
  work=$(mktemp -d /var/tmp/copy-to-ehr-api.XXXXXX)
  chmod 700 "$work"
  case "$work" in
    */Desktop/cosmaneura-os|*/Desktop/cosmaneura-os/*)
      printf 'DESKTOP_PATH_REFUSED\n' >&2
      return 1
      ;;
  esac
  git clone --quiet "$PUBLIC_GIT_URL" "$work/src"
  git -C "$work/src" checkout --detach --quiet "$COPY_TO_EHR_SHA"
  head=$(git -C "$work/src" rev-parse HEAD)
  [[ "$head" == "$COPY_TO_EHR_SHA" ]] || { printf 'SHA_MISMATCH\n' >&2; return 1; }
  [[ -z "$(git -C "$work/src" status --porcelain)" ]] || { printf 'DIRTY_TREE\n' >&2; return 1; }
  python3 "$work/src/infra/standalone/package/prepare_api_recipe.py" \
    --source "$work/src" --output "$work/recipe"
  cp "$work/recipe/Dockerfile" "$work/src/Dockerfile.copy-to-ehr"
  cp "$work/recipe/Dockerfile.dockerignore" "$work/src/Dockerfile.copy-to-ehr.dockerignore"
  if ! docker build --platform linux/amd64 \
    --file "$work/src/Dockerfile.copy-to-ehr" \
    --build-arg "SOURCE_COMMIT=${COPY_TO_EHR_SHA}" \
    --tag "${STAGING_API_REPOSITORY}:${COPY_TO_EHR_SHA}" \
    "$work/src" >"$work/build.log" 2>&1; then
    printf 'API_BUILD_FAILED\n' >&2
    return 1
  fi
  docker image inspect --format '{{.Id}}' "${STAGING_API_REPOSITORY}:${COPY_TO_EHR_SHA}"
  printf 'API_IMAGE_OK\n'
}

copy_to_ehr_side_port_main() {
  local release="" archive="" url_file="" pass_file="" live_pg="" image="" edge_src=""
  local public_src="" private_src=""
  set +x
  umask 077
  : "${COPY_TO_EHR_TRIAL_POSTGRES_PORT:=54130}"
  : "${COPY_TO_EHR_LIVE_POSTGRES_PORT:=54111}"
  if [[ "$COPY_TO_EHR_TRIAL_POSTGRES_PORT" == "$COPY_TO_EHR_LIVE_POSTGRES_PORT" ]]; then
    printf 'SIDE_PORT_REFUSED_LIVE_DATABASE\n' >&2
    return 1
  fi
  copy_to_ehr_live_still_serving || return 1
  release=$(copy_to_ehr_release_dir "$COPY_TO_EHR_SHA" "$STAGING_DATA_ROOT")
  COPY_TO_EHR_RELEASE="$release"
  archive="${release}/cosmabot-web-${COPY_TO_EHR_SHA}.tar.gz"
  [[ -s "$archive" ]] || { printf 'WEB_ARCHIVE_MISSING\n' >&2; return 1; }
  mkdir -p -- "$release/web" "$release/config"
  chmod 700 "$release" "$release/config"
  tar -xzf "$archive" -C "$release/web"
  python3 -c 'import json,sys; assert json.load(open(sys.argv[1]))["commit"]==sys.argv[2]' \
    "$release/web/version.json" "$COPY_TO_EHR_SHA" || return 1
  copy_to_ehr_remove_trial
  live_pg=$(docker ps --format '{{.ID}} {{.Ports}}' | awk '/(^|[^0-9])54111([^0-9]|$)/ {print $1; exit}')
  [[ -n "$live_pg" ]] || { printf 'LIVE_POSTGRES_CONTAINER_NOT_FOUND\n' >&2; return 1; }
  image=$(docker inspect --format '{{.Image}}' "$live_pg")
  pass_file="${release}/trial-postgres.password"
  url_file="${release}/trial-database.url"
  python3 -c 'import secrets; print(secrets.token_urlsafe(32))' >"$pass_file"
  chmod 400 "$pass_file"
  {
    printf 'postgresql+psycopg://cosmabot_copyehr_trial:'
    tr -d '[:space:]' <"$pass_file"
    printf '@127.0.0.1:54130/cosmabot_copy_ehr_trial\n'
  } >"$url_file"
  chmod 400 "$url_file"
  if ! copy_to_ehr_trial_url_file_allowed "$url_file"; then
    printf 'SIDE_PORT_REFUSED_LIVE_DATABASE\n' >&2
    return 1
  fi
  docker run -d --name "cosmabot-standalone-copyehr-trial-pg-${STAGING_SHORT}" \
    --network host \
    -v "${pass_file}:/run/pgpass:ro" \
    -e POSTGRES_PASSWORD_FILE=/run/pgpass \
    -e POSTGRES_USER=cosmabot_copyehr_trial \
    -e POSTGRES_DB=cosmabot_copy_ehr_trial \
    "$image" \
    postgres -c listen_addresses=127.0.0.1 -c port=54130 >/dev/null
  public_src="${STAGING_DATA_ROOT}/release-r5r1/config/api-public.json"
  private_src="${STAGING_DATA_ROOT}/release-r5r1/config/api-private.json"
  python3 - "$public_src" "${release}/config/api-public.json" <<'PY'
import json, sys
from pathlib import Path
source, dest = sys.argv[1:]
data = json.loads(Path(source).read_text())
private_names = {
    "DATABASE_URL", "HUMAN_DEPLOY_EVIDENCE_REF", "WORKSPACE_LLM_API_KEY",
    "GOOGLE_CONNECTION_CLIENT_SECRET", "GOOGLE_CONNECTION_ENCRYPTION_KEY",
    "MICROSOFT_CONNECTION_CLIENT_SECRET", "MICROSOFT_CONNECTION_ENCRYPTION_KEY",
}
if private_names.intersection(data):
    raise SystemExit(1)
data["COPY_TO_EHR_ENABLED"] = True
data["COPY_TO_EHR_REMOTE_ENABLED"] = True
data["COPY_TO_EHR_FALLBACK_ENABLED"] = True
Path(dest).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
Path(dest).chmod(0o644)
PY
  python3 - "$private_src" "${release}/config/api-private.json" "$url_file" <<'PY'
import json, sys
from pathlib import Path
source, dest, url_path = sys.argv[1:]
url = Path(url_path).read_text().strip()
if ":54111" in url or "cosmabot_standalone_" in url:
    raise SystemExit(1)
data = json.loads(Path(source).read_text())
data["DATABASE_URL"] = url
Path(dest).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
Path(dest).chmod(0o400)
PY
  chown 21000:21000 "${release}/config/api-private.json"
  edge_src="${STAGING_DATA_ROOT}/release-r10/edge-nginx.conf"
  [[ -f "$edge_src" ]] || edge_src="${STAGING_DATA_ROOT}/release-r6r1/edge-nginx.conf"
  python3 - "$edge_src" "${release}/edge-nginx.trial.conf" <<'PY'
from pathlib import Path
import sys
source, dest = sys.argv[1:]
text = Path(source).read_text()
text = text.replace("172.30.241.1:54112", "127.0.0.1:54122").replace("127.0.0.1:54110", "127.0.0.1:54120")
Path(dest).write_text(text)
PY
  nft add rule ip filter "CB21000_${STAGING_SHORT}" tcp dport 54120 accept comment "copy-ehr-trial" \
    || { printf 'NFT_TRIAL_RULE_FAILED\n' >&2; copy_to_ehr_remove_trial; return 1; }
  docker run --rm --network host --user 0:0 \
    --entrypoint /usr/local/bin/python \
    -v "${url_file}:/run/trial-database.url:ro" \
    "${STAGING_API_REPOSITORY}:${COPY_TO_EHR_SHA}" \
    -c 'from pathlib import Path
from alembic.config import Config
from alembic import command
url = Path("/run/trial-database.url").read_text().strip()
if ":54111" in url or not url.endswith("@127.0.0.1:54130/cosmabot_copy_ehr_trial"):
    raise SystemExit(1)
cfg = Config("/app/alembic.ini")
cfg.set_main_option("sqlalchemy.url", url)
command.upgrade(cfg, "head")' >/dev/null \
    || { printf 'SIDE_PORT_REFUSED_LIVE_DATABASE\n' >&2; copy_to_ehr_remove_trial; return 1; }
  docker run -d --name "cosmabot-standalone-copyehr-trial-api-${STAGING_SHORT}" \
    --network host --userns host --user 21000:21000 --read-only \
    --security-opt no-new-privileges:true --restart=on-failure:3 \
    --cap-drop ALL --pids-limit 128 --memory 1536m --cpus 1.25 --dns 127.0.0.53 \
    --entrypoint /usr/local/bin/python \
    -v "${STAGING_DATA_ROOT}/app:${STAGING_DATA_ROOT}/app" \
    -v "${release}/config/api-public.json:/run/cosmabot-standalone/api-public.json:ro" \
    -v "${release}/config/api-private.json:/run/cosmabot-standalone/api-private.json:ro" \
    "${STAGING_API_REPOSITORY}:${COPY_TO_EHR_SHA}" \
    -I /app/standalone-entrypoint.py "$TRIAL_API_PORT" >/dev/null \
    || { copy_to_ehr_remove_trial; return 1; }
  docker run -d --name "cosmabot-standalone-copyehr-trial-edge-${STAGING_SHORT}" \
    --network host --user 21002:21002 --read-only \
    --security-opt no-new-privileges:true --restart=on-failure:3 \
    --cap-drop ALL --tmpfs /tmp:rw,noexec,nosuid,size=32m \
    -v "${release}/edge-nginx.trial.conf:/run/cosmabot-edge/nginx.conf:ro" \
    -v "${release}/web:/usr/share/nginx/html:ro" \
    --entrypoint /usr/sbin/nginx \
    "$STAGING_EDGE_IMAGE" \
    -c /run/cosmabot-edge/nginx.conf -g 'daemon off;' >/dev/null \
    || { copy_to_ehr_remove_trial; return 1; }
  copy_to_ehr_expect_ready "$TRIAL_API_PORT" || { copy_to_ehr_remove_trial; return 1; }
  copy_to_ehr_expect_version "$TRIAL_EDGE_PORT" "$COPY_TO_EHR_SHA" || { copy_to_ehr_remove_trial; return 1; }
  copy_to_ehr_expect_feature "${release}/web" "$TRIAL_EDGE_PORT" || { copy_to_ehr_remove_trial; return 1; }
  copy_to_ehr_live_still_serving || { copy_to_ehr_remove_trial; return 1; }
  printf 'SIDE_PORT_OK\n'
}

copy_to_ehr_remote_prelude() {
  local sha="$1" prior="$2" dump="$3"
  cat <<EOF
set -euo pipefail
set +x
umask 077
STAGING_DATA_ROOT='$STAGING_DATA_ROOT'
STAGING_INSTANCE_ID='$STAGING_INSTANCE_ID'
STAGING_SHORT='$STAGING_SHORT'
STAGING_PRIOR_RELEASE='$STAGING_PRIOR_RELEASE'
STAGING_EDGE_IMAGE='$STAGING_EDGE_IMAGE'
STAGING_API_REPOSITORY='$STAGING_API_REPOSITORY'
STAGING_LIVE_SCHEMA='$STAGING_LIVE_SCHEMA'
STAGING_TARGET_SCHEMA='$STAGING_TARGET_SCHEMA'
STAGING_WEB_HOST='$STAGING_WEB_HOST'
LIVE_API_PORT=$LIVE_API_PORT
LIVE_EDGE_PORT=$LIVE_EDGE_PORT
LIVE_POSTGRES_PORT=$LIVE_POSTGRES_PORT
TRIAL_API_PORT=$TRIAL_API_PORT
TRIAL_EDGE_PORT=$TRIAL_EDGE_PORT
TRIAL_POSTGRES_PORT=$TRIAL_POSTGRES_PORT
COPY_TO_EHR_TRIAL_POSTGRES_PORT=$TRIAL_POSTGRES_PORT
COPY_TO_EHR_LIVE_POSTGRES_PORT=$LIVE_POSTGRES_PORT
MIN_FREE_KIB=$MIN_FREE_KIB
PUBLIC_GIT_URL='$PUBLIC_GIT_URL'
COPY_TO_EHR_SHA='$sha'
COPY_TO_EHR_PRIOR='$prior'
COPY_TO_EHR_DUMP='$dump'
EOF
}

copy_to_ehr_wrap_remote() {
  local body="$1"
  printf "%s\n" "exec /bin/bash <<'COPY_TO_EHR_BASH_BODY'"
  printf '%s\n' "$body"
  printf '%s\n' "COPY_TO_EHR_BASH_BODY"
}

copy_to_ehr_render_api_build() {
  local sha="$1" body
  body=$(copy_to_ehr_remote_prelude "$sha" "" "")
  body="${body}
$(declare -f copy_to_ehr_api_build_main)
copy_to_ehr_api_build_main"
  copy_to_ehr_wrap_remote "$body"
}

copy_to_ehr_render_side_port() {
  local sha="$1" body
  body=$(copy_to_ehr_remote_prelude "$sha" "" "")
  body="${body}
$(declare -f \
    copy_to_ehr_release_dir \
    copy_to_ehr_trial_url_file_allowed \
    copy_to_ehr_remove_trial \
    copy_to_ehr_expect_ready \
    copy_to_ehr_expect_version \
    copy_to_ehr_expect_feature \
    copy_to_ehr_live_still_serving \
    copy_to_ehr_side_port_main)
copy_to_ehr_side_port_main"
  copy_to_ehr_wrap_remote "$body"
}

copy_to_ehr_render_cutover() {
  local sha="$1" prior="$2" dump="$3" body
  body=$(copy_to_ehr_remote_prelude "$sha" "$prior" "$dump")
  body="${body}
$(declare -f \
    copy_to_ehr_prior_matches \
    copy_to_ehr_read_served_commit \
    copy_to_ehr_confirm_prior_identity \
    copy_to_ehr_assert_target_schema \
    copy_to_ehr_disarm_cutover_trap \
    copy_to_ehr_cutover_trap_rollback \
    copy_to_ehr_arm_cutover_trap \
    copy_to_ehr_rollback_verify_prior \
    copy_to_ehr_fail_rollback \
    copy_to_ehr_release_dir \
    copy_to_ehr_dump_file_on_staging_vm \
    copy_to_ehr_pg_dump \
    copy_to_ehr_pg_restore \
    copy_to_ehr_psql \
    copy_to_ehr_createdb \
    copy_to_ehr_dropdb \
    copy_to_ehr_restore_gate \
    copy_to_ehr_run_live_migrate \
    copy_to_ehr_migrate_live \
    copy_to_ehr_stop_live_listeners \
    copy_to_ehr_start_prior_listeners \
    copy_to_ehr_write_prior_pointer \
    copy_to_ehr_write_new_pointer \
    copy_to_ehr_restore_dump_over_live \
    copy_to_ehr_remove_new_listeners \
    copy_to_ehr_expect_ready \
    copy_to_ehr_expect_version \
    copy_to_ehr_expect_feature \
    copy_to_ehr_start_new_listeners \
    copy_to_ehr_ready_for_pointer \
    copy_to_ehr_post_switch_checks \
    copy_to_ehr_rollback_to_r10 \
    copy_to_ehr_cutover_sequence \
    copy_to_ehr_cutover_main)
copy_to_ehr_cutover_main"
  copy_to_ehr_wrap_remote "$body"
}

copy_to_ehr_invoke_remote() {
  local name="$1" body="$2" file result
  if [[ "${COPY_TO_EHR_EXECUTE:-0}" != "1" ]]; then
    printf 'dry-run: az vm run-command invoke --subscription %s --resource-group %s --name %s --command-id RunShellScript --scripts @%s\n' \
      "$STAGING_SUBSCRIPTION_ID" "$STAGING_RESOURCE_GROUP" "$STAGING_VM_NAME" "$name"
    printf 'remote-script %s begin\n%s\nremote-script %s end\n' "$name" "$body" "$name"
    return 0
  fi
  umask 077
  file=$(mktemp "${TMPDIR:-/tmp}/copy-to-ehr-${name}.XXXXXX")
  chmod 600 "$file"
  printf '%s\n' "$body" >"$file"
  if ! result=$(az vm run-command invoke \
    --subscription "$STAGING_SUBSCRIPTION_ID" \
    --resource-group "$STAGING_RESOURCE_GROUP" \
    --name "$STAGING_VM_NAME" \
    --command-id RunShellScript \
    --scripts "@${file}"); then
    rm -f -- "$file"
    copy_to_ehr_die "run-command ${name} failed"
  fi
  rm -f -- "$file"
  printf '%s' "$result" | copy_to_ehr_filter_run_output
}

copy_to_ehr_filter_run_output() {
  python3 -c '
import json, sys
raw = sys.stdin.read()
try:
    data = json.loads(raw)
except Exception:
    sys.stderr.write("run-command response was not json\n")
    sys.exit(1)
value = data.get("value")
text = ""
if isinstance(value, list):
    for item in value:
        if isinstance(item, dict):
            text += str(item.get("message") or "")
allowed = {
    "OK", "REFUSED", "ABORT", "DUMP_BYTES", "COUNT", "ROLLBACK",
    "CHUNK", "POINTER", "READY", "VERSION", "COPY_TO_EHR", "PRIOR",
    "DISK", "API_IMAGE", "POST_SWITCH", "RESTORE", "SCHEMA",
}

def whole(token):
    head = token.split("=", 1)[0]
    parts = head.split("_")
    if head in allowed or token in allowed:
        return True
    return any(part in allowed for part in parts)

for line in text.splitlines():
    if len(line) > 200:
        continue
    if any(whole(word) for word in line.split()):
        sys.stdout.write(line + "\n")
'
}

copy_to_ehr_print_plan() {
  local sha="$1" workdir="$2" web_env="$3" dump_file="$4" cutover="$5" prior="$6"
  local release
  release=$(copy_to_ehr_release_dir "$sha" "$STAGING_DATA_ROOT")
  cat <<EOF
dry-run: df -Pk ${workdir}
dry-run: git clone --quiet ${PUBLIC_GIT_URL} ${workdir}/src
dry-run: git -C ${workdir}/src checkout --detach ${sha}
dry-run: test "\$(git -C ${workdir}/src rev-parse HEAD)" = ${sha}
dry-run: test -z "\$(git -C ${workdir}/src status --porcelain)"
dry-run: cp -p -- ${web_env} ${workdir}/src/web/.env.production
dry-run: VITE_BUILD_SHA=${sha} corepack pnpm install --frozen-lockfile
dry-run: VITE_BUILD_SHA=${sha} corepack pnpm run build
dry-run: node scripts/package-staging-web.mjs --dist web/dist --output ${workdir}/web-package
dry-run: transfer the web archive in ${CHUNK_BYTES}-byte chunks with az vm run-command invoke to ${release}/cosmabot-web-${sha}.tar.gz
dry-run: chunk payloads are not printed; the database dump is not part of this transfer
EOF
  copy_to_ehr_invoke_remote "api-build" "$(copy_to_ehr_render_api_build "$sha")"
  copy_to_ehr_invoke_remote "side-port" "$(copy_to_ehr_render_side_port "$sha")"
  if [[ "$cutover" == "1" ]]; then
    copy_to_ehr_invoke_remote "cutover" "$(copy_to_ehr_render_cutover "$sha" "$prior" "$dump_file")"
    printf 'dry-run: cutover would dump on the VM, prove a scratch restore, then migrate and switch\n'
    printf 'dry-run: rollback restores that on-VM dump and repoints to %s\n' "$STAGING_PRIOR_RELEASE"
  else
    printf 'stop before cutover: live %s stays on %s/%s\n' \
      "$STAGING_PRIOR_RELEASE" "$LIVE_API_PORT" "$LIVE_EDGE_PORT"
  fi
}

copy_to_ehr_check_names() {
  local resource_group="$1" vm_name="$2" web_host="$3" api_host="$4" subscription_flag="$5"
  if copy_to_ehr_explicitly_production "$resource_group" || [[ "$resource_group" != "$STAGING_RESOURCE_GROUP" ]]; then
    copy_to_ehr_die "resource group is not the staging allowlist"
  fi
  if copy_to_ehr_explicitly_production "$vm_name" || [[ "$vm_name" != "$STAGING_VM_NAME" ]]; then
    copy_to_ehr_die "vm is not the staging allowlist"
  fi
  if copy_to_ehr_explicitly_production "$web_host" || [[ "$web_host" != "$STAGING_WEB_HOST" ]]; then
    copy_to_ehr_die "hostname is not the staging allowlist"
  fi
  if copy_to_ehr_explicitly_production "$api_host" || [[ "$api_host" != "$STAGING_API_HOST" ]]; then
    copy_to_ehr_die "hostname is not the staging allowlist"
  fi
  if [[ -n "$subscription_flag" ]]; then
    if copy_to_ehr_explicitly_production "$subscription_flag" || [[ "$subscription_flag" != "$STAGING_SUBSCRIPTION_ID" ]]; then
      copy_to_ehr_die "subscription is not the staging allowlist"
    fi
  fi
}

copy_to_ehr_check_az() {
  local account_json vm_json
  account_json=$(az account show --output json)
  printf '%s' "$account_json" | copy_to_ehr_assert_account_json
  vm_json=$(az vm show \
    --subscription "$STAGING_SUBSCRIPTION_ID" \
    --resource-group "$STAGING_RESOURCE_GROUP" \
    --name "$STAGING_VM_NAME" \
    --show-details \
    --query "{name:name, resourceGroup:resourceGroup, publicIps:publicIps}" \
    --output json)
  printf '%s' "$vm_json" | copy_to_ehr_assert_vm_json
}

copy_to_ehr_main() {
  local execute=0 cutover=0 sha="$DEFAULT_SOURCE_SHA" expect_prior=""
  local resource_group="$STAGING_RESOURCE_GROUP" vm_name="$STAGING_VM_NAME"
  local web_host="$STAGING_WEB_HOST" api_host="$STAGING_API_HOST"
  local workdir="" web_env="${COPY_TO_EHR_WEB_ENV:-${HOME:-}/code/cosmaneura-os-beta-staging-r10/web/.env.production}"
  local dump_target="${STAGING_DATA_ROOT}/copy-to-ehr-dumps/pre-migrate.dump"
  local subscription_flag="" dump_file="" expanded=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --execute) execute=1; shift ;;
      --cutover) cutover=1; shift ;;
      --sha)
        [[ $# -ge 2 ]] || copy_to_ehr_die "--sha requires a value"
        sha="$2"; shift 2 ;;
      --expect-prior-sha)
        [[ $# -ge 2 ]] || copy_to_ehr_die "--expect-prior-sha requires a value"
        expect_prior="$2"; shift 2 ;;
      --resource-group)
        [[ $# -ge 2 ]] || copy_to_ehr_die "--resource-group requires a value"
        resource_group="$2"; shift 2 ;;
      --vm)
        [[ $# -ge 2 ]] || copy_to_ehr_die "--vm requires a value"
        vm_name="$2"; shift 2 ;;
      --web-host)
        [[ $# -ge 2 ]] || copy_to_ehr_die "--web-host requires a value"
        web_host="$2"; shift 2 ;;
      --api-host)
        [[ $# -ge 2 ]] || copy_to_ehr_die "--api-host requires a value"
        api_host="$2"; shift 2 ;;
      --workdir)
        [[ $# -ge 2 ]] || copy_to_ehr_die "--workdir requires a value"
        workdir="$2"; shift 2 ;;
      --web-env)
        [[ $# -ge 2 ]] || copy_to_ehr_die "--web-env requires a value"
        web_env="$2"; shift 2 ;;
      --dump-target)
        [[ $# -ge 2 ]] || copy_to_ehr_die "--dump-target requires a value"
        dump_target="$2"; shift 2 ;;
      --subscription)
        [[ $# -ge 2 ]] || copy_to_ehr_die "--subscription requires a value"
        subscription_flag="$2"; shift 2 ;;
      -h|--help) copy_to_ehr_usage; exit 0 ;;
      *) copy_to_ehr_die "unknown argument" ;;
    esac
  done
  if [[ "$execute" -eq 1 && "$cutover" -eq 1 ]]; then
    printf '%s\n' 'Tonight for existing live users: this run cuts staging over only after a verified dump and restore check on the staging VM; production stays untouched.'
  else
    printf '%s\n' 'Tonight for existing live users: nothing changes.'
  fi
  copy_to_ehr_require_sha "$sha" source || copy_to_ehr_die "--sha must be 40 lowercase hex characters"
  if copy_to_ehr_path_is_desktop_checkout "$PWD"; then
    copy_to_ehr_die "refusing a path inside ~/Desktop/cosmaneura-os"
  fi
  if [[ -n "$workdir" ]]; then
    expanded=$(copy_to_ehr_expand_path "$workdir")
    if copy_to_ehr_path_is_desktop_checkout "$expanded"; then
      copy_to_ehr_die "refusing a path inside ~/Desktop/cosmaneura-os"
    fi
    workdir="$expanded"
  fi
  expanded=$(copy_to_ehr_expand_path "$web_env")
  if copy_to_ehr_path_is_desktop_checkout "$expanded"; then
    copy_to_ehr_die "refusing a path inside ~/Desktop/cosmaneura-os"
  fi
  copy_to_ehr_check_names "$resource_group" "$vm_name" "$web_host" "$api_host" "$subscription_flag"
  if [[ "$cutover" -eq 1 ]]; then
    [[ -n "$expect_prior" ]] || copy_to_ehr_die "--cutover requires --expect-prior-sha"
    copy_to_ehr_require_sha "$expect_prior" prior || copy_to_ehr_die "--expect-prior-sha must be 8 to 40 lowercase hex characters"
  fi
  case "$dump_target" in
    /subscriptions/*) dump_file="${STAGING_DATA_ROOT}/copy-to-ehr-dumps/${sha}/pre-migrate.dump" ;;
    *) dump_file="$dump_target" ;;
  esac
  copy_to_ehr_validate_dump_target "$dump_target" || copy_to_ehr_die "dump target is outside the staging resource group or is on this Mac"
  copy_to_ehr_validate_dump_target "$dump_file" || copy_to_ehr_die "dump file is not on the staging VM"
  copy_to_ehr_check_az
  if [[ -z "$workdir" ]]; then
    if [[ "$execute" -eq 1 ]]; then
      workdir=$(mktemp -d "${TMPDIR:-/tmp}/copy-to-ehr-src.XXXXXX")
      chmod 700 "$workdir"
    else
      workdir='${TMPDIR:-/tmp}/copy-to-ehr-src.XXXXXX'
    fi
  fi
  export COPY_TO_EHR_EXECUTE="$execute"
  if [[ "$execute" -ne 1 ]]; then
    copy_to_ehr_print_plan "$sha" "$workdir" "$web_env" "$dump_file" "$cutover" "$expect_prior"
    return 0
  fi
  copy_to_ehr_execute "$sha" "$workdir" "$web_env" "$dump_file" "$cutover" "$expect_prior"
}

copy_to_ehr_execute() {
  local sha="$1" workdir="$2" web_env="$3" dump_file="$4" cutover="$5" prior="$6"
  local free_kib="" head="" release="" archive="" keys=""
  free_kib=$(df -Pk "$workdir" | awk 'NR==2 {print $4}')
  if [[ -z "$free_kib" || "$free_kib" -lt "$MIN_FREE_KIB" ]]; then
    copy_to_ehr_die "not enough free disk before the web build"
  fi
  git clone --quiet "$PUBLIC_GIT_URL" "$workdir/src"
  git -C "$workdir/src" checkout --detach --quiet "$sha"
  head=$(git -C "$workdir/src" rev-parse HEAD)
  [[ "$head" == "$sha" ]] || copy_to_ehr_die "checkout HEAD does not equal --sha"
  [[ -z "$(git -C "$workdir/src" status --porcelain)" ]] || copy_to_ehr_die "checkout is not clean"
  [[ -f "$web_env" && ! -L "$web_env" ]] || copy_to_ehr_die "web env file is missing"
  keys=$(copy_to_ehr_read_web_env_keys "$web_env")
  printf '%s\n' "$keys" | sed 's/^/web env key: /'
  cp -p -- "$web_env" "$workdir/src/web/.env.production"
  chmod 600 "$workdir/src/web/.env.production"
  (
    cd "$workdir/src/web"
    VITE_BUILD_SHA="$sha" corepack pnpm install --frozen-lockfile
    VITE_BUILD_SHA="$sha" corepack pnpm run build
  )
  node "$workdir/src/scripts/package-staging-web.mjs" \
    --dist "$workdir/src/web/dist" --output "$workdir/web-package"
  python3 -c 'import json,sys; assert json.load(open(sys.argv[1]))["commit"]==sys.argv[2]' \
    "$workdir/src/web/dist/version.json" "$sha" || copy_to_ehr_die "web version.json sha mismatch"
  release=$(copy_to_ehr_release_dir "$sha" "$STAGING_DATA_ROOT")
  archive="${workdir}/web-package/cosmabot-web-${sha}.tar.gz"
  [[ -s "$archive" ]] || copy_to_ehr_die "web archive was not created"
  copy_to_ehr_invoke_remote "api-build" "$(copy_to_ehr_render_api_build "$sha")"
  copy_to_ehr_ship_web "$archive" "${release}/cosmabot-web-${sha}.tar.gz"
  copy_to_ehr_invoke_remote "side-port" "$(copy_to_ehr_render_side_port "$sha")"
  if [[ "$cutover" -ne 1 ]]; then
    printf 'stop before cutover: live %s stays on %s/%s\n' \
      "$STAGING_PRIOR_RELEASE" "$LIVE_API_PORT" "$LIVE_EDGE_PORT"
    return 0
  fi
  copy_to_ehr_invoke_remote "cutover" "$(copy_to_ehr_render_cutover "$sha" "$prior" "$dump_file")"
}

copy_to_ehr_ship_web() {
  local archive="$1" remote_path="$2" size total index body
  size=$(wc -c <"$archive" | tr -d '[:space:]')
  total=$(((size + CHUNK_BYTES - 1) / CHUNK_BYTES))
  [[ "$total" -ge 1 ]] || copy_to_ehr_die "web archive is empty"
  index=0
  while [[ "$index" -lt "$total" ]]; do
    body=$(python3 - "$archive" "$remote_path" "$index" "$CHUNK_BYTES" "$STAGING_DATA_ROOT" <<'PY'
import base64, pathlib, sys
archive, dest, index, size, root = sys.argv[1:]
index, size = int(index), int(size)
if not dest.startswith(root + "/"):
    raise SystemExit(1)
data = pathlib.Path(archive).read_bytes()
chunk = data[index * size:(index + 1) * size]
payload = base64.b64encode(chunk).decode("ascii")
op = ": >" if index == 0 else "printf '' >>"
script = """exec /bin/bash <<'COPY_TO_EHR_BASH_BODY'
set -euo pipefail
set +x
umask 077
dest='%s'
case "$dest" in
  %s/*) ;;
  *) printf 'CHUNK_PATH_REFUSED\\n' >&2; exit 1 ;;
esac
mkdir -p "$(dirname "$dest")"
chmod 700 "$(dirname "$dest")"
%s "$dest"
base64 -d >> "$dest" <<'CHUNK'
%s
CHUNK
chmod 600 "$dest"
printf 'CHUNK_OK %%s\\n' '%s'
COPY_TO_EHR_BASH_BODY
""" % (dest, root, op, payload, index)
sys.stdout.write(script)
PY
)
    copy_to_ehr_invoke_remote "web-chunk-${index}" "$body"
    index=$((index + 1))
  done
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  copy_to_ehr_main "$@"
fi
