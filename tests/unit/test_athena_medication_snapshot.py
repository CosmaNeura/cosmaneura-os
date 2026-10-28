"""Whole-source fidelity, exact boundary and authority checks for medication review."""

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest
from tests.unit.test_athena_medication_read import Harness

from cosmas_os.adapters.athena_medication_read import (
    AthenaMedicationError,
    AthenaMedicationRecord,
    clinical_dumps,
    clinical_loads,
    medication_records,
    observation_hash,
)
from cosmas_os.application.athena_medication_snapshot import _source, prepare_medication_review


def observed():
    value = Harness().read()
    value = replace(value, observed_at=datetime(2026, 10, 26, 12, 34, 56, 123456, tzinfo=UTC))
    return replace(value, source_sha256=observation_hash(value))


def changed(value, section):
    item = replace(value, section_json=clinical_dumps(section), groups=medication_records(section))
    return replace(item, source_sha256=observation_hash(item))


def prepare(value, **overrides):
    options = dict(
        expected_scope=value.scope,
        expected_source_sha256=value.source_sha256,
        expected_patient_identity_sha256=value.patient.identity_sha256,
        authorize_read=lambda _: True,
    )
    options.update(overrides)
    return prepare_medication_review(value, **options)


def test_source_preserves_exact_original_packet_and_separates_claims_from_current_use():
    value = observed()
    review = prepare(value)
    assert value.section_json in review.source_content
    assert '"quantity":0.50' in review.source_content and '"tiny":1e-7' in review.source_content
    assert "No medications reported statement: Explicitly true" in review.source_content
    assert "Returned medication groups: 3; returned entries: 2" in review.source_content
    assert "neither is discarded or reconciled" in review.source_content
    assert (
        "PEND entries are associated with approved future orders and have not yet been submitted."
        in review.source_content
    )
    assert "does not establish that the patient stopped taking it" in review.source_content
    assert "attempted medication-history download" in review.source_content
    assert "proof of current use" in review.source_content
    assert "2026-10-26T12:34:56.123456+00:00" in review.source_content
    assert (
        '"patientid"' not in review.source_content and '"departmentid"' not in review.source_content
    )
    assert (
        review.source_content_sha256 == hashlib.sha256(review.source_content.encode()).hexdigest()
    )
    assert review.completeness == "bounded_recorded_medication_section"


@pytest.mark.parametrize("statement", [None, False, True])
def test_empty_section_and_recorded_no_medications_statement_remain_distinct(statement):
    section = {"medications": [[], []]}
    if statement is not None:
        section["nomedicationsreported"] = statement
    review = prepare(changed(observed(), section))
    assert "empty returned section is not a statement" in review.source_content
    assert (
        "No medications reported statement: "
        + (
            "Not provided"
            if statement is None
            else "Explicitly true"
            if statement
            else "Explicitly false"
        )
    ) in review.source_content
    assert "Returned medication groups: 2; returned entries: 0" in review.source_content


def test_original_dates_download_flags_notes_and_structured_instructions_are_not_normalized():
    section = clinical_loads(
        r'{"lastdownloadeddate":"10/25/2026 01:02", "lastdownloaddenied":true,"lastdownloaddenialreason":"Original reason", "patientneedsdownloadconsent":true,"patientdownloadconsent":false,"lastupdated":"", "sectionnote":"Original\r\n\tsection", "medications":[[{"medication":"Invented tablet","isdiscontinued":true,"issafetorenew":false,"isstructuredsig":false,"status":"Unknown vendor state","earliestfilldate":"10/31/2026","filldate":"","futuresubmitdate":"2026","stopreason":"Original reason","unstructuredsig":"Original\r\n\tinstruction", "structuredsig":{"units":"mg","dose":0.50,"frequency":1e-7,"negative":-0},"quantity":0.50,"quantityunit":"tablets","refillsallowed":9223372036854775807,"encounterid":-9223372036854775808,"ndcoptions":[{"ndcoption":"00012"}],"rxnorm":[{"rxnormidentifier":"00123"}]}]]}'
    )
    value = changed(observed(), section)
    review = prepare(value)
    assert value.section_json in review.source_content
    assert '"refillsallowed":9223372036854775807' in review.source_content
    assert '"lastupdated":""' in review.source_content
    assert '"isdiscontinued":true' in review.source_content
    assert '"futuresubmitdate":"2026"' in review.source_content
    assert "PEND entries are" not in review.source_content


@pytest.mark.parametrize(
    "field",
    [
        "account_id",
        "connection_id",
        "credential_generation",
        "workspace_id",
        "patient_link_id",
        "department_id",
        "authorization_sha256",
    ],
)
def test_a_different_independent_patient_authority_cannot_prepare_the_snapshot(field):
    value = observed()
    replacement = (
        "904"
        if field == "department_id"
        else "b" * 64
        if field == "authorization_sha256"
        else UUID(int=99)
    )
    scope = replace(value.scope, **{field: replacement})
    with pytest.raises(AthenaMedicationError, match="access_denied"):
        prepare(value, expected_scope=scope)


@pytest.mark.parametrize(
    "change",
    [
        "drop_empty_group",
        "drop_repeated_record",
        "rename_record",
        "section_whitespace",
        "numeric_rounding",
        "patient_hash",
        "source_hash",
        "provider_hash",
        "query_flag",
        "timestamp",
    ],
)
def test_hashes_and_projection_cannot_discard_or_reinterpret_original_details(change):
    value = observed()
    if change == "drop_empty_group":
        value = replace(value, groups=(value.groups[0], value.groups[2]))
    elif change == "drop_repeated_record":
        value = replace(value, groups=(value.groups[0], (), ()))
    elif change == "rename_record":
        value = replace(
            value,
            groups=(
                (
                    AthenaMedicationRecord(
                        "C-invented-one", "Changed", value.groups[0][0].original_json
                    ),
                ),
                (),
                value.groups[2],
            ),
        )
    elif change == "section_whitespace":
        value = replace(value, section_json=" " + value.section_json)
    elif change == "numeric_rounding":
        value = replace(value, section_json=value.section_json.replace("0.50", "0.5"))
    elif change == "patient_hash":
        value = replace(value, patient=replace(value.patient, identity_sha256="b" * 64))
    elif change == "source_hash":
        value = replace(value, source_sha256="c" * 64)
    elif change == "provider_hash":
        value = replace(value, provider_sources=("not a digest", "a" * 64))
    elif change == "query_flag":
        value = replace(value, includes_pending=False)
    else:
        value = replace(value, observed_at=datetime(2026, 10, 26))
    with pytest.raises(AthenaMedicationError):
        prepare(value)


def test_complete_source_accepts_exactly5000_unicode_characters_and_refuses5001():
    value = observed()
    value = replace(value, scope=replace(value.scope, practice_label="Invented É Clinic 🧪"))
    section = {"medications": [], "sectionnote": ""}
    value = changed(value, section)
    padding = 5000 - len(_source(value))
    assert 0 < padding <= 4096
    section["sectionnote"] = "x" * padding
    value = changed(value, section)
    review = prepare(value)
    assert len(review.source_content) == 5000
    assert len(review.source_content.encode()) > 5000
    section["sectionnote"] += "x"
    value = changed(value, section)
    assert len(_source(value)) == 5001
    with pytest.raises(AthenaMedicationError, match="source_too_large"):
        prepare(value)


@pytest.mark.parametrize("when", ["before", "release"])
def test_authority_withdrawal_withholds_the_complete_review(when):
    value = observed()
    calls = []

    def allowed(scope):
        calls.append(scope)
        return when == "release" and len(calls) == 1

    with pytest.raises(AthenaMedicationError, match="access_denied"):
        prepare(value, authorize_read=allowed)
    assert len(calls) == (1 if when == "before" else 2)
