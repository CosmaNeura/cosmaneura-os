"""CosmaBot recording path must not reach AssemblyAI or Recall.ai (T-REL-6).

Scans the live capture/upload/Core-adapter code path. Docs/reference text is
ignored. Upload-origin refusal is covered by clients/shared and clients/capture
tests; this module proves there is no SDK/host/env wiring on the CosmaBot path
and that the dormant desktop Recall config strings have zero importers.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# Matches vendor wiring, not the intentional refusal blocklists/messages.
WIRING_RE = re.compile(
    r"""(?x)
    (?:from\s+['\"]@?(?:assemblyai|recallai))
    |(?:import\s*\(\s*['\"]@?(?:assemblyai|recallai))
    |(?:require\s*\(\s*['\"]@?(?:assemblyai|recallai))
    |https?://[^\s'\"`]*?(?:assemblyai\.com|recall\.ai)
    |(?:ASSEMBLYAI_[A-Z0-9_]+|RECALL_AI_[A-Z0-9_]+|ASSEMBLY_AI_[A-Z0-9_]+)
    |@assemblyai/|@recallai/
    """,
    re.IGNORECASE,
)

NAME_RE = re.compile(r"assemblyai|recall\.ai|@recallai|@assemblyai|COSMAS_RECALL", re.IGNORECASE)

CAPTURE_GLOBS = [
    "src/cosmas_os/adapters/core_capture*.py",
    "src/cosmas_os/application/*capture*.py",
    "src/cosmas_os/application/private_recording.py",
    "src/cosmas_os/ports/capture*.py",
    "src/cosmas_os/ports/core_capture.py",
    "clients/capture/src/**/*.ts",
    "clients/capture/src/**/*.tsx",
    "clients/shared/beta-feature-profile.mjs",
    "web/src/capture*.ts",
    "web/src/capture*.tsx",
    "web/src/saved-recording*.ts",
]

# Intentional refusal surfaces may name the vendors in comments/errors/blocklists.
REFUSAL_FILES = {
    REPO / "clients/capture/src/bff/forbidden-upload-hosts.ts",
    REPO / "clients/capture/src/bff/upload-target.ts",
    REPO / "clients/shared/beta-feature-profile.mjs",
}

DORMANT_RECALL_CONFIG = REPO / "clients/desktop/recorder/config.ts"


def _capture_sources() -> list[Path]:
    found: set[Path] = set()
    for pattern in CAPTURE_GLOBS:
        found.update(REPO.glob(pattern))
    return sorted(
        path
        for path in found
        if path.is_file()
        and not path.name.endswith((".test.ts", ".test.tsx", ".test.mjs", ".test.js"))
    )


def test_cosmabot_capture_modules_have_no_assemblyai_or_recall_wiring():
    offenders: list[str] = []
    for path in _capture_sources():
        text = path.read_text(encoding="utf-8")
        for match in WIRING_RE.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            offenders.append(f"{path.relative_to(REPO)}:{line}:{match.group(0)}")
        if path in REFUSAL_FILES:
            continue
        for match in NAME_RE.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            offenders.append(f"{path.relative_to(REPO)}:{line}:{match.group(0)}")
    assert offenders == [], (
        "CosmaBot recording path must not wire AssemblyAI/Recall: " + "; ".join(offenders)
    )


def test_package_manifests_do_not_depend_on_assemblyai_or_recall():
    for path in list(REPO.glob("**/package.json")) + [REPO / "pyproject.toml", REPO / "uv.lock"]:
        if "node_modules" in path.parts or ".venv" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"assemblyai|@recallai|recallai", text, re.IGNORECASE), path


def test_dormant_desktop_recall_config_has_zero_importers():
    """Dormant Recall-named constants exist only in config.ts and are unreferenced.

    File: clients/desktop/recorder/config.ts:1-17. No other module imports them,
    so the CosmaBot recording path cannot reach Recall through this config.
    """
    text = DORMANT_RECALL_CONFIG.read_text(encoding="utf-8")
    assert "COSMAS_RECALL_DESKTOP_COMPANION_ENABLED" in text
    assert "@recallai/desktop-sdk" in text
    tokens = (
        "RECALL_DESKTOP_SDK_CONFIG",
        "COSMAS_RECALL_DESKTOP_COMPANION_ENABLED",
        "DESKTOP_COMPANION_FEATURE_FLAG",
        "parseCompanionFeatureFlag",
        "@recallai/desktop-sdk",
    )
    importers: list[str] = []
    for path in REPO.rglob("*"):
        if not path.is_file() or path == DORMANT_RECALL_CONFIG:
            continue
        if path.suffix not in {".ts", ".tsx", ".mjs", ".js", ".py", ".json"}:
            continue
        if any(part in {"node_modules", ".venv", "dist", "build", "tests"} for part in path.parts):
            continue
        # Isolation tests may name the dormant tokens; they are not runtime importers.
        if path.name.startswith("test_cosmabot_recording_vendor"):
            continue
        body = path.read_text(encoding="utf-8", errors="ignore")
        if any(token in body for token in tokens):
            importers.append(str(path.relative_to(REPO)))
    assert importers == [], "Dormant Recall config must stay unreferenced: " + ", ".join(importers)
