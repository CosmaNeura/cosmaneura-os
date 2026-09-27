"""Exercise the real native service against the current OS wire contracts.

Uses invented API receipts and native credentials. No network, Keychain, app
installation or audio source is used.
"""

import base64
import json
import platform
import subprocess
from pathlib import Path
from uuid import UUID

import pytest

from cosmas_os.api.capture_schemas import CaptureOperationRequest
from cosmas_os.ports.capture_protocol import (
    EncryptionKey,
    KeyReceipt,
    LeaseReceipt,
    NativeRecordingContext,
    ReservationReceipt,
)

pytestmark = pytest.mark.skipif(platform.system() != "Darwin", reason="Apple native service")
ROOT = Path(__file__).parents[2]
KINDS = ["encryption_key", "bind_key", "issue_lease", "renew_lease", "reserve_chunks"]


def uid(value):
    return f"00000000-0000-4000-8000-{value:012d}"


@pytest.fixture(scope="module")
def probe(tmp_path_factory):
    build = tmp_path_factory.mktemp("native-recording-service")
    auth = ROOT / "clients/apple/native-auth"
    recording = ROOT / "clients/capture/native-recording"
    compiler = ["/usr/bin/xcrun", "swiftc", "-swift-version", "6", "-parse-as-library",
                "-target", f"{platform.machine()}-apple-macosx14.0",
                "-module-cache-path", str(build / "modules")]
    for module, source in [("CosmasNativeAuth", auth), ("CosmaneuraNativeRecording", recording)]:
        command = [*compiler, "-emit-library", "-emit-module", "-module-name", module,
                   "-emit-module-path", str(build / f"{module}.swiftmodule"),
                   "-o", str(build / f"lib{module}.dylib"),
                   *map(str, sorted((source / "Sources" / module).glob("*.swift")))]
        result = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
        assert result.returncode == 0, result.stdout + result.stderr
    command = [*compiler, "-I", str(build), "-L", str(build),
               "-lCosmasNativeAuth", "-lCosmaneuraNativeRecording",
               "-Xlinker", "-rpath", "-Xlinker", str(build), "-o", str(build / "probe"),
               *[str(auth / "Bridge" / name) for name in [
                   "NativeProviderConnection.swift", "WorkspaceSourceTransport.swift",
                   "NativeProviderRecordingService.swift"]],
               str(ROOT / "tests/fixtures/native_recording_service.swift")]
    result = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    return build / "probe"


@pytest.fixture(scope="module")
def fixture():
    tenant, workspace, session, lease = uid(100), uid(101), uid(102), uid(103)
    def envelope(kind, receipt):
        return {"workspace_id": workspace, "session_id": session,
                "operation": kind, "receipt": receipt.model_dump(mode="json")}
    issued, expires, renewed = (
        "2026-09-27T12:00:00Z", "2026-09-27T12:15:00Z", "2026-09-27T12:20:00Z")
    rows = []
    for sequence in range(2):
        object_id = uid(110 + sequence)
        aad = json.dumps({"tenant_id": tenant, "session_id": session, "object_id": object_id,
                          "channel": "microphone", "sequence_number": sequence},
                         sort_keys=True, separators=(",", ":")).encode()
        rows.append({"protocol_version": "1.0", "object_id": object_id, "session_id": session,
                     "channel": "microphone", "sequence_number": sequence,
                     "additional_authenticated_data": base64.urlsafe_b64encode(aad).decode().rstrip("="),
                     "created_at": issued})
    return {
        "workspace_id": workspace, "session_id": session,
        "envelopes": {
            "native_recording_context": envelope("native_recording_context", NativeRecordingContext(
                schema_version="1.0", workspace_id=workspace, session_id=session,
                tenant_id=tenant, status="created")),
            "encryption_key": envelope("encryption_key", EncryptionKey(
                key_version="synthetic", algorithm="RSA-OAEP-256",
                public_jwk={"kty": "RSA", "n": base64.urlsafe_b64encode(bytes([129]) * 384).decode(),
                            "e": "AQAB", "alg": "RSA-OAEP-256", "ext": True, "key_ops": ["wrapKey"]})),
            "bind_key": envelope("bind_key", KeyReceipt(
                session_id=session, key_version="synthetic", created_at=issued)),
            "issue_lease": envelope("issue_lease", LeaseReceipt(
                receipt_id=uid(104), lease_id=lease, session_id=session, generation=1,
                issued_at=issued, expires_at=expires)),
            "renew_lease": envelope("renew_lease", LeaseReceipt(
                receipt_id=uid(105), lease_id=lease, session_id=session, generation=2,
                issued_at="2026-09-27T12:05:00Z", expires_at=renewed)),
            "reserve_chunks": envelope("reserve_chunks", ReservationReceipt(
                batch_id=uid(106), session_id=session, capture_authorized_until=renewed,
                reservations=rows)),
        },
    }


def run(probe, fixture, operation="", fault=""):
    value = {**fixture, "fault": {"operation": operation, "kind": fault}}
    result = subprocess.run([str(probe)], input=json.dumps(value), capture_output=True,
                            text=True, timeout=15, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def test_native_service_emits_current_os_contracts(probe, fixture):
    result = run(probe, fixture)
    assert result["failure"] is None
    assert result["completed"] == KINDS
    assert result["renderer_rejected"] and result["confused_action_rejected"]
    assert [row["kind"] for row in result["requests"]] == ["native_recording_context", *KINDS]
    for row in result["requests"]:
        request = CaptureOperationRequest.model_validate(row["body"])
        assert str(request.session_id) == fixture["session_id"]
        assert request.operation.kind == row["kind"]
        assert str(UUID(request.idempotency_key)) == request.idempotency_key
        assert row["url"] == f'https://api.example.invalid/workspaces/{fixture["workspace_id"]}/capture/operations'
        headers = {key.lower(): value for key, value in row["headers"].items()}
        assert headers["x-cosmas-workspace-protocol"] == "1"
        assert headers["x-cosmas-draft-recovery"] == "2"
        assert headers["origin"] == "app://cosmas"
        assert headers["cache-control"] == "no-store"
    requests = {row["kind"]: row["body"]["operation"] for row in result["requests"]}
    assert requests["renew_lease"]["payload"]["expected_generation"] == 1
    assert requests["reserve_chunks"]["payload"]["capture_lease_generation"] == 2
    assert requests["reserve_chunks"]["payload"]["count"] == 2


@pytest.mark.parametrize(("operation", "fault"), [
    ("encryption_key", "algorithm"), ("encryption_key", "jwk_boolean"),
    ("bind_key", "version"), ("bind_key", "receipt_session"),
    ("issue_lease", "generation"), ("renew_lease", "lease"),
    ("reserve_chunks", "deadline"), ("reserve_chunks", "count"),
    ("reserve_chunks", "sequence"), ("reserve_chunks", "aad"),
    ("reserve_chunks", "duplicate"),
    *[("renew_lease", fault) for fault in [
        "workspace", "session", "operation", "extra", "signout", "organization",
        "401", "403", "409", "422", "503"]],
])
def test_native_service_stops_on_unbound_or_denied_response(probe, fixture, operation, fault):
    result = run(probe, fixture, operation, fault)
    assert result["completed"] == KINDS[:KINDS.index(operation)]
    assert result["failure"]
    assert result["requests"][-1]["kind"] == operation
    if fault in {"401", "403", "409", "422"}:
        assert result["failure"] == "authorityChanged"
    elif fault == "503":
        assert result["failure"] == "unavailable"
