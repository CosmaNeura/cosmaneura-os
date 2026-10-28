"""Clinical meaning, original representation and exact whole-packet size boundaries."""

import hashlib
import json
from dataclasses import replace
from uuid import UUID

import pytest
from tests.unit.test_elation_lab_read import REPORT, Harness

from cosmas_os.adapters.elation_lab_read import ElationLabError, observation_hash
from cosmas_os.application.elation_lab_snapshot import prepare_lab_review, source_text
from cosmas_os.domain.hashing import canonical_json, payload_hash


def prepare(value, **changes):
    arguments = dict(
        expected_scope=value.scope,
        expected_source_sha256=value.source_sha256,
        expected_candidates_sha256=value.parent_candidates_sha256,
        expected_report_id=value.report_id,
        authorize_read=lambda _: True,
    )
    return prepare_lab_review(value, **(arguments | changes))


def rehashed(value, report):
    value = replace(
        value,
        report_json=canonical_json(report),
        report_sha256=payload_hash(report),
        changed_since_selection=payload_hash(report) != value.selected_report_sha256,
    )
    return replace(value, source_sha256=observation_hash(value))


def test_full_source_preserves_literal_values_flags_corrections_dates_and_unfetched_reference_metadata():
    value = Harness().read()
    review = prepare(value)
    assert value.report_json in review.source_content
    report = json.loads(value.report_json)
    result = report["grids"][0]["results"][0]
    assert (
        result["value"] == "001.2300"
        and result["value_type"] == "Numeric"
        and result["units"] == "µg/L"
    )
    assert result["reference_min"] == "< 0.10" and result["reference_max"] == "≤ 3.00"
    assert result["is_abnormal"] is False and result["abnormal_flag"] == "Alert high"
    assert result["status"] == "CORRECTED" and report["grids"][0]["status"] == "AMENDED"
    assert result["note"] == "Première ligne\r\n\tOriginal second line"
    assert (
        report["document_date"] == "2026-10-24T09:00:00-04:00"
        and report["grids"][0]["collected_date"] == "2026-10-24T08:00:00"
    )
    assert report["reported_date"] is None and report["signed_date"] is None
    assert (
        "not fetched" in review.source_content
        and "correction history is not established" in review.source_content
    )
    assert "123456789012345678" in review.source_content
    assert (
        hashlib.sha256(review.source_content.encode()).hexdigest() == review.source_content_sha256
    )
    assert value.scope.authorization_sha256 not in review.source_content and "Alex" not in repr(
        review
    )


@pytest.mark.parametrize("grids", ["absent", "empty", "no_results"])
def test_missing_and_empty_structured_results_have_distinct_explicit_limits(grids):
    h = Harness()
    if grids == "absent":
        h.report.pop("grids")
    elif grids == "empty":
        h.report["grids"] = []
    else:
        h.report["grids"][0]["results"] = []
    review = prepare(h.read())
    expected = {
        "absent": "Structured result grids were not provided.",
        "empty": "No structured result grids were returned.",
        "no_results": "The returned grids contain no result rows.",
    }[grids]
    assert expected in review.warnings and expected in review.source_content


def test_absent_null_and_recorded_blank_fields_are_not_interchanged():
    h = Harness()
    r = h.report["grids"][0]["results"][0]
    r.pop("units")
    r["value_type"] = None
    r["reference_min"] = ""
    r["text"] = ""
    value = h.read()
    review = prepare(value)
    raw = json.loads(value.report_json)["grids"][0]["results"][0]
    assert (
        "units" not in raw
        and raw["value_type"] is None
        and raw["reference_min"] == ""
        and raw["text"] == ""
    )
    assert value.report_json in review.source_content


def test_corrected_fresh_report_requires_human_review_of_fresh_values_without_hiding_change():
    h = Harness()
    page = h.reader.list_reports()
    h.report["grids"][0]["results"][0]["value"] = "<0.10"
    review = prepare(h.read(page))
    assert review.observation.changed_since_selection is True
    assert "Report fields changed after the candidate list was loaded" in review.source_content


@pytest.mark.parametrize("change", ["scope", "source", "parent", "report"])
def test_changed_expected_authority_or_exact_selection_withholds_entire_review(change):
    value = Harness().read()
    overrides = {
        "scope": {"expected_scope": replace(value.scope, workspace_id=UUID(int=99))},
        "source": {"expected_source_sha256": "b" * 64},
        "parent": {"expected_candidates_sha256": "b" * 64},
        "report": {"expected_report_id": REPORT["id"] + 1},
    }
    with pytest.raises(ElationLabError):
        prepare(value, **overrides[change])


def test_revocation_during_format_withholds_entire_model():
    value = Harness().read()
    calls = []

    def authorize(_):
        calls.append(True)
        return len(calls) == 1

    with pytest.raises(ElationLabError, match="access_denied"):
        prepare(value, authorize_read=authorize)
    assert len(calls) == 2


def test_whole_source_accepts_exact_5000_unicode_codepoints_and_refuses_5001_without_truncation():
    value = Harness().read()
    report = json.loads(value.report_json)
    report["grids"][0]["note"] = ""
    # Mark the fresh report changed first, so the fixed warning is included in both boundaries.
    value = rehashed(value, report)
    needed = 5000 - len(source_text(value))
    assert 0 < needed <= 4000
    report["grids"][0]["note"] = "x" * needed
    exact = rehashed(value, report)
    review = prepare(exact)
    assert len(review.source_content) == 5000 and len(review.source_content.encode()) > 5000
    report["grids"][0]["note"] += "x"
    oversized = rehashed(value, report)
    assert len(source_text(oversized)) == 5001
    with pytest.raises(ElationLabError, match="source_too_large"):
        prepare(oversized)


def test_even_rehashed_packet_cannot_hide_change_flag_or_invent_optional_status():
    value = Harness().read()
    report = json.loads(value.report_json)
    report["signed_date"] = "2026-10-26T10:00:00Z"
    changed = rehashed(value, report)
    forged = replace(changed, changed_since_selection=False)
    forged = replace(forged, source_sha256=observation_hash(forged))
    with pytest.raises(ElationLabError, match="invalid_proof"):
        prepare(forged)
