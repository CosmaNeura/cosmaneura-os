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
    if params["workspace_llm_backend"] != "disabled":
        raise DryRunError("workspace_llm_backend_must_be_disabled_until_cutover")
    if params["workspace_llm_deployment"] != "gpt-4.1":
        raise DryRunError("model_deployment_must_stay_gpt41")
    if "WORKSPACE_LLM_ENDPOINT" in profile["runtime"]["environment"]:
        raise DryRunError("workspace_llm_endpoint_must_be_absent_until_cutover")
    if profile["runtime"]["environment"].get("WORKSPACE_LLM_USDZ_ENABLED") != "false":
        raise DryRunError("usdz_must_default_false_in_profile")
    if profile["azure_openai_module"].get("routes_runtime_traffic") is not False:
        raise DryRunError("routes_runtime_traffic_must_be_false")
    if profile["azure_openai_module"].get("first_apply_capacity") != 1:
        raise DryRunError("first_apply_capacity_must_be_1")
    if "WORKSPACE_LLM_API_KEY" in profile["runtime"]["secret_names"]:
        raise DryRunError("workspace_llm_api_key_must_wait_for_cutover")
    if "dns" in profile:
        raise DryRunError("profile_must_not_declare_dns_records")
    if "cosmas" + "code" in json.dumps(profile).lower():
        raise DryRunError("prod_must_not_reference_shared_model_account")
    expected_secrets = {
        "CLERK_SECRET_KEY",
        "CLERK_ACCOUNT_DELETION_SECRET",
        "DATABASE_PASSWORD",
        "POSTGRES_PASSWORD",
        "REDIS_PASSWORD",
        "HUMAN_DEPLOY_EVIDENCE_REF",
    }
    if set(profile["runtime"]["secret_names"]) != expected_secrets:
        raise DryRunError("secret_names_must_match_first_apply_set")
    if "CLERK_SECRET_KEY" not in params["clerk_secret_names_only"]:
        raise DryRunError("clerk_secret_name_required")
    # No secret values may appear in the checked-in profile.
    blob = json.dumps(profile)
    if re.search(r"sk_live_|sk_test_|pk_live_[A-Za-z0-9]{10,}", blob):
        raise DryRunError("clerk_secret_values_forbidden")
    if prices["label"] != "estimate" or not prices.get("price_date"):
        raise DryRunError("price_table_must_be_labeled_estimate_with_date")
    notes_blob = " ".join(prices.get("notes", []))
    if "43,800,000" not in notes_blob and "43800000" not in json.dumps(prices):
        raise DryRunError("price_notes_must_state_capacity_1_token_ceiling")
    if "$96" not in notes_blob or "$385" not in notes_blob or "reviewer arithmetic" not in notes_blob.lower():
        raise DryRunError("price_notes_must_state_saturation_dollar_range")
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
        "capacity = 1",
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
    if "azurerm_role_assignment" in module:
        raise DryRunError("openai_must_not_grant_runtime_mi_role")
    if "runtime_principal_id" in (FOUNDATION / "modules/azure_openai/variables.tf").read_text():
        raise DryRunError("openai_must_not_grant_runtime_mi_role")
    # Every resource block must gate on the enable variable via count/for_each.
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
        if not re.search(r"(count|for_each)\s*=\s*[^\n]*var\.enabled", body):
            raise DryRunError("openai_resource_missing_enable_gate")


class _expect:
    def __init__(self, exc_type):
        self.exc_type = exc_type

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            raise DryRunError(f"expected_{self.exc_type.__name__}")
        return issubclass(exc_type, self.exc_type)


def validate_secret_name_alignment(readme: str) -> None:
    """Table rows and profile secret_names must match 1:1 (no runnable set block in #356)."""
    profile = load_json(ROOT / "profile" / "runtime-public.json")
    secret_names = set(profile["runtime"]["secret_names"])
    table = readme.split("Names-only mapping", 1)[1].split("## ", 1)[0]
    host_files: set[str] = set()
    kv_from_table: set[str] = set()
    for line in table.splitlines():
        if not line.startswith("|") or line.startswith("| ---") or "Key Vault secret name" in line:
            continue
        cells = [cell.strip().strip("`") for cell in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        kv_name, host_name = cells[0], cells[1]
        if not kv_name or not host_name:
            continue
        kv_from_table.add(kv_name.replace("-", "_"))
        host_files.add(host_name)
    secret_section = readme.split("Load secrets into Key Vault", 1)[1].split("## Later LLM cutover", 1)[0]
    if re.search(r"```(?:bash|sh)?\s*\n", secret_section) and re.search(
        r"az\s+keyvault\s+secret\s+set", secret_section
    ):
        raise DryRunError("readme_must_not_contain_runnable_key_vault_load_block")
    if "az keyvault secret set" in secret_section or "az keyvault update" in secret_section:
        raise DryRunError("readme_must_not_contain_runnable_key_vault_load_block")
    if host_files != secret_names:
        raise DryRunError(f"secret_table_host_files_mismatch:{sorted(host_files ^ secret_names)}")
    if kv_from_table != secret_names:
        raise DryRunError(f"secret_table_kv_mismatch:{sorted(kv_from_table ^ secret_names)}")


ALLOWED_RESOURCE_TYPES = frozenset(
    {
        "azurerm_cognitive_account",
        "azurerm_cognitive_deployment",
        "azurerm_container_registry",
        "azurerm_key_vault",
        "azurerm_linux_virtual_machine",
        "azurerm_log_analytics_workspace",
        "azurerm_managed_disk",
        "azurerm_monitor_action_group",
        "azurerm_monitor_data_collection_rule",
        "azurerm_monitor_data_collection_rule_association",
        "azurerm_monitor_metric_alert",
        "azurerm_monitor_scheduled_query_rules_alert_v2",
        "azurerm_network_interface",
        "azurerm_network_security_group",
        "azurerm_private_dns_zone",
        "azurerm_private_dns_zone_virtual_network_link",
        "azurerm_private_endpoint",
        "azurerm_public_ip",
        "azurerm_resource_group",
        "azurerm_role_assignment",
        "azurerm_storage_account",
        "azurerm_storage_container",
        "azurerm_subnet",
        "azurerm_subnet_network_security_group_association",
        "azurerm_user_assigned_identity",
        "azurerm_virtual_machine_data_disk_attachment",
        "azurerm_virtual_machine_extension",
        "azurerm_virtual_network",
        "terraform_data",
    }
)


def _rel_parts(path: Path, root: Path = ROOT) -> tuple[str, ...]:
    try:
        return path.resolve().relative_to(root.resolve()).parts
    except ValueError:
        return path.parts


def _skip_scan_path(path: Path, root: Path = ROOT) -> bool:
    return any(part in {".terraform", ".git", "tests"} for part in _rel_parts(path, root))


def _resource_blocks(text: str):
    for match in re.finditer(r'^\s*resource\s+"([^"]+)"\s+"([^"]+)"\s*\{', text, re.M):
        start = match.end()
        depth = 1
        i = start
        while i < len(text) and depth:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        yield match.group(1), match.group(2), text[start : i - 1], match.start()


def validate_resource_type_allowlist() -> None:
    """Pin foundation/*.tf and modules/** resource TYPE set; pin the sole VM extension."""
    for path in sorted(ROOT.rglob("*.tf.json")):
        if path.is_file() and not _skip_scan_path(path):
            raise DryRunError(f"tf_json_forbidden:{path}")
    found: set[str] = set()
    extensions: list[tuple[Path, str, str]] = []
    for path in sorted(FOUNDATION.rglob("*.tf")):
        if _skip_scan_path(path, FOUNDATION):
            continue
        text = path.read_text()
        for rtype, name, body, _ in _resource_blocks(text):
            found.add(rtype)
            if rtype == "azurerm_virtual_machine_extension":
                extensions.append((path, name, body))
    if found != ALLOWED_RESOURCE_TYPES:
        raise DryRunError(
            f"resource_type_allowlist_mismatch:extra={sorted(found - ALLOWED_RESOURCE_TYPES)};"
            f"missing={sorted(ALLOWED_RESOURCE_TYPES - found)}"
        )
    if len(extensions) != 1:
        raise DryRunError(f"vm_extension_count_must_be_one:{len(extensions)}")
    path, name, body = extensions[0]
    if path.name != "runtime_monitoring.tf" or name != "health":
        raise DryRunError(f"vm_extension_must_be_health_in_runtime_monitoring:{path.name}:{name}")
    if not re.search(r'(?m)^\s*publisher\s*=\s*"Microsoft\.Azure\.Monitor"\s*$', body):
        raise DryRunError("vm_extension_must_use_azure_monitor_publisher")
    if not re.search(r'(?m)^\s*type\s*=\s*"AzureMonitorLinuxAgent"\s*$', body):
        raise DryRunError("vm_extension_must_be_azure_monitor_linux_agent")
    for path in sorted(ROOT.rglob("*.tf")):
        if not path.is_file() or _skip_scan_path(path):
            continue
        text = path.read_text()
        for needle in ("CustomScript", "commandToExecute", "protected_settings", "fileUris"):
            if needle in text:
                raise DryRunError(f"vm_extension_forbidden_setting:{path}:{needle}")


def _allowed_transport_mention_lines() -> frozenset[str]:
    """Exact stripped lines allowed to mention the forbid pattern (built without contiguous needles)."""
    u = "run" + "_command"
    h = "run" + "-command"
    sp = "run" + " command"
    return frozenset(
        {
            # foundation/bootstrap_local.py refusal lines
            f'if rtype == "azurerm_virtual_machine_{u}":',
            'raise Refused("Plan contains azurerm_virtual_machine_'
            + u
            + "; "
            + "Run"
            + " Command is forbidden\")",
            # dry_run.py pattern / message lines
            '"""Forbid '
            + "Run"
            + ' Command transports; allow only forbid-sentences in README/profile and pinned self-refs."""',
            "def validate_no_" + u + "() -> None:",
            'pattern = re.compile(r"run[-_ ]?command", re.I)',
            'or "not ' + sp + '" in lowered',
            'or "no ' + sp + '" in lowered',
            'raise DryRunError(f"' + u + '_forbidden:{path}:{line_no}:{line.strip()[:120]}")',
            'raise DryRunError(f"' + u + '_forbidden:{path}:extra_py_sh:{pat}")',
            'raise DryRunError(f"' + u + '_forbidden:{path}:az_vm_adjacent")',
            "validate_no_" + u + "()",
            "if stripped in pinned:",
            "if re.search(pat, line, re.I) and line.strip() not in pinned:",
            "extra = (",
            "pinned = _allowed_transport_mention_lines()",
        }
    )


def validate_no_run_command() -> None:
    """Forbid Run Command transports; allow only forbid-sentences in README/profile and pinned self-refs."""
    paths = [
        *ROOT.rglob("*.tf"),
        *ROOT.rglob("*.py"),
        *ROOT.rglob("*.sh"),
        *ROOT.rglob("*.md"),
        *ROOT.rglob("*.json"),
        REPO / "infra/beta/review-cosmabot-prod-foundation.sh",
        REPO / "infra/beta/apply-cosmabot-prod-foundation.sh",
    ]
    pattern = re.compile(r"run[-_ ]?command", re.I)
    pinned = _allowed_transport_mention_lines()
    h = "run" + "-command"
    extra = (
        h + r"\s+invoke",
        r"invoke[^\n]*--scripts",
        r"--scripts[^\n]*install-secrets",
    )
    for path in paths:
        if not path.is_file():
            continue
        if path.resolve().is_relative_to(ROOT.resolve()):
            if _skip_scan_path(path, ROOT):
                continue
        elif "tests" in path.parts:
            continue
        text = path.read_text()
        for line_no, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped in pinned:
                continue
            if not pattern.search(line):
                continue
            lowered = line.lower()
            allowed = (
                "must never" in lowered
                or "never be used" in lowered
                or "forbid" in lowered
                or "forbidden" in lowered
                or "not run command" in lowered
                or "no run command" in lowered
            )
            if path.name in {"README.md", "runtime-public.json"} and allowed:
                continue
            raise DryRunError(f"run_command_forbidden:{path}:{line_no}:{line.strip()[:120]}")
        if path.suffix in {".py", ".sh"} and path.name != "dry_run.py":
            for pat in extra:
                for line in text.splitlines():
                    if re.search(pat, line, re.I) and line.strip() not in pinned:
                        raise DryRunError(f"run_command_forbidden:{path}:extra_py_sh:{pat}")
        if path.name == "bootstrap_local.py" and re.search(
            r'["\']az["\']\s*,\s*["\']vm["\']', text
        ):
            raise DryRunError(f"run_command_forbidden:{path}:az_vm_adjacent")

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
    if not re.search(r"enabled\s*=\s*var\.enable_azure_openai", openai):
        raise DryRunError("openai_module_call_must_pass_enabled_var")
    module_vars = (FOUNDATION / "modules/azure_openai/variables.tf").read_text()
    enabled_var = re.search(r'variable\s+"enabled"\s*\{.*?\}', module_vars, re.S)
    if not enabled_var or not re.search(r"default\s*=\s*false", enabled_var.group(0)):
        raise DryRunError("openai_module_enabled_default_must_be_false")
    # Opt-in resources exist behind count; default plan still creates none.
    validate_openai_opt_in_source()
    validate_resource_type_allowlist()
    for path in ROOT.rglob("*.tf"):
        if "azurerm_key_vault_secret" in path.read_text():
            raise DryRunError(f"key_vault_secret_resource_forbidden:{path}")
    readme = (ROOT / "README.md").read_text()
    if "Load secrets into Key Vault" not in readme:
        raise DryRunError("readme_secret_loading_section_missing")
    if "CTO decision, 11 Nov 2026" not in readme:
        raise DryRunError("readme_must_cite_cto_decision_date")
    if "Approved temporary path" in readme:
        raise DryRunError("readme_must_not_use_approved_temporary_path_label")
    if "needs CTO yes" in readme or "needs-CTO-yes" in readme:
        raise DryRunError("readme_must_not_use_needs_cto_yes_label")
    secret = readme.split("Load secrets into Key Vault", 1)[1].split("## Later LLM cutover", 1)[0]
    if "option a" not in secret.lower() and "(option a)" not in secret.lower():
        raise DryRunError("readme_must_keep_option_a_description")
    if "separate later" not in secret.lower() and "separate later ticket" not in readme.lower():
        raise DryRunError("readme_must_state_host_install_is_later_ticket")
    if "Names-only mapping" not in secret and "Names-only mapping" not in readme:
        raise DryRunError("readme_must_keep_secret_names_table")
    if "POSTGRES-PASSWORD" not in secret or "REDIS-PASSWORD" not in secret:
        raise DryRunError("readme_secret_table_must_list_postgres_and_redis")
    if "Press Ctrl-C once" not in readme:
        raise DryRunError("readme_apply_must_document_ctrl_c_and_logs")
    if "detaches the wrapper" not in readme:
        raise DryRunError("readme_apply_must_document_second_ctrl_c_detaches")
    if "logs/apply-*.log" not in readme:
        raise DryRunError("readme_apply_must_document_apply_log_path")
    if "code **2**" not in readme and "code 2" not in readme.lower():
        raise DryRunError("readme_apply_must_document_exit_code_2")
    if "routes_runtime_traffic" not in readme or "false" not in readme:
        raise DryRunError("readme_must_state_routes_runtime_traffic_false")
    if "Later LLM cutover" not in readme:
        raise DryRunError("readme_must_document_llm_cutover_list")
    cutover = readme.split("## Later LLM cutover", 1)[1]
    if "az cognitiveservices account keys list" in cutover or "az keyvault secret set" in cutover:
        raise DryRunError("readme_cutover_must_not_contain_key_command_block")
    if "account base URL alone is not" not in cutover and "exact form the app ticket defines" not in cutover:
        raise DryRunError("readme_cutover_step2_must_require_app_ticket_form")
    validate_secret_name_alignment(readme)
    if "cosmas" + "code" in readme.lower() and "never be loaded" not in readme.lower():
        raise DryRunError("prod_readme_must_not_reference_shared_model_account")
    # Whole-README / profile / scripts DNS mutation scan (no "later ticket" escape).
    dns_needles = (
        "az network dns",
        "dns record set",
        "nsupdate",
        "cloudflare api",
        "update the beta.cosmas.ai",
        "A records at the DNS provider",
    )
    scan_targets = [
        readme,
        (ROOT / "profile" / "runtime-public.json").read_text(),
        (REPO / "infra/beta/review-cosmabot-prod-foundation.sh").read_text(),
        (REPO / "infra/beta/apply-cosmabot-prod-foundation.sh").read_text(),
    ]
    for text in scan_targets:
        lowered = text.lower()
        for needle in dns_needles:
            if needle.lower() in lowered:
                raise DryRunError(f"dns_record_change_wording_forbidden:{needle}")
    if "## DNS" not in readme or "Nothing in #356 touches DNS" not in readme:
        raise DryRunError("dns_one_liner_missing")
    validate_no_run_command()
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
