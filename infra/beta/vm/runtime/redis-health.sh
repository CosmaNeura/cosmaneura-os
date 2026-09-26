#!/bin/sh
set -eu
REDISCLI_AUTH="$(cat /run/cosmabot/secrets/REDIS_PASSWORD)"
export REDISCLI_AUTH
exec redis-cli --tls --cacert /opt/cosmabot/runtime/system-ca.pem -h redis -p 6379 ping
