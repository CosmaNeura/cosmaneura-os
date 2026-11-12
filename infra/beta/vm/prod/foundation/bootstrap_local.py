"""Prepare, plan, and apply a fresh encrypted local CosmaBot production foundation.

First-apply-only tooling. OpenAI opt-in must be in the first apply's inputs or
wait for a separately reviewed day-2 tool. Do not run raw tofu by hand.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import signal
import stat
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from name_guards import NameGuardError, assert_production_inputs  # noqa: E402

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
    "and open a separately reviewed recovery ticket before retry."
)
EXTRA_FINGERPRINT = (
    PROD / "name_guards.py",
    REPO / "infra/beta/review-cosmabot-prod-foundation.sh",
    REPO / "infra/beta/apply-cosmabot-prod-foundation.sh",
)


class Refused(RuntimeError):
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


def owner_context(env: dict, inputs: dict) -> dict:
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
    if exists.returncode or json.loads(exists.stdout) is not False:
        raise Refused("The exact new workload resource group must still be absent for the fresh initial plan")
    return {
        "subscription_id": account["id"].lower(),
        "tenant_id": account["tenantId"].lower(),
        "user_type": "user",
        "user_name_sha256": hashlib.sha256(user["name"].encode()).hexdigest(),
    }


def execution_environment(folder: Path) -> dict[str, str]:
    env = clean_environment()
    env.update(
        {
            "TF_DATA_DIR": str(folder / "tofu-data"),
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


def prepare(folder: Path, inputs_path: Path, expected_source: str, expected_lock: str, tofu: Path, mirror: Path) -> dict:
    env = clean_environment()
    actual = fingerprint()
    if actual["source_sha256"] != expected_source or actual["lock_sha256"] != expected_lock:
        raise Refused("Foundation source/lock differs from the reviewed hashes")
    inputs = normalize_inputs(read_json(inputs_path))
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
        secure_file(folder / name)
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


def sanitize_plan_summary(plan_json: dict, *, inputs: dict, plan_sha256: str) -> dict:
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


def plan(folder: Path) -> dict:
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


def apply(folder: Path, *, confirm_apply: bool, approval_path: Path) -> dict:
    logs = folder / "logs"
    if logs.is_dir() and any(logs.glob("apply-*.log")):
        _operator_print(
            "An earlier apply may have been partial; existing apply-*.log files found under logs/."
        )
    if not confirm_apply:
        raise Refused("refusing apply without --confirm-apply")
    os.umask(0o077)
    manifest, inputs = _verify_prepared(folder)
    if manifest.get("resource_group") != RESOURCE_GROUP:
        raise Refused(f"manifest resource_group is not production: {manifest.get('resource_group')}")
    if manifest.get("profile") != NAMESPACE:
        raise Refused(f"manifest profile is not production namespace: {manifest.get('profile')}")
    plan_path = folder / "plans/first.tfplan"
    result_path = folder / "plan-result.json"
    summary_path = folder / "plan-summary.json"
    if not plan_path.is_file() or not result_path.is_file() or not summary_path.is_file():
        raise Refused("Reviewed plan, plan-result.json, and plan-summary.json are required before apply")
    secure_file(plan_path)
    secure_file(result_path)
    secure_file(summary_path)
    plan_sha = digest(plan_path)
    plan_result = read_json(result_path)
    summary = read_json(summary_path)
    if plan_result.get("plan_sha256") != plan_sha:
        raise Refused("plan-result.json plan_sha256 does not match plans/first.tfplan")
    if summary.get("plan_sha256") != plan_sha or summary.get("summary_sha256") != plan_result.get("summary_sha256"):
        raise Refused("plan-summary.json does not match the reviewed plan result")
    read_approval(approval_path, plan_sha256=plan_sha, summary_sha256=summary["summary_sha256"])
    tofu = Path(manifest["tofu"])
    if digest(tofu) != manifest["tofu_sha256"]:
        raise Refused("Pinned OpenTofu executable changed")
    version = command([str(tofu), "version", "-json"], env=clean_environment())
    if version.returncode or json.loads(version.stdout).get("terraform_version") != TOFU_VERSION:
        raise Refused("OpenTofu must be the pinned version 1.12.5")
    env = execution_environment(folder)
    if owner_context(clean_environment(), inputs) != manifest["context"]:
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
    recomputed = sanitize_plan_summary(
        json.loads(show.stdout),
        inputs=inputs,
        plan_sha256=plan_sha,
    )
    if recomputed != summary:
        raise Refused("Recomputed plan summary does not match plan-summary.json")
    if recomputed["summary_sha256"] != plan_result.get("summary_sha256"):
        raise Refused("Recomputed plan summary does not match plan-result.json")
    if recomputed["summary_sha256"] != read_json(approval_path)["summary_sha256"]:
        raise Refused("Recomputed plan summary does not match approval summary_sha256")
    logs.mkdir(mode=0o700, exist_ok=True)
    log_path = logs / f"apply-{secrets.token_hex(8)}.log"
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

    try:
        with open(log_path, "wb") as log_stream:
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
                        raise ApplyAttempted(
                            "Apply interrupted after start; OpenTofu must be left to finish. "
                            f"{APPLY_RECOVERY} {status}"
                        ) from second
                    raise ApplyAttempted(
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
                raise ApplyAttempted(
                    "Apply was attempted and did not complete cleanly; tofu may have started; "
                    f"private logs retained. {APPLY_RECOVERY} log={log_path}"
                ) from exc
            status = _tofu_runtime_status(proc, log_path, interrupt_sent=interrupt_sent)
            raise ApplyAttempted(
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
        raise ApplyAttempted(
            "Apply was attempted and failed; private logs retained. "
            f"{APPLY_RECOVERY} {status}"
        )
    return {"applied": True, "plan_sha256": plan_sha, "resource_group": RESOURCE_GROUP, "first_apply_only": True}


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
    apply_cmd = commands.add_parser("apply")
    apply_cmd.add_argument("--private-dir", type=Path, required=True)
    apply_cmd.add_argument("--confirm-apply", action="store_true")
    apply_cmd.add_argument("--approval", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    result = None
    try:
        if args.command == "fingerprint":
            result = fingerprint()
        elif args.command == "prepare":
            result = prepare(
                args.private_dir,
                args.inputs,
                args.source_sha256,
                args.lock_sha256,
                args.tofu,
                args.provider_mirror,
            )
        elif args.command == "plan":
            result = plan(args.private_dir)
        else:
            result = apply(args.private_dir, confirm_apply=args.confirm_apply, approval_path=args.approval)
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
    except (Refused, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        _operator_print(
            "Encrypted local bootstrap refused; inspect reviewed inputs or private logs. No apply was attempted."
        )
        raise SystemExit(1) from None



if __name__ == "__main__":
    main()
