"""Optional chart scope and legacy-compatible command/source boundaries."""

from dataclasses import replace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from tests.unit.test_elation_sandbox_configuration import document
from tests.unit.test_managed_service_configuration import install, no_session
from tests.unit.test_scheduling_runtime import configuration as configuration

from cosmas_os.adapters.managed_service_configuration import load_managed_profile
from cosmas_os.adapters.managed_services import ManagedServices
from cosmas_os.api.ehr_read_schemas import EHR_COMMAND
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.ports.ehr_reads import PrivateSnapshot, ProblemDisplay, ProblemList


def test_managed_problem_capability_requires_both_installation_and_host_opt_in(tmp_path, configuration, monkeypatch):
    doc = document(configuration)
    install(tmp_path, configuration, doc)
    legacy = load_managed_profile(configuration).elation_sandbox[0]
    # Adding the capability changes the reviewed installation, not the old scope body.
    opted = replace(legacy, problems_enabled=True)
    assert legacy.scope.commitment() == opted.scope.commitment()
    assert legacy.commitment() != opted.commitment()
    legacy_body = dict(contract="elation-sandbox-installation.v1", id=str(legacy.id), account_id=str(legacy.account_id),
        scope_sha256=legacy.scope.commitment(), timezone=legacy.timezone,
        client_id_sha256=legacy.client_id_sha256, client_secret_sha256=legacy.client_secret_sha256,
        data_classification=legacy.data_classification)
    assert legacy.commitment() == payload_hash(legacy_body)
    configuration.workspace_ehr_read_enabled = configuration.workspace_elation_sandbox_enabled = True
    monkeypatch.setenv("COSMAS_MANAGED_SECRET_ELATION_ID", "invented-client")
    monkeypatch.setenv("COSMAS_MANAGED_SECRET_ELATION_SECRET", "invented-secret")
    for installation_opt in (False, True):
        doc["elation_sandbox"][0]["problems_enabled"] = installation_opt
        install(tmp_path, configuration, doc)
        runtime = ManagedServices(configuration, load_managed_profile(configuration), no_session)
        assert runtime.ehr_reads is not None
        for host_opt in (False, True):
            configuration.workspace_elation_problems_enabled = host_opt
            assert runtime.ehr_reads.problems_available(legacy.scope) is (installation_opt and host_opt)
        runtime.close()


def test_status_capability_is_opt_in_without_changing_legacy_request():
    assert EHR_COMMAND.validate_python({"action": "status"}).model_dump(exclude_unset=True) == {"action": "status"}
    assert EHR_COMMAND.validate_python({"action": "status", "include_problems": True}).include_problems is True
    for invalid in (False, 1, "true", None):
        with pytest.raises(ValidationError):
            EHR_COMMAND.validate_python({"action": "status", "include_problems": invalid})


@pytest.mark.parametrize("change", [dict(patient_id="930"), dict(practice_id="910"), dict(offset=25),
    dict(cursor="next"), dict(provider="tebra"), dict(last_name="Example"), dict(include_problems=True)])
def test_problems_command_never_accepts_provider_ids_or_pages(change):
    body = dict(action="problems", connection_id=str(uuid4()), binding_sha256="a"*64,
        observation_id=str(uuid4()), observation_sha256="b"*64, item_handle=str(uuid4()), item_sha256="c"*64,
        idempotency_key="problem-command-1")
    assert EHR_COMMAND.validate_python(body).action == "problems"
    with pytest.raises(ValidationError):
        EHR_COMMAND.validate_python(body | change)


def test_problem_semantics_reject_unknown_or_inconsistent_values():
    body = dict(description="Invented concern", status="Active", start_date="2025-01-02", resolved_date=None,
        verification_status="unconfirmed")
    value = ProblemDisplay.model_validate(body)
    assert value.verification_status == "unconfirmed"
    for changed in (dict(status="Diagnosed"), dict(verification_status="verified"), dict(description="  "),
                    dict(resolved_date="2025-02-03"), dict(start_date="2025-02-30")):
        with pytest.raises(ValidationError):
            ProblemDisplay.model_validate(body | changed)
    with pytest.raises(ValidationError):
        ProblemList.model_validate(dict(coverage="end_of_results", total_count=2, items=[body]))
    with pytest.raises(ValidationError):
        ProblemList.model_validate(dict(coverage="more_rows_available", total_count=0, items=[]))


def test_legacy_private_snapshot_does_not_accept_three_provider_sources():
    with pytest.raises(ValidationError):
        PrivateSnapshot.model_validate(dict(binding_sha256="a"*64, request_sha256="b"*64,
            items=[], provider_sources=["c"*64]*3))
