"""Plain-text normalisation for clipboard paste. No leading '#'."""

from __future__ import annotations

import re

_BULLET = re.compile(r"^[\t ]*(?:[-*•]|\d+[.)])[\t ]+")
_LEADING_HASH = re.compile(r"^[\t ]*#+[\t ]*")


def words_label(key: str) -> str:
    """Turn a field key into a words-style label (``chief_complaint`` → ``Chief Complaint``)."""
    parts = re.split(r"[_\s]+", key.strip())
    return " ".join(part[:1].upper() + part[1:] if part else "" for part in parts if part)


def normalise_section_text(text: str, *, forbid_leading_hash: bool = True) -> str:
    """Plain text only: normalise bullets to plain lines; strip a leading ``#``."""
    if not isinstance(text, str):
        raise TypeError("section_text_required")
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = _BULLET.sub("", raw)
        if forbid_leading_hash:
            line = _LEADING_HASH.sub("", line)
        lines.append(line.rstrip())
    # Drop a single trailing empty line; keep internal blank lines.
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)
