"""Owned synthetic MCP session; the application runs in a clean worker process.

Only allowlisted fixture cases enter the application. Tool calls keep the startup
role, encounter and database; saved drafts never invoke the simulated human flow.
"""

import errno
import json
import os
import selectors
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, TypedDict

from pydantic import ValidationError

from lab.application import OwnedPostgres
from lab.cases import CASES, ROLES
from lab.engine import SCHEMAS
from lab.store import LabError

REPO = Path(__file__).resolve().parents[1]
SCHEMA = "cosmabot-mcp-lab.v1"
MAX_MESSAGE_BYTES = 65536
FAULTS = ("none", "lost_save_reply", "read_timeout")


class RuntimeConfig(TypedDict):
    case: str
    role: str
    mode: str
    fault: str
    max_calls: int
    max_tokens: int
    max_seconds: int
    concurrency: int
    connector_tools: bool


def _write(path, value):
    temporary = path.with_suffix(".next.json")
    temporary.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")
    temporary.replace(path)


def _schemas(connector_tools):
    if connector_tools:
        from lab.connector_tools import ALL_SCHEMAS

        return ALL_SCHEMAS
    return SCHEMAS


def _visible(role, name, connector_tools):
    if connector_tools:
        from lab.connector_tools import visible

        return visible(role, name)
    return name in SCHEMAS and (role == "chief" or name != "delegate_team")


def _definitions(role, connector_tools=False):
    writes = {"save_artifact", "delegate_team"}
    if connector_tools:
        from lab.connector_tools import WRITES

        writes = WRITES
    return [{"name": name, "description": description,
             "inputSchema": schema.model_json_schema(),
             "annotations": {"readOnlyHint": name not in writes,
                             "destructiveHint": False, "idempotentHint": True,
                             "openWorldHint": False}}
            for name, (schema, description) in _schemas(connector_tools).items()
            if _visible(role, name, connector_tools)]


def _checked_arguments(role, name, arguments, connector_tools=False):
    if not isinstance(name, str) or not _visible(role, name, connector_tools):
        raise LabError("unknown_tool")
    try:
        if not isinstance(arguments, dict):
            raise ValueError
        if len(json.dumps(arguments, allow_nan=False).encode()) > MAX_MESSAGE_BYTES:
            raise ValueError
        return _schemas(connector_tools)[name][0].model_validate(arguments).model_dump(mode="json", exclude_none=True)
    except (ValueError, TypeError, ValidationError, RecursionError):
        raise LabError("invalid_tool_arguments") from None


class MCPRuntime:
    """One fixed-role session. close() can interrupt an outstanding call."""

    def __init__(self, output: Path | None, postgres_bin: Path, *, case="walk_in", role="chief",
                 mode="replay", allow_azure=False, max_calls=60, max_tokens=100000,
                 max_seconds=900, concurrency=3, fault="none", connector_tools=False):
        if (type(case) is not str or case not in CASES or type(role) is not str or role not in ROLES
                or type(mode) is not str or mode not in {"replay", "azure"} or type(allow_azure) is not bool
                or mode == "azure" and not allow_azure or type(fault) is not str or fault not in FAULTS
                or type(connector_tools) is not bool):
            raise LabError("invalid_runtime_configuration")
        for value, lower, upper in ((max_calls, 1, 250), (max_tokens, 1000, 500000),
                                    (max_seconds, 1, 1800), (concurrency, 1, 3)):
            if type(value) is not int or not lower <= value <= upper:
                raise LabError("invalid_runtime_budget")
        self._requested_output = output
        self._binary = Path(postgres_bin).resolve()
        if any(not os.access(self._binary / tool, os.X_OK) for tool in ("initdb", "pg_ctl", "createdb")):
            raise LabError("postgres_tools_unavailable")
        self.config = RuntimeConfig(case=case, role=role, mode=mode, fault=fault, max_calls=max_calls,
                                    max_tokens=max_tokens, max_seconds=max_seconds, concurrency=concurrency,
                                    connector_tools=connector_tools)
        self.output = None
        self._pg = self._worker = self._stderr = None
        self._buffer = bytearray()
        self._io_lock = threading.Lock()
        self._close_lock = threading.Lock()
        self._started = self._closed = False
        self._sequence = 0
        self._deadline = 0.0
        self._last_status = {"schema": SCHEMA, "state": "not_started", "synthetic": True,
                             **{k: self.config[k] for k in ("case", "role", "mode", "fault")}}
        self._cleanup = None

    def __enter__(self):
        if self._started or self._closed:
            raise LabError("runtime_already_started")
        if (REPO / ".env").exists() or (REPO / ".env").is_symlink():
            raise LabError("runtime_source_env_forbidden")
        if self._requested_output is None:
            temporary_root = Path(tempfile.gettempdir()).resolve(strict=True)
            if temporary_root.is_relative_to(REPO):
                raise LabError("fresh_external_output_required")
            self.output = Path(tempfile.mkdtemp(prefix="cosmabot-mcp-lab-", dir=temporary_root)).resolve()
        else:
            requested = Path(self._requested_output)
            if not requested.is_absolute() or requested.name in {"", ".", ".."}:
                raise LabError("fresh_external_output_required")
            root = requested.parent.resolve(strict=True) / requested.name
            if root.is_relative_to(REPO) or root.exists() or root.is_symlink():
                raise LabError("fresh_external_output_required")
            root.mkdir(mode=0o700)
            self.output = root
        self._started = True
        _write(self.output / "startup.json", {"schema": SCHEMA, "synthetic": True, **self.config})
        try:
            self._pg = OwnedPostgres(self.output, self._binary)
            self._pg.__enter__()
            env = self._environment()
            self._stderr = (self.output / "worker.stderr.log").open("xb")
            self._worker = subprocess.Popen(
                [sys.executable, "-B", "-m", "lab.mcp_runtime", "--worker", str(self.output)],
                cwd=REPO, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=self._stderr, start_new_session=True,
            )
            ready = self._receive(60)
            if ready.get("id") != 0 or "error" in ready:
                raise LabError("runtime_startup_failed")
            self._last_status = ready["result"]
            self._deadline = time.monotonic() + self.config["max_seconds"]
            return self
        except BaseException:
            self.close()
            raise LabError("runtime_startup_failed") from None

    def _environment(self):
        root = self.output
        assert root is not None and self._pg is not None
        for name in ("tmp", "blobs"):
            (root / name).mkdir()
        dirs = [str(self._binary), str(Path(sys.executable).parent), os.defpath]
        git = shutil.which("git")
        if git:
            dirs.insert(0, str(Path(git).parent))
        env = {"PATH": os.pathsep.join(dirs), "LANG": "C", "LC_ALL": "C", "PYTHONUTF8": "1",
               "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
               "PYTHONPATH": os.pathsep.join((str(REPO), str(REPO / "src"))),
               "TMPDIR": str(root / "tmp"), "DATABASE_URL": self._pg.url,
               "COSMAS_ENV": "synth_os", "DATA_MODE": "synthetic", "AUTH_MODE": "synth_headers",
               "WORKSPACE_ENABLED": "true", "SYNTH_SEED": "true", "SYNC_WORKER": "true",
               "BLOB_BACKEND": "local", "BLOB_ROOT": str(root / "blobs"),
               "REDIS_URL": "redis://127.0.0.1:1/0"}
        if self.config["mode"] == "azure":
            # The existing AzureCliCredential is the only optional model identity.
            az = shutil.which("az")
            if not az or not os.environ.get("HOME"):
                raise LabError("existing_azure_cli_unavailable")
            env["PATH"] = os.pathsep.join((str(Path(az).parent), env["PATH"]))
            env["HOME"] = os.environ["HOME"]
        return env

    def _receive(self, seconds) -> dict[str, Any]:
        worker = self._worker
        if worker is None or worker.stdout is None:
            raise LabError("runtime_worker_unavailable")
        deadline = time.monotonic() + seconds
        with selectors.DefaultSelector() as selector:
            selector.register(worker.stdout, selectors.EVENT_READ)
            while b"\n" not in self._buffer:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise LabError("runtime_call_timeout")
                chunk = os.read(worker.stdout.fileno(), 8192)
                if not chunk:
                    raise LabError("runtime_worker_unavailable")
                self._buffer.extend(chunk)
                if len(self._buffer) > MAX_MESSAGE_BYTES:
                    raise LabError("runtime_response_limit")
        line, _, remainder = self._buffer.partition(b"\n")
        self._buffer = bytearray(remainder)
        try:
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError
            return value
        except ValueError:
            raise LabError("runtime_response_invalid") from None

    def _request(self, action, **values) -> Any:
        with self._io_lock:
            if not self._started or self._closed or self._worker is None:
                raise LabError("runtime_closed")
            worker = self._worker
            if worker.stdin is None:
                raise LabError("runtime_worker_unavailable")
            remaining = self._deadline - time.monotonic()
            if remaining <= 0:
                raise LabError("run_budget_exhausted")
            self._sequence += 1
            message = {"id": self._sequence, "action": action, **values}
            try:
                worker.stdin.write(json.dumps(message, allow_nan=False).encode() + b"\n")
                worker.stdin.flush()
                answer = self._receive(remaining)
            except (OSError, ValueError):
                raise LabError("runtime_worker_unavailable") from None
            if answer.get("id") != self._sequence or "result" not in answer:
                raise LabError("runtime_response_invalid")
            return answer["result"]

    def tool_definitions(self):
        return _definitions(self.config["role"], self.config["connector_tools"])

    def call(self, name, arguments) -> Any:
        try:
            parsed = _checked_arguments(self.config["role"], name, arguments, self.config["connector_tools"])
            return self._request("call", name=name, arguments=parsed)
        except LabError as error:
            if str(error) in {"runtime_call_timeout", "runtime_worker_unavailable", "run_budget_exhausted",
                              "runtime_response_invalid", "runtime_response_limit"}:
                self.close()
            return {"error": str(error)}

    def status(self):
        if self._closed:
            return {**self._last_status, "state": "closed"}
        try:
            self._last_status = self._request("status")
        except LabError:
            self.close()
            raise
        return self._last_status

    def _restore_status(self):
        if self.output is None:
            return "not_created"
        path = self.output / "status.json"
        try:
            # Receipts are optional after interruption. Never accept extra data
            # or an unrelated episode as a replacement for verified metadata.
            if path.is_symlink() or path.stat().st_size > MAX_MESSAGE_BYTES:
                return "invalid"
            value = json.loads(path.read_text())
            if (not isinstance(value, dict) or set(value) != set(self._last_status)
                    or any(value.get(k) != self._last_status.get(k)
                           for k in ("schema", "synthetic", "case", "role", "mode", "fault", "source", "limits"))
                    or value.get("state") not in {"ready", "closed"}):
                return "invalid"
            self._last_status = value
            return "loaded"
        except FileNotFoundError:
            return "missing"
        except (OSError, ValueError, TypeError):
            return "invalid"

    def close(self):
        with self._close_lock:
            if self._cleanup is not None:
                return self._cleanup
            self._closed = True
            worker = self._worker
            if worker is not None and worker.poll() is None:
                # EOF exits normally when idle. Cancellation terminates only our
                # process group; PostgreSQL is stopped after the worker has exited.
                try:
                    if worker.stdin is not None:
                        worker.stdin.close()
                    worker.wait(timeout=2)
                except (OSError, subprocess.TimeoutExpired):
                    for sig in (signal.SIGTERM, signal.SIGKILL):
                        if worker.poll() is not None:
                            break
                        try:
                            os.killpg(worker.pid, sig)
                            worker.wait(timeout=5)
                        except (OSError, subprocess.TimeoutExpired):
                            continue
            worker_exited = worker is None or worker.poll() is not None
            if worker_exited and self._pg is not None:
                try:
                    self._pg.close()
                except Exception:
                    pass  # The receipt records failure; never claim successful cleanup.
            pg_stopped = self._pg is None or not (self._pg.data / "postmaster.pid").exists()
            if pg_stopped and self._pg is not None:
                try:
                    with socket.socket() as probe:
                        probe.settimeout(1)
                        pg_stopped = probe.connect_ex(("127.0.0.1", self._pg.port)) == errno.ECONNREFUSED
                except OSError:
                    pg_stopped = False
            if self._stderr is not None:
                try:
                    self._stderr.close()
                except OSError:
                    pass
            self._cleanup = {"schema": SCHEMA, "worker_exited": worker_exited,
                             "pg_stopped": pg_stopped, "retained_artifacts": True,
                             "successful": worker_exited and pg_stopped,
                             "status_receipt": self._restore_status() if worker_exited else "unavailable"}
            if self.output is not None:
                _write(self.output / "cleanup.json", self._cleanup)
            return self._cleanup

    def __exit__(self, exc_type, *_):
        cleanup = self.close()
        if exc_type is None and not cleanup["successful"]:
            raise LabError("runtime_cleanup_failed")


def _worker(root):
    """Private protocol; never import application configuration in the host."""
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url

    from lab.application import Application
    from lab.engine import AzureModel, Budget, World
    from lab.runner import source_record
    from lab.store import Store

    config = json.loads((root / "startup.json").read_text())
    database = make_url(os.environ["DATABASE_URL"])
    pid = root / "postgres/postmaster.pid"
    if (root.is_relative_to(REPO) or database.drivername != "postgresql+psycopg"
            or database.host != "127.0.0.1" or database.username != "cosmabot_lab"
            or database.database != "w1a_agent_lab" or database.query or not pid.is_file()
            or str(database.port) != pid.read_text().splitlines()[3]):
        raise LabError("owned_database_required")
    engine = create_engine(database, pool_size=6, max_overflow=0, hide_parameters=True)
    model = None
    world = None
    try:
        from alembic import command
        from alembic.config import Config

        command.upgrade(Config(str(REPO / "alembic.ini")), "head")
        source = source_record()
        _write(root / "source.json", source)
        store = Store(root)
        budget = Budget(calls=config["max_calls"], tokens=config["max_tokens"], seconds=config["max_seconds"])
        model = AzureModel(budget) if config["mode"] == "azure" else None
        episode = "mcp-" + config["case"]
        app = Application(engine, CASES[config["case"]],
                          lambda role, kind, **values: store.event(episode, role, kind, **values))
        world_type = World
        if config["connector_tools"]:
            from lab.connector_tools import ConnectorWorld

            world_type = ConnectorWorld
        world = world_type(store, episode, CASES[config["case"]], app, model,
                      concurrency=config["concurrency"], fault=config["fault"])

        def status():
            assert world is not None
            artifacts = store.visible(episode, config["role"])
            return {"schema": SCHEMA, "state": "ready", "synthetic": True,
                    **{k: config[k] for k in ("case", "role", "mode", "fault")}, "roles": list(ROLES),
                    "artifacts": artifacts, "artifact_count": len(artifacts), "tool_count": world.tool_count,
                    "faults_seen": sorted(world.faults_seen), "failures": world.failures,
                    "external_effects": 0, "source": {k: source[k] for k in ("commit", "source_sha256")},
                    "usage": {"model_calls": budget.calls, "tokens": budget.tokens},
                    "limits": {k: config[k] for k in ("max_calls", "max_tokens", "max_seconds", "concurrency")},
                    "connector_tools": config["connector_tools"], "schema_setup": "alembic-upgrade-head"}

        def answer(request_id, result):
            raw = json.dumps({"id": request_id, "result": result}, allow_nan=False).encode()
            if len(raw) > MAX_MESSAGE_BYTES:
                raw = json.dumps({"id": request_id, "result": {"error": "runtime_response_limit"}}).encode()
            sys.stdout.buffer.write(raw + b"\n")
            sys.stdout.buffer.flush()

        answer(0, status())
        while raw := sys.stdin.buffer.readline(MAX_MESSAGE_BYTES + 1):
            if len(raw) > MAX_MESSAGE_BYTES or not raw.endswith(b"\n"):
                break
            request = json.loads(raw)
            try:
                if request["action"] == "status":
                    result = status()
                elif request["action"] == "call":
                    arguments = _checked_arguments(config["role"], request["name"], request["arguments"], config["connector_tools"])
                    result = world.execute(config["role"], request["name"], arguments)
                else:
                    result = {"error": "unknown_runtime_action"}
            except LabError as error:
                result = {"error": str(error)}
            except Exception:
                result = {"error": "runtime_operation_failed"}
            _write(root / "status.json", status())
            answer(request["id"], result)
        _write(root / "status.json", {**status(), "state": "closed"})
    finally:
        try:
            close_world = getattr(world, "close", None)
            if callable(close_world):
                close_world()
            if model is not None:
                model.close()
        finally:
            engine.dispose()


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "--worker":
        raise SystemExit("Use the MCP server entrypoint; this module owns a private worker protocol.")
    try:
        _worker(Path(sys.argv[2]).resolve(strict=True))
    except BaseException:
        sys.stderr.write("Synthetic MCP worker stopped; inspect metadata receipts.\n")
        raise SystemExit(1) from None
