"""The recovered iPhone tree is frozen 1107 evidence, not a qualified new build."""

import hashlib
import importlib.util
import json
import plistlib
import re
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
        if equivalent["path"] == "clients/apple/native-auth/Bridge/NativeCaptureProcessFence.swift":
            current = live.read_text(encoding="utf-8")
            old_header = "// INERT PROPOSAL: not part of any selected app or source package."
            new_header = "// Desktop process fencing; iOS metadata operations are compiled out and fail closed."
            assert current.startswith(new_header + "\n")
            assert current.count("#if os(macOS)") == 4
            fallbacks = re.findall(r"#else\n(.*?)#endif", current, re.DOTALL)
            assert len(fallbacks) == 4
            assert all(part.strip() == "throw NativeFenceError.unavailable" for part in fallbacks)
            macos = re.sub(r"#if os\(macOS\)\n(.*?)#else\n.*?#endif\n", r"\1", current, flags=re.DOTALL)
            assert macos.replace(new_header, old_header, 1) == recovered.read_text(encoding="utf-8")
            iphone = re.sub(r"#if os\(macOS\)\n.*?#else\n(.*?)#endif\n", r"\1", current, flags=re.DOTALL)
            assert re.search(r"\bfstat(?:at)?\s*\(", iphone) is None
        else:
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
        "ios/App/App/CosmasWorkspaceViewController.swift",
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
    frozen_count = json.loads(PROVENANCE.read_text(encoding="utf-8"))["native_source_file_count"]
    assert len(manifest["files"]) == frozen_count + 1
    assert len({item["path"] for item in manifest["files"]}) == len(manifest["files"])
    privacy = [item for item in manifest["files"] if item["path"] == "ios/App/App/PrivacyInfo.xcprivacy"]
    assert len(privacy) == 1
    assert privacy[0]["role"] == "implementation"
    assert privacy[0]["owner"] == "clients/apple"
    assert privacy[0]["authoritative_counterpart"] == "clients/apple/startup-recovery/PrivacyInfo.xcprivacy"
    assert plistlib.loads((output / "apps/capture/ios/App/App/PrivacyInfo.xcprivacy").read_bytes()) == {
        "NSPrivacyAccessedAPITypes": [{
            "NSPrivacyAccessedAPIType": "NSPrivacyAccessedAPICategorySystemBootTime",
            "NSPrivacyAccessedAPITypeReasons": ["35F9.1"],
        }],
    }
    assert (output / "apps/capture/ios/App/App/Info.plist").read_bytes() == (
        ROOT / "apps/capture/ios/App/App/Info.plist"
    ).read_bytes()
    default_info = plistlib.loads((output / "apps/capture/ios/App/App/Info.plist").read_bytes())
    assert default_info["CosmasNativeAuth"]["enabled"] is False
    assert default_info["CosmasConfiguredCapture"]["enabled"] is False
    derived = [item for item in manifest["files"] if item["role"] == "derived-app-resource-wiring"]
    assert len(derived) == 1
    assert derived[0]["path"] == "ios/App/App.xcodeproj/project.pbxproj"

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
        elif item["role"] == "derived-app-resource-wiring":
            assert item["owner"] == "apps/capture"
            assert item["path"] == "ios/App/App.xcodeproj/project.pbxproj"
            original = ROOT / "apps/capture" / item["path"]
            assert item["scaffold_input_sha256"] == _sha256(original)
            assert item["derivation_source"] == "scripts/compose-portable-iphone.py"
            assert item["derivation_source_sha256"] == _sha256(PORTABLE_COMPOSE)
            text = placed.read_text(encoding="utf-8")
            privacy_lines = [line for line in text.splitlines(keepends=True) if "PrivacyInfo.xcprivacy" in line]
            assert len(privacy_lines) == 4
            assert "".join(line for line in text.splitlines(keepends=True) if "PrivacyInfo.xcprivacy" not in line) == original.read_text(encoding="utf-8")
        elif item["role"] == "app-scaffold":
            assert item["owner"] == "apps/capture"
            assert placed.read_bytes() == (ROOT / "apps/capture" / item["path"]).read_bytes()
        else:
            raise AssertionError(item["role"])
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
