"""Production-only CosmasNativeAuth Info.plist stamping for iPhone composition."""

from __future__ import annotations

import base64
import copy
import hashlib
import importlib.util
import json
import plistlib
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "scripts/compose-portable-iphone.py"
PROFILE = ROOT / "scripts/native_iphone_auth_profile.py"
PREPARE = ROOT / "scripts/prepare-owned-iphone-candidate.py"
APP_INFO = ROOT / "apps/capture/ios/App/App/Info.plist"
SWIFT_CONFIG = (
    ROOT / "clients/apple/native-auth/Sources/CosmasNativeAuth/NativeClerkConfiguration.swift"
)
EXPECTED_COMPOSITION_FILES = 513


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
        "profile": AUTH.PRODUCTION_IDENTITY_PROFILE,
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


def _live_beta_identity() -> dict:
    """Synthetic live operational-beta-v1 identity on clerk.cosmas.ai."""
    host = AUTH.SWIFT_OPERATIONAL_BETA_CLERK_HOST
    native = {
        "version": 1,
        "profile": "operational-beta-v1",
        "client": "apple",
        "apiOrigin": "https://api.cosmas.ai",
        "publishableKey": _live_key(host),
        "frontendOrigin": "https://" + host,
        "organizationId": "org_invented_live_beta",
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


def _staging_identity(*, accounts_dev: bool = False) -> dict:
    host = "invented-staging.clerk.accounts.dev" if accounts_dev else "clerk.staging.cosmas.ai"
    native = {
        "version": 1,
        "profile": "operational-staging-v1",
        "client": "apple",
        "apiOrigin": AUTH.STAGING_ORIGINS["api"],
        "publishableKey": _live_key(host),
        "frontendOrigin": "https://" + host,
        "organizationId": "org_invented_staging",
        "audience": "",
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


def _composition_source() -> dict:
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    return {"commit": commit}


def _swift_allowed_hosts(profile_case: str) -> set[str]:
    text = SWIFT_CONFIG.read_text(encoding="utf-8")
    match = re.search(
        rf"case \.{profile_case}:\s*return \[([^\]]*)\]",
        text,
    )
    assert match is not None, profile_case
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def test_frozen_info_plist_keeps_auth_disabled_with_empty_origins():
    info = plistlib.loads(APP_INFO.read_bytes())
    assert info["CosmasNativeAuth"]["enabled"] is False
    assert info["CosmasNativeAuth"]["frontendOrigin"] == ""
    assert info["CosmasNativeIdentity"]["apiOrigin"] == ""
    assert info["CosmasNativeIdentity"]["frontendOrigin"] == ""
    assert info.get("CosmaneuraWebOrigin", "") == ""


def test_python_production_clerk_host_matches_swift_operational_production_allowlist():
    assert AUTH.PRODUCTION_ORIGINS["clerk"] == "https://clerk.beta.cosmas.ai"
    assert AUTH.SWIFT_OPERATIONAL_PRODUCTION_CLERK_HOST == "clerk.beta.cosmas.ai"
    assert AUTH.SWIFT_OPERATIONAL_BETA_CLERK_HOST == "clerk.cosmas.ai"
    assert _swift_allowed_hosts("operationalBeta") == {"clerk.cosmas.ai"}
    assert _swift_allowed_hosts("operationalProduction") == {"clerk.beta.cosmas.ai"}
    # Removing either host from the Swift allow-list fails this agreement test.
    assert "https://" + next(iter(_swift_allowed_hosts("operationalProduction"))) == (
        AUTH.PRODUCTION_ORIGINS["clerk"])


def test_production_stamp_sets_origins_without_enabling_or_web_origin():
    before = plistlib.loads(APP_INFO.read_bytes())
    stamped = AUTH.production_native_auth_stamp(before)
    assert stamped["CosmasNativeAuth"]["enabled"] is False
    assert stamped["CosmasNativeAuth"]["profile"] == "operational-production-v1"
    assert stamped["CosmasNativeAuth"]["frontendOrigin"] == "https://clerk.beta.cosmas.ai"
    assert stamped["CosmasNativeIdentity"]["frontendOrigin"] == "https://clerk.beta.cosmas.ai"
    assert stamped["CosmasNativeIdentity"]["apiOrigin"] == "https://api.beta.cosmas.ai"
    assert stamped["CosmasNativeIdentity"]["profile"] == "operational-production-v1"
    assert stamped.get("CosmaneuraWebOrigin", "") == before.get("CosmaneuraWebOrigin", "")
    assert plistlib.loads(APP_INFO.read_bytes()) == before


def test_production_stamp_enables_only_with_validated_key():
    before = plistlib.loads(APP_INFO.read_bytes())
    identity = _production_identity()
    stamped = AUTH.production_native_auth_stamp(before, auth=identity["auth"])
    assert stamped["CosmasNativeAuth"]["enabled"] is True
    assert stamped["CosmasNativeAuth"]["profile"] == "operational-production-v1"
    assert stamped["CosmasNativeAuth"]["publishableKey"] == identity["auth"]["publishableKey"]
    assert AUTH.publishable_key_host(stamped["CosmasNativeAuth"]["publishableKey"]) == (
        AUTH.SWIFT_OPERATIONAL_PRODUCTION_CLERK_HOST)
    with pytest.raises(ValueError, match="without a validated key"):
        AUTH.production_native_auth_stamp(before, auth={
            "enabled": True,
            "profile": "operational-production-v1",
            "publishableKey": "",
            "frontendOrigin": AUTH.PRODUCTION_ORIGINS["clerk"],
            "organizationId": "org_invented_production",
            "audience": "cosmas-os-beta",
        })
    with pytest.raises(ValueError, match="operational-production-v1"):
        AUTH.production_native_auth_stamp(before, auth={
            **identity["auth"],
            "profile": "operational-beta-v1",
        })


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


@pytest.mark.parametrize("frontend,api,web,match", [
    ("https://clerk.beta.cosmas.ai", "https://api.staging.cosmas.ai", None, "refuses staging"),
    ("https://clerk.staging.cosmas.ai", "https://api.beta.cosmas.ai", None, "refuses staging"),
    ("https://clerk.cosmas.ai", "https://api.beta.cosmas.ai", None, "requires clerk.beta"),
    ("https://clerk.beta.cosmas.ai", "https://api.beta.cosmas.ai", "https://staging.cosmas.ai", "refuses staging"),
    ("https://clerk.beta.cosmas.ai:443", "https://api.beta.cosmas.ai", None, "exact HTTPS"),
    ("https://clerk.beta.cosmas.ai/path", "https://api.beta.cosmas.ai", None, "exact HTTPS"),
    ("http://clerk.beta.cosmas.ai", "https://api.beta.cosmas.ai", None, "exact HTTPS"),
])
def test_production_origin_mixes_ports_paths_and_reserved_host_are_refused(frontend, api, web, match):
    with pytest.raises(ValueError, match=match):
        AUTH.require_installation_profile_origins(
            "production", frontend_origin=frontend, api_origin=api, web_origin=web)


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
    assert result["CosmasNativeAuth"]["profile"] == "operational-production-v1"
    assert result["CosmasNativeAuth"]["frontendOrigin"] == AUTH.PRODUCTION_ORIGINS["clerk"]
    assert result["CosmasNativeAuth"]["publishableKey"] == identity["auth"]["publishableKey"]
    assert AUTH.publishable_key_host(result["CosmasNativeAuth"]["publishableKey"]) == (
        "clerk.beta.cosmas.ai")
    assert result["CosmasNativeIdentity"]["profile"] == "operational-production-v1"
    assert result["CosmasNativeIdentity"]["apiOrigin"] == AUTH.PRODUCTION_ORIGINS["api"]
    assert result.get("CosmaneuraWebOrigin", "") == before.get("CosmaneuraWebOrigin", "")


def test_owned_production_profile_refuses_missing_or_mismatched_key():
    identity = _production_identity()
    before = plistlib.loads(APP_INFO.read_bytes())
    configured = {
        **copy.deepcopy(before),
        "CosmasNativeIdentity": copy.deepcopy(identity["identity"]),
        "CosmasNativeAuth": copy.deepcopy(identity["auth"]),
    }
    with pytest.raises(ValueError, match="without a validated key"):
        AUTH.apply_installation_profile_to_configured_info(configured, "production", identity=None)
    bad = copy.deepcopy(identity)
    bad["auth"]["publishableKey"] = _live_key("clerk.cosmas.ai")
    with pytest.raises(ValueError, match="without a validated key"):
        AUTH.apply_installation_profile_to_configured_info(configured, "production", identity=bad)


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


def test_owned_staging_profile_accepts_dedicated_and_accounts_dev_with_empty_web():
    before = plistlib.loads(APP_INFO.read_bytes())
    assert before.get("CosmaneuraWebOrigin", "") == ""
    for accounts_dev in (False, True):
        identity = _staging_identity(accounts_dev=accounts_dev)
        configured = {
            **copy.deepcopy(before),
            "CosmasNativeIdentity": copy.deepcopy(identity["identity"]),
            "CosmasNativeAuth": copy.deepcopy(identity["auth"]),
            "CosmaneuraWebOrigin": "",
        }
        result = AUTH.apply_installation_profile_to_configured_info(
            configured, "staging", identity=identity)
        assert result == configured


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


def test_owned_beta_and_omitted_profiles_leave_live_beta_identity_unchanged():
    # Live clerk.cosmas.ai identity must not be treated as production. If None
    # were routed into the production stamp path, this would raise instead of
    # returning the configured Info unchanged.
    identity = _live_beta_identity()
    assert identity["identity"]["profile"] == "operational-beta-v1"
    assert identity["identity"]["frontendOrigin"] == "https://clerk.cosmas.ai"
    assert AUTH.publishable_key_host(identity["auth"]["publishableKey"]) == "clerk.cosmas.ai"
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
    with pytest.raises(ValueError, match="requires clerk.beta"):
        AUTH.apply_installation_profile_to_configured_info(
            configured, "production", identity=identity)


@pytest.mark.parametrize("profile", [None, "beta"])
def test_owned_beta_and_omitted_profiles_refuse_production_review_identity(profile):
    identity = _production_identity()
    before = plistlib.loads(APP_INFO.read_bytes())
    configured = {
        **copy.deepcopy(before),
        "CosmasNativeIdentity": copy.deepcopy(identity["identity"]),
        "CosmasNativeAuth": copy.deepcopy(identity["auth"]),
    }
    with pytest.raises(ValueError, match="--installation-profile production"):
        AUTH.apply_installation_profile_to_configured_info(
            configured, profile, identity=identity)


@pytest.mark.parametrize("profile", [None, "beta"])
def test_owned_beta_and_omitted_profiles_leave_staging_identity_unchanged(profile):
    identity = _staging_identity()
    before = plistlib.loads(APP_INFO.read_bytes())
    configured = {
        **copy.deepcopy(before),
        "CosmasNativeIdentity": copy.deepcopy(identity["identity"]),
        "CosmasNativeAuth": copy.deepcopy(identity["auth"]),
    }
    original = copy.deepcopy(configured)
    assert AUTH.apply_installation_profile_to_configured_info(
        configured, profile, identity=identity) == original


def test_apply_and_require_refuse_unknown_installation_profile():
    identity = _live_beta_identity()
    before = plistlib.loads(APP_INFO.read_bytes())
    configured = {
        **copy.deepcopy(before),
        "CosmasNativeIdentity": copy.deepcopy(identity["identity"]),
        "CosmasNativeAuth": copy.deepcopy(identity["auth"]),
    }
    with pytest.raises(ValueError, match="production, beta, or staging"):
        AUTH.apply_installation_profile_to_configured_info(
            configured, "review", identity=identity)
    with pytest.raises(ValueError, match="production, beta, or staging"):
        AUTH.require_installation_profile_origins(
            "review",
            frontend_origin=AUTH.PRODUCTION_ORIGINS["clerk"],
            api_origin=AUTH.PRODUCTION_ORIGINS["api"],
        )


@pytest.mark.parametrize("profile", [None, "beta", "staging"])
def test_compose_default_beta_staging_keeps_auth_disabled_and_single_info_derivation(tmp_path, profile):
    output = tmp_path / f"compose-{profile or 'default'}"
    project = COMPOSE_MODULE.compose(ROOT, output, installation_profile=profile)
    assert project.is_dir()
    composed = output / "apps/capture/ios/App/App/Info.plist"
    # Usage descriptions are derived; CosmasNativeAuth stays fail-closed.
    assert composed.read_bytes() != APP_INFO.read_bytes()
    info = plistlib.loads(composed.read_bytes())
    assert info["CosmasNativeAuth"]["enabled"] is False
    assert info["CosmasNativeAuth"]["frontendOrigin"] == ""
    assert info["NSMicrophoneUsageDescription"] == COMPOSE_MODULE.REVIEWED_MICROPHONE_USAGE
    manifest = json.loads((output / "composition.json").read_text(encoding="utf-8"))
    assert "installation_profile" not in manifest
    owned = [item for item in manifest["files"] if item["role"] == "derived-owned-info-plist"]
    assert len(owned) == 1
    assert owned[0].get("production_native_auth") is False
    assert "derived-production-native-auth" not in json.dumps(manifest)
    assert "derived-usage-description" not in json.dumps(manifest)
    assert len(manifest["files"]) == EXPECTED_COMPOSITION_FILES


def test_compose_production_profile_stamps_exact_auth_keys(tmp_path):
    output = tmp_path / "compose-production"
    COMPOSE_MODULE.compose(ROOT, output, installation_profile="production")
    composed = output / "apps/capture/ios/App/App/Info.plist"
    info = plistlib.loads(composed.read_bytes())
    assert info["CosmasNativeAuth"]["enabled"] is False
    assert info["CosmasNativeAuth"]["profile"] == "operational-production-v1"
    assert info["CosmasNativeAuth"]["frontendOrigin"] == "https://clerk.beta.cosmas.ai"
    assert info["CosmasNativeIdentity"]["apiOrigin"] == "https://api.beta.cosmas.ai"
    assert info["CosmasNativeIdentity"]["frontendOrigin"] == "https://clerk.beta.cosmas.ai"
    assert info["CosmasNativeIdentity"]["profile"] == "operational-production-v1"
    assert info["NSMicrophoneUsageDescription"] == COMPOSE_MODULE.REVIEWED_MICROPHONE_USAGE
    assert info.get("CosmaneuraWebOrigin", "") == ""
    frozen = plistlib.loads(APP_INFO.read_bytes())
    assert frozen["CosmasNativeAuth"]["enabled"] is False
    manifest = json.loads((output / "composition.json").read_text(encoding="utf-8"))
    assert manifest["installation_profile"] == "production"
    assert len(manifest["files"]) == EXPECTED_COMPOSITION_FILES
    stamped = [item for item in manifest["files"] if item["path"] == "ios/App/App/Info.plist"]
    assert len(stamped) == 1
    assert stamped[0]["role"] == "derived-owned-info-plist"
    assert stamped[0]["production_native_auth"] is True
    assert stamped[0]["scaffold_input_sha256"] == _sha256(APP_INFO)
    assert stamped[0]["auth_profile_source"] == "scripts/native_iphone_auth_profile.py"
    assert stamped[0]["auth_profile_source_sha256"] == _sha256(PROFILE)
    assert stamped[0]["derivation_source_sha256"] == _sha256(COMPOSE)


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
    default = plistlib.loads((default_out / "apps/capture/ios/App/App/Info.plist").read_bytes())
    assert default["CosmasNativeAuth"]["enabled"] is False
    assert default["CosmasNativeAuth"]["frontendOrigin"] == ""
    prod = plistlib.loads((prod_out / "apps/capture/ios/App/App/Info.plist").read_bytes())
    assert prod["CosmasNativeAuth"]["enabled"] is False
    assert prod["CosmasNativeAuth"]["frontendOrigin"] == "https://clerk.beta.cosmas.ai"
    assert prod["CosmasNativeAuth"]["profile"] == "operational-production-v1"
    assert prod.get("CosmaneuraWebOrigin", "") == ""


def test_compose_unknown_profile_is_refused(tmp_path):
    with pytest.raises(ValueError, match="production, beta, or staging"):
        COMPOSE_MODULE.compose(ROOT, tmp_path / "bad", installation_profile="review")


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


def test_composition_bindings_accept_default_and_production_compositions(tmp_path):
    default_out = tmp_path / "bindings-default"
    prod_out = tmp_path / "bindings-production"
    COMPOSE_MODULE.compose(ROOT, default_out)
    COMPOSE_MODULE.compose(ROOT, prod_out, installation_profile="production")
    source = _composition_source()
    default_composition, default_bindings = OWNED.composition_bindings(ROOT, source, default_out)
    prod_composition, prod_bindings = OWNED.composition_bindings(ROOT, source, prod_out)
    assert len(default_composition["files"]) == EXPECTED_COMPOSITION_FILES
    assert len(default_bindings) == EXPECTED_COMPOSITION_FILES
    assert len(prod_composition["files"]) == EXPECTED_COMPOSITION_FILES
    assert len(prod_bindings) == EXPECTED_COMPOSITION_FILES
    default_owned = [item for item in default_composition["files"]
                     if item["role"] == "derived-owned-info-plist"]
    prod_owned = [item for item in prod_composition["files"]
                  if item["role"] == "derived-owned-info-plist"]
    assert len(default_owned) == 1 and default_owned[0]["production_native_auth"] is False
    assert len(prod_owned) == 1 and prod_owned[0]["production_native_auth"] is True
    assert prod_owned[0]["auth_profile_source_sha256"] == _sha256(PROFILE)


def test_composition_bindings_refuse_tampered_production_stamp(tmp_path):
    output = tmp_path / "bindings-tamper"
    COMPOSE_MODULE.compose(ROOT, output, installation_profile="production")
    source = _composition_source()
    info_path = output / "apps/capture/ios/App/App/Info.plist"
    info = plistlib.loads(info_path.read_bytes())
    info["CosmasNativeAuth"]["frontendOrigin"] = "https://clerk.cosmas.ai"
    info_path.write_bytes(plistlib.dumps(info, sort_keys=False))
    with pytest.raises(ValueError, match="Composed bytes differ|differs from the reviewed"):
        OWNED.composition_bindings(ROOT, source, output)


def test_composition_bindings_refuse_wrong_scaffold_input_hash(tmp_path):
    output = tmp_path / "bindings-scaffold-hash"
    COMPOSE_MODULE.compose(ROOT, output, installation_profile="production")
    source = _composition_source()
    manifest_path = output / "composition.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for item in manifest["files"]:
        if item["role"] == "derived-owned-info-plist":
            item["scaffold_input_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="lost its frozen scaffold Info.plist input"):
        OWNED.composition_bindings(ROOT, source, output)


def test_composition_bindings_refuse_changed_derivation_or_auth_profile_hash(tmp_path):
    output = tmp_path / "bindings-derivation-hash"
    COMPOSE_MODULE.compose(ROOT, output, installation_profile="production")
    source = _composition_source()
    manifest_path = output / "composition.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for item in manifest["files"]:
        if item["role"] == "derived-owned-info-plist":
            item["derivation_source_sha256"] = "1" * 64
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="drifted from the committed composer"):
        OWNED.composition_bindings(ROOT, source, output)
    COMPOSE_MODULE.compose(ROOT, tmp_path / "bindings-auth-hash", installation_profile="production")
    auth_out = tmp_path / "bindings-auth-hash"
    manifest_path = auth_out / "composition.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for item in manifest["files"]:
        if item["role"] == "derived-owned-info-plist":
            item["auth_profile_source_sha256"] = "2" * 64
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="drifted from native_iphone_auth_profile"):
        OWNED.composition_bindings(ROOT, source, auth_out)
