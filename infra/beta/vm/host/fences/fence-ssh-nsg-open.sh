cosmabot_ssh_nsg_open() {
  command -v az >/dev/null || {
    echo "STOP: ssh-nsg-open needs az" >&2
    return 1
  }
  command -v curl >/dev/null || {
    echo "STOP: ssh-nsg-open needs curl" >&2
    return 1
  }
  command -v jq >/dev/null || {
    echo "STOP: ssh-nsg-open needs jq (preflight before open)" >&2
    return 1
  }
  jq -n 'true' >/dev/null 2>&1 || {
    echo "STOP: ssh-nsg-open needs working jq (preflight before open)" >&2
    return 1
  }
  command -v python3 >/dev/null || {
    echo "STOP: ssh-nsg-open needs python3 (preflight before open)" >&2
    return 1
  }
  command -v ssh >/dev/null || {
    echo "STOP: ssh-nsg-open needs ssh (preflight before open)" >&2
    return 1
  }
  command -v sha256sum >/dev/null || {
    echo "STOP: ssh-nsg-open needs sha256sum (preflight before open)" >&2
    return 1
  }
  command -v install >/dev/null || {
    echo "STOP: ssh-nsg-open needs install (preflight before open)" >&2
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
  test -n "${SECRETS_TRANSPORT_PY:-}" || {
    echo "STOP: ssh-nsg-open SECRETS_TRANSPORT_PY unset (preflight before open)" >&2
    return 1
  }
  test -f "$SECRETS_TRANSPORT_PY" || {
    echo "STOP: ssh-nsg-open SECRETS_TRANSPORT_PY missing (preflight before open)" >&2
    return 1
  }
  test -n "${ADMIN_USERNAME:-}" || {
    echo "STOP: ssh-nsg-open ADMIN_USERNAME unset - export reviewed admin_username" >&2
    return 1
  }
  test -n "${SSH_IDENTITY_PATH:-}" || {
    echo "STOP: ssh-nsg-open SSH_IDENTITY_PATH unset - export private key path matching admin_ssh_public_key" >&2
    return 1
  }
  test -f "$SSH_IDENTITY_PATH" || {
    echo "STOP: ssh-nsg-open SSH_IDENTITY_PATH missing" >&2
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
