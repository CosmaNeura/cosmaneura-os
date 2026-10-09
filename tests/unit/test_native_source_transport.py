"""Compile the real Swift request builder and pass its wire through the API gates.

No Clerk initialization, Keychain access, network request, or device is involved.
This covers transport compatibility, not recording or authenticated acceptance.
"""

import base64
import json
import platform
import subprocess
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from cosmas_os.api import app as api
from cosmas_os.api import provider_identity_routes
from cosmas_os.api.workspace_protocol import WorkspaceProtocolBoundary

pytestmark = pytest.mark.skipif(platform.system() != "Darwin", reason="Native Swift transport runs on macOS")
ROOT = Path(__file__).parents[2]


@pytest.fixture(scope="module")
def native_requests(tmp_path_factory):
    build = tmp_path_factory.mktemp("native-source-wire")
    source = ROOT / "clients/apple/native-auth"
    compiler = ["/usr/bin/xcrun", "swiftc", "-swift-version", "6", "-parse-as-library",
                "-target", f"{platform.machine()}-apple-macosx14.0",
                "-module-cache-path", str(build / "modules")]
    commands = [
        [*compiler, "-emit-library", "-emit-module", "-module-name", "CosmasNativeAuth",
         "-emit-module-path", str(build / "CosmasNativeAuth.swiftmodule"),
         "-o", str(build / "libCosmasNativeAuth.dylib"),
         *map(str, sorted((source / "Sources/CosmasNativeAuth").glob("*.swift")))],
        [*compiler, "-I", str(build), "-L", str(build), "-lCosmasNativeAuth",
         "-Xlinker", "-rpath", "-Xlinker", str(build), "-o", str(build / "probe"),
         str(source / "Bridge/NativeProviderConnection.swift"),
         str(source / "Bridge/WorkspaceSourceTransport.swift"),
         str(ROOT / "tests/fixtures/native_source_transport.swift")],
    ]
    for command in commands:
        result = subprocess.run(command, capture_output=True, text=True, timeout=90, check=False)
        assert result.returncode == 0, result.stdout + result.stderr
    result = subprocess.run([str(build / "probe")], capture_output=True, text=True, timeout=10, check=True)
    return {row["kind"]: row for row in json.loads(result.stdout)}


@pytest.fixture
def gated_api(monkeypatch):
    runtime = SimpleNamespace(workspace_available=True, workspace_hosted_enabled=True,
                              workspace_draft_recovery_required=True)
    monkeypatch.setattr(api, "settings", runtime)
    app = FastAPI()
    app.add_middleware(WorkspaceProtocolBoundary, runtime=lambda: runtime)
    received = []

    @app.post("/workspaces/{workspace_id}/capture/operations", dependencies=[Depends(api._workspace_gate)])
    async def probe(request: Request):
        received.append(await request.body())
        return {"admitted": True}

    with TestClient(app) as client:
        yield client, received


@pytest.mark.parametrize("kind", ["source_start", "source_extend", "native_recording_context"])
def test_native_source_wire_passes_current_workspace_gates(native_requests, gated_api, kind):
    wire = native_requests[kind]
    client, received = gated_api
    body = base64.b64decode(wire["body_base64"])
    result = client.request(wire["method"], urlsplit(wire["url"]).path,
                            headers=wire["headers"], content=body)
    assert result.status_code == 200
    assert result.headers["x-cosmas-workspace-protocol"] == "1"
    assert received == [body]
    assert json.loads(body) == {"session_id": "00000000-0000-4000-8000-000000000102",
                               "idempotency_key": "00000000-0000-4000-8000-000000000103"
                               if kind == "native_recording_context" else "synthetic-source-key",
                               "operation": {"kind": kind}}


@pytest.mark.parametrize("kind", ["source_start", "source_extend", "native_recording_context"])
@pytest.mark.parametrize("header", ["x-cosmas-workspace-protocol", "x-cosmas-draft-recovery"])
def test_each_native_protocol_header_remains_required(native_requests, gated_api, kind, header):
    wire = native_requests[kind]
    client, received = gated_api
    headers = {key: value for key, value in wire["headers"].items() if key.lower() != header}
    result = client.request(wire["method"], urlsplit(wire["url"]).path,
                            headers=headers, content=base64.b64decode(wire["body_base64"]))
    assert result.status_code == 426
    assert received == []


def test_native_context_rejects_unbound_receipts_and_authority_changes(native_requests):
    assert native_requests["context_checks"] == {
        "kind": "context_checks", "scenarios": 15,
        "generic_rejected": True, "confused_action_rejected": True,
    }


@pytest.mark.parametrize("omit", [None, "x-cosmas-team-contract", "x-cosmas-draft-recovery",
                                  "x-cosmas-workspace-protocol"])
def test_native_account_get_passes_actual_identity_boundary(native_requests, omit):
    wire = native_requests["native_recording_account"]
    assert wire["method"] == "GET" and wire["body_base64"] == ""
    assert wire["url"] == "https://api.example.invalid/provider-team/identity"
    assert {key.lower(): value for key, value in wire["headers"].items()}[
        "x-cosmas-workspace-protocol"] == "1"
    called = []

    def authenticate():
        called.append(True)
        raise HTTPException(401, "synthetic authentication boundary")

    app = FastAPI()
    runtime = SimpleNamespace(workspace_hosted_enabled=True, workspace_draft_recovery_required=True)
    app.add_middleware(WorkspaceProtocolBoundary, runtime=lambda: runtime)
    provider_identity_routes.register(app, lambda: None, authenticate, gate=lambda *args: None,
                                      reauthenticate=lambda *args: None, recovery_scope=lambda *args: None)
    headers = {key: value for key, value in wire["headers"].items() if key.lower() != omit}
    with TestClient(app) as client:
        result = client.request(wire["method"], urlsplit(wire["url"]).path, headers=headers)
    # Passing the protocol reaches authentication; this does not claim a real sign-in.
    assert result.status_code == (401 if omit is None else 426)
    assert called == ([True] if omit is None else [])
    assert result.headers["cache-control"] == "no-store"
