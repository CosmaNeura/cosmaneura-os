"""The recovered iPhone tree is frozen 1107 evidence, not a qualified new build."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROVENANCE = ROOT / "apps/capture/SOURCE_PROVENANCE.json"
APPLE_PREPARE = ROOT / "scripts/prepare-apple-synthetic.py"
PORTABLE_COMPOSE = ROOT / "scripts/compose-portable-iphone.py"
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
        "native-plugins/cosmas-native-auth/Sources/CosmasNativeAuth/NativeClerkConfiguration.swift",
        "native-plugins/native-recording-pcm/Package.swift",
    ]


def _portable():
    spec = importlib.util.spec_from_file_location("portable_iphone_compose", PORTABLE_COMPOSE)
    if spec is None or spec.loader is None:
        raise AssertionError("portable iPhone composition entry is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_portable_iphone_entry_selects_owned_clients_without_the_external_snapshot(tmp_path):
    text = PORTABLE_COMPOSE.read_text(encoding="utf-8")
    assert "ea7f99d" not in text
    assert EXTERNAL_CAPTURE_SNAPSHOT not in text
    module = _portable()
    assert module.IMPLEMENTATION_OWNERS == ("clients/apple", "clients/capture")

    before = _sha256(ROOT / "apps/capture/ios/App/App/Info.plist")
    output = tmp_path / "iphone-inputs"
    project = module.compose(ROOT, output)
    assert project == output / "apps/capture/ios/App/App.xcodeproj"
    assert project.is_dir()
    assert _sha256(ROOT / "apps/capture/ios/App/App/Info.plist") == before

    manifest_text = (output / "composition.json").read_text(encoding="utf-8")
    assert "ea7f99d" not in manifest_text
    manifest = json.loads(manifest_text)
    assert manifest["implementation_owners"] == ["clients/apple", "clients/capture"]
    assert manifest["app_scaffold"] == "apps/capture"
    assert manifest["scaffold_role"] == "frozen-1107-evidence"
    assert manifest["external_snapshot_required"] is False
    assert manifest["qualified_install"] is False
    assert manifest["compiled_signed_or_installed"] is False
    assert manifest["generated_web_assets"] == "absent"
    assert not (output / "apps/capture/ios/App/App/public").exists()
    assert len(manifest["files"]) == json.loads(PROVENANCE.read_text(encoding="utf-8"))["native_source_file_count"]

    owners = set()
    for item in manifest["files"]:
        placed = output / "apps/capture" / item["path"]
        assert _sha256(placed) == item["sha256"]
        if item["role"] == "implementation":
            owners.add(item["owner"])
            counterpart = ROOT / item["authoritative_counterpart"]
            assert item["owner"] in {"clients/apple", "clients/capture"}
            assert str(counterpart.relative_to(ROOT)).startswith(item["owner"] + "/")
            assert placed.read_bytes() == counterpart.read_bytes()
        elif item["role"] == "supporting-client":
            counterpart = ROOT / item["authoritative_counterpart"]
            assert str(counterpart.relative_to(ROOT)).startswith("clients/shared/")
            assert placed.read_bytes() == counterpart.read_bytes()
        elif item["role"] == "scaffold-package-wiring":
            assert item["owner"] == "apps/capture"
            assert placed.read_bytes() == (ROOT / "apps/capture" / item["path"]).read_bytes()
            counterpart = item["authoritative_counterpart"]
            assert counterpart.startswith("clients/apple/") or counterpart.startswith("clients/capture/")
    assert owners == {"clients/apple", "clients/capture"}
    apple = output / "apps/capture/ios/App/App/SceneDelegate.swift"
    capture = output / "apps/capture/native-plugins/ios-pcm-capture/Sources/CosmaneuraIOSPCMCore/IOSPCMCore.swift"
    assert apple.read_bytes() == (ROOT / "clients/apple/startup-recovery/SceneDelegate.swift").read_bytes()
    assert capture.read_bytes() == (
        ROOT / "clients/capture/native-configured/ios-pcm-capture/Sources/CosmaneuraIOSPCMCore/IOSPCMCore.swift"
    ).read_bytes()


def test_portable_iphone_compose_refuses_to_rewrite_the_frozen_scaffold(tmp_path):
    inside = ROOT / "apps/capture/not-an-output"
    with pytest.raises(ValueError, match="outside the repository"):
        _portable().compose(ROOT, inside)
    assert not inside.exists()
    existing = tmp_path / "already"
    existing.mkdir()
    with pytest.raises(ValueError, match="must not exist"):
        _portable().compose(ROOT, existing)
    assert list(existing.iterdir()) == []
