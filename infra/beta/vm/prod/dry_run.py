#!/usr/bin/env python3
"""Offline dry-run render/validate for the CosmaBot production hosting profile.

Runnable in CI with no Azure credentials. Renders public params, checks name
guards, price table, recording-off, OpenAI default-off, and foundation source
shape. Optionally runs `tofu fmt -check` / `tofu validate` when tofu is present.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[3]
FOUNDATION = ROOT / "foundation"
sys.path.insert(0, str(ROOT))
from name_guards import (  # noqa: E402
    PRODUCTION,
    STAGING,
    NameGuardError,
    assert_production_inputs,
    assert_staging_inputs,
)


class DryRunError(RuntimeError):
    pass


def load_json(path: Path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise DryRunError(f"duplicate_json_key:{path.name}")
            result[key] = value
        return result

    return json.loads(path.read_text(), object_pairs_hook=unique)


def render_params(*, enable_azure_openai: bool = False) -> dict:
    profile = load_json(ROOT / "profile" / "runtime-public.json")
    prices = load_json(ROOT / "prices" / "monthly-estimate.json")
    if not isinstance(enable_azure_openai, bool):
        raise DryRunError("enable_azure_openai_must_be_bool")
    params = {
        "environment": "production",
        "resource_group": PRODUCTION["resource_group"],
        "vm_name": PRODUCTION["vm_name"],
        "location": "eastus2",
        "vm_size": "Standard_D2s_v5",
        "web_host": PRODUCTION["web_host"],
        "api_host": PRODUCTION["api_host"],
        "acr_prefix": PRODUCTION["acr_prefix"],
        "key_vault_prefix": PRODUCTION["key_vault_prefix"],
        "storage_prefixes": list(PRODUCTION["storage_prefixes"]),
        "state_namespace": PRODUCTION["state_namespace"],
        "enable_azure_openai": enable_azure_openai,
        "dns_proxy": False,
        "clerk_secret_names_only": profile["runtime"]["secret_names"],
        "real_patient_recording_enabled": profile["runtime"]["environment"][
            "REAL_PATIENT_RECORDING_ENABLED"
        ],
        "workspace_llm_backend": profile["runtime"]["environment"]["WORKSPACE_LLM_BACKEND"],
        "workspace_llm_deployment": profile["runtime"]["environment"]["WORKSPACE_LLM_DEPLOYMENT"],
        "price_date": prices["price_date"],
        "price_label": prices["label"],
    }
    return {"params": params, "profile": profile, "prices": prices}


def monthly_total(prices: dict, *, include_openai: bool = True) -> float:
    amount = 0.0
    for item in prices["line_items"]:
        if not include_openai and item.get("requires") == "enable_azure_openai":
            continue
        amount += float(item["monthly_usd"])
    return round(amount, 2)


def validate_rendered(bundle: dict) -> None:
    params = bundle["params"]
    profile = bundle["profile"]
    prices = bundle["prices"]
    assert_production_inputs(
        {
            "resource_group": params["resource_group"],
            "vm_name": params["vm_name"],
            "web_host": params["web_host"],
            "api_host": params["api_host"],
            "acr_prefix": params["acr_prefix"],
            "key_vault_prefix": params["key_vault_prefix"],
            "state_namespace": params["state_namespace"],
            **{f"storage_{i}": name for i, name in enumerate(params["storage_prefixes"])},
        }
    )
    with _expect(NameGuardError):
        assert_production_inputs({"resource_group": STAGING["resource_group"]})
    with _expect(NameGuardError):
        assert_staging_inputs({"resource_group": PRODUCTION["resource_group"]})
    with _expect(NameGuardError):
        assert_staging_inputs({"web_host": PRODUCTION["web_host"]})
    with _expect(NameGuardError):
        assert_production_inputs({"acr_prefix": STAGING["acr_prefix"]})

    if params["real_patient_recording_enabled"] != "false":
        raise DryRunError("real_patient_recording_must_stay_false")
    if profile["runtime"]["environment"]["REAL_PATIENT_RECORDING_ENABLED"] != "false":
        raise DryRunError("profile_recording_must_stay_false")
    # Code/profile default stays false. Opt-in is only via John's inputs at plan time.
    if profile["azure_openai_module"]["enabled_by_default"] is not False:
        raise DryRunError("azure_openai_profile_must_default_off")
    if params["enable_azure_openai"] is False:
        pass
    elif params["enable_azure_openai"] is True:
        validate_openai_opt_in_source()
    else:
        raise DryRunError("azure_openai_flag_must_be_bool")
    if params["workspace_llm_backend"] != "azure_gpt41":
        raise DryRunError("model_backend_must_match_staging")
    if params["workspace_llm_deployment"] != "gpt-4.1":
        raise DryRunError("model_deployment_must_stay_gpt41")
    if "WORKSPACE_LLM_ENDPOINT" in profile["runtime"]["environment"]:
        raise DryRunError("workspace_llm_endpoint_must_be_absent_until_optin")
    if profile["runtime"]["environment"].get("WORKSPACE_LLM_USDZ_ENABLED") != "false":
        raise DryRunError("usdz_must_default_false_in_profile")
    if "cosmas" + "code" in json.dumps(profile).lower():
        raise DryRunError("prod_must_not_reference_shared_model_account")
    if "CLERK_SECRET_KEY" not in params["clerk_secret_names_only"]:
        raise DryRunError("clerk_secret_name_required")
    # No secret values may appear in the checked-in profile.
    blob = json.dumps(profile)
    if re.search(r"sk_live_|sk_test_|pk_live_[A-Za-z0-9]{10,}", blob):
        raise DryRunError("clerk_secret_values_forbidden")
    if prices["label"] != "estimate" or not prices.get("price_date"):
        raise DryRunError("price_table_must_be_labeled_estimate_with_date")
    default_total = monthly_total(prices, include_openai=False)
    optin_total = monthly_total(prices, include_openai=True)
    if default_total <= 0 or optin_total <= 0:
        raise DryRunError("price_total_invalid")
    if abs(default_total - 180.27) > 0.001 or abs(optin_total - 188.07) > 0.001:
        raise DryRunError("price_totals_must_match_checked_in_envelope")
    params["estimated_monthly_total_usd"] = optin_total
    params["default_plan_monthly_usd"] = default_total
    params["openai_optin_monthly_usd"] = optin_total
    params["exceeds_300"] = max(default_total, optin_total) > float(
        prices["warning_threshold_usd"]
    )


def validate_openai_opt_in_source() -> None:
    """When enable_azure_openai is true, require the reviewed opt-in resource shape."""
    openai = (FOUNDATION / "openai.tf").read_text()
    module = (FOUNDATION / "modules/azure_openai/main.tf").read_text()
    block = re.search(
        r'variable\s+"enable_azure_openai"\s*\{.*?\n\}',
        openai,
        re.S,
    )
    if not block or not re.search(r"default\s*=\s*false", block.group(0)):
        raise DryRunError("openai_module_must_default_false")
    for needle in (
        '"gpt-4.1-dzus"',
        '"2025-04-14"',
        '"DataZoneStandard"',
        "capacity = 10",
        '"privatelink.openai.azure.com"',
        "public_network_access_enabled = false",
        'subresource_names              = ["account"]',
        "azurerm_cognitive_deployment",
        "azurerm_private_endpoint",
    ):
        if needle not in module:
            raise DryRunError(f"openai_opt_in_source_missing:{needle}")
    if re.search(r"local_auth_enabled\s*=\s*false", module):
        raise DryRunError("openai_must_keep_local_key_auth")
    if 'role_definition_name             = "Cognitive Services OpenAI User"' in module:
        raise DryRunError("openai_must_not_grant_runtime_mi_role")
    if "runtime_principal_id" in (FOUNDATION / "modules/azure_openai/variables.tf").read_text():
        raise DryRunError("openai_must_not_grant_runtime_mi_role")


class _expect:
    def __init__(self, exc_type):
        self.exc_type = exc_type

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            raise DryRunError(f"expected_{self.exc_type.__name__}")
        return issubclass(exc_type, self.exc_type)


def validate_foundation_source() -> None:
    text = "\n".join(
        path.read_text()
        for path in sorted(FOUNDATION.rglob("*"))
        if path.is_file()
        and path.suffix in {".tf", ".py", ".hcl"}
        and "tests" not in path.parts
    )
    for needle in (
        STAGING["resource_group"],
        STAGING["vm_name"],
        STAGING["web_host"],
        STAGING["acr_prefix"],
        STAGING["key_vault_prefix"],
        STAGING["state_namespace"],
        *STAGING["storage_prefixes"],
    ):
        if needle in text:
            raise DryRunError(f"production_source_contains_staging_name:{needle}")
    for needle in (
        PRODUCTION["resource_group"],
        PRODUCTION["vm_name"],
        PRODUCTION["acr_prefix"],
        PRODUCTION["key_vault_prefix"],
        PRODUCTION["state_namespace"],
        "stcbotprd",
    ):
        if needle not in text:
            raise DryRunError(f"production_source_missing_required_name:{needle}")
    if 'stcbotprd${each.key == "application" ? "app" : "bak"}' not in text:
        raise DryRunError("production_storage_name_template_missing")
    openai = (FOUNDATION / "openai.tf").read_text()
    block = re.search(
        r'variable\s+"enable_azure_openai"\s*\{.*?\n\}',
        openai,
        re.S,
    )
    if not block or not re.search(r"default\s*=\s*false", block.group(0)):
        raise DryRunError("openai_module_must_default_false")
    if "refuses plans with this false" in openai or "must set true" in openai.lower():
        raise DryRunError("openai_must_not_refuse_default_false_plan")
    if 'module "azure_openai"' not in openai:
        raise DryRunError("openai_must_be_separate_module")
    # Opt-in resources exist behind count; default plan still creates none.
    validate_openai_opt_in_source()
    for path in ROOT.rglob("*.tf"):
        if "azurerm_key_vault_secret" in path.read_text():
            raise DryRunError(f"key_vault_secret_resource_forbidden:{path}")
    readme = (ROOT / "README.md").read_text()
    if "Load secrets (release operator, after apply, before any runtime start)" not in readme:
        raise DryRunError("readme_secret_loading_section_missing")
    secret = readme.split("Load secrets", 1)[1].split("## DNS", 1)[0]
    if "--file" not in secret:
        raise DryRunError("readme_secret_loading_must_use_file_not_value")
    # Forbid command forms that pass a secret via --value= / --value <secret>
    if re.search(r"--value(=|\s+\S)", secret):
        raise DryRunError("readme_secret_loading_must_use_file_not_value")
    if "cosmas" + "code" in readme.lower():
        raise DryRunError("prod_readme_must_not_reference_shared_model_account")
    dns_section = readme.split("## DNS", 1)[1].split("## ", 1)[0]
    for needle in ("az network dns", "dns record", "nsupdate", "cloudflare", "TTL"):
        if needle.lower() in dns_section.lower() and "separate later ticket" not in dns_section:
            raise DryRunError("dns_section_must_not_change_records")
    if "Nothing in #356 touches DNS" not in dns_section:
        raise DryRunError("dns_one_liner_missing")
    staging_foundation = REPO / "infra/beta/vm/foundation"
    staging_text = "\n".join(
        path.read_text()
        for path in sorted(staging_foundation.rglob("*"))
        if path.is_file() and path.suffix in {".tf", ".py", ".hcl"}
    )
    for needle in (
        PRODUCTION["resource_group"],
        PRODUCTION["vm_name"],
        PRODUCTION["web_host"],
        PRODUCTION["acr_prefix"],
        PRODUCTION["key_vault_prefix"],
        PRODUCTION["state_namespace"],
        *PRODUCTION["storage_prefixes"],
    ):
        if needle in staging_text:
            raise DryRunError(f"staging_source_contains_production_name:{needle}")


def tofu_offline_validate(*, allow_no_provider: bool = False) -> dict:
    tofu = shutil.which("tofu")
    if not tofu:
        return {"tofu": "absent", "fmt": None, "validate": None, "skipped": True}
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("TF_", "ARM_")) and key != "AZURE_CONFIG_DIR"
    }
    fmt = subprocess.run(
        [tofu, "fmt", "-check", "-recursive", str(FOUNDATION)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if fmt.returncode != 0:
        raise DryRunError(f"tofu_fmt_failed:{fmt.stdout}{fmt.stderr}")
    with tempfile.TemporaryDirectory(prefix="cosmabot-prod-dry-run-") as tmp:
        key = Path(tmp) / "encryption.passphrase"
        key.write_text("synthetic-production-foundation-encryption-fixture-never-live\n")
        key.chmod(0o600)
        data_dir = Path(tmp) / "tofu-data"
        data_dir.mkdir()
        run_env = dict(env)
        run_env.update(
            {
                "TF_DATA_DIR": str(data_dir),
                "TF_IN_AUTOMATION": "1",
                "TF_INPUT": "0",
                "TF_VAR_bootstrap_key_file": str(key),
            }
        )
        init = subprocess.run(
            [tofu, "init", "-backend=false", "-input=false", "-lockfile=readonly"],
            cwd=FOUNDATION,
            capture_output=True,
            text=True,
            env=run_env,
            check=False,
        )
        if init.returncode != 0:
            if not allow_no_provider:
                raise DryRunError(f"tofu_init_failed:{init.stderr[-500:]}")
            return {
                "tofu": tofu,
                "fmt": "ok",
                "validate": "skipped_provider_unavailable",
                "skipped": False,
                "init_stderr_tail": init.stderr[-500:],
            }
        validate = subprocess.run(
            [tofu, "validate", "-no-color"],
            cwd=FOUNDATION,
            capture_output=True,
            text=True,
            env=run_env,
            check=False,
        )
        if validate.returncode != 0:
            raise DryRunError(f"tofu_validate_failed:{validate.stdout}{validate.stderr}")
        return {"tofu": tofu, "fmt": "ok", "validate": "ok", "skipped": False}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    enable_openai = False
    allow_no_provider = False
    while args:
        if args[0] == "--enable-azure-openai":
            enable_openai = True
            args = args[1:]
        elif args[0] == "--allow-no-provider":
            allow_no_provider = True
            args = args[1:]
        else:
            print(
                "cosmabot_prod_dry_run_refused:usage_python3_dry_run.py_[--enable-azure-openai]_[--allow-no-provider]",
                file=sys.stderr,
            )
            return 1
    try:
        bundle = render_params(enable_azure_openai=enable_openai)
        validate_rendered(bundle)
        validate_foundation_source()
        tofu = tofu_offline_validate(allow_no_provider=allow_no_provider)
        result = {
            "dry_run": True,
            "azure_calls": False,
            "params": bundle["params"],
            "estimated_monthly_total_usd": bundle["params"]["estimated_monthly_total_usd"],
            "price_date": bundle["prices"]["price_date"],
            "price_label": bundle["prices"]["label"],
            "exceeds_300_warning": bundle["params"]["exceeds_300"],
            "tofu": tofu,
        }
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0
    except (DryRunError, NameGuardError, OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"cosmabot_prod_dry_run_refused:{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
