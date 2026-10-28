"""Invented reports exercise patient proof, literal lab values and bounded selection."""

import json
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from typing import cast
from uuid import UUID

import httpx
import pytest

from cosmas_os.adapters.elation_lab_read import (
    ElationLabError,
    ElationLabReader,
    ElationLabScope,
    page_hash,
    patient_identity,
)
from cosmas_os.adapters.elation_read import ElationReadScope

PATIENT = {
    "id": 903,
    "caregiver_practice": 901,
    "primary_physician": 902,
    "first_name": "Alex",
    "last_name": "Éxample",
    "dob": "1980-01-02",
    "deleted_date": None,
}
CONNECTION = ElationReadScope(
    UUID(int=1), UUID(int=2), UUID(int=3), UUID(int=4), 901, "Invented Clinic 🧪"
)
SCOPE = ElationLabScope(
    CONNECTION,
    UUID(int=5),
    UUID(int=6),
    UUID(int=7),
    903,
    "a" * 64,
    patient_identity(PATIENT, 903, 901).identity_sha256,
)
RESULT = {
    "test": {"code": "INVENTED", "loinc": None, "name": "Invented analyte"},
    "test_category": {"description": "Invented panel", "value": "SYNTH"},
    "value": "001.2300",
    "units": "µg/L",
    "value_type": "Numeric",
    "reference_min": "< 0.10",
    "reference_max": "≤ 3.00",
    "abnormal_flag": "Alert high",
    "is_abnormal": False,
    "status": "CORRECTED",
    "note": "Première ligne\r\n\tOriginal second line",
    "text": None,
}
REPORT = {
    "id": 123456789012345678,
    "patient": 903,
    "practice": 901,
    "physician": 902,
    "report_type": "Lab",
    "chart_date": "2026-10-25T12:00:00Z",
    "document_date": "2026-10-24T09:00:00-04:00",
    "reported_date": None,
    "custom_title": "Invented corrected panel",
    "created_date": "2026-10-25T12:00:00.120000Z",
    "signed_date": None,
    "deleted_date": None,
    "is_urgent": False,
    "order_status": "COMPLETED",
    "grids": [
        {
            "accession_number": "Invented A",
            "collected_date": "2026-10-24T08:00:00",
            "resulted_date": "2026-10-25T11:00:00Z",
            "status": "AMENDED",
            "note": "Original grid note",
            "results": [RESULT],
        }
    ],
    "files": [
        {
            "id": 7,
            "document": "https://invented.invalid/original.pdf",
            "content_type": "application/pdf",
        }
    ],
    "images": [],
    "printable_view": "https://invented.invalid/printable",
    "tags": [8],
    "vendor": None,
}


class Harness:
    def __init__(self):
        self.patient, self.report = deepcopy(PATIENT), deepcopy(REPORT)
        self.other = dict(deepcopy(REPORT), id=29, report_type="Imaging")
        self.enabled, self.authorized, self.changed = True, True, False
        self.calls = []
        self.after = lambda: None
        self.page_extra = {"next": None, "previous": None, "count": 2}
        self.raw = None
        self.status = 200
        self.transport = httpx.MockTransport(self.send)
        self.reader = ElationLabReader(
            SCOPE, self.transport, enabled=lambda: self.enabled, authorize=lambda _: self.authorized
        )

    def send(self, request):
        self.calls.append(request)
        self.after()
        if request.url.path == "/api/2.0/patients/903/":
            body = self.patient
        elif request.url.path == "/api/2.0/reports/":
            body = {"results": [self.report, self.other], **self.page_extra}
        else:
            assert request.url.path == f"/api/2.0/reports/{REPORT['id']}/"
            body = self.report
        raw = self.raw if self.raw is not None else json.dumps(body).encode()
        return httpx.Response(
            self.status, headers={"Content-Type": "application/json"}, stream=httpx.ByteStream(raw)
        )

    def read(self, page=None):
        page = page or self.reader.list_reports()
        return self.reader.read_report(
            page, REPORT["id"], expected_candidates_sha256=page.source_sha256
        )


def test_exact_patient_practice_requests_one_report_page_then_fresh_selected_report():
    h = Harness()
    page = h.reader.list_reports()
    assert (
        page.returned_report_count == 2
        and page.other_report_count == 1
        and len(page.candidates) == 1
    )
    assert page.coverage == "returned_page_only" and page.reported_total == 2
    value = h.read(page)
    assert [str(r.url) for r in h.calls] == [
        "https://sandbox.elationemr.com/api/2.0/patients/903/",
        "https://sandbox.elationemr.com/api/2.0/reports/?patient=903&practice=901&limit=25&order_by=-document_date",
        "https://sandbox.elationemr.com/api/2.0/patients/903/",
        f"https://sandbox.elationemr.com/api/2.0/reports/{REPORT['id']}/",
    ]
    assert all(r.method == "GET" and "report_type" not in r.url.params for r in h.calls)
    assert json.loads(value.report_json) == REPORT and value.changed_since_selection is False
    assert "Alex" not in repr(value) and "invented-elation-lab-token" not in value.report_json


def test_fresh_correction_preserves_new_originals_and_marks_change_without_reconciling():
    h = Harness()
    page = h.reader.list_reports()
    h.report["grids"][0]["results"][0]["value"] = "<0.1000"
    h.report["grids"][0]["results"][0]["status"] = "DELETED"
    value = h.read(page)
    assert (
        value.changed_since_selection
        and json.loads(value.report_json)["grids"][0]["results"][0]["value"] == "<0.1000"
    )
    assert value.selected_report_sha256 == page.candidates[0].report_sha256


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", 904),
        ("caregiver_practice", 902),
        ("dob", "1981-01-02"),
        ("deleted_date", "2026-10-24T12:00:00Z"),
    ],
)
def test_changed_patient_stops_before_clinical_list_or_detail(field, value):
    h = Harness()
    page = h.reader.list_reports()
    h.patient[field] = value
    with pytest.raises(ElationLabError):
        h.read(page)
    assert len(h.calls) == 3


@pytest.mark.parametrize("target", ["enabled", "authorized"])
def test_authority_withdrawal_after_patient_response_prevents_clinical_get(target):
    h = Harness()
    h.after = lambda: setattr(h, target, False)
    with pytest.raises(ElationLabError, match="access_denied"):
        h.reader.list_reports()
    assert len(h.calls) == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "patient",
        "practice",
        "not_lab",
        "unknown_qualifier",
        "numeric_value",
        "bad_units",
        "null_status",
        "attachment_bytes",
    ],
)
def test_entire_report_refused_on_binding_or_unsupported_clinical_representation(mutation):
    h = Harness()
    page = h.reader.list_reports()
    result = h.report["grids"][0]["results"][0]
    if mutation in ("patient", "practice"):
        h.report[mutation] = 999
    elif mutation == "not_lab":
        h.report["report_type"] = "Imaging"
    elif mutation == "unknown_qualifier":
        result["method_interpretation"] = "Unqualified semantic field"
    elif mutation == "numeric_value":
        result["value"] = 1
    elif mutation == "bad_units":
        result["units"] = "x" * 21
    elif mutation == "null_status":
        result["status"] = None
    else:
        h.report["files"][0]["base64_content"] = "invented-encoded-bytes"
    with pytest.raises(ElationLabError):
        h.read(page)
    assert len(h.calls) == 4


@pytest.mark.parametrize(
    "next_value",
    [
        "https://evil.invalid/reports/?cursor=a",
        "https://sandbox.elationemr.com/api/2.0/reports/?patient=904&cursor=a",
        "https://sandbox.elationemr.com/api/2.0/reports/?cursor=a&cursor=b",
    ],
)
def test_untrusted_continuation_refused_without_following(next_value):
    h = Harness()
    h.page_extra = {"next": next_value, "count": 3}
    with pytest.raises(ElationLabError):
        h.reader.list_reports()
    assert len(h.calls) == 2


def test_next_page_is_disclosed_and_never_followed_and_absent_count_stays_unknown():
    h = Harness()
    h.page_extra = {
        "next": "https://sandbox.elationemr.com/api/2.0/reports/?patient=903&practice=901&cursor=opaque"
    }
    p = h.reader.list_reports()
    assert p.coverage == "more_rows_available" and p.reported_total is None and len(h.calls) == 2
    h.page_extra = {}
    p = h.reader.list_reports()
    assert p.coverage == "continuation_unknown" and p.reported_total is None


@pytest.mark.parametrize("change", ["hash", "selected", "scope", "expired"])
def test_client_substitution_or_expired_selection_never_issues_detail_request(change):
    h = Harness()
    p = h.reader.list_reports()
    identifier = REPORT["id"]
    expected = p.source_sha256
    if change == "hash":
        expected = "b" * 64
    elif change == "selected":
        identifier = 29
    elif change == "scope":
        p = replace(p, scope=replace(SCOPE, workspace_id=UUID(int=99)))
    else:
        p = replace(p, observed_at=p.observed_at - timedelta(minutes=31))
        p = replace(p, source_sha256=page_hash(p))
        expected = p.source_sha256
    with pytest.raises(ElationLabError):
        h.reader.read_report(p, identifier, expected_candidates_sha256=expected)
    assert len(h.calls) == 2


@pytest.mark.parametrize("raw", [b'{"id":903,"id":904}', b'{"id":NaN}', b"x" * 65537])
def test_duplicate_invalid_or_oversized_patient_json_is_refused(raw):
    h = Harness()
    h.raw = raw
    with pytest.raises(ElationLabError):
        h.reader.list_reports()
    assert len(h.calls) == 1


def test_real_or_subclassed_transport_is_rejected_before_any_request():
    h = Harness()

    class Other(httpx.MockTransport):
        pass

    for t in (httpx.HTTPTransport(), Other(h.send)):
        try:
            with pytest.raises(ElationLabError, match="synthetic_transport_required"):
                ElationLabReader(
                    SCOPE,
                    cast(httpx.MockTransport, t),
                    enabled=lambda: True,
                    authorize=lambda _: True,
                )
        finally:
            t.close()
    assert not h.calls
