#!/usr/bin/env python3
"""Bind current workload verification to protected saved-plan/apply evidence.

The protected runner renders plan_json with its pinned tofu from the exact plan
bytes and rechecks the existing critical/security review projections first.
This helper never accepts expected runtime values from its environment or ARM.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

import validate_workload_attestation as attestation
import workload_verification as workload

UTC = timezone.utc  # noqa: UP017 -- protected runner uses Python 3.10.
HASH = re.compile(r"^[0-9a-f]{64}$")
INPUTS = (
    "plan",
    "plan_json",
    "review",
    "var_file",
    "apply_result",
    "state",
    "bootstrap_outputs",
    "build_evidence",
    "provider_lock",
)
PUBLIC_NAMES = frozenset(
    "CORE_CAPTURE_ORIGIN CORE_CAPTURE_SCOPE CORE_WEB_ORIGIN CORE_CONNECTION_TENANT_REF WORKSPACE_CAPTURE_BACKEND WORKSPACE_LLM_BACKEND SCHEDULING_ORIGIN SCHEDULING_GOOGLE_CLIENT_ID SCHEDULING_ENROLLMENT_PRACTICE_ID GOOGLE_CONNECTION_CLIENT_ID MICROSOFT_CONNECTION_TENANT_ID MICROSOFT_CONNECTION_CLIENT_ID RESEARCH_SOURCES RESEARCH_DATASET_MAPPINGS".split()
)
SECRET_NAMES = frozenset(
    "SCHEDULING_GOOGLE_CLIENT_SECRET SCHEDULING_LOGIN_ENCRYPTION_KEY GOOGLE_CONNECTION_CLIENT_SECRET GOOGLE_CONNECTION_ENCRYPTION_KEY MICROSOFT_CONNECTION_CLIENT_SECRET MICROSOFT_CONNECTION_ENCRYPTION_KEY WORKSPACE_LLM_API_KEY RESEARCH_OPENFDA_API_KEY".split()
)
FEATURE_NAMES = frozenset(
    "WORKSPACE_AI_ACTIVITY_ENABLED WORKSPACE_TEAM_SETUP_ENABLED WORKSPACE_ROUTINES_ENABLED WORKSPACE_RESEARCH_ENABLED WORKSPACE_RESEARCH_IO_ENABLED WORKSPACE_CORE_RECORD_ENABLED WORKSPACE_CORE_CONNECTION_ENABLED WORKSPACE_CORE_APPOINTMENT_SETUP_ENABLED WORKSPACE_ATHENA_CONNECTION_ENABLED WORKSPACE_ATHENA_VISIT_LINK_ENABLED WORKSPACE_PREP_ENABLED WORKSPACE_PREP_WORK_ENABLED WORKSPACE_APPOINTMENTS_ENABLED WORKSPACE_CAPTURE_NOTES_ENABLED WORKSPACE_CAPTURE_CORRECTIONS_ENABLED WORKSPACE_CAPTURE_RECOVERY_ENABLED WORKSPACE_CAPTURE_SOURCE_ENABLED WORKSPACE_CAPTURE_LONG_VISITS_ENABLED WORKSPACE_SCHEDULING_ENABLED WORKSPACE_SCHEDULING_LOGIN_ENABLED WORKSPACE_SCHEDULING_ENROLLMENT_ENABLED WORKSPACE_SCHEDULING_PATIENT_SETUP_ENABLED WORKSPACE_GOOGLE_CONNECTION_ENABLED WORKSPACE_GOOGLE_MESSAGE_ENABLED WORKSPACE_GOOGLE_CALENDAR_ENABLED WORKSPACE_MICROSOFT_CONNECTION_ENABLED VENDOR_SETUP_ENABLED VENDOR_WORK_ENABLED VENDOR_IO_ENABLED VENDOR_EVENTS_ENABLED FINANCE_SETUP_ENABLED FINANCE_WORK_ENABLED FINANCE_IO_ENABLED FINANCE_EVENTS_ENABLED PORTAL_SETUP_ENABLED PORTAL_WORK_ENABLED MEMBERSHIP_WORK_ENABLED INBOX_WORK_ENABLED INBOX_HANDOFF_ENABLED".split()
)


class BindingError(ValueError):
    """A fixed, non-sensitive reason code; never include input values."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise BindingError(code)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


def same(left: object, right: object) -> bool:
    return canonical(left) == canonical(right)


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate-json-key")
        result[key] = value
    return result


def _constant(_: str) -> None:
    raise BindingError("invalid-json")


def load(raw: bytes) -> dict[str, Any]:
    require(len(raw) <= 32 * 1024 * 1024, "oversize-input")
    try:
        value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise BindingError("invalid-json") from error
    require(isinstance(value, dict), "invalid-json-object")
    return value


def output(outputs: dict, name: str) -> Any:
    value = outputs.get(name)
    require(isinstance(value, dict) and "value" in value, "unresolved-output")
    return value["value"]


def string(value: Any, code: str = "invalid-string") -> str:
    require(
        isinstance(value, str)
        and 0 < len(value) <= 16384
        and not any(c in value for c in "\x00\r\n"),
        code,
    )
    return value


def runtime_value(value: Any) -> str:
    require(
        isinstance(value, str) and 0 < len(value) <= 16384 and "\x00" not in value,
        "invalid-runtime-value",
    )
    return value


def variable(plan: dict, name: str, default: Any = None) -> Any:
    values = plan.get("variables")
    require(isinstance(values, dict), "missing-plan-variables")
    return output(values, name) if name in values else default


def _resource_changes(plan: dict) -> dict[str, dict]:
    result = {}
    require(isinstance(plan.get("resource_changes"), list), "invalid-plan-resources")
    for item in plan["resource_changes"]:
        require(isinstance(item, dict), "invalid-plan-resources")
        address = string(item.get("address"), "invalid-plan-address")
        require(
            address not in result and isinstance(item.get("change"), dict),
            "duplicate-plan-resource",
        )
        if item.get("mode") == "managed":
            require(
                item["change"].get("actions") in (["create"], ["update"], ["no-op"]),
                "unsafe-plan-actions",
            )
        result[address] = item
    return result


def _after(changes: dict, address: str) -> dict:
    require(address in changes, "missing-plan-resource")
    item = changes[address]
    require(
        item.get("mode") == "managed"
        and item.get("type") == address.split(".")[0]
        and item.get("name") == address.split(".")[1].split("[")[0]
        and isinstance(item["change"].get("after"), dict),
        "invalid-plan-resource",
    )
    return item["change"]["after"]


def _one(value: Any) -> dict:
    require(
        isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict),
        "invalid-plan-template",
    )
    return value[0]


def _project_env(value: Any) -> dict[str, list[str]]:
    require(isinstance(value, list), "unresolved-runtime-env")
    result = {}
    for item in value:
        require(
            isinstance(item, dict) and not set(item) - {"name", "value", "secret_name"},
            "invalid-runtime-env",
        )
        name = string(item.get("name"))
        fields = [key for key in ("value", "secret_name") if item.get(key) not in (None, "")]
        require(name not in result and len(fields) == 1, "ambiguous-runtime-env")
        field = fields[0]
        result[name] = [
            "value" if field == "value" else "secretRef",
            runtime_value(item[field]) if field == "value" else string(item[field]),
        ]
    return result


def _workspace_extension(plan: dict, config: workload.Config) -> tuple[dict, dict]:
    hosted = variable(plan, "workspace_hosted_enabled", False)
    apple = variable(plan, "workspace_apple_enabled", False)
    desktop = variable(plan, "workspace_desktop_enabled", False)
    require(
        all(type(value) is bool for value in (hosted, apple, desktop)), "invalid-workspace-flags"
    )
    features = variable(plan, "workspace_features", {})
    public = variable(plan, "workspace_public_configuration", {})
    references = variable(plan, "workspace_secret_references", {})
    manifest = variable(plan, "workspace_managed_manifest")
    require(
        all(isinstance(value, dict) for value in (features, public, references)),
        "invalid-workspace-settings",
    )
    require(
        set(features) <= FEATURE_NAMES and all(type(v) is bool for v in features.values()),
        "unknown-workspace-feature",
    )
    require(
        set(public) <= PUBLIC_NAMES
        and all(isinstance(v, str) and 0 < len(v) <= 16384 for v in public.values()),
        "unknown-public-setting",
    )
    require(
        len(references) <= 100
        and all(
            name in SECRET_NAMES
            or re.fullmatch(r"COSMAS_MANAGED_SECRET_[A-Z][A-Z0-9_]{0,63}", name)
            for name in references
        ),
        "unknown-secret-setting",
    )
    if not hosted:
        require(
            not apple
            and not desktop
            and not features
            and not public
            and not references
            and manifest is None,
            "workspace-not-enabled",
        )
        return {}, {}
    env = {
        name: "true"
        for name in (
            "WORKSPACE_ENABLED",
            "WORKSPACE_AUTHENTICATED_ENABLED",
            "WORKSPACE_HOSTED_ENABLED",
            "WORKSPACE_DRAFT_RECOVERY_REQUIRED",
            "WORKSPACE_TEAM_SETUP_ENABLED",
            "WORKSPACE_AI_ACTIVITY_ENABLED",
            "WORKSPACE_ROUTINES_ENABLED",
        )
    }
    env.update(
        WORKSPACE_APPLE_HOSTED_TRANSPORT_ENABLED=str(apple).lower(),
        WORKSPACE_DESKTOP_HOSTED_TRANSPORT_ENABLED=str(desktop).lower(),
    )
    env.update({name: str(value).lower() for name, value in features.items()})
    env.update(public)
    for flag, prefix, path in (
        (
            "WORKSPACE_SCHEDULING_LOGIN_ENABLED",
            "SCHEDULING_GOOGLE",
            "/connections/scheduling/google/callback",
        ),
        (
            "WORKSPACE_GOOGLE_CONNECTION_ENABLED",
            "GOOGLE_CONNECTION",
            "/connections/google/callback",
        ),
        (
            "WORKSPACE_MICROSOFT_CONNECTION_ENABLED",
            "MICROSOFT_CONNECTION",
            "/connections/microsoft/callback",
        ),
    ):
        if features.get(flag):
            env[prefix + "_CALLBACK_URI"] = config.api_ready_url.removesuffix("/ready") + path
            env[
                "SCHEDULING_LOGIN_RETURN_ORIGIN"
                if prefix == "SCHEDULING_GOOGLE"
                else prefix + "_RETURN_ORIGIN"
            ] = config.web_origin
    if (
        features.get("WORKSPACE_CORE_CONNECTION_ENABLED")
        or public.get("WORKSPACE_CAPTURE_BACKEND") == "core"
    ):
        env["CORE_CAPTURE_MANAGED_IDENTITY_CLIENT_ID"] = config.runtime_identity_client_id
    references = dict(references)
    if manifest is not None:
        require(
            isinstance(manifest, dict)
            and set(manifest) == {"secret_name", "version", "sha256"}
            and isinstance(manifest["sha256"], str)
            and bool(HASH.fullmatch(manifest["sha256"])),
            "invalid-managed-manifest",
        )
        env["MANAGED_SERVICES_CONFIG_SHA256"] = manifest["sha256"]
        references["MANAGED_SERVICES_CONFIG_JSON"] = {
            key: manifest[key] for key in ("secret_name", "version")
        }
    result = {name: ["value", runtime_value(value)] for name, value in env.items()}
    secrets = {}
    for name, ref in references.items():
        require(
            isinstance(ref, dict)
            and set(ref) == {"secret_name", "version"}
            and isinstance(ref["secret_name"], str)
            and bool(re.fullmatch(r"[A-Za-z0-9-]{1,127}", ref["secret_name"]))
            and isinstance(ref["version"], str)
            and bool(re.fullmatch(r"[0-9a-f]{32}", ref["version"])),
            "invalid-versioned-secret",
        )
        alias = "ws-" + sha(name.encode())[:32]
        result[name] = ["secretRef", alias]
        secrets[alias] = f"{config.key_vault_uri}secrets/{ref['secret_name']}/{ref['version']}"
    return result, secrets


def _runtime_contract(plan: dict, changes: dict, config: workload.Config) -> dict:
    extra_env, extra_secrets = _workspace_extension(plan, config)
    expected_env = {
        name: list(value) for name, value in workload._expected_runtime_env(config).items()
    } | extra_env
    origins = [config.web_origin]
    for flag, origin in (
        ("workspace_apple_enabled", "capacitor://localhost"),
        ("workspace_desktop_enabled", "app://cosmas"),
    ):
        if variable(plan, flag, False):
            origins.append(origin)
    expected_env["CORS_ALLOWED_ORIGINS"] = expected_env["CLERK_AUTHORIZED_PARTIES"] = [
        "value",
        ",".join(origins),
    ]
    expected_secrets = {
        name: f"{config.key_vault_uri}secrets/{name}"
        for name in ("database-url", "redis-url", "human-deploy-evidence-reference")
    } | extra_secrets
    contract: dict[str, Any] = {"env": {}, "secrets": {}, "max_inactive_revisions": {}}
    for kind in ("api", "worker", "web"):
        app = _after(changes, f"azurerm_container_app.{kind}[0]")
        require(
            app.get("name") == f"ca-{kind}-cosmas-beta-{config.beta_id}"
            and app.get("resource_group_name") == config.resource_group
            and app.get("container_app_environment_id", "").lower()
            == config.managed_environment_id.lower(),
            "invalid-app-boundary",
        )
        require(
            app.get("revision_mode") == "Single"
            and type(app.get("max_inactive_revisions")) is int
            and app["max_inactive_revisions"] == 3,
            "invalid-planned-retention",
        )
        identity = config.web_identity_id if kind == "web" else config.runtime_identity_id
        app_identity = _one(app.get("identity"))
        require(
            app_identity.get("type") == "UserAssigned"
            and same(app_identity.get("identity_ids"), [identity]),
            "invalid-app-identity",
        )
        registry = _one(app.get("registry"))
        require(
            registry.get("server") == config.registry
            and registry.get("identity") == identity
            and all(registry.get(k) in (None, "") for k in ("username", "password_secret_name")),
            "invalid-app-registry",
        )
        template = _one(app.get("template"))
        container = _one(template.get("container"))
        minimum, maximum = {"api": (1, config.api_max_replicas), "worker": (1, 1), "web": (0, 1)}[
            kind
        ]
        require(
            type(template.get("min_replicas")) is int
            and type(template.get("max_replicas")) is int
            and template["min_replicas"] == minimum
            and template["max_replicas"] == maximum,
            "invalid-planned-scale",
        )
        cpu, memory = (0.25, "0.5Gi") if kind == "web" else (0.5, "1Gi")
        require(
            container.get("name") == kind
            and container.get("image") == workload._image(config, kind)
            and type(container.get("cpu")) in (int, float)
            and container["cpu"] == cpu
            and container.get("memory") == memory,
            "invalid-planned-container",
        )
        env = _project_env(container.get("env", []))
        secrets = {}
        require(isinstance(app.get("secret", []), list), "unresolved-secret-references")
        for item in app.get("secret", []):
            require(
                isinstance(item, dict)
                and not set(item) - {"name", "identity", "key_vault_secret_id", "value"},
                "invalid-secret-reference",
            )
            name = string(item.get("name"))
            require(
                name not in secrets
                and item.get("value") in (None, "")
                and item.get("identity") == identity,
                "inline-or-ambiguous-secret",
            )
            secrets[name] = string(item.get("key_vault_secret_id"))
        require(
            same(env, {} if kind == "web" else expected_env)
            and same(secrets, {} if kind == "web" else expected_secrets),
            "runtime-projection-mismatch",
        )
        contract["env"][kind] = env
        contract["secrets"][kind] = secrets
        contract["max_inactive_revisions"][kind] = app["max_inactive_revisions"]
    return contract


@dataclass(frozen=True)
class BoundWorkload:
    config: workload.Config
    expected: attestation.ExpectedBinding


def derive_binding(
    inputs: Mapping[str, bytes], *, source_sha: str, release_id: str
) -> BoundWorkload:
    require(set(inputs) == set(INPUTS), "input-set")
    require(
        bool(re.fullmatch(r"[0-9a-f]{40}", source_sha))
        and bool(re.fullmatch(r"[a-z0-9][a-z0-9-]{2,31}", release_id)),
        "source-release",
    )
    parsed = {
        name: load(raw) for name, raw in inputs.items() if name not in {"plan", "provider_lock"}
    }
    plan, review, state = parsed["plan_json"], parsed["review"], parsed["state"]
    result, bootstrap, build = (
        parsed["apply_result"],
        parsed["bootstrap_outputs"],
        parsed["build_evidence"],
    )
    require(
        type(review.get("schema_version")) is int
        and review["schema_version"] == 1
        and review.get("phase") == "subsequent"
        and review.get("source_sha") == source_sha,
        "review-source",
    )
    require(review.get("plan_sha256") == sha(inputs["plan"]), "plan-hash")
    require(review.get("variable_file_sha256") == sha(inputs["var_file"]), "variable-hash")
    require(
        review.get("provider_lock_sha256") == sha(inputs["provider_lock"])
        and plan.get("terraform_version") == review.get("terraform_version"),
        "toolchain-binding",
    )
    beta_match = re.fullmatch(
        r"early-adopter-beta/([a-z0-9][a-z0-9-]{1,8}[a-z0-9])/terraform\.tfstate",
        string(output(bootstrap, "backend_key")),
    )
    require(beta_match is not None, "bootstrap-boundary")
    beta = beta_match[1]
    boundary = {
        name: output(bootstrap, key)
        for name, key in {
            "subscription_id": "subscription_id",
            "tenant_id": "tenant_id",
            "deploy_identity_client_id": "deploy_identity_client_id",
            "box_id": "box_id",
            "state_resource_group": "backend_resource_group_name",
            "workload_resource_group": "workload_resource_group_name",
            "state_vnet_id": "state_vnet_id",
            "state_blob_private_dns_zone_id": "state_blob_private_dns_zone_id",
            "deployment_mode": "deployment_mode",
            "data_classification": "data_classification",
        }.items()
    }
    boundary["beta_id"] = beta
    require(
        same(review.get("boundary"), boundary)
        and boundary["deployment_mode"] == "synthetic_lab"
        and boundary["data_classification"] == "synthetic-only"
        and boundary["workload_resource_group"] == f"rg-cosmas-os-beta-{beta}"
        and boundary["state_resource_group"] == f"rg-cosmas-os-beta-state-{beta}",
        "bootstrap-review-boundary",
    )
    for name in ("subscription_id", "tenant_id", "deploy_identity_client_id", "box_id"):
        require(str(UUID(boundary[name])) == boundary[name], "noncanonical-identity")
    state_prefix = f"/subscriptions/{boundary['subscription_id']}/resourceGroups/{boundary['state_resource_group']}/providers/Microsoft.Network/"
    require(
        boundary["state_vnet_id"]
        == state_prefix + f"virtualNetworks/vnet-cosmas-os-beta-state-{beta}"
        and boundary["state_blob_private_dns_zone_id"]
        == state_prefix + "privateDnsZones/privatelink.blob.core.windows.net",
        "bootstrap-network-boundary",
    )
    require(
        type(state.get("serial")) is int
        and state["serial"] >= 0
        and isinstance(state.get("lineage"), str)
        and str(UUID(state["lineage"])) == state["lineage"],
        "invalid-state",
    )
    require(
        type(result.get("schema_version")) is int
        and result["schema_version"] == 1
        and result.get("plan_sha256") == review["plan_sha256"]
        and same(
            result.get("boundary"),
            {"box_id": boundary["box_id"], "deployment_mode": "synthetic_lab"},
        ),
        "apply-result-binding",
    )
    previous = review.get("prior_state")
    applied = result.get("state")
    require(
        isinstance(previous, dict)
        and set(previous) == {"lineage", "serial", "sha256"}
        and isinstance(applied, dict),
        "apply-state-shape",
    )
    require(
        same(
            previous,
            {
                "lineage": applied.get("lineage"),
                "serial": applied.get("pre_serial"),
                "sha256": applied.get("pre_sha256"),
            },
        )
        and applied.get("lineage") == state["lineage"]
        and type(applied.get("post_serial")) is int
        and applied["post_serial"] == state["serial"]
        and applied.get("post_sha256") == sha(inputs["state"]),
        "stale-applied-state",
    )
    require(
        type(previous["serial"]) is int
        and bool(HASH.fullmatch(string(previous["sha256"])))
        and type(result.get("no_changes")) is bool,
        "invalid-apply-transition",
    )
    require(
        (
            applied["post_serial"] == previous["serial"]
            and applied["post_sha256"] == previous["sha256"]
        )
        if result["no_changes"]
        else applied["post_serial"] > previous["serial"],
        "invalid-apply-transition",
    )
    outputs = state.get("outputs")
    planned = plan.get("planned_values", {}).get("outputs")
    require(isinstance(outputs, dict) and isinstance(planned, dict), "missing-output-map")
    critical = review.get("critical_planned_values")
    require(
        isinstance(critical, dict)
        and {"location", "api_max_replicas", "workloads_enabled"} <= set(critical),
        "missing-critical-profile",
    )
    for key, value in critical.items():
        # Terraform omits null outputs from pulled state, but a saved plan must
        # expose a known value; an unknown planned value is never treated as null.
        actual = output(outputs, key) if key in outputs else None
        require(same(value, output(planned, key)) and same(value, actual), "critical-output-drift")
    require(
        critical.get("workloads_enabled") is True
        and output(outputs, "runtime_data_mode") == "synthetic",
        "workloads-not-synthetic",
    )
    for key, value in {
        "box_id": boundary["box_id"],
        "environment": "early_adopter_beta",
        "deployment_mode": "synthetic_lab",
        "data_classification": "synthetic-only",
        "resource_group_name": boundary["workload_resource_group"],
        "state_vnet_id": boundary["state_vnet_id"],
        "state_blob_private_dns_zone_id": boundary["state_blob_private_dns_zone_id"],
    }.items():
        require(
            same(output(outputs, key), value) and same(output(planned, key), value),
            "state-boundary",
        )
    require(
        same(critical["location"], variable(plan, "location", "centralus"))
        and same(critical["api_max_replicas"], variable(plan, "api_max_replicas", 2))
        and type(critical["api_max_replicas"]) is int,
        "plan-profile",
    )
    changes = _resource_changes(plan)
    actions = [
        {key: item[key] for key in ("address", "type", "mode")}
        | {"actions": item["change"]["actions"]}
        for item in changes.values()
    ]
    require(same(review.get("managed_actions"), actions), "review-action-drift")
    build_payload = {k: v for k, v in build.items() if k != "evidence_payload_sha256"}
    require(
        build.get("evidence_payload_sha256") == sha(canonical(build_payload) + b"\n")
        and type(build.get("schema_version")) is int
        and build["schema_version"] == 1
        and build.get("evidence_type") == "protected-runner-build-push"
        and build.get("source_sha") == source_sha
        and build.get("build_release_id") == release_id
        and build.get("box_id") == boundary["box_id"],
        "build-evidence-binding",
    )
    require(build.get("state", {}).get("lineage") == state["lineage"], "build-state-lineage")
    for image in ("api", "web"):
        item = build.get("images", {}).get(image, {})
        require(
            item.get("tag_write_delete_locked") is True
            and item.get("manifest_write_delete_locked") is True
            and type(item.get("high_critical_vulnerabilities")) is int
            and item["high_critical_vulnerabilities"] == 0,
            "unaccepted-image",
        )

    def bound_output(key: str) -> str:
        value = string(output(planned, key), "unresolved-config-output")
        require(same(value, output(outputs, key)), "config-output-drift")
        return value

    scalar_outputs = {
        "runtime_identity_id": "runtime_identity_resource_id",
        "managed_environment_id": "container_app_environment_resource_id",
        "log_analytics_customer_id": "log_analytics_workspace_customer_id",
        "runtime_identity_client_id": "runtime_identity_client_id",
        "web_origin": "web_origin",
        "clerk_organization_id": "clerk_organization_id",
        "clerk_issuer": "clerk_issuer_url",
        "clerk_jwks_url": "clerk_jwks_url",
        "clerk_audience": "clerk_audience",
        "blob_account_url": "blob_account_url",
        "blob_container": "blob_container_name",
        "key_vault_uri": "key_vault_uri",
        "registry_posture": "registry_network_posture",
        "web_health_url": "web_health_url",
    }
    values = {key: bound_output(name) for key, name in scalar_outputs.items()}
    values.update(
        subscription_id=boundary["subscription_id"],
        resource_group=boundary["workload_resource_group"],
        beta_id=beta,
        box_id=boundary["box_id"],
        registry=bound_output("acr_login_server"),
        web_identity_id=string(_after(changes, "azurerm_user_assigned_identity.web").get("id")),
        api_ready_url=bound_output("api_origin") + "/ready",
        source_sha=source_sha,
        release_id=release_id,
        api_digest=build["images"]["api"]["digest"],
        web_digest=build["images"]["web"]["digest"],
        state_lineage=state["lineage"],
        state_serial=state["serial"],
        state_sha256=sha(inputs["state"]),
        location=critical["location"],
        api_max_replicas=critical["api_max_replicas"],
    )
    require(
        build.get("registry", {}).get("login_server") == values["registry"]
        and build["registry"].get("admin_user_enabled") is False,
        "registry-build-binding",
    )
    config = workload.Config.from_environment(
        {"COSMAS_WORKLOAD_" + key.upper(): str(value) for key, value in values.items()}
    )
    require(
        bool(re.fullmatch(r"https://[a-z0-9-]{3,24}\.vault\.azure\.net/", config.key_vault_uri)),
        "invalid-dedicated-vault",
    )
    vault = _after(changes, "azurerm_key_vault.beta")
    require(
        vault.get("resource_group_name") == config.resource_group
        and vault.get("location") == config.location
        and vault.get("vault_uri") == config.key_vault_uri
        and vault.get("public_network_access_enabled") is False
        and vault.get("rbac_authorization_enabled") is True,
        "private-vault-boundary",
    )
    acl = _one(vault.get("network_acls"))
    require(
        acl.get("bypass") == "None" and acl.get("default_action") == "Deny",
        "private-vault-boundary",
    )
    environment = _after(changes, "azurerm_container_app_environment.beta")
    require(
        environment.get("id") == config.managed_environment_id
        and environment.get("resource_group_name") == config.resource_group
        and environment.get("location") == config.location,
        "managed-environment-boundary",
    )
    contract = _runtime_contract(plan, changes, config)
    config = replace(
        config,
        plan_sha256=sha(inputs["plan"]),
        review_sha256=sha(inputs["review"]),
        runtime_contract_sha256=workload.runtime_contract_sha256(contract),
        runtime_contract=contract,
    )
    workload._validate_bound_runtime_contract(config)
    expected = attestation.ExpectedBinding(
        source_sha=source_sha,
        release_id=release_id,
        state_lineage=config.state_lineage,
        state_serial=config.state_serial,
        state_sha256=config.state_sha256,
        box_id=config.box_id,
        api_digest=config.api_digest,
        web_digest=config.web_digest,
        location=config.location,
        api_max_replicas=config.api_max_replicas,
        plan_sha256=config.plan_sha256,
        review_sha256=config.review_sha256,
        runtime_contract_sha256=config.runtime_contract_sha256,
    ).validated()
    return BoundWorkload(config, expected)


def _read(path: Path, *, private: bool = True) -> bytes:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        require(
            stat.S_ISREG(info.st_mode)
            and info.st_uid == 0
            and not info.st_mode & (0o077 if private else 0o022)
            and info.st_size <= 32 * 1024 * 1024,
            "unsafe-input-file",
        )
        return handle.read(32 * 1024 * 1024 + 1)


def _write(path: Path, evidence: dict) -> None:
    parent = path.parent.lstat()
    require(
        stat.S_ISDIR(parent.st_mode) and parent.st_uid == 0 and not parent.st_mode & 0o077,
        "unsafe-output-directory",
    )
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(canonical(evidence) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    for name in ("verify", "validate"):
        command = commands.add_parser(name)
        for key in INPUTS:
            command.add_argument("--" + key.replace("_", "-"), type=Path, required=True)
        command.add_argument("--source-sha", required=True)
        command.add_argument("--release-id", required=True)
        command.add_argument(
            "--output" if name == "verify" else "--artifact", type=Path, required=True
        )
    args = parser.parse_args(argv)
    try:
        inputs = {key: _read(getattr(args, key), private=key != "provider_lock") for key in INPUTS}
        bound = derive_binding(inputs, source_sha=args.source_sha, release_id=args.release_id)
        if args.operation == "verify":
            require(not args.output.exists() and not args.output.is_symlink(), "output-exists")
            evidence = workload.verify_workload(
                bound.config, workload.SubprocessRunner(), now=datetime.now(UTC)
            )
            attestation.validate_attestation(evidence, bound.expected)
            _write(args.output, evidence)
        else:
            attestation.load_and_validate_attestation(args.artifact, bound.expected)
    except BindingError as error:
        print(f"Workload binding refused ({error}).")
        return 1
    except workload.WorkloadVerificationError:
        print("Workload verification refused (live-configuration-or-readiness).")
        return 1
    except attestation.WorkloadAttestationError:
        print("Workload verification refused (stale-or-invalid-attestation).")
        return 1
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        print("Workload binding refused (unsafe-or-invalid-input).")
        return 1
    print("Workload verification validated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
