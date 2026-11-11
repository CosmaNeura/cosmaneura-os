"""Production-only CosmasNativeAuth Info.plist stamping for iPhone composition."""

from __future__ import annotations

import base64
import copy
import hashlib
import importlib.util
import plistlib
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "scripts/compose-portable-iphone.py"
PROFILE = ROOT / "scripts/native_iphone_auth_profile.py"
PREPARE = ROOT / "scripts/prepare-owned-iphone-candidate.py"
APP_INFO = ROOT / "apps/capture/ios/App/App/Info.plist"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


AUTH = _load(PROFILE, "native_iphone_auth_profile")
COMPOSE_MODULE = _load(COMPOSE, "compose_portable_iphone")
OWNED = _load(PREPARE, "owned_iphone_preparation")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _live_key(host: str) -> str:
    return "pk_live_" + base64.b64encode(f"{host}$".encode()).decode()


def _production_identity() -> dict:
    host = "clerk.beta.cosmas.ai"
    native = {
        "version": 1,
        "profile": "operational-beta-v1",
        "client": "apple",
        "apiOrigin": AUTH.PRODUCTION_ORIGINS["api"],
        "publishableKey": _live_key(host),
        "frontendOrigin": AUTH.PRODUCTION_ORIGINS["clerk"],
        "organizationId": "org_invented_production",
        "audience": "cosmas-os-beta",
    }
    auth = {
        "enabled": True,
        "profile": native["profile"],
        "publishableKey": native["publishableKey"],
        "frontendOrigin": native["frontendOrigin"],
        "organizationId": native["organizationId"],
        "audience": native["audience"],
    }
    return {"identity": native, "auth": auth, "bundle": "com.cosmasos.beta.ios"}


def _staging_identity() -> dict:
    host = "clerk.staging.cosmas.ai"
    native = {
        "version": 1,
        "profile": "operational-staging-v1",
        "client": "apple",
        "apiOrigin": AUTH.STAGING_ORIGINS["api"],
        "publishableKey": _live_key(host),
        "frontendOrigin": AUTH.STAGING_ORIGINS["clerk"],
        "organizationId": "org_invented_staging",
        "audience": "cosmas-os-beta-api",
    }
    auth = {
        "enabled": True,
        "profile": native["profile"],
        "publishableKey": native["publishableKey"],
        "frontendOrigin": native["frontendOrigin"],
        "organizationId": native["organizationId"],
        "audience": native["audience"],
    }
    return {"identity": native, "auth": auth, "bundle": "com.cosmasos.beta.ios"}


def test_frozen_info_plist_keeps_auth_disabled_with_empty_origins():
    info = plistlib.loads(APP_INFO.read_bytes())
    assert info["CosmasNativeAuth"]["enabled"] is False
    assert info["CosmasNativeAuth"]["frontendOrigin"] == ""
    assert info["CosmasNativeIdentity"]["apiOrigin"] == ""
    assert info["CosmasNativeIdentity"]["frontendOrigin"] == ""
    assert info.get("CosmaneuraWebOrigin", "") == ""


def test_production_stamp_sets_enabled_and_exact_production_origins():
    before = plistlib.loads(APP_INFO.read_bytes())
    stamped = AUTH.production_native_auth_stamp(before)
    assert stamped["CosmasNativeAuth"]["enabled"] is True
    assert stamped["CosmasNativeAuth"]["frontendOrigin"] == "https://clerk.beta.cosmas.ai"
    assert stamped["CosmasNativeIdentity"]["frontendOrigin"] == "https://clerk.beta.cosmas.ai"
    assert stamped["CosmasNativeIdentity"]["apiOrigin"] == "https://api.beta.cosmas.ai"
    assert stamped["CosmaneuraWebOrigin"] == "https://beta.cosmas.ai"
    # Frozen scaffold bytes stay untouched.
    assert plistlib.loads(APP_INFO.read_bytes()) == before


def test_production_refuses_staging_origins_and_staging_refuses_production():
    with pytest.raises(ValueError, match="refuses staging origins"):
        AUTH.require_installation_profile_origins(
            "production",
            frontend_origin=AUTH.STAGING_ORIGINS["clerk"],
            api_origin=AUTH.STAGING_ORIGINS["api"],
            web_origin=AUTH.STAGING_ORIGINS["web"],
        )
    with pytest.raises(ValueError, match="refuses production origins"):
        AUTH.require_installation_profile_origins(
            "staging",
            frontend_origin=AUTH.PRODUCTION_ORIGINS["clerk"],
            api_origin=AUTH.PRODUCTION_ORIGINS["api"],
            web_origin=AUTH.PRODUCTION_ORIGINS["web"],
        )
    AUTH.require_installation_profile_origins(
        "production",
        frontend_origin=AUTH.PRODUCTION_ORIGINS["clerk"],
        api_origin=AUTH.PRODUCTION_ORIGINS["api"],
        web_origin=AUTH.PRODUCTION_ORIGINS["web"],
    )
    AUTH.require_installation_profile_origins(
        "staging",
        frontend_origin=AUTH.STAGING_ORIGINS["clerk"],
        api_origin=AUTH.STAGING_ORIGINS["api"],
        web_origin=AUTH.STAGING_ORIGINS["web"],
    )


def test_owned_production_profile_stamps_auth_and_keeps_reviewed_credentials():
    identity = _production_identity()
    before = plistlib.loads(APP_INFO.read_bytes())
    configured = {
        **copy.deepcopy(before),
        "CosmasNativeIdentity": copy.deepcopy(identity["identity"]),
        "CosmasNativeAuth": copy.deepcopy(identity["auth"]),
    }
    result = AUTH.apply_installation_profile_to_configured_info(
        configured, "production", identity=identity)
    assert result["CosmasNativeAuth"]["enabled"] is True
    assert result["CosmasNativeAuth"]["frontendOrigin"] == AUTH.PRODUCTION_ORIGINS["clerk"]
    assert result["CosmasNativeAuth"]["publishableKey"] == identity["auth"]["publishableKey"]
    assert result["CosmasNativeAuth"]["organizationId"] == identity["auth"]["organizationId"]
    assert result["CosmasNativeIdentity"]["apiOrigin"] == AUTH.PRODUCTION_ORIGINS["api"]
    assert result["CosmaneuraWebOrigin"] == AUTH.PRODUCTION_ORIGINS["web"]


def test_owned_production_profile_refuses_staging_identity_origins():
    identity = _staging_identity()
    before = plistlib.loads(APP_INFO.read_bytes())
    configured = {
        **copy.deepcopy(before),
        "CosmasNativeIdentity": copy.deepcopy(identity["identity"]),
        "CosmasNativeAuth": copy.deepcopy(identity["auth"]),
    }
    with pytest.raises(ValueError, match="refuses staging origins"):
        AUTH.apply_installation_profile_to_configured_info(
            configured, "production", identity=identity)


def test_owned_staging_profile_refuses_production_identity_origins():
    identity = _production_identity()
    before = plistlib.loads(APP_INFO.read_bytes())
    configured = {
        **copy.deepcopy(before),
        "CosmasNativeIdentity": copy.deepcopy(identity["identity"]),
        "CosmasNativeAuth": copy.deepcopy(identity["auth"]),
    }
    with pytest.raises(ValueError, match="refuses production origins"):
        AUTH.apply_installation_profile_to_configured_info(
            configured, "staging", identity=identity)


def test_owned_beta_and_default_profiles_leave_configured_info_unchanged():
    identity = _production_identity()
    before = plistlib.loads(APP_INFO.read_bytes())
    configured = {
        **copy.deepcopy(before),
        "CosmasNativeIdentity": copy.deepcopy(identity["identity"]),
        "CosmasNativeAuth": copy.deepcopy(identity["auth"]),
    }
    original = copy.deepcopy(configured)
    assert AUTH.apply_installation_profile_to_configured_info(
        configured, "beta", identity=identity) == original
    assert AUTH.apply_installation_profile_to_configured_info(
        configured, None, identity=identity) == original


@pytest.mark.parametrize("profile", [None, "beta", "staging"])
def test_compose_default_beta_staging_info_plist_matches_frozen_scaffold(tmp_path, profile):
    output = tmp_path / f"compose-{profile or 'default'}"
    project = COMPOSE_MODULE.compose(ROOT, output, installation_profile=profile)
    assert project.is_dir()
    composed = output / "apps/capture/ios/App/App/Info.plist"
    assert composed.read_bytes() == APP_INFO.read_bytes()
    info = plistlib.loads(composed.read_bytes())
    assert info["CosmasNativeAuth"]["enabled"] is False
    assert info["CosmasNativeAuth"]["frontendOrigin"] == ""
    manifest = (output / "composition.json").read_text(encoding="utf-8")
    assert "installation_profile" not in manifest
    assert "derived-production-native-auth" not in manifest


def test_compose_production_profile_stamps_exact_auth_keys(tmp_path):
    output = tmp_path / "compose-production"
    COMPOSE_MODULE.compose(ROOT, output, installation_profile="production")
    composed = output / "apps/capture/ios/App/App/Info.plist"
    assert composed.read_bytes() != APP_INFO.read_bytes()
    info = plistlib.loads(composed.read_bytes())
    assert info["CosmasNativeAuth"]["enabled"] is True
    assert info["CosmasNativeAuth"]["frontendOrigin"] == "https://clerk.beta.cosmas.ai"
    assert info["CosmasNativeIdentity"]["apiOrigin"] == "https://api.beta.cosmas.ai"
    assert info["CosmasNativeIdentity"]["frontendOrigin"] == "https://clerk.beta.cosmas.ai"
    assert info["CosmaneuraWebOrigin"] == "https://beta.cosmas.ai"
    # Frozen scaffold remains the disabled default.
    assert _sha256(APP_INFO) == _sha256(ROOT / "apps/capture/ios/App/App/Info.plist")
    frozen = plistlib.loads(APP_INFO.read_bytes())
    assert frozen["CosmasNativeAuth"]["enabled"] is False
    manifest = __import__("json").loads((output / "composition.json").read_text(encoding="utf-8"))
    assert manifest["installation_profile"] == "production"
    stamped = [item for item in manifest["files"] if item["path"] == "ios/App/App/Info.plist"]
    assert len(stamped) == 1
    assert stamped[0]["role"] == "derived-production-native-auth"
    assert stamped[0]["scaffold_input_sha256"] == _sha256(APP_INFO)


def test_compose_cli_production_and_default_match_module(tmp_path):
    default_out = tmp_path / "cli-default"
    prod_out = tmp_path / "cli-production"
    subprocess.run(
        [sys.executable, str(COMPOSE), "--repository", str(ROOT), "--output", str(default_out)],
        check=True, cwd=ROOT, capture_output=True)
    subprocess.run(
        [sys.executable, str(COMPOSE), "--repository", str(ROOT), "--output", str(prod_out),
         "--installation-profile", "production"],
        check=True, cwd=ROOT, capture_output=True)
    assert (default_out / "apps/capture/ios/App/App/Info.plist").read_bytes() == APP_INFO.read_bytes()
    prod = plistlib.loads((prod_out / "apps/capture/ios/App/App/Info.plist").read_bytes())
    assert prod["CosmasNativeAuth"]["enabled"] is True
    assert prod["CosmaneuraWebOrigin"] == "https://beta.cosmas.ai"


def test_owned_prepare_arguments_accept_installation_profile():
    args = OWNED.arguments([
        "--inputs", "/invented/public",
        "--retained-info", "/invented/Info.plist",
        "--node", "/invented/node",
        "--output", "/invented/new",
        "--installation-profile", "production",
    ])
    assert args.installation_profile == "production"
    default = OWNED.arguments([
        "--inputs", "/invented/public",
        "--retained-info", "/invented/Info.plist",
        "--node", "/invented/node",
        "--output", "/invented/new",
    ])
    assert default.installation_profile is None
