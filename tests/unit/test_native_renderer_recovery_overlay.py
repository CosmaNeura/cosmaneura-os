"""Read-only pinned-source inputs; mutations stay inside each temporary archive."""

import hashlib
import importlib.util
import io
import json
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
SOURCE = ROOT.parent / "cosmaneura-scribe"
REF = "ea7f99d0278a05706531ffb1288cb1df7acf507b"
PREFIX = "apps/capture/native-plugins/"
pytestmark = pytest.mark.skipif(not SOURCE.is_dir(), reason="Local read-only Scribe source required")


def module(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / name)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def inventory(output):
    return {str(path.relative_to(output)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in output.rglob("*") if path.is_file()}


@pytest.fixture
def archived(tmp_path):
    content = subprocess.check_output(["git", "archive", REF,
                                      PREFIX + "ios-pcm-capture", PREFIX + "ios-pcm-capacitor"], cwd=SOURCE)
    output = tmp_path / "archive"
    output.mkdir()
    with tarfile.open(fileobj=io.BytesIO(content)) as archive:
        assert not any(member.issym() or member.islnk() for member in archive.getmembers())
        archive.extractall(output, filter="data")
    return output


@pytest.fixture
def renewable(archived):
    module("apply-native-capture-overlay.py").apply(archived, REF)
    # A durable-store canary is outside this overlay's source contract.
    (archived / "encrypted-queue.canary").write_bytes(b"synthetic ciphertext must stay unchanged")
    return archived


def test_renderer_overlay_changes_exact_sources_once_and_keeps_js_surface(renewable):
    overlay = module("apply-native-renderer-recovery-overlay.py")
    before = inventory(renewable)
    plugin = renewable / (PREFIX + "ios-pcm-capacitor/Sources/CosmaneuraIOSPCMCapacitor/IOSPCMCapacitorPlugin.swift")
    registrations = plugin.read_text().split("public let pluginMethods:")[1].split("private var transport:")[0]
    result = overlay.apply(renewable, REF)
    after = inventory(renewable)
    assert {name for name in before if before[name] != after[name]} == set(result["files"])
    assert set(before) == set(after)
    assert all(after[name] == hashes["after"] for name, hashes in result["files"].items())
    assert registrations == plugin.read_text().split("public let pluginMethods:")[1].split("private var transport:")[0]
    assert "@nonobjc public func fenceAndStopForRendererLoss" in plugin.read_text()
    assert "@nonobjc public static func confirmProcessCaptureIdle" in plugin.read_text()
    with pytest.raises(ValueError, match="base changed"):
        overlay.apply(renewable, REF)
    assert inventory(renewable) == after


def test_renderer_overlay_requires_complete_renewable_base(archived):
    overlay = module("apply-native-renderer-recovery-overlay.py")
    before = inventory(archived)
    with pytest.raises(ValueError, match="base changed"):
        overlay.apply(archived, REF)
    assert inventory(archived) == before


@pytest.mark.parametrize("damage", ["changed-source", "changed-prerequisite", "wrong-ref", "finalized", "git-root"])
def test_renderer_overlay_rejects_drift_before_any_mutation(renewable, damage):
    overlay = module("apply-native-renderer-recovery-overlay.py")
    if damage == "changed-source":
        (renewable / sorted(overlay.ALLOWED_FILES)[0]).write_text("// independent work\n")
    elif damage == "changed-prerequisite":
        path = renewable / (PREFIX + "ios-pcm-capture/Sources/CosmaneuraIOSPCMCore/IOSPCMCore.swift")
        path.write_text(path.read_text() + "\n// independently changed core\n")
    elif damage == "finalized":
        (renewable / "composition.json").write_text("{}")
    elif damage == "git-root":
        (renewable / ".git").mkdir()
    before = inventory(renewable)
    with pytest.raises(ValueError):
        overlay.apply(renewable, "wrong-ref" if damage == "wrong-ref" else REF)
    assert inventory(renewable) == before


def test_renderer_overlay_cannot_follow_source_symlink(renewable, tmp_path):
    overlay = module("apply-native-renderer-recovery-overlay.py")
    source = renewable / sorted(overlay.ALLOWED_FILES)[0]
    outside = tmp_path / "preserve-source.swift"
    outside.write_bytes(source.read_bytes())
    source.unlink()
    source.symlink_to(outside)
    before = inventory(renewable)
    preserved = outside.read_bytes()
    with pytest.raises(ValueError, match="ordinary archived"):
        overlay.apply(renewable, REF)
    assert inventory(renewable) == before
    assert outside.read_bytes() == preserved


@pytest.mark.parametrize("damage", ["patch-hash", "unlisted-patch", "bad-hash-contract"])
def test_renderer_overlay_validates_patch_and_manifest_before_writing(renewable, tmp_path, damage):
    overlay = module("apply-native-renderer-recovery-overlay.py")
    copied = tmp_path / "overlay"
    shutil.copytree(overlay.OVERLAY, copied)
    overlay.OVERLAY = copied
    patch = copied / "source.patch"
    manifest = json.loads((copied / "manifest.json").read_text())
    if damage == "bad-hash-contract":
        manifest["files"][sorted(overlay.ALLOWED_FILES)[0]]["after"] = "not-a-hash"
    else:
        patch.write_text(patch.read_text() + "\ndiff --git a/encrypted-queue.canary b/encrypted-queue.canary\n"
                         "--- a/encrypted-queue.canary\n+++ b/encrypted-queue.canary\n"
                         "@@ -1 +1 @@\n-synthetic ciphertext must stay unchanged\n+wrong\n")
        if damage == "unlisted-patch":
            manifest["patch_sha256"] = hashlib.sha256(patch.read_bytes()).hexdigest()
    (copied / "manifest.json").write_text(json.dumps(manifest))
    before = inventory(renewable)
    with pytest.raises(ValueError):
        overlay.apply(renewable, REF)
    assert inventory(renewable) == before
