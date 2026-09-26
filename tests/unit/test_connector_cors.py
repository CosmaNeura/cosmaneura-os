"""Production route/middleware stack with read-only dependency doubles; no DB or vendor I/O."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from cosmas_os.api import app as api
from cosmas_os.api.auth import RequestIdentity
from cosmas_os.application import (
    finance_settings,
    finance_work,
    portal_setup,
    portal_work,
    vendor_work,
)
from cosmas_os.application.workspace import WorkspaceError

WORKSPACE = "00000000-0000-4000-8000-000000000071"
CASES = [
    (f"/workspaces/{WORKSPACE}/vendor-work", "X-Cosmas-Vendor-Contract", vendor_work, 400),
    (f"/workspaces/{WORKSPACE}/finance-work", "X-Cosmas-Finance-Contract", finance_work, 400),
    (f"/workspaces/{WORKSPACE}/portal-work", "X-Cosmas-Portal-Work-Contract", portal_work, 426),
    ("/portal-setup", "X-Cosmas-Portal-Contract", portal_setup, 426),
    ("/finance-setup", "X-Cosmas-Finance-Setup-Contract", finance_settings, 426),
]
PROJECTION = {"fixture": "read-only projection"}


@pytest.fixture
def boundary(monkeypatch):
    # Clone the installed production order and routes, not a hand-built CORS order.
    # Lifespan workers and database operations are outside this transport-policy test.
    app = FastAPI(
        middleware=list(api.app.user_middleware),
    )
    app.exception_handlers.update(api.app.exception_handlers)
    app.include_router(api.app.router)
    cors = next(item for item in api.app.user_middleware if item.cls is CORSMiddleware)
    origins = cors.kwargs["allow_origins"]
    assert isinstance(origins, list) and origins and isinstance(origins[0], str)
    origin = origins[0]
    identity = RequestIdentity(
        box_id="00000000-0000-4000-8000-000000000001",
        principal_id="00000000-0000-4000-8000-000000000002",
        auth_mode="synth_headers",
    )
    monkeypatch.setattr(type(api.settings), "workspace_available", property(lambda _: True))
    monkeypatch.setattr(api.settings, "auth_mode", "synth_headers")
    monkeypatch.setattr(api, "authenticate_request", lambda *args, **kwargs: identity)
    app.dependency_overrides[api._identity] = lambda: identity
    app.dependency_overrides[api.get_session] = lambda: SimpleNamespace(
        info={}, expire_all=lambda: None, rollback=lambda: None
    )
    reads = []
    for _, _, module, _ in CASES:
        read = Mock(return_value=PROJECTION)
        reads.append(read)
        monkeypatch.setattr(module, "catalog", read)
    with TestClient(app) as client:
        yield SimpleNamespace(app=app, client=client, origin=origin, reads=reads)


def headers(boundary, contract, value="1", *, origin=None):
    return {
        "Origin": origin or boundary.origin,
        "Authorization": "Bearer invented-transport-test-only",
        "X-Cosmas-Draft-Recovery": "2",
        contract: value,
    }


def readable(response, boundary, status):
    assert response.status_code == status
    assert response.headers["access-control-allow-origin"] == boundary.origin
    assert "origin" in response.headers["vary"].lower()
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("path,contract,module,query_status", CASES)
def test_allowed_origin_reads_valid_and_rejected_connector_responses(
    boundary, path, contract, module, query_status
):
    response = boundary.client.get(path, headers=headers(boundary, contract))
    readable(response, boundary, 200)
    assert response.json() == PROJECTION
    readable(
        boundary.client.get(path, headers=headers(boundary, contract, "unsupported")),
        boundary,
        426,
    )
    readable(
        boundary.client.get(path + "?unexpected=local-test", headers=headers(boundary, contract)),
        boundary,
        query_status,
    )
    assert module.catalog.call_count == 1


@pytest.mark.parametrize("path,contract,module,query_status", CASES)
@pytest.mark.parametrize("status", [401, 403, 404])
def test_authentication_and_access_denials_remain_readable_without_private_work(
    boundary, path, contract, module, query_status, status
):
    def denied():
        raise HTTPException(status, "access unavailable", headers={"Cache-Control": "no-store"})

    boundary.app.dependency_overrides[api._identity] = denied
    response = boundary.client.get(path, headers=headers(boundary, contract))
    readable(response, boundary, status)
    assert response.json() != PROJECTION
    module.catalog.assert_not_called()


@pytest.mark.parametrize("path,contract,module,query_status", CASES)
def test_mapped_service_errors_keep_cors_and_no_store(
    boundary, path, contract, module, query_status
):
    module.catalog.side_effect = WorkspaceError("workspace_storage_unavailable", 503)
    response = boundary.client.get(path, headers=headers(boundary, contract))
    readable(response, boundary, 503)
    assert response.json() != PROJECTION


@pytest.mark.parametrize("path,contract,module,query_status", CASES)
def test_preflight_preserves_exact_origins_and_headers_without_authentication(
    boundary, path, contract, module, query_status
):
    def must_not_authenticate():
        raise AssertionError("A preflight must not run authentication")

    boundary.app.dependency_overrides[api._identity] = must_not_authenticate
    preflight = {
        "Origin": boundary.origin,
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": f"authorization,content-type,x-cosmas-draft-recovery,{contract.lower()}",
    }
    accepted = boundary.client.options(path, headers=preflight)
    assert accepted.status_code == 200
    assert accepted.headers["access-control-allow-origin"] == boundary.origin
    assert contract.lower() in accepted.headers["access-control-allow-headers"].lower()
    for changed in [
        {"Origin": "https://unknown-origin.invalid"},
        {"Access-Control-Request-Headers": "x-unapproved-connector-header"},
        {"Access-Control-Request-Method": "DELETE"},
    ]:
        rejected = boundary.client.options(path, headers=preflight | changed)
        assert rejected.status_code == 400
        if "Origin" in changed:
            assert "access-control-allow-origin" not in rejected.headers
    module.catalog.assert_not_called()


@pytest.mark.parametrize("path,contract,module,query_status", CASES)
def test_unknown_origin_never_gains_browser_visibility_on_success_or_rejection(
    boundary, path, contract, module, query_status
):
    for value, expected in [("1", 200), ("unsupported", 426)]:
        response = boundary.client.get(
            path,
            headers=headers(boundary, contract, value, origin="https://unknown-origin.invalid"),
        )
        assert response.status_code == expected
        assert "access-control-allow-origin" not in response.headers
        assert response.headers["cache-control"] == "no-store"
