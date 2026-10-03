from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.unit import test_workload_verification as fixture

DIRECTORY = Path(__file__).resolve().parents[2] / "infra/beta"
SPEC = importlib.util.spec_from_file_location(
    "test_bound_workload_module", DIRECTORY / "workload_plan_binding.py"
)
assert SPEC is not None and SPEC.loader is not None
binding = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = binding
sys.path.insert(0, str(DIRECTORY))
try:
    SPEC.loader.exec_module(binding)
finally:
    sys.path.pop(0)
workload = binding.workload
validator = binding.attestation
NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


def bound_config():
    config = workload.Config.from_environment(fixture._environment())
    env = {name: list(value) for name, value in workload._expected_runtime_env(config).items()}
    secrets = {
        name: f"{config.key_vault_uri}secrets/{name}"
        for name in ("database-url", "redis-url", "human-deploy-evidence-reference")
    }
    contract = {
        "env": {"api": copy.deepcopy(env), "worker": copy.deepcopy(env), "web": {}},
        "secrets": {"api": secrets, "worker": secrets, "web": {}},
        "max_inactive_revisions": dict.fromkeys(("api", "worker", "web"), 3),
    }
    return replace(
        config,
        runtime_contract=contract,
        runtime_contract_sha256=workload.runtime_contract_sha256(contract),
        plan_sha256="1" * 64,
        review_sha256="2" * 64,
    )


def expected(config):
    return validator.ExpectedBinding(
        **{
            name: getattr(config, name)
            for name in (
                "source_sha",
                "release_id",
                "state_lineage",
                "state_serial",
                "state_sha256",
                "box_id",
                "api_digest",
                "web_digest",
                "location",
                "api_max_replicas",
                "plan_sha256",
                "review_sha256",
                "runtime_contract_sha256",
            )
        }
    )


def test_google_callback_projection_uses_connection_gate_without_whole_message_activation():
    config = bound_config()
    plan = {"variables": {
        "workspace_hosted_enabled": {"value": True},
        "workspace_features": {"value": {
            "WORKSPACE_GOOGLE_CONNECTION_ENABLED": True,
            "WORKSPACE_GOOGLE_CALENDAR_ENABLED": True,
            "WORKSPACE_GOOGLE_MESSAGE_ENABLED": False,
        }},
    }}
    projected, _ = binding._workspace_extension(plan, config)
    assert projected["GOOGLE_CONNECTION_CALLBACK_URI"] == [
        "value", config.api_ready_url.removesuffix("/ready") + "/connections/google/callback"]
    assert projected["GOOGLE_CONNECTION_RETURN_ORIGIN"] == ["value", config.web_origin]
    assert projected["WORKSPACE_GOOGLE_CALENDAR_ENABLED"] == ["value", "true"]
    assert projected["WORKSPACE_GOOGLE_MESSAGE_ENABLED"] == ["value", "false"]
    plan["variables"]["workspace_features"]["value"]["WORKSPACE_GOOGLE_CONNECTION_ENABLED"] = False
    projected, _ = binding._workspace_extension(plan, config)
    assert "GOOGLE_CONNECTION_CALLBACK_URI" not in projected
    assert "GOOGLE_CONNECTION_RETURN_ORIGIN" not in projected


def test_bound_producer_and_consumer_roundtrip() -> None:
    config = bound_config()
    evidence = workload.verify_workload(config, fixture.FakeRunner(), now=NOW)
    assert evidence["schema_version"] == 2
    assert evidence["contract"] == "cosmas-os-d3-workload-verification-v2"
    assert evidence["runtime_contract_sha256"] == config.runtime_contract_sha256
    assert "runtime_contract" not in evidence
    validator.validate_attestation(evidence, expected(config), observed_at=NOW)


@pytest.mark.parametrize("field", ["plan_sha256", "review_sha256", "runtime_contract_sha256"])
def test_rehashed_wrong_binding_is_rejected(field: str) -> None:
    config = bound_config()
    evidence = workload.verify_workload(config, fixture.FakeRunner(), now=NOW)
    evidence[field] = "3" * 64
    payload = {k: v for k, v in evidence.items() if k != "evidence_payload_sha256"}
    evidence["evidence_payload_sha256"] = workload._sha256_json(payload)
    with pytest.raises(validator.WorkloadAttestationError, match="plan binding"):
        validator.validate_attestation(evidence, expected(config), observed_at=NOW)


def test_legacy_evidence_cannot_satisfy_bound_expectation() -> None:
    legacy = workload.Config.from_environment(fixture._environment())
    evidence = workload.verify_workload(legacy, fixture.FakeRunner(), now=NOW)
    with pytest.raises(validator.WorkloadAttestationError, match="shape"):
        validator.validate_attestation(evidence, expected(bound_config()), observed_at=NOW)


@pytest.mark.parametrize(
    "field", ["plan_sha256", "review_sha256", "runtime_contract_sha256", "runtime_contract"]
)
def test_partial_binding_fails_before_arm(field: str) -> None:
    runner = fixture.FakeRunner()
    config = replace(bound_config(), **{field: None})
    with pytest.raises(workload.WorkloadVerificationError):
        workload.verify_workload(config, runner, now=NOW)
    assert not runner.arm_calls


@pytest.mark.parametrize("separator", [None, "\n", "\r\n"])
def test_unicode_and_multiline_contract_roundtrip_and_mutation(separator: str | None) -> None:
    config = bound_config()
    contract = copy.deepcopy(config.runtime_contract)
    value = json.dumps({"label": "Café — 心"}, ensure_ascii=False)
    if separator is not None:
        value = json.dumps({"label": "Café — 心"}, ensure_ascii=False, indent=2)
        value = value.replace("\n", separator)
    plan = {
        "variables": {
            "workspace_hosted_enabled": {"value": True},
            "workspace_public_configuration": {"value": {"RESEARCH_DATASET_MAPPINGS": value}},
        }
    }
    projected, _ = binding._workspace_extension(plan, config)
    assert projected["RESEARCH_DATASET_MAPPINGS"] == ["value", value]
    assert binding._project_env([{"name": "RESEARCH_DATASET_MAPPINGS", "value": value}]) == {
        "RESEARCH_DATASET_MAPPINGS": ["value", value]
    }
    for kind in ("api", "worker"):
        contract["env"][kind]["RESEARCH_DATASET_MAPPINGS"] = ["value", value]
    digest = workload.runtime_contract_sha256(contract)
    assert digest == hashlib.sha256(binding.canonical(contract)).hexdigest()
    config = replace(config, runtime_contract=contract, runtime_contract_sha256=digest)
    runner = fixture.FakeRunner()
    for kind in ("api", "worker"):
        for properties in (
            runner.apps[kind]["properties"],
            runner.revisions[kind][0]["properties"],
        ):
            properties["template"]["containers"][0]["env"].append(
                {"name": "RESEARCH_DATASET_MAPPINGS", "value": value}
            )
    evidence = workload.verify_workload(config, runner, now=NOW)
    validator.validate_attestation(evidence, expected(config), observed_at=NOW)
    assert "Café" not in json.dumps(evidence, ensure_ascii=False)
    contract["env"]["api"]["RESEARCH_DATASET_MAPPINGS"][1] = "changed"
    with pytest.raises(workload.WorkloadVerificationError, match="runtime contract"):
        workload.verify_workload(config, runner, now=NOW)


@pytest.mark.parametrize("surface", ["app", "revision"])
def test_runtime_observations_cannot_coerce_numeric_public_values(surface: str) -> None:
    config = bound_config()
    contract = copy.deepcopy(config.runtime_contract)
    for kind in ("api", "worker"):
        contract["env"][kind]["RESEARCH_SOURCES"] = ["value", "3"]
    config = replace(
        config,
        runtime_contract=contract,
        runtime_contract_sha256=workload.runtime_contract_sha256(contract),
    )
    runner = fixture.FakeRunner()
    for kind in ("api", "worker"):
        for properties in (
            runner.apps[kind]["properties"],
            runner.revisions[kind][0]["properties"],
        ):
            properties["template"]["containers"][0]["env"].append(
                {"name": "RESEARCH_SOURCES", "value": "3"}
            )
    workload.verify_workload(config, runner, now=NOW)
    target = runner.apps["api"] if surface == "app" else runner.revisions["api"][0]
    env = target["properties"]["template"]["containers"][0]["env"]
    next(item for item in env if item["name"] == "RESEARCH_SOURCES")["value"] = 3
    with pytest.raises(workload.WorkloadVerificationError, match="runtime environment"):
        workload.verify_workload(config, runner, now=NOW)


@pytest.mark.parametrize(
    "name,value",
    [
        ("AUTH_MODE", "disabled"),
        ("DATA_MODE", "live"),
        ("BETA_BOX_ID", "different"),
        ("SYNC_WORKER", "true"),
        ("CORS_ALLOWED_ORIGINS", "*"),
    ],
)
def test_rehashed_contract_cannot_weaken_baseline(name: str, value: str) -> None:
    config = bound_config()
    contract = copy.deepcopy(config.runtime_contract)
    for kind in ("api", "worker"):
        contract["env"][kind][name] = ["value", value]
    config = replace(
        config,
        runtime_contract=contract,
        runtime_contract_sha256=workload.runtime_contract_sha256(contract),
    )
    runner = fixture.FakeRunner()
    with pytest.raises(workload.WorkloadVerificationError, match="baseline"):
        workload.verify_workload(config, runner, now=NOW)
    assert not runner.arm_calls


@pytest.mark.parametrize(
    "value",
    [
        [],
        [{"name": "A", "value": "one", "secret_name": "two"}],
        [{"name": "A", "value": None, "secret_name": ""}],
        [{"name": "A", "value": "one"}, {"name": "A", "value": "one"}],
        [{"name": "A", "value": 3}],
        [{"name": "A", "value": "hidden\x00value"}],
        [{"name": "A", "secret_name": "invalid\nreference"}],
        [{"name": "A", "value": "one", "extra": "two"}],
    ],
)
def test_runtime_env_normalization_refuses_ambiguity(value) -> None:
    if not value:
        assert binding._project_env(value) == {}
    else:
        with pytest.raises(binding.BindingError):
            binding._project_env(value)


def test_unused_terraform_env_fields_are_normalized_exactly() -> None:
    assert binding._project_env(
        [
            {"name": "PUBLIC", "value": "yes", "secret_name": ""},
            {"name": "SECRET", "value": None, "secret_name": "ref"},
        ]
    ) == {"PUBLIC": ["value", "yes"], "SECRET": ["secretRef", "ref"]}


@pytest.mark.parametrize(
    "variable,value",
    [
        ("workspace_features", {"UNKNOWN_ENABLED": True}),
        ("workspace_features", {"WORKSPACE_TEAM_SETUP_ENABLED": "true"}),
        ("workspace_public_configuration", {"WORKSPACE_LLM_API_KEY": "inline-secret"}),
        (
            "workspace_secret_references",
            {"UNKNOWN_SECRET": {"secret_name": "name", "version": "a" * 32}},
        ),
        (
            "workspace_secret_references",
            {"WORKSPACE_LLM_API_KEY": {"secret_name": "name", "version": "latest"}},
        ),
    ],
)
def test_workspace_projection_refuses_unknown_or_inline_secret_expansion(variable, value) -> None:
    plan = {"variables": {"workspace_hosted_enabled": {"value": True}, variable: {"value": value}}}
    with pytest.raises(binding.BindingError):
        binding._workspace_extension(plan, bound_config())


def test_duplicate_json_keys_fail_closed() -> None:
    with pytest.raises(binding.BindingError, match="duplicate-json"):
        binding.load(b'{"a":1,"a":2}')


def test_secure_reader_rejects_symlink_without_reading_target(tmp_path: Path) -> None:
    target = tmp_path / "private.json"
    target.write_text("private sentinel")
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(OSError):
        binding._read(link)


PATIENT_SETUP_FEATURE = "WORKSPACE_SCHEDULING_PATIENT_SETUP_ENABLED"


def patient_setup_plan(enabled=True):
    return {"variables": {
        "workspace_hosted_enabled": {"value": True},
        "workspace_features": {"value": {
            "WORKSPACE_SCHEDULING_ENABLED": True,
            "WORKSPACE_SCHEDULING_LOGIN_ENABLED": True,
            "WORKSPACE_APPOINTMENTS_ENABLED": True,
            PATIENT_SETUP_FEATURE: enabled,
        }},
        "workspace_public_configuration": {"value": {
            "SCHEDULING_ORIGIN": "https://synthetic-scheduling.example",
            "SCHEDULING_GOOGLE_CLIENT_ID": "invented-client",
        }},
        "workspace_secret_references": {"value": {
            "SCHEDULING_GOOGLE_CLIENT_SECRET": {
                "secret_name": "invented-scheduling-client", "version": "1" * 32},
            "SCHEDULING_LOGIN_ENCRYPTION_KEY": {
                "secret_name": "invented-scheduling-custody", "version": "2" * 32},
        }},
    }}


def test_patient_setup_activation_preserves_reviewed_public_and_secret_projection():
    projected, secrets = binding._workspace_extension(patient_setup_plan(), bound_config())
    assert projected[PATIENT_SETUP_FEATURE] == ["value", "true"]
    assert projected["WORKSPACE_APPOINTMENTS_ENABLED"] == ["value", "true"]
    assert projected["WORKSPACE_SCHEDULING_LOGIN_ENABLED"] == ["value", "true"]
    assert projected["SCHEDULING_GOOGLE_CALLBACK_URI"][1].endswith(
        "/connections/scheduling/google/callback")
    assert set(secrets) == {
        "ws-" + hashlib.sha256(name.encode()).hexdigest()[:32]
        for name in ("SCHEDULING_GOOGLE_CLIENT_SECRET", "SCHEDULING_LOGIN_ENCRYPTION_KEY")
    }


def test_patient_setup_disabled_remains_explicit_in_runtime_projection():
    projected, _ = binding._workspace_extension(patient_setup_plan(False), bound_config())
    assert projected[PATIENT_SETUP_FEATURE] == ["value", "false"]


def test_patient_setup_activation_still_refuses_unknown_and_nonboolean_features():
    for name, value in (("WORKSPACE_UNREVIEWED_ENABLED", True),
                        (PATIENT_SETUP_FEATURE, "true"), (PATIENT_SETUP_FEATURE, 1)):
        plan = patient_setup_plan()
        plan["variables"]["workspace_features"]["value"][name] = value
        with pytest.raises(binding.BindingError, match="unknown-workspace-feature"):
            binding._workspace_extension(plan, bound_config())


def test_protected_feature_allowlist_matches_actual_terraform_module_inputs():
    import re

    text = (DIRECTORY / "environment/modules/workspace-runtime/main.tf").read_text()
    declaration = text.split("alltrue([for name in keys(var.features) : contains([", 1)[1]
    declaration = declaration.split("], name)", 1)[0]
    assert set(re.findall(r'"([A-Z][A-Z0-9_]+)"', declaration)) == binding.FEATURE_NAMES
