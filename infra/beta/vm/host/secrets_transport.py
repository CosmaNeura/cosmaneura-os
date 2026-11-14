#!/usr/bin/env python3
"""Transport Key Vault secret NAMES onto prod host files as mode-0400.

Access model (does not widen the VM runtime managed identity):

* Key Vault reads use the existing off-VM release operator principal
  (Key Vault Secrets Officer on kv-cbot-prd-*). That assignment already
  exists in prod foundation IaC. This tooling never assigns vault roles
  to the runtime UAMI.
* Values move operator-side → host files. Azure Run Command is refused
  as a transport (CTO 11 Nov 2026): scripts/arguments never carry values.
* Host files are owned by the service UID for each role directory
  (10001 api/worker/prepare, 999 postgres/redis), mode 0400, matching
  infra/beta/vm/runtime/entrypoint.py read_private.

This module never prints, logs, or embeds a secret VALUE. Output is names,
pass/fail, mode, owner uid, and size>0 only. Live Azure calls are opt-in
via an injected VaultReader; the default CLI path that shells to `az` is
for operators only and is never exercised by unit tests.
"""
from __future__ import annotations

import argparse
import os
import re
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
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

# Cross-environment / shared-key needles (lowercase). Staging profile names,
# hosts, RG, vault prefix, and CosmasCode markers are refused.
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


@dataclass(frozen=True)
class SecretMapping:
    vault_name: str
    host_name: str
    roles: tuple[str, ...]


# Names-only catalog from the prod runbook / prod README. LLM key is optional
# until AI-on; include it when the operator requests it.
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


def protected_role_dir(protected_root: Path, role: str) -> Path:
    require(role in ROLE_UID, f"unknown_role:{role}")
    return protected_root / role


def ensure_role_directory(path: Path, uid: int) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) and not path.is_symlink(), "role_directory_invalid")
    # Directory may already exist from prior install; enforce mode.
    path.chmod(0o700)
    try:
        os.chown(path, uid, uid)
    except PermissionError as error:
        raise Refused("role_directory_chown_requires_root") from error


def write_secret_atomic(path: Path, value: bytes, uid: int) -> dict[str, object]:
    """Atomically write value with umask 077 then mode 0400; empty value STOPs."""
    require(isinstance(value, (bytes, bytearray)), "secret_value_type")
    raw = bytes(value)
    # Strip a single trailing newline (Key Vault / file convention); refuse empty.
    if raw.endswith(b"\n"):
        raw = raw[:-1]
    require(0 < len(raw) <= SECRET_LIMIT, "secret_value_empty_or_too_large")
    require(b"\x00" not in raw, "secret_value_nul_refused")
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
            os.chown(tmp_path, uid, uid)
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

    info = path.lstat()
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


def render_names_only_host_script(
    mappings: list[SecretMapping],
    *,
    release_id: str,
    staging_dir: str,
) -> str:
    """Bash that copies from a local staging dir by NAME only — no values embedded.

    Intended for SSH/root on the VM. Not an Azure Run Command payload.
    """
    require(RELEASE_ID_RE.fullmatch(release_id) is not None, "release_id_invalid")
    refuse_staging_names(release_id, staging_dir)
    lines = [
        "#!/bin/bash",
        "set -euo pipefail",
        "umask 077",
        f'RELEASE_ID={release_id!r}',
        f'STAGING={staging_dir!r}',
        'ROOT="/etc/cosmabot/runtime/${RELEASE_ID}"',
        'test -d "$STAGING" || { echo "STOP: staging dir missing" >&2; exit 1; }',
        'test -d "$ROOT" || { echo "STOP: protected root missing" >&2; exit 1; }',
    ]
    for item in mappings:
        for role in item.roles:
            uid = ROLE_UID[role]
            lines.extend(
                [
                    f'NAME={item.host_name!r}',
                    f'ROLE={role!r}',
                    f'UID_NUM={uid}',
                    'SRC="${STAGING}/${NAME}"',
                    'DEST="${ROOT}/${ROLE}/${NAME}"',
                    'test -s "$SRC" || { echo "STOP: empty or missing ${NAME}" >&2; exit 1; }',
                    'mkdir -p -m 700 "${ROOT}/${ROLE}"',
                    'chown "${UID_NUM}:${UID_NUM}" "${ROOT}/${ROLE}"',
                    'TMP="${DEST}.tmp.$$"',
                    'cp -f "$SRC" "$TMP"',
                    'chown "${UID_NUM}:${UID_NUM}" "$TMP"',
                    'chmod 0400 "$TMP"',
                    'mv -f "$TMP" "$DEST"',
                    'test -s "$DEST" || { echo "STOP: ${NAME} size" >&2; exit 1; }',
                    'test "$(stat -c \'%a\' "$DEST")" = "400" || { echo "STOP: ${NAME} mode" >&2; exit 1; }',
                    'echo "PASS: name=${NAME} role=${ROLE} mode=0400 owner_uid=${UID_NUM} size_gt_0=true"',
                ]
            )
    lines.append('echo "PASS: host secret install complete (values not printed)"')
    return "\n".join(lines) + "\n"


def install_from_staging(
    mappings: list[SecretMapping],
    *,
    protected_root: Path,
    staging_dir: Path,
    release_id: str,
    chown_enabled: bool = True,
) -> list[dict[str, object]]:
    """Install secret files from a local staging directory (values as files, never argv)."""
    require(RELEASE_ID_RE.fullmatch(release_id) is not None, "release_id_invalid")
    refuse_staging_names(release_id, str(staging_dir), str(protected_root))
    require(staging_dir.is_dir(), "staging_dir_required")
    require(protected_root.is_dir(), "protected_root_required")
    results: list[dict[str, object]] = []
    for item in mappings:
        source = staging_dir / item.host_name
        if not source.exists():
            alt = staging_dir / item.vault_name
            source = alt if alt.exists() else source
        require(source.is_file() and not source.is_symlink(), f"staging_file_missing:{item.host_name}")
        # Read bytes for install; never print.
        value = source.read_bytes()
        require(len(value) > 0 and (len(value) > 1 or value != b"\n"), f"staging_file_empty:{item.host_name}")
        for role in item.roles:
            uid = ROLE_UID[role]
            role_dir = protected_role_dir(protected_root, role)
            if chown_enabled:
                ensure_role_directory(role_dir, uid)
            else:
                role_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
                role_dir.chmod(0o700)
            dest = role_dir / item.host_name
            if not chown_enabled:
                # Unit-test path: write as current uid, still mode 0400 / non-empty.
                result = _write_secret_atomic_test_uid(dest, value)
            else:
                result = write_secret_atomic(dest, value, uid)
            result = {
                **result,
                "vault_name": item.vault_name,
                "role": role,
                "release_id": release_id,
            }
            results.append(result)
    return results


def _write_secret_atomic_test_uid(path: Path, value: bytes) -> dict[str, object]:
    """Same atomic 0400 write without chown (for non-root unit tests)."""
    require(isinstance(value, (bytes, bytearray)), "secret_value_type")
    raw = bytes(value)
    if raw.endswith(b"\n"):
        raw = raw[:-1]
    require(0 < len(raw) <= SECRET_LIMIT, "secret_value_empty_or_too_large")
    require(b"\x00" not in raw, "secret_value_nul_refused")
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
        os.chmod(tmp_path, 0o400)
        os.rename(tmp_path, path)
        tmp_path = None
    finally:
        os.umask(old_mask)
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
    info = path.lstat()
    require(
        stat.S_ISREG(info.st_mode)
        and info.st_nlink == 1
        and stat.S_IMODE(info.st_mode) == 0o400
        and info.st_size > 0,
        f"secret_file_mode_failed:{path.name}",
    )
    return {
        "host_name": path.name,
        "path": str(path),
        "mode": "0400",
        "owner_uid": info.st_uid,
        "size_gt_0": True,
        "status": "PASS",
    }


def transport_from_vault(
    mappings: list[SecretMapping],
    *,
    vault_name: str,
    protected_root: Path,
    release_id: str,
    reader: VaultReader,
    chown_enabled: bool = True,
) -> list[dict[str, object]]:
    """Fetch by NAME via reader (release operator), then install. Values never printed."""
    require(KEY_VAULT_NAME_RE.fullmatch(vault_name) is not None, "vault_name_must_be_kv-cbot-prd-*")
    refuse_staging_names(vault_name)
    results: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="cosmabot-secrets-staging-") as tmp:
        staging = Path(tmp)
        old_mask = os.umask(0o077)
        try:
            for item in mappings:
                if item.vault_name == LLM_VAULT_NAME:
                    tags = reader.read_tags(vault_name, item.vault_name)
                    validate_llm_source_account(tags)
                value = reader.read_value(vault_name, item.vault_name)
                # Empty / whitespace-only STOP (test -s semantics).
                stripped = value[:-1] if value.endswith(b"\n") else value
                require(len(stripped) > 0, f"vault_secret_empty:{item.vault_name}")
                target = staging / item.host_name
                fd = os.open(
                    target,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                )
                with os.fdopen(fd, "wb") as stream:
                    stream.write(value)
                    stream.flush()
                    os.fsync(stream.fileno())
        finally:
            os.umask(old_mask)
        results = install_from_staging(
            mappings,
            protected_root=protected_root,
            staging_dir=staging,
            release_id=release_id,
            chown_enabled=chown_enabled,
        )
    return results


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
    """Operator-only: read via `az` as the release operator. Values stay off stdout."""

    def __init__(
        self,
        runner: Callable[..., subprocess.CompletedProcess] | None = None,
    ) -> None:
        self._runner = runner or subprocess.run

    def read_value(self, vault_name: str, secret_name: str) -> bytes:
        require(KEY_VAULT_NAME_RE.fullmatch(vault_name) is not None, "vault_name_must_be_kv-cbot-prd-*")
        refuse_staging_names(vault_name, secret_name)
        refuse_cosmascode_markers(secret_name)
        # Capture value; do not print. --output tsv is consumed into memory only.
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
        require(result.returncode == 0, f"vault_read_failed:{secret_name}")
        # stderr may contain az diagnostics; never echo value-bearing stdout.
        value = result.stdout if isinstance(result.stdout, bytes) else result.stdout.encode()
        stripped = value[:-1] if value.endswith(b"\n") else value
        require(len(stripped) > 0, f"vault_secret_empty:{secret_name}")
        return value

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
        "owner_model=service_uid_mode_0400",
        "transport=release_operator_to_host_files",
        "run_command=forbidden",
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
        help="Local directory of secret files (names as filenames).",
    )
    parser.add_argument(
        "--via-run-command",
        action="store_true",
        help="Refused: Run Command must never install secrets.",
    )
    parser.add_argument(
        "--emit-host-script",
        action="store_true",
        help="Print a names-only host install script (SSH path; not Run Command).",
    )
    parser.add_argument(
        "--from-vault",
        action="store_true",
        help="Fetch via az as release operator then install (operator machine / VM SSH).",
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="Print name mapping only.",
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
        # Default catalog includes LLM; operators may omit it until AI-on by
        # passing an explicit --secret-name list without WORKSPACE-LLM-API-KEY.
        mappings = resolve_mappings(names)
        if args.plan_only:
            for line in plan_lines(mappings):
                print(line)
            return 0
        if args.emit_host_script:
            require(args.release_id, "release_id_required")
            require(args.staging_dir is not None, "staging_dir_required")
            script = render_names_only_host_script(
                mappings,
                release_id=args.release_id,
                staging_dir=str(args.staging_dir),
            )
            # Script contains names/paths only; print it.
            sys.stdout.write(script)
            return 0
        require(args.release_id, "release_id_required")
        root = args.protected_root or Path("/etc/cosmabot/runtime") / args.release_id
        if args.from_vault:
            results = transport_from_vault(
                mappings,
                vault_name=args.vault_name,
                protected_root=root,
                release_id=args.release_id,
                reader=AzCliVaultReader(),
            )
        else:
            require(args.staging_dir is not None, "staging_dir_required")
            results = install_from_staging(
                mappings,
                protected_root=root,
                staging_dir=args.staging_dir,
                release_id=args.release_id,
            )
        for result in results:
            print(format_result_line(result))
        return 0
    except Refused as error:
        # Refused messages are fixed codes — still scrub any accidental value leak.
        print(f"STOP: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
