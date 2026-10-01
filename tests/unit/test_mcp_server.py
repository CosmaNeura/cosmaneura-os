import json
import os
import signal
import threading
from contextlib import asynccontextmanager

import anyio
import pytest
from anyio import to_thread
from lab.mcp_runtime import _checked_arguments, _definitions
from lab.mcp_server import RESOURCES, StdinLines, create_server, resource_value, run_blocking, serve
from lab.store import LabError


class RuntimeFixture:
    config = {"case": "walk_in", "role": "scribe", "mode": "replay"}
    closed = False

    def tool_definitions(self):
        return _definitions(self.config["role"])

    def call(self, name, arguments):
        try:
            _checked_arguments(self.config["role"], name, arguments)
        except LabError as error:
            return {"error": str(error)}
        if name == "read_source":
            raise RuntimeError("private-diagnostic-canary")
        return []

    def status(self):
        return {"synthetic": True, "artifacts": [], "external_effects": 0}

    def close(self):
        self.closed = True


def test_resources_distinguish_synthetic_tools_from_http_connector_reference():
    runtime = RuntimeFixture()
    case = resource_value(runtime, "cosmabot://lab/case")
    assert case["synthetic"] and not case["recording_available"] and not case["public_research_available"]
    assert "source" not in case and "body" not in case
    capabilities = resource_value(runtime, "cosmabot://lab/capabilities")
    assert capabilities["discovery_only"] and not capabilities["callable_over_this_server"]
    from cosmas_os.api.plugin_catalog import definitions

    assert len(capabilities["tools"]) == len(definitions())
    assert all(not tool["_meta"]["ai.cosmas/operation"]["feature_enabled"] for tool in capabilities["tools"])
    with pytest.raises(LabError, match="unknown_resource"):
        resource_value(runtime, "file:///tmp/arbitrary-source")


@pytest.mark.asyncio
async def test_official_memory_client_gets_scoped_tools_resources_and_safe_errors():
    pytest.importorskip("mcp")
    from mcp import ClientSession
    from mcp.shared.exceptions import MCPError
    from mcp.shared.memory import create_client_server_memory_streams
    from mcp.types import TextResourceContents

    runtime = RuntimeFixture()
    server = create_server(runtime)
    async with create_client_server_memory_streams() as (client_streams, server_streams):
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(server.run, *server_streams, server.create_initialization_options())
            async with ClientSession(*client_streams, read_timeout_seconds=5) as session:
                initialized = await session.initialize()
                assert initialized.server_info.name == "cosmabot-lab"
                listed = await session.list_tools()
                assert len(listed.tools) == 6 and "delegate_team" not in {t.name for t in listed.tools}
                assert all(t.input_schema["additionalProperties"] is False for t in listed.tools)
                result = await session.call_tool("list_sources", {})
                assert not result.is_error and result.structured_content == {"result": []}
                assert result.content[0].type == "text"
                assert json.loads(result.content[0].text) == result.structured_content
                for name, args, code in (
                    ("delegate_team", {"roles": ["chief"]}, "unknown_tool"),
                    ("list_sources", {"actor": "chief"}, "invalid_tool_arguments"),
                    ("read_source", {"source_id": "invented"}, "runtime_operation_failed"),
                ):
                    response = await session.call_tool(name, args)
                    assert response.is_error and response.structured_content == {"result": {"error": code}}
                    assert "private-diagnostic-canary" not in response.model_dump_json()
                resources = await session.list_resources()
                assert {r.uri for r in resources.resources} == set(RESOURCES)
                for uri in RESOURCES:
                    response = await session.read_resource(uri)
                    assert len(response.contents) == 1
                    assert isinstance(response.contents[0], TextResourceContents)
                    assert json.loads(response.contents[0].text) == resource_value(runtime, uri)
                with pytest.raises(MCPError, match="Unknown laboratory resource"):
                    await session.read_resource("file:///tmp/arbitrary-source")
            tasks.cancel_scope.cancel()


@pytest.mark.asyncio
async def test_cancelled_operation_closes_runtime_and_releases_blocked_work():
    started, stopped, released = threading.Event(), threading.Event(), threading.Event()

    class BlockingRuntime(RuntimeFixture):
        def call(self):
            started.set()
            assert released.wait(5)
            stopped.set()

        def close(self):
            super().close()
            released.set()

    runtime = BlockingRuntime()
    async with anyio.create_task_group() as tasks:
        tasks.start_soon(run_blocking, runtime, runtime.call)
        assert await to_thread.run_sync(started.wait, 2)
        tasks.cancel_scope.cancel()
    assert runtime.closed and await to_thread.run_sync(stopped.wait, 2)


def test_termination_during_startup_unwinds_runtime(monkeypatch):
    pytest.importorskip("mcp")
    from lab import mcp_server

    closed = []

    class StartupFixture:
        def __init__(self, **_):
            pass

        def __enter__(self):
            os.kill(os.getpid(), signal.SIGTERM)

        def __exit__(self, *_):
            pass

        def close(self):
            closed.append(True)

    previous = signal.getsignal(signal.SIGTERM)
    monkeypatch.setattr(mcp_server, "MCPRuntime", StartupFixture)
    assert mcp_server.main(["--postgres-bin", "/tmp/invented-postgres-bin"]) == 1
    assert closed and signal.getsignal(signal.SIGTERM) == previous


@pytest.mark.asyncio
async def test_idle_transport_exits_at_session_deadline(monkeypatch):
    pytest.importorskip("mcp")
    from mcp import ClientSession
    from mcp.server import stdio
    from mcp.shared.memory import create_client_server_memory_streams

    runtime = RuntimeFixture()
    runtime.config = {**runtime.config, "max_seconds": 0.1}
    done = anyio.Event()
    async with create_client_server_memory_streams() as (client_streams, server_streams):
        @asynccontextmanager
        async def memory_stdio(**_):
            yield server_streams

        monkeypatch.setattr(stdio, "stdio_server", memory_stdio)
        monkeypatch.setattr("sys.stdin", type("Input", (), {"fileno": lambda _: 0})())

        async def run():
            await serve(runtime)
            done.set()

        with anyio.fail_after(2):
            async with anyio.create_task_group() as tasks:
                tasks.start_soon(run)
                async with ClientSession(*client_streams, read_timeout_seconds=1) as session:
                    await session.initialize()
                    await done.wait()
                tasks.cancel_scope.cancel()


@pytest.mark.asyncio
async def test_pipe_input_preserves_partial_frames_and_cancels_idle_read():
    reader, writer = os.pipe()
    try:
        lines = StdinLines(reader)
        os.write(writer, b'{"first":')
        async with anyio.create_task_group() as tasks:
            async def finish():
                await anyio.sleep(0)
                assert writer is not None
                os.write(writer, b'1}\n{"second":2}\n')
            tasks.start_soon(finish)
            assert await anext(lines) == '{"first":1}\n'
            assert await anext(lines) == '{"second":2}\n'
        with anyio.move_on_after(0.02) as cancellation:
            await anext(lines)
        assert cancellation.cancel_called
        os.close(writer)
        writer = None
        with pytest.raises(StopAsyncIteration):
            await anext(lines)
    finally:
        os.close(reader)
        if writer is not None:
            os.close(writer)
