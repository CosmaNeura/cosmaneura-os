"""Installation-profile fence coverage and raw-validate caller allow-list."""

from __future__ import annotations

import base64
import importlib.util
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
NATIVE_IDENTITY = ROOT / "scripts/native_identity_build.py"
APPLE = ROOT / "scripts/prepare-apple-synthetic.py"
OWNED = ROOT / "scripts/prepare-owned-iphone-candidate.py"
WORKSPACE_IDENTITY = ROOT / "scripts/prepare-workspace-identity.mjs"
SWIFT = (
    ROOT / "clients/apple/native-auth/Sources/CosmasNativeAuth/NativeClerkConfiguration.swift"
)
SHARED = ROOT / "clients/shared/operational-native-identity.mjs"

# Explicit allow-list of production call sites that may still call
# validateOperationalNativeIdentity outside the shared module. A new raw caller
# outside this set fails CI. Tests and the shared module itself are excluded.
RAW_VALIDATE_ALLOW_LIST = frozenset({
    "scripts/prepare-workspace-identity.mjs",  # 1d: intentional; fence at package/prepare
    "scripts/transition-desktop-identity.mjs",  # offline beta→staging; Release Lead check pending
    "clients/shared/native-practice-profile.mjs",
    "clients/shared/synthetic-iphone-sim-identity.mjs",
    # clients/desktop/native-identity-config.mjs re-exports only (no call site).
})


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


AUTH = _load(ROOT / "scripts/native_iphone_auth_profile.py", "native_iphone_auth_profile")
IDENTITY = _load(NATIVE_IDENTITY, "native_identity_build")
APPLE_MOD = _load(APPLE, "prepare_apple_synthetic")
OWNED_MOD = _load(OWNED, "owned_iphone_preparation")


def _live_key(host: str) -> str:
    return "pk_live_" + base64.b64encode(f"{host}$".encode()).decode()


def _test_key(host: str) -> str:
    return "pk_test_" + base64.b64encode(f"{host}$".encode()).decode()


def _identity(profile: str, frontend: str, api: str, client: str = "apple") -> dict:
    host = frontend.removeprefix("https://")
    return {
        "version": 1,
        "profile": profile,
        "client": client,
        "apiOrigin": api,
        "frontendOrigin": frontend,
        "publishableKey": _live_key(host),
        "organizationId": "org_invented_beta",
        "audience": "cosmas-os-beta-api",
    }


def _write(path: Path, document: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document))
    return path


def test_raw_validate_callers_match_explicit_allow_list():
    """Every production caller of validateOperationalNativeIdentity is listed."""
    pattern = re.compile(r"validateOperationalNativeIdentity\s*\(")
    found = set()
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT).as_posix()
        if any(part in {"node_modules", ".git", ".venv", "dist", "build"} for part in path.parts):
            continue
        if rel.endswith((".mjs", ".js", ".ts", ".tsx", ".py")) is False:
            continue
        if rel == "clients/shared/operational-native-identity.mjs":
            continue
        if "/test" in f"/{rel}" or rel.endswith(".test.mjs") or rel.startswith("tests/"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if pattern.search(text):
            found.add(rel)
    assert found == RAW_VALIDATE_ALLOW_LIST, (
        f"Unexpected raw validate callers: {sorted(found - RAW_VALIDATE_ALLOW_LIST)}; "
        f"missing allow-list entries: {sorted(RAW_VALIDATE_ALLOW_LIST - found)}"
    )


def test_native_identity_build_refuses_production_without_installation_profile(tmp_path):
    """N1 killer: validate must use loadOperationalNativeIdentity; None refuses production."""
    production = _identity(
        "operational-production-v1", "https://clerk.beta.cosmas.ai", "https://api.beta.cosmas.ai")
    path = _write(tmp_path / "production.json", production)
    with pytest.raises(ValueError, match="Native identity must match"):
        IDENTITY.load(path, "apple", installation_profile=None)
    with pytest.raises(ValueError, match="Native identity must match"):
        IDENTITY.validate(production, "apple", installation_profile=None)
    with pytest.raises(ValueError, match="Native identity must match"):
        IDENTITY.validate(production, "apple", installation_profile="beta")
    ok = IDENTITY.validate(production, "apple", installation_profile="production")
    assert ok["identity"]["profile"] == "operational-production-v1"


def test_native_identity_build_keeps_beta_and_staging_under_every_profile(tmp_path):
    beta = _identity("operational-beta-v1", "https://clerk.cosmas.ai", "https://api.example.invalid")
    # Shipped TestFlight/Mac identity: operational-beta-v1 on clerk.staging.
    shipped = _identity(
        "operational-beta-v1", "https://clerk.staging.cosmas.ai", "https://api.staging.cosmas.ai")
    staging = _identity(
        "operational-staging-v1", "https://clerk.staging.cosmas.ai", "https://api.staging.cosmas.ai")
    for profile in (None, "beta", "staging", "production"):
        assert IDENTITY.validate(beta, "apple", beta["apiOrigin"], profile)["identity"]["frontendOrigin"] == (
            "https://clerk.cosmas.ai")
        assert IDENTITY.validate(
            shipped, "apple", shipped["apiOrigin"], profile)["identity"]["frontendOrigin"] == (
            "https://clerk.staging.cosmas.ai")
        assert IDENTITY.validate(
            staging, "apple", staging["apiOrigin"], profile)["identity"]["frontendOrigin"] == (
            "https://clerk.staging.cosmas.ai")
    with pytest.raises(ValueError, match="Native identity must match"):
        IDENTITY.validate(
            _identity(
                "operational-beta-v1", "https://clerk.beta.cosmas.ai", "https://api.beta.cosmas.ai"),
            "apple", "https://api.beta.cosmas.ai", None)


def test_prepare_apple_refuses_production_without_installation_profile(tmp_path):
    """Simulator and device paths: omitted/beta refuse operational-production-v1 (N3)."""
    production = _identity(
        "operational-production-v1", "https://clerk.beta.cosmas.ai", "https://api.beta.cosmas.ai")
    identity_path = _write(tmp_path / "id.json", production)
    for profile in (None, "beta"):
        with pytest.raises(ValueError, match="Native identity must match"):
            APPLE_MOD.prepare(
                tmp_path / "source", tmp_path / "web", tmp_path / f"out-{profile}",
                hosted_workspace=True, workspace_api_origin=production["apiOrigin"],
                native_auth_clerk_archive=tmp_path / "clerk.tar.gz",
                native_identity_config=identity_path, data_mode="synthetic",
                allow_simulator_staging_native_auth=True,
                installation_profile=profile)
        with pytest.raises(ValueError, match="Native identity must match"):
            APPLE_MOD.prepare(
                tmp_path / "source", tmp_path / "web", tmp_path / f"device-{profile}",
                hosted_workspace=True, workspace_api_origin=production["apiOrigin"],
                native_identity_config=identity_path, data_mode="synthetic",
                installation_profile=profile)


def test_swift_python_clerk_beta_parity_for_production_only():
    """CTO: clerk.beta admitted only for operationalProduction; Swift hosts match."""
    text = SWIFT.read_text(encoding="utf-8")
    assert 'case operationalProduction = "operational-production-v1"' in text
    assert 'case .operationalProduction:' in text
    # Operational production allow-list is clerk.beta only.
    prod_block = text.split("case .operationalProduction:")[1].split("case ")[0]
    assert "clerk.beta.cosmas.ai" in prod_block
    sim_block = text.split("case .simulatorStaging:")[1].split("case ")[0]
    assert "clerk.beta.cosmas.ai" not in sim_block
    beta_block = text.split("case .operationalBeta:")[1].split("case ")[0]
    assert "clerk.cosmas.ai" in beta_block
    assert "clerk.beta.cosmas.ai" not in beta_block
    # Python authorize admits beta pair only for operational-production-v1.
    assert APPLE_MOD._allowed_simulator_auth(
        "clerk.beta.cosmas.ai", "https://api.beta.cosmas.ai",
        identity_profile="operational-production-v1") is True
    for profile in ("operational-beta-v1", "operational-staging-v1", "simulator-staging-v1", None):
        assert APPLE_MOD._allowed_simulator_auth(
            "clerk.beta.cosmas.ai", "https://api.beta.cosmas.ai",
            identity_profile=profile) is False


def test_accounts_dev_python_rejects_hyphen_edge_labels():
    assert AUTH.is_accounts_dev_clerk_host("invented.clerk.accounts.dev") is True
    assert AUTH.is_accounts_dev_clerk_host("-invented.clerk.accounts.dev") is False
    assert AUTH.is_accounts_dev_clerk_host("invented-.clerk.accounts.dev") is False
    assert AUTH.is_accounts_dev_clerk_host("inv-ented.clerk.accounts.dev") is True
    assert AUTH.is_accounts_dev_clerk_host("bad.-label.clerk.accounts.dev") is False
