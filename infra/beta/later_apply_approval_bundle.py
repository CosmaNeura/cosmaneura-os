#!/usr/bin/env python3
"""Create authority-separated D3 database/workload apply bundles.

The ``request`` command creates only a non-authoritative, exact-plan approval
request.  The ``materialize`` command accepts a separately authored owner
authorization and publishes the five-file bundle consumed by
``validate_apply_approval.py``.  Neither command invokes Terraform or any
external service.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NoReturn
from uuid import UUID

HASH_RE = re.compile(r"^[0-9a-f]{64}$")
SOURCE_RE = re.compile(r"^[0-9a-f]{40}$")
RELEASE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,31}$")
REVIEWER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/ -]{2,127}$")
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
TIME_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
UTC = timezone.utc  # noqa: UP017 -- the protected runner supports Python 3.10.

REQUEST_CONTRACT = "cosmas-os-d3-protected-apply-request-v2"
OWNER_CONTRACT = "cosmas-os-d3-protected-owner-authorization-v2"
CLAIM_CONTRACT = "cosmas-os-d3-protected-apply-claim-v2"
APPROVAL_CONTRACT = "cosmas-os-d3-protected-apply-authorization-v2"
BUNDLE_CONTRACT = "cosmas-os-d3-protected-apply-bundle-v2"
MAX_VALIDITY_SECONDS = 1800
MAX_JSON_BYTES = 8 * 1024 * 1024
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = Path(__file__).resolve().with_name("validate_apply_approval.py")

REVIEW_KEYS = {
    "schema_version",
    "phase",
    "generated_at",
    "plan_sha256",
    "source_sha",
    "terraform_version",
    "provider_lock_sha256",
    "variable_file_sha256",
    "prior_state",
    "boundary",
    "managed_action_counts",
    "managed_actions",
    "critical_planned_values",
    "security_posture",
}
BOUNDARY_KEYS = {
    "subscription_id",
    "tenant_id",
    "deploy_identity_client_id",
    "beta_id",
    "box_id",
    "state_resource_group",
    "workload_resource_group",
    "state_vnet_id",
    "state_blob_private_dns_zone_id",
    "deployment_mode",
    "data_classification",
}
CRITICAL_VALUE_KEYS = {
    "environment",
    "location",
    "box_id",
    "deployment_mode",
    "data_classification",
    "registry_network_posture",
    "workloads_enabled",
    "database_preparation_job_enabled",
    "runtime_acceptance_job_enabled",
    "image_reference",
    "web_image_reference",
    "api_origin",
    "web_origin",
    "web_default_fqdn",
    "web_custom_domain",
    "web_custom_domain_binding_enabled",
    "acr_login_server",
}
BASE_KEYS = {
    "source_sha",
    "release_id",
    "stage",
    "plan_sha256",
    "review_sha256",
    "variable_file_sha256",
    "state",
}
REQUEST_KEYS = {
    "schema_version",
    "contract",
    "status",
    *BASE_KEYS,
    "exact_owner_assertion",
    "maximum_validity_seconds",
    "does_not_authorize",
    "evidence_payload_sha256",
}
OWNER_KEYS = {
    "schema_version",
    "contract",
    "authorization_status",
    *BASE_KEYS,
    "owner_assertion",
    "reviewer",
    "approved_at",
    "expires_at",
}


def fail(message: str) -> NoReturn:
    raise ValueError(message)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            fail(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _canonical(value: object, *, trailing_lf: bool) -> bytes:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    return encoded + (b"\n" if trailing_lf else b"")


def _pretty(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()


def _self_hashed(value: dict[str, Any], *, trailing_lf: bool) -> dict[str, Any]:
    result = dict(value)
    result["evidence_payload_sha256"] = hashlib.sha256(
        _canonical(value, trailing_lf=trailing_lf)
    ).hexdigest()
    return result


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _require_hash(value: object, field: str) -> str:
    if not isinstance(value, str) or HASH_RE.fullmatch(value) is None:
        fail(f"{field} must be a lowercase SHA-256")
    return value


def _parse_time(value: object, field: str) -> datetime:
    if not isinstance(value, str) or TIME_RE.fullmatch(value) is None:
        fail(f"{field} must be an exact UTC second timestamp")
    try:
        return datetime.strptime(value, TIME_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        fail(f"{field} must be an exact UTC second timestamp")


def _format_time(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).strftime(TIME_FORMAT)


def _now(value: str | None) -> datetime:
    return _parse_time(value, "now") if value else datetime.now(UTC).replace(microsecond=0)


def _require_absolute(path: Path, label: str) -> None:
    if not path.is_absolute():
        fail(f"{label} path must be absolute")


def _outside_repository(path: Path, label: str) -> None:
    try:
        path.relative_to(REPOSITORY_ROOT)
    except ValueError:
        return
    fail(f"{label} must remain outside the source repository")


def _secure_directory(path: Path, label: str) -> Path:
    _require_absolute(path, label)
    if path.is_symlink():
        fail(f"{label} must not be a symlink")
    resolved = path.resolve(strict=True)
    if resolved != path:
        fail(f"{label} path must not traverse aliases or symlinks")
    _outside_repository(resolved, label)
    details = resolved.stat()
    if not stat.S_ISDIR(details.st_mode) or details.st_uid != os.getuid():
        fail(f"{label} must be an owner-controlled directory")
    if stat.S_IMODE(details.st_mode) != 0o700:
        fail(f"{label} must have mode 0700")
    return resolved


def _secure_file(path: Path, label: str, *, max_bytes: int = MAX_JSON_BYTES) -> bytes:
    _require_absolute(path, label)
    if path.is_symlink():
        fail(f"{label} must not be a symlink")
    parent = _secure_directory(path.parent, f"{label} parent")
    normalized = parent / path.name
    if normalized != path:
        fail(f"{label} path must not traverse aliases or symlinks")

    directory_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    directory_flags |= getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    file_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    parent_descriptor = -1
    descriptor = -1
    try:
        parent_descriptor = os.open(parent, directory_flags)
        parent_details = os.fstat(parent_descriptor)
        if (
            not stat.S_ISDIR(parent_details.st_mode)
            or parent_details.st_uid != os.getuid()
            or stat.S_IMODE(parent_details.st_mode) != 0o700
        ):
            fail(f"{label} parent must be an owner-controlled mode-0700 directory")
        descriptor = os.open(path.name, file_flags, dir_fd=parent_descriptor)
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode) or details.st_uid != os.getuid():
            fail(f"{label} must be an owner-controlled regular file")
        if stat.S_IMODE(details.st_mode) != 0o600 or details.st_nlink != 1:
            fail(f"{label} must be a single-link mode-0600 file")
        if details.st_size > max_bytes:
            fail(f"{label} exceeds its size limit")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            raw = stream.read(max_bytes + 1)
        if len(raw) > max_bytes:
            fail(f"{label} exceeds its size limit")
        return raw
    except OSError as exc:
        fail(f"{label} must be an owner-controlled non-symlink regular file: {exc}")
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if parent_descriptor >= 0:
            os.close(parent_descriptor)


def _new_output(path: Path, label: str) -> tuple[Path, Path]:
    _require_absolute(path, label)
    if path.name in {"", ".", ".."}:
        fail(f"{label} filename is invalid")
    parent = _secure_directory(path.parent, f"{label} parent")
    normalized = parent / path.name
    if normalized != path or path.exists() or path.is_symlink():
        fail(f"{label} already exists or has an unsafe path")
    return parent, normalized


def _load_json(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_unique_object,
            parse_constant=lambda constant: fail(f"invalid JSON constant: {constant}"),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"{label} is not strict JSON: {exc}")
    if not isinstance(value, dict):
        fail(f"{label} must be a JSON object")
    return value


def _exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        fail(f"{label} keys do not exactly match the expected schema")


def _canonical_uuid(value: object, field: str) -> str:
    if not isinstance(value, str):
        fail(f"{field} must be a canonical UUID")
    try:
        parsed = str(UUID(value))
    except ValueError:
        fail(f"{field} must be a canonical UUID")
    if parsed != value:
        fail(f"{field} must be a canonical UUID")
    return value


def _validate_state(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"exists", "lineage", "serial", "sha256"}:
        fail(f"{label} state shape is invalid")
    if value["exists"] is not True:
        fail(f"{label} must bind existing state")
    _canonical_uuid(value["lineage"], f"{label} state lineage")
    if type(value["serial"]) is not int or value["serial"] < 0:
        fail(f"{label} state serial is invalid")
    _require_hash(value["sha256"], f"{label} state SHA-256")
    return value


def _validate_review(
    raw: bytes,
    *,
    source_sha: str,
    variable_file_sha256: str,
    stage: str,
    now: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    review = _load_json(raw, "sanitized review")
    _exact_keys(review, REVIEW_KEYS, "sanitized review")
    if type(review["schema_version"]) is not int or review["schema_version"] != 1:
        fail("sanitized review schema version is invalid")
    if review["phase"] != "subsequent" or review["source_sha"] != source_sha:
        fail("sanitized review phase/source binding is invalid")
    _require_hash(review["plan_sha256"], "sanitized review plan SHA-256")
    _require_hash(review["provider_lock_sha256"], "sanitized review provider lock SHA-256")
    if review["variable_file_sha256"] != variable_file_sha256:
        fail("sanitized review variable-file binding is invalid")
    _require_hash(review["variable_file_sha256"], "sanitized review variable-file SHA-256")
    generated_at = _parse_time(review["generated_at"], "sanitized review generated_at")
    if generated_at > now:
        fail("sanitized review timestamp is in the future")
    if not isinstance(review["terraform_version"], str) or not review["terraform_version"]:
        fail("sanitized review Terraform version is invalid")

    prior = review["prior_state"]
    if not isinstance(prior, dict) or set(prior) != {"lineage", "serial", "sha256"}:
        fail("sanitized review prior-state shape is invalid")
    state = _validate_state({"exists": True, **prior}, "sanitized review")

    boundary = review["boundary"]
    if not isinstance(boundary, dict) or set(boundary) != BOUNDARY_KEYS:
        fail("sanitized review boundary shape is invalid")
    for field in ("subscription_id", "tenant_id", "deploy_identity_client_id", "box_id"):
        _canonical_uuid(boundary[field], f"sanitized review boundary {field}")
    for field in ("beta_id", "state_resource_group", "workload_resource_group"):
        if not isinstance(boundary[field], str) or not boundary[field]:
            fail(f"sanitized review boundary {field} is invalid")
    for field in ("state_vnet_id", "state_blob_private_dns_zone_id"):
        if not isinstance(boundary[field], str) or not boundary[field].startswith(
            "/subscriptions/"
        ):
            fail(f"sanitized review boundary {field} is invalid")
    if (
        boundary["deployment_mode"] != "synthetic_lab"
        or boundary["data_classification"] != "synthetic-only"
    ):
        fail("sanitized review is outside the D3 synthetic-lab boundary")

    counts = review["managed_action_counts"]
    count_keys = {"create", "update", "delete", "replace", "no_op"}
    if not isinstance(counts, dict) or set(counts) != count_keys:
        fail("sanitized review action-count shape is invalid")
    if any(type(counts[key]) is not int or counts[key] < 0 for key in count_keys):
        fail("sanitized review action counts are invalid")
    if counts["delete"] != 0 or counts["replace"] != 0:
        fail("sanitized review contains destructive managed actions")

    actions = review["managed_actions"]
    if not isinstance(actions, list):
        fail("sanitized review managed actions must be an array")
    observed = {"create": 0, "update": 0, "no_op": 0}
    managed_by_address: dict[str, tuple[str, list[str]]] = {}
    for item in actions:
        if not isinstance(item, dict) or set(item) != {"address", "type", "mode", "actions"}:
            fail("sanitized review managed-action shape is invalid")
        if not all(
            isinstance(item[field], str) and item[field] for field in ("address", "type", "mode")
        ):
            fail("sanitized review managed-action identity is invalid")
        if not isinstance(item["actions"], list) or not all(
            isinstance(action, str) for action in item["actions"]
        ):
            fail("sanitized review managed-action operation is invalid")
        if item["mode"] == "managed":
            if item["actions"] not in (["create"], ["update"], ["no-op"]):
                fail("sanitized review contains an unsafe managed action")
            key = "no_op" if item["actions"] == ["no-op"] else item["actions"][0]
            observed[key] += 1
            if item["address"] in managed_by_address:
                fail("sanitized review repeats a managed resource address")
            managed_by_address[item["address"]] = (item["type"], item["actions"])
    if any(counts[key] != observed[key] for key in observed):
        fail("sanitized review action counts do not match its action list")

    posture = review["security_posture"]
    if not isinstance(posture, list):
        fail("sanitized review security posture must be an array")
    posture_by_address: dict[str, tuple[str, list[str]]] = {}
    for item in posture:
        if not isinstance(item, dict) or set(item) != {
            "address",
            "type",
            "actions",
            "before",
            "after",
        }:
            fail("sanitized review security-posture shape is invalid")
        if not isinstance(item["address"], str) or not isinstance(item["type"], str):
            fail("sanitized review security-posture identity is invalid")
        if not isinstance(item["actions"], list) or not all(
            isinstance(action, str) for action in item["actions"]
        ):
            fail("sanitized review security-posture action is invalid")
        if item["address"] in posture_by_address:
            fail("sanitized review repeats a security-posture address")
        posture_by_address[item["address"]] = (item["type"], item["actions"])
    if posture_by_address != managed_by_address:
        fail("sanitized review actions and security posture are not congruent")

    critical = review["critical_planned_values"]
    if not isinstance(critical, dict) or set(critical) != CRITICAL_VALUE_KEYS:
        fail("sanitized review critical planned-value shape is invalid")
    if (
        critical["environment"] != "early_adopter_beta"
        or str(critical["location"]).lower() != "centralus"
        or critical["box_id"] != boundary["box_id"]
        or critical["deployment_mode"] != "synthetic_lab"
        or critical["data_classification"] != "synthetic-only"
    ):
        fail("sanitized review critical values are outside the D3 boundary")
    for field in (
        "workloads_enabled",
        "database_preparation_job_enabled",
        "runtime_acceptance_job_enabled",
        "web_custom_domain_binding_enabled",
    ):
        if type(critical[field]) is not bool:
            fail(f"sanitized review critical value {field} is invalid")
    expected_stage_switches = {
        "database": (True, False, False),
        "workloads": (True, True, True),
    }
    expected_database, expected_workloads, expected_runtime_acceptance = expected_stage_switches[
        stage
    ]
    if (
        critical["database_preparation_job_enabled"] is not expected_database
        or critical["workloads_enabled"] is not expected_workloads
        or critical["runtime_acceptance_job_enabled"] is not expected_runtime_acceptance
    ):
        fail(f"sanitized review does not describe the exact {stage} stage")
    return review, state


def _base_from_inputs(
    *,
    review_raw: bytes,
    variable_raw: bytes,
    source_sha: str,
    release_id: str,
    stage: str,
    now: datetime,
) -> dict[str, Any]:
    if SOURCE_RE.fullmatch(source_sha) is None or RELEASE_RE.fullmatch(release_id) is None:
        fail("source SHA or release ID is invalid")
    if stage not in {"database", "workloads"}:
        fail("only database or workloads approval bundles can be created")
    variable_sha = _sha256(variable_raw)
    review, state = _validate_review(
        review_raw,
        source_sha=source_sha,
        variable_file_sha256=variable_sha,
        stage=stage,
        now=now,
    )
    return {
        "source_sha": source_sha,
        "release_id": release_id,
        "stage": stage,
        "plan_sha256": review["plan_sha256"],
        "review_sha256": _sha256(review_raw),
        "variable_file_sha256": variable_sha,
        "state": state,
    }


def _validate_request(value: dict[str, Any], base: dict[str, Any]) -> None:
    _exact_keys(value, REQUEST_KEYS, "approval request")
    expected_assertion = (
        f"AUTHORIZE D3 {base['stage'].upper()} APPLY {base['plan_sha256']} {base['review_sha256']}"
    )
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != 2
        or value["contract"] != REQUEST_CONTRACT
        or value["status"] != "PENDING_OWNER_AUTHORIZATION"
        or any(value[key] != item for key, item in base.items())
        or value["exact_owner_assertion"] != expected_assertion
        or type(value["maximum_validity_seconds"]) is not int
        or value["maximum_validity_seconds"] != MAX_VALIDITY_SECONDS
        or value["does_not_authorize"] is not True
    ):
        fail("approval request contract/binding is invalid")
    expected_hash = _require_hash(value["evidence_payload_sha256"], "approval request hash")
    payload = dict(value)
    del payload["evidence_payload_sha256"]
    if _sha256(_canonical(payload, trailing_lf=True)) != expected_hash:
        fail("approval request evidence hash is invalid")


def _validate_owner(
    value: dict[str, Any], base: dict[str, Any], request: dict[str, Any], now: datetime
) -> tuple[datetime, datetime]:
    _exact_keys(value, OWNER_KEYS, "owner authorization")
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != 2
        or value["contract"] != OWNER_CONTRACT
        or value["authorization_status"] != "APPROVED"
        or any(value[key] != item for key, item in base.items())
        or value["owner_assertion"] != request["exact_owner_assertion"]
    ):
        fail("owner authorization contract/binding is invalid")
    reviewer = value["reviewer"]
    if not isinstance(reviewer, str) or REVIEWER_RE.fullmatch(reviewer) is None or "@" in reviewer:
        fail("owner authorization reviewer is invalid")
    approved_at = _parse_time(value["approved_at"], "owner approved_at")
    expires_at = _parse_time(value["expires_at"], "owner expires_at")
    if approved_at > now or now >= expires_at:
        fail("owner authorization is not currently effective")
    if (
        expires_at <= approved_at
        or (expires_at - approved_at).total_seconds() > MAX_VALIDITY_SECONDS
    ):
        fail("owner authorization window must be positive and no longer than 30 minutes")
    return approved_at, expires_at


def _write_new_file(path: Path, raw: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _publish_new_file(path: Path, raw: bytes) -> None:
    parent, destination = _new_output(path, "approval request output")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".partial", dir=parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.close(descriptor)
        descriptor = -1
        os.link(temporary, destination, follow_symlinks=False)
        _fsync_directory(parent)
    except FileExistsError:
        fail("approval request output already exists")
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _request(args: argparse.Namespace) -> int:
    now = _now(args.now)
    review_raw = _secure_file(args.review, "sanitized review")
    variable_raw = _secure_file(args.var_file, "variable file")
    base = _base_from_inputs(
        review_raw=review_raw,
        variable_raw=variable_raw,
        source_sha=args.source_sha,
        release_id=args.release_id,
        stage=args.stage,
        now=now,
    )
    assertion = (
        f"AUTHORIZE D3 {args.stage.upper()} APPLY {base['plan_sha256']} {base['review_sha256']}"
    )
    request = _self_hashed(
        {
            "schema_version": 2,
            "contract": REQUEST_CONTRACT,
            "status": "PENDING_OWNER_AUTHORIZATION",
            **base,
            "exact_owner_assertion": assertion,
            "maximum_validity_seconds": MAX_VALIDITY_SECONDS,
            "does_not_authorize": True,
        },
        trailing_lf=True,
    )
    _validate_request(request, base)
    _publish_new_file(args.request_out, _pretty(request))
    print(f"D3 {args.stage} non-authoritative approval request created: {args.request_out}")
    print(f"Exact owner assertion: {assertion}")
    return 0


def _validate_staged_bundle(
    bundle: Path,
    base: dict[str, Any],
    *,
    now: datetime,
) -> None:
    command = [
        sys.executable,
        "-I",
        "-E",
        "-s",
        str(VALIDATOR),
        str(bundle / "source-approval.json"),
        "--bundle-dir",
        str(bundle),
        "--source-sha",
        str(base["source_sha"]),
        "--release-id",
        str(base["release_id"]),
        "--stage",
        str(base["stage"]),
        "--plan-sha256",
        str(base["plan_sha256"]),
        "--review-sha256",
        str(base["review_sha256"]),
        "--variable-file-sha256",
        str(base["variable_file_sha256"]),
        "--state-exists",
        "true",
        "--state-lineage",
        str(base["state"]["lineage"]),
        "--state-serial",
        str(base["state"]["serial"]),
        "--state-sha256",
        str(base["state"]["sha256"]),
        "--now",
        _format_time(now),
    ]
    result = subprocess.run(command, capture_output=True, check=False, text=True)
    if result.returncode != 0:
        detail = result.stderr.strip() or "validator returned a non-zero status"
        fail(f"staged authorization bundle failed protected validation: {detail}")


def _materialize(args: argparse.Namespace) -> int:
    now = _now(args.now)
    review_raw = _secure_file(args.review, "sanitized review")
    variable_raw = _secure_file(args.var_file, "variable file")
    request_raw = _secure_file(args.request, "approval request", max_bytes=65_536)
    owner_raw = _secure_file(args.owner_authorization, "owner authorization", max_bytes=65_536)
    base = _base_from_inputs(
        review_raw=review_raw,
        variable_raw=variable_raw,
        source_sha=args.source_sha,
        release_id=args.release_id,
        stage=args.stage,
        now=now,
    )
    request = _load_json(request_raw, "approval request")
    owner = _load_json(owner_raw, "owner authorization")
    _validate_request(request, base)
    _validate_owner(owner, base, request, now)

    bundle_root = _secure_directory(args.bundle_root, "approval bundle root")
    bundle = bundle_root / str(base["plan_sha256"])
    try:
        # Reserving the final content-addressed name is the append-only claim.
        # Do not remove this directory after a later failure: an interrupted
        # materialization must be inspected rather than silently resumed.
        bundle.mkdir(mode=0o700)
    except FileExistsError:
        fail("content-addressed approval bundle already exists; refusing replay or overwrite")
    os.chmod(bundle, 0o700)
    _fsync_directory(bundle_root)

    request_sha = _sha256(request_raw)
    owner_sha = _sha256(owner_raw)
    claimed_at = _format_time(now)
    claim = _self_hashed(
        {
            "schema_version": 2,
            "contract": CLAIM_CONTRACT,
            "status": "CLAIMED_FOR_EXACT_PROTECTED_APPLY",
            **base,
            "approval_request_sha256": request_sha,
            "authorization_sha256": owner_sha,
            "claimed_at": claimed_at,
            "owner_expires_at": owner["expires_at"],
            "effective_expires_at": owner["expires_at"],
            "reviewer_reference_sha256": _sha256(str(owner["reviewer"]).encode()),
        },
        trailing_lf=True,
    )

    # Preserve the separately supplied source documents byte-for-byte.
    _write_new_file(bundle / "approval-request.json", request_raw)
    _write_new_file(bundle / "owner-authorization.json", owner_raw)
    _write_new_file(bundle / "claim.json", _pretty(claim))
    claim_sha = _sha256((bundle / "claim.json").read_bytes())

    source_approval = _self_hashed(
        {
            "schema_version": 2,
            "contract": APPROVAL_CONTRACT,
            "authorization_status": "APPROVED",
            **base,
            "reviewer": owner["reviewer"],
            "owner_assertion": owner["owner_assertion"],
            "review_reference": f"owner-authorization:sha256:{owner_sha}",
            "authorization_sha256": owner_sha,
            "authorization_claim_sha256": claim_sha,
            "authorization_bundle_id": base["plan_sha256"],
            "approval_request_sha256": request_sha,
            "approved_at": owner["approved_at"],
            "claimed_at": claimed_at,
            "owner_expires_at": owner["expires_at"],
            "expires_at": owner["expires_at"],
        },
        trailing_lf=False,
    )
    _write_new_file(bundle / "source-approval.json", _pretty(source_approval))

    file_hashes = {
        name: _sha256((bundle / name).read_bytes())
        for name in (
            "approval-request.json",
            "owner-authorization.json",
            "claim.json",
            "source-approval.json",
        )
    }
    manifest = _self_hashed(
        {
            "schema_version": 2,
            "contract": BUNDLE_CONTRACT,
            "status": "CLAIMED_READY_FOR_EXACT_PROTECTED_APPLY",
            **base,
            "authorization_bundle_id": base["plan_sha256"],
            "owner_authorization": {
                "sha256": owner_sha,
                "approved_at": owner["approved_at"],
                "expires_at": owner["expires_at"],
                "claimed_at": claimed_at,
            },
            "files": file_hashes,
            "append_only": True,
            "does_not_execute_apply": True,
        },
        trailing_lf=True,
    )
    # The manifest is deliberately the last file written. A directory without
    # it is an incomplete, permanently claimed bundle rather than resumable work.
    _fsync_directory(bundle)
    _write_new_file(bundle / "manifest.json", _pretty(manifest))
    _fsync_directory(bundle)
    _validate_staged_bundle(bundle, base, now=now)

    print(f"D3 {args.stage} approval bundle materialized without applying: {bundle}")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create non-authoritative D3 requests and exact database/workload bundles."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_exact_inputs(command: argparse.ArgumentParser) -> None:
        command.add_argument("--review", type=Path, required=True)
        command.add_argument("--var-file", type=Path, required=True)
        command.add_argument("--source-sha", required=True)
        command.add_argument("--release-id", required=True)
        command.add_argument("--stage", choices=("database", "workloads"), required=True)
        command.add_argument("--now", help=argparse.SUPPRESS)

    request = subparsers.add_parser(
        "request", help="create a non-authoritative exact-plan approval request"
    )
    add_exact_inputs(request)
    request.add_argument("--request-out", type=Path, required=True)
    request.set_defaults(handler=_request)

    materialize = subparsers.add_parser(
        "materialize", help="validate separate owner authority and atomically create a bundle"
    )
    add_exact_inputs(materialize)
    materialize.add_argument("--request", type=Path, required=True)
    materialize.add_argument("--owner-authorization", type=Path, required=True)
    materialize.add_argument("--bundle-root", type=Path, required=True)
    materialize.set_defaults(handler=_materialize)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"D3 approval-bundle tool refused: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
