"""Strip patient identifiers and clinical note text from log records.

Scrubbing is always on. Nothing in this module reads data mode, and there is
no switch that lets a log line through unredacted.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import traceback
from collections.abc import Mapping
from typing import Any
from urllib.parse import unquote_plus

REDACTED = "[redacted]"

# Structured note text is removed by these keys. Values are not detected by
# guessing what clinical prose looks like.
NOTE_TEXT_KEYS = frozenset(
    {
        "assessment",
        "body",
        "clinical_note",
        "completion",
        "draft",
        "draft_body",
        "draft_text",
        "model_prompt",
        "model_response",
        "note_body",
        "note_text",
        "objective",
        "plan",
        "prompt",
        "request_body",
        "response",
        "response_body",
        "soap",
        "soap_body",
        "soap_note",
        "subjective",
        "transcript",
        "working_transcript",
    }
)

IDENTIFIER_KEYS = frozenset(
    {
        "address",
        "beneficiary_id",
        "birth_date",
        "birthdate",
        "date_of_birth",
        "dob",
        "email",
        "email_address",
        "fax",
        "first_name",
        "full_name",
        "insurance_id",
        "last_name",
        "medical_record_number",
        "member_id",
        "middle_name",
        "mobile",
        "mrn",
        "name",
        "patient_name",
        "phone",
        "phone_number",
        "policy_number",
        "postal_code",
        "social_security_number",
        "ssn",
        "street",
        "street_address",
        "subscriber_id",
        "zip",
        "zip_code",
    }
)

# Query keys that are operational, not patient identifiers.
_KEEP_QUERY_KEYS = frozenset(
    {
        "correlation_id",
        "duration",
        "duration_ms",
        "request_id",
        "requestid",
        "status",
        "status_code",
        "trace_id",
        "x_request_id",
    }
)

_RESERVED_RECORD_ATTRS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)

_NOTE_KEY_PATTERN = "|".join(
    re.escape(key) for key in sorted(NOTE_TEXT_KEYS, key=len, reverse=True)
)
_NOTE_FIELD = re.compile(
    rf"(?<![A-Za-z0-9_])(?i:{_NOTE_KEY_PATTERN})(?![A-Za-z0-9_])"
    rf"\s*[:=]\s*"
    rf"(?P<value>\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^\n]*)"
)
_NAME = re.compile(
    r"(?<![A-Za-z0-9_])(?i:patient(?:[\s_-]*name)?|full[\s_-]*name|"
    r"first[\s_-]*name|last[\s_-]*name|name)[\s:=#-]+"
    r"(?P<value>[A-Z][a-z]+(?:[ \t]+[A-Z][a-z.'-]+){0,3})"
)
_DOB = re.compile(
    r"(?<![A-Za-z0-9_])(?i:d\.?o\.?b\.?|date[\s_-]*of[\s_-]*birth|"
    r"birth[\s_-]*date|born)[\s:=#-]+"
    r"(?P<value>(?:\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})"
    r"(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2})?)?"
    r"|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*"
    r"[ \t]+\d{1,2},?[ \t]+\d{4})"
)
_MRN = re.compile(
    r"(?<![A-Za-z0-9_])(?i:mrn|medical[\s_-]*record(?:[\s_-]*number)?)"
    r"[\s:=#-]+(?P<value>[A-Za-z0-9][A-Za-z0-9-]{2,64})"
)
_INSURANCE = re.compile(
    r"(?<![A-Za-z0-9_])(?i:insurance|member|subscriber|policy|beneficiary)"
    r"(?:[\s_-]*(?:id|number))?[\s:=#-]+"
    r"(?P<value>[A-Za-z0-9][A-Za-z0-9-]{3,64})"
)
_ADDRESS = re.compile(
    r"(?<!\d)\d{1,6}[ \t]+[A-Za-z0-9.'-]+(?:[ \t]+[A-Za-z0-9.'-]+){0,4}[ \t]+"
    r"(?i:street|st|avenue|ave|road|rd|boulevard|blvd|lane|ln|drive|dr|court|ct|way|place|pl)\b\.?"
)
_PHONE = re.compile(
    r"(?<!\d)(?:\+1[\s.-])?(?:\(\d{3}\)[\s.-]?|\d{3}[\s.-])\d{3}[\s.-]\d{4}(?!\d)"
)
_EMAIL = re.compile(
    r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z0-9.-])"
)
_SSN = re.compile(r"(?<![A-Za-z0-9])\d{3}-\d{2}-\d{4}(?![A-Za-z0-9])")
_LABELED_SSN = re.compile(
    r"(?<![A-Za-z0-9_])(?i:ssn|social[\s_-]*security(?:[\s_-]*number)?)"
    r"[\s:=#-]+(?P<value>\d{3}-?\d{2}-?\d{4})"
)
_QUERY = re.compile(r"\?[A-Za-z0-9%_.~+-]+=[^ \t\r\n]*")
_CAMEL = re.compile(r"(?<=[a-z0-9])([A-Z])")

_guard = threading.local()


def _norm_key(key: object) -> str:
    text = _CAMEL.sub(r"_\1", str(key).strip())
    return text.replace("-", "_").replace(" ", "_").lower()


def _replace_value(match: re.Match[str]) -> str:
    value = match.group("value")
    if value == "":
        return match.group(0)
    start, end = match.span("value")
    return match.string[match.start() : start] + REDACTED + match.string[end : match.end()]


def _scrub_plain(text: str) -> str:
    text = _NOTE_FIELD.sub(_replace_value, text)
    for pattern in (_NAME, _DOB, _MRN, _INSURANCE, _LABELED_SSN):
        text = pattern.sub(_replace_value, text)
    text = _ADDRESS.sub(REDACTED, text)
    text = _PHONE.sub(REDACTED, text)
    text = _EMAIL.sub(REDACTED, text)
    text = _SSN.sub(REDACTED, text)
    return text


def _scrub_query(raw: str) -> str:
    kept: list[str] = []
    for pair in raw[1:].split("&"):
        if not pair:
            continue
        key, separator, value = pair.partition("=")
        norm = _norm_key(unquote_plus(key))
        if norm in NOTE_TEXT_KEYS:
            continue
        if not separator:
            kept.append(key)
            continue
        if norm in IDENTIFIER_KEYS:
            kept.append(f"{key}={REDACTED}")
            continue
        decoded = unquote_plus(value)
        scrubbed = _scrub_plain(decoded)
        if norm in _KEEP_QUERY_KEYS and scrubbed == decoded:
            kept.append(pair)
        elif scrubbed == decoded:
            kept.append(pair)
        elif norm in _KEEP_QUERY_KEYS:
            kept.append(f"{key}={scrubbed}")
        else:
            kept.append(f"{key}={REDACTED}")
    if not kept:
        return ""
    return "?" + "&".join(kept)


def scrub_structure(value: Any, *, depth: int = 0) -> Any:
    """Drop note-text keys and redact identifier keys in mappings and sequences."""
    if depth > 8:
        return REDACTED
    if isinstance(value, Mapping):
        cleaned: dict[Any, Any] = {}
        for key, item in value.items():
            norm = _norm_key(key)
            if norm in NOTE_TEXT_KEYS:
                continue
            if norm in IDENTIFIER_KEYS:
                cleaned[key] = REDACTED
            else:
                cleaned[key] = scrub_structure(item, depth=depth + 1)
        return cleaned
    if isinstance(value, tuple):
        return tuple(scrub_structure(item, depth=depth + 1) for item in value)
    if isinstance(value, list):
        return [scrub_structure(item, depth=depth + 1) for item in value]
    if isinstance(value, str):
        return scrub_text(value, depth=depth + 1)
    if isinstance(value, bytes | bytearray):
        decoded = bytes(value).decode("utf-8", "replace")
        return scrub_text(decoded, depth=depth + 1).encode("utf-8")
    return value


def _scrub_embedded_json(text: str, depth: int) -> str:
    decoder = json.JSONDecoder()
    pieces: list[str] = []
    index = 0
    length = len(text)
    while index < length:
        start = index
        while start < length and text[start] not in "{[":
            start += 1
        if start >= length:
            pieces.append(text[index:])
            break
        try:
            parsed, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            pieces.append(text[index : start + 1])
            index = start + 1
            continue
        pieces.append(text[index:start])
        if isinstance(parsed, dict | list):
            pieces.append(
                json.dumps(
                    scrub_structure(parsed, depth=depth + 1),
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
        else:
            pieces.append(text[start:end])
        index = end
    return "".join(pieces)


def scrub_text(value: str, *, depth: int = 0) -> str:
    """Redact identifiers and note text in a log string."""
    if depth > 8:
        return REDACTED
    stripped = value.strip()
    if stripped[:1] in "{[":
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict | list):
            rendered = json.dumps(
                scrub_structure(parsed, depth=depth + 1),
                ensure_ascii=False,
                separators=(",", ":"),
            )
            leading = value[: len(value) - len(value.lstrip())]
            trailing = value[len(value.rstrip()) :]
            return leading + rendered + trailing
    scrubbed = _scrub_embedded_json(value, depth)
    scrubbed = _QUERY.sub(lambda match: _scrub_query(match.group(0)), scrubbed)
    return _scrub_plain(scrubbed)


def _scrub_traceback(exc: traceback.TracebackException) -> None:
    captured: Any = exc
    message = getattr(captured, "_str", None)
    if isinstance(message, str):
        captured._str = _scrub_plain(message)
    notes = getattr(exc, "__notes__", None)
    if isinstance(notes, list):
        exc.__notes__ = [_scrub_plain(str(note)) for note in notes]
    for attr in ("msg", "text"):
        syntax = getattr(exc, attr, None)
        if isinstance(syntax, str):
            setattr(exc, attr, _scrub_plain(syntax))
    # Frame locals stay out of the written traceback. A local can hold a note,
    # an identifier, or a credential.
    stack = getattr(exc, "stack", None)
    if stack:
        for frame in stack:
            frame.locals = None
    for nested_name in ("__cause__", "__context__"):
        nested = getattr(exc, nested_name, None)
        if isinstance(nested, traceback.TracebackException):
            _scrub_traceback(nested)
    grouped = getattr(exc, "exceptions", None)
    if grouped:
        for nested in grouped:
            if isinstance(nested, traceback.TracebackException):
                _scrub_traceback(nested)


def format_scrubbed_traceback(exc_info: tuple[type[BaseException], BaseException, Any]) -> str:
    captured = traceback.TracebackException(*exc_info, capture_locals=False)
    _scrub_traceback(captured)
    return _scrub_plain("".join(captured.format()))


def _scrub_message(record: logging.LogRecord) -> None:
    if record.name.startswith("uvicorn.access") and isinstance(record.args, tuple):
        record.args = tuple(
            scrub_text(arg) if isinstance(arg, str) else arg for arg in record.args
        )
        return
    if isinstance(record.args, Mapping):
        record.args = scrub_structure(dict(record.args))
        if isinstance(record.msg, str):
            record.msg = scrub_text(record.msg)
        return
    if record.args:
        try:
            rendered = record.getMessage()
        except Exception:
            rendered = str(record.msg)
        record.msg = scrub_text(rendered)
        record.args = ()
        return
    if isinstance(record.msg, str):
        record.msg = scrub_text(record.msg)
    else:
        record.msg = scrub_structure(record.msg)


def _scrub_log_record(record: logging.LogRecord) -> None:
    _scrub_message(record)
    for key in list(record.__dict__):
        if key in _RESERVED_RECORD_ATTRS:
            continue
        norm = _norm_key(key)
        if norm in NOTE_TEXT_KEYS:
            del record.__dict__[key]
            continue
        value = record.__dict__[key]
        if norm in IDENTIFIER_KEYS:
            record.__dict__[key] = REDACTED
        else:
            record.__dict__[key] = scrub_structure(value)
    if record.exc_info and record.exc_info[0] is not None:
        record.exc_text = format_scrubbed_traceback(record.exc_info)
        record.exc_info = None
    elif isinstance(record.exc_text, str):
        record.exc_text = scrub_text(record.exc_text)
    if isinstance(record.stack_info, str):
        record.stack_info = scrub_text(record.stack_info)


def scrub_log_record(record: logging.LogRecord) -> None:
    """Scrub one log record in place. Failures redact the record instead of logging it raw."""
    if getattr(_guard, "active", False):
        return
    _guard.active = True
    try:
        _scrub_log_record(record)
    except Exception:
        record.msg = REDACTED
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        for key in list(record.__dict__):
            if key not in _RESERVED_RECORD_ATTRS:
                del record.__dict__[key]
    finally:
        _guard.active = False


class LogScrubFilter(logging.Filter):
    """Logging filter that redacts a record before any handler writes it."""

    def filter(self, record: logging.LogRecord) -> bool:
        scrub_log_record(record)
        return True


class ScrubbingFormatter(logging.Formatter):
    """Formatter wrapper that scrubs the record and the rendered line."""

    def __init__(self, inner: logging.Formatter) -> None:
        super().__init__()
        self.inner = inner

    def format(self, record: logging.LogRecord) -> str:
        scrub_log_record(record)
        return scrub_text(self.inner.format(record))
