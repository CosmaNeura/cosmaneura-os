#!/usr/bin/env python3
"""Build the CosmaBot host creation receipt from read-only Azure ARM gets.

John runs this from a workstation (typically macOS) after the foundation apply.
It issues only read-only `az` gets (`az vm show`, `az disk show`), writes the
JSON receipt that `bootstrap_host.validate_receipt` expects, and writes the
matching sha256 sidecar.

No Azure writes. No secrets. Does not change or loosen `bootstrap_host.py`.

Timestamp provenance (ARM-backed only; never invented):
  * disk_created_utc   = `az disk show` → timeCreated
  * apply_started_utc  = earliest ARM timeCreated of the VM and the disk
    (explicit proxy: Azure does not store a separate foundation-apply start on
    the VM or disk; bootstrap's 24h window is anchored to this proxy)
  * apply_completed_utc = latest of VM timeCreated (when present) and disk
    timeCreated. Same honesty rule: no tofu/apply end stamp exists on these
    resources, so the latest ARM creation time is a lower bound on apply end
    that still satisfies started <= created <= completed.

If a required ARM field is missing, this tool STOPs with a clear message and
exit status 1. It never fabricates IDs or timestamps.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib

# Import profile helpers from the adjacent bootstrap module without installing a package.
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

_MODULE_DIR = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "bootstrap_host_for_receipt", _MODULE_DIR / "bootstrap_host.py"
)
assert _spec is not None and _spec.loader is not None
_bootstrap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_bootstrap)

STAGING_PROFILE = _bootstrap.STAGING_PROFILE
PROD_PROFILE = _bootstrap.PROD_PROFILE
PROFILES = _bootstrap.PROFILES
resolve_profile = _bootstrap.resolve_profile
refuse_cross_environment = _bootstrap.refuse_cross_environment
validate_receipt = _bootstrap.validate_receipt
Refused = _bootstrap.Refused

AzRunner = Callable[[list[str]], dict[str, Any]]

RECEIPT_SOURCE = "azure-arm-disk-and-vm-get"
RECEIPT_VERSION = 1
SIZE_GIB = 128
REQUIRED_LUN = 0
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_AZ_READ_VERBS = frozenset({"show", "list", "get"})
# Azure write verbs that must never appear in the argv we construct.
_AZ_WRITE_VERBS = frozenset({
    "create", "update", "delete", "set", "remove", "start", "stop", "restart",
    "deallocate", "resize", "attach-data-disk", "detach-data-disk", "run-command",
    "extension", "wait", "apply", "deploy",
})
# Env keys forwarded to az. Secrets / SP credentials are never passed through.
_AZ_ENV_ALLOWLIST = (
    "HOME", "PATH", "USER", "LOGNAME", "LANG", "LC_ALL", "AZURE_CONFIG_DIR",
    "AZURE_SUBSCRIPTION_ID", "ARM_SUBSCRIPTION_ID",
)
_AZ_ENV_SECRET_DENYLIST = (
    "AZURE_CLIENT_SECRET", "AZURE_CLIENT_ID", "AZURE_TENANT_ID",
)


class Stop(RuntimeError):
    """Operator-facing refusal; main() prints STOP: and exits 1."""


def stop(reason: str) -> None:
    raise Stop(reason)


def normalize_utc(value: str, *, field: str) -> str:
    """Normalize an ARM timestamp to an ISO8601 string bootstrap.timestamp accepts."""
    if not isinstance(value, str) or not value.strip():
        stop(f"Missing required ARM timestamp field: {field}")
    raw = value.strip()
    try:
        parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        # Azure sometimes emits >6 fractional digits; trim to microseconds.
        match = re.fullmatch(
            r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(\.\d+)?(Z|[+-]\d{2}:\d{2})",
            raw,
        )
        if match is None:
            stop(f"Unreadable ARM timestamp for {field}: {raw!r}")
        base, frac, tz = match.group(1), match.group(2) or "", match.group(3)
        if frac:
            digits = frac[1:7].ljust(6, "0")
            raw = f"{base}.{digits}{tz}"
        else:
            raw = f"{base}{tz}"
        try:
            parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            stop(f"Unreadable ARM timestamp for {field}: {value!r} ({exc})")
    if parsed.tzinfo is None:
        stop(f"ARM timestamp for {field} lacks a timezone: {value!r}")
    parsed = parsed.astimezone(dt.UTC).replace(microsecond=0)
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def az_subprocess_env(source: dict[str, str] | None = None) -> dict[str, str]:
    """Build the env passed to az: allowlist only; never forward SP secrets."""
    env_source = os.environ if source is None else source
    env = {key: env_source[key] for key in _AZ_ENV_ALLOWLIST if key in env_source}
    for denied in _AZ_ENV_SECRET_DENYLIST:
        env.pop(denied, None)
    return env


def default_az_runner(argv: list[str]) -> dict[str, Any]:
    """Run a read-only az CLI command and parse JSON stdout."""
    if not argv or argv[0] != "az":
        stop("Internal az runner refused non-az argv")
    # Refuse any write-shaped verb in the command (defense in depth).
    for token in argv[1:]:
        if token.startswith("-"):
            continue
        if token.lower() in _AZ_WRITE_VERBS:
            stop(f"Refused non-read az verb in argv: {token}")
        # First non-option after `az <group>` is enough; break after group+verb check below.
    if len(argv) < 3:
        stop("Internal az runner refused short argv")
    group, verb = argv[1], argv[2]
    if verb.lower() not in _AZ_READ_VERBS:
        stop(f"Refused non-read az verb: az {group} {verb}")
    try:
        result = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            shell=False,
            env=az_subprocess_env(),
        )
    except FileNotFoundError:
        stop("az CLI not found on PATH; install Azure CLI before building the receipt")
    if result.returncode != 0:
        # Never dump stderr wholesale (may contain subscription noise); keep short.
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        hint = detail[0] if detail else f"exit {result.returncode}"
        stop(f"az read failed ({' '.join(argv[:4])}…): {hint[:200]}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        stop(f"az returned non-JSON for {' '.join(argv[:4])}")
    if not isinstance(payload, dict):
        stop(f"az returned a non-object JSON payload for {' '.join(argv[:4])}")
    return payload


def az_vm_show(*, rg: str, vm: str, runner: AzRunner) -> dict[str, Any]:
    return runner([
        "az", "vm", "show",
        "--resource-group", rg,
        "--name", vm,
        "-o", "json",
    ])


def az_disk_show(*, rg: str, disk: str, runner: AzRunner) -> dict[str, Any]:
    return runner([
        "az", "disk", "show",
        "--resource-group", rg,
        "--name", disk,
        "-o", "json",
    ])


def require_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        stop(f"Missing required field from az: {field}")
    return value.strip()


def require_uuid(value: Any, field: str) -> str:
    text = require_str(value, field)
    if UUID_RE.fullmatch(text) is None:
        stop(f"Field {field} is not a UUID: {text!r}")
    return text


def data_disks_from_vm(vm_payload: dict[str, Any]) -> list[dict[str, Any]]:
    profile = vm_payload.get("storageProfile")
    if not isinstance(profile, dict):
        stop("Missing required field from az: vm.storageProfile")
    disks = profile.get("dataDisks")
    if disks is None:
        stop("Missing required field from az: vm.storageProfile.dataDisks")
    if not isinstance(disks, list):
        stop("vm.storageProfile.dataDisks must be a list")
    return disks


def lun_for_disk(data_disks: list[dict[str, Any]], disk_id: str) -> int:
    if len(data_disks) == 0:
        stop("No data disks attached to the VM")
    if len(data_disks) > 1:
        stop(f"Multiple data disks attached ({len(data_disks)}); exactly one Empty LUN 0 disk is required")
    disk = data_disks[0]
    if not isinstance(disk, dict):
        stop("VM data disk entry is not an object")
    managed = disk.get("managedDisk")
    if not isinstance(managed, dict):
        stop("Missing required field from az: dataDisks[0].managedDisk")
    attached_id = require_str(managed.get("id"), "dataDisks[0].managedDisk.id")
    if attached_id.lower() != disk_id.lower():
        stop("Sole data disk managedDisk.id does not match the profile data disk")
    lun_raw = disk.get("lun")
    if lun_raw is None:
        stop("Missing required field from az: dataDisks[0].lun")
    try:
        lun = int(lun_raw)
    except (TypeError, ValueError):
        stop(f"dataDisks[0].lun is not an integer: {lun_raw!r}")
    if lun != REQUIRED_LUN:
        stop(f"Data disk LUN is {lun}, not {REQUIRED_LUN}")
    return lun


def size_gib_from_disk(disk_payload: dict[str, Any]) -> int:
    # Azure CLI may emit diskSizeGb or diskSizeGB.
    raw = disk_payload.get("diskSizeGb", disk_payload.get("diskSizeGB"))
    if raw is None:
        stop("Missing required field from az: disk.diskSizeGb")
    try:
        size = int(raw)
    except (TypeError, ValueError):
        stop(f"disk.diskSizeGb is not an integer: {raw!r}")
    if size != SIZE_GIB:
        stop(f"Data disk size is {size} GiB, not {SIZE_GIB} GiB")
    return size


def create_option_from_disk(disk_payload: dict[str, Any]) -> str:
    creation = disk_payload.get("creationData")
    if not isinstance(creation, dict):
        stop("Missing required field from az: disk.creationData")
    option = creation.get("createOption")
    if not isinstance(option, str) or not option:
        stop("Missing required field from az: disk.creationData.createOption")
    if option != "Empty":
        stop(f"Disk createOption is {option!r}, not 'Empty'")
    return option


def build_receipt(
    *,
    profile: str,
    runner: AzRunner,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """Read ARM VM+disk and build a receipt dict that validate_receipt accepts."""
    spec = resolve_profile(profile)
    refuse_cross_environment(spec["profile"], [profile, spec["rg"], spec["vm"], spec["disk"]])

    vm_payload = az_vm_show(rg=spec["rg"], vm=spec["vm"], runner=runner)
    disk_payload = az_disk_show(rg=spec["rg"], disk=spec["disk"], runner=runner)

    vm_id = require_str(vm_payload.get("id"), "vm.id")
    disk_id = require_str(disk_payload.get("id"), "disk.id")
    refuse_cross_environment(spec["profile"], [vm_id, disk_id])

    # Profile name binding: IDs must identify this profile's RG/VM/disk only.
    vm_pattern = (
        rf"/subscriptions/[0-9a-f-]{{36}}/resourceGroups/{re.escape(spec['rg'])}"
        rf"/providers/Microsoft.Compute/virtualMachines/{re.escape(spec['vm'])}"
    )
    if re.fullmatch(vm_pattern, vm_id, re.I) is None:
        stop("az vm id does not match the selected profile VM identity")
    expected_disk = (
        vm_id.rsplit("/providers/", 1)[0]
        + "/providers/Microsoft.Compute/disks/"
        + spec["disk"]
    )
    if disk_id.lower() != expected_disk.lower():
        stop("az disk id does not match the selected profile data disk identity")

    managed_by = require_str(disk_payload.get("managedBy"), "disk.managedBy")
    if managed_by.lower() != vm_id.lower():
        stop("disk.managedBy does not match vm.id")

    data_disks = data_disks_from_vm(vm_payload)
    lun = lun_for_disk(data_disks, disk_id)
    size_gib = size_gib_from_disk(disk_payload)
    create_option = create_option_from_disk(disk_payload)

    vm_instance_id = require_uuid(vm_payload.get("vmId"), "vm.vmId")
    disk_unique_id = require_uuid(disk_payload.get("uniqueId"), "disk.uniqueId")

    disk_created = normalize_utc(
        require_str(disk_payload.get("timeCreated"), "disk.timeCreated"),
        field="disk.timeCreated",
    )
    vm_created_raw = vm_payload.get("timeCreated")
    if vm_created_raw is None or (isinstance(vm_created_raw, str) and not vm_created_raw.strip()):
        # VM timeCreated is optional in older API shapes; fall back to disk only.
        apply_started = disk_created
        apply_completed = disk_created
    else:
        vm_created = normalize_utc(str(vm_created_raw), field="vm.timeCreated")
        started_dt = min(parse_utc(vm_created), parse_utc(disk_created))
        completed_dt = max(parse_utc(vm_created), parse_utc(disk_created))
        apply_started = started_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        apply_completed = completed_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    clock = now if now is not None else dt.datetime.now(dt.UTC)
    if clock.tzinfo is None:
        stop("Internal clock must be timezone-aware")
    age = clock - parse_utc(apply_started)
    if age < dt.timedelta(0):
        stop("apply_started_utc is in the future relative to now")
    if age > dt.timedelta(hours=24):
        stop(
            "Receipt apply_started_utc is older than 24 hours "
            f"(apply_started_utc={apply_started}); stop and tell the CTO"
        )

    receipt: dict[str, Any] = {
        "version": RECEIPT_VERSION,
        "source": RECEIPT_SOURCE,
        "profile": spec["profile"],
        "unit": spec["unit"],
        "vm_id": vm_id,
        "vm_instance_id": vm_instance_id,
        "disk_id": disk_id,
        "disk_unique_id": disk_unique_id,
        "managed_by_vm_id": managed_by,
        "create_option": create_option,
        "size_gib": size_gib,
        "lun": lun,
        "apply_started_utc": apply_started,
        "disk_created_utc": disk_created,
        "apply_completed_utc": apply_completed,
        "notes": [
            "Built by build_creation_receipt.py from read-only az vm show + az disk show.",
            "apply_started_utc is the earliest ARM timeCreated of the VM and the disk "
            "(explicit proxy for foundation-apply start). apply_completed_utc is the "
            "latest of those timeCreated values (a lower bound on apply end). "
            "disk_created_utc is disk.timeCreated.",
            "Never commit real subscription IDs or secret values.",
        ],
    }

    # Prove against the real bootstrap validator before writing.
    try:
        validate_receipt(
            receipt, vm_id, disk_id, disk_id, clock, profile=spec["profile"]
        )
    except Refused as exc:
        stop(f"Built receipt failed bootstrap_host.validate_receipt: {exc}")
    return receipt


def receipt_bytes(receipt: dict[str, Any]) -> bytes:
    return (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8")


def write_receipt_files(
    receipt: dict[str, Any],
    *,
    receipt_path: Path,
    sha256_path: Path,
    uid: int | None = None,
) -> str:
    """Write receipt + sha256. Root (uid 0) chowns and modes 0600; else print install cmd."""
    raw = receipt_bytes(receipt)
    if len(raw) >= 16384:
        stop("Receipt payload exceeds bootstrap size limit (16384 bytes)")
    digest = hashlib.sha256(raw).hexdigest()

    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    # Restrictive umask during write, then explicit chmod 0600 (do not rely on umask alone).
    previous = os.umask(0o077)
    try:
        receipt_path.write_bytes(raw)
        sha256_path.write_text(digest + "\n", encoding="utf-8")
    finally:
        os.umask(previous)
    os.chmod(receipt_path, 0o600)
    os.chmod(sha256_path, 0o600)

    effective_uid = os.geteuid() if uid is None else uid
    if effective_uid == 0:
        os.chown(receipt_path, 0, 0)
        os.chown(sha256_path, 0, 0)
        meta = os.lstat(receipt_path)
        if not (
            stat.S_ISREG(meta.st_mode)
            and meta.st_uid == 0
            and meta.st_nlink == 1
            and stat.S_IMODE(meta.st_mode) in (0o400, 0o600)
        ):
            stop("Failed to write a private root-owned receipt file")
    return digest


def root_install_commands(*, local_receipt: Path, local_sha256: Path, digest: str) -> str:
    """Exact commands John runs on the prod VM to place the receipt root-owned."""
    remote_receipt = "/etc/cosmabot/creation-receipt.json"
    return "\n".join([
        "NOTE: this workstation is not root; bootstrap_host.py requires a private root-owned receipt on the VM.",
        "Review the local files, copy them to the VM, then as root on the VM run:",
        "  sudo install -d -o root -g root -m 0700 /etc/cosmabot",
        f"  sudo install -o root -g root -m 0600 {local_receipt} {remote_receipt}",
        f"  # reviewed sha256 (also in {local_sha256}): {digest}",
        "Then pass:",
        f"  --creation-receipt {remote_receipt}",
        f"  --creation-receipt-sha256 {digest}",
    ])


def main(argv: list[str] | None = None, *, runner: AzRunner | None = None,
         now: dt.datetime | None = None, uid: int | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        default=PROD_PROFILE,
        choices=sorted(PROFILES),
        help="Host bootstrap profile (binds exact RG/VM/disk names).",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("."),
        help="Directory for creation-receipt.json and creation-receipt.sha256",
    )
    parser.add_argument(
        "--receipt-path",
        type=Path,
        help="Override receipt JSON path (default: <out-dir>/creation-receipt.json)",
    )
    parser.add_argument(
        "--sha256-path",
        type=Path,
        help="Override sha256 path (default: <out-dir>/creation-receipt.sha256)",
    )
    args = parser.parse_args(argv)

    out_dir = args.out_dir
    receipt_path = args.receipt_path or (out_dir / "creation-receipt.json")
    sha256_path = args.sha256_path or (out_dir / "creation-receipt.sha256")

    try:
        receipt = build_receipt(
            profile=args.profile,
            runner=runner or default_az_runner,
            now=now,
        )
        digest = write_receipt_files(
            receipt,
            receipt_path=receipt_path,
            sha256_path=sha256_path,
            uid=uid,
        )
    except (Stop, Refused) as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        return 1
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        return 1

    print(f"PASS: wrote {receipt_path}")
    print(f"PASS: wrote {sha256_path}")
    print(f"sha256={digest}")
    print(f"vm_id={receipt['vm_id']}")
    print(f"disk_id={receipt['disk_id']}")
    print(f"apply_started_utc={receipt['apply_started_utc']}")
    print(f"disk_created_utc={receipt['disk_created_utc']}")
    print(f"apply_completed_utc={receipt['apply_completed_utc']}")
    effective_uid = os.geteuid() if uid is None else uid
    if effective_uid != 0:
        print(root_install_commands(
            local_receipt=receipt_path,
            local_sha256=sha256_path,
            digest=digest,
        ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
