#!/usr/bin/env bash
# Copy to EHR staging deploy for John's Mac.
#
# Dry-run unless --execute. Refuses every target except the staging allowlist.
# Transport is `az vm run-command invoke` (RunShellScript). This is the Oct 31
# pointer-switch path. It does not use the section 9 compose/ACR/render.py path.
#
# The pre-cutover pg_dump stays on the staging VM, inside
# rg-cosmas-os-vm-staging-eus2-lab01. This script never downloads it, never
# uploads it, and never copies it to the operator Mac. A /subscriptions/*
# dump target is refused.
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
COPY_TO_EHR_READY_TRIES="${COPY_TO_EHR_READY_TRIES:-30}"
COPY_TO_EHR_CURL_MAX_TIME=5

copy_to_ehr_die() {
  printf 'copy-to-ehr staging deploy refused: %s\n' "$1" >&2
  exit 1
}

copy_to_ehr_usage() {
  cat <<EOF
Usage: $0 [--execute] [--cutover --expect-prior-sha SHA] [--teardown-trial]
          [--sha SHA] [--workdir PATH] [--web-env PATH] [--dump-target PATH]

Dry-run is the default. --execute builds the trial on side ports and stops
before cutover. --cutover also requires --expect-prior-sha. --dump-target is
a path on the staging VM. A storage account id is refused. --teardown-trial
removes a side-port trial and does not stop release-r10.
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

copy_to_ehr_validate_dump_target() {
  local target="$1"
  [[ -n "$target" ]] || { printf 'DUMP_TARGET_REFUSED\n' >&2; return 1; }
  if copy_to_ehr_explicitly_production "$target"; then
    printf 'DUMP_TARGET_REFUSED\n' >&2
    return 1
  fi
  case "$target" in
    /subscriptions/*) printf 'DUMP_TARGET_REFUSED\n' >&2; return 1 ;;
  esac
  case "$target" in
    *[!A-Za-z0-9._/-]*) printf 'DUMP_TARGET_REFUSED\n' >&2; return 1 ;;
  esac
  if copy_to_ehr_path_is_desktop_checkout "$target"; then
    printf 'DUMP_TARGET_REFUSED\n' >&2
    return 1
  fi
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
    *[!A-Za-z0-9._/-]*|*..*|*prod*|*PROD*) return 1 ;;
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

copy_to_ehr_parse_web_env() {
  local mode="$1" source="$2" dest="${3:-}"
  python3 - "$mode" "$source" "$dest" "$WEB_ENV_KEY_COUNT" <<'PY'
import os, re, stat, sys
mode, source, dest, expected = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
line_re = re.compile(r"^VITE_[A-Z0-9_]+=\S+$")
profiles = {
    "operational-beta-v1",
    "first-owner-staging-v1",
    "standalone-practice-v1",
    "independent-beta-v1",
}
drop_names = ("VITE_COSMANEURA_WEB_ORIGIN", "VITE_CAPTURE_UPLOAD_ORIGINS")

def refuse():
    sys.stderr.write("WEB_ENV_REFUSED\n")
    raise SystemExit(1)

def load(path):
    info = os.lstat(path)
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        refuse()
    if stat.S_IMODE(info.st_mode) & 0o077:
        refuse()
    blob = open(path, "rb").read()
    if b"\r" in blob or b"\x00" in blob:
        refuse()
    try:
        text = blob.decode("utf-8")
    except UnicodeError:
        refuse()
    rows = []
    seen = set()
    profile = ""
    for raw_line in text.split("\n"):
        if raw_line == "":
            continue
        if (
            not line_re.match(raw_line)
            or "#" in raw_line
            or '"' in raw_line
            or "'" in raw_line
            or " " in raw_line
            or "\t" in raw_line
            or raw_line.startswith("export ")
        ):
            refuse()
        key, value = raw_line.split("=", 1)
        if key in seen or value == "" or "$" in value or "\\" in value:
            refuse()
        seen.add(key)
        if key == "VITE_WORKSPACE_FEATURE_PROFILE":
            profile = value
        rows.append((key, raw_line))
    if len(rows) != expected or profile not in profiles:
        refuse()
    return rows, profile

if mode == "keys":
    rows, _profile = load(source)
    sys.stdout.write("".join("%s\n" % key for key, _line in rows))
    raise SystemExit(0)
if mode != "stage" or not dest or os.path.realpath(source) == os.path.realpath(dest):
    refuse()
rows, profile = load(source)
drop = set(drop_names) if profile in {"independent-beta-v1", "standalone-practice-v1"} else set()
flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
if hasattr(os, "O_NOFOLLOW"):
    flags |= os.O_NOFOLLOW
try:
    fd = os.open(dest, flags, 0o600)
except OSError:
    refuse()
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        for key, raw_line in rows:
            if key in drop:
                continue
            handle.write(raw_line + "\n")
    os.chmod(dest, 0o600)
    if drop:
        parent = os.path.dirname(dest)
        own = os.path.basename(dest)
        watched = (".env", ".env.local", ".env.production", ".env.production.local")
        for name in watched:
            if name == own:
                continue
            other = os.path.join(parent, name)
            if not os.path.lexists(other):
                continue
            info = os.lstat(other)
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                refuse()
            try:
                other_text = open(other, "r", encoding="utf-8").read()
            except UnicodeError:
                refuse()
            for raw_line in other_text.splitlines():
                stripped = raw_line.strip()
                if stripped == "" or stripped.startswith("#"):
                    continue
                if stripped.startswith("export "):
                    stripped = stripped[len("export "):].strip()
                key = stripped.split("=", 1)[0].strip()
                if key in drop_names:
                    refuse()
except SystemExit:
    try:
        os.unlink(dest)
    except OSError:
        pass
    raise
except BaseException:
    try:
        os.unlink(dest)
    except OSError:
        pass
    refuse()
PY
}

copy_to_ehr_read_web_env_keys() {
  copy_to_ehr_parse_web_env keys "$1"
}

copy_to_ehr_cleanup_web_env_copy() {
  if [[ -n "${COPY_TO_EHR_WEB_ENV_COPY:-}" ]]; then
    rm -f -- "$COPY_TO_EHR_WEB_ENV_COPY"
    unset COPY_TO_EHR_WEB_ENV_COPY
  fi
}

copy_to_ehr_local_exit() {
  local owned="${COPY_TO_EHR_OWNED_WORKDIR:-}"
  copy_to_ehr_cleanup_web_env_copy
  if [[ -n "$owned" ]]; then
    rm -rf -- "$owned"
  fi
}

copy_to_ehr_local_signal() {
  copy_to_ehr_local_exit
  exit 1
}

copy_to_ehr_stage_web_env() {
  local source="$1" dest="$2"
  [[ "$source" != "$dest" ]] || return 1
  umask 077
  copy_to_ehr_parse_web_env stage "$source" "$dest"
}

copy_to_ehr_run_web_build() {
  local sha="$1" name=""
  for name in $(compgen -v); do
    case "$name" in
      VITE_BUILD_SHA) ;;
      VITE_*) unset "$name" ;;
    esac
  done
  export VITE_BUILD_SHA="$sha"
  corepack pnpm run build
}

copy_to_ehr_clone_at_sha() {
  local dest="$1" sha="$2" head=""
  git clone --quiet "$PUBLIC_GIT_URL" "$dest" || return 1
  git -C "$dest" checkout --detach --quiet "$sha" || return 1
  head=$(git -C "$dest" rev-parse HEAD) || return 1
  [[ "$head" == "$sha" ]] || { printf 'SHA_MISMATCH\n' >&2; return 1; }
  [[ -z "$(git -C "$dest" status --porcelain)" ]] || { printf 'DIRTY_TREE\n' >&2; return 1; }
}

copy_to_ehr_database_facts() {
  local private_json="$1" dest="$2"
  python3 - "$private_json" "$dest" <<'PY'
import json, os, sys
from urllib.parse import urlparse
private_path, dest = sys.argv[1:]
try:
    raw = json.loads(open(private_path, "r", encoding="utf-8").read())["DATABASE_URL"]
    parsed = urlparse(raw.replace("postgresql+psycopg://", "postgresql://", 1))
    database = parsed.path.lstrip("/").split("?", 1)[0]
    if parsed.port != 54111 or not database.startswith("cosmabot_standalone_"):
        raise RuntimeError("refused")
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write("%s\n%s\n%s\n" % (parsed.port, database, raw))
except Exception:
    sys.stderr.write("LIVE_DATABASE_REFUSED\n")
    sys.exit(1)
PY
}

copy_to_ehr_write_migrate_env() {
  local private_json="$1" env_file="$2" facts="" port="" database="" raw="" short="" admin=""
  facts=$(mktemp /tmp/copy-to-ehr-db-facts.XXXXXX)
  chmod 600 "$facts"
  if ! copy_to_ehr_database_facts "$private_json" "$facts"; then
    rm -f -- "$facts"
    return 1
  fi
  port=$(sed -n '1p' "$facts")
  database=$(sed -n '2p' "$facts")
  raw=$(sed -n '3p' "$facts")
  rm -f -- "$facts"
  [[ "$port" == "54111" && "$database" == cosmabot_standalone_* && -n "$raw" ]] || {
    printf 'LIVE_DATABASE_REFUSED\n' >&2
    return 1
  }
  short=$(printf '%s' "$STAGING_INSTANCE_ID" | tr -d '-')
  short=$(printf '%s' "$short" | cut -c1-12)
  admin="postgresql+psycopg://cbpg_${short}@/${database}?host=/var/run/postgresql&port=54111"
  umask 077
  {
    printf 'STANDALONE_INSTANCE_ID=%s\n' "$STAGING_INSTANCE_ID"
    printf 'DATABASE_ADMIN_URL=%s\n' "$admin"
    printf 'DATABASE_URL=%s\n' "$raw"
  } >"$env_file"
  chmod 600 "$env_file"
}

copy_to_ehr_write_trial_migrate_env() {
  local url_file="$1" env_file="$2" url=""
  copy_to_ehr_trial_url_file_allowed "$url_file" || return 1
  url=$(tr -d '[:space:]' <"$url_file")
  umask 077
  {
    printf 'STANDALONE_INSTANCE_ID=%s\n' "$STAGING_INSTANCE_ID"
    printf 'DATABASE_ADMIN_URL=%s\n' "$url"
    printf 'DATABASE_URL=%s\n' "$url"
  } >"$env_file"
  chmod 600 "$env_file"
}

copy_to_ehr_run_migrate_py() {
  local env_file="$1" source_dir="$2" status=0
  chown 21000:21000 "$env_file" || return 1
  chmod 600 "$env_file" || return 1
  # The clone is created with umask 077. uid 21000 has to be able to read it.
  chmod -R a+rX "$source_dir" || return 1
  docker run --rm --network host --userns host --user 21000:21000 \
    --entrypoint /usr/local/bin/python \
    -v "$source_dir:/opt/copy-to-ehr-src:ro" \
    -v "$env_file:/run/copy-to-ehr-migrate.env:ro" \
    -v /var/run/postgresql:/var/run/postgresql \
    "${STAGING_API_REPOSITORY}:${COPY_TO_EHR_SHA}" \
    -c 'import os, runpy, sys
from pathlib import Path
sys.path.insert(0, "/app/src")
for line in Path("/run/copy-to-ehr-migrate.env").read_text().splitlines():
    if "=" not in line:
        continue
    key, value = line.split("=", 1)
    os.environ[key] = value
runpy.run_path("/opt/copy-to-ehr-src/infra/standalone/package/migrate.py", run_name="__main__")
sys.exit(0)' \
    || status=$?
  return "$status"
}

copy_to_ehr_wait_postgres() {
  local container="$1" port="$2" i=0 tries="${COPY_TO_EHR_READY_TRIES:-30}"
  while [[ "$i" -lt "$tries" ]]; do
    if docker exec -u postgres "$container" pg_isready -h 127.0.0.1 -p "$port" >/dev/null 2>&1; then
      printf 'POSTGRES_READY %s\n' "$port"
      return 0
    fi
    sleep 1
    i=$((i + 1))
  done
  printf 'POSTGRES_NOT_READY %s\n' "$port" >&2
  return 1
}

copy_to_ehr_wait_listener() {
  local api_port="$1" edge_port="$2" sha="$3" i=0 tries="${COPY_TO_EHR_READY_TRIES:-30}"
  while [[ "$i" -lt "$tries" ]]; do
    if copy_to_ehr_expect_ready "$api_port" && copy_to_ehr_expect_version "$edge_port" "$sha"; then
      return 0
    fi
    sleep 1
    i=$((i + 1))
  done
  printf 'LISTENER_NOT_READY %s %s\n' "$api_port" "$edge_port" >&2
  return 1
}

copy_to_ehr_edge_conf_source() {
  local root="$1"
  if [[ -f "$root/release-r10/edge-nginx.conf" ]]; then
    printf '%s\n' "$root/release-r10/edge-nginx.conf"
    return 0
  fi
  if [[ -f "$root/release-r6r1/edge-nginx.conf" ]]; then
    printf '%s\n' "$root/release-r6r1/edge-nginx.conf"
    return 0
  fi
  return 1
}

copy_to_ehr_write_trial_edge() {
  local source="$1" dest="$2"
  python3 - "$source" "$dest" <<'PY'
from pathlib import Path
import os, sys
source, dest = sys.argv[1:]
text = Path(source).read_text()
rewritten = text.replace("172.30.241.1:54112", "127.0.0.1:54122").replace("127.0.0.1:54110", "127.0.0.1:54120")
if "54110" in rewritten or "54112" in rewritten:
    sys.stderr.write("EDGE_PORT_REWRITE_FAILED\n")
    sys.exit(1)
if "127.0.0.1:54120" not in rewritten or "127.0.0.1:54122" not in rewritten:
    sys.stderr.write("EDGE_PORT_REWRITE_FAILED\n")
    sys.exit(1)
Path(dest).write_text(rewritten)
os.chmod(dest, 0o644)
PY
}

copy_to_ehr_extract_web() {
  local archive="$1" dest="$2" sha="$3"
  mkdir -p -- "$dest"
  tar -xzf "$archive" -C "$dest"
  chmod -R a+rX "$dest"
  python3 -c 'import json,sys; assert json.load(open(sys.argv[1]))["commit"]==sys.argv[2]' \
    "$dest/version.json" "$sha"
}

copy_to_ehr_remove_trial_nft() {
  local chain="CB21000_${STAGING_SHORT}" handle=""
  handle=$(nft -a list chain ip filter "$chain" 2>/dev/null | awk '/copy-ehr-trial/ {print $NF; exit}') || true
  if [[ -z "$handle" ]]; then
    return 0
  fi
  case "$handle" in
    [0-9]*) ;;
    *) printf 'NFT_TRIAL_RULE_FAILED\n' >&2; return 1 ;;
  esac
  nft delete rule ip filter "$chain" handle "$handle" || {
    printf 'NFT_TRIAL_RULE_FAILED\n' >&2
    return 1
  }
}

copy_to_ehr_docker_api() {
  local name="$1"
  shift
  docker run -d --name "$name" \
    --network host --userns host --user 21000:21000 --read-only \
    --security-opt no-new-privileges:true --restart=on-failure:3 \
    --cap-drop ALL --pids-limit 128 --memory 1536m --cpus 1.25 --dns 127.0.0.53 \
    "$@"
}

copy_to_ehr_docker_edge() {
  local name="$1"
  shift
  docker run -d --name "$name" \
    --network host --user 21002:21002 --read-only \
    --security-opt no-new-privileges:true --restart=on-failure:3 \
    --cap-drop ALL --tmpfs /tmp:rw,noexec,nosuid,size=32m \
    "$@"
}

copy_to_ehr_pointer_file() {
  printf '%s\n' "${COPY_TO_EHR_POINTER_FILE:-/etc/cosmabot/active-release}"
}

copy_to_ehr_write_pointer() {
  local release_dir="$1" token="$2" dest="" tmp="" dir=""
  dest=$(copy_to_ehr_pointer_file)
  dir=$(dirname -- "$dest")
  mkdir -p -- "$dir"
  umask 022
  tmp=$(mktemp "$dir/active-release.XXXXXX")
  if ! printf 'RELEASE_DIR=%s\n' "$release_dir" >"$tmp"; then
    rm -f -- "$tmp"
    return 1
  fi
  chmod 644 "$tmp" || { rm -f -- "$tmp"; return 1; }
  mv -f "$tmp" "$dest"
  printf '%s\n' "$token"
}

copy_to_ehr_marker_file() {
  if [[ -n "${COPY_TO_EHR_MARKER_FILE:-}" ]]; then
    printf '%s\n' "$COPY_TO_EHR_MARKER_FILE"
    return 0
  fi
  printf '%s/copy-to-ehr-cutover.in-progress\n' "$STAGING_DATA_ROOT"
}

copy_to_ehr_refuse_cutover_marker() {
  local marker
  marker=$(copy_to_ehr_marker_file)
  if [[ -f "$marker" ]]; then
    printf 'CUTOVER_IN_PROGRESS\n' >&2
    return 1
  fi
}

copy_to_ehr_write_cutover_marker() {
  local marker
  marker=$(copy_to_ehr_marker_file)
  umask 022
  printf 'in-progress\n' >"$marker"
}

copy_to_ehr_clear_cutover_marker() {
  rm -f -- "$(copy_to_ehr_marker_file)"
}

copy_to_ehr_sha256_file() {
  local file="$1" hash=""
  if command -v sha256sum >/dev/null 2>&1; then
    hash=$(sha256sum "$file" | awk '{print $1}')
  else
    hash=$(shasum -a 256 "$file" | awk '{print $1}')
  fi
  case "$hash" in
    [0-9a-f]*) ;;
    *) return 1 ;;
  esac
  [[ ${#hash} -eq 64 ]] || return 1
  printf '%s\n' "$hash"
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

copy_to_ehr_restore_target_ok() {
  case "$1" in
    cosmabot_copy_ehr_scratch) return 0 ;;
    cosmabot_standalone_[a-z0-9_]*_copy_ehr_in) return 0 ;;
    cosmabot_standalone_[a-z0-9_]*_copy_ehr_old) return 0 ;;
  esac
  return 1
}

copy_to_ehr_live_db_name_ok() {
  case "$1" in
    cosmabot_standalone_[a-z0-9_]*) ;;
    *) return 1 ;;
  esac
  case "$1" in
    *_copy_ehr_in|*_copy_ehr_old|cosmabot_copy_ehr_scratch|cosmabot_copy_ehr_trial) return 1 ;;
  esac
  return 0
}

copy_to_ehr_pg_restore() {
  local database="$1" dump="$2" status=0
  copy_to_ehr_restore_target_ok "$database" || return 1
  docker exec -i -u postgres "$COPY_TO_EHR_PG_CONTAINER" \
    pg_restore --single-transaction --exit-on-error --no-password --dbname "$database" \
    <"$dump" >/dev/null || status=$?
  return "$status"
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
  copy_to_ehr_restore_target_ok "$1" || return 1
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
  : >"${dump}.counts"
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
    printf '%s %s\n' "$table" "$live_count" >>"${dump}.counts"
    printf 'COUNT %s=%s\n' "$table" "$live_count"
  done
  chmod 600 "${dump}.counts" || true
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
  local env_file="" clone="" status=0
  COPY_TO_EHR_DB_TOUCHED=0
  umask 077
  env_file=$(mktemp /tmp/copy-to-ehr-migrate-env.XXXXXX) || return 1
  chmod 600 "$env_file" || { rm -f -- "$env_file"; return 1; }
  if ! copy_to_ehr_write_migrate_env \
    "$STAGING_DATA_ROOT/release-r5r1/config/api-private.json" "$env_file"; then
    rm -f -- "$env_file"
    return 1
  fi
  clone=$(mktemp -d /var/tmp/copy-to-ehr-migrate-src.XXXXXX) || {
    rm -f -- "$env_file"
    return 1
  }
  chmod 700 "$clone" || { rm -rf -- "$clone"; rm -f -- "$env_file"; return 1; }
  if ! copy_to_ehr_clone_at_sha "$clone/src" "$COPY_TO_EHR_SHA"; then
    rm -rf -- "$clone"
    rm -f -- "$env_file"
    return 1
  fi
  COPY_TO_EHR_DB_TOUCHED=1
  copy_to_ehr_run_migrate_py "$env_file" "$clone/src" || status=$?
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
  copy_to_ehr_write_pointer "${STAGING_DATA_ROOT}/${STAGING_PRIOR_RELEASE}" "POINTER_R10"
}

copy_to_ehr_write_new_pointer() {
  copy_to_ehr_write_pointer "$COPY_TO_EHR_RELEASE" "POINTER_NEW"
}

copy_to_ehr_database_matches_dump() {
  local database="$1" counts="$2" version="" table="" sql="" count="" expected=""
  version=$(copy_to_ehr_psql "$database" "SELECT version_num FROM public.alembic_version") || return 1
  [[ "$version" == "$STAGING_LIVE_SCHEMA" ]] || return 1
  for table in alembic_version audit_events practice_owner_reservations; do
    case "$table" in
      alembic_version) sql="SELECT count(*) FROM public.alembic_version" ;;
      audit_events) sql="SELECT count(*) FROM public.audit_events" ;;
      practice_owner_reservations) sql="SELECT count(*) FROM public.practice_owner_reservations" ;;
      *) return 1 ;;
    esac
    count=$(copy_to_ehr_psql "$database" "$sql") || return 1
    expected=$(awk -v table="$table" '$1 == table {print $2; exit}' "$counts")
    [[ "$count" == "$expected" && "$count" =~ ^[0-9]+$ ]] || return 1
  done
  return 0
}

copy_to_ehr_terminate_connections() {
  local database="$1"
  docker exec -u postgres "$COPY_TO_EHR_PG_CONTAINER" \
    psql -d postgres -v ON_ERROR_STOP=1 -c \
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${database}' AND pid <> pg_backend_pid();" \
    >/dev/null
}

copy_to_ehr_rename_database() {
  local source="$1" dest="$2"
  docker exec -u postgres "$COPY_TO_EHR_PG_CONTAINER" \
    psql -d postgres -v ON_ERROR_STOP=1 -c \
    "ALTER DATABASE \"${source}\" RENAME TO \"${dest}\";" >/dev/null
}

copy_to_ehr_restore_dump_over_live() {
  local dump="$1" live_db="$2" incoming="" old="" owner="" encoding=""
  copy_to_ehr_dump_file_on_staging_vm "$dump" "$STAGING_DATA_ROOT" || return 1
  [[ -s "$dump" && -s "${dump}.counts" ]] || return 1
  copy_to_ehr_live_db_name_ok "$live_db" || return 1
  if [[ "${COPY_TO_EHR_DB_TOUCHED:-0}" != "1" ]]; then
    printf 'RESTORE_SKIPPED_UNTOUCHED\n'
    return 0
  fi
  if copy_to_ehr_database_matches_dump "$live_db" "${dump}.counts"; then
    printf 'RESTORE_SKIPPED_UNTOUCHED\n'
    return 0
  fi
  owner=$(copy_to_ehr_psql postgres "SELECT pg_catalog.pg_get_userbyid(datdba) FROM pg_catalog.pg_database WHERE datname = '${live_db}'") || {
    printf 'PG_RESTORE_FAILED\n' >&2
    return 1
  }
  encoding=$(copy_to_ehr_psql postgres "SELECT pg_catalog.pg_encoding_to_char(encoding) FROM pg_catalog.pg_database WHERE datname = '${live_db}'") || {
    printf 'PG_RESTORE_FAILED\n' >&2
    return 1
  }
  [[ "$owner" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || { printf 'PG_RESTORE_FAILED\n' >&2; return 1; }
  [[ "$encoding" =~ ^[A-Za-z0-9_]+$ ]] || { printf 'PG_RESTORE_FAILED\n' >&2; return 1; }
  incoming="${live_db}_copy_ehr_in"
  old="${live_db}_copy_ehr_old"
  copy_to_ehr_restore_target_ok "$incoming" || { printf 'PG_RESTORE_FAILED\n' >&2; return 1; }
  copy_to_ehr_restore_target_ok "$old" || { printf 'PG_RESTORE_FAILED\n' >&2; return 1; }
  if ! copy_to_ehr_dropdb "$incoming" || ! copy_to_ehr_dropdb "$old"; then
    printf 'PG_RESTORE_FAILED\n' >&2
    return 1
  fi
  if ! docker exec -u postgres "$COPY_TO_EHR_PG_CONTAINER" \
    createdb --no-password --owner "$owner" --encoding "$encoding" --template template0 "$incoming" >/dev/null; then
    printf 'PG_RESTORE_FAILED\n' >&2
    return 1
  fi
  if ! copy_to_ehr_pg_restore "$incoming" "$dump"; then
    copy_to_ehr_dropdb "$incoming" || true
    printf 'PG_RESTORE_FAILED\n' >&2
    return 1
  fi
  if ! copy_to_ehr_database_matches_dump "$incoming" "${dump}.counts"; then
    copy_to_ehr_dropdb "$incoming" || true
    printf 'PG_RESTORE_FAILED\n' >&2
    return 1
  fi
  if ! copy_to_ehr_terminate_connections "$live_db"; then
    copy_to_ehr_dropdb "$incoming" || true
    printf 'PG_RESTORE_FAILED\n' >&2
    return 1
  fi
  if ! copy_to_ehr_rename_database "$live_db" "$old"; then
    copy_to_ehr_dropdb "$incoming" || true
    printf 'PG_RESTORE_FAILED\n' >&2
    return 1
  fi
  if ! copy_to_ehr_rename_database "$incoming" "$live_db"; then
    copy_to_ehr_rename_database "$old" "$live_db" || true
    copy_to_ehr_dropdb "$incoming" || true
    printf 'PG_RESTORE_FAILED\n' >&2
    return 1
  fi
  copy_to_ehr_terminate_connections "$old" || true
  if ! copy_to_ehr_dropdb "$old"; then
    printf 'PG_RESTORE_FAILED\n' >&2
    return 1
  fi
  printf 'DUMP_RESTORED\n'
}

copy_to_ehr_remove_new_listeners() {
  docker rm -f \
    "cosmabot-standalone-copyehr-api-${STAGING_SHORT}" \
    "cosmabot-standalone-copyehr-edge-${STAGING_SHORT}" >/dev/null 2>&1 || true
}

copy_to_ehr_remove_trial() {
  local status=0
  copy_to_ehr_remove_trial_nft || status=1
  docker rm -f \
    "cosmabot-standalone-copyehr-trial-pg-${STAGING_SHORT}" \
    "cosmabot-standalone-copyehr-trial-api-${STAGING_SHORT}" \
    "cosmabot-standalone-copyehr-trial-edge-${STAGING_SHORT}" >/dev/null 2>&1 || true
  return "$status"
}

copy_to_ehr_expect_ready() {
  local port="$1" body
  body=$(curl -sf --max-time "$COPY_TO_EHR_CURL_MAX_TIME" "http://127.0.0.1:${port}/ready") || return 1
  printf '%s' "$body" | grep -F '"status":"ready"' >/dev/null || return 1
  printf '%s' "$body" | grep -F 'standalone_clerk_synthetic' >/dev/null || return 1
  printf 'READY_OK %s\n' "$port"
}

copy_to_ehr_expect_version() {
  local port="$1" sha="$2" body commit
  body=$(curl -sf --max-time "$COPY_TO_EHR_CURL_MAX_TIME" -H "Host: ${STAGING_WEB_HOST}" "http://127.0.0.1:${port}/version.json") || return 1
  commit=$(printf '%s' "$body" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("commit",""))')
  [[ "$commit" == "$sha" ]] || return 1
  printf 'VERSION_OK\n'
}

copy_to_ehr_expect_feature() {
  local web_dir="$1" html_port="$2"
  grep -R -F -q -- 'Copy to EHR' "$web_dir" || return 1
  curl -sf --max-time "$COPY_TO_EHR_CURL_MAX_TIME" -H "Host: ${STAGING_WEB_HOST}" "http://127.0.0.1:${html_port}/" | grep -F -q 'id="root"' || return 1
  printf 'COPY_TO_EHR_PRESENT\n'
}

copy_to_ehr_live_still_serving() {
  local active
  active=$(tr -d '[:space:]' <"$(copy_to_ehr_pointer_file)")
  case "$active" in
    *"RELEASE_DIR=${STAGING_DATA_ROOT}/${STAGING_PRIOR_RELEASE}") ;;
    *) printf 'LIVE_POINTER_CHANGED\n' >&2; return 1 ;;
  esac
  [[ "$(docker inspect --format '{{.State.Running}}' "cosmabot-standalone-r10-api-${STAGING_SHORT}")" == "true" ]] || return 1
  [[ "$(docker inspect --format '{{.State.Running}}' "cosmabot-standalone-r10-edge-${STAGING_SHORT}")" == "true" ]] || return 1
}

copy_to_ehr_start_new_listeners() {
  local edge_conf=""
  edge_conf=$(copy_to_ehr_edge_conf_source "$STAGING_DATA_ROOT") || return 1
  copy_to_ehr_docker_api "cosmabot-standalone-copyehr-api-${STAGING_SHORT}" \
    --entrypoint /usr/local/bin/python \
    -v "${STAGING_DATA_ROOT}/app:${STAGING_DATA_ROOT}/app" \
    -v "${COPY_TO_EHR_RELEASE}/config/api-public.json:/run/cosmabot-standalone/api-public.json:ro" \
    -v "${STAGING_DATA_ROOT}/release-r5r1/config/api-private.json:/run/cosmabot-standalone/api-private.json:ro" \
    "${STAGING_API_REPOSITORY}:${COPY_TO_EHR_SHA}" \
    -I /app/standalone-entrypoint.py "$LIVE_API_PORT" >/dev/null || return 1
  copy_to_ehr_docker_edge "cosmabot-standalone-copyehr-edge-${STAGING_SHORT}" \
    -v "${edge_conf}:/run/cosmabot-edge/nginx.conf:ro" \
    -v "${COPY_TO_EHR_RELEASE}/web:/usr/share/nginx/html:ro" \
    --entrypoint /usr/sbin/nginx \
    "$STAGING_EDGE_IMAGE" \
    -c /run/cosmabot-edge/nginx.conf -g 'daemon off;' >/dev/null || return 1
}

copy_to_ehr_ready_for_pointer() {
  copy_to_ehr_wait_listener "$LIVE_API_PORT" "$LIVE_EDGE_PORT" "$COPY_TO_EHR_SHA" || return 1
  copy_to_ehr_expect_feature "${COPY_TO_EHR_RELEASE}/web" "$LIVE_EDGE_PORT"
}

copy_to_ehr_post_switch_checks() {
  local active
  copy_to_ehr_ready_for_pointer || return 1
  active=$(tr -d '[:space:]' <"$(copy_to_ehr_pointer_file)")
  case "$active" in
    *"RELEASE_DIR=${COPY_TO_EHR_RELEASE}") ;;
    *) return 1 ;;
  esac
  printf 'POST_SWITCH_OK\n'
}

copy_to_ehr_read_served_commit() {
  local port="$1" body commit
  body=$(curl -sf --max-time "$COPY_TO_EHR_CURL_MAX_TIME" -H "Host: ${STAGING_WEB_HOST}" "http://127.0.0.1:${port}/version.json") || return 1
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
  trap - ERR EXIT INT TERM HUP
}

copy_to_ehr_cutover_trap_rollback() {
  local status=$?
  copy_to_ehr_disarm_cutover_trap
  if ! copy_to_ehr_rollback_to_r10 "$COPY_TO_EHR_TRAP_DUMP" "$COPY_TO_EHR_TRAP_DB"; then
    exit 1
  fi
  copy_to_ehr_clear_cutover_marker
  printf 'CUTOVER_ROLLBACK\n' >&2
  if [[ "$status" -eq 0 ]]; then
    status=1
  fi
  exit "$status"
}

copy_to_ehr_arm_cutover_trap() {
  COPY_TO_EHR_TRAP_DUMP="$1"
  COPY_TO_EHR_TRAP_DB="$2"
  copy_to_ehr_write_cutover_marker || return 1
  trap copy_to_ehr_cutover_trap_rollback ERR EXIT INT TERM HUP
}

copy_to_ehr_rollback_verify_prior() {
  local i=0 tries="${COPY_TO_EHR_READY_TRIES:-30}" ready_body="" ready_code="" version_commit=""
  while [[ "$i" -lt "$tries" ]]; do
    ready_body=$(mktemp /tmp/copy-to-ehr-ready.XXXXXX)
    ready_code=$(curl -s --max-time "$COPY_TO_EHR_CURL_MAX_TIME" -o "$ready_body" -w '%{http_code}' "http://127.0.0.1:${LIVE_API_PORT}/ready" || true)
    if [[ "$ready_code" == "200" ]] && grep -F -q '"status":"ready"' "$ready_body"; then
      rm -f -- "$ready_body"
      version_commit=$(copy_to_ehr_read_served_commit "$LIVE_EDGE_PORT" || true)
      if [[ -n "$version_commit" ]]; then
        if [[ -z "${COPY_TO_EHR_SERVED_PRIOR:-}" || "$version_commit" == "$COPY_TO_EHR_SERVED_PRIOR" ]]; then
          if copy_to_ehr_prior_matches "${COPY_TO_EHR_PRIOR:-}" "$version_commit"; then
            printf 'ROLLBACK_READY\n'
            return 0
          fi
        fi
      fi
    else
      rm -f -- "$ready_body"
    fi
    sleep 1
    i=$((i + 1))
  done
  printf 'LISTENER_NOT_READY %s %s\n' "$LIVE_API_PORT" "$LIVE_EDGE_PORT" >&2
  return 1
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
  copy_to_ehr_clear_cutover_marker
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
  copy_to_ehr_arm_cutover_trap "$dump" "$live_db" || return 1
  if ! copy_to_ehr_stop_live_listeners; then
    copy_to_ehr_disarm_cutover_trap
    if ! copy_to_ehr_start_prior_listeners || ! copy_to_ehr_rollback_verify_prior; then
      printf 'CUTOVER_ROLLBACK_FAILED\n' >&2
      return 1
    fi
    copy_to_ehr_clear_cutover_marker
    printf 'CUTOVER_ABORT_STOP\n' >&2
    return 1
  fi
  if ! copy_to_ehr_restore_gate "$root" "$dump" "$live_db"; then
    copy_to_ehr_disarm_cutover_trap
    if ! copy_to_ehr_start_prior_listeners || ! copy_to_ehr_rollback_verify_prior; then
      printf 'CUTOVER_ROLLBACK_FAILED\n' >&2
      return 1
    fi
    copy_to_ehr_clear_cutover_marker
    printf 'CUTOVER_ABORT_RESTORE_CHECK\n' >&2
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
  copy_to_ehr_clear_cutover_marker
  if ! copy_to_ehr_remove_trial; then
    printf 'TRIAL_TEARDOWN_FAILED\n' >&2
    return 1
  fi
  printf 'CUTOVER_OK\n'
}

copy_to_ehr_cutover_main() {
  local live_port="" live_db="" meta_file image_ref="" source_file observed=""
  local active=""
  set +x
  umask 077
  copy_to_ehr_refuse_cutover_marker || return 1
  active=$(tr -d '[:space:]' <"$(copy_to_ehr_pointer_file)")
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
  if ! copy_to_ehr_database_facts "${STAGING_DATA_ROOT}/release-r5r1/config/api-private.json" "$meta_file"; then
    rm -f -- "$meta_file"
    return 1
  fi
  live_port=$(sed -n '1p' "$meta_file")
  live_db=$(sed -n '2p' "$meta_file")
  rm -f -- "$meta_file"
  [[ "$live_port" == "54111" ]] || { printf 'LIVE_DATABASE_PORT_REFUSED\n' >&2; return 1; }
  COPY_TO_EHR_RELEASE=$(copy_to_ehr_release_dir "$COPY_TO_EHR_SHA" "$STAGING_DATA_ROOT")
  copy_to_ehr_cutover_sequence "$STAGING_DATA_ROOT" "$COPY_TO_EHR_DUMP" "$live_db"
}

copy_to_ehr_api_build_main() {
  local free_kib=""
  set +x
  umask 077
  copy_to_ehr_refuse_cutover_marker || return 1
  free_kib=$(df -Pk /var/tmp | awk 'NR==2 {print $4}')
  if [[ -z "$free_kib" || "$free_kib" -lt "$MIN_FREE_KIB" ]]; then
    printf 'DISK_REFUSED\n' >&2
    return 1
  fi
  COPY_TO_EHR_API_BUILD_DIR=$(mktemp -d /var/tmp/copy-to-ehr-api.XXXXXX)
  chmod 700 "$COPY_TO_EHR_API_BUILD_DIR"
  trap 'rm -rf -- "$COPY_TO_EHR_API_BUILD_DIR"' EXIT
  case "$COPY_TO_EHR_API_BUILD_DIR" in
    */Desktop/cosmaneura-os|*/Desktop/cosmaneura-os/*)
      printf 'DESKTOP_PATH_REFUSED\n' >&2
      return 1
      ;;
  esac
  if ! copy_to_ehr_clone_at_sha "$COPY_TO_EHR_API_BUILD_DIR/src" "$COPY_TO_EHR_SHA"; then
    return 1
  fi
  python3 "$COPY_TO_EHR_API_BUILD_DIR/src/infra/standalone/package/prepare_api_recipe.py" \
    --source "$COPY_TO_EHR_API_BUILD_DIR/src" --output "$COPY_TO_EHR_API_BUILD_DIR/recipe"
  cp "$COPY_TO_EHR_API_BUILD_DIR/recipe/Dockerfile" "$COPY_TO_EHR_API_BUILD_DIR/src/Dockerfile.copy-to-ehr"
  cp "$COPY_TO_EHR_API_BUILD_DIR/recipe/Dockerfile.dockerignore" "$COPY_TO_EHR_API_BUILD_DIR/src/Dockerfile.copy-to-ehr.dockerignore"
  if ! docker build --platform linux/amd64 \
    --file "$COPY_TO_EHR_API_BUILD_DIR/src/Dockerfile.copy-to-ehr" \
    --build-arg "SOURCE_COMMIT=${COPY_TO_EHR_SHA}" \
    --tag "${STAGING_API_REPOSITORY}:${COPY_TO_EHR_SHA}" \
    "$COPY_TO_EHR_API_BUILD_DIR/src" >"$COPY_TO_EHR_API_BUILD_DIR/build.log" 2>&1; then
    printf 'API_BUILD_FAILED\n' >&2
    return 1
  fi
  docker image inspect --format '{{.Id}}' "${STAGING_API_REPOSITORY}:${COPY_TO_EHR_SHA}"
  printf 'API_IMAGE_OK\n'
}

copy_to_ehr_side_port_main() {
  local release="" archive="" url_file="" pass_file="" live_pg="" image="" edge_src=""
  local public_src="" private_src="" env_file="" clone="" migrate_status=0
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
  mkdir -p -- "$release/config"
  chmod 700 "$release" "$release/config"
  copy_to_ehr_extract_web "$archive" "$release/web" "$COPY_TO_EHR_SHA" || return 1
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
    postgres -c listen_addresses=127.0.0.1 -c port=54130 >/dev/null \
    || { copy_to_ehr_remove_trial; return 1; }
  if ! copy_to_ehr_wait_postgres "cosmabot-standalone-copyehr-trial-pg-${STAGING_SHORT}" "$TRIAL_POSTGRES_PORT"; then
    copy_to_ehr_remove_trial
    return 1
  fi
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
  edge_src=$(copy_to_ehr_edge_conf_source "$STAGING_DATA_ROOT") || {
    copy_to_ehr_remove_trial
    return 1
  }
  copy_to_ehr_write_trial_edge "$edge_src" "${release}/edge-nginx.trial.conf" || {
    copy_to_ehr_remove_trial
    return 1
  }
  nft add rule ip filter "CB21000_${STAGING_SHORT}" tcp dport 54120 accept comment "copy-ehr-trial" \
    || { printf 'NFT_TRIAL_RULE_FAILED\n' >&2; copy_to_ehr_remove_trial; return 1; }
  env_file=$(mktemp /tmp/copy-to-ehr-trial-migrate-env.XXXXXX)
  chmod 600 "$env_file"
  clone=$(mktemp -d /var/tmp/copy-to-ehr-trial-migrate.XXXXXX)
  chmod 700 "$clone"
  migrate_status=0
  if ! copy_to_ehr_write_trial_migrate_env "$url_file" "$env_file"; then
    migrate_status=1
  elif ! copy_to_ehr_clone_at_sha "$clone/src" "$COPY_TO_EHR_SHA"; then
    migrate_status=1
  elif ! copy_to_ehr_run_migrate_py "$env_file" "$clone/src"; then
    migrate_status=1
    printf 'MIGRATE_FAILED\n' >&2
  fi
  rm -f -- "$env_file"
  rm -rf -- "$clone"
  if [[ "$migrate_status" -ne 0 ]]; then
    copy_to_ehr_remove_trial
    return 1
  fi
  copy_to_ehr_docker_api "cosmabot-standalone-copyehr-trial-api-${STAGING_SHORT}" \
    --entrypoint /usr/local/bin/python \
    -v "${STAGING_DATA_ROOT}/app:${STAGING_DATA_ROOT}/app" \
    -v "${release}/config/api-public.json:/run/cosmabot-standalone/api-public.json:ro" \
    -v "${release}/config/api-private.json:/run/cosmabot-standalone/api-private.json:ro" \
    "${STAGING_API_REPOSITORY}:${COPY_TO_EHR_SHA}" \
    -I /app/standalone-entrypoint.py "$TRIAL_API_PORT" >/dev/null \
    || { copy_to_ehr_remove_trial; return 1; }
  copy_to_ehr_docker_edge "cosmabot-standalone-copyehr-trial-edge-${STAGING_SHORT}" \
    -v "${release}/edge-nginx.trial.conf:/run/cosmabot-edge/nginx.conf:ro" \
    -v "${release}/web:/usr/share/nginx/html:ro" \
    --entrypoint /usr/sbin/nginx \
    "$STAGING_EDGE_IMAGE" \
    -c /run/cosmabot-edge/nginx.conf -g 'daemon off;' >/dev/null \
    || { copy_to_ehr_remove_trial; return 1; }
  copy_to_ehr_wait_listener "$TRIAL_API_PORT" "$TRIAL_EDGE_PORT" "$COPY_TO_EHR_SHA" \
    || { copy_to_ehr_remove_trial; return 1; }
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
COPY_TO_EHR_READY_TRIES=90
COPY_TO_EHR_CURL_MAX_TIME=$COPY_TO_EHR_CURL_MAX_TIME
COPY_TO_EHR_MARKER_FILE='$STAGING_DATA_ROOT/copy-to-ehr-cutover.in-progress'
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
$(declare -f \
    copy_to_ehr_marker_file \
    copy_to_ehr_refuse_cutover_marker \
    copy_to_ehr_clone_at_sha \
    copy_to_ehr_api_build_main)
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
    copy_to_ehr_remove_trial_nft \
    copy_to_ehr_remove_trial \
    copy_to_ehr_expect_ready \
    copy_to_ehr_expect_version \
    copy_to_ehr_expect_feature \
    copy_to_ehr_wait_postgres \
    copy_to_ehr_wait_listener \
    copy_to_ehr_edge_conf_source \
    copy_to_ehr_write_trial_edge \
    copy_to_ehr_extract_web \
    copy_to_ehr_write_trial_migrate_env \
    copy_to_ehr_clone_at_sha \
    copy_to_ehr_run_migrate_py \
    copy_to_ehr_docker_api \
    copy_to_ehr_docker_edge \
    copy_to_ehr_pointer_file \
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
    copy_to_ehr_marker_file \
    copy_to_ehr_refuse_cutover_marker \
    copy_to_ehr_write_cutover_marker \
    copy_to_ehr_clear_cutover_marker \
    copy_to_ehr_disarm_cutover_trap \
    copy_to_ehr_cutover_trap_rollback \
    copy_to_ehr_arm_cutover_trap \
    copy_to_ehr_rollback_verify_prior \
    copy_to_ehr_fail_rollback \
    copy_to_ehr_release_dir \
    copy_to_ehr_dump_file_on_staging_vm \
    copy_to_ehr_pg_dump \
    copy_to_ehr_restore_target_ok \
    copy_to_ehr_live_db_name_ok \
    copy_to_ehr_pg_restore \
    copy_to_ehr_psql \
    copy_to_ehr_createdb \
    copy_to_ehr_dropdb \
    copy_to_ehr_restore_gate \
    copy_to_ehr_database_facts \
    copy_to_ehr_write_migrate_env \
    copy_to_ehr_clone_at_sha \
    copy_to_ehr_run_migrate_py \
    copy_to_ehr_run_live_migrate \
    copy_to_ehr_migrate_live \
    copy_to_ehr_stop_live_listeners \
    copy_to_ehr_start_prior_listeners \
    copy_to_ehr_pointer_file \
    copy_to_ehr_write_pointer \
    copy_to_ehr_write_prior_pointer \
    copy_to_ehr_write_new_pointer \
    copy_to_ehr_database_matches_dump \
    copy_to_ehr_terminate_connections \
    copy_to_ehr_rename_database \
    copy_to_ehr_restore_dump_over_live \
    copy_to_ehr_remove_new_listeners \
    copy_to_ehr_remove_trial_nft \
    copy_to_ehr_remove_trial \
    copy_to_ehr_expect_ready \
    copy_to_ehr_expect_version \
    copy_to_ehr_expect_feature \
    copy_to_ehr_wait_listener \
    copy_to_ehr_edge_conf_source \
    copy_to_ehr_docker_api \
    copy_to_ehr_docker_edge \
    copy_to_ehr_start_new_listeners \
    copy_to_ehr_ready_for_pointer \
    copy_to_ehr_post_switch_checks \
    copy_to_ehr_rollback_to_r10 \
    copy_to_ehr_cutover_sequence \
    copy_to_ehr_cutover_main)
copy_to_ehr_cutover_main"
  copy_to_ehr_wrap_remote "$body"
}

copy_to_ehr_teardown_main() {
  set +x
  copy_to_ehr_remove_trial || return 1
  printf 'TEARDOWN_OK\n'
}

copy_to_ehr_render_teardown() {
  local body
  body=$(copy_to_ehr_remote_prelude "$DEFAULT_SOURCE_SHA" "" "")
  body="${body}
$(declare -f \
    copy_to_ehr_remove_trial_nft \
    copy_to_ehr_remove_trial \
    copy_to_ehr_teardown_main)
copy_to_ehr_teardown_main"
  copy_to_ehr_wrap_remote "$body"
}

copy_to_ehr_require_sentinel() {
  local name="$1" output="$2" index=""
  case "$name" in
    api-build) grep -qx 'API_IMAGE_OK' <<<"$output" ;;
    side-port) grep -qx 'SIDE_PORT_OK' <<<"$output" ;;
    cutover) grep -qx 'CUTOVER_OK' <<<"$output" ;;
    teardown-trial) grep -qx 'TEARDOWN_OK' <<<"$output" ;;
    web-chunk-*)
      index="${name#web-chunk-}"
      grep -qx "CHUNK_OK ${index}" <<<"$output"
      ;;
    web-verify) grep -qx "ARCHIVE_SHA256 ${COPY_TO_EHR_ARCHIVE_SHA256}" <<<"$output" ;;
    *) return 1 ;;
  esac
}

copy_to_ehr_invoke_remote() {
  local name="$1" body="$2" file result filtered=""
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
  filtered=$(printf '%s' "$result" | copy_to_ehr_filter_run_output) || copy_to_ehr_die "run-command ${name} output refused"
  printf '%s\n' "$filtered"
  if ! copy_to_ehr_require_sentinel "$name" "$filtered"; then
    copy_to_ehr_die "run-command ${name} did not report success"
  fi
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
    "API_BUILD_FAILED", "WEB_ARCHIVE_MISSING", "LIVE_POINTER_CHANGED",
    "PG_DUMP_FAILED", "SHA_MISMATCH", "DIRTY_TREE", "ACTIVE_RELEASE_NOT_R10",
    "NFT_TRIAL_RULE_FAILED", "MIGRATE_FAILED", "PG_RESTORE_FAILED",
    "STORAGE_UPLOAD_FAILED", "EDGE_PORT_REWRITE_FAILED", "CUTOVER_IN_PROGRESS",
    "ARCHIVE_SHA256", "ARCHIVE_SHA256_FAILED", "DUMP_RESTORED",
    "POSTGRES_NOT_READY", "LISTENER_NOT_READY",
    "LIVE_POSTGRES_CONTAINER_NOT_FOUND", "TEARDOWN",
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
dry-run: write a mode 600 copy of the web env at ${workdir}/src/web/.env.production
dry-run: independent-beta-v1 and standalone-practice-v1 omit VITE_COSMANEURA_WEB_ORIGIN and VITE_CAPTURE_UPLOAD_ORIGINS
dry-run: ${workdir}/src/scripts/install-client-deps.sh
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
  local execute=0 cutover=0 teardown=0 sha="$DEFAULT_SOURCE_SHA" expect_prior=""
  local resource_group="$STAGING_RESOURCE_GROUP" vm_name="$STAGING_VM_NAME"
  local web_host="$STAGING_WEB_HOST" api_host="$STAGING_API_HOST"
  local workdir="" web_env="${COPY_TO_EHR_WEB_ENV:-${HOME:-}/code/cosmaneura-os-beta-staging-r10/web/.env.production}"
  local dump_target="${STAGING_DATA_ROOT}/copy-to-ehr-dumps/pre-migrate.dump"
  local subscription_flag="" dump_file="" expanded=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --execute) execute=1; shift ;;
      --cutover) cutover=1; shift ;;
      --teardown-trial) teardown=1; shift ;;
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
  if [[ "$teardown" -eq 1 && "$cutover" -eq 1 ]]; then
    copy_to_ehr_die "--teardown-trial does not cut over"
  fi
  if [[ "$execute" -eq 1 && "$cutover" -eq 1 ]]; then
    printf '%s\n' 'Tonight for existing live users: this run cuts staging over only after a verified dump and restore check on the staging VM; production stays untouched.'
  else
    printf '%s\n' 'Tonight for existing live users: nothing changes.'
  fi
  if [[ "$teardown" -eq 1 ]]; then
    printf '%s\n' 'Teardown removes the side-port trial containers and nft rule. It does not stop release-r10.'
  else
    printf '%s\n' 'Cutover stops live staging until release-r10 is serving again. The build and the side-port trial load the staging VM.'
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
  dump_file="$dump_target"
  copy_to_ehr_validate_dump_target "$dump_target" || copy_to_ehr_die "dump target is outside the staging resource group or is on this Mac"
  copy_to_ehr_validate_dump_target "$dump_file" || copy_to_ehr_die "dump file is not on the staging VM"
  copy_to_ehr_check_az
  if [[ "$teardown" -eq 1 ]]; then
    export COPY_TO_EHR_EXECUTE="$execute"
    copy_to_ehr_invoke_remote "teardown-trial" "$(copy_to_ehr_render_teardown)"
    return 0
  fi
  if [[ -z "$workdir" ]]; then
    if [[ "$execute" -eq 1 ]]; then
      workdir=$(mktemp -d "${TMPDIR:-/tmp}/copy-to-ehr-src.XXXXXX")
      chmod 700 "$workdir"
      COPY_TO_EHR_OWNED_WORKDIR="$workdir"
      trap copy_to_ehr_local_exit EXIT
      trap copy_to_ehr_local_signal INT TERM HUP
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
  local free_kib="" release="" archive="" keys="" dest=""
  free_kib=$(df -Pk "$workdir" | awk 'NR==2 {print $4}')
  if [[ -z "$free_kib" || "$free_kib" -lt "$MIN_FREE_KIB" ]]; then
    copy_to_ehr_die "not enough free disk before the web build"
  fi
  copy_to_ehr_clone_at_sha "$workdir/src" "$sha" || copy_to_ehr_die "checkout is not the requested clean sha"
  [[ -f "$web_env" && ! -L "$web_env" ]] || copy_to_ehr_die "web env file is missing"
  keys=$(copy_to_ehr_read_web_env_keys "$web_env") || copy_to_ehr_die "web env file refused"
  printf '%s\n' "$keys" | sed 's/^/web env key: /'
  dest="$workdir/src/web/.env.production"
  copy_to_ehr_stage_web_env "$web_env" "$dest" || copy_to_ehr_die "web env copy refused"
  COPY_TO_EHR_WEB_ENV_COPY="$dest"
  trap copy_to_ehr_local_exit EXIT
  trap copy_to_ehr_local_signal INT TERM HUP
  (
    COPY_TO_EHR_OWNED_WORKDIR=
    cd "$workdir/src/web"
    "$workdir/src/scripts/install-client-deps.sh"
    copy_to_ehr_run_web_build "$sha"
  )
  copy_to_ehr_cleanup_web_env_copy
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
  printf 'web archive chunks: %s\n' "$total"
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
  COPY_TO_EHR_ARCHIVE_SHA256=$(copy_to_ehr_sha256_file "$archive") || copy_to_ehr_die "web archive hash failed"
  body=$(python3 - "$remote_path" "$STAGING_DATA_ROOT" <<'PY'
import sys
dest, root = sys.argv[1:]
if not dest.startswith(root + "/"):
    raise SystemExit(1)
script = """exec /bin/bash <<'COPY_TO_EHR_BASH_BODY'
set -euo pipefail
set +x
dest='%s'
case "$dest" in
  %s/*) ;;
  *) printf 'CHUNK_PATH_REFUSED\\n' >&2; exit 1 ;;
esac
hash=$(sha256sum "$dest" | awk '{print $1}')
case "$hash" in
  [0-9a-f]*) ;;
  *) printf 'ARCHIVE_SHA256_FAILED\\n' >&2; exit 1 ;;
esac
printf 'ARCHIVE_SHA256 %%s\\n' "$hash"
COPY_TO_EHR_BASH_BODY
""" % (dest, root)
sys.stdout.write(script)
PY
)
  copy_to_ehr_invoke_remote "web-verify" "$body"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  copy_to_ehr_main "$@"
fi
