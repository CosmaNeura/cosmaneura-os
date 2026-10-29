"""Read-only setup availability. Availability is not an account grant or health claim."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from cosmas_os.application import workspace as ws


def catalog(settings, runtime, *, version=1, identity=None, managed=None, portal=None, setup_allowed=False):
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
    legacy = {"version": 1, "services": [
        {"id": name, "setup_available": bool(available)}
        for name, available in enabled.items()
    ]}
    if version == 1:
        return legacy

    def installed(supplier, attribute, vendor=None):
        # Count only this caller's explicitly installed accounts. No credential
        # lookup, provider request, account label or foreign installation escapes.
        items = getattr(getattr(supplier, attribute, None), "installations", {}).values()
        return [item for item in items if identity is not None
                and str(item.selection.box_id) == identity.box_id
                and str(item.selection.owner_id) == identity.principal_id
                and (vendor is None or item.selection.vendor == vendor)]

    vendor_accounts = installed(managed, "vendor_catalog")
    finance_accounts = installed(managed, "finance_catalog", "stripe")
    portal_accounts = installed(portal, "catalog", "portal")
    production_vendor = [item for item in vendor_accounts if item.selection.environment == "production"]
    production_portal = [item for item in portal_accounts
                         if item.selection.environment == "production"
                         and not item.profile.portal_id.startswith("synthetic_")]
    credential_runtime = bool(managed is not None and getattr(managed, "has_credentials", False))
    portal_runtime = bool(portal is not None and getattr(portal, "has_execution", False))
    hosted = bool(getattr(settings, "workspace_hosted_enabled", False))
    usable_vendor = production_vendor if hosted else vendor_accounts
    vendor_runtime = credential_runtime and bool(getattr(settings, "vendor_work_enabled", False)
                                                   and getattr(settings, "vendor_io_enabled", False))
    def inbound_accounts(attribute):
        return [item for item in getattr(managed, attribute, ()) if identity is not None
                and str(item.selection.box_id) == identity.box_id
                and str(item.selection.owner_id) == identity.principal_id
                and (not hosted or item.selection.environment == "production")]

    fax_accounts = inbound_accounts("fax_inbound_installations")
    efax_accounts = inbound_accounts("efax_inbound_installations")
    inbound_accounts_current = [*fax_accounts, *efax_accounts]
    production_inbound = [i for i in inbound_accounts_current if i.selection.environment == "production"]
    inbound_available = credential_runtime and (
        bool(fax_accounts) and getattr(settings, "fax_inbound_enabled", False)
        or any(i.metadata_enabled for i in efax_accounts) and getattr(settings, "efax_inbound_enabled", False))

    def action(name, available, *, supported=True):
        return {"id": name, "supported": supported, "runtime_available": bool(available and supported)}

    actions = {
        "core": [action("practice_connection", enabled["core"]), action("visit_discovery", enabled["core"]),
                 action("athena_schedule", getattr(settings, "workspace_athena_connection_available", False)),
                 action("ehr_write", False, supported=False)],
        "google": [action("mail_headers", enabled["google"]),
                   action("reviewed_email_source", enabled["google"] and getattr(settings, "workspace_google_message_available", False)),
                   action("calendar_source", enabled["google"] and getattr(settings, "workspace_google_calendar_available", False)),
                   action("email_send", False, supported=False), action("calendar_write", False, supported=False)],
        "microsoft": [action("mail_headers", enabled["microsoft"]), action("calendar_summaries", enabled["microsoft"]),
                      action("full_email_source", enabled["microsoft"] and getattr(settings, "workspace_microsoft_message_available", False)), action("email_send", False, supported=False)],
        "scheduling": [action("availability", enabled["scheduling"]),
                       action("appointment_proposals", enabled["scheduling"] and getattr(settings, "workspace_appointments_enabled", False)),
                       action("live_booking", False, supported=False)],
        "messaging": [action("spruce_administrative_message", vendor_runtime and any("spruce_secure_message" in i.capabilities for i in usable_vendor)),
                      action("fax_delivery", vendor_runtime and getattr(managed, "artifact_store", None) is not None
                             and any(any(c.endswith("_fax") for c in i.capabilities) for i in usable_vendor)),
                      action("reviewed_received_fax", inbound_available)],
        # The current Stripe installation contract is sandbox-only. Its test
        # workflow and historical receipts are not a live payment connection.
        "payments": [action("sandbox_payment_request", not hosted and bool(finance_accounts) and credential_runtime
                            and getattr(settings, "finance_work_enabled", False)
                            and getattr(settings, "finance_io_enabled", False)),
                     action("live_payment_collection", False, supported=False)],
        "portals": [action("named_portal_work", bool(production_portal) and portal_runtime
                           and getattr(settings, "portal_work_enabled", False)
                           and getattr(settings, "portal_io_enabled", False), supported=bool(production_portal)),
                    action("arbitrary_portal_connection", False, supported=False)],
    }
    rows = []
    for name in enabled:
        installed_state = "not_checked"
        supported = name != "portals" or bool(production_portal)
        state = "user_connectable" if name in {"google", "microsoft"} and enabled[name] else "practice_setup"
        setup_available = enabled[name]
        if name in {"messaging", "payments", "portals"}:
            accounts = {"messaging": [*usable_vendor, *inbound_accounts_current], "payments": finance_accounts, "portals": production_portal}[name]
            any_accounts = {"messaging": [*vendor_accounts, *inbound_accounts_current], "payments": finance_accounts, "portals": portal_accounts}[name]
            production = {"messaging": [*production_vendor, *production_inbound], "payments": [], "portals": production_portal}[name]
            installed_state = "installed" if production else "sandbox_only" if any_accounts else "missing"
            setup_available = enabled[name] and setup_allowed and bool(accounts) and (name != "payments" or not hosted)
        if not supported or name == "payments" and (hosted or not finance_accounts):
            state = "coming_soon"
            setup_available = False
        rows.append({"id": name, "setup_available": bool(setup_available), "setup_allowed": bool(setup_allowed or name not in {"messaging", "payments", "portals"}), "supported": supported,
                     "state": state, "runtime_available": any(a["runtime_available"] for a in actions[name]),
                     "installed_account": installed_state, "client_status": "not_checked",
                     "account_status": "not_checked", "operation_status": "not_checked", "actions": actions[name]})
    return {"version": 2, "services": rows}


def router(*, settings, runtime, identity_dependency, workspace_gate, session_factory=None):
    routes = APIRouter()

    @routes.get("/connections/plugins", dependencies=[Depends(workspace_gate)])
    def read_plugins(request: Request, identity=Depends(identity_dependency)):
        from cosmas_os.api.plugin_catalog import plugin_catalog

        validate(request, identity, versions=("1",))
        from cosmas_os.adapters.managed_services import managed_services
        from cosmas_os.adapters.portal_services import portal_services

        return JSONResponse(plugin_catalog(settings(), runtime(), managed=managed_services(request.app),
            portal=portal_services(request.app)), headers={
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        })

    @routes.get("/connections/catalog", dependencies=[Depends(workspace_gate)])
    def read(request: Request, identity=Depends(identity_dependency)):
        version = validate(request, identity, versions=("1", "2"))
        from cosmas_os.adapters.managed_services import managed_services
        from cosmas_os.adapters.portal_services import portal_services

        owner = False
        if version == "2" and session_factory is not None:
            with session_factory() as session:
                owner = ws._human(session, identity.box_id, identity.principal_id).is_owner
        return JSONResponse(catalog(settings(), runtime(), version=int(version), identity=identity,
                                   managed=managed_services(request.app), portal=portal_services(request.app), setup_allowed=owner), headers={
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        })

    def validate(request: Request, identity, *, versions):
        if identity.auth_mode != "clerk_jwt" or identity.external_identity_id is None:
            raise ws.WorkspaceError("workspace_access_denied", 403)
        contract = request.headers.getlist("x-cosmas-connection-contract")
        if len(contract) != 1 or contract[0] not in versions:
            raise ws.WorkspaceError("connection_catalog_contract_required", 426)
        if request.query_params or request.headers.getlist("content-encoding"):
            raise ws.WorkspaceError("invalid_connection_catalog_request", 422)
        return contract[0]

    return routes
