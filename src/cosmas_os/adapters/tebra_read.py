"""Bounded Tebra SOAP reads, currently restricted to synthetic transports.

No runtime registration, credential store, write operation, or readiness claim.
See docs/tebra-read.md for the vendor qualifications required before live use.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from uuid import UUID
from xml.etree import ElementTree as ET
from xml.parsers import expat

import httpx
from pydantic import SecretStr

ENDPOINT = "https://webservice.kareo.com/services/soap/2.1/KareoServices.svc"
SCHEMA = "http://www.kareo.com/api/schemas/"
SOAP = "http://schemas.xmlsoap.org/soap/envelope/"
ARRAYS = "http://schemas.microsoft.com/2003/10/Serialization/Arrays"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
MAX_RESPONSE_BYTES = 262_144
MAX_ROWS = 100
MAX_NODES = 4096
MAX_DEPTH = 16
Operation = Literal["GetPractices", "GetPatients", "GetAppointments"]
ErrorCode = Literal[
    "connector_disabled", "provider_qualification_required", "access_denied",
    "scope_changed", "request_invalid", "response_invalid", "response_too_large",
    "too_many_results", "provider_throttled", "provider_rejected", "transport_unconfirmed",
]


class TebraReadError(Exception):
    """Only fixed local codes; never vendor XML, faults, headers, or credentials."""

    def __init__(self, code: ErrorCode):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, repr=False)
class TebraReadScope:
    box_id: UUID
    owner_id: UUID
    connection_id: UUID
    credential_generation: UUID
    customer_id: int
    practice_id: int
    practice_name: str

    def validate(self) -> None:
        if any(type(value) is not UUID for value in (
            self.box_id, self.owner_id, self.connection_id, self.credential_generation,
        )) or any(type(value) is not int or not 1 <= value <= 2_147_483_647
                  for value in (self.customer_id, self.practice_id)):
            raise TebraReadError("request_invalid")
        _label(self.practice_name)


@dataclass(frozen=True, repr=False)
class TebraCredentials:
    """Supplied by the server for this call, never retained on the adapter."""

    user: SecretStr
    password: SecretStr
    customer_key: SecretStr


@dataclass(frozen=True, repr=False)
class TebraPractice:
    practice_id: int
    practice_name: str


@dataclass(frozen=True, repr=False)
class TebraPatient:
    patient_id: int
    full_name: str
    birth_date: date


@dataclass(frozen=True, repr=False)
class TebraAppointment:
    appointment_id: int
    patient_id: int
    starts_at: datetime
    ends_at: datetime
    source_status: str


@dataclass(frozen=True, repr=False)
class TebraReadResult:
    scope: TebraReadScope
    operation: Operation
    observed_at: datetime
    rows: tuple[TebraPractice | TebraPatient | TebraAppointment, ...]
    # No total/cursor is supplied. Empty rows do not prove that no appointments exist.
    coverage: Literal["returned_rows_only"] = "returned_rows_only"


def _label(value: str) -> str:
    if (type(value) is not str or not 1 <= len(value) <= 255 or value != value.strip()
            or any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in value)):
        raise TebraReadError("request_invalid")
    return value


def _tag(name: str, namespace: str = SCHEMA) -> str:
    return "{" + namespace + "}" + name


def _one(parent: ET.Element, name: str, namespace: str = SCHEMA) -> ET.Element:
    matches = parent.findall(_tag(name, namespace))
    if len(matches) != 1 or matches[0].get(_tag("nil", XSI)) in {"true", "1"}:
        raise TebraReadError("response_invalid")
    return matches[0]


def _text(parent: ET.Element, name: str) -> str:
    node = _one(parent, name)
    value = node.text or ""
    if (len(node) or len(value) > 255 or not value or value != value.strip()
            or any(ord(c) < 32 for c in value)):
        raise TebraReadError("response_invalid")
    return value


def _id(value: str) -> int:
    if re.fullmatch(r"[1-9][0-9]{0,17}", value) is None:
        raise TebraReadError("response_invalid")
    return int(value)


def _bool(parent: ET.Element, name: str) -> bool:
    value = _text(parent, name)
    if value not in {"true", "false", "1", "0"}:
        raise TebraReadError("response_invalid")
    return value in {"true", "1"}


def _xml(data: bytes) -> ET.Element:
    """Expat rejects DTD/entity declarations before expansion, including UTF-16."""

    builder = ET.TreeBuilder()
    parser = expat.ParserCreate(namespace_separator="}")
    count = depth = 0

    def qualify(name):
        return "{" + name if "}" in name else name

    def start(name, attrs):
        nonlocal count, depth
        count += 1
        depth += 1
        if count > MAX_NODES or depth > MAX_DEPTH or len(attrs) > 8:
            raise TebraReadError("response_too_large")
        builder.start(qualify(name), {qualify(k): v for k, v in attrs.items()})

    def end(name):
        nonlocal depth
        builder.end(qualify(name))
        depth -= 1

    def forbidden(*_args):
        raise TebraReadError("response_invalid")

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = builder.data
    parser.StartDoctypeDeclHandler = forbidden
    parser.EntityDeclHandler = forbidden
    parser.ExternalEntityRefHandler = forbidden
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    try:
        parser.Parse(data, True)
        return builder.close()
    except (expat.ExpatError, ValueError):
        raise TebraReadError("response_invalid") from None


def _envelope(operation: Operation, credentials: TebraCredentials,
              fields: tuple[str, ...], filters: dict[str, str]) -> bytes:
    root = ET.Element(_tag("Envelope", SOAP))
    body = ET.SubElement(root, _tag("Body", SOAP))
    request = ET.SubElement(ET.SubElement(body, _tag(operation)), _tag("request"))
    # WSDL RequestBase precedes Fields/Filter. RequestHeader is in the body.
    header = ET.SubElement(request, _tag("RequestHeader"))
    for name, secret in (("CustomerKey", credentials.customer_key),
                         ("Password", credentials.password), ("User", credentials.user)):
        if not isinstance(secret, SecretStr):
            raise TebraReadError("request_invalid")
        value = secret.get_secret_value()
        if not 1 <= len(value) <= 4096 or any(
            ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in value
        ):
            raise TebraReadError("request_invalid")
        ET.SubElement(header, _tag(name)).text = value
    selection = ET.SubElement(request, _tag("Fields"))
    for name in sorted(fields):
        ET.SubElement(selection, _tag(name)).text = "true"
    filtering = ET.SubElement(request, _tag("Filter"))
    for name, value in sorted(filters.items()):
        ET.SubElement(filtering, _tag(name)).text = value
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _rows(data: bytes, operation: Operation, scope: TebraReadScope,
          collection: str, row_name: str) -> list[ET.Element]:
    root = _xml(data)
    if root.tag != _tag("Envelope", SOAP) or [e.tag for e in root] != [_tag("Body", SOAP)]:
        raise TebraReadError("response_invalid")
    body = root[0]
    if len(body) != 1 or body[0].tag != _tag(operation + "Response"):
        raise TebraReadError("response_invalid")
    result = _one(body[0], operation + "Result")
    if len(body[0]) != 1 or {e.tag for e in result} != {
        _tag("ErrorResponse"), _tag("SecurityResponse"), _tag(collection),
    } or len(result) != 3:
        raise TebraReadError("response_invalid")
    error = _one(result, "ErrorResponse")
    if _bool(error, "IsError"):
        raise TebraReadError("provider_rejected")
    for name in ("ErrorMessage", "StackTrace"):
        nodes = error.findall(_tag(name))
        if len(nodes) > 1 or any(len(n) or (n.text or "").strip() for n in nodes):
            raise TebraReadError("response_invalid")
    security = _one(result, "SecurityResponse")
    if not all(_bool(security, name) for name in (
        "Authenticated", "Authorized", "CustomerKeyValid",
    )):
        raise TebraReadError("access_denied")
    # Fixed synthetic fixture assumption, not configurable production polarity.
    # Live transport remains prohibited until the conflicting guide is resolved.
    if not _bool(security, "SecurityResultSuccess") or _text(security, "SecurityResult") != "Success":
        raise TebraReadError("response_invalid")
    if _id(_text(security, "CustomerId")) != scope.customer_id:
        raise TebraReadError("scope_changed")
    missing = _one(security, "PermissionsMissing")
    if any((e.text or "").strip() for e in missing.iter()) or any(
        e.tag not in {_tag("Permission"), _tag("string", ARRAYS)} for e in missing.iter()
        if e is not missing
    ):
        raise TebraReadError("access_denied")
    authorized = _one(_one(security, "PracticesAuthorized"), "PracticeID")
    ids = []
    for child in authorized:
        if child.tag != _tag("int", ARRAYS) or len(child):
            raise TebraReadError("response_invalid")
        ids.append(_id(child.text or ""))
    if scope.practice_id not in ids or len(ids) != len(set(ids)):
        raise TebraReadError("scope_changed")
    rows = _one(result, collection)
    if len(rows) > MAX_ROWS:
        raise TebraReadError("too_many_results")
    if any(row.tag != _tag(row_name) for row in rows):
        raise TebraReadError("response_invalid")
    return list(rows)


class TebraReadAdapter:
    def __init__(self, *, authorize_read: Callable[[TebraReadScope], bool],
                 enabled: bool = False, transport: httpx.MockTransport | None = None):
        """authorize_read verifies current CosmaBot caller/Box and scope generation.

        Vendor Authenticated/Authorized flags never replace that application check.
        No default HTTP transport can be created while qualification is pending.
        """
        self._authorize_read = authorize_read
        self._enabled = enabled is True
        self._transport = transport

    def _guard(self, scope: TebraReadScope) -> None:
        if not self._enabled:
            raise TebraReadError("connector_disabled")
        if not isinstance(self._transport, httpx.MockTransport):
            raise TebraReadError("provider_qualification_required")
        if not isinstance(scope, TebraReadScope):
            raise TebraReadError("request_invalid")
        scope.validate()
        try:
            authorized = self._authorize_read(scope)
        except Exception:
            raise TebraReadError("access_denied") from None
        if authorized is not True:
            raise TebraReadError("access_denied")

    def _read(self, operation: Operation, scope: TebraReadScope,
              credentials: TebraCredentials, fields: tuple[str, ...],
              filters: dict[str, str], collection: str, row_name: str) -> list[ET.Element]:
        self._guard(scope)
        if operation not in {"GetPractices", "GetPatients", "GetAppointments"}:
            raise TebraReadError("request_invalid")
        if not isinstance(credentials, TebraCredentials):
            raise TebraReadError("request_invalid")
        payload = _envelope(operation, credentials, fields, filters)
        try:
            # A fresh client prevents cookies or credentials surviving into another read.
            with httpx.Client(transport=self._transport, trust_env=False, follow_redirects=False,
                              timeout=httpx.Timeout(10, connect=5)) as client:
                with client.stream("POST", ENDPOINT, content=payload, headers={
                    "Content-Type": "text/xml; charset=utf-8", "Accept": "text/xml",
                    "Accept-Encoding": "identity",
                    "SOAPAction": '"' + SCHEMA + "KareoServices/" + operation + '"',
                }) as response:
                    if response.status_code in {401, 403}:
                        raise TebraReadError("access_denied")
                    if response.status_code == 429:
                        raise TebraReadError("provider_throttled")
                    if response.status_code != 200:
                        raise TebraReadError("provider_rejected")
                    if (str(response.url) != ENDPOINT
                            or response.headers.get("content-type", "").split(";", 1)[0].lower()
                            not in {"text/xml", "application/xml"}
                            or response.headers.get("content-encoding", "identity") != "identity"):
                        raise TebraReadError("response_invalid")
                    data = bytearray()
                    for chunk in response.iter_raw():
                        if len(data) + len(chunk) > MAX_RESPONSE_BYTES:
                            raise TebraReadError("response_too_large")
                        data.extend(chunk)
                    result = _rows(bytes(data), operation, scope, collection, row_name)
                    self._guard(scope)
                    return result
        except httpx.HTTPError:
            raise TebraReadError("transport_unconfirmed") from None

    def read_practice(self, scope: TebraReadScope, credentials: TebraCredentials) -> TebraReadResult:
        rows = self._read("GetPractices", scope, credentials, ("ID", "PracticeName"),
                          {"ID": str(scope.practice_id), "PracticeName": scope.practice_name},
                          "Practices", "PracticeData")
        if len(rows) != 1 or _id(_text(rows[0], "ID")) != scope.practice_id:
            raise TebraReadError("scope_changed")
        self._practice_label(rows[0], scope)
        return TebraReadResult(scope, "GetPractices", datetime.now(UTC),
                               (TebraPractice(scope.practice_id, scope.practice_name),))

    def find_patients(self, scope: TebraReadScope, credentials: TebraCredentials, *,
                      last_name: str, birth_date: date) -> TebraReadResult:
        _label(last_name)
        if type(birth_date) is not date or not date(1850, 1, 1) <= birth_date <= date.today():
            raise TebraReadError("request_invalid")
        rows = self._read("GetPatients", scope, credentials,
                          ("DOB", "ID", "LastName", "PatientFullName", "PracticeName"),
                          {"FromDateOfBirth": birth_date.isoformat(), "LastName": last_name,
                           "PracticeID": str(scope.practice_id), "PracticeName": scope.practice_name,
                           "ToDateOfBirth": birth_date.isoformat()}, "Patients", "PatientData")
        patients = []
        for row in rows:
            self._practice_label(row, scope)
            if _text(row, "DOB") != birth_date.isoformat() or _text(row, "LastName") != last_name:
                raise TebraReadError("response_invalid")
            patients.append(TebraPatient(_id(_text(row, "ID")),
                                         _text(row, "PatientFullName"), birth_date))
        self._unique([p.patient_id for p in patients])
        return TebraReadResult(scope, "GetPatients", datetime.now(UTC), tuple(patients))

    def read_appointments(self, scope: TebraReadScope, credentials: TebraCredentials, *,
                          starts_at: datetime, ends_at: datetime) -> TebraReadResult:
        if (type(starts_at) is not datetime or type(ends_at) is not datetime
                or starts_at.utcoffset() is None or ends_at.utcoffset() is None):
            raise TebraReadError("request_invalid")
        starts_at, ends_at = starts_at.astimezone(UTC), ends_at.astimezone(UTC)
        if not timedelta(0) < ends_at - starts_at <= timedelta(days=7):
            raise TebraReadError("request_invalid")
        rows = self._read("GetAppointments", scope, credentials,
                          ("ConfirmationStatus", "EndDate", "ID", "PatientID", "PracticeID",
                           "PracticeName", "StartDate"),
                          {"EndDate": ends_at.isoformat(), "PracticeName": scope.practice_name,
                           "StartDate": starts_at.isoformat(), "TimeZoneOffsetFromGMT": "0",
                           "Type": "P"}, "Appointments", "AppointmentData")
        appointments = []
        for row in rows:
            self._practice_label(row, scope)
            if _id(_text(row, "PracticeID")) != scope.practice_id:
                raise TebraReadError("scope_changed")
            start, end = self._instant(row, "StartDate"), self._instant(row, "EndDate")
            if not starts_at <= start < ends_at or not timedelta(0) < end - start <= timedelta(days=1):
                raise TebraReadError("response_invalid")
            status = _text(row, "ConfirmationStatus")
            if status not in {"Confirmed", "Check-in", "No-show", "Check-out", "Rescheduled",
                              "Scheduled", "Cancelled"}:
                raise TebraReadError("response_invalid")
            appointments.append(TebraAppointment(_id(_text(row, "ID")),
                                                 _id(_text(row, "PatientID")), start, end, status))
        self._unique([a.appointment_id for a in appointments])
        return TebraReadResult(scope, "GetAppointments", datetime.now(UTC), tuple(appointments))

    @staticmethod
    def _practice_label(row: ET.Element, scope: TebraReadScope) -> None:
        if _text(row, "PracticeName") != scope.practice_name:
            raise TebraReadError("scope_changed")

    @staticmethod
    def _unique(values: list[int]) -> None:
        if len(values) != len(set(values)):
            raise TebraReadError("response_invalid")

    @staticmethod
    def _instant(row: ET.Element, name: str) -> datetime:
        try:
            value = datetime.fromisoformat(_text(row, name))
            if value.utcoffset() is None:
                raise ValueError
            return value.astimezone(UTC)
        except ValueError:
            raise TebraReadError("response_invalid") from None
