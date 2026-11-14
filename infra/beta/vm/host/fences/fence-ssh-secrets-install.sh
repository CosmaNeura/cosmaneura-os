cosmabot_ssh_secrets_install() {
  command -v az >/dev/null || {
    echo "STOP: ssh-install needs az" >&2
    return 1
  }
  command -v jq >/dev/null || {
    echo "STOP: ssh-install needs jq" >&2
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
  command -v sha256sum >/dev/null || {
    echo "STOP: ssh-install needs sha256sum" >&2
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
  test -n "${SECRETS_TRANSPORT_SHA256_PIN:-}" || {
    SECRETS_TRANSPORT_SHA256_PIN="$(dirname "$SECRETS_TRANSPORT_PY")/secrets_transport.sha256"
  }
  test -f "$SECRETS_TRANSPORT_SHA256_PIN" || {
    echo "STOP: ssh-install sha256 pin missing" >&2
    return 1
  }
  test -n "${JOHN_SSH_CIDR:-}" || {
    echo "STOP: ssh-install JOHN_SSH_CIDR unset - run open first" >&2
    return 1
  }
  printf '%s' "$PROD_KV_NAME" | grep -Eq '^kv-cbot-prd-[a-z0-9]+$' || {
    echo "STOP: ssh-install PROD_KV_NAME shape" >&2
    return 1
  }
  printf '%s' "$JOHN_SSH_CIDR" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+/32$' || {
    echo "STOP: ssh-install JOHN_SSH_CIDR shape" >&2
    return 1
  }
  python3 "$SECRETS_TRANSPORT_PY" \
    --profile cosmabot-vm-prod-v1 \
    --resource-group rg-cosmabot-prod-eus2-01 \
    --vault-name "$PROD_KV_NAME" \
    --verify-module-sha256 \
    --module-path "$SECRETS_TRANSPORT_PY" \
    --sha256-pin-path "$SECRETS_TRANSPORT_SHA256_PIN" || {
    echo "STOP: ssh-install local module sha256 mismatch" >&2
    return 1
  }
  RULES_JSON=$(az network nsg rule list \
    --resource-group "$RG" \
    --nsg-name nsg-cosmabot-prod-eus2-01 \
    --query "[].{name:name,port:destinationPortRange,access:access,priority:priority,protocol:protocol,source:sourceAddressPrefix}" \
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
  printf '%s' "$RULES_JSON" | jq -e \
    --arg n TEMP-JOHN-SSH-SECRETS-INSTALL \
    --arg src "$JOHN_SSH_CIDR" \
    'map(select(.name==$n and .port=="22" and .access=="Allow" and ((.protocol|ascii_downcase)=="tcp") and .source==$src and (.priority|tonumber)==200)) | length == 1' \
    >/dev/null || {
    echo "STOP: ssh-install TEMP-JOHN-SSH-SECRETS-INSTALL not Allow Tcp/22 priority 200 from JOHN_SSH_CIDR" >&2
    rm -f "$RULES_FILE"
    return 1
  }
  python3 "$SECRETS_TRANSPORT_PY" \
    --profile cosmabot-vm-prod-v1 \
    --resource-group rg-cosmabot-prod-eus2-01 \
    --vault-name "$PROD_KV_NAME" \
    --check-ssh-install-ready \
    --ack-close-and-verify \
    --expected-source-cidr "$JOHN_SSH_CIDR" \
    --nsg-rules-json "$RULES_FILE" || {
    echo "STOP: ssh-install gate refused (TEMP-JOHN-SSH-SECRETS-INSTALL + close ack)" >&2
    rm -f "$RULES_FILE"
    return 1
  }
  rm -f "$RULES_FILE"
  SSH_KNOWN_HOSTS_FILE=$(mktemp "${TMPDIR:-/tmp}/cosmabot-known-hosts.XXXXXX") || {
    echo "STOP: ssh-install known_hosts mktemp failed" >&2
    return 1
  }
  export SSH_KNOWN_HOSTS_FILE
  HOSTKEY_JSON=$(az vm run-command invoke \
    --resource-group "$RG" \
    --name vm-cosmabot-prod-eus2-01 \
    --command-id RunShellScript \
    --scripts "cat /etc/ssh/ssh_host_ed25519_key.pub" \
    -o json) || {
    echo "STOP: ssh-install host-key run-command failed" >&2
    rm -f "$SSH_KNOWN_HOSTS_FILE"
    return 1
  }
  HOSTKEY_LINE=$(printf '%s' "$HOSTKEY_JSON" | jq -r '
    .value[0].message
    | split("\n")
    | map(select(test("^ssh-ed25519 ")))
    | .[0]
    // empty
  ') || {
    echo "STOP: ssh-install host-key parse failed" >&2
    rm -f "$SSH_KNOWN_HOSTS_FILE"
    return 1
  }
  printf '%s' "$HOSTKEY_LINE" | grep -Eq '^ssh-ed25519 [A-Za-z0-9+/=]+' || {
    echo "STOP: ssh-install host-key shape invalid" >&2
    rm -f "$SSH_KNOWN_HOSTS_FILE"
    return 1
  }
  HOSTKEY_BODY=$(printf '%s' "$HOSTKEY_LINE" | awk '{print $1" "$2}')
  printf '%s %s\n' "$VM_PUBLIC_IP" "$HOSTKEY_BODY" >"$SSH_KNOWN_HOSTS_FILE" || {
    echo "STOP: ssh-install known_hosts write failed" >&2
    rm -f "$SSH_KNOWN_HOSTS_FILE"
    return 1
  }
  PINNED_SHA=$(tr -d ' \n\r\t' <"$SECRETS_TRANSPORT_SHA256_PIN")
  REMOTE_MODULE="/opt/cosmabot/host/secrets_transport.py"
  REMOTE_ROOT="/etc/cosmabot/runtime/${RELEASE_ID}"
  ssh -o BatchMode=yes -o ConnectTimeout=15 \
    -o StrictHostKeyChecking=yes \
    -o "UserKnownHostsFile=${SSH_KNOWN_HOSTS_FILE}" \
    "cosmasoperator@${VM_PUBLIC_IP}" \
    "set -euo pipefail; sudo mkdir -p -m 755 /opt/cosmabot/host '${REMOTE_ROOT}'; sudo tee '${REMOTE_MODULE}' >/dev/null; sudo chmod 0644 '${REMOTE_MODULE}'; test \"\$(sudo sha256sum '${REMOTE_MODULE}' | awk '{print \$1}')\" = '${PINNED_SHA}'" \
    <"$SECRETS_TRANSPORT_PY" || {
    echo "STOP: ssh-install ship module or remote sha256 failed" >&2
    rm -f "$SSH_KNOWN_HOSTS_FILE"
    return 1
  }
  for staged in "$LOCAL_STAGING"/*; do
    test -e "$staged" || continue
    case "$staged" in
      *.source-account) continue ;;
    esac
    test -f "$staged" || continue
    base=$(basename "$staged")
    REMOTE_CMD="set -euo pipefail; sudo python3 '${REMOTE_MODULE}' --profile cosmabot-vm-prod-v1 --resource-group rg-cosmabot-prod-eus2-01 --vault-name '${PROD_KV_NAME}' --release-id '${RELEASE_ID}' --protected-root '${REMOTE_ROOT}' --install-from-stdin --host-name '${base}'"
    SIDE="$LOCAL_STAGING/${base}.source-account"
    if test -f "$SIDE"; then
      LLM_ACCT=$(tr -d '\n' <"$SIDE")
      REMOTE_CMD="${REMOTE_CMD} --llm-source-account $(printf '%q' "$LLM_ACCT")"
    fi
    ssh -o BatchMode=yes -o ConnectTimeout=15 \
      -o StrictHostKeyChecking=yes \
      -o "UserKnownHostsFile=${SSH_KNOWN_HOSTS_FILE}" \
      "cosmasoperator@${VM_PUBLIC_IP}" \
      "$REMOTE_CMD" \
      <"$staged" || {
      echo "STOP: ssh-install stdin write failed for name=${base} (value not printed)" >&2
      rm -f "$SSH_KNOWN_HOSTS_FILE"
      return 1
    }
    echo "PASS: installed name=${base} via ssh stdin (value not printed)"
  done
  rm -rf "${LOCAL_STAGING:?}"
  test ! -e "$LOCAL_STAGING" || {
    echo "STOP: local staging still present" >&2
    rm -f "$SSH_KNOWN_HOSTS_FILE"
    return 1
  }
  rm -f "$SSH_KNOWN_HOSTS_FILE"
  echo "PASS: local staging removed; module shipped; values piped over ssh stdin only"
  return 0
}
