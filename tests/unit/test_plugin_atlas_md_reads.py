"""Atlas.md plugin reads stay unsupported and never touch the network."""

import json
from pathlib import Path

import anyio
import httpx
import pytest
from mcp.client.session import ClientSession
from mcp.shared.memory import create_client_server_memory_streams

from cosmas_os.api.plugin_catalog import CONTRACT, META
from cosmas_os.plugins.atlas_md import NAMES, RECOVERY, UNSUPPORTED, tool_definitions
from cosmas_os.plugins.runtime import AuthenticatedSession, PluginError, PluginRuntime
from cosmas_os.plugins.server import JOURNEY, create_server

DOC = Path("docs/plugins/atlas-md.md")
LIVE_CLAIMS = (
    "live atlas",
    "live connection",
    "live read",
    "live api",
    "live sync",
    "live ehr",
    "is live",
    "are live",
    "now live",
    "currently live",
)


def catalog(*identities):
    return {"_meta": {"ai.cosmas/contract": CONTRACT},
            "tools": [{"_meta": {META: {"id": identity, "feature_enabled": True}}} for identity in identities]}


def runtime_for(*, plugins=(), workspace=None):
    calls = []

    def request(method, url, **options):
        calls.append((method, url, options))
        raise AssertionError("Atlas.md read must not call the network")

    runtime = PluginRuntime(
        "https://fixture.invalid", workspace_id=workspace, plugins=plugins,
        session=AuthenticatedSession(request, lambda: "signed-in-session-1"),
    )
    return runtime, calls


@pytest.mark.parametrize("name", NAMES)
def test_each_read_is_unsupported_and_makes_no_network_call(name):
    runtime, calls = runtime_for()
    try:
        result = runtime.call(name, {})
        assert result["operation"].startswith("atlas_md.read_")
        assert result["recovery"] == RECOVERY
        assert result["result"] == {
            "state": "unsupported", "message": UNSUPPORTED, "read_only": True, "confirmed": False,
        }
        assert UNSUPPORTED == "This Atlas.md read is not supported yet."
        assert "rows" not in result["result"]
        assert calls == []
    finally:
        runtime.close()


@pytest.mark.parametrize("arguments", [
    {"token": "not-a-real-token"},
    {"cursor": "next-page"},
    {"query": "patients named Alex Example"},
    {"request": {"action": "read"}},
    {"patient": "Alex Example"},
    {"connection_id": "33333333-3333-4333-8333-333333333333"},
    {"read": "labs"},
    None,
    [],
    "appointments",
    1,
])
@pytest.mark.parametrize("name", NAMES)
def test_token_cursor_and_free_form_arguments_are_rejected(name, arguments):
    runtime, calls = runtime_for()
    try:
        with pytest.raises(PluginError, match="invalid_tool_arguments"):
            runtime.call(name, arguments)
        assert calls == []
    finally:
        runtime.close()


def test_definitions_are_read_only_and_name_no_endpoint():
    rows = tool_definitions()
    assert [row["name"] for row in rows] == list(NAMES)
    assert NAMES
    for row in rows:
        assert row["annotations"]["readOnlyHint"] is True
        assert row["annotations"]["destructiveHint"] is False
        assert row["inputSchema"]["additionalProperties"] is False
        assert row["inputSchema"]["properties"] == {}
        assert row["inputSchema"]["required"] == []
        operation = row["_meta"]["ai.cosmas/operation"]
        assert operation["plugin"] == "atlas_md"
        assert operation["implementation"] == "unsupported"
        assert operation["external_send"] is False
        assert "http" not in operation
        assert "path" not in operation
        encoded = json.dumps(row).lower()
        assert "token" not in encoded and "cursor" not in encoded and "authorization" not in encoded


def test_atlas_plugin_filter_still_returns_unsupported_without_http():
    runtime, calls = runtime_for(plugins=("atlas_md",))
    try:
        result = runtime.call(NAMES[0], {})["result"]
        assert result["message"] == UNSUPPORTED and calls == []
        with pytest.raises(PluginError, match="unknown_tool"):
            runtime.call("elation_read_appointments", {})
        assert calls == []
    finally:
        runtime.close()


def test_other_plugin_filter_hides_atlas_reads_before_http():
    runtime, calls = runtime_for(plugins=("elation",))
    try:
        with pytest.raises(PluginError, match="unknown_tool"):
            runtime.call(NAMES[0], {})
        assert calls == []
    finally:
        runtime.close()


def test_token_file_transport_is_not_used(tmp_path):
    token = tmp_path / "session.jwt"
    token.write_text("aaa.bbb.ccc")
    token.chmod(0o600)
    calls = []

    def endpoint(request):
        calls.append(request.url.path)
        raise AssertionError(request.url.path)

    runtime = PluginRuntime("https://fixture.invalid", token, transport=httpx.MockTransport(endpoint))
    try:
        result = runtime.call(NAMES[0], {})["result"]
        assert result["message"] == UNSUPPORTED and calls == []
    finally:
        runtime.close()


def test_capability_page_exists_and_makes_no_live_claim():
    text = DOC.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "this atlas.md read is not supported yet." in lowered
    assert "atlas_md_read_appointments" in text and "atlas_md_read_patients" in text
    assert "does not connect to atlas.md" in lowered
    assert "staff-supplied" in lowered
    for claim in LIVE_CLAIMS:
        assert claim not in lowered
    assert "live" not in lowered


def test_journey_says_atlas_reads_are_not_supported_yet():
    assert "Atlas.md read tools do not call Atlas.md." in JOURNEY
    assert "this read is not supported yet." in JOURNEY


@pytest.mark.asyncio
async def test_mcp_lists_atlas_reads_as_read_only_after_elation():
    calls = []

    def request(method, url, **options):
        calls.append((method, url))
        if url.endswith("/connections/plugins"):
            return httpx.Response(200, json=catalog("workspace.read"))
        raise AssertionError(url)

    runtime = PluginRuntime(
        "https://fixture.invalid",
        session=AuthenticatedSession(request, lambda: "signed-in-session-1"),
    )
    server = create_server(runtime)
    try:
        async with create_client_server_memory_streams() as (client_streams, server_streams):
            async with anyio.create_task_group() as group:
                group.start_soon(server.run, *server_streams, server.create_initialization_options())
                async with ClientSession(*client_streams) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    names = {row.name for row in listed.tools}
                    assert set(NAMES) <= names
                    for row in listed.tools:
                        if row.name in NAMES:
                            assert row.annotations.read_only_hint is True
                            assert row.annotations.destructive_hint is False
                            assert row.input_schema["properties"] == {}
                    value = await session.call_tool(NAMES[0], {})
                    assert value.structured_content["result"]["message"] == UNSUPPORTED
                    assert value.is_error is False
                    refused = await session.call_tool(NAMES[0], {"cursor": "next", "token": "x"})
                    assert refused.is_error is True
                    assert "not supported yet" not in json.dumps(refused.structured_content)
                group.cancel_scope.cancel()
        assert [url for _method, url in calls] == ["https://fixture.invalid/connections/plugins"]
    finally:
        runtime.close()
