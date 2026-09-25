"""Prepare and plan a fresh encrypted local VM foundation; never apply resources."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import subprocess
import sys

MODULE = Path(__file__).resolve().parent
REPO = MODULE.parents[3]
NAMESPACE = "cosmabot-vm/eastus2/lab01/local-initial"
RESOURCE_GROUP = "rg-cosmas-os-vm-staging-eus2-lab01"
TOFU_VERSION = "1.12.5"
REQUIRED = {
    "subscription_id", "tenant_id", "resource_name_suffix", "vnet_address_prefix",
    "admin_username", "admin_ssh_public_key", "release_operator_object_id", "alert_contact_email",
}
OPTIONAL = {"location", "ubuntu_image_version"}
PROTECTED_FILES = {"inputs.json", "backend.hcl", "tofurc", "encryption.passphrase"}


class Refused(RuntimeError):
    pass


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_bytes(value) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def secure_file(path: Path) -> None:
    value = path.lstat()
    if not stat.S_ISREG(value.st_mode) or value.st_uid != os.getuid() or value.st_nlink != 1 or stat.S_IMODE(value.st_mode) != 0o600:
        raise Refused("Private bootstrap file ownership or mode is invalid")


def write_private(path: Path, value: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())


def private_directory(path: Path, *, fresh=False) -> Path:
    if not path.is_absolute() or path.resolve() != path or path.is_relative_to(REPO):
        raise Refused("Use an absolute canonical private directory outside the repository")
    if fresh:
        path.mkdir(mode=0o700, parents=False, exist_ok=False)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise Refused("Bootstrap directory must be owned by the operator with mode 0700")
    return path


def read_json(path: Path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise Refused("Duplicate JSON fields are refused")
            result[key] = value
        return result
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
        raise Refused("Use one bounded regular JSON input")
    return json.loads(path.read_text(), object_pairs_hook=unique)


def source_manifest() -> dict[str, str]:
    files = sorted([*MODULE.glob("*.tf"), MODULE / ".terraform.lock.hcl", MODULE / "bootstrap_local.py"])
    for path in MODULE.iterdir():
        if path.name.endswith((".tf.json", ".tofu", ".tofu.json", ".tfvars", ".tfvars.json")):
            raise Refused("Unreviewed alternate configuration or automatic variable file in foundation source")
    if any(path.is_symlink() or not path.is_file() for path in files):
        raise Refused("Foundation source must consist of regular reviewed files")
    return {path.name: digest(path) for path in files}


def fingerprint() -> dict:
    files = source_manifest()
    return {"source_sha256": hashlib.sha256(json_bytes(files)).hexdigest(), "lock_sha256": files[".terraform.lock.hcl"], "files": files}


def clean_environment() -> dict[str, str]:
    if any(key.startswith(("TF_", "ARM_")) for key in os.environ) or "AZURE_CONFIG_DIR" in os.environ:
        raise Refused("Remove ambient TF/ARM overrides and AZURE_CONFIG_DIR; use the current owner CLI context")
    return dict(os.environ)


def command(argv, *, env, cwd=None, timeout=120):
    return subprocess.run(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout, check=False, umask=0o077)


def owner_context(env: dict, inputs: dict) -> dict:
    result = command(["az", "account", "show", "--output", "json", "--only-show-errors"], env=env)
    if result.returncode:
        raise Refused("Cannot verify the current owner Azure CLI context")
    account = json.loads(result.stdout)
    user = account.get("user", {})
    if (account.get("state") != "Enabled" or user.get("type") != "user" or not user.get("name")
            or str(account.get("id", "")).lower() != inputs["subscription_id"].lower()
            or str(account.get("tenantId", "")).lower() != inputs["tenant_id"].lower()):
        raise Refused("The enabled subscription/tenant must match the current owner user CLI session; managed identities are refused")
    exists = command(["az", "group", "exists", "--name", RESOURCE_GROUP, "--subscription", inputs["subscription_id"], "--output", "json", "--only-show-errors"], env=env)
    if exists.returncode or json.loads(exists.stdout) is not False:
        raise Refused("The exact new workload resource group must still be absent for the fresh initial plan")
    return {"subscription_id": account["id"].lower(), "tenant_id": account["tenantId"].lower(),
            "user_type": "user", "user_name_sha256": hashlib.sha256(user["name"].encode()).hexdigest()}


def execution_environment(folder: Path) -> dict[str, str]:
    env = clean_environment()
    env.update({"TF_DATA_DIR": str(folder / "tofu-data"), "TF_WORKSPACE": "default", "TF_INPUT": "0", "TF_IN_AUTOMATION": "1",
                "TF_CLI_CONFIG_FILE": str(folder / "tofurc"), "TF_VAR_bootstrap_key_file": str(folder / "encryption.passphrase"),
                "ARM_USE_CLI": "true", "ARM_USE_MSI": "false", "ARM_USE_OIDC": "false"})
    return env


def prepare(folder: Path, inputs_path: Path, expected_source: str, expected_lock: str, tofu: Path, mirror: Path) -> dict:
    env = clean_environment()
    actual = fingerprint()
    if actual["source_sha256"] != expected_source or actual["lock_sha256"] != expected_lock:
        raise Refused("Foundation source/lock differs from the reviewed hashes")
    inputs = read_json(inputs_path)
    if not isinstance(inputs, dict) or not REQUIRED <= set(inputs) or set(inputs) - REQUIRED - OPTIONAL or not all(isinstance(value, str) and value for value in inputs.values()):
        raise Refused("Provide the explicit reviewed public foundation inputs only; no generated encryption/state field or secret")
    if inputs.get("location", "eastus2") != "eastus2" or inputs.get("ubuntu_image_version", "22.04.202608060") != "22.04.202608060":
        raise Refused("Keep the reviewed East US 2 location and immutable image")
    context = owner_context(env, inputs)
    tofu = tofu.resolve(strict=True)
    mirror = mirror.resolve(strict=True)
    if not tofu.is_file() or not os.access(tofu, os.X_OK) or not mirror.is_dir():
        raise Refused("Provide the pinned executable and verified local provider mirror")
    version = command([str(tofu), "version", "-json"], env=env)
    if version.returncode or json.loads(version.stdout).get("terraform_version") != TOFU_VERSION:
        raise Refused("OpenTofu must be the pinned version 1.12.5")
    folder = private_directory(folder, fresh=True)
    for name in ("module", "state", "plans", "workspaces", "logs"):
        (folder / name).mkdir(mode=0o700)
    # Secret material is generated directly into a private file. It is never an argument, environment value or output.
    write_private(folder / "encryption.passphrase", (secrets.token_urlsafe(48) + "\n").encode())
    for name in actual["files"]:
        if name != "bootstrap_local.py":
            write_private(folder / "module" / name, (MODULE / name).read_bytes())
    inputs["state_namespace"] = NAMESPACE
    write_private(folder / "inputs.json", json_bytes(inputs))
    backend = {"path": str(folder / "state/foundation.tfstate"), "workspace_dir": str(folder / "workspaces")}
    write_private(folder / "backend.hcl", "\n".join(f"{key} = {json.dumps(value)}" for key, value in backend.items()).encode() + b"\n")
    cli = 'provider_installation {\n filesystem_mirror {\n  path = ' + json.dumps(str(mirror)) + '\n  include = ["registry.opentofu.org/hashicorp/azurerm"]\n }\n}\n'
    write_private(folder / "tofurc", cli.encode())
    manifest = {"version": 1, "profile": NAMESPACE, "resource_group": RESOURCE_GROUP, "source": actual,
                "tofu": str(tofu), "tofu_sha256": digest(tofu), "context": context,
                "protected_files": {name: digest(folder / name) for name in sorted(PROTECTED_FILES)}}
    write_private(folder / "manifest.json", json_bytes(manifest))
    return {"prepared": True, "private_directory": str(folder), "source_sha256": expected_source, "state_backend": "local-encrypted", "cloud_mutations": False}


def ciphertext(path: Path) -> None:
    secure_file(path)
    value = read_json_large(path)
    if not isinstance(value, dict) or value.get("encryption_version") != "v0" or not isinstance(value.get("encrypted_data"), str) or not value["encrypted_data"] or not isinstance(value.get("meta"), dict):
        raise Refused("Saved artifact is not an encrypted OpenTofu envelope")


def read_json_large(path: Path):
    # This reads the encryption envelope only, never decrypted plan/state contents.
    if path.stat().st_size > 128 * 1024 * 1024:
        raise Refused("Encrypted artifact exceeds the reviewed bound")
    return json.loads(path.read_bytes())


def plan(folder: Path) -> dict:
    folder = private_directory(folder)
    for name in ("manifest.json", "inputs.json", "backend.hcl", "tofurc", "encryption.passphrase"):
        secure_file(folder / name)
    manifest = read_json(folder / "manifest.json")
    if manifest.get("version") != 1 or manifest.get("profile") != NAMESPACE or manifest.get("resource_group") != RESOURCE_GROUP or manifest.get("source") != fingerprint():
        raise Refused("Prepared bootstrap no longer matches the reviewed source/namespace")
    if set(manifest.get("protected_files", {})) != PROTECTED_FILES:
        raise Refused("Prepared bootstrap file bindings are incomplete")
    for name, expected in manifest["protected_files"].items():
        if digest(folder / name) != expected:
            raise Refused("Prepared bootstrap inputs changed")
    expected_files = {name: value for name, value in manifest["source"]["files"].items() if name != "bootstrap_local.py"}
    if {path.name: digest(path) for path in (folder / "module").iterdir() if path.is_file()} != expected_files:
        raise Refused("Private module snapshot changed")
    for path in (folder / "module").iterdir():
        secure_file(path)
    for name in ("module", "state", "plans", "workspaces", "logs"):
        private_directory(folder / name)
    if (folder / "tofu-data").exists() or any((folder / "state").iterdir()) or any((folder / "plans").iterdir()) or any((folder / "workspaces").iterdir()):
        raise Refused("Only a fresh initial plan with no state, saved plan or alternate workspace is supported")
    tofu = Path(manifest["tofu"])
    if digest(tofu) != manifest["tofu_sha256"]:
        raise Refused("Pinned OpenTofu executable changed")
    env = execution_environment(folder)
    if owner_context(clean_environment(), read_json(folder / "inputs.json")) != manifest["context"]:
        raise Refused("Owner CLI context changed since preparation")
    commands = [
        ("init", ["init", "-input=false", "-lockfile=readonly", "-backend-config=" + str(folder / "backend.hcl")]),
        ("plan", ["plan", "-input=false", "-lock=true", "-lock-timeout=30s", "-var-file=" + str(folder / "inputs.json"), "-out=" + str(folder / "plans/first.tfplan")]),
    ]
    for name, args in commands:
        result = command([str(tofu), *args], cwd=folder / "module", env=env, timeout=300)
        write_private(folder / "logs" / (name + ".log"), result.stdout + result.stderr)
        if result.returncode:
            raise Refused("Initial " + name + " failed; private logs retained, no apply was attempted")
        if name == "init":
            backend = read_json(folder / "tofu-data/terraform.tfstate").get("backend", {})
            config = backend.get("config", {})
            if backend.get("type") != "local" or config.get("path") != str(folder / "state/foundation.tfstate") or config.get("workspace_dir") != str(folder / "workspaces"):
                raise Refused("Initialized backend differs from the fixed new local paths")
            workspace_file = folder / "tofu-data/environment"
            if workspace_file.exists() and workspace_file.read_text().strip() != "default":
                raise Refused("Only the new default workspace is supported")
    ciphertext(folder / "plans/first.tfplan")
    result = {"planned": True, "plan": str(folder / "plans/first.tfplan"), "plan_sha256": digest(folder / "plans/first.tfplan"),
              "source_sha256": manifest["source"]["source_sha256"], "state_backend": "local-encrypted", "applied": False}
    write_private(folder / "plan-result.json", json_bytes(result))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("fingerprint")
    first = commands.add_parser("prepare")
    for name in ("private-dir", "inputs", "tofu", "provider-mirror"):
        first.add_argument("--" + name, type=Path, required=True)
    first.add_argument("--source-sha256", required=True)
    first.add_argument("--lock-sha256", required=True)
    later = commands.add_parser("plan")
    later.add_argument("--private-dir", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.command == "fingerprint":
            result = fingerprint()
        elif args.command == "prepare":
            result = prepare(args.private_dir, args.inputs, args.source_sha256, args.lock_sha256, args.tofu, args.provider_mirror)
        else:
            result = plan(args.private_dir)
        print(json.dumps(result, sort_keys=True))
    except (Refused, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        # Never echo arbitrary provider errors, inputs or key material to the caller.
        print("Encrypted local bootstrap refused; inspect reviewed inputs or private logs. No apply was attempted.", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
