cosmabot_ssh_nsg_recovery_if_stranded() {
  command -v az >/dev/null || {
    echo "STOP: ssh-nsg-recovery needs az" >&2
    return 1
  }
  test -n "${RG:-}" || {
    echo "STOP: ssh-nsg-recovery RG unset - export rg-cosmabot-prod-eus2-01" >&2
    return 1
  }
  printf '%s' "$RG" | grep -Eq '^rg-cosmabot-prod-eus2-01$' || {
    echo "STOP: ssh-nsg-recovery RG must be rg-cosmabot-prod-eus2-01" >&2
    return 1
  }
  _delete_rc=0
  az network nsg rule delete \
    --resource-group "$RG" \
    --nsg-name nsg-cosmabot-prod-eus2-01 \
    --name TEMP-JOHN-SSH-SECRETS-INSTALL \
    --output none || _delete_rc=$?
  command -v jq >/dev/null || {
    echo "STOP: ssh-nsg-recovery needs jq after delete (rule delete attempted rc=${_delete_rc})" >&2
    return 1
  }
  jq -n 'true' >/dev/null 2>&1 || {
    echo "STOP: ssh-nsg-recovery needs jq after delete (rule delete attempted rc=${_delete_rc})" >&2
    return 1
  }
  test -n "${LOCAL_STAGING:-}" || {
    echo "STOP: ssh-nsg-recovery LOCAL_STAGING unset - export the mode-700 staging path (same rule as KEYFILE)" >&2
    return 1
  }
  test -d "$LOCAL_STAGING" || {
    echo "STOP: ssh-nsg-recovery LOCAL_STAGING missing or not a directory (empty/partial)" >&2
    return 1
  }
  rm -rf "${LOCAL_STAGING:?}" || {
    echo "STOP: ssh-nsg-recovery LOCAL_STAGING remove failed" >&2
    return 1
  }
  test ! -e "$LOCAL_STAGING" || {
    echo "STOP: ssh-nsg-recovery LOCAL_STAGING still present" >&2
    return 1
  }
  RULES_JSON=$(az network nsg rule list \
    --resource-group "$RG" \
    --nsg-name nsg-cosmabot-prod-eus2-01 \
    --query "[].{name:name,port:destinationPortRange,destinationPortRanges:destinationPortRanges,access:access,priority:priority}" \
    -o json) || {
    echo "STOP: ssh-nsg-recovery rule list failed" >&2
    return 1
  }
  printf '%s\n' "$RULES_JSON" | jq -r '.[] | "name=\(.name) port=\(.port // .destinationPortRanges) access=\(.access) priority=\(.priority)"' || {
    echo "STOP: ssh-nsg-recovery rule print failed" >&2
    return 1
  }
  test "$(printf '%s' "$RULES_JSON" | jq -r '[.[] | select(.name=="TEMP-JOHN-SSH-SECRETS-INSTALL")] | length')" = "0" || {
    echo "STOP: recovery left TEMP-JOHN-SSH-SECRETS-INSTALL in place" >&2
    return 1
  }
  test "$(printf '%s' "$RULES_JSON" | jq -r '[.[] | select(.name=="deny-all-other-ingress" and .access=="Deny" and (.priority|tonumber)==4000)] | length')" = "1" || {
    echo "STOP: recovery deny-all-other-ingress missing or not Deny priority 4000" >&2
    return 1
  }
  echo "PASS: recovery deleted TEMP-JOHN-SSH-SECRETS-INSTALL; local staging removed; deny-all intact"
  echo "NOTE: out-of-band NSG rules drift the next Terraform plan; close-and-verify is MANDATORY before any plan or apply"
  return 0
}
