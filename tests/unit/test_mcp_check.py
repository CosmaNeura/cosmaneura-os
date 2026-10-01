"""Checker qualification; real stdio/owned-Postgres evidence is a separate CLI run."""

import asyncio
import json
import sqlite3
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from lab import mcp_check as check
from lab.cases import CASES
from lab.engine import SCHEMAS, World
from lab.store import Store

SOURCE = "11111111-1111-4111-8111-111111111111"
WORKSPACE = "22222222-2222-4222-8222-222222222222"


class SyntheticApplication:
    def sources(self, metadata_only=False):
        return [{"id": SOURCE, "revision": 1, "label": "Invented walk-in",
                 **({} if metadata_only else {"content": "Synthetic encounter; date of birth unknown."})}]

    def status(self):
        return {"workspace_id": WORKSPACE, "workflow": {"status": "drafts_only", "external_effects": 0},
                "synthetic": True, "human_review": "simulated provider only; agents cannot approve"}

    def check_agent(self, role):
        assert role in check.ROLES

    def agent_id(self, role):
        return "synthetic:" + role


def response(value, *, failed=None):
    structured = {"result": value}
    return SimpleNamespace(structured_content=structured,
                           content=[SimpleNamespace(type="text", text=json.dumps(structured))],
                           is_error=(isinstance(value, dict) and "error" in value) if failed is None else failed)


def catalog():
    return [SimpleNamespace(name=name, input_schema=model.model_json_schema(),
                            output_schema={"type": "object", "additionalProperties": False,
                                          "properties": {"result": {}}, "required": ["result"]})
            for name, (model, _) in SCHEMAS.items()]


class LocalSessionDouble:
    """Only unit-tests the independent checker; not described as MCP wire evidence."""

    def __init__(self, tmp_path, fault="none"):
        self.world = World(Store(tmp_path), "check", CASES["walk_in"], SyntheticApplication(), fault=fault)
        self.calls = []

    async def initialize(self):
        return SimpleNamespace(protocol_version="synthetic-unit-test")

    async def list_tools(self):
        return SimpleNamespace(tools=catalog(), next_cursor=None)

    async def call_tool(self, name, arguments):
        value = self.world.execute("chief", name, arguments)
        self.calls.append((name, deepcopy(arguments), value))
        return response(value)

    async def read_resource(self, uri):
        value = {"schema": "cosmabot-mcp-lab.v1", "state": "ready", "synthetic": True,
                 "case": "walk_in", "role": "chief", "mode": "replay", "fault": self.world.fault,
                 "artifacts": self.world.store.visible("check", "chief"), "artifact_count": 5,
                 "faults_seen": sorted(self.world.faults_seen), "failures": self.world.failures,
                 "tool_count": self.world.tool_count, "usage": {"model_calls": 0, "tokens": 0},
                 "limits": {"concurrency": 3}, "external_effects": 0,
                 "roles": list(check.ROLES),
                 "source": {"commit": "f" * 40, "source_sha256": "a" * 64}}
        return SimpleNamespace(contents=[SimpleNamespace(uri=uri, text=json.dumps(value))])


@pytest.mark.parametrize("fault", check.FAULTS)
def test_checker_drives_exact_sources_handoffs_and_one_successful_chief_save(tmp_path, fault):
    pytest.importorskip("jsonschema")
    session = LocalSessionDouble(tmp_path, fault)
    result = asyncio.run(check.exercise(session, fault))
    assert result["artifact_count"] == 5 and result["external_effects"] == 0
    assert result["wire_write_retries"] == 0 and len(result["source_reads"]) == 1
    assert {name for name, _, _ in session.calls} == set(check.KEYS) | {"unknown_tool"}
    saves = [(args, reply) for name, args, reply in session.calls if name == "save_artifact"]
    assert sum("error" not in reply for _, reply in saves) == 1
    assert session.world.source_reads["chief"] == {SOURCE}
    assert len(session.world.faults_seen) == (fault != "none")
    with sqlite3.connect(tmp_path / "artifacts.sqlite3") as db:
        assert db.execute("SELECT count(*) FROM artifacts").fetchone()[0] == 5
    encoded = json.dumps(result)
    assert "Synthetic encounter;" not in encoded and "Synthetic Chief review:" not in encoded
    assert check.durable_fault_metadata(tmp_path, fault)["injected_fault_count"] == (fault != "none")


@pytest.mark.parametrize("mutation", ["extra_tool", "actor", "open_arguments", "no_output"])
def test_checker_rejects_widened_tool_contract(mutation):
    pytest.importorskip("jsonschema")
    tools = catalog()
    if mutation == "extra_tool":
        tools.append(SimpleNamespace(name="approve"))
    elif mutation == "actor":
        tools[0].input_schema["properties"]["actor"] = {"type": "string"}
    elif mutation == "open_arguments":
        tools[0].input_schema["additionalProperties"] = True
    else:
        tools[0].output_schema = None
    with pytest.raises(check.CheckFailed):
        check.validate_catalog(tools)


def saved_artifact(**changes):
    payload = {"body": "Synthetic reviewed-source draft, still requiring human review.",
               "source_ids": [SOURCE], "dependencies": [], "share_with": ["chief", "follow_up"], **changes}
    return {"id": "scribe", "role": "scribe", "sha256": check.digest(payload), **payload}


@pytest.mark.parametrize("mutation", ["body_tamper", "source", "dependencies", "share", "role"])
def test_checker_rejects_misattribution_or_rewritten_artifacts(mutation):
    value = saved_artifact()
    if mutation == "body_tamper":
        value["body"] += " Altered later."
    elif mutation == "source":
        value = saved_artifact(source_ids=[WORKSPACE])
    elif mutation == "dependencies":
        value = saved_artifact(dependencies=[{"artifact_id": "research", "sha256": "a" * 64}])
    elif mutation == "share":
        value = saved_artifact(share_with=["chief"])
    else:
        value["role"] = "chief"
    with pytest.raises(check.CheckFailed):
        check.artifact(value, {"artifact_id": "scribe", "sha256": value["sha256"]}, [SOURCE], [])


@pytest.mark.parametrize("mutation", ["error_flag", "text", "wrapper", "extra_content"])
def test_checker_rejects_ambiguous_wire_results(mutation):
    value = response({"error": "unknown_tool"})
    if mutation == "error_flag":
        value.is_error = False
    elif mutation == "text":
        value.content[0].text = '{"result": "a different result"}'
    elif mutation == "wrapper":
        value.structured_content["actor"] = "chief"
    else:
        value.content.append(SimpleNamespace(type="image"))
    with pytest.raises(check.CheckFailed):
        check.unpack(value)


@pytest.mark.parametrize("changes", [{"synthetic": False}, {"workspace_id": SOURCE},
                                       {"workflow": {"status": "delivered", "external_effects": 1}}])
def test_checker_rejects_wrong_workspace_or_external_effect(changes):
    with pytest.raises(check.CheckFailed):
        check.application_status({**SyntheticApplication().status(), **changes}, WORKSPACE)


def test_child_command_is_fixed_and_does_not_forward_credentials(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "private-sentinel")
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "private-sentinel")
    parameters = check.server_parameters(tmp_path / "server", Path("/synthetic/postgres"), "none")
    assert parameters["args"][:2] == ["-m", "lab.mcp_server"]
    assert parameters["args"][6:] == ["--case", "walk_in", "--role", "chief", "--mode", "replay", "--fault", "none"]
    assert "private-sentinel" not in json.dumps(parameters)


def test_cli_refuses_existing_outputs_before_starting_any_child(tmp_path):
    for name in ("initdb", "pg_ctl", "createdb"):
        (tmp_path / name).touch()
    with pytest.raises(check.CheckFailed, match="new_output_required"):
        check.main(["--postgres-bin", str(tmp_path), "--output", str(tmp_path)])


@pytest.mark.parametrize("mutation", ["missing_fault", "changed_retry", "extra_retry", "missing_artifact"])
def test_fault_evidence_must_prove_one_exact_recovery_and_five_durable_artifacts(tmp_path, mutation):
    session = LocalSessionDouble(tmp_path, "lost_save_reply")
    session.world.run_agent("chief")
    events = [json.loads(line) for line in session.world.store.events.read_text().splitlines()]
    failed = next(event for event in events if str(event.get("error", "")).startswith("injected_"))
    saved = next(event for event in events if event.get("role") == "scribe"
                 and event.get("tool") == "save_artifact" and event.get("ok") is True)
    if mutation == "missing_fault":
        events.remove(failed)
    elif mutation == "changed_retry":
        saved["arguments"]["body"] += " A different operation."
    elif mutation == "extra_retry":
        events.append(saved)
    else:
        with sqlite3.connect(tmp_path / "artifacts.sqlite3") as db:
            db.execute("DELETE FROM artifacts WHERE role='research'")
    session.world.store.events.write_text("".join(json.dumps(event) + "\n" for event in events))
    with pytest.raises(check.CheckFailed):
        check.durable_fault_metadata(tmp_path, "lost_save_reply")


def test_report_rejects_extra_source_metadata_instead_of_exporting_it(tmp_path):
    class UnexpectedMetadata(LocalSessionDouble):
        async def read_resource(self, uri):
            value = await super().read_resource(uri)
            content = json.loads(value.contents[0].text)
            content["source"]["body"] = "PRIVATE sentinel must never enter report"
            value.contents[0].text = json.dumps(content)
            return value

    session = UnexpectedMetadata(tmp_path)
    session.world.run_agent("chief")
    refs = check.metadata(session.world.store.visible("check", "chief"), check.ROLES)
    with pytest.raises(check.CheckFailed, match="invalid_source_fingerprint"):
        asyncio.run(check.status_resource(session, "none", refs))
