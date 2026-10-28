"""Medication intent cannot borrow an allergy or another provider's authority."""

from typing import Any

import pytest
from pydantic import ValidationError

from cosmas_os.api.ehr_read_schemas import EHR_COMMAND, ReviewEhr
from cosmas_os.application.ehr_reads import _review_body, item_hash
from cosmas_os.config import Settings
from cosmas_os.domain.hashing import payload_hash

ID = "10000000-0000-4000-8000-000000000001"
DIGEST = "a" * 64
SCOPE = {"provider": "athena", "protocol": "core", "clinical_scope": "medications"}


def command(action: str) -> dict[str, Any]:
    result: dict[str, Any] = {**SCOPE, "action": action}
    if action in ("core_patients", "core_medications"):
        result.update(connection_id=ID, binding_sha256=DIGEST, workspace_id=ID, idempotency_key="medication-intent-1")
    if action == "core_medications":
        result.update(observation_id=ID, observation_sha256=DIGEST, item_handle=ID, item_sha256=DIGEST)
    if action == "inspect":
        result["observation_id"] = ID
    if action == "resolve":
        result["idempotency_key"] = "medication-intent-1"
    return result


@pytest.mark.parametrize("action", ["status", "core_patients", "core_medications", "inspect", "resolve"])
def test_explicit_medication_commands_round_trip_without_losing_scope(action):
    body = command(action)
    assert EHR_COMMAND.validate_python(body).model_dump(mode="json", exclude_unset=True) == body


@pytest.mark.parametrize("action", ["status", "core_patients", "core_medications", "inspect", "resolve"])
@pytest.mark.parametrize("field,value", [("clinical_scope", None), ("clinical_scope", "allergies"), ("provider", "elation"), ("protocol", "fhir")])
def test_unknown_or_cross_provider_scope_is_closed(action, field, value):
    with pytest.raises(ValidationError):
        EHR_COMMAND.validate_python({**command(action), field: value})


def test_medication_child_requires_scope_and_allergy_child_refuses_it():
    body = command("core_medications")
    del body["clinical_scope"]
    with pytest.raises(ValidationError):
        EHR_COMMAND.validate_python(body)
    with pytest.raises(ValidationError):
        EHR_COMMAND.validate_python({**command("core_medications"), "action": "core_allergies"})


@pytest.mark.parametrize("action", ["status", "core_patients", "inspect", "resolve"])
def test_legacy_allergy_omitted_scope_wire_remains_exact(action):
    body = command(action)
    del body["clinical_scope"]
    assert EHR_COMMAND.validate_python(body).model_dump(mode="json", exclude_unset=True) == body


def review_body():
    return {**SCOPE, "expected_revision": 1, "idempotency_key": "medication-review-1", "observation_id": ID,
        "observation_sha256": DIGEST, "item_handle": ID, "item_sha256": DIGEST,
        "reviewed_patient_identity": True, "reviewed_exact_snapshot": True, "reviewed_untrusted_source": True}


def test_medication_review_has_three_fresh_checks_and_no_fabricated_visit():
    body = review_body()
    assert ReviewEhr.model_validate(body).model_dump(mode="json", exclude_unset=True) == body
    with pytest.raises(ValidationError):
        ReviewEhr.model_validate({**body, "reviewed_visit": True})
    for key in ("reviewed_patient_identity", "reviewed_exact_snapshot", "reviewed_untrusted_source"):
        for invalid in (False, 1, None):
            with pytest.raises(ValidationError):
                ReviewEhr.model_validate({**body, key: invalid})


def test_medication_approval_and_item_hashes_cannot_reuse_allergy_hashes():
    args = (ID, 1, "medication-review-1", ID, DIGEST, ID, DIGEST, None, True, True, True, "athena", "core")
    old = _review_body(*args)
    medication = _review_body(*args, clinical_scope="medications")
    assert "clinical_scope" not in old
    assert medication == {**old, "clinical_scope": "medications"}
    assert payload_hash(old) != payload_hash(medication)
    item = {"handle": ID, "patient_identity_json": "{}", "department_label": "Invented clinic"}
    assert item_hash("core_patients", item) != item_hash("core_medication_patients", item)
    assert item_hash("core_allergies", item) != item_hash("core_medications", item)


def test_medication_host_flag_is_dark_independently_of_allergy_flag():
    arguments: dict[str, Any] = {"_env_file": None}
    assert Settings(**arguments).workspace_athena_medications_enabled is False
    assert Settings(**arguments, workspace_athena_allergies_enabled=True).workspace_athena_medications_enabled is False


def test_existing_allergy_snapshot_can_still_match_shared_public_union():
    from pydantic import TypeAdapter
    from tests.unit.test_athena_allergy_read import SECTION

    from cosmas_os.domain.hashing import canonical_json
    from cosmas_os.ports.athena_allergy_ehr import AthenaAllergiesObservation
    from cosmas_os.ports.ehr_reads import SnapshotPayload

    value: dict[str, Any] = dict(provider="athena", protocol="core", mode="synthetic", kind="core_allergies", workspace_id=ID,
        practice_label="Invented", observed_at="2026-10-26T12:00:00Z", parent=dict(observation_id=ID, source_sha256=DIGEST, item_sha256=DIGEST),
        item=dict(handle=ID, sha256=DIGEST, patient_identity_json=canonical_json({"firstname":"Alex","lastname":"Example"}),
            department_label="Invented", coverage="returned_section_only", includes_inactive=True, section_json=canonical_json(SECTION),
            source_content="Invented", content_sha256=DIGEST))
    adapter = TypeAdapter(SnapshotPayload.model_fields["public"].annotation)
    result = adapter.validate_python(value)
    assert type(result) is AthenaAllergiesObservation
    assert result.model_dump(mode="json")["item"]["section_json"] == value["item"]["section_json"]
    assert "clinical_scope" not in result.model_dump(mode="json")
