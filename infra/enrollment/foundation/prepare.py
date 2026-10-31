#!/usr/bin/env python3
"""Private staging foundation bootstrap. No cloud command runs during prepare.

Plan/apply are explicit operator subcommands. Passwords are read into a child's
ephemeral environment, never arguments, JSON state, stdout or plan receipts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import stat
import subprocess
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parent
PUBLIC_KEYS = {
    "subscription_id", "tenant_id", "resource_name_suffix", "vnet_address_prefix",
    "release_operator_object_id", "state_operator_ipv4",
}


def private_read(path: Path, limit: int = 65536) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > limit:
            raise ValueError("protected regular 0600 owner file required")
        chunks = []
        remaining = info.st_size
        while remaining:
            chunk = os.read(fd, min(remaining, 65536))
            if not chunk:
                raise ValueError("protected file changed while reading")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def private_write(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def source_files() -> list[Path]:
    files = sorted(SOURCE.glob("*.tf")) + [SOURCE / ".terraform.lock.hcl", SOURCE / "prepare.py"]
    if any(SOURCE.glob("*.tf.json")) or any(SOURCE.glob("*.tofu")) or any(SOURCE.glob("*.auto.tfvars*")) or any(SOURCE.glob("*override.tf*")):
        raise ValueError("unreviewed automatic Terraform configuration")
    return files


def fingerprint(files: list[Path]) -> dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def prepare(inputs: Path, directory: Path) -> dict[str, object]:
    if not directory.is_absolute() or directory.exists() or directory.is_symlink():
        raise ValueError("fresh absolute bootstrap directory required")
    repo = SOURCE.parents[2]
    if directory.resolve().is_relative_to(repo):
        raise ValueError("bootstrap credentials/state must remain outside the repository")
    values = json.loads(private_read(inputs))
    if not isinstance(values, dict) or set(values) != PUBLIC_KEYS or any(not isinstance(v, str) for v in values.values()):
        raise ValueError("only the six reviewed public foundation inputs are accepted")
    # Terraform validates actual CIDR, namespace and object IDs before planning.
    directory.mkdir(mode=0o700)
    module = directory / "module"
    module.mkdir(mode=0o700)
    files = source_files()
    for p in files:
        private_write(module / p.name, p.read_bytes())
    private_write(directory / "inputs.tfvars.json", json.dumps(values, sort_keys=True).encode())
    private_write(directory / "encryption.passphrase", secrets.token_urlsafe(64).encode())
    private_write(directory / "postgres-admin.password", (secrets.token_urlsafe(48) + "Aa1_").encode())
    private_write(directory / "backend.hcl", f"path = {json.dumps(str(directory / 'foundation.tfstate'))}\n".encode())
    tofu = shutil.which("tofu")
    if not tofu:
        raise ValueError("OpenTofu 1.12.5 required")
    receipt = {"contract_version": "enrollment-foundation-bootstrap.v1", "source": fingerprint(files),
               "inputs_sha256": hashlib.sha256(private_read(directory / "inputs.tfvars.json")).hexdigest(),
               "tofu_sha256": hashlib.sha256(Path(tofu).read_bytes()).hexdigest(), "applied": False}
    private_write(directory / "bootstrap.json", json.dumps(receipt, sort_keys=True).encode())
    return {"prepared": True, "applied": False, "source_files": len(files)}


def child_environment(directory: Path) -> dict[str, str]:
    if not directory.is_absolute() or directory.is_symlink() or stat.S_IMODE(directory.stat().st_mode) != 0o700:
        raise ValueError("protected bootstrap directory required")
    if any(k.startswith(("TF_", "ARM_")) or k in {"TOFU_ENCRYPTION", "AZURE_CONFIG_DIR"} for k in os.environ):
        raise ValueError("ambient Terraform/Azure overrides are not accepted")
    receipt = json.loads(private_read(directory / "bootstrap.json"))
    if receipt.get("source") != fingerprint(source_files()) or receipt.get("source") != fingerprint([directory / "module" / p.name for p in source_files()]):
        raise ValueError("source changed; prepare a new reviewed bootstrap")
    values = json.loads(private_read(directory / "inputs.tfvars.json"))
    if set(values) != PUBLIC_KEYS or receipt.get("inputs_sha256") != hashlib.sha256(private_read(directory / "inputs.tfvars.json")).hexdigest():
        raise ValueError("bootstrap public inputs changed")
    private_read(directory / "encryption.passphrase")
    password = private_read(directory / "postgres-admin.password").decode()
    return {**os.environ, "TF_DATA_DIR": str(directory / "provider-data"), "TF_INPUT": "0", "TF_WORKSPACE": "default",
            "TF_VAR_bootstrap_key_file": str(directory / "encryption.passphrase"), "TF_VAR_postgres_admin_password": password,
            "ARM_USE_CLI": "true", "ARM_USE_MSI": "false", "ARM_USE_OIDC": "false"}


def execute(directory: Path, operation: str, plan_sha256: str | None = None, output: Path | None = None) -> dict[str, object]:
    env = child_environment(directory)
    tofu = shutil.which("tofu")
    if not tofu:
        raise ValueError("OpenTofu 1.12.5 required")
    receipt = json.loads(private_read(directory / "bootstrap.json"))
    if receipt.get("tofu_sha256") != hashlib.sha256(Path(tofu).read_bytes()).hexdigest():
        raise ValueError("OpenTofu executable changed since preparation")
    version = subprocess.run([tofu, "version", "-json"], capture_output=True, check=True, timeout=20)
    if json.loads(version.stdout)["terraform_version"] != "1.12.5":
        raise ValueError("OpenTofu 1.12.5 required")
    module = directory / "module"
    plan = directory / "foundation.tfplan"
    values = json.loads(private_read(directory / "inputs.tfvars.json"))
    if operation == "export":
        if not output or not output.is_absolute() or output.exists() or output.resolve().is_relative_to(SOURCE.parents[2]) or not (directory / "foundation.tfstate").exists():
            raise ValueError("actual local state and a fresh protected output outside the repository required")
        response = subprocess.run([tofu, "output", "-json", "foundation"], cwd=module, env=env, check=True, capture_output=True, timeout=30)
        coordinates = json.loads(response.stdout)
        if (coordinates.get("contract_version") != "enrollment-foundation.v1" or coordinates.get("environment") != "staging"
                or coordinates.get("resource_group_name") != f"rg-cosmabot-enrollment-staging-{values['resource_name_suffix']}"
                or coordinates.get("subscription_id") != values["subscription_id"] or coordinates.get("tenant_id") != values["tenant_id"]):
            raise ValueError("local state does not match the reviewed enrollment foundation")
        private_write(output, json.dumps(coordinates, sort_keys=True).encode())
        return {"exported": True, "application_deployed": False, "qualified": False}
    account = subprocess.run(["az", "account", "show", "--query", "{id:id,tenantId:tenantId,state:state}", "--output", "json"], check=True, capture_output=True, timeout=30)
    account_info = json.loads(account.stdout)
    if account_info != {"id": values["subscription_id"], "tenantId": values["tenant_id"], "state": "Enabled"}:
        raise ValueError("wrong Azure subscription/tenant")
    if not (directory / "foundation.tfstate").exists():
        group = subprocess.run(["az", "group", "exists", "--subscription", values["subscription_id"], "--name", f"rg-cosmabot-enrollment-staging-{values['resource_name_suffix']}"], check=True, capture_output=True, timeout=30)
        if group.stdout.strip() != b"false":
            raise ValueError("initial enrollment resource group already exists; do not adopt it")
    if operation == "apply":
        if not plan_sha256 or len(plan_sha256) != 64 or hashlib.sha256(private_read(plan, 32 * 1024 * 1024)).hexdigest() != plan_sha256:
            raise ValueError("reviewed encrypted plan SHA-256 required")
        command = [tofu, "apply", "-input=false", str(plan)]
    else:
        subprocess.run([tofu, "init", "-reconfigure", "-input=false", "-lockfile=readonly", f"-backend-config={directory / 'backend.hcl'}"], cwd=module, env=env, check=True, timeout=300, umask=0o077)
        command = [tofu, "plan", "-input=false", f"-var-file={directory / 'inputs.tfvars.json'}", f"-out={plan}"]
    # OpenTofu redacts sensitive ephemeral values. Do not enable debug logs.
    subprocess.run(command, cwd=module, env=env, check=True, timeout=1800, umask=0o077)
    if plan.exists():
        os.chmod(plan, 0o600)
    for state in directory.glob("foundation.tfstate*"):
        os.chmod(state, 0o600)
    return {"operation": operation, "plan_sha256": hashlib.sha256(private_read(plan, 32 * 1024 * 1024)).hexdigest(), "applied": operation == "apply"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["prepare", "plan", "apply", "export"])
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--inputs", type=Path)
    parser.add_argument("--plan-sha256")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.operation == "prepare":
            if not args.inputs:
                raise ValueError("reviewed public input file required")
            result = prepare(args.inputs, args.directory)
        else:
            result = execute(args.directory, args.operation, args.plan_sha256, args.output)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as error:
        # No input/credential/database exception content enters operator logs.
        print(json.dumps({"error": "foundation_operation_failed", "class": type(error).__name__}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
