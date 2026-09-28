from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from cosmas_os.api.connection_catalog import catalog, router
from cosmas_os.application.workspace import WorkspaceError


def configuration(**changes):
    return SimpleNamespace(**({
        "workspace_core_connection_available": True,
        "workspace_google_connection_enabled": False,
        "workspace_microsoft_connection_enabled": False,
        "workspace_scheduling_available": False,
        "workspace_scheduling_login_enabled": False,
        "vendor_setup_enabled": False, "finance_setup_enabled": False,
        "portal_setup_enabled": False,
    } | changes))


def test_catalog_does_not_advertise_missing_oauth_runtimes_or_claim_account_connection():
    settings = configuration(workspace_google_connection_enabled=True,
                             workspace_microsoft_connection_enabled=True)
    result = catalog(settings, SimpleNamespace())
    assert result == {"version": 1, "services": [
        {"id": name, "setup_available": name == "core"}
        for name in ["core", "google", "microsoft", "scheduling", "messaging", "payments", "portals"]
    ]}
    result = catalog(settings, SimpleNamespace(google_connection=object()))
    assert result["services"][1] == {"id": "google", "setup_available": True}
    assert "connected" not in str(result)


@pytest.mark.parametrize("authenticated,gate,headers,query,expected", [
    (False, True, {"X-Cosmas-Connection-Contract": "1"}, "", 401),
    (True, False, {"X-Cosmas-Connection-Contract": "1"}, "", 404),
    (True, True, {}, "", 426),
    (True, True, {"X-Cosmas-Connection-Contract": "1"}, "?provider=google", 422),
    (True, True, {"X-Cosmas-Connection-Contract": "1"}, "", 200),
])
def test_catalog_uses_existing_auth_and_workspace_gates(authenticated, gate, headers, query, expected):
    app = FastAPI()

    def identity():
        if not authenticated:
            raise HTTPException(401)
        return SimpleNamespace(auth_mode="clerk_jwt", external_identity_id="invented")

    def workspace_gate():
        if not gate:
            raise HTTPException(404)

    @app.exception_handler(WorkspaceError)
    async def error(_request, cause):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": cause.code}, status_code=cause.status)

    app.include_router(router(settings=configuration, runtime=SimpleNamespace,
                              identity_dependency=identity, workspace_gate=workspace_gate))
    with TestClient(app) as client:
        response = client.get("/connections/catalog" + query, headers=headers)
    assert response.status_code == expected
    if expected == 200:
        assert response.headers["cache-control"] == "no-store"
        assert response.json() == catalog(configuration(), SimpleNamespace())
