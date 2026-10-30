#!/usr/bin/env bash
# Reuse the synthetic endpoints created by the cloud hook or Docker.
# Start containers only for missing endpoints; never compete for an occupied port.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ $# -eq 0 ]]; then
  echo "Request postgres and/or redis." >&2
  exit 2
fi
for service in "$@"; do
  case "$service" in postgres|redis) ;; *) echo "Unknown local service: $service" >&2; exit 2 ;; esac
done

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is required to check local endpoints safely." >&2
  exit 1
fi

PSQL=""
if command -v psql >/dev/null 2>&1; then
  PSQL="$(command -v psql)"
elif command -v pg_config >/dev/null 2>&1; then
  PG_BIN="$(pg_config --bindir)"
  if [[ -x "$PG_BIN/psql" ]]; then PSQL="$PG_BIN/psql"; fi
fi

service_ready() {
  case "$1" in
    postgres)
      if [[ -n "$PSQL" ]]; then
        PGPASSWORD=cosmas PGCONNECT_TIMEOUT=2 python3 - "$PSQL" <<'PY_POSTGRES'
import subprocess
import sys
try:
    result = subprocess.run(
        [sys.argv[1], "-X", "-w", "-h", "127.0.0.1", "-p", "54329",
         "-U", "cosmas", "-d", "cosmas_os", "-tAc", "SELECT 1"],
        capture_output=True, text=True, timeout=2,
    )
except (OSError, subprocess.TimeoutExpired):
    sys.exit(1)
sys.exit(0 if result.returncode == 0 and result.stdout.strip() == "1" else 1)
PY_POSTGRES
      else
        docker-compose exec -T postgres pg_isready -U cosmas -d cosmas_os >/dev/null 2>&1
      fi
      ;;
    redis)
      if command -v redis-cli >/dev/null 2>&1; then
        python3 - "$(command -v redis-cli)" <<'PY_REDIS'
import subprocess
import sys
try:
    result = subprocess.run(
        [sys.argv[1], "-h", "127.0.0.1", "-p", "63799", "ping"],
        capture_output=True, text=True, timeout=2,
    )
except (OSError, subprocess.TimeoutExpired):
    sys.exit(1)
sys.exit(0 if result.returncode == 0 and result.stdout.strip() == "PONG" else 1)
PY_REDIS
      else
        docker-compose exec -T redis redis-cli ping 2>/dev/null | grep -qx PONG
      fi
      ;;
  esac
}

endpoint_busy() {
  local port=54329
  if [[ "$1" == redis ]]; then port=63799; fi
  python3 - "$port" <<'PY'
import socket
import sys
try:
    with socket.create_connection(("127.0.0.1", int(sys.argv[1])), timeout=0.2):
        pass
except OSError:
    sys.exit(1)
PY
}

missing=()
for service in "$@"; do
  if ! service_ready "$service" && ! endpoint_busy "$service"; then
    missing+=("$service")
  fi
done
if [[ ${#missing[@]} -gt 0 ]]; then
  if ! command -v docker-compose >/dev/null 2>&1; then
    echo "Missing local services: ${missing[*]}. Run the cloud startup hook or install Docker Compose." >&2
    exit 1
  fi
  docker-compose up -d "${missing[@]}"
fi

for service in "$@"; do
  ready=0
  for _ in $(seq 1 45); do
    if service_ready "$service"; then ready=1; break; fi
    sleep 1
  done
  if [[ "$ready" -ne 1 ]]; then
    echo "$service did not become ready at its local endpoint; an occupied endpoint was left untouched." >&2
    exit 1
  fi
done
