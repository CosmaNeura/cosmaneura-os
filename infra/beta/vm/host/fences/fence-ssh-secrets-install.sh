cosmabot_ssh_secrets_install() {
  command -v az >/dev/null || {
    echo "STOP: ssh-install needs az" >&2
    return 1
  }
  command -v jq >/dev/null || {
    echo "STOP: ssh-install needs jq" >&2
    return 1
  }
  command -v scp >/dev/null || {
    echo "STOP: ssh-install needs scp" >&2
    return 1
  }
  command -v ssh >/dev/null || {
    echo "STOP: ssh-install needs ssh" >&2
    return 1
  }
  command -v python3 >/dev/null || {
    echo "STOP: ssh-install needs python3" >&2
    return 1
  }
  test -n "${RG:-}" || {
    echo "STOP: ssh-install RG unset" >&2
    return 1
  }
  test -n "${VM_PUBLIC_IP:-}" || {
    echo "STOP: ssh-install VM_PUBLIC_IP unset" >&2
    return 1
  }
  test -n "${RELEASE_ID:-}" || {
    echo "STOP: ssh-install RELEASE_ID unset" >&2
    return 1
  }
  test -n "${LOCAL_STAGING:-}" || {
    echo "STOP: ssh-install LOCAL_STAGING unset" >&2
    return 1
  }
  test -d "$LOCAL_STAGING" || {
    echo "STOP: ssh-install LOCAL_STAGING missing" >&2
    return 1
  }
  test -n "${PROD_KV_NAME:-}" || {
    echo "STOP: ssh-install PROD_KV_NAME unset" >&2
    return 1
  }
  test -n "${SECRETS_TRANSPORT_PY:-}" || {
    echo "STOP: ssh-install SECRETS_TRANSPORT_PY unset" >&2
    return 1
  }
  test -f "$SECRETS_TRANSPORT_PY" || {
    echo "STOP: ssh-install SECRETS_TRANSPORT_PY missing" >&2
    return 1
  }
  printf '%s' "$PROD_KV_NAME" | grep -Eq '^kv-cbot-prd-[a-z0-9]+$' || {
    echo "STOP: ssh-install PROD_KV_NAME shape" >&2
    return 1
  }
  RULES_JSON=$(az network nsg rule list \
    --resource-group "$RG" \
    --nsg-name nsg-cosmabot-prod-eus2-01 \
    --query "[].{name:name,port:destinationPortRange,access:access,priority:priority}" \
    -o json) || {
    echo "STOP: ssh-install nsg list failed" >&2
    return 1
  }
  RULES_FILE=$(mktemp "${TMPDIR:-/tmp}/nsg-rules.XXXXXX") || {
    echo "STOP: ssh-install mktemp failed" >&2
    return 1
  }
  printf '%s' "$RULES_JSON" >"$RULES_FILE" || {
    echo "STOP: ssh-install rules write failed" >&2
    rm -f "$RULES_FILE"
    return 1
  }
  python3 "$SECRETS_TRANSPORT_PY" \
    --profile cosmabot-vm-prod-v1 \
    --resource-group rg-cosmabot-prod-eus2-01 \
    --vault-name "$PROD_KV_NAME" \
    --check-ssh-install-ready \
    --ack-close-and-verify \
    --nsg-rules-json "$RULES_FILE" || {
    echo "STOP: ssh-install gate refused" >&2
    rm -f "$RULES_FILE"
    return 1
  }
  rm -f "$RULES_FILE"
  REMOTE_STAGING="/root/cosmabot-secret-staging-${RELEASE_ID}"
  REMOTE_ROOT="/etc/cosmabot/runtime/${RELEASE_ID}"
  scp -o BatchMode=yes -o ConnectTimeout=15 -r \
    "$LOCAL_STAGING/." "cosmasoperator@${VM_PUBLIC_IP}:/tmp/cosmabot-secret-staging-upload/" || {
    echo "STOP: ssh-install scp failed" >&2
    return 1
  }
  ssh -o BatchMode=yes -o ConnectTimeout=15 "cosmasoperator@${VM_PUBLIC_IP}" \
    "set -euo pipefail; sudo mkdir -p -m 700 '${REMOTE_STAGING}' '${REMOTE_ROOT}'; sudo rm -rf '${REMOTE_STAGING:?}/'*; sudo cp -a /tmp/cosmabot-secret-staging-upload/. '${REMOTE_STAGING}/'; sudo rm -rf /tmp/cosmabot-secret-staging-upload; sudo python3 -m compileall -q /opt/cosmabot/host/secrets_transport.py 2>/dev/null || true; if test -f /opt/cosmabot/host/secrets_transport.py; then sudo python3 /opt/cosmabot/host/secrets_transport.py --profile cosmabot-vm-prod-v1 --resource-group rg-cosmabot-prod-eus2-01 --vault-name '${PROD_KV_NAME}' --release-id '${RELEASE_ID}' --protected-root '${REMOTE_ROOT}' --staging-dir '${REMOTE_STAGING}' --cleanup-staging; else echo STOP: remote secrets_transport.py missing >&2; exit 1; fi; test ! -d '${REMOTE_STAGING}' -o -z \"\$(sudo ls -A '${REMOTE_STAGING}' 2>/dev/null)\" || { echo STOP: remote staging not empty >&2; exit 1; }; echo PASS: remote staging absent after cleanup" || {
    echo "STOP: ssh-install remote failed - run close-and-verify next" >&2
    return 1
  }
  for staged in "$LOCAL_STAGING"/*; do
    test -e "$staged" || continue
    case "$staged" in
      *.source-account) continue ;;
    esac
    test -f "$staged" || continue
    base=$(basename "$staged")
    echo "PASS: local staged name=${base} (value not printed)"
  done
  rm -rf "${LOCAL_STAGING:?}"
  test ! -e "$LOCAL_STAGING" || {
    echo "STOP: local staging still present" >&2
    return 1
  }
  echo "PASS: local staging removed; names cleaned; values not printed"
  return 0
}
