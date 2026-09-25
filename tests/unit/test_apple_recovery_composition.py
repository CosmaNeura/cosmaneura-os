"""Fresh local source composition; never edits or runs the Scribe source."""
import hashlib
import importlib.util
import json
import plistlib
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
SOURCE = ROOT.parent / "cosmaneura-scribe-beta-preintegration-20260904"


def composer():
    spec = importlib.util.spec_from_file_location("apple_recovery_composer", ROOT / "scripts/prepare-apple-synthetic.py")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_recovery_rejects_missing_capture_fence_before_creating_output(tmp_path):
    output = tmp_path / "output"
    with pytest.raises(ValueError, match="requires the renewable"):
        composer().prepare(SOURCE, tmp_path / "missing", output, native_renderer_recovery=True)
    assert not output.exists()


@pytest.mark.skipif(not SOURCE.is_dir(), reason="Local read-only Scribe source required")
def test_recovery_has_one_programmatic_owner_and_exact_native_provenance(tmp_path):
    module = composer()
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<title>Invented recovery composition</title>")
    output = tmp_path / "output"
    module.prepare(SOURCE, web, output, verification_variant="w31q", renewable_native_capture=True,
                   native_renderer_recovery=True, app_version="0.1.12", build_number="3101")
    manifest = json.loads((output / "composition.json").read_text())
    assert manifest["native_renderer_recovery"]["version"] == 1
    for name, hashes in manifest["native_renderer_recovery"]["files"].items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == hashes["after"]
    app = output / "apps/capture/ios/App/App"
    info = plistlib.loads((app / "Info.plist").read_bytes())
    assert "UIMainStoryboardFile" not in info
    assert all("UISceneStoryboardFile" not in scene for scene in
               info["UIApplicationSceneManifest"]["UISceneConfigurations"]["UIWindowSceneSessionRoleApplication"])
    assert "CAPBridgeViewController" not in (app / "Base.lproj/Main.storyboard").read_text()
    for name in (*module.RECOVERY_SOURCES, "SceneDelegate.swift"):
        assert (app / name).read_bytes() == (module.RECOVERY_UI / name).read_bytes()
    project = (app.parent / "App.xcodeproj/project.pbxproj").read_text()
    for name in module.RECOVERY_SOURCES:
        assert project.count(f"/* {name} in Sources */") == 2
    assert "SceneDelegateProxy.shared.scene" in (app / "SceneDelegate.swift").read_text()
    # A finalized candidate and independently edited source are never repair targets.
    before = {str(p.relative_to(output)): p.read_bytes() for p in output.rglob("*") if p.is_file()}
    with pytest.raises(ValueError, match="fresh source archive"):
        module.include_recovery_ui(output)
    assert before == {str(p.relative_to(output)): p.read_bytes() for p in output.rglob("*") if p.is_file()}


def test_ui_rejects_source_drift_without_touching_other_files(tmp_path):
    module = composer()
    output = tmp_path / "archive"
    path = output / next(iter(module.RECOVERY_INPUTS))
    path.parent.mkdir(parents=True)
    path.write_text("// preserve independent local source\n")
    with pytest.raises(ValueError, match="source base changed"):
        module.include_recovery_ui(output)
    assert path.read_text() == "// preserve independent local source\n"
    assert len([p for p in output.rglob("*") if p.is_file()]) == 1
