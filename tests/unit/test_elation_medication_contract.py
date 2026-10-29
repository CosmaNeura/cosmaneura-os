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
from cosmas_os.ports.ehr_reads import MedicationDisplay, MedicationList, PrivateSnapshot


def test_managed_medication_capability_requires_both_installation_and_host_opt_in(tmp_path, configuration, monkeypatch):
    doc = document(configuration)
    install(tmp_path, configuration, doc)
    legacy = load_managed_profile(configuration).elation_sandbox[0]
    # Adding the capability changes the reviewed installation, not the old scope body.
    opted = replace(legacy, medications_enabled=True)
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
        doc["elation_sandbox"][0]["medications_enabled"] = installation_opt
        install(tmp_path, configuration, doc)
        runtime = ManagedServices(configuration, load_managed_profile(configuration), no_session)
        assert runtime.ehr_reads is not None
        for host_opt in (False, True):
            configuration.workspace_elation_medications_enabled = host_opt
            assert runtime.ehr_reads.medications_available(legacy.scope) is (installation_opt and host_opt)
        runtime.close()


def test_status_capability_is_opt_in_without_changing_legacy_request():
    assert EHR_COMMAND.validate_python({"action": "status"}).model_dump(exclude_unset=True) == {"action": "status"}
    assert EHR_COMMAND.validate_python({"action": "status", "include_medications": True}).include_medications is True
    for invalid in (False, 1, "true", None):
        with pytest.raises(ValidationError):
            EHR_COMMAND.validate_python({"action": "status", "include_medications": invalid})


@pytest.mark.parametrize("change", [dict(patient_id="930"), dict(practice_id="910"), dict(offset=25),
    dict(cursor="next"), dict(provider="tebra"), dict(last_name="Example"), dict(include_medications=True)])
def test_medications_command_never_accepts_provider_ids_or_pages(change):
    body = dict(action="medications", connection_id=str(uuid4()), binding_sha256="a"*64,
        observation_id=str(uuid4()), observation_sha256="b"*64, item_handle=str(uuid4()), item_sha256="c"*64,
        idempotency_key="medication-command-1")
    assert EHR_COMMAND.validate_python(body).action == "medications"
    with pytest.raises(ValidationError):
        EHR_COMMAND.validate_python(body | change)


def display_row(**changes):
    return dict(medication_name="Invented medication", strength=None, route=None, form=None, directions=None,
        medication_type=None, order_type=None, is_doc_med=None, is_permanent=None, start_date=None,
        document_date=None, signed_date=None, deleted_date=None, discontinue_date=None,
        signature_state="unknown", discontinuation_state="unknown", deletion_state="unknown") | changes


@pytest.mark.parametrize("change", [dict(medication_name="\u2003"), dict(medication_name="x\n"),
    dict(strength="a"*256), dict(route="a"*101), dict(directions="x"*1001), dict(directions="x\x1f"),
    dict(is_doc_med=1), dict(is_permanent="false"), dict(start_date="2025-02-30"),
    dict(document_date="2025-01-01"), dict(document_date="2025-01-01 12:00:00"),
    dict(document_date="2025-01-01T24:00:00"), dict(document_date="2025-01-01T12:00:00.1234567"),
    dict(discontinue_date="2025-02-30"), dict(signed_date="2025-01-01T12:00:00"),
    dict(signature_state="date_recorded"), dict(active=True)])
def test_medication_projection_rejects_forged_or_inconsistent_values(change):
    with pytest.raises(ValidationError):
        MedicationDisplay.model_validate(display_row(**change))


def test_medication_projection_preserves_blanks_multiline_dates_and_uncertainty():
    body = display_row(strength="", directions="First line\n\tSecond\rline", medication_type="discontinued",
        is_doc_med=False, is_permanent=True, document_date="2024-02-29T23:59:59.123456-23:59",
        signed_date="2025-01-01T01:00:00", signature_state="date_recorded", discontinue_date="2025-01-02",
        discontinuation_state="date_recorded", deletion_state="no_date_recorded")
    assert MedicationDisplay.model_validate(body).model_dump() == body
    for changed in (dict(coverage="end_of_results", total_count=2, items=[body]),
                    dict(coverage="more_rows_available", total_count=0, items=[]),
                    dict(coverage="unknown", total_count=True, items=[])):
        with pytest.raises(ValidationError):
            MedicationList.model_validate(changed)


def test_legacy_private_snapshot_does_not_accept_three_provider_sources():
    with pytest.raises(ValidationError):
        PrivateSnapshot.model_validate(dict(binding_sha256="a"*64, request_sha256="b"*64,
            items=[], provider_sources=["c"*64]*3))
