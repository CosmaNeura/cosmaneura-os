#!/usr/bin/env python3
"""Transport Key Vault secret NAMES onto prod host files as mode-0400.

Access model (does not widen the VM runtime managed identity):

* Key Vault reads use the existing off-VM release operator principal
  (Key Vault Secrets Officer on kv-cbot-prd-*). That assignment already
  exists in prod foundation IaC. This tooling never assigns vault roles
  to the runtime UAMI.
* Workstation stage-only mode runs inside John's temporary /32 vault
  public-access window (see runbook §4.1 / §4.3). It fetches into a
  mode-700 private directory, records the source-account check, never
  prints values, and cleans up staged copies.
* Do **not** `az login` as Secrets Officer on the prod VM (would leave a
  privileged token on the host). No Bastion.
* VM access (John, 14 Nov 2026 9:45am ET): temporary NSG inbound Allow SSH
  TCP/22 from John's own /32 only, fixed rule name
  TEMP-JOHN-SSH-SECRETS-INSTALL, then close-and-verify. No permanent
  Terraform/NSG IaC change. Out-of-band rules drift the next plan —
  close-and-verify is MANDATORY before any plan or apply.
* Host install writes service-UID-owned mode-0400 files matching
  infra/beta/vm/runtime/entrypoint.py read_private.
* Azure Run Command is refused (CTO 11 Nov 2026).

This module never prints, logs, or embeds a secret VALUE. Output is names,
pass/fail, mode, owner uid, and size>0 only. Live Azure calls are opt-in
via an injected VaultReader; unit tests use fakes only.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

PROFILE = "cosmabot-vm-prod-v1"
RESOURCE_GROUP = "rg-cosmabot-prod-eus2-01"
VM_NAME = "vm-cosmabot-prod-eus2-01"
KEY_VAULT_PREFIX = "kv-cbot-prd-"
KEY_VAULT_NAME_RE = re.compile(r"^kv-cbot-prd-[a-z0-9]+$")
RELEASE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
PROD_OAI_ACCOUNT_RE = re.compile(
    r"^/subscriptions/[^/]+/resourceGroups/rg-cosmabot-prod-eus2-01/"
    r"providers/Microsoft\.CognitiveServices/accounts/"
    r"oai-cbot-prd-[a-z0-9]{6,10}$"
)
LLM_VAULT_NAME = "WORKSPACE-LLM-API-KEY"
LLM_HOST_NAME = "WORKSPACE_LLM_API_KEY"
SOURCE_ACCOUNT_TAG = "source-account"
SOURCE_ACCOUNT_SIDECAR_SUFFIX = ".source-account"
# Runbook §4.3 restore/verify after any vault public-access window.
RUNBOOK_VAULT_RESTORE = "docs/runbooks/cosmabot-production-post-apply.md §4.3"
# Temporary SSH install window (John 14 Nov 2026 9:45am ET). Not in Terraform.
PROD_NSG_NAME = "nsg-cosmabot-prod-eus2-01"
TEMP_SSH_NSG_RULE_NAME = "TEMP-JOHN-SSH-SECRETS-INSTALL"
TEMP_SSH_NSG_RULE_PRIORITY = 200
DENY_ALL_INGRESS_RULE_NAME = "deny-all-other-ingress"
DENY_ALL_INGRESS_PRIORITY = 4000
RUNBOOK_SSH_CLOSE = "docs/runbooks/cosmabot-production-post-apply.md §4.5"

STAGING_NEEDLES = (
    "cosmabot-vm-staging",
    "rg-cosmas-os-vm-staging-eus2-lab01",
    "vm-cosmabot-staging-eus2-lab01",
    "kv-cbot-stg-",
    "staging.cosmas.ai",
    "api.staging.cosmas.ai",
    "acrcbotstgeus2",
    "stcbotapp",
    "stcbotbak",
    "cosmabot-vm/eastus2/lab01",
)
COSMASCODE_NEEDLES = (
    "cosmascode",
    "services.ai.azure.com",
    "shared-model",
    "shared_model",
)

API_UID = 10001
DATA_UID = 999
SECRET_LIMIT = 32768

ChownFn = Callable[[str | os.PathLike[str], int, int], None]
LstatFn = Callable[[str | os.PathLike[str]], os.stat_result]


@dataclass(frozen=True)
class SecretMapping:
    vault_name: str
    host_name: str
    roles: tuple[str, ...]


SECRET_CATALOG: tuple[SecretMapping, ...] = (
    SecretMapping("CLERK-SECRET-KEY", "CLERK_SECRET_KEY", ("api", "worker")),
    SecretMapping(
        "CLERK-ACCOUNT-DELETION-SECRET",
        "CLERK_ACCOUNT_DELETION_SECRET",
        ("api", "worker"),
    ),
    SecretMapping(
        "DATABASE-PASSWORD",
        "DATABASE_PASSWORD",
        ("api", "worker", "prepare"),
    ),
    SecretMapping(
        "POSTGRES-PASSWORD",
        "POSTGRES_PASSWORD",
        ("prepare", "postgres"),
    ),
    SecretMapping(
        "REDIS-PASSWORD",
        "REDIS_PASSWORD",
        ("api", "worker", "redis"),
    ),
    SecretMapping(
        "HUMAN-DEPLOY-EVIDENCE-REF",
        "HUMAN_DEPLOY_EVIDENCE_REF",
        ("api", "worker"),
    ),
    SecretMapping(
        LLM_VAULT_NAME,
        LLM_HOST_NAME,
        ("api", "worker"),
    ),
)

ROLE_UID: Mapping[str, int] = {
    "api": API_UID,
    "worker": API_UID,
    "prepare": API_UID,
    "postgres": DATA_UID,
    "redis": DATA_UID,
}


class Refused(RuntimeError):
    """Fixed diagnostic text only — never include secret values."""


class VaultReader(Protocol):
    def read_value(self, vault_name: str, secret_name: str) -> bytes:
        """Return raw secret bytes. Caller must not print them."""

    def read_tags(self, vault_name: str, secret_name: str) -> dict[str, str]:
        """Return secret tags (metadata only)."""


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise Refused(reason)


def _lower(value: str) -> str:
    return value.strip().lower()


def refuse_staging_names(*candidates: str) -> None:
    for raw in candidates:
        if not isinstance(raw, str) or not raw:
            continue
        value = _lower(raw)
        for needle in STAGING_NEEDLES:
            if value == needle or needle in value:
                raise Refused(f"staging_name_refused:{needle}")


def refuse_cosmascode_markers(*candidates: str) -> None:
    for raw in candidates:
        if not isinstance(raw, str) or not raw:
            continue
        value = _lower(raw)
        for needle in COSMASCODE_NEEDLES:
            if needle in value:
                raise Refused(f"cosmascode_key_refused:{needle}")


def validate_prod_coordinates(
    *,
    profile: str,
    resource_group: str,
    vault_name: str,
    vm_name: str | None = None,
) -> None:
    require(profile == PROFILE, f"profile_required:{PROFILE}")
    require(resource_group == RESOURCE_GROUP, f"resource_group_required:{RESOURCE_GROUP}")
    require(KEY_VAULT_NAME_RE.fullmatch(vault_name) is not None, "vault_name_must_be_kv-cbot-prd-*")
    if vm_name is not None:
        require(vm_name == VM_NAME, f"vm_name_required:{VM_NAME}")
    refuse_staging_names(profile, resource_group, vault_name, vm_name or "")
    refuse_cosmascode_markers(profile, resource_group, vault_name, vm_name or "")


def catalog_by_vault() -> dict[str, SecretMapping]:
    return {item.vault_name: item for item in SECRET_CATALOG}


def catalog_by_host() -> dict[str, SecretMapping]:
    return {item.host_name: item for item in SECRET_CATALOG}


def resolve_mappings(secret_names: list[str]) -> list[SecretMapping]:
    """Accept vault names or host file names; return catalog rows."""
    by_vault = catalog_by_vault()
    by_host = catalog_by_host()
    resolved: list[SecretMapping] = []
    seen: set[str] = set()
    for raw in secret_names:
        require(isinstance(raw, str) and raw.strip(), "secret_name_required")
        name = raw.strip()
        refuse_staging_names(name)
        refuse_cosmascode_markers(name)
        item = by_vault.get(name) or by_host.get(name)
        require(item is not None, f"unknown_secret_name:{name}")
        require(item.vault_name not in seen, f"duplicate_secret_name:{item.vault_name}")
        seen.add(item.vault_name)
        resolved.append(item)
    require(bool(resolved), "secret_names_required")
    return resolved


def is_llm_mapping(item: SecretMapping) -> bool:
    return item.vault_name == LLM_VAULT_NAME or item.host_name == LLM_HOST_NAME


def validate_llm_source_account(tags: Mapping[str, str]) -> str:
    """Require WORKSPACE-LLM-API-KEY source-account tag is the prod oai-cbot-prd-* id."""
    raw = tags.get(SOURCE_ACCOUNT_TAG, "")
    require(isinstance(raw, str) and raw.strip(), "llm_source_account_tag_required")
    account = raw.strip()
    refuse_cosmascode_markers(account)
    refuse_staging_names(account)
    require(
        PROD_OAI_ACCOUNT_RE.fullmatch(account) is not None,
        "llm_source_account_must_be_oai-cbot-prd",
    )
    return account


def source_account_sidecar_path(staging_dir: Path, item: SecretMapping) -> Path | None:
    for name in (item.host_name, item.vault_name):
        path = staging_dir / f"{name}{SOURCE_ACCOUNT_SIDECAR_SUFFIX}"
        if path.exists() or path.is_symlink():
            return path
    return None


def load_staging_llm_tags(staging_dir: Path, item: SecretMapping) -> dict[str, str]:
    """Load non-secret source-account sidecar required for LLM installs."""
    path = source_account_sidecar_path(staging_dir, item)
    require(path is not None, f"llm_source_account_sidecar_required:{item.host_name}")
    assert path is not None
    require(path.is_file() and not path.is_symlink(), f"llm_source_account_sidecar_invalid:{item.host_name}")
    text = path.read_text(encoding="utf-8")
    return {SOURCE_ACCOUNT_TAG: text.strip()}


def write_source_account_sidecar(staging_dir: Path, item: SecretMapping, account: str) -> None:
    path = staging_dir / f"{item.host_name}{SOURCE_ACCOUNT_SIDECAR_SUFFIX}"
    require(not path.exists() and not path.is_symlink(), "llm_source_account_sidecar_exists")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(account)
        stream.flush()
        os.fsync(stream.fileno())


def enforce_llm_source_account_on_mappings(
    mappings: list[SecretMapping],
    *,
    tags_for: Callable[[SecretMapping], Mapping[str, str]],
) -> None:
    """Call validate_llm_source_account for every LLM mapping on every install path."""
    for item in mappings:
        if is_llm_mapping(item):
            validate_llm_source_account(tags_for(item))


def normalize_secret_value(value: bytes) -> bytes:
    """Strip all leading/trailing whitespace; empty or NUL → STOP."""
    require(isinstance(value, (bytes, bytearray)), "secret_value_type")
    raw = bytes(value).strip()
    require(0 < len(raw) <= SECRET_LIMIT, "secret_value_empty_or_too_large")
    require(b"\x00" not in raw, "secret_value_nul_refused")
    return raw


def protected_role_dir(protected_root: Path, role: str) -> Path:
    require(role in ROLE_UID, f"unknown_role:{role}")
    return protected_root / role


def ensure_role_directory(
    path: Path,
    uid: int,
    *,
    chown_fn: ChownFn = os.chown,
    lstat_fn: LstatFn = os.lstat,
) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = lstat_fn(path)
    require(stat.S_ISDIR(info.st_mode) and not path.is_symlink(), "role_directory_invalid")
    path.chmod(0o700)
    try:
        chown_fn(path, uid, uid)
    except PermissionError as error:
        raise Refused("role_directory_chown_requires_root") from error


def write_secret_atomic(
    path: Path,
    value: bytes,
    uid: int,
    *,
    chown_fn: ChownFn = os.chown,
    lstat_fn: LstatFn = os.lstat,
) -> dict[str, object]:
    """Atomically write value with umask 077 then mode 0400; empty/whitespace STOP."""
    raw = normalize_secret_value(value)
    require(not path.exists() and not path.is_symlink(), f"secret_file_exists:{path.name}")

    old_mask = os.umask(0o077)
    tmp_path: Path | None = None
    try:
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=str(path.parent),
        )
        tmp_path = Path(tmp_name)
        try:
            os.fchmod(fd, 0o400)
            written = os.write(fd, raw)
            require(written == len(raw), "secret_write_short")
            os.fsync(fd)
        finally:
            os.close(fd)
        try:
            chown_fn(tmp_path, uid, uid)
        except PermissionError as error:
            tmp_path.unlink(missing_ok=True)
            raise Refused("secret_file_chown_requires_root") from error
        os.chmod(tmp_path, 0o400)
        os.rename(tmp_path, path)
        tmp_path = None
    finally:
        os.umask(old_mask)
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)

    info = lstat_fn(path)
    require(
        stat.S_ISREG(info.st_mode)
        and info.st_nlink == 1
        and stat.S_IMODE(info.st_mode) == 0o400
        and info.st_uid == uid
        and info.st_size > 0,
        f"secret_file_mode_owner_failed:{path.name}",
    )
    return {
        "host_name": path.name,
        "path": str(path),
        "mode": "0400",
        "owner_uid": uid,
        "size_gt_0": True,
        "status": "PASS",
    }


def refuse_run_command_transport() -> None:
    """CTO 11 Nov 2026: Run Command must never carry secret values or install them."""
    raise Refused("run_command_secret_transport_forbidden")


def _rule_port(rule: Mapping[str, object]) -> str:
    port = rule.get("port", rule.get("destinationPortRange", ""))
    return str(port)


def require_temp_ssh_rule_open(rules: list[Mapping[str, object]]) -> None:
    """Require TEMP-JOHN-SSH-SECRETS-INSTALL Allow TCP/22 with priority before deny-all."""
    require(isinstance(rules, list), "nsg_rules_required")
    matches = [
        rule
        for rule in rules
        if str(rule.get("name", "")) == TEMP_SSH_NSG_RULE_NAME
    ]
    require(len(matches) == 1, "temp_ssh_nsg_rule_missing")
    rule = matches[0]
    require(str(rule.get("access", "")) == "Allow", "temp_ssh_nsg_rule_not_allow")
    require(_rule_port(rule) == "22", "temp_ssh_nsg_rule_port_not_22")
    try:
        priority = int(rule.get("priority", -1))
    except (TypeError, ValueError) as error:
        raise Refused("temp_ssh_nsg_rule_priority_invalid") from error
    require(
        priority == TEMP_SSH_NSG_RULE_PRIORITY
        and priority < DENY_ALL_INGRESS_PRIORITY,
        "temp_ssh_nsg_rule_priority_invalid",
    )


def require_temp_ssh_rule_closed(rules: list[Mapping[str, object]]) -> None:
    """Require temp rule gone, no port-22 Allow, deny-all intact."""
    require(isinstance(rules, list), "nsg_rules_required")
    require(
        all(str(rule.get("name", "")) != TEMP_SSH_NSG_RULE_NAME for rule in rules),
        "temp_ssh_nsg_rule_still_present",
    )
    require(
        all(
            not (_rule_port(rule) == "22" and str(rule.get("access", "")) == "Allow")
            for rule in rules
        ),
        "port_22_allow_still_present",
    )
    deny = [
        rule
        for rule in rules
        if str(rule.get("name", "")) == DENY_ALL_INGRESS_RULE_NAME
        and str(rule.get("access", "")) == "Deny"
    ]
    require(len(deny) == 1, "deny_all_ingress_missing")
    try:
        priority = int(deny[0].get("priority", -1))
    except (TypeError, ValueError) as error:
        raise Refused("deny_all_ingress_priority_invalid") from error
    require(priority == DENY_ALL_INGRESS_PRIORITY, "deny_all_ingress_priority_invalid")


def require_ssh_install_ready(
    *,
    nsg_rules: list[Mapping[str, object]],
    close_verify_acked: bool,
) -> None:
    """Refuse install when the temp SSH rule is absent or close-and-verify was not acknowledged."""
    require(close_verify_acked, "close_and_verify_ack_required_before_install")
    require_temp_ssh_rule_open(nsg_rules)


def load_nsg_rules_json(path: Path) -> list[Mapping[str, object]]:
    import json

    require(path.is_file() and not path.is_symlink(), "nsg_rules_json_required")
    payload = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(payload, list), "nsg_rules_json_shape")
    return [item for item in payload if isinstance(item, dict)]


def cleanup_private_dir(path: Path) -> None:
    """Remove a private staging directory and its contents (best-effort)."""
    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
        return
    for child in sorted(path.rglob("*"), reverse=True):
        try:
            if child.is_symlink() or child.is_file():
                child.unlink(missing_ok=True)
            elif child.is_dir():
                child.rmdir()
        except OSError:
            pass
    try:
        path.rmdir()
    except OSError:
        shutil.rmtree(path, ignore_errors=True)


def private_work_parent(explicit: Path | None = None) -> Path:
    """Prefer tmpfs (/dev/shm) for private work; else a mode-700 under gettempdir."""
    if explicit is not None:
        return explicit
    shm = Path("/dev/shm")
    if shm.is_dir() and os.access(shm, os.W_OK):
        return shm / "cosmabot-secrets-work"
    return Path(tempfile.gettempdir()) / "cosmabot-secrets-work"


@contextmanager
def private_work_dir(parent: Path | None = None) -> Iterator[Path]:
    """Yield a mode-700 work directory; always clean up on exit (including errors)."""
    base = private_work_parent(parent)
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        base.chmod(0o700)
    except OSError as error:
        raise Refused("private_work_parent_mode_700_required") from error
    path = Path(tempfile.mkdtemp(prefix="stage-", dir=str(base)))
    try:
        path.chmod(0o700)
        yield path
    finally:
        cleanup_private_dir(path)


def ensure_staging_dir_mode_700(staging_dir: Path) -> None:
    staging_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    require(staging_dir.is_dir() and not staging_dir.is_symlink(), "staging_dir_invalid")
    staging_dir.chmod(0o700)
    info = staging_dir.lstat()
    require(stat.S_IMODE(info.st_mode) == 0o700, "staging_dir_mode_700_required")


def stage_from_vault(
    mappings: list[SecretMapping],
    *,
    vault_name: str,
    staging_dir: Path,
    reader: VaultReader,
) -> list[dict[str, object]]:
    """Workstation stage-only: fetch into mode-700 dir under John's /32 window.

    Records source-account for LLM. Never prints values. Never installs on the
    VM. Caller must cleanup_private_dir / cleanup after transfer. After the
    vault window: restore per runbook §4.3.
    """
    require(KEY_VAULT_NAME_RE.fullmatch(vault_name) is not None, "vault_name_must_be_kv-cbot-prd-*")
    refuse_staging_names(vault_name, str(staging_dir))
    ensure_staging_dir_mode_700(staging_dir)
    results: list[dict[str, object]] = []
    old_mask = os.umask(0o077)
    try:
        for item in mappings:
            if is_llm_mapping(item):
                tags = reader.read_tags(vault_name, item.vault_name)
                account = validate_llm_source_account(tags)
                write_source_account_sidecar(staging_dir, item, account)
            value = normalize_secret_value(reader.read_value(vault_name, item.vault_name))
            target = staging_dir / item.host_name
            require(not target.exists() and not target.is_symlink(), f"staging_file_exists:{item.host_name}")
            fd = os.open(
                target,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
            )
            with os.fdopen(fd, "wb") as stream:
                stream.write(value)
                stream.flush()
                os.fsync(stream.fileno())
            info = target.lstat()
            require(
                stat.S_ISREG(info.st_mode)
                and stat.S_IMODE(info.st_mode) == 0o600
                and info.st_size > 0,
                f"staging_file_mode_failed:{item.host_name}",
            )
            results.append(
                {
                    "vault_name": item.vault_name,
                    "host_name": item.host_name,
                    "role": "staging",
                    "mode": "0600",
                    "owner_uid": info.st_uid,
                    "size_gt_0": True,
                    "status": "PASS",
                    "vault_restore": RUNBOOK_VAULT_RESTORE,
                }
            )
    finally:
        os.umask(old_mask)
    return results


def install_from_staging(
    mappings: list[SecretMapping],
    *,
    protected_root: Path,
    staging_dir: Path,
    release_id: str,
    chown_fn: ChownFn = os.chown,
    lstat_fn: LstatFn = os.lstat,
) -> list[dict[str, object]]:
    """Install secret files from a local staging directory (values as files, never argv)."""
    require(RELEASE_ID_RE.fullmatch(release_id) is not None, "release_id_invalid")
    refuse_staging_names(release_id, str(staging_dir), str(protected_root))
    require(staging_dir.is_dir() and not staging_dir.is_symlink(), "staging_dir_required")
    require(protected_root.is_dir() and not protected_root.is_symlink(), "protected_root_required")
    enforce_llm_source_account_on_mappings(
        mappings,
        tags_for=lambda item: load_staging_llm_tags(staging_dir, item),
    )
    results: list[dict[str, object]] = []
    for item in mappings:
        source = staging_dir / item.host_name
        if not source.exists():
            alt = staging_dir / item.vault_name
            source = alt if alt.exists() else source
        require(
            source.is_file() and not source.is_symlink(),
            f"staging_file_missing:{item.host_name}",
        )
        value = source.read_bytes()
        # normalize_secret_value enforces whitespace-only / empty / NUL STOP.
        for role in item.roles:
            uid = ROLE_UID[role]
            role_dir = protected_role_dir(protected_root, role)
            ensure_role_directory(role_dir, uid, chown_fn=chown_fn, lstat_fn=lstat_fn)
            dest = role_dir / item.host_name
            result = write_secret_atomic(
                dest,
                value,
                uid,
                chown_fn=chown_fn,
                lstat_fn=lstat_fn,
            )
            results.append(
                {
                    **result,
                    "vault_name": item.vault_name,
                    "role": role,
                    "release_id": release_id,
                }
            )
    return results


def transport_from_vault(
    mappings: list[SecretMapping],
    *,
    vault_name: str,
    protected_root: Path,
    release_id: str,
    reader: VaultReader,
    work_parent: Path | None = None,
    chown_fn: ChownFn = os.chown,
    lstat_fn: LstatFn = os.lstat,
) -> list[dict[str, object]]:
    """Stage into a private mode-700 dir (not world-writable default temp), then install.

    Always cleans up the private work dir on success or exception. CLI operators
    should prefer stage_from_vault on the workstation under the /32 window.
    """
    require(KEY_VAULT_NAME_RE.fullmatch(vault_name) is not None, "vault_name_must_be_kv-cbot-prd-*")
    refuse_staging_names(vault_name)
    with private_work_dir(work_parent) as staging:
        # Fetch + LLM check into private dir, then install from that dir.
        stage_from_vault(
            mappings,
            vault_name=vault_name,
            staging_dir=staging,
            reader=reader,
        )
        return install_from_staging(
            mappings,
            protected_root=protected_root,
            staging_dir=staging,
            release_id=release_id,
            chown_fn=chown_fn,
            lstat_fn=lstat_fn,
        )


class FakeVaultReader:
    """Synthetic fixture reader for tests. Never used against Azure."""

    def __init__(
        self,
        values: Mapping[str, bytes],
        tags: Mapping[str, Mapping[str, str]] | None = None,
    ) -> None:
        self._values = dict(values)
        self._tags = {key: dict(value) for key, value in (tags or {}).items()}

    def read_value(self, vault_name: str, secret_name: str) -> bytes:
        require(secret_name in self._values, f"fake_missing:{secret_name}")
        return self._values[secret_name]

    def read_tags(self, vault_name: str, secret_name: str) -> dict[str, str]:
        return dict(self._tags.get(secret_name, {}))


class AzCliVaultReader:
    """Workstation-only: read via `az` as the release operator. Values stay off stdout.

    Never run this on the prod VM (do not leave a Secrets Officer token there).
    """

    def __init__(
        self,
        runner: Callable[..., subprocess.CompletedProcess] | None = None,
    ) -> None:
        self._runner = runner or subprocess.run

    def read_value(self, vault_name: str, secret_name: str) -> bytes:
        require(KEY_VAULT_NAME_RE.fullmatch(vault_name) is not None, "vault_name_must_be_kv-cbot-prd-*")
        refuse_staging_names(vault_name, secret_name)
        refuse_cosmascode_markers(secret_name)
        result = self._runner(
            [
                "az",
                "keyvault",
                "secret",
                "show",
                "--vault-name",
                vault_name,
                "--name",
                secret_name,
                "--query",
                "value",
                "-o",
                "tsv",
            ],
            capture_output=True,
            check=False,
        )
        # Never print stdout/stderr (may contain the value on failure paths).
        require(result.returncode == 0, f"vault_read_failed:{secret_name}")
        value = result.stdout if isinstance(result.stdout, bytes) else result.stdout.encode()
        return normalize_secret_value(value)

    def read_tags(self, vault_name: str, secret_name: str) -> dict[str, str]:
        require(KEY_VAULT_NAME_RE.fullmatch(vault_name) is not None, "vault_name_must_be_kv-cbot-prd-*")
        result = self._runner(
            [
                "az",
                "keyvault",
                "secret",
                "show",
                "--vault-name",
                vault_name,
                "--name",
                secret_name,
                "--query",
                "tags",
                "-o",
                "json",
            ],
            capture_output=True,
            check=False,
            text=True,
        )
        require(result.returncode == 0, f"vault_tags_failed:{secret_name}")
        import json

        payload = json.loads(result.stdout or "{}")
        require(isinstance(payload, dict), "vault_tags_shape")
        return {str(key): str(value) for key, value in payload.items()}


def format_result_line(result: Mapping[str, object]) -> str:
    """Public status line: names / mode / owner / size flag only."""
    return (
        f"PASS: vault_name={result.get('vault_name', '')} "
        f"host_name={result.get('host_name', '')} "
        f"role={result.get('role', '')} "
        f"mode={result.get('mode', '')} "
        f"owner_uid={result.get('owner_uid', '')} "
        f"size_gt_0={result.get('size_gt_0', False)}"
    )


def plan_lines(mappings: list[SecretMapping]) -> list[str]:
    lines = [
        f"profile={PROFILE}",
        f"resource_group={RESOURCE_GROUP}",
        f"vm_name={VM_NAME}",
        f"key_vault_prefix={KEY_VAULT_PREFIX}",
        f"nsg_name={PROD_NSG_NAME}",
        f"temp_ssh_rule={TEMP_SSH_NSG_RULE_NAME}",
        f"temp_ssh_priority={TEMP_SSH_NSG_RULE_PRIORITY}",
        "owner_model=service_uid_mode_0400",
        "transport=workstation_stage_then_temp_ssh_install",
        "run_command=forbidden",
        "bastion=forbidden",
        "vm_az_login_as_secrets_officer=forbidden",
        "vm_access_step=temp_ssh_nsg_rule_john_32",
        "close_and_verify=mandatory_before_terraform_plan_or_apply",
        f"vault_window_restore={RUNBOOK_VAULT_RESTORE}",
        f"ssh_close_verify={RUNBOOK_SSH_CLOSE}",
    ]
    for item in mappings:
        roles = ",".join(item.roles)
        lines.append(
            f"map vault_name={item.vault_name} host_name={item.host_name} roles={roles}"
        )
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--vault-name", required=True)
    parser.add_argument("--vm-name", default=VM_NAME)
    parser.add_argument(
        "--secret-name",
        action="append",
        dest="secret_names",
        default=[],
        help="Vault or host secret name (repeatable). Names only.",
    )
    parser.add_argument("--release-id", default="")
    parser.add_argument(
        "--protected-root",
        type=Path,
        default=None,
        help="Usually /etc/cosmabot/runtime/<release_id>",
    )
    parser.add_argument(
        "--staging-dir",
        type=Path,
        default=None,
        help="Mode-700 private directory of secret files (names as filenames).",
    )
    parser.add_argument(
        "--via-run-command",
        action="store_true",
        help="Refused: Run Command must never install secrets.",
    )
    parser.add_argument(
        "--stage-from-vault",
        action="store_true",
        help=(
            "Workstation only (John /32 vault window): fetch names into --staging-dir. "
            "Never on the prod VM. Restore vault per §4.3 after."
        ),
    )
    parser.add_argument(
        "--cleanup-staging",
        action="store_true",
        help="Remove --staging-dir contents after a successful install (VM or workstation).",
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="Print name mapping only.",
    )
    parser.add_argument(
        "--check-ssh-install-ready",
        action="store_true",
        help=(
            "Workstation gate: require TEMP-JOHN-SSH-SECRETS-INSTALL open and "
            "--ack-close-and-verify before SCP/install."
        ),
    )
    parser.add_argument(
        "--ack-close-and-verify",
        action="store_true",
        help="Acknowledge that §4.5 close-and-verify is mandatory after every outcome.",
    )
    parser.add_argument(
        "--nsg-rules-json",
        type=Path,
        default=None,
        help="JSON list of NSG rules {name,port,access,priority} only (no secrets).",
    )
    parser.add_argument(
        "--check-ssh-closed",
        action="store_true",
        help="Verify temp SSH rule absent, no port-22 Allow, deny-all intact.",
    )
    args = parser.parse_args(argv)

    try:
        if args.via_run_command:
            refuse_run_command_transport()
        validate_prod_coordinates(
            profile=args.profile,
            resource_group=args.resource_group,
            vault_name=args.vault_name,
            vm_name=args.vm_name,
        )
        names = args.secret_names or [item.vault_name for item in SECRET_CATALOG]
        mappings = resolve_mappings(names)
        if args.plan_only:
            for line in plan_lines(mappings):
                print(line)
            return 0
        if args.check_ssh_install_ready or args.check_ssh_closed:
            require(args.nsg_rules_json is not None, "nsg_rules_json_required")
            rules = load_nsg_rules_json(args.nsg_rules_json)
            if args.check_ssh_closed:
                require_temp_ssh_rule_closed(rules)
                print(
                    f"PASS: temp SSH rule closed; see {RUNBOOK_SSH_CLOSE}; "
                    "mandatory before Terraform plan or apply"
                )
                return 0
            require_ssh_install_ready(
                nsg_rules=rules,
                close_verify_acked=args.ack_close_and_verify,
            )
            print(
                f"PASS: {TEMP_SSH_NSG_RULE_NAME} open; close-and-verify acknowledged"
            )
            return 0
        if args.stage_from_vault:
            require(args.staging_dir is not None, "staging_dir_required")
            results = stage_from_vault(
                mappings,
                vault_name=args.vault_name,
                staging_dir=args.staging_dir,
                reader=AzCliVaultReader(),
            )
            for result in results:
                print(format_result_line(result))
            print(
                "PASS: workstation stage complete; restore vault per "
                f"{RUNBOOK_VAULT_RESTORE}; next §4.5 temp SSH open/install/close"
            )
            return 0
        require(args.release_id, "release_id_required")
        require(args.staging_dir is not None, "staging_dir_required")
        root = args.protected_root or Path("/etc/cosmabot/runtime") / args.release_id
        results = install_from_staging(
            mappings,
            protected_root=root,
            staging_dir=args.staging_dir,
            release_id=args.release_id,
        )
        for result in results:
            print(format_result_line(result))
        if args.cleanup_staging:
            cleanup_private_dir(args.staging_dir)
            print("PASS: staging cleanup complete (values not printed)")
        return 0
    except Refused as error:
        print(f"STOP: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
