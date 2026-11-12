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


def test_staging_refuses_production_names():
    with pytest.raises(guards.NameGuardError, match="staging_refuses"):
        guards.assert_staging_inputs(
            {"resource_group": guards.PRODUCTION["resource_group"]}
        )
    with pytest.raises(guards.NameGuardError, match="staging_refuses"):
        guards.assert_staging_inputs({"api_host": guards.PRODUCTION["api_host"]})


def test_m4_embedded_name_refusal_both_directions():
    with pytest.raises(guards.NameGuardError):
        guards.assert_production_inputs({"acr": guards.STAGING["acr_prefix"] + "x"})
    with pytest.raises(guards.NameGuardError):
        guards.assert_production_inputs({"kv": "x" + guards.STAGING["key_vault_prefix"]})
    with pytest.raises(guards.NameGuardError):
        guards.assert_production_inputs(
            {"st": "pre" + guards.STAGING["storage_prefixes"][0] + "suf"}
        )
    with pytest.raises(guards.NameGuardError):
        guards.assert_production_inputs(
            {"url": f"https://{guards.STAGING['web_host']}/path"}
        )
    with pytest.raises(guards.NameGuardError):
        guards.assert_staging_inputs({"acr": guards.PRODUCTION["acr_prefix"] + "x"})


def test_m4_legitimate_production_values_pass():
    guards.assert_production_inputs(
        {
            "resource_group": guards.PRODUCTION["resource_group"],
            "vm_name": guards.PRODUCTION["vm_name"],
            "web_host": guards.PRODUCTION["web_host"],
            "api_host": guards.PRODUCTION["api_host"],
            "acr_prefix": guards.PRODUCTION["acr_prefix"],
            "key_vault_prefix": guards.PRODUCTION["key_vault_prefix"],
            "storage_0": guards.PRODUCTION["storage_prefixes"][0],
            "storage_1": guards.PRODUCTION["storage_prefixes"][1],
            "state_namespace": guards.PRODUCTION["state_namespace"],
        }
    )


def test_real_patient_recording_stays_off_in_prod_profile():
    profile = json.loads((PROD / "profile/runtime-public.json").read_text())
    assert profile["runtime"]["environment"]["REAL_PATIENT_RECORDING_ENABLED"] == "false"


def test_model_config_routes_false_and_no_endpoint_until_cutover():
    profile = json.loads((PROD / "profile/runtime-public.json").read_text())
    env = profile["runtime"]["environment"]
    assert env["WORKSPACE_LLM_BACKEND"] == "disabled"
    assert env["WORKSPACE_LLM_DEPLOYMENT"] == "gpt-4.1"
    assert env["WORKSPACE_LLM_USDZ_ENABLED"] == "false"
    assert "WORKSPACE_LLM_ENDPOINT" not in env
    assert profile["azure_openai_module"]["deployment_created_when_enabled"] == "gpt-4.1-dzus"
    assert profile["azure_openai_module"]["routes_runtime_traffic"] is False
    assert profile["azure_openai_module"]["first_apply_capacity"] == 1
    assert "WORKSPACE_LLM_API_KEY" not in profile["runtime"]["secret_names"]
    assert "dns" not in profile


def test_prod_tree_never_references_cosmascode():
    needle = "cosmas" + "code"
    for path in PROD.rglob("*"):
        if not path.is_file() or path.suffix not in {".tf", ".py", ".hcl", ".json", ".md"}:
            continue
        if path.name in {"name_guards.py", "dry_run.py", "test_cosmabot_prod_hosting.py"}:
            continue
        if "tests" in path.parts:
            continue
        text = path.read_text().lower()
        # README may mention the shared account only to forbid loading its key.
        if path.name == "README.md" and "never be loaded into prod" in text:
            continue
        assert needle not in text, path


def test_prod_tree_has_no_staging_names_except_guards():
    for path in PROD.rglob("*"):
        if not path.is_file() or path.suffix not in {".tf", ".py", ".hcl", ".json", ".md"}:
            continue
        if path.name == "name_guards.py":
            continue
        if "tests" in path.parts:
            continue
        text = path.read_text()
        for needle in (
            guards.STAGING["resource_group"],
            guards.STAGING["vm_name"],
            guards.STAGING["web_host"],
            guards.STAGING["api_host"],
            guards.STAGING["acr_prefix"],
            guards.STAGING["key_vault_prefix"],
            guards.STAGING["state_namespace"],
            *guards.STAGING["storage_prefixes"],
        ):
            assert needle not in text, f"{path} contains staging name {needle}"


def test_azure_openai_defaults_off_and_opt_in_shape():
    openai = (FOUNDATION / "openai.tf").read_text()
    block = re.search(r'variable\s+"enable_azure_openai"\s*\{.*?\n\}', openai, re.S)
    assert block and re.search(r"default\s*=\s*false", block.group(0))
    assert re.search(r"enabled\s*=\s*var\.enable_azure_openai", openai)
    assert "refuses plans with this false" not in openai
    module_vars = (FOUNDATION / "modules/azure_openai/variables.tf").read_text()
    enabled = re.search(r'variable\s+"enabled"\s*\{.*?\}', module_vars, re.S)
    assert enabled and re.search(r"default\s*=\s*false", enabled.group(0))
    module = (FOUNDATION / "modules/azure_openai/main.tf").read_text()
    assert "gpt-4.1-dzus" in module
    assert "DataZoneStandard" in module
    assert "capacity = 1" in module
    assert not re.search(r"local_auth_enabled\s*=\s*false", module)
    assert "azurerm_role_assignment" not in module
    for match in re.finditer(r'resource\s+"[^"]+"\s+"[^"]+"\s*\{', module):
        start = match.end()
        depth = 1
        i = start
        while i < len(module) and depth:
            if module[i] == "{":
                depth += 1
            elif module[i] == "}":
                depth -= 1
            i += 1
        body = module[start:i]
        assert re.search(r"(count|for_each)\s*=\s*[^\n]*var\.enabled", body)


def test_compute_control_path_and_allow_extension():
    compute = (FOUNDATION / "compute.tf").read_text()
    assert 'control_path = "separate-release-ticket"' in compute
    assert "run-command" not in compute.lower()
    assert "allow_extension_operations      = true" in compute


def test_readme_secret_loading_dns_and_cto_labels():
    readme = (PROD / "README.md").read_text()
    assert "Load secrets into Key Vault" in readme
    assert "CTO decision, 11 Nov 2026" in readme
    assert "Approved temporary path" not in readme
    assert "needs CTO yes" not in readme
    assert "needs-CTO-yes" not in readme
    assert "option a" in readme.lower()
    assert "separate later" in readme.lower()
    assert "Names-only mapping" in readme
    assert "set -euo pipefail" not in readme.split("Load secrets into Key Vault", 1)[1].split(
        "## Later LLM cutover", 1
    )[0]
    assert "Press Ctrl-C once" in readme
    assert "second Ctrl-C does" in readme
    assert "detaches the wrapper" in readme
    assert "code **2**" in readme
    assert "logs/apply-*.log" in readme
    assert "Later LLM cutover" in readme
    assert "routes_runtime_traffic" in readme
    assert "Nothing in #356 touches DNS" in readme
    assert '"enable_azure_openai": false' in readme
    assert "inputs.optin.example.json" in readme
    assert "exact form the app ticket defines" in readme
    assert "account base URL alone is not" in readme
    secret = readme.split("Load secrets into Key Vault", 1)[1].split("## Later LLM cutover", 1)[0]
    assert "az keyvault secret set" not in secret
    assert "az keyvault update" not in secret
    cutover = readme.split("## Later LLM cutover", 1)[1]
    assert "az cognitiveservices account keys list" not in cutover
    assert "az vm run-command" not in readme.lower()


def test_secret_names_table_set_and_profile_align():
    dry_run.validate_secret_name_alignment((PROD / "README.md").read_text())


def test_inputs_examples_schema_and_no_secret_looking_values():
    for name, enabled in (("inputs.example.json", False), ("inputs.optin.example.json", True)):
        data = json.loads((PROD / name).read_text())
        assert data["enable_azure_openai"] is enabled
        blob = json.dumps(data)
        assert not re.search(r"sk_live_|sk_test_|-----BEGIN|password\s*=", blob, re.I)
        assert "AAAAOPENSSHPLACEHOLDER" in data["admin_ssh_public_key"]


def test_price_table_dual_totals_and_capacity_ceiling():
    prices = json.loads((PROD / "prices/monthly-estimate.json").read_text())
    assert prices["label"] == "estimate"
    assert dry_run.monthly_total(prices, include_openai=False) == 180.27
    assert dry_run.monthly_total(prices, include_openai=True) == 188.07
    notes = " ".join(prices["notes"])
    assert "43,800,000" in notes
    assert "$96" in notes and "$385" in notes
    assert "reviewer arithmetic" in notes.lower()
    assert any(item.get("requires") == "enable_azure_openai" for item in prices["line_items"])


def test_dry_run_offline_default_and_opt_in(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    for key in list(os.environ):
        if key.startswith(("ARM_", "TF_")) or key == "AZURE_CONFIG_DIR":
            monkeypatch.delenv(key, raising=False)
    off = subprocess.run(
        [sys.executable, str(PROD / "dry_run.py"), "--allow-no-provider"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert off.returncode == 0, off.stderr
    payload = json.loads(off.stdout)
    assert payload["params"]["enable_azure_openai"] is False
    assert payload["params"]["default_plan_monthly_usd"] == 180.27
    on = subprocess.run(
        [
            sys.executable,
            str(PROD / "dry_run.py"),
            "--enable-azure-openai",
            "--allow-no-provider",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert on.returncode == 0, on.stderr
    assert json.loads(on.stdout)["params"]["enable_azure_openai"] is True


def test_apply_refuses_without_confirm(tmp_path):
    script = REPO / "infra/beta/apply-cosmabot-prod-foundation.sh"
    result = subprocess.run(
        ["bash", str(script), "--private-dir", str(tmp_path / "never"), "--approval", str(tmp_path / "a.json")],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "refusing apply without --confirm-apply" in result.stderr


def test_plan_summary_refuses_delete_or_replace():
    boot = _load("cosmabot_prod_bootstrap", FOUNDATION / "bootstrap_local.py")
    summary = {
        "resource_changes": [
            {"type": "azurerm_resource_group", "change": {"actions": ["delete"]}},
        ]
    }
    with pytest.raises(Exception, match="delete or replace"):
        boot.sanitize_plan_summary(
            summary,
            inputs={
                "subscription_id": "00000000-0000-4000-8000-000000000001",
                "tenant_id": "00000000-0000-4000-8000-000000000002",
                "enable_azure_openai": False,
            },
            plan_sha256="a" * 64,
        )


def test_plan_summary_happy_path_counts():
    boot = _load("cosmabot_prod_bootstrap_summary", FOUNDATION / "bootstrap_local.py")
    plan = {
        "resource_changes": [
            {"type": "azurerm_resource_group", "change": {"actions": ["create"]}},
            {"type": "azurerm_linux_virtual_machine", "change": {"actions": ["create"]}},
        ]
    }
    out = boot.sanitize_plan_summary(
        plan,
        inputs={
            "subscription_id": "00000000-0000-4000-8000-000000000001",
            "tenant_id": "00000000-0000-4000-8000-000000000002",
            "enable_azure_openai": True,
        },
        plan_sha256="b" * 64,
    )
    assert out["create"]["azurerm_resource_group"] == 1
    assert out["enable_azure_openai"] is True
    assert out["plan_sha256"] == "b" * 64
    assert out["summary_sha256"]


def test_plan_summary_refuses_run_command_and_unlisted_extension():
    boot = _load("cosmabot_prod_bootstrap_run_cmd", FOUNDATION / "bootstrap_local.py")
    inputs = {
        "subscription_id": "00000000-0000-4000-8000-000000000001",
        "tenant_id": "00000000-0000-4000-8000-000000000002",
        "enable_azure_openai": False,
    }
    with pytest.raises(Exception, match="run_command|Run Command"):
        boot.sanitize_plan_summary(
            {
                "resource_changes": [
                    {
                        "type": "azurerm_virtual_machine_run_command",
                        "change": {"actions": ["create"], "after": {}},
                    }
                ]
            },
            inputs=inputs,
            plan_sha256="c" * 64,
        )
    with pytest.raises(Exception, match="unlisted VM extension|unlisted resource type"):
        boot.sanitize_plan_summary(
            {
                "resource_changes": [
                    {
                        "type": "azurerm_virtual_machine_extension",
                        "change": {
                            "actions": ["create"],
                            "after": {
                                "publisher": "Microsoft.Azure.Extensions",
                                "type": "CustomScript",
                            },
                        },
                    }
                ]
            },
            inputs=inputs,
            plan_sha256="d" * 64,
        )


def test_resource_type_allowlist_and_root_wiring():
    dry_run.validate_resource_type_allowlist()
    openai = (FOUNDATION / "openai.tf").read_text()
    assert re.search(r"enabled\s*=\s*var\.enable_azure_openai", openai)


def test_vm_extension_block_pin_and_forbidden_settings(tmp_path, monkeypatch):
    dry_run.validate_resource_type_allowlist()
    # .terraform noise must not fail dry_run (H4).
    terraform = PROD / ".terraform" / "providers" / "x"
    terraform.mkdir(parents=True, exist_ok=True)
    changelog = terraform / "CHANGELOG.md"
    changelog.write_text("mentions azurerm_virtual_machine_run_command for providers\n")
    try:
        dry_run.validate_no_run_command()
    finally:
        changelog.unlink(missing_ok=True)
        # best-effort cleanup of empty dirs
        for path in (terraform, terraform.parent, PROD / ".terraform"):
            try:
                path.rmdir()
            except OSError:
                break
    # Same text in a tracked prod .md must fail.
    tracked = PROD / "RUN_COMMAND_PROBE.md"
    tracked.write_text("azurerm_virtual_machine_run_command must never appear here\n")
    try:
        with pytest.raises(dry_run.DryRunError, match="run_command_forbidden"):
            dry_run.validate_no_run_command()
    finally:
        tracked.unlink(missing_ok=True)


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


def test_shell_hosting_checks(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    for key in list(os.environ):
        if key.startswith(("ARM_", "TF_")) or key == "AZURE_CONFIG_DIR":
            monkeypatch.delenv(key, raising=False)
    result = subprocess.run(
        ["bash", str(REPO / "infra/beta/tests/cosmabot-prod-hosting.sh")],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "cosmabot-prod-hosting shell checks passed" in result.stdout


def test_no_run_command_and_dns_guards():
    dry_run.validate_no_run_command()
    readme = (PROD / "README.md").read_text().lower()
    for needle in ("az network dns", "dns record set", "nsupdate", "cloudflare api"):
        assert needle not in readme
