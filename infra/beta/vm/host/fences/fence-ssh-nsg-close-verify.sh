cosmabot_ssh_nsg_close_and_verify() {
  command -v az >/dev/null || {
    echo "STOP: ssh-nsg-close needs az" >&2
    return 1
  }
  command -v jq >/dev/null || {
    echo "STOP: ssh-nsg-close needs jq" >&2
    return 1
  }
  command -v python3 >/dev/null || {
    echo "STOP: ssh-nsg-close needs python3" >&2
    return 1
  }
  command -v ssh >/dev/null || {
    echo "STOP: ssh-nsg-close needs ssh" >&2
    return 1
  }
  test -n "${RG:-}" || {
    echo "STOP: ssh-nsg-close RG unset - export rg-cosmabot-prod-eus2-01" >&2
    return 1
  }
  printf '%s' "$RG" | grep -Eq '^rg-cosmabot-prod-eus2-01$' || {
    echo "STOP: ssh-nsg-close RG must be rg-cosmabot-prod-eus2-01" >&2
    return 1
  }
  test -n "${SECRETS_TRANSPORT_PY:-}" || {
    echo "STOP: ssh-nsg-close SECRETS_TRANSPORT_PY unset" >&2
    return 1
  }
  test -f "$SECRETS_TRANSPORT_PY" || {
    echo "STOP: ssh-nsg-close SECRETS_TRANSPORT_PY missing" >&2
    return 1
  }
  az network nsg rule delete \
    --resource-group "$RG" \
    --nsg-name nsg-cosmabot-prod-eus2-01 \
    --name TEMP-JOHN-SSH-SECRETS-INSTALL \
    --output none 2>/dev/null || true
  RULES_JSON=$(az network nsg rule list \
    --resource-group "$RG" \
    --nsg-name nsg-cosmabot-prod-eus2-01 \
    --query "[].{name:name,port:destinationPortRange,access:access,priority:priority,protocol:protocol,source:sourceAddressPrefix}" \
    -o json) || {
    echo "STOP: ssh-nsg-close rule list failed" >&2
    return 1
  }
  printf '%s\n' "$RULES_JSON" | jq -r '.[] | "name=\(.name) port=\(.port) access=\(.access) priority=\(.priority)"' || {
    echo "STOP: ssh-nsg-close rule print failed" >&2
    return 1
  }
  test "$(printf '%s' "$RULES_JSON" | jq -r '[.[] | select(.name=="TEMP-JOHN-SSH-SECRETS-INSTALL")] | length')" = "0" || {
    echo "STOP: TEMP-JOHN-SSH-SECRETS-INSTALL still present" >&2
    return 1
  }
  test "$(printf '%s' "$RULES_JSON" | jq -r '[.[] | select(.name=="deny-all-other-ingress" and .access=="Deny" and (.priority|tonumber)==4000)] | length')" = "1" || {
    echo "STOP: deny-all-other-ingress missing or not Deny priority 4000" >&2
    return 1
  }
  test "$(printf '%s' "$RULES_JSON" | jq -r '[.[] | select((.port=="22" or .port==22) and .access=="Allow")] | length')" = "0" || {
    echo "STOP: port-22 Allow rule still present" >&2
    return 1
  }
  RULES_FILE=$(mktemp "${TMPDIR:-/tmp}/nsg-rules-close.XXXXXX") || {
    echo "STOP: ssh-nsg-close mktemp failed" >&2
    return 1
  }
  printf '%s' "$RULES_JSON" >"$RULES_FILE" || {
    echo "STOP: ssh-nsg-close rules write failed" >&2
    rm -f "$RULES_FILE"
    return 1
  }
  test -n "${PROD_KV_NAME:-}" || PROD_KV_NAME="kv-cbot-prd-placeholder"
  python3 "$SECRETS_TRANSPORT_PY" \
    --profile cosmabot-vm-prod-v1 \
    --resource-group rg-cosmabot-prod-eus2-01 \
    --vault-name "$PROD_KV_NAME" \
    --check-ssh-closed \
    --nsg-rules-json "$RULES_FILE" || {
    echo "STOP: ssh-nsg-close --check-ssh-closed refused" >&2
    rm -f "$RULES_FILE"
    return 1
  }
  rm -f "$RULES_FILE"
  test -n "${VM_PUBLIC_IP:-}" || {
    echo "STOP: ssh-nsg-close VM_PUBLIC_IP unset" >&2
    return 1
  }
  PROBE_ERR=$(mktemp "${TMPDIR:-/tmp}/ssh-probe-err.XXXXXX") || {
    echo "STOP: ssh-nsg-close probe mktemp failed" >&2
    return 1
  }
  PROBE_RC=0
  ssh -o BatchMode=yes -o ConnectTimeout=3 \
    -o StrictHostKeyChecking=yes \
    -o UserKnownHostsFile="${SSH_KNOWN_HOSTS_FILE:-/dev/null}" \
    "cosmasoperator@${VM_PUBLIC_IP}" true >"$PROBE_ERR" 2>&1 || PROBE_RC=$?
  python3 "$SECRETS_TRANSPORT_PY" \
    --profile cosmabot-vm-prod-v1 \
    --resource-group rg-cosmabot-prod-eus2-01 \
    --vault-name "$PROD_KV_NAME" \
    --check-ssh-probe \
    --ssh-probe-exit-code "$PROBE_RC" \
    --ssh-probe-stderr-file "$PROBE_ERR" || {
    echo "STOP: SSH still reachable after close (auth failure counts as reachable)" >&2
    rm -f "$PROBE_ERR"
    return 1
  }
  rm -f "$PROBE_ERR"
  echo "PASS: TEMP-JOHN-SSH-SECRETS-INSTALL gone; no port-22 Allow; deny-all priority 4000; SSH refused-or-timeout"
  echo "NOTE: out-of-band NSG rules drift the next Terraform plan; close-and-verify is MANDATORY before any plan or apply"
  return 0
}
