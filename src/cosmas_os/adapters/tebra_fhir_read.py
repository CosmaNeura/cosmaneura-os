"""Bounded synthetic Tebra FHIR reads; no OAuth, live transport or runtime wiring.

Resource/reference design follows FHIR R4 and US Core 3.1.1. See
docs/tebra-fhir-read.md for evidence, limits and unresolved vendor contracts.
"""

import json
import math
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from typing import Literal
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import httpx
from pydantic import SecretStr

from cosmas_os.domain.hashing import canonical_json, payload_hash

FHIR_BASE = "https://fhir.prd.cloud.tebra.com/fhir-request"
MAX_BYTES = 262144
MAX_ROWS = 25
MAX_ENTRIES = 75
MAX_PROJECTION_BYTES = 65536
_ID = re.compile(r"[A-Za-z0-9.-]{1,64}\Z")
_DATE = re.compile(r"[0-9]{4}(?:-[0-9]{2}(?:-[0-9]{2})?)?\Z")
_TIME = re.compile(r"([0-9]{4}-[0-9]{2}-[0-9]{2})T(?:[01][0-9]|2[0-3]):[0-5][0-9]:(?:[0-5][0-9]|60)(?:\.[0-9]+)?(?:Z|[+-](?:(?:0[0-9]|1[0-3]):[0-5][0-9]|14:00))\Z")
_STATUSES = {"active", "on-hold", "cancelled", "completed", "entered-in-error", "stopped", "draft", "unknown"}
ErrorCode = Literal["connector_disabled", "provider_qualification_required", "access_denied", "scope_changed",
    "request_invalid", "response_invalid", "response_too_large", "too_many_results", "unsupported_record",
    "patient_changed", "provider_throttled", "provider_rejected", "transport_unconfirmed"]


class TebraFhirReadError(Exception):
    def __init__(self, code: ErrorCode):
        self.code = code
        super().__init__(code)


def _id(value):
    if type(value) is not str or not _ID.fullmatch(value) or value in (".", ".."):
        raise TebraFhirReadError("response_invalid")
    return value


def _text(value, maximum=1000, *, instructions=False):
    if (type(value) is not str or not 1 <= len(value) <= maximum
            or any((ord(c) < 32 and not (instructions and c in "\t\r\n"))
                   or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in value)):
        raise TebraFhirReadError("response_invalid")
    return value


def _date(value, *, time_allowed=False):
    _text(value, 64)
    try:
        if _DATE.fullmatch(value):
            fields = value.split("-")
            date(int(fields[0]), int(fields[1]) if len(fields) > 1 else 1,
                 int(fields[2]) if len(fields) > 2 else 1)
        elif time_allowed and (match := _TIME.fullmatch(value)):
            date.fromisoformat(match[1])
        else:
            raise ValueError
    except ValueError:
        raise TebraFhirReadError("response_invalid") from None
    return value


def _object(value):
    if type(value) is not dict:
        raise TebraFhirReadError("response_invalid")
    return value


def _array(value, maximum=25):
    if type(value) is not list:
        raise TebraFhirReadError("response_invalid")
    if len(value) > maximum:
        raise TebraFhirReadError("too_many_results")
    return value


def _tree(value):
    """Bound JSON and refuse unknown clinical modifiers anywhere in a resource."""
    nodes = 0

    def visit(item, depth=0):
        nonlocal nodes
        nodes += 1
        if nodes > 12000 or depth > 24:
            raise TebraFhirReadError("response_too_large")
        if isinstance(item, dict):
            if "modifierExtension" in item or "implicitRules" in item:
                raise TebraFhirReadError("unsupported_record")
            for key, child in item.items():
                _text(key, 100)
                visit(child, depth+1)
        elif isinstance(item, list):
            for child in item:
                visit(child, depth+1)
        elif isinstance(item, str):
            # Empty optional FHIR strings are not valid elements.
            _text(item, 12000, instructions=True)
        elif type(item) is float and not math.isfinite(item):
            raise TebraFhirReadError("response_invalid")
        elif item is None or type(item) not in (int, float, bool):
            raise TebraFhirReadError("response_invalid")
    visit(value)


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise TebraFhirReadError("response_invalid")
            result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: None)
        _tree(value)
        return _object(value)
    except (ValueError, UnicodeError, RecursionError):
        raise TebraFhirReadError("response_invalid") from None


@dataclass(frozen=True, repr=False)
class TebraFhirScope:
    box_id: UUID
    owner_id: UUID
    connection_id: UUID
    credential_generation: UUID
    patient_id: str
    # Server-owned commitment to current clinical authorization, not an OAuth scope string.
    authorization_sha256: str

    def validate(self):
        if (any(type(v) is not UUID for v in (self.box_id, self.owner_id, self.connection_id, self.credential_generation))
                or type(self.authorization_sha256) is not str or not re.fullmatch(r"[a-f0-9]{64}", self.authorization_sha256)):
            raise TebraFhirReadError("request_invalid")
        try:
            _id(self.patient_id)
        except TebraFhirReadError:
            raise TebraFhirReadError("request_invalid") from None

    def commitment(self):
        self.validate()
        return payload_hash({"contract": "tebra-fhir-patient-scope.v1", "fhir_base": FHIR_BASE,
            **{key: str(value) for key, value in asdict(self).items()}})


@dataclass(frozen=True, repr=False)
class TebraFhirCredential:
    scope_sha256: str
    access_token: SecretStr


@dataclass(frozen=True, repr=False)
class TebraFhirPatient:
    patient_id: str
    # Canonical JSON keeps all supplied names/identifiers and missing-field distinction.
    identity_json: str
    identity_sha256: str


@dataclass(frozen=True, repr=False)
class TebraFhirMedication:
    record_id: str
    patient_id: str
    status: str
    intent: Literal["order", "plan"]
    authored_on: str
    do_not_perform: bool | None
    reported_json: str | None
    # Preserve the original choice and reference metadata; it does not override the resolved drug.
    request_medication_json: str
    medication_name: str | None
    medication_json: str
    dosage_instructions_json: str | None
    # Status reasons, requester and encounter are retained without dereferencing them.
    context_json: str


@dataclass(frozen=True, repr=False)
class TebraFhirMedicationRead:
    scope: TebraFhirScope
    patient: TebraFhirPatient
    observed_at: datetime
    rows: tuple[TebraFhirMedication, ...]
    coverage: Literal["more_rows_available", "returned_page_only"]
    reported_total: int | None
    warnings: tuple[str, ...]
    source_sha256: str
    provider_sources: tuple[str, ...]


def _resource(value, kind, identifier=None):
    _object(value)
    if value.get("resourceType") != kind or identifier is not None and value.get("id") != identifier:
        raise TebraFhirReadError("response_invalid")
    _id(value.get("id"))
    return value


def _reference(value, kind):
    _text(value, 512)
    prefix = FHIR_BASE+"/"+kind+"/"
    identifier = value.removeprefix(prefix) if value.startswith(prefix) else value.removeprefix(kind+"/")
    if identifier == value:
        raise TebraFhirReadError("unsupported_record")
    _id(identifier)
    return identifier


def _concept(value):
    value = _object(value)
    label = _text(value["text"], 1000, instructions=True) if "text" in value else None
    codings = _array(value.get("coding", []), 20)
    displays = []
    for coding in codings:
        coding = _object(coding)
        _text(coding.get("code"), 256)
        if "system" in coding:
            _text(coding["system"], 512)
        if "display" in coding:
            displays.append(_text(coding["display"], 1000, instructions=True))
    if label is None and not codings:
        raise TebraFhirReadError("response_invalid")
    return label or (displays[0] if displays and len(set(displays)) == 1 else None)


def _patient(value, scope):
    _resource(value, "Patient", scope.patient_id)
    names = _array(value.get("name", []), 20)
    if not names:
        raise TebraFhirReadError("unsupported_record")
    for key in ("active", "deceasedBoolean"):
        if key in value and type(value[key]) is not bool:
            raise TebraFhirReadError("response_invalid")
    if "deceasedDateTime" in value:
        _date(value["deceasedDateTime"], time_allowed=True)
    if "deceasedDateTime" in value and "deceasedBoolean" in value:
        raise TebraFhirReadError("response_invalid")
    for name in names:
        name = _object(name)
        if not any(name.get(key) for key in ("text", "family", "given")):
            raise TebraFhirReadError("unsupported_record")
        for key in ("text", "family", "use"):
            if key in name:
                _text(name[key], 300)
        for key in ("given", "prefix", "suffix"):
            for part in _array(name.get(key, []), 20):
                _text(part, 100)
    if "birthDate" in value:
        _date(value["birthDate"])
    if "gender" in value and value["gender"] not in ("male", "female", "other", "unknown"):
        raise TebraFhirReadError("response_invalid")
    for identifier in _array(value.get("identifier", []), 30):
        _object(identifier)
        if "value" in identifier:
            _text(identifier["value"], 300)
        if "system" in identifier:
            _text(identifier["system"], 512)
    identity = {key: value[key] for key in ("resourceType", "id", "name", "birthDate", "gender", "identifier", "active", "deceasedBoolean", "deceasedDateTime", "link", "managingOrganization") if key in value}
    return TebraFhirPatient(scope.patient_id, canonical_json(identity), payload_hash(identity))


def _page(value, scope):
    if value.get("resourceType") != "Bundle" or value.get("type") != "searchset":
        raise TebraFhirReadError("response_invalid")
    links = {}
    for link in _array(value.get("link", []), 10):
        link = _object(link)
        relation, url = _text(link.get("relation"), 32), _text(link.get("url"), 2048)
        if relation in links:
            raise TebraFhirReadError("response_invalid")
        parts = urlsplit(url)
        if (parts.scheme != "https" or parts.netloc != "fhir.prd.cloud.tebra.com"
                or not (parts.path == "/fhir-request" or parts.path.startswith("/fhir-request/"))
                or parts.fragment or any(part in (".", "..") for part in parts.path.split("/"))
                or "%" in parts.path or any(c in url for c in "\\\r\n\t")):
            raise TebraFhirReadError("response_invalid")
        links[relation] = url
    self_url = urlsplit(links.get("self", ""))
    query = parse_qs(self_url.query, keep_blank_values=True)
    if (self_url.path != "/fhir-request/MedicationRequest" or query != {
            "patient": [scope.patient_id], "intent": ["order,plan"],
            "_include": ["MedicationRequest:medication"], "_count": ["25"]}):
        raise TebraFhirReadError("response_invalid")
    requests, medications, warnings, seen = [], {}, [], set()
    for entry in _array(value.get("entry", []), MAX_ENTRIES):
        entry = _object(entry)
        row = _object(entry.get("resource"))
        kind = _text(row.get("resourceType"), 64)
        search = _object(entry.get("search", {}))
        expected_mode = {"MedicationRequest": "match", "Medication": "include", "OperationOutcome": "outcome"}.get(kind)
        if expected_mode is None or search.get("mode", expected_mode) != expected_mode:
            raise TebraFhirReadError("response_invalid")
        if kind == "OperationOutcome":
            for issue in _array(row.get("issue"), 20):
                issue = _object(issue)
                if issue.get("severity") not in ("warning", "information"):
                    raise TebraFhirReadError("provider_rejected")
                warnings.append(_text(issue.get("code"), 64))
            continue
        _resource(row, kind)
        resource_key = (kind, row["id"])
        if resource_key in seen:
            raise TebraFhirReadError("response_invalid")
        seen.add(resource_key)
        if entry.get("fullUrl") != FHIR_BASE+"/"+kind+"/"+row["id"]:
            raise TebraFhirReadError("response_invalid")
        if kind == "MedicationRequest":
            if _reference(_object(row.get("subject")).get("reference"), "Patient") != scope.patient_id:
                raise TebraFhirReadError("scope_changed")
            requests.append(row)
        else:
            medications[row["id"]] = row
    if len(requests) > MAX_ROWS or len(medications) > MAX_ROWS:
        raise TebraFhirReadError("too_many_results")
    total = value.get("total")
    if "total" in value and (type(total) is not int or not len(requests) <= total <= 2147483647):
        raise TebraFhirReadError("response_invalid")
    return requests, medications, tuple(warnings), "next" in links, total


def _project(row, medication, patient_id):
    if type(row.get("status")) is not str or row["status"] not in _STATUSES or row.get("intent") not in ("order", "plan"):
        raise TebraFhirReadError("response_invalid")
    authored = _date(row.get("authoredOn"), time_allowed=True)
    negation = row.get("doNotPerform")
    if "doNotPerform" in row and type(negation) is not bool:
        raise TebraFhirReadError("response_invalid")
    reported = [key for key in ("reportedBoolean", "reportedReference") if key in row]
    if len(reported) > 1:
        raise TebraFhirReadError("response_invalid")
    if reported:
        if reported[0] == "reportedBoolean" and type(row[reported[0]]) is not bool:
            raise TebraFhirReadError("response_invalid")
        if reported[0] == "reportedReference":
            _object(row[reported[0]])
    dosage = row.get("dosageInstruction")
    if "dosageInstruction" in row:
        for instruction in _array(dosage, 20):
            _object(instruction)
            if "sequence" in instruction and (type(instruction["sequence"]) is not int or instruction["sequence"] < 0):
                raise TebraFhirReadError("response_invalid")
            if "asNeededBoolean" in instruction and type(instruction["asNeededBoolean"]) is not bool:
                raise TebraFhirReadError("response_invalid")
            if "asNeededBoolean" in instruction and "asNeededCodeableConcept" in instruction:
                raise TebraFhirReadError("response_invalid")
            for key in ("route", "site", "method", "asNeededCodeableConcept"):
                if key in instruction:
                    _concept(instruction[key])
            for additional in _array(instruction.get("additionalInstruction", []), 20):
                _concept(additional)
            if "timing" in instruction:
                _object(instruction["timing"])
            for dose in _array(instruction.get("doseAndRate", []), 20):
                _object(dose)
            if "text" in instruction:
                _text(instruction["text"], 4000, instructions=True)
            if "patientInstruction" in instruction:
                _text(instruction["patientInstruction"], 4000, instructions=True)
    context = {key: row[key] for key in ("statusReason", "requester", "encounter", "category", "note", "reasonCode", "reasonReference",
        "courseOfTherapyType", "dispenseRequest", "substitution", "priorPrescription", "basedOn", "groupIdentifier",
        "insurance", "supportingInformation", "detectedIssue", "eventHistory") if key in row}
    return TebraFhirMedication(row["id"], patient_id, row["status"], row["intent"], authored, negation,
        canonical_json({reported[0]: row[reported[0]]}) if reported else None,
        canonical_json({key: row[key] for key in ("medicationCodeableConcept", "medicationReference") if key in row}),
        _concept(medication.get("code")), canonical_json(medication),
        canonical_json(dosage) if dosage is not None else None, canonical_json(context))


class TebraFhirReadAdapter:
    """Mock-only reader of one already-authorized FHIR patient; never authenticates."""

    def __init__(self, *, enabled=False, transport=None, authorize_read: Callable[[TebraFhirScope], bool] | None = None,
                 verify_patient: Callable[[TebraFhirScope, TebraFhirPatient], bool] | None = None,
                 now=lambda: datetime.now(UTC), monotonic=time.monotonic):
        if type(enabled) is not bool:
            raise TebraFhirReadError("request_invalid")
        self._enabled, self._transport = enabled, transport
        self._authorize, self._verify_patient = authorize_read, verify_patient
        self._now, self._monotonic = now, monotonic

    def medication_history(self, scope: TebraFhirScope, credential: TebraFhirCredential) -> TebraFhirMedicationRead:
        if not self._enabled:
            raise TebraFhirReadError("connector_disabled")
        if type(self._transport) is not httpx.MockTransport:
            raise TebraFhirReadError("provider_qualification_required")
        if type(scope) is not TebraFhirScope or not callable(self._authorize) or not callable(self._verify_patient):
            raise TebraFhirReadError("request_invalid")
        authorize, verify_patient = self._authorize, self._verify_patient
        scope.validate()
        deadline = self._monotonic()+30
        used = 0
        proofs = []

        def authorized():
            if self._monotonic() >= deadline:
                raise TebraFhirReadError("transport_unconfirmed")
            if authorize(scope) is not True:
                raise TebraFhirReadError("access_denied")

        try:
            authorized()
            if type(credential) is not TebraFhirCredential or credential.scope_sha256 != scope.commitment():
                raise TebraFhirReadError("scope_changed")
            if not isinstance(credential.access_token, SecretStr):
                raise TebraFhirReadError("request_invalid")
            token = credential.access_token.get_secret_value()
            if not 1 <= len(token) <= 16384 or any(ord(c) < 33 or ord(c) > 126 for c in token):
                raise TebraFhirReadError("request_invalid")
            with httpx.Client(transport=self._transport, timeout=10, follow_redirects=False, trust_env=False) as client:
                def get(resource, *, params=None):
                    nonlocal used
                    authorized()
                    client.cookies.clear()
                    with client.stream("GET", FHIR_BASE+"/"+resource, params=params,
                            headers={"Authorization": "Bearer "+token, "Accept": "application/fhir+json", "Accept-Encoding": "identity"}) as response:
                        if response.status_code == 429:
                            raise TebraFhirReadError("provider_throttled")
                        if response.status_code != 200:
                            raise TebraFhirReadError("provider_rejected")
                        if (response.headers.get("content-type", "").split(";", 1)[0].lower() not in ("application/fhir+json", "application/json")
                                or response.headers.get("content-encoding") not in (None, "identity")):
                            raise TebraFhirReadError("response_invalid")
                        raw = bytearray()
                        for chunk in response.iter_raw():
                            authorized()
                            used += len(chunk)
                            if used > MAX_BYTES:
                                raise TebraFhirReadError("response_too_large")
                            raw.extend(chunk)
                    authorized()
                    value = _json(raw)
                    proofs.append(payload_hash({"url": str(response.request.url), "body": value}))
                    return value

                patient = _patient(get("Patient/"+scope.patient_id), scope)
                if verify_patient(scope, patient) is not True:
                    raise TebraFhirReadError("patient_changed")
                authorized()
                rows, included, warnings, more, total = _page(get("MedicationRequest", params={
                    "patient": scope.patient_id, "intent": "order,plan", "_include": "MedicationRequest:medication", "_count": "25"}), scope)
                projected, fetched, used_includes = [], {}, set()
                for row in rows:
                    variants = [key for key in ("medicationCodeableConcept", "medicationReference") if key in row]
                    if len(variants) != 1:
                        raise TebraFhirReadError("response_invalid")
                    if variants[0] == "medicationCodeableConcept":
                        medication = {"code": row[variants[0]]}
                    else:
                        reference = _text(_object(row[variants[0]]).get("reference"), 512)
                        if reference.startswith("#"):
                            identifier = _id(reference[1:])
                            contained = _array(row.get("contained", []), 25)
                            matches = [item for item in contained if _object(item).get("id") == identifier]
                            if len(matches) != 1:
                                raise TebraFhirReadError("response_invalid")
                            medication = _resource(matches[0], "Medication", identifier)
                        else:
                            identifier = _reference(reference, "Medication")
                            if identifier in included:
                                medication = included[identifier]
                                used_includes.add(identifier)
                            else:
                                if identifier not in fetched:
                                    fetched[identifier] = _resource(get("Medication/"+identifier), "Medication", identifier)
                                medication = fetched[identifier]
                    projected.append(_project(row, medication, scope.patient_id))
                if used_includes != set(included):
                    raise TebraFhirReadError("response_invalid")
            authorized()
            observed = self._now()
            if type(observed) is not datetime or observed.utcoffset() is None:
                raise TebraFhirReadError("response_invalid")
            content = {"scope_sha256": scope.commitment(), "patient": asdict(patient), "rows": [asdict(r) for r in projected],
                "observed_at": observed.isoformat(), "coverage": "more_rows_available" if more else "returned_page_only",
                "reported_total": total, "warnings": warnings, "provider_sources": proofs}
            if len(canonical_json(content).encode()) > MAX_PROJECTION_BYTES:
                raise TebraFhirReadError("response_too_large")
            return TebraFhirMedicationRead(scope, patient, observed, tuple(projected), content["coverage"], total, warnings,
                payload_hash({"contract": "tebra-fhir-medication-history.v1", **content}), tuple(proofs))
        except TebraFhirReadError:
            raise
        except Exception:
            raise TebraFhirReadError("transport_unconfirmed") from None
