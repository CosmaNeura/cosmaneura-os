"""Use export_workload_plan_fixture.py, then set COSMAS_TEST_WORKLOAD_PLAN_EXPORT.

The plan is emitted by OpenTofu. Apply/build/bootstrap companions and healthy ARM
responses are invented local evidence, not assertions about a deployed service.
"""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "infra/beta"))
binding = importlib.import_module("workload_plan_binding")
workload = binding.workload
SOURCE = "e" * 40
RELEASE = "mocked-plan-export"
LINEAGE = "00000000-0000-4000-8000-000000000016"
NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


def encoded(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def guard_projections(plan_path: Path, destination: Path) -> dict:
    source = (REPO / "infra/beta/deployment-guard-lib.sh").read_text()
    functions = []
    for name in ("guard_validate_safe_plan_actions", "guard_write_security_posture", "guard_write_critical_planned_values"):
        start = source.index(name + "() {\n")
        functions.append(source[start:source.index("\n}\n", start) + 3])
    shell = "set -euo pipefail\nguard_die() { exit 1; }\n" + "\n".join(functions) + '''
guard_validate_safe_plan_actions "$PLAN" true
guard_write_security_posture "$PLAN" "$POSTURE"
guard_write_critical_planned_values "$PLAN" "$CRITICAL"
jq -n --argjson create "$GUARD_CREATE_COUNT" --argjson update "$GUARD_UPDATE_COUNT" --argjson no_op "$GUARD_NOOP_COUNT" '{create:$create,update:$update,no_op:$no_op,delete:0,replace:0}' > "$COUNTS"
'''
    environment = {"PATH": os.defpath, "PLAN": str(plan_path)}
    for name in ("POSTURE", "CRITICAL", "COUNTS"):
        environment[name] = str(destination / (name.lower() + ".json"))
    result = subprocess.run([shutil.which("bash") or "/bin/bash", "-c", shell],
                            env=environment, capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode == 0, result.stderr
    return {name: json.loads(Path(environment[name]).read_text()) for name in ("POSTURE", "CRITICAL", "COUNTS")}


@pytest.fixture(scope="module")
def exported_plan(tmp_path_factory):
    location = os.environ.get("COSMAS_TEST_WORKLOAD_PLAN_EXPORT")
    if not location:
        pytest.skip("export the one cached-provider mocked plan and set COSMAS_TEST_WORKLOAD_PLAN_EXPORT")
    directory = Path(location).resolve(strict=True)
    receipt = json.loads((directory / "EXPORT.json").read_text())
    for relative, expected_hash in receipt["source_sha256"].items():
        assert digest((REPO / relative).read_bytes()) == expected_hash, f"stale mocked plan source: {relative}"
    raw = (directory / "plan.json").read_bytes()
    plan = json.loads(raw)
    assert plan == json.loads((directory / "test-plan-event.json").read_text())["test_plan"]
    assert len([item for item in receipt["commands"] if "test" in item["argv"]]) == 1
    assert all(item["exit_code"] == 0 for item in receipt["commands"])
    projections = guard_projections(directory / "plan.json", tmp_path_factory.mktemp("plan-projections"))
    return directory, plan, raw, projections


def companions(exported) -> dict[str, bytes]:
    directory, plan, raw, projections = exported
    values = {key: item["value"] for key, item in plan["variables"].items()}
    outputs = plan["planned_values"]["outputs"]
    def value(key):
        return outputs[key]["value"]
    boundary = {
        "subscription_id": values["subscription_id"], "tenant_id": values["tenant_id"],
        "deploy_identity_client_id": "00000000-0000-4000-8000-000000000005",
        "beta_id": values["beta_id"], "box_id": values["box_id"],
        "state_resource_group": "rg-cosmas-os-beta-state-lab01",
        "workload_resource_group": value("resource_group_name"),
        "state_vnet_id": values["state_vnet_id"],
        "state_blob_private_dns_zone_id": values["state_blob_private_dns_zone_id"],
        "deployment_mode": value("deployment_mode"), "data_classification": value("data_classification"),
    }
    bootstrap = {key: {"value": item} for key, item in boundary.items() if key not in {"beta_id", "state_resource_group", "workload_resource_group"}}
    bootstrap.update({
        "backend_key": {"value": "early-adopter-beta/lab01/terraform.tfstate"},
        "backend_resource_group_name": {"value": boundary["state_resource_group"]},
        "workload_resource_group_name": {"value": boundary["workload_resource_group"]},
    })
    # Test mode cannot save a deployment binary. These opaque bytes are explicitly
    # the mocked plan event; only their binding is exercised by the pure helper.
    opaque_plan = (directory / "test-plan-event.json").read_bytes()
    lock = (directory / "environment/.terraform.lock.hcl").read_bytes()
    state = {"version": 4, "terraform_version": plan["terraform_version"], "lineage": LINEAGE,
             "serial": 2, "outputs": {key: item for key, item in outputs.items() if item["value"] is not None}}
    state_raw = encoded(state)
    review = {
        "schema_version": 1, "phase": "subsequent", "source_sha": SOURCE,
        "plan_sha256": digest(opaque_plan), "terraform_version": plan["terraform_version"],
        "provider_lock_sha256": digest(lock), "variable_file_sha256": digest(encoded(values)),
        "prior_state": {"lineage": LINEAGE, "serial": 1, "sha256": "9" * 64},
        "boundary": boundary, "critical_planned_values": projections["CRITICAL"],
        "security_posture": projections["POSTURE"], "managed_action_counts": projections["COUNTS"],
        "managed_actions": [{key: item[key] for key in ("address", "type", "mode")}
                            | {"actions": item["change"]["actions"]} for item in plan["resource_changes"]],
    }
    result = {
        "schema_version": 1, "plan_sha256": digest(opaque_plan), "no_changes": False,
        "boundary": {"box_id": boundary["box_id"], "deployment_mode": "synthetic_lab"},
        "state": {"lineage": LINEAGE, "pre_serial": 1, "post_serial": 2,
                  "pre_sha256": "9" * 64, "post_sha256": digest(state_raw)},
    }
    build = {
        "schema_version": 1, "evidence_type": "protected-runner-build-push", "source_sha": SOURCE,
        "build_release_id": RELEASE, "box_id": boundary["box_id"], "state": {"lineage": LINEAGE},
        "registry": {"login_server": value("acr_login_server"), "admin_user_enabled": False},
        "images": {kind: {"digest": value(output).split("@", 1)[1], "tag_write_delete_locked": True,
                          "manifest_write_delete_locked": True, "high_critical_vulnerabilities": 0}
                   for kind, output in (("api", "image_reference"), ("web", "web_image_reference"))},
    }
    build["evidence_payload_sha256"] = digest(encoded(build) + b"\n")
    return {"plan": opaque_plan, "plan_json": raw, "review": encoded(review), "var_file": encoded(values),
            "apply_result": encoded(result), "state": state_raw, "bootstrap_outputs": encoded(bootstrap),
            "build_evidence": encoded(build), "provider_lock": lock}


class PlanRunner:
    """Invent healthy ARM observations; copy configured runtime values from the plan."""

    def __init__(self, plan: dict):
        self.calls = []
        resources = {item["address"]: item["change"]["after"] for item in plan["resource_changes"]}
        outputs = plan["planned_values"]["outputs"]
        env = resources["azurerm_container_app_environment.beta"]
        self.environment = {
            "id": env["id"], "location": env["location"], "type": "Microsoft.App/managedEnvironments",
            "name": env["name"], "properties": {"provisioningState": "Succeeded",
                "vnetConfiguration": {"infrastructureSubnetId": env["infrastructure_subnet_id"], "internal": False},
                "appLogsConfiguration": {"destination": "log-analytics", "logAnalyticsConfiguration": {
                    "customerId": outputs["log_analytics_workspace_customer_id"]["value"]}}},
        }
        self.apps = {}
        self.revisions = {}
        for kind in ("api", "worker", "web"):
            actual = resources[f"azurerm_container_app.{kind}[0]"]
            original = actual["template"][0]["container"][0]
            container = {"name": original["name"], "image": original["image"],
                "resources": {key: original[key] for key in ("cpu", "memory")}, "probes": [],
                "env": [{"name": item["name"], **({"secretRef": item["secret_name"]} if item.get("secret_name")
                         else {"value": item["value"]})} for item in original["env"]]}
            for field in ("command", "args"):
                if original[field]:
                    container[field] = original[field]
            for key, label in (("startup_probe", "Startup"), ("readiness_probe", "Readiness"), ("liveness_probe", "Liveness")):
                for probe in original[key]:
                    container["probes"].append({"type": label,
                        "httpGet": {"path": probe["path"], "port": probe["port"], "scheme": probe["transport"]},
                        "initialDelaySeconds": probe["initial_delay"] or 0,
                        "periodSeconds": probe["interval_seconds"], "timeoutSeconds": probe["timeout"],
                        "failureThreshold": probe["failure_count_threshold"],
                        "successThreshold": probe.get("success_count_threshold", 1)})
            identity = actual["identity"][0]["identity_ids"][0]
            configuration = {"activeRevisionsMode": actual["revision_mode"],
                "maxInactiveRevisions": actual["max_inactive_revisions"],
                "registries": [{key: item[key] for key in ("server", "identity")} for item in actual["registry"]],
                "secrets": [{"name": item["name"], "identity": item["identity"], "keyVaultUrl": item["key_vault_secret_id"]}
                            for item in actual["secret"]]}
            if actual["ingress"]:
                ingress = actual["ingress"][0]
                configuration["ingress"] = {"external": ingress["external_enabled"],
                    "allowInsecure": ingress["allow_insecure_connections"], "targetPort": ingress["target_port"],
                    "fqdn": urlsplit(outputs["web_origin" if kind == "web" else "api_origin"]["value"]).hostname,
                    "traffic": [{"latestRevision": item["latest_revision"], "weight": item["percentage"]}
                                for item in ingress["traffic_weight"]]}
            template = {"containers": [container], "scale": {
                "minReplicas": actual["template"][0]["min_replicas"],
                "maxReplicas": actual["template"][0]["max_replicas"]}}
            revision = actual["name"] + "--ready"
            self.apps[kind] = {"id": actual["id"], "location": env["location"], "tags": actual["tags"],
                "identity": {"type": "UserAssigned", "userAssignedIdentities": {identity: {}}},
                "properties": {"provisioningState": "Succeeded", "managedEnvironmentId": actual["container_app_environment_id"],
                    "latestRevisionName": revision, "latestReadyRevisionName": revision,
                    "configuration": configuration, "template": template}}
            self.revisions[kind] = [{"id": actual["id"] + "/revisions/" + revision, "name": revision,
                "properties": {"active": True, "healthState": "Healthy", "provisioningState": "Provisioned",
                               "replicas": 0 if kind == "web" else 1, "template": copy.deepcopy(template)}}]

    def run(self, argv):
        self.calls.append(argv)
        if argv[0] == workload._CURL_BINARY:
            body = '{"status":"ready","env":"early_adopter_beta"}' if argv[-1].endswith("/ready") else "ok"
            return workload.CommandResult(0, body + "\n200")
        assert argv[0] == workload._AZ_BINARY and argv[1:4] == ["rest", "--method", "get"]
        address = argv[argv.index("--url") + 1]
        if "/managedEnvironments/" in address:
            value = self.environment
        else:
            kind = next(name for name in self.apps if f"ca-{name}-" in address)
            value = {"value": self.revisions[kind]} if "/revisions?" in address else self.apps[kind]
        return workload.CommandResult(0, json.dumps(value))


def test_actual_terraform_plan_and_guard_projections_verify_hosted_native_runtime(exported_plan) -> None:
    bound = binding.derive_binding(companions(exported_plan), source_sha=SOURCE, release_id=RELEASE)
    runner = PlanRunner(exported_plan[1])
    evidence = workload.verify_workload(bound.config, runner, now=NOW)
    binding.attestation.validate_attestation(evidence, bound.expected, observed_at=NOW)
    assert bound.config.location == "eastus2" and bound.config.api_max_replicas == 1
    assert bound.config.runtime_contract["env"]["api"]["CORS_ALLOWED_ORIGINS"] == [
        "value", "https://workspace.example.invalid,capacitor://localhost,app://cosmas"]
    assert len(bound.config.runtime_contract["secrets"]["api"]) == 5
    assert bound.config.runtime_contract["secrets"]["web"] == {}


@pytest.mark.parametrize("fault", ["feature", "secret_version", "native_origin"])
@pytest.mark.parametrize("surface", ["app", "revision"])
def test_actual_plan_bound_runtime_rejects_environment_secret_and_native_drift(exported_plan, fault, surface) -> None:
    bound = binding.derive_binding(companions(exported_plan), source_sha=SOURCE, release_id=RELEASE)
    runner = PlanRunner(exported_plan[1])
    workload.verify_workload(bound.config, runner, now=NOW)
    target = runner.apps["api"] if surface == "app" else runner.revisions["api"][0]
    env = target["properties"]["template"]["containers"][0]["env"]
    if fault == "feature":
        next(item for item in env if item["name"] == "WORKSPACE_TEAM_SETUP_ENABLED")["value"] = "false"
    elif fault == "native_origin":
        next(item for item in env if item["name"] == "CLERK_AUTHORIZED_PARTIES")["value"] = "https://workspace.example.invalid"
    elif surface == "app":
        secret = next(item for item in target["properties"]["configuration"]["secrets"] if item["name"].startswith("ws-"))
        secret["keyVaultUrl"] = secret["keyVaultUrl"].rsplit("/", 1)[0] + "/" + "f" * 32
    else:
        next(item for item in env if item["name"] == "WORKSPACE_LLM_API_KEY")["secretRef"] = "unreviewed-secret-alias"
    with pytest.raises(workload.WorkloadVerificationError):
        workload.verify_workload(bound.config, runner, now=NOW)


@pytest.mark.parametrize("fault", ["feature", "secret_version", "native_origin"])
def test_actual_plan_projection_detects_runtime_values_that_disagree_with_its_variables(exported_plan, fault) -> None:
    inputs = companions(exported_plan)
    binding.derive_binding(inputs, source_sha=SOURCE, release_id=RELEASE)
    plan = json.loads(inputs["plan_json"])
    app = next(item for item in plan["resource_changes"] if item["address"] == "azurerm_container_app.api[0]")["change"]["after"]
    env = app["template"][0]["container"][0]["env"]
    if fault == "feature":
        next(item for item in env if item["name"] == "WORKSPACE_TEAM_SETUP_ENABLED")["value"] = "false"
    elif fault == "native_origin":
        next(item for item in env if item["name"] == "CORS_ALLOWED_ORIGINS")["value"] = "https://workspace.example.invalid"
    else:
        secret = next(item for item in app["secret"] if item["name"].startswith("ws-"))
        secret["key_vault_secret_id"] = secret["key_vault_secret_id"].rsplit("/", 1)[0] + "/" + "f" * 32
    inputs["plan_json"] = encoded(plan)
    with pytest.raises(binding.BindingError, match="runtime-projection-mismatch"):
        binding.derive_binding(inputs, source_sha=SOURCE, release_id=RELEASE)


def replace_input(inputs: dict[str, bytes], name: str, value: dict) -> None:
    if name == "build_evidence":
        value.pop("evidence_payload_sha256")
        value["evidence_payload_sha256"] = digest(encoded(value) + b"\n")
    inputs[name] = encoded(value)


@pytest.mark.parametrize("fault", [
    "plan_bytes", "review_source", "review_plan_hash", "var_file_bytes", "provider_lock_bytes",
    "result_serial", "result_hash", "state_bytes", "build_source", "build_release", "build_digest",
    "duplicate_env", "unknown_env", "inline_secret", "secret_identity",
])
def test_generated_plan_chain_rejects_stale_or_unreviewed_bindings(exported_plan, fault) -> None:
    inputs = companions(exported_plan)
    binding.derive_binding(inputs, source_sha=SOURCE, release_id=RELEASE)
    if fault in {"plan_bytes", "var_file_bytes", "provider_lock_bytes", "state_bytes"}:
        key = {"plan_bytes": "plan", "var_file_bytes": "var_file",
               "provider_lock_bytes": "provider_lock", "state_bytes": "state"}[fault]
        inputs[key] += b" "
    elif fault.startswith("review_"):
        value = json.loads(inputs["review"])
        value["source_sha" if fault == "review_source" else "plan_sha256"] = "f" * (40 if fault == "review_source" else 64)
        replace_input(inputs, "review", value)
    elif fault.startswith("result_"):
        value = json.loads(inputs["apply_result"])
        value["state"]["post_serial" if fault == "result_serial" else "post_sha256"] = 3 if fault == "result_serial" else "f" * 64
        replace_input(inputs, "apply_result", value)
    elif fault.startswith("build_"):
        value = json.loads(inputs["build_evidence"])
        if fault == "build_source":
            value["source_sha"] = "f" * 40
        elif fault == "build_release":
            value["build_release_id"] = "another-release"
        else:
            value["images"]["api"]["digest"] = "sha256:" + "f" * 64
        replace_input(inputs, "build_evidence", value)
    else:
        plan = json.loads(inputs["plan_json"])
        app = next(item for item in plan["resource_changes"] if item["address"] == "azurerm_container_app.api[0]")["change"]["after"]
        env = app["template"][0]["container"][0]["env"]
        if fault == "duplicate_env":
            env.append(copy.deepcopy(env[0]))
        elif fault == "unknown_env":
            env.append({"name": "UNREVIEWED_FEATURE", "value": "true", "secret_name": ""})
        elif fault == "inline_secret":
            app["secret"][0]["value"] = "invented-inline-value"
        else:
            app["secret"][0]["identity"] += "-different"
        replace_input(inputs, "plan_json", plan)
    with pytest.raises(binding.BindingError):
        binding.derive_binding(inputs, source_sha=SOURCE, release_id=RELEASE)


@pytest.mark.parametrize("input_name", ["review", "apply_result", "build_evidence"])
@pytest.mark.parametrize("schema_version", [True, 1.0])
def test_generated_plan_chain_requires_integer_schema_versions(exported_plan, input_name, schema_version) -> None:
    inputs = companions(exported_plan)
    binding.derive_binding(inputs, source_sha=SOURCE, release_id=RELEASE)
    value = json.loads(inputs[input_name])
    value["schema_version"] = schema_version
    replace_input(inputs, input_name, value)
    with pytest.raises(binding.BindingError):
        binding.derive_binding(inputs, source_sha=SOURCE, release_id=RELEASE)
