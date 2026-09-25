from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "infra" / "beta" / "workload_verification.py"
_SPEC = importlib.util.spec_from_file_location("cosmas_workload_verification", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
workload = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = workload
_SPEC.loader.exec_module(workload)

SUBSCRIPTION = "00000000-0000-4000-8000-000000000101"
BOX_ID = "00000000-0000-4000-8000-000000000102"
LINEAGE = "00000000-0000-4000-8000-000000000103"
RESOURCE_GROUP = "rg-cosmas-os-beta-testbeta"
BETA_ID = "testbeta"
REGISTRY = "cosmastest.azurecr.io"
API_DIGEST = "sha256:" + "1" * 64
WEB_DIGEST = "sha256:" + "2" * 64
MANAGED_ENVIRONMENT_ID = (
    f"/subscriptions/{SUBSCRIPTION}/resourceGroups/{RESOURCE_GROUP}/providers/"
    f"Microsoft.App/managedEnvironments/cae-cosmas-beta-{BETA_ID}"
)
CONTAINER_APPS_SUBNET_ID = (
    f"/subscriptions/{SUBSCRIPTION}/resourceGroups/{RESOURCE_GROUP}/providers/"
    f"Microsoft.Network/virtualNetworks/vnet-cosmas-beta-{BETA_ID}/subnets/"
    "snet-container-apps"
)
LOG_ANALYTICS_CUSTOMER_ID = "00000000-0000-4000-8000-000000000105"
RUNTIME_CLIENT_ID = "00000000-0000-4000-8000-000000000104"
WEB_ORIGIN = "https://web.example.invalid"
KEY_VAULT_URI = "https://kvtest.vault.azure.net/"
BLOB_ACCOUNT_URL = "https://blobtest.blob.core.windows.net/"


def _identity(name: str) -> str:
    return (
        f"/subscriptions/{SUBSCRIPTION}/resourceGroups/{RESOURCE_GROUP}/providers/"
        f"Microsoft.ManagedIdentity/userAssignedIdentities/{name}"
    )


def _resource_id(kind: str) -> str:
    return (
        f"/subscriptions/{SUBSCRIPTION}/resourceGroups/{RESOURCE_GROUP}/providers/"
        f"Microsoft.App/containerApps/ca-{kind}-cosmas-beta-{BETA_ID}"
    )


def _image(kind: str) -> str:
    repository = "cosmas-os-web" if kind == "web" else "cosmas-os"
    digest = WEB_DIGEST if kind == "web" else API_DIGEST
    return f"{REGISTRY}/{repository}@{digest}"


def _app(kind: str, revision: str) -> dict[str, Any]:
    identity = _identity("id-web") if kind == "web" else _identity("id-runtime")
    configuration: dict[str, Any] = {
        "activeRevisionsMode": "Single",
        "maxInactiveRevisions": 3,
        "registries": [{"server": REGISTRY, "identity": identity}],
        "secrets": _secrets(kind),
    }
    if kind != "worker":
        configuration["ingress"] = {
            "external": True,
            "allowInsecure": False,
            "targetPort": 8080 if kind == "web" else 8000,
            "fqdn": f"{kind}.example.invalid",
            "traffic": [{"latestRevision": True, "weight": 100}],
        }
    container = _container(kind)
    return {
        "id": _resource_id(kind),
        "location": "centralus",
        "identity": {"type": "UserAssigned", "userAssignedIdentities": {identity: {}}},
        "tags": {
            "track": "B",
            "product": "cosmas-os",
            "env": "early_adopter_beta",
            "deployment_mode": "synthetic_lab",
            "data_classification": "synthetic-only",
            "registry_posture": "private",
            "box_scope": "dedicated",
            "box_id": BOX_ID,
            "connectors": "dark",
            "managed": "terraform",
        },
        "properties": {
            "provisioningState": "Succeeded",
            "managedEnvironmentId": MANAGED_ENVIRONMENT_ID,
            "latestRevisionName": revision,
            "latestReadyRevisionName": revision,
            "configuration": configuration,
            "template": {"containers": [container], "scale": _scale(kind)},
        },
    }


def _probes(kind: str) -> list[dict[str, Any]]:
    port = 8080 if kind == "web" else 8001 if kind == "worker" else 8000
    startup_path = "/healthz" if kind == "web" else "/ready" if kind == "worker" else "/health"
    probes = [
        {
            "type": "Startup",
            "httpGet": {"path": startup_path, "port": port, "scheme": "HTTP"},
            "periodSeconds": 5,
            "timeoutSeconds": 5 if kind == "worker" else 2,
            "failureThreshold": 60 if kind == "worker" else 30,
            "successThreshold": 1,
        },
        {
            "type": "Readiness",
            "httpGet": {
                "path": "/healthz" if kind == "web" else "/ready",
                "port": port,
                "scheme": "HTTP",
            },
            "initialDelaySeconds": 2 if kind == "web" else 0 if kind == "worker" else 5,
            "periodSeconds": 10,
            "timeoutSeconds": 2 if kind == "web" else 5,
            "failureThreshold": 3,
            "successThreshold": 1,
        },
    ]
    if kind == "web":
        probes.append(
            {
                "type": "Liveness",
                "httpGet": {"path": "/healthz", "port": 8080, "scheme": "HTTP"},
                "initialDelaySeconds": 10,
                "periodSeconds": 30,
                "timeoutSeconds": 2,
                "failureThreshold": 3,
                "successThreshold": 1,
            }
        )
    return probes


def _scale(kind: str) -> dict[str, int]:
    minimum, maximum = {"api": (1, 2), "worker": (1, 1), "web": (0, 1)}[kind]
    return {"minReplicas": minimum, "maxReplicas": maximum}


def _runtime_env() -> list[dict[str, str]]:
    values = {
        "COSMAS_ENV": "early_adopter_beta",
        "DATA_MODE": "synthetic",
        "AUTH_MODE": "clerk_jwt",
        "CORS_ALLOWED_ORIGINS": WEB_ORIGIN,
        "SYNTH_SEED": "false",
        "BLOB_BACKEND": "azure",
        "BETA_BOX_ID": BOX_ID,
        "CLERK_ORGANIZATION_ID": "org_beta",
        "CLERK_ISSUER": "https://clerk.example.invalid/",
        "CLERK_JWKS_URL": "https://clerk.example.invalid/.well-known/jwks.json",
        "CLERK_AUDIENCE": "cosmas-beta",
        "CLERK_AUTHORIZED_PARTIES": WEB_ORIGIN,
        "AZURE_CLIENT_ID": RUNTIME_CLIENT_ID,
        "AZURE_STORAGE_ACCOUNT_URL": BLOB_ACCOUNT_URL,
        "AZURE_BLOB_CONTAINER": "artifacts",
        "SYNC_WORKER": "false",
    }
    result = [{"name": name, "value": value} for name, value in values.items()]
    result.extend(
        {"name": name, "secretRef": secret}
        for name, secret in {
            "HUMAN_DEPLOY_EVIDENCE_REF": "human-deploy-evidence-reference",
            "DATABASE_URL": "database-url",
            "REDIS_URL": "redis-url",
        }.items()
    )
    return result


def _secrets(kind: str) -> list[dict[str, str]]:
    if kind == "web":
        return []
    return [
        {
            "name": name,
            "identity": _identity("id-runtime"),
            "keyVaultUrl": f"{KEY_VAULT_URI}secrets/{name}",
        }
        for name in ("database-url", "redis-url", "human-deploy-evidence-reference")
    ]


def _container(kind: str) -> dict[str, Any]:
    cpu, memory = {
        "api": (0.5, "1Gi"),
        "worker": (0.5, "1Gi"),
        "web": (0.25, "0.5Gi"),
    }[kind]
    container: dict[str, Any] = {
        "name": kind,
        "image": _image(kind),
        "resources": {"cpu": cpu, "memory": memory},
        "probes": _probes(kind),
        "env": [] if kind == "web" else _runtime_env(),
    }
    if kind == "worker":
        container["command"] = ["celery"]
        container["args"] = [
            "-A",
            "cosmas_os.worker.celery_app:celery_app",
            "worker",
            "--loglevel=INFO",
            "--concurrency=1",
        ]
    return container


def _revision(kind: str, name: str) -> dict[str, Any]:
    container = _container(kind)
    return {
        "id": f"{_resource_id(kind)}/revisions/{name}",
        "name": name,
        "properties": {
            "active": True,
            "healthState": "Healthy",
            "provisioningState": "Provisioned",
            "replicas": 0 if kind == "web" else 1,
            "template": {"containers": [container], "scale": _scale(kind)},
        },
    }


def _environment() -> dict[str, str]:
    return {
        "COSMAS_WORKLOAD_SUBSCRIPTION_ID": SUBSCRIPTION,
        "COSMAS_WORKLOAD_RESOURCE_GROUP": RESOURCE_GROUP,
        "COSMAS_WORKLOAD_BETA_ID": BETA_ID,
        "COSMAS_WORKLOAD_BOX_ID": BOX_ID,
        "COSMAS_WORKLOAD_REGISTRY": REGISTRY,
        "COSMAS_WORKLOAD_RUNTIME_IDENTITY_ID": _identity("id-runtime"),
        "COSMAS_WORKLOAD_WEB_IDENTITY_ID": _identity("id-web"),
        "COSMAS_WORKLOAD_MANAGED_ENVIRONMENT_ID": MANAGED_ENVIRONMENT_ID,
        "COSMAS_WORKLOAD_LOG_ANALYTICS_CUSTOMER_ID": LOG_ANALYTICS_CUSTOMER_ID,
        "COSMAS_WORKLOAD_RUNTIME_IDENTITY_CLIENT_ID": RUNTIME_CLIENT_ID,
        "COSMAS_WORKLOAD_WEB_ORIGIN": WEB_ORIGIN,
        "COSMAS_WORKLOAD_CLERK_ORGANIZATION_ID": "org_beta",
        "COSMAS_WORKLOAD_CLERK_ISSUER": "https://clerk.example.invalid/",
        "COSMAS_WORKLOAD_CLERK_JWKS_URL": "https://clerk.example.invalid/.well-known/jwks.json",
        "COSMAS_WORKLOAD_CLERK_AUDIENCE": "cosmas-beta",
        "COSMAS_WORKLOAD_BLOB_ACCOUNT_URL": BLOB_ACCOUNT_URL,
        "COSMAS_WORKLOAD_BLOB_CONTAINER": "artifacts",
        "COSMAS_WORKLOAD_KEY_VAULT_URI": KEY_VAULT_URI,
        "COSMAS_WORKLOAD_REGISTRY_POSTURE": "private",
        "COSMAS_WORKLOAD_API_READY_URL": "https://api.example.invalid/ready",
        "COSMAS_WORKLOAD_WEB_HEALTH_URL": "https://web.example.invalid/healthz",
        "COSMAS_WORKLOAD_SOURCE_SHA": "a" * 40,
        "COSMAS_WORKLOAD_RELEASE_ID": "release-b",
        "COSMAS_WORKLOAD_API_DIGEST": API_DIGEST,
        "COSMAS_WORKLOAD_WEB_DIGEST": WEB_DIGEST,
        "COSMAS_WORKLOAD_STATE_LINEAGE": LINEAGE,
        "COSMAS_WORKLOAD_STATE_SERIAL": "42",
        "COSMAS_WORKLOAD_STATE_SHA256": "b" * 64,
    }


class FakeRunner:
    def __init__(self) -> None:
        self.health_status = "200"
        self.managed_environment: dict[str, Any] = {
            "id": MANAGED_ENVIRONMENT_ID,
            "name": f"cae-cosmas-beta-{BETA_ID}",
            "type": "Microsoft.App/managedEnvironments",
            "location": "centralus",
            "properties": {
                "provisioningState": "Succeeded",
                "vnetConfiguration": {
                    "infrastructureSubnetId": CONTAINER_APPS_SUBNET_ID,
                    "internal": False,
                },
                "appLogsConfiguration": {
                    "destination": "log-analytics",
                    "logAnalyticsConfiguration": {
                        "customerId": LOG_ANALYTICS_CUSTOMER_ID,
                    },
                },
            },
        }
        self.apps: dict[str, dict[str, Any]] = {}
        self.revisions: dict[str, list[dict[str, Any]]] = {}
        self.revision_next_links: dict[str, object] = {}
        self.arm_urls: list[str] = []
        self.arm_calls: list[tuple[str, ...]] = []
        self.curl_calls: list[tuple[str, ...]] = []
        for kind in ("api", "worker", "web"):
            name = f"ca-{kind}-cosmas-beta-{BETA_ID}--ready"
            self.apps[kind] = _app(kind, name)
            self.revisions[kind] = [_revision(kind, name)]

    def run(self, argv: list[str] | tuple[str, ...]) -> Any:
        if argv[0] == workload._CURL_BINARY:
            self.curl_calls.append(tuple(argv))
            body = (
                '{"status":"ready","env":"early_adopter_beta"}\n'
                if argv[-1].endswith("/ready")
                else "ok\n"
            )
            return workload.CommandResult(
                0,
                f"{body}\n{self.health_status}",
            )
        url = argv[argv.index("--url") + 1]
        self.arm_calls.append(tuple(argv))
        self.arm_urls.append(url)
        if "/managedEnvironments/" in url:
            return workload.CommandResult(0, json.dumps(self.managed_environment))
        kind = next(kind for kind in ("api", "worker", "web") if f"ca-{kind}-" in url)
        value: dict[str, Any]
        if "/revisions?" in url:
            value = {"value": self.revisions[kind]}
            if kind in self.revision_next_links:
                value["nextLink"] = self.revision_next_links[kind]
        else:
            value = self.apps[kind]
        return workload.CommandResult(0, json.dumps(value))


def test_workload_verification_proves_exact_topology_and_health() -> None:
    runner = FakeRunner()
    evidence = workload.verify_workload(
        workload.Config.from_environment(_environment()),
        runner,
        now=datetime(2026, 9, 4, 12, 0, tzinfo=UTC),
    )

    payload = {key: value for key, value in evidence.items() if key != "evidence_payload_sha256"}
    assert (
        evidence["evidence_payload_sha256"]
        == hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    assert evidence["status"] == "verified"
    assert evidence["images"] == {
        "api": API_DIGEST,
        "worker": API_DIGEST,
        "web": WEB_DIGEST,
    }
    assert evidence["state"] == {
        "exists": True,
        "lineage": LINEAGE,
        "serial": 42,
        "sha256": "b" * 64,
    }
    assert evidence["worker_private_and_ready"] is True
    assert evidence["worker_probe_configuration_verified"] is True
    assert evidence["synthetic_box_id_returned"] is True
    assert evidence["person_or_patient_identifiers_returned"] is False
    assert evidence["box_id"] == BOX_ID
    assert set(evidence["revision_id_sha256"]) == {"api", "worker", "web"}
    assert runner.arm_urls[0].startswith(f"https://management.azure.com{MANAGED_ENVIRONMENT_ID}?")
    assert all(
        call[:5] == (workload._AZ_BINARY, "rest", "--method", "get", "--url")
        for call in runner.arm_calls
    )
    assert all(
        call[:2] == (workload._CURL_BINARY, "--disable")
        and ("--noproxy", "*") == call[call.index("--noproxy") : call.index("--noproxy") + 2]
        and workload._SYSTEM_CA_BUNDLE in call
        for call in runner.curl_calls
    )
    serialized = json.dumps(evidence)
    assert "example.invalid" not in serialized
    assert "/subscriptions/" not in serialized


def test_workload_verification_evidence_round_trips_with_python_canonical_hash(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
    first = workload.verify_workload(
        workload.Config.from_environment(_environment()), FakeRunner(), now=now
    )
    artifact = tmp_path / "workload-verification.json"
    artifact.write_text(json.dumps(first, indent=2) + "\n", encoding="utf-8")
    stored = json.loads(artifact.read_text(encoding="utf-8"))
    expected_hash = stored.pop("evidence_payload_sha256")

    assert (
        hashlib.sha256(
            json.dumps(stored, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        == expected_hash
    )
    assert (
        workload.verify_workload(
            workload.Config.from_environment(_environment()), FakeRunner(), now=now
        )
        == first
    )


@pytest.mark.parametrize("empty_array", [None, []], ids=["null", "empty-list"])
def test_workload_verification_accepts_realistic_empty_arm_defaults(
    empty_array: object,
) -> None:
    runner = FakeRunner()
    for kind in ("api", "worker", "web"):
        for template in (
            runner.apps[kind]["properties"]["template"],
            runner.revisions[kind][0]["properties"]["template"],
        ):
            template.update({"initContainers": empty_array, "volumes": empty_array})
            template["containers"][0]["volumeMounts"] = empty_array
            if kind != "worker":
                template["containers"][0].update({"command": None, "args": None})
        runner.revision_next_links[kind] = None
    for kind in ("api", "web"):
        runner.apps[kind]["properties"]["configuration"]["ingress"]["customDomains"] = empty_array
    runner.apps["web"]["properties"]["configuration"]["secrets"] = empty_array
    runner.apps["web"]["properties"]["template"]["containers"][0]["env"] = empty_array
    runner.revisions["web"][0]["properties"]["template"]["containers"][0]["env"] = empty_array

    evidence = workload.verify_workload(
        workload.Config.from_environment(_environment()),
        runner,
        now=datetime(2026, 9, 4, 12, 0, tzinfo=UTC),
    )

    assert evidence["status"] == "verified"


def test_workload_verification_accepts_managed_custom_domain_certificate() -> None:
    runner = FakeRunner()
    ingress = runner.apps["web"]["properties"]["configuration"]["ingress"]
    ingress["fqdn"] = "ca-web-cosmas-beta-testbeta.example.azurecontainerapps.io"
    ingress["customDomains"] = [
        {
            "name": "web.example.invalid",
            "bindingType": "SniEnabled",
            "certificateId": (f"{MANAGED_ENVIRONMENT_ID}/managedCertificates/web-example").upper(),
        }
    ]

    evidence = workload.verify_workload(
        workload.Config.from_environment(_environment()),
        runner,
        now=datetime(2026, 9, 4, 12, 0, tzinfo=UTC),
    )

    assert evidence["web_health_verified"] is True


@pytest.mark.parametrize(
    "certificate_id",
    [
        f"{MANAGED_ENVIRONMENT_ID}/certificates/legacy-path",
        f"{_resource_id('api')}/managedCertificates/wrong-parent",
        f"{MANAGED_ENVIRONMENT_ID}/managedCertificates/{'a' * 261}",
    ],
)
def test_workload_verification_rejects_mismatched_managed_certificate(
    certificate_id: str,
) -> None:
    runner = FakeRunner()
    ingress = runner.apps["web"]["properties"]["configuration"]["ingress"]
    ingress["fqdn"] = "ca-web-cosmas-beta-testbeta.example.azurecontainerapps.io"
    ingress["customDomains"] = [
        {
            "name": "web.example.invalid",
            "bindingType": "SniEnabled",
            "certificateId": certificate_id,
        }
    ]

    with pytest.raises(workload.WorkloadVerificationError, match="health route"):
        workload.verify_workload(
            workload.Config.from_environment(_environment()),
            runner,
            now=datetime(2026, 9, 4, 12, 0, tzinfo=UTC),
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        pytest.param(
            lambda runner: runner.apps["api"]["properties"]["template"].update(
                {"initContainers": {}}
            ),
            "template contract",
            id="object-as-init-containers",
        ),
        pytest.param(
            lambda runner: runner.revisions["web"][0]["properties"]["template"].update(
                {"volumes": [{"name": "unsafe"}]}
            ),
            "template contract",
            id="nonempty-volumes",
        ),
        pytest.param(
            lambda runner: runner.apps["api"]["properties"]["template"]["containers"][0].update(
                {"volumeMounts": {}}
            ),
            "container contract",
            id="object-as-volume-mounts",
        ),
        pytest.param(
            lambda runner: runner.revisions["api"][0]["properties"]["template"]["containers"][
                0
            ].update({"command": ["unsafe"]}),
            "command/args",
            id="nonempty-api-command",
        ),
        pytest.param(
            lambda runner: runner.apps["worker"]["properties"]["template"]["containers"][0].update(
                {"args": None}
            ),
            "command/args",
            id="null-worker-args",
        ),
    ],
)
def test_workload_verification_rejects_unsafe_arm_defaults(mutation, message: str) -> None:
    runner = FakeRunner()
    mutation(runner)
    with pytest.raises(workload.WorkloadVerificationError, match=message):
        workload.verify_workload(
            workload.Config.from_environment(_environment()),
            runner,
            now=datetime(2026, 9, 4, 12, 0, tzinfo=UTC),
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda runner: runner.apps["api"]["properties"]["configuration"]["ingress"][
                "traffic"
            ].append({"weight": 1}),
            "route",
        ),
        (
            lambda runner: runner.revisions["worker"][0]["properties"].update({"replicas": 0}),
            "ready",
        ),
        (
            lambda runner: runner.apps["web"]["properties"]["template"]["containers"][0].update(
                {"image": f"{REGISTRY}/cosmas-os-web:latest"}
            ),
            "binding",
        ),
        (
            lambda runner: runner.apps["worker"]["properties"]["template"]["containers"][0].update(
                {"probes": []}
            ),
            "probes",
        ),
        (
            lambda runner: runner.revisions["worker"][0]["properties"]["template"]["containers"][0][
                "probes"
            ][1]["httpGet"].update({"port": 8000}),
            "probes",
        ),
        (
            lambda runner: runner.apps["api"]["properties"].update(
                {"managedEnvironmentId": _resource_id("api")}
            ),
            "binding",
        ),
        (
            lambda runner: runner.apps["api"]["tags"].update({"box_id": BOX_ID[:-1] + "9"}),
            "binding",
        ),
        (
            lambda runner: runner.apps["api"]["properties"]["template"]["containers"][0][
                "env"
            ].append({"name": "UNREVIEWED", "value": "true"}),
            "environment",
        ),
        (
            lambda runner: runner.apps["worker"]["properties"]["configuration"]["secrets"][
                0
            ].update({"keyVaultUrl": f"{KEY_VAULT_URI}secrets/wrong"}),
            "secret",
        ),
        (
            lambda runner: runner.apps["api"]["properties"]["template"]["containers"][0]["probes"][
                0
            ].update({"timeoutSeconds": 9}),
            "probes",
        ),
        (
            lambda runner: runner.revisions["web"][0]["properties"]["template"]["containers"][0][
                "probes"
            ][2]["httpGet"].update({"path": "/"}),
            "probes",
        ),
        (
            lambda runner: runner.apps["worker"]["properties"]["template"]["containers"][0].update(
                {"args": ["worker"]}
            ),
            "command/args",
        ),
        (
            lambda runner: runner.revisions["api"][0]["properties"]["template"]["scale"].update(
                {"maxReplicas": 9}
            ),
            "scale",
        ),
    ],
)
def test_workload_verification_fails_closed_on_drift(mutation, message: str) -> None:
    runner = FakeRunner()
    mutation(runner)
    with pytest.raises(workload.WorkloadVerificationError, match=message):
        workload.verify_workload(
            workload.Config.from_environment(_environment()),
            runner,
            now=datetime(2026, 9, 4, 12, 0, tzinfo=UTC),
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        pytest.param(
            lambda runner: runner.managed_environment.update({"location": "eastus"}),
            "managed environment",
            id="managed-environment-location",
        ),
        pytest.param(
            lambda runner: runner.managed_environment.update({"id": _resource_id("api")}),
            "managed environment",
            id="managed-environment-resource-id",
        ),
        pytest.param(
            lambda runner: runner.managed_environment["properties"]["vnetConfiguration"].update(
                {"infrastructureSubnetId": CONTAINER_APPS_SUBNET_ID + "-wrong"}
            ),
            "managed environment",
            id="managed-environment-subnet",
        ),
        pytest.param(
            lambda runner: runner.managed_environment["properties"]["vnetConfiguration"].update(
                {"internal": True}
            ),
            "managed environment",
            id="managed-environment-internal",
        ),
        pytest.param(
            lambda runner: runner.managed_environment["properties"]["vnetConfiguration"].update(
                {"platformReservedCidr": "10.255.0.0/16"}
            ),
            "managed environment",
            id="managed-environment-platform-reserved-cidr",
        ),
        pytest.param(
            lambda runner: runner.managed_environment["properties"]["appLogsConfiguration"][
                "logAnalyticsConfiguration"
            ].update({"customerId": "00000000-0000-4000-8000-000000000999"}),
            "managed environment",
            id="managed-environment-log-analytics-customer",
        ),
        pytest.param(
            lambda runner: runner.managed_environment["properties"]["appLogsConfiguration"].update(
                {"destination": "azure-monitor"}
            ),
            "managed environment",
            id="managed-environment-log-destination",
        ),
        pytest.param(
            lambda runner: runner.apps["api"].update({"location": "eastus"}),
            "binding",
            id="container-app-location",
        ),
        pytest.param(
            lambda runner: runner.apps["api"]["properties"]["template"]["containers"][0][
                "resources"
            ].update({"cpu": 1.0}),
            "CPU/memory",
            id="app-cpu",
        ),
        pytest.param(
            lambda runner: runner.revisions["web"][0]["properties"]["template"]["containers"][0][
                "resources"
            ].update({"memory": "1Gi"}),
            "CPU/memory",
            id="revision-memory",
        ),
        pytest.param(
            lambda runner: runner.apps["api"]["properties"]["template"]["containers"][0][
                "resources"
            ].update({"ephemeralStorage": "99Gi"}),
            "CPU/memory",
            id="app-ephemeral-storage",
        ),
        pytest.param(
            lambda runner: runner.revisions["web"][0]["properties"]["template"]["containers"][0][
                "resources"
            ].update({"ephemeralStorage": "2Gi"}),
            "CPU/memory",
            id="revision-ephemeral-storage",
        ),
        pytest.param(
            lambda runner: runner.apps["api"]["properties"]["configuration"].update(
                {"maxInactiveRevisions": 0}
            ),
            "configuration contract",
            id="max-inactive-revisions-zero",
        ),
        pytest.param(
            lambda runner: runner.apps["api"]["properties"]["configuration"].update(
                {"maxInactiveRevisions": False}
            ),
            "configuration contract",
            id="bool-as-max-inactive-revisions",
        ),
        pytest.param(
            lambda runner: runner.apps["api"]["properties"]["template"]["scale"].update(
                {"rules": [{"name": "unreviewed"}]}
            ),
            "scale contract",
            id="app-scale-rule",
        ),
        pytest.param(
            lambda runner: runner.revisions["worker"][0]["properties"]["template"]["scale"].update(
                {"rules": [{"name": "unreviewed"}]}
            ),
            "scale contract",
            id="revision-scale-rule",
        ),
        pytest.param(
            lambda runner: runner.apps["api"]["properties"]["configuration"]["registries"][
                0
            ].update({"passwordSecretRef": "registry-password"}),
            "registry binding",
            id="registry-password-credential",
        ),
        pytest.param(
            lambda runner: runner.apps["api"]["properties"]["configuration"]["registries"][
                0
            ].update({"username": "unreviewed"}),
            "registry binding",
            id="registry-username-credential",
        ),
        pytest.param(
            lambda runner: runner.apps["api"]["properties"]["configuration"]["registries"][
                0
            ].update({"unexpected": "field"}),
            "registry binding",
            id="registry-unexpected-field",
        ),
        pytest.param(
            lambda runner: runner.revision_next_links.update(
                {"api": "https://management.azure.com/unreviewed-next-page"}
            ),
            "revision response",
            id="revision-next-link",
        ),
        pytest.param(
            lambda runner: runner.revision_next_links.update({"api": []}),
            "revision response",
            id="non-null-revision-next-link",
        ),
        pytest.param(
            lambda runner: runner.revisions["api"].append(
                {
                    "id": f"{_resource_id('web')}/revisions/unbound-revision",
                    "name": "unbound-revision",
                    "properties": {"active": False},
                }
            ),
            "revision response",
            id="unbound-inactive-revision-in-full-page",
        ),
        pytest.param(
            lambda runner: runner.apps["worker"]["properties"]["template"]["scale"].update(
                {"maxReplicas": True}
            ),
            "scale contract",
            id="bool-as-scale-integer",
        ),
        pytest.param(
            lambda runner: runner.apps["api"]["properties"]["template"]["containers"][0]["probes"][
                0
            ].update({"successThreshold": True}),
            "probes",
            id="bool-as-probe-integer",
        ),
        pytest.param(
            lambda runner: runner.revisions["worker"][0]["properties"].update({"replicas": True}),
            "ready",
            id="bool-as-replica-integer",
        ),
        pytest.param(
            lambda runner: runner.apps["worker"]["properties"]["template"]["scale"].update(
                {"maxReplicas": 1.0}
            ),
            "scale contract",
            id="float-as-scale-integer",
        ),
        pytest.param(
            lambda runner: runner.apps["api"]["properties"]["template"].update(
                {"initContainers": [_container("api")]}
            ),
            "template contract",
            id="app-init-container",
        ),
        pytest.param(
            lambda runner: runner.revisions["worker"][0]["properties"]["template"].update(
                {"volumes": [{"name": "secret", "storageType": "Secret"}]}
            ),
            "template contract",
            id="revision-secret-volume",
        ),
        pytest.param(
            lambda runner: runner.apps["web"]["properties"]["template"].update(
                {"serviceBinds": [{"serviceId": _resource_id("api")}]}
            ),
            "template contract",
            id="app-service-bind",
        ),
        pytest.param(
            lambda runner: runner.revisions["api"][0]["properties"]["template"]["containers"][
                0
            ].update({"volumeMounts": [{"volumeName": "secret", "mountPath": "/secret"}]}),
            "container contract",
            id="revision-volume-mount",
        ),
        pytest.param(
            lambda runner: runner.apps["api"]["properties"]["configuration"].update(
                {"dapr": {"enabled": True, "appId": "unreviewed"}}
            ),
            "configuration contract",
            id="dapr-sidecar",
        ),
        pytest.param(
            lambda runner: runner.apps["api"]["properties"]["configuration"]["ingress"].update(
                {
                    "customDomains": [
                        {
                            "name": "evil.example.invalid",
                            "bindingType": "SniEnabled",
                            "certificateId": f"{MANAGED_ENVIRONMENT_ID}/certificates/evil",
                        }
                    ]
                }
            ),
            "health route",
            id="extra-custom-domain",
        ),
        pytest.param(
            lambda runner: runner.apps["api"]["properties"]["configuration"]["ingress"].update(
                {"customDomains": False}
            ),
            "health route",
            id="bool-as-empty-custom-domains",
        ),
        pytest.param(
            lambda runner: runner.apps["api"]["properties"]["configuration"]["ingress"]["traffic"][
                0
            ].update({"unreviewed": True}),
            "route",
            id="traffic-extra-field",
        ),
        pytest.param(
            lambda runner: runner.apps["web"]["properties"]["configuration"].update(
                {"secrets": False}
            ),
            "secret references",
            id="bool-as-empty-secrets",
        ),
        pytest.param(
            lambda runner: runner.apps["web"]["properties"]["template"]["containers"][0].update(
                {"env": False}
            ),
            "runtime environment",
            id="bool-as-empty-web-env",
        ),
        pytest.param(
            lambda runner: runner.apps["api"]["properties"]["template"]["containers"][0].update(
                {"command": False}
            ),
            "command/args",
            id="bool-as-empty-command",
        ),
        pytest.param(
            lambda runner: runner.apps["web"]["properties"]["template"]["containers"][0].update(
                {"args": {}}
            ),
            "command/args",
            id="object-as-empty-args",
        ),
        pytest.param(
            lambda runner: runner.apps["api"]["properties"]["configuration"]["ingress"].update(
                {
                    "additionalPortMappings": [
                        {"external": True, "targetPort": 9000, "exposedPort": 9000}
                    ]
                }
            ),
            "route",
            id="additional-external-port",
        ),
        pytest.param(
            lambda runner: runner.apps["api"]["properties"]["configuration"]["ingress"].update(
                {"clientCertificateMode": "Require"}
            ),
            "route",
            id="client-certificate-mode",
        ),
        pytest.param(
            lambda runner: runner.apps["api"]["properties"]["configuration"]["ingress"].update(
                {"exposedPort": False}
            ),
            "route",
            id="bool-as-exposed-port-integer",
        ),
        pytest.param(
            lambda runner: runner.apps["api"]["properties"]["configuration"]["ingress"].update(
                {"transport": "tcp"}
            ),
            "route",
            id="tcp-transport",
        ),
        pytest.param(
            lambda runner: runner.apps["api"]["properties"]["configuration"]["ingress"].update(
                {"ipSecurityRestrictions": [{"action": "Allow", "ipAddressRange": "0.0.0.0/0"}]}
            ),
            "route",
            id="unreviewed-ip-rule",
        ),
    ],
)
def test_workload_verification_rejects_unreviewed_live_contract(mutation, message: str) -> None:
    runner = FakeRunner()
    mutation(runner)
    with pytest.raises(workload.WorkloadVerificationError, match=message):
        workload.verify_workload(
            workload.Config.from_environment(_environment()),
            runner,
            now=datetime(2026, 9, 4, 12, 0, tzinfo=UTC),
        )


def test_workload_verification_rejects_reused_api_and_web_digest() -> None:
    environment = _environment()
    environment["COSMAS_WORKLOAD_WEB_DIGEST"] = API_DIGEST
    with pytest.raises(workload.WorkloadVerificationError, match="configuration invalid"):
        workload.Config.from_environment(environment)


def test_workload_verification_requires_exact_http_200() -> None:
    runner = FakeRunner()
    runner.health_status = "302"
    with pytest.raises(workload.WorkloadVerificationError, match="health check"):
        workload.verify_workload(
            workload.Config.from_environment(_environment()),
            runner,
            now=datetime(2026, 9, 4, 12, 0, tzinfo=UTC),
        )


def test_subprocess_runner_uses_fixed_commands_and_allowlisted_environment(
    monkeypatch,
) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(argv, **kwargs):
        calls.append((list(argv), kwargs))
        return SimpleNamespace(returncode=0, stdout="{}", stderr="")

    monkeypatch.setattr(workload.subprocess, "run", fake_run)
    monkeypatch.setenv("AZURE_CONFIG_DIR", "/run/cosmas-azure-session.ABC123")
    monkeypatch.setenv("HTTPS_PROXY", "https://attacker.invalid")
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", "/tmp/attacker-ca.pem")
    monkeypatch.setenv("AZURE_CLI_DISABLE_CONNECTION_VERIFICATION", "1")
    runner = workload.SubprocessRunner()
    runner.run([workload._AZ_BINARY, "rest"])
    runner.run([workload._CURL_BINARY, "--disable"])

    assert calls[0][0][0] == workload._AZ_BINARY
    assert calls[1][0][0] == workload._CURL_BINARY
    assert calls[0][1]["env"] == {
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": workload._COMMAND_PATH,
        "AZURE_CONFIG_DIR": "/run/cosmas-azure-session.ABC123",
        "AZURE_CORE_NO_COLOR": "1",
        "AZURE_CORE_ONLY_SHOW_ERRORS": "1",
    }
    assert calls[1][1]["env"] == {
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": workload._COMMAND_PATH,
    }


def test_subprocess_runner_rejects_ambient_or_unreviewed_commands(monkeypatch) -> None:
    monkeypatch.delenv("AZURE_CONFIG_DIR", raising=False)
    runner = workload.SubprocessRunner()
    with pytest.raises(workload.WorkloadVerificationError, match="session boundary"):
        runner.run([workload._AZ_BINARY, "rest"])
    with pytest.raises(workload.WorkloadVerificationError, match="unreviewed"):
        runner.run(["az", "rest"])
