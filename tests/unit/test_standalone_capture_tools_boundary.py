"""Standalone request filter + pinned Core capture upload host (PR #354 beta fix)."""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from tests.unit import test_standalone_beta_features as beta
from tests.unit import test_standalone_clerk_runtime as clerk_tests
from tests.unit.test_capture_upload_proxy import _Runtime, _receipt, _seed

from cosmas_os.application import capture_upload_proxy as proxy
from cosmas_os.application import workspace as ws
from cosmas_os.models import CaptureUploadProxy
from cosmas_os.standalone_runtime import standalone_request_allowed

clerk_standalone = clerk_tests.clerk_standalone
standalone = clerk_tests.standalone

WS = "00000000-0000-4000-8000-0000000000aa"
PROXY_ID = "00000000-0000-4000-8000-0000000000bb"
PINNED = "inventedcaptureacct.blob.core.windows.net"
CAPTURE_POST = f"/workspaces/{WS}/capture/admission"
CAPTURE_PUT = f"/workspaces/{WS}/capture/ciphertexts/{PROXY_ID}"
F2_URLS = (
    "https://otheraccount.blob.core.windows.net/synth?sig=1",
    "https://evil.example.com/synth?sig=1",
    f"https://{PINNED}.evil.example.com/synth?sig=1",
    "https://203.0.113.10/synth?sig=1",
    f"https://{PINNED}:8443/synth?sig=1",
    f"http://{PINNED}/synth?sig=1",
    "https://InventedCaptureAcct.blob.core.windows.net/synth?sig=1",
    f"https://{PINNED}./synth?sig=1",
)


def _opt_in(runtime):
    return runtime.model_copy(update=beta.model_values() | beta.google_values() | beta.core_capture_values())


@pytest.fixture
def db(engine):
    with Session(engine) as session:
        yield session


@pytest.mark.parametrize("method,path", [
    ("POST", CAPTURE_POST),
    ("POST", f"/workspaces/{WS}/capture/notes"),
    ("POST", f"/workspaces/{WS}/capture/operations"),
    ("PUT", CAPTURE_PUT),
    ("PUT", "/schedule/import"),
])
def test_capture_routes_and_put_refused_when_opt_in_off(clerk_standalone, method, path):
    base = clerk_standalone.runtime
    assert not standalone_request_allowed(method, path, base)
    assert not standalone_request_allowed(method, path, None)


def test_capture_routes_and_put_allowed_only_when_opt_in_on(clerk_standalone):
    on = _opt_in(clerk_standalone.runtime)
    off = clerk_standalone.runtime
    for path in (
        CAPTURE_POST,
        f"/workspaces/{WS}/capture/existing",
        f"/workspaces/{WS}/capture/notes",
        f"/workspaces/{WS}/capture/note-links",
        f"/workspaces/{WS}/capture/operations",
        f"/workspaces/{WS}/capture/source-packets",
    ):
        assert standalone_request_allowed("POST", path, on)
        assert not standalone_request_allowed("POST", path, off)
    assert standalone_request_allowed("PUT", CAPTURE_PUT, on)
    assert not standalone_request_allowed("PUT", CAPTURE_PUT, off)
    assert not standalone_request_allowed("PUT", "/schedule/import", on)


def test_opt_in_off_api_still_returns_403_for_capture_and_put(standalone, monkeypatch):
    from cosmas_os.api import app as api
    from cosmas_os.application import services

    runtime, _, _ = standalone

    def forbidden(*args, **kwargs):
        raise AssertionError("Forbidden standalone route reached database or dispatch")

    monkeypatch.setattr(api, "settings", runtime)
    monkeypatch.setattr(services, "_dispatch_operation", forbidden)
    previous = api.app.dependency_overrides.copy()
    api.app.dependency_overrides[api.get_session] = forbidden
    try:
        client = TestClient(api.app)
        for method, path in (("post", CAPTURE_POST), ("put", CAPTURE_PUT)):
            response = getattr(client, method)(
                path,
                content=b"{}",
                headers={
                    "X-Cosmas-Workspace-Protocol": "1",
                    "Content-Type": "application/octet-stream" if method == "put" else "application/json",
                },
            )
            assert response.status_code == 403
            assert response.json() == {"detail": "standalone_operation_unavailable"}
    finally:
        api.app.dependency_overrides = previous


def test_opt_in_on_capture_route_passes_request_filter(clerk_standalone, monkeypatch):
    """With opt-in on, capture POST/PUT are not blocked by standalone_operation_unavailable."""
    from cosmas_os.api import app as api

    runtime = _opt_in(clerk_standalone.runtime)
    runtime.validate_runtime_configuration()
    monkeypatch.setattr(api, "settings", runtime)
    client = TestClient(api.app, raise_server_exceptions=False)
    for method, path, content_type in (
        ("post", CAPTURE_POST, "application/json"),
        ("put", CAPTURE_PUT, "application/octet-stream"),
    ):
        response = getattr(client, method)(
            path,
            content=b"{}",
            headers={"X-Cosmas-Workspace-Protocol": "1", "Content-Type": content_type},
        )
        assert response.json().get("detail") != "standalone_operation_unavailable"
        assert not (
            response.status_code == 403 and response.json() == {"detail": "standalone_operation_unavailable"}
        )


@pytest.mark.parametrize("upload_url", F2_URLS)
def test_pinned_upload_host_refuses_beta_f2_targets(upload_url):
    assert not proxy._allowed_target_upload_url(upload_url, pinned_upload_host=PINNED)


def test_pinned_upload_host_allows_exact_https_443():
    assert proxy._allowed_target_upload_url(
        f"https://{PINNED}/container/blob?sig=invented", pinned_upload_host=PINNED)
    assert proxy._allowed_target_upload_url(
        f"https://{PINNED}:443/container/blob?sig=invented", pinned_upload_host=PINNED)


def test_mint_and_stream_respect_pinned_host(db):
    box, owner, workspace, _ = _seed(db)
    good = _receipt(upload_url=f"https://{PINNED}/synth?sig=1")
    rewritten = proxy.mint_proxy_upload(
        db, receipt=good, box_id=box.id, workspace_id=workspace.id,
        session_id=str(uuid4()), principal_id=owner.id,
        proxy_origin="https://api.staging.cosmas.ai",
        pinned_upload_host=PINNED,
    )
    for bad in F2_URLS:
        with pytest.raises(ws.WorkspaceError, match="capture_request_unconfirmed"):
            proxy.mint_proxy_upload(
                db, receipt=_receipt(upload_url=bad), box_id=box.id, workspace_id=workspace.id,
                session_id=str(uuid4()), principal_id=owner.id,
                proxy_origin="https://api.staging.cosmas.ai",
                pinned_upload_host=PINNED,
            )

    proxy_id = rewritten.upload_url.rsplit("/", 1)[-1]
    runtime = _Runtime()
    runtime.core_capture_upload_host = PINNED
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(201)

    proxy.stream_ciphertext_to_core(
        db, box_id=box.id, workspace_id=workspace.id, principal_id=owner.id,
        proxy_id=proxy_id, body=b"synthetic-ciphertext",
        runtime=runtime, transport=httpx.MockTransport(handler),
    )
    assert len(seen) == 1
    assert PINNED in seen[0]

    row = db.get(CaptureUploadProxy, proxy_id)
    row.consumed_at = None
    row.target_upload_url = "https://evil.example.com/synth?sig=1"
    db.commit()
    with pytest.raises(ws.WorkspaceError, match="capture_request_unconfirmed"):
        proxy.stream_ciphertext_to_core(
            db, box_id=box.id, workspace_id=workspace.id, principal_id=owner.id,
            proxy_id=proxy_id, body=b"synthetic-ciphertext",
            runtime=runtime, transport=httpx.MockTransport(handler),
        )
