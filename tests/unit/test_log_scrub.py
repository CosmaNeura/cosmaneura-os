"""Log scrubber coverage for app, API, worker, and proxy access logs."""

from __future__ import annotations

import importlib.util
import io
import json
import logging
import re
import sys
from pathlib import Path

import pytest
from celery.signals import after_setup_logger
from uvicorn.logging import AccessFormatter

from cosmas_os.log_scrub import (
    IDENTIFIER_KEYS,
    NOTE_TEXT_KEYS,
    REDACTED,
    LogScrubFilter,
    scrub_structure,
    scrub_text,
)
from cosmas_os.logging_setup import _original_add_handler, install, install_worker

NOTE = "SOAP subjective: synthetic headache for two days"
PROMPT = "Write a fake note about stuffed penguin Zed"
RESPONSE = "Invented draft: the penguin felt fine."
SECRET_TOKENS = (
    "Zara Zedstone",
    "Zedstone",
    "zara.zedstone@example.test",
    "1980-04-02",
    "SYNTH100",
    "555-0199",
    "900-00-0000",
    "FAKEPOL123",
    "Fake Street",
    "synthetic headache",
    "stuffed penguin",
    "penguin felt fine",
)
OPERATIONAL = "request_id=req-synth-100 status_code=201 duration_ms=37"
PLAIN = (
    f"{OPERATIONAL} patient_name=Zara Zedstone email=zara.zedstone@example.test "
    "dob=1980-04-02 mrn=SYNTH100 phone=(415) 555-0199 ssn=900-00-0000 "
    "insurance_id=FAKEPOL123 address=123 Fake Street "
    f"transcript={NOTE} prompt={PROMPT} response={RESPONSE}"
)
STRUCTURED = {
    "request_id": "req-synth-100",
    "status_code": 201,
    "duration_ms": 37,
    "patient_name": "Zara Zedstone",
    "email": "zara.zedstone@example.test",
    "dob": "1980-04-02",
    "mrn": "SYNTH100",
    "phone": "(415) 555-0199",
    "ssn": "900-00-0000",
    "insurance_id": "FAKEPOL123",
    "address": "123 Fake Street",
    "transcript": NOTE,
    "prompt": PROMPT,
    "response": RESPONSE,
    "body": NOTE,
}
ACCESS_PATH = (
    "/notes?patient_name=Zara%20Zedstone&email=zara.zedstone@example.test"
    "&dob=1980-04-02&mrn=SYNTH100&phone=%28415%29%20555-0199&ssn=900-00-0000"
    "&insurance_id=FAKEPOL123&address=123%20Fake%20Street"
    "&transcript=SOAP%20subjective%20synthetic%20headache"
    "&prompt=stuffed%20penguin%20Zed&response=penguin%20felt%20fine"
    "&request_id=req-synth-100&status_code=201&duration_ms=37"
)
UUID = "11111111-1111-4111-8111-111111111111"


def _assert_redacted(text: str) -> None:
    for token in SECRET_TOKENS:
        assert token not in text
    assert "req-synth-100" in text
    assert "201" in text
    assert "37" in text


def _capture(name: str, formatter: logging.Formatter | None = None):
    install()
    logger = logging.getLogger(name)
    previous = (logger.level, logger.propagate, list(logger.handlers))
    logger.handlers = []
    logger.setLevel(logging.INFO)
    logger.propagate = False
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(formatter or logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    return logger, stream, previous


def _restore(logger: logging.Logger, previous: tuple[int, bool, list[logging.Handler]]) -> None:
    level, propagate, handlers = previous
    logger.handlers = handlers
    logger.setLevel(level)
    logger.propagate = propagate


def _raise_with_note() -> None:
    transcript = NOTE
    prompt = PROMPT
    response = RESPONSE
    patient_name = "Zara Zedstone"
    database_url = "postgresql://invented:invented@127.0.0.1:1/synth"
    if not database_url:
        raise RuntimeError("unreachable")
    raise RuntimeError(
        "save failed "
        f"transcript={transcript} prompt={prompt} response={response} patient_name={patient_name}"
    )


def test_structured_note_keys_are_dropped_and_identifiers_redacted() -> None:
    cleaned = scrub_structure(STRUCTURED)
    for key in ("transcript", "prompt", "response", "body"):
        assert key not in cleaned
    assert cleaned["request_id"] == "req-synth-100"
    assert cleaned["status_code"] == 201
    assert cleaned["duration_ms"] == 37
    for key in ("patient_name", "email", "dob", "mrn", "phone", "ssn", "insurance_id", "address"):
        assert cleaned[key] == REDACTED
    rendered = json.dumps(cleaned)
    _assert_redacted(rendered)


def test_plain_text_redacts_identifiers_and_note_text() -> None:
    _assert_redacted(scrub_text(PLAIN))
    assert scrub_text(f"request_id={UUID} status_code=204 duration_ms=8") == (
        f"request_id={UUID} status_code=204 duration_ms=8"
    )
    assert scrub_text("Google callback rejected at completion") == (
        "Google callback rejected at completion"
    )
    assert scrub_text("127.0.0.1:51234") == "127.0.0.1:51234"


def test_environment_cannot_turn_scrubbing_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COSMAS_LOG_SCRUB", "0")
    monkeypatch.setenv("DATA_MODE", "authorized_beta")
    assert "Zedstone" not in scrub_text("patient_name=Zara Zedstone")


def test_app_log_redacts_identifiers_and_note_text() -> None:
    logger, stream, previous = _capture("cosmas_os.app")
    try:
        logger.info("%s", PLAIN)
        logger.info(json.dumps(STRUCTURED))
    finally:
        _restore(logger, previous)
    text = stream.getvalue()
    _assert_redacted(text)
    parsed = json.loads(text.strip().splitlines()[-1])
    assert "transcript" not in parsed
    assert "prompt" not in parsed
    assert "response" not in parsed
    assert parsed["request_id"] == "req-synth-100"
    assert parsed["status_code"] == 201
    assert parsed["duration_ms"] == 37


def test_api_access_log_redacts_query_and_keeps_status() -> None:
    formatter = AccessFormatter(
        '%(client_addr)s - "%(request_line)s" %(status_code)s',
        use_colors=False,
    )
    logger, stream, previous = _capture("uvicorn.access", formatter)
    try:
        logger.info(
            '%s - "%s %s HTTP/%s" %d',
            "127.0.0.1:51234",
            "GET",
            ACCESS_PATH,
            "1.1",
            201,
        )
    finally:
        _restore(logger, previous)
    text = stream.getvalue()
    _assert_redacted(text)
    assert "127.0.0.1:51234" in text
    assert "GET /notes" in text
    assert "201 Created" in text


def test_api_traceback_scrubs_note_text_locals_and_keeps_status() -> None:
    logger, stream, previous = _capture("uvicorn.error")
    try:
        try:
            _raise_with_note()
        except RuntimeError:
            logger.exception(
                "request_id=req-synth-100 status_code=500 duration_ms=37"
            )
    finally:
        _restore(logger, previous)
    text = stream.getvalue()
    for token in ("synthetic headache", "stuffed penguin", "penguin felt fine", "Zedstone"):
        assert token not in text
    assert "req-synth-100" in text
    assert "500" in text
    assert "37" in text
    assert "Traceback (most recent call last)" in text
    assert "patient_name = " not in text
    assert "invented:invented" not in text


def test_worker_log_redacts_identifiers_and_note_text() -> None:
    install_worker()
    logger, stream, previous = _capture("celery.worker")
    try:
        logger.info("%s", PLAIN)
        logger.info(json.dumps(STRUCTURED))
        after_setup_logger.send(sender="cosmas-test", logger=logger)
        logger.info("request_id=req-synth-100 status_code=201 duration_ms=37 email=zara.zedstone@example.test")
    finally:
        _restore(logger, previous)
    text = stream.getvalue()
    _assert_redacted(text)
    assert "zara.zedstone@example.test" not in text


def test_preexisting_handler_is_scrubbed() -> None:
    logger = logging.getLogger("cosmas_os.preexisting")
    previous = (logger.level, logger.propagate, list(logger.handlers))
    logger.handlers = []
    logger.setLevel(logging.INFO)
    logger.propagate = False
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    _original_add_handler(logger, handler)
    assert not any(isinstance(existing, LogScrubFilter) for existing in handler.filters)
    try:
        install()
        assert any(isinstance(existing, LogScrubFilter) for existing in handler.filters)
        logger.info("%s", PLAIN)
        _assert_redacted(stream.getvalue())
    finally:
        _restore(logger, previous)


def test_app_and_worker_modules_install_scrubber() -> None:
    import cosmas_os.api.app as app_module
    import cosmas_os.worker.celery_app as worker_module

    assert app_module.install_log_scrubbing is install
    assert worker_module.install_worker is install_worker
    from cosmas_os.logging_setup import is_installed

    assert is_installed()
    for key in ("transcript", "prompt", "response", "soap", "draft", "body"):
        assert key in NOTE_TEXT_KEYS
    for key in ("patient_name", "dob", "mrn", "phone", "email", "address", "ssn", "insurance_id"):
        assert key in IDENTIFIER_KEYS


def test_proxy_config_drops_query_strings_and_bodies() -> None:
    runtime = Path(__file__).resolve().parents[2] / "infra/beta/vm/runtime"
    sys.path.insert(0, str(runtime))
    try:
        spec = importlib.util.spec_from_file_location("cosmas_vm_renderer_log_scrub", runtime / "render.py")
        module = importlib.util.module_from_spec(spec)
        assert spec is not None and spec.loader is not None
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(runtime))
    document = module.caddy(
        {"web_origin": "https://app.example.test", "api_origin": "https://api.example.test"}
    )
    assert document.count("import cosmas_access_log") == 3
    assert "http_port 8080" in document
    assert "https_port 8443" in document
    assert "reverse_proxy web:8080" in document
    assert "reverse_proxy api:8000" in document
    assert "log_append request_id {http.request.uuid}" in document
    assert "log_credentials" not in document
    assert "http.request.body" not in document
    assert "http.response.body" not in document
    deleted = set(re.findall(r"^\s*(\S+) delete$", document, re.M))
    assert deleted == {
        "request>headers",
        "request>body",
        "resp_headers",
        "response>body",
    }
    assert "status" not in deleted
    assert "duration" not in deleted
    found = re.search(r"request>uri regexp (\S+) (\S+)", document)
    assert found is not None
    pattern, replacement = found.group(1), found.group(2)
    sample = (
        "/notes?patient_name=Zara+Zedstone&email=zara.zedstone@example.test"
        "&transcript=SOAP&request_id=req-synth-100"
    )
    redacted = re.sub(pattern, replacement, sample)
    assert redacted == "/notes[redacted-query]"
    for token in ("Zedstone", "zara.zedstone@example.test", "SOAP", "req-synth-100"):
        assert token not in redacted
    assert "request_id" in document
