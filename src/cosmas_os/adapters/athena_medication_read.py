"""Inactive athenaOne medication-section reader; only invented MockTransport is accepted."""

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

import httpx

from cosmas_os.adapters.athena_allergy_read import (
    AthenaAllergyError,
)
from cosmas_os.adapters.athena_allergy_read import (
    _text as _identity_text,
)
from cosmas_os.adapters.athena_allergy_read import (
    patient_identity as _patient_identity,
)
from cosmas_os.domain.hashing import payload_hash

ORIGINS = {
    "preview": "https://api.preview.platform.athenahealth.com",
    "production": "https://api.platform.athenahealth.com",
}
MAX_BYTES = 65536
MAX_RECORDS = 25
MAX_GROUPS = 25
MAX_DEPTH = 16
MAX_NODES = 4096
MAX_STRING = 4096
MAX_KEY = 128
MAX_NUMBER = 128
NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z")
INTEGER = re.compile(r"-?(?:0|[1-9][0-9]*)\Z")


class AthenaMedicationError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _text(value, limit=1000, *, multiline=False):
    # Scope labels and the existing Patient identity retain their original bounds.
    try:
        return _identity_text(value, limit, multiline=multiline)
    except AthenaAllergyError:
        raise AthenaMedicationError("response_invalid") from None


def _string(value, limit=MAX_STRING):
    if (
        type(value) is not str
        or len(value) > limit
        or any(ord(c) == 0 or 0xD800 <= ord(c) <= 0xDFFF for c in value)
    ):
        raise AthenaMedicationError("response_invalid")
    return value


@dataclass(frozen=True, repr=False)
class RecordedNumber:
    """A validated JSON number token, never a binary float or a clinical value."""

    token: str

    def __post_init__(self):
        if (
            type(self.token) is not str
            or len(self.token) > MAX_NUMBER
            or not NUMBER.fullmatch(self.token)
        ):
            raise AthenaMedicationError("response_invalid")


def _digest(value):
    if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise AthenaMedicationError("invalid_proof")
    return value


def _id(value):
    if type(value) is not str or not re.fullmatch(r"[1-9][0-9]{0,17}", value):
        raise AthenaMedicationError("invalid_scope")
    return value


def _tree(value):
    count = 0

    def visit(item, depth=0):
        nonlocal count
        count += 1
        if count > MAX_NODES or depth > MAX_DEPTH:
            raise AthenaMedicationError("response_too_large")
        if type(item) is dict:
            if len(item) > 64:
                raise AthenaMedicationError("response_too_large")
            for key, child in item.items():
                _string(key, MAX_KEY)
                visit(child, depth + 1)
        elif type(item) is list:
            if len(item) > 256:
                raise AthenaMedicationError("response_too_large")
            for child in item:
                visit(child, depth + 1)
        elif type(item) is str:
            _string(item)
        elif type(item) is RecordedNumber:
            RecordedNumber(item.token)
        elif item is not None and type(item) is not bool:
            raise AthenaMedicationError("response_invalid")

    visit(value)


def clinical_loads(raw):
    """Strict bounded UTF-8 JSON; escaped string contents and number tokens survive."""

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise AthenaMedicationError("response_invalid")
            result[key] = value
        return result

    try:
        if type(raw) is bytes:
            if len(raw) > MAX_BYTES:
                raise AthenaMedicationError("response_too_large")
            text = raw.decode("utf-8", errors="strict")
        elif type(raw) is str:
            if len(raw.encode("utf-8")) > MAX_BYTES:
                raise AthenaMedicationError("response_too_large")
            text = raw
        else:
            raise AthenaMedicationError("response_invalid")
        value = json.loads(
            text,
            object_pairs_hook=pairs,
            parse_int=RecordedNumber,
            parse_float=RecordedNumber,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
        _tree(value)
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise AthenaMedicationError("response_invalid") from None


def clinical_dumps(value):
    """Medication-only canonical JSON: codepoint-sorted keys, exact numeric spelling."""
    _tree(value)

    def encode(item):
        if type(item) is dict:
            return (
                "{"
                + ",".join(
                    json.dumps(key, ensure_ascii=True) + ":" + encode(item[key])
                    for key in sorted(item)
                )
                + "}"
            )
        if type(item) is list:
            return "[" + ",".join(encode(child) for child in item) + "]"
        if type(item) is RecordedNumber:
            return item.token
        return json.dumps(item, ensure_ascii=True, separators=(",", ":"))

    return encode(value)


def _object(value, allowed):
    if type(value) is not dict or set(value) - set(allowed):
        raise AthenaMedicationError("unsupported_record")
    return value


def _array(value, maximum):
    if type(value) is not list:
        raise AthenaMedicationError("response_invalid")
    if len(value) > maximum:
        raise AthenaMedicationError("too_many_results")
    return value


@dataclass(frozen=True, repr=False)
class AthenaMedicationScope:
    box_id: UUID
    owner_id: UUID
    account_id: UUID
    connection_id: UUID
    credential_generation: UUID
    workspace_id: UUID
    patient_link_id: UUID
    practice_id: str
    department_id: str
    patient_id: str
    practice_label: str
    department_label: str
    authorization_sha256: str
    environment: Literal["preview", "production"] = "preview"
    medication_type: Literal["ACTIVE"] = "ACTIVE"
    includes_pending: Literal[True] = True
    includes_ndc: Literal[True] = True
    includes_rxnorm: Literal[True] = True

    def __post_init__(self):
        for name in (
            "box_id",
            "owner_id",
            "account_id",
            "connection_id",
            "credential_generation",
            "workspace_id",
            "patient_link_id",
        ):
            if type(getattr(self, name)) is not UUID:
                raise AthenaMedicationError("invalid_scope")
        for name in ("practice_id", "department_id", "patient_id"):
            _id(getattr(self, name))
        for value in (self.practice_label, self.department_label):
            if not _text(value, 200).strip():
                raise AthenaMedicationError("invalid_scope")
        _digest(self.authorization_sha256)
        if (
            self.medication_type != "ACTIVE"
            or self.includes_pending is not True
            or self.includes_ndc is not True
            or self.includes_rxnorm is not True
        ):
            raise AthenaMedicationError("invalid_scope")
        if self.environment not in ORIGINS:
            raise AthenaMedicationError("invalid_scope")

    def commitment(self):
        return payload_hash(
            {
                "contract": "athena-medication-patient-scope.v1",
                "origin": ORIGINS[self.environment],
                **{k: str(v) if type(v) is UUID else v for k, v in asdict(self).items()},
            }
        )


@dataclass(frozen=True, repr=False)
class AthenaMedicationPatient:
    patient_id: str
    identity_json: str
    identity_sha256: str


def patient_identity(value, scope):
    # Shared identity validation is not shared permission. Only the medication
    # scope/authorization callback grants this reader's independent chart read.
    try:
        patient = _patient_identity(value, scope)
    except AthenaAllergyError as exc:
        raise AthenaMedicationError(exc.code) from None
    return AthenaMedicationPatient(
        patient.patient_id, patient.identity_json, patient.identity_sha256
    )


@dataclass(frozen=True, repr=False)
class AthenaMedicationRecord:
    medication_entry_id: str | None
    medication_name: str | None
    original_json: str


SECTION_KEYS = {
    "lastdownloaddenialreason",
    "lastdownloaddenied",
    "lastdownloadeddate",
    "lastupdated",
    "medications",
    "nomedicationsreported",
    "patientdownloadconsent",
    "patientneedsdownloadconsent",
    "sectionnote",
}
SECTION_BOOLEANS = {
    "lastdownloaddenied",
    "nomedicationsreported",
    "patientdownloadconsent",
    "patientneedsdownloadconsent",
}
RECORD_KEYS = {
    "approvedby",
    "billingndc",
    "createdby",
    "earliestfilldate",
    "encounterid",
    "events",
    "filldate",
    "futuresubmitdate",
    "isdiscontinued",
    "issafetorenew",
    "isstructuredsig",
    "medication",
    "medicationentryid",
    "medicationid",
    "ndcoptions",
    "newindicator",
    "orderingmode",
    "organclass",
    "patientnote",
    "pharmacy",
    "pharmacyncpdpid",
    "prescribedby",
    "providernote",
    "quantity",
    "quantityunit",
    "refillsallowed",
    "route",
    "rxnorm",
    "source",
    "status",
    "stopreason",
    "structuredsig",
    "therapeuticclass",
    "unstructuredsig",
}
RECORD_BOOLEANS = {"isdiscontinued", "issafetorenew", "isstructuredsig"}
RECORD_INTEGERS = {"encounterid", "medicationid", "refillsallowed"}
EVENT_KEYS = {"eventdate", "type", "userdisplayname"}


def medication_records(value):
    _tree(value)
    value = _object(value, SECTION_KEYS)
    groups = _array(value.get("medications"), MAX_GROUPS)
    for key in set(value) - {"medications"}:
        if key in SECTION_BOOLEANS:
            if type(value[key]) is not bool:
                raise AthenaMedicationError("response_invalid")
        else:
            _string(value[key])
    result, count = [], 0
    for group in groups:
        rows = []
        for record in _array(group, MAX_RECORDS):
            count += 1
            if count > MAX_RECORDS:
                raise AthenaMedicationError("too_many_results")
            record = _object(record, RECORD_KEYS)
            for key, item in record.items():
                if key in RECORD_BOOLEANS:
                    if type(item) is not bool:
                        raise AthenaMedicationError("response_invalid")
                elif key in RECORD_INTEGERS:
                    if (
                        type(item) is not RecordedNumber
                        or not INTEGER.fullmatch(item.token)
                        or not -(2**63) <= int(item.token) <= 2**63 - 1
                    ):
                        raise AthenaMedicationError("response_invalid")
                elif key == "quantity":
                    if type(item) is not RecordedNumber:
                        raise AthenaMedicationError("response_invalid")
                elif key == "structuredsig":
                    if type(item) is not dict:
                        raise AthenaMedicationError("response_invalid")
                elif key == "events":
                    for event in _array(item, 100):
                        event = _object(event, EVENT_KEYS)
                        for field, recorded in event.items():
                            if field != "userdisplayname" or recorded is not None:
                                _string(recorded)
                elif key in ("ndcoptions", "rxnorm"):
                    field = "ndcoption" if key == "ndcoptions" else "rxnormidentifier"
                    for option in _array(item, 100):
                        option = _object(option, {field})
                        for recorded in option.values():
                            _string(recorded)
                else:
                    _string(item, 300 if key == "medicationentryid" else MAX_STRING)
            rows.append(
                AthenaMedicationRecord(
                    record.get("medicationentryid"),
                    record.get("medication"),
                    clinical_dumps(record),
                )
            )
        result.append(tuple(rows))
    return tuple(result)


@dataclass(frozen=True, repr=False)
class AthenaMedicationObservation:
    scope: AthenaMedicationScope
    patient: AthenaMedicationPatient
    observed_at: datetime
    groups: tuple[tuple[AthenaMedicationRecord, ...], ...]
    section_json: str
    provider_sources: tuple[str, str]
    source_sha256: str
    coverage: Literal["returned_section_only"] = "returned_section_only"
    medication_type: Literal["ACTIVE"] = "ACTIVE"
    includes_pending: Literal[True] = True
    includes_ndc: Literal[True] = True
    includes_rxnorm: Literal[True] = True


def observation_hash(value):
    return payload_hash(
        {
            "contract": "athena-medication-observation.v1",
            "scope_sha256": value.scope.commitment(),
            "patient": asdict(value.patient),
            "observed_at": value.observed_at.isoformat(),
            "section_json": value.section_json,
            "provider_sources": list(value.provider_sources),
            "coverage": value.coverage,
            "medication_type": value.medication_type,
            "includes_pending": value.includes_pending,
            "includes_ndc": value.includes_ndc,
            "includes_rxnorm": value.includes_rxnorm,
        }
    )


class AthenaMedicationReader:
    def __init__(
        self,
        scope: AthenaMedicationScope,
        transport: httpx.MockTransport,
        *,
        expected_identity_sha256: str,
        enabled: Callable[[], bool],
        authorize: Callable[[AthenaMedicationScope], bool],
    ):
        if type(scope) is not AthenaMedicationScope or type(transport) is not httpx.MockTransport:
            raise AthenaMedicationError("synthetic_transport_required")
        self.scope, self.transport = scope, transport
        self.expected_identity_sha256 = _digest(expected_identity_sha256)
        self.enabled, self.authorize = enabled, authorize

    def _current(self):
        if not self.enabled():
            raise AthenaMedicationError("disabled")
        if self.authorize(self.scope) is not True:
            raise AthenaMedicationError("access_denied")

    def _get(self, client, path, parameters):
        self._current()
        try:
            with client.stream(
                "GET",
                ORIGINS[self.scope.environment] + path,
                params=parameters,
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "identity",
                    "Authorization": "Bearer invented-athena-clinical-token",
                },
            ) as response:
                if response.status_code == 429:
                    raise AthenaMedicationError("rate_limited")
                if response.status_code in (401, 403):
                    raise AthenaMedicationError("access_denied")
                if response.status_code != 200:
                    raise AthenaMedicationError("provider_unavailable")
                if (
                    response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    != "application/json"
                    or response.headers.get("content-encoding", "identity").lower() != "identity"
                ):
                    raise AthenaMedicationError("response_invalid")
                raw = bytearray()
                for part in response.iter_raw():
                    if len(raw) + len(part) > MAX_BYTES:
                        raise AthenaMedicationError("response_too_large")
                    raw.extend(part)
            self._current()
            return clinical_loads(bytes(raw)), hashlib.sha256(raw).hexdigest()
        except httpx.HTTPError:
            raise AthenaMedicationError("provider_unavailable") from None

    def read(self):
        self._current()
        scope = self.scope
        with httpx.Client(
            transport=self.transport, follow_redirects=False, trust_env=False, timeout=15
        ) as client:
            raw, identity_proof = self._get(
                client,
                f"/v1/{scope.practice_id}/patients/{scope.patient_id}",
                {"departmentid": scope.department_id},
            )
            patient = patient_identity(raw, scope)
            if patient.identity_sha256 != self.expected_identity_sha256:
                raise AthenaMedicationError("patient_changed")
            section, clinical_proof = self._get(
                client,
                f"/v1/{scope.practice_id}/chart/{scope.patient_id}/medications",
                {
                    "departmentid": scope.department_id,
                    "medicationtype": "ACTIVE",
                    "showpend": "true",
                    "showndc": "true",
                    "showrxnorm": "true",
                },
            )
            groups = medication_records(section)
            observed = AthenaMedicationObservation(
                scope,
                patient,
                datetime.now(UTC),
                groups,
                clinical_dumps(section),
                (identity_proof, clinical_proof),
                "",
            )
            self._current()
            return AthenaMedicationObservation(
                scope,
                patient,
                observed.observed_at,
                groups,
                observed.section_json,
                observed.provider_sources,
                observation_hash(observed),
            )
