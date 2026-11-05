"""Run the real owned copy path; no external checkout, SDK or app is accessed."""
import hashlib
import importlib.util
import json
import plistlib
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("owned_desktop_composer", ROOT / "scripts/prepare-desktop-synthetic.py")
composer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(composer)


def scope(monkeypatch, web, output):
    monkeypatch.setattr(sys, "argv", ["prepare-desktop-synthetic.py", "--web-dist", str(web), "--output", str(output)])
    # Test-only Git identity, never a release qualification or legacy template.
    monkeypatch.setattr(composer._source_module, "provenance", lambda *_args, **_kwargs: {
        "version": 1, "commit": "1" * 40, "tree": "2" * 40, "dirty": False,
    })


def test_real_composition_needs_no_external_checkout_or_typescript(tmp_path, monkeypatch):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<html><body>Invented local renderer</body></html>")
    (web / "theme.css").write_text("body { color: black; }")
    output = tmp_path / "composed"
    scope(monkeypatch, web, output)

    def external_process_forbidden(*_args, **_kwargs):
        raise AssertionError("This local composition must not extract or transpile an external source")

    monkeypatch.setattr(composer.subprocess, "check_output", external_process_forbidden)
    monkeypatch.setattr(composer.subprocess, "run", external_process_forbidden)
    composer.main()
    app = output / "app"
    manifest, sources = composer.load_boundary_sources(ROOT)
    for name in ("scribe-security.mjs", "scribe-diagnostics.mjs"):
        assert (app / name).read_bytes() == sources[name]
    assets = (app / "static-assets.mjs").read_text()
    assert '"/theme.css"' in assets
    assert "resolveStaticAsset" in assets
    assert (app / "main.mjs").read_bytes() == (ROOT / "clients/desktop/main.mjs").read_bytes()
    receipt = json.loads((output / "composition.json").read_text())
    assert receipt["source_ref"] == "cosmabot-owned-desktop-boundary-v1"
    assert receipt["boundary_recovery_provenance"] == manifest
    assert receipt["source_sha256"] == {
        "clients/desktop/" + name: hashlib.sha256(data).hexdigest() for name, data in sources.items()
    }


def test_installation_storage_stays_outside_owned_source(tmp_path, monkeypatch):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<html>Invented renderer</html>")
    output = tmp_path / "never-created"
    scope(monkeypatch, web, output)
    monkeypatch.setattr(sys, "argv", [*sys.argv, "--native-auth-helper", str(tmp_path / "unused.app"),
                                      "--installation-profile", "w1", "--installation-root", str(ROOT)])
    with pytest.raises(SystemExit):
        composer.main()
    assert not output.exists()


def test_native_practice_connection_requires_authenticated_helper(tmp_path, monkeypatch, capsys):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<html>Invented renderer</html>")
    output = tmp_path / "never-created"
    scope(monkeypatch, web, output)
    monkeypatch.setattr(sys, "argv", [*sys.argv, "--native-practice-connection"])
    with pytest.raises(SystemExit):
        composer.main()
    assert "Native practice connection requires the authenticated desktop composition" in capsys.readouterr().err
    assert not output.exists()


def _synthetic_disabled_helper(path: Path) -> Path:
    """Minimal disabled synthetic auth helper accepted by prepare-desktop-synthetic."""
    contents = path / "Contents"
    (contents / "MacOS").mkdir(parents=True)
    (contents / "MacOS" / "CosmasDesktopAuth").write_bytes(b"invented-helper-binary")
    (contents / "Info.plist").write_bytes(plistlib.dumps({
        "CFBundleExecutable": "CosmasDesktopAuth",
        "CFBundleIdentifier": "com.cosmasos.synthetic.desktop.auth.w7",
        "CosmasNativeAuth": {"enabled": False},
    }))
    return path


def test_native_practice_connection_opt_in_composes_practice_host(tmp_path, monkeypatch):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<html><body>Invented local renderer</body></html>")
    helper = _synthetic_disabled_helper(tmp_path / "CosmasDesktopAuth.app")
    output = tmp_path / "composed-practice"
    scope(monkeypatch, web, output)
    monkeypatch.setattr(sys, "argv", [
        *sys.argv,
        "--native-auth-helper", str(helper),
        "--native-practice-connection",
    ])
    composer.main()
    build = json.loads((output / "app" / "synthetic-build.json").read_text())
    assert build["nativeAuthEnabled"] is True
    assert build["nativePracticeConnectionEnabled"] is True
    for name in (
        "practice-session.mjs", "practice-ipc.mjs", "practice-fake-wire.mjs",
        "practice-infos-config.mjs", "practice-https-wire.mjs",
    ):
        assert (output / "app" / name).is_file()
    assert (output / "app" / "main.mjs").read_bytes() == (
        ROOT / "clients/desktop/main-authenticated.mjs"
    ).read_bytes()


@pytest.mark.parametrize("damage", ["changed", "missing", "linked", "extra-manifest-file"])
def test_unreviewed_boundary_is_rejected_before_output(tmp_path, monkeypatch, damage):
    owned = tmp_path / "owned"
    target = owned / "clients/desktop"
    target.mkdir(parents=True)
    (target / "release").mkdir()
    for name in composer.BOUNDARY_FILES:
        shutil.copyfile(ROOT / "clients/desktop" / name, target / name)
    source_manifest = ROOT / "clients/desktop/release/owned-boundary.json"
    manifest = target / "release/owned-boundary.json"
    shutil.copyfile(source_manifest, manifest)
    file = target / "scribe-security.mjs"
    if damage == "changed":
        file.write_bytes(file.read_bytes() + b"\n// unreviewed change\n")
    elif damage == "missing":
        file.unlink()
    elif damage == "linked":
        file.unlink()
        file.symlink_to(ROOT / "clients/desktop/scribe-security.mjs")
    else:
        receipt = json.loads(manifest.read_text())
        receipt["files"]["external.mjs"] = receipt["files"]["scribe-security.mjs"]
        manifest.write_text(json.dumps(receipt))
    original = composer.load_boundary_sources
    monkeypatch.setattr(composer, "load_boundary_sources", lambda _root: original(owned))
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<html>Invented renderer</html>")
    output = tmp_path / "never-created"
    scope(monkeypatch, web, output)
    with pytest.raises(ValueError, match="Owned desktop boundary"):
        composer.main()
    assert not output.exists()
