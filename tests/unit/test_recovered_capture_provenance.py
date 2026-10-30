"""The recovered iPhone tree is frozen 1107 evidence, not a qualified new build."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROVENANCE = ROOT / "apps/capture/SOURCE_PROVENANCE.json"
APPLE_PREPARE = ROOT / "scripts/prepare-apple-synthetic.py"
EXTERNAL_CAPTURE_SNAPSHOT = "ea7f99d0278a05706531ffb1288cb1df7acf507b"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_recovered_capture_matches_its_recorded_evidence_and_stays_unqualified():
    record = json.loads(PROVENANCE.read_text(encoding="utf-8"))
    assert record["compiled_signed_or_installed_by_this_change"] is False
    assert record["native_current_source_build_qualification"].startswith("PENDING")
    assert EXTERNAL_CAPTURE_SNAPSHOT in APPLE_PREPARE.read_text(encoding="utf-8")

    treatments = {item["treatment"] for item in record["files"]}
    assert treatments == {"exact-released-source", "unconfigured-public-settings-template"}
    redacted = [
        item["path"] for item in record["files"]
        if item["treatment"] == "unconfigured-public-settings-template"
    ]
    assert redacted == ["ios/App/App/Info.plist"]

    differed = []
    for item in record["files"]:
        recovered = ROOT / "apps/capture" / item["path"]
        assert _sha256(recovered) == item["repository_sha256"]
        equivalent = item["tracked_equivalent"]
        if equivalent is None:
            continue
        live = ROOT / equivalent["path"]
        assert _sha256(live) == equivalent["sha256"]
        same = equivalent["sha256"] == item["repository_sha256"]
        if equivalent["status"] == "byte-identical":
            assert same
        elif equivalent["status"] == "differs":
            assert not same
            differed.append(item["path"])
        else:
            raise AssertionError(equivalent["status"])
    assert differed == [
        "native-plugins/cosmas-native-auth/Package.swift",
        "native-plugins/native-recording-pcm/Package.swift",
    ]
