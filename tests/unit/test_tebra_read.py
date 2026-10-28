"""Synthetic wire/security regressions. No vendor account or network access."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

import httpx
import pytest
from pydantic import SecretStr

from cosmas_os.adapters.tebra_read import (
    ENDPOINT,
    MAX_RESPONSE_BYTES,
    MAX_ROWS,
    Operation,
    TebraAppointment,
    TebraCredentials,
    TebraPatient,
    TebraPractice,
    TebraReadAdapter,
    TebraReadError,
    TebraReadResult,
    TebraReadScope,
)

NS = "http://www.kareo.com/api/schemas/"
SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
PRACTICE = "Invented & Independent Clinic"
SCOPE = TebraReadScope(
    UUID(int=1), UUID(int=2), UUID(int=3), UUID(int=4), 900, 901, PRACTICE,
)
CREDENTIALS = TebraCredentials(
    SecretStr("synthetic-user"), SecretStr('synthetic-<&"password'), SecretStr("synthetic-key"),
)
START = datetime(2026, 10, 25, 12, tzinfo=UTC)
END = START + timedelta(days=1)

# Shape follows the public SOAP 2.1 WSDL, including the misspelled
# PracticiesAuthorized type's PracticeID/Arrays:int wrapper.
SECURITY = """
<SecurityResponse>
 <Authenticated>true</Authenticated><Authorized>true</Authorized>
 <CustomerId>900</CustomerId><CustomerKeyValid>true</CustomerKeyValid>
 <PermissionsMissing><Permission /></PermissionsMissing>
 <PracticesAuthorized><PracticeID><a:int>901</a:int></PracticeID></PracticesAuthorized>
 <SecurityResult>Success</SecurityResult><SecurityResultSuccess>true</SecurityResultSuccess>
</SecurityResponse>"""
PATIENT = """<PatientData><DOB>1980-01-02</DOB><ID>910</ID><LastName>Example</LastName>
<PatientFullName>Alex Example</PatientFullName>
<PracticeName>Invented &amp; Independent Clinic</PracticeName></PatientData>"""
APPOINTMENT = """<AppointmentData><ConfirmationStatus>Scheduled</ConfirmationStatus>
<EndDate>2026-10-25T13:30:00Z</EndDate><ID>920</ID><PatientID>910</PatientID>
<PracticeID>901</PracticeID><PracticeName>Invented &amp; Independent Clinic</PracticeName>
<StartDate>2026-10-25T13:00:00Z</StartDate></AppointmentData>"""
PRACTICE_ROW = """<PracticeData><ID>901</ID>
<PracticeName>Invented &amp; Independent Clinic</PracticeName></PracticeData>"""


def envelope(operation="GetPatients", rows=PATIENT, *, security=SECURITY, error="false"):
    collection = {"GetPatients": "Patients", "GetAppointments": "Appointments",
                  "GetPractices": "Practices"}[operation]
    return f"""<s:Envelope xmlns:s="{SOAP_NS}" xmlns="{NS}"
      xmlns:a="http://schemas.microsoft.com/2003/10/Serialization/Arrays">
    <s:Body><{operation}Response><{operation}Result>
    <ErrorResponse><ErrorMessage /><IsError>{error}</IsError><StackTrace /></ErrorResponse>
    {security}<{collection}>{rows}</{collection}>
    </{operation}Result></{operation}Response></s:Body></s:Envelope>""".encode()


def adapter(payload=None, *, status=200, handler=None, authorize=None, headers=None):
    calls = []

    def handle(request):
        calls.append(request)
        if handler:
            return handler(request)
        return httpx.Response(status, stream=httpx.ByteStream(payload or envelope()), headers={
            "Content-Type": "text/xml; charset=utf-8", **(headers or {}),
        })

    result = TebraReadAdapter(enabled=True, transport=httpx.MockTransport(handle),
                              authorize_read=authorize or (lambda scope: scope == SCOPE))
    return result, calls


def patients(port: TebraReadAdapter, scope: TebraReadScope = SCOPE) -> TebraReadResult:
    return port.find_patients(scope, CREDENTIALS, last_name="Example", birth_date=date(1980, 1, 2))


def test_default_inactive_and_live_transport_remains_unavailable():
    calls = []

    def unexpected_request(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise AssertionError("The disabled adapter must not call its transport")

    port = TebraReadAdapter(authorize_read=lambda _: True,
                            transport=httpx.MockTransport(unexpected_request))
    with pytest.raises(TebraReadError, match="^connector_disabled$"):
        patients(port)
    assert not calls
    # Enabling a feature cannot silently create a live client before qualification.
    port = TebraReadAdapter(enabled=True, authorize_read=lambda _: True)
    with pytest.raises(TebraReadError, match="^provider_qualification_required$"):
        patients(port)


def test_patient_request_uses_exact_practice_and_bounded_demographics_not_a_fake_rest_api():
    port, calls = adapter()
    result = patients(port)
    request = calls[0]
    assert str(request.url) == ENDPOINT and request.method == "POST"
    assert request.headers["soapaction"] == '"http://www.kareo.com/api/schemas/KareoServices/GetPatients"'
    assert "authorization" not in request.headers and "cookie" not in request.headers
    xml = ET.fromstring(request.content)
    def q(name):
        return "{" + NS + "}" + name
    body = xml.find("{" + SOAP_NS + "}Body")
    assert body is not None and len(body) == 1
    incoming = body[0].find(q("request"))
    assert incoming is not None
    assert [n.tag for n in incoming] == [q("RequestHeader"), q("Fields"), q("Filter")]
    header = incoming[0]
    assert [n.tag for n in header] == [q("CustomerKey"), q("Password"), q("User")]
    assert header[1].text == CREDENTIALS.password.get_secret_value()
    assert {n.tag.removeprefix("{" + NS + "}"): n.text for n in incoming[2]} == {
        "FromDateOfBirth": "1980-01-02", "LastName": "Example", "PracticeID": "901",
        "PracticeName": PRACTICE, "ToDateOfBirth": "1980-01-02",
    }
    assert all(n.text == "true" for n in incoming[1])
    assert len(result.rows) == 1
    patient = result.rows[0]
    assert isinstance(patient, TebraPatient)
    assert patient.patient_id == 910
    assert patient.full_name == "Alex Example"
    assert result.scope == SCOPE and result.coverage == "returned_rows_only"
    assert result.observed_at.utcoffset() == timedelta(0)
    assert "Alex" not in repr(result.rows[0]) and "synthetic" not in repr(CREDENTIALS)
    assert not any(isinstance(v, TebraCredentials) for v in vars(port).values())


def test_practice_check_requires_exact_one_practice():
    port, _ = adapter(envelope("GetPractices", PRACTICE_ROW))
    practice = port.read_practice(SCOPE, CREDENTIALS).rows[0]
    assert isinstance(practice, TebraPractice)
    assert practice.practice_id == 901
    for rows in ("", PRACTICE_ROW * 2, PRACTICE_ROW.replace("901", "902")):
        port, _ = adapter(envelope("GetPractices", rows))
        with pytest.raises(TebraReadError, match="^scope_changed$"):
            port.read_practice(SCOPE, CREDENTIALS)


def test_schedule_preserves_instants_and_source_status_with_explicit_date_bounds():
    port, calls = adapter(envelope("GetAppointments", APPOINTMENT))
    result = port.read_appointments(SCOPE, CREDENTIALS, starts_at=START, ends_at=END)
    appointment = result.rows[0]
    assert isinstance(appointment, TebraAppointment)
    assert appointment.starts_at == datetime(2026, 10, 25, 13, tzinfo=UTC)
    assert appointment.source_status == "Scheduled"
    xml = ET.fromstring(calls[0].content)
    offset = xml.find(".//{" + NS + "}TimeZoneOffsetFromGMT")
    assert offset is not None and offset.text == "0"
    filtering = xml.find(".//{" + NS + "}Filter")
    assert filtering is not None
    start = filtering.find("{" + NS + "}StartDate")
    end = filtering.find("{" + NS + "}EndDate")
    assert start is not None and start.text == START.isoformat()
    assert end is not None and end.text == END.isoformat()
    port, _ = adapter(envelope("GetAppointments", ""))
    empty = port.read_appointments(SCOPE, CREDENTIALS, starts_at=START, ends_at=END)
    assert not empty.rows and empty.coverage == "returned_rows_only"
    assert not hasattr(empty, "available_slots")


@pytest.mark.parametrize("field,value,code", [
    ("Authenticated", "false", "access_denied"),
    ("Authorized", "false", "access_denied"),
    ("CustomerKeyValid", "false", "access_denied"),
    ("SecurityResultSuccess", "false", "response_invalid"),
    ("SecurityResultSuccess", "yes", "response_invalid"),
    ("CustomerId", "902", "scope_changed"),
])
def test_http_success_is_not_auth_success(field, value, code):
    security = SECURITY.replace(f"<{field}>true</{field}>", f"<{field}>{value}</{field}>")
    if field == "CustomerId":
        security = SECURITY.replace("<CustomerId>900", "<CustomerId>" + value)
    port, calls = adapter(envelope(security=security))
    with pytest.raises(TebraReadError, match="^" + code + "$"):
        patients(port)
    assert len(calls) == 1


@pytest.mark.parametrize("security", [
    SECURITY.replace("<Authenticated>true</Authenticated>", ""),
    SECURITY.replace("<Authenticated>true</Authenticated>", "<Authenticated>true</Authenticated>" * 2),
    SECURITY.replace("<a:int>901</a:int>", "<a:int>902</a:int>"),
    SECURITY.replace("<a:int>901</a:int>", "<a:int>901</a:int>" * 2),
    SECURITY.replace("<Permission />", "<Permission><a:string>GetPatients</a:string></Permission>"),
    SECURITY.replace("<PermissionsMissing><Permission /></PermissionsMissing>", ""),
    SECURITY.replace("<SecurityResult>Success", "<SecurityResult>Failure"),
])
def test_missing_conflicting_or_wrong_practice_security_cannot_expose_rows(security):
    port, _ = adapter(envelope(security=security))
    with pytest.raises(TebraReadError):
        patients(port)


def test_application_box_authority_is_required_even_when_vendor_authenticates():
    port, calls = adapter(authorize=lambda _: False)
    with pytest.raises(TebraReadError, match="^access_denied$"):
        patients(port)
    assert not calls
    port, calls = adapter()
    with pytest.raises(TebraReadError, match="^access_denied$"):
        patients(port, replace(SCOPE, box_id=uuid4()))
    assert not calls


def test_scope_change_during_read_discards_late_rows():
    current = [SCOPE]

    def handle(_request):
        current[0] = replace(SCOPE, credential_generation=uuid4())
        return httpx.Response(200, stream=httpx.ByteStream(envelope()),
                              headers={"Content-Type": "text/xml"})

    port, _ = adapter(handler=handle, authorize=lambda scope: scope == current[0])
    with pytest.raises(TebraReadError, match="^access_denied$"):
        patients(port)


@pytest.mark.parametrize("rows", [
    PATIENT.replace("Independent Clinic", "Other Clinic"),
    PATIENT.replace("1980-01-02", "1981-01-02"),
    PATIENT.replace("<LastName>Example", "<LastName>Elsewhere"),
    PATIENT.replace("<ID>910</ID>", "<ID>910</ID>" * 2),
    PATIENT * 2,
])
def test_patient_scope_and_ambiguity_cannot_be_silently_normalized(rows):
    port, _ = adapter(envelope(rows=rows))
    with pytest.raises(TebraReadError):
        patients(port)


@pytest.mark.parametrize("rows", [
    APPOINTMENT.replace("<PracticeID>901", "<PracticeID>902"),
    APPOINTMENT.replace("2026-10-25T13:00:00Z", "2026-10-26T13:00:00Z"),
    APPOINTMENT.replace("2026-10-25T13:00:00Z", "2026-10-25T13:00:00"),
    APPOINTMENT.replace("2026-10-25T13:30:00Z", "2026-10-25T12:30:00Z"),
    APPOINTMENT.replace("Scheduled", "Unrecognized status"),
    APPOINTMENT * 2,
])
def test_schedule_rejects_cross_practice_naive_time_bad_interval_unknown_status_and_duplicates(rows):
    port, _ = adapter(envelope("GetAppointments", rows))
    with pytest.raises(TebraReadError):
        port.read_appointments(SCOPE, CREDENTIALS, starts_at=START, ends_at=END)


@pytest.mark.parametrize("status,code", [
    (302, "provider_rejected"), (401, "access_denied"), (403, "access_denied"),
    (429, "provider_throttled"), (500, "provider_rejected"),
])
def test_http_errors_do_not_redirect_retry_or_reveal_vendor_body(status, code):
    port, calls = adapter(b"synthetic-sensitive-error", status=status,
                          headers={"Location": "https://untrusted.invalid"})
    with pytest.raises(TebraReadError, match="^" + code + "$"):
        patients(port)
    assert len(calls) == 1


def test_faults_and_interruption_are_closed_and_never_automatically_retried():
    port, _ = adapter(envelope(error="true"))
    with pytest.raises(TebraReadError, match="^provider_rejected$"):
        patients(port)

    def timeout(request):
        raise httpx.ReadTimeout("synthetic-sensitive-error", request=request)

    port, calls = adapter(handler=timeout)
    with pytest.raises(TebraReadError, match="^transport_unconfirmed$") as error:
        patients(port)
    assert error.value.__suppress_context__ and len(calls) == 1
    contradictory = envelope().replace(b"<ErrorMessage />", b"<ErrorMessage>failure</ErrorMessage>")
    port, _ = adapter(contradictory)
    with pytest.raises(TebraReadError, match="^response_invalid$"):
        patients(port)


@pytest.mark.parametrize("data", [
    b'<!DOCTYPE x [<!ENTITY sample "expanded">]>' + envelope(),
    b'<!DOCTYPE x SYSTEM "file:///unread-secret">' + envelope(),
    ('<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE x [<!ENTITY a "text">]>'
     + envelope().decode()).encode("utf-16"),
    envelope().replace(b"<s:Body>", b"<s:Body><s:Fault>synthetic-sensitive-error</s:Fault>"),
    envelope().replace(b"<Patients>", b'<Patients xmlns="https://untrusted.invalid">'),
    b"<unclosed",
])
def test_xml_dtd_entities_wrong_namespaces_faults_and_malformed_xml_are_rejected(data):
    port, _ = adapter(data)
    with pytest.raises(TebraReadError, match="^response_invalid$"):
        patients(port)


def test_row_byte_and_depth_budgets_reject_instead_of_returning_incomplete_success():
    port, _ = adapter(envelope(rows=PATIENT * (MAX_ROWS + 1)))
    with pytest.raises(TebraReadError, match="^too_many_results$"):
        patients(port)
    port, _ = adapter(b"<root>" + b"<child>" * 17 + b"</child>" * 17 + b"</root>")
    with pytest.raises(TebraReadError, match="^response_too_large$"):
        patients(port)

    class Oversize(httpx.SyncByteStream):
        closed = False
        chunks = 0

        def __iter__(self):
            for chunk in [b" " * MAX_RESPONSE_BYTES, b"over-budget", b"must-not-read"]:
                self.chunks += 1
                yield chunk

        def close(self):
            self.closed = True

    stream = Oversize()
    port, _ = adapter(handler=lambda _: httpx.Response(
        200, stream=stream, headers={"Content-Type": "text/xml"},
    ))
    with pytest.raises(TebraReadError, match="^response_too_large$"):
        patients(port)
    assert stream.closed and stream.chunks == 2


def test_compressed_body_and_invalid_inputs_never_pass_through():
    port, _ = adapter(headers={"Content-Encoding": "gzip"})
    with pytest.raises(TebraReadError, match="^response_invalid$"):
        patients(port)
    port, calls = adapter()
    for start, end in ((START.replace(tzinfo=None), END), (END, START),
                       (START, END + timedelta(days=7))):
        with pytest.raises(TebraReadError, match="^request_invalid$"):
            port.read_appointments(SCOPE, CREDENTIALS, starts_at=start, ends_at=end)
    with pytest.raises(TebraReadError, match="^request_invalid$"):
        port.find_patients(SCOPE, CREDENTIALS, last_name="", birth_date=date(1980, 1, 2))
    assert not calls


def test_window_budget_counts_elapsed_time_across_daylight_saving_transition():
    eastern = ZoneInfo("America/New_York")
    port, calls = adapter()
    with pytest.raises(TebraReadError, match="^request_invalid$"):
        port.read_appointments(SCOPE, CREDENTIALS,
                               starts_at=datetime(2026, 10, 31, 12, tzinfo=eastern),
                               ends_at=datetime(2026, 11, 7, 12, tzinfo=eastern))
    assert not calls


def test_write_names_are_unreachable_and_authorization_failures_stay_closed():
    port, calls = adapter()
    with pytest.raises(TebraReadError, match="^request_invalid$"):
        # Deliberately cross the static boundary to exercise the runtime allowlist.
        port._read(cast(Operation, "CreatePatient"), SCOPE, CREDENTIALS,
                   (), {}, "Patients", "PatientData")
    assert not calls

    def rejected(_scope):
        raise ValueError("synthetic-sensitive-error")

    port, calls = adapter(authorize=rejected)
    with pytest.raises(TebraReadError, match="^access_denied$") as error:
        patients(port)
    assert error.value.__suppress_context__ and not calls
