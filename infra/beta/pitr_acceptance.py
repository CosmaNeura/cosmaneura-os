#!/usr/bin/env python3
"""Guarded, resumable PostgreSQL PITR acceptance for the protected D3 runner.

The approved manifest and execution state are private runner files.  Standard
output is always a small, self-hashed record containing no resource IDs,
hostnames, database URLs, credentials, row values, or Box identifiers.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.parse import parse_qs, urlsplit, urlunsplit
from uuid import UUID

UTC = timezone.utc  # noqa: UP017 -- protected runner supports Python 3.10.
ARM_API_VERSION = "2024-08-01"
MANIFEST_CONTRACT = "cosmas-os-d3-pitr-manifest-v1"
STATE_CONTRACT = "cosmas-os-d3-pitr-state-v1"
EVIDENCE_CONTRACT = "cosmas-os-d3-pitr-acceptance-v1"
FINGERPRINT_CONTRACT = "cosmas-os-d3-database-fingerprint-v1"
MANIFEST_LIFETIME = timedelta(hours=24)
MAX_QUIET_WINDOW = timedelta(hours=4)
MIN_QUIET_WINDOW_REMAINING = timedelta(minutes=15)
MAX_PRIVATE_FILE_BYTES = 256 * 1024

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_SHA = re.compile(r"^[0-9a-f]{40}$")
_RELEASE = re.compile(r"^[a-z0-9][a-z0-9-]{2,31}$")
_RESOURCE_GROUP = re.compile(r"^[A-Za-z0-9._()\-]{1,90}$")
_LOCATION = re.compile(r"^[a-z0-9]{2,32}$")
_FQDN = re.compile(r"^[a-z0-9][a-z0-9.-]{1,251}[a-z0-9]$")
_IMAGE = re.compile(r"^[a-z0-9][a-z0-9.-]*/[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$")
_RESTORE_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class PitrError(RuntimeError):
    """A guarded PITR assertion failed; its text is never emitted by main()."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class CommandRunner(Protocol):
    def run(self, argv: Sequence[str]) -> CommandResult: ...


class SubprocessRunner:
    def run(self, argv: Sequence[str]) -> CommandResult:
        completed = subprocess.run(  # noqa: S603 - argv is validated and shell is never used
            list(argv),
            check=False,
            capture_output=True,
            text=True,
            env=os.environ.copy(),
        )
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)


@dataclass(frozen=True)
class Config:
    operation: Literal["manifest", "start", "complete", "cleanup"]
    subscription_id: str
    resource_group: str
    location: str
    source_server_id: str
    source_fqdn: str
    postgres_subnet_id: str
    private_dns_zone_id: str
    source_sha: str
    release_id: str
    api_image_digest: str
    web_image_digest: str
    fingerprint_image: str
    box_id: str
    quiet_window_start_utc: str
    quiet_window_end_utc: str
    write_freeze_evidence_sha256: str
    manifest_path: Path
    state_path: Path | None
    database_url_file: Path | None
    restore_time_utc: str | None
    approved_manifest_sha256: str | None
    poll_attempts: int
    poll_interval_seconds: int

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> Config:
        def required(name: str) -> str:
            value = environment.get(name, "")
            if not value or value != value.strip() or "\x00" in value or "\n" in value:
                raise PitrError("PITR configuration invalid")
            return value

        operation = required("COSMAS_PITR_OPERATION")
        if operation not in {"manifest", "start", "complete", "cleanup"}:
            raise PitrError("PITR configuration invalid")
        subscription_id = required("COSMAS_PITR_SUBSCRIPTION_ID").lower()
        box_id = required("COSMAS_PITR_BOX_ID").lower()
        if not _UUID.fullmatch(subscription_id) or str(UUID(subscription_id)) != subscription_id:
            raise PitrError("PITR configuration invalid")
        if not _UUID.fullmatch(box_id) or str(UUID(box_id)) != box_id:
            raise PitrError("PITR configuration invalid")

        resource_group = required("COSMAS_PITR_RESOURCE_GROUP")
        location = required("COSMAS_PITR_LOCATION").lower()
        source_server_id = required("COSMAS_PITR_SOURCE_SERVER_ID")
        source_fqdn = required("COSMAS_PITR_SOURCE_FQDN").lower()
        postgres_subnet_id = required("COSMAS_PITR_POSTGRES_SUBNET_ID")
        private_dns_zone_id = required("COSMAS_PITR_PRIVATE_DNS_ZONE_ID")
        source_sha = required("COSMAS_PITR_SOURCE_SHA")
        release_id = required("COSMAS_PITR_RELEASE_ID")
        api_image_digest = required("COSMAS_PITR_API_IMAGE_DIGEST")
        web_image_digest = required("COSMAS_PITR_WEB_IMAGE_DIGEST")
        fingerprint_image = required("COSMAS_PITR_FINGERPRINT_IMAGE")
        quiet_window_start = required("COSMAS_PITR_QUIET_WINDOW_START_UTC")
        quiet_window_end = required("COSMAS_PITR_QUIET_WINDOW_END_UTC")
        write_freeze_evidence = required("COSMAS_PITR_WRITE_FREEZE_EVIDENCE_SHA256")
        manifest_path = Path(required("COSMAS_PITR_MANIFEST_PATH"))
        if (
            not _RESOURCE_GROUP.fullmatch(resource_group)
            or not _LOCATION.fullmatch(location)
            or not _FQDN.fullmatch(source_fqdn)
            or not _SOURCE_SHA.fullmatch(source_sha)
            or not _RELEASE.fullmatch(release_id)
            or not _SHA256.fullmatch(api_image_digest)
            or not _SHA256.fullmatch(web_image_digest)
            or not _IMAGE.fullmatch(fingerprint_image)
            or not fingerprint_image.endswith(f"@sha256:{api_image_digest}")
            or not _RESTORE_TIME.fullmatch(quiet_window_start)
            or not _RESTORE_TIME.fullmatch(quiet_window_end)
            or not _SHA256.fullmatch(write_freeze_evidence)
            or not manifest_path.is_absolute()
        ):
            raise PitrError("PITR configuration invalid")
        quiet_start = _parse_timestamp(quiet_window_start)
        quiet_end = _parse_timestamp(quiet_window_end)
        if quiet_start >= quiet_end or quiet_end - quiet_start > MAX_QUIET_WINDOW:
            raise PitrError("PITR configuration invalid")

        source_pattern = re.compile(
            rf"^/subscriptions/{re.escape(subscription_id)}/resourceGroups/"
            rf"{re.escape(resource_group)}/providers/Microsoft\.DBforPostgreSQL/"
            r"flexibleServers/[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$",
            re.IGNORECASE,
        )
        subnet_pattern = re.compile(
            rf"^/subscriptions/{re.escape(subscription_id)}/resourceGroups/"
            rf"{re.escape(resource_group)}/providers/Microsoft\.Network/virtualNetworks/"
            r"[A-Za-z0-9._-]{1,64}/subnets/[A-Za-z0-9._-]{1,80}$",
            re.IGNORECASE,
        )
        dns_pattern = re.compile(
            rf"^/subscriptions/{re.escape(subscription_id)}/resourceGroups/"
            rf"{re.escape(resource_group)}/providers/Microsoft\.Network/privateDnsZones/"
            r"[a-z0-9](?:[a-z0-9.-]{0,241}[a-z0-9])?\.postgres\.database\.azure\.com$",
            re.IGNORECASE,
        )
        if (
            source_pattern.fullmatch(source_server_id) is None
            or subnet_pattern.fullmatch(postgres_subnet_id) is None
            or dns_pattern.fullmatch(private_dns_zone_id) is None
            or source_server_id.rsplit("/", 1)[-1] != source_server_id.rsplit("/", 1)[-1].lower()
            or source_fqdn != f"{source_server_id.rsplit('/', 1)[-1]}.postgres.database.azure.com"
        ):
            raise PitrError("PITR configuration invalid")

        state_path_value = environment.get("COSMAS_PITR_STATE_PATH")
        database_url_value = environment.get("COSMAS_PITR_DATABASE_URL_FILE")
        restore_time = environment.get("COSMAS_PITR_RESTORE_TIME_UTC")
        approval = environment.get("COSMAS_PITR_APPROVED_MANIFEST_SHA256")
        if operation == "manifest":
            if not restore_time or _RESTORE_TIME.fullmatch(restore_time) is None or approval:
                raise PitrError("PITR configuration invalid")
        elif not approval or _SHA256.fullmatch(approval) is None:
            raise PitrError("PITR configuration invalid")
        elif operation in {"start", "complete"} and (
            not state_path_value or not database_url_value
        ):
            raise PitrError("PITR configuration invalid")
        if state_path_value and not Path(state_path_value).is_absolute():
            raise PitrError("PITR configuration invalid")
        if database_url_value and not Path(database_url_value).is_absolute():
            raise PitrError("PITR configuration invalid")

        try:
            poll_attempts = int(environment.get("COSMAS_PITR_POLL_ATTEMPTS", "1"))
            poll_interval = int(environment.get("COSMAS_PITR_POLL_INTERVAL_SECONDS", "0"))
        except ValueError:
            raise PitrError("PITR configuration invalid") from None
        if not 1 <= poll_attempts <= 60 or not 0 <= poll_interval <= 30:
            raise PitrError("PITR configuration invalid")

        return cls(
            operation=operation,  # type: ignore[arg-type]
            subscription_id=subscription_id,
            resource_group=resource_group,
            location=location,
            source_server_id=source_server_id,
            source_fqdn=source_fqdn,
            postgres_subnet_id=postgres_subnet_id,
            private_dns_zone_id=private_dns_zone_id,
            source_sha=source_sha,
            release_id=release_id,
            api_image_digest=api_image_digest,
            web_image_digest=web_image_digest,
            fingerprint_image=fingerprint_image,
            box_id=box_id,
            quiet_window_start_utc=quiet_window_start,
            quiet_window_end_utc=quiet_window_end,
            write_freeze_evidence_sha256=write_freeze_evidence,
            manifest_path=manifest_path,
            state_path=Path(state_path_value) if state_path_value else None,
            database_url_file=Path(database_url_value) if database_url_value else None,
            restore_time_utc=restore_time,
            approved_manifest_sha256=approval,
            poll_attempts=poll_attempts,
            poll_interval_seconds=poll_interval,
        )


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise PitrError("PITR timestamp invalid")
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _now_utc() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _read_utc_clock(clock: Callable[[], datetime]) -> datetime:
    observed = clock()
    if observed.tzinfo is None:
        raise PitrError("PITR timestamp invalid")
    return observed.astimezone(UTC).replace(microsecond=0)


def _parse_timestamp(value: str) -> datetime:
    normalized = re.sub(r"\.\d+Z$", "Z", value)
    if _RESTORE_TIME.fullmatch(normalized) is None:
        raise PitrError("PITR timestamp invalid")
    try:
        return datetime.strptime(normalized, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        raise PitrError("PITR timestamp invalid") from None


def _arm_url(resource_id: str) -> str:
    return f"https://management.azure.com{resource_id}?api-version={ARM_API_VERSION}"


def _not_found(result: CommandResult) -> bool:
    if result.returncode == 0:
        return False
    text = result.stderr.strip()
    if re.match(r"^ERROR: \(ResourceNotFound\)(?:\s|$)", text):
        return True
    # Azure CLI 2.89.1 emits an HTTP 404 as one JSON error suffix rather than a
    # separate status field. Parse that exact shape; never accept a substring in
    # an arbitrary provider/network failure as proof of absence.
    match = re.fullmatch(r"ERROR: Not Found\((\{.*\})\)", text, flags=re.DOTALL)
    if match is None:
        return False
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return False
    error = payload.get("error") if isinstance(payload, dict) else None
    return isinstance(error, dict) and error.get("code") == "ResourceNotFound"


def _az_get(runner: CommandRunner, resource_id: str) -> dict[str, Any] | None:
    result = runner.run(
        [
            "az",
            "rest",
            "--method",
            "get",
            "--url",
            _arm_url(resource_id),
            "--only-show-errors",
            "--output",
            "json",
        ]
    )
    if _not_found(result):
        return None
    if result.returncode != 0:
        raise PitrError("Azure resource read failed")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise PitrError("Azure resource read failed") from None
    if not isinstance(value, dict):
        raise PitrError("Azure resource read failed")
    return value


def _required_path(path: Path, *, maximum_bytes: int = MAX_PRIVATE_FILE_BYTES) -> Path:
    resolved = path.resolve(strict=True)
    info = resolved.stat()
    if (
        path.is_symlink()
        or not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) & 0o077
        or info.st_size <= 0
        or info.st_size > maximum_bytes
    ):
        raise PitrError("protected file invalid")
    return resolved


def _new_path(path: Path) -> Path:
    if not path.is_absolute() or path.exists() or path.is_symlink():
        raise PitrError("protected output path invalid")
    parent = path.parent.resolve(strict=True)
    info = parent.stat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) & 0o077
    ):
        raise PitrError("protected output path invalid")
    return parent / path.name


def _write_new(path: Path, value: dict[str, Any], mode: int) -> None:
    destination = _new_path(path)
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(_canonical_json(value))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def _write_state(path: Path, value: dict[str, Any]) -> None:
    if not path.is_absolute():
        raise PitrError("protected state path invalid")
    parent = path.parent.resolve(strict=True)
    parent_info = parent.stat()
    if parent_info.st_uid != os.geteuid() or stat.S_IMODE(parent_info.st_mode) & 0o077:
        raise PitrError("protected state path invalid")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(_canonical_json(value))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _self_hashed(payload: dict[str, Any], field: str) -> dict[str, Any]:
    return {**payload, field: _sha256_json(payload)}


def _read_self_hashed(path: Path, contract: str, field: str) -> dict[str, Any]:
    source = _required_path(path)
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise PitrError("protected file invalid") from None
    if not isinstance(value, dict) or value.get("contract") != contract:
        raise PitrError("protected file invalid")
    expected = value.get(field)
    payload = {key: item for key, item in value.items() if key != field}
    if not isinstance(expected, str) or not hmac_compare(expected, _sha256_json(payload)):
        raise PitrError("protected file invalid")
    return value


def hmac_compare(left: str, right: str) -> bool:
    import hmac

    return hmac.compare_digest(left, right)


def _source_name(config: Config) -> str:
    return config.source_server_id.rstrip("/").rsplit("/", 1)[-1]


def _target_id(config: Config, target_name: str) -> str:
    return (
        f"/subscriptions/{config.subscription_id}/resourceGroups/{config.resource_group}"
        f"/providers/Microsoft.DBforPostgreSQL/flexibleServers/{target_name}"
    )


def _validate_source(config: Config, value: dict[str, Any]) -> datetime:
    properties = value.get("properties")
    tags = value.get("tags")
    if not isinstance(properties, dict) or not isinstance(tags, dict):
        raise PitrError("source binding invalid")
    network = properties.get("network")
    backup = properties.get("backup")
    if not isinstance(network, dict) or not isinstance(backup, dict):
        raise PitrError("source binding invalid")
    expected_tags = {
        "track": "B",
        "product": "cosmas-os",
        "env": "early_adopter_beta",
        "deployment_mode": "synthetic_lab",
        "data_classification": "synthetic-only",
        "box_scope": "dedicated",
        "box_id": config.box_id,
        "managed": "terraform",
    }
    if (
        str(value.get("id", "")).lower() != config.source_server_id.lower()
        or value.get("name") != _source_name(config)
        or str(value.get("location", "")).lower() != config.location
        or str(properties.get("fullyQualifiedDomainName", "")).lower() != config.source_fqdn
        or str(properties.get("state", "")).lower() != "ready"
        or str(properties.get("version")) != "16"
        or str(network.get("publicNetworkAccess", "")).lower() != "disabled"
        or str(network.get("delegatedSubnetResourceId", "")).lower()
        != config.postgres_subnet_id.lower()
        or str(network.get("privateDnsZoneArmResourceId", "")).lower()
        != config.private_dns_zone_id.lower()
        or any(tags.get(key) != expected for key, expected in expected_tags.items())
    ):
        raise PitrError("source binding invalid")
    earliest = backup.get("earliestRestoreDate")
    if not isinstance(earliest, str):
        raise PitrError("source binding invalid")
    return _parse_timestamp(earliest)


def _manifest_binding(config: Config) -> dict[str, Any]:
    return {
        "subscription_id": config.subscription_id,
        "resource_group": config.resource_group,
        "location": config.location,
        "source_server_id": config.source_server_id,
        "source_fqdn": config.source_fqdn,
        "postgres_subnet_id": config.postgres_subnet_id,
        "private_dns_zone_id": config.private_dns_zone_id,
        "source_sha": config.source_sha,
        "release_id": config.release_id,
        "api_image_digest": config.api_image_digest,
        "web_image_digest": config.web_image_digest,
        "fingerprint_image": config.fingerprint_image,
        "box_id": config.box_id,
        "deployment_mode": "synthetic_lab",
        "data_classification": "synthetic-only",
        "quiet_window_start_utc": config.quiet_window_start_utc,
        "quiet_window_end_utc": config.quiet_window_end_utc,
        "write_freeze_evidence_sha256": config.write_freeze_evidence_sha256,
    }


def _assert_quiet_window(
    config: Config,
    now: datetime,
    *,
    require_remaining: bool,
) -> None:
    start = _parse_timestamp(config.quiet_window_start_utc)
    end = _parse_timestamp(config.quiet_window_end_utc)
    current = now.astimezone(UTC)
    if current < start or current >= end:
        raise PitrError("source quiet window is not active")
    if require_remaining and end - current < MIN_QUIET_WINDOW_REMAINING:
        raise PitrError("source quiet window is too close to expiry")


def _validate_manifest_binding(config: Config, manifest: dict[str, Any]) -> None:
    binding = manifest.get("binding")
    restore = manifest.get("restore")
    if binding != _manifest_binding(config) or not isinstance(restore, dict):
        raise PitrError("approved manifest binding invalid")
    target_name = restore.get("target_name")
    target_prefix = f"pitr-{_source_name(config)[:38].rstrip('-')}-"
    if (
        not isinstance(target_name, str)
        or not re.fullmatch(r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$", target_name)
        or not target_name.startswith(target_prefix)
        or re.fullmatch(r"[0-9a-f]{12}", target_name.removeprefix(target_prefix)) is None
        or restore.get("target_resource_id") != _target_id(config, target_name)
        or str(restore.get("target_resource_id", "")).lower() == config.source_server_id.lower()
        or restore.get("delete_target_after_verification") is not True
        or not isinstance(restore.get("point_in_time_utc"), str)
    ):
        raise PitrError("approved manifest binding invalid")
    restore_time = _parse_timestamp(str(restore["point_in_time_utc"]))
    if not (
        _parse_timestamp(config.quiet_window_start_utc)
        <= restore_time
        <= _parse_timestamp(config.quiet_window_end_utc)
    ):
        raise PitrError("approved manifest binding invalid")


def _read_approved_manifest(
    config: Config, now: datetime, *, require_unexpired: bool
) -> dict[str, Any]:
    manifest = _read_self_hashed(config.manifest_path, MANIFEST_CONTRACT, "manifest_sha256")
    _validate_manifest_binding(config, manifest)
    manifest_hash = manifest["manifest_sha256"]
    if not isinstance(manifest_hash, str) or not hmac_compare(
        manifest_hash, config.approved_manifest_sha256 or ""
    ):
        raise PitrError("approved manifest hash mismatch")
    created_at = _parse_timestamp(str(manifest.get("created_at", "")))
    expires_at = _parse_timestamp(str(manifest.get("expires_at", "")))
    current = now.astimezone(UTC)
    if (
        expires_at - created_at != MANIFEST_LIFETIME
        or current < created_at
        or (require_unexpired and current >= expires_at)
    ):
        raise PitrError("approved manifest expired")
    return manifest


def _evidence(operation: str, status: str, now: datetime, **values: Any) -> dict[str, Any]:
    payload = {
        "schema_version": 1,
        "contract": EVIDENCE_CONTRACT,
        "operation": operation,
        "status": status,
        "completed_at": _timestamp(now),
        **values,
    }
    return _self_hashed(payload, "evidence_sha256")


def create_manifest(
    config: Config,
    runner: CommandRunner,
    *,
    now: datetime,
    nonce: str | None = None,
) -> dict[str, Any]:
    source = _az_get(runner, config.source_server_id)
    if source is None:
        raise PitrError("source server missing")
    earliest = _validate_source(config, source)
    if config.restore_time_utc is None:
        raise PitrError("restore timestamp missing")
    restore_time = _parse_timestamp(config.restore_time_utc)
    quiet_start = _parse_timestamp(config.quiet_window_start_utc)
    quiet_end = _parse_timestamp(config.quiet_window_end_utc)
    if (
        restore_time < earliest
        or restore_time > now.astimezone(UTC) - timedelta(minutes=5)
        or restore_time < quiet_start
        or restore_time > quiet_end
    ):
        raise PitrError("restore timestamp outside exact restorable interval")
    _assert_quiet_window(config, now, require_remaining=True)
    target_nonce = nonce or secrets.token_hex(6)
    if re.fullmatch(r"[0-9a-f]{12}", target_nonce) is None:
        raise PitrError("target nonce invalid")
    target_name = f"pitr-{_source_name(config)[:38].rstrip('-')}-{target_nonce}"
    target_id = _target_id(config, target_name)
    if _az_get(runner, target_id) is not None:
        raise PitrError("restore target already exists")

    payload = {
        "schema_version": 1,
        "contract": MANIFEST_CONTRACT,
        "created_at": _timestamp(now),
        "expires_at": _timestamp(now + MANIFEST_LIFETIME),
        "binding": _manifest_binding(config),
        "source": {
            "version": "16",
            "earliest_restore_utc": _timestamp(earliest),
            "live_binding_verified": True,
        },
        "restore": {
            "point_in_time_utc": _timestamp(restore_time),
            "target_name": target_name,
            "target_resource_id": target_id,
            "delete_target_after_verification": True,
        },
    }
    manifest = _self_hashed(payload, "manifest_sha256")
    _write_new(config.manifest_path, manifest, 0o400)
    return _evidence(
        "manifest",
        "ready_for_owner_approval",
        now,
        manifest_sha256=manifest["manifest_sha256"],
        source_binding_verified=True,
        restore_timestamp_valid=True,
        source_quiet_window_bound=True,
        same_region_private_restore=True,
        target_absence_verified=True,
        boundary_sha256=_sha256_json(_manifest_binding(config)),
    )


def _read_database_url(config: Config, target_fqdn: str | None = None) -> str:
    if config.database_url_file is None:
        raise PitrError("database URL file missing")
    source = _required_path(config.database_url_file, maximum_bytes=8_192)
    try:
        value = source.read_text(encoding="utf-8").strip()
    except UnicodeDecodeError:
        raise PitrError("database URL invalid") from None
    if not value or "\n" in value or "\r" in value or "\x00" in value:
        raise PitrError("database URL invalid")
    parsed = urlsplit(value)
    query = parse_qs(parsed.query, keep_blank_values=True)
    if (
        parsed.scheme != "postgresql+psycopg"
        or (parsed.hostname or "").lower() != config.source_fqdn
        or parsed.port != 5432
        or parsed.path != "/cosmas_os"
        or parsed.fragment
        or not parsed.username
        or parsed.password is None
        or set(query) != {"sslmode", "sslrootcert"}
        or query.get("sslmode") != ["verify-full"]
        or query.get("sslrootcert") != ["system"]
    ):
        raise PitrError("database URL invalid")
    if target_fqdn is None:
        return value
    if _FQDN.fullmatch(target_fqdn) is None:
        raise PitrError("restore hostname invalid")
    user_info, separator, _ = parsed.netloc.rpartition("@")
    if separator != "@" or not user_info:
        raise PitrError("database URL invalid")
    return urlunsplit(
        (parsed.scheme, f"{user_info}@{target_fqdn}:5432", parsed.path, parsed.query, "")
    )


def _hardened_docker_prefix(config: Config) -> list[str]:
    return [
        "docker",
        "run",
        "--rm",
        "--pull",
        "never",
        "--network",
        "bridge",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "128",
        "--memory",
        "256m",
        "--cpus",
        "1",
        "--user",
        "10001:10001",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=16m",
    ]


def _verify_docker_platform_isolation(config: Config, runner: CommandRunner) -> None:
    """Prove the runner's Docker firewall still blocks Azure platform credentials."""

    for destination in ("169.254.169.254/32", "168.63.129.16/32"):
        result = runner.run(["iptables", "-C", "DOCKER-USER", "-d", destination, "-j", "REJECT"])
        if result.returncode != 0:
            raise PitrError("container platform isolation is not active")
    probe = (
        "import socket\n"
        "reachable=[]\n"
        "for endpoint in (('169.254.169.254',80),('168.63.129.16',80),"
        "('168.63.129.16',32526)):\n"
        " try:\n"
        "  connection=socket.create_connection(endpoint,3)\n"
        " except OSError:\n"
        "  continue\n"
        " connection.close()\n"
        " reachable.append(endpoint)\n"
        "raise SystemExit(1) if reachable else print('isolated')\n"
    )
    result = runner.run(
        [
            *_hardened_docker_prefix(config),
            config.fingerprint_image,
            "python",
            "-c",
            probe,
        ]
    )
    if result.returncode != 0 or result.stdout != "isolated\n":
        raise PitrError("container platform isolation probe failed")


def _fingerprint(config: Config, runner: CommandRunner, database_url: str) -> dict[str, Any]:
    if config.state_path is None:
        raise PitrError("state path missing")
    _verify_docker_platform_isolation(config, runner)
    state_parent = config.state_path.parent.resolve(strict=True)
    descriptor, env_name = tempfile.mkstemp(prefix=".pitr-db-env.", dir=state_parent)
    env_path = Path(env_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write("COSMAS_ENV=early_adopter_beta\n")
            handle.write("DATA_MODE=synthetic\n")
            handle.write(f"DATABASE_URL={database_url}\n")
        result = runner.run(
            [
                *_hardened_docker_prefix(config),
                "--env-file",
                str(env_path),
                config.fingerprint_image,
                "python",
                "-m",
                "cosmas_os.cli",
                "fingerprint-beta-database",
                "--confirm-synthetic-only",
                "--confirm-read-only",
            ]
        )
    finally:
        env_path.unlink(missing_ok=True)
    if result.returncode != 0 or len(result.stdout.encode()) > 128 * 1024:
        raise PitrError("database fingerprint failed")
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise PitrError("database fingerprint failed")
    try:
        fingerprint = json.loads(lines[0])
    except json.JSONDecodeError:
        raise PitrError("database fingerprint failed") from None
    required_keys = {
        "contract",
        "status",
        "schema_revision",
        "schema_at_expected_head",
        "structures",
        "aggregate_sha256",
        "evidence_sha256",
    }
    if (
        not isinstance(fingerprint, dict)
        or set(fingerprint) != required_keys
        or fingerprint.get("contract") != FINGERPRINT_CONTRACT
        or fingerprint.get("status") != "ready"
        or fingerprint.get("schema_at_expected_head") is not True
        or not isinstance(fingerprint.get("structures"), dict)
        or not isinstance(fingerprint.get("aggregate_sha256"), str)
        or _SHA256.fullmatch(str(fingerprint.get("aggregate_sha256"))) is None
    ):
        raise PitrError("database fingerprint failed")
    evidence_hash = fingerprint.pop("evidence_sha256", None)
    if not isinstance(evidence_hash, str) or not hmac_compare(
        evidence_hash, _sha256_json(fingerprint)
    ):
        raise PitrError("database fingerprint failed")
    fingerprint["evidence_sha256"] = evidence_hash
    return fingerprint


def _restore_tags(config: Config, manifest_hash: str) -> dict[str, str]:
    return {
        "track": "B",
        "product": "cosmas-os",
        "env": "early_adopter_beta",
        "deployment_mode": "synthetic_lab",
        "data_classification": "synthetic-only",
        "box_scope": "dedicated",
        "box_id": config.box_id,
        "managed": "pitr-acceptance",
        "pitr_manifest_sha256": manifest_hash,
        "pitr_source_id_sha256": hashlib.sha256(
            config.source_server_id.lower().encode()
        ).hexdigest(),
    }


def _restore_request(config: Config, manifest: dict[str, Any]) -> dict[str, Any]:
    restore = manifest["restore"]
    return {
        "location": config.location,
        "tags": _restore_tags(config, str(manifest["manifest_sha256"])),
        "properties": {
            "createMode": "PointInTimeRestore",
            "sourceServerResourceId": config.source_server_id,
            "pointInTimeUTC": restore["point_in_time_utc"],
            "network": {
                "delegatedSubnetResourceId": config.postgres_subnet_id,
                "privateDnsZoneArmResourceId": config.private_dns_zone_id,
                "publicNetworkAccess": "Disabled",
            },
        },
    }


def _initial_state(manifest: dict[str, Any], fingerprint: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "schema_version": 1,
        "contract": STATE_CONTRACT,
        "manifest_sha256": manifest["manifest_sha256"],
        "phase": "f1_captured",
        "f1": fingerprint,
        "restore_request_sha256": None,
        "restore_started_at_utc": None,
        "restore_ready_at_utc": None,
    }
    return _self_hashed(payload, "state_sha256")


def _read_state(config: Config, manifest: dict[str, Any]) -> dict[str, Any] | None:
    if config.state_path is None or not config.state_path.exists():
        return None
    state = _read_self_hashed(config.state_path, STATE_CONTRACT, "state_sha256")
    if state.get("manifest_sha256") != manifest.get("manifest_sha256"):
        raise PitrError("PITR state binding invalid")
    return state


def _save_state(config: Config, state: dict[str, Any]) -> None:
    if config.state_path is None:
        raise PitrError("state path missing")
    payload = {key: value for key, value in state.items() if key != "state_sha256"}
    _write_state(config.state_path, _self_hashed(payload, "state_sha256"))


def _put_restore(
    runner: CommandRunner, target_id: str, request: dict[str, Any], parent: Path
) -> None:
    descriptor, request_name = tempfile.mkstemp(prefix=".pitr-request.", suffix=".json", dir=parent)
    request_path = Path(request_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(_canonical_json(request))
        result = runner.run(
            [
                "az",
                "rest",
                "--method",
                "put",
                "--url",
                _arm_url(target_id),
                "--body",
                f"@{request_path}",
                "--only-show-errors",
                "--output",
                "none",
            ]
        )
    finally:
        request_path.unlink(missing_ok=True)
    if result.returncode != 0:
        raise PitrError("restore create failed")


def _measurement(
    config: Config,
    manifest: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any]:
    started = _parse_timestamp(str(state.get("restore_started_at_utc", "")))
    ready = _parse_timestamp(str(state.get("restore_ready_at_utc", "")))
    freeze = _parse_timestamp(config.quiet_window_start_utc)
    restore_point = _parse_timestamp(str(manifest["restore"]["point_in_time_utc"]))
    if ready < started or restore_point < freeze:
        raise PitrError("PITR measurement timestamps invalid")
    measured_rto = int((ready - started).total_seconds())
    measured_rpo = max(0, int((freeze - restore_point).total_seconds()))
    return {
        "restore_started_at_utc": _timestamp(started),
        "restore_ready_at_utc": _timestamp(ready),
        "write_freeze_at_utc": _timestamp(freeze),
        "restore_point_utc": _timestamp(restore_point),
        "measured_rto_seconds": measured_rto,
        "measured_rpo_seconds": measured_rpo,
    }


def start_restore(config: Config, runner: CommandRunner, *, now: datetime) -> dict[str, Any]:
    manifest = _read_approved_manifest(config, now, require_unexpired=True)
    _assert_quiet_window(config, now, require_remaining=True)
    source = _az_get(runner, config.source_server_id)
    if source is None:
        raise PitrError("source server missing")
    _validate_source(config, source)
    target_id = str(manifest["restore"]["target_resource_id"])
    state = _read_state(config, manifest)
    if state is None:
        if _az_get(runner, target_id) is not None:
            raise PitrError("unbound restore target exists")
        fingerprint = _fingerprint(config, runner, _read_database_url(config))
        state = _initial_state(manifest, fingerprint)
        _save_state(config, state)
        state = _read_state(config, manifest)
        assert state is not None
    if state.get("phase") not in {"f1_captured", "restore_started"}:
        raise PitrError("restore start phase invalid")

    request = _restore_request(config, manifest)
    request_sha = _sha256_json(request)
    target = _az_get(runner, target_id)
    if state.get("restore_started_at_utc") is None:
        if state["phase"] != "f1_captured" or target is not None:
            raise PitrError("restore start timestamp missing")
        state["restore_started_at_utc"] = _timestamp(now)
        _save_state(config, state)
        state = _read_state(config, manifest)
        assert state is not None
    else:
        started_at = _parse_timestamp(str(state["restore_started_at_utc"]))
        if started_at > now.astimezone(UTC):
            raise PitrError("restore start timestamp invalid")
    if target is None:
        if state.get("phase") != "f1_captured":
            raise PitrError("started restore target disappeared")
        assert config.state_path is not None
        _put_restore(runner, target_id, request, config.state_path.parent.resolve(strict=True))
    else:
        _validate_target(config, manifest, target, phase="provisioning")
    state["phase"] = "restore_started"
    state["restore_request_sha256"] = request_sha
    _save_state(config, state)
    return _evidence(
        "start",
        "restore_started",
        now,
        manifest_sha256=manifest["manifest_sha256"],
        approved_manifest_hash_matched=True,
        source_binding_verified=True,
        f1_sha256=_sha256_json(state["f1"]),
        restore_request_sha256=request_sha,
        target_resource_id_sha256=hashlib.sha256(target_id.lower().encode()).hexdigest(),
    )


def _validate_target(
    config: Config,
    manifest: dict[str, Any],
    target: dict[str, Any],
    *,
    phase: Literal["provisioning", "ready", "cleanup"],
) -> str:
    restore = manifest["restore"]
    properties = target.get("properties")
    tags = target.get("tags")
    if not isinstance(properties, dict) or not isinstance(tags, dict):
        raise PitrError("restore target binding invalid")
    network = properties.get("network")
    if not isinstance(network, dict):
        raise PitrError("restore target binding invalid")
    state = str(properties.get("state", ""))
    valid_states = {
        "provisioning": {"Ready", "Creating", "Provisioning", "Updating"},
        "ready": {"Ready"},
        "cleanup": {
            "Ready",
            "Creating",
            "Provisioning",
            "Updating",
            "Dropping",
            "Disabled",
            "Starting",
            "Stopping",
            "Stopped",
            "Restarting",
            "Inaccessible",
            "Failed",
        },
    }[phase]
    fqdn = str(properties.get("fullyQualifiedDomainName", "")).lower()
    expected_fqdn = f"{restore['target_name']}.postgres.database.azure.com"
    if (
        str(target.get("id", "")).lower() != str(restore["target_resource_id"]).lower()
        or str(target.get("id", "")).lower() == config.source_server_id.lower()
        or target.get("name") != restore["target_name"]
        or str(target.get("location", "")).lower() != config.location
        or state not in valid_states
        or str(properties.get("version")) != "16"
        or str(network.get("publicNetworkAccess", "")).lower() != "disabled"
        or str(network.get("delegatedSubnetResourceId", "")).lower()
        != config.postgres_subnet_id.lower()
        or str(network.get("privateDnsZoneArmResourceId", "")).lower()
        != config.private_dns_zone_id.lower()
        or tags != _restore_tags(config, str(manifest["manifest_sha256"]))
        or (fqdn and fqdn != expected_fqdn)
        or (state == "Ready" and not fqdn)
    ):
        raise PitrError("restore target binding invalid")
    return fqdn


def _delete_target(runner: CommandRunner, target_id: str) -> None:
    result = runner.run(
        [
            "az",
            "rest",
            "--method",
            "delete",
            "--url",
            _arm_url(target_id),
            "--only-show-errors",
            "--output",
            "none",
        ]
    )
    if result.returncode != 0 and not _not_found(result):
        raise PitrError("restore target deletion failed")


def _poll_target(
    config: Config,
    runner: CommandRunner,
    target_id: str,
    *,
    want_absent: bool,
    sleeper: Callable[[float], None],
) -> dict[str, Any] | None:
    target: dict[str, Any] | None = None
    for attempt in range(config.poll_attempts):
        target = _az_get(runner, target_id)
        if want_absent == (target is None):
            return target
        if attempt + 1 < config.poll_attempts and config.poll_interval_seconds:
            sleeper(config.poll_interval_seconds)
    return target


def _poll_ready_target(
    config: Config,
    manifest: dict[str, Any],
    runner: CommandRunner,
    target_id: str,
    *,
    sleeper: Callable[[float], None],
) -> dict[str, Any] | None:
    target: dict[str, Any] | None = None
    for attempt in range(config.poll_attempts):
        target = _az_get(runner, target_id)
        if target is not None:
            state = str(target.get("properties", {}).get("state", ""))
            _validate_target(
                config,
                manifest,
                target,
                phase="ready" if state == "Ready" else "provisioning",
            )
            if state == "Ready":
                return target
        if attempt + 1 < config.poll_attempts and config.poll_interval_seconds:
            sleeper(config.poll_interval_seconds)
    return target


def complete_restore(
    config: Config,
    runner: CommandRunner,
    *,
    now: datetime,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], datetime] = _now_utc,
) -> tuple[dict[str, Any], int]:
    manifest = _read_approved_manifest(config, now, require_unexpired=False)
    _assert_quiet_window(config, now, require_remaining=False)
    state = _read_state(config, manifest)
    if state is None or state.get("phase") not in {
        "restore_started",
        "fingerprints_captured",
        "delete_started",
        "target_deleted",
    }:
        raise PitrError("restore completion phase invalid")
    source = _az_get(runner, config.source_server_id)
    if source is None:
        raise PitrError("source server missing")
    _validate_source(config, source)
    target_id = str(manifest["restore"]["target_resource_id"])

    if state["phase"] == "restore_started":
        target = _poll_ready_target(
            config,
            manifest,
            runner,
            target_id,
            sleeper=sleeper,
        )
        if target is None:
            raise PitrError("restore target disappeared")
        if str(target.get("properties", {}).get("state", "")) != "Ready":
            _validate_target(config, manifest, target, phase="provisioning")
            return (
                _evidence(
                    "complete",
                    "restore_pending",
                    now,
                    manifest_sha256=manifest["manifest_sha256"],
                    approved_manifest_hash_matched=True,
                    target_resource_id_sha256=hashlib.sha256(
                        target_id.lower().encode()
                    ).hexdigest(),
                ),
                2,
            )
        target_fqdn = _validate_target(config, manifest, target, phase="ready")
        ready_observed_at = _read_utc_clock(clock)
        started_at = _parse_timestamp(str(state.get("restore_started_at_utc", "")))
        if ready_observed_at < now.astimezone(UTC) or ready_observed_at < started_at:
            raise PitrError("restore ready timestamp invalid")
        if state.get("restore_ready_at_utc") is None:
            state["restore_ready_at_utc"] = _timestamp(ready_observed_at)
            _save_state(config, state)
            state = _read_state(config, manifest)
            assert state is not None
        else:
            ready_at = _parse_timestamp(str(state["restore_ready_at_utc"]))
            if ready_at > ready_observed_at:
                raise PitrError("restore ready timestamp invalid")
        state["f2"] = _fingerprint(
            config,
            runner,
            _read_database_url(config, target_fqdn=target_fqdn),
        )
        source = _az_get(runner, config.source_server_id)
        if source is None:
            raise PitrError("source server missing")
        _validate_source(config, source)
        state["f3"] = _fingerprint(config, runner, _read_database_url(config))
        state["fingerprints_match"] = state["f1"] == state["f2"] == state["f3"]
        state["phase"] = "fingerprints_captured"
        _save_state(config, state)

    if state["phase"] == "fingerprints_captured":
        target = _az_get(runner, target_id)
        if target is None:
            raise PitrError("restore target disappeared before guarded deletion")
        _validate_target(config, manifest, target, phase="ready")
        state["phase"] = "delete_started"
        _save_state(config, state)

    if state["phase"] == "delete_started":
        target = _az_get(runner, target_id)
        if target is not None:
            _validate_target(config, manifest, target, phase="cleanup")
            if str(target.get("properties", {}).get("state", "")) != "Dropping":
                _delete_target(runner, target_id)
        remaining = _poll_target(
            config,
            runner,
            target_id,
            want_absent=True,
            sleeper=sleeper,
        )
        if remaining is not None:
            _validate_target(config, manifest, remaining, phase="cleanup")
            return (
                _evidence(
                    "complete",
                    "cleanup_pending",
                    now,
                    manifest_sha256=manifest["manifest_sha256"],
                    approved_manifest_hash_matched=True,
                    exact_target_delete_started=True,
                    target_resource_id_sha256=hashlib.sha256(
                        target_id.lower().encode()
                    ).hexdigest(),
                ),
                2,
            )
        state["phase"] = "target_deleted"
        _save_state(config, state)

    source = _az_get(runner, config.source_server_id)
    if source is None:
        raise PitrError("source server missing")
    _validate_source(config, source)
    f4 = _fingerprint(config, runner, _read_database_url(config))
    f123_equal = state.get("fingerprints_match") is True
    f4_equal = state.get("f1") == f4
    state["f4"] = f4
    state["phase"] = "complete"
    state["f4_matches_f1"] = f4_equal
    _save_state(config, state)
    verified = f123_equal and f4_equal
    measurement = _measurement(config, manifest, state)
    return (
        _evidence(
            "complete",
            "verified" if verified else "failed",
            now,
            manifest_sha256=manifest["manifest_sha256"],
            approved_manifest_hash_matched=True,
            exact_target_binding_verified=True,
            f1_f2_f3_equal=f123_equal,
            exact_target_deleted=True,
            target_absence_404_verified=True,
            f4_equals_f1=f4_equal,
            measurement=measurement,
        ),
        0 if verified else 1,
    )


def cleanup_restore(
    config: Config,
    runner: CommandRunner,
    *,
    now: datetime,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    manifest = _read_approved_manifest(config, now, require_unexpired=False)
    target_id = str(manifest["restore"]["target_resource_id"])
    target = _az_get(runner, target_id)
    if target is not None:
        _validate_target(config, manifest, target, phase="cleanup")
        if str(target.get("properties", {}).get("state", "")) != "Dropping":
            _delete_target(runner, target_id)
    remaining = _poll_target(
        config,
        runner,
        target_id,
        want_absent=True,
        sleeper=sleeper,
    )
    if remaining is not None:
        _validate_target(config, manifest, remaining, phase="cleanup")
        return _evidence(
            "cleanup",
            "cleanup_pending",
            now,
            manifest_sha256=manifest["manifest_sha256"],
            approved_manifest_hash_matched=True,
            exact_target_delete_started=True,
        )
    return _evidence(
        "cleanup",
        "cleaned",
        now,
        manifest_sha256=manifest["manifest_sha256"],
        approved_manifest_hash_matched=True,
        exact_target_deleted=True,
        target_absence_404_verified=True,
    )


def _run(config: Config, runner: CommandRunner, now: datetime) -> tuple[dict[str, Any], int]:
    if config.operation == "manifest":
        return create_manifest(config, runner, now=now), 0
    if config.operation == "start":
        return start_restore(config, runner, now=now), 0
    if config.operation == "complete":
        return complete_restore(config, runner, now=now)
    evidence = cleanup_restore(config, runner, now=now)
    return evidence, 2 if evidence.get("status") == "cleanup_pending" else 0


def main() -> int:
    operation = os.environ.get("COSMAS_PITR_OPERATION", "unknown")
    now = _now_utc()
    try:
        if os.geteuid() != 0:
            raise PitrError("protected runner root required")
        config = Config.from_environment(os.environ)
        evidence, status = _run(config, SubprocessRunner(), now)
    except Exception:  # noqa: BLE001 - never emit provider, path, identifier, or secret details
        evidence = _evidence(
            operation if operation in {"manifest", "start", "complete", "cleanup"} else "unknown",
            "failed",
            now,
        )
        status = 1
    print(_canonical_json(evidence))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
