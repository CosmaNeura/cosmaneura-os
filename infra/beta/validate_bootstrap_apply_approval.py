#!/usr/bin/env python3
"""Strict validation for the local-state bootstrap mutation authorization."""

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
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
TIME_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
UTC = timezone.utc  # noqa: UP017 -- protected runner supports Python 3.10.
CONTRACT = "cosmas-os-d3-bootstrap-protected-apply-authorization-v2"
KEYS = {
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
    "approved_at",
    "expires_at",
    "evidence_payload_sha256",
}


def fail(message: str) -> NoReturn:
    raise ValueError(message)


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            fail(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def require_hash(value: object, field: str) -> str:
    if not isinstance(value, str) or HASH_RE.fullmatch(value) is None:
        fail(f"{field} must be a lowercase SHA-256")
    return value


def timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str) or TIME_RE.fullmatch(value) is None:
        fail(f"{field} must be a UTC timestamp")
    try:
        return datetime.strptime(value, TIME_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        fail(f"{field} must be an exact UTC second timestamp")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("approval", type=Path)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--review-sha256", required=True)
    parser.add_argument("--variable-file-sha256", required=True)
    parser.add_argument("--state-exists", choices=("true", "false"), required=True)
    parser.add_argument("--state-lineage", default="")
    parser.add_argument("--state-serial", default="null")
    parser.add_argument("--state-sha256", default="")
    parser.add_argument("--now")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if SOURCE_RE.fullmatch(args.source_sha) is None:
        fail("expected source SHA is invalid")
    expected_hashes = {
        field: require_hash(getattr(args, field), f"expected {field}")
        for field in ("plan_sha256", "review_sha256", "variable_file_sha256")
    }
    if args.approval.is_symlink() or not args.approval.is_file():
        fail("bootstrap approval is unavailable or unsafe")
    raw = args.approval.read_bytes()
    if len(raw) > 16_384:
        fail("bootstrap approval exceeds 16 KiB")
    try:
        approval = json.loads(
            raw,
            object_pairs_hook=unique_object,
            parse_constant=lambda value: fail(f"invalid JSON constant: {value}"),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"bootstrap approval is not strict JSON: {exc}")
    if not isinstance(approval, dict) or set(approval) != KEYS:
        fail("bootstrap approval keys do not exactly match the v2 contract")
    if type(approval["schema_version"]) is not int or approval["schema_version"] != 2:
        fail("bootstrap approval schema version is invalid")
    if approval["contract"] != CONTRACT or approval["authorization_status"] != "APPROVED":
        fail("bootstrap approval contract or status is invalid")
    if (
        approval["source_sha"] != args.source_sha
        or approval["release_id"] != "bootstrap"
        or approval["stage"] != "bootstrap"
    ):
        fail("bootstrap approval source/stage binding is invalid")
    for field, expected in expected_hashes.items():
        require_hash(approval[field], field)
        if approval[field] != expected:
            fail(f"bootstrap approval {field} binding is invalid")

    state_exists = args.state_exists == "true"
    if state_exists:
        try:
            lineage = str(UUID(args.state_lineage))
            serial = int(args.state_serial)
        except ValueError:
            fail("expected bootstrap state binding is invalid")
        if serial < 0 or str(serial) != args.state_serial:
            fail("expected bootstrap state serial is invalid")
        state_sha = require_hash(args.state_sha256, "expected state sha256")
        expected_state: dict[str, object] = {
            "exists": True,
            "lineage": lineage,
            "serial": serial,
            "sha256": state_sha,
        }
    else:
        if args.state_lineage or args.state_serial != "null" or args.state_sha256:
            fail("absent bootstrap state must use null bindings")
        expected_state = {"exists": False, "lineage": None, "serial": None, "sha256": None}
    actual_state = approval["state"]
    if not isinstance(actual_state, dict) or set(actual_state) != {
        "exists",
        "lineage",
        "serial",
        "sha256",
    }:
        fail("bootstrap approval state shape is invalid")
    if type(actual_state["exists"]) is not bool:
        fail("bootstrap approval state existence type is invalid")
    if actual_state["exists"]:
        if not isinstance(actual_state["lineage"], str):
            fail("bootstrap approval state lineage type is invalid")
        try:
            UUID(actual_state["lineage"])
        except ValueError:
            fail("bootstrap approval state lineage is invalid")
        if type(actual_state["serial"]) is not int or actual_state["serial"] < 0:
            fail("bootstrap approval state serial type is invalid")
        require_hash(actual_state["sha256"], "bootstrap approval state sha256")
    elif any(actual_state[field] is not None for field in ("lineage", "serial", "sha256")):
        fail("bootstrap approval absent-state bindings are invalid")
    if actual_state != expected_state:
        fail("bootstrap approval state binding is invalid")

    reviewer = approval["reviewer"]
    if (
        not isinstance(reviewer, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/ -]{2,127}", reviewer) is None
        or "@" in reviewer
    ):
        fail("bootstrap approval reviewer is invalid")
    assertion = f"AUTHORIZE D3 BOOTSTRAP APPLY {args.plan_sha256} {args.review_sha256}"
    if approval["owner_assertion"] != assertion:
        fail("bootstrap owner assertion is invalid")
    if (
        not isinstance(approval["review_reference"], str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/ -]{2,127}", approval["review_reference"])
        is None
        or "@" in approval["review_reference"]
    ):
        fail("bootstrap review reference is invalid")

    approved_at = timestamp(approval["approved_at"], "approved_at")
    expires_at = timestamp(approval["expires_at"], "expires_at")
    now = timestamp(args.now, "now") if args.now else datetime.now(UTC).replace(microsecond=0)
    if approved_at > now or now >= expires_at:
        fail("bootstrap approval is not currently effective")
    if expires_at <= approved_at or (expires_at - approved_at).total_seconds() > 1800:
        fail("bootstrap approval window must be positive and no longer than 30 minutes")

    evidence_hash = require_hash(approval["evidence_payload_sha256"], "evidence_payload_sha256")
    payload = dict(approval)
    del payload["evidence_payload_sha256"]
    if hashlib.sha256(canonical(payload)).hexdigest() != evidence_hash:
        fail("bootstrap approval evidence hash is invalid")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"D3 deployment guard refused: {exc}", file=__import__("sys").stderr)
        raise SystemExit(1) from None
