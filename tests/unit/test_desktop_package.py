"""Packaging must advertise the platform requirements of its native helper."""
import json
import plistlib
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/package-desktop-synthetic.py"


@pytest.mark.parametrize("native,helper_minimum,expected", [
    (False, None, "12.0"), (True, "14.0", "14.0"), (True, "15.2", "15.2"),
])
def test_packaged_minimum_covers_shell_and_native_sdk(tmp_path, native, helper_minimum, expected):
    runtime, app, output = inputs(tmp_path, native, helper_minimum)
    result = subprocess.run([sys.executable, str(SCRIPT), "--electron-app", str(runtime),
        "--composed-app", str(app), "--output", str(output), "--verification-variant", "w16"], capture_output=True)
    assert result.returncode == 0, result.stderr.decode()
    info = plistlib.loads((output / "Contents/Info.plist").read_bytes())
    assert info["LSMinimumSystemVersion"] == expected
    assert info["CFBundleIdentifier"] == "com.cosmasos.synthetic.desktop.w16"
    assert info["CFBundleShortVersionString"] == "0.1.0"
    assert info["CFBundleVersion"] == "1"
    assert info["CosmasElectronVersion"] == "43.4.1"


def inputs(tmp_path, native, helper_minimum):
    runtime, app, output = tmp_path / "Electron.app", tmp_path / "composed", tmp_path / "Output.app"
    (runtime / "Contents").mkdir(parents=True)
    (runtime / "Contents/Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": "com.github.Electron",
        "CFBundleVersion": "43.4.1", "LSMinimumSystemVersion": "12.0"}))
    app.mkdir()
    (app / "main.mjs").write_text("// Package fixture; never executed.\n")
    (app / "package.json").write_text(json.dumps({"version": "0.1.0"}))
    (app / "synthetic-build.json").write_text(json.dumps({"mode": "local-synthetic-authenticated" if native else "local-synthetic"}))
    if native:
        helper = app / "native-auth/CosmasDesktopAuth.app/Contents"
        helper.mkdir(parents=True)
        (helper / "Info.plist").write_bytes(plistlib.dumps({"LSMinimumSystemVersion": helper_minimum,
            "CFBundleIdentifier": "com.cosmasos.synthetic.desktop.auth.w16"}))
    return runtime, app, output


def test_invalid_helper_minimum_cannot_produce_a_launchable_package(tmp_path):
    runtime, app, output = inputs(tmp_path, True, "unknown")
    result = subprocess.run([sys.executable, str(SCRIPT), "--electron-app", str(runtime),
        "--composed-app", str(app), "--output", str(output)], capture_output=True)
    assert result.returncode != 0 and not output.exists()


def test_update_preserves_identity_and_uses_product_versions(tmp_path):
    runtime, app, output = inputs(tmp_path, True, "14.0")
    config = json.loads((app / "synthetic-build.json").read_text())
    config.update(appVersion="0.2.0", buildNumber="19", installation={
        "profile": "w19", "bundleIdentifier": "com.cosmasos.synthetic.desktop.w19",
        "authHelperBundleIdentifier": "com.cosmasos.synthetic.desktop.auth.w16"})
    (app / "synthetic-build.json").write_text(json.dumps(config))
    (app / "package.json").write_text(json.dumps({"version": "0.2.0"}))
    result = subprocess.run([sys.executable, str(SCRIPT), "--electron-app", str(runtime),
        "--composed-app", str(app), "--output", str(output), "--verification-variant", "w19"], capture_output=True)
    assert result.returncode == 0, result.stderr.decode()
    info = plistlib.loads((output / "Contents/Info.plist").read_bytes())
    assert (info["CFBundleIdentifier"], info["CFBundleShortVersionString"], info["CFBundleVersion"]) == (
        "com.cosmasos.synthetic.desktop.w19", "0.2.0", "19")


@pytest.mark.parametrize("change", [
    {"appVersion": "43.4.1"}, {"buildNumber": "0"}, {"buildNumber": "10000"},
    {"buildNumber": "1.2.3.4"}, {"appVersion": "0.1.0-beta"},
    {"installation": {"profile": "w13", "bundleIdentifier": "com.cosmasos.synthetic.desktop.w13"}},
    {"installation": {"profile": "w19", "bundleIdentifier": "com.cosmasos.synthetic.desktop.w19",
                      "authHelperBundleIdentifier": "com.cosmasos.synthetic.desktop.auth.w13"}},
])
def test_inconsistent_version_or_profile_refuses_before_copy(tmp_path, change):
    runtime, app, output = inputs(tmp_path, True, "14.0")
    config_path = app / "synthetic-build.json"
    config = json.loads(config_path.read_text())
    config.update(change)
    config_path.write_text(json.dumps(config))
    result = subprocess.run([sys.executable, str(SCRIPT), "--electron-app", str(runtime),
        "--composed-app", str(app), "--output", str(output), "--verification-variant", "w19"], capture_output=True)
    assert result.returncode != 0 and not output.exists()
