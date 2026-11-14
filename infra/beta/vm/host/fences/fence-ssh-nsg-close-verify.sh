cosmabot_ssh_nsg_close_and_verify() {
  command -v az >/dev/null || {
    echo "STOP: ssh-nsg-close needs az" >&2
    return 1
  }
  command -v jq >/dev/null || {
    echo "STOP: ssh-nsg-close needs jq" >&2
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
  az network nsg rule delete \
    --resource-group "$RG" \
    --nsg-name nsg-cosmabot-prod-eus2-01 \
    --name TEMP-JOHN-SSH-SECRETS-INSTALL \
    --output none 2>/dev/null || true
  RULES_JSON=$(az network nsg rule list \
    --resource-group "$RG" \
    --nsg-name nsg-cosmabot-prod-eus2-01 \
    --query "[].{name:name,port:destinationPortRange,access:access,priority:priority}" \
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
  test "$(printf '%s' "$RULES_JSON" | jq -r '[.[] | select(.name=="deny-all-other-ingress" and .access=="Deny")] | length')" = "1" || {
    echo "STOP: deny-all-other-ingress missing or not Deny" >&2
    return 1
  }
  test "$(printf '%s' "$RULES_JSON" | jq -r '[.[] | select((.port=="22" or .port==22) and .access=="Allow")] | length')" = "0" || {
    echo "STOP: port-22 Allow rule still present" >&2
    return 1
  }
  test -n "${VM_PUBLIC_IP:-}" || {
    echo "STOP: ssh-nsg-close VM_PUBLIC_IP unset" >&2
    return 1
  }
  if ssh -o BatchMode=yes -o ConnectTimeout=3 -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null "cosmasoperator@${VM_PUBLIC_IP}" true 2>/dev/null
  then
    echo "STOP: SSH still reachable after close" >&2
    return 1
  fi
  echo "PASS: TEMP-JOHN-SSH-SECRETS-INSTALL gone; no port-22 Allow; deny-all intact; SSH timeout"
  echo "NOTE: out-of-band NSG rules drift the next Terraform plan; close-and-verify is MANDATORY before any plan or apply"
  return 0
}
cosmabot_ssh_nsg_close_and_verify || {
  echo "STOP: ssh-nsg-close-verify failed - fix before any Terraform plan or apply" >&2
  false
}
