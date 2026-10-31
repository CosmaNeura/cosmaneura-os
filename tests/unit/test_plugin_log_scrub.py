"""Plugin server logs redact identifiers, drop note text, and redact query strings."""

from __future__ import annotations

import io
import json
import logging
import sys
from contextlib import asynccontextmanager

import anyio
import httpx
import pytest
from mcp.client.session import ClientSession
from mcp.shared.memory import create_client_server_memory_streams

from cosmas_os.logging_setup import _original_add_handler
from cosmas_os.plugins.elation import NAMES, tool_definitions
from cosmas_os.plugins.log_setup import arm_plugin_loggers, scrub_diverted_stdout
from cosmas_os.plugins.runtime import AuthenticatedSession
from cosmas_os.plugins.server import create_server, main, serve

MRN = "000-TEST-123"
EMAIL = "ada.invented@example.test"
PHONE = "555-010-0199"
SSN = "000-00-0000"
DOB = "1990-01-02"
NAME = "Ada Invented"
NOTE = "synthetic penguin note"
REQUEST = "req-synth-1"
URL = (
    "https://fixture.invalid/connections/ehr/reads"
    f"?mrn={MRN}&email={EMAIL}&note_text=stuffed%20penguin&dob={DOB}&request_id={REQUEST}"
)


def _secrets() -> tuple[str, ...]:
    return (MRN, EMAIL, PHONE, SSN, DOB, NAME, NOTE, "stuffed penguin", "Ada")


def _capture(name: str) -> tuple[logging.Logger, io.StringIO, tuple[int, bool, list[logging.Handler]]]:
    arm_plugin_loggers()
    logger = logging.getLogger(name)
    previous = (logger.level, logger.propagate, list(logger.handlers))
    logger.handlers = []
    logger.setLevel(logging.INFO)
    logger.propagate = False
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    return logger, stream, previous


def _restore(logger: logging.Logger, previous: tuple[int, bool, list[logging.Handler]]) -> None:
    level, propagate, handlers = previous
    logger.handlers = handlers
    logger.setLevel(level)
    logger.propagate = propagate


def test_plugin_logger_redacts_identifiers_drops_note_fields_and_redacts_queries() -> None:
    logger, stream, previous = _capture("cosmas_os.plugins")
    try:
        logger.info(
            "request_id=%s status_code=200 mrn=%s email=%s dob=%s phone=%s ssn=%s name=%s note_text=%s",
            REQUEST,
            MRN,
            EMAIL,
            DOB,
            PHONE,
            SSN,
            NAME,
            NOTE,
        )
        logger.info(
            json.dumps(
                {
                    "request_id": REQUEST,
                    "mrn": MRN,
                    "email": EMAIL,
                    "note_text": NOTE,
                    "body": NOTE,
                    "clinical_note": NOTE,
                }
            )
        )
        logger.info("HTTP Request: POST %s \"HTTP/1.1 200 OK\"", URL)
    finally:
        _restore(logger, previous)
    text = stream.getvalue()
    for secret in _secrets():
        assert secret not in text
    assert REQUEST in text
    assert "status_code=200" in text
    parsed = json.loads(text.strip().splitlines()[1])
    assert "note_text" not in parsed
    assert "body" not in parsed
    assert "clinical_note" not in parsed
    assert parsed["request_id"] == REQUEST
    assert parsed["mrn"] == "[redacted]"
    assert "mrn=[redacted]" in text
    seen: dict[str, object] = {}

    class Capture(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            seen["note"] = "note_text" in record.__dict__
            seen["mrn"] = getattr(record, "mrn", None)
            return True

    extra_logger, extra_stream, extra_previous = _capture("cosmas_os.plugins.extra")
    extra_logger.handlers[0].addFilter(Capture())
    try:
        extra_logger.info("request_id=%s", REQUEST, extra={"mrn": MRN, "note_text": NOTE, "body": NOTE})
    finally:
        _restore(extra_logger, extra_previous)
    assert seen["note"] is False
    assert seen["mrn"] == "[redacted]"
    assert NOTE not in extra_stream.getvalue()
    assert REQUEST in extra_stream.getvalue()


def test_httpx_and_runner_logs_scrub_urls_and_exceptions() -> None:
    httpx_logger, httpx_stream, httpx_previous = _capture("httpx")
    runner, runner_stream, runner_previous = _capture("mcp.server.runner")
    try:
        httpx_logger.info(
            'HTTP Request: %s %s "%s %d %s"',
            "POST",
            URL,
            "HTTP/1.1",
            200,
            "OK",
        )

        def boom() -> None:
            note_text = NOTE
            mrn = MRN
            email = EMAIL
            if not mrn:
                raise RuntimeError("unreachable")
            raise RuntimeError(f"failed mrn={mrn} email={email} note_text={note_text} kept={note_text}")

        try:
            boom()
        except RuntimeError:
            runner.exception("request_id=%s status_code=500", REQUEST)
    finally:
        _restore(httpx_logger, httpx_previous)
        _restore(runner, runner_previous)
    combined = httpx_stream.getvalue() + runner_stream.getvalue()
    for secret in (MRN, EMAIL, NOTE, "stuffed penguin"):
        assert secret not in combined
    assert REQUEST in httpx_stream.getvalue()
    assert "request_id=" + REQUEST in runner_stream.getvalue()
    assert "Traceback (most recent call last)" in runner_stream.getvalue()
    assert "note_text = " not in runner_stream.getvalue()
    assert "mrn = " not in runner_stream.getvalue()
    assert "note_text" not in httpx_stream.getvalue()
    assert f"request_id={REQUEST}" in httpx_stream.getvalue()


def test_preexisting_httpx_handler_is_armed() -> None:
    logger = logging.getLogger("httpx")
    previous = (logger.level, logger.propagate, list(logger.handlers))
    logger.handlers = []
    logger.setLevel(logging.INFO)
    logger.propagate = False
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    _original_add_handler(logger, handler)
    try:
        arm_plugin_loggers()
        logger.info("GET %s", URL)
        text = stream.getvalue()
        assert MRN not in text
        assert EMAIL not in text
        assert "penguin" not in text
        assert REQUEST in text
    finally:
        _restore(logger, previous)


def test_stderr_writes_are_scrubbed_and_sign_in_text_remains(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--origin", "https://fixture.invalid", "--check"]) == 1
    sys.stderr.write(
        f"request_id={REQUEST} mrn={MRN} email={EMAIL} phone={PHONE} ssn={SSN} note_text={NOTE}\n"
    )
    sys.stderr.write(f"dob={DOB}")
    sys.stderr.flush()
    message = capsys.readouterr().err
    assert "authenticated application session" in message
    assert "Browser sign-in is not exported to stdio" in message
    for secret in (MRN, EMAIL, PHONE, SSN, DOB, NOTE):
        assert secret not in message
    assert REQUEST in message


def test_diverted_stdout_is_scrubbed_only_while_stdio_is_serving(capsys: pytest.CaptureFixture[str]) -> None:
    with scrub_diverted_stdout():
        print(f"mrn={MRN} email={EMAIL} phone={PHONE} ssn={SSN} dob={DOB} name={NAME}")
        print(f"POST {URL}")
    print(f"mrn={MRN}")
    captured = capsys.readouterr().out.splitlines()
    assert MRN not in captured[0]
    assert EMAIL not in captured[0]
    assert PHONE not in captured[0]
    assert SSN not in captured[0]
    assert DOB not in captured[0]
    assert NAME not in captured[0]
    assert MRN not in captured[1]
    assert "penguin" not in captured[1]
    assert REQUEST in captured[1]
    assert captured[2] == f"mrn={MRN}"


@pytest.mark.asyncio
async def test_serve_scrubs_stdio_log_channel(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    @asynccontextmanager
    async def fake_stdio():
        yield None, None

    class Server:
        def create_initialization_options(self) -> None:
            return None

        async def run(self, reader: object, writer: object, options: object) -> None:
            assert reader is None and writer is None and options is None
            print(f"mrn={MRN} email={EMAIL} note_text={NOTE}")
            sys.stderr.write(f"ssn={SSN} phone={PHONE} dob={DOB}\n")

    monkeypatch.setattr("mcp.server.stdio.stdio_server", fake_stdio)
    monkeypatch.setattr("cosmas_os.plugins.server.create_server", lambda _runtime: Server())
    await serve(object())
    print(f"mrn={MRN}")
    captured = capsys.readouterr()
    logged, restored = captured.out.splitlines()
    assert MRN not in logged
    assert EMAIL not in logged
    assert NOTE not in logged
    assert restored == f"mrn={MRN}"
    for secret in (SSN, PHONE, DOB):
        assert secret not in captured.err


@pytest.mark.asyncio
async def test_tool_result_keeps_chart_rows_while_the_log_does_not() -> None:
    class Runtime:
        def tool_definitions(self) -> list[dict[str, object]]:
            return [
                {
                    "name": "workspace_read",
                    "description": "Read the current encounter.",
                    "inputSchema": {"type": "object", "additionalProperties": False},
                }
            ]

        def call(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
            logging.getLogger("cosmas_os.plugins.runtime").info(
                "request_id=%s mrn=%s email=%s note_text=%s url=%s",
                REQUEST,
                MRN,
                EMAIL,
                NOTE,
                URL,
            )
            return {
                "operation": "workspace.read",
                "result": {"patient_name": NAME, "mrn": MRN, "rows": [NOTE]},
                "recovery": "Repeat the same read.",
            }

    logger, stream, previous = _capture("cosmas_os.plugins.runtime")
    server = create_server(Runtime())
    try:
        async with create_client_server_memory_streams() as (client_streams, server_streams):
            async with anyio.create_task_group() as group:
                group.start_soon(server.run, *server_streams, server.create_initialization_options())
                async with ClientSession(*client_streams) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    assert {tool.name for tool in listed.tools} == {"workspace_read"}
                    result = await session.call_tool("workspace_read", {})
                    assert result.is_error is False
                    assert result.structured_content is not None
                    assert result.structured_content["result"]["mrn"] == MRN
                    assert result.structured_content["result"]["patient_name"] == NAME
                    assert NOTE in result.structured_content["result"]["rows"]
                group.cancel_scope.cancel()
    finally:
        _restore(logger, previous)
    text = stream.getvalue()
    for secret in (MRN, EMAIL, NOTE, "penguin"):
        assert secret not in text
    assert REQUEST in text


def test_elation_tool_names_stay_a_set() -> None:
    rows = tool_definitions()
    assert {row["name"] for row in rows} == set(NAMES)
    assert len(rows) == len(NAMES)


def test_check_receipt_tool_set_is_unchanged(capsys: pytest.CaptureFixture[str]) -> None:
    from cosmas_os.api.plugin_catalog import CONTRACT, META

    def catalog() -> dict[str, object]:
        return {
            "_meta": {"ai.cosmas/contract": CONTRACT},
            "tools": [{"_meta": {META: {"id": "workspace.read", "feature_enabled": True}}}],
        }

    adapter = AuthenticatedSession(
        lambda *_args, **_options: httpx.Response(200, json=catalog()),
        lambda: "signed-in-current-session",
    )
    assert main(["--origin", "https://fixture.invalid", "--check"], session=adapter) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert set(receipt["tools"]) == {"workspace_read", *NAMES}
    assert receipt["account_status"] == "not_checked"
    assert receipt["ready"] is True
    for secret in _secrets():
        assert secret not in json.dumps(receipt)
