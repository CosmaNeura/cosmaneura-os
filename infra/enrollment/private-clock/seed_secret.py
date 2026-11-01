#!/usr/bin/env python3
"""Protected ARM secureString seed; no Key Vault data-plane opening/read."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from database import DATABASE, LOGINS, input_bindings
from prepare import SOURCE_ROOT, private_read, private_write
from scope import NAMES, coordinates
from sqlalchemy.engine import make_url


def seed(f: dict, name: str, value_file: Path, receipt: Path) -> dict:
    if name not in NAMES.values() or receipt.exists() or receipt.is_symlink() or not receipt.is_absolute() or receipt.resolve().is_relative_to(SOURCE_ROOT):
        raise ValueError("allowed enrollment secret and fresh protected receipt path required")
    value = private_read(value_file).decode()
    if not value or len(value.encode()) > 25000 or "\x00" in value:
        raise ValueError("bounded protected secret required")
    slot = next(slot for slot, secret in NAMES.items() if name == secret)
    if slot == "bindings":
        input_bindings(value, f["postgres_fqdn"], f["binding_sha256"])
    else:
        url = make_url(value)
        if (url.drivername != "postgresql+psycopg" or url.host != f["postgres_fqdn"] or url.port != 5432 or url.database != DATABASE
                or url.username != LOGINS[slot] or not url.password or dict(url.query) != {"sslmode": "verify-full", "sslrootcert": "/etc/ssl/certs/ca-certificates.crt"}):
            raise ValueError("bound journal-only role/TLS credential required")
    if any(key in os.environ for key in ("AZURE_CORE_LOG_LEVEL", "AZURE_LOG_LEVEL", "AZURE_HTTP_LOGGING_ENABLED")):
        raise ValueError("credential transport debugging is not permitted")
    # The account is checked without requesting any access-token output.
    account = subprocess.run(["az", "account", "show", "--query", "{id:id,tenantId:tenantId,state:state}", "--output", "json"], check=True, capture_output=True, timeout=30)
    account_info = json.loads(account.stdout)
    if (account_info.get("id") != f["subscription_id"] or account_info.get("tenantId") != f["tenant_id"] or account_info.get("state") != "Enabled"):
        raise ValueError("wrong Azure account")
    with tempfile.TemporaryDirectory(prefix="enrollment-arm-secret-") as directory:
        parameters = Path(directory) / "parameters.json"
        private_write(parameters, json.dumps({"vaultName": {"value": f["key_vault_uri"].split("//")[1].split(".")[0]}, "secretName": {"value": name}, "secretValue": {"value": value}}).encode())
        command = ["az", "deployment", "group", "create", "--subscription", f["subscription_id"], "--resource-group", f["resource_group_name"],
                   "--name", f"private-clock-secret-{uuid.uuid4().hex}", "--template-file", str(Path(__file__).with_name("secret.template.json")),
                   "--parameters", f"@{parameters}", "--only-show-errors", "--output", "none"]
        # Capture both streams. Never forward a server/CLI error that might echo
        # secure input. ARM records this parameter as secureString, not string.
        subprocess.run(command, check=True, capture_output=True, timeout=300)
    result = subprocess.run(["az", "resource", "show", "--ids", f"{f['key_vault_id']}/secrets/{name}", "--api-version", "2024-11-01",
                             "--query", "properties.secretUriWithVersion", "--only-show-errors", "--output", "tsv"], check=True, capture_output=True, timeout=30)
    reference = result.stdout.decode().strip()
    if not re.fullmatch(re.escape(f"{f['key_vault_uri']}secrets/{name}/") + r"[0-9a-f]{32}", reference):
        raise ValueError("exact versioned ARM secret reference unavailable")
    public_receipt = {"contract_version": "enrollment-private-clock-secret-reference.v1", "secret_name": name, "reference": reference, "value_returned": False}
    private_write(receipt, json.dumps(public_receipt, sort_keys=True).encode())
    return public_receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coordinates", type=Path, required=True)
    parser.add_argument("--secret-name", choices=sorted(NAMES.values()), required=True)
    parser.add_argument("--value-file", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(seed(coordinates(private_read(args.coordinates)), args.secret_name, args.value_file, args.receipt), sort_keys=True))
        return 0
    except Exception as error:
        print(json.dumps({"error": "private_clock_secret_seed_failed", "class": type(error).__name__}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
