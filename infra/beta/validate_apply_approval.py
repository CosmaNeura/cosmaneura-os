#!/usr/bin/env python3
"""Strict causal validation for protected D3 apply-authorization bundles."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NoReturn
from uuid import UUID

HASH_RE = re.compile(r"^[0-9a-f]{64}$")
SOURCE_RE = re.compile(r"^[0-9a-f]{40}$")
RELEASE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,31}$")
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
TIME_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
UTC = timezone.utc  # noqa: UP017 -- protected runner supports Python 3.10.
FOUNDATION_CONTRACT = "cosmas-os-d3-foundation-protected-apply-authorization-v2"
LATER_CONTRACT = "cosmas-os-d3-protected-apply-authorization-v2"

COMMON_KEYS = {
    "schema_version",
    "contract",
    "authorization_status",
    "source_sha",
    "release_id",
    "stage",
    "plan_sha256",
    "review_sha256",
    "variable_file_sha256",
    "state",
    "reviewer",
    "owner_assertion",
    "review_reference",
    "authorization_sha256",
    "authorization_claim_sha256",
    "authorization_bundle_id",
    "approval_request_sha256",
    "approved_at",
    "claimed_at",
    "owner_expires_at",
    "expires_at",
    "evidence_payload_sha256",
}
FOUNDATION_KEYS = COMMON_KEYS | {
    "readiness_payload_sha256",
    "human_review_payload_sha256",
    "cost_evidence_payload_sha256",
    "foundation_package_manifest_sha256",
    "readiness_expires_at",
    "human_review_expires_at",
    "cost_expires_at",
}
BUNDLE_FILES = {
    "approval-request.json",
    "owner-authorization.json",
    "claim.json",
    "source-approval.json",
    "manifest.json",
}


def fail(message: str) -> NoReturn:
    raise ValueError(message)


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            fail(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def canonical(value: object, *, trailing_lf: bool) -> bytes:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    return encoded + (b"\n" if trailing_lf else b"")


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_strict(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        fail(f"{label} is unavailable or unsafe")
    raw = path.read_bytes()
    if len(raw) > 65_536:
        fail(f"{label} exceeds 64 KiB")
    try:
        value = json.loads(
            raw,
            object_pairs_hook=unique_object,
            parse_constant=lambda constant: fail(f"invalid JSON constant: {constant}"),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"{label} is not strict JSON: {exc}")
    if not isinstance(value, dict):
        fail(f"{label} must be an object")
    return value


def exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        fail(f"{label} keys do not exactly match its contract")


def require_hash(value: object, field: str) -> str:
    if not isinstance(value, str) or HASH_RE.fullmatch(value) is None:
        fail(f"{field} must be a lowercase SHA-256")
    return value


def require_payload_hash(value: dict[str, Any], label: str, *, trailing_lf: bool = True) -> None:
    expected = require_hash(value.get("evidence_payload_sha256"), f"{label} evidence hash")
    payload = dict(value)
    del payload["evidence_payload_sha256"]
    if hashlib.sha256(canonical(payload, trailing_lf=trailing_lf)).hexdigest() != expected:
        fail(f"{label} evidence hash is invalid")


def parse_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str) or TIME_RE.fullmatch(value) is None:
        fail(f"{field} must be a UTC timestamp")
    try:
        return datetime.strptime(value, TIME_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        fail(f"{field} must be an exact UTC second timestamp")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("approval", type=Path)
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--stage", choices=("foundation", "database", "workloads"), required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--review-sha256", required=True)
    parser.add_argument("--variable-file-sha256", required=True)
    parser.add_argument("--state-exists", choices=("true", "false"), required=True)
    parser.add_argument("--state-lineage", default="")
    parser.add_argument("--state-serial", default="null")
    parser.add_argument("--state-sha256", default="")
    parser.add_argument("--now")
    return parser.parse_args()


def expected_state(args: argparse.Namespace) -> dict[str, object]:
    if args.state_exists == "false":
        if args.state_lineage or args.state_serial != "null" or args.state_sha256:
            fail("absent state must use null bindings")
        return {"exists": False, "lineage": None, "serial": None, "sha256": None}
    try:
        lineage = str(UUID(args.state_lineage))
        serial = int(args.state_serial)
    except ValueError:
        fail("expected state binding is invalid")
    if serial < 0 or str(serial) != args.state_serial:
        fail("expected state serial is invalid")
    return {
        "exists": True,
        "lineage": lineage,
        "serial": serial,
        "sha256": require_hash(args.state_sha256, "expected state sha256"),
    }


def validate_state(value: object, expected: dict[str, object], label: str) -> None:
    if not isinstance(value, dict) or set(value) != {"exists", "lineage", "serial", "sha256"}:
        fail(f"{label} state shape is invalid")
    if type(value["exists"]) is not bool:
        fail(f"{label} state existence type is invalid")
    if value["exists"]:
        if not isinstance(value["lineage"], str):
            fail(f"{label} state lineage type is invalid")
        try:
            UUID(value["lineage"])
        except ValueError:
            fail(f"{label} state lineage is invalid")
        if type(value["serial"]) is not int or value["serial"] < 0:
            fail(f"{label} state serial type is invalid")
        require_hash(value["sha256"], f"{label} state sha256")
    elif any(value[field] is not None for field in ("lineage", "serial", "sha256")):
        fail(f"{label} absent state bindings are invalid")
    if value != expected:
        fail(f"{label} state binding is invalid")


def validate_reduced_state(value: object, expected: dict[str, object], label: str) -> None:
    if not isinstance(value, dict) or set(value) != {"exists", "lineage", "serial"}:
        fail(f"{label} state shape is invalid")
    if type(value["exists"]) is not bool:
        fail(f"{label} state existence type is invalid")
    if value["exists"]:
        if not isinstance(value["lineage"], str):
            fail(f"{label} state lineage type is invalid")
        try:
            UUID(value["lineage"])
        except ValueError:
            fail(f"{label} state lineage is invalid")
        if type(value["serial"]) is not int or value["serial"] < 0:
            fail(f"{label} state serial type is invalid")
    elif value["lineage"] is not None or value["serial"] is not None:
        fail(f"{label} absent state bindings are invalid")
    reduced_expected = {key: item for key, item in expected.items() if key != "sha256"}
    if value != reduced_expected:
        fail(f"{label} state binding is invalid")


def validate_foundation_bundle(
    bundle: Path,
    approval: dict[str, Any],
    state: dict[str, object],
    now: datetime,
) -> None:
    request_path = bundle / "approval-request.json"
    owner_path = bundle / "owner-authorization.json"
    claim_path = bundle / "claim.json"
    manifest_path = bundle / "manifest.json"
    request = load_strict(request_path, "foundation approval request")
    owner = load_strict(owner_path, "foundation owner authorization")
    claim = load_strict(claim_path, "foundation authorization claim")
    manifest = load_strict(manifest_path, "foundation authorization manifest")

    owner_keys = {
        "schema_version",
        "contract",
        "authorization_status",
        "source_sha",
        "release_id",
        "plan_sha256",
        "review_sha256",
        "state_lineage",
        "state_serial",
        "owner_assertion",
        "reviewer_reference",
        "approved_at",
        "expires_at",
    }
    exact_keys(owner, owner_keys, "foundation owner authorization")
    if (
        type(owner["schema_version"]) is not int
        or owner["schema_version"] != 1
        or owner["contract"] != "cosmas-os-d3-foundation-plan-authorization-v1"
        or owner["authorization_status"] != "APPROVED"
    ):
        fail("foundation owner authorization contract is invalid")
    if any(
        owner[field] != approval[field]
        for field in ("source_sha", "release_id", "plan_sha256", "review_sha256", "owner_assertion")
    ):
        fail("foundation owner authorization binding is invalid")
    if state["exists"]:
        if not isinstance(owner["state_lineage"], str) or type(owner["state_serial"]) is not int:
            fail("foundation owner authorization state types are invalid")
    elif owner["state_lineage"] is not None or owner["state_serial"] is not None:
        fail("foundation owner authorization absent-state binding is invalid")
    if (
        owner["state_lineage"] != state["lineage"]
        or owner["state_serial"] != state["serial"]
        or owner["reviewer_reference"] != approval["reviewer"]
    ):
        fail("foundation owner authorization state/reviewer binding is invalid")
    if (
        owner["approved_at"] != approval["approved_at"]
        or owner["expires_at"] != approval["owner_expires_at"]
        or file_hash(owner_path) != approval["authorization_sha256"]
    ):
        fail("foundation owner authorization timestamp/hash binding is invalid")

    request_keys = {
        "schema_version",
        "contract",
        "artifact_status",
        "source_sha",
        "release_id",
        "readiness_payload_sha256",
        "foundation_package_id",
        "foundation_package_manifest_sha256",
        "foundation_tfvars_sha256",
        "credential_claim_sha256",
        "review_sha256",
        "plan_sha256",
        "state",
        "exact_owner_assertion",
        "authorization_contract",
        "authorization_template",
        "maximum_validity_seconds",
        "evidence_expiration",
        "does_not_authorize",
        "evidence_payload_sha256",
    }
    exact_keys(request, request_keys, "foundation approval request")
    require_payload_hash(request, "foundation approval request")
    if (
        type(request["schema_version"]) is not int
        or request["schema_version"] != 1
        or request["contract"] != "cosmas-os-d3-foundation-plan-approval-request-v1"
        or request["artifact_status"] != "IMMUTABLE_EXACT_PLAN_APPROVAL_REQUEST_NOT_AUTHORITY"
        or request["authorization_contract"] != "cosmas-os-d3-foundation-plan-authorization-v1"
        or type(request["maximum_validity_seconds"]) is not int
        or request["maximum_validity_seconds"] != 1800
        or request["does_not_authorize"]
        != [
            "a different or regenerated plan",
            "Terraform apply before append-only claim",
            "workloads",
            "DNS or Clerk mutation",
        ]
    ):
        fail("foundation approval request contract/policy is invalid")
    if (
        any(
            request[field] != approval[field]
            for field in (
                "source_sha",
                "release_id",
                "plan_sha256",
                "review_sha256",
                "readiness_payload_sha256",
                "foundation_package_manifest_sha256",
            )
        )
        or request["foundation_tfvars_sha256"] != approval["variable_file_sha256"]
    ):
        fail("foundation approval request binding is invalid")
    validate_reduced_state(request["state"], state, "foundation approval request")
    require_hash(request["credential_claim_sha256"], "foundation credential claim sha256")
    if request["foundation_package_id"] != approval["readiness_payload_sha256"]:
        fail("foundation approval request package ID is invalid")
    template = request["authorization_template"]
    expected_template_name = (
        f"foundation-plan-authorization-{approval['source_sha'][:7]}.template.json"
    )
    expected_template = {
        "schema_version": 1,
        "contract": "cosmas-os-d3-foundation-plan-authorization-v1",
        "authorization_status": "PENDING_NOT_AUTHORITY",
        "source_sha": approval["source_sha"],
        "release_id": approval["release_id"],
        "plan_sha256": None,
        "review_sha256": None,
        "state_lineage": None,
        "state_serial": None,
        "owner_assertion": None,
        "reviewer_reference": None,
        "approved_at": None,
        "expires_at": None,
    }
    expected_template_sha256 = hashlib.sha256(
        (json.dumps(expected_template, ensure_ascii=False, indent=2) + "\n").encode()
    ).hexdigest()
    if (
        not isinstance(template, dict)
        or set(template) != {"path", "sha256"}
        or not isinstance(template["path"], str)
        or Path(template["path"]).name != expected_template_name
        or template["sha256"] != expected_template_sha256
    ):
        fail("foundation approval request authorization template is invalid")
    if (
        request["exact_owner_assertion"] != approval["owner_assertion"]
        or file_hash(request_path) != approval["approval_request_sha256"]
    ):
        fail("foundation approval request state/assertion/hash binding is invalid")
    expiry = request.get("evidence_expiration")
    expected_expiry = {
        "readiness_expires_at": approval["readiness_expires_at"],
        "human_review_expires_at": approval["human_review_expires_at"],
        "cost_expires_at": approval["cost_expires_at"],
        "earliest_evidence_expires_at": min(
            (
                parse_timestamp(approval[field], field),
                approval[field],
            )
            for field in (
                "readiness_expires_at",
                "human_review_expires_at",
                "cost_expires_at",
            )
        )[1],
    }
    if expiry != expected_expiry:
        fail("foundation approval request expiry binding is invalid")

    claim_keys = {
        "schema_version",
        "contract",
        "status",
        "source_sha",
        "release_id",
        "plan_sha256",
        "review_sha256",
        "approval_request_sha256",
        "authorization_sha256",
        "credential_claim_sha256",
        "readiness_payload_sha256",
        "human_review_payload_sha256",
        "cost_evidence_payload_sha256",
        "readiness_expires_at",
        "human_review_expires_at",
        "cost_expires_at",
        "owner_expires_at",
        "effective_expires_at",
        "claimed_at",
        "reviewer_reference_sha256",
        "evidence_payload_sha256",
    }
    exact_keys(claim, claim_keys, "foundation authorization claim")
    require_payload_hash(claim, "foundation authorization claim")
    if (
        type(claim["schema_version"]) is not int
        or claim["schema_version"] != 1
        or claim["contract"] != "cosmas-os-d3-foundation-plan-claim-v1"
        or claim["status"] != "CLAIMED_FOR_EXACT_PROTECTED_APPLY"
    ):
        fail("foundation authorization claim contract is invalid")
    if claim["credential_claim_sha256"] != request["credential_claim_sha256"]:
        fail("foundation authorization claim credential binding is invalid")
    direct_bindings = (
        "source_sha",
        "release_id",
        "plan_sha256",
        "review_sha256",
        "approval_request_sha256",
        "authorization_sha256",
        "readiness_payload_sha256",
        "human_review_payload_sha256",
        "cost_evidence_payload_sha256",
        "readiness_expires_at",
        "human_review_expires_at",
        "cost_expires_at",
        "owner_expires_at",
        "claimed_at",
    )
    if any(claim[field] != approval[field] for field in direct_bindings):
        fail("foundation authorization claim binding is invalid")
    if (
        claim["effective_expires_at"] != approval["expires_at"]
        or file_hash(claim_path) != approval["authorization_claim_sha256"]
    ):
        fail("foundation authorization claim hash/effective expiry is invalid")
    if (
        claim["reviewer_reference_sha256"]
        != hashlib.sha256(str(owner["reviewer_reference"]).encode()).hexdigest()
    ):
        fail("foundation authorization claim reviewer binding is invalid")

    manifest_keys = {
        "schema_version",
        "contract",
        "status",
        "source_sha",
        "release_id",
        "plan_sha256",
        "review_sha256",
        "foundation_package_id",
        "foundation_package_manifest_sha256",
        "foundation_tfvars_sha256",
        "owner_authorization",
        "effective_expires_at",
        "upstream_expiration",
        "files",
        "append_only",
        "does_not_execute_apply",
        "evidence_payload_sha256",
    }
    exact_keys(manifest, manifest_keys, "foundation authorization manifest")
    require_payload_hash(manifest, "foundation authorization manifest")
    expected_files = {name: file_hash(bundle / name) for name in BUNDLE_FILES - {"manifest.json"}}
    if manifest["files"] != expected_files or any(
        manifest[field] != approval[field]
        for field in ("source_sha", "release_id", "plan_sha256", "review_sha256")
    ):
        fail("foundation authorization manifest file/source binding is invalid")
    if (
        type(manifest["schema_version"]) is not int
        or manifest["schema_version"] != 1
        or manifest["contract"] != "cosmas-os-d3-foundation-apply-authorization-bundle-v1"
        or manifest["status"] != "CLAIMED_READY_FOR_EXACT_PROTECTED_APPLY"
        or manifest["foundation_package_id"] != request["foundation_package_id"]
        or manifest["foundation_tfvars_sha256"] != approval["variable_file_sha256"]
        or manifest["foundation_package_manifest_sha256"]
        != approval["foundation_package_manifest_sha256"]
        or manifest["effective_expires_at"] != approval["expires_at"]
        or manifest["upstream_expiration"] != expected_expiry
    ):
        fail("foundation authorization manifest deployment binding is invalid")
    owner_summary = {
        "sha256": approval["authorization_sha256"],
        "approved_at": approval["approved_at"],
        "expires_at": approval["owner_expires_at"],
        "claimed_at": approval["claimed_at"],
    }
    if (
        manifest["owner_authorization"] != owner_summary
        or manifest["append_only"] is not True
        or manifest["does_not_execute_apply"] is not True
    ):
        fail("foundation authorization manifest owner/safety binding is invalid")
    if parse_timestamp(claim["claimed_at"], "claim claimed_at") > now:
        fail("foundation authorization claim is in the future")


def validate_later_bundle(
    bundle: Path, approval: dict[str, Any], state: dict[str, object], now: datetime
) -> None:
    request_path = bundle / "approval-request.json"
    owner_path = bundle / "owner-authorization.json"
    claim_path = bundle / "claim.json"
    manifest_path = bundle / "manifest.json"
    request = load_strict(request_path, "apply approval request")
    owner = load_strict(owner_path, "owner authorization")
    claim = load_strict(claim_path, "authorization claim")
    manifest = load_strict(manifest_path, "authorization manifest")
    base = {
        "source_sha": approval["source_sha"],
        "release_id": approval["release_id"],
        "stage": approval["stage"],
        "plan_sha256": approval["plan_sha256"],
        "review_sha256": approval["review_sha256"],
        "variable_file_sha256": approval["variable_file_sha256"],
        "state": state,
    }
    for document, label in (
        (request, "apply approval request"),
        (owner, "owner authorization"),
        (claim, "authorization claim"),
        (manifest, "authorization manifest"),
    ):
        if isinstance(document, dict) and "state" in document:
            validate_state(document["state"], state, label)
    request_keys = {
        "schema_version",
        "contract",
        "status",
        *base,
        "exact_owner_assertion",
        "maximum_validity_seconds",
        "does_not_authorize",
        "evidence_payload_sha256",
    }
    exact_keys(request, request_keys, "apply approval request")
    require_payload_hash(request, "apply approval request")
    if (
        type(request["schema_version"]) is not int
        or request["schema_version"] != 2
        or request["contract"] != "cosmas-os-d3-protected-apply-request-v2"
        or request["status"] != "PENDING_OWNER_AUTHORIZATION"
        or any(request[key] != value for key, value in base.items())
        or request["exact_owner_assertion"] != approval["owner_assertion"]
        or type(request["maximum_validity_seconds"]) is not int
        or request["maximum_validity_seconds"] != 1800
        or request["does_not_authorize"] is not True
    ):
        fail("apply approval request contract/binding is invalid")
    owner_keys = {
        "schema_version",
        "contract",
        "authorization_status",
        *base,
        "owner_assertion",
        "reviewer",
        "approved_at",
        "expires_at",
    }
    exact_keys(owner, owner_keys, "owner authorization")
    if (
        type(owner["schema_version"]) is not int
        or owner["schema_version"] != 2
        or owner["contract"] != "cosmas-os-d3-protected-owner-authorization-v2"
        or owner["authorization_status"] != "APPROVED"
        or any(owner[key] != value for key, value in base.items())
        or owner["owner_assertion"] != approval["owner_assertion"]
        or owner["reviewer"] != approval["reviewer"]
        or owner["approved_at"] != approval["approved_at"]
        or owner["expires_at"] != approval["owner_expires_at"]
    ):
        fail("owner authorization contract/binding is invalid")
    if (
        file_hash(owner_path) != approval["authorization_sha256"]
        or file_hash(request_path) != approval["approval_request_sha256"]
    ):
        fail("authorization/request file hash is invalid")
    claim_keys = {
        "schema_version",
        "contract",
        "status",
        *base,
        "approval_request_sha256",
        "authorization_sha256",
        "claimed_at",
        "owner_expires_at",
        "effective_expires_at",
        "reviewer_reference_sha256",
        "evidence_payload_sha256",
    }
    exact_keys(claim, claim_keys, "authorization claim")
    require_payload_hash(claim, "authorization claim")
    claim_expected = {
        **base,
        "approval_request_sha256": approval["approval_request_sha256"],
        "authorization_sha256": approval["authorization_sha256"],
        "claimed_at": approval["claimed_at"],
        "owner_expires_at": approval["owner_expires_at"],
        "effective_expires_at": approval["expires_at"],
        "reviewer_reference_sha256": hashlib.sha256(str(approval["reviewer"]).encode()).hexdigest(),
    }
    if (
        type(claim["schema_version"]) is not int
        or claim["schema_version"] != 2
        or claim["contract"] != "cosmas-os-d3-protected-apply-claim-v2"
        or claim["status"] != "CLAIMED_FOR_EXACT_PROTECTED_APPLY"
        or any(claim[key] != value for key, value in claim_expected.items())
        or file_hash(claim_path) != approval["authorization_claim_sha256"]
    ):
        fail("authorization claim binding is invalid")
    manifest_keys = {
        "schema_version",
        "contract",
        "status",
        *base,
        "authorization_bundle_id",
        "owner_authorization",
        "files",
        "append_only",
        "does_not_execute_apply",
        "evidence_payload_sha256",
    }
    exact_keys(manifest, manifest_keys, "authorization manifest")
    require_payload_hash(manifest, "authorization manifest")
    expected_files = {name: file_hash(bundle / name) for name in BUNDLE_FILES - {"manifest.json"}}
    owner_summary = {
        "sha256": approval["authorization_sha256"],
        "approved_at": approval["approved_at"],
        "expires_at": approval["owner_expires_at"],
        "claimed_at": approval["claimed_at"],
    }
    if (
        type(manifest["schema_version"]) is not int
        or manifest["schema_version"] != 2
        or manifest["contract"] != "cosmas-os-d3-protected-apply-bundle-v2"
        or manifest["status"] != "CLAIMED_READY_FOR_EXACT_PROTECTED_APPLY"
        or any(manifest[key] != value for key, value in base.items())
        or manifest["authorization_bundle_id"] != approval["authorization_bundle_id"]
        or manifest["owner_authorization"] != owner_summary
        or manifest["files"] != expected_files
        or manifest["append_only"] is not True
        or manifest["does_not_execute_apply"] is not True
    ):
        fail("authorization manifest binding is invalid")
    if parse_timestamp(claim["claimed_at"], "claim claimed_at") > now:
        fail("authorization claim is in the future")


def main() -> int:
    args = parse_args()
    if (
        SOURCE_RE.fullmatch(args.source_sha) is None
        or RELEASE_RE.fullmatch(args.release_id) is None
    ):
        fail("expected source/release binding is invalid")
    for field in ("plan_sha256", "review_sha256", "variable_file_sha256"):
        require_hash(getattr(args, field), f"expected {field}")
    if args.bundle_dir.is_symlink() or args.approval.is_symlink():
        fail("approval bundle and source approval must not be symlinks")
    bundle = args.bundle_dir.resolve(strict=True)
    approval_path = args.approval.resolve(strict=True)
    if not bundle.is_dir() or approval_path != bundle / "source-approval.json":
        fail("approval must be the fixed source-approval.json inside its bundle")
    entries = list(bundle.iterdir())
    if {item.name for item in entries} != BUNDLE_FILES or any(
        item.is_symlink() or not item.is_file() for item in entries
    ):
        fail("authorization bundle files do not exactly match the selected contract")
    approval = load_strict(approval_path, "source approval")
    foundation = args.stage == "foundation"
    exact_keys(approval, FOUNDATION_KEYS if foundation else COMMON_KEYS, "source approval")
    expected_contract = FOUNDATION_CONTRACT if foundation else LATER_CONTRACT
    if (
        type(approval["schema_version"]) is not int
        or approval["schema_version"] != 2
        or approval["contract"] != expected_contract
        or approval["authorization_status"] != "APPROVED"
    ):
        fail("source approval contract/status is invalid")
    if (
        approval["source_sha"] != args.source_sha
        or approval["release_id"] != args.release_id
        or approval["stage"] != args.stage
    ):
        fail("source approval source/release/stage binding is invalid")
    for field in ("plan_sha256", "review_sha256", "variable_file_sha256"):
        require_hash(approval[field], field)
        if approval[field] != getattr(args, field):
            fail(f"source approval {field} binding is invalid")
    state = expected_state(args)
    validate_state(approval["state"], state, "source approval")
    reviewer = approval["reviewer"]
    if (
        not isinstance(reviewer, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/ -]{2,127}", reviewer) is None
        or "@" in reviewer
    ):
        fail("source approval reviewer is invalid")
    assertion = f"AUTHORIZE D3 {args.stage.upper()} APPLY {args.plan_sha256} {args.review_sha256}"
    if approval["owner_assertion"] != assertion:
        fail("source approval owner assertion is invalid")
    authorization_sha = require_hash(approval["authorization_sha256"], "authorization_sha256")
    if approval["review_reference"] != f"owner-authorization:sha256:{authorization_sha}":
        fail("source approval review reference is invalid")
    for field in (
        "authorization_claim_sha256",
        "approval_request_sha256",
        "evidence_payload_sha256",
    ):
        require_hash(approval[field], field)
    if (
        approval["authorization_bundle_id"] != args.plan_sha256
        or bundle.name != approval["authorization_bundle_id"]
    ):
        fail("source approval bundle path/ID is not the exact plan hash")
    if foundation:
        for field in (
            "readiness_payload_sha256",
            "human_review_payload_sha256",
            "cost_evidence_payload_sha256",
            "foundation_package_manifest_sha256",
        ):
            require_hash(approval[field], field)
    approved_at = parse_timestamp(approval["approved_at"], "approved_at")
    claimed_at = parse_timestamp(approval["claimed_at"], "claimed_at")
    now = parse_timestamp(args.now, "now") if args.now else datetime.now(UTC).replace(microsecond=0)
    owner_expires_at = parse_timestamp(approval["owner_expires_at"], "owner_expires_at")
    expiry_fields = ["owner_expires_at"] + (
        ["readiness_expires_at", "human_review_expires_at", "cost_expires_at"] if foundation else []
    )
    expiries = [parse_timestamp(approval[field], field) for field in expiry_fields]
    effective = parse_timestamp(approval["expires_at"], "expires_at")
    if (
        effective != min(expiries)
        or not approved_at <= claimed_at <= now
        or now >= effective
        or any(now >= expiry for expiry in expiries)
    ):
        fail("source approval chronology or expiry is invalid")
    if owner_expires_at <= approved_at or (owner_expires_at - approved_at).total_seconds() > 1800:
        fail("owner approval window must be positive and no longer than 30 minutes")
    require_payload_hash(approval, "source approval", trailing_lf=False)
    if foundation:
        validate_foundation_bundle(bundle, approval, state, now)
    else:
        validate_later_bundle(bundle, approval, state, now)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"D3 deployment guard refused: {exc}", file=__import__("sys").stderr)
        raise SystemExit(1) from None
