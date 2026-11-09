"""C11/C20 Elation FHIR R4 sandbox adapter — mock transport only.

Synthetic patients and canary secrets exist only in-process. No network, no
real Key Vault, no live Elation sandbox calls. Appointments stay on REST.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from urllib.parse import parse_qs, urlencode

import httpx
import pytest

from cosmas_os.adapters.ehr_auth import (
    ELATION_FHIR_CLIENT_ID_REF,
    ELATION_FHIR_CLIENT_SECRET_REF,
    ClientCredentialsConfig,
    ClientCredentialsTokenClient,
    ManagedSecretEnvResolver,
)
from cosmas_os.adapters.elation_fhir_r4 import (
    ELATION_FHIR_EXTRA_SANDBOX_HOSTS,
    ELATION_FHIR_R4_BASE_URL,
    ELATION_FHIR_RESOURCES,
    ELATION_FHIR_SANDBOX_HOST,
    ELATION_FHIR_SYSTEM_READ_SCOPES,
    ELATION_FHIR_TOKEN_URL,
    ELATION_REST_APPOINTMENT_SURFACE,
    FORBIDDEN_FHIR_RESOURCES,
    ElationFhirR4Adapter,
    ElationFhirR4Error,
    elation_fhir_sandbox_client_credentials_config,
)
from cosmas_os.ehr_real_data_gate import (
    ELATION_FHIR_PRODUCTION_ORIGIN,
    ELATION_FHIR_SANDBOX_ORIGIN,
    EhrRealDataGateError,
    assert_ehr_request_allowed,
    classify_ehr_origin,
)
from cosmas_os.plugins.ehr_fhir import READABLE_RESOURCES, FhirR4ReadClient
from cosmas_os.ports import elation_fhir_ehr as port

FIXTURES = Path(__file__).parent / "fixtures" / "ehr_fhir"
BASE = ELATION_FHIR_R4_BASE_URL
FAKE_CLIENT_ID = "fake-elation-fhir-c20-client-id-PLACEHOLDER"
FAKE_CLIENT_SECRET = "fake-elation-fhir-c20-client-secret-PLACEHOLDER"
CANARY_TOKEN = "CANARY_ELATION_FHIR_C20_TOKEN_aa11bb22_NEVER_LOG"
CANARY_SECRET = "CANARY_ELATION_FHIR_C20_SECRET_cc33dd44_NEVER_LOG"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def bundle(resource_type: str, rows: list[dict], *, next_url: str | None = None) -> dict:
    links = [{"relation": "self", "url": f"{BASE}/{resource_type}"}]
    if next_url is not None:
        links.append({"relation": "next", "url": next_url})
    return {
        "resourceType": "Bundle",
        "id": f"SYNTHETIC-elation-{resource_type.lower()}-bundle",
        "type": "searchset",
        "total": len(rows),
        "link": links,
        "entry": [
            {
                "fullUrl": f"{BASE}/{resource_type}/{row['id']}",
                "resource": row,
                "search": {"mode": "match"},
            }
            for row in rows
        ],
    }


def fhir_response(payload: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status,
        headers={"Content-Type": "application/fhir+json"},
        content=json.dumps(payload).encode(),
    )


def query_map(request: httpx.Request) -> dict[str, list[str]]:
    raw = request.url.query
    if isinstance(raw, bytes):
        raw = raw.decode()
    return parse_qs(raw, keep_blank_values=True)


class CombinedMock:
    """Single MockTransport serving token mint + FHIR sandbox reads."""

    def __init__(self, fhir_handler) -> None:
        self.fhir_handler = fhir_handler
        self.token_calls = 0
        self.fhir_calls: list[httpx.Request] = []
        self.access_token = CANARY_TOKEN
        self.granted_scope = " ".join(sorted(ELATION_FHIR_SYSTEM_READ_SCOPES))
        self.transport = httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.method == "POST" and url.rstrip("/") == ELATION_FHIR_TOKEN_URL:
            self.token_calls += 1
            return httpx.Response(
                200,
                json={
                    "access_token": self.access_token,
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "scope": self.granted_scope,
                },
            )
        self.fhir_calls.append(request)
        return self.fhir_handler(request)


def _bind_secrets(monkeypatch: pytest.MonkeyPatch, *, secret: str = FAKE_CLIENT_SECRET) -> None:
    monkeypatch.setenv(ELATION_FHIR_CLIENT_ID_REF, FAKE_CLIENT_ID)
    monkeypatch.setenv(ELATION_FHIR_CLIENT_SECRET_REF, secret)


def _token_client(transport: httpx.MockTransport, *, scopes=None) -> ClientCredentialsTokenClient:
    config = ClientCredentialsConfig(
        client_id_ref=ELATION_FHIR_CLIENT_ID_REF,
        client_secret_ref=ELATION_FHIR_CLIENT_SECRET_REF,
        token_url=ELATION_FHIR_TOKEN_URL,
        scopes=scopes or ELATION_FHIR_SYSTEM_READ_SCOPES,
    )
    return ClientCredentialsTokenClient(
        config=config,
        secrets=ManagedSecretEnvResolver(),
        transport=transport,
    )


def _adapter(monkeypatch, fhir_handler, **kwargs) -> tuple[ElationFhirR4Adapter, CombinedMock]:
    _bind_secrets(monkeypatch)
    mock = CombinedMock(fhir_handler)
    adapter = ElationFhirR4Adapter(
        token_client=_token_client(mock.transport),
        transport=mock.transport,
        sandbox_enabled=True,
        **kwargs,
    )
    return adapter, mock


def test_sandbox_constants_and_port_surface():
    assert ELATION_FHIR_R4_BASE_URL == "https://sandbox.fhir.elationemr.com/fhir"
    assert ELATION_FHIR_TOKEN_URL.endswith("/smart/token")
    assert "Appointment" not in ELATION_FHIR_RESOURCES
    assert "system/Appointment.read" not in ELATION_FHIR_SYSTEM_READ_SCOPES
    assert FORBIDDEN_FHIR_RESOURCES == frozenset({"Appointment"})
    assert len(ELATION_FHIR_SYSTEM_READ_SCOPES) == 12
    assert all(s.endswith(".read") and s.startswith("system/") for s in ELATION_FHIR_SYSTEM_READ_SCOPES)
    assert "*" not in "".join(ELATION_FHIR_SYSTEM_READ_SCOPES)
    assert not any("write" in s.lower() for s in ELATION_FHIR_SYSTEM_READ_SCOPES)
    cfg = elation_fhir_sandbox_client_credentials_config()
    assert cfg.token_url == ELATION_FHIR_TOKEN_URL
    assert cfg.scopes == ELATION_FHIR_SYSTEM_READ_SCOPES
    assert cfg.client_id_ref.startswith("COSMAS_MANAGED_SECRET_")
    assert cfg.client_secret_ref.startswith("COSMAS_MANAGED_SECRET_")
    assert port.ELATION_FHIR_R4_BASE_URL == ELATION_FHIR_R4_BASE_URL
    assert port.ElationFhirR4Adapter is ElationFhirR4Adapter
    assert ELATION_REST_APPOINTMENT_SURFACE == "adapters.elation_read.ElationReadAdapter"


def test_shared_c4_defaults_not_widened_for_other_vendors():
    """Elation FHIR host / DiagnosticReport / Binary require explicit opt-in."""
    assert ELATION_FHIR_SANDBOX_HOST not in {
        "fhir.sandbox.example.com",
        "sandbox.fhir.example.org",
        "synthetic.invalid",
        "mock.example.com",
        "localhost",
        "127.0.0.1",
    }
    # Athena Preview host must also stay out of the shared default set.
    assert "api.preview.platform.athenahealth.com" not in {
        "fhir.sandbox.example.com",
        "sandbox.fhir.example.org",
        "synthetic.invalid",
        "mock.example.com",
        "localhost",
        "127.0.0.1",
    }
    assert ELATION_FHIR_EXTRA_SANDBOX_HOSTS == frozenset({ELATION_FHIR_SANDBOX_HOST})
    with pytest.raises(PermissionError, match="fhir_base_url_not_sandbox"):
        FhirR4ReadClient(ELATION_FHIR_R4_BASE_URL)
    assert "DiagnosticReport" not in READABLE_RESOURCES
    assert "Binary" not in READABLE_RESOURCES
    harness_refused = FhirR4ReadClient(
        "https://fhir.sandbox.example.com/r4",
        transport=httpx.MockTransport(lambda r: pytest.fail("no transport")),
    )
    assert harness_refused.search("DiagnosticReport").state == "malformed"
    assert harness_refused.read("Binary", "x").state == "malformed"


def test_c14_fhir_sandbox_and_production_origins():
    assert classify_ehr_origin("elation", ELATION_FHIR_SANDBOX_ORIGIN) == "sandbox"
    assert classify_ehr_origin("elation", ELATION_FHIR_PRODUCTION_ORIGIN) == "production"
    with pytest.raises(EhrRealDataGateError) as raised:
        assert_ehr_request_allowed(
            vendor="elation",
            origin=ELATION_FHIR_SANDBOX_ORIGIN,
            sandbox_enabled=False,
        )
    assert raised.value.code == "sandbox_flag_required"
    allowed = assert_ehr_request_allowed(
        vendor="elation",
        origin=ELATION_FHIR_SANDBOX_ORIGIN,
        sandbox_enabled=True,
    )
    assert allowed.allowed is True
    with pytest.raises(EhrRealDataGateError) as raised:
        assert_ehr_request_allowed(
            vendor="elation",
            origin=ELATION_FHIR_PRODUCTION_ORIGIN,
            sandbox_enabled=True,
            real_data_enabled=False,
            practice_baa_recorded=False,
            mock_transport_only=True,
        )
    assert raised.value.code == "real_data_required"


def test_real_data_flag_alone_does_not_open_sandbox_without_sandbox_flag(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("gate must refuse first")

    _bind_secrets(monkeypatch)
    mock = CombinedMock(handler)
    adapter = ElationFhirR4Adapter(
        token_client=_token_client(mock.transport),
        transport=mock.transport,
        sandbox_enabled=False,
        real_data_enabled=True,
        practice_baa_recorded=True,
    )
    with pytest.raises(ElationFhirR4Error) as raised:
        adapter.search("Patient")
    assert raised.value.code == "sandbox_flag_required"


def test_search_returns_synthetic_patient(monkeypatch):
    patient = load("patient.json")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.headers["Authorization"] == f"Bearer {CANARY_TOKEN}"
        assert request.url.path.endswith("/Patient")
        return fhir_response(bundle("Patient", [patient]))

    adapter, mock = _adapter(monkeypatch, handler)
    result = adapter.search("Patient", {"name": "Northwind"})
    assert result.ok
    assert result.resource_type == "Patient"
    assert len(result.resources) == 1
    assert result.resources[0]["id"] == "synth-patient-1001"
    assert mock.token_calls == 1
    assert len(mock.fhir_calls) == 1


def test_synthetic_named_elation_fixture(monkeypatch):
    fixture = load("SYNTHETIC_elation_patient_searchset.json")
    assert fixture["id"].startswith("SYNTHETIC-")
    assert fixture["entry"][0]["resource"]["id"].startswith("SYNTHETIC-")

    def handler(request: httpx.Request) -> httpx.Response:
        return fhir_response(fixture)

    adapter, _ = _adapter(monkeypatch, handler)
    result = adapter.search("Patient")
    assert result.ok
    assert result.resources[0]["id"] == "SYNTHETIC-elation-patient-1"


def test_bounded_paging(monkeypatch):
    page1 = load("patient.json")
    page2 = dict(page1)
    page2["id"] = "synth-patient-1002"
    page3 = dict(page1)
    page3["id"] = "synth-patient-1003"
    page4 = dict(page1)
    page4["id"] = "synth-patient-1004"

    pages = {
        "1": bundle("Patient", [page1], next_url=f"{BASE}/Patient?page=2"),
        "2": bundle("Patient", [page2], next_url=f"{BASE}/Patient?page=3"),
        "3": bundle("Patient", [page3], next_url=f"{BASE}/Patient?page=4"),
        "4": bundle("Patient", [page4]),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        page = query_map(request).get("page", ["1"])[0]
        return fhir_response(pages[page])

    adapter, mock = _adapter(monkeypatch, handler, max_pages=3)
    result = adapter.search("Patient")
    assert result.ok
    assert result.pages_read == 3
    assert result.more_available is True
    assert [row["id"] for row in result.resources] == [
        "synth-patient-1001",
        "synth-patient-1002",
        "synth-patient-1003",
    ]
    assert len(mock.fhir_calls) == 3


def test_appointment_refused_use_rest(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("forbidden resource must not hit transport")

    adapter, _ = _adapter(monkeypatch, handler)
    with pytest.raises(ElationFhirR4Error) as raised:
        adapter.search("Appointment")
    assert raised.value.code == "use_rest_appointments"
    assert adapter.rest_appointment_surface == ELATION_REST_APPOINTMENT_SURFACE
    with pytest.raises(ElationFhirR4Error) as raised:
        adapter.read("Coverage", "x")
    assert raised.value.code == "resource_unsupported"


def test_write_actions_refused(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("writes must not hit transport")

    adapter, _ = _adapter(monkeypatch, handler)
    for method in ("create", "update", "delete"):
        with pytest.raises(ElationFhirR4Error) as raised:
            getattr(adapter, method)({"resourceType": "Patient"})
        assert raised.value.code == "action_refused"
    with pytest.raises(ElationFhirR4Error) as raised:
        adapter.refuse_write("prescribe")
    assert raised.value.code == "action_refused"


def test_narrowed_grant_refuses_missing_resource_scope(monkeypatch):
    narrow = frozenset({"system/Patient.read", "system/Encounter.read"})

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("narrowed grant must refuse before FHIR call")

    _bind_secrets(monkeypatch)
    mock = CombinedMock(handler)
    mock.granted_scope = " ".join(sorted(narrow))
    adapter = ElationFhirR4Adapter(
        token_client=_token_client(mock.transport, scopes=narrow),
        transport=mock.transport,
        sandbox_enabled=True,
    )
    patient = load("patient.json")

    def patient_handler(request: httpx.Request) -> httpx.Response:
        return fhir_response(bundle("Patient", [patient]))

    mock.fhir_handler = patient_handler
    assert adapter.search("Patient").ok
    with pytest.raises(ElationFhirR4Error) as raised:
        adapter.search("Condition")
    assert raised.value.code == "unsupported_scope"


def test_sandbox_flag_required(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("gate must refuse first")

    _bind_secrets(monkeypatch)
    mock = CombinedMock(handler)
    adapter = ElationFhirR4Adapter(
        token_client=_token_client(mock.transport),
        transport=mock.transport,
        sandbox_enabled=False,
    )
    with pytest.raises(ElationFhirR4Error) as raised:
        adapter.search("Patient")
    assert raised.value.code == "sandbox_flag_required"


def test_flags_default_off_at_construction(monkeypatch):
    _bind_secrets(monkeypatch)
    mock = CombinedMock(lambda r: httpx.Response(500))
    adapter = ElationFhirR4Adapter(
        token_client=_token_client(mock.transport),
        transport=mock.transport,
    )
    assert adapter._sandbox_enabled is False
    assert adapter._real_data_enabled is False
    assert adapter._practice_baa_recorded is False


def test_live_transport_refused():
    class NotMock(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

    with pytest.raises(ElationFhirR4Error) as raised:
        ElationFhirR4Adapter(
            token_client=object(),  # type: ignore[arg-type]
            transport=NotMock(),  # type: ignore[arg-type]
            sandbox_enabled=True,
        )
    assert raised.value.code == "synthetic_transport_required"


def test_production_base_url_refused_at_construction(monkeypatch):
    _bind_secrets(monkeypatch)
    mock = CombinedMock(lambda r: httpx.Response(500))
    with pytest.raises(ElationFhirR4Error) as raised:
        ElationFhirR4Adapter(
            token_client=_token_client(mock.transport),
            transport=mock.transport,
            sandbox_enabled=True,
            base_url="https://fhir.elationemr.com/fhir",
        )
    assert raised.value.code == "off_origin_refused"


def test_canary_token_and_secret_absent_from_logs_and_errors(monkeypatch, caplog):
    _bind_secrets(monkeypatch, secret=CANARY_SECRET)

    def handler(request: httpx.Request) -> httpx.Response:
        return fhir_response(bundle("Patient", [load("patient.json")]))

    mock = CombinedMock(handler)
    mock.access_token = CANARY_TOKEN
    adapter = ElationFhirR4Adapter(
        token_client=_token_client(mock.transport),
        transport=mock.transport,
        sandbox_enabled=True,
    )
    with caplog.at_level(logging.DEBUG):
        result = adapter.search("Patient")
        assert result.ok
        with pytest.raises(ElationFhirR4Error) as raised:
            adapter.search("Appointment")
        assert raised.value.code == "use_rest_appointments"
        err_text = f"{raised.value!r} {raised.value} {raised.value.code}"
        assert CANARY_TOKEN not in err_text
        assert CANARY_SECRET not in err_text
        assert FAKE_CLIENT_SECRET not in err_text

    blob = "\n".join(r.getMessage() for r in caplog.records)
    blob += "\n" + "\n".join(str(getattr(r, "message", "")) for r in caplog.records)
    blob += repr(adapter)
    assert CANARY_TOKEN not in blob
    assert CANARY_SECRET not in blob
    assert "CANARY_ELATION_FHIR_C20" not in blob


def test_encounter_is_visit_source_on_fhir(monkeypatch):
    encounter = load("encounter.json")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/Encounter")
        return fhir_response(bundle("Encounter", [encounter]))

    adapter, _ = _adapter(monkeypatch, handler)
    result = adapter.search("Encounter")
    assert result.ok
    assert result.resource_type == "Encounter"


@pytest.mark.parametrize(
    "resource_type,fixture",
    [
        ("AllergyIntolerance", "allergy_intolerance.json"),
        ("MedicationRequest", "medication_request.json"),
        ("Condition", "condition.json"),
        ("Observation", "observation.json"),
        ("DiagnosticReport", "diagnostic_report.json"),
        ("DocumentReference", "document_reference.json"),
        ("Binary", "binary.json"),
        ("Practitioner", "practitioner.json"),
        ("Organization", "organization.json"),
        ("Medication", "medication.json"),
    ],
)
def test_approved_resource_instance_read(monkeypatch, resource_type, fixture):
    resource = load(fixture)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith(f"/{resource_type}/{resource['id']}")
        return fhir_response(resource)

    adapter, _ = _adapter(monkeypatch, handler)
    result = adapter.read(resource_type, resource["id"])
    assert result.ok
    assert result.resources[0]["id"] == resource["id"]


def test_off_origin_next_link_not_followed(monkeypatch):
    patient = load("patient.json")
    evil = "https://evil.example.com/fhir/Patient?" + urlencode({"page": "2"})

    def handler(request: httpx.Request) -> httpx.Response:
        return fhir_response(bundle("Patient", [patient], next_url=evil))

    adapter, mock = _adapter(monkeypatch, handler)
    result = adapter.search("Patient")
    assert result.state == "stale"
    assert len(mock.fhir_calls) == 1
