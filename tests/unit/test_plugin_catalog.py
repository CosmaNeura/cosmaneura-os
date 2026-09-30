import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from cosmas_os.api.google_connection_routes import GoogleCommand
from cosmas_os.api.microsoft_connection_routes import MicrosoftCommand
from cosmas_os.api.plugin_catalog import META, definitions, find_operation, plugin_catalog
from cosmas_os.api.research_schemas import Search
from cosmas_os.api.vendor_work_schemas import VendorProposal

DELIVERY_FIELDS = {
    "spruce": ({"correspondence", "message"}, {"document"}),
    "srfax": ({"correspondence", "document"}, {"message", "uploaded_media_operation_id"}),
    "documo": ({"correspondence", "document"}, {"message", "uploaded_media_operation_id"}),
}


def delivery_request(provider):
    request = json.loads(Path("tests/fixtures/vendor_work/proposal.json").read_text())
    for field in ("uploaded_media_operation_id", "supersedes_operation_id", "acknowledge_prior_uncertainty"):
        request.pop(field)
    request["expected_outcome"] = "Prepare the synthetic reviewed follow-up."
    if provider == "spruce":
        request["message"] = "Synthetic follow-up for review."
    else:
        request["action"] = f"{provider}_fax"
        del request["message"]
        request["document"] = {
            "artifact_id": request["proposed_operation_id"], "sha256": "a" * 64,
            "byte_length": 5, "media_type": "application/pdf",
        }
    return request


def test_discovery_separates_configuration_from_account_and_operation_evidence():
    settings = SimpleNamespace(workspace_google_connection_enabled=True,
                               workspace_microsoft_connection_enabled=True)
    missing = plugin_catalog(settings, SimpleNamespace())
    assert all(not tool["_meta"][META]["feature_enabled"] for tool in missing["tools"])
    configured = plugin_catalog(settings, SimpleNamespace(google_connection=object()))
    for tool in configured["tools"]:
        meta = tool["_meta"][META]
        assert meta["feature_enabled"] is (meta["plugin"] == "google")
        assert meta["account_status"] == meta["operation_health"] == "not_checked"
        assert meta["external_send"] is False
    assert configured["_meta"]["ai.cosmas/discovery_only"] is True
    assert "no Google, Microsoft or fax inbox transport" in configured["_meta"]["ai.cosmas/inbound"]["production"]


def test_contract_inventory_has_closed_arguments_and_real_test_references():
    catalog = plugin_catalog(SimpleNamespace(), SimpleNamespace())
    ids = set()
    for tool in catalog["tools"]:
        assert set(tool) == {"name", "title", "description", "inputSchema", "annotations", "_meta"}
        meta = tool["_meta"][META]
        assert meta["id"] not in ids
        ids.add(meta["id"])
        schema = tool["inputSchema"]
        assert schema["type"] == "object" and schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])
        assert schema["properties"]["request"]["additionalProperties"] is False
        assert tool["annotations"]["destructiveHint"] is False
        for path in meta["test_files"]:
            assert Path(path).is_file(), path
        for key in ("permissions", "health_check", "completion_evidence", "recovery"):
            assert meta[key]
        assert meta["http"]["path"].startswith("/")
        assert 0 < meta["deadline_seconds"] <= 120
    assert ids == {operation.id for operation in definitions()}


@pytest.mark.parametrize("provider,model", [("google", GoogleCommand), ("microsoft", MicrosoftCommand)])
def test_personal_tools_keep_the_exact_read_actions_and_narrow_permissions(provider, model):
    for suffix, action in (("mail_headers", "mail"), ("calendar_summaries", "calendar")):
        definition = find_operation(f"{provider}.{suffix}")
        assert definition.request == {
            "type": "object", "additionalProperties": False,
            "properties": {"action": {"type": "string", "const": action}}, "required": ["action"],
        }
        assert model.model_validate({"action": action}).action == action
        assert definition.read_only and "explicit bounded read" in definition.permission
    if provider == "google":
        assert "https://www.googleapis.com/auth/gmail.metadata" in find_operation("google.mail_headers").permission
        assert "https://www.googleapis.com/auth/gmail.readonly" not in find_operation("google.mail_headers").permission


def test_research_arguments_derive_from_the_actual_review_and_revision_contract():
    operation = find_operation("research.search")
    assert operation.request == Search.model_json_schema()
    required = operation.request["required"]
    assert {"expected_revision", "team_revision", "public_query_confirmed", "idempotency_key"} <= set(required)
    assert not operation.read_only  # The public lookup also records an immutable local run.
    assert operation.public_read


@pytest.mark.parametrize("operation", ["send_email", "documo.send", "https://example.test/plugin", "../module"])
def test_discovery_never_loads_unknown_or_external_operations(operation):
    with pytest.raises(ValueError, match="unknown first-party operation"):
        find_operation(operation)


def test_mutating_a_returned_schema_does_not_change_future_discovery():
    first = plugin_catalog(SimpleNamespace(), SimpleNamespace())
    first["tools"][0]["inputSchema"]["properties"]["request"]["properties"]["action"]["const"] = "send"
    next_catalog = plugin_catalog(SimpleNamespace(), SimpleNamespace())
    assert next_catalog["tools"][0]["inputSchema"]["properties"]["request"]["properties"]["action"]["const"] == "mail"


@pytest.mark.parametrize("provider", DELIVERY_FIELDS)
def test_delivery_action_requirements_match_the_handler(provider):
    schema = find_operation(f"{provider}.prepare_delivery").request
    request = delivery_request(provider)
    assert VendorProposal.model_validate(request).action == request["action"]
    assert schema["properties"]["action"] == {"type": "string", "const": request["action"]}
    required, forbidden = DELIVERY_FIELDS[provider]
    assert required <= set(schema["required"])
    assert not forbidden & schema["properties"].keys()
    for field in required:
        missing = deepcopy(request)
        del missing[field]
        with pytest.raises(ValidationError, match="invalid delivery action fields"):
            VendorProposal.model_validate(missing)
    other_action = delivery_request("spruce" if provider != "spruce" else "documo")
    for field in forbidden:
        invalid = {**request, field: other_action.get(field, request["proposed_operation_id"])}
        with pytest.raises(ValidationError, match="invalid delivery action fields"):
            VendorProposal.model_validate(invalid)


@pytest.mark.parametrize("provider", DELIVERY_FIELDS)
def test_delivery_schema_and_handler_reject_explicit_nulls(provider):
    schema = find_operation(f"{provider}.prepare_delivery").request
    assert '"null"' not in json.dumps(schema)
    request = delivery_request(provider)
    for field in schema["properties"]:
        with pytest.raises(ValidationError, match="unknown/null field"):
            VendorProposal.model_validate({**request, field: None})


@pytest.mark.parametrize("provider", DELIVERY_FIELDS)
def test_delivery_replacement_dependencies_preserve_uncertain_send_review(provider):
    schema = find_operation(f"{provider}.prepare_delivery").request
    request = delivery_request(provider)
    prior = request["proposed_operation_id"]
    pair = {"supersedes_operation_id": prior, "acknowledge_prior_uncertainty": True}
    assert schema["dependentRequired"] == {
        "supersedes_operation_id": ["acknowledge_prior_uncertainty"],
        "acknowledge_prior_uncertainty": ["supersedes_operation_id"],
    }
    assert schema["not"] == {"required": ["supersedes_operation_id", "revises"]}
    assert VendorProposal.model_validate({**request, **pair}).supersedes_operation_id == prior
    for field, value in pair.items():
        with pytest.raises(ValidationError, match="invalid replacement"):
            VendorProposal.model_validate({**request, field: value})
    revises = {"ticket_id": prior, "expected_version": 1, "revision_id": prior, "payload_hash": "b" * 64}
    assert VendorProposal.model_validate({**request, "revises": revises}).revises is not None
    with pytest.raises(ValidationError, match="invalid replacement"):
        VendorProposal.model_validate({**request, **pair, "revises": revises})


def test_http_bindings_include_shared_workspace_and_current_identity_requirements():
    catalog = plugin_catalog(SimpleNamespace(), SimpleNamespace())
    for descriptor in catalog["tools"]:
        operation = find_operation(descriptor["_meta"][META]["id"])
        binding = descriptor["_meta"][META]["http"]
        assert binding["authentication"] == "current_clerk_jwt"
        assert binding["required_headers"] == {
            "Content-Type": "application/json",
            "X-Cosmas-Workspace-Protocol": "1",
            "X-Cosmas-Draft-Recovery": "2",
        }
        assert binding["contract_header"] == operation.header
        assert binding["contract_version"] == ("1" if operation.header else None)
