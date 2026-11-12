"""One-path Mac practice-helper package: refuse rules and fixed artifact layout."""

from __future__ import annotations

import base64
import importlib.util
import json
import plistlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "compose_mac_practice_helper", ROOT / "scripts/compose-mac-practice-helper.py")
MODULE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(MODULE)


def production_infos(path: Path) -> Path:
    host = "clerk.cosmas.ai"
    path.write_text(json.dumps({
        "enabled": True,
        "accountOrigin": "https://enrollment-api.cosmas.ai",
        "realm": {
            "publishableKey": "pk_live_" + base64.b64encode((host + "$").encode()).decode(),
            "frontendOrigin": "https://" + host,
            "audience": "cosmabot-practice-api",
            "profile": "operational-beta-v1",
            "keychainNamespace": "c" * 64,
        },
        "apiOrigins": [],
        "registeredPracticeOrigins": "practice-uuid-production-v1",
    }))
    return path


def staging_infos(path: Path) -> Path:
    host = "invented.clerk.accounts.dev"
    path.write_text(json.dumps({
        "enabled": True,
        "accountOrigin": "https://enrollment-api.staging.cosmas.ai",
        "realm": {
            "publishableKey": "pk_test_" + base64.b64encode((host + "$").encode()).decode(),
            "frontendOrigin": "https://" + host,
            "audience": "",
            "profile": "operational-staging-v1",
            "keychainNamespace": "d" * 64,
        },
        "apiOrigins": ["https://api.example.invalid"],
        "registeredPracticeOrigins": "exact",
    }))
    return path


def test_production_defaults_pin_enrollment_api_and_authorized_beta(tmp_path):
    infos = MODULE.load_infos(production_infos(tmp_path / "native-practice.json"))
    origin, mode = MODULE.derive_defaults(infos, hosted_api_origin=None, data_mode=None)
    assert origin == "https://enrollment-api.cosmas.ai"
    assert mode == "authorized_beta"


def test_production_refuses_synthetic_data_mode(tmp_path):
    infos = MODULE.load_infos(production_infos(tmp_path / "native-practice.json"))
    with pytest.raises(ValueError, match="authorized_beta"):
        MODULE.derive_defaults(infos, hosted_api_origin=None, data_mode="synthetic")


def test_production_refuses_fake_practice_host(tmp_path):
    infos = MODULE.load_infos(production_infos(tmp_path / "native-practice.json"))
    with pytest.raises(ValueError, match="fake/local"):
        MODULE.refuse_fake_with_production(infos, True)


def test_staging_refuses_production_enrollment_origin(tmp_path):
    infos = MODULE.load_infos(staging_infos(tmp_path / "staging.json"))
    with pytest.raises(ValueError, match="cannot target production"):
        MODULE.derive_defaults(
            infos, hosted_api_origin="https://enrollment-api.cosmas.ai", data_mode="synthetic")


def test_prepare_argv_includes_infos_and_omits_fake_for_production(tmp_path):
    argv = MODULE.prepare_argv(
        repository=ROOT,
        web_dist=tmp_path / "web",
        composed_output=tmp_path / "composed",
        helper=tmp_path / "CosmasAuth.app",
        identity=tmp_path / "desktop-identity.json",
        practice_config=tmp_path / "native-practice.json",
        hosted_api_origin="https://enrollment-api.cosmas.ai",
        data_mode="authorized_beta",
        enable_fake_practice_host=False,
    )
    assert "--native-practice-config" in argv
    assert "--data-mode" in argv and "authorized_beta" in argv
    assert "--native-practice-connection" not in argv
    assert "--installation-profile" in argv and "beta" in argv


def test_write_manifest_names_one_artifact_and_signup_path(tmp_path):
    infos = MODULE.load_infos(production_infos(tmp_path / "native-practice.json"))
    helper = tmp_path / "CosmasAuth.app"
    composed = tmp_path / "composed-desktop"
    helper.mkdir()
    composed.mkdir()
    manifest = MODULE.write_manifest(
        tmp_path / MODULE.MANIFEST_NAME,
        infos=infos,
        hosted_api_origin="https://enrollment-api.cosmas.ai",
        data_mode="authorized_beta",
        helper=helper,
        composed=composed,
        helper_embedded=None,
        source_commit="a" * 40,
    )
    assert manifest["purpose"] == "mac-practice-helper-one-path"
    assert manifest["artifacts"]["manifest"] == MODULE.MANIFEST_NAME
    assert manifest["fail_closed_without_signed_helper"] is True
    assert manifest["signed"] is False
    assert "Open Chief" in " ".join(manifest["signup_to_open_chief"])
    guide = tmp_path / MODULE.GUIDE_NAME
    MODULE.write_guide(guide, production=True, account_origin=infos["accountOrigin"])
    text = guide.read_text()
    assert "package-manifest.json" in text
    assert "Open Chief" in text


def _disabled_helper(path: Path) -> Path:
    contents = path / "Contents"
    (contents / "MacOS").mkdir(parents=True)
    (contents / "MacOS" / "CosmasDesktopAuth").write_bytes(b"invented-helper-binary")
    (contents / "Info.plist").write_bytes(plistlib.dumps({
        "CFBundleExecutable": "CosmasDesktopAuth",
        "CFBundleIdentifier": "com.cosmasos.beta.desktop.auth",
        "CosmasNativeAuth": {"enabled": True},
    }))
    return path


def test_compose_refuses_production_plus_fake_before_output(tmp_path, monkeypatch, capsys):
    practice = production_infos(tmp_path / "native-practice.json")
    identity = tmp_path / "desktop-identity.json"
    identity.write_text("{}")
    web = tmp_path / "web"
    web.mkdir()
    helper = _disabled_helper(tmp_path / "helper.app")
    output = tmp_path / "never-created"
    monkeypatch.setattr(sys, "argv", [
        "compose-mac-practice-helper.py",
        "--native-practice-config", str(practice),
        "--native-identity-config", str(identity),
        "--web-dist", str(web),
        "--native-auth-helper", str(helper),
        "--output", str(output),
        "--enable-fake-practice-host",
    ])
    with pytest.raises(SystemExit):
        MODULE.main()
    assert "fake/local" in capsys.readouterr().err
    assert not output.exists()


def test_compose_writes_fixed_layout_when_prepare_succeeds(tmp_path, monkeypatch):
    practice = production_infos(tmp_path / "native-practice.json")
    identity = tmp_path / "desktop-identity.json"
    identity.write_text(json.dumps({
        "version": 1, "profile": "operational-beta-v1", "client": "desktop",
        "apiOrigin": "https://enrollment-api.cosmas.ai",
        "frontendOrigin": "https://clerk.cosmas.ai",
        "publishableKey": "pk_live_" + base64.b64encode(b"clerk.cosmas.ai$").decode(),
        "organizationId": "org_fixture", "audience": "cosmabot-practice-api",
    }))
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<html>Invented</html>")
    helper = _disabled_helper(tmp_path / "helper.app")
    output = tmp_path / "package"

    def fake_run(argv, check=True):
        # First child may be helper copy only via shutil; prepare-desktop-synthetic is subprocess.
        if "prepare-desktop-synthetic.py" in " ".join(str(part) for part in argv):
            composed = Path(argv[argv.index("--output") + 1])
            app = composed / "app"
            app.mkdir(parents=True)
            (app / "synthetic-build.json").write_text(json.dumps({
                "nativePracticeConnectionEnabled": True,
                "dataMode": "authorized_beta",
            }))
            return type("Completed", (), {"returncode": 0})()
        raise AssertionError(f"unexpected subprocess: {argv}")

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
    monkeypatch.setattr(MODULE, "git_commit", lambda _repo: "b" * 40)
    code = MODULE.main([
        "--native-practice-config", str(practice),
        "--native-identity-config", str(identity),
        "--web-dist", str(web),
        "--native-auth-helper", str(helper),
        "--output", str(output),
    ])
    assert code == 0
    manifest = json.loads((output / MODULE.MANIFEST_NAME).read_text())
    assert manifest["environment"] == "production"
    assert (output / MODULE.HELPER_NAME / "Contents/Info.plist").is_file()
    assert (output / MODULE.COMPOSED_NAME / "app" / "synthetic-build.json").is_file()
    assert (output / MODULE.GUIDE_NAME).is_file()
    assert not (output / ".incomplete").exists()
