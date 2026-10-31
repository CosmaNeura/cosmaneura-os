"""Operator-only ARM secureString seed into the selected synthetic Box vault."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

from prepare import read_private, write_private
from sqlalchemy.engine import make_url

NAMES = {
    "database-url",
    "database-admin-url",
    "redis-url",
    "enrollment-admission-key",
    "owner-manifest",
}


def validate_value(deployment: dict, practice: str, name: str, value: str) -> None:
    """Reject wrong-Box/central credentials before invoking even Azure metadata."""
    selected = deployment["practices"][practice]
    namespace = deployment["namespace"]
    if name == "enrollment-admission-key":
        valid = re.fullmatch(r"[0-9a-f]{64}", value) is not None
    elif name == "owner-manifest":
        manifest = json.loads(value)
        plan = selected["plan"]
        valid = (
            hashlib.sha256(value.encode()).hexdigest() == selected["owner_manifest_sha256"]
            and manifest.get("schema_version") == "cosmas-os/d3-beta-bootstrap/v1"
            and all(
                manifest.get(key) == plan[field]
                for key, field in (
                    ("box_id", "box_id"),
                    ("clerk_subject", "owner_subject"),
                    ("clerk_issuer", "issuer"),
                    ("clerk_organization_id", "organization_id"),
                )
            )
        )
    else:
        url = make_url(value)
        if name == "redis-url":
            valid = (
                url.drivername == "rediss"
                and not url.username
                and bool(url.password)
                and url.port == 10000
                and url.database == "0"
                and re.fullmatch(
                    rf"redis-cews-stg-{namespace}-{practice}\.[a-z0-9.-]+\.redis\.azure\.net",
                    url.host or "",
                )
                and dict(url.query) == {"ssl_cert_reqs": "required"}
            )
        else:
            login = "box_bootstrap" if name == "database-admin-url" else "box_runtime"
            valid = (
                url.drivername == "postgresql+psycopg"
                and url.username == login
                and bool(url.password)
                and url.host == f"psql-cews-stg-{namespace}-{practice}.postgres.database.azure.com"
                and url.port == 5432
                and url.database == "cosmas_os"
                and dict(url.query) == {"sslmode": "verify-full", "sslrootcert": "system"}
            )
    if not valid:
        raise ValueError("exact protected Box secret required")


def seed(deployment: dict, practice: str, name: str, value_file: Path, output: Path) -> dict:
    if (
        deployment.get("environment") != "staging"
        or deployment.get("synthetic_only") is not True
        or deployment.get("rendered_only") is not True
        or not re.fullmatch(r"[a-z0-9]{6,8}", deployment.get("namespace", ""))
        or practice not in {"a", "b"}
        or name not in NAMES
        or not output.is_absolute()
        or output.exists()
    ):
        raise ValueError("prepared synthetic Box required")
    foundation = deployment["foundation"]
    group = foundation["resource_group_name"]
    if not re.fullmatch(r"rg-cosmabot-enrollment-staging-[a-z0-9]{6,8}", group):
        raise ValueError("owned staging foundation required")
    vault = f"kv-cews-{deployment['namespace']}-{practice}"
    value = read_private(value_file).decode()
    # The existing protected provisioner writes one final LF. Normalize only
    # that framing byte for derived keys; owner manifests remain byte-exact.
    if name == "enrollment-admission-key" and value.endswith("\n"):
        value = value[:-1]
    if not value or len(value.encode()) > 25000 or "\x00" in value:
        raise ValueError("bounded protected value required")
    validate_value(deployment, practice, name, value)
    if any(
        key in os.environ
        for key in ("AZURE_CORE_LOG_LEVEL", "AZURE_LOG_LEVEL", "AZURE_HTTP_LOGGING_ENABLED")
    ):
        raise ValueError("credential transport logging refused")
    account = subprocess.run(
        [
            "az",
            "account",
            "show",
            "--query",
            "{id:id,tenantId:tenantId,state:state}",
            "--output",
            "json",
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    if json.loads(account.stdout) != {
        "id": foundation["subscription_id"],
        "tenantId": foundation["tenant_id"],
        "state": "Enabled",
    }:
        raise ValueError("wrong Azure context")
    with tempfile.TemporaryDirectory(prefix="cosmabot-box-secret-") as directory:
        parameters = Path(directory) / "parameters.json"
        write_private(
            parameters,
            json.dumps(
                {
                    "vaultName": {"value": vault},
                    "secretName": {"value": name},
                    "secretValue": {"value": value},
                }
            ).encode(),
        )
        subprocess.run(
            [
                "az",
                "deployment",
                "group",
                "create",
                "--subscription",
                foundation["subscription_id"],
                "--resource-group",
                group,
                "--name",
                "box-secret-" + uuid4().hex,
                "--template-file",
                str(Path(__file__).with_name("secret.template.json")),
                "--parameters",
                "@" + str(parameters),
                "--only-show-errors",
                "--output",
                "none",
            ],
            check=True,
            capture_output=True,
            timeout=300,
        )
    secret_id = f"/subscriptions/{foundation['subscription_id']}/resourceGroups/{group}/providers/Microsoft.KeyVault/vaults/{vault}/secrets/{name}"
    response = subprocess.run(
        [
            "az",
            "resource",
            "show",
            "--ids",
            secret_id,
            "--api-version",
            "2024-11-01",
            "--query",
            "properties.secretUriWithVersion",
            "--only-show-errors",
            "--output",
            "tsv",
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    reference = response.stdout.decode().strip()
    if not re.fullmatch(
        rf"https://{vault}\.vault\.azure\.net/secrets/{name}/[0-9a-f]{{32}}", reference
    ):
        raise ValueError("exact versioned reference unavailable")
    receipt = {
        "practice": practice,
        "secret_name": name,
        "reference": reference,
        "value_returned": False,
    }
    write_private(output, json.dumps(receipt, sort_keys=True).encode())
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployment", type=Path, required=True)
    parser.add_argument("--practice", choices=["a", "b"], required=True)
    parser.add_argument("--secret-name", choices=sorted(NAMES), required=True)
    parser.add_argument("--value-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(
            json.dumps(
                seed(
                    json.loads(read_private(args.deployment)),
                    args.practice,
                    args.secret_name,
                    args.value_file,
                    args.output,
                ),
                sort_keys=True,
            )
        )
        return 0
    except Exception as error:
        print(
            json.dumps({"error": "workspace_secret_seed_failed", "class": type(error).__name__}),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
