"""Invented receiver identities only; no account, lookup or patient mutation."""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from cosmas_os.adapters.scheduling_patient_setup import (
    PATH,
    VERSION_HEADER,
    HttpSchedulingPatientSetup,
)
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.scheduling import SchedulingSelection
from cosmas_os.ports.scheduling_patient_setup import (
    MAX_PREVIEW_BYTES,
    AppointmentPatientSelector,
    PatientPreview,
    PatientPreviewRequest,
    PatientVerification,
    PatientVerifyRequest,
    SearchPatientSelector,
    build_scheduling_patient_setup,
    patient_digest,
)

NOW = datetime(2026, 10, 2, 19, tzinfo=UTC)
HEADERS = {"Content-Type": "application/json", "Cache-Control": "private, no-store", VERSION_HEADER: "1"}


def choice(**changes):
    value = {"choice_ref": str(uuid4()), "display_name": "Invented Jordan", "birth_date": None,
             "subject_revision": 4, **changes}
    value["identity_sha256"] = patient_digest("cosmas-scheduling-patient-identity.v1", value)
    return value


def preview(lookup_request, scope, **changes):
    value = {"contract_version": "1", "request_nonce": str(lookup_request.request_nonce),
        "practice_id": str(scope.practice_id), "actor_id": str(scope.expected_actor_id),
        "checked_at": NOW.isoformat().replace("+00:00", "Z"), "lookup_ref": str(uuid4()),
        "expires_at": (NOW + timedelta(minutes=3)).isoformat().replace("+00:00", "Z"), "choices": [choice()], "more": False, **changes}
    value["preview_sha256"] = patient_digest("cosmas-scheduling-patient-preview.v1", value)
    return value


def verification(lookup_request, scope, observed, **changes):
    value = {"contract_version": "1", "request_nonce": str(lookup_request.request_nonce),
        "practice_id": str(scope.practice_id), "actor_id": str(scope.expected_actor_id),
        "lookup_ref": str(lookup_request.lookup_ref), "patient_id": str(uuid4()),
        "identity": observed.choices[0].model_dump(mode="json"), "verified_at": NOW.isoformat().replace("+00:00", "Z"),
        "expires_at": (NOW + timedelta(minutes=3)).isoformat().replace("+00:00", "Z"), **changes}
    value["verification_sha256"] = patient_digest("cosmas-scheduling-patient-verification.v1", value)
    return value


@pytest.fixture
def scope():
    return SchedulingSelection(**{key: uuid4() for key in SchedulingSelection.model_fields})


@pytest.fixture
def lookup_request(scope):
    return PatientPreviewRequest(request_nonce=uuid4(), expected_actor_id=scope.expected_actor_id,
        selector=SearchPatientSelector(kind="search", query="Invented Jordan", birth_date=None), limit=5)


def client(handler, **kwargs):
    return HttpSchedulingPatientSetup(kwargs.pop("origin", "https://scheduling.example.invalid"),
        kwargs.pop("staff_credential", lambda _: SecretStr("INVENTED_no_network")),
        enabled=kwargs.pop("enabled", lambda: True), transport=httpx.MockTransport(handler),
        now=kwargs.pop("now", lambda: NOW))


@pytest.mark.parametrize("base", ["", "/api"])
def test_dob_optional_exact_preview_verify_no_local_ids_or_cookie(scope, lookup_request, base):
    calls = []
    observed = PatientPreview.model_validate(preview(lookup_request, scope))
    verify = PatientVerifyRequest(request_nonce=uuid4(), expected_actor_id=scope.expected_actor_id,
        lookup_ref=observed.lookup_ref, choice_ref=observed.choices[0].choice_ref,
        identity_sha256=observed.choices[0].identity_sha256)

    def handler(wire):
        calls.append(wire)
        assert wire.method == "POST" and not wire.url.query
        assert wire.url.path == base + PATH + ("preview" if len(calls) == 1 else "verify")
        assert wire.headers["authorization"] == "Bearer INVENTED_no_network"
        assert wire.headers["x-practice-id"] == str(scope.practice_id)
        assert wire.headers[VERSION_HEADER] == "1" and "cookie" not in wire.headers
        assert "idempotency-key" not in wire.headers
        for identifier in (scope.box_id, scope.owner_id):
            assert str(identifier).encode() not in wire.content
        if len(calls) == 1:
            assert json.loads(wire.content)["selector"]["birth_date"] is None
            value = observed.model_dump(mode="json")
        else:
            assert "display_name" not in json.loads(wire.content)
            value = verification(verify, scope, observed)
        return httpx.Response(200, json=value, headers={**HEADERS, "Set-Cookie": "ambient=FORBIDDEN; Path=/"})

    port = client(handler, origin="https://scheduling.example.invalid" + base)
    try:
        assert port.preview(scope, lookup_request) == observed
        result = port.verify(scope, verify, observed)
        assert isinstance(result, PatientVerification) and result.identity.birth_date is None
        assert "Invented Jordan" not in repr(result) and len(calls) == 2
    finally:
        port.close()


@pytest.mark.parametrize("change", [
    {"actor_id": str(uuid4())}, {"practice_id": str(uuid4())}, {"request_nonce": str(uuid4())},
    {"checked_at": (NOW - timedelta(seconds=31)).isoformat().replace("+00:00", "Z")},
    {"checked_at": (NOW + timedelta(seconds=6)).isoformat().replace("+00:00", "Z")},
    {"expires_at": (NOW - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")},
    {"expires_at": (NOW + timedelta(minutes=6)).isoformat().replace("+00:00", "Z")},
    {"choices": [choice(birth_date="2030-01-01")]}, {"more": True},
])
def test_wrong_scope_nonce_freshness_or_future_dob_rejected(scope, lookup_request, change):
    port = client(lambda wire: httpx.Response(200, json=preview(lookup_request, scope, **change), headers=HEADERS))
    try:
        with pytest.raises(ConnectorUnavailable, match="scheduling_patient_setup_unavailable"):
            port.preview(scope, lookup_request)
    finally:
        port.close()


@pytest.mark.parametrize("fault", ["hash", "duplicate_choice", "extra", "bool_revision", "bool_limit", "control_name", "blank_query"])
def test_closed_contract_identity_and_preview_custody(scope, lookup_request, fault):
    if fault == "bool_limit":
        with pytest.raises(ValidationError):
            PatientPreviewRequest.model_validate({**lookup_request.model_dump(), "limit": True})
        return
    if fault == "blank_query":
        with pytest.raises(ValidationError):
            PatientPreviewRequest.model_validate({**lookup_request.model_dump(), "selector": {"kind": "search", "query": " ", "birth_date": None}})
        return
    value = preview(lookup_request, scope)
    if fault == "hash":
        value["choices"][0]["display_name"] = "Changed after hash"
    elif fault == "duplicate_choice":
        value["choices"] *= 2
    elif fault == "extra":
        value["patient_id"] = str(uuid4())
    elif fault == "bool_revision":
        value["choices"] = [choice(subject_revision=True)]
    else:
        value["choices"] = [choice(display_name="Invented\nJordan")]
    value["preview_sha256"] = patient_digest("cosmas-scheduling-patient-preview.v1",
        {key: item for key, item in value.items() if key != "preview_sha256"})
    with pytest.raises(ValidationError):
        PatientPreview.model_validate(value)


@pytest.mark.parametrize("fault", ["redirect", "cache", "version", "duplicate_json", "too_large", "encoding", "http_error"])
def test_bounded_transport_never_retries_or_follows(scope, lookup_request, fault):
    calls = []

    def handler(wire):
        calls.append(wire)
        if fault == "http_error":
            raise httpx.ReadError("PRIVATE_name_token_must_not_escape")
        value = preview(lookup_request, scope)
        if fault == "duplicate_json":
            return httpx.Response(200, content='{"contract_version":"1","contract_version":"1"}', headers=HEADERS)
        if fault == "too_large":
            return httpx.Response(200, content=b" " * (MAX_PREVIEW_BYTES + 1), headers=HEADERS)
        headers = dict(HEADERS)
        if fault == "cache":
            headers.pop("Cache-Control")
        elif fault == "version":
            headers[VERSION_HEADER] = "2"
        elif fault == "encoding":
            headers["Content-Encoding"] = "br"
        if fault == "redirect":
            return httpx.Response(307, headers={"Location": "https://other.example.invalid"})
        return httpx.Response(200, json=value, headers=headers)

    port = client(handler)
    try:
        with pytest.raises(ConnectorUnavailable) as error:
            port.preview(scope, lookup_request)
        assert str(error.value) == "scheduling_patient_setup_unavailable" and len(calls) == 1
    finally:
        port.close()


@pytest.mark.parametrize("fault", ["choice", "identity", "lookup", "expired_preview", "other_practice", "changed_revision", "wrong_nonce"])
def test_verification_binds_original_choice_revision_and_scope(scope, lookup_request, fault):
    observed = PatientPreview.model_validate(preview(lookup_request, scope))
    verify = PatientVerifyRequest(request_nonce=uuid4(), expected_actor_id=scope.expected_actor_id,
        lookup_ref=observed.lookup_ref, choice_ref=observed.choices[0].choice_ref,
        identity_sha256=observed.choices[0].identity_sha256)
    if fault == "choice":
        verify = verify.model_copy(update={"choice_ref": uuid4()})
    elif fault == "identity":
        verify = verify.model_copy(update={"identity_sha256": "f" * 64})
    elif fault == "lookup":
        verify = verify.model_copy(update={"lookup_ref": uuid4()})
    elif fault == "expired_preview":
        observed = PatientPreview.model_validate(preview(lookup_request, scope,
            checked_at=(NOW - timedelta(minutes=4)).isoformat().replace("+00:00", "Z"), expires_at=(NOW - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")))
    elif fault == "other_practice":
        observed = PatientPreview.model_validate(preview(lookup_request, scope, practice_id=str(uuid4())))
    calls = []

    def handler(wire):
        calls.append(wire)
        changed = {"identity": choice(choice_ref=str(observed.choices[0].choice_ref), subject_revision=5)} if fault == "changed_revision" else {"request_nonce": str(uuid4())}
        return httpx.Response(200, json=verification(verify, scope, observed, **changed), headers=HEADERS)

    port = client(handler)
    try:
        with pytest.raises(ConnectorUnavailable):
            port.verify(scope, verify, observed)
        assert len(calls) == (1 if fault in {"changed_revision", "wrong_nonce"} else 0)
    finally:
        port.close()


def test_default_gate_and_changed_gate_before_or_after_credentials_do_no_io(scope, lookup_request):
    calls = []
    default = HttpSchedulingPatientSetup("https://scheduling.example.invalid", lambda _: SecretStr("invented"),
        transport=httpx.MockTransport(lambda wire: (calls.append(wire), httpx.Response(500))[1]))
    with pytest.raises(ConnectorUnavailable):
        default.preview(scope, lookup_request)
    default.close()
    enabled = [True]

    def credential(_):
        enabled[0] = False
        return SecretStr("invented")

    port = client(lambda wire: calls.append(wire), staff_credential=credential, enabled=lambda: enabled[0])
    with pytest.raises(ConnectorUnavailable):
        port.preview(scope, lookup_request)
    port.close()
    with pytest.raises(ConnectorUnavailable):
        build_scheduling_patient_setup().preview(scope, lookup_request)
    assert not calls


def test_imported_appointment_selector_and_gate_revocation_after_io(scope):
    lookup_request = PatientPreviewRequest(request_nonce=uuid4(), expected_actor_id=scope.expected_actor_id,
        selector=AppointmentPatientSelector(kind="appointment", appointment_ref=uuid4()), limit=5)
    active = [True]
    calls = []

    def handler(wire):
        calls.append(wire)
        assert json.loads(wire.content)["selector"] == lookup_request.selector.model_dump(mode="json")
        active[0] = False
        return httpx.Response(200, json=preview(lookup_request, scope), headers=HEADERS)

    port = client(handler, enabled=lambda: active[0])
    try:
        with pytest.raises(ConnectorUnavailable):
            port.preview(scope, lookup_request)
        assert len(calls) == 1
    finally:
        port.close()


def test_receiver_identity_commitment_includes_optional_dob_and_monotonic_revision():
    first = choice()
    same = choice(choice_ref=first["choice_ref"])
    revised = choice(choice_ref=first["choice_ref"], subject_revision=5)
    dated = choice(choice_ref=first["choice_ref"], birth_date="1980-01-01")
    assert first["identity_sha256"] == same["identity_sha256"]
    assert len({first["identity_sha256"], revised["identity_sha256"], dated["identity_sha256"]}) == 3


@pytest.mark.parametrize("value", [True, 1, 0.0, "19800101", "1980-01-01T00:00:00Z"])
def test_dob_must_be_an_explicit_date_or_null(value):
    with pytest.raises(ValidationError):
        SearchPatientSelector(kind="search", query="Invented Jordan", birth_date=value)


@pytest.mark.parametrize("origin", ["http://scheduling.example.invalid", "https://user:secret@scheduling.example.invalid", "https://scheduling.example.invalid/path", "https://scheduling.example.invalid?token=secret", "https://scheduling.example.invalid:8443", "https://scheduling.example.invalid."])
def test_only_fixed_https_origin(origin):
    with pytest.raises(ValueError):
        HttpSchedulingPatientSetup(origin, lambda _: SecretStr("invented"))
