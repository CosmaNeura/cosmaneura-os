import errno
import json
import signal
import subprocess
from types import SimpleNamespace

import pytest
from lab import mcp_runtime as runtime
from lab.store import LabError


@pytest.fixture
def binary(tmp_path):
    path = tmp_path / "postgres-bin"
    path.mkdir()
    for name in ("initdb", "pg_ctl", "createdb"):
        tool = path / name
        tool.write_text("#!/bin/sh\nexit 1\n")
        tool.chmod(0o700)
    return path


@pytest.mark.parametrize("changes", [
    {"case": "clinic"}, {"case": "../../private"}, {"role": "human"},
    {"mode": "azure"}, {"mode": "external"}, {"mode": {}}, {"allow_azure": 1},
    {"max_calls": True}, {"max_calls": 251}, {"max_tokens": 999},
    {"max_seconds": 1801}, {"concurrency": 4}, {"fault": "external_url"},
])
def test_startup_is_allowlisted_and_model_access_requires_explicit_opt_in(binary, tmp_path, changes):
    with pytest.raises(LabError):
        runtime.MCPRuntime(tmp_path / "new", binary, **changes)
    assert not (tmp_path / "new").exists()


@pytest.mark.parametrize("role,count", [("chief", 7), ("scribe", 6), ("research", 6)])
def test_definitions_preserve_exact_world_tools_and_fixed_role(binary, role, count):
    session = runtime.MCPRuntime(None, binary, role=role)
    tools = session.tool_definitions()
    assert len(tools) == count
    assert {item["name"] for item in tools} <= set(runtime.SCHEMAS)
    assert ("delegate_team" in {item["name"] for item in tools}) == (role == "chief")
    assert all(item["inputSchema"]["additionalProperties"] is False for item in tools)
    assert all(item["annotations"]["destructiveHint"] is False for item in tools)
    assert not {"send", "approve", "exercise_follow_up", "shell", "fetch_url"} & {item["name"] for item in tools}


@pytest.mark.parametrize("arguments", [None, [], {"actor": "foreign"}, {"workspace_id": "foreign"},
                                       {"credentials": "synthetic_PRIVATE_secret"}])
def test_invalid_authority_fields_never_reach_worker_or_logs(binary, tmp_path, monkeypatch, arguments):
    session = runtime.MCPRuntime(tmp_path / "new", binary)
    monkeypatch.setattr(session, "_request", lambda *_a, **_k: pytest.fail("worker reached"))
    assert session.call("list_sources", arguments) == {"error": "invalid_tool_arguments"}
    assert not (tmp_path / "new").exists()


def test_unknown_hidden_and_oversized_calls_stop_before_worker(binary, monkeypatch):
    session = runtime.MCPRuntime(None, binary, role="scribe")
    monkeypatch.setattr(session, "_request", lambda *_a, **_k: pytest.fail("worker reached"))
    assert session.call("delegate_team", {"roles": ["research"]}) == {"error": "unknown_tool"}
    assert session.call("send_email", {}) == {"error": "unknown_tool"}
    assert session.call("read_source", {"source_id": "x" * 65536}) == {"error": "invalid_tool_arguments"}


def test_output_must_be_fresh_absolute_and_outside_source(binary, tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "OwnedPostgres", lambda *_: pytest.fail("PostgreSQL reached"))
    for path in (tmp_path, runtime.REPO / "never-create-test-output", runtime.Path("relative-output")):
        with pytest.raises(LabError, match="fresh_external_output_required"):
            runtime.MCPRuntime(path, binary).__enter__()
    assert not (runtime.REPO / "never-create-test-output").exists()


def test_default_output_rejects_repository_tmpdir_before_creating_anything(binary, monkeypatch):
    monkeypatch.setattr(runtime.tempfile, "gettempdir", lambda: str(runtime.REPO))
    monkeypatch.setattr(runtime.tempfile, "mkdtemp", lambda **_: pytest.fail("output created"))
    monkeypatch.setattr(runtime, "OwnedPostgres", lambda *_: pytest.fail("PostgreSQL reached"))
    with pytest.raises(LabError, match="fresh_external_output_required"):
        runtime.MCPRuntime(None, binary).__enter__()


@pytest.mark.parametrize("content,receipt", [(None, "missing"), ("{", "invalid"),
                                             ("[]", "invalid"), ('{"body":"private"}', "invalid")])
def test_corrupt_or_missing_status_does_not_mask_cleanup_or_replace_cached_metadata(binary, tmp_path, content, receipt):
    session = runtime.MCPRuntime(None, binary)
    session.output = tmp_path
    if content is not None:
        (tmp_path / "status.json").write_text(content)
    (tmp_path / "retained-artifact").write_text("saved synthetic draft")
    cleanup = session.close()
    assert cleanup["successful"] and cleanup["status_receipt"] == receipt
    assert json.loads((tmp_path / "cleanup.json").read_text()) == cleanup
    assert session.status()["case"] == "walk_in" and "private" not in json.dumps(session.status())
    assert (tmp_path / "retained-artifact").read_text() == "saved synthetic draft"


@pytest.mark.parametrize("stage", ["postgres", "worker"])
def test_partial_startup_stops_database_and_preserves_sanitized_failure_receipt(binary, tmp_path, monkeypatch, stage):
    events = []

    class Postgres:
        def __init__(self, root, _binary):
            self.data, self.port = root / "postgres", 1
            self.url = "owned_synthetic_database"

        def __enter__(self):
            events.append("partial-startup")
            if stage == "postgres":
                raise OSError("synthetic_PRIVATE_credential_detail")
            return self

        def close(self):
            events.append("postgres-closed")

    class Probe:
        def __enter__(self): return self
        def __exit__(self, *_): return None
        def settimeout(self, _): pass
        def connect_ex(self, _): return errno.ECONNREFUSED

    monkeypatch.setattr(runtime, "OwnedPostgres", Postgres)
    monkeypatch.setattr(runtime.socket, "socket", Probe)

    def spawn_failed(*_a, **_k):
        raise OSError("synthetic_PRIVATE_credential_detail")

    monkeypatch.setattr(runtime.subprocess, "Popen", spawn_failed)
    session = runtime.MCPRuntime(tmp_path / "partial-startup", binary)
    with pytest.raises(LabError, match="^runtime_startup_failed$"):
        session.__enter__()
    assert events == ["partial-startup", "postgres-closed"]
    assert session.close()["successful"]
    assert session.output is not None
    assert "synthetic_PRIVATE" not in (session.output / "cleanup.json").read_text()


@pytest.mark.parametrize("probe_error", ["raise", errno.EPERM, errno.ETIMEDOUT])
def test_unverifiable_database_stop_is_not_reported_successful(binary, tmp_path, monkeypatch, probe_error):
    session = runtime.MCPRuntime(None, binary)
    session.output = tmp_path
    monkeypatch.setattr(session, "_pg", SimpleNamespace(data=tmp_path / "postgres", port=1, close=lambda: None))

    class Probe:
        def __enter__(self): return self
        def __exit__(self, *_): return None
        def settimeout(self, _): pass
        def connect_ex(self, _):
            if probe_error == "raise":
                raise OSError("probe unavailable")
            return probe_error

    monkeypatch.setattr(runtime.socket, "socket", Probe)
    assert session.close()["successful"] is False
    assert json.loads((tmp_path / "cleanup.json").read_text())["pg_stopped"] is False


def test_failed_worker_shutdown_does_not_stop_database_or_claim_success(binary, tmp_path, monkeypatch):
    session = runtime.MCPRuntime(None, binary)
    session.output = tmp_path
    data = tmp_path / "postgres"
    data.mkdir()
    (data / "postmaster.pid").write_text("owned process still present")

    def wait_failed(timeout):
        raise subprocess.TimeoutExpired("owned worker", timeout)

    def signal_failed(*_):
        raise PermissionError("cannot stop owned worker")

    monkeypatch.setattr(session, "_worker", SimpleNamespace(pid=1234, poll=lambda: None, stdin=None, wait=wait_failed))
    monkeypatch.setattr(session, "_pg", SimpleNamespace(data=data, close=lambda: pytest.fail("database stopped before worker")))
    monkeypatch.setattr(runtime.os, "killpg", signal_failed)
    assert session.close()["successful"] is False
    receipt = json.loads((tmp_path / "cleanup.json").read_text())
    assert receipt["worker_exited"] is False and receipt["pg_stopped"] is False


def test_replay_environment_ignores_ambient_provider_and_database_inputs(binary, tmp_path, monkeypatch):
    session = runtime.MCPRuntime(None, binary)
    session.output = tmp_path / "environment"
    session.output.mkdir()
    monkeypatch.setattr(session, "_pg", SimpleNamespace(url="owned_synthetic_database"))
    for name in ("DATABASE_URL", "AZURE_CLIENT_SECRET", "AZURE_OPENAI_API_KEY", "VITE_API_BASE", "HTTP_PROXY"):
        monkeypatch.setenv(name, "synthetic_PRIVATE_ambient")
    env = session._environment()
    assert env["DATABASE_URL"] == "owned_synthetic_database"
    assert "synthetic_PRIVATE_ambient" not in json.dumps(env)
    assert "HOME" not in env
    assert env["WORKSPACE_ENABLED"] == "true" and env["DATA_MODE"] == "synthetic"


def test_cancel_stops_only_owned_worker_before_database_and_close_is_idempotent(binary, tmp_path, monkeypatch):
    events = []

    class Worker:
        pid = 1234
        code: int | None = None
        stdin = SimpleNamespace(close=lambda: events.append("stdin-closed"))

        def poll(self):
            return self.code

        def wait(self, timeout):
            if self.code is None:
                raise subprocess.TimeoutExpired("owned-worker", timeout)
            return self.code

    worker = Worker()

    def kill(pid, sig):
        assert pid == worker.pid and sig == signal.SIGTERM
        events.append("worker-terminated")
        worker.code = -15

    class Probe:
        def __enter__(self): return self
        def __exit__(self, *_): return None
        def settimeout(self, _): pass
        def connect_ex(self, address):
            assert address == ("127.0.0.1", 12345)
            return errno.ECONNREFUSED

    monkeypatch.setattr(runtime.os, "killpg", kill)
    monkeypatch.setattr(runtime.socket, "socket", Probe)
    session = runtime.MCPRuntime(None, binary)
    session.output = tmp_path
    monkeypatch.setattr(session, "_worker", worker)
    monkeypatch.setattr(session, "_pg", SimpleNamespace(data=tmp_path / "postgres", port=12345,
                                                       close=lambda: events.append("postgres-closed")))
    first = session.close()
    assert first == session.close()
    assert events == ["stdin-closed", "worker-terminated", "postgres-closed"]
    assert first["worker_exited"] and first["pg_stopped"] and first["retained_artifacts"]
    assert json.loads((tmp_path / "cleanup.json").read_text()) == first


def test_deadline_failure_closes_runtime_without_claiming_a_completed_call(binary, monkeypatch):
    session = runtime.MCPRuntime(None, binary)
    closed = []

    def fail(*_a, **_k):
        raise LabError("runtime_call_timeout")

    monkeypatch.setattr(session, "_request", fail)
    monkeypatch.setattr(session, "close", lambda: closed.append(True))
    assert session.call("list_sources", {}) == {"error": "runtime_call_timeout"}
    assert closed == [True]
