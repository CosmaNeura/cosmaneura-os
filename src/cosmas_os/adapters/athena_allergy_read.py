"""Inactive athenaOne allergy-section reader; only invented MockTransport is accepted."""

import hashlib
import json
import math
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

import httpx

from cosmas_os.domain.hashing import canonical_json, payload_hash

ORIGINS = {
    "preview": "https://api.preview.platform.athenahealth.com",
    "production": "https://api.platform.athenahealth.com",
}
MAX_BYTES = 65536
MAX_RECORDS = 25


class AthenaAllergyError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _text(value, limit=1000, *, multiline=False):
    if (
        type(value) is not str
        or len(value) > limit
        or any(
            ord(c) == 127
            or 0xD800 <= ord(c) <= 0xDFFF
            or ord(c) < 32
            and not (multiline and c in "\r\n\t")
            for c in value
        )
    ):
        raise AthenaAllergyError("response_invalid")
    return value


def _digest(value):
    if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise AthenaAllergyError("invalid_proof")
    return value


def _id(value):
    if type(value) is not str or not re.fullmatch(r"[1-9][0-9]{0,17}", value):
        raise AthenaAllergyError("invalid_scope")
    return value


def _tree(value):
    count = 0

    def visit(item, depth=0):
        nonlocal count
        count += 1
        if count > 12000 or depth > 20:
            raise AthenaAllergyError("response_too_large")
        if type(item) is dict:
            for key, child in item.items():
                _text(key, 100)
                visit(child, depth + 1)
        elif type(item) is list:
            for child in item:
                visit(child, depth + 1)
        elif type(item) is str:
            _text(item, 12000, multiline=True)
        elif type(item) is float:
            if not math.isfinite(item):
                raise AthenaAllergyError("response_invalid")
        elif item is not None and type(item) not in (bool, int):
            raise AthenaAllergyError("response_invalid")

    visit(value)


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise AthenaAllergyError("response_invalid")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw,
            object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
        _tree(value)
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise AthenaAllergyError("response_invalid") from None


def _object(value, allowed):
    if type(value) is not dict or set(value) - set(allowed):
        raise AthenaAllergyError("unsupported_record")
    return value


def _array(value, maximum):
    if type(value) is not list:
        raise AthenaAllergyError("response_invalid")
    if len(value) > maximum:
        raise AthenaAllergyError("too_many_results")
    return value


@dataclass(frozen=True, repr=False)
class AthenaAllergyScope:
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
                raise AthenaAllergyError("invalid_scope")
        for name in ("practice_id", "department_id", "patient_id"):
            _id(getattr(self, name))
        for value in (self.practice_label, self.department_label):
            if not _text(value, 200).strip():
                raise AthenaAllergyError("invalid_scope")
        _digest(self.authorization_sha256)
        if self.environment not in ORIGINS:
            raise AthenaAllergyError("invalid_scope")

    def commitment(self):
        return payload_hash(
            {
                "contract": "athena-allergy-patient-scope.v1",
                "origin": ORIGINS[self.environment],
                **{k: str(v) if type(v) is UUID else v for k, v in asdict(self).items()},
            }
        )


@dataclass(frozen=True, repr=False)
class AthenaAllergyPatient:
    patient_id: str
    identity_json: str
    identity_sha256: str


def patient_identity(value, scope):
    rows = _array(value, 1)
    if len(rows) != 1 or type(rows[0]) is not dict:
        raise AthenaAllergyError("patient_unavailable")
    raw = rows[0]
    if raw.get("patientid") != scope.patient_id:
        raise AthenaAllergyError("patient_changed")
    for key in ("firstname", "lastname"):
        if not _text(raw.get(key), 300).strip():
            raise AthenaAllergyError("patient_unavailable")
    keys = (
        "patientid",
        "firstname",
        "middlename",
        "lastname",
        "dob",
        "status",
        "deceaseddate",
        "departmentid",
        "primarydepartmentid",
    )
    identity = {key: raw[key] for key in keys if key in raw}
    for key, value in identity.items():
        _text(value, 300)
        if key == "dob" and value:
            try:
                if not re.fullmatch(r"[0-9]{2}/[0-9]{2}/[0-9]{4}", value):
                    raise ValueError
                datetime.strptime(value, "%m/%d/%Y")
            except ValueError:
                raise AthenaAllergyError("response_invalid") from None
    # The returned department is a registration/current department, not chart authorization.
    return AthenaAllergyPatient(scope.patient_id, canonical_json(identity), payload_hash(identity))


@dataclass(frozen=True, repr=False)
class AthenaAllergyRecord:
    record_id: str
    allergen_name: str
    original_json: str


SECTION_KEYS = {
    "allergies",
    "nkda",
    "sectionnote",
    "lastmodifiedby",
    "lastmodifieddatetime",
    "lastupdated",
    "notelastmodifiedby",
    "notelastmodifieddatetime",
}
RECORD_KEYS = {
    "id",
    "allergenid",
    "allergenname",
    "categories",
    "criticality",
    "deactivatedate",
    "deactivateduser",
    "lastmodifiedby",
    "lastmodifieddatetime",
    "note",
    "onsetdate",
    "reactions",
}
REACTION_KEYS = {"reactionname", "severity", "severitysnomedcode", "snomedcode"}


def allergy_records(value):
    value = _object(value, SECTION_KEYS)
    records = _array(value.get("allergies"), MAX_RECORDS)
    if "nkda" in value and type(value["nkda"]) is not bool:
        raise AthenaAllergyError("response_invalid")
    for key in set(value) - {"allergies", "nkda"}:
        _text(value[key], 4000 if key == "sectionnote" else 300, multiline=key == "sectionnote")
    result, identifiers = [], set()
    for record in records:
        record = _object(record, RECORD_KEYS)
        identifier = _text(record.get("id"), 80)
        name = _text(record.get("allergenname"), 1000)
        if not identifier.strip() or identifier in identifiers or not name.strip():
            raise AthenaAllergyError("response_invalid")
        identifiers.add(identifier)
        for key in set(record) - {"allergenid", "categories", "reactions"}:
            _text(record[key], 4000 if key == "note" else 1000, multiline=key == "note")
        if "allergenid" in record and (
            type(record["allergenid"]) is not int or not 1 <= record["allergenid"] <= 2**63 - 1
        ):
            raise AthenaAllergyError("response_invalid")
        if "categories" in record:
            for category in _array(record["categories"], 20):
                _text(category, 100)
        if "reactions" in record:
            for reaction in _array(record["reactions"], 25):
                reaction = _object(reaction, REACTION_KEYS)
                for key, item in reaction.items():
                    if key in ("snomedcode", "severitysnomedcode"):
                        if type(item) is not int or not 0 <= item <= 2**63 - 1:
                            raise AthenaAllergyError("response_invalid")
                    else:
                        _text(item, 1000)
        result.append(AthenaAllergyRecord(identifier, name, canonical_json(record)))
    return tuple(result)


@dataclass(frozen=True, repr=False)
class AthenaAllergyObservation:
    scope: AthenaAllergyScope
    patient: AthenaAllergyPatient
    observed_at: datetime
    records: tuple[AthenaAllergyRecord, ...]
    section_json: str
    provider_sources: tuple[str, str]
    source_sha256: str
    coverage: Literal["returned_section_only"] = "returned_section_only"
    includes_inactive: Literal[True] = True


def observation_hash(value):
    return payload_hash(
        {
            "contract": "athena-allergy-observation.v1",
            "scope_sha256": value.scope.commitment(),
            "patient": asdict(value.patient),
            "observed_at": value.observed_at.isoformat(),
            "section_json": value.section_json,
            "provider_sources": list(value.provider_sources),
            "coverage": value.coverage,
            "includes_inactive": value.includes_inactive,
        }
    )


class AthenaAllergyReader:
    def __init__(
        self,
        scope: AthenaAllergyScope,
        transport: httpx.MockTransport,
        *,
        expected_identity_sha256: str,
        enabled: Callable[[], bool],
        authorize: Callable[[AthenaAllergyScope], bool],
    ):
        if type(scope) is not AthenaAllergyScope or type(transport) is not httpx.MockTransport:
            raise AthenaAllergyError("synthetic_transport_required")
        self.scope, self.transport = scope, transport
        self.expected_identity_sha256 = _digest(expected_identity_sha256)
        self.enabled, self.authorize = enabled, authorize

    def _current(self):
        if not self.enabled():
            raise AthenaAllergyError("disabled")
        if self.authorize(self.scope) is not True:
            raise AthenaAllergyError("access_denied")

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
                    raise AthenaAllergyError("rate_limited")
                if response.status_code in (401, 403):
                    raise AthenaAllergyError("access_denied")
                if response.status_code != 200:
                    raise AthenaAllergyError("provider_unavailable")
                if (
                    response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    != "application/json"
                    or response.headers.get("content-encoding", "identity").lower() != "identity"
                ):
                    raise AthenaAllergyError("response_invalid")
                raw = bytearray()
                for part in response.iter_raw():
                    if len(raw) + len(part) > MAX_BYTES:
                        raise AthenaAllergyError("response_too_large")
                    raw.extend(part)
            self._current()
            return _json(bytes(raw)), hashlib.sha256(raw).hexdigest()
        except httpx.HTTPError:
            raise AthenaAllergyError("provider_unavailable") from None

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
                raise AthenaAllergyError("patient_changed")
            section, clinical_proof = self._get(
                client,
                f"/v1/{scope.practice_id}/chart/{scope.patient_id}/allergies",
                {"departmentid": scope.department_id, "showinactive": "true"},
            )
            records = allergy_records(section)
            observed = AthenaAllergyObservation(
                scope,
                patient,
                datetime.now(UTC),
                records,
                canonical_json(section),
                (identity_proof, clinical_proof),
                "",
            )
            self._current()
            return AthenaAllergyObservation(
                scope,
                patient,
                observed.observed_at,
                records,
                observed.section_json,
                observed.provider_sources,
                observation_hash(observed),
            )
