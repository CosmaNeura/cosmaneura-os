"""Prepare, plan, and apply a fresh encrypted local CosmaBot production foundation.

First-apply-only tooling by default. Pass --recover for the separately reviewed
partial-apply recovery path (reuse encrypted state/passphrase in place; ADD-ONLY
plans under plans/recover-<UTC>.tfplan). Pass --recheck for a print-only
post-apply re-check (same reviewed inputs + existing private dir; writes only
plans/recheck-<UTC>.tfplan and matching summary/result; never apply). Pass
--recreate-workload for the off-by-default path that replaces only
azurerm_linux_virtual_machine.workload and azurerm_managed_disk.data (plus the
data-disk attachment) under plans/recreate-workload-<UTC>.tfplan with
-var=allow_workload_recreate=true. Pass refresh-module-snapshot --confirm-refresh
to explicitly refresh a live private module/*.tf snapshot on a clean origin/main
checkout (sanctioned *.tf diffs only; binds new digests into manifest.source).
OpenAI opt-in must be in the first apply's inputs or wait for a separately
reviewed day-2 tool. Do not run raw tofu by hand.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import secrets
import signal
import stat
import subprocess
import sys
from collections import Counter
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from name_guards import (  # noqa: E402
    STAGING,
    NameGuardError,
    assert_production_inputs,
    refuse_cross_environment,
)

MODULE = Path(__file__).resolve().parent
PROD = MODULE.parent
REPO = MODULE.parents[4]
NAMESPACE = "cosmabot-vm/eastus2/prod01/local-initial"
RESOURCE_GROUP = "rg-cosmabot-prod-eus2-01"
TOFU_VERSION = "1.12.5"
REQUIRED = {
    "subscription_id",
    "tenant_id",
    "resource_name_suffix",
    "vnet_address_prefix",
    "admin_username",
    "admin_ssh_public_key",
    "release_operator_object_id",
    "alert_contact_email",
}
OPTIONAL = {"location", "ubuntu_image_version"}
OPTIONAL_BOOLS = {"enable_azure_openai"}
PROTECTED_FILES = {"inputs.json", "backend.hcl", "tofurc", "encryption.passphrase"}
ALLOWED_RESOURCE_TYPES = frozenset(
    {
        "azurerm_cognitive_account",
        "azurerm_cognitive_deployment",
        "azurerm_container_registry",
        "azurerm_key_vault",
        "azurerm_linux_virtual_machine",
        "azurerm_log_analytics_workspace",
        "azurerm_managed_disk",
        "azurerm_monitor_action_group",
        "azurerm_monitor_data_collection_rule",
        "azurerm_monitor_data_collection_rule_association",
        "azurerm_monitor_metric_alert",
        "azurerm_monitor_scheduled_query_rules_alert_v2",
        "azurerm_network_interface",
        "azurerm_network_security_group",
        "azurerm_private_dns_zone",
        "azurerm_private_dns_zone_virtual_network_link",
        "azurerm_private_endpoint",
        "azurerm_public_ip",
        "azurerm_resource_group",
        "azurerm_role_assignment",
        "azurerm_storage_account",
        "azurerm_storage_container",
        "azurerm_subnet",
        "azurerm_subnet_network_security_group_association",
        "azurerm_user_assigned_identity",
        "azurerm_virtual_machine_data_disk_attachment",
        "azurerm_virtual_machine_extension",
        "azurerm_virtual_network",
        "terraform_data",
    }
)
MONITOR_AGENT_PUBLISHER = "Microsoft.Azure.Monitor"
MONITOR_AGENT_TYPE = "AzureMonitorLinuxAgent"
APPLY_RECOVERY = (
    "Partial-apply recovery: keep the private directory, do not run raw tofu by hand, "
    "and use --recover on the reviewed recovery tooling before retry."
)
RECOVER_PLAN_NAME = re.compile(r"^recover-\d{8}T\d{6}Z\.tfplan$")
RECOVER_SUMMARY_NAME = re.compile(r"^recover-plan-summary-\d{8}T\d{6}Z\.json$")
RECOVER_RESULT_NAME = re.compile(r"^recover-plan-result-\d{8}T\d{6}Z\.json$")
RECHECK_PLAN_NAME = re.compile(r"^recheck-\d{8}T\d{6}Z\.tfplan$")
RECHECK_SUMMARY_NAME = re.compile(r"^recheck-plan-summary-\d{8}T\d{6}Z\.json$")
RECHECK_RESULT_NAME = re.compile(r"^recheck-plan-result-\d{8}T\d{6}Z\.json$")
RECHECK_PREPARE_NAME = re.compile(r"^recheck-prepare-\d{8}T\d{6}Z\.json$")
RECREATE_PLAN_NAME = re.compile(r"^recreate-workload-\d{8}T\d{6}Z\.tfplan$")
RECREATE_SUMMARY_NAME = re.compile(r"^recreate-workload-plan-summary-\d{8}T\d{6}Z\.json$")
RECREATE_RESULT_NAME = re.compile(r"^recreate-workload-plan-result-\d{8}T\d{6}Z\.json$")
RECREATE_VM_ADDRESS = "azurerm_linux_virtual_machine.workload"
RECREATE_DISK_ADDRESS = "azurerm_managed_disk.data"
RECREATE_ATTACHMENT_ADDRESS = "azurerm_virtual_machine_data_disk_attachment.data"
RECREATE_REQUIRED_REPLACE_ADDRESSES = frozenset(
    {
        RECREATE_VM_ADDRESS,
        RECREATE_DISK_ADDRESS,
        RECREATE_ATTACHMENT_ADDRESS,
    }
)
RECREATE_ALLOWED_ALERT_ADDRESSES = frozenset(
    {
        'azurerm_monitor_metric_alert.vm["unavailable"]',
        'azurerm_monitor_metric_alert.vm["cpu"]',
        'azurerm_monitor_metric_alert.vm["disk_iops"]',
    }
)
# Optional replace-only when runtime_monitoring_enabled retargets after VM recreate.
RECREATE_ALLOWED_OPTIONAL_REPLACE_ADDRESSES = frozenset(
    {
        "azurerm_virtual_machine_extension.health[0]",
        "azurerm_monitor_data_collection_rule_association.health[0]",
    }
)
# Update-only, limited to query or scopes, when the scheduled-query alert embeds workload.id.
RECREATE_ALLOWED_RUNTIME_ALERT_ADDRESSES = frozenset(
    {
        'azurerm_monitor_scheduled_query_rules_alert_v2.runtime["application"]',
        'azurerm_monitor_scheduled_query_rules_alert_v2.runtime["backup"]',
    }
)
# Every module resource address that may reference azurerm_linux_virtual_machine.workload.id.
WORKLOAD_ID_REFERENCE_ADDRESSES = frozenset(
    {
        RECREATE_ATTACHMENT_ADDRESS,
        *RECREATE_ALLOWED_ALERT_ADDRESSES,
        *RECREATE_ALLOWED_OPTIONAL_REPLACE_ADDRESSES,
        *RECREATE_ALLOWED_RUNTIME_ALERT_ADDRESSES,
    }
)
# Types that must never appear as create/update/replace/delete in a recreate plan
# unless the exact address is in an allow-list above.
RECREATE_FORBIDDEN_TOUCH_TYPES = frozenset(
    {
        "azurerm_public_ip",
        "azurerm_network_interface",
        "azurerm_user_assigned_identity",
        "azurerm_role_assignment",
        "azurerm_key_vault",
        "azurerm_storage_account",
        "azurerm_storage_container",
        "azurerm_container_registry",
        "azurerm_cognitive_account",
        "azurerm_cognitive_deployment",
        "azurerm_virtual_network",
        "azurerm_subnet",
        "azurerm_subnet_network_security_group_association",
        "azurerm_network_security_group",
        "azurerm_private_dns_zone",
        "azurerm_private_dns_zone_virtual_network_link",
        "azurerm_private_endpoint",
        "azurerm_resource_group",
        "azurerm_log_analytics_workspace",
        "azurerm_monitor_action_group",
        "azurerm_monitor_data_collection_rule",
        "azurerm_monitor_data_collection_rule_association",
        "azurerm_monitor_scheduled_query_rules_alert_v2",
        "azurerm_virtual_machine_extension",
        "terraform_data",
    }
)
OS_DISK_NAME = "osdisk-vm-cosmabot-prod-eus2-01"
DATA_DISK_NAME = "data-vm-cosmabot-prod-eus2-01"
WORKLOAD_LIVE_NAME = "workload-live.json"
OS_DISK_COMPUTE_TF_NEEDLE = 'name                 = "osdisk-${local.vm_name}"'
ALLOW_WORKLOAD_RECREATE_VAR = "allow_workload_recreate=true"
# Private-module refresh may rewrite only these reviewed *.tf paths (relative to module/).
SANCTIONED_MODULE_REFRESH_PATHS = frozenset(
    {
        "compute.tf",
        "variables.tf",
        "versions.tf",
    }
)
VM_AZURE_NAME = "vm-cosmabot-prod-eus2-01"
ARM_SUBSCRIPTION_RE = re.compile(r"/subscriptions/([^/]+)", re.IGNORECASE)
MODULE_REFRESH_RECEIPT_NAME = re.compile(r"^module-snapshot-refresh-\d{8}T\d{6}Z\.json$")
ARM_RESOURCE_GROUP_RE = re.compile(
    r"/subscriptions/([^/]+)/resourceGroups/([^/]+)",
    re.IGNORECASE,
)
# Derived from name_guards.STAGING (parity-tested); refuse embedding this RG name.
STAGING_RG_NEEDLE = STAGING["resource_group"].lower()
# Configured reference inputs only. Never refuse the resource's own computed id,
# principal_id, client_id, tenant_id, virtual_machine_id, or role_definition_id.
RELEVANT_UNKNOWN_REFERENCE_KEYS = frozenset(
    {
        "subnet_id",
        "virtual_network_id",
        "private_connection_resource_id",
        "private_dns_zone_ids",
        "scope",
        "target_resource_id",
        "data_collection_rule_id",
        "managed_disk_id",
        "network_security_group_id",
        "storage_account_id",
        "cognitive_account_id",
        "network_interface_ids",
        "identity_ids",
        "public_ip_address_id",
        "workspace_resource_id",
    }
)
EXTRA_FINGERPRINT = (
    PROD / "name_guards.py",
    REPO / "infra/beta/review-cosmabot-prod-foundation.sh",
    REPO / "infra/beta/apply-cosmabot-prod-foundation.sh",
)


class Refused(RuntimeError):
    pass


class RecheckDriftRefused(Refused):
    """Post-apply re-check drift. Message lists resource addresses only; safe for stderr."""

    pass


class ApplyAttempted(Refused):
    """Raised after tofu apply has started (success path never raises this)."""

    pass


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_bytes(value) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def secure_file(path: Path) -> None:
    value = path.lstat()
    if (
        not stat.S_ISREG(value.st_mode)
        or value.st_uid != os.getuid()
        or value.st_nlink != 1
        or stat.S_IMODE(value.st_mode) != 0o600
    ):
        raise Refused("Private bootstrap file ownership or mode is invalid")


def _assert_not_workload_live_path(path: Path) -> None:
    if path.name == WORKLOAD_LIVE_NAME:
        raise Refused(f"{WORKLOAD_LIVE_NAME} can only be created by first package admission")


def _open_private_exclusive(path: Path):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    return os.fdopen(fd, "wb")


def write_private(path: Path, value: bytes) -> None:
    _assert_not_workload_live_path(path)
    with _open_private_exclusive(path) as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())


def replace_private(path: Path, value: bytes) -> None:
    """Replace an existing 0600 private file without widening mode or following links."""
    _assert_not_workload_live_path(path)
    secure_file(path)
    tmp = path.with_name(path.name + ".tmp-" + secrets.token_hex(4))
    write_private(tmp, value)
    os.replace(tmp, path)
    os.chmod(path, 0o600)
    secure_file(path)


def utc_plan_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def private_directory(path: Path, *, fresh=False) -> Path:
    if not path.is_absolute() or path.resolve() != path or path.is_relative_to(REPO):
        raise Refused("Use an absolute canonical private directory outside the repository")
    if fresh:
        path.mkdir(mode=0o700, parents=False, exist_ok=False)
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise Refused("Bootstrap directory must be owned by the operator with mode 0700") from exc
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


def source_files() -> list[Path]:
    files = sorted(
        {
            *MODULE.glob("*.tf"),
            *MODULE.glob("modules/**/*.tf"),
            MODULE / ".terraform.lock.hcl",
            MODULE / "bootstrap_local.py",
        }
    )
    for path in MODULE.iterdir():
        if path.name.endswith((".tf.json", ".tofu", ".tofu.json", ".tfvars", ".tfvars.json")):
            raise Refused("Unreviewed alternate configuration or automatic variable file in foundation source")
    if any(path.is_symlink() or not path.is_file() for path in files):
        raise Refused("Foundation source must consist of regular reviewed files")
    return files


def source_manifest() -> dict[str, str]:
    files = {path.relative_to(MODULE).as_posix(): digest(path) for path in source_files()}
    for path in EXTRA_FINGERPRINT:
        files[f"extra/{path.name}"] = digest(path)
    return files


def fingerprint() -> dict:
    files = source_manifest()
    return {
        "source_sha256": hashlib.sha256(json_bytes(files)).hexdigest(),
        "lock_sha256": files[".terraform.lock.hcl"],
        "files": files,
    }


def _git(argv: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(REPO), *argv],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def assert_clean_origin_main_checkout() -> str:
    """Refuse unless the working tree is a clean checkout of a commit on origin/main.

    Returns the HEAD commit SHA (lowercase hex).
    """
    status = _git(["status", "--porcelain"])
    if status.returncode:
        raise Refused("Cannot verify git working tree cleanliness for module snapshot refresh")
    if status.stdout.strip():
        raise Refused(
            "Module snapshot refresh requires a clean git working tree "
            "(no staged, unstaged, or untracked changes)"
        )
    head = _git(["rev-parse", "HEAD"])
    if head.returncode or not head.stdout.strip():
        raise Refused("Cannot resolve HEAD for module snapshot refresh")
    head_sha = head.stdout.decode().strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", head_sha):
        raise Refused("HEAD SHA for module snapshot refresh is not a 40-char hex commit")
    # Ensure origin/main is available without mutating the working tree.
    fetch = _git(["rev-parse", "--verify", "origin/main"])
    if fetch.returncode:
        raise Refused("origin/main is required for module snapshot refresh; fetch main first")
    ancestor = _git(["merge-base", "--is-ancestor", head_sha, "origin/main"])
    if ancestor.returncode:
        raise Refused(
            "Module snapshot refresh requires HEAD to be a commit on origin/main "
            "(merge this PR before refreshing a live private directory)"
        )
    return head_sha


def _module_tf_relpaths(files: dict[str, str]) -> list[str]:
    return sorted(
        name
        for name in files
        if name.endswith(".tf") and not name.startswith("extra/") and name != "bootstrap_local.py"
    )


def _unified_diff(path: str, old: bytes, new: bytes) -> str:
    import difflib

    old_lines = old.decode(errors="replace").splitlines(keepends=True)
    new_lines = new.decode(errors="replace").splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/module/{path}",
            tofile=f"b/module/{path}",
        )
    )


def refresh_module_snapshot(
    folder: Path,
    expected_source: str,
    expected_lock: str,
    *,
    confirm_refresh: bool = False,
) -> dict:
    """Explicitly refresh private module/*.tf to the reviewed foundation snapshot.

    Not silent: requires --confirm-refresh, a clean origin/main checkout, prints
    every *.tf unified diff, refuses any path outside SANCTIONED_MODULE_REFRESH_PATHS,
    then rewrites the private module files and binds the new fingerprint into
    manifest.source (the digests John must approve on the next plan).
    """
    if not confirm_refresh:
        raise Refused("refusing module snapshot refresh without --confirm-refresh")
    head_sha = assert_clean_origin_main_checkout()
    actual = fingerprint()
    if actual["source_sha256"] != expected_source or actual["lock_sha256"] != expected_lock:
        raise Refused("Foundation source/lock differs from the reviewed hashes")
    folder = private_directory(folder, fresh=False)
    for name in ("manifest.json", "inputs.json", "backend.hcl", "tofurc", "encryption.passphrase"):
        if not (folder / name).exists():
            raise Refused(f"Module snapshot refresh requires existing private {name}")
        secure_file(folder / name)
    private_directory(folder / "module")
    prior = read_json(folder / "manifest.json")
    if (
        prior.get("version") != 1
        or prior.get("profile") != NAMESPACE
        or prior.get("resource_group") != RESOURCE_GROUP
    ):
        raise Refused("Prepared bootstrap no longer matches the reviewed source/namespace")
    expected_module = {
        name: value
        for name, value in actual["files"].items()
        if name != "bootstrap_local.py" and not name.startswith("extra/")
    }
    actual_module = {
        path.relative_to(folder / "module").as_posix(): digest(path)
        for path in (folder / "module").rglob("*")
        if path.is_file()
    }
    if actual_module == expected_module:
        raise Refused("Private module snapshot already matches the reviewed foundation; nothing to refresh")
    changed: list[str] = []
    missing: list[str] = []
    unexpected: list[str] = []
    diffs: dict[str, str] = {}
    for rel in sorted(set(expected_module) | set(actual_module)):
        old_path = folder / "module" / rel
        new_path = MODULE / rel
        old_bytes = old_path.read_bytes() if old_path.is_file() else b""
        new_bytes = new_path.read_bytes() if new_path.is_file() else b""
        if old_bytes == new_bytes:
            continue
        if rel not in expected_module:
            unexpected.append(rel)
            continue
        if rel not in actual_module:
            missing.append(rel)
        if not rel.endswith(".tf"):
            unexpected.append(rel)
            continue
        if rel not in SANCTIONED_MODULE_REFRESH_PATHS:
            unexpected.append(rel)
            continue
        changed.append(rel)
        diffs[rel] = _unified_diff(rel, old_bytes, new_bytes)
    if unexpected:
        raise Refused(
            "Module snapshot refresh refuses unexpected private-module drift outside the "
            "sanctioned *.tf allow-list: "
            + ", ".join(sorted(set(unexpected)))
        )
    if missing:
        raise Refused(
            "Module snapshot refresh refuses missing sanctioned module files: "
            + ", ".join(sorted(missing))
        )
    if not changed:
        raise Refused("Module snapshot refresh found digest drift but no sanctioned *.tf content diff")
    for rel in sorted(changed):
        _operator_print(f"=== module snapshot refresh diff: {rel} ===")
        _operator_print(diffs[rel] if diffs[rel] else "(binary or empty diff)")
    stamp = utc_plan_stamp()
    receipt_path = folder / f"module-snapshot-refresh-{stamp}.json"
    if receipt_path.exists():
        raise Refused("Module snapshot refresh receipt path already exists; refuse overwrite")
    previous_source = prior.get("source") if isinstance(prior.get("source"), dict) else {}
    previous_source_sha256 = previous_source.get("source_sha256")
    # Backup prior manifest.source before overwrite (operator recovery / audit).
    source_backup_path = folder / f"manifest.source.pre-refresh-{stamp}.json"
    if source_backup_path.exists():
        raise Refused("Module snapshot refresh source backup path already exists; refuse overwrite")
    write_private(source_backup_path, json_bytes(previous_source if previous_source else {}))
    secure_file(source_backup_path)
    # Rewrite only sanctioned changed files from the reviewed MODULE tree.
    for rel in changed:
        target = folder / "module" / rel
        payload = (MODULE / rel).read_bytes()
        if target.exists():
            replace_private(target, payload)
        else:
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            write_private(target, payload)
        secure_file(target)
    refreshed_module = {
        path.relative_to(folder / "module").as_posix(): digest(path)
        for path in (folder / "module").rglob("*")
        if path.is_file()
    }
    if refreshed_module != expected_module:
        raise Refused("Module snapshot refresh left private module digests mismatched")
    # Bind the new reviewed fingerprint into the private manifest (approval substrate).
    prior["source"] = actual
    prior["module_snapshot_refresh"] = {
        "head_sha": head_sha,
        "stamp": stamp,
        "changed_files": changed,
        "previous_source_sha256": previous_source_sha256,
        "source_backup": str(source_backup_path),
        "source_sha256": actual["source_sha256"],
        "lock_sha256": actual["lock_sha256"],
    }
    replace_private(folder / "manifest.json", json_bytes(prior))
    receipt = {
        "module_snapshot_refresh": True,
        "stamp": stamp,
        "head_sha": head_sha,
        "changed_files": changed,
        "diffs": diffs,
        "previous_source_sha256": previous_source_sha256,
        "source_backup": str(source_backup_path),
        "source_sha256": actual["source_sha256"],
        "lock_sha256": actual["lock_sha256"],
        "private_directory": str(folder),
        "confirm_refresh": True,
    }
    write_private(receipt_path, json_bytes(receipt))
    secure_file(receipt_path)
    _operator_print(
        "Module snapshot refresh bound new source_sha256="
        + actual["source_sha256"]
        + " lock_sha256="
        + actual["lock_sha256"]
        + ". Use these digests on the next prepare/plan approval."
    )
    return {
        "refreshed": True,
        "stamp": stamp,
        "receipt_path": str(receipt_path),
        "source_backup": str(source_backup_path),
        "head_sha": head_sha,
        "changed_files": changed,
        "source_sha256": actual["source_sha256"],
        "lock_sha256": actual["lock_sha256"],
        "private_directory": str(folder),
    }


def clean_environment() -> dict[str, str]:
    if any(key.startswith(("TF_", "ARM_")) for key in os.environ) or "AZURE_CONFIG_DIR" in os.environ:
        raise Refused("Remove ambient TF/ARM overrides and AZURE_CONFIG_DIR; use the current owner CLI context")
    return dict(os.environ)


def command(argv, *, env, cwd=None, timeout=120):
    return subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=timeout,
        check=False,
        umask=0o077,
    )


def _assert_single_mode(*, recover: bool = False, recheck: bool = False, recreate_workload: bool = False) -> None:
    if sum(1 for flag in (recover, recheck, recreate_workload) if flag) > 1:
        raise Refused("--recover, --recheck, and --recreate-workload are mutually exclusive")


def owner_context(
    env: dict,
    inputs: dict,
    *,
    recover: bool = False,
    recheck: bool = False,
    recreate_workload: bool = False,
) -> dict:
    _assert_single_mode(recover=recover, recheck=recheck, recreate_workload=recreate_workload)
    result = command(["az", "account", "show", "--output", "json", "--only-show-errors"], env=env)
    if result.returncode:
        raise Refused("Cannot verify the current owner Azure CLI context")
    account = json.loads(result.stdout)
    user = account.get("user", {})
    if (
        account.get("state") != "Enabled"
        or user.get("type") != "user"
        or not user.get("name")
        or str(account.get("id", "")).lower() != inputs["subscription_id"].lower()
        or str(account.get("tenantId", "")).lower() != inputs["tenant_id"].lower()
    ):
        raise Refused(
            "The enabled subscription/tenant must match the current owner user CLI session; managed identities are refused"
        )
    exists = command(
        [
            "az",
            "group",
            "exists",
            "--name",
            RESOURCE_GROUP,
            "--subscription",
            inputs["subscription_id"],
            "--output",
            "json",
            "--only-show-errors",
        ],
        env=env,
    )
    present = None if exists.returncode else json.loads(exists.stdout)
    if recover or recheck or recreate_workload:
        if present is not True:
            if recreate_workload:
                label = "Workload recreate"
            elif recover:
                label = "Recovery"
            else:
                label = "Post-apply re-check"
            raise Refused(
                f"{label} requires the existing workload resource group "
                f"{RESOURCE_GROUP} to already be present"
            )
    elif exists.returncode or present is not False:
        raise Refused("The exact new workload resource group must still be absent for the fresh initial plan")
    return {
        "subscription_id": account["id"].lower(),
        "tenant_id": account["tenantId"].lower(),
        "user_type": "user",
        "user_name_sha256": hashlib.sha256(user["name"].encode()).hexdigest(),
    }


def execution_environment(folder: Path, *, data_dir: Path | None = None) -> dict[str, str]:
    env = clean_environment()
    env.update(
        {
            "TF_DATA_DIR": str(data_dir if data_dir is not None else folder / "tofu-data"),
            "TF_WORKSPACE": "default",
            "TF_INPUT": "0",
            "TF_IN_AUTOMATION": "1",
            "TF_CLI_CONFIG_FILE": str(folder / "tofurc"),
            "TF_VAR_bootstrap_key_file": str(folder / "encryption.passphrase"),
            "ARM_USE_CLI": "true",
            "ARM_USE_MSI": "false",
            "ARM_USE_OIDC": "false",
        }
    )
    return env


def normalize_inputs(inputs: dict) -> dict:
    if not isinstance(inputs, dict) or not REQUIRED <= set(inputs):
        raise Refused(
            "Provide the explicit reviewed public foundation inputs only; no generated encryption/state field or secret"
        )
    if "allow_workload_recreate" in inputs:
        raise Refused(
            "allow_workload_recreate must not be stored in inputs.json; "
            "recreate plans pass -var=allow_workload_recreate=true only"
        )
    unknown = set(inputs) - REQUIRED - OPTIONAL - OPTIONAL_BOOLS
    if unknown:
        raise Refused(
            "Provide the explicit reviewed public foundation inputs only; no generated encryption/state field or secret"
        )
    string_keys = (REQUIRED | OPTIONAL) & set(inputs)
    if not all(isinstance(inputs[key], str) and inputs[key] for key in string_keys):
        raise Refused(
            "Provide the explicit reviewed public foundation inputs only; no generated encryption/state field or secret"
        )
    for key in OPTIONAL_BOOLS & set(inputs):
        if not isinstance(inputs[key], bool):
            raise Refused("enable_azure_openai must be a JSON boolean when present")
    if inputs.get("location", "eastus2") != "eastus2" or inputs.get(
        "ubuntu_image_version", "22.04.202608060"
    ) != "22.04.202608060":
        raise Refused("Keep the reviewed East US 2 location and immutable image")
    try:
        assert_production_inputs({key: value for key, value in inputs.items() if isinstance(value, str)})
    except NameGuardError as exc:
        raise Refused(str(exc)) from exc
    return inputs


def _verify_tofu_mirror(tofu: Path, mirror: Path, env: dict) -> Path:
    tofu = tofu.resolve(strict=True)
    mirror = mirror.resolve(strict=True)
    if not tofu.is_file() or not os.access(tofu, os.X_OK) or not mirror.is_dir():
        raise Refused("Provide the pinned executable and verified local provider mirror")
    version = command([str(tofu), "version", "-json"], env=env)
    if version.returncode or json.loads(version.stdout).get("terraform_version") != TOFU_VERSION:
        raise Refused("OpenTofu must be the pinned version 1.12.5")
    return tofu


def prepare(
    folder: Path,
    inputs_path: Path,
    expected_source: str,
    expected_lock: str,
    tofu: Path,
    mirror: Path,
    *,
    recover: bool = False,
    recheck: bool = False,
    recreate_workload: bool = False,
) -> dict:
    _assert_single_mode(recover=recover, recheck=recheck, recreate_workload=recreate_workload)
    if recheck:
        return prepare_recheck(folder, inputs_path, expected_source, expected_lock, tofu, mirror)
    if recover:
        return prepare_recover(folder, inputs_path, expected_source, expected_lock, tofu, mirror)
    if recreate_workload:
        return prepare_recreate_workload(
            folder, inputs_path, expected_source, expected_lock, tofu, mirror
        )
    env = clean_environment()
    actual = fingerprint()
    if actual["source_sha256"] != expected_source or actual["lock_sha256"] != expected_lock:
        raise Refused("Foundation source/lock differs from the reviewed hashes")
    inputs = normalize_inputs(read_json(inputs_path))
    context = owner_context(env, inputs)
    tofu = _verify_tofu_mirror(tofu, mirror, env)
    folder = private_directory(folder, fresh=True)
    for name in ("module", "state", "plans", "workspaces", "logs"):
        (folder / name).mkdir(mode=0o700)
    write_private(folder / "encryption.passphrase", (secrets.token_urlsafe(48) + "\n").encode())
    for name in actual["files"]:
        if name == "bootstrap_local.py" or name.startswith("extra/"):
            continue
        target = folder / "module" / name
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        write_private(target, (MODULE / name).read_bytes())
    inputs = dict(inputs)
    inputs["state_namespace"] = NAMESPACE
    write_private(folder / "inputs.json", json_bytes(inputs))
    backend = {"path": str(folder / "state/foundation.tfstate"), "workspace_dir": str(folder / "workspaces")}
    write_private(
        folder / "backend.hcl",
        "\n".join(f"{key} = {json.dumps(value)}" for key, value in backend.items()).encode() + b"\n",
    )
    cli = (
        "provider_installation {\n filesystem_mirror {\n  path = "
        + json.dumps(str(mirror))
        + '\n  include = ["registry.opentofu.org/hashicorp/azurerm"]\n }\n}\n'
    )
    write_private(folder / "tofurc", cli.encode())
    manifest = {
        "version": 1,
        "profile": NAMESPACE,
        "resource_group": RESOURCE_GROUP,
        "source": actual,
        "tofu": str(tofu),
        "tofu_sha256": digest(tofu),
        "context": context,
        "protected_files": {name: digest(folder / name) for name in sorted(PROTECTED_FILES)},
        "first_apply_only": True,
    }
    write_private(folder / "manifest.json", json_bytes(manifest))
    return {
        "prepared": True,
        "private_directory": str(folder),
        "source_sha256": expected_source,
        "state_backend": "local-encrypted",
        "cloud_mutations": False,
        "first_apply_only": True,
    }


def prepare_recover(
    folder: Path,
    inputs_path: Path,
    expected_source: str,
    expected_lock: str,
    tofu: Path,
    mirror: Path,
) -> dict:
    """Reuse an existing private dir for ADD-ONLY recovery. Never regenerate the passphrase."""
    env = clean_environment()
    actual = fingerprint()
    if actual["source_sha256"] != expected_source or actual["lock_sha256"] != expected_lock:
        raise Refused("Foundation source/lock differs from the reviewed hashes")
    inputs = normalize_inputs(read_json(inputs_path))
    context = owner_context(env, inputs, recover=True)
    tofu = _verify_tofu_mirror(tofu, mirror, env)
    folder = private_directory(folder, fresh=False)
    passphrase = folder / "encryption.passphrase"
    state_path = folder / "state/foundation.tfstate"
    if not passphrase.exists():
        raise Refused("Recovery requires the existing encryption.passphrase file")
    if not state_path.exists():
        raise Refused("Recovery requires existing state/foundation.tfstate")
    for name in ("manifest.json", "inputs.json", "backend.hcl", "tofurc", "encryption.passphrase"):
        secure_file(folder / name)
    ciphertext(state_path)
    for name in ("module", "state", "plans", "workspaces", "logs"):
        private_directory(folder / name)
    prior = read_json(folder / "manifest.json")
    if (
        prior.get("version") != 1
        or prior.get("profile") != NAMESPACE
        or prior.get("resource_group") != RESOURCE_GROUP
    ):
        raise Refused("Prepared bootstrap no longer matches the reviewed source/namespace")
    if set(prior.get("protected_files", {})) != PROTECTED_FILES:
        raise Refused("Prepared bootstrap file bindings are incomplete")
    for name, expected in prior["protected_files"].items():
        if digest(folder / name) != expected:
            raise Refused("Prepared bootstrap inputs changed")
    expected_module = {
        name: value
        for name, value in actual["files"].items()
        if name != "bootstrap_local.py" and not name.startswith("extra/")
    }
    actual_module = {
        path.relative_to(folder / "module").as_posix(): digest(path)
        for path in (folder / "module").rglob("*")
        if path.is_file()
    }
    if actual_module != expected_module:
        raise Refused("Private module snapshot changed")
    bound = dict(inputs)
    bound["state_namespace"] = NAMESPACE
    if read_json(folder / "inputs.json") != bound:
        raise Refused("Recovery inputs must match the existing private inputs.json")
    first_apply_path = folder / "manifest.first-apply.json"
    if first_apply_path.exists():
        secure_file(first_apply_path)
        first_apply = read_json(first_apply_path)
    else:
        if prior.get("recover"):
            raise Refused("manifest.first-apply.json is required before a second recover prepare")
        write_private(first_apply_path, json_bytes(prior))
        first_apply = prior
    tofu_sha = digest(tofu)
    if first_apply.get("tofu_sha256") != tofu_sha:
        raise Refused(
            "Recovery tofu_sha256 differs from first-apply manifest: "
            f"first_apply={first_apply.get('tofu_sha256')} recover={tofu_sha}"
        )
    if first_apply.get("context") != context:
        raise Refused(
            "Recovery owner context differs from first-apply manifest: "
            f"first_apply={first_apply.get('context')} recover={context}"
        )
    stamp = utc_plan_stamp()
    state_backup = folder / "state" / f"foundation.tfstate.pre-recover-{stamp}"
    write_private(state_backup, state_path.read_bytes())
    secure_file(state_backup)
    ciphertext(state_backup)
    first_plan = folder / "plans/first.tfplan"
    first_plan_sha = digest(first_plan) if first_plan.is_file() else None
    state_sha = digest(state_path)
    manifest = {
        "version": 1,
        "profile": NAMESPACE,
        "resource_group": RESOURCE_GROUP,
        "source": actual,
        "tofu": str(tofu),
        "tofu_sha256": tofu_sha,
        "context": context,
        "protected_files": {name: digest(folder / name) for name in sorted(PROTECTED_FILES)},
        "first_apply_only": True,
        "recover": True,
        "recover_backups": {
            "state_pre_recover": str(state_backup),
            "state_pre_recover_sha256": digest(state_backup),
            "state_sha256_at_prepare": state_sha,
            "manifest_first_apply": str(first_apply_path),
            "manifest_first_apply_sha256": digest(first_apply_path),
        },
    }
    replace_private(folder / "manifest.json", json_bytes(manifest))
    if first_plan_sha is not None and digest(first_plan) != first_plan_sha:
        raise Refused("Recovery prepare must not modify plans/first.tfplan")
    if digest(passphrase) != prior["protected_files"]["encryption.passphrase"]:
        raise Refused("Recovery prepare must not modify encryption.passphrase")
    if digest(state_path) != state_sha:
        raise Refused("Recovery prepare must not modify state/foundation.tfstate")
    return {
        "prepared": True,
        "recover": True,
        "private_directory": str(folder),
        "source_sha256": expected_source,
        "state_backend": "local-encrypted",
        "cloud_mutations": False,
        "first_apply_only": True,
    }


def prepare_recheck(
    folder: Path,
    inputs_path: Path,
    expected_source: str,
    expected_lock: str,
    tofu: Path,
    mirror: Path,
) -> dict:
    """Verify an existing private dir for a print-only post-apply re-check.

    Never regenerates the passphrase, never backs up or writes state, and never
    mutates manifests, first.tfplan, or recover artifacts. Manifest ``source``
    may differ from the current fingerprint (bootstrap/scripts can change after
    prepare --recover); the reviewed digests are recorded in
    ``recheck-prepare-<UTC>.json`` instead. Private module ``*.tf`` files must
    still match the current fingerprint.
    """
    env = clean_environment()
    actual = fingerprint()
    if actual["source_sha256"] != expected_source or actual["lock_sha256"] != expected_lock:
        raise Refused("Foundation source/lock differs from the reviewed hashes")
    inputs = normalize_inputs(read_json(inputs_path))
    context = owner_context(env, inputs, recheck=True)
    tofu = _verify_tofu_mirror(tofu, mirror, env)
    folder = private_directory(folder, fresh=False)
    passphrase = folder / "encryption.passphrase"
    state_path = folder / "state/foundation.tfstate"
    if not passphrase.exists():
        raise Refused("Post-apply re-check requires the existing encryption.passphrase file")
    if not state_path.exists():
        raise Refused("Post-apply re-check requires existing state/foundation.tfstate")
    for name in ("manifest.json", "inputs.json", "backend.hcl", "tofurc", "encryption.passphrase"):
        secure_file(folder / name)
    ciphertext(state_path)
    for name in ("module", "state", "plans", "workspaces", "logs"):
        private_directory(folder / name)
    prior = read_json(folder / "manifest.json")
    if (
        prior.get("version") != 1
        or prior.get("profile") != NAMESPACE
        or prior.get("resource_group") != RESOURCE_GROUP
    ):
        raise Refused("Prepared bootstrap no longer matches the reviewed source/namespace")
    if set(prior.get("protected_files", {})) != PROTECTED_FILES:
        raise Refused("Prepared bootstrap file bindings are incomplete")
    for name, expected in prior["protected_files"].items():
        if digest(folder / name) != expected:
            raise Refused("Prepared bootstrap inputs changed")
    # Compare private module to the *current* reviewed fingerprint (not the
    # possibly-stale manifest.source). bootstrap_local.py / extra/ are not
    # snapshotted into module/.
    expected_module = {
        name: value
        for name, value in actual["files"].items()
        if name != "bootstrap_local.py" and not name.startswith("extra/")
    }
    actual_module = {
        path.relative_to(folder / "module").as_posix(): digest(path)
        for path in (folder / "module").rglob("*")
        if path.is_file()
    }
    if actual_module != expected_module:
        raise Refused("Private module snapshot changed")
    bound = dict(inputs)
    bound["state_namespace"] = NAMESPACE
    if read_json(folder / "inputs.json") != bound:
        raise Refused("Post-apply re-check inputs must match the existing private inputs.json")
    tofu_sha = digest(tofu)
    if prior.get("tofu_sha256") != tofu_sha:
        raise Refused(
            "Post-apply re-check tofu_sha256 differs from private manifest: "
            f"manifest={prior.get('tofu_sha256')} recheck={tofu_sha}"
        )
    if prior.get("context") != context:
        raise Refused(
            "Post-apply re-check owner context differs from private manifest: "
            f"manifest={prior.get('context')} recheck={context}"
        )
    stamp = utc_plan_stamp()
    prepare_path = folder / f"recheck-prepare-{stamp}.json"
    if prepare_path.exists():
        raise Refused("Post-apply re-check prepare path already exists; refuse overwrite")
    record = {
        "recheck": True,
        "stamp": stamp,
        "source": actual,
        "source_sha256": expected_source,
        "lock_sha256": expected_lock,
        "tofu_sha256": tofu_sha,
        "context": context,
        "manifest_source_sha256": (prior.get("source") or {}).get("source_sha256"),
        "private_directory": str(folder),
    }
    write_private(prepare_path, json_bytes(record))
    secure_file(prepare_path)
    return {
        "prepared": True,
        "recheck": True,
        "stamp": stamp,
        "prepare_path": str(prepare_path),
        "private_directory": str(folder),
        "source_sha256": expected_source,
        "state_backend": "local-encrypted",
        "cloud_mutations": False,
        "first_apply_only": False,
        "applied": False,
    }


def prepare_recreate_workload(
    folder: Path,
    inputs_path: Path,
    expected_source: str,
    expected_lock: str,
    tofu: Path,
    mirror: Path,
) -> dict:
    with _workload_lifecycle_lock(folder):
        assert_no_workload_live_latch(folder)
        return _prepare_recreate_workload(folder, inputs_path, expected_source, expected_lock, tofu, mirror)


def _prepare_recreate_workload(
    folder: Path,
    inputs_path: Path,
    expected_source: str,
    expected_lock: str,
    tofu: Path,
    mirror: Path,
) -> dict:
    """Reuse an existing private dir for VM+data-disk recreate. Never regenerate the passphrase."""
    env = clean_environment()
    actual = fingerprint()
    if actual["source_sha256"] != expected_source or actual["lock_sha256"] != expected_lock:
        raise Refused("Foundation source/lock differs from the reviewed hashes")
    inputs = normalize_inputs(read_json(inputs_path))
    context = owner_context(env, inputs, recreate_workload=True)
    tofu = _verify_tofu_mirror(tofu, mirror, env)
    passphrase = folder / "encryption.passphrase"
    state_path = folder / "state/foundation.tfstate"
    if not passphrase.exists():
        raise Refused("Workload recreate requires the existing encryption.passphrase file")
    if not state_path.exists():
        raise Refused("Workload recreate requires existing state/foundation.tfstate")
    for name in ("manifest.json", "inputs.json", "backend.hcl", "tofurc", "encryption.passphrase"):
        secure_file(folder / name)
    ciphertext(state_path)
    for name in ("module", "state", "plans", "workspaces", "logs"):
        private_directory(folder / name)
    prior = read_json(folder / "manifest.json")
    if (
        prior.get("version") != 1
        or prior.get("profile") != NAMESPACE
        or prior.get("resource_group") != RESOURCE_GROUP
    ):
        raise Refused("Prepared bootstrap no longer matches the reviewed source/namespace")
    if set(prior.get("protected_files", {})) != PROTECTED_FILES:
        raise Refused("Prepared bootstrap file bindings are incomplete")
    for name, expected in prior["protected_files"].items():
        if digest(folder / name) != expected:
            raise Refused("Prepared bootstrap inputs changed")
    expected_module = {
        name: value
        for name, value in actual["files"].items()
        if name != "bootstrap_local.py" and not name.startswith("extra/")
    }
    actual_module = {
        path.relative_to(folder / "module").as_posix(): digest(path)
        for path in (folder / "module").rglob("*")
        if path.is_file()
    }
    if actual_module != expected_module:
        raise Refused("Private module snapshot changed")
    bound = dict(inputs)
    bound["state_namespace"] = NAMESPACE
    if read_json(folder / "inputs.json") != bound:
        raise Refused("Workload recreate inputs must match the existing private inputs.json")
    if "allow_workload_recreate" in bound:
        raise Refused(
            "allow_workload_recreate must not be stored in inputs.json; "
            "recreate plans pass -var=allow_workload_recreate=true only"
        )
    first_apply_path = folder / "manifest.first-apply.json"
    if first_apply_path.exists():
        secure_file(first_apply_path)
        first_apply = read_json(first_apply_path)
    else:
        if prior.get("recreate_workload") or prior.get("recover"):
            raise Refused("manifest.first-apply.json is required before a second recreate prepare")
        write_private(first_apply_path, json_bytes(prior))
        first_apply = prior
    tofu_sha = digest(tofu)
    if first_apply.get("tofu_sha256") != tofu_sha:
        raise Refused(
            "Workload recreate tofu_sha256 differs from first-apply manifest: "
            f"first_apply={first_apply.get('tofu_sha256')} recreate={tofu_sha}"
        )
    if first_apply.get("context") != context:
        raise Refused(
            "Workload recreate owner context differs from first-apply manifest: "
            f"first_apply={first_apply.get('context')} recreate={context}"
        )
    stamp = utc_plan_stamp()
    state_backup = folder / "state" / f"foundation.tfstate.pre-recreate-workload-{stamp}"
    write_private(state_backup, state_path.read_bytes())
    secure_file(state_backup)
    ciphertext(state_backup)
    first_plan = folder / "plans/first.tfplan"
    first_plan_sha = digest(first_plan) if first_plan.is_file() else None
    state_sha = digest(state_path)
    manifest = {
        "version": 1,
        "profile": NAMESPACE,
        "resource_group": RESOURCE_GROUP,
        "source": actual,
        "tofu": str(tofu),
        "tofu_sha256": tofu_sha,
        "context": context,
        "protected_files": {name: digest(folder / name) for name in sorted(PROTECTED_FILES)},
        "first_apply_only": True,
        "recreate_workload": True,
        "recreate_workload_backups": {
            "state_pre_recreate": str(state_backup),
            "state_pre_recreate_sha256": digest(state_backup),
            "state_sha256_at_prepare": state_sha,
            "manifest_first_apply": str(first_apply_path),
            "manifest_first_apply_sha256": digest(first_apply_path),
        },
    }
    replace_private(folder / "manifest.json", json_bytes(manifest))
    if first_plan_sha is not None and digest(first_plan) != first_plan_sha:
        raise Refused("Workload recreate prepare must not modify plans/first.tfplan")
    if digest(passphrase) != prior["protected_files"]["encryption.passphrase"]:
        raise Refused("Workload recreate prepare must not modify encryption.passphrase")
    if digest(state_path) != state_sha:
        raise Refused("Workload recreate prepare must not modify state/foundation.tfstate")
    return {
        "prepared": True,
        "recreate_workload": True,
        "private_directory": str(folder),
        "source_sha256": expected_source,
        "state_backend": "local-encrypted",
        "cloud_mutations": False,
        "first_apply_only": True,
    }


def ciphertext(path: Path) -> None:
    secure_file(path)
    value = read_json_large(path)
    if (
        not isinstance(value, dict)
        or value.get("encryption_version") != "v0"
        or not isinstance(value.get("encrypted_data"), str)
        or not value["encrypted_data"]
        or not isinstance(value.get("meta"), dict)
    ):
        raise Refused("Saved artifact is not an encrypted OpenTofu envelope")


def read_json_large(path: Path):
    if path.stat().st_size > 128 * 1024 * 1024:
        raise Refused("Encrypted artifact exceeds the reviewed bound")
    return json.loads(path.read_bytes())


def _verify_prepared(folder: Path) -> tuple[dict, dict]:
    folder = private_directory(folder)
    for name in ("manifest.json", "inputs.json", "backend.hcl", "tofurc", "encryption.passphrase"):
        path = folder / name
        if not path.exists():
            raise Refused(f"Prepared bootstrap missing {name}")
        secure_file(path)
    manifest = read_json(folder / "manifest.json")
    if (
        manifest.get("version") != 1
        or manifest.get("profile") != NAMESPACE
        or manifest.get("resource_group") != RESOURCE_GROUP
        or manifest.get("source") != fingerprint()
    ):
        raise Refused("Prepared bootstrap no longer matches the reviewed source/namespace")
    if set(manifest.get("protected_files", {})) != PROTECTED_FILES:
        raise Refused("Prepared bootstrap file bindings are incomplete")
    for name, expected in manifest["protected_files"].items():
        if digest(folder / name) != expected:
            raise Refused("Prepared bootstrap inputs changed")
    expected_files = {
        name: value
        for name, value in manifest["source"]["files"].items()
        if name != "bootstrap_local.py" and not name.startswith("extra/")
    }
    actual_files = {
        path.relative_to(folder / "module").as_posix(): digest(path)
        for path in (folder / "module").rglob("*")
        if path.is_file()
    }
    if actual_files != expected_files:
        raise Refused("Private module snapshot changed")
    for path in (folder / "module").rglob("*"):
        if path.is_file():
            secure_file(path)
    for name in ("module", "state", "plans", "workspaces", "logs"):
        private_directory(folder / name)
    return manifest, read_json(folder / "inputs.json")


def _latest_recheck_prepare(folder: Path) -> tuple[Path, dict]:
    """Return the latest recheck-prepare path and the record already read/validated.

    ``plan_recheck`` must call this exactly once, pass the returned pair into
    ``_verify_prepared_recheck``, and reuse the same path for the result's
    ``prepare_path``. Callers must use the returned ``record`` and must not
    ``read_json`` or re-glob the file again — a second look could observe a
    swapped/tampered or newer artifact.
    """
    matches = sorted(
        path
        for path in folder.glob("recheck-prepare-*.json")
        if path.is_file() and RECHECK_PREPARE_NAME.match(path.name)
    )
    if not matches:
        raise Refused(
            "Post-apply re-check requires prepare --recheck "
            "(recheck-prepare-<UTC>.json) on this private directory"
        )
    latest = matches[-1]
    secure_file(latest)
    record = read_json(latest)
    if record.get("private_directory") != str(folder):
        raise Refused(
            "recheck-prepare private_directory does not match this private directory"
        )
    return latest, record


def _verify_prepared_recheck(
    folder: Path,
    prepare_path: Path,
    recheck_prepare: dict,
) -> tuple[dict, dict, dict]:
    """Like ``_verify_prepared``, but do not require ``manifest.source == fingerprint()``.

    Re-check binds the reviewed source digests via the ``prepare_path`` /
    ``recheck_prepare`` already returned by ``_latest_recheck_prepare``. Callers
    (``plan_recheck``) must invoke ``_latest_recheck_prepare`` exactly once and
    pass that same ``(path, record)`` here — this function must not glob or
    ``read_json`` any ``recheck-prepare-*.json`` itself. That record's
    ``source`` must equal the running ``fingerprint()`` and
    ``private_directory`` must equal this folder. Private module ``*.tf`` files
    must still match that reviewed fingerprint. Manifest ``source`` may still
    reflect an older prepare --recover head.
    """
    folder = private_directory(folder)
    for name in ("manifest.json", "inputs.json", "backend.hcl", "tofurc", "encryption.passphrase"):
        path = folder / name
        if not path.exists():
            raise Refused(f"Prepared bootstrap missing {name}")
        secure_file(path)
    manifest = read_json(folder / "manifest.json")
    if (
        manifest.get("version") != 1
        or manifest.get("profile") != NAMESPACE
        or manifest.get("resource_group") != RESOURCE_GROUP
    ):
        raise Refused("Prepared bootstrap no longer matches the reviewed source/namespace")
    # Intentionally omit: manifest.get("source") != fingerprint()
    if set(manifest.get("protected_files", {})) != PROTECTED_FILES:
        raise Refused("Prepared bootstrap file bindings are incomplete")
    for name, expected in manifest["protected_files"].items():
        if digest(folder / name) != expected:
            raise Refused("Prepared bootstrap inputs changed")
    secure_file(prepare_path)
    # Use the caller-provided validated record — do not re-glob or re-read.
    if not recheck_prepare.get("recheck") or not isinstance(recheck_prepare.get("source"), dict):
        raise Refused("recheck-prepare artifact is missing reviewed source digests")
    if recheck_prepare.get("source") != fingerprint():
        raise Refused(
            "recheck-prepare source digests do not match the running foundation fingerprint"
        )
    reviewed = recheck_prepare["source"]
    expected_files = {
        name: value
        for name, value in reviewed.get("files", {}).items()
        if name != "bootstrap_local.py" and not name.startswith("extra/")
    }
    actual_files = {
        path.relative_to(folder / "module").as_posix(): digest(path)
        for path in (folder / "module").rglob("*")
        if path.is_file()
    }
    if actual_files != expected_files:
        raise Refused("Private module snapshot changed")
    for path in (folder / "module").rglob("*"):
        if path.is_file():
            secure_file(path)
    for name in ("module", "state", "plans", "workspaces", "logs"):
        private_directory(folder / name)
    return manifest, read_json(folder / "inputs.json"), recheck_prepare


def _assert_recheck_commands_safe(commands: list[tuple[str, list[str]]]) -> None:
    """Refuse planted apply / -refresh=false before any tofu subprocess runs."""
    for _name, args in commands:
        if not isinstance(args, list) or not args:
            raise Refused("Post-apply re-check command list is invalid")
        if args[0] == "apply" or "apply" in args[1:]:
            raise Refused("Post-apply re-check must never invoke tofu apply")
        if args[0] == "plan" and "-refresh=false" in args:
            raise Refused("Post-apply re-check must refresh against Azure (no -refresh=false)")


def _recheck_tofu_commands(
    *, backend_hcl: Path, inputs: Path, plan_out: Path
) -> list[tuple[str, list[str]]]:
    commands = [
        (
            "init",
            [
                "init",
                "-input=false",
                "-lockfile=readonly",
                "-reconfigure",
                "-backend-config=" + str(backend_hcl),
            ],
        ),
        (
            "plan",
            [
                "plan",
                "-input=false",
                "-lock=true",
                "-lock-timeout=30s",
                "-var-file=" + str(inputs),
                "-out=" + str(plan_out),
            ],
        ),
    ]
    _assert_recheck_commands_safe(commands)
    return commands


def plan_json_allow_workload_recreate_value(plan_json: dict):
    """Return tofu show -json variables.allow_workload_recreate.value, or None if absent."""
    variables = plan_json.get("variables")
    if not isinstance(variables, dict):
        return None
    entry = variables.get("allow_workload_recreate")
    if not isinstance(entry, dict) or "value" not in entry:
        return None
    return entry["value"]


def assert_non_recreate_refuses_allow_workload_recreate_true(
    plan_json: dict, *, mode: str
) -> None:
    """First-apply / recover / recheck must refuse when the plan var is True."""
    if plan_json_allow_workload_recreate_value(plan_json) is True:
        raise Refused(
            f"{mode} refuses when plan variables.allow_workload_recreate.value is true; "
            "use --recreate-workload only"
        )


def sanitize_plan_summary(plan_json: dict, *, inputs: dict, plan_sha256: str) -> dict:
    assert_non_recreate_refuses_allow_workload_recreate_true(
        plan_json, mode="First-apply plan"
    )
    changes = plan_json.get("resource_changes") or []
    counts: dict[str, Counter] = {
        "create": Counter(),
        "update": Counter(),
        "replace": Counter(),
        "delete": Counter(),
    }
    for change in changes:
        actions = (change.get("change") or {}).get("actions") or []
        rtype = change.get("type") or "unknown"
        if rtype == "azurerm_virtual_machine_run_command":
            raise Refused("Plan contains azurerm_virtual_machine_run_command; Run Command is forbidden")
        if rtype not in ALLOWED_RESOURCE_TYPES:
            raise Refused(f"Plan contains unlisted resource type: {rtype}")
        after = (change.get("change") or {}).get("after") or {}
        if rtype == "azurerm_virtual_machine_extension":
            publisher = after.get("publisher")
            ext_type = after.get("type")
            if publisher != MONITOR_AGENT_PUBLISHER or ext_type != MONITOR_AGENT_TYPE:
                raise Refused(
                    "Plan contains unlisted VM extension; only AzureMonitorLinuxAgent is allowed"
                )
        if actions == ["create"]:
            counts["create"][rtype] += 1
        elif actions == ["update"]:
            counts["update"][rtype] += 1
        elif "delete" in actions and "create" in actions:
            counts["replace"][rtype] += 1
        elif actions == ["delete"]:
            counts["delete"][rtype] += 1
    if sum(counts["delete"].values()) or sum(counts["replace"].values()):
        raise Refused("Plan contains delete or replace actions; first-apply-only tooling refuses")
    enabled = bool(inputs.get("enable_azure_openai", False))
    summary = {
        "create": dict(sorted(counts["create"].items())),
        "update": dict(sorted(counts["update"].items())),
        "replace": {},
        "delete": {},
        "enable_azure_openai": enabled,
        "subscription_id": inputs["subscription_id"],
        "tenant_id": inputs["tenant_id"],
        "plan_sha256": plan_sha256,
        "resource_group": RESOURCE_GROUP,
        "first_apply_only": True,
    }
    summary["summary_sha256"] = hashlib.sha256(json_bytes(summary)).hexdigest()
    return summary


def _string_candidates(value) -> list[str]:
    found: list[str] = []
    if isinstance(value, str):
        found.append(value)
    elif isinstance(value, dict):
        for item in value.values():
            found.extend(_string_candidates(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_string_candidates(item))
    return found


def _iter_unknown_true_keys(value, prefix: str = ""):
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if item is True:
                yield path, str(key)
            else:
                yield from _iter_unknown_true_keys(item, path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _iter_unknown_true_keys(item, f"{prefix}[{index}]")


def _relevant_unknown_reference_key(key: str) -> bool:
    return key in RELEVANT_UNKNOWN_REFERENCE_KEYS


def _change_resource_group(change: dict) -> str | None:
    after = (change.get("change") or {}).get("after") or {}
    rtype = change.get("type") or ""
    if rtype == "azurerm_resource_group":
        name = after.get("name")
        return name if isinstance(name, str) else None
    rg = after.get("resource_group_name")
    if isinstance(rg, str) and rg:
        return rg
    scope = after.get("scope")
    if isinstance(scope, str):
        match = ARM_RESOURCE_GROUP_RE.search(scope)
        if match:
            return match.group(2)
    return None


def _in_prod_rg_arm_ids(after) -> list[str]:
    found: list[str] = []
    for raw in _string_candidates(after):
        for match in ARM_RESOURCE_GROUP_RE.finditer(raw):
            if match.group(2).lower() == RESOURCE_GROUP.lower():
                found.append(raw)
    return found


def _assert_arm_ids_in_prod_rg(after, *, subscription_id: str, address: str) -> None:
    for raw in _string_candidates(after):
        for match in ARM_SUBSCRIPTION_RE.finditer(raw):
            sub = match.group(1)
            if sub.lower() != subscription_id.lower():
                raise Refused(
                    "Recovery plan ARM id is outside "
                    f"{RESOURCE_GROUP} in subscription {subscription_id}: "
                    f"{address} -> /subscriptions/{sub}"
                )
        for match in ARM_RESOURCE_GROUP_RE.finditer(raw):
            sub, rg = match.group(1), match.group(2)
            if sub.lower() != subscription_id.lower() or rg.lower() != RESOURCE_GROUP.lower():
                raise Refused(
                    "Recovery plan ARM id is outside "
                    f"{RESOURCE_GROUP} in subscription {subscription_id}: "
                    f"{address} -> /subscriptions/{sub}/resourceGroups/{rg}"
                )


def _assert_no_unknown_id_fields(change: dict) -> None:
    after_unknown = (change.get("change") or {}).get("after_unknown")
    if after_unknown is None:
        return
    for path, key in _iter_unknown_true_keys(after_unknown):
        if _relevant_unknown_reference_key(key):
            raise Refused(
                "Recovery plan has after_unknown configured reference "
                f"(refused until known): {change.get('address') or change.get('type')} {path}"
            )


def _assert_recover_entry_type_guards(change: dict) -> str:
    rtype = change.get("type") or "unknown"
    if rtype == "azurerm_virtual_machine_run_command":
        raise Refused("Plan contains azurerm_virtual_machine_run_command; Run Command is forbidden")
    if rtype not in ALLOWED_RESOURCE_TYPES:
        raise Refused(f"Plan contains unlisted resource type: {rtype}")
    after = (change.get("change") or {}).get("after") or {}
    if rtype == "azurerm_virtual_machine_extension":
        publisher = after.get("publisher") if isinstance(after, dict) else None
        ext_type = after.get("type") if isinstance(after, dict) else None
        if publisher != MONITOR_AGENT_PUBLISHER or ext_type != MONITOR_AGENT_TYPE:
            raise Refused("Plan contains unlisted VM extension; only AzureMonitorLinuxAgent is allowed")
    return rtype


def assert_recover_add_only(plan_json: dict, *, subscription_id: str) -> Counter:
    """Hard-fail unless the plan is ADD-ONLY inside the production RG with no staging names."""
    if not isinstance(subscription_id, str) or not subscription_id:
        raise Refused("Recovery plan validation requires subscription_id")
    changes = plan_json.get("resource_changes") or []
    creates: Counter = Counter()
    for change in changes:
        if not isinstance(change, dict):
            raise Refused("Recovery plan resource_changes entries must be objects")
        rtype = _assert_recover_entry_type_guards(change)
        if change.get("importing") is not None:
            raise Refused("Recovery plan must not import resources into state")
        previous = change.get("previous_address")
        address = change.get("address")
        if previous is not None and previous != address:
            raise Refused("Recovery plan must not move/rename resources in state")
        if change.get("deposed") is not None:
            raise Refused("Recovery plan must not include deposed resource instances")
        change_body = change.get("change")
        if not isinstance(change_body, dict):
            raise Refused("Recovery plan change body is missing")
        if "actions" not in change_body:
            raise Refused("Recovery plan change is missing actions")
        actions = change_body.get("actions")
        if not isinstance(actions, list) or not actions:
            raise Refused("Recovery plan change has empty or invalid actions")
        if actions == ["no-op"] or actions == ["read"]:
            continue
        after = change_body.get("after") or {}
        if not isinstance(after, dict):
            after = {}
        _assert_no_unknown_id_fields(change)
        if actions == ["update"]:
            raise Refused("Recovery plan must be ADD-ONLY; update/change actions are refused")
        if "delete" in actions and "create" in actions:
            raise Refused("Recovery plan must be ADD-ONLY; replace actions are refused")
        if actions == ["delete"] or "delete" in actions:
            raise Refused("Recovery plan must be ADD-ONLY; destroy actions are refused")
        if actions != ["create"]:
            raise Refused(f"Recovery plan must be ADD-ONLY; refused actions {actions}")
        address_label = str(change.get("address") or rtype)
        if rtype != "terraform_data":
            _assert_arm_ids_in_prod_rg(
                after, subscription_id=subscription_id, address=address_label
            )
            rg = _change_resource_group(change)
            if rg is None:
                if not _in_prod_rg_arm_ids(after):
                    raise Refused(
                        "Recovery plan resource is outside "
                        f"{RESOURCE_GROUP}: {address_label}"
                    )
            elif rg.lower() != RESOURCE_GROUP.lower():
                raise Refused(
                    "Recovery plan resource is outside "
                    f"{RESOURCE_GROUP}: {address_label}"
                )
        candidates = [
            str(change.get("address") or ""),
            str(change.get("name") or ""),
            str(change.get("module_address") or ""),
            *(_string_candidates(after)),
        ]
        for raw in candidates:
            if STAGING_RG_NEEDLE in raw.lower():
                raise Refused("Recovery plan touches staging resource group names")
        try:
            refuse_cross_environment("production", candidates)
        except NameGuardError as exc:
            raise Refused(f"Recovery plan touches staging names: {exc}") from exc
        creates[rtype] += 1
    if not sum(creates.values()):
        raise Refused("Recovery plan has no create actions to apply")
    return creates


def sanitize_recover_plan_summary(plan_json: dict, *, inputs: dict, plan_sha256: str) -> dict:
    assert_non_recreate_refuses_allow_workload_recreate_true(
        plan_json, mode="Recovery plan"
    )
    creates = assert_recover_add_only(plan_json, subscription_id=str(inputs["subscription_id"]))
    enabled = bool(inputs.get("enable_azure_openai", False))
    summary = {
        "create": dict(sorted(creates.items())),
        "update": {},
        "replace": {},
        "delete": {},
        "enable_azure_openai": enabled,
        "subscription_id": inputs["subscription_id"],
        "tenant_id": inputs["tenant_id"],
        "plan_sha256": plan_sha256,
        "resource_group": RESOURCE_GROUP,
        "first_apply_only": False,
        "recover": True,
    }
    summary["summary_sha256"] = hashlib.sha256(json_bytes(summary)).hexdigest()
    return summary


def assert_recheck_zero_drift(plan_json: dict) -> list[str]:
    """Hard-fail unless the plan has 0 add/change/destroy/replace (and no import/move/deposed).

    On drift, raises RecheckDriftRefused listing resource addresses only (no attribute
    values). ``main()`` prints that message to stderr so operators see the addresses.
    Returns the empty drift address list on pass.
    """
    changes = plan_json.get("resource_changes") or []
    drifted: list[str] = []
    for change in changes:
        if not isinstance(change, dict):
            raise Refused("Post-apply re-check resource_changes entries must be objects")
        rtype = _assert_recover_entry_type_guards(change)
        address = str(change.get("address") or rtype)
        if change.get("importing") is not None:
            raise RecheckDriftRefused(
                "Post-apply re-check found import; refused. Addresses: " + address
            )
        previous = change.get("previous_address")
        if previous is not None and previous != change.get("address"):
            raise RecheckDriftRefused(
                "Post-apply re-check found moved resource; refused. Addresses: " + address
            )
        if change.get("deposed") is not None:
            raise RecheckDriftRefused(
                "Post-apply re-check found deposed resource; refused. Addresses: " + address
            )
        change_body = change.get("change")
        if not isinstance(change_body, dict):
            raise Refused("Post-apply re-check change body is missing")
        if "actions" not in change_body:
            raise Refused("Post-apply re-check change is missing actions")
        actions = change_body.get("actions")
        if not isinstance(actions, list) or not actions:
            raise Refused("Post-apply re-check change has empty or invalid actions")
        after = change_body.get("after") or {}
        if not isinstance(after, dict):
            after = {}
        candidates = [
            str(change.get("address") or ""),
            str(change.get("name") or ""),
            str(change.get("module_address") or ""),
            *(_string_candidates(after)),
        ]
        for raw in candidates:
            if STAGING_RG_NEEDLE in raw.lower():
                raise Refused("Post-apply re-check touches staging resource group names")
        try:
            refuse_cross_environment("production", candidates)
        except NameGuardError as exc:
            raise Refused(f"Post-apply re-check touches staging names: {exc}") from exc
        if actions == ["no-op"] or actions == ["read"]:
            continue
        drifted.append(address)
    if drifted:
        # Addresses only — never attribute values from the plan JSON.
        raise RecheckDriftRefused(
            "Post-apply re-check found drift (add/change/destroy/replace); refused. Addresses: "
            + ", ".join(drifted)
        )
    return drifted


def sanitize_recheck_plan_summary(plan_json: dict, *, inputs: dict, plan_sha256: str) -> dict:
    assert_non_recreate_refuses_allow_workload_recreate_true(
        plan_json, mode="Post-apply re-check"
    )
    assert_recheck_zero_drift(plan_json)
    enabled = bool(inputs.get("enable_azure_openai", False))
    summary = {
        "create": {},
        "update": {},
        "replace": {},
        "delete": {},
        "enable_azure_openai": enabled,
        "subscription_id": inputs["subscription_id"],
        "tenant_id": inputs["tenant_id"],
        "plan_sha256": plan_sha256,
        "resource_group": RESOURCE_GROUP,
        "first_apply_only": False,
        "recheck": True,
    }
    summary["summary_sha256"] = hashlib.sha256(json_bytes(summary)).hexdigest()
    return summary


def assert_recreate_allow_var(plan_json: dict) -> bool:
    """Require tofu show -json variables.allow_workload_recreate.value is exactly True."""
    value = plan_json_allow_workload_recreate_value(plan_json)
    if value is not True:
        raise Refused(
            "Workload recreate requires plan variables.allow_workload_recreate.value "
            "to be true (from tofu show -json); the mode refuses when the variable is "
            f"false or missing (got {value!r})"
        )
    return True


def _is_replace_actions(actions: list) -> bool:
    return actions in (["delete", "create"], ["create", "delete"])


def _runtime_alert_update_limited_to_query_or_scopes(change_body: dict) -> bool:
    """True when before/after differ only in scopes and/or criteria.query."""
    def without_query_or_scopes(values: dict) -> dict:
        remaining = {key: value for key, value in values.items() if key != "scopes"}
        criteria = remaining.get("criteria")
        if isinstance(criteria, dict):
            remaining["criteria"] = {key: value for key, value in criteria.items() if key != "query"}
        elif isinstance(criteria, list) and len(criteria) == 1 and isinstance(criteria[0], dict):
            remaining["criteria"] = [{key: value for key, value in criteria[0].items() if key != "query"}]
        return remaining

    def has_unknown(value) -> bool:
        if isinstance(value, dict):
            return any(has_unknown(entry) for entry in value.values())
        if isinstance(value, list):
            return any(has_unknown(entry) for entry in value)
        return value is not False

    before = change_body.get("before")
    after = change_body.get("after")
    unknown = change_body.get("after_unknown", {})
    return (
        all(isinstance(values, dict) for values in (before, after, unknown))
        and without_query_or_scopes(before) == without_query_or_scopes(after)
        and not has_unknown(without_query_or_scopes(unknown))
    )


def assert_recreate_workload_changeset(
    plan_json: dict, *, subscription_id: str
) -> dict[str, list[str]]:
    """Hard-fail unless the plan is exactly VM+data-disk(+attachment) recreate.

    Allowed non-noop actions for each required address:
    - replace, or
    - create (mid-replace recovery when the address is absent from state)

    Optional replace-only for health extension + DCRA when runtime monitoring
    retargets the new VM. Optional in-place updates of the three
    azurerm_monitor_metric_alert.vm[...] and update-only query/scopes changes
    on the two scheduled-query runtime alerts.

    Everything else must be no-op/read. Public IP, NIC, identity, role assignments,
    Key Vault, storage, registry, OpenAI, network, DNS, and staging are refused on
    any create/update/replace/delete.
    """
    assert_recreate_allow_var(plan_json)
    if not isinstance(subscription_id, str) or not subscription_id:
        raise Refused("Workload recreate plan validation requires subscription_id")
    changes = plan_json.get("resource_changes") or []
    recreate_addresses: list[str] = []
    replace_addresses: list[str] = []
    create_addresses: list[str] = []
    update_addresses: list[str] = []
    for change in changes:
        if not isinstance(change, dict):
            raise Refused("Workload recreate resource_changes entries must be objects")
        rtype = _assert_recover_entry_type_guards(change)
        address = str(change.get("address") or rtype)
        if change.get("importing") is not None:
            raise Refused("Workload recreate plan must not import resources into state")
        previous = change.get("previous_address")
        if previous is not None and previous != change.get("address"):
            raise Refused("Workload recreate plan must not move/rename resources in state")
        if change.get("deposed") is not None:
            raise Refused("Workload recreate plan must not include deposed resource instances")
        change_body = change.get("change")
        if not isinstance(change_body, dict):
            raise Refused("Workload recreate plan change body is missing")
        if "actions" not in change_body:
            raise Refused("Workload recreate plan change is missing actions")
        actions = change_body.get("actions")
        if not isinstance(actions, list) or not actions:
            raise Refused("Workload recreate plan change has empty or invalid actions")
        after = change_body.get("after") or {}
        if not isinstance(after, dict):
            after = {}
        candidates = [
            str(change.get("address") or ""),
            str(change.get("name") or ""),
            str(change.get("module_address") or ""),
            *(_string_candidates(after)),
        ]
        for raw in candidates:
            if STAGING_RG_NEEDLE in raw.lower():
                raise Refused("Workload recreate plan touches staging resource group names")
        try:
            refuse_cross_environment("production", candidates)
        except NameGuardError as exc:
            raise Refused(f"Workload recreate plan touches staging names: {exc}") from exc
        if actions == ["no-op"] or actions == ["read"]:
            continue
        if _is_replace_actions(actions):
            if address in RECREATE_REQUIRED_REPLACE_ADDRESSES:
                recreate_addresses.append(address)
                replace_addresses.append(address)
                continue
            if address in RECREATE_ALLOWED_OPTIONAL_REPLACE_ADDRESSES:
                replace_addresses.append(address)
                continue
            if rtype in RECREATE_FORBIDDEN_TOUCH_TYPES:
                raise Refused(
                    "Workload recreate refuses changes to public IP, NIC, identity, role "
                    f"assignments, Key Vault, storage, registry, OpenAI, network, DNS, or "
                    f"other non-workload resources: {address}"
                )
            raise Refused(f"Workload recreate plan has unexpected replace: {address}")
        if actions == ["create"]:
            if address not in RECREATE_REQUIRED_REPLACE_ADDRESSES:
                if rtype in RECREATE_FORBIDDEN_TOUCH_TYPES:
                    raise Refused(
                        "Workload recreate refuses changes to public IP, NIC, identity, role "
                        f"assignments, Key Vault, storage, registry, OpenAI, network, DNS, or "
                        f"other non-workload resources: {address}"
                    )
                raise Refused(f"Workload recreate plan must not create extra resources: {address}")
            recreate_addresses.append(address)
            create_addresses.append(address)
            continue
        if actions == ["update"]:
            if address in RECREATE_ALLOWED_ALERT_ADDRESSES:
                update_addresses.append(address)
                continue
            if address in RECREATE_ALLOWED_RUNTIME_ALERT_ADDRESSES:
                if not _runtime_alert_update_limited_to_query_or_scopes(change_body):
                    raise Refused(
                        "Workload recreate allows scheduled-query alert updates only when "
                        f"limited to query or scopes; refused: {address}"
                    )
                update_addresses.append(address)
                continue
            if rtype in RECREATE_FORBIDDEN_TOUCH_TYPES:
                raise Refused(
                    "Workload recreate refuses changes to public IP, NIC, identity, role "
                    f"assignments, Key Vault, storage, registry, OpenAI, network, DNS, or "
                    f"other non-workload resources: {address}"
                )
            raise Refused(
                "Workload recreate allows in-place updates only for the three "
                "azurerm_monitor_metric_alert.vm[...] resources and query/scopes "
                f"updates on the two runtime scheduled-query alerts; refused: {address}"
            )
        if actions == ["delete"] or "delete" in actions:
            if rtype in RECREATE_FORBIDDEN_TOUCH_TYPES:
                raise Refused(
                    "Workload recreate refuses changes to public IP, NIC, identity, role "
                    f"assignments, Key Vault, storage, registry, OpenAI, network, DNS, or "
                    f"other non-workload resources: {address}"
                )
            raise Refused(f"Workload recreate plan must not destroy extra resources: {address}")
        if rtype in RECREATE_FORBIDDEN_TOUCH_TYPES:
            raise Refused(
                "Workload recreate refuses changes to public IP, NIC, identity, role "
                f"assignments, Key Vault, storage, registry, OpenAI, network, DNS, or "
                f"other non-workload resources: {address}"
            )
        raise Refused(f"Workload recreate plan refused actions {actions} on {address}")
    missing = RECREATE_REQUIRED_REPLACE_ADDRESSES - set(recreate_addresses)
    if missing:
        raise Refused(
            "Workload recreate plan is missing required VM/disk/attachment "
            "create-or-replace actions: "
            + ", ".join(sorted(missing))
        )
    if set(recreate_addresses) != RECREATE_REQUIRED_REPLACE_ADDRESSES:
        raise Refused(
            "Workload recreate plan create/replace set must be exactly "
            + ", ".join(sorted(RECREATE_REQUIRED_REPLACE_ADDRESSES))
        )
    allowed_updates = RECREATE_ALLOWED_ALERT_ADDRESSES | RECREATE_ALLOWED_RUNTIME_ALERT_ADDRESSES
    unexpected_alerts = set(update_addresses) - allowed_updates
    if unexpected_alerts:
        raise Refused(
            "Workload recreate plan has unexpected alert updates: "
            + ", ".join(sorted(unexpected_alerts))
        )
    return {
        "replace_addresses": sorted(replace_addresses),
        "create_addresses": sorted(create_addresses),
        "recreate_addresses": sorted(recreate_addresses),
        "update_addresses": sorted(update_addresses),
    }


def sanitize_recreate_workload_plan_summary(
    plan_json: dict, *, inputs: dict, plan_sha256: str
) -> dict:
    allow_value = assert_recreate_allow_var(plan_json)
    addressed = assert_recreate_workload_changeset(
        plan_json,
        subscription_id=str(inputs["subscription_id"]),
    )
    enabled = bool(inputs.get("enable_azure_openai", False))
    replace_counts: Counter = Counter()
    create_counts: Counter = Counter()

    def _count(address: str, into: Counter) -> None:
        if address.startswith("azurerm_linux_virtual_machine."):
            into["azurerm_linux_virtual_machine"] += 1
        elif address.startswith("azurerm_managed_disk."):
            into["azurerm_managed_disk"] += 1
        elif address.startswith("azurerm_virtual_machine_data_disk_attachment."):
            into["azurerm_virtual_machine_data_disk_attachment"] += 1
        elif address.startswith("azurerm_virtual_machine_extension."):
            into["azurerm_virtual_machine_extension"] += 1
        elif address.startswith("azurerm_monitor_data_collection_rule_association."):
            into["azurerm_monitor_data_collection_rule_association"] += 1

    for address in addressed["replace_addresses"]:
        _count(address, replace_counts)
    for address in addressed["create_addresses"]:
        _count(address, create_counts)
    update_counts: Counter = Counter()
    for address in addressed["update_addresses"]:
        if address.startswith("azurerm_monitor_metric_alert."):
            update_counts["azurerm_monitor_metric_alert"] += 1
        elif address.startswith("azurerm_monitor_scheduled_query_rules_alert_v2."):
            update_counts["azurerm_monitor_scheduled_query_rules_alert_v2"] += 1
    summary = {
        "create": dict(sorted(create_counts.items())),
        "update": dict(sorted(update_counts.items())),
        "replace": dict(sorted(replace_counts.items())),
        "delete": {},
        "replace_addresses": addressed["replace_addresses"],
        "create_addresses": addressed["create_addresses"],
        "recreate_addresses": addressed["recreate_addresses"],
        "update_addresses": addressed["update_addresses"],
        "enable_azure_openai": enabled,
        "subscription_id": inputs["subscription_id"],
        "tenant_id": inputs["tenant_id"],
        "plan_sha256": plan_sha256,
        "resource_group": RESOURCE_GROUP,
        "first_apply_only": False,
        "recreate_workload": True,
        "allow_workload_recreate": allow_value,
    }
    summary["summary_sha256"] = hashlib.sha256(json_bytes(summary)).hexdigest()
    return summary


def _plan_has_allow_workload_recreate_true(args: list[str]) -> bool:
    for index, item in enumerate(args):
        if item == f"-var={ALLOW_WORKLOAD_RECREATE_VAR}":
            return True
        if item == "-var" and index + 1 < len(args) and args[index + 1] == ALLOW_WORKLOAD_RECREATE_VAR:
            return True
    return False


def _assert_recreate_commands_safe(
    commands: list[tuple[str, list[str]]],
    *,
    replace_addresses: frozenset[str] | set[str] | None = None,
) -> None:
    """Refuse planted apply / missing plan / missing allow var / illegal -replace before tofu runs."""
    expected_replaces = (
        frozenset(replace_addresses)
        if replace_addresses is not None
        else frozenset({RECREATE_VM_ADDRESS, RECREATE_DISK_ADDRESS})
    )
    if not expected_replaces <= {RECREATE_VM_ADDRESS, RECREATE_DISK_ADDRESS}:
        raise Refused("Workload recreate -replace set may only include the workload VM and data disk")
    saw_plan = False
    for _name, args in commands:
        if not isinstance(args, list) or not args:
            raise Refused("Workload recreate command list is invalid")
        if args[0] == "apply" or "apply" in args[1:]:
            raise Refused("Workload recreate command builder must not invoke tofu apply here")
        if args[0] != "plan":
            continue
        saw_plan = True
        joined = " ".join(args)
        if "-var=allow_workload_recreate=false" in args or "allow_workload_recreate=false" in joined:
            raise Refused(
                "Workload recreate requires allow_workload_recreate=true; "
                "the mode refuses when the variable is false"
            )
        if not _plan_has_allow_workload_recreate_true(args):
            raise Refused("Workload recreate plan must pass -var=allow_workload_recreate=true")
        present_replaces = {
            item.removeprefix("-replace=")
            for item in args
            if isinstance(item, str) and item.startswith("-replace=")
        }
        if present_replaces != set(expected_replaces):
            raise Refused(
                "Workload recreate -replace set must match state presence: expected "
                + ", ".join(sorted(expected_replaces) or ["(none)"])
                + "; got "
                + ", ".join(sorted(present_replaces) or ["(none)"])
            )
    if not saw_plan:
        raise Refused("Workload recreate command list is missing plan")


def _recreate_workload_tofu_commands(
    *,
    backend_hcl: Path,
    inputs: Path,
    plan_out: Path,
    replace_addresses: frozenset[str] | set[str] | None = None,
) -> list[tuple[str, list[str]]]:
    replaces = (
        frozenset(replace_addresses)
        if replace_addresses is not None
        else frozenset({RECREATE_VM_ADDRESS, RECREATE_DISK_ADDRESS})
    )
    plan_args = [
        "plan",
        "-input=false",
        "-lock=true",
        "-lock-timeout=30s",
        "-var-file=" + str(inputs),
        f"-var={ALLOW_WORKLOAD_RECREATE_VAR}",
    ]
    for address in sorted(replaces):
        plan_args.append(f"-replace={address}")
    plan_args.append("-out=" + str(plan_out))
    commands = [
        (
            "init",
            [
                "init",
                "-input=false",
                "-lockfile=readonly",
                "-reconfigure",
                "-backend-config=" + str(backend_hcl),
            ],
        ),
        ("plan", plan_args),
    ]
    _assert_recreate_commands_safe(commands, replace_addresses=replaces)
    return commands


def _state_addresses(
    *,
    tofu: Path,
    folder: Path,
    env: dict,
) -> frozenset[str]:
    """Return tofu state list addresses. Fail-closed on empty or failed list."""
    listed = command(
        [str(tofu), "state", "list"],
        cwd=folder / "module",
        env=env,
        timeout=120,
    )
    if listed.returncode:
        raise Refused("Workload recreate could not list OpenTofu state addresses")
    lines = [
        line.strip()
        for line in listed.stdout.decode(errors="replace").splitlines()
        if line.strip()
    ]
    if not lines:
        raise Refused("Workload recreate state list is empty; refuse create-from-empty-state")
    return frozenset(lines)


def _replace_addresses_for_state(state_addresses: frozenset[str] | set[str]) -> frozenset[str]:
    """Pass -replace only for VM/disk addresses still present in state (mid-replace)."""
    return frozenset(
        address
        for address in (RECREATE_VM_ADDRESS, RECREATE_DISK_ADDRESS)
        if address in state_addresses
    )


def expected_workload_vm_resource_id(subscription_id: str) -> str:
    """Canonical Azure resource ID for the production workload VM."""
    if not isinstance(subscription_id, str) or not subscription_id.strip():
        raise Refused("Workload VM resource id requires subscription_id")
    return (
        f"/subscriptions/{subscription_id.strip()}/resourceGroups/{RESOURCE_GROUP}"
        f"/providers/Microsoft.Compute/virtualMachines/{VM_AZURE_NAME}"
    )


def managed_by_matches_workload_vm(managed_by: object, *, subscription_id: str) -> bool:
    """Exact case-insensitive match on the full workload VM resource ID (no substring)."""
    if not isinstance(managed_by, str) or not managed_by.strip():
        return False
    expected = expected_workload_vm_resource_id(subscription_id)
    return managed_by.strip().casefold() == expected.casefold()


def _list_named_os_disks(
    env: dict, inputs: dict, *, require_present: bool
) -> list[dict]:
    """List disks named OS_DISK_NAME.

    CLI failure / timeout / OSError / non-array / invalid JSON always refuse
    (fail-closed). When require_present is True, an empty filtered list also
    refuses (post-apply / ApplyAttempted). When False (preflight), empty means
    no orphan candidate yet.
    """
    try:
        result = command(
            [
                "az",
                "disk",
                "list",
                "--resource-group",
                RESOURCE_GROUP,
                "--subscription",
                inputs["subscription_id"],
                "--query",
                f"[?name=='{OS_DISK_NAME}'].{{name:name,managedBy:managedBy}}",
                "--output",
                "json",
                "--only-show-errors",
            ],
            env=env,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
        raise Refused(
            f"Could not list OS disks named {OS_DISK_NAME}; refuse (fail-closed): {exc}"
        ) from exc
    if result.returncode:
        raise Refused(
            f"Could not list OS disks named {OS_DISK_NAME}; refuse (fail-closed)"
        )
    raw = result.stdout or b""
    if not raw.strip():
        if require_present:
            raise Refused(
                f"OS disk list for {OS_DISK_NAME} was empty; refuse (fail-closed, not a pass)"
            )
        return []
    try:
        disks = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise Refused(
            f"OS disk list for {OS_DISK_NAME} was not valid JSON; refuse (fail-closed)"
        ) from exc
    if not isinstance(disks, list):
        raise Refused(
            f"OS disk list for {OS_DISK_NAME} was not a JSON array; refuse (fail-closed)"
        )
    named = [
        disk
        for disk in disks
        if isinstance(disk, dict) and disk.get("name") == OS_DISK_NAME
    ]
    if require_present and not named:
        raise Refused(
            f"No disk named {OS_DISK_NAME} was returned; refuse empty az disk list "
            "(fail-closed, not a pass)"
        )
    return named


def assert_no_workload_live_latch(folder: Path) -> None:
    """Refuse --recreate-workload after go-live wrote workload-live.json (mode 0600)."""
    latch = folder / WORKLOAD_LIVE_NAME
    try:
        latch.lstat()
    except FileNotFoundError:
        return
    raise Refused(f"{WORKLOAD_LIVE_NAME} is present; --recreate-workload refuses after go-live")


@contextmanager
def _workload_lifecycle_lock(folder: Path):
    """Serialize first admission with recreate in the same private directory."""
    private_directory(folder)
    fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Refused("First package admission or workload recreate is already running") from exc
        yield fd
    finally:
        os.close(fd)


def admit_first_package(folder: Path) -> dict:
    """Record the operator's first package admission before opening access."""
    with _workload_lifecycle_lock(folder) as folder_fd:
        latch = folder / WORKLOAD_LIVE_NAME
        record = {"go_live": True}
        try:
            stream = _open_private_exclusive(latch)
        except FileExistsError:
            secure_file(latch)
            existing = read_json(latch)
            if not isinstance(existing, dict) or existing.get("go_live") is not True:
                raise Refused(f"Existing {WORKLOAD_LIVE_NAME} has unexpected contents")
        else:
            with stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(json_bytes(record))
                stream.flush()
                os.fsync(stream.fileno())
        os.fsync(folder_fd)
        return {"first_package_admitted": True, "workload_live_latch": str(latch)}


def assert_os_disk_preflight(env: dict, inputs: dict) -> None:
    """Pre-apply: refuse any OS_DISK_NAME disk not attached to the current VM.

    Missing disk is allowed (mid-replace after delete_os_disk_on_deletion). An
    existing unattached / wrong-VM disk refuses before tofu apply starts.
    Failed az disk list still refuses (fail-closed). managedBy must be an exact
    case-insensitive match on the full workload VM resource ID.
    """
    disks = _list_named_os_disks(env, inputs, require_present=False)
    subscription_id = str(inputs["subscription_id"])
    for disk in disks:
        managed_by = disk.get("managedBy")
        if not managed_by:
            raise Refused(
                f"Pre-apply OS disk check: {OS_DISK_NAME} exists unattached "
                f"(managedBy empty); refuse recreate until the orphan is resolved"
            )
        if not managed_by_matches_workload_vm(managed_by, subscription_id=subscription_id):
            raise Refused(
                f"Pre-apply OS disk check: {OS_DISK_NAME} managedBy is not the exact "
                f"workload VM id {expected_workload_vm_resource_id(subscription_id)}; "
                "refuse recreate"
            )


def assert_data_disk_preflight(env: dict, inputs: dict) -> None:
    """Pre-apply: az disk show data disk must be Empty/128GiB and unattached or on workload VM."""
    subscription_id = str(inputs["subscription_id"])
    try:
        result = command(
            [
                "az",
                "disk",
                "show",
                "--resource-group",
                RESOURCE_GROUP,
                "--subscription",
                subscription_id,
                "--name",
                DATA_DISK_NAME,
                "--query",
                "{createOption:creationData.createOption,diskSizeGb:diskSizeGb,managedBy:managedBy}",
                "--output",
                "json",
                "--only-show-errors",
            ],
            env=env,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
        raise Refused(
            f"Could not show data disk {DATA_DISK_NAME}; refuse (fail-closed): {exc}"
        ) from exc
    if result.returncode:
        raise Refused(f"Could not show data disk {DATA_DISK_NAME}; refuse (fail-closed)")
    try:
        disk = json.loads(result.stdout or b"")
    except json.JSONDecodeError as exc:
        raise Refused(
            f"Data disk show for {DATA_DISK_NAME} was not valid JSON; refuse (fail-closed)"
        ) from exc
    if not isinstance(disk, dict):
        raise Refused(
            f"Data disk show for {DATA_DISK_NAME} was not a JSON object; refuse (fail-closed)"
        )
    create_option = disk.get("createOption")
    size = disk.get("diskSizeGb")
    managed_by = disk.get("managedBy", False)
    if create_option != "Empty":
        raise Refused(
            f"Pre-apply data disk check: {DATA_DISK_NAME} createOption must be Empty "
            f"(got {create_option!r}); refuse recreate"
        )
    if size != 128:
        raise Refused(
            f"Pre-apply data disk check: {DATA_DISK_NAME} diskSizeGb must be 128 "
            f"(got {size!r}); refuse recreate"
        )
    if managed_by in (None, ""):
        return
    if not managed_by_matches_workload_vm(managed_by, subscription_id=subscription_id):
        raise Refused(
            f"Pre-apply data disk check: {DATA_DISK_NAME} managedBy must be empty or the "
            f"exact workload VM id {expected_workload_vm_resource_id(subscription_id)}; "
            "refuse recreate"
        )


def module_workload_id_reference_addresses(module_dir: Path | None = None) -> set[str]:
    """Scan module *.tf for azurerm_linux_virtual_machine.workload.id resource addresses."""
    root = module_dir if module_dir is not None else MODULE
    reference = re.compile(r"\bazurerm_linux_virtual_machine\.workload\.id\b")
    resource_blocks = re.compile(r'^resource "([^"]+)" "([^"]+)" \{\n(.*?)^\}', re.M | re.S)
    found: set[str] = set()
    for path in sorted(root.glob("*.tf")):
        text = path.read_text()
        for rtype, name, body in resource_blocks.findall(text):
            if not reference.search(body):
                continue
            address = f"{rtype}.{name}"
            for_each = re.search(r"^  for_each\s*=\s*(.+)$", body, re.M)
            count = re.search(r"^  count\s*=\s*(.+)$", body, re.M)
            if for_each:
                expression = for_each.group(1)
                literal_set = re.fullmatch(r'var\.\w+ \? toset\((\[.*\])\) : toset\(\[\]\)', expression)
                local_map = re.fullmatch(r"local\.(\w+)", expression)
                if literal_set:
                    keys = json.loads(literal_set.group(1))
                elif local_map and (mapping := re.search(rf"^  {local_map[1]}\s*=\s*\{{\n(.*?)^  \}}", text, re.M | re.S)):
                    keys = re.findall(r"^    (\w+)\s*=", mapping.group(1), re.M)
                else:
                    raise Refused(f"Cannot enumerate workload.id references for {address}")
                found.update(f"{address}[{json.dumps(key)}]" for key in keys)
            elif count:
                if not re.fullmatch(r"var\.\w+ \? 1 : 0", count.group(1)):
                    raise Refused(f"Cannot enumerate workload.id references for {address}")
                found.add(f"{address}[0]")
            else:
                found.add(address)
    return found


def assert_no_orphaned_os_disk(env: dict, inputs: dict) -> None:
    """Post-recreate / ApplyAttempted: require named OS disk attached to workload VM."""
    disks = _list_named_os_disks(env, inputs, require_present=True)
    subscription_id = str(inputs["subscription_id"])
    orphans = [
        disk
        for disk in disks
        if not managed_by_matches_workload_vm(
            disk.get("managedBy"), subscription_id=subscription_id
        )
    ]
    if orphans:
        raise Refused(
            f"Workload recreate left orphaned or mis-attached OS disk {OS_DISK_NAME}; "
            "stop and investigate before Sitting 2"
        )
    if len(disks) != 1:
        raise Refused(
            f"Workload recreate expected exactly one {OS_DISK_NAME}; found {len(disks)}"
        )


_OS_DISK_CHECK_FAILURES = (
    Refused,
    OSError,
    subprocess.TimeoutExpired,
    subprocess.CalledProcessError,
)


def _apply_attempted_with_os_disk_check(
    message: str,
    *,
    recreate_workload: bool,
    env: dict,
    inputs: dict,
) -> ApplyAttempted:
    """Build ApplyAttempted; on recreate, always attempt the orphan OS-disk check.

    az timeout / OSError / CalledProcessError are treated as apply-attempted
    (fail-closed), never as a clean pre-apply refusal.
    """
    detail = message
    if recreate_workload:
        try:
            assert_no_orphaned_os_disk(env, inputs)
            detail = message + f" OS disk check passed for {OS_DISK_NAME}."
        except _OS_DISK_CHECK_FAILURES as orphan_exc:
            detail = (
                message
                + f" OS disk check refused (fail-closed / apply-attempted): {orphan_exc}"
            )
    return ApplyAttempted(detail)


def plan(folder: Path, *, recover: bool = False, recheck: bool = False, recreate_workload: bool = False) -> dict:
    _assert_single_mode(recover=recover, recheck=recheck, recreate_workload=recreate_workload)
    if recheck:
        return plan_recheck(folder)
    if recover:
        return plan_recover(folder)
    if recreate_workload:
        return plan_recreate_workload(folder)
    manifest, inputs = _verify_prepared(folder)
    if (folder / "tofu-data").exists() or any((folder / "state").iterdir()) or any(
        (folder / "plans").iterdir()
    ) or any((folder / "workspaces").iterdir()):
        raise Refused("Only a fresh initial plan with no state, saved plan or alternate workspace is supported")
    tofu = Path(manifest["tofu"])
    if digest(tofu) != manifest["tofu_sha256"]:
        raise Refused("Pinned OpenTofu executable changed")
    env = execution_environment(folder)
    if owner_context(clean_environment(), inputs) != manifest["context"]:
        raise Refused("Owner CLI context changed since preparation")
    commands = [
        ("init", ["init", "-input=false", "-lockfile=readonly", "-backend-config=" + str(folder / "backend.hcl")]),
        (
            "plan",
            [
                "plan",
                "-input=false",
                "-lock=true",
                "-lock-timeout=30s",
                "-var-file=" + str(folder / "inputs.json"),
                "-out=" + str(folder / "plans/first.tfplan"),
            ],
        ),
    ]
    for name, args in commands:
        result = command([str(tofu), *args], cwd=folder / "module", env=env, timeout=300)
        write_private(folder / "logs" / (name + ".log"), result.stdout + result.stderr)
        if result.returncode:
            raise Refused("Initial " + name + " failed; private logs retained, no apply was attempted")
        if name == "init":
            backend = read_json(folder / "tofu-data/terraform.tfstate").get("backend", {})
            config = backend.get("config", {})
            if (
                backend.get("type") != "local"
                or config.get("path") != str(folder / "state/foundation.tfstate")
                or config.get("workspace_dir") != str(folder / "workspaces")
            ):
                raise Refused("Initialized backend differs from the fixed new local paths")
            workspace_file = folder / "tofu-data/environment"
            if workspace_file.exists() and workspace_file.read_text().strip() != "default":
                raise Refused("Only the new default workspace is supported")
    ciphertext(folder / "plans/first.tfplan")
    plan_sha = digest(folder / "plans/first.tfplan")
    show = command(
        [str(tofu), "show", "-json", str(folder / "plans/first.tfplan")],
        cwd=folder / "module",
        env=env,
        timeout=120,
    )
    if show.returncode:
        raise Refused("Unable to render sanitised plan summary; no apply was attempted")
    summary = sanitize_plan_summary(json.loads(show.stdout), inputs=inputs, plan_sha256=plan_sha)
    write_private(folder / "plan-summary.json", json_bytes(summary))
    result = {
        "planned": True,
        "plan": str(folder / "plans/first.tfplan"),
        "plan_sha256": plan_sha,
        "summary_sha256": summary["summary_sha256"],
        "enable_azure_openai": summary["enable_azure_openai"],
        "source_sha256": manifest["source"]["source_sha256"],
        "state_backend": "local-encrypted",
        "applied": False,
        "first_apply_only": True,
    }
    write_private(folder / "plan-result.json", json_bytes(result))
    return result


def plan_recover(folder: Path) -> dict:
    manifest, inputs = _verify_prepared(folder)
    if not manifest.get("recover"):
        raise Refused("Recovery plan requires prepare --recover on this private directory")
    backups = manifest.get("recover_backups") or {}
    expected_state_sha = backups.get("state_sha256_at_prepare")
    if not isinstance(expected_state_sha, str) or not expected_state_sha:
        raise Refused("Recovery manifest is missing state_sha256_at_prepare backup binding")
    passphrase = folder / "encryption.passphrase"
    state_path = folder / "state/foundation.tfstate"
    if not passphrase.exists():
        raise Refused("Recovery requires the existing encryption.passphrase file")
    if not state_path.exists():
        raise Refused("Recovery requires existing state/foundation.tfstate")
    secure_file(passphrase)
    ciphertext(state_path)
    if digest(state_path) != expected_state_sha:
        raise Refused("Recovery state/foundation.tfstate changed since prepare --recover")
    first_plan = folder / "plans/first.tfplan"
    first_plan_sha = digest(first_plan) if first_plan.is_file() else None
    first_summary = folder / "plan-summary.json"
    first_result = folder / "plan-result.json"
    first_summary_sha = digest(first_summary) if first_summary.is_file() else None
    first_result_sha = digest(first_result) if first_result.is_file() else None
    stamp = utc_plan_stamp()
    plan_path = folder / "plans" / f"recover-{stamp}.tfplan"
    summary_path = folder / f"recover-plan-summary-{stamp}.json"
    result_path = folder / f"recover-plan-result-{stamp}.json"
    if plan_path.name == "first.tfplan" or plan_path.resolve() == (folder / "plans/first.tfplan").resolve():
        raise Refused("Recovery plan must not overwrite plans/first.tfplan")
    if plan_path.exists() or summary_path.exists() or result_path.exists():
        raise Refused("Recovery plan path already exists; refuse overwrite")
    tofu = Path(manifest["tofu"])
    if digest(tofu) != manifest["tofu_sha256"]:
        raise Refused("Pinned OpenTofu executable changed")
    env = execution_environment(folder)
    if owner_context(clean_environment(), inputs, recover=True) != manifest["context"]:
        raise Refused("Owner CLI context changed since preparation")
    commands = [
        (
            "init",
            [
                "init",
                "-input=false",
                "-lockfile=readonly",
                "-reconfigure",
                "-backend-config=" + str(folder / "backend.hcl"),
            ],
        ),
        (
            "plan",
            [
                "plan",
                "-input=false",
                "-lock=true",
                "-lock-timeout=30s",
                "-var-file=" + str(folder / "inputs.json"),
                "-out=" + str(plan_path),
            ],
        ),
    ]
    summary = None
    result = None
    try:
        for name, args in commands:
            cmd_result = command([str(tofu), *args], cwd=folder / "module", env=env, timeout=300)
            write_private(folder / "logs" / f"recover-{name}-{stamp}.log", cmd_result.stdout + cmd_result.stderr)
            if cmd_result.returncode:
                raise Refused("Recovery " + name + " failed; private logs retained, no apply was attempted")
            if name == "init":
                backend = read_json(folder / "tofu-data/terraform.tfstate").get("backend", {})
                config = backend.get("config", {})
                if (
                    backend.get("type") != "local"
                    or config.get("path") != str(folder / "state/foundation.tfstate")
                    or config.get("workspace_dir") != str(folder / "workspaces")
                ):
                    raise Refused("Initialized backend differs from the fixed local paths")
                workspace_file = folder / "tofu-data/environment"
                if workspace_file.exists() and workspace_file.read_text().strip() != "default":
                    raise Refused("Only the default workspace is supported")
        if first_plan_sha is not None and digest(first_plan) != first_plan_sha:
            raise Refused("Recovery plan must not overwrite plans/first.tfplan")
        if digest(state_path) != expected_state_sha:
            raise Refused("Recovery plan modified state/foundation.tfstate")
        ciphertext(plan_path)
        plan_sha = digest(plan_path)
        show = command(
            [str(tofu), "show", "-json", str(plan_path)],
            cwd=folder / "module",
            env=env,
            timeout=120,
        )
        if show.returncode:
            raise Refused("Unable to render sanitised recovery plan summary; no apply was attempted")
        summary = sanitize_recover_plan_summary(
            json.loads(show.stdout), inputs=inputs, plan_sha256=plan_sha
        )
        result = {
            "planned": True,
            "recover": True,
            "stamp": stamp,
            "plan": str(plan_path),
            "summary_path": str(summary_path),
            "result_path": str(result_path),
            "plan_sha256": plan_sha,
            "summary_sha256": summary["summary_sha256"],
            "enable_azure_openai": summary["enable_azure_openai"],
            "source_sha256": manifest["source"]["source_sha256"],
            "state_backend": "local-encrypted",
            "applied": False,
            "first_apply_only": False,
        }
        write_private(summary_path, json_bytes(summary))
        write_private(result_path, json_bytes(result))
    except Exception:
        if plan_path.exists():
            plan_path.unlink()
        if summary_path.exists():
            summary_path.unlink()
        if result_path.exists():
            result_path.unlink()
        raise
    if first_plan_sha is not None and digest(first_plan) != first_plan_sha:
        raise Refused("Recovery plan must not overwrite plans/first.tfplan")
    if first_summary_sha is not None and digest(first_summary) != first_summary_sha:
        raise Refused("Recovery plan must not overwrite first-apply plan-summary.json")
    if first_result_sha is not None and digest(first_result) != first_result_sha:
        raise Refused("Recovery plan must not overwrite first-apply plan-result.json")
    if digest(state_path) != expected_state_sha:
        raise Refused("Recovery plan left state/foundation.tfstate changed after writing recover artifacts")
    assert result is not None
    return result


def plan_recreate_workload(folder: Path) -> dict:
    with _workload_lifecycle_lock(folder):
        assert_no_workload_live_latch(folder)
        return _plan_recreate_workload(folder)


def _plan_recreate_workload(folder: Path) -> dict:
    """Plan exact VM + data-disk recreate with -var=allow_workload_recreate=true.

    Mid-replace recovery: after init, list state and pass -replace only for the
    workload VM / data disk addresses still present. Addresses absent from state
    are expected as create-only in the sanitised change-set. The plan sanitiser
    requires tofu show -json variables.allow_workload_recreate.value is True.
    """
    manifest, inputs = _verify_prepared(folder)
    if not manifest.get("recreate_workload"):
        raise Refused(
            "Workload recreate plan requires prepare --recreate-workload on this private directory"
        )
    backups = manifest.get("recreate_workload_backups") or {}
    expected_state_sha = backups.get("state_sha256_at_prepare")
    if not isinstance(expected_state_sha, str) or not expected_state_sha:
        raise Refused("Workload recreate manifest is missing state_sha256_at_prepare backup binding")
    passphrase = folder / "encryption.passphrase"
    state_path = folder / "state/foundation.tfstate"
    if not passphrase.exists():
        raise Refused("Workload recreate requires the existing encryption.passphrase file")
    if not state_path.exists():
        raise Refused("Workload recreate requires existing state/foundation.tfstate")
    secure_file(passphrase)
    ciphertext(state_path)
    if digest(state_path) != expected_state_sha:
        raise Refused("Workload recreate state/foundation.tfstate changed since prepare --recreate-workload")
    if "allow_workload_recreate" in inputs:
        raise Refused(
            "allow_workload_recreate must not be stored in inputs.json; "
            "recreate plans pass -var=allow_workload_recreate=true only"
        )
    first_plan = folder / "plans/first.tfplan"
    first_plan_sha = digest(first_plan) if first_plan.is_file() else None
    first_summary = folder / "plan-summary.json"
    first_result = folder / "plan-result.json"
    first_summary_sha = digest(first_summary) if first_summary.is_file() else None
    first_result_sha = digest(first_result) if first_result.is_file() else None
    stamp = utc_plan_stamp()
    plan_path = folder / "plans" / f"recreate-workload-{stamp}.tfplan"
    summary_path = folder / f"recreate-workload-plan-summary-{stamp}.json"
    result_path = folder / f"recreate-workload-plan-result-{stamp}.json"
    for path in (plan_path, summary_path, result_path):
        _assert_not_workload_live_path(path)
        if path.is_symlink() or path.exists():
            raise Refused("Workload recreate plan path already exists; refuse overwrite")
    if plan_path.name == "first.tfplan" or plan_path.resolve() == (folder / "plans/first.tfplan").resolve():
        raise Refused("Workload recreate plan must not overwrite plans/first.tfplan")
    tofu = Path(manifest["tofu"])
    if digest(tofu) != manifest["tofu_sha256"]:
        raise Refused("Pinned OpenTofu executable changed")
    env = execution_environment(folder)
    if owner_context(clean_environment(), inputs, recreate_workload=True) != manifest["context"]:
        raise Refused("Owner CLI context changed since preparation")
    # Init first so state list can see encrypted local state; then selective -replace.
    init_commands = [
        (
            "init",
            [
                "init",
                "-input=false",
                "-lockfile=readonly",
                "-reconfigure",
                "-backend-config=" + str(folder / "backend.hcl"),
            ],
        ),
    ]
    summary = None
    result = None
    try:
        for name, args in init_commands:
            cmd_result = command([str(tofu), *args], cwd=folder / "module", env=env, timeout=300)
            write_private(
                folder / "logs" / f"recreate-workload-{name}-{stamp}.log",
                cmd_result.stdout + cmd_result.stderr,
            )
            if cmd_result.returncode:
                raise Refused(
                    "Workload recreate " + name + " failed; private logs retained, no apply was attempted"
                )
            backend = read_json(folder / "tofu-data/terraform.tfstate").get("backend", {})
            config = backend.get("config", {})
            if (
                backend.get("type") != "local"
                or config.get("path") != str(folder / "state/foundation.tfstate")
                or config.get("workspace_dir") != str(folder / "workspaces")
            ):
                raise Refused("Initialized backend differs from the fixed local paths")
            workspace_file = folder / "tofu-data/environment"
            if workspace_file.exists() and workspace_file.read_text().strip() != "default":
                raise Refused("Only the default workspace is supported")
        state_addresses = _state_addresses(tofu=tofu, folder=folder, env=env)
        replace_addresses = _replace_addresses_for_state(state_addresses)
        commands = _recreate_workload_tofu_commands(
            backend_hcl=folder / "backend.hcl",
            inputs=folder / "inputs.json",
            plan_out=plan_path,
            replace_addresses=replace_addresses,
        )
        # Init already ran; only execute the plan command from the builder.
        plan_only = [item for item in commands if item[0] == "plan"]
        if len(plan_only) != 1:
            raise Refused("Workload recreate command builder must yield exactly one plan")
        for name, args in plan_only:
            cmd_result = command([str(tofu), *args], cwd=folder / "module", env=env, timeout=300)
            write_private(
                folder / "logs" / f"recreate-workload-{name}-{stamp}.log",
                cmd_result.stdout + cmd_result.stderr,
            )
            if cmd_result.returncode:
                raise Refused(
                    "Workload recreate " + name + " failed; private logs retained, no apply was attempted"
                )
        if first_plan_sha is not None and digest(first_plan) != first_plan_sha:
            raise Refused("Workload recreate plan must not overwrite plans/first.tfplan")
        if digest(state_path) != expected_state_sha:
            raise Refused("Workload recreate plan modified state/foundation.tfstate")
        ciphertext(plan_path)
        plan_sha = digest(plan_path)
        show = command(
            [str(tofu), "show", "-json", str(plan_path)],
            cwd=folder / "module",
            env=env,
            timeout=120,
        )
        if show.returncode:
            raise Refused(
                "Unable to render sanitised workload recreate plan summary; no apply was attempted"
            )
        summary = sanitize_recreate_workload_plan_summary(
            json.loads(show.stdout),
            inputs=inputs,
            plan_sha256=plan_sha,
        )
        result = {
            "planned": True,
            "recreate_workload": True,
            "stamp": stamp,
            "plan": str(plan_path),
            "summary_path": str(summary_path),
            "result_path": str(result_path),
            "plan_sha256": plan_sha,
            "summary_sha256": summary["summary_sha256"],
            "enable_azure_openai": summary["enable_azure_openai"],
            "allow_workload_recreate": summary["allow_workload_recreate"],
            "replace_addresses": summary["replace_addresses"],
            "create_addresses": summary["create_addresses"],
            "recreate_addresses": summary["recreate_addresses"],
            "update_addresses": summary["update_addresses"],
            "state_replace_addresses": sorted(replace_addresses),
            "source_sha256": manifest["source"]["source_sha256"],
            "state_backend": "local-encrypted",
            "applied": False,
            "first_apply_only": False,
        }
        write_private(summary_path, json_bytes(summary))
        write_private(result_path, json_bytes(result))
    except Exception:
        if plan_path.exists():
            plan_path.unlink()
        if summary_path.exists():
            summary_path.unlink()
        if result_path.exists():
            result_path.unlink()
        raise
    if first_plan_sha is not None and digest(first_plan) != first_plan_sha:
        raise Refused("Workload recreate plan must not overwrite plans/first.tfplan")
    if first_summary_sha is not None and digest(first_summary) != first_summary_sha:
        raise Refused("Workload recreate plan must not overwrite first-apply plan-summary.json")
    if first_result_sha is not None and digest(first_result) != first_result_sha:
        raise Refused("Workload recreate plan must not overwrite first-apply plan-result.json")
    if digest(state_path) != expected_state_sha:
        raise Refused(
            "Workload recreate plan left state/foundation.tfstate changed after writing recreate artifacts"
        )
    assert result is not None
    return result


def plan_recheck(folder: Path) -> dict:
    """Print-only post-apply plan. Never apply. Never write state or first/recover artifacts.

    OpenTofu flags:
    - Default refresh (no ``-refresh=false``): refresh is a read-only Azure
      comparison so out-of-band portal drift is visible in the plan. State-file
      digests before/after the run must still match — proving the encrypted local
      state file was not rewritten.
    - ``-lock=true -lock-timeout=30s``: brief exclusive lock while reading state.
    - ``TF_DATA_DIR`` is a recheck-scoped ``tofu-data-recheck-<UTC>/`` directory so
      ``init -reconfigure`` never mutates the shared ``tofu-data/`` used by
      first-apply / recover.
    """
    # Canonicalize before any recheck-prepare glob/read; never reuse the raw argument.
    folder = private_directory(folder)
    # Exactly one glob+read of recheck-prepare for this plan path; reuse path+record.
    prepare_path, recheck_prepare = _latest_recheck_prepare(folder)
    manifest, inputs, recheck_prepare = _verify_prepared_recheck(
        folder, prepare_path, recheck_prepare
    )
    passphrase = folder / "encryption.passphrase"
    state_path = folder / "state/foundation.tfstate"
    if not passphrase.exists():
        raise Refused("Post-apply re-check requires the existing encryption.passphrase file")
    if not state_path.exists():
        raise Refused("Post-apply re-check requires existing state/foundation.tfstate")
    secure_file(passphrase)
    ciphertext(state_path)
    state_sha = digest(state_path)
    passphrase_sha = digest(passphrase)
    manifest_sha = digest(folder / "manifest.json")
    first_plan = folder / "plans/first.tfplan"
    first_plan_sha = digest(first_plan) if first_plan.is_file() else None
    first_summary = folder / "plan-summary.json"
    first_result = folder / "plan-result.json"
    first_summary_sha = digest(first_summary) if first_summary.is_file() else None
    first_result_sha = digest(first_result) if first_result.is_file() else None
    recover_digests = {
        path: digest(path)
        for path in sorted((folder / "plans").glob("recover-*.tfplan"))
        if path.is_file()
    }
    recover_summary_digests = {
        path: digest(path)
        for path in sorted(folder.glob("recover-plan-summary-*.json"))
        if path.is_file()
    }
    recover_result_digests = {
        path: digest(path)
        for path in sorted(folder.glob("recover-plan-result-*.json"))
        if path.is_file()
    }
    stamp = utc_plan_stamp()
    plan_path = folder / "plans" / f"recheck-{stamp}.tfplan"
    summary_path = folder / f"recheck-plan-summary-{stamp}.json"
    result_path = folder / f"recheck-plan-result-{stamp}.json"
    data_dir = folder / f"tofu-data-recheck-{stamp}"
    if plan_path.exists() or summary_path.exists() or result_path.exists() or data_dir.exists():
        raise Refused("Post-apply re-check plan path already exists; refuse overwrite")
    tofu = Path(manifest["tofu"])
    if digest(tofu) != manifest["tofu_sha256"]:
        raise Refused("Pinned OpenTofu executable changed")
    if digest(tofu) != recheck_prepare.get("tofu_sha256"):
        raise Refused("Pinned OpenTofu executable changed since prepare --recheck")
    data_dir.mkdir(mode=0o700)
    shared_tofu_data = folder / "tofu-data"
    shared_tofu_before = None
    if shared_tofu_data.exists():
        shared_tofu_before = {
            path.relative_to(shared_tofu_data).as_posix(): digest(path)
            for path in shared_tofu_data.rglob("*")
            if path.is_file()
        }
    env = execution_environment(folder, data_dir=data_dir)
    if owner_context(clean_environment(), inputs, recheck=True) != manifest["context"]:
        raise Refused("Owner CLI context changed since preparation")
    commands = _recheck_tofu_commands(
        backend_hcl=folder / "backend.hcl",
        inputs=folder / "inputs.json",
        plan_out=plan_path,
    )
    summary = None
    result = None
    try:
        for name, args in commands:
            cmd_result = command([str(tofu), *args], cwd=folder / "module", env=env, timeout=300)
            write_private(
                folder / "logs" / f"recheck-{name}-{stamp}.log",
                cmd_result.stdout + cmd_result.stderr,
            )
            if cmd_result.returncode:
                raise Refused(
                    "Post-apply re-check " + name + " failed; private logs retained, no apply was attempted"
                )
            if name == "init":
                backend = read_json(data_dir / "terraform.tfstate").get("backend", {})
                config = backend.get("config", {})
                if (
                    backend.get("type") != "local"
                    or config.get("path") != str(folder / "state/foundation.tfstate")
                    or config.get("workspace_dir") != str(folder / "workspaces")
                ):
                    raise Refused("Initialized backend differs from the fixed local paths")
                workspace_file = data_dir / "environment"
                if workspace_file.exists() and workspace_file.read_text().strip() != "default":
                    raise Refused("Only the default workspace is supported")
            if digest(state_path) != state_sha:
                raise Refused("Post-apply re-check must not modify state/foundation.tfstate")
        if first_plan_sha is not None and digest(first_plan) != first_plan_sha:
            raise Refused("Post-apply re-check must not overwrite plans/first.tfplan")
        if digest(folder / "manifest.json") != manifest_sha:
            raise Refused("Post-apply re-check must not modify manifest.json")
        if digest(passphrase) != passphrase_sha:
            raise Refused("Post-apply re-check must not modify encryption.passphrase")
        for path, expected in recover_digests.items():
            if digest(path) != expected:
                raise Refused("Post-apply re-check must not overwrite recover plan artifacts")
        for path, expected in recover_summary_digests.items():
            if digest(path) != expected:
                raise Refused("Post-apply re-check must not overwrite recover summary artifacts")
        for path, expected in recover_result_digests.items():
            if digest(path) != expected:
                raise Refused("Post-apply re-check must not overwrite recover result artifacts")
        if shared_tofu_before is not None:
            shared_tofu_after = {
                path.relative_to(shared_tofu_data).as_posix(): digest(path)
                for path in shared_tofu_data.rglob("*")
                if path.is_file()
            }
            if shared_tofu_after != shared_tofu_before:
                raise Refused("Post-apply re-check must not modify shared tofu-data/")
        ciphertext(plan_path)
        plan_sha = digest(plan_path)
        show = command(
            [str(tofu), "show", "-json", str(plan_path)],
            cwd=folder / "module",
            env=env,
            timeout=120,
        )
        if show.returncode:
            raise Refused("Unable to render sanitised re-check plan summary; no apply was attempted")
        summary = sanitize_recheck_plan_summary(
            json.loads(show.stdout), inputs=inputs, plan_sha256=plan_sha
        )
        result = {
            "planned": True,
            "recheck": True,
            "stamp": stamp,
            "plan": str(plan_path),
            "summary_path": str(summary_path),
            "result_path": str(result_path),
            "prepare_path": str(prepare_path),
            "plan_sha256": plan_sha,
            "summary_sha256": summary["summary_sha256"],
            "enable_azure_openai": summary["enable_azure_openai"],
            "source_sha256": recheck_prepare["source_sha256"],
            "state_backend": "local-encrypted",
            "applied": False,
            "first_apply_only": False,
            "create": 0,
            "update": 0,
            "replace": 0,
            "delete": 0,
            "data_dir": str(data_dir),
        }
        write_private(summary_path, json_bytes(summary))
        write_private(result_path, json_bytes(result))
    except Exception:
        if plan_path.exists():
            plan_path.unlink()
        if summary_path.exists():
            summary_path.unlink()
        if result_path.exists():
            result_path.unlink()
        raise
    if first_plan_sha is not None and digest(first_plan) != first_plan_sha:
        raise Refused(
            "Post-apply re-check left plans/first.tfplan changed after writing recheck artifacts"
        )
    if first_summary_sha is not None and digest(first_summary) != first_summary_sha:
        raise Refused("Post-apply re-check must not overwrite first-apply plan-summary.json")
    if first_result_sha is not None and digest(first_result) != first_result_sha:
        raise Refused("Post-apply re-check must not overwrite first-apply plan-result.json")
    if digest(state_path) != state_sha:
        raise Refused("Post-apply re-check left state/foundation.tfstate changed after writing recheck artifacts")
    if digest(folder / "manifest.json") != manifest_sha:
        raise Refused("Post-apply re-check left manifest.json changed after writing recheck artifacts")
    assert result is not None
    return result


def read_approval(path: Path, *, plan_sha256: str, summary_sha256: str) -> dict:
    if not path.is_absolute() or path.resolve() != path or path.is_relative_to(REPO):
        raise Refused("Approval file must be an absolute path outside the repository")
    secure_file(path)
    approval = read_json(path)
    required = {"reviewer", "review_reference", "plan_sha256", "summary_sha256"}
    if set(approval) != required or not all(isinstance(approval[key], str) and approval[key] for key in required):
        raise Refused("Approval file must contain reviewer, review_reference, plan_sha256, summary_sha256 only")
    if approval["plan_sha256"] != plan_sha256:
        raise Refused("Approval plan_sha256 does not match the reviewed plan file")
    if approval["summary_sha256"] != summary_sha256:
        raise Refused("Approval summary_sha256 does not match the sanitised plan summary")
    return approval


def _operator_print(message: str) -> None:
    try:
        print(message, file=sys.stderr)
    except OSError:
        pass


def _tofu_runtime_status(
    proc: subprocess.Popen, log_path: Path, *, interrupt_sent: bool
) -> str:
    alive = proc.poll() is None
    pid = getattr(proc, "pid", "?")
    if alive:
        if interrupt_sent:
            detail = (
                "it received one graceful interrupt and no further signal; "
                "do not retry, move or edit the private directory until it exits; follow the log path"
            )
        else:
            detail = (
                "no signal was sent; do not retry, move or edit the private directory until it exits; "
                "follow the log path"
            )
        return f"tofu pid {pid} is STILL RUNNING; {detail}. log={log_path}"
    code = getattr(proc, "returncode", proc.poll())
    return f"tofu pid {pid} is not running (exit={code}). log={log_path}"


def _latest_recover_result(folder: Path) -> Path:
    matches = sorted(
        path
        for path in folder.glob("recover-plan-result-*.json")
        if path.is_file() and RECOVER_RESULT_NAME.match(path.name)
    )
    if not matches:
        raise Refused(
            "Reviewed recover-plan-result-<UTC>.json is required before recovery apply"
        )
    return matches[-1]


def _latest_recreate_result(folder: Path) -> Path:
    matches = sorted(
        path
        for path in folder.glob("recreate-workload-plan-result-*.json")
        if path.is_file() and RECREATE_RESULT_NAME.match(path.name)
    )
    if not matches:
        raise Refused(
            "Reviewed recreate-workload-plan-result-<UTC>.json is required before recreate apply"
        )
    return matches[-1]


def _resolve_mode_apply_artifacts(
    folder: Path,
    *,
    mode: str,
    result_glob: str,
    result_name_re: re.Pattern[str],
    summary_name_re: re.Pattern[str],
    plan_name_re: re.Pattern[str],
    latest_result,
    marker: str,
) -> tuple[Path, Path, Path, dict, dict]:
    result_path = latest_result(folder)
    secure_file(result_path)
    plan_result = read_json(result_path)
    summary_value = plan_result.get("summary_path")
    if isinstance(summary_value, str) and summary_value:
        summary_path = Path(summary_value)
    else:
        stamp = plan_result.get("stamp")
        if not isinstance(stamp, str) or not stamp:
            raise Refused(f"{mode}-plan-result is missing stamp/summary_path")
        summary_path = folder / f"{mode}-plan-summary-{stamp}.json"
    if not summary_path.is_absolute():
        raise Refused(f"{mode} summary path must be absolute")
    if summary_path.parent.resolve() != folder.resolve():
        raise Refused(f"{mode} summary must live in the private directory root")
    if not summary_name_re.match(summary_path.name):
        raise Refused(f"{mode} summary name must be {mode}-plan-summary-<UTC>.json")
    if not summary_path.is_file():
        raise Refused(f"Reviewed {mode}-plan-summary-<UTC>.json is required before {mode} apply")
    secure_file(summary_path)
    summary = read_json(summary_path)
    plan_value = plan_result.get("plan")
    if not isinstance(plan_value, str) or not plan_value:
        raise Refused(f"{mode}-plan-result is missing the {mode} plan path")
    plan_path = Path(plan_value)
    if not plan_path.is_absolute():
        raise Refused(f"{mode} plan path must be absolute")
    plans_dir = (folder / "plans").resolve()
    resolved_plan = plan_path.resolve()
    if resolved_plan.parent != plans_dir:
        raise Refused(f"{mode} plan must live under the private plans/ directory")
    if resolved_plan.name == "first.tfplan" or not plan_name_re.match(resolved_plan.name):
        raise Refused(
            f"{mode} apply refuses plans/first.tfplan; use plans/{mode}-<UTC>.tfplan"
        )
    if plan_result.get("recheck") or summary.get("recheck"):
        raise Refused(f"{mode} apply refuses recheck plans; post-apply re-check is print-only")
    if mode != "recreate-workload" and (
        plan_result.get("recreate_workload") or summary.get("recreate_workload")
    ):
        raise Refused(f"{mode} apply refuses recreate-workload plan artifacts")
    if not resolved_plan.is_file():
        raise Refused(f"Reviewed {mode} plan file is required before apply")
    if not plan_result.get(marker) or not summary.get(marker):
        raise Refused(f"{mode} apply requires {marker}-marked plan artifacts")
    return resolved_plan, result_path, summary_path, plan_result, summary


def _resolve_apply_artifacts(
    folder: Path, *, recover: bool = False, recreate_workload: bool = False
) -> tuple[Path, Path, Path, dict, dict]:
    _assert_single_mode(recover=recover, recreate_workload=recreate_workload)
    if recover:
        return _resolve_mode_apply_artifacts(
            folder,
            mode="recover",
            result_glob="recover-plan-result-*.json",
            result_name_re=RECOVER_RESULT_NAME,
            summary_name_re=RECOVER_SUMMARY_NAME,
            plan_name_re=RECOVER_PLAN_NAME,
            latest_result=_latest_recover_result,
            marker="recover",
        )
    if recreate_workload:
        return _resolve_mode_apply_artifacts(
            folder,
            mode="recreate-workload",
            result_glob="recreate-workload-plan-result-*.json",
            result_name_re=RECREATE_RESULT_NAME,
            summary_name_re=RECREATE_SUMMARY_NAME,
            plan_name_re=RECREATE_PLAN_NAME,
            latest_result=_latest_recreate_result,
            marker="recreate_workload",
        )
    plan_path = folder / "plans/first.tfplan"
    result_path = folder / "plan-result.json"
    summary_path = folder / "plan-summary.json"
    if not plan_path.is_file() or not result_path.is_file() or not summary_path.is_file():
        raise Refused("Reviewed plan, plan-result.json, and plan-summary.json are required before apply")
    secure_file(plan_path)
    secure_file(result_path)
    secure_file(summary_path)
    plan_result = read_json(result_path)
    summary = read_json(summary_path)
    if plan_result.get("recheck") or summary.get("recheck"):
        raise Refused("Apply refuses recheck plan artifacts; post-apply re-check is print-only")
    if plan_result.get("recreate_workload") or summary.get("recreate_workload"):
        raise Refused("First-apply path refuses recreate-workload plan artifacts; pass --recreate-workload")
    return plan_path, result_path, summary_path, plan_result, summary


def apply(
    folder: Path,
    *,
    confirm_apply: bool,
    approval_path: Path,
    recover: bool = False,
    recreate_workload: bool = False,
) -> dict:
    logs = folder / "logs"
    if logs.is_dir() and any(logs.glob("apply-*.log")):
        _operator_print(
            "An earlier apply may have been partial; existing apply-*.log files found under logs/."
        )
    if not confirm_apply:
        raise Refused("refusing apply without --confirm-apply")
    _assert_single_mode(recover=recover, recreate_workload=recreate_workload)
    with (_workload_lifecycle_lock(folder) if recreate_workload else nullcontext()) as lifecycle_fd:
        if recreate_workload:
            assert_no_workload_live_latch(folder)
        return _apply(folder, approval_path, recover=recover, lifecycle_fd=lifecycle_fd)


def _apply(folder: Path, approval_path: Path, *, recover: bool, lifecycle_fd: int | None) -> dict:
    recreate_workload = lifecycle_fd is not None
    logs = folder / "logs"
    os.umask(0o077)
    manifest, inputs = _verify_prepared(folder)
    if manifest.get("resource_group") != RESOURCE_GROUP:
        raise Refused(f"manifest resource_group is not production: {manifest.get('resource_group')}")
    if manifest.get("profile") != NAMESPACE:
        raise Refused(f"manifest profile is not production namespace: {manifest.get('profile')}")
    if recover and not manifest.get("recover"):
        raise Refused("Recovery apply requires prepare --recover on this private directory")
    if not recover and manifest.get("recover"):
        raise Refused("Private directory was prepared for recovery; pass --recover to apply")
    if recreate_workload and not manifest.get("recreate_workload"):
        raise Refused(
            "Workload recreate apply requires prepare --recreate-workload on this private directory"
        )
    if not recreate_workload and manifest.get("recreate_workload"):
        raise Refused(
            "Private directory was prepared for workload recreate; pass --recreate-workload to apply"
        )
    plan_path, result_path, summary_path, plan_result, summary = _resolve_apply_artifacts(
        folder, recover=recover, recreate_workload=recreate_workload
    )
    secure_file(plan_path)
    plan_sha = digest(plan_path)
    if recover or recreate_workload:
        mismatch_label = result_path.name
        summary_label = summary_path.name
    else:
        mismatch_label = "plan-result.json"
        summary_label = "plan-summary.json"
    expected_plan_name = plan_path.name
    if recover or recreate_workload:
        if plan_result.get("plan_sha256") != plan_sha:
            raise Refused(f"{mismatch_label} plan_sha256 does not match {expected_plan_name}")
        if summary.get("plan_sha256") != plan_sha or summary.get("summary_sha256") != plan_result.get(
            "summary_sha256"
        ):
            raise Refused(f"{summary_label} does not match the reviewed {('recover' if recover else 'recreate')} plan result")
    else:
        if plan_result.get("plan_sha256") != plan_sha:
            raise Refused("plan-result.json plan_sha256 does not match plans/first.tfplan")
        if summary.get("plan_sha256") != plan_sha or summary.get("summary_sha256") != plan_result.get(
            "summary_sha256"
        ):
            raise Refused("plan-summary.json does not match the reviewed plan result")
    read_approval(approval_path, plan_sha256=plan_sha, summary_sha256=summary["summary_sha256"])
    tofu = Path(manifest["tofu"])
    if digest(tofu) != manifest["tofu_sha256"]:
        raise Refused("Pinned OpenTofu executable changed")
    if recover:
        backups = manifest.get("recover_backups") or {}
        backup_value = backups.get("state_pre_recover")
        backup_sha = backups.get("state_pre_recover_sha256")
        if not isinstance(backup_value, str) or not backup_value:
            raise Refused("Recovery apply requires state_pre_recover backup path")
        if not isinstance(backup_sha, str) or not backup_sha:
            raise Refused("Recovery apply requires state_pre_recover_sha256")
        backup_path = Path(backup_value)
        if not backup_path.is_file():
            raise Refused("Recovery pre-recover state backup is missing")
        secure_file(backup_path)
        if digest(backup_path) != backup_sha:
            raise Refused("Recovery pre-recover state backup sha256 mismatch")
    if recreate_workload:
        backups = manifest.get("recreate_workload_backups") or {}
        backup_value = backups.get("state_pre_recreate")
        backup_sha = backups.get("state_pre_recreate_sha256")
        if not isinstance(backup_value, str) or not backup_value:
            raise Refused("Workload recreate apply requires state_pre_recreate backup path")
        if not isinstance(backup_sha, str) or not backup_sha:
            raise Refused("Workload recreate apply requires state_pre_recreate_sha256")
        backup_path = Path(backup_value)
        if not backup_path.is_file():
            raise Refused("Workload recreate pre-recreate state backup is missing")
        secure_file(backup_path)
        if digest(backup_path) != backup_sha:
            raise Refused("Workload recreate pre-recreate state backup sha256 mismatch")
    version = command([str(tofu), "version", "-json"], env=clean_environment())
    if version.returncode or json.loads(version.stdout).get("terraform_version") != TOFU_VERSION:
        raise Refused("OpenTofu must be the pinned version 1.12.5")
    env = execution_environment(folder)
    if (
        owner_context(
            clean_environment(),
            inputs,
            recover=recover,
            recreate_workload=recreate_workload,
        )
        != manifest["context"]
    ):
        raise Refused("Owner CLI context changed since preparation")
    # Recompute the sanitised summary from the hashed plan before apply.
    show = command(
        [str(tofu), "show", "-json", str(plan_path)],
        cwd=folder / "module",
        env=env,
        timeout=120,
    )
    if show.returncode:
        raise Refused("Cannot re-show the reviewed plan before apply")
    if recreate_workload:
        recomputed = sanitize_recreate_workload_plan_summary(
            json.loads(show.stdout),
            inputs=inputs,
            plan_sha256=plan_sha,
        )
    elif recover:
        recomputed = sanitize_recover_plan_summary(
            json.loads(show.stdout),
            inputs=inputs,
            plan_sha256=plan_sha,
        )
    else:
        recomputed = sanitize_plan_summary(
            json.loads(show.stdout),
            inputs=inputs,
            plan_sha256=plan_sha,
        )
    if recomputed != summary:
        raise Refused(f"Recomputed plan summary does not match {summary_label}")
    if recomputed["summary_sha256"] != plan_result.get("summary_sha256"):
        raise Refused(f"Recomputed plan summary does not match {mismatch_label}")
    if recomputed["summary_sha256"] != read_json(approval_path)["summary_sha256"]:
        raise Refused("Recomputed plan summary does not match approval summary_sha256")
    if recreate_workload:
        # Pre-apply fences: must run before tofu apply starts.
        assert_os_disk_preflight(env, inputs)
        assert_data_disk_preflight(env, inputs)
    logs.mkdir(mode=0o700, exist_ok=True)
    if recreate_workload:
        log_prefix = "recreate-workload-apply"
    elif recover:
        log_prefix = "recover-apply"
    else:
        log_prefix = "apply"
    log_path = logs / f"{log_prefix}-{secrets.token_hex(8)}.log"
    _assert_not_workload_live_path(log_path)
    _operator_print(f"Apply log path: {log_path}")
    argv = [
        str(tofu),
        "apply",
        "-input=false",
        "-lock=true",
        "-lock-timeout=30s",
        str(plan_path),
    ]
    apply_started = False
    returncode = None
    proc: subprocess.Popen | None = None
    previous_handlers: dict[int, object] = {}
    interrupt_sent = False
    handlers_installed = False

    def _route_to_keyboard_interrupt(signum, frame):  # noqa: ARG001
        raise KeyboardInterrupt()

    def _restore_handlers() -> None:
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)  # type: ignore[arg-type]

    def _attempted(message: str) -> ApplyAttempted:
        return _apply_attempted_with_os_disk_check(
            message,
            recreate_workload=recreate_workload,
            env=env,
            inputs=inputs,
        )

    # Keep the lock in the recreate child so admission still refuses if this
    # process dies while OpenTofu is running.
    child_options = {"pass_fds": (lifecycle_fd,)} if recreate_workload else {}
    try:
        with (_open_private_exclusive(log_path) if recreate_workload else open(log_path, "wb")) as log_stream:
            if recreate_workload:
                assert_no_workload_live_latch(folder)
            for sig in (signal.SIGTERM, signal.SIGHUP):
                previous_handlers[sig] = signal.signal(sig, _route_to_keyboard_interrupt)
            handlers_installed = True
            apply_started = True
            try:
                try:
                    proc = subprocess.Popen(
                        argv,
                        cwd=folder / "module",
                        env=env,
                        stdin=subprocess.DEVNULL,
                        stdout=log_stream,
                        stderr=subprocess.STDOUT,
                        umask=0o077,
                        start_new_session=True,
                        **child_options,
                    )
                except OSError:
                    apply_started = False
                    raise
                try:
                    returncode = proc.wait(timeout=None)
                except KeyboardInterrupt as first:
                    proc.send_signal(signal.SIGINT)
                    interrupt_sent = True
                    _operator_print(
                        f"graceful stop requested, do not press Ctrl-C again; log={log_path}"
                    )
                    try:
                        returncode = proc.wait(timeout=None)
                    except KeyboardInterrupt as second:
                        status = _tofu_runtime_status(
                            proc, log_path, interrupt_sent=True
                        )
                        _operator_print(status)
                        raise _attempted(
                            "Apply interrupted after start; OpenTofu must be left to finish. "
                            f"{APPLY_RECOVERY} {status}"
                        ) from second
                    raise _attempted(
                        "Apply interrupted after start; "
                        f"{APPLY_RECOVERY} "
                        f"{_tofu_runtime_status(proc, log_path, interrupt_sent=True)}"
                    ) from first
            finally:
                if handlers_installed:
                    _restore_handlers()
                    handlers_installed = False
    except ApplyAttempted:
        raise
    except BaseException as exc:
        if handlers_installed:
            _restore_handlers()
            handlers_installed = False
        if apply_started:
            if proc is None:
                raise _attempted(
                    "Apply was attempted and did not complete cleanly; tofu may have started; "
                    f"private logs retained. {APPLY_RECOVERY} log={log_path}"
                ) from exc
            status = _tofu_runtime_status(proc, log_path, interrupt_sent=interrupt_sent)
            raise _attempted(
                "Apply was attempted and did not complete cleanly; private logs retained. "
                f"{APPLY_RECOVERY} {status}"
            ) from exc
        raise
    if returncode:
        status = (
            _tofu_runtime_status(proc, log_path, interrupt_sent=interrupt_sent)
            if proc is not None
            else f"log={log_path}"
        )
        raise _attempted(
            "Apply was attempted and failed; private logs retained. "
            f"{APPLY_RECOVERY} {status}"
        )
    outcome = {
        "applied": True,
        "plan_sha256": plan_sha,
        "resource_group": RESOURCE_GROUP,
        "first_apply_only": not recover and not recreate_workload,
    }
    if recover:
        outcome["recover"] = True
    if recreate_workload:
        outcome["recreate_workload"] = True
        try:
            assert_no_orphaned_os_disk(env, inputs)
        except _OS_DISK_CHECK_FAILURES as orphan_exc:
            # tofu already exited 0; never tell the operator "No apply was attempted".
            raise ApplyAttempted(
                "Apply completed but OS disk check refused "
                f"(fail-closed / apply-attempted): {orphan_exc}"
            ) from orphan_exc
        outcome["orphaned_os_disk_check"] = "passed"
        outcome["os_disk_name"] = OS_DISK_NAME
    return outcome


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("fingerprint")
    first = commands.add_parser("prepare")
    for name in ("private-dir", "inputs", "tofu", "provider-mirror"):
        first.add_argument("--" + name, type=Path, required=True)
    first.add_argument("--source-sha256", required=True)
    first.add_argument("--lock-sha256", required=True)
    first.add_argument("--recover", action="store_true")
    first.add_argument("--recheck", action="store_true")
    first.add_argument("--recreate-workload", action="store_true")
    later = commands.add_parser("plan")
    later.add_argument("--private-dir", type=Path, required=True)
    later.add_argument("--recover", action="store_true")
    later.add_argument("--recheck", action="store_true")
    later.add_argument("--recreate-workload", action="store_true")
    apply_cmd = commands.add_parser("apply")
    apply_cmd.add_argument("--private-dir", type=Path, required=True)
    apply_cmd.add_argument("--confirm-apply", action="store_true")
    apply_cmd.add_argument("--approval", type=Path, required=True)
    apply_cmd.add_argument("--recover", action="store_true")
    apply_cmd.add_argument("--recreate-workload", action="store_true")
    admit_cmd = commands.add_parser(
        "admit-first-package", help="Record go-live before admitting the first production package"
    )
    admit_cmd.add_argument("--private-dir", type=Path, required=True)
    refresh_cmd = commands.add_parser(
        "refresh-module-snapshot",
        help=(
            "Explicitly refresh private module/*.tf to the reviewed foundation "
            "(clean origin/main only; sanctioned *.tf diffs; binds new digests)"
        ),
    )
    refresh_cmd.add_argument("--private-dir", type=Path, required=True)
    refresh_cmd.add_argument("--source-sha256", required=True)
    refresh_cmd.add_argument("--lock-sha256", required=True)
    refresh_cmd.add_argument("--confirm-refresh", action="store_true")
    # Intentionally no --recheck on apply: re-check is print-only and must never apply.
    args = parser.parse_args()
    os.umask(0o077)
    result = None
    try:
        if args.command == "fingerprint":
            result = fingerprint()
        elif args.command == "prepare":
            _assert_single_mode(
                recover=args.recover,
                recheck=args.recheck,
                recreate_workload=args.recreate_workload,
            )
            result = prepare(
                args.private_dir,
                args.inputs,
                args.source_sha256,
                args.lock_sha256,
                args.tofu,
                args.provider_mirror,
                recover=args.recover,
                recheck=args.recheck,
                recreate_workload=args.recreate_workload,
            )
        elif args.command == "plan":
            _assert_single_mode(
                recover=args.recover,
                recheck=args.recheck,
                recreate_workload=args.recreate_workload,
            )
            result = plan(
                args.private_dir,
                recover=args.recover,
                recheck=args.recheck,
                recreate_workload=args.recreate_workload,
            )
        elif args.command == "refresh-module-snapshot":
            result = refresh_module_snapshot(
                args.private_dir,
                args.source_sha256,
                args.lock_sha256,
                confirm_refresh=args.confirm_refresh,
            )
        elif args.command == "admit-first-package":
            result = admit_first_package(args.private_dir)
        else:
            result = apply(
                args.private_dir,
                confirm_apply=args.confirm_apply,
                approval_path=args.approval,
                recover=args.recover,
                recreate_workload=args.recreate_workload,
            )
        try:
            print(json.dumps(result, sort_keys=True))
        except Exception:
            if isinstance(result, dict) and result.get("applied"):
                _operator_print(
                    "Encrypted local bootstrap: apply was attempted and did not complete cleanly. "
                    f"tofu exited 0 and only the result print failed. {APPLY_RECOVERY}"
                )
                raise SystemExit(2) from None
            raise
    except ApplyAttempted as exc:
        _operator_print(
            f"Encrypted local bootstrap: apply was attempted and did not complete cleanly. {exc}"
        )
        raise SystemExit(2) from None
    except RecheckDriftRefused as exc:
        # Address-only message — never point operators at raw plan logs (they
        # contain attribute values).
        _operator_print(str(exc))
        raise SystemExit(1) from None
    except (Refused, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        _operator_print(
            "Encrypted local bootstrap refused; inspect reviewed inputs or private logs. No apply was attempted."
        )
        raise SystemExit(1) from None



if __name__ == "__main__":
    main()
