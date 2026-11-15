cosmabot_require_local_staging_shape() {
  test -n "${LOCAL_STAGING:-}" || {
    echo "STOP: LOCAL_STAGING unset - use mktemp -d /tmp/cosmabot-staging.XXXXXX" >&2
    return 1
  }
  case "$LOCAL_STAGING" in
    /*) ;;
    *)
      echo "STOP: LOCAL_STAGING must be absolute" >&2
      return 1
      ;;
  esac
  printf '%s' "$LOCAL_STAGING" | grep -Eq '^(/private)?/tmp/cosmabot-staging\.[A-Za-z0-9]{6}$' || {
    echo "STOP: LOCAL_STAGING must match mktemp -d /tmp/cosmabot-staging.XXXXXX (/tmp or /private/tmp only; never /var/folders)" >&2
    return 1
  }
  return 0
}
cosmabot_guarded_rm_local_staging() {
  cosmabot_require_local_staging_shape || return 1
  test -d "$LOCAL_STAGING" || {
    echo "STOP: guarded-rm LOCAL_STAGING not a directory" >&2
    return 1
  }
  _gs_mode=$(stat -c '%a' "$LOCAL_STAGING" 2>/dev/null || stat -f '%Lp' "$LOCAL_STAGING") || {
    echo "STOP: guarded-rm LOCAL_STAGING stat failed" >&2
    return 1
  }
  test "$_gs_mode" = "700" || {
    echo "STOP: guarded-rm LOCAL_STAGING mode not 0700" >&2
    return 1
  }
  _gs_owner=$(stat -c '%u' "$LOCAL_STAGING" 2>/dev/null || stat -f '%u' "$LOCAL_STAGING") || {
    echo "STOP: guarded-rm LOCAL_STAGING owner stat failed" >&2
    return 1
  }
  test "$_gs_owner" = "$(id -u)" || {
    echo "STOP: guarded-rm LOCAL_STAGING not owned by current user" >&2
    return 1
  }
  rm -rf "${LOCAL_STAGING:?}" || {
    echo "STOP: guarded-rm LOCAL_STAGING remove failed" >&2
    return 1
  }
  test ! -e "$LOCAL_STAGING" || {
    echo "STOP: guarded-rm LOCAL_STAGING still present" >&2
    return 1
  }
  return 0
}
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
  if test -n "${LOCAL_STAGING:-}" && test -e "${LOCAL_STAGING}"; then
    cosmabot_guarded_rm_local_staging || {
      echo "STOP: recovery could not remove LOCAL_STAGING - NSG verified closed but staging remains; no PASS" >&2
      return 1
    }
    test ! -e "${LOCAL_STAGING}" || {
      echo "STOP: recovery LOCAL_STAGING still present after guarded rm; no PASS" >&2
      return 1
    }
    echo "NOTE: recovery removed local staging path (values not printed)"
  else
    echo "NOTE: LOCAL_STAGING unset or already gone - NSG close verified without staging cleanup"
  fi
  echo "PASS: recovery deleted TEMP-JOHN-SSH-SECRETS-INSTALL; deny-all intact"
  echo "NOTE: out-of-band NSG rules drift the next Terraform plan; close-and-verify is MANDATORY before any plan or apply"
  return 0
}
