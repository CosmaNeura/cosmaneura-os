"""Scheduling discovery retains exact existing contracts and truthful outcomes."""

from copy import deepcopy
from types import SimpleNamespace

import jsonschema
import pytest
from fastapi.routing import APIRoute
from pydantic import ValidationError

from cosmas_os.api.plugin_catalog import META, find_operation, plugin_catalog
from cosmas_os.api.scheduling_schemas import (
    AppointmentPrepare,
    CurrentAppointmentRequest,
    WorkspaceAvailabilityRequest,
)

IDS = ("scheduling.read_availability", "scheduling.read_current", "scheduling.prepare_appointment", "scheduling.inspect_proposal")
UUID = "11111111-1111-4111-8111-111111111111"
BOT = {"address": "follow_up", "team_revision": 2}
SLOT = {"starts_at": "2026-10-03T13:00:00Z", "ends_at": "2026-10-03T13:30:00Z"}


def descriptors(**configuration):
    return {row["_meta"][META]["id"]: row for row in plugin_catalog(SimpleNamespace(**configuration), SimpleNamespace())["tools"]}


def test_scheduling_catalog_only_names_existing_routes_and_never_approval_or_execution():
    from cosmas_os.api.app import app

    routes = {(r.path, m) for r in app.routes if isinstance(r, APIRoute) for m in r.methods or ()}
    rows = descriptors()
    for name in IDS:
        operation = find_operation(name)
        metadata = rows[name]["_meta"][META]
        assert (operation.path, metadata["http"]["method"]) in routes
        assert metadata["http"]["method"] == operation.method
        assert metadata["external_send"] is False
        assert metadata["account_status"] == metadata["operation_health"] == "not_checked"
    assert not any("decide" in name or "execute" in name or "cancel" in name for name in rows)
    assert rows[IDS[-1]]["_meta"][META]["http"]["body_argument"] is None
    assert {"workspace_id", "ticket_id", "request"} == set(rows[IDS[-1]]["inputSchema"]["required"])


def test_availability_and_current_read_use_the_exact_handler_schemas():
    assert find_operation(IDS[0]).request == WorkspaceAvailabilityRequest.model_json_schema()
    assert find_operation(IDS[1]).request == CurrentAppointmentRequest.model_json_schema()
    assert "not reserved" in find_operation(IDS[0]).description
    assert "calendar synchronization" in find_operation(IDS[1]).description


@pytest.mark.parametrize("change", [{"share": False}, {"share": 1}, {"action": "cancel", "slot": None}, {"slot": None}])
def test_proposal_schema_requires_exact_slot_and_explicit_share(change):
    valid = {"bot": BOT, "action": "book", "slot": SLOT, "share": True, "idempotency_key": "observed-slot-1"}
    operation = find_operation(IDS[2])
    validator = jsonschema.Draft202012Validator(operation.request)
    assert not list(validator.iter_errors(valid))
    assert AppointmentPrepare.model_validate(valid).share is True
    invalid = valid | change
    assert list(validator.iter_errors(invalid))
    if invalid["action"] != "cancel":
        with pytest.raises(ValidationError):
            AppointmentPrepare.model_validate(invalid)


def test_nested_scheduling_tool_refs_resolve_and_refuse_actor_or_slot_injection():
    rows = descriptors()
    requests = {
        IDS[0]: {"bot": BOT, "window": SLOT}, IDS[1]: {"bot": BOT},
        IDS[2]: {"bot": BOT, "action": "reschedule", "slot": SLOT, "share": True, "idempotency_key": "reschedule-1"},
        IDS[3]: {},
    }
    for name in IDS:
        schema = rows[name]["inputSchema"]
        jsonschema.Draft202012Validator.check_schema(schema)
        validator = jsonschema.Draft202012Validator(schema)
        args = {"workspace_id": UUID, "request": requests[name]}
        if name == IDS[3]:
            args["ticket_id"] = UUID
        assert not list(validator.iter_errors(args))
        bad = deepcopy(args)
        bad["request"]["actor_principal_id"] = UUID
        assert list(validator.iter_errors(bad))


def test_discovery_configuration_never_establishes_account_or_work_readiness():
    for scheduling in (False, True):
        for appointments in (False, True):
            rows = descriptors(workspace_scheduling_available=scheduling, workspace_appointments_enabled=appointments)
            for name in IDS:
                metadata = rows[name]["_meta"][META]
                assert metadata["feature_enabled"] is (scheduling and (appointments or name == IDS[0]))
                assert metadata["operation_health"] == "not_checked"
                assert metadata["account_status"] == "not_checked"
