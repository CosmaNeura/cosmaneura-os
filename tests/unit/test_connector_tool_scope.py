"""Closed fixed-role connector advertisements reject expanded authority upfront."""

import pytest
from lab.account_tools import ACCOUNT_SCHEMAS
from lab.cases import ROLES
from lab.connector_tools import ALL_SCHEMAS, CONNECTOR_SCHEMAS, TEAM_SCHEMAS, visible
from lab.fax_tools import FAX_SCHEMAS
from lab.mcp_runtime import MCPRuntime, _checked_arguments, _definitions
from lab.research_tools import RESEARCH_SCHEMAS
from lab.store import LabError

FORBIDDEN_FIELDS = {"actor", "actor_id", "actor_principal_id", "role", "owner_id", "box_id",
    "workspace_id", "account_id", "credentials", "secret", "url", "query", "public_query_confirmed"}
FORBIDDEN_TOOLS = {"approve", "send", "send_email", "fax_submit", "human_submit", "exercise_follow_up",
    "connect_account", "disconnect_account", "grant_permission", "prepare_fax_fixture", "shell", "run_test"}


@pytest.fixture
def synthetic_binary(tmp_path):
    path = tmp_path / "postgres-bin"
    path.mkdir()
    for name in ("initdb", "pg_ctl", "createdb"):
        tool = path / name
        tool.write_text("#!/bin/sh\nexit 1\n")
        tool.chmod(0o700)
    return path


def expected_connectors(role):
    return set(TEAM_SCHEMAS) | (set(ACCOUNT_SCHEMAS) if role in {"chief", "visit_prep", "follow_up"} else set()) | (
        set(FAX_SCHEMAS) if role in {"chief", "follow_up"} else set()) | (
        set(RESEARCH_SCHEMAS) if role == "research" else set())


@pytest.mark.parametrize("role", ROLES)
def test_each_fixed_role_sees_only_its_real_connector_boundaries(synthetic_binary, role):
    tools = MCPRuntime(None, synthetic_binary, role=role, connector_tools=True).tool_definitions()
    names = {item["name"] for item in tools}
    assert names & set(CONNECTOR_SCHEMAS) == expected_connectors(role)
    assert names == {name for name in ALL_SCHEMAS if visible(role, name)}
    assert ("delegate_team" in names) == (role == "chief")
    assert not names & FORBIDDEN_TOOLS
    for item in tools:
        schema = item["inputSchema"]
        assert schema["type"] == "object" and schema["additionalProperties"] is False
        assert not set(schema["properties"]) & (FORBIDDEN_FIELDS - {"role"} if item["name"] == "read_shared_draft" else FORBIDDEN_FIELDS)
        for nested in schema.get("$defs", {}).values():
            if nested.get("type") == "object":
                assert nested["additionalProperties"] is False
        assert item["annotations"]["openWorldHint"] is False
        assert item["annotations"]["destructiveHint"] is False
    assert next(item for item in tools if item["name"] == "save_artifact")["annotations"]["readOnlyHint"] is False
    for name in expected_connectors(role):
        definition = next(item for item in tools if item["name"] == name)
        if name in {"account_save_selected_observations", "account_select_observed_items", "fax_prepare", "research_lookup_trials", "research_save_selection"}:
            assert definition["annotations"]["readOnlyHint"] is False


@pytest.mark.parametrize("role", ROLES)
def test_connector_opt_in_preserves_legacy_tool_profile(role):
    legacy = {item["name"] for item in _definitions(role, False)}
    opted = {item["name"] for item in _definitions(role, True)}
    assert opted - legacy == expected_connectors(role)
    assert legacy <= opted


@pytest.mark.parametrize("role,name,args", [
    ("scribe", "account_read_mail_headers", {"provider": "google", "idempotency_key": "read-one"}),
    ("research", "account_read_calendar", {"provider": "google", "idempotency_key": "read-one"}),
    ("visit_prep", "fax_readiness", {"provider": "documo"}),
    ("chief", "research_lookup_trials", {"idempotency_key": "lookup-one", "expected_workspace_revision": 1}),
    ("follow_up", "research_resolve_lookup", {"idempotency_key": "lookup-one"}),
])
def test_hidden_tool_never_reaches_worker(synthetic_binary, monkeypatch, role, name, args):
    session = MCPRuntime(None, synthetic_binary, role=role, connector_tools=True)
    monkeypatch.setattr(session, "_request", lambda *_a, **_k: pytest.fail("worker reached"))
    assert session.call(name, args) == {"error": "unknown_tool"}


@pytest.mark.parametrize("field", sorted(FORBIDDEN_FIELDS))
@pytest.mark.parametrize("role,name,args", [
    ("chief", "account_read_mail_headers", {"provider": "google", "idempotency_key": "read-one"}),
    ("follow_up", "fax_readiness", {"provider": "documo"}),
    ("research", "research_lookup_trials", {"idempotency_key": "lookup-one", "expected_workspace_revision": 1}),
])
def test_authority_or_private_query_override_never_reaches_worker(synthetic_binary, monkeypatch, field, role, name, args):
    session = MCPRuntime(None, synthetic_binary, role=role, connector_tools=True)
    monkeypatch.setattr(session, "_request", lambda *_a, **_k: pytest.fail("worker reached"))
    assert session.call(name, {**args, field: "synthetic_PRIVATE_canary"}) == {"error": "invalid_tool_arguments"}


@pytest.mark.parametrize("name", sorted(FORBIDDEN_TOOLS))
def test_approval_send_setup_and_generic_execution_are_not_tools(synthetic_binary, monkeypatch, name):
    session = MCPRuntime(None, synthetic_binary, role="chief", connector_tools=True)
    monkeypatch.setattr(session, "_request", lambda *_a, **_k: pytest.fail("worker reached"))
    assert session.call(name, {}) == {"error": "unknown_tool"}


def test_argument_validator_cannot_use_startup_opt_in_to_expand_call_scope():
    with pytest.raises(LabError, match="unknown_tool"):
        _checked_arguments("scribe", "fax_prepare", {}, True)
    with pytest.raises(LabError, match="invalid_tool_arguments"):
        _checked_arguments("research", "research_lookup_trials", {
            "idempotency_key": "lookup-one", "expected_workspace_revision": True}, True)
    with pytest.raises(LabError, match="invalid_tool_arguments"):
        _checked_arguments("chief", "account_connection_status", {"provider": "external"}, True)
