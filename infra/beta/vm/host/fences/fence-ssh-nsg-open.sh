cosmabot_ssh_nsg_open() {
  command -v az >/dev/null || {
    echo "STOP: ssh-nsg-open needs az" >&2
    return 1
  }
  command -v curl >/dev/null || {
    echo "STOP: ssh-nsg-open needs curl" >&2
    return 1
  }
  test -n "${RG:-}" || {
    echo "STOP: ssh-nsg-open RG unset - export rg-cosmabot-prod-eus2-01" >&2
    return 1
  }
  printf '%s' "$RG" | grep -Eq '^rg-cosmabot-prod-eus2-01$' || {
    echo "STOP: ssh-nsg-open RG must be rg-cosmabot-prod-eus2-01" >&2
    return 1
  }
  JOHN_IP=$(curl -fsS https://api.ipify.org) || {
    echo "STOP: ssh-nsg-open IP detect failed" >&2
    return 1
  }
  printf '%s' "$JOHN_IP" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' || {
    echo "STOP: ssh-nsg-open IP shape invalid" >&2
    return 1
  }
  JOHN_SSH_CIDR="${JOHN_IP}/32"
  export JOHN_SSH_CIDR
  az network nsg rule create \
    --resource-group "$RG" \
    --nsg-name nsg-cosmabot-prod-eus2-01 \
    --name TEMP-JOHN-SSH-SECRETS-INSTALL \
    --priority 200 \
    --direction Inbound \
    --access Allow \
    --protocol Tcp \
    --source-address-prefixes "${JOHN_SSH_CIDR}" \
    --source-port-ranges '*' \
    --destination-address-prefixes '*' \
    --destination-port-ranges 22 \
    --output none || {
    echo "STOP: ssh-nsg-open rule create failed" >&2
    return 1
  }
  echo "PASS: TEMP-JOHN-SSH-SECRETS-INSTALL Allow Tcp/22 from ${JOHN_SSH_CIDR} priority 200"
  return 0
}
