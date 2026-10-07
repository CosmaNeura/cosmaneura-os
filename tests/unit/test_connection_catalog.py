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


def test_v2_distinguishes_missing_installations_unsupported_actions_and_existing_oauth():
    config = configuration(workspace_google_connection_enabled=True, vendor_setup_enabled=True,
                           finance_setup_enabled=True, portal_setup_enabled=True, workspace_hosted_enabled=True)
    result = catalog(config, SimpleNamespace(google_connection=object()), version=2)
    services = {row["id"]: row for row in result["services"]}
    assert services["google"]["state"] == "user_connectable"
    assert services["google"]["account_status"] == services["google"]["operation_status"] == "not_checked"
    assert services["messaging"]["state"] == "practice_setup"
    assert services["messaging"]["installed_account"] == "missing"
    assert services["messaging"]["setup_available"] is False
    assert services["portals"]["state"] == "coming_soon"
    assert services["payments"]["state"] == "coming_soon"
    assert next(a for a in services["google"]["actions"] if a["id"] == "email_send")["supported"] is False
    assert next(a for a in services["scheduling"]["actions"] if a["id"] == "live_booking")["supported"] is False


def test_v2_scope_filters_installed_accounts_and_never_claims_credential_or_provider_acceptance():
    def item(box, owner, vendor="spruce", environment="production"):
        return SimpleNamespace(selection=SimpleNamespace(box_id=box, owner_id=owner, vendor=vendor,
                               environment=environment), capabilities=("spruce_secure_message",))

    identity = SimpleNamespace(box_id="owned_box", principal_id="owned_human")
    supplier = SimpleNamespace(vendor_catalog=SimpleNamespace(installations={
        "foreign_owner": item("owned_box", "other_human"), "foreign_box": item("other_box", "owned_human"),
    }), has_credentials=True)
    config = configuration(vendor_setup_enabled=True, vendor_work_enabled=True, vendor_io_enabled=True)
    services = catalog(config, SimpleNamespace(), version=2, identity=identity, managed=supplier, setup_allowed=True)["services"]
    assert services[4]["installed_account"] == "missing"
    assert not services[4]["setup_available"]
    supplier.vendor_catalog.installations["owned"] = item("owned_box", "owned_human")
    result = catalog(config, SimpleNamespace(), version=2, identity=identity, managed=supplier, setup_allowed=True)
    assert result["services"][4]["installed_account"] == "installed"
    assert result["services"][4]["setup_available"] is True
    assert result["services"][4]["actions"][0]["runtime_available"] is True
    assert "owned_human" not in str(result) and "owned_box" not in str(result)
    assert result["services"][4]["operation_status"] == "not_checked"
    denied = catalog(config, SimpleNamespace(), version=2, identity=identity, managed=supplier)
    assert denied["services"][4]["installed_account"] == "installed"
    assert denied["services"][4]["setup_available"] is False
    supplier.vendor_catalog.installations["owned"].capabilities = ("spruce_media_upload",)
    no_message = catalog(config, SimpleNamespace(), version=2, identity=identity, managed=supplier, setup_allowed=True)
    assert not no_message["services"][4]["actions"][0]["runtime_available"]
    assert not no_message["services"][4]["actions"][1]["runtime_available"]
    assert not no_message["services"][4]["actions"][2]["runtime_available"]


def test_v2_sandbox_portal_does_not_become_a_production_connection():
    identity = SimpleNamespace(box_id="owned_box", principal_id="owned_human")
    selection = SimpleNamespace(box_id="owned_box", owner_id="owned_human", vendor="portal", environment="sandbox")
    item = SimpleNamespace(selection=selection, profile=SimpleNamespace(portal_id="synthetic_portal"))
    supplier = SimpleNamespace(catalog=SimpleNamespace(installations={"one": item}), has_execution=True)
    result = catalog(configuration(portal_setup_enabled=True, portal_io_enabled=True), SimpleNamespace(),
                     version=2, identity=identity, portal=supplier, setup_allowed=True)
    assert result["services"][6]["state"] == "coming_soon"
    assert result["services"][6]["installed_account"] == "sandbox_only"
    assert not result["services"][6]["runtime_available"]


def test_v2_independent_efax_installation_requires_current_scope_and_read_permission():
    identity = SimpleNamespace(box_id="owned_box", principal_id="owned_human")
    selection = SimpleNamespace(box_id="owned_box", owner_id="owned_human", environment="production")
    item = SimpleNamespace(selection=selection, metadata_enabled=True)
    supplier = SimpleNamespace(efax_inbound_installations=(item,), has_credentials=True)
    config = configuration(vendor_setup_enabled=True, efax_inbound_enabled=True, workspace_hosted_enabled=True)
    def messaging():
        return catalog(config, SimpleNamespace(), version=2, identity=identity, managed=supplier,
                       setup_allowed=True)["services"][4]

    assert messaging()["installed_account"] == "installed"
    assert messaging()["setup_available"] is True
    assert messaging()["actions"][2]["runtime_available"] is True
    assert not messaging()["actions"][0]["runtime_available"]
    item.metadata_enabled = False
    assert not messaging()["actions"][2]["runtime_available"]
    selection.owner_id = "other_human"
    assert messaging()["installed_account"] == "missing"
    assert not messaging()["setup_available"]


def test_v2_hosted_inbound_sandbox_is_not_production_ready():
    identity = SimpleNamespace(box_id="owned_box", principal_id="owned_human")
    selection = SimpleNamespace(box_id="owned_box", owner_id="owned_human", environment="sandbox")
    supplier = SimpleNamespace(fax_inbound_installations=(SimpleNamespace(selection=selection),), has_credentials=True)
    result = catalog(configuration(vendor_setup_enabled=True, fax_inbound_enabled=True, workspace_hosted_enabled=True),
                     SimpleNamespace(), version=2, identity=identity, managed=supplier, setup_allowed=True)["services"][4]
    assert not result["setup_available"]
    assert not result["actions"][2]["runtime_available"]


@pytest.mark.parametrize("authenticated,gate,headers,query,expected", [
    (False, True, {"X-Cosmas-Connection-Contract": "1"}, "", 401),
    (True, False, {"X-Cosmas-Connection-Contract": "1"}, "", 404),
    (True, True, {}, "", 426),
    (True, True, {"X-Cosmas-Connection-Contract": "1"}, "?provider=google", 422),
    (True, True, {"X-Cosmas-Connection-Contract": "1"}, "", 200),
])
@pytest.mark.parametrize("path", ["/connections/catalog", "/connections/plugins"])
def test_catalog_uses_existing_auth_and_workspace_gates(authenticated, gate, headers, query, expected, path):
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
        response = client.get(path + query, headers=headers)
    assert response.status_code == expected
    if expected == 200:
        assert response.headers["cache-control"] == "no-store"
        if path.endswith("/catalog"):
            assert response.json() == catalog(configuration(), SimpleNamespace())
        else:
            from cosmas_os.api.plugin_catalog import plugin_catalog
            assert response.json() == plugin_catalog(configuration(), SimpleNamespace())


def test_only_catalog_negotiates_v2_and_keeps_plugin_contract_v1():
    app = FastAPI()
    @app.exception_handler(WorkspaceError)
    async def error(_request, cause):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": cause.code}, status_code=cause.status)
    app.include_router(router(settings=configuration, runtime=SimpleNamespace,
        identity_dependency=lambda: SimpleNamespace(auth_mode="clerk_jwt", external_identity_id="invented"), workspace_gate=lambda: None))
    with TestClient(app) as client:
        assert client.get("/connections/catalog", headers={"X-Cosmas-Connection-Contract": "2"}).json()["version"] == 2
        assert client.get("/connections/plugins", headers={"X-Cosmas-Connection-Contract": "2"}).status_code == 426
        assert client.get("/connections/catalog", headers=[("X-Cosmas-Connection-Contract", "1"), ("X-Cosmas-Connection-Contract", "2")]).status_code == 426


@pytest.mark.parametrize("owner", [True, False])
def test_v2_checks_current_human_setup_permission_in_closed_read_session(monkeypatch, owner):
    from cosmas_os.api import connection_catalog

    checked, closed = [], []
    class ReadSession:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            closed.append(True)

    def human(session, box, actor):
        checked.append((session, box, actor))
        return SimpleNamespace(is_owner=owner)

    monkeypatch.setattr(connection_catalog.ws, "_human", human)
    identity = SimpleNamespace(auth_mode="clerk_jwt", external_identity_id="invented", box_id="owned_box", principal_id="owned_human")
    app = FastAPI()
    app.include_router(router(settings=configuration, runtime=SimpleNamespace, identity_dependency=lambda: identity,
                             workspace_gate=lambda: None, session_factory=ReadSession))
    with TestClient(app) as client:
        response = client.get("/connections/catalog", headers={"X-Cosmas-Connection-Contract": "2"})
        client.get("/connections/catalog", headers={"X-Cosmas-Connection-Contract": "1"})
    assert response.status_code == 200
    assert response.json()["services"][4]["setup_allowed"] is owner
    assert len(checked) == len(closed) == 1
    assert checked[0][1:] == ("owned_box", "owned_human")
