"""Independent official-SDK stdio check of the synthetic laboratory, never a live agent."""

import argparse
import asyncio
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import quote
from uuid import UUID

REPO = Path(__file__).resolve().parents[1]
ROLES = {"chief", "scribe", "visit_prep", "research", "follow_up"}
UPSTREAM = {"scribe", "visit_prep", "research"}
FAULTS = ("none", "read_timeout", "lost_save_reply")
KEYS = {
    "list_sources": set(), "read_source": {"source_id"}, "list_artifacts": set(),
    "read_artifact": {"artifact_id", "sha256"},
    "save_artifact": {"body", "source_ids", "dependencies", "share_with"},
    "delegate_team": {"roles"}, "application_status": set(),
}


class CheckFailed(Exception):
    """Only fixed checker codes, never response content, reach reports."""


def require(condition, code):
    if not condition:
        raise CheckFailed(code)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def uuid_text(value):
    try:
        return isinstance(value, str) and str(UUID(value)) == value
    except ValueError:
        return False


def hash_text(value):
    return isinstance(value, str) and len(value) == 64 and set(value) <= set("0123456789abcdef")


def validate_catalog(tools):
    """Inspect the wire advertisement without importing the server or World schemas."""
    from jsonschema import Draft202012Validator

    require(len(tools) == 7 and {tool.name for tool in tools} == set(KEYS), "unexpected_tool_catalog")
    schemas = {}
    for tool in tools:
        schema = tool.input_schema
        require(schema.get("type") == "object" and schema.get("additionalProperties") is False,
                "open_tool_arguments")
        require(set(schema.get("properties", {})) == KEYS[tool.name]
                and set(schema.get("required", [])) == KEYS[tool.name], "tool_argument_contract_changed")
        require(isinstance(tool.output_schema, dict), "output_schema_missing")
        for value in (schema, tool.output_schema):
            Draft202012Validator.check_schema(value)
        schemas[tool.name] = Draft202012Validator(tool.output_schema)
    return schemas


def unpack(result, validator=None):
    structured = result.structured_content
    require(isinstance(structured, dict) and set(structured) == {"result"}, "invalid_result_envelope")
    if validator is not None:
        require(validator.is_valid(structured), "output_schema_mismatch")
    require(len(result.content) == 1 and result.content[0].type == "text", "unexpected_result_content")
    try:
        text = json.loads(result.content[0].text)
    except (TypeError, ValueError):
        raise CheckFailed("invalid_result_json") from None
    require(text == structured, "structured_text_mismatch")
    value = structured["result"]
    error = isinstance(value, dict) and "error" in value
    require(result.is_error is error, "error_flag_mismatch")
    return value, error


def metadata(items, expected_roles):
    require(isinstance(items, list) and len(items) == len(expected_roles), "artifact_count_mismatch")
    found = {}
    for item in items:
        require(isinstance(item, dict) and set(item) == {"id", "role", "sha256"}, "invalid_artifact_metadata")
        require(item["id"] == item["role"] and item["role"] in expected_roles
                and item["role"] not in found and hash_text(item["sha256"]), "artifact_identity_mismatch")
        found[item["role"]] = {"artifact_id": item["id"], "sha256": item["sha256"]}
    require(set(found) == expected_roles, "artifact_roles_mismatch")
    return found


def artifact(value, reference, source_ids, dependencies):
    fields = {"id", "role", "sha256", "body", "source_ids", "dependencies", "share_with"}
    require(isinstance(value, dict) and set(value) == fields, "invalid_saved_artifact")
    require(value["id"] == value["role"] == reference["artifact_id"]
            and value["sha256"] == reference["sha256"], "saved_artifact_identity_mismatch")
    payload = {key: item for key, item in value.items() if key not in {"id", "role", "sha256"}}
    require(digest(payload) == value["sha256"], "artifact_hash_mismatch")
    require(isinstance(value["body"], str) and 10 <= len(value["body"]) <= 4000, "invalid_artifact_body")
    require(isinstance(value["source_ids"], list) and set(value["source_ids"]) == set(source_ids)
            and len(value["source_ids"]) == len(source_ids), "artifact_source_mismatch")
    require(isinstance(value["dependencies"], list)
            and sorted(value["dependencies"], key=lambda item: item["artifact_id"])
            == sorted(dependencies, key=lambda item: item["artifact_id"]), "artifact_dependency_mismatch")
    require(isinstance(value["share_with"], list) and set(value["share_with"]) <= ROLES, "artifact_share_mismatch")
    if value["role"] != "chief":
        require("chief" in value["share_with"], "artifact_not_shared_with_chief")
    if value["role"] in UPSTREAM:
        require("follow_up" in value["share_with"], "artifact_not_shared_with_follow_up")
    return {"role": value["role"], "sha256": value["sha256"], "source_count": len(source_ids),
            "dependency_count": len(dependencies)}


def application_status(value, workspace=None):
    require(isinstance(value, dict) and value.get("synthetic") is True
            and uuid_text(value.get("workspace_id")), "not_synthetic_workspace")
    require(value.get("workflow") == {"status": "drafts_only", "external_effects": 0}, "unexpected_external_effect")
    require(workspace is None or value["workspace_id"] == workspace, "workspace_changed")
    return value["workspace_id"]


async def status_resource(session, fault, references):
    resource = await session.read_resource("cosmabot://lab/status")
    require(len(resource.contents) == 1 and str(resource.contents[0].uri) == "cosmabot://lab/status",
            "invalid_status_resource")
    value = json.loads(resource.contents[0].text)
    require(value.get("schema") == "cosmabot-mcp-lab.v1" and value.get("state") == "ready"
            and value.get("synthetic") is True and value.get("mode") == "replay"
            and value.get("case") == "walk_in" and value.get("role") == "chief", "runtime_identity_mismatch")
    require(value.get("fault") == fault and value.get("external_effects") == 0
            and value.get("usage") == {"model_calls": 0, "tokens": 0}, "runtime_mode_mismatch")
    expected = [] if fault == "none" else ["read_source" if fault == "read_timeout" else "save_artifact"]
    require(value.get("faults_seen") == expected and value.get("failures") == [], "fault_recovery_failed")
    require(value.get("artifact_count") == 5 and metadata(value.get("artifacts"), ROLES) == references,
            "runtime_artifact_mismatch")
    require(isinstance(value.get("roles"), list) and set(value["roles"]) == ROLES, "runtime_roles_mismatch")
    require(value.get("limits", {}).get("concurrency") == 3, "parallel_delegation_not_configured")
    require(type(value.get("tool_count")) is int and 1 <= value["tool_count"] <= 120, "tool_budget_invalid")
    source = value.get("source")
    require(isinstance(source, dict) and set(source) == {"commit", "source_sha256"}
            and isinstance(source["commit"], str) and len(source["commit"]) == 40
            and set(source["commit"]) <= set("0123456789abcdef") and hash_text(source["source_sha256"]),
            "invalid_source_fingerprint")
    return {"faults_seen": expected, "tool_count": value["tool_count"], "source": value["source"],
            "model_calls": 0, "tokens": 0, "concurrency": 3}


async def exercise(session, fault="none"):
    """All agent work crosses ClientSession; no in-process World calls or write retries."""
    started = time.monotonic()
    initialized = await session.initialize()
    listing = await session.list_tools()
    require(not listing.next_cursor, "unexpected_catalog_pagination")
    schemas = validate_catalog(listing.tools)
    calls = []

    async def call(name, arguments, *, error=None):
        at = time.monotonic()
        response = await session.call_tool(name, arguments=arguments)
        value, failed = unpack(response, schemas.get(name))
        calls.append({"tool": name, "ok": not failed,
                      "duration_ms": round((time.monotonic() - at) * 1000)})
        require(failed == (error is not None), "unexpected_tool_outcome")
        if failed:
            require(value.get("error") == error, "unexpected_tool_error")
        return value

    workspace = application_status(await call("application_status", {}))
    await call("unknown_tool", {}, error="unknown_tool")
    await call("list_sources", {"actor": "simulated_provider"}, error="invalid_tool_arguments")
    sources = await call("list_sources", {})
    require(isinstance(sources, list) and 1 <= len(sources) <= 8, "invalid_source_list")
    ids = [item.get("id") for item in sources if isinstance(item, dict)]
    require(len(ids) == len(sources) and len(set(ids)) == len(ids) and all(map(uuid_text, ids)), "invalid_source_identity")
    payload = {"body": "Synthetic Chief review: original encounter source and exact team drafts read. "
               "Date of birth remains unknown. Human review is required; no external action occurred.",
               "source_ids": ids, "dependencies": [], "share_with": ["follow_up"]}
    await call("save_artifact", payload, error="unread_or_foreign_citation")
    source_proof = []
    for item in sources:
        require(set(item) == {"id", "revision", "label"} and type(item["revision"]) is int
                and item["revision"] >= 1, "invalid_source_metadata")
        value = await call("read_source", {"source_id": item["id"]})
        require(isinstance(value, dict) and set(value) == {*item, "content"}
                and all(value[key] == item[key] for key in item)
                and isinstance(value["content"], str) and value["content"], "source_read_mismatch")
        source_proof.append({"id": item["id"], "revision": item["revision"],
                             "sha256": hashlib.sha256(value["content"].encode()).hexdigest()})
    await call("save_artifact", payload, error="chief_must_read_follow_up_result")
    require(await call("list_artifacts", {}) == [], "refused_save_created_artifact")
    delegated = await call("delegate_team", {"roles": ["scribe", "visit_prep", "research"]})
    require(isinstance(delegated, dict) and {item["role"] for item in delegated.get("results", [])} == UPSTREAM
            and len(delegated["results"]) == 3
            and all(item["status"] == "saved" for item in delegated["results"]), "upstream_delegation_failed")
    first_useful_ms = round((time.monotonic() - started) * 1000)
    upstream = metadata(await call("list_artifacts", {}), UPSTREAM)
    artifacts = [artifact(await call("read_artifact", ref), ref, ids, []) for ref in upstream.values()]
    followed = await call("delegate_team", {"roles": ["follow_up"]})
    require(isinstance(followed, dict) and len(followed.get("results", [])) == 1
            and followed["results"][0].get("role") == "follow_up"
            and followed["results"][0].get("status") == "saved", "follow_up_delegation_failed")
    shared = metadata(await call("list_artifacts", {}), UPSTREAM | {"follow_up"})
    require(all(shared[role] == ref for role, ref in upstream.items()), "upstream_changed")
    ref = shared["follow_up"]
    artifacts.append(artifact(await call("read_artifact", ref), ref, ids, list(upstream.values())))
    payload["dependencies"] = list(shared.values())
    bad = dict(payload, dependencies=[{**ref, "sha256": "0" * 64}])
    await call("save_artifact", bad, error="unread_or_stale_dependency")
    saved = await call("save_artifact", payload)
    chief = {"artifact_id": "chief", "sha256": digest(payload)}
    artifacts.append(artifact(saved, chief, ids, list(shared.values())))
    all_saved = metadata(await call("list_artifacts", {}), ROLES)
    require(all_saved == {**shared, "chief": chief}, "final_artifacts_changed")
    artifact(await call("read_artifact", chief), chief, ids, list(shared.values()))
    application_status(await call("application_status", {}), workspace)
    require(set(KEYS) <= {entry["tool"] for entry in calls}, "tool_coverage_incomplete")
    runtime = await status_resource(session, fault, all_saved)
    return {"protocol_version": initialized.protocol_version, "workspace_id": workspace,
            "source_reads": source_proof, "artifacts": artifacts, "artifact_count": len(artifacts),
            "wire_calls": calls, "time_to_first_useful_result_ms": first_useful_ms,
            "elapsed_ms": round((time.monotonic() - started) * 1000), "external_effects": 0,
            "human_approval_or_send_tools": False, "wire_write_retries": 0, "runtime": runtime}


def durable_fault_metadata(root, fault):
    """Additional local evidence, distinct from the successful MCP wire calls."""
    path = root / "events.jsonl"
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 4_000_000,
            "invalid_event_evidence")
    events = [json.loads(line) for line in path.read_text().splitlines()]
    active, peak = set(), 0
    for event in events:
        if event["role"] in UPSTREAM:
            if event["kind"] == "agent_started":
                active.add(event["role"])
                peak = max(peak, len(active))
            elif event["kind"] in {"agent_completed", "agent_failed"}:
                active.discard(event["role"])
    injected = [event for event in events if str(event.get("error", "")).startswith("injected_")]
    require(len(injected) == (fault != "none"), "fault_not_exercised_once")
    recovery = None
    if injected:
        failed = injected[0]
        role, tool, code = (("research", "read_source", "injected_timeout_retry_read") if fault == "read_timeout"
                            else ("scribe", "save_artifact", "injected_lost_reply_write_may_have_succeeded; read saved artifact or retry identical arguments"))
        require(failed.get("role") == role and failed.get("tool") == tool and failed["error"] == code,
                "wrong_fault_injected")
        attempts = [event for event in events if event.get("role") == role and event.get("tool") == tool]
        require(len(attempts) == 2 and attempts[0] == failed and attempts[1].get("ok") is True
                and attempts[0]["arguments"] == attempts[1]["arguments"], "nonidentical_or_repeated_recovery")
        recovery = {"role": role, "tool": tool, "attempts": 2, "identical_arguments": True,
                    "arguments_sha256": digest(failed["arguments"])}
    db_path = root / "artifacts.sqlite3"
    require(db_path.is_file() and not db_path.is_symlink(), "artifact_store_missing")
    with sqlite3.connect("file:" + quote(str(db_path)) + "?mode=ro", uri=True) as db:
        rows = db.execute("SELECT role, count(*) FROM artifacts GROUP BY role").fetchall()
    require(dict(rows) == dict.fromkeys(ROLES, 1), "duplicate_or_missing_durable_artifact")
    return {"injected_fault_count": len(injected), "recovery": recovery, "durable_artifact_count": 5,
            "duplicate_artifact_count": 0, "observed_parallel_specialists": peak,
            "evidence_level": "local metadata after SDK shutdown"}


def server_parameters(output, postgres_bin, fault):
    """The client cannot select an actor per call or connect to an arbitrary endpoint."""
    return {"command": sys.executable,
            "args": ["-m", "lab.mcp_server", "--postgres-bin", str(postgres_bin), "--output", str(output),
                     "--case", "walk_in", "--role", "chief", "--mode", "replay", "--fault", fault],
            "cwd": str(REPO),
            "env": {"PATH": os.defpath, "PYTHONPATH": str(REPO / "src") + os.pathsep + str(REPO),
                    "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"}}


async def run_one(output, postgres_bin, fault):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    output.mkdir(mode=0o700)
    server_output = output / "server"
    with (output / "server-stderr.log").open("w") as stderr:
        async with stdio_client(StdioServerParameters(**server_parameters(server_output, postgres_bin, fault)), errlog=stderr) as streams:
            async with ClientSession(*streams, read_timeout_seconds=60) as session:
                result = await exercise(session, fault)
    cleanup = json.loads((server_output / "cleanup.json").read_text())
    require(cleanup.get("pg_stopped") is True and cleanup.get("worker_exited") is True, "child_cleanup_incomplete")
    require(not (server_output / "postgres/postmaster.pid").exists()
            and not (server_output / "temporary-postgres-password").exists(), "postgres_files_not_cleaned")
    return {"fault": fault, "passed": True, **result,
            "durable_fault_metadata": durable_fault_metadata(server_output, fault),
            "cleanup": {"pg_stopped": True, "worker_exited": True}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="New report directory outside the repository")
    parser.add_argument("--postgres-bin", type=Path, required=True, help="Absolute PostgreSQL 16 tools directory")
    parser.add_argument("--fault", choices=(*FAULTS, "all"), default="all")
    args = parser.parse_args(argv)
    require(args.postgres_bin.is_absolute() and all((args.postgres_bin / name).is_file()
            for name in ("initdb", "pg_ctl", "createdb")), "postgres_tools_unavailable")
    require(not (REPO / ".env").exists(), "checkout_env_refused")
    if args.output is None:
        args.output = Path(tempfile.mkdtemp(prefix="cosmabot-mcp-check-"))
    else:
        require(not args.output.is_symlink() and not args.output.exists(), "new_output_required")
        require(not args.output.resolve().is_relative_to(REPO), "output_inside_repository")
        args.output = args.output.resolve()
        args.output.mkdir(parents=True, mode=0o700)
    report = {"schema": "cosmabot-mcp-check.v1", "synthetic_only": True, "mode": "deterministic-replay-no-model",
              "case": "walk_in", "transport": "official-mcp-sdk-stdio", "status": "failed", "runs": []}
    try:
        for fault in FAULTS if args.fault == "all" else (args.fault,):
            report["runs"].append(asyncio.run(run_one(args.output / fault, args.postgres_bin, fault)))
        report["status"] = "passed"
    except Exception as error:
        report["error"] = str(error) if isinstance(error, CheckFailed) else type(error).__name__
    target = args.output / "mcp-check.json"
    target.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "runs": len(report["runs"]), "report": str(target)}))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
