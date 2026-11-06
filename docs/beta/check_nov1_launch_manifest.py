#!/usr/bin/env python3
"""Fail when the November 1 launch manifest drops a required statement.

The five statements are the launch rules in
docs/beta/COSMABOT_NOV1_LAUNCH_MANIFEST.md. This script reads that file
and exits non-zero if any statement is missing. It does not change CI.
"""

from __future__ import annotations

import sys
from pathlib import Path

MANIFEST = Path(__file__).with_name("COSMABOT_NOV1_LAUNCH_MANIFEST.md")

# Each item is one required statement. Every phrase must appear verbatim.
STATEMENTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("EHR is synthetic only", ("EHR is synthetic only.",)),
    (
        "For Zoom, tell users to use Upload Recording and never say Zoom is fixed",
        ('use Upload Recording', 'Never say Zoom is "fixed".'),
    ),
    ("There is no SOC 2", ("There is no SOC 2.",)),
    ("There is no EHR write-back", ("There is no EHR write-back.",)),
    (
        "There is no stranger checkout",
        ("There is no stranger checkout", "no self-serve purchase by unknown users"),
    ),
)

ZOOM_WARNING = 'Never say Zoom is "fixed".'
ZOOM_CLAIMS = ('Zoom is "fixed"', "Zoom is fixed")


def missing_statements(text: str) -> list[str]:
    missing: list[str] = []
    for name, phrases in STATEMENTS:
        if any(phrase not in text for phrase in phrases):
            missing.append(name)
    remainder = text.replace(ZOOM_WARNING, "")
    if any(claim in remainder for claim in ZOOM_CLAIMS):
        missing.append("document says Zoom is fixed")
    return missing


def self_check() -> None:
    """The detector must fail when any one required statement is removed."""
    complete = "\n".join(phrase for _, phrases in STATEMENTS for phrase in phrases)
    if missing_statements(complete):
        raise SystemExit("detector accepted a broken complete sample")
    for name, phrases in STATEMENTS:
        broken = complete.replace(phrases[0], "", 1)
        found = missing_statements(broken)
        if name not in found:
            raise SystemExit(f"detector did not fail when missing: {name}")
    claimed = complete + "\nZoom is fixed.\n"
    if "document says Zoom is fixed" not in missing_statements(claimed):
        raise SystemExit("detector did not fail when the document says Zoom is fixed")


def main() -> int:
    self_check()
    if not MANIFEST.is_file():
        print(f"missing manifest: {MANIFEST}", file=sys.stderr)
        return 1
    text = MANIFEST.read_text(encoding="utf-8")
    missing = missing_statements(text)
    if missing:
        print("November 1 launch manifest is missing required statements:", file=sys.stderr)
        for name in missing:
            print(f"- {name}", file=sys.stderr)
        return 1
    print(f"ok: {len(STATEMENTS)} required statements in {MANIFEST.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
