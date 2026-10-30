"""Native scene hints: executable delivery contract, not device acceptance."""

import hashlib
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "clients/apple/startup-recovery"
NODE = Path("~/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node").expanduser()
GENERATION = "00000000-0000-4000-8000-000000000001"


@pytest.fixture(scope="module")
def scripts(tmp_path_factory):
    swift = shutil.which("swiftc")
    if swift is None or not NODE.is_file():
        pytest.skip("Local Swift compiler and bundled Node required")
    directory = tmp_path_factory.mktemp("native-scene-script")
    main = directory / "main.swift"
    main.write_text('''import Foundation
let generation = "00000000-0000-4000-8000-000000000001"
let scripts = ["active": WorkspaceSceneSignalState.script(generation: generation, active: true)!,
               "inactive": WorkspaceSceneSignalState.script(generation: generation, active: false)!]
let data = try JSONSerialization.data(withJSONObject: scripts, options: [.sortedKeys])
print(String(data: data, encoding: .utf8)!)
''')
    executable = directory / "scene-script"
    result = subprocess.run([swift, "-module-cache-path", str(directory / "module-cache"),
        str(NATIVE / "WorkspaceSceneSignalState.swift"), str(main), "-o", str(executable)],
        capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stderr
    result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=10, check=True)
    return json.loads(result.stdout)


def delivered(script, *, generation=GENERATION, frame="main", protocol="capacitor:", host="localhost", port=""):
    program = '''import vm from "node:vm";
const input = JSON.parse(process.argv[1]), events = [];
const window = {location: input.location, __cosmasWorkspaceGeneration: input.generation,
                dispatchEvent: event => events.push({type:event.type,detail:event.detail})};
window.top = input.frame === "main" ? window : {};
class CustomEvent {constructor(type, options) {this.type=type;this.detail=options.detail;}}
vm.runInNewContext(input.script, {window,CustomEvent});
process.stdout.write(JSON.stringify(events));
'''
    result = subprocess.run([str(NODE), "--input-type=module", "-e", program,
        json.dumps({"script": script, "generation": generation, "frame": frame,
                   "location": {"protocol": protocol, "hostname": host, "port": port}})],
        capture_output=True, text=True, timeout=10, check=True)
    return json.loads(result.stdout)


@pytest.mark.parametrize("name,active", [("active", True), ("inactive", False)])
def test_current_main_document_gets_only_closed_scene_hint(scripts, name, active):
    assert delivered(scripts[name]) == [{"type": "cosmas:native-scene-state",
        "detail": {"generation": GENERATION, "active": active}}]


@pytest.mark.parametrize("changes", [
    {"generation": "00000000-0000-4000-8000-000000000002"}, {"generation": None},
    {"frame": "child"}, {"protocol": "https:"}, {"host": "other.localhost"}, {"port": "18765"},
])
def test_queued_hint_withholds_replaced_or_untrusted_document(scripts, changes):
    assert delivered(scripts["active"], **changes) == []


def test_native_delivery_is_current_view_and_scene_scoped_without_auth_or_capture_commands():
    bridge = (NATIVE / "CosmasBridgeViewController.swift").read_text()
    method = bridge.split("func notifySceneState", 1)[1].split("func quarantine", 1)[0]
    for boundary in ("!quarantined", "startedNavigation", "generation == workspaceGeneration",
                     "webView.window?.windowScene", 'url.scheme == "capacitor"', 'url.host == "localhost"',
                     "scene.activationState == .foregroundActive", "in: .page"):
        assert boundary in method
    assert "authPlugin" not in method and "capturePlugin" not in method
    assert "stopForRendererLoss" not in method and "fetch" not in method
    controller = (NATIVE / "CosmasWorkspaceViewController.swift").read_text()
    assert controller.count("self.workspace === next") == 2
    assert controller.index("sceneSignal?.close()", controller.index("private func showFailure")) < controller.index(
        "workspace?.quarantine()", controller.index("private func showFailure"))
    assert "recovery.phase == .active" in controller.split("private func dispatchSceneSignal", 1)[1]


def test_scene_policy_is_in_generated_app_and_swift_test_target():
    composer = (ROOT / "scripts/prepare-apple-synthetic.py").read_text()
    source_inventory = composer.split("RECOVERY_SOURCES =", 1)[1].split("def digest", 1)[0]
    assert '"WorkspaceSceneSignalState.swift"' in source_inventory
    package = (NATIVE / "Package.swift").read_text()
    assert 'sources: ["WorkspaceRecoveryState.swift", "WorkspaceSceneSignalState.swift"]' in package
    scene = (NATIVE / "SceneDelegate.swift").read_text()
    assert "sceneDidBecomeActive" in scene and "setSceneActive(true)" in scene
    assert "sceneWillResignActive" in scene and "setSceneActive(false)" in scene


def test_composer_includes_scene_policy_in_exact_synthetic_archive(tmp_path):
    spec = importlib.util.spec_from_file_location("scene_signal_composer", ROOT / "scripts/prepare-apple-synthetic.py")
    assert spec is not None and spec.loader is not None
    composer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(composer)
    output = tmp_path / "archive"
    app = output / "apps/capture/ios/App/App"
    (app / "Base.lproj").mkdir(parents=True)
    project = app.parent / "App.xcodeproj/project.pbxproj"
    project.parent.mkdir()
    project.write_text('''/* End PBXBuildFile section */
/* End PBXFileReference section */
\t\t\t\t9582B6822FE993A50072D4E8 /* SceneDelegate.swift */,
\t\t\t\t9582B6832FE993A70072D4E8 /* SceneDelegate.swift in Sources */,
''')
    scene = app / "SceneDelegate.swift"
    scene.write_text("// invented unfinalized source archive\n")
    storyboard = app / "Base.lproj/Main.storyboard"
    storyboard.write_text('customClass="CAPBridgeViewController" customModule="Capacitor"')
    original = [scene, storyboard, project]
    # This test supplies invented pinned inputs; existing composition test keeps
    # the real historical archive/hash contract separate when it is available.
    composer.__dict__["RECOVERY_INPUTS"] = {
        str(path.relative_to(output)): hashlib.sha256(path.read_bytes()).hexdigest() for path in original}
    canary = output / "encrypted-queue.canary"
    canary.write_bytes(b"invented ciphertext retained")
    manifest = composer.include_recovery_ui(output)
    for name in composer.RECOVERY_SOURCES:
        assert (app / name).read_bytes() == (NATIVE / name).read_bytes()
        assert project.read_text().count(f"/* {name} in Sources */") == 2
    assert str((app / "WorkspaceSceneSignalState.swift").relative_to(output)) in manifest["files"]
    assert canary.read_bytes() == b"invented ciphertext retained"
    before = {str(path.relative_to(output)): path.read_bytes() for path in output.rglob("*") if path.is_file()}
    with pytest.raises(ValueError, match="source base changed"):
        composer.include_recovery_ui(output)
    assert before == {str(path.relative_to(output)): path.read_bytes() for path in output.rglob("*") if path.is_file()}
