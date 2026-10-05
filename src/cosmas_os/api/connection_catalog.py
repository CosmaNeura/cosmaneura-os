"""Read-only setup availability. Availability is not an account grant or health claim."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from cosmas_os.application import workspace as ws


def catalog(settings, runtime):
    enabled = {
        "core": settings.workspace_core_connection_available,
        "google": settings.workspace_google_connection_enabled
        and getattr(runtime, "google_connection", None) is not None,
        "microsoft": settings.workspace_microsoft_connection_enabled
        and getattr(runtime, "microsoft_connection", None) is not None,
        "scheduling": settings.workspace_scheduling_available
        and settings.workspace_scheduling_login_enabled
        and getattr(runtime, "scheduling_google_login", None) is not None,
        "messaging": settings.vendor_setup_enabled,
        "payments": settings.finance_setup_enabled,
        "portals": settings.portal_setup_enabled,
    }
    return {"version": 1, "services": [
        {"id": name, "setup_available": bool(available)}
        for name, available in enabled.items()
    ]}


def router(*, settings, runtime, identity_dependency, workspace_gate):
    routes = APIRouter()

    @routes.get("/connections/plugins", dependencies=[Depends(workspace_gate)])
    def read_plugins(request: Request, identity=Depends(identity_dependency)):
        from cosmas_os.api.plugin_catalog import plugin_catalog

        validate(request, identity)
        from cosmas_os.adapters.managed_services import managed_services
        from cosmas_os.adapters.portal_services import portal_services

        return JSONResponse(plugin_catalog(settings(), runtime(), managed=managed_services(request.app),
            portal=portal_services(request.app)), headers={
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        })

    @routes.get("/connections/catalog", dependencies=[Depends(workspace_gate)])
    def read(request: Request, identity=Depends(identity_dependency)):
        validate(request, identity)
        return JSONResponse(catalog(settings(), runtime()), headers={
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        })

    def validate(request: Request, identity):
        if identity.auth_mode != "clerk_jwt" or identity.external_identity_id is None:
            raise ws.WorkspaceError("workspace_access_denied", 403)
        if request.headers.getlist("x-cosmas-connection-contract") != ["1"]:
            raise ws.WorkspaceError("connection_catalog_contract_required", 426)
        if request.query_params or request.headers.getlist("content-encoding"):
            raise ws.WorkspaceError("invalid_connection_catalog_request", 422)

    return routes
