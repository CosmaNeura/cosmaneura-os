"""Pin shared production_review_profile.py to the CTO handoff digest (#377/#381)."""

from __future__ import annotations

import hashlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MODULE = REPO / "src/cosmas_os/production_review_profile.py"
# Byte-identical shared predicate handoff:
# /cursor/stores/bot/handoff/shared-review-predicate/production_review_profile.py.sha256
HANDOFF_SHA256 = "f8417ede7a6b1ffd4dc8921dd69e6569bdb9e1f5bcf1357899f835fc4e704740"


def test_production_review_profile_matches_handoff_sha256():
    digest = hashlib.sha256(MODULE.read_bytes()).hexdigest()
    assert digest == HANDOFF_SHA256
    # Mutation: rewriting the module or reformatting it must fail this pin.
    assert MODULE.name == "production_review_profile.py"
