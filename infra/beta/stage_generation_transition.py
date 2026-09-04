#!/usr/bin/env python3
"""Fail-closed, append-only recovery for immutable D3 stage generations.

The protected runner keeps every superseded stage directory. A replacement
tfvars file is installed only when an exact, short-lived owner authorization
binds both the current artifact hashes and the replacement bytes.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import stat
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

UTC = timezone.utc  # noqa: UP017 -- protected runner supports Python 3.10.
CONTRACT = "cosmas-os-d3-stage-generation-approval-v1"
EVIDENCE_TYPE = "protected-runner-stage-generation-transition"
CONFIRMATION = "AUTHORIZE D3 IMMUTABLE STAGE GENERATION TRANSITION"
MAX_PAYLOAD_BYTES = 128 * 1024
MAX_JSON_BYTES = 64 * 1024

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_SHA = re.compile(r"^[0-9a-f]{40}$")
_RELEASE = re.compile(r"^[a-z0-9][a-z0-9-]{2,31}$")
_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/ -]{2,511}$")
_HOSTNAME = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)

ARTIFACT_FILES = {
    "environment_tfvars_sha256": "environment.tfvars.json",
    "plan_sha256": "plan.tfplan",
    "review_sha256": "review.json",
    "approval_sha256": "approval.json",
    "result_sha256": "result.json",
}


class StageTransitionError(RuntimeError):
    """The immutable stage generation transition failed closed."""


@dataclass(frozen=True)
class Config:
    action: Literal["inspect", "transition"]
    source_sha: str
    release_id: str
    stage: Literal["foundation", "database", "workloads"]
    release_root: Path
    stage_root: Path
    payload_path: Path

    @classmethod
    def from_argv(cls, argv: list[str]) -> Config:
        if len(argv) != 7:
            raise StageTransitionError("stage transition invocation invalid")
        action, source_sha, release_id, stage = argv[1:5]
        release_root = Path(argv[5])
        payload_path = Path(argv[6])
        if (
            action not in {"inspect", "transition"}
            or not _SOURCE_SHA.fullmatch(source_sha)
            or not _RELEASE.fullmatch(release_id)
            or stage not in {"foundation", "database", "workloads"}
            or not release_root.is_absolute()
            or not payload_path.is_absolute()
        ):
            raise StageTransitionError("stage transition invocation invalid")
        return cls(
            action=action,  # type: ignore[arg-type]
            source_sha=source_sha,
            release_id=release_id,
            stage=stage,  # type: ignore[arg-type]
            release_root=release_root,
            stage_root=release_root / "stages" / stage,
            payload_path=payload_path,
        )


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: Any) -> str:
    return _sha256_bytes(_canonical_json(value).encode())


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise StageTransitionError("stage transition timestamp invalid")
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_timestamp(value: Any) -> datetime:
    if (
        not isinstance(value, str)
        or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", value) is None
    ):
        raise StageTransitionError("stage authorization timestamp invalid")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        raise StageTransitionError("stage authorization timestamp invalid") from None
    return parsed


def _load_json(path: Path, *, maximum: int = MAX_JSON_BYTES) -> Any:
    try:
        raw = path.read_bytes()
    except OSError:
        raise StageTransitionError("stage transition input unavailable") from None
    if not 0 < len(raw) <= maximum:
        raise StageTransitionError("stage transition input size invalid")
    try:
        return json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise StageTransitionError("stage transition JSON invalid") from None


def _safe_private_file(path: Path, *, required: bool, allow_empty: bool = False) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        if required:
            raise StageTransitionError(f"required stage artifact missing: {path.name}") from None
        return False
    if (
        path.is_symlink()
        or not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) & 0o077
        or (info.st_size <= 0 and not allow_empty)
    ):
        raise StageTransitionError(f"stage artifact is unsafe: {path.name}")
    return True


def _safe_private_directory(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        raise StageTransitionError("current stage generation is unavailable") from None
    if (
        path.is_symlink()
        or not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) & 0o077
    ):
        raise StageTransitionError("current stage generation is unsafe")


def _artifact_inventory(stage_root: Path) -> dict[str, str | None]:
    inventory: dict[str, str | None] = {}
    for key, name in ARTIFACT_FILES.items():
        path = stage_root / name
        present = _safe_private_file(
            path,
            required=key == "environment_tfvars_sha256",
            allow_empty=key != "environment_tfvars_sha256",
        )
        inventory[key] = _sha256_file(path) if present else None
    return inventory


def _successful_result_present(stage_root: Path, inventory: dict[str, str | None]) -> bool:
    if inventory["result_sha256"] is None:
        return False
    if any(inventory[key] is None for key in ("plan_sha256", "review_sha256", "approval_sha256")):
        return False
    try:
        review = _load_json(stage_root / "review.json")
        result = _load_json(stage_root / "result.json")
    except StageTransitionError:
        return False
    return bool(
        isinstance(review, dict)
        and isinstance(result, dict)
        and result.get("schema_version") == 1
        and review.get("plan_sha256") == inventory["plan_sha256"]
        and result.get("plan_sha256") == review.get("plan_sha256")
    )


def _decode_replacement(value: Any) -> bytes:
    if not isinstance(value, str) or not value or len(value) > MAX_PAYLOAD_BYTES:
        raise StageTransitionError("replacement tfvars encoding invalid")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise StageTransitionError("replacement tfvars encoding invalid") from None
    if not 0 < len(decoded) <= MAX_JSON_BYTES:
        raise StageTransitionError("replacement tfvars size invalid")
    try:
        parsed = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise StageTransitionError("replacement tfvars JSON invalid") from None
    if not isinstance(parsed, dict):
        raise StageTransitionError("replacement tfvars must be a JSON object")
    return decoded


def _validate_approval(
    config: Config,
    payload: Any,
    replacement: bytes,
) -> tuple[str, dict[str, Any], datetime]:
    if not isinstance(payload, dict) or set(payload) != {
        "owner_approval",
        "replacement_tfvars_base64",
        "transition_mode",
    }:
        raise StageTransitionError("stage transition payload invalid")
    mode = payload.get("transition_mode")
    if mode not in {"abandoned_retry", "planned_workloads_progression"}:
        raise StageTransitionError("stage transition mode invalid")
    approval = payload.get("owner_approval")
    expected_keys = {
        "approved_at",
        "confirmation",
        "contract",
        "current_artifacts",
        "reason_reference",
        "release_id",
        "replacement_tfvars_sha256",
        "reviewer_reference",
        "schema_version",
        "source_sha",
        "stage",
        "transition_mode",
    }
    if not isinstance(approval, dict) or set(approval) != expected_keys:
        raise StageTransitionError("stage owner authorization invalid")
    if (
        approval.get("schema_version") != 1
        or approval.get("contract") != CONTRACT
        or approval.get("confirmation") != CONFIRMATION
        or approval.get("source_sha") != config.source_sha
        or approval.get("release_id") != config.release_id
        or approval.get("stage") != config.stage
        or approval.get("transition_mode") != mode
        or approval.get("replacement_tfvars_sha256") != _sha256_bytes(replacement)
    ):
        raise StageTransitionError("stage owner authorization binding invalid")
    for key in ("reviewer_reference", "reason_reference"):
        reference = approval.get(key)
        if (
            not isinstance(reference, str)
            or not _REFERENCE.fullmatch(reference)
            or "@" in reference
        ):
            raise StageTransitionError("stage owner authorization reference invalid")
    approved_at = _parse_timestamp(approval.get("approved_at"))
    current = approval.get("current_artifacts")
    if not isinstance(current, dict) or set(current) != set(ARTIFACT_FILES):
        raise StageTransitionError("stage owner authorization artifact inventory invalid")
    for key, value in current.items():
        if key == "environment_tfvars_sha256":
            if not isinstance(value, str) or not _SHA256.fullmatch(value):
                raise StageTransitionError("stage owner authorization artifact hash invalid")
        elif value is not None and (not isinstance(value, str) or not _SHA256.fullmatch(value)):
            raise StageTransitionError("stage owner authorization artifact hash invalid")
    if mode == "planned_workloads_progression" and config.stage != "workloads":
        raise StageTransitionError("planned progression is limited to the workloads stage")
    return mode, approval, approved_at


def _validate_planned_workload_progression(current: bytes, replacement: bytes) -> None:
    old = json.loads(current)
    new = json.loads(replacement)
    custom_domain = old.get("web_custom_domain")
    if (
        old.get("deploy_workloads") is not True
        or new.get("deploy_workloads") is not True
        or old.get("web_custom_domain_dns_ready") is not False
        or new.get("web_custom_domain_dns_ready") is not True
        or not isinstance(custom_domain, str)
        or not _HOSTNAME.fullmatch(custom_domain)
        or new.get("web_custom_domain") != custom_domain
        or old.get("web_origin") != f"https://{custom_domain}"
        or new.get("web_origin") != f"https://{custom_domain}"
        or not isinstance(old.get("runner_live_network_evidence_reference"), str)
        or not isinstance(new.get("runner_live_network_evidence_reference"), str)
        or old.get("runner_live_network_evidence_reference")
        == new.get("runner_live_network_evidence_reference")
    ):
        raise StageTransitionError(
            "planned workloads progression is outside the DNS-ready boundary"
        )
    ignored = {"web_custom_domain_dns_ready", "runner_live_network_evidence_reference"}
    if {key: value for key, value in old.items() if key not in ignored} != {
        key: value for key, value in new.items() if key not in ignored
    }:
        raise StageTransitionError("planned workloads progression changes unrelated tfvars")


def _write_exclusive(
    path: Path,
    data: bytes,
    *,
    temporary_root: Path,
    mode: int = 0o600,
) -> None:
    _safe_private_directory(temporary_root)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=temporary_root)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        descriptor = -1
        os.link(temporary, path)
        parent_descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent_descriptor)
        finally:
            os.close(parent_descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _fsync_directory(path: Path) -> None:
    _safe_private_directory(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _durable_rename(source: Path, destination: Path) -> None:
    os.rename(source, destination)
    _fsync_directory(destination.parent)
    if source.parent != destination.parent:
        _fsync_directory(source.parent)


def _validate_evidence(path: Path, approval_sha256: str) -> dict[str, Any]:
    _safe_private_file(path, required=True)
    evidence = _load_json(path)
    if not isinstance(evidence, dict):
        raise StageTransitionError("stored stage transition evidence invalid")
    expected = evidence.get("evidence_payload_sha256")
    payload = {key: value for key, value in evidence.items() if key != "evidence_payload_sha256"}
    if (
        not isinstance(expected, str)
        or not _SHA256.fullmatch(expected)
        or not hmac.compare_digest(expected, _sha256_json(payload))
        or evidence.get("owner_approval_sha256") != approval_sha256
    ):
        raise StageTransitionError("stored stage transition evidence invalid")
    return evidence


def _validate_generation_marker(path: Path, transition_id: str, replacement_hash: str) -> None:
    _safe_private_file(path, required=True)
    marker = _load_json(path)
    if not isinstance(marker, dict) or marker != {
        "archive_id": transition_id,
        "replacement_tfvars_sha256": replacement_hash,
        "schema_version": 1,
    }:
        raise StageTransitionError("replacement stage generation marker invalid")


def _validate_replacement_generation(
    path: Path,
    transition_id: str,
    replacement_hash: str,
    *,
    complete: bool,
    allow_additional: bool = False,
) -> None:
    _safe_private_directory(path)
    allowed = {"environment.tfvars.json", ".stage-generation.json"}
    try:
        entries = {entry.name for entry in os.scandir(path)}
    except OSError:
        raise StageTransitionError("replacement stage generation is unavailable") from None
    if (not allow_additional and not entries.issubset(allowed)) or (
        complete
        and (not allowed.issubset(entries) or (not allow_additional and entries != allowed))
    ):
        raise StageTransitionError("replacement stage generation contains unexpected artifacts")
    if not complete:
        return
    _safe_private_file(path / "environment.tfvars.json", required=True)
    if _sha256_file(path / "environment.tfvars.json") != replacement_hash:
        raise StageTransitionError("pending replacement stage generation was modified")
    _validate_generation_marker(path / ".stage-generation.json", transition_id, replacement_hash)


def _ensure_parent(path: Path) -> None:
    created = False
    try:
        path.mkdir(mode=0o700)
        created = True
    except FileExistsError:
        pass
    _safe_private_directory(path)
    if created:
        _fsync_directory(path)
        _fsync_directory(path.parent)


def run_transition(config: Config, *, now: datetime) -> dict[str, Any]:
    _safe_private_file(config.payload_path, required=True)
    payload = _load_json(config.payload_path, maximum=MAX_PAYLOAD_BYTES)
    if not isinstance(payload, dict):
        raise StageTransitionError("stage transition payload invalid")
    replacement = _decode_replacement(payload.get("replacement_tfvars_base64"))
    mode, approval, approved_at = _validate_approval(config, payload, replacement)
    approval_sha256 = _sha256_json(approval)
    transition_id = approval_sha256
    replacement_hash = _sha256_bytes(replacement)
    history_parent = config.release_root / "stage-history" / config.stage
    publication_parent = config.release_root / "stage-transition-work" / config.stage
    archive_root = history_parent / transition_id
    pending_root = config.release_root / "stages" / f".{config.stage}.next-{transition_id}"
    archive_evidence = archive_root / ".stage-transition-attestation.json"
    in_place_evidence = config.stage_root / ".stage-transition-attestation.json"
    durable_transition_exists = (
        archive_root.exists()
        or archive_root.is_symlink()
        or pending_root.exists()
        or pending_root.is_symlink()
        or in_place_evidence.exists()
        or in_place_evidence.is_symlink()
    )
    if not durable_transition_exists and (
        approved_at > now or approved_at <= now - timedelta(hours=4)
    ):
        raise StageTransitionError("stage owner authorization is outside its four-hour window")

    # Completed transitions are idempotently retrievable with the exact same
    # authorization and replacement, but cannot be reopened or overwritten.
    if archive_root.exists() or archive_root.is_symlink():
        _safe_private_directory(archive_root)
        archived_inventory = _artifact_inventory(archive_root)
        if archived_inventory != approval["current_artifacts"]:
            raise StageTransitionError("archived stage artifacts were modified")
        archived_success = _successful_result_present(archive_root, archived_inventory)
        if mode == "abandoned_retry" and archived_success:
            raise StageTransitionError("a successfully applied stage cannot be abandoned")
        if mode == "planned_workloads_progression" and not archived_success:
            raise StageTransitionError(
                "planned progression requires an applied workloads generation"
            )
        if not config.stage_root.exists() and not config.stage_root.is_symlink():
            _validate_replacement_generation(
                pending_root, transition_id, replacement_hash, complete=True
            )
            _durable_rename(pending_root, config.stage_root)
            _validate_replacement_generation(
                config.stage_root, transition_id, replacement_hash, complete=True
            )
        else:
            _validate_replacement_generation(
                config.stage_root,
                transition_id,
                replacement_hash,
                complete=True,
                allow_additional=True,
            )
        return _validate_evidence(archive_evidence, approval_sha256)

    _safe_private_directory(config.release_root)
    _safe_private_directory(config.stage_root)
    source_binding = config.release_root / "source-sha"
    _safe_private_file(source_binding, required=True)
    if source_binding.read_text(encoding="utf-8").strip() != config.source_sha:
        raise StageTransitionError("release ID is bound to a different source commit")

    current_inventory = _artifact_inventory(config.stage_root)
    if current_inventory != approval["current_artifacts"]:
        raise StageTransitionError("stage artifacts differ from the owner-authorized inventory")
    successful_result = _successful_result_present(config.stage_root, current_inventory)
    if mode == "abandoned_retry" and successful_result:
        raise StageTransitionError("a successfully applied stage cannot be abandoned")
    if mode == "planned_workloads_progression" and not successful_result:
        raise StageTransitionError("planned progression requires an applied workloads generation")
    current_tfvars = (config.stage_root / "environment.tfvars.json").read_bytes()
    if mode == "planned_workloads_progression":
        _validate_planned_workload_progression(current_tfvars, replacement)

    _ensure_parent(config.release_root / "stages")
    _ensure_parent(config.release_root / "stage-history")
    _ensure_parent(history_parent)
    _ensure_parent(config.release_root / "stage-transition-work")
    _ensure_parent(publication_parent)

    marker = {
        "archive_id": transition_id,
        "replacement_tfvars_sha256": replacement_hash,
        "schema_version": 1,
    }
    if pending_root.exists() or pending_root.is_symlink():
        _validate_replacement_generation(
            pending_root, transition_id, replacement_hash, complete=False
        )
    else:
        pending_root.mkdir(mode=0o700)
        _fsync_directory(pending_root)
        _fsync_directory(pending_root.parent)

    pending_tfvars = pending_root / "environment.tfvars.json"
    pending_marker = pending_root / ".stage-generation.json"
    if _safe_private_file(pending_tfvars, required=False):
        if _sha256_file(pending_tfvars) != replacement_hash:
            raise StageTransitionError("pending replacement stage generation was modified")
    else:
        _write_exclusive(
            pending_tfvars,
            replacement,
            temporary_root=publication_parent,
        )
    if pending_marker.exists() or pending_marker.is_symlink():
        _validate_generation_marker(pending_marker, transition_id, replacement_hash)
    else:
        _write_exclusive(
            pending_marker,
            (_canonical_json(marker) + "\n").encode(),
            temporary_root=publication_parent,
        )
    _validate_replacement_generation(pending_root, transition_id, replacement_hash, complete=True)

    evidence_payload = {
        "schema_version": 1,
        "evidence_type": EVIDENCE_TYPE,
        "completed_at": _timestamp(now),
        "source_sha": config.source_sha,
        "release_id": config.release_id,
        "stage": config.stage,
        "transition_mode": mode,
        "archive_id": transition_id,
        "current_artifacts": current_inventory,
        "replacement_tfvars_sha256": replacement_hash,
        "owner_approval_sha256": approval_sha256,
        "reviewer_reference_sha256": _sha256_bytes(approval["reviewer_reference"].encode()),
        "history_preserved": True,
        "successful_result_archived": successful_result,
        "secrets_returned": False,
    }
    evidence = {
        **evidence_payload,
        "evidence_payload_sha256": _sha256_json(evidence_payload),
    }
    encoded_evidence = (_canonical_json(evidence) + "\n").encode()
    if in_place_evidence.exists() or in_place_evidence.is_symlink():
        existing = _validate_evidence(in_place_evidence, approval_sha256)
        stable_keys = set(evidence) - {"completed_at", "evidence_payload_sha256"}
        if any(existing.get(key) != evidence.get(key) for key in stable_keys):
            raise StageTransitionError("staged transition evidence differs from authorization")
        evidence = existing
    else:
        _write_exclusive(
            in_place_evidence,
            encoded_evidence,
            temporary_root=publication_parent,
        )

    # Both renames are on the same protected filesystem. If interruption lands
    # between them, the exact authorization can finish from the deterministic
    # pending path without overwriting either generation.
    _durable_rename(config.stage_root, archive_root)
    try:
        _durable_rename(pending_root, config.stage_root)
    except Exception:
        if not config.stage_root.exists() and archive_root.exists():
            _durable_rename(archive_root, config.stage_root)
        raise
    _validate_replacement_generation(
        config.stage_root, transition_id, replacement_hash, complete=True
    )
    return _validate_evidence(archive_evidence, approval_sha256)


def inspect_stage(config: Config, *, now: datetime) -> dict[str, Any]:
    _safe_private_file(config.payload_path, required=True)
    if _load_json(config.payload_path) != {}:
        raise StageTransitionError("stage inspection payload must be empty")
    _safe_private_directory(config.release_root)
    _safe_private_directory(config.stage_root)
    source_binding = config.release_root / "source-sha"
    _safe_private_file(source_binding, required=True)
    if source_binding.read_text(encoding="utf-8").strip() != config.source_sha:
        raise StageTransitionError("release ID is bound to a different source commit")
    inventory = _artifact_inventory(config.stage_root)
    latest_transition: dict[str, Any] | None = None
    marker_path = config.stage_root / ".stage-generation.json"
    if marker_path.exists() or marker_path.is_symlink():
        _safe_private_file(marker_path, required=True)
        marker = _load_json(marker_path)
        if (
            not isinstance(marker, dict)
            or set(marker)
            != {
                "archive_id",
                "replacement_tfvars_sha256",
                "schema_version",
            }
            or marker.get("schema_version") != 1
            or not isinstance(marker.get("archive_id"), str)
            or not _SHA256.fullmatch(marker["archive_id"])
            or marker.get("replacement_tfvars_sha256") != inventory["environment_tfvars_sha256"]
        ):
            raise StageTransitionError("current stage generation marker invalid")
        archive_root = config.release_root / "stage-history" / config.stage / marker["archive_id"]
        _safe_private_directory(archive_root)
        latest_transition = _validate_evidence(
            archive_root / ".stage-transition-attestation.json", marker["archive_id"]
        )
        if (
            _artifact_inventory(archive_root) != latest_transition.get("current_artifacts")
            or latest_transition.get("source_sha") != config.source_sha
            or latest_transition.get("release_id") != config.release_id
            or latest_transition.get("stage") != config.stage
            or latest_transition.get("replacement_tfvars_sha256")
            != inventory["environment_tfvars_sha256"]
        ):
            raise StageTransitionError("latest stage transition binding invalid")
    payload = {
        "schema_version": 1,
        "evidence_type": "protected-runner-stage-generation-inspection",
        "completed_at": _timestamp(now),
        "source_sha": config.source_sha,
        "release_id": config.release_id,
        "stage": config.stage,
        "current_artifacts": inventory,
        "successful_result_present": _successful_result_present(config.stage_root, inventory),
        "latest_transition": latest_transition,
        "secrets_returned": False,
    }
    return {**payload, "evidence_payload_sha256": _sha256_json(payload)}


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv if argv is None else argv
    try:
        config = Config.from_argv(arguments)
        evidence = (
            inspect_stage(config, now=datetime.now(UTC))
            if config.action == "inspect"
            else run_transition(config, now=datetime.now(UTC))
        )
    except Exception:  # noqa: BLE001 - never reflect protected path or secret details
        print(_canonical_json({"evidence_type": EVIDENCE_TYPE, "status": "failed"}))
        return 1
    print(_canonical_json(evidence))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
