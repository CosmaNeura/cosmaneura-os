"""Scrub plugin-process logs with the shared log scrubber.

Nothing here copies the scrubber. Startup installs ``LogScrubFilter`` and
``ScrubbingFormatter`` from ``cosmas_os.log_scrub`` on the process loggers.

The MCP stdio transport duplicates stderr onto stdout while it is serving, so
a print during a tool call is a log line. Protocol frames use a private copy
of the original stdout and do not pass through this wrapper.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from typing import TextIO

from cosmas_os.log_scrub import REDACTED, scrub_text
from cosmas_os.logging_setup import install

_LIMIT = 262144


def arm_plugin_loggers() -> None:
    """Install the shared scrubbing filter and formatter on current and later handlers."""
    install()


def _safe(text: str) -> str:
    try:
        return scrub_text(text)
    except Exception:
        return f"{REDACTED}\n" if text.endswith("\n") else REDACTED


def _attach(stream: TextIO) -> None:
    if getattr(stream, "_cosmas_plugin_scrub", False):
        return
    original_write = stream.write
    original_flush = stream.flush
    pending = ""
    busy = False

    def write(data: str) -> int:
        nonlocal pending, busy
        if not isinstance(data, str):
            data = str(data)
        if data == "":
            return 0
        if busy:
            original_write(REDACTED)
            return len(data)
        pending += data
        _drain(force=False)
        return len(data)

    def _drain(*, force: bool) -> None:
        nonlocal pending
        while "\n" in pending:
            line, pending = pending.split("\n", 1)
            _emit(line + "\n")
        if pending and (force or len(pending) > _LIMIT):
            _emit(pending)
            pending = ""

    def _emit(text: str) -> None:
        nonlocal busy
        busy = True
        try:
            original_write(_safe(text))
        finally:
            busy = False

    def flush() -> None:
        if busy:
            original_flush()
            return
        _drain(force=True)
        original_flush()

    def writelines(lines: Iterable[str]) -> None:
        for line in lines:
            write(line)

    stream.write = write  # type: ignore[method-assign]
    stream.flush = flush  # type: ignore[method-assign]
    stream.writelines = writelines  # type: ignore[method-assign]
    stream._cosmas_plugin_scrub = True  # type: ignore[attr-defined]


def install_plugin_log_scrubbing() -> None:
    """Arm loggers and scrub every text write to stderr for this process."""
    arm_plugin_loggers()
    _attach(sys.stderr)


@contextmanager
def scrub_diverted_stdout() -> Iterator[None]:
    """Scrub stdout while the stdio transport is using it as the log channel."""
    stream = sys.stdout
    if getattr(stream, "_cosmas_plugin_scrub", False):
        yield
        return
    original_write = stream.write
    original_flush = stream.flush
    original_writelines = stream.writelines
    _attach(stream)
    try:
        yield
    finally:
        stream.flush()
        stream.write = original_write  # type: ignore[method-assign]
        stream.flush = original_flush  # type: ignore[method-assign]
        stream.writelines = original_writelines  # type: ignore[method-assign]
        stream._cosmas_plugin_scrub = False  # type: ignore[attr-defined]
