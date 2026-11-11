"""CosmaBot production hosting profile: name guards, recording-off, dry-run."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PROD = REPO / "infra/beta/vm/prod"
FOUNDATION = PROD / "foundation"
STAGING_FOUNDATION = REPO / "infra/beta/vm/foundation"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


guards = _load("cosmabot_prod_name_guards", PROD / "name_guards.py")
dry_run = _load("cosmabot_prod_dry_run", PROD / "dry_run.py")


def test_production_refuses_staging_names():
    with pytest.raises(guards.NameGuardError, match="production_refuses"):
        guards.assert_production_inputs(
            {"resource_group": guards.STAGING["resource_group"]}
        )
    with pytest.raises(guards.NameGuardError, match="production_refuses"):
        guards.assert_production_inputs({"web_host": guards.STAGING["web_host"]})
    with pytest.raises(guards.NameGuardError, match="production_refuses"):
        guards.assert_production_inputs({"acr_prefix": guards.STAGING["acr_prefix"]})
    with pytest.raises(guards.NameGuardError, match="production_refuses"):
        guards.assert_production_inputs(
            {"key_vault_prefix": guards.STAGING["key_vault_prefix"]}
        )
    with pytest.raises(guards.NameGuardError, match="production_refuses"):
        guards.assert_production_inputs(
            {"storage": guards.STAGING["storage_prefixes"][0]}
        )


def test_staging_refuses_production_names():
    with pytest.raises(guards.NameGuardError, match="staging_refuses"):
        guards.assert_staging_inputs(
            {"resource_group": guards.PRODUCTION["resource_group"]}
        )
    with pytest.raises(guards.NameGuardError, match="staging_refuses"):
        guards.assert_staging_inputs({"web_host": guards.PRODUCTION["web_host"]})
    with pytest.raises(guards.NameGuardError, match="staging_refuses"):
        guards.assert_staging_inputs({"api_host": guards.PRODUCTION["api_host"]})
    with pytest.raises(guards.NameGuardError, match="staging_refuses"):
        guards.assert_staging_inputs({"acr_prefix": guards.PRODUCTION["acr_prefix"]})
    with pytest.raises(guards.NameGuardError, match="staging_refuses"):
        guards.assert_staging_inputs(
            {"key_vault_prefix": guards.PRODUCTION["key_vault_prefix"]}
        )
    with pytest.raises(guards.NameGuardError, match="staging_refuses"):
        guards.assert_staging_inputs(
            {"storage": guards.PRODUCTION["storage_prefixes"][0]}
        )


def test_real_patient_recording_stays_off_in_prod_profile():
    profile = json.loads((PROD / "profile/runtime-public.json").read_text())
    assert profile["runtime"]["environment"]["REAL_PATIENT_RECORDING_ENABLED"] == "false"
    bundle = dry_run.render_params()
    dry_run.validate_rendered(bundle)
    assert bundle["params"]["real_patient_recording_enabled"] == "false"


def test_model_config_matches_staging_profile():
    profile = json.loads((PROD / "profile/runtime-public.json").read_text())
    assert profile["runtime"]["environment"]["WORKSPACE_LLM_BACKEND"] == "azure_gpt41"
    assert profile["runtime"]["environment"]["WORKSPACE_LLM_DEPLOYMENT"] == "gpt-4.1"


def test_azure_openai_defaults_off():
    openai = (FOUNDATION / "openai.tf").read_text()
    assert "enable_azure_openai" in openai
    assert re.search(r"default\s*=\s*false", openai)
    assert 'module "azure_openai"' in openai
    profile = json.loads((PROD / "profile/runtime-public.json").read_text())
    assert profile["azure_openai_module"]["enabled_by_default"] is False
    bundle = dry_run.render_params()
    dry_run.validate_rendered(bundle)
    assert bundle["params"]["enable_azure_openai"] is False


def test_azure_openai_opt_in_path_validates_dzus_shape():
    module = (FOUNDATION / "modules/azure_openai/main.tf").read_text()
    assert "gpt-4.1-dzus" in module
    assert "DataZoneStandard" in module
    assert "2025-04-14" in module
    assert "privatelink.openai.azure.com" in module
    assert "Cognitive Services OpenAI User" in module
    assert "public_network_access_enabled = false" in module
    assert not re.search(r"local_auth_enabled\s*=\s*false", module)
    bundle = dry_run.render_params(enable_azure_openai=True)
    dry_run.validate_rendered(bundle)
    assert bundle["params"]["enable_azure_openai"] is True


def test_clerk_secret_names_only_no_values():
    profile = json.loads((PROD / "profile/runtime-public.json").read_text())
    assert "CLERK_SECRET_KEY" in profile["runtime"]["secret_names"]
    blob = json.dumps(profile)
    assert "sk_live_" not in blob
    assert "sk_test_" not in blob


def test_price_table_estimate_and_total():
    prices = json.loads((PROD / "prices/monthly-estimate.json").read_text())
    assert prices["label"] == "estimate"
    assert prices["price_date"] == "2026-11-11"
    components = {item["component"] for item in prices["line_items"]}
    assert any("Azure OpenAI gpt-4.1 Data Zone" in name for name in components)
    assert any("OpenAI private endpoint" in name for name in components)
    assert any("privatelink.openai.azure.com" in name for name in components)
    total = dry_run.monthly_total(prices)
    assert 180 <= total <= 260
    assert total == 188.07
    assert total <= float(prices["warning_threshold_usd"])


def test_dry_run_offline_no_azure_default_off(monkeypatch):
    # Ensure dry-run does not require or call Azure tooling.
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    for key in list(os.environ):
        if key.startswith(("ARM_", "TF_")) or key == "AZURE_CONFIG_DIR":
            monkeypatch.delenv(key, raising=False)
    result = subprocess.run(
        [sys.executable, str(PROD / "dry_run.py")],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["dry_run"] is True
    assert payload["azure_calls"] is False
    assert payload["params"]["resource_group"] == "rg-cosmabot-prod-eus2-01"
    assert payload["params"]["web_host"] == "beta.cosmas.ai"
    assert payload["params"]["real_patient_recording_enabled"] == "false"
    assert payload["params"]["enable_azure_openai"] is False


def test_dry_run_offline_opt_in_openai(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    for key in list(os.environ):
        if key.startswith(("ARM_", "TF_")) or key == "AZURE_CONFIG_DIR":
            monkeypatch.delenv(key, raising=False)
    result = subprocess.run(
        [sys.executable, str(PROD / "dry_run.py"), "--enable-azure-openai"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["params"]["enable_azure_openai"] is True
    assert payload["azure_calls"] is False


def test_apply_refuses_without_confirm():
    script = REPO / "infra/beta/apply-cosmabot-prod-foundation.sh"
    result = subprocess.run(
        ["bash", str(script), "--private-dir", "/tmp/cosmabot-prod-never-apply"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "refusing apply without --confirm-apply" in result.stderr


def test_staging_foundation_untouched_and_without_prod_names():
    staging_text = "\n".join(
        path.read_text()
        for path in sorted(STAGING_FOUNDATION.rglob("*"))
        if path.is_file() and path.suffix in {".tf", ".py", ".hcl"}
    )
    for needle in (
        guards.PRODUCTION["resource_group"],
        guards.PRODUCTION["vm_name"],
        guards.PRODUCTION["web_host"],
        guards.PRODUCTION["acr_prefix"],
        guards.PRODUCTION["key_vault_prefix"],
        guards.PRODUCTION["state_namespace"],
        *guards.PRODUCTION["storage_prefixes"],
    ):
        assert needle not in staging_text
    assert guards.STAGING["resource_group"] in staging_text
