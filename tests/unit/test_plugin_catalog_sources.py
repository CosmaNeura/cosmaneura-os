"""First-party discovery points to real bounded source/review handlers."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from cosmas_os.api.capture_schemas import (
    EncounterPrepRequest,
    ExistingCaptureRequest,
    ScribeSourcePacketRequest,
)
from cosmas_os.api.plugin_catalog import META, find_operation, plugin_catalog
from cosmas_os.api.team_schemas import ConversationRequest

NEW_OPERATIONS = ("workspace.review", "scribe.read_existing", "scribe.share_transcript", "visit_prep.read_brief")
WORKSPACE_ID = "11111111-1111-4111-8111-111111111111"


def descriptors(configuration=None):
    return {row["_meta"][META]["id"]: row for row in plugin_catalog(configuration or SimpleNamespace(), SimpleNamespace())["tools"]}


def source_request():
    return {"idempotency_key": "source-review-1", "expected_revision": 3, "reviewed": True, "share_with_team": True,
        "selection": {"version": 1, "session_id": WORKSPACE_ID, "source_transcript_version": 1,
            "working_transcript_id": WORKSPACE_ID, "working_transcript_version": 1, "snapshot_sha256": "a" * 64}}


def test_new_catalog_operations_are_real_post_handlers_with_actual_boundaries():
    from fastapi.routing import APIRoute

    from cosmas_os.api.app import app
    from cosmas_os.api.conversation_deadline import ConversationMiddleware

    routes = {(route.path, method) for route in app.routes if isinstance(route, APIRoute) for method in route.methods or ()}
    capture_bounds = {(row["path"], method): row["seconds"]
                      for row in app.state.capture_deadline_routes for method in row["methods"]}
    conversation_route = next(row.kwargs["route"] for row in app.user_middleware if row.cls is ConversationMiddleware)
    assert isinstance(conversation_route, APIRoute)
    for identity in NEW_OPERATIONS:
        operation = find_operation(identity)
        binding = descriptors()[identity]["_meta"][META]["http"]
        key = operation.path, binding["method"]
        assert key in routes and binding["method"] == "POST"
        assert binding["authentication"] == "current_clerk_jwt"
        if identity == "workspace.review":
            assert operation.path == conversation_route.path and operation.deadline_seconds == 120
            assert binding["contract_header"] == "X-Cosmas-Model-Contract" and binding["contract_version"] == "1"
        else:
            assert operation.deadline_seconds == capture_bounds[key] == 120
            assert binding["contract_header"] is None


def test_source_and_review_schemas_are_the_handler_contracts():
    for identity, schema in (("workspace.review", ConversationRequest), ("scribe.read_existing", ExistingCaptureRequest),
                             ("scribe.share_transcript", ScribeSourcePacketRequest)):
        assert find_operation(identity).request == schema.model_json_schema()
    assert find_operation("scribe.read_existing").read_only
    assert not find_operation("scribe.share_transcript").read_only
    assert not find_operation("workspace.review").read_only  # A saved conversation is a new private record.
    assert not find_operation("visit_prep.read_brief").read_only  # Core action closure and audit receipt are recorded.


def test_nested_tool_schema_references_resolve_and_refuse_identity_injection():
    jsonschema = pytest.importorskip("jsonschema")
    requests = {"workspace.review": {"idempotency_key": "review-chief-1", "expected_revision": 3,
            "team_revision": 1, "role": "chief", "content": "Review my saved work."},
        "scribe.read_existing": {"idempotency_key": "read-source-1"},
        "scribe.share_transcript": source_request(),
        "visit_prep.read_brief": {"idempotency_key": "read-prep-1", "view": "brief",
            "bot": {"address": "visit_prep", "team_revision": 1}}}
    for identity in NEW_OPERATIONS:
        schema = descriptors()[identity]["inputSchema"]
        jsonschema.Draft202012Validator.check_schema(schema)
        validator = jsonschema.Draft202012Validator(schema)
        valid = {"workspace_id": WORKSPACE_ID, "request": requests[identity]}
        assert not list(validator.iter_errors(valid))
        invalid = deepcopy(valid)
        invalid["request"]["actor_principal_id"] = WORKSPACE_ID
        assert list(validator.iter_errors(invalid))


@pytest.mark.parametrize("field", ["reviewed", "share_with_team"])
@pytest.mark.parametrize("value", [False, None, 1])
def test_source_sharing_requires_both_explicit_human_confirmations(field, value):
    jsonschema = pytest.importorskip("jsonschema")
    request = source_request() | {field: value}
    with pytest.raises(ValidationError):
        ScribeSourcePacketRequest.model_validate(request)
    validator = jsonschema.Draft202012Validator(find_operation("scribe.share_transcript").request)
    assert list(validator.iter_errors(request))


def test_prepared_brief_discovery_cannot_default_to_raw_sources_or_omit_bot():
    jsonschema = pytest.importorskip("jsonschema")
    operation = find_operation("visit_prep.read_brief")
    validator = jsonschema.Draft202012Validator(operation.request)
    valid = {"idempotency_key": "read-prep-1", "view": "brief", "bot": {"address": "visit_prep", "team_revision": 2}}
    assert EncounterPrepRequest.model_validate(valid).view == "brief"
    assert not list(validator.iter_errors(valid))
    for invalid in (valid | {"view": "sources"}, valid | {"bot": None},
                    {key: value for key, value in valid.items() if key != "view"},
                    {key: value for key, value in valid.items() if key != "bot"}):
        assert list(validator.iter_errors(invalid))
    assert any("encounter_prep" in text for text in operation.permission)
    assert any("core_preparation" in text for text in operation.permission)


def test_chief_saved_review_is_discoverable_without_external_connectors_or_model():
    values = descriptors(SimpleNamespace(workspace_available=True))
    enabled = {key for key, row in values.items() if row["_meta"][META]["feature_enabled"]}
    assert {"workspace.review", "workspace.read", "workspace.draft_from_saved_sources"} <= enabled
    assert all(key.startswith("workspace.") or key == "google.inspect_saved_sources" for key in enabled)
    meta = values["workspace.review"]["_meta"][META]
    assert meta["account_status"] == meta["operation_health"] == "not_checked"
    assert "when the model is disabled" in values["workspace.review"]["description"]
    assert "no new grants" in " ".join(meta["permissions"])
    assert "/conversation/resolve" in meta["recovery"] and "exact original request" in meta["recovery"]


@pytest.mark.parametrize("missing", [None, "workspace_capture_available", "workspace_prep_enabled", "workspace_session_prep_available"])
def test_brief_discovery_requires_every_existing_route_gate(missing):
    configuration = {"workspace_capture_available": True, "workspace_prep_enabled": True,
                     "workspace_session_prep_available": True}
    if missing:
        configuration[missing] = False
    row = descriptors(SimpleNamespace(**configuration))["visit_prep.read_brief"]
    assert row["_meta"][META]["feature_enabled"] is (missing is None)
    assert row["_meta"][META]["operation_health"] == "not_checked"
