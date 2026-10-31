#!/usr/bin/env python3
"""Private staging foundation bootstrap. No cloud command runs during prepare.

Plan/apply are explicit operator subcommands. Passwords are read into a child's
ephemeral environment, never arguments, JSON state, stdout or plan receipts.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote

from scope import DATABASE, LOGINS, NAMES, coordinates, foundation

SOURCE = Path(__file__).resolve().parent
SOURCE_ROOT = SOURCE.parents[2] if SOURCE.parent.name == "enrollment" and SOURCE.parent.parent.name == "infra" else SOURCE
PUBLIC_KEYS = {"subscription_id", "tenant_id", "resource_name_suffix", "foundation_file"}
OPTIONAL_KEYS = {"operation", "create_job", "image", "secret_references", "runtime_principal_ids"}
INPUT_KEYS = PUBLIC_KEYS | OPTIONAL_KEYS | {"binding_sha256"}


def private_read(path: Path, limit: int = 65536) -> bytes:
    if not path.is_absolute() or path.resolve().is_relative_to(SOURCE_ROOT):
        raise ValueError("protected absolute file outside source required")
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
    if not path.is_absolute() or path.resolve().is_relative_to(SOURCE_ROOT):
        raise ValueError("protected absolute output outside source required")
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
    files = sorted(SOURCE.glob("*.tf")) + [SOURCE / name for name in (".terraform.lock.hcl", "prepare.py", "scope.py", "database.py", "seed_secret.py", "prepare_bindings.py", "secret.template.json", "Dockerfile")]
    if any(SOURCE.glob("*.tf.json")) or any(SOURCE.glob("*.tofu*")) or any(SOURCE.glob("*.auto.tfvars*")) or any(SOURCE.glob("*override.tf*")):
        raise ValueError("unreviewed automatic Terraform configuration")
    return files


def fingerprint(files: list[Path]) -> dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def public_job_config(values: dict, f: dict) -> None:
    operation = values.get("operation", "check")
    create = values.get("create_job", False)
    references, image = values.get("secret_references", {}), values.get("image", "")
    principals = values.get("runtime_principal_ids", {})
    if operation not in {"bootstrap", "check"} or type(create) is not bool or not isinstance(references, dict) or not isinstance(principals, dict):
        raise ValueError("bounded public job configuration required")
    hashes = values.get("binding_sha256", {})
    if (not isinstance(hashes, dict) or hashes and (set(hashes) != {"a", "b"} or len(set(hashes.values())) != 2
            or any(not isinstance(h, str) or not re.fullmatch(r"[0-9a-f]{64}", h) for h in hashes.values()))
            or not hashes and (create or principals)):
        raise ValueError("closed capacity may be unbound; jobs/grants require two frozen binding hashes")
    selected = set(NAMES) if operation == "bootstrap" else {"a", "b", "bindings"}
    if create:
        if (not isinstance(image, str) or not re.fullmatch(re.escape(f["registry_server"])+r"/[a-z0-9/_-]+@sha256:[0-9a-f]{64}", image)
                or set(references) != selected or any(not isinstance(ref, str) or not re.fullmatch(re.escape(f"{f['key_vault_uri']}secrets/{NAMES[slot]}/")+r"[0-9a-f]{32}", ref) for slot, ref in references.items())):
            raise ValueError("exact owned image and versioned journal-only references required")
    elif references or image != "":
        raise ValueError("closed resource preparation contains no image or secret references")
    if (set(principals) - {"a", "b"} or any(not isinstance(id, str) or not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", id) for id in principals.values())
            or len(set(principals.values())) != len(principals)):
        raise ValueError("distinct reviewed composition workload principals required")


def prepare(inputs: Path, directory: Path) -> dict[str, object]:
    if not directory.is_absolute() or directory.exists() or directory.is_symlink():
        raise ValueError("fresh absolute bootstrap directory required")
    repo = SOURCE_ROOT
    if directory.resolve().is_relative_to(repo):
        raise ValueError("bootstrap credentials/state must remain outside the repository")
    values = json.loads(private_read(inputs))
    if not isinstance(values, dict) or not PUBLIC_KEYS.issubset(values) or set(values) - INPUT_KEYS:
        raise ValueError("only reviewed public private-journal inputs are accepted")
    fraw = private_read(Path(values["foundation_file"]))
    f = foundation(fraw)
    if f["subscription_id"] != values["subscription_id"] or f["tenant_id"] != values["tenant_id"] or not re.fullmatch(r"[a-z0-9]{6,8}", values["resource_name_suffix"]):
        raise ValueError("exact owned staging foundation and fresh suffix required")
    values.setdefault("binding_sha256", {})
    public_job_config(values, f)
    # No binding documents, customer IDs, URLs with credentials or secret values enter this file.
    directory.mkdir(mode=0o700)
    module = directory / "module"
    module.mkdir(mode=0o700)
    files = source_files()
    for p in files:
        private_write(module / p.name, p.read_bytes())
    private_write(directory / "foundation.json", fraw)
    values["foundation_file"] = str(directory / "foundation.json")
    private_write(directory / "inputs.tfvars.json", json.dumps(values, sort_keys=True).encode())
    private_write(directory / "encryption.passphrase", secrets.token_urlsafe(64).encode())
    for role in LOGINS:
        private_write(directory / f"{role}.password", (secrets.token_urlsafe(48) + "Aa1_").encode())
    private_write(directory / "backend.hcl", f"path = {json.dumps(str(directory / 'private-clock.tfstate'))}\n".encode())
    tofu = shutil.which("tofu")
    if not tofu:
        raise ValueError("OpenTofu 1.12.5 required")
    receipt = {"contract_version": "enrollment-private-clock-bootstrap.v1", "source": fingerprint(files),
               "inputs_sha256": hashlib.sha256(private_read(directory / "inputs.tfvars.json")).hexdigest(),
               "foundation_sha256": hashlib.sha256(fraw).hexdigest(),
               "backend_sha256": hashlib.sha256(private_read(directory / "backend.hcl")).hexdigest(),
               "custody_sha256": {name: hashlib.sha256(private_read(directory / name)).hexdigest() for name in ("encryption.passphrase", "admin.password", "a.password", "b.password")},
               "tofu_sha256": hashlib.sha256(Path(tofu).read_bytes()).hexdigest(), "applied": False}
    private_write(directory / "bootstrap.json", json.dumps(receipt, sort_keys=True).encode())
    return {"prepared": True, "applied": False, "source_files": len(files)}


def child_environment(directory: Path) -> dict[str, str]:
    if not directory.is_absolute() or directory.is_symlink() or directory.resolve() != directory or directory.stat().st_uid != os.getuid() or stat.S_IMODE(directory.stat().st_mode) != 0o700:
        raise ValueError("protected bootstrap directory required")
    if any(k.startswith(("TF_", "ARM_", "TOFU_")) or k in {"AZURE_CONFIG_DIR", "AZURE_CORE_LOG_LEVEL", "AZURE_LOG_LEVEL", "AZURE_HTTP_LOGGING_ENABLED"} for k in os.environ):
        raise ValueError("ambient Terraform/Azure overrides are not accepted")
    receipt = json.loads(private_read(directory / "bootstrap.json"))
    module = directory / "module"
    if module.is_symlink() or stat.S_IMODE(module.stat().st_mode) != 0o700 or {p.name for p in module.iterdir()} != {p.name for p in source_files()}:
        raise ValueError("unreviewed snapshot contents")
    if receipt.get("source") != fingerprint(source_files()) or receipt.get("source") != fingerprint([directory / "module" / p.name for p in source_files()]):
        raise ValueError("source changed; prepare a new reviewed bootstrap")
    values = json.loads(private_read(directory / "inputs.tfvars.json"))
    if not PUBLIC_KEYS.issubset(values) or set(values) - INPUT_KEYS or receipt.get("inputs_sha256") != hashlib.sha256(private_read(directory / "inputs.tfvars.json")).hexdigest():
        raise ValueError("bootstrap public inputs changed")
    if receipt.get("foundation_sha256") != hashlib.sha256(private_read(directory / "foundation.json")).hexdigest() or receipt.get("backend_sha256") != hashlib.sha256(private_read(directory / "backend.hcl")).hexdigest():
        raise ValueError("private scope or backend changed")
    if receipt.get("custody_sha256") != {name: hashlib.sha256(private_read(directory / name)).hexdigest() for name in ("encryption.passphrase", "admin.password", "a.password", "b.password")}:
        raise ValueError("protected key or role credential custody changed")
    private_read(directory / "encryption.passphrase")
    password = private_read(directory / "admin.password").decode()
    return {**os.environ, "TF_DATA_DIR": str(directory / "provider-data"), "TF_INPUT": "0", "TF_WORKSPACE": "default",
            "TF_VAR_bootstrap_key_file": str(directory / "encryption.passphrase"), "TF_VAR_postgres_admin_password": password,
            "ARM_USE_CLI": "true", "ARM_USE_MSI": "false", "ARM_USE_OIDC": "false"}


def configure_job(directory: Path, config: Path) -> dict[str, object]:
    """Explicit reviewed job-only revision; preserve server scope, key and passwords."""
    child_environment(directory)
    update = json.loads(private_read(config))
    if not isinstance(update, dict) or set(update) not in (OPTIONAL_KEYS, OPTIONAL_KEYS | {"binding_sha256"}):
        raise ValueError("exact public job-only configuration required")
    old_inputs = private_read(directory / "inputs.tfvars.json")
    old_receipt = private_read(directory / "bootstrap.json")
    values, receipt = json.loads(old_inputs), json.loads(old_receipt)
    if values.get("binding_sha256") and "binding_sha256" in update and update["binding_sha256"] != values["binding_sha256"]:
        raise ValueError("protected binding hashes are frozen; no rebinding or removal")
    values.update(update)
    public_job_config(values, foundation(private_read(directory / "foundation.json")))
    raw = json.dumps(values, sort_keys=True).encode()
    receipt["inputs_sha256"] = hashlib.sha256(raw).hexdigest()
    receipt["configuration_revision"] = receipt.get("configuration_revision", 0) + 1
    # A torn revision fails the input/receipt hash fence and cannot run a plan/apply.
    archive = directory / f"configuration-{uuid.uuid4().hex}"
    archive.mkdir(mode=0o700)
    private_write(archive / "inputs.json", old_inputs)
    private_write(archive / "receipt.json", old_receipt)
    for name, data in (("inputs.tfvars.json", raw), ("bootstrap.json", json.dumps(receipt, sort_keys=True).encode())):
        temp = directory / f".{uuid.uuid4().hex}"
        private_write(temp, data)
        os.replace(temp, directory / name)
    (directory / "private-clock.tfplan").unlink(missing_ok=True)
    return {"configured": True, "revision": receipt["configuration_revision"], "applied": False, "hosted_qualified": False}


@contextmanager
def operator_lock(directory: Path):
    # One private operator process at a time; shared files/plan cannot race configure.
    child_environment(directory)
    fd = os.open(directory / "operator.lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError("protected operation lock required")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


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
    plan = directory / "private-clock.tfplan"
    values = json.loads(private_read(directory / "inputs.tfvars.json"))
    if operation == "review-plan":
        if not output or not output.is_absolute() or output.exists() or output.resolve().is_relative_to(SOURCE_ROOT):
            raise ValueError("fresh protected public review path required")
        digest = hashlib.sha256(private_read(plan, 32 * 1024 * 1024)).hexdigest()
        shown = subprocess.run([tofu, "show", "-json", str(plan)], cwd=module, env=env, check=True, capture_output=True, timeout=60)
        body = json.loads(shown.stdout)
        review = {"contract_version": "enrollment-private-clock-plan-review.v1", "plan_sha256": digest,
            "source": receipt["source"], "inputs_sha256": receipt["inputs_sha256"], "hosted_qualified": False,
            "changes": [{"address": r["address"], "type": r["type"], "actions": r["change"]["actions"]} for r in body.get("resource_changes", [])]}
        private_write(output, json.dumps(review, sort_keys=True).encode())
        return {"reviewed": True, "plan_sha256": digest, "hosted_qualified": False}
    if operation == "export":
        if not output or not output.is_absolute() or output.exists() or output.resolve().is_relative_to(SOURCE_ROOT) or not (directory / "private-clock.tfstate").exists():
            raise ValueError("actual local state and a fresh protected output outside the repository required")
        response = subprocess.run([tofu, "output", "-json", "private_clock"], cwd=module, env=env, check=True, capture_output=True, timeout=30)
        c = coordinates(response.stdout)
        if (c["postgres_fqdn"] != f"psql-cbot-clock-stg-{values['resource_name_suffix']}.postgres.database.azure.com"
                or c["subscription_id"] != values["subscription_id"] or c["tenant_id"] != values["tenant_id"]
                or c["binding_sha256"] != values["binding_sha256"]):
            raise ValueError("local state does not match the reviewed private journal")
        private_write(output, json.dumps(c, sort_keys=True).encode())
        return {"exported": True, "hosted_qualified": False}
    account = subprocess.run(["az", "account", "show", "--query", "{id:id,tenantId:tenantId,state:state}", "--output", "json"], check=True, capture_output=True, timeout=30)
    account_info = json.loads(account.stdout)
    if account_info != {"id": values["subscription_id"], "tenantId": values["tenant_id"], "state": "Enabled"}:
        raise ValueError("wrong Azure subscription/tenant")
    if not (directory / "private-clock.tfstate").exists():
        f = foundation(private_read(directory / "foundation.json"))
        existing = subprocess.run(["az", "resource", "list", "--subscription", values["subscription_id"], "--resource-group", f["resource_group_name"],
            "--query", f"[?name == 'psql-cbot-clock-stg-{values['resource_name_suffix']}' || name == 'clock-{values['resource_name_suffix']}.postgres.database.azure.com'].id", "--output", "json"],
            check=True, capture_output=True, timeout=30)
        if json.loads(existing.stdout):
            raise ValueError("fresh journal names required; do not adopt existing resources")
    if operation == "apply":
        if not plan_sha256 or len(plan_sha256) != 64 or hashlib.sha256(private_read(plan, 32 * 1024 * 1024)).hexdigest() != plan_sha256:
            raise ValueError("reviewed encrypted plan SHA-256 required")
        command = [tofu, "apply", "-input=false", str(plan)]
    else:
        subprocess.run([tofu, "init", "-reconfigure", "-input=false", "-lockfile=readonly", f"-backend-config={directory / 'backend.hcl'}"], cwd=module, env=env, check=True, capture_output=True, timeout=300, umask=0o077)
        command = [tofu, "plan", "-input=false", f"-var-file={directory / 'inputs.tfvars.json'}", f"-out={plan}"]
    # Capture every provider stream; never forward an error or credential-shaped payload.
    subprocess.run(command, cwd=module, env=env, check=True, capture_output=True, timeout=1800, umask=0o077)
    if plan.exists():
        os.chmod(plan, 0o600)
    for state in directory.glob("private-clock.tfstate*"):
        os.chmod(state, 0o600)
    return {"operation": operation, "plan_sha256": hashlib.sha256(private_read(plan, 32 * 1024 * 1024)).hexdigest(), "applied": operation == "apply"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["prepare", "plan", "review-plan", "apply", "export", "urls", "configure-job"])
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
            with operator_lock(args.directory):
                if args.operation == "configure-job":
                    if not args.inputs:
                        raise ValueError("reviewed job-only inputs required")
                    result = configure_job(args.directory, args.inputs)
                elif args.operation == "urls":
                    values = json.loads(private_read(args.directory / "inputs.tfvars.json"))
                    host = f"psql-cbot-clock-stg-{values['resource_name_suffix']}.postgres.database.azure.com"
                    if any((args.directory / f"{role}.url").exists() or (args.directory / f"{role}.url").is_symlink() for role in LOGINS):
                        raise ValueError("fresh protected credential URL outputs required")
                    for role, login in LOGINS.items():
                        password = private_read(args.directory / f"{role}.password").decode()
                        url = f"postgresql+psycopg://{login}:{quote(password, safe='')}@{host}:5432/{DATABASE}?sslmode=verify-full&sslrootcert=/etc/ssl/certs/ca-certificates.crt"
                        private_write(args.directory / f"{role}.url", url.encode())
                    result = {"credential_files_prepared": True, "seeded": False, "hosted_qualified": False}
                else:
                    result = execute(args.directory, args.operation, args.plan_sha256, args.output)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as error:
        # No input/credential/database exception content enters operator logs.
        print(json.dumps({"error": "private_clock_operation_failed", "class": type(error).__name__}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
