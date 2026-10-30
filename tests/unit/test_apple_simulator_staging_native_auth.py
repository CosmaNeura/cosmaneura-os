"""Staging-only native sign-in for the synthetic iOS simulator variant."""

import base64
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STAGING_HOST = "clerk.staging.cosmas.ai"
STAGING_ORIGIN = "https://clerk.staging.cosmas.ai"
STAGING_API = "https://api.staging.cosmas.ai"
STAGING_KEY = "pk_live_Y2xlcmsuc3RhZ2luZy5jb3NtYXMuYWkk"
ORGANIZATION = "org_invented_beta"
AUDIENCE = "cosmas-os-beta-api"
SCRIPT = ROOT / "scripts/prepare-apple-synthetic.py"


def composition():
    spec = importlib.util.spec_from_file_location("apple_simulator_staging_auth", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Apple composer is unavailable.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def live_key(host: str) -> str:
    return "pk_live_" + base64.b64encode(f"{host}$".encode()).decode()


def identity_document(api: str, frontend: str, key: str, profile: str = "operational-beta-v1") -> dict:
    return {
        "version": 1,
        "profile": profile,
        "client": "apple",
        "apiOrigin": api,
        "frontendOrigin": frontend,
        "publishableKey": key,
        "organizationId": ORGANIZATION,
        "audience": AUDIENCE,
    }


def write_identity(root: Path, document: dict) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / "identity.json"
    path.write_text(json.dumps(document))
    return path


def test_public_staging_key_decodes_to_the_allowlisted_host():
    script = composition()
    assert live_key(STAGING_HOST) == STAGING_KEY
    assert script.publishable_key_host(STAGING_KEY) == STAGING_HOST


def test_simulator_variant_callback_is_its_own_scheme_and_not_the_device_scheme():
    script = composition()
    sign_in = script.simulator_staging_sign_in("com.cosmasos.synthetic")
    assert sign_in["callback_url"] == "com.cosmasos.synthetic://callback"
    assert sign_in["callback_scheme"] == "com.cosmasos.synthetic"
    assert sign_in["CFBundleURLTypes"] == [{
        "CFBundleURLName": "com.cosmasos.synthetic",
        "CFBundleURLSchemes": ["com.cosmasos.synthetic"],
    }]
    variant = script.simulator_staging_sign_in("com.cosmasos.synthetic.w8m")
    assert variant["callback_url"] == "com.cosmasos.synthetic.w8m://callback"
    with pytest.raises(ValueError, match="synthetic simulator variant"):
        script.simulator_staging_sign_in("com.cosmasos.beta.ios")


def test_bundle_stays_synthetic_only_for_the_simulator_flag():
    script = composition()
    device = {"bundle": "com.cosmasos.beta.ios"}
    assert script.resolve_apple_bundle(device, None, operational=True, simulator_staging_auth=False) == (
        "com.cosmasos.beta.ios", "CosmaBot")
    assert script.resolve_apple_bundle(device, None, operational=True, simulator_staging_auth=True) == (
        "com.cosmasos.synthetic", "CosmasOS Synth")
    assert script.resolve_apple_bundle(device, "w8m", operational=True, simulator_staging_auth=True) == (
        "com.cosmasos.synthetic.w8m", "CosmasOS Synth W8M")


def test_gate_accepts_either_identity_profile_when_the_staging_allowlist_matches():
    script = composition()
    for profile in ("operational-beta-v1", "operational-staging-v1", "staging-clerk-v1"):
        script.authorize_simulator_staging_native_auth(
            {"identity": identity_document(STAGING_API, STAGING_ORIGIN, STAGING_KEY, profile)},
            "synthetic", hosted_workspace=True)


def test_gate_requires_both_the_frontend_host_and_the_decoded_key_host():
    script = composition()
    other = identity_document(STAGING_API, STAGING_ORIGIN, live_key("identity.example.invalid"))
    with pytest.raises(ValueError, match="clerk.staging.cosmas.ai"):
        script.authorize_simulator_staging_native_auth(
            {"identity": other}, "synthetic", hosted_workspace=True)
    swapped = identity_document(STAGING_API, "https://identity.example.invalid", STAGING_KEY)
    with pytest.raises(ValueError, match="clerk.staging.cosmas.ai"):
        script.authorize_simulator_staging_native_auth(
            {"identity": swapped}, "synthetic", hosted_workspace=True)


def test_simulator_runtime_profile_is_separate_from_device_sign_in():
    script = composition()
    source = (ROOT / "clients/apple/native-auth/Sources/CosmasNativeAuth/NativeClerkConfiguration.swift").read_text()
    assert f'case simulatorStaging = "{script.SIMULATOR_RUNTIME_PROFILE}"' in source
    settings = script.simulator_native_auth_settings({
        "auth": {
            "enabled": True, "profile": "operational-beta-v1", "publishableKey": STAGING_KEY,
            "frontendOrigin": STAGING_ORIGIN, "organizationId": ORGANIZATION, "audience": AUDIENCE,
        },
    })
    assert settings["profile"] == "simulator-staging-v1"
    assert settings["publishableKey"] == STAGING_KEY
    assert settings["frontendOrigin"] == STAGING_ORIGIN
    assert settings["audience"] == AUDIENCE
    with pytest.raises(ValueError, match="enabled native identity"):
        script.simulator_native_auth_settings({"auth": {"enabled": False, "profile": "operational-beta-v1"}})


def test_cli_exposes_the_simulator_staging_flag():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"], check=True, capture_output=True, text=True)
    assert "--allow-simulator-staging-native-auth" in result.stdout


@pytest.mark.parametrize(("api", "frontend", "key"), [
    (STAGING_API, "https://clerk.cosmaneura.com", live_key("clerk.cosmaneura.com")),
    (STAGING_API, "https://app.cosmaneura.com", live_key("app.cosmaneura.com")),
    ("https://api.cosmaneura.com", STAGING_ORIGIN, STAGING_KEY),
])
def test_production_hosts_are_refused(tmp_path, api, frontend, key):
    script = composition()
    output = tmp_path / "output"
    with pytest.raises(ValueError, match="refuses production hosts") as caught:
        script.prepare(
            tmp_path / "source", tmp_path / "web", output,
            hosted_workspace=True, workspace_api_origin=api,
            native_auth_clerk_archive=tmp_path / "clerk.tar.gz",
            native_identity_config=write_identity(tmp_path, identity_document(api, frontend, key)),
            data_mode="synthetic", allow_simulator_staging_native_auth=True,
            verification_variant="w8m", simulator_custody=True)
    assert "clerk.cosmaneura.com" in str(caught.value)
    assert "app.cosmaneura.com" in str(caught.value)
    assert "api.cosmaneura.com" in str(caught.value)
    assert not output.exists()


def test_host_outside_the_allowlist_is_refused(tmp_path):
    script = composition()
    output = tmp_path / "output"
    document = identity_document(
        "https://api.example.invalid", "https://identity.example.invalid", live_key("identity.example.invalid"))
    with pytest.raises(ValueError, match="clerk.staging.cosmas.ai") as caught:
        script.prepare(
            tmp_path / "source", tmp_path / "web", output,
            hosted_workspace=True, workspace_api_origin=document["apiOrigin"],
            native_auth_clerk_archive=tmp_path / "clerk.tar.gz",
            native_identity_config=write_identity(tmp_path, document),
            data_mode="synthetic", allow_simulator_staging_native_auth=True)
    assert "production hosts" not in str(caught.value)
    assert not output.exists()


def test_non_synthetic_data_mode_is_refused(tmp_path):
    script = composition()
    output = tmp_path / "output"
    with pytest.raises(ValueError, match="requires synthetic data mode"):
        script.prepare(
            tmp_path / "source", tmp_path / "web", output,
            hosted_workspace=True, workspace_api_origin=STAGING_API,
            native_auth_clerk_archive=tmp_path / "clerk.tar.gz",
            native_identity_config=write_identity(
                tmp_path, identity_document(STAGING_API, STAGING_ORIGIN, STAGING_KEY)),
            data_mode="authorized_beta", allow_simulator_staging_native_auth=True)
    assert not output.exists()


def test_flag_absent_keeps_the_device_custody_refusal(tmp_path):
    script = composition()
    output = tmp_path / "output"
    with pytest.raises(ValueError, match="without a synthetic variant or Simulator identity") as caught:
        script.prepare(
            tmp_path / "source", tmp_path / "web", output,
            verification_variant="w8m", simulator_custody=True,
            hosted_workspace=True, workspace_api_origin=STAGING_API,
            native_auth_clerk_archive=tmp_path / "clerk.tar.gz",
            native_identity_config=write_identity(
                tmp_path, identity_document(STAGING_API, STAGING_ORIGIN, STAGING_KEY)),
            data_mode="synthetic")
    assert str(caught.value) == script.DEVICE_CUSTODY_REFUSAL
    assert "clerk.staging.cosmas.ai" not in str(caught.value)
    assert not output.exists()


def test_default_device_and_synthetic_paths_are_unchanged_without_the_flag(tmp_path):
    script = composition()
    device = tmp_path / "device"
    with pytest.raises(FileNotFoundError):
        script.prepare(
            tmp_path / "source", tmp_path / "missing-web", device,
            hosted_workspace=True, workspace_api_origin="https://api.cosmaneura.com",
            native_auth_clerk_archive=tmp_path / "clerk.tar.gz",
            native_identity_config=write_identity(tmp_path, identity_document(
                "https://api.cosmaneura.com", "https://clerk.cosmaneura.com", live_key("clerk.cosmaneura.com"))),
            data_mode="synthetic")
    assert not device.exists()
    staging_device = tmp_path / "staging-device"
    with pytest.raises(FileNotFoundError):
        script.prepare(
            tmp_path / "source", tmp_path / "missing-web", staging_device,
            hosted_workspace=True, workspace_api_origin=STAGING_API,
            native_auth_clerk_archive=tmp_path / "clerk.tar.gz",
            native_identity_config=write_identity(tmp_path / "staging", identity_document(
                STAGING_API, STAGING_ORIGIN, STAGING_KEY)),
            data_mode="synthetic")
    assert not staging_device.exists()
    synthetic = tmp_path / "synthetic"
    with pytest.raises(ValueError, match="synthetic OS web bundle"):
        script.prepare(
            tmp_path / "source", tmp_path / "missing-web", synthetic,
            verification_variant="w8m", simulator_custody=True)
    assert not synthetic.exists()


def hosted_inputs(root: Path, feature_profile: str) -> tuple[Path, Path, dict]:
    """Build the Apple web manifest. Shared identity preparation also emits web,
    so the helper supplies a Core origin even when the Apple profile clears it."""
    candidate = identity_document(STAGING_API, STAGING_ORIGIN, STAGING_KEY)
    candidate["client"] = "desktop"
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
            json.dumps(candidate), feature_profile,
        ],
        check=True, capture_output=True, text=True,
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
    path = root / "apple-identity.json"
    path.write_text(json.dumps(values["identity"]))
    return web, path, manifest


def test_flag_allows_the_unsuffixed_simulator_variant_until_source_archive(tmp_path):
    script = composition()
    web, identity, manifest = hosted_inputs(tmp_path, "first-owner-staging-v1")
    source = tmp_path / "source"
    source.mkdir()
    output = tmp_path / "output"
    with pytest.raises(subprocess.CalledProcessError) as caught:
        script.prepare(
            source, web, output,
            hosted_workspace=True, workspace_api_origin=STAGING_API,
            capture_upload_origins=tuple(manifest["captureUploadOrigins"]),
            cosmaneura_web_origin=manifest["coreWebOrigin"],
            native_auth_clerk_archive=tmp_path / "clerk.tar.gz",
            native_identity_config=identity, data_mode="synthetic",
            allow_simulator_staging_native_auth=True)
    assert caught.value.cmd[1] == "archive"
    assert not output.exists()


def test_flag_allows_simulator_custody_until_source_archive(tmp_path):
    script = composition()
    web, identity, manifest = hosted_inputs(tmp_path, "operational-beta-v1")
    source = tmp_path / "source"
    source.mkdir()
    output = tmp_path / "output"
    with pytest.raises(subprocess.CalledProcessError) as caught:
        script.prepare(
            source, web, output,
            verification_variant="w8m", simulator_custody=True,
            renewable_native_capture=True, native_renderer_recovery=True,
            hosted_workspace=True, workspace_api_origin=STAGING_API,
            capture_upload_origins=tuple(manifest["captureUploadOrigins"]),
            cosmaneura_web_origin=manifest["coreWebOrigin"],
            native_auth_clerk_archive=tmp_path / "clerk.tar.gz",
            native_identity_config=identity, data_mode="synthetic",
            allow_simulator_staging_native_auth=True)
    assert caught.value.cmd[1] == "archive"
    assert not output.exists()
