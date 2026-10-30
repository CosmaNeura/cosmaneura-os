#!/usr/bin/env bash
# Start the local Postgres and Redis endpoints used by tests and the app.
# Safe to run more than once. Package installation belongs in environment install.
set -euo pipefail

if command -v pg_config >/dev/null 2>&1; then
  PG_BIN="$(pg_config --bindir)"
elif [[ -x /usr/lib/postgresql/16/bin/pg_ctl ]]; then
  PG_BIN=/usr/lib/postgresql/16/bin
else
  echo "PostgreSQL 16 tools are missing." >&2
  exit 1
fi

for tool in redis-server redis-cli; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "$tool is missing." >&2
    exit 1
  fi
done

STATE_DIR="${COSMAS_AGENT_STATE_DIR:-"$HOME/.local/share/cosmas-os"}"
PG_DATA="$STATE_DIR/postgres"
PG_PORT=54329
REDIS_PORT=63799
REDIS_DIR="$STATE_DIR/redis"
mkdir -p "$STATE_DIR" "$REDIS_DIR"

postgres_ready() {
  "$PG_BIN/pg_isready" -h 127.0.0.1 -p "$PG_PORT" -q
}

if ! postgres_ready; then
  if [[ -f "$PG_DATA/postmaster.pid" ]]; then
    old_pid="$(head -n 1 "$PG_DATA/postmaster.pid" || true)"
    if [[ -z "${old_pid}" ]] || ! kill -0 "$old_pid" 2>/dev/null; then
      rm -f "$PG_DATA/postmaster.pid"
    fi
  fi
  if [[ ! -f "$PG_DATA/PG_VERSION" ]]; then
    rm -rf "$PG_DATA"
    mkdir -p "$PG_DATA"
    password_file="$(mktemp)"
    chmod 600 "$password_file"
    printf '%s\n' cosmas >"$password_file"
    "$PG_BIN/initdb" -D "$PG_DATA" --username=cosmas --pwfile="$password_file" \
      --auth-local=trust --auth-host=scram-sha-256 --no-locale --encoding=UTF8
    rm -f "$password_file"
  fi
  "$PG_BIN/pg_ctl" -D "$PG_DATA" -l "$STATE_DIR/postgres.log" -w -t 30 \
    -o "-h 127.0.0.1 -p ${PG_PORT} -k ''" start
fi

ready=0
for _ in $(seq 1 50); do
  if postgres_ready; then
    ready=1
    break
  fi
  sleep 0.2
done
if [[ "$ready" -ne 1 ]]; then
  echo "Postgres did not become ready on 127.0.0.1:${PG_PORT}." >&2
  exit 1
fi

export PGPASSWORD=cosmas
if ! "$PG_BIN/psql" -h 127.0.0.1 -p "$PG_PORT" -U cosmas -d postgres -tAc \
  "SELECT 1 FROM pg_database WHERE datname = 'cosmas_os'" | grep -qx 1; then
  "$PG_BIN/createdb" -h 127.0.0.1 -p "$PG_PORT" -U cosmas -O cosmas cosmas_os
fi
"$PG_BIN/psql" -h 127.0.0.1 -p "$PG_PORT" -U cosmas -d cosmas_os -tAc "SELECT 1" | grep -qx 1

if ! redis-cli -h 127.0.0.1 -p "$REDIS_PORT" ping 2>/dev/null | grep -qx PONG; then
  if [[ -f "$REDIS_DIR/redis.pid" ]]; then
    old_pid="$(cat "$REDIS_DIR/redis.pid" || true)"
    if [[ -z "${old_pid}" ]] || ! kill -0 "$old_pid" 2>/dev/null; then
      rm -f "$REDIS_DIR/redis.pid"
    fi
  fi
  redis-server \
    --daemonize yes \
    --bind 127.0.0.1 \
    --port "$REDIS_PORT" \
    --protected-mode yes \
    --dir "$REDIS_DIR" \
    --pidfile "$REDIS_DIR/redis.pid" \
    --logfile "$STATE_DIR/redis.log" \
    --save "" \
    --appendonly no
fi

ready=0
for _ in $(seq 1 50); do
  if redis-cli -h 127.0.0.1 -p "$REDIS_PORT" ping 2>/dev/null | grep -qx PONG; then
    ready=1
    break
  fi
  sleep 0.2
done
if [[ "$ready" -ne 1 ]]; then
  echo "Redis did not become ready on 127.0.0.1:${REDIS_PORT}." >&2
  exit 1
fi

echo "Postgres ready on 127.0.0.1:${PG_PORT} database cosmas_os"
echo "Redis ready on 127.0.0.1:${REDIS_PORT}"
