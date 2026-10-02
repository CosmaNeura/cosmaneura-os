"""Closed personal identity commands and exact immutable receipt commitments."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from tests.unit.test_scheduling_patient_setup import choice

from cosmas_os.api.scheduling_patient_schemas import PATIENT_SETUP_COMMAND, Confirm
from cosmas_os.application import scheduling_patient_setup as service
from cosmas_os.application.workspace import WorkspaceError
from cosmas_os.ports.scheduling import SchedulingSelection
from cosmas_os.ports.scheduling_patient_setup import PatientPreview, patient_digest


def command(**changes):
    return {"action": "preview", "expected_revision": 1, "idempotency_key": str(uuid4()),
        "search": {"kind": "search", "query": "Invented Jordan", "birth_date": None}, **changes}


def test_null_dob_explicit_human_search_closed_command():
    value = command()
    assert PATIENT_SETUP_COMMAND.validate_python(value).model_dump(mode="json") == value
    assert PATIENT_SETUP_COMMAND.validate_python({**value, "search": {**value["search"], "birth_date": "2000-02-29"}}).search.birth_date.isoformat() == "2000-02-29"


@pytest.mark.parametrize("change", [{"patient_id": str(uuid4())}, {"account_id": str(uuid4())},
    {"expected_revision": True}, {"search": {"kind": "appointment", "appointment_ref": str(uuid4())}},
    {"search": {"kind": "search", "query": " Invented Jordan", "birth_date": None}},
    {"search": {"kind": "search", "query": "Invented\nJordan", "birth_date": None}},
    {"search": {"kind": "search", "query": "Invented", "birth_date": "not-a-date"}}])
def test_unsafe_selector_is_not_a_grant(change):
    with pytest.raises(ValidationError):
        PATIENT_SETUP_COMMAND.validate_python(command(**change))


@pytest.mark.parametrize("field", ["reviewed_same_patient", "reviewed_exact_identity"])
@pytest.mark.parametrize("value", [False, 1, "true", None])
def test_confirm_requires_literal_human_acknowledgments(field, value):
    body = {"action": "confirm", "expected_revision": 1, "idempotency_key": str(uuid4()), "preview_id": str(uuid4()),
        "preview_sha256": "a" * 64, "choice_ref": str(uuid4()), "identity_sha256": "b" * 64,
        "reviewed_same_patient": True, "reviewed_exact_identity": True, field: value}
    with pytest.raises(ValidationError):
        Confirm.model_validate(body)


def test_command_hash_covers_workspace_exact_key_optional_dob_and_expected_revision():
    body, wid = command(), str(uuid4())
    hash_value = service.request_hash(wid, body)
    for changed_wid, changed_body in ((str(uuid4()), body), (wid, {**body, "expected_revision": 2}),
        (wid, {**body, "idempotency_key": str(uuid4())}), (wid, {**body, "search": {**body["search"], "birth_date": "2000-01-01"}})):
        assert service.request_hash(changed_wid, changed_body) != hash_value


def test_binding_is_frozen_and_hides_credentials():
    selection = SchedulingSelection(**{k: uuid4() for k in SchedulingSelection.model_fields})
    binding = service.PatientSetupBinding(account_id=str(uuid4()), selection=selection, binding_sha256="a" * 64,
        connected_at=datetime.now(UTC), grant_sha256="b" * 64)
    with pytest.raises(ValidationError):
        binding.grant_sha256 = "c" * 64
    with pytest.raises(ValidationError):
        service.PatientSetupBinding.model_validate({**binding.model_dump(), "token": "forbidden"})


def test_missing_disabled_or_nonboolean_configuration_is_closed():
    for configuration in (None, SimpleNamespace(), SimpleNamespace(workspace_scheduling_patient_setup_available=False),
                          SimpleNamespace(workspace_scheduling_patient_setup_available=1)):
        with pytest.raises(WorkspaceError, match="scheduling_patient_setup_unavailable"):
            service._gate(configuration)


def test_unsafe_public_subject_revision_refused_without_truncation():
    now = datetime.now(UTC)
    value = {"contract_version": "1", "request_nonce": str(uuid4()), "practice_id": str(uuid4()), "actor_id": str(uuid4()),
        "checked_at": now.isoformat().replace("+00:00", "Z"), "expires_at": (now + timedelta(minutes=3)).isoformat().replace("+00:00", "Z"), "lookup_ref": str(uuid4()),
        "choices": [choice(subject_revision=9007199254740992)], "more": False}
    value["preview_sha256"] = patient_digest("cosmas-scheduling-patient-preview.v1", value)
    parsed = PatientPreview.model_validate(value)
    with pytest.raises(WorkspaceError, match="scheduling_patient_receipt_invalid"):
        service._public_revision(parsed)


def test_source_commitment_changes_when_binding_or_context_changes():
    request = SimpleNamespace(id=str(uuid4()), request_sha256="a" * 64, account_id=str(uuid4()), binding_sha256="b" * 64,
        connected_at=datetime.now(UTC), grant_sha256="c" * 64, source_context_sha256="d" * 64)
    original = service._source_hash(request, "e" * 64)
    request.grant_sha256 = "f" * 64
    assert service._source_hash(request, "e" * 64) != original
