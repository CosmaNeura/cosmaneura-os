"""Exact allergy-review meaning, complete source size, and changed authority."""

import json
from dataclasses import replace
from uuid import UUID

import pytest
from tests.unit.test_athena_allergy_read import SCOPE, Harness

from cosmas_os.adapters.athena_allergy_read import (
    AthenaAllergyError,
    allergy_records,
    observation_hash,
)
from cosmas_os.application.athena_allergy_snapshot import _source, prepare_allergy_review
from cosmas_os.domain.hashing import canonical_json


def prepare(value, **changes):
    return prepare_allergy_review(
        value,
        **{
            "expected_scope": SCOPE,
            "expected_source_sha256": value.source_sha256,
            "expected_patient_identity_sha256": value.patient.identity_sha256,
            "authorize_read": lambda _: True,
            **changes,
        },
    )


def revise(value, section):
    revised = replace(value, section_json=canonical_json(section), records=allergy_records(section))
    return replace(revised, source_sha256=observation_hash(revised))


def test_full_original_qualifiers_and_contradictory_nkda_survive_review():
    h = Harness()
    h.section["nkda"] = True
    value = h.read()
    snapshot = prepare(value)
    assert value.section_json in snapshot.source_content
    assert "No known drug allergies statement: Explicitly true" in snapshot.source_content
    assert "neither is discarded or reconciled" in snapshot.source_content
    assert (
        '"onsetdate":"2024"' in snapshot.source_content
        and '"deactivatedate":"10/01/2026"' in snapshot.source_content
    )
    assert (
        "recorded severity" in snapshot.source_content
        and "recorded criticality" in snapshot.source_content
    )
    assert (
        '"patientid"' not in snapshot.source_content
        and '"departmentid"' not in snapshot.source_content
    )
    assert (
        json.loads(snapshot.observation.records[0].original_json)["note"]
        == h.section["allergies"][0]["note"]
    )


@pytest.mark.parametrize(
    "nkda,label",
    [(True, "Explicitly true"), (False, "Explicitly false"), ("missing", "Not provided")],
)
def test_empty_returned_list_does_not_become_no_known_allergies(nkda, label):
    h = Harness()
    h.section["allergies"] = []
    if nkda == "missing":
        h.section.pop("nkda")
    else:
        h.section["nkda"] = nkda
    source = prepare(h.read()).source_content
    assert "No known drug allergies statement: " + label in source
    assert "An empty returned list is not a statement of no known allergies." in source


def test_absent_and_empty_recorded_dates_remain_distinct():
    h = Harness()
    h.section["allergies"][0].pop("onsetdate")
    h.section["allergies"][0]["deactivatedate"] = ""
    snapshot = prepare(h.read())
    original = snapshot.observation.records[0].original_json
    assert '"onsetdate"' not in original and '"deactivatedate":""' in original
    assert "no precision or timezone is inferred" in snapshot.source_content


@pytest.mark.parametrize(
    "change",
    ["scope", "source", "identity", "records", "section", "inactive", "coverage", "aware_time"],
)
def test_changed_proof_or_projection_is_withheld(change):
    value = Harness().read()
    if change == "scope":
        value = replace(value, scope=replace(SCOPE, department_id="990"))
    elif change == "source":
        value = replace(value, source_sha256="b" * 64)
    elif change == "identity":
        value = replace(value, patient=replace(value.patient, identity_sha256="b" * 64))
    elif change == "records":
        value = replace(value, records=())
    elif change == "section":
        value = replace(value, section_json='{"allergies":[]}')
    elif change == "inactive":
        value = replace(value, includes_inactive=False)
    elif change == "coverage":
        value = replace(value, coverage="complete")
    else:
        value = replace(value, observed_at=value.observed_at.replace(tzinfo=None))
    with pytest.raises(AthenaAllergyError):
        prepare(value)


def test_final_source_5000_unicode_characters_allowed_5001_whole_packet_refused():
    value = Harness().read()
    section = json.loads(value.section_json)
    # Source text counts Unicode codepoints; labels stay human-readable Unicode.
    value = replace(value, scope=replace(SCOPE, department_label="Éxample chart"))
    section["sectionnote"] = ""
    value = revise(value, section)
    size = 5000 - len(_source(value))
    assert 0 < size <= 4000
    section["sectionnote"] = "x" * size
    exact = revise(value, section)
    snapshot = prepare(exact, expected_scope=exact.scope)
    assert len(snapshot.source_content) == 5000 and len(snapshot.source_content.encode()) > 5000
    section["sectionnote"] += "x"
    with pytest.raises(AthenaAllergyError, match="source_too_large"):
        prepare(revise(value, section), expected_scope=value.scope)


def test_authority_revoked_during_formatting_withholds_the_entire_snapshot():
    value = Harness().read()
    calls = []

    def authorize(scope):
        calls.append(scope)
        return len(calls) == 1

    with pytest.raises(AthenaAllergyError, match="access_denied"):
        prepare(value, authorize_read=authorize)
    assert calls == [SCOPE, SCOPE]


def test_unrelated_workspace_or_account_cannot_reuse_the_snapshot():
    value = Harness().read()
    for scope in (
        replace(SCOPE, workspace_id=UUID(int=99)),
        replace(SCOPE, account_id=UUID(int=99)),
    ):
        with pytest.raises(AthenaAllergyError, match="access_denied"):
            prepare(value, expected_scope=scope)
