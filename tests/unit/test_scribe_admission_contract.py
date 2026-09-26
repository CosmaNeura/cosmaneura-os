from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from cosmas_os.adapters.scribe_admission import HttpScribeAdmission
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.scribe_capture import (
    ConsentAttestation,
    ScribeConsentReceipt,
    ScribeEncounterBinding,
    build_scribe_admission,
)


@pytest.fixture
def binding():
    return ScribeEncounterBinding(
        box_id=uuid4(),
        owner_id=uuid4(),
        workspace_id=uuid4(),
        tenant_id=uuid4(),
        appointment_id="encounter-synthetic-1",
        practitioner_id="provider-synthetic-1",
        patient_id="patient-synthetic-1",
    )


@pytest.fixture
def attestation():
    return ConsentAttestation(
        modality="in_person",
        participant_regions=("US-NY",),
        method="verbal_attestation",
        all_parties_consented=True,
        granted_at=datetime(2026, 9, 16, tzinfo=UTC),
    )


def receipt(binding, attestation, **changes):
    return {
        **attestation.model_dump(mode="json"),
        "appointment_id": binding.appointment_id,
        "practitioner_id": binding.practitioner_id,
        "patient_id": binding.patient_id,
        "id": str(uuid4()),
        "policy_version": "synthetic-policy-1",
        "evidence_object_id": None,
        "revoked_at": None,
        **changes,
    }


@pytest.mark.parametrize("regions", [("US-NY",), ()])
def test_existing_wire_contract_and_fixed_scope_are_preserved(binding, attestation, regions):
    attestation = ConsentAttestation.model_validate(
        {**attestation.model_dump(), "participant_regions": regions}
    )
    calls = []
    consent = receipt(binding, attestation)
    session_id = str(uuid4())

    def handler(request):
        import json

        calls.append(request)
        assert request.headers["authorization"] == "Bearer invented-token"
        assert request.headers["x-tenant-id"] == str(binding.tenant_id)
        assert request.headers["x-tenant-id"] != str(binding.box_id)
        body = json.loads(request.content)
        assert "box_id" not in body and "owner_id" not in body
        if request.url.path == "/v1/consents":
            assert body["all_parties_consented"] is True
            assert body["participant_regions"] == list(regions)
            assert body["patient_id"] == binding.patient_id
            return httpx.Response(201, json=consent)
        assert request.url.path == "/v1/sessions"
        assert body["consent_record_id"] == consent["id"]
        return httpx.Response(
            201,
            json={
                **body,
                "id": session_id,
                "ingest_mode": "chunk_upload",
                "status": "created",
                "created_at": "2026-09-16T00:00:01Z",
            },
        )

    client = HttpScribeAdmission(
        "https://scribe.example.invalid",
        lambda: "invented-token",
        transport=httpx.MockTransport(handler),
    )
    try:
        accepted = client.record_consent(binding, attestation, "consent-key-1")
        session = client.create_session(binding, accepted, "session-key-1")
        assert str(session.id) == session_id and session.status == "created"
        assert [r.headers["idempotency-key"] for r in calls] == ["consent-key-1", "session-key-1"]
    finally:
        client.close()


@pytest.mark.parametrize("field", ["appointment_id", "practitioner_id", "patient_id"])
def test_wrong_encounter_scope_is_rejected(binding, attestation, field):
    raw = receipt(binding, attestation, **{field: "foreign-synthetic-reference"})
    client = HttpScribeAdmission(
        "https://scribe.example.invalid",
        lambda: "invented-token",
        transport=httpx.MockTransport(lambda _: httpx.Response(201, json=raw)),
    )
    try:
        with pytest.raises(ConnectorUnavailable, match="scope_conflict"):
            client.record_consent(binding, attestation, "consent-key")
    finally:
        client.close()


@pytest.mark.parametrize(
    "changes",
    [
        {"revoked_at": "2026-09-16T00:00:01Z"},
        {"modality": "phone"},
        {"granted_at": "2026-09-15T00:00:00Z"},
        {"participant_regions": ["US-CA"]},
    ],
)
def test_changed_or_revoked_consent_receipt_is_rejected(binding, attestation, changes):
    client = HttpScribeAdmission(
        "https://scribe.example.invalid",
        lambda: "invented-token",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(201, json=receipt(binding, attestation, **changes))
        ),
    )
    try:
        with pytest.raises(ConnectorUnavailable, match="scope_conflict"):
            client.record_consent(binding, attestation, "consent-key")
    finally:
        client.close()


@pytest.mark.parametrize("value", [False, 1, "true", None])
@pytest.mark.parametrize("regions", [("US-NY",), ()])
def test_consent_must_be_explicit_true(attestation, value, regions):
    with pytest.raises(ValidationError):
        ConsentAttestation.model_validate(
            {**attestation.model_dump(), "participant_regions": regions, "all_parties_consented": value}
        )


def test_invalid_consent_cannot_start_a_session_or_call_network(binding, attestation):
    calls = []
    client = HttpScribeAdmission(
        "https://scribe.example.invalid",
        lambda: "invented-token",
        transport=httpx.MockTransport(lambda r: calls.append(r)),
    )
    try:
        invalid = ScribeConsentReceipt.model_validate(
            receipt(binding, attestation, patient_id="other-invented")
        )
        with pytest.raises(ConnectorUnavailable, match="consent_scope_conflict"):
            client.create_session(binding, invalid, "session-key")
        assert calls == []
    finally:
        client.close()


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(302, headers={"location": "https://outside.invalid/secret"}),
        httpx.Response(503, text="PRIVATE DETAILS"),
        httpx.Response(200, text="PRIVATE DETAILS", headers={"content-type": "text/html"}),
        httpx.Response(200, content=b"x" * 65537, headers={"content-type": "application/json"}),
        httpx.Response(200, json={"private_extra_field": "PRIVATE DETAILS"}),
    ],
)
def test_errors_are_bounded_no_redirect_or_retry_and_do_not_expose_content(
    binding, attestation, response
):
    calls = []

    def handler(request):
        calls.append(request)
        return response

    client = HttpScribeAdmission(
        "https://scribe.example.invalid",
        lambda: "invented-token",
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(ConnectorUnavailable) as caught:
            client.record_consent(binding, attestation, "consent-key")
        assert "PRIVATE" not in str(caught.value) and "secret" not in str(caught.value)
        assert len(calls) == 1
    finally:
        client.close()


def test_transport_timeout_does_not_retry_or_claim_failure_of_remote_write(binding, attestation):
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("PRIVATE token details", request=request)

    client = HttpScribeAdmission(
        "https://scribe.example.invalid",
        lambda: "invented-token",
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(ConnectorUnavailable, match="request_unconfirmed"):
            client.record_consent(binding, attestation, "same-retry-key")
        assert len(calls) == 1
    finally:
        client.close()


@pytest.mark.parametrize(
    "origin",
    [
        "http://scribe.invalid",
        "https://user:secret@scribe.invalid",
        "https://scribe.invalid/private",
        "https://scribe.invalid?target=other",
        "https://scribe.invalid#fragment",
    ],
)
def test_unsafe_origins_are_rejected(origin):
    with pytest.raises(ValueError, match="configured HTTPS origin"):
        HttpScribeAdmission(origin, lambda: "invented-token")


def test_runtime_is_disabled_and_protected_metadata_is_not_rendered(binding, attestation):
    port = build_scribe_admission()
    with pytest.raises(ConnectorUnavailable, match="connection_required"):
        port.record_consent(binding, attestation, "consent-key")
    assert "patient-synthetic" not in repr(binding)
    assert "US-NY" not in str(attestation)


@pytest.mark.parametrize(
    "changes",
    [
        {"patient_id": "foreign-synthetic"},
        {"consent_record_id": str(uuid4())},
        {"ingest_mode": "external_async_transcript"},
        {"status": "recording_started"},
    ],
)
def test_session_receipt_cannot_change_scope_or_claim_an_unrecognized_capture_state(
    binding, attestation, changes
):
    consent = ScribeConsentReceipt.model_validate(receipt(binding, attestation))
    body = {
        "id": str(uuid4()),
        "appointment_id": binding.appointment_id,
        "practitioner_id": binding.practitioner_id,
        "patient_id": binding.patient_id,
        "consent_record_id": str(consent.id),
        "modality": consent.modality,
        "ingest_mode": "chunk_upload",
        "status": "created",
        "created_at": "2026-09-16T00:00:01Z",
        **changes,
    }
    client = HttpScribeAdmission(
        "https://scribe.example.invalid",
        lambda: "invented-token",
        transport=httpx.MockTransport(lambda _: httpx.Response(201, json=body)),
    )
    try:
        with pytest.raises(ConnectorUnavailable):
            client.create_session(binding, consent, "session-key")
    finally:
        client.close()


def test_missing_identity_and_invalid_key_do_not_make_a_request(binding, attestation):
    calls = []
    client = HttpScribeAdmission(
        "https://scribe.example.invalid",
        lambda: "",
        transport=httpx.MockTransport(lambda r: calls.append(r)),
    )
    try:
        with pytest.raises(ConnectorUnavailable, match="identity_unavailable"):
            client.record_consent(binding, attestation, "consent-key")
        with pytest.raises(ConnectorUnavailable, match="invalid_idempotency_key"):
            client.record_consent(binding, attestation, "bad key")
        assert calls == []
    finally:
        client.close()
