"""Pin the 1d choice: prepare-workspace-identity keeps raw validate (no fence)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ROOT / "scripts/prepare-workspace-identity.mjs"
FENCE = ROOT / "tests/unit/test_installation_profile_fence_callers.py"


def test_workspace_identity_documents_raw_validate_choice():
    text = WORKSPACE.read_text(encoding="utf-8")
    assert "Leave raw validateOperationalNativeIdentity (no installation-profile fence)." in text
    assert "Pinned by tests/unit/test_workspace_identity_raw_validate_choice.py." in text
    assert "loadOperationalNativeIdentity" not in text
    assert "requireProductionInstallationProfile" not in text
    # Still on the raw-caller allow-list.
    allow = FENCE.read_text(encoding="utf-8")
    assert '"scripts/prepare-workspace-identity.mjs"' in allow
