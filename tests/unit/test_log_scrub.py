"""Log scrubber coverage for app, API, worker, and proxy access logs."""

from __future__ import annotations

import importlib.util
import io
import json
import logging
import re
import sys
from pathlib import Path
from types import SimpleNamespace

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
    for key in ("transcript", "prompt", "response", "soap", "draft", "body", "note", "notes"):
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
    assert "ts" not in deleted


def _caddy_document() -> str:
    runtime = Path(__file__).resolve().parents[2] / "infra/beta/vm/runtime"
    sys.path.insert(0, str(runtime))
    try:
        spec = importlib.util.spec_from_file_location(
            "cosmas_vm_renderer_log_scrub_dates", runtime / "render.py"
        )
        module = importlib.util.module_from_spec(spec)
        assert spec is not None and spec.loader is not None
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(runtime))
    return module.caddy(
        {"web_origin": "https://app.example.test", "api_origin": "https://api.example.test"}
    )


def test_bare_dates_are_redacted_but_asctime_duration_and_caddy_ts_stay() -> None:
    bare = "01/02/1970 1/2/1970 1970-01-02 02-01-1970"
    redacted = scrub_text(f"saw {bare} duration_ms=37 elapsed=02-01-1970 ts=1761861234.778")
    for token in ("01/02/1970", "1/2/1970", "1970-01-02"):
        assert token not in redacted
    assert redacted.count("02-01-1970") == 1
    assert "duration_ms=37" in redacted
    assert "elapsed=02-01-1970" in redacted
    assert "ts=1761861234.778" in redacted
    fields = scrub_structure(
        {
            "detail": "01/02/1970",
            "when": "1/2/1970",
            "iso": "1970-01-02",
            "dmy": "02-01-1970",
            "duration_ms": "37",
            "elapsed": "02-01-1970",
            "ts": "1761861234.778",
            "request_id": "req-synth-100",
        }
    )
    for key in ("detail", "when", "iso", "dmy"):
        assert "1970" not in fields[key]
    assert fields["duration_ms"] == "37"
    assert fields["elapsed"] == "02-01-1970"
    assert fields["ts"] == "1761861234.778"
    assert fields["request_id"] == "req-synth-100"
    formatter = logging.Formatter("%(asctime)s %(message)s", datefmt="%Y-%m-%d")
    logger, stream, previous = _capture("cosmas_os.dates", formatter)
    try:
        logger.info("saw 1970-01-02 duration_ms=37")
    finally:
        _restore(logger, previous)
    line = stream.getvalue().strip()
    stamp, _, message = line.partition(" ")
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", stamp)
    assert stamp != "1970-01-02"
    assert "1970-01-02" not in message
    assert "duration_ms=37" in message
    document = _caddy_document()
    deleted = set(re.findall(r"^\s*(\S+) delete$", document, re.M))
    assert "ts" not in deleted
    assert not re.search(r"^\s*ts\b", document, re.M)


def test_note_and_near_miss_keys_are_dropped_case_insensitively() -> None:
    for key in ("note", "notes", "note_body", "clinical_note", "clinical_notes"):
        assert key in NOTE_TEXT_KEYS
    payload = {
        "Note": "synthetic headache for two days",
        "NOTES": "stuffed penguin Zed",
        "Note_Body": "Invented draft: the penguin felt fine.",
        "Clinical-Note": "Zara Zedstone chart line",
        "clinical_notes": "another synthetic note",
        "request_id": "req-synth-100",
        "status_code": 201,
        "duration_ms": 37,
    }
    cleaned = scrub_structure(payload)
    assert set(cleaned) == {"request_id", "status_code", "duration_ms"}
    rendered = json.dumps(cleaned)
    for token in ("synthetic headache", "stuffed penguin", "penguin felt fine", "Zedstone"):
        assert token not in rendered
    assert "req-synth-100" in rendered
    logger, stream, previous = _capture("cosmas_os.notekeys")
    try:
        logger.info("Note=%s notes=%s", "synthetic headache for two days", "stuffed penguin Zed")
    finally:
        _restore(logger, previous)
    text = stream.getvalue()
    assert "synthetic headache" not in text
    assert "stuffed penguin" not in text


def test_mapping_arg_is_scrubbed_before_percent_format() -> None:
    logger, stream, previous = _capture("cosmas_os.dictargs")
    try:
        logger.info(
            "dict %s",
            {"note_text": NOTE, "request_id": "req-synth-100", "status_code": 201, "duration_ms": 37},
        )
        logger.info(
            "obj %s",
            SimpleNamespace(note_text=NOTE, request_id="req-synth-100", status_code=201),
        )
        logger.info(
            "request_id=%(request_id)s status_code=%(status_code)s",
            {"request_id": "req-synth-100", "status_code": 201, "note_text": NOTE},
        )
    finally:
        _restore(logger, previous)
    text = stream.getvalue()
    assert "dict %s" not in text
    assert "obj %s" not in text
    assert "synthetic headache" not in text
    assert "note_text" not in text
    assert "req-synth-100" in text
    assert "201" in text
    assert "37" in text
