"""Actual MCP memory streams to bounded HTTP fixtures; no real account/provider I/O."""

import base64
import hashlib

import anyio
import httpx
import pytest
from mcp.client.session import ClientSession
from mcp.shared.memory import create_client_server_memory_streams

from cosmas_os.api.plugin_catalog import CONTRACT, META
from cosmas_os.plugins.runtime import PluginError, PluginRuntime
from cosmas_os.plugins.server import create_server

UUID = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
CHIEF = {"expected_revision": 2, "team_revision": 1, "idempotency_key": "exact-draft-key-1",
         "role": "chief", "content": "Prepare private saved-source drafts."}


def catalog(*identities):
    return {"_meta": {"ai.cosmas/contract": CONTRACT},
            "tools": [{"_meta": {META: {"id": identity, "feature_enabled": True}}}
                      for identity in identities]}


def fixture_runtime(tmp_path, handler, *, ids=("workspace.read",), workspace=UUID, rotate=False):
    token = tmp_path / "private-sign-in"
    token.write_text("first.payload.signature")
    token.chmod(0o600)
    calls = []

    def endpoint(request):
        calls.append(request)
        assert request.url.host == "fixture.invalid" and request.url.scheme == "https"
        if request.url.path == "/connections/plugins":
            assert request.headers["X-Cosmas-Connection-Contract"] == "1"
            if rotate:
                token.write_text("rotated.payload.signature")
            return httpx.Response(200, json=catalog(*ids))
        return handler(request)

    runtime = PluginRuntime("https://fixture.invalid", token, workspace_id=workspace,
                            transport=httpx.MockTransport(endpoint))
    return runtime, token, calls


@pytest.mark.asyncio
async def test_real_mcp_lists_reads_and_preserves_current_workspace_without_get_body(tmp_path):
    runtime, _, calls = fixture_runtime(tmp_path, lambda _: httpx.Response(200, json={"revision": 7, "handoffs": []}))
    server = create_server(runtime)
    try:
        async with create_client_server_memory_streams() as (client_streams, server_streams):
            async with anyio.create_task_group() as group:
                group.start_soon(server.run, *server_streams, server.create_initialization_options())
                async with ClientSession(*client_streams) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    assert [row.name for row in tools.tools] == ["workspace_read"]
                    assert set(tools.tools[0].input_schema["required"]) == {"workspace_id"}
                    result = await session.call_tool("workspace_read", {"workspace_id": UUID})
                    assert not result.is_error and result.structured_content["result"]["revision"] == 7
                    resource = await session.read_resource("cosmabot://journey")
                    assert "Human acceptance remains" in resource.contents[0].text
                group.cancel_scope.cancel()
        request = calls[-1]
        assert request.url.path == f"/workspaces/{UUID}" and not request.content
        assert request.headers["X-Cosmas-Model-Contract"] == "1"
        assert request.headers["X-Cosmas-Workspace-Protocol"] == "1"
        assert request.headers["X-Cosmas-Draft-Recovery"] == "2"
    finally:
        runtime.close()


def test_closed_arguments_refuse_cross_workspace_traversal_consent_and_unknown_before_http(tmp_path):
    runtime, _, calls = fixture_runtime(tmp_path, lambda _: pytest.fail("operation must not dispatch"))
    try:
        for args in ({"workspace_id": OTHER}, {"workspace_id": "../other"},
                     {"workspace_id": UUID, "request": {}}, {"workspace_id": UUID, "consented": True}):
            with pytest.raises(PluginError):
                runtime.call("workspace_read", args)
        with pytest.raises(PluginError, match="unknown_tool"):
            runtime.call("workspace_accept", {})
        assert not calls
    finally:
        runtime.close()


def test_lost_response_is_one_dispatch_with_explicit_recovery_and_no_retry(tmp_path):
    def lost(request):
        raise httpx.ReadTimeout("protected fixture detail", request=request)
    runtime, _, calls = fixture_runtime(tmp_path, lost)
    try:
        result = runtime.call("workspace_read", {"workspace_id": UUID})
        assert result["result"] == {"error": "response_unconfirmed", "recovery_required": True, "automatic_retry": False}
        assert len(calls) == 2 and "protected fixture detail" not in str(result)
    finally:
        runtime.close()


def test_pending_409_keeps_canonical_retained_draft_state_without_new_dispatch(tmp_path):
    pending = {"contract_version": 1, "outcome": "running", "request_sha256": "a" * 64,
               "admission": {"id": UUID, "state": "running"}, "saved_entry": None}
    runtime, _, calls = fixture_runtime(tmp_path, lambda _: httpx.Response(409, json=pending),
                                      ids=("workspace.draft_from_saved_sources",))
    try:
        result = runtime.call("workspace_draft_from_saved_sources", {"workspace_id": UUID, "request": CHIEF})
        assert result["result"]["outcome"] == "running" and result["result"]["request_sha256"] == "a" * 64
        assert len(calls) == 2 and "resolve" in result["recovery"]
    finally:
        runtime.close()


@pytest.mark.parametrize("status", [401, 403, 302])
def test_signed_request_rotation_and_closed_auth_redirect_errors(tmp_path, status):
    runtime, _, calls = fixture_runtime(tmp_path, lambda _: httpx.Response(status, headers={"Location": "https://outside.invalid/private"}, json={"secret": "not returned"}), rotate=True)
    try:
        result = runtime.call("workspace_read", {"workspace_id": UUID})
        assert [request.headers["Authorization"] for request in calls] == ["Bearer first.payload.signature", "Bearer rotated.payload.signature"]
        assert result["result"]["http_status"] == status and "secret" not in str(result)
        assert len(calls) == 2
    finally:
        runtime.close()


def test_pdf_bytes_hash_and_invalid_document_are_bounded(tmp_path):
    pdf = b"%PDF-1.7\nsynthetic byte fixture\n%%EOF"
    runtime, _, _ = fixture_runtime(tmp_path, lambda _: httpx.Response(200, content=pdf, headers={"Content-Type": "application/pdf"}))
    try:
        value = runtime.request("GET", "/fixture-document")["document"]
        assert base64.b64decode(value["base64"]) == pdf and value["sha256"] == hashlib.sha256(pdf).hexdigest()
        assert value["byte_length"] == len(pdf)
        runtime.client.close()
        runtime.client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"html", headers={"Content-Type": "application/pdf"})))
        with pytest.raises(PluginError, match="invalid_document_response"):
            runtime.request("GET", "/fixture-document")
    finally:
        runtime.close()


@pytest.mark.parametrize("response", [catalog("workspace.read") | {"tools": [{"_meta": {META: {"id": "workspace.read", "feature_enabled": "false"}}}]},
                                    catalog("workspace.read", "workspace.read"), {"tools": [{}]}])
def test_malformed_catalog_cannot_enable_tools_or_escape_closed_error(tmp_path, response):
    runtime, _, _ = fixture_runtime(tmp_path, lambda _: httpx.Response(200, json={}))
    try:
        runtime.client.close()
        runtime.client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response)))
        with pytest.raises(PluginError):
            runtime.catalog()
    finally:
        runtime.close()


def test_duplicate_json_keys_and_unsafe_token_file_fail_closed(tmp_path):
    runtime, token, _ = fixture_runtime(tmp_path, lambda _: httpx.Response(200, content=b'{"outcome":"saved","outcome":"unknown"}', headers={"Content-Type": "application/json"}))
    try:
        with pytest.raises(PluginError, match="invalid_api_response"):
            runtime.request("GET", "/fixture-json")
        token.chmod(0o644)
        with pytest.raises(PluginError, match="sign_in_required"):
            runtime.request("GET", "/fixture-json")
    finally:
        runtime.close()


@pytest.mark.parametrize("name,args,ids,path,headers,query", [
    ("workspace_revise_after_human_feedback", {"workspace_id": UUID, "handoff_id": OTHER,
        "request": {"expected_revision": 3, "idempotency_key": "revision-key-1", "review_id": UUID}},
     ("workspace.revise_after_human_feedback",), f"/workspaces/{UUID}/handoffs/{OTHER}/revision",
     {"X-Cosmas-Handoff-Review": "1", "X-Cosmas-Model-Contract": "1"}, {}),
    ("research_read_saved_evidence", {"workspace_id": UUID, "bot": OTHER},
     ("research.read_saved_evidence",), f"/workspaces/{UUID}/research/saved",
     {"X-Cosmas-Research-Contract": "1"}, {"bot": OTHER}),
])
def test_exact_extra_contract_headers_paths_and_flat_query_arguments(tmp_path, name, args, ids, path, headers, query):
    runtime, _, calls = fixture_runtime(tmp_path, lambda _: httpx.Response(200, json={"saved": True}), ids=ids)
    try:
        runtime.call(name, args)
        request = calls[-1]
        assert request.url.path == path and dict(request.url.params) == query
        assert all(request.headers[key] == value for key, value in headers.items())
        assert bool(request.content) == ("request" in args)
    finally:
        runtime.close()
