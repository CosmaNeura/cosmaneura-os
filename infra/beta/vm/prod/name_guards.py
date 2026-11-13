"""Refuse cross-environment CosmaBot VM hosting names.

Production profile refuses staging names; staging profile refuses production
names. Staging IaC under infra/beta/vm/foundation stays untouched; this module
encodes both allowlists for review/apply/dry-run and for tests.
"""

from __future__ import annotations

from collections.abc import Iterable

STAGING = {
    "profile": "staging",
    "resource_group": "rg-cosmas-os-vm-staging-eus2-lab01",
    "vm_name": "vm-cosmabot-staging-eus2-lab01",
    "web_host": "staging.cosmas.ai",
    "api_host": "api.staging.cosmas.ai",
    "acr_prefix": "acrcbotstgeus2",
    "key_vault_prefix": "kv-cbot-stg-",
    "storage_prefixes": ("stcbotapp", "stcbotbak"),
    "state_namespace": "cosmabot-vm/eastus2/lab01/local-initial",
}

PRODUCTION = {
    "profile": "production",
    "resource_group": "rg-cosmabot-prod-eus2-01",
    "vm_name": "vm-cosmabot-prod-eus2-01",
    "web_host": "beta.cosmas.ai",
    "api_host": "api.beta.cosmas.ai",
    "acr_prefix": "acrcbotprdeus2",
    "key_vault_prefix": "kv-cbot-prd-",
    "storage_prefixes": ("stcbotprdapp", "stcbotprdbak"),
    "state_namespace": "cosmabot-vm/eastus2/prod01/local-initial",
}

PROFILES = {"staging": STAGING, "production": PRODUCTION}


class NameGuardError(ValueError):
    pass


def _lower(value: str) -> str:
    return value.strip().lower()


def forbidden_needles(profile: str) -> list[str]:
    if profile not in PROFILES:
        raise NameGuardError(f"unknown_profile:{profile}")
    other = PRODUCTION if profile == "staging" else STAGING
    return [
        _lower(other["resource_group"]),
        _lower(other["vm_name"]),
        _lower(other["web_host"]),
        _lower(other["api_host"]),
        _lower(other["acr_prefix"]),
        _lower(other["key_vault_prefix"]),
        _lower(other["state_namespace"]),
        *(_lower(item) for item in other["storage_prefixes"]),
    ]


def refuse_cross_environment(profile: str, candidates: Iterable[str]) -> None:
    """Refuse when any candidate equals or embeds the other environment's names."""
    needles = forbidden_needles(profile)
    for raw in candidates:
        if not isinstance(raw, str) or not raw:
            continue
        value = _lower(raw)
        for needle in needles:
            if value == needle or needle in value:
                raise NameGuardError(
                    f"{profile}_refuses_cross_environment_name:{needle}"
                )


def assert_production_inputs(inputs: dict) -> None:
    """Production prepare/review: refuse staging coordinates in reviewed inputs."""
    refuse_cross_environment(
        "production",
        [str(value) for value in inputs.values() if isinstance(value, str)],
    )


def assert_staging_inputs(inputs: dict) -> None:
    """Staging profile helper: refuse production coordinates (tests + review)."""
    refuse_cross_environment(
        "staging",
        [str(value) for value in inputs.values() if isinstance(value, str)],
    )
