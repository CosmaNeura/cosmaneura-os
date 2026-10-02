"""Optional connector MCP profile on real owned PostgreSQL and official SDK stdio."""

import asyncio
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from lab.connector_tools import ALL_SCHEMAS, visible
from lab.fax_sandbox import bound
from lab.mcp_runtime import REPO, MCPRuntime
from lab.store import Store
from sqlalchemy import create_engine, text


@pytest.fixture
def connector_postgres_bin():
    found = shutil.which("pg_ctl")
    if not found:
        pytest.skip("Connector MCP qualification requires owned local PostgreSQL tools")
    assert found is not None
    return Path(found).resolve().parent


def checked_cleanup(root):
    receipt = json.loads((root / "cleanup.json").read_text())
    assert receipt["successful"] and receipt["worker_exited"] and receipt["pg_stopped"]
    assert not (root / "postgres/postmaster.pid").exists()
    assert not (root / "temporary-postgres-password").exists()
    return receipt


def database_checks(runtime, *, expected_vendor_work=0):
    """Read only the owned synthetic DB from the test driver, never an MCP tool."""
    assert runtime._pg is not None
    engine = create_engine(runtime._pg.url, hide_parameters=True)
    try:
        with engine.connect() as connection:
            heads = ScriptDirectory.from_config(Config(str(REPO / "alembic.ini"))).get_heads()
            assert set(connection.scalars(text("SELECT version_num FROM alembic_version"))) == set(heads)
            assert connection.scalar(text("SELECT count(*) FROM decisions")) == 0
            assert connection.scalar(text("SELECT count(*) FROM vendor_submit_claims")) == 0
            assert connection.scalar(text("SELECT count(*) FROM vendor_provider_observations")) == 0
            assert connection.scalar(text("SELECT count(*) FROM vendor_work")) == expected_vendor_work
    finally:
        engine.dispose()


def prepare_documo(readiness):
    options = readiness["options"]
    return {"provider": "documo", "expected_workspace_revision": options["entry_revision"],
        "idempotency_key": "documo-proposal-one", "proposed_operation_id": readiness["proposal_ids"]["fax"],
        "source": options["source"], "connection": {key: options["connections"][0][key]
            for key in ("id", "revision", "public_sha256")}, "action": "fax",
        "document": readiness["document"], "correspondence": {key: options["correspondences"][0][key]
            for key in ("id", "revision", "public_sha256")}}


def select_account(receipt, revision, key):
    return {"observation_id": receipt["observation_id"], "observation_sha256": receipt["observation_sha256"],
        "item_ids": [receipt["observation"]["items"][0]["id"]],
        "expected_workspace_revision": revision, "idempotency_key": key}


def test_connector_runtime_google_reads_select_exact_evidence_without_draft_leak(tmp_path, connector_postgres_bin):
    root = tmp_path / "mcp-google"
    with MCPRuntime(root, connector_postgres_bin, role="visit_prep", connector_tools=True) as runtime:
        status = runtime.status()
        assert status["connector_tools"] is True and status["schema_setup"] == "alembic-upgrade-head"
        assert status["usage"] == {"model_calls": 0, "tokens": 0}
        original_ids = {source["id"] for source in runtime.call("list_sources", {})}
        for name in ("account_read_mail_headers", "account_read_calendar"):
            args = {"provider": "google", "idempotency_key": name}
            receipt = runtime.call(name, args)
            assert receipt["status"] == "ready", receipt
            replay = runtime.call(name, args)
            assert replay["idempotent_replay"] and replay["observation"] == receipt["observation"]
            assert replay["observation_sha256"] == receipt["observation_sha256"]
            assert runtime.call("list_artifacts", {}) == []
            revision = runtime.call("application_status", {})["workspace_revision"]
            selection = select_account(receipt, revision, "selected-" + name)
            saved = runtime.call("account_save_selected_observations", selection)
            retry = runtime.call("account_save_selected_observations", selection)
            assert saved["status"] == retry["status"] == "saved", (saved, retry)
            assert saved["entry_id"] == retry["entry_id"] and retry["idempotent_replay"]
            source = runtime.call("read_source", {"source_id": saved["entry_id"]})
            assert hashlib.sha256(source["content"].encode()).hexdigest() == saved["content_sha256"]
            payload = json.loads(source["content"])
            assert payload["source_observation_sha256"] == receipt["observation_sha256"]
            assert payload["items"] == [receipt["observation"]["items"][0]]
        assert len(runtime.call("list_sources", {})) == len(original_ids) + 2
        assert runtime.status()["artifact_count"] == 0
        assert runtime.call("account_read_mail_headers", {"provider": "google", "idempotency_key": "bad",
            "actor_id": "synthetic-foreign"}) == {"error": "invalid_tool_arguments"}
        assert runtime.call("send_email", {}) == {"error": "unknown_tool"}
        database_checks(runtime)
    checked_cleanup(root)
    assert Store(root).visible("mcp-walk_in", "visit_prep") == []
    assert len(Store(root).visible("mcp-walk_in:accounts", "visit_prep")) == 2


def test_connector_runtime_research_fixed_lookup_selected_save_and_recovery(tmp_path, connector_postgres_bin):
    root = tmp_path / "mcp-research"
    with MCPRuntime(root, connector_postgres_bin, role="research", connector_tools=True) as runtime:
        revision = runtime.call("application_status", {})["workspace_revision"]
        command = {"expected_workspace_revision": revision, "idempotency_key": "fixed-trial-one"}
        refused = runtime.call("research_lookup_trials", {**command, "query": "synthetic_PRIVATE_encounter"})
        assert refused == {"error": "invalid_tool_arguments"}
        lookup = runtime.call("research_lookup_trials", command)
        assert lookup["provider_reads"] == 1 and lookup["external_effects"] == 0, lookup
        result = lookup["result"]
        assert result["state"] == "completed" and result["results"]
        assert "synthetic_PRIVATE_encounter" not in json.dumps(result)
        resolved = runtime.call("research_resolve_lookup", {"idempotency_key": command["idempotency_key"]})
        assert resolved["provider_reads"] == 1 and resolved["result"] == result
        retried = runtime.call("research_lookup_trials", command)
        assert retried["provider_reads"] == 1 and retried["result"] == result
        selected_hash = result["results"][0]["sha256"]
        selection = {"run_id": result["run_id"], "source_hashes": [selected_hash],
            "expected_workspace_revision": runtime.call("application_status", {})["workspace_revision"],
            "idempotency_key": "trial-selection-one"}
        wrong = runtime.call("research_save_selection", {**selection, "source_hashes": ["0" * 64]})
        assert wrong["error"] == "research_selection_unavailable"
        saved = runtime.call("research_save_selection", selection)
        repeated = runtime.call("research_save_selection", selection)
        assert saved["result"]["entry_id"] == repeated["result"]["entry_id"], (saved, repeated)
        source = runtime.call("read_source", {"source_id": saved["result"]["entry_id"]})
        assert selected_hash in source["content"] and "SYNTHETIC" in source["content"]
        assert runtime.call("account_connection_status", {"provider": "google"}) == {"error": "unknown_tool"}
        assert runtime.status()["artifact_count"] == 0 and runtime.status()["schema_setup"] == "alembic-upgrade-head"
        database_checks(runtime)
    checked_cleanup(root)
    assert "synthetic_PRIVATE_encounter" not in (root / "events.jsonl").read_text()


def test_fresh_connector_runtime_four_fax_readiness_and_one_unsubmitted_proposal(tmp_path, connector_postgres_bin):
    # Account/research evidence intentionally invalidates source review. This
    # fresh fax-only episode uses only the separately reviewed startup fixture.
    root = tmp_path / "mcp-fax"
    with MCPRuntime(root, connector_postgres_bin, role="follow_up", connector_tools=True) as runtime:
        readiness = {}
        for provider in ("spruce", "srfax", "documo", "efax"):
            readiness[provider] = runtime.call("fax_readiness", {"provider": provider})
            assert readiness[provider]["ready_for_proposal"], readiness[provider]
            assert readiness[provider]["document_custody"] == "ready"
            assert readiness[provider]["broker"]["external_calls"] == 0
            assert readiness[provider]["broker"]["simulated_provider_calls"] == 0
        command = prepare_documo(readiness["documo"])
        prepared = runtime.call("fax_prepare", command)
        replay = runtime.call("fax_prepare", command)
        detail = prepared["detail"]
        assert replay["detail"]["summary"]["ticket_id"] == detail["summary"]["ticket_id"]
        assert detail["summary"]["state"] == "pending_approval"
        assert detail["summary"]["dispatch"] == "not_started"
        assert detail["summary"]["acceptance"] == "not_observed"
        args = {"provider": "documo", "ticket_id": detail["summary"]["ticket_id"],
            **bound(detail, "documo-inspect-one"), "refresh": False}
        observed = runtime.call("fax_receipt", args)
        assert observed["detail"]["summary"] == detail["summary"]
        assert observed["broker"]["simulated_provider_calls"] == 0
        assert runtime.call("fax_receipt", {**args, "refresh": True})["error"] == "vendor_reference_unavailable"
        assert runtime.call("fax_prepare", {**command, "actor": "human"}) == {"error": "invalid_tool_arguments"}
        for forbidden in ("approve", "human_submit", "fax_submit", "prepare_fax_fixture"):
            assert runtime.call(forbidden, {}) == {"error": "unknown_tool"}
        assert runtime.call("application_status", {})["workflow"]["status"] == "drafts_only"
        database_checks(runtime, expected_vendor_work=1)
    checked_cleanup(root)


def test_official_sdk_stdio_connector_profile_keeps_closed_schema_and_exact_evidence(tmp_path, connector_postgres_bin):
    pytest.importorskip("mcp")
    root = tmp_path / "sdk-chief"

    async def exercise():
        from mcp import ClientSession, StdioServerParameters, types
        from mcp.client.stdio import stdio_client

        parameters = StdioServerParameters(command=sys.executable,
            args=["-B", "-m", "lab.mcp_server", "--postgres-bin", str(connector_postgres_bin),
                "--output", str(root), "--case", "walk_in", "--role", "chief", "--mode", "replay",
                "--connector-tools", "--max-seconds", "120"], cwd=str(REPO),
            env={"PATH": os.defpath, "PYTHONPATH": str(REPO / "src") + os.pathsep + str(REPO),
                "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"})
        with (tmp_path / "sdk-stderr.log").open("w") as stderr:
            async with stdio_client(parameters, errlog=stderr) as streams:
                async with ClientSession(*streams, read_timeout_seconds=60) as session:
                    initialized = await session.initialize()
                    assert initialized.protocol_version
                    tools = (await session.list_tools()).tools
                    assert {tool.name for tool in tools} == {name for name in ALL_SCHEMAS if visible("chief", name)}
                    for tool in tools:
                        assert tool.input_schema["additionalProperties"] is False
                        assert tool.output_schema == {"type": "object", "properties": {"result": {}},
                            "required": ["result"], "additionalProperties": False}

                    async def call(name, args):
                        response = await session.call_tool(name, args)
                        assert len(response.content) == 1 and response.content[0].type == "text"
                        assert json.loads(response.content[0].text) == response.structured_content
                        value = response.structured_content["result"]
                        assert response.is_error == (isinstance(value, dict) and "error" in value)
                        return value

                    read_args = {"provider": "google", "idempotency_key": "sdk-mail-one"}
                    receipt = await call("account_read_mail_headers", read_args)
                    assert receipt["status"] == "ready"
                    replay = await call("account_read_mail_headers", read_args)
                    assert replay["observation_sha256"] == receipt["observation_sha256"] and replay["idempotent_replay"]
                    status = await call("application_status", {})
                    compact = {"read_key": receipt["read_key"],
                        "item_ids": [receipt["observation"]["items"][0]["id"]],
                        "expected_workspace_revision": status["workspace_revision"],
                        "idempotency_key": "sdk-selection-one"}
                    saved = await call("account_select_observed_items", compact)
                    assert saved["status"] == "saved"
                    repeated_save = await call("account_select_observed_items", compact)
                    assert repeated_save["entry_id"] == saved["entry_id"] and repeated_save["idempotent_replay"]
                    assert saved["source_observation_sha256"] == receipt["observation_sha256"]
                    source = await call("read_source", {"source_id": saved["entry_id"]})
                    assert hashlib.sha256(source["content"].encode()).hexdigest() == saved["content_sha256"]
                    assert (await call("approve", {}))["error"] == "unknown_tool"
                    assert (await call("account_read_mail_headers", {**read_args, "owner_id": "foreign"}))["error"] == "invalid_tool_arguments"
                    resource = await session.read_resource("cosmabot://lab/status")
                    resource_content = resource.contents[0]
                    assert isinstance(resource_content, types.TextResourceContents)
                    metadata = json.loads(resource_content.text)
                    assert metadata["connector_tools"] and metadata["schema_setup"] == "alembic-upgrade-head"
                    assert metadata["artifact_count"] == 0 and metadata["external_effects"] == 0

                    headers = await call("google_inbox_read_headers", {"idempotency_key": "sdk-inbox-read"})
                    assert headers["metadata_only"] and headers["incomplete_message"]
                    message = headers["observation"]["items"][0]
                    revision = (await call("application_status", {}))["workspace_revision"]
                    selected_inbox = await call("google_inbox_select_message", {"read_key": "sdk-inbox-read",
                        "message_id": message["id"], "expected_workspace_revision": revision,
                        "idempotency_key": "sdk-inbox-select"})
                    assert selected_inbox["status"] == "saved" and selected_inbox["source_ref"].startswith("source-")
                    assert (await call("read_selected_source", {"source_ref": selected_inbox["source_ref"]}))["id"] == selected_inbox["entry_id"]
                    draft = await call("google_inbox_prepare_review", {"selection_key": "sdk-inbox-select",
                        "expected_workspace_revision": (await call("application_status", {}))["workspace_revision"],
                        "idempotency_key": "sdk-inbox-review"})
                    assert draft["status"] == "private_draft" and "source_ref" not in draft
                    reviews = await call("google_inbox_list_reviews", {})
                    assert any(item["review_key"] == "sdk-inbox-review" for item in reviews["items"])
                    review = await call("google_inbox_review_status", {"review_key": "sdk-inbox-review"})
                    assert review["f8"] is None and review["metadata_reviewed_by_human"] is False
                    assert review["whole_message_reviewed"] is False and review["completed"] is False
                    availability = await call("scheduling_read_availability", {"timezone": "America/New_York"})
                    assert len(availability["availability"]["slots"]) == 2
                    proposed = await call("scheduling_prepare_observed", {
                        "slot_ref": availability["availability"]["slots"][0]["slot_ref"],
                        "expected_workspace_revision": availability["workspace_revision"], "idempotency_key": "sdk-appointment"})
                    assert proposed["detail"]["operation_id"] is None and proposed["detail"]["appointment_saved"] is False
                    await call("scheduling_list_proposals", {})
                    assert (await call("scheduling_inspect_prepared", {"proposal_ref": proposed["proposal_ref"]}))["detail"] == proposed["detail"]
                    for forbidden in ("human_review_assign", "human_accept", "human_execute", "book_appointment"):
                        assert (await call(forbidden, {}))["error"] == "unknown_tool"

    asyncio.run(exercise())
    checked_cleanup(root)
