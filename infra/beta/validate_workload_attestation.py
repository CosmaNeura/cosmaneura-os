#!/usr/bin/env python3
"""Fail-closed validation of a resident D3 workload-verification attestation."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import stat
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

_CONTRACT = "cosmas-os-d3-workload-verification-v1"
_MAX_AGE = timedelta(hours=1)
_MAX_FUTURE_SKEW = timedelta(minutes=5)
_UTC = timezone.utc  # noqa: UP017 -- protected runner supports Python 3.10.
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_LOCATION = re.compile(r"^[a-z][a-z0-9]{2,31}$")
_RELEASE = re.compile(r"^[a-z0-9][a-z0-9-]{2,31}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_SHA = re.compile(r"^[0-9a-f]{40}$")
_UTC_TIMESTAMP = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
_TOP_LEVEL_KEYS = {
    "api_ready_verified",
    "box_id",
    "completed_at",
    "contract",
    "evidence_payload_sha256",
    "exact_revisions_and_images_verified",
    "exact_runtime_configuration_verified",
    "images",
    "managed_environment_verified",
    "person_or_patient_identifiers_returned",
    "release_id",
    "revision_id_sha256",
    "schema_version",
    "secrets_returned",
    "single_revision_traffic_verified",
    "source_sha",
    "state",
    "status",
    "synthetic_box_id_returned",
    "web_health_verified",
    "worker_private_and_ready",
    "worker_probe_configuration_verified",
}
_TRUE_ASSERTIONS = {
    "api_ready_verified",
    "exact_revisions_and_images_verified",
    "exact_runtime_configuration_verified",
    "managed_environment_verified",
    "single_revision_traffic_verified",
    "synthetic_box_id_returned",
    "web_health_verified",
    "worker_private_and_ready",
    "worker_probe_configuration_verified",
}
_FALSE_ASSERTIONS = {"person_or_patient_identifiers_returned", "secrets_returned"}
_PROFILE_KEYS = {"location", "api_max_replicas"}


class WorkloadAttestationError(RuntimeError):
    """The resident workload attestation is absent, unsafe, stale, or invalid."""


@dataclass(frozen=True)
class ExpectedBinding:
    source_sha: str
    release_id: str
    state_lineage: str
    state_serial: int
    state_sha256: str
    box_id: str
    api_digest: str
    web_digest: str
    location: str = "centralus"
    api_max_replicas: int = 2

    def validated(self) -> ExpectedBinding:
        if not all(
            isinstance(value, str)
            for value in (
                self.source_sha,
                self.release_id,
                self.state_lineage,
                self.state_sha256,
                self.box_id,
                self.api_digest,
                self.web_digest,
                self.location,
            )
        ):
            raise WorkloadAttestationError("invalid expected binding")
        try:
            lineage = str(UUID(self.state_lineage))
            box_id = str(UUID(self.box_id))
        except ValueError as error:
            raise WorkloadAttestationError("invalid expected binding") from error
        if (
            not _SOURCE_SHA.fullmatch(self.source_sha)
            or not _RELEASE.fullmatch(self.release_id)
            or type(self.state_serial) is not int
            or self.state_serial < 0
            or not _SHA256.fullmatch(self.state_sha256)
            or not _DIGEST.fullmatch(self.api_digest)
            or not _DIGEST.fullmatch(self.web_digest)
            or self.api_digest == self.web_digest
            or not _LOCATION.fullmatch(self.location)
            or type(self.api_max_replicas) is not int
            or self.api_max_replicas not in {1, 2}
        ):
            raise WorkloadAttestationError("invalid expected binding")
        return ExpectedBinding(
            source_sha=self.source_sha,
            release_id=self.release_id,
            state_lineage=lineage,
            state_serial=self.state_serial,
            state_sha256=self.state_sha256,
            box_id=box_id,
            api_digest=self.api_digest,
            web_digest=self.web_digest,
            location=self.location,
            api_max_replicas=self.api_max_replicas,
        )


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise WorkloadAttestationError("duplicate JSON key")
        result[key] = value
    return result


def _invalid_constant(_: str) -> None:
    raise WorkloadAttestationError("invalid JSON constant")


def _canonical_sha256(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def validate_attestation(
    evidence: object,
    expected: ExpectedBinding,
    *,
    observed_at: datetime | None = None,
) -> None:
    expected = expected.validated()
    observed_at = datetime.now(_UTC) if observed_at is None else observed_at
    if observed_at.tzinfo is None:
        raise WorkloadAttestationError("invalid workload attestation observation time")
    observed_at = observed_at.astimezone(_UTC)
    if not isinstance(evidence, dict) or set(evidence) not in (
        _TOP_LEVEL_KEYS,
        _TOP_LEVEL_KEYS | _PROFILE_KEYS,
    ):
        raise WorkloadAttestationError("invalid workload attestation shape")
    # Old v1 attestations proved only Central US with a two-replica API cap.
    # They cannot qualify another region or cap. Current producers bind both.
    if (
        evidence.get("location", "centralus") != expected.location
        or type(evidence.get("api_max_replicas", 2)) is not int
        or evidence.get("api_max_replicas", 2) != expected.api_max_replicas
    ):
        raise WorkloadAttestationError("stale workload attestation profile binding")
    if (
        type(evidence["schema_version"]) is not int
        or evidence["schema_version"] != 1
        or evidence["contract"] != _CONTRACT
        or evidence["status"] != "verified"
        or evidence["source_sha"] != expected.source_sha
        or evidence["release_id"] != expected.release_id
    ):
        raise WorkloadAttestationError("stale workload attestation release binding")
    try:
        if not isinstance(evidence["completed_at"], str) or not _UTC_TIMESTAMP.fullmatch(
            evidence["completed_at"]
        ):
            raise ValueError
        completed_at = datetime.strptime(evidence["completed_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=_UTC
        )
        if not isinstance(evidence["box_id"], str):
            raise ValueError
        evidence_box_id = str(UUID(evidence["box_id"]))
    except (TypeError, ValueError) as error:
        raise WorkloadAttestationError("invalid workload attestation identity") from error
    if evidence["box_id"] != evidence_box_id or evidence_box_id != expected.box_id:
        raise WorkloadAttestationError("stale workload attestation Box binding")
    if completed_at > observed_at + _MAX_FUTURE_SKEW or completed_at < observed_at - _MAX_AGE:
        raise WorkloadAttestationError("stale workload attestation completion time")
    state_binding = evidence["state"]
    if (
        not isinstance(state_binding, dict)
        or set(state_binding) != {"exists", "lineage", "serial", "sha256"}
        or state_binding["exists"] is not True
        or not isinstance(state_binding["lineage"], str)
        or state_binding["lineage"] != expected.state_lineage
        or type(state_binding["serial"]) is not int
        or state_binding["serial"] != expected.state_serial
        or not isinstance(state_binding["sha256"], str)
        or state_binding["sha256"] != expected.state_sha256
    ):
        raise WorkloadAttestationError("stale workload attestation state binding")
    if evidence["images"] != {
        "api": expected.api_digest,
        "worker": expected.api_digest,
        "web": expected.web_digest,
    }:
        raise WorkloadAttestationError("stale workload attestation image binding")
    revisions = evidence["revision_id_sha256"]
    if (
        not isinstance(revisions, dict)
        or set(revisions) != {"api", "web", "worker"}
        or any(
            not isinstance(value, str) or not _SHA256.fullmatch(value)
            for value in revisions.values()
        )
    ):
        raise WorkloadAttestationError("invalid workload attestation revision binding")
    if any(evidence[key] is not True for key in _TRUE_ASSERTIONS) or any(
        evidence[key] is not False for key in _FALSE_ASSERTIONS
    ):
        raise WorkloadAttestationError("unsuccessful workload attestation")
    stored_hash = evidence["evidence_payload_sha256"]
    if not isinstance(stored_hash, str) or not _SHA256.fullmatch(stored_hash):
        raise WorkloadAttestationError("invalid workload attestation self-hash")
    payload = dict(evidence)
    del payload["evidence_payload_sha256"]
    if not hmac.compare_digest(stored_hash, _canonical_sha256(payload)):
        raise WorkloadAttestationError("modified workload attestation")


def load_and_validate_attestation(
    path: Path,
    expected: ExpectedBinding,
    *,
    require_protected_metadata: bool = True,
    observed_at: datetime | None = None,
) -> None:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise WorkloadAttestationError("workload attestation is unavailable") from error
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise WorkloadAttestationError("workload attestation is not a regular file")
        if require_protected_metadata and (
            metadata.st_uid != 0 or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            raise WorkloadAttestationError("workload attestation metadata is unsafe")
        if metadata.st_size < 1 or metadata.st_size > 16384:
            raise WorkloadAttestationError("workload attestation size is invalid")
        chunks: list[bytes] = []
        remaining = metadata.st_size
        while remaining:
            chunk = os.read(descriptor, remaining)
            if not chunk:
                raise WorkloadAttestationError("workload attestation changed while reading")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise WorkloadAttestationError("workload attestation changed while reading")
        raw = b"".join(chunks)
    finally:
        os.close(descriptor)
    if not raw or len(raw) != metadata.st_size:
        raise WorkloadAttestationError("workload attestation size is invalid")
    try:
        evidence = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_invalid_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise WorkloadAttestationError("workload attestation is not strict JSON") from error
    validate_attestation(evidence, expected, observed_at=observed_at)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) not in {9, 11}:
        return 1
    try:
        if len(arguments) == 11 and arguments[10] not in {"1", "2"}:
            return 1
        state_serial = int(arguments[4])
        expected = ExpectedBinding(
            source_sha=arguments[1],
            release_id=arguments[2],
            state_lineage=arguments[3],
            state_serial=state_serial,
            state_sha256=arguments[5],
            box_id=arguments[6],
            api_digest=arguments[7],
            web_digest=arguments[8],
            location=arguments[9] if len(arguments) == 11 else "centralus",
            api_max_replicas=int(arguments[10]) if len(arguments) == 11 else 2,
        )
        load_and_validate_attestation(Path(arguments[0]), expected)
    except (ValueError, WorkloadAttestationError):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
