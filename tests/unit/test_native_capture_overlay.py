"""Local pinned-source integration checks; no app execution or vendor access."""

import hashlib
import importlib.util
import io
import json
import plistlib
import subprocess
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
SOURCE = ROOT.parent / "cosmaneura-scribe-beta-preintegration-20260904"
pytestmark = pytest.mark.skipif(not SOURCE.is_dir(), reason="Local read-only Scribe source required")


def module(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / name)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@pytest.fixture
def archived(tmp_path):
    composer = module("prepare-apple-synthetic.py")
    content = subprocess.check_output(["git", "archive", composer.SOURCE_REF,
                                       *composer.SOURCE_PATHS], cwd=SOURCE)
    output = tmp_path / "archive"
    output.mkdir()
    with tarfile.open(fileobj=io.BytesIO(content)) as archive:
        archive.extractall(output, filter="data")
    return output


def inventory(output):
    return {str(path.relative_to(output)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in output.rglob("*") if path.is_file()}


def test_exact_overlay_applies_once_and_verifies_every_result(archived):
    overlay = module("apply-native-capture-overlay.py")
    result = overlay.apply(archived, module("prepare-apple-synthetic.py").SOURCE_REF)
    assert all(inventory(archived)[name] == values["after"]
               for name, values in result["files"].items())
    after = inventory(archived)
    with pytest.raises(ValueError, match="base changed"):
        overlay.apply(archived, module("prepare-apple-synthetic.py").SOURCE_REF)
    assert inventory(archived) == after


@pytest.mark.parametrize("damage", ["changed-base", "occupied-new-file", "wrong-ref"])
def test_overlay_rejects_drift_before_mutating_any_other_file(archived, damage):
    overlay = module("apply-native-capture-overlay.py")
    manifest = json.loads((overlay.OVERLAY / "manifest.json").read_text())
    if damage != "wrong-ref":
        name = next(name for name, hashes in manifest["files"].items()
                    if (hashes["before"] is None) == (damage == "occupied-new-file"))
        (archived / name).write_text("// preserve independent local work\n")
    before = inventory(archived)
    with pytest.raises(ValueError):
        overlay.apply(archived, "invalid" if damage == "wrong-ref" else manifest["source_ref"])
    assert inventory(archived) == before


def test_apple_composer_keeps_overlay_opt_in_and_records_exact_delta(tmp_path):
    composer = module("prepare-apple-synthetic.py")
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<title>Invented local native composition</title>")
    plain, enabled = tmp_path / "plain", tmp_path / "enabled"
    composer.prepare(SOURCE, web, plain, verification_variant="w9q")
    composer.prepare(SOURCE, web, enabled, verification_variant="w9q", renewable_native_capture=True)
    original = json.loads((plain / "composition.json").read_text())
    changed = json.loads((enabled / "composition.json").read_text())
    assert original["renewable_native_capture"] is None
    assert changed["renewable_native_capture"]["version"] == 1
    assert original["source_sha256"] == changed["source_sha256"]
    assert original["bundle_id"] == changed["bundle_id"] == "com.cosmasos.synthetic.w9q"
    assert original["simulator_custody"] == changed["simulator_custody"]
    assert original["minimum_ios_version"] == changed["minimum_ios_version"] == "17.0"
    # Xcode compiles each package at its own minimum, independently of the app.
    # The renewable clock requires the accepted iOS 17 platform throughout its
    # dependency chain; an app-only deployment target does not qualify it.
    for package in ("ios-pcm-capture", "ios-pcm-capacitor"):
        relative = f"apps/capture/native-plugins/{package}/Package.swift"
        assert ".iOS(.v17)" in (enabled / relative).read_text()
        assert ".iOS(.v15)" not in (enabled / relative).read_text()
        assert ".iOS(.v15)" in (plain / relative).read_text()
        assert inventory(enabled)[relative] == changed["renewable_native_capture"]["files"][relative]["after"]


def test_product_update_preserves_apple_container_and_simulator_key_identity(tmp_path):
    composer = module("prepare-apple-synthetic.py")
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<title>Invented update qualification</title>")
    identities = []
    for version, build in (("0.1.0", "1901"), ("0.1.1", "1902")):
        output = tmp_path / build
        project = composer.prepare(SOURCE, web, output, verification_variant="w19",
                                   simulator_custody=True, app_version=version, build_number=build)
        app = project.parent / "App"
        settings = (project / "project.pbxproj").read_text()
        assert settings.count(f"MARKETING_VERSION = {version};") == 2
        assert settings.count(f"CURRENT_PROJECT_VERSION = {build};") == 2
        assert f'version="{version}"' in (app / "config.xml").read_text()
        manifest = json.loads((output / "composition.json").read_text())
        assert (manifest["app_version"], manifest["build_number"]) == (version, build)
        identities.append((manifest["bundle_id"], plistlib.loads((app / "CosmasSimulator.entitlements").read_bytes()),
                           json.loads((app / "capacitor.config.json").read_text())["appId"]))
    assert identities[0] == identities[1]


@pytest.mark.parametrize("version,build", [("0.1.0-beta", "1"), ("1.0", "1"), ("0.1.0", "0"), ("0.1.0", "10000")])
def test_invalid_apple_product_version_fails_before_creating_any_output(tmp_path, version, build):
    output = tmp_path / "output"
    with pytest.raises(ValueError, match="numeric"):
        module("prepare-apple-synthetic.py").prepare(SOURCE, tmp_path / "missing", output,
                                                   app_version=version, build_number=build)
    assert not output.exists()
