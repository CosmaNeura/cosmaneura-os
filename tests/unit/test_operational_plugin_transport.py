"""Actual MCP memory streams to bounded HTTP fixtures; no real account/provider I/O."""

import base64
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import anyio
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mcp.client.session import ClientSession
from mcp.shared.memory import create_client_server_memory_streams

from cosmas_os.api.microsoft_connection_routes import router as microsoft_router
from cosmas_os.api.plugin_catalog import CONTRACT, META
from cosmas_os.plugins import runtime as runtime_module
from cosmas_os.plugins.configure import generate
from cosmas_os.plugins.elation import NAMES
from cosmas_os.plugins.runtime import AuthenticatedSession, PluginError, PluginRuntime
from cosmas_os.plugins.server import create_server, main

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
                    assert [row.name for row in tools.tools] == ["workspace_read", *NAMES]
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


def session_runtime(handler, *, ids=("workspace.read",)):
    state = {"revision": "signed-in-session-1"}
    calls = []

    def request(method, url, **options):
        calls.append((method, url, options))
        assert "Authorization" not in options["headers"] and "Cookie" not in options["headers"]
        if url.endswith("/connections/plugins"):
            return httpx.Response(200, json=catalog(*ids))
        return handler(state, options)

    runtime = PluginRuntime("https://fixture.invalid", workspace_id=UUID,
        session=AuthenticatedSession(request, lambda: state["revision"]))
    return runtime, state, calls


def test_current_app_session_calls_actual_microsoft_handler_without_exporting_credentials():
    app = FastAPI()
    identity = SimpleNamespace(box_id=UUID, principal_id=OTHER, external_identity_id=OTHER)
    calls = []
    service = SimpleNamespace(mail=lambda current: calls.append(current) or {"items": [], "current_account": "synthetic"})
    app.include_router(microsoft_router(runtime=lambda: service, identity_dependency=lambda: identity,
                                        workspace_gate=lambda: None))

    @app.get("/connections/plugins")
    def inventory():
        return catalog("microsoft.read_mail")

    with TestClient(app, base_url="https://fixture.invalid") as client:
        def authenticated_request(method, url, **options):
            assert "Authorization" not in options["headers"]
            # The trusted host retains authentication; the handler gets its
            # current identity dependency, not an identity from tool arguments.
            options.pop("timeout")  # In-process ASGI contract check has no socket deadline.
            options["headers"] = {**options["headers"], "Authorization": "Bearer invented-host-owned-session"}
            result = client.request(method, url, **options)
            return httpx.Response(result.status_code, headers=result.headers, content=result.content)

        runtime = PluginRuntime("https://fixture.invalid", session=AuthenticatedSession(
            authenticated_request, lambda: "signed-in-host-session"))
        try:
            result = runtime.call("microsoft_read_mail", {"request": {"action": "mail"}})
            assert result["result"]["items"] == [] and calls == [identity]
            assert runtime.token_file is None and runtime.client is None
        finally:
            runtime.close()


@pytest.mark.parametrize("changed", [None, "different-account-session"])
def test_session_change_after_catalog_prevents_operation_dispatch(changed):
    runtime, state, calls = session_runtime(lambda *_: pytest.fail("must not dispatch"))
    original = runtime.session.request

    def change_after_catalog(method, url, **options):
        result = original(method, url, **options)
        state["revision"] = changed
        return result

    runtime.session = AuthenticatedSession(change_after_catalog, runtime.session.current_revision)
    try:
        with pytest.raises(PluginError, match="sign_in_required|session_changed"):
            runtime.call("workspace_read", {"workspace_id": UUID})
        assert len(calls) == 1
    finally:
        runtime.close()


def test_session_revocation_during_stream_masks_partial_content_and_closes_response():
    class ChangedStream(httpx.SyncByteStream):
        closed = False

        def __iter__(self):
            yield b'{"private":'
            state["revision"] = None
            yield b'"must never return"}'

        def close(self):
            self.closed = True

    stream = ChangedStream()
    runtime, state, calls = session_runtime(lambda *_: httpx.Response(200, stream=stream,
                                               headers={"Content-Type": "application/json"}))
    try:
        with pytest.raises(PluginError, match="sign_in_required") as error:
            runtime.call("workspace_read", {"workspace_id": UUID})
        assert stream.closed and len(calls) == 2 and "private" not in str(error.value)
    finally:
        runtime.close()


def test_session_timeout_is_one_dispatch_and_recovery_without_retry():
    def lost(*_):
        raise httpx.ReadTimeout("private provider context")

    runtime, _, calls = session_runtime(lost)
    try:
        result = runtime.call("workspace_read", {"workspace_id": UUID})
        assert result["result"] == {"error": "response_unconfirmed", "recovery_required": True, "automatic_retry": False}
        assert len(calls) == 2 and "private provider context" not in str(result)
    finally:
        runtime.close()


def test_session_transport_rejects_arbitrary_routes_identity_headers_and_large_bodies():
    runtime, _, calls = session_runtime(lambda *_: pytest.fail("must not dispatch"))
    try:
        for path, options in (("https://outside.invalid/private", {}), ("/../private", {}),
            (f"/workspaces/{UUID}", {"headers": {"X-Cosmas-Model-Contract": "1", "Authorization": "injected"}}),
            (f"/workspaces/{OTHER}", {"headers": {"X-Cosmas-Model-Contract": "1"}})):
            with pytest.raises(PluginError):
                runtime.request("GET", path, **options)
        with pytest.raises(PluginError, match="invalid_tool_arguments"):
            runtime.call("workspace_draft_from_saved_sources", {"workspace_id": UUID, "request": {**CHIEF, "content": "x" * 70000}})
        assert not calls
    finally:
        runtime.close()


def test_session_rejects_mixed_auth_and_closed_host_exceptions(tmp_path):
    adapter = AuthenticatedSession(lambda *_args, **_options: (_ for _ in ()).throw(RuntimeError("private token detail")),
                                   lambda: "current-session")
    for options in ({"token_file": tmp_path / "credential"}, {"transport": httpx.MockTransport(lambda _: None)}):
        with pytest.raises(PluginError, match="ambiguous_authentication"):
            PluginRuntime("https://fixture.invalid", session=adapter, **options)
    runtime = PluginRuntime("https://fixture.invalid", session=adapter)
    try:
        result = runtime.request("GET", "/connections/plugins", headers={"X-Cosmas-Connection-Contract": "1"})
        assert result == {"error": "response_unconfirmed", "recovery_required": True, "automatic_retry": False}
        assert "private token detail" not in str(result)
    finally:
        runtime.close()


def test_configure_app_session_profile_does_not_create_broken_stdio_config(tmp_path):
    source = Path(__file__).resolve().parents[2]
    output = tmp_path / "current-app"
    result = generate(output, python=sys.executable, source=source, origin="https://fixture.invalid", workspace_id=UUID)
    profile = json.loads((output / "app-session.json").read_text())
    assert profile["authentication"] == "current_app_session" and profile["workspace_id"] == UUID
    assert profile["requires_authenticated_host_adapter"] and not (output / ".mcp.json").exists()
    assert not result["external_mcp_configured"] and not result["credentials_stored"]
    explicit = tmp_path / "external"
    result = generate(explicit, python=sys.executable, source=source, origin="https://fixture.invalid",
                      token_file=tmp_path / "owner-session")
    assert "--token-file" in json.loads((explicit / ".mcp.json").read_text())["mcpServers"]["cosmabot-connectors"]["args"]
    assert result["external_mcp_configured"] and not (explicit / "app-session.json").exists()


def test_stdio_without_session_explains_separate_auth_requirement(capsys):
    assert main(["--origin", "https://fixture.invalid", "--check"]) == 1
    message = capsys.readouterr().err
    assert "authenticated application session" in message and "Browser sign-in is not exported to stdio" in message


@pytest.mark.asyncio
async def test_real_mcp_session_transport_reuses_host_without_file_and_closes_after_signout():
    runtime, state, calls = session_runtime(lambda *_: httpx.Response(200, json={"revision": 4}))
    server = create_server(runtime)
    try:
        async with create_client_server_memory_streams() as (client_streams, server_streams):
            async with anyio.create_task_group() as group:
                group.start_soon(server.run, *server_streams, server.create_initialization_options())
                async with ClientSession(*client_streams) as session:
                    await session.initialize()
                    result = await session.call_tool("workspace_read", {"workspace_id": UUID})
                    assert result.structured_content["result"]["revision"] == 4 and not result.is_error
                    before_signout = len(calls)
                    state["revision"] = None
                    refused = await session.call_tool("workspace_read", {"workspace_id": UUID})
                    assert refused.is_error and refused.structured_content == {"error": "sign_in_required"}
                group.cancel_scope.cancel()
        assert runtime.token_file is None and len(calls) == before_signout
        assert len([url for _, url, _ in calls if "/workspaces/" in url]) == 1
    finally:
        runtime.close()


@pytest.mark.parametrize("status", [401, 302, 409])
def test_session_authority_redirect_and_pending_receipts_preserve_closed_recovery(status):
    runtime, _, calls = session_runtime(lambda *_: httpx.Response(status,
        headers={"Location": "https://outside.invalid/private"},
        json={"outcome": "running", "request_sha256": "b" * 64, "secret": "not an error disclosure"}))
    try:
        result = runtime.call("workspace_read", {"workspace_id": UUID})["result"]
        assert result["http_status"] == status and len(calls) == 2
        if status == 409:
            assert result["request_sha256"] == "b" * 64 and result["recovery_required"]
        else:
            assert "secret" not in result and "Location" not in result
    finally:
        runtime.close()


def test_session_response_size_bound_closes_stream(monkeypatch):
    class Oversize(httpx.SyncByteStream):
        closed = False

        def __iter__(self):
            yield b"x" * 129

        def close(self):
            self.closed = True

    stream = Oversize()
    runtime, _, calls = session_runtime(lambda *_: httpx.Response(200, stream=stream,
                                        headers={"Content-Type": "application/json"}))
    monkeypatch.setattr(runtime_module, "MAX_RESPONSE", 128)
    try:
        # Catalog is intentionally read before the reduced response limit.
        runtime.catalog = lambda: {"workspace.read": True}
        with pytest.raises(PluginError, match="response_limit_exceeded"):
            runtime.call("workspace_read", {"workspace_id": UUID})
        assert stream.closed and len(calls) == 1
    finally:
        runtime.close()


def test_injected_server_check_reports_only_catalog_not_connected_account(capsys):
    adapter = AuthenticatedSession(lambda *_args, **_options: httpx.Response(200, json=catalog("workspace.read")),
                                   lambda: "signed-in-current-session")
    assert main(["--origin", "https://fixture.invalid", "--check"], session=adapter) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt == {"ready": True, "transport": "current_app_session", "tools": ["workspace_read", *NAMES],
                       "account_status": "not_checked"}
