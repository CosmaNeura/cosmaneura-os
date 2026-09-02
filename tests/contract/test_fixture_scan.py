from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "fixtures" / "synthetic"

# Patterns that look like production MRNs / real patient dumps — fail the build.
FORBIDDEN = [
    re.compile(r"\bMRN[-_ ]?\d{6,}\b", re.I),
    re.compile(r"\bSSN\b", re.I),
    re.compile(r"sk_live_"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
]


def test_fixtures_have_no_production_like_identifiers():
    assert FIX.exists()
    for path in FIX.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pat in FORBIDDEN:
            assert not pat.search(text), f"{path} matched {pat.pattern}"
