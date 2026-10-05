"""Managed plugin contracts retain exact handler paths and authority boundaries."""

from pathlib import Path
from types import SimpleNamespace

import jsonschema
import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute

from cosmas_os.api import plugin_managed_operations as managed
from cosmas_os.api.plugin_catalog import tool


def rows():
    return {row.id: row for row in managed.definitions()}


def test_managed_descriptors_point_to_registered_http_handlers():
    from cosmas_os.api import (
        efax_inbound_routes,
        fax_inbound_routes,
        finance_routes,
        finance_setup_routes,
        inbox_handoff_routes,
        inbox_review_routes,
        inbox_work_routes,
        portal_setup_routes,
        portal_work_routes,
        vendor_routes,
    )

    app = FastAPI()
    def dependency():
        return None
    def reauthenticate(*_):
        return None
    fax_inbound_routes.register(app, dependency, dependency,
                                execution_dependency=dependency, reauthenticate=reauthenticate)
    efax_inbound_routes.register(app, dependency, dependency)
    portal_setup_routes.register(app, dependency, dependency)
    portal_work_routes.register(app, dependency, dependency)
    finance_setup_routes.register(app, dependency, dependency)
    inbox_work_routes.register(app, dependency, dependency)
    inbox_review_routes.register(app, dependency, dependency)
    inbox_handoff_routes.register(app, dependency, dependency)
    finance_routes.install(app, get_session=dependency, identity_dependency=dependency,
                           policy_dependency=dependency, execution_factory_dependency=dependency,
                           event_route_dependency=dependency, core_connection=dependency,
                           current_core_note=dependency, reauthenticate=reauthenticate,
                           session_factory=dependency)
    vendor_routes.install(app, get_session=dependency, identity_dependency=dependency,
                          core_connection=dependency, current_core_note=dependency,
                          execution_factory_dependency=dependency, artifact_store_dependency=dependency,
                          event_route_dependency=dependency, reauthenticate=reauthenticate,
                          session_factory=dependency)
    routes = {(row.path, method) for row in app.routes if isinstance(row, APIRoute)
              for method in row.methods or ()}
    for definition in managed.definitions():
        # The two inbox dispatch routes enforce their allowed kind inside the handler.
        path = definition.path.replace("/resolve", "/{kind}") if definition.path.startswith("/inbox-handoffs/") else definition.path
        assert (path, definition.method) in routes, definition.id


def test_no_operation_approves_mutates_accounts_or_attests_new_human_review():
    definitions = managed.definitions()
    assert len({row.id for row in definitions}) == len(definitions)
    assert all(row.agent_callable for row in definitions)
    assert not {row.path.rsplit("/", 1)[-1] for row in definitions} & {
        "grant", "revoke", "activate", "decide", "submit", "publish", "verify", "result", "handoff"
    }
    assert "efax_inbound.acquire_approved_image" not in rows()
    assert rows()["fax_inbound.acquire_approved_image"].path == "/fax-inbound/acquire"
    assert "does not mark" in rows()["fax_inbound.acquire_approved_image"].description
    for definition in definitions:
        assert not any(name.startswith("reviewed_") for name in definition.request.get("properties", {}))
        assert definition.permission and definition.completion and definition.recovery
        for path in definition.tests:
            assert Path(path).is_file()


def test_request_schemas_match_existing_closed_handler_models():
    expected = {
        "fax_inbound.read_metadata": managed.fax.Observe,
        "fax_inbound.prepare_image": managed.fax.Propose,
        "fax_inbound.acquire_approved_image": managed.fax.Acquire,
        "fax_inbound.resolve_reviewed_source": managed.fax.Resolve,
        "efax_inbound.read_metadata": managed.efax.Observe,
        "efax_inbound.resolve_reviewed_source": managed.efax.SourceResolve,
        "portal.prepare": managed.portal.Proposal,
        "portal.read_provider_status": managed.portal.Bound,
        "stripe.prepare": managed.finance.FinanceProposal,
        "stripe.read_provider_status": managed.BoundCommand,
    }
    for name, model in expected.items():
        assert rows()[name].request == model.model_json_schema()
    for definition in managed.definitions():
        schema = tool(definition, False)["inputSchema"]
        jsonschema.Draft202012Validator.check_schema(schema)
        assert schema["additionalProperties"] is False
        assert set(schema["properties"]) == set(schema["required"])
        if definition.method == "GET":
            assert "request" not in schema["properties"]


@pytest.mark.parametrize("name,arguments", [
    ("fax_inbound.resolve_reviewed_source", {"workspace_id": "11111111-1111-4111-8111-111111111111",
                                            "request": {"idempotency_key": "reviewed-1"}}),
    ("fax_inbound.inspect_image_proposal", {"ticket_id": "11111111-1111-4111-8111-111111111111",
                                           "revision_id": "22222222-2222-4222-8222-222222222222"}),
    ("spruce.read_inbox_source", {"item_id": "11111111-1111-4111-8111-111111111111",
                                 "source_id": "22222222-2222-4222-8222-222222222222"}),
])
def test_tools_accept_exact_arguments_and_refuse_account_or_endpoint_injection(name, arguments):
    schema = tool(rows()[name], False)["inputSchema"]
    validator = jsonschema.Draft202012Validator(schema)
    assert not list(validator.iter_errors(arguments))
    assert list(validator.iter_errors(arguments | {"endpoint": "https://unreviewed.invalid"}))
    if "request" in arguments:
        assert list(validator.iter_errors(arguments | {"request": arguments["request"] | {"owner_id": "foreign"}}))


def test_configuration_never_claims_account_health_and_provider_reads_require_suppliers():
    flags = SimpleNamespace(workspace_available=True, fax_inbound_enabled=True, efax_inbound_enabled=True,
                            fax_inbound_source_available=True, efax_inbound_source_available=True,
                            portal_setup_enabled=True, portal_work_enabled=True, portal_io_enabled=True,
                            finance_setup_enabled=True, finance_work_enabled=True, finance_io_enabled=True,
                            inbox_work_enabled=True, inbox_handoff_enabled=True,
                            vendor_work_enabled=True, vendor_io_enabled=True)
    supplier = SimpleNamespace(has_credentials=True)
    portal = SimpleNamespace(has_execution=True)
    for definition in managed.definitions():
        assert not managed.configured(definition, SimpleNamespace(), SimpleNamespace(), managed=supplier, portal=portal)
        assert managed.configured(definition, flags, SimpleNamespace(), managed=supplier, portal=portal)
        descriptor = tool(definition, True)
        assert descriptor["_meta"]["ai.cosmas/operation"]["account_status"] == "not_checked"
        assert descriptor["_meta"]["ai.cosmas/operation"]["operation_health"] == "not_checked"
    for name in ("fax_inbound.read_metadata", "efax_inbound.read_metadata", "portal.read_provider_status",
                 "stripe.read_provider_status", "vendor_work.read_provider_status"):
        assert not managed.configured(rows()[name], flags, SimpleNamespace())
    assert "application/pdf" in rows()["fax_inbound.read_saved_document"].description
    assert "source_withheld" in rows()["efax_inbound.resolve_reviewed_source"].description


def test_saved_source_recovery_remains_available_when_new_sharing_is_disabled():
    flags = SimpleNamespace(workspace_available=True, fax_inbound_enabled=True, efax_inbound_enabled=True,
                            fax_inbound_source_available=False, efax_inbound_source_available=False)
    assert managed.configured(rows()["fax_inbound.resolve_reviewed_source"], flags, SimpleNamespace(),
                              managed=SimpleNamespace(has_credentials=True))
    assert managed.configured(rows()["efax_inbound.resolve_reviewed_source"], flags, SimpleNamespace())
