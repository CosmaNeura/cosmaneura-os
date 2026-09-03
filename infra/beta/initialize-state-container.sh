#!/usr/bin/env bash
set -euo pipefail

# Intended for Azure VM Run Command on the protected deployment runner. It
# uses only the attached user-assigned identity and never accepts a key, SAS,
# password, or client secret.

die() {
  printf 'D3 state initialization refused: %s\n' "$1" >&2
  exit 1
}

[[ $# -eq 2 ]] || die "expected STORAGE_ACCOUNT_NAME and DEPLOY_IDENTITY_CLIENT_ID"
storage_account_name="$1"
deploy_identity_client_id="$2"

[[ "$storage_account_name" =~ ^[a-z0-9]{3,24}$ ]] || die "storage account name is invalid"
[[ "$deploy_identity_client_id" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]] || die "deploy identity client ID is invalid"
command -v python3 >/dev/null 2>&1 || die "python3 is required on the protected runner"

python3 - "$storage_account_name" "$deploy_identity_client_id" <<'PY'
import email.utils
import json
import sys
import urllib.error
import urllib.parse
import urllib.request


account, client_id = sys.argv[1:]
query = urllib.parse.urlencode(
    {
        "api-version": "2018-02-01",
        "resource": "https://storage.azure.com/",
        "client_id": client_id,
    }
)
token_request = urllib.request.Request(
    f"http://169.254.169.254/metadata/identity/oauth2/token?{query}",
    headers={"Metadata": "true"},
)
with urllib.request.urlopen(token_request, timeout=10) as response:
    token = json.load(response)["access_token"]

container_url = f"https://{account}.blob.core.windows.net/tfstate?restype=container"
headers = {
    "Authorization": f"Bearer {token}",
    "Content-Length": "0",
    "x-ms-date": email.utils.formatdate(usegmt=True),
    "x-ms-version": "2023-11-03",
}
create_request = urllib.request.Request(
    container_url,
    data=b"",
    headers=headers,
    method="PUT",
)
try:
    with urllib.request.urlopen(create_request, timeout=30) as response:
        if response.status != 201:
            raise RuntimeError(f"unexpected create status {response.status}")
except urllib.error.HTTPError as error:
    if error.code != 409 or error.headers.get("x-ms-error-code") != "ContainerAlreadyExists":
        raise

verify_request = urllib.request.Request(container_url, headers=headers, method="HEAD")
with urllib.request.urlopen(verify_request, timeout=30) as response:
    if response.status != 200:
        raise RuntimeError(f"unexpected verification status {response.status}")

print("D3 private tfstate container is ready through the attached deploy identity")
PY
