"""Bounded, synthetic-only Elation report selection and fresh laboratory reads.

Official contract: help.elationhealth.com/articles/rest/patient-document-api/reports/list-reports
No credentials, OAuth exchange, live transport, attachments or automatic pagination.
"""

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID

import httpx

from cosmas_os.adapters.elation_read import ORIGIN, SCOPES, ElationReadScope
from cosmas_os.domain.hashing import canonical_json, payload_hash

LAB_SCOPES = SCOPES + " system/reports.read"
MAX_ID = 9_223_372_036_854_775_807
PAGE_SIZE = 25
REPORT_KEYS = frozenset(
    "id chart_date document_date patient physician practice report_type created_date custom_title deleted_date files grids images is_urgent order_status printable_view reported_date requisition_number routed_document_delegates signed_by signed_date tags vendor".split()
)
HEADER_KEYS = REPORT_KEYS - {
    "files",
    "grids",
    "images",
    "routed_document_delegates",
    "tags",
    "printable_view",
}
RESULT_KEYS = frozenset(
    "abnormal_flag is_abnormal note reference_max reference_min status test test_category text units value value_type".split()
)


class ElationLabError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def text(value, maximum=1000, *, nullable=False, multiline=False, nonblank=False):
    if value is None and nullable:
        return
    if (
        type(value) is not str
        or len(value) > maximum
        or nonblank
        and not value.strip()
        or any(
            ord(c) == 127
            or 0xD800 <= ord(c) <= 0xDFFF
            or ord(c) < 32
            and not (multiline and c in "\r\n\t")
            for c in value
        )
    ):
        raise ElationLabError("response_invalid")


def identifier(value):
    if type(value) is not int or not 0 < value <= MAX_ID:
        raise ElationLabError("invalid_scope")


def digest(value):
    if type(value) is not str or re.fullmatch(r"[a-f0-9]{64}", value) is None:
        raise ElationLabError("invalid_proof")


def timestamp(value, *, nullable=False):
    if value is None and nullable:
        return
    if (
        type(value) is not str
        or re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)?",
            value,
        )
        is None
    ):
        raise ElationLabError("response_invalid")
    try:
        datetime.fromisoformat(value)
    except ValueError:
        raise ElationLabError("response_invalid") from None


def closed(value, required, allowed):
    if type(value) is not dict or not set(required) <= set(value) <= set(allowed):
        raise ElationLabError("unsupported_fields")


def array(value, maximum):
    if type(value) is not list or len(value) > maximum:
        raise ElationLabError("response_too_large")


def parse_json(raw):
    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result:
                raise ElationLabError("response_invalid")
            result[key] = value
        return result

    def invalid(_):
        raise ElationLabError("response_invalid")

    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
        count = 0

        def visit(item, depth=0):
            nonlocal count
            count += 1
            if depth > 20 or count > 50000:
                raise ElationLabError("response_too_large")
            if type(item) is dict:
                for key, child in item.items():
                    text(key, 100)
                    visit(child, depth + 1)
            elif type(item) is list:
                for child in item:
                    visit(child, depth + 1)
            elif type(item) is str:
                text(item, 65536, multiline=True)
            elif type(item) is float or item is not None and type(item) not in (bool, int):
                # Laboratory values are strings. No numeric representation is coerced.
                raise ElationLabError("unsupported_number")

        visit(value)
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ElationLabError("response_invalid") from None


@dataclass(frozen=True, repr=False)
class ElationLabScope:
    connection_scope: ElationReadScope
    account_id: UUID
    workspace_id: UUID
    patient_link_id: UUID
    patient_id: int
    authorization_sha256: str
    patient_identity_sha256: str

    def __post_init__(self):
        c = self.connection_scope
        if (
            type(c) is not ElationReadScope
            or c.environment != "sandbox"
            or any(
                type(v) is not UUID
                for v in (
                    c.box_id,
                    c.owner_id,
                    c.connection_id,
                    c.credential_generation,
                    self.account_id,
                    self.workspace_id,
                    self.patient_link_id,
                )
            )
        ):
            raise ElationLabError("invalid_scope")
        identifier(c.practice_id)
        identifier(self.patient_id)
        text(c.practice_name, 200, nonblank=True)
        digest(self.authorization_sha256)
        digest(self.patient_identity_sha256)

    def commitment(self):
        return payload_hash(
            {
                "contract": "elation-lab-patient-scope.v1",
                "connection_scope_sha256": self.connection_scope.commitment(),
                "account_id": str(self.account_id),
                "workspace_id": str(self.workspace_id),
                "patient_link_id": str(self.patient_link_id),
                "patient_id": self.patient_id,
                "authorization_sha256": self.authorization_sha256,
                "patient_identity_sha256": self.patient_identity_sha256,
            }
        )


@dataclass(frozen=True, repr=False)
class ElationLabPatient:
    identity_json: str
    identity_sha256: str


def patient_identity(row, patient_id, practice_id):
    if (
        type(row) is not dict
        or row.get("id") != patient_id
        or row.get("caregiver_practice") != practice_id
        or "deleted_date" not in row
    ):
        raise ElationLabError("patient_changed")
    for key in ("id", "caregiver_practice", "primary_physician"):
        identifier(row.get(key))
    for key in ("first_name", "last_name"):
        text(row.get(key), 70, nonblank=True)
    dob = row.get("dob")
    if type(dob) is not str or re.fullmatch(r"\d{4}-\d{2}-\d{2}", dob) is None:
        raise ElationLabError("response_invalid")
    try:
        date.fromisoformat(dob)
    except ValueError:
        raise ElationLabError("response_invalid") from None
    if row["deleted_date"] is not None:
        raise ElationLabError("record_unavailable")
    identity = {
        key: row[key]
        for key in (
            "id",
            "caregiver_practice",
            "primary_physician",
            "first_name",
            "last_name",
            "dob",
            "deleted_date",
        )
    }
    return ElationLabPatient(canonical_json(identity), payload_hash(identity))


def report_header(row, scope):
    if type(row) is not dict:
        raise ElationLabError("response_invalid")
    for key in ("id", "patient", "practice", "physician"):
        identifier(row.get(key))
    if row["patient"] != scope.patient_id or row["practice"] != scope.connection_scope.practice_id:
        raise ElationLabError("patient_changed")
    text(row.get("report_type"), 100, nonblank=True)
    for key in ("chart_date", "document_date"):
        timestamp(row.get(key))
    for key in ("created_date", "deleted_date", "signed_date", "reported_date"):
        if key in row:
            timestamp(row[key], nullable=True)
    for key, limit in (("custom_title", 255), ("requisition_number", 100), ("order_status", 100)):
        if key in row:
            text(row[key], limit, nullable=True)
    for key in ("signed_by", "vendor"):
        if key in row and row[key] is not None:
            identifier(row[key])
    if "is_urgent" in row and type(row["is_urgent"]) is not bool:
        raise ElationLabError("response_invalid")
    return {key: row[key] for key in HEADER_KEYS if key in row}


def validate_report(row, scope, report_id):
    closed(
        row,
        ("id", "chart_date", "document_date", "patient", "physician", "practice", "report_type"),
        REPORT_KEYS,
    )
    report_header(row, scope)
    if row["id"] != report_id or row["report_type"] != "Lab":
        raise ElationLabError("record_unavailable")
    if "grids" in row:
        array(row["grids"], 10)
        for grid in row["grids"]:
            closed(
                grid,
                (
                    "accession_number",
                    "collected_date",
                    "note",
                    "resulted_date",
                    "results",
                    "status",
                ),
                (
                    "accession_number",
                    "collected_date",
                    "note",
                    "resulted_date",
                    "results",
                    "status",
                ),
            )
            text(grid["accession_number"], 300)
            text(grid["status"], 100, nonblank=True)
            text(grid["note"], 4000, nullable=True, multiline=True)
            timestamp(grid["collected_date"])
            timestamp(grid["resulted_date"])
            array(grid["results"], 100)
            for result in grid["results"]:
                closed(result, RESULT_KEYS - {"units", "value_type"}, RESULT_KEYS)
                text(result["value"], 500, multiline=True)
                text(result["abnormal_flag"], 200, nonblank=True)
                text(result["status"], 100, nonblank=True)
                if type(result["is_abnormal"]) is not bool:
                    raise ElationLabError("response_invalid")
                for key in ("note", "text", "reference_min", "reference_max"):
                    text(result[key], 4000, nullable=True, multiline=True)
                if "units" in result:
                    text(result["units"], 20, nullable=True)
                if "value_type" in result:
                    text(result["value_type"], 100, nullable=True)
                closed(result["test"], ("code", "loinc", "name"), ("code", "loinc", "name"))
                text(result["test"]["code"], 50)
                text(result["test"]["loinc"], 300, nullable=True)
                text(result["test"]["name"], 255, nonblank=True)
                closed(result["test_category"], ("description", "value"), ("description", "value"))
                text(result["test_category"]["description"], 200)
                text(result["test_category"]["value"], 50)
    for key in ("files", "images", "routed_document_delegates", "tags"):
        if key not in row or row[key] is None and key in ("files", "images"):
            continue
        array(row[key], 25)
        for item in row[key]:
            if key == "tags":
                identifier(item)
                continue
            allowed = (
                {
                    "base64_content",
                    "content_type",
                    "document",
                    "external_content",
                    "id",
                    "original_filename",
                }
                if key == "files"
                else {"id", "document"}
                if key == "images"
                else {"id", "user", "group", "created_date", "deleted_date"}
            )
            closed(item, (), allowed)
            if item.get("base64_content") not in (None, ""):
                raise ElationLabError("unsupported_embedded_content")
            for k, v in item.items():
                if k in ("id", "user", "group") and v is not None:
                    identifier(v)
                elif k.endswith("_date"):
                    timestamp(v, nullable=True)
                elif k != "external_content":
                    text(v, 2048, nullable=k in ("id", "user", "group"))
    if "printable_view" in row:
        text(row["printable_view"], 2048)
    return canonical_json(row)


@dataclass(frozen=True, repr=False)
class ElationReportCandidate:
    report_id: int
    metadata_json: str
    report_sha256: str


@dataclass(frozen=True, repr=False)
class ElationReportPage:
    scope: ElationLabScope
    patient: ElationLabPatient
    observed_at: datetime
    candidates: tuple[ElationReportCandidate, ...]
    returned_report_count: int
    other_report_count: int
    reported_total: int | None
    coverage: str
    provider_sources: tuple[str, str]
    source_sha256: str


def page_hash(value):
    return payload_hash(
        {
            "contract": "elation-lab-candidates.v1",
            "scope_sha256": value.scope.commitment(),
            "patient": asdict(value.patient),
            "observed_at": value.observed_at.isoformat(),
            "candidates": [asdict(c) for c in value.candidates],
            "returned_report_count": value.returned_report_count,
            "other_report_count": value.other_report_count,
            "reported_total": value.reported_total,
            "coverage": value.coverage,
            "provider_sources": list(value.provider_sources),
        }
    )


def validate_page(value, scope, expected_sha256):
    if (
        type(value) is not ElationReportPage
        or value.scope != scope
        or value.source_sha256 != expected_sha256
        or page_hash(value) != expected_sha256
    ):
        raise ElationLabError("invalid_proof")
    if (
        type(value.candidates) is not tuple
        or len(value.candidates) > PAGE_SIZE
        or value.observed_at.utcoffset() is None
        or value.returned_report_count != len(value.candidates) + value.other_report_count
        or type(value.returned_report_count) is not int
        or type(value.other_report_count) is not int
        or not 0 <= value.other_report_count <= PAGE_SIZE
        or not 0 <= value.returned_report_count <= PAGE_SIZE
        or value.coverage
        not in ("returned_page_only", "more_rows_available", "continuation_unknown")
        or value.reported_total is not None
        and (
            type(value.reported_total) is not int
            or not value.returned_report_count <= value.reported_total <= MAX_ID
        )
    ):
        raise ElationLabError("invalid_proof")
    if (
        type(value.provider_sources) is not tuple
        or len(value.provider_sources) != 2
        or len({c.report_id for c in value.candidates}) != len(value.candidates)
    ):
        raise ElationLabError("invalid_proof")
    for proof in value.provider_sources:
        digest(proof)
    patient = patient_identity(
        parse_json(value.patient.identity_json),
        scope.patient_id,
        scope.connection_scope.practice_id,
    )
    if patient != value.patient or patient.identity_sha256 != scope.patient_identity_sha256:
        raise ElationLabError("patient_changed")
    for candidate in value.candidates:
        if type(candidate) is not ElationReportCandidate:
            raise ElationLabError("invalid_proof")
        identifier(candidate.report_id)
        metadata = parse_json(candidate.metadata_json)
        if (
            report_header(metadata, scope) != metadata
            or canonical_json(metadata) != candidate.metadata_json
            or metadata["id"] != candidate.report_id
            or metadata["report_type"] != "Lab"
        ):
            raise ElationLabError("invalid_proof")
        digest(candidate.report_sha256)


@dataclass(frozen=True, repr=False)
class ElationLabObservation:
    scope: ElationLabScope
    patient: ElationLabPatient
    observed_at: datetime
    report_id: int
    report_json: str
    report_sha256: str
    parent_candidates_sha256: str
    selected_report_sha256: str
    changed_since_selection: bool
    provider_sources: tuple[str, str]
    source_sha256: str


def observation_hash(value):
    return payload_hash(
        {
            "contract": "elation-lab-report.v1",
            "scope_sha256": value.scope.commitment(),
            "patient": asdict(value.patient),
            "observed_at": value.observed_at.isoformat(),
            "report_id": value.report_id,
            "report_json": value.report_json,
            "report_sha256": value.report_sha256,
            "parent_candidates_sha256": value.parent_candidates_sha256,
            "selected_report_sha256": value.selected_report_sha256,
            "changed_since_selection": value.changed_since_selection,
            "provider_sources": list(value.provider_sources),
        }
    )


class ElationLabReader:
    def __init__(
        self,
        scope: ElationLabScope,
        transport: httpx.MockTransport,
        *,
        enabled: Callable[[], bool],
        authorize: Callable[[ElationLabScope], bool],
    ):
        if (
            type(scope) is not ElationLabScope
            or type(transport) is not httpx.MockTransport
            or not callable(enabled)
            or not callable(authorize)
        ):
            raise ElationLabError("synthetic_transport_required")
        self.scope, self.transport, self.enabled, self.authorize = (
            scope,
            transport,
            enabled,
            authorize,
        )

    def _current(self):
        if self.enabled() is not True or self.authorize(self.scope) is not True:
            raise ElationLabError("access_denied")

    def _get(self, client, path, parameters, maximum=1048576):
        self._current()
        try:
            with client.stream(
                "GET",
                ORIGIN + path,
                params=parameters,
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "identity",
                    "Authorization": "Bearer invented-elation-lab-token",
                },
            ) as response:
                if response.status_code != 200:
                    raise ElationLabError(
                        "rate_limited"
                        if response.status_code == 429
                        else "access_denied"
                        if response.status_code in (401, 403)
                        else "provider_unavailable"
                    )
                if (
                    response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    != "application/json"
                    or response.headers.get("content-encoding", "identity").lower() != "identity"
                ):
                    raise ElationLabError("response_invalid")
                raw = bytearray()
                for part in response.iter_raw():
                    if len(raw) + len(part) > maximum:
                        raise ElationLabError("response_too_large")
                    raw.extend(part)
            self._current()
            return parse_json(bytes(raw)), hashlib.sha256(raw).hexdigest()
        except httpx.HTTPError:
            raise ElationLabError("provider_unavailable") from None

    def _patient(self, client):
        row, proof = self._get(client, f"/api/2.0/patients/{self.scope.patient_id}/", {}, 65536)
        patient = patient_identity(
            row, self.scope.patient_id, self.scope.connection_scope.practice_id
        )
        if patient.identity_sha256 != self.scope.patient_identity_sha256:
            raise ElationLabError("patient_changed")
        return patient, proof

    def list_reports(self):
        self._current()
        with httpx.Client(
            transport=self.transport, follow_redirects=False, trust_env=False, timeout=15
        ) as client:
            patient, patient_proof = self._patient(client)
            raw, report_proof = self._get(
                client,
                "/api/2.0/reports/",
                {
                    "patient": str(self.scope.patient_id),
                    "practice": str(self.scope.connection_scope.practice_id),
                    "limit": str(PAGE_SIZE),
                    "order_by": "-document_date",
                },
            )
        closed(raw, ("results",), ("results", "next", "previous", "count"))
        array(raw["results"], PAGE_SIZE)
        if raw.get("previous") is not None:
            raise ElationLabError("response_invalid")
        count = raw.get("count")
        if "count" in raw and (
            type(count) is not int or not len(raw["results"]) <= count <= MAX_ID
        ):
            raise ElationLabError("response_invalid")
        coverage = "continuation_unknown" if "next" not in raw else "returned_page_only"
        if raw.get("next") is not None:
            text(raw["next"], 2048, nonblank=True)
            u = urlsplit(raw["next"])
            if (
                u.scheme != "https"
                or u.netloc != urlsplit(ORIGIN).netloc
                or u.path not in ("/api/2.0/reports/", "/api/2.0/reports")
                or u.fragment
            ):
                raise ElationLabError("response_invalid")
            query = parse_qsl(u.query, keep_blank_values=True)
            if len({key for key, _ in query}) != len(query) or len(query) > 8:
                raise ElationLabError("response_invalid")
            for key, val in query:
                expected = {
                    "patient": str(self.scope.patient_id),
                    "practice": str(self.scope.connection_scope.practice_id),
                    "limit": str(PAGE_SIZE),
                    "order_by": "-document_date",
                }
                if (
                    key not in {*expected, "cursor", "offset"}
                    or key in expected
                    and val != expected[key]
                    or key in ("cursor", "offset")
                    and not val
                ):
                    raise ElationLabError("response_invalid")
            coverage = "more_rows_available"
            if not raw["results"] or count is not None and count <= len(raw["results"]):
                raise ElationLabError("response_invalid")
        elif "next" in raw and count is not None and count > len(raw["results"]):
            raise ElationLabError("response_invalid")
        candidates, seen = [], set()
        for row in raw["results"]:
            header = report_header(row, self.scope)
            if row["id"] in seen:
                raise ElationLabError("response_invalid")
            seen.add(row["id"])
            if row["report_type"] == "Lab":
                candidates.append(
                    ElationReportCandidate(row["id"], canonical_json(header), payload_hash(row))
                )
        value = ElationReportPage(
            self.scope,
            patient,
            datetime.now(UTC),
            tuple(candidates),
            len(raw["results"]),
            len(raw["results"]) - len(candidates),
            count,
            coverage,
            (patient_proof, report_proof),
            "",
        )
        from dataclasses import replace

        value = replace(value, source_sha256=page_hash(value))
        validate_page(value, self.scope, value.source_sha256)
        self._current()
        return value

    def read_report(
        self, page: ElationReportPage, report_id: int, *, expected_candidates_sha256: str
    ):
        self._current()
        identifier(report_id)
        validate_page(page, self.scope, expected_candidates_sha256)
        if (
            not timedelta(seconds=-30)
            <= datetime.now(UTC) - page.observed_at
            <= timedelta(minutes=30)
        ):
            raise ElationLabError("selection_expired")
        selected = next((c for c in page.candidates if c.report_id == report_id), None)
        if selected is None:
            raise ElationLabError("record_unavailable")
        with httpx.Client(
            transport=self.transport, follow_redirects=False, trust_env=False, timeout=15
        ) as client:
            patient, patient_proof = self._patient(client)
            raw, report_proof = self._get(client, f"/api/2.0/reports/{report_id}/", {}, 65536)
        encoded = validate_report(raw, self.scope, report_id)
        current_sha256 = payload_hash(raw)
        value = ElationLabObservation(
            self.scope,
            patient,
            datetime.now(UTC),
            report_id,
            encoded,
            current_sha256,
            page.source_sha256,
            selected.report_sha256,
            current_sha256 != selected.report_sha256,
            (patient_proof, report_proof),
            "",
        )
        from dataclasses import replace

        value = replace(value, source_sha256=observation_hash(value))
        self._current()
        return value
