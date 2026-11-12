"""Shipped operational-beta-v1 identity (CTO DECISION_LOG 12 Nov 2026 10:12 ET).

TestFlight 1107/1110/1120 and synthetic Mac 1120 use:
operational-beta-v1 + clerk.staging.cosmas.ai + api.staging.cosmas.ai +
audience cosmas-os-beta-api. Synthetic/invented keys only.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SHIPPED_CLERK = "clerk.staging.cosmas.ai"
SHIPPED_API = "https://api.staging.cosmas.ai"
SHIPPED_FRONTEND = "https://clerk.staging.cosmas.ai"
SHIPPED_AUDIENCE = "cosmas-os-beta-api"
SHIPPED_ORG = "org_invented_beta"
BETA_CLERK = "clerk.beta.cosmas.ai"
COSMAS_CLERK = "clerk.cosmas.ai"


def _live_key(host: str) -> str:
    return "pk_live_" + base64.b64encode(f"{host}$".encode()).decode()


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


IDENTITY = _load(ROOT / "scripts/native_identity_build.py", "native_identity_build")
APPLE = _load(ROOT / "scripts/prepare-apple-synthetic.py", "prepare_apple_synthetic")
AUTH = _load(ROOT / "scripts/native_iphone_auth_profile.py", "native_iphone_auth_profile")


def shipped_identity(client: str) -> dict:
    return {
        "version": 1,
        "profile": "operational-beta-v1",
        "client": client,
        "apiOrigin": SHIPPED_API,
        "frontendOrigin": SHIPPED_FRONTEND,
        "publishableKey": _live_key(SHIPPED_CLERK),
        "organizationId": SHIPPED_ORG,
        "audience": SHIPPED_AUDIENCE,
    }


def _write(path: Path, document: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document))
    return path


def test_python_operational_beta_hosts_match_js_dual_set():
    assert AUTH.OPERATIONAL_BETA_CLERK_HOSTS == frozenset({
        "clerk.cosmas.ai", "clerk.staging.cosmas.ai",
    })
    assert AUTH.SWIFT_OPERATIONAL_BETA_CLERK_HOST == "clerk.cosmas.ai"
    assert BETA_CLERK not in AUTH.OPERATIONAL_BETA_CLERK_HOSTS


def test_shipped_identity_validates_for_desktop_and_apple(tmp_path):
    for client in ("desktop", "apple"):
        document = shipped_identity(client)
        loaded = IDENTITY.validate(document, client, SHIPPED_API, installation_profile=None)
        assert loaded["identity"]["profile"] == "operational-beta-v1"
        assert loaded["identity"]["frontendOrigin"] == SHIPPED_FRONTEND
        assert loaded["identity"]["apiOrigin"] == SHIPPED_API
        assert loaded["identity"]["audience"] == SHIPPED_AUDIENCE
        path = _write(tmp_path / f"{client}.json", document)
        assert IDENTITY.load(path, client, SHIPPED_API)["identity"]["frontendOrigin"] == (
            SHIPPED_FRONTEND)


def test_hosts_outside_beta_set_are_refused_including_clerk_beta():
    base = shipped_identity("apple")
    for host, api in (
        (BETA_CLERK, "https://api.beta.cosmas.ai"),
        ("clerk.example.invalid", "https://api.example.invalid"),
        ("clerk.cosmaneura.com", "https://api.example.invalid"),
        ("preview.clerk.staging.cosmas.ai", "https://api.staging.cosmas.ai"),
    ):
        bad = {
            **base,
            "frontendOrigin": f"https://{host}",
            "publishableKey": _live_key(host),
            "apiOrigin": api,
        }
        with pytest.raises(ValueError, match="Native identity must match"):
            IDENTITY.validate(bad, "apple", api, installation_profile=None)


def test_cosmas_and_staging_hosts_both_accepted_on_beta():
    for host, api in (
        (COSMAS_CLERK, "https://api.example.invalid"),
        (SHIPPED_CLERK, SHIPPED_API),
    ):
        document = {
            **shipped_identity("desktop"),
            "frontendOrigin": f"https://{host}",
            "publishableKey": _live_key(host),
            "apiOrigin": api,
        }
        loaded = IDENTITY.validate(document, "desktop", api)
        assert loaded["identity"]["frontendOrigin"] == f"https://{host}"


def test_simulator_authorize_accepts_shipped_identity():
    APPLE.authorize_simulator_staging_native_auth(
        {"identity": shipped_identity("apple")}, "synthetic", hosted_workspace=True)


def test_simulator_authorize_refuses_clerk_beta_on_operational_beta():
    with pytest.raises(ValueError, match="clerk.staging.cosmas.ai"):
        APPLE.authorize_simulator_staging_native_auth(
            {"identity": {
                **shipped_identity("apple"),
                "frontendOrigin": f"https://{BETA_CLERK}",
                "publishableKey": _live_key(BETA_CLERK),
                "apiOrigin": "https://api.beta.cosmas.ai",
            }},
            "synthetic", hosted_workspace=True)


def _hosted_web_and_shipped_identity(root: Path) -> tuple[Path, Path, dict]:
    """Compose Apple web inputs (staging sample), then stamp shipped beta identity."""
    candidate = {
        "version": 1,
        "profile": "operational-staging-v1",
        "client": "desktop",
        "apiOrigin": SHIPPED_API,
        "frontendOrigin": SHIPPED_FRONTEND,
        "publishableKey": _live_key(SHIPPED_CLERK),
        "organizationId": SHIPPED_ORG,
        "audience": SHIPPED_AUDIENCE,
    }
    result = subprocess.run(
        [
            "node", "--input-type=module", "-e",
            "const identity=await import(process.argv[1]);"
            "const profile=await import(process.argv[2]);"
            "const files=identity.workspaceIdentityInputs(JSON.parse(process.argv[3]),{"
            "webOrigin:'https://app.example.invalid',coreWebOrigin:'https://core.example.invalid',"
            "captureUploadOrigins:['https://uploads.example.invalid'],dataMode:'synthetic',"
            "nativeFeatureProfile:process.argv[4]});"
            "const manifest=profile.resolveBetaFeatureProfile(files['apple-build-env.json']).manifest;"
            "process.stdout.write(JSON.stringify({identity:files['apple-identity.json'],manifest}));",
            (ROOT / "scripts/prepare-workspace-identity.mjs").as_uri(),
            (ROOT / "clients/shared/beta-feature-profile.mjs").as_uri(),
            json.dumps(candidate), "first-owner-staging-v1",
        ],
        check=True, capture_output=True, text=True, cwd=ROOT,
    )
    values = json.loads(result.stdout)
    web = root / "web"
    web.mkdir()
    (web / "index.html").write_text("<html><head></head><body></body></html>")
    manifest = values["manifest"]
    (web / "cosmas-beta-features.json").write_text(json.dumps(manifest))
    (web / "cosmas-workspace-build.json").write_text(json.dumps({
        "version": 1,
        **{key: manifest[key] for key in ("client", "dataMode", "apiOrigin", "apiBase", "pageOrigin")},
    }))
    path = _write(root / "apple-identity.json", shipped_identity("apple"))
    return web, path, manifest


def test_simulator_prepare_accepts_shipped_identity_until_archive(tmp_path):
    """Simulator prepare: identity load + authorize pass; archive is the next gate."""
    web, identity_path, manifest = _hosted_web_and_shipped_identity(tmp_path)
    source = tmp_path / "source"
    source.mkdir()
    output = tmp_path / "output"
    with pytest.raises(subprocess.CalledProcessError) as caught:
        APPLE.prepare(
            source, web, output,
            hosted_workspace=True, workspace_api_origin=SHIPPED_API,
            capture_upload_origins=tuple(manifest["captureUploadOrigins"]),
            cosmaneura_web_origin=manifest["coreWebOrigin"],
            native_auth_clerk_archive=tmp_path / "clerk.tar.gz",
            native_identity_config=identity_path, data_mode="synthetic",
            allow_simulator_staging_native_auth=True)
    assert caught.value.cmd[1] == "archive"
    assert not output.exists()


def test_device_prepare_accepts_shipped_identity_past_load(tmp_path):
    """Device prepare: shipped identity loads; missing web fails later (not identity)."""
    identity_path = _write(tmp_path / "device-identity.json", shipped_identity("apple"))
    device = tmp_path / "device"
    with pytest.raises(FileNotFoundError):
        APPLE.prepare(
            tmp_path / "source", tmp_path / "missing-web", device,
            hosted_workspace=True, workspace_api_origin=SHIPPED_API,
            native_auth_clerk_archive=tmp_path / "clerk.tar.gz",
            native_identity_config=identity_path, data_mode="synthetic")
    assert not device.exists()


def test_desktop_package_accepts_shipped_identity_validate():
    """Desktop packaging identity gate accepts the exact shipped public identity."""
    document = shipped_identity("desktop")
    loaded = IDENTITY.validate(document, "desktop", SHIPPED_API, installation_profile="beta")
    assert loaded["identity"]["frontendOrigin"] == SHIPPED_FRONTEND
    assert loaded["auth"]["frontendOrigin"] == SHIPPED_FRONTEND
    # package-desktop-synthetic.py uses the same validate gate for operational packages.
    source = (ROOT / "scripts/package-desktop-synthetic.py").read_text(encoding="utf-8")
    assert "_identity.validate(" in source
    assert "installation_profile=installation_profile" in source


def test_desktop_release_profile_accepts_shipped_identity():
    result = subprocess.run(
        [
            "node", "--input-type=module", "-e",
            "const release=await import(process.argv[1]);"
            "const features=await import(process.argv[2]);"
            "const identity=JSON.parse(process.argv[3]);"
            "const profile=features.resolveBetaFeatureProfile({"
            "VITE_WORKSPACE_FEATURE_PROFILE:'first-owner-staging-v1',"
            "VITE_WORKSPACE_HOSTED_CLIENT:'desktop',"
            "VITE_WORKSPACE_DATA_MODE:'synthetic',"
            "VITE_WORKSPACE_HOSTED_API_ORIGIN:identity.apiOrigin,"
            "VITE_API_BASE:'app://cosmas/api',"
            "VITE_WORKSPACE_WEB_ORIGIN:'',"
            "VITE_COSMANEURA_WEB_ORIGIN:'',"
            "VITE_CAPTURE_UPLOAD_ORIGINS:'',"
            "VITE_WORKSPACE_CAPTURE_MODE:'disabled'}).manifest;"
            "const info={CFBundleIdentifier:'com.cosmasos.beta.desktop',"
            "CFBundleShortVersionString:'0.1.0',CFBundleVersion:'1120'};"
            "const config={nativeIdentity:identity,mode:'hosted-beta-authenticated',"
            "dataMode:'synthetic',apiOrigin:identity.apiOrigin,"
            "appVersion:info.CFBundleShortVersionString,buildNumber:info.CFBundleVersion,"
            "installation:{bundleIdentifier:info.CFBundleIdentifier},"
            "nativeCaptureEnabled:false};"
            "const out=release.validateOperationalReleaseProfile(config,profile,info);"
            "process.stdout.write(JSON.stringify(out));",
            (ROOT / "scripts/package-desktop-release.mjs").as_uri(),
            (ROOT / "clients/shared/beta-feature-profile.mjs").as_uri(),
            json.dumps(shipped_identity("desktop")),
        ],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["frontendOrigin"] == SHIPPED_FRONTEND


def test_transition_fixture_source_is_staging_host():
    text = (ROOT / "scripts/transition-desktop-identity.test.mjs").read_text(encoding="utf-8")
    assert "clerk.staging.cosmas.ai" in text
    assert "sourceIdentity = identity('clerk.staging.cosmas.ai')" in text


def test_package_desktop_synthetic_source_refuses_production_identity():
    text = (ROOT / "scripts/package-desktop-synthetic.py").read_text(encoding="utf-8")
    assert "operational-production-v1" in text
    assert "refuse at package time" in text
