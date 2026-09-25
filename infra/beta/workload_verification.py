#!/usr/bin/env python3
"""Read-only, fail-closed verification of the exact deployed D3 workload.

The protected runner supplies only reviewed deployment bindings.  This command
reads the three Container Apps and their revisions, probes the two public
health routes, and emits one bounded, self-hashed record without hostnames,
resource IDs, response bodies, credentials, or application data.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol
from urllib.parse import urlsplit
from uuid import UUID

ARM_API_VERSION = "2024-03-01"
EVIDENCE_CONTRACT = "cosmas-os-d3-workload-verification-v1"
UTC = timezone.utc  # noqa: UP017 -- protected runner supports Python 3.10.

_AZ_BINARY = "/usr/bin/az"
_CURL_BINARY = "/usr/bin/curl"
_SYSTEM_CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"
_COMMAND_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

_BETA_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,20}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_LOCATION = re.compile(r"^[a-z][a-z0-9]{2,31}$")
_MANAGED_CERTIFICATE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,259}$")
_REGISTRY = re.compile(r"^[a-z0-9]{5,50}\.azurecr\.io$")
_RELEASE = re.compile(r"^[a-z0-9][a-z0-9-]{2,31}$")
_RESOURCE_GROUP = re.compile(r"^[A-Za-z0-9._()\-]{1,90}$")
_REVISION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,255}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_SHA = re.compile(r"^[0-9a-f]{40}$")


class WorkloadVerificationError(RuntimeError):
    """A live workload assertion failed; details remain private on the runner."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class CommandRunner(Protocol):
    def run(self, argv: Sequence[str]) -> CommandResult: ...


class SubprocessRunner:
    def run(self, argv: Sequence[str]) -> CommandResult:
        if not argv or argv[0] not in {_AZ_BINARY, _CURL_BINARY}:
            raise WorkloadVerificationError("unreviewed workload verification command")
        environment = {
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": _COMMAND_PATH,
        }
        if argv[0] == _AZ_BINARY:
            azure_config_dir = os.environ.get("AZURE_CONFIG_DIR", "")
            if not re.fullmatch(r"/run/cosmas-azure-session\.[A-Za-z0-9]+", azure_config_dir):
                raise WorkloadVerificationError("Azure CLI session boundary invalid")
            environment.update(
                {
                    "AZURE_CONFIG_DIR": azure_config_dir,
                    "AZURE_CORE_NO_COLOR": "1",
                    "AZURE_CORE_ONLY_SHOW_ERRORS": "1",
                }
            )
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
            list(argv),
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)


@dataclass(frozen=True)
class Config:
    subscription_id: str
    resource_group: str
    beta_id: str
    box_id: str
    registry: str
    runtime_identity_id: str
    web_identity_id: str
    managed_environment_id: str
    log_analytics_customer_id: str
    runtime_identity_client_id: str
    web_origin: str
    clerk_organization_id: str
    clerk_issuer: str
    clerk_jwks_url: str
    clerk_audience: str
    blob_account_url: str
    blob_container: str
    key_vault_uri: str
    registry_posture: str
    api_ready_url: str
    web_health_url: str
    source_sha: str
    release_id: str
    api_digest: str
    web_digest: str
    state_lineage: str
    state_serial: int
    state_sha256: str
    # Legacy callers selected this exact profile before these inputs existed.
    location: str = "centralus"
    api_max_replicas: int = 2

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> Config:
        def required(name: str) -> str:
            value = environment.get(name, "")
            if (
                not isinstance(value, str)
                or not value
                or value != value.strip()
                or any(c in value for c in "\r\n\x00")
            ):
                raise WorkloadVerificationError("workload verification configuration invalid")
            return value

        subscription_id = required("COSMAS_WORKLOAD_SUBSCRIPTION_ID").lower()
        resource_group = required("COSMAS_WORKLOAD_RESOURCE_GROUP")
        beta_id = required("COSMAS_WORKLOAD_BETA_ID")
        box_id = required("COSMAS_WORKLOAD_BOX_ID").lower()
        registry = required("COSMAS_WORKLOAD_REGISTRY").lower()
        runtime_identity_id = required("COSMAS_WORKLOAD_RUNTIME_IDENTITY_ID")
        web_identity_id = required("COSMAS_WORKLOAD_WEB_IDENTITY_ID")
        managed_environment_id = required("COSMAS_WORKLOAD_MANAGED_ENVIRONMENT_ID")
        log_analytics_customer_id = required("COSMAS_WORKLOAD_LOG_ANALYTICS_CUSTOMER_ID").lower()
        runtime_identity_client_id = required("COSMAS_WORKLOAD_RUNTIME_IDENTITY_CLIENT_ID").lower()
        web_origin = required("COSMAS_WORKLOAD_WEB_ORIGIN")
        clerk_organization_id = required("COSMAS_WORKLOAD_CLERK_ORGANIZATION_ID")
        clerk_issuer = required("COSMAS_WORKLOAD_CLERK_ISSUER")
        clerk_jwks_url = required("COSMAS_WORKLOAD_CLERK_JWKS_URL")
        clerk_audience = required("COSMAS_WORKLOAD_CLERK_AUDIENCE")
        blob_account_url = required("COSMAS_WORKLOAD_BLOB_ACCOUNT_URL")
        blob_container = required("COSMAS_WORKLOAD_BLOB_CONTAINER")
        key_vault_uri = required("COSMAS_WORKLOAD_KEY_VAULT_URI")
        registry_posture = required("COSMAS_WORKLOAD_REGISTRY_POSTURE")
        api_ready_url = required("COSMAS_WORKLOAD_API_READY_URL")
        web_health_url = required("COSMAS_WORKLOAD_WEB_HEALTH_URL")
        source_sha = required("COSMAS_WORKLOAD_SOURCE_SHA")
        release_id = required("COSMAS_WORKLOAD_RELEASE_ID")
        api_digest = required("COSMAS_WORKLOAD_API_DIGEST")
        web_digest = required("COSMAS_WORKLOAD_WEB_DIGEST")
        state_lineage = required("COSMAS_WORKLOAD_STATE_LINEAGE").lower()
        state_sha256 = required("COSMAS_WORKLOAD_STATE_SHA256")
        # Only omission of both new inputs preserves the exact legacy profile.
        # Current invocations must take the pair from the reviewed plan, never ARM.
        if (
            not {"COSMAS_WORKLOAD_LOCATION", "COSMAS_WORKLOAD_API_MAX_REPLICAS"}
            & environment.keys()
        ):
            location, api_max_replicas = "centralus", 2
        else:
            location = required("COSMAS_WORKLOAD_LOCATION")
            cap = required("COSMAS_WORKLOAD_API_MAX_REPLICAS")
            if not _LOCATION.fullmatch(location) or cap not in {"1", "2"}:
                raise WorkloadVerificationError("workload verification configuration invalid")
            api_max_replicas = int(cap)
        try:
            state_serial = int(required("COSMAS_WORKLOAD_STATE_SERIAL"))
        except ValueError:
            raise WorkloadVerificationError("workload verification configuration invalid") from None

        try:
            subscription_id = str(UUID(subscription_id))
            box_id = str(UUID(box_id))
            state_lineage = str(UUID(state_lineage))
            runtime_identity_client_id = str(UUID(runtime_identity_client_id))
            log_analytics_customer_id = str(UUID(log_analytics_customer_id))
        except ValueError:
            raise WorkloadVerificationError("workload verification configuration invalid") from None
        if (
            not _RESOURCE_GROUP.fullmatch(resource_group)
            or not _BETA_ID.fullmatch(beta_id)
            or not _REGISTRY.fullmatch(registry)
            or not _SOURCE_SHA.fullmatch(source_sha)
            or not _RELEASE.fullmatch(release_id)
            or not _DIGEST.fullmatch(api_digest)
            or not _DIGEST.fullmatch(web_digest)
            or api_digest == web_digest
            or not _SHA256.fullmatch(state_sha256)
            or state_serial < 0
            or registry_posture not in {"private", "synthetic_public_exception"}
            or not re.fullmatch(r"org_[^\s]+", clerk_organization_id)
            or not re.fullmatch(r"[A-Za-z0-9._:/-]{1,255}", clerk_audience)
            or not re.fullmatch(r"[a-z0-9-]{3,63}", blob_container)
        ):
            raise WorkloadVerificationError("workload verification configuration invalid")
        _validate_url(api_ready_url, "/ready")
        _validate_url(web_health_url, "/healthz")
        _validate_origin(web_origin)
        _validate_url(clerk_issuer.rstrip("/") + "/", "/")
        _validate_https_url(clerk_jwks_url)
        _validate_url(blob_account_url, "/")
        _validate_url(key_vault_uri, "/")
        identity_prefix = (
            f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/"
            "Microsoft.ManagedIdentity/userAssignedIdentities/"
        ).lower()
        if (
            not runtime_identity_id.lower().startswith(identity_prefix)
            or not web_identity_id.lower().startswith(identity_prefix)
            or runtime_identity_id.lower() == web_identity_id.lower()
            or managed_environment_id.lower()
            != (
                f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/"
                f"Microsoft.App/managedEnvironments/cae-cosmas-beta-{beta_id}"
            ).lower()
        ):
            raise WorkloadVerificationError("workload verification configuration invalid")
        return cls(
            subscription_id=subscription_id,
            resource_group=resource_group,
            beta_id=beta_id,
            box_id=box_id,
            registry=registry,
            runtime_identity_id=runtime_identity_id,
            web_identity_id=web_identity_id,
            managed_environment_id=managed_environment_id,
            log_analytics_customer_id=log_analytics_customer_id,
            runtime_identity_client_id=runtime_identity_client_id,
            web_origin=web_origin,
            clerk_organization_id=clerk_organization_id,
            clerk_issuer=clerk_issuer,
            clerk_jwks_url=clerk_jwks_url,
            clerk_audience=clerk_audience,
            blob_account_url=blob_account_url,
            blob_container=blob_container,
            key_vault_uri=key_vault_uri,
            registry_posture=registry_posture,
            api_ready_url=api_ready_url,
            web_health_url=web_health_url,
            source_sha=source_sha,
            release_id=release_id,
            api_digest=api_digest,
            web_digest=web_digest,
            state_lineage=state_lineage,
            state_serial=state_serial,
            state_sha256=state_sha256,
            location=location,
            api_max_replicas=api_max_replicas,
        )


def _validate_url(value: str, required_path: str) -> None:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or parsed.path != required_path
        or parsed.query
        or parsed.fragment
    ):
        raise WorkloadVerificationError("workload verification configuration invalid")


def _validate_https_url(value: str) -> None:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or parsed.query
        or parsed.fragment
    ):
        raise WorkloadVerificationError("workload verification configuration invalid")


def _validate_origin(value: str) -> None:
    parsed = urlsplit(value)
    if parsed.path not in {"", "/"} or parsed.query:
        raise WorkloadVerificationError("workload verification configuration invalid")
    _validate_https_url(value)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _resource_id(config: Config, kind: str) -> str:
    return (
        f"/subscriptions/{config.subscription_id}/resourceGroups/{config.resource_group}/"
        f"providers/Microsoft.App/containerApps/ca-{kind}-cosmas-beta-{config.beta_id}"
    )


def _image(config: Config, kind: str) -> str:
    repository = "cosmas-os-web" if kind == "web" else "cosmas-os"
    digest = config.web_digest if kind == "web" else config.api_digest
    return f"{config.registry}/{repository}@{digest}"


def _is_exact_int(value: object, expected: int) -> bool:
    """Return true only for a JSON integer, never for Python's bool subtype."""

    return type(value) is int and value == expected


def _is_exact_number(value: object, expected: float) -> bool:
    """Return true only for a JSON number with the reviewed value."""

    return type(value) in {int, float} and value == expected


def _is_null_or_empty_list(value: object) -> bool:
    """Accept only ARM's semantically empty optional-array representations."""

    return value is None or (isinstance(value, list) and not value)


def _is_expected_location(value: object, expected: str) -> bool:
    """Match the reviewed region, including known ARM display spellings."""

    display_names = {"centralus": "Central US", "eastus2": "East US 2"}
    return isinstance(value, str) and (value == expected or value == display_names.get(expected))


def _arm_url(resource_id: str, *, revisions: bool = False) -> str:
    suffix = "/revisions" if revisions else ""
    return f"https://management.azure.com{resource_id}{suffix}?api-version={ARM_API_VERSION}"


def _get_json(
    runner: CommandRunner, resource_id: str, *, revisions: bool = False
) -> dict[str, Any]:
    result = runner.run(
        [
            _AZ_BINARY,
            "rest",
            "--method",
            "get",
            "--url",
            _arm_url(resource_id, revisions=revisions),
            "--only-show-errors",
            "--output",
            "json",
        ]
    )
    if result.returncode != 0:
        raise WorkloadVerificationError("Container App read failed")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise WorkloadVerificationError("Container App response invalid") from None
    if not isinstance(value, dict):
        raise WorkloadVerificationError("Container App response invalid")
    return value


def _identity_id(app: dict[str, Any]) -> str:
    identity = app.get("identity")
    if not isinstance(identity, dict) or identity.get("type") != "UserAssigned":
        raise WorkloadVerificationError("Container App identity invalid")
    identities = identity.get("userAssignedIdentities")
    if not isinstance(identities, dict) or len(identities) != 1:
        raise WorkloadVerificationError("Container App identity invalid")
    return str(next(iter(identities))).lower()


def _validate_managed_environment(config: Config, environment: dict[str, Any]) -> None:
    properties = environment.get("properties")
    expected_name = f"cae-cosmas-beta-{config.beta_id}"
    expected_subnet_id = (
        f"/subscriptions/{config.subscription_id}/resourceGroups/{config.resource_group}/"
        f"providers/Microsoft.Network/virtualNetworks/vnet-cosmas-beta-{config.beta_id}/"
        "subnets/snet-container-apps"
    )
    vnet = properties.get("vnetConfiguration") if isinstance(properties, dict) else None
    app_logs = properties.get("appLogsConfiguration") if isinstance(properties, dict) else None
    log_analytics = (
        app_logs.get("logAnalyticsConfiguration") if isinstance(app_logs, dict) else None
    )
    if (
        str(environment.get("id", "")).lower() != config.managed_environment_id.lower()
        or environment.get("name") != expected_name
        or str(environment.get("type", "")).lower() != "microsoft.app/managedenvironments"
        or not _is_expected_location(environment.get("location"), config.location)
        or not isinstance(properties, dict)
        or properties.get("provisioningState") != "Succeeded"
        or not isinstance(vnet, dict)
        or str(vnet.get("infrastructureSubnetId", "")).lower() != expected_subnet_id.lower()
        or vnet.get("internal") is not False
        or any(
            vnet.get(field) is not None
            for field in ("dockerBridgeCidr", "platformReservedCidr", "platformReservedDnsIP")
        )
        or not isinstance(app_logs, dict)
        or app_logs.get("destination") != "log-analytics"
        or not isinstance(log_analytics, dict)
        or str(log_analytics.get("customerId", "")).lower() != config.log_analytics_customer_id
    ):
        raise WorkloadVerificationError("managed environment binding invalid")


def _validate_registry(
    config: Config,
    kind: str,
    registries: object,
    expected_identity: str,
) -> None:
    if not isinstance(registries, list) or len(registries) != 1:
        raise WorkloadVerificationError("Container App registry binding invalid")
    registry = registries[0]
    if (
        not isinstance(registry, dict)
        or set(registry) != {"server", "identity"}
        or not isinstance(registry.get("server"), str)
        or registry["server"].lower() != config.registry
        or not isinstance(registry.get("identity"), str)
        or registry["identity"].lower() != expected_identity.lower()
    ):
        raise WorkloadVerificationError(f"{kind} registry binding invalid")


def _validate_scale(config: Config, kind: str, scale: object) -> tuple[int, int]:
    minimum, maximum = {"api": (1, config.api_max_replicas), "worker": (1, 1), "web": (0, 1)}[kind]
    if (
        not isinstance(scale, dict)
        or not {"minReplicas", "maxReplicas"}.issubset(scale)
        or set(scale) - {"minReplicas", "maxReplicas", "rules"}
        or not _is_exact_int(scale.get("minReplicas"), minimum)
        or not _is_exact_int(scale.get("maxReplicas"), maximum)
        or ("rules" in scale and scale["rules"] not in (None, []))
    ):
        raise WorkloadVerificationError(f"{kind} scale contract invalid")
    return minimum, maximum


def _validate_route(config: Config, kind: str, app: dict[str, Any]) -> None:
    properties = app.get("properties")
    configuration = properties.get("configuration") if isinstance(properties, dict) else None
    if not isinstance(configuration, dict) or configuration.get("activeRevisionsMode") != "Single":
        raise WorkloadVerificationError("Container App route invalid")
    ingress = configuration.get("ingress")
    if kind == "worker":
        if ingress is not None and ingress != {}:
            raise WorkloadVerificationError("worker ingress is not private")
        return
    if not isinstance(ingress, dict):
        raise WorkloadVerificationError("Container App route invalid")
    if set(ingress) - {
        "additionalPortMappings",
        "allowInsecure",
        "clientCertificateMode",
        "customDomains",
        "exposedPort",
        "external",
        "fqdn",
        "ipSecurityRestrictions",
        "stickySessions",
        "targetPort",
        "traffic",
        "transport",
    }:
        raise WorkloadVerificationError("Container App route invalid")
    traffic = ingress.get("traffic")
    expected_port = 8080 if kind == "web" else 8000
    if (
        ingress.get("external") is not True
        or ingress.get("allowInsecure") is not False
        or not _is_exact_int(ingress.get("targetPort"), expected_port)
        or not isinstance(traffic, list)
        or len(traffic) != 1
        or not isinstance(traffic[0], dict)
        or set(traffic[0]) - {"weight", "latestRevision", "label", "revisionName"}
        or not _is_exact_int(traffic[0].get("weight"), 100)
        or traffic[0].get("latestRevision") is not True
        or traffic[0].get("label") not in {None, ""}
        or traffic[0].get("revisionName") not in {None, ""}
        or str(ingress.get("transport", "auto")).lower() != "auto"
        or ingress.get("additionalPortMappings") not in (None, [])
        or not (ingress.get("exposedPort") is None or _is_exact_int(ingress.get("exposedPort"), 0))
        or ingress.get("ipSecurityRestrictions") not in (None, [])
        or ingress.get("clientCertificateMode") not in (None, "Ignore", "ignore")
        or ingress.get("stickySessions") not in (None, {}, {"affinity": "none"})
    ):
        raise WorkloadVerificationError("Container App route invalid")
    health_url = config.web_health_url if kind == "web" else config.api_ready_url
    health_host = (urlsplit(health_url).hostname or "").lower()
    fqdn = str(ingress.get("fqdn", "")).lower()
    custom_domains = ingress.get("customDomains")
    if custom_domains is None:
        custom_domains = []
    if not isinstance(custom_domains, list):
        raise WorkloadVerificationError("health route is not bound to the Container App")
    if health_host == fqdn:
        if custom_domains:
            raise WorkloadVerificationError("health route is not bound to the Container App")
    else:
        if len(custom_domains) != 1 or not isinstance(custom_domains[0], dict):
            raise WorkloadVerificationError("health route is not bound to the Container App")
        custom_domain = custom_domains[0]
        certificate_id = custom_domain.get("certificateId")
        certificate_prefix = f"{config.managed_environment_id}/managedCertificates/"
        certificate_suffix = (
            certificate_id[len(certificate_prefix) :]
            if isinstance(certificate_id, str)
            and certificate_id.lower().startswith(certificate_prefix.lower())
            else ""
        )
        if (
            set(custom_domain) != {"name", "bindingType", "certificateId"}
            or str(custom_domain.get("name", "")).lower() != health_host
            or str(custom_domain.get("bindingType", "")).lower() != "snienabled"
            or not _MANAGED_CERTIFICATE_NAME.fullmatch(certificate_suffix)
        ):
            raise WorkloadVerificationError("health route is not bound to the Container App")


def _expected_probes(kind: str) -> dict[str, dict[str, Any]]:
    port = 8080 if kind == "web" else 8001 if kind == "worker" else 8000
    path = "/healthz" if kind == "web" else "/ready" if kind == "worker" else "/health"
    startup = {
        "path": path,
        "port": port,
        "scheme": "HTTP",
        "initialDelaySeconds": 0,
        "periodSeconds": 5,
        "timeoutSeconds": 5 if kind == "worker" else 2,
        "failureThreshold": 60 if kind == "worker" else 30,
        "successThreshold": 1,
    }
    readiness = {
        "path": "/healthz" if kind == "web" else "/ready",
        "port": port,
        "scheme": "HTTP",
        "initialDelaySeconds": 2 if kind == "web" else 0 if kind == "worker" else 5,
        "periodSeconds": 10,
        "timeoutSeconds": 2 if kind == "web" else 5,
        "failureThreshold": 3,
        "successThreshold": 1,
    }
    expected = {"startup": startup, "readiness": readiness}
    if kind == "web":
        expected["liveness"] = {
            "path": "/healthz",
            "port": 8080,
            "scheme": "HTTP",
            "initialDelaySeconds": 10,
            "periodSeconds": 30,
            "timeoutSeconds": 2,
            "failureThreshold": 3,
            "successThreshold": 1,
        }
    return expected


def _validate_probes(container: dict[str, Any], kind: str) -> None:
    probes = container.get("probes")
    expected = _expected_probes(kind)
    if not isinstance(probes, list) or len(probes) != len(expected):
        raise WorkloadVerificationError(f"{kind} probes invalid")
    by_type: dict[str, dict[str, Any]] = {}
    for probe in probes:
        if not isinstance(probe, dict):
            raise WorkloadVerificationError(f"{kind} probes invalid")
        probe_type = str(probe.get("type", "")).lower()
        if probe_type in by_type:
            raise WorkloadVerificationError(f"{kind} probes invalid")
        by_type[probe_type] = probe
    if set(by_type) != set(expected):
        raise WorkloadVerificationError(f"{kind} probes invalid")
    for probe_type, expected_values in expected.items():
        probe = by_type[probe_type]
        if set(probe) - {
            "type",
            "httpGet",
            "initialDelaySeconds",
            "periodSeconds",
            "timeoutSeconds",
            "failureThreshold",
            "successThreshold",
        }:
            raise WorkloadVerificationError(f"{kind} probes invalid")
        http_get = probe.get("httpGet")
        if not isinstance(http_get, dict) or set(http_get) - {
            "path",
            "port",
            "scheme",
            "httpHeaders",
        }:
            raise WorkloadVerificationError(f"{kind} probes invalid")
        realized = {
            "path": http_get.get("path"),
            "port": http_get.get("port"),
            "scheme": str(http_get.get("scheme", "HTTP")).upper(),
            "initialDelaySeconds": probe.get("initialDelaySeconds", 0),
            "periodSeconds": probe.get("periodSeconds"),
            "timeoutSeconds": probe.get("timeoutSeconds"),
            "failureThreshold": probe.get("failureThreshold"),
            "successThreshold": probe.get("successThreshold", 1),
        }
        if any(
            type(realized[field]) is not int
            for field in (
                "port",
                "initialDelaySeconds",
                "periodSeconds",
                "timeoutSeconds",
                "failureThreshold",
                "successThreshold",
            )
        ):
            raise WorkloadVerificationError(f"{kind} probes invalid")
        if http_get.get("httpHeaders") not in (None, []):
            raise WorkloadVerificationError(f"{kind} probes invalid")
        if realized != expected_values or probe.get("tcpSocket") is not None:
            raise WorkloadVerificationError(f"{kind} probes invalid")


def _expected_runtime_env(config: Config) -> dict[str, tuple[str, str]]:
    return {
        "COSMAS_ENV": ("value", "early_adopter_beta"),
        "DATA_MODE": ("value", "synthetic"),
        "AUTH_MODE": ("value", "clerk_jwt"),
        "CORS_ALLOWED_ORIGINS": ("value", config.web_origin),
        "SYNTH_SEED": ("value", "false"),
        "BLOB_BACKEND": ("value", "azure"),
        "BETA_BOX_ID": ("value", config.box_id),
        "CLERK_ORGANIZATION_ID": ("value", config.clerk_organization_id),
        "CLERK_ISSUER": ("value", config.clerk_issuer),
        "CLERK_JWKS_URL": ("value", config.clerk_jwks_url),
        "CLERK_AUDIENCE": ("value", config.clerk_audience),
        "CLERK_AUTHORIZED_PARTIES": ("value", config.web_origin),
        "AZURE_CLIENT_ID": ("value", config.runtime_identity_client_id),
        "HUMAN_DEPLOY_EVIDENCE_REF": ("secretRef", "human-deploy-evidence-reference"),
        "DATABASE_URL": ("secretRef", "database-url"),
        "REDIS_URL": ("secretRef", "redis-url"),
        "AZURE_STORAGE_ACCOUNT_URL": ("value", config.blob_account_url),
        "AZURE_BLOB_CONTAINER": ("value", config.blob_container),
        "SYNC_WORKER": ("value", "false"),
    }


def _validate_env(config: Config, kind: str, container: dict[str, Any]) -> None:
    env = container.get("env")
    if env is None:
        env = []
    if not isinstance(env, list):
        raise WorkloadVerificationError(f"{kind} runtime environment invalid")
    expected = {} if kind == "web" else _expected_runtime_env(config)
    actual: dict[str, tuple[str, str]] = {}
    for item in env:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise WorkloadVerificationError(f"{kind} runtime environment invalid")
        name = item["name"]
        if name in actual:
            raise WorkloadVerificationError(f"{kind} runtime environment invalid")
        fields = [field for field in ("value", "secretRef") if item.get(field) is not None]
        if len(fields) != 1 or set(item) != {"name", fields[0]}:
            raise WorkloadVerificationError(f"{kind} runtime environment invalid")
        actual[name] = (fields[0], str(item[fields[0]]))
    if actual != expected:
        raise WorkloadVerificationError(f"{kind} runtime environment invalid")


def _validate_secrets(config: Config, kind: str, configuration: dict[str, Any]) -> None:
    secrets = configuration.get("secrets")
    if secrets is None:
        secrets = []
    if not isinstance(secrets, list):
        raise WorkloadVerificationError(f"{kind} secret references invalid")
    expected = (
        {}
        if kind == "web"
        else {
            "database-url": f"{config.key_vault_uri}secrets/database-url",
            "redis-url": f"{config.key_vault_uri}secrets/redis-url",
            "human-deploy-evidence-reference": f"{config.key_vault_uri}secrets/human-deploy-evidence-reference",
        }
    )
    actual: dict[str, str] = {}
    for item in secrets:
        if not isinstance(item, dict) or set(item) != {"name", "identity", "keyVaultUrl"}:
            raise WorkloadVerificationError(f"{kind} secret references invalid")
        name = item.get("name")
        if not isinstance(name, str) or name in actual:
            raise WorkloadVerificationError(f"{kind} secret references invalid")
        if str(item.get("identity", "")).lower() != config.runtime_identity_id.lower():
            raise WorkloadVerificationError(f"{kind} secret references invalid")
        actual[name] = str(item.get("keyVaultUrl", ""))
    if actual != expected:
        raise WorkloadVerificationError(f"{kind} secret references invalid")


def _validate_container_contract(config: Config, kind: str, container: dict[str, Any]) -> None:
    allowed_container_fields = {
        "name",
        "image",
        "resources",
        "probes",
        "env",
        "command",
        "args",
        "volumeMounts",
    }
    if set(container) - allowed_container_fields:
        raise WorkloadVerificationError(f"{kind} container contract invalid")
    expected_command = ["celery"] if kind == "worker" else []
    expected_args = (
        [
            "-A",
            "cosmas_os.worker.celery_app:celery_app",
            "worker",
            "--loglevel=INFO",
            "--concurrency=1",
        ]
        if kind == "worker"
        else []
    )
    command = container.get("command")
    args = container.get("args")
    if command is None:
        command = []
    if args is None:
        args = []
    if (
        not isinstance(command, list)
        or not isinstance(args, list)
        or command != expected_command
        or args != expected_args
    ):
        raise WorkloadVerificationError(f"{kind} command/args invalid")
    if not _is_null_or_empty_list(container.get("volumeMounts")):
        raise WorkloadVerificationError(f"{kind} container contract invalid")
    resources = container.get("resources")
    expected_cpu, expected_memory, expected_ephemeral = {
        "api": (0.5, "1Gi", "2Gi"),
        "worker": (0.5, "1Gi", "2Gi"),
        "web": (0.25, "0.5Gi", "1Gi"),
    }[kind]
    if (
        not isinstance(resources, dict)
        or set(resources) - {"cpu", "memory", "ephemeralStorage"}
        or not _is_exact_number(resources.get("cpu"), expected_cpu)
        or resources.get("memory") != expected_memory
        or ("ephemeralStorage" in resources and resources["ephemeralStorage"] != expected_ephemeral)
    ):
        raise WorkloadVerificationError(f"{kind} CPU/memory invalid")
    _validate_env(config, kind, container)
    _validate_probes(container, kind)


def _validate_app(
    config: Config,
    kind: str,
    app: dict[str, Any],
    revisions: dict[str, Any],
) -> str:
    resource_id = _resource_id(config, kind)
    expected_image = _image(config, kind)
    expected_identity = config.web_identity_id if kind == "web" else config.runtime_identity_id
    properties = app.get("properties")
    tags = app.get("tags")
    if not isinstance(properties, dict) or not isinstance(tags, dict):
        raise WorkloadVerificationError("Container App binding invalid")
    template = properties.get("template")
    containers = template.get("containers") if isinstance(template, dict) else None
    configuration = properties.get("configuration")
    registries = configuration.get("registries") if isinstance(configuration, dict) else None
    expected_tags = {
        "track": "B",
        "product": "cosmas-os",
        "env": "early_adopter_beta",
        "deployment_mode": "synthetic_lab",
        "data_classification": "synthetic-only",
        "registry_posture": config.registry_posture,
        "box_scope": "dedicated",
        "box_id": config.box_id,
        "connectors": "dark",
        "managed": "terraform",
    }
    scale = template.get("scale") if isinstance(template, dict) else None
    if (
        str(app.get("id", "")).lower() != resource_id.lower()
        or not _is_expected_location(app.get("location"), config.location)
        or _identity_id(app) != expected_identity.lower()
        or tags != expected_tags
        or str(properties.get("managedEnvironmentId", "")).lower()
        != config.managed_environment_id.lower()
        or not isinstance(template, dict)
        or not isinstance(containers, list)
        or len(containers) != 1
        or not isinstance(containers[0], dict)
        or containers[0].get("name") != kind
        or containers[0].get("image") != expected_image
        or properties.get("provisioningState") != "Succeeded"
    ):
        raise WorkloadVerificationError("Container App binding invalid")
    if set(template) - {
        "containers",
        "initContainers",
        "revisionSuffix",
        "scale",
        "volumes",
    }:
        raise WorkloadVerificationError("Container App template contract invalid")
    for collection in ("initContainers", "volumes"):
        if not _is_null_or_empty_list(template.get(collection)):
            raise WorkloadVerificationError("Container App template contract invalid")
    if not isinstance(configuration, dict):
        raise WorkloadVerificationError("Container App binding invalid")
    if set(configuration) - {
        "activeRevisionsMode",
        "dapr",
        "identitySettings",
        "ingress",
        "maxInactiveRevisions",
        "registries",
        "runtime",
        "secrets",
        "service",
    }:
        raise WorkloadVerificationError("Container App configuration contract invalid")
    for extension in ("dapr", "identitySettings", "runtime", "service"):
        if configuration.get(extension) not in (None, {}, []):
            raise WorkloadVerificationError("Container App configuration contract invalid")
    maximum_inactive = configuration.get("maxInactiveRevisions")
    if not _is_exact_int(maximum_inactive, 3):
        raise WorkloadVerificationError("Container App configuration contract invalid")
    _validate_registry(config, kind, registries, expected_identity)
    minimum_replicas, maximum_replicas = _validate_scale(config, kind, scale)
    _validate_secrets(config, kind, configuration)
    _validate_container_contract(config, kind, containers[0])
    latest = properties.get("latestRevisionName")
    ready = properties.get("latestReadyRevisionName")
    if not isinstance(latest, str) or latest != ready or not _REVISION.fullmatch(latest):
        raise WorkloadVerificationError("Container App readiness invalid")
    revision_suffix = template.get("revisionSuffix")
    if revision_suffix not in (None, "") and (
        not isinstance(revision_suffix, str) or not latest.endswith(f"--{revision_suffix}")
    ):
        raise WorkloadVerificationError("Container App template contract invalid")
    values = revisions.get("value")
    if (
        set(revisions) - {"value", "nextLink"}
        or not isinstance(values, list)
        or revisions.get("nextLink") is not None
    ):
        raise WorkloadVerificationError("Container App revision response invalid")
    active: list[dict[str, Any]] = []
    seen_revisions: set[str] = set()
    for item in values:
        if not isinstance(item, dict):
            raise WorkloadVerificationError("Container App revision response invalid")
        item_name = item.get("name")
        item_properties = item.get("properties")
        if (
            not isinstance(item_name, str)
            or not _REVISION.fullmatch(item_name)
            or item_name in seen_revisions
            or str(item.get("id", "")).lower() != f"{resource_id}/revisions/{item_name}".lower()
            or not isinstance(item_properties, dict)
            or type(item_properties.get("active")) is not bool
        ):
            raise WorkloadVerificationError("Container App revision response invalid")
        seen_revisions.add(item_name)
        if item_properties["active"] is True:
            active.append(item)
    if len(active) != 1:
        raise WorkloadVerificationError("Container App active revision set invalid")
    revision = active[0]
    revision_properties = revision.get("properties")
    revision_template = (
        revision_properties.get("template") if isinstance(revision_properties, dict) else None
    )
    revision_containers = (
        revision_template.get("containers") if isinstance(revision_template, dict) else None
    )
    revision_scale = revision_template.get("scale") if isinstance(revision_template, dict) else None
    replicas = (
        revision_properties.get("replicas") if isinstance(revision_properties, dict) else None
    )
    if (
        revision.get("name") != latest
        or str(revision.get("id", "")).lower() != f"{resource_id}/revisions/{latest}".lower()
        or not isinstance(revision_properties, dict)
        or not isinstance(revision_template, dict)
        or not isinstance(revision_containers, list)
        or len(revision_containers) != 1
        or not isinstance(revision_containers[0], dict)
        or revision_containers[0].get("name") != kind
        or revision_containers[0].get("image") != expected_image
        or revision_properties.get("healthState") != "Healthy"
        or revision_properties.get("provisioningState") != "Provisioned"
        or type(replicas) is not int
        or replicas < minimum_replicas
        or replicas > maximum_replicas
    ):
        raise WorkloadVerificationError("Container App active revision is not ready")
    if set(revision_template) - {
        "containers",
        "initContainers",
        "revisionSuffix",
        "scale",
        "volumes",
    }:
        raise WorkloadVerificationError("Container App revision template contract invalid")
    for collection in ("initContainers", "volumes"):
        if not _is_null_or_empty_list(revision_template.get(collection)):
            raise WorkloadVerificationError("Container App revision template contract invalid")
    revision_suffix = revision_template.get("revisionSuffix")
    if revision_suffix not in (None, "") and (
        not isinstance(revision_suffix, str) or not latest.endswith(f"--{revision_suffix}")
    ):
        raise WorkloadVerificationError("Container App revision template contract invalid")
    _validate_scale(config, kind, revision_scale)
    _validate_container_contract(config, kind, revision_containers[0])
    _validate_route(config, kind, app)
    return hashlib.sha256(str(revision["id"]).lower().encode()).hexdigest()


def _probe_health(config: Config, runner: CommandRunner) -> None:
    probes: tuple[tuple[str, str, object], ...] = (
        ("api", config.api_ready_url, {"status": "ready", "env": "early_adopter_beta"}),
        ("web", config.web_health_url, "ok"),
    )
    for kind, url, expected in probes:
        result = runner.run(
            [
                _CURL_BINARY,
                "--disable",
                "--silent",
                "--show-error",
                "--fail",
                "--proto",
                "=https",
                "--tlsv1.2",
                "--noproxy",
                "*",
                "--cacert",
                _SYSTEM_CA_BUNDLE,
                "--max-time",
                "30",
                "--write-out",
                "\n%{http_code}",
                url,
            ]
        )
        try:
            body, status_code = result.stdout.rsplit("\n", 1)
        except ValueError:
            raise WorkloadVerificationError("public workload health check failed") from None
        if result.returncode != 0 or status_code != "200" or len(body.encode()) > 4096:
            raise WorkloadVerificationError("public workload health check failed")
        if kind == "api":
            try:
                actual = json.loads(body)
            except json.JSONDecodeError:
                raise WorkloadVerificationError("API readiness response invalid") from None
            if actual != expected:
                raise WorkloadVerificationError("API readiness response invalid")
        elif body.strip() != expected:
            raise WorkloadVerificationError("web health response invalid")


def verify_workload(
    config: Config,
    runner: CommandRunner,
    *,
    now: datetime,
) -> dict[str, Any]:
    if (
        not isinstance(config.location, str)
        or not _LOCATION.fullmatch(config.location)
        or type(config.api_max_replicas) is not int
        or config.api_max_replicas not in {1, 2}
    ):
        raise WorkloadVerificationError("workload verification configuration invalid")
    _validate_managed_environment(
        config,
        _get_json(runner, config.managed_environment_id),
    )
    revision_hashes: dict[str, str] = {}
    for kind in ("api", "worker", "web"):
        resource_id = _resource_id(config, kind)
        revision_hashes[kind] = _validate_app(
            config,
            kind,
            _get_json(runner, resource_id),
            _get_json(runner, resource_id, revisions=True),
        )
    _probe_health(config, runner)
    if now.tzinfo is None:
        raise WorkloadVerificationError("workload verification timestamp invalid")
    payload = {
        "schema_version": 1,
        "contract": EVIDENCE_CONTRACT,
        "status": "verified",
        "completed_at": now.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source_sha": config.source_sha,
        "release_id": config.release_id,
        "box_id": config.box_id,
        "location": config.location,
        "api_max_replicas": config.api_max_replicas,
        "state": {
            "exists": True,
            "lineage": config.state_lineage,
            "serial": config.state_serial,
            "sha256": config.state_sha256,
        },
        "images": {"api": config.api_digest, "worker": config.api_digest, "web": config.web_digest},
        "revision_id_sha256": revision_hashes,
        "exact_revisions_and_images_verified": True,
        "single_revision_traffic_verified": True,
        "api_ready_verified": True,
        "web_health_verified": True,
        "worker_probe_configuration_verified": True,
        "exact_runtime_configuration_verified": True,
        "managed_environment_verified": True,
        "worker_private_and_ready": True,
        # The synthetic Box UUID is deliberately retained above as the tenancy
        # binding; no person or patient identifier is emitted.
        "synthetic_box_id_returned": True,
        "person_or_patient_identifiers_returned": False,
        "secrets_returned": False,
    }
    return {**payload, "evidence_payload_sha256": _sha256_json(payload)}


def main() -> int:
    try:
        evidence = verify_workload(
            Config.from_environment(os.environ),
            SubprocessRunner(),
            now=datetime.now(UTC),
        )
    except Exception:  # noqa: BLE001 - never expose live topology or response details
        print(_canonical_json({"contract": EVIDENCE_CONTRACT, "status": "failed"}))
        return 1
    print(_canonical_json(evidence))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
