from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTRACT = PROJECT_ROOT / "infra" / "beta" / "runtime-acceptance-job-contract.jq"
START_CONTRACT = PROJECT_ROOT / "infra" / "beta" / "runtime-acceptance-start-request.jq"
EXECUTION_CONTRACT = PROJECT_ROOT / "infra" / "beta" / "runtime-acceptance-execution-contract.jq"
IDENTITY_ID = (
    "/subscriptions/00000000-0000-4000-8000-000000000001/"
    "resourcegroups/rg-cosmas-os-beta-lab01/providers/"
    "microsoft.managedidentity/userassignedidentities/id-cosmas-runtime"
)
JOB_ID = (
    "/subscriptions/00000000-0000-4000-8000-000000000001/"
    "resourcegroups/rg-cosmas-os-beta-lab01/providers/"
    "microsoft.app/jobs/job-cosmas-runtime-acceptance"
)
ENVIRONMENT_ID = (
    "/subscriptions/00000000-0000-4000-8000-000000000001/"
    "resourcegroups/rg-cosmas-os-beta-lab01/providers/"
    "microsoft.app/managedenvironments/cae-cosmas-beta"
)
REGISTRY = "cosmasbetalab01.azurecr.io"
IMAGE = f"{REGISTRY}/cosmas-os@sha256:{'a' * 64}"
CLIENT_ID = "00000000-0000-4000-8000-000000000007"
KEY_VAULT = "https://kv-cosmas-beta.vault.azure.net/secrets/"


def _environment() -> list[dict[str, str]]:
    direct = {
        "COSMAS_ENV": "early_adopter_beta",
        "DATA_MODE": "synthetic",
        "AUTH_MODE": "clerk_jwt",
        "CORS_ALLOWED_ORIGINS": "https://beta.example.test",
        "SYNTH_SEED": "false",
        "BLOB_BACKEND": "azure",
        "BETA_BOX_ID": "00000000-0000-4000-8000-000000000004",
        "CLERK_ORGANIZATION_ID": "org_beta_lab",
        "CLERK_ISSUER": "https://clerk.example.test",
        "CLERK_JWKS_URL": "https://clerk.example.test/.well-known/jwks.json",
        "CLERK_AUDIENCE": "cosmas-beta",
        "CLERK_AUTHORIZED_PARTIES": "https://beta.example.test",
        "AZURE_CLIENT_ID": CLIENT_ID,
        "EXPECTED_RUNTIME_MANAGED_IDENTITY_CLIENT_ID": CLIENT_ID,
        "AZURE_STORAGE_ACCOUNT_URL": "https://cmbeta.blob.core.windows.net/",
        "AZURE_BLOB_CONTAINER": "artifacts",
        "SYNC_WORKER": "false",
    }
    secret_refs = {
        "COSMAS_ACCEPTANCE_HMAC_KEY": "acceptance-hmac-key",
        "HUMAN_DEPLOY_EVIDENCE_REF": "human-deploy-evidence-reference",
        "DATABASE_URL": "database-url",
        "REDIS_URL": "redis-url",
    }
    return [
        *({"name": name, "value": value} for name, value in direct.items()),
        *({"name": name, "secretRef": value} for name, value in secret_refs.items()),
    ]


def _valid_job() -> dict[str, Any]:
    return {
        "id": JOB_ID,
        "identity": {
            "type": "UserAssigned",
            "userAssignedIdentities": {IDENTITY_ID: {}},
        },
        "properties": {
            "environmentId": ENVIRONMENT_ID,
            "configuration": {
                "triggerType": "Manual",
                "replicaTimeout": 900,
                "replicaRetryLimit": 0,
                "manualTriggerConfig": {
                    "parallelism": 1,
                    "replicaCompletionCount": 1,
                },
                "registries": [{"server": REGISTRY, "identity": IDENTITY_ID}],
                "secrets": [
                    {
                        "name": name,
                        "identity": IDENTITY_ID,
                        "keyVaultUrl": f"{KEY_VAULT}{secret}",
                    }
                    for name, secret in (
                        ("database-url", "database-url"),
                        ("redis-url", "redis-url"),
                        ("human-deploy-evidence-reference", "human-deploy-evidence-reference"),
                        ("acceptance-hmac-key", "runtime-acceptance-hmac-key"),
                    )
                ],
            },
            "template": {
                "containers": [
                    {
                        "name": "runtime-acceptance",
                        "image": IMAGE,
                        "resources": {"cpu": 0.25, "memory": "0.5Gi"},
                        "command": ["python", "-m", "cosmas_os.cli"],
                        "args": [
                            "verify-beta-runtime",
                            "--confirm-synthetic-only",
                            "--confirm-runtime-uami",
                        ],
                        "env": _environment(),
                    }
                ]
            },
        },
    }


def _validate(payload: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    arguments = [
        "jq",
        "-e",
        "--arg",
        "job_id",
        JOB_ID,
        "--arg",
        "image",
        IMAGE,
        "--arg",
        "registry",
        REGISTRY,
        "--arg",
        "identity_id",
        IDENTITY_ID,
        "--arg",
        "client_id",
        CLIENT_ID,
        "--arg",
        "environment_id",
        ENVIRONMENT_ID,
        "--arg",
        "box_id",
        "00000000-0000-4000-8000-000000000004",
        "--arg",
        "web_origin",
        "https://beta.example.test",
        "--arg",
        "clerk_org",
        "org_beta_lab",
        "--arg",
        "clerk_issuer",
        "https://clerk.example.test",
        "--arg",
        "clerk_jwks",
        "https://clerk.example.test/.well-known/jwks.json",
        "--arg",
        "clerk_audience",
        "cosmas-beta",
        "--arg",
        "blob_url",
        "https://cmbeta.blob.core.windows.net/",
        "--arg",
        "blob_container",
        "artifacts",
        "--arg",
        "database_secret",
        f"{KEY_VAULT}database-url",
        "--arg",
        "redis_secret",
        f"{KEY_VAULT}redis-url",
        "--arg",
        "evidence_secret",
        f"{KEY_VAULT}human-deploy-evidence-reference",
        "--arg",
        "hmac_secret",
        f"{KEY_VAULT}runtime-acceptance-hmac-key",
        "-f",
        str(CONTRACT),
    ]
    return subprocess.run(
        arguments,
        input=json.dumps(payload),
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=False,
    )


def _start_request(tmp_path: Path, phase: str = "audit-replay") -> subprocess.CompletedProcess[str]:
    job_path = tmp_path / "job.json"
    job_path.write_text(json.dumps(_valid_job()), encoding="utf-8")
    return subprocess.run(
        [
            "jq",
            "-n",
            "--arg",
            "phase",
            phase,
            "--arg",
            "prior_state_json",
            '{"safe":"state"}',
            "--slurpfile",
            "job",
            str(job_path),
            "-f",
            str(START_CONTRACT),
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def _validate_execution(
    tmp_path: Path, execution: dict[str, Any], requested: dict[str, Any]
) -> subprocess.CompletedProcess[str]:
    requested_path = tmp_path / "requested.json"
    requested_path.write_text(json.dumps(requested), encoding="utf-8")
    execution_id = f"{JOB_ID}/executions/execution-1"
    return subprocess.run(
        [
            "jq",
            "-e",
            "--slurpfile",
            "requested",
            str(requested_path),
            "--arg",
            "execution_id",
            execution_id,
            "-f",
            str(EXECUTION_CONTRACT),
        ],
        input=json.dumps(execution),
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=False,
    )


def test_runtime_acceptance_job_contract_accepts_exact_job() -> None:
    assert _validate(_valid_job()).returncode == 0
    with_ephemeral = _valid_job()
    with_ephemeral["properties"]["template"]["containers"][0]["resources"][  # type: ignore[index]
        "ephemeralStorage"
    ] = "1Gi"
    assert _validate(with_ephemeral).returncode == 0


def test_runtime_acceptance_start_request_enumerates_only_reviewed_phases(
    tmp_path: Path,
) -> None:
    result = _start_request(tmp_path)
    assert result.returncode == 0
    request = json.loads(result.stdout)
    assert request["template"]["containers"][0]["args"] == [
        "verify-beta-audit-replay",
        "--confirm-synthetic-only",
        "--confirm-no-content-export",
    ]
    assert _start_request(tmp_path, "unreviewed").returncode != 0


@pytest.mark.parametrize(
    "mutation",
    [
        "registry_server",
        "registry_password_ref",
        "inline_secret",
        "cpu",
        "memory",
        "ephemeral_storage",
        "resource_extension",
        "init_container",
        "volume_mount",
        "configuration_extension",
        "false_event_trigger",
        "false_init_containers",
        "false_volumes",
        "false_probes",
        "false_volume_mounts",
        "object_registries",
        "object_secrets",
        "object_containers",
        "object_environment",
    ],
)
def test_runtime_acceptance_job_contract_rejects_security_drift(mutation: str) -> None:
    payload = copy.deepcopy(_valid_job())
    properties = payload["properties"]
    configuration = properties["configuration"]
    container = properties["template"]["containers"][0]
    if mutation == "registry_server":
        configuration["registries"][0]["server"] = "evil.example.invalid"
    elif mutation == "registry_password_ref":
        configuration["registries"][0]["passwordSecretRef"] = "registry-password"
    elif mutation == "inline_secret":
        configuration["secrets"][0]["value"] = "not-allowed"
    elif mutation == "cpu":
        container["resources"]["cpu"] = 1
    elif mutation == "memory":
        container["resources"]["memory"] = "2Gi"
    elif mutation == "ephemeral_storage":
        container["resources"]["ephemeralStorage"] = "2Gi"
    elif mutation == "resource_extension":
        container["resources"]["gpu"] = 1
    elif mutation == "init_container":
        properties["template"]["initContainers"] = [{"name": "shadow"}]
    elif mutation == "volume_mount":
        container["volumeMounts"] = [{"volumeName": "shadow", "mountPath": "/app"}]
    elif mutation == "configuration_extension":
        configuration["dapr"] = {"enabled": True}
    elif mutation == "false_event_trigger":
        configuration["eventTriggerConfig"] = False
    elif mutation == "false_init_containers":
        properties["template"]["initContainers"] = False
    elif mutation == "false_volumes":
        properties["template"]["volumes"] = False
    elif mutation == "false_probes":
        container["probes"] = False
    elif mutation == "false_volume_mounts":
        container["volumeMounts"] = False
    elif mutation == "object_registries":
        configuration["registries"] = {"only": configuration["registries"][0]}
    elif mutation == "object_secrets":
        configuration["secrets"] = {item["name"]: item for item in configuration["secrets"]}
    elif mutation == "object_containers":
        properties["template"]["containers"] = {"only": container}
    else:
        container["env"] = {item["name"]: item for item in container["env"]}
    assert _validate(payload).returncode != 0


@pytest.mark.parametrize(
    "mutation",
    [
        "cpu",
        "resource_extension",
        "false_init_containers",
        "false_volumes",
        "false_probes",
        "false_volume_mounts",
        "object_environment",
        "object_containers",
        "command",
    ],
)
def test_runtime_acceptance_execution_contract_rejects_drift(tmp_path: Path, mutation: str) -> None:
    start_result = _start_request(tmp_path, "runtime")
    assert start_result.returncode == 0
    requested = json.loads(start_result.stdout)
    execution_id = f"{JOB_ID}/executions/execution-1"
    execution: dict[str, Any] = {
        "id": execution_id,
        "properties": {
            "status": "Succeeded",
            "template": copy.deepcopy(requested["template"]),
        },
    }
    template = execution["properties"]["template"]
    container = template["containers"][0]
    if mutation == "cpu":
        container["resources"]["cpu"] = 1
    elif mutation == "resource_extension":
        container["resources"]["gpu"] = 1
    elif mutation == "false_init_containers":
        template["initContainers"] = False
    elif mutation == "false_volumes":
        template["volumes"] = False
    elif mutation == "false_probes":
        container["probes"] = False
    elif mutation == "false_volume_mounts":
        container["volumeMounts"] = False
    elif mutation == "object_environment":
        container["env"] = {item["name"]: item for item in container["env"]}
    elif mutation == "object_containers":
        template["containers"] = {"only": container}
    else:
        container["command"] = ["sh", "-c"]
    assert _validate_execution(tmp_path, execution, requested).returncode != 0


def test_runtime_acceptance_execution_contract_accepts_exact_execution(
    tmp_path: Path,
) -> None:
    start_result = _start_request(tmp_path, "runtime")
    assert start_result.returncode == 0
    requested = json.loads(start_result.stdout)
    execution = {
        "id": f"{JOB_ID}/executions/execution-1",
        "properties": {
            "status": "Succeeded",
            "template": copy.deepcopy(requested["template"]),
        },
    }
    assert _validate_execution(tmp_path, execution, requested).returncode == 0
