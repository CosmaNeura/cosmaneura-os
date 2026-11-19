"""Pin HandoffReview closed feedback schema (loc/type contracts)."""

import pytest
from pydantic import ValidationError

from cosmas_os.api.handoff_review_schemas import HandoffReview

BASE = {
    "expected_revision": 1,
    "idempotency_key": "review-key-0001",
    "attempt_id": "00000000-0000-4000-8000-000000000001",
    "result_entry_id": "00000000-0000-4000-8000-000000000002",
    "result_sha256": "a" * 64,
    "decision": "accepted",
}

REQUIRED_FIELDS = (
    "expected_revision",
    "idempotency_key",
    "attempt_id",
    "result_entry_id",
    "result_sha256",
    "decision",
)


def review(**overrides):
    body = {**BASE, **overrides}
    return HandoffReview.model_validate(body)


def test_valid_accepted_defaults_feedback_empty():
    model = review()
    assert model.feedback == ""
    assert model.decision == "accepted"
    assert model.expected_revision == 1
    assert model.idempotency_key == "review-key-0001"
    assert model.result_sha256 == "a" * 64


def test_valid_changes_requested_with_feedback():
    model = review(decision="changes_requested", feedback="fix it")
    assert model.decision == "changes_requested"
    assert model.feedback == "fix it"


def test_valid_feedback_exactly_2000_chars():
    model = review(feedback="x" * 2000)
    assert model.feedback == "x" * 2000


def test_valid_accepted_with_whitespace_feedback():
    model = review(feedback="  ")
    assert model.feedback == "  "


def test_valid_feedback_with_non_nul_control():
    model = review(feedback="a\x01b")
    assert model.feedback == "a\x01b"


def _assert_one_error(exc: ValidationError, *, loc: tuple, type_: str) -> None:
    errors = exc.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == loc
    assert errors[0]["type"] == type_


def _assert_feedback_required(exc: ValidationError) -> None:
    _assert_one_error(exc, loc=(), type_="value_error")
    assert "handoff_review_feedback_required" in exc.errors()[0]["msg"]


def test_rejects_nul_in_feedback():
    with pytest.raises(ValidationError) as exc:
        review(feedback="a\0b")
    _assert_feedback_required(exc.value)


def test_rejects_changes_requested_with_empty_feedback():
    with pytest.raises(ValidationError) as exc:
        review(decision="changes_requested", feedback="")
    _assert_feedback_required(exc.value)


def test_rejects_changes_requested_with_blank_feedback():
    with pytest.raises(ValidationError) as exc:
        review(decision="changes_requested", feedback="  \n")
    _assert_feedback_required(exc.value)


def test_rejects_unknown_decision():
    with pytest.raises(ValidationError) as exc:
        review(decision="maybe")
    _assert_one_error(exc.value, loc=("decision",), type_="literal_error")


def test_rejects_expected_revision_below_one():
    with pytest.raises(ValidationError) as exc:
        review(expected_revision=0)
    _assert_one_error(exc.value, loc=("expected_revision",), type_="greater_than_equal")


@pytest.mark.parametrize("value", ["1", True, 1.0])
def test_rejects_expected_revision_non_int(value):
    with pytest.raises(ValidationError) as exc:
        review(expected_revision=value)
    _assert_one_error(exc.value, loc=("expected_revision",), type_="int_type")


@pytest.mark.parametrize("value", ["a" * 63, "A" * 64, "a" * 65, "g" * 64])
def test_rejects_result_sha256_pattern(value):
    with pytest.raises(ValidationError) as exc:
        review(result_sha256=value)
    _assert_one_error(exc.value, loc=("result_sha256",), type_="string_pattern_mismatch")


def test_rejects_idempotency_key_too_short():
    with pytest.raises(ValidationError) as exc:
        review(idempotency_key="short")
    _assert_one_error(exc.value, loc=("idempotency_key",), type_="string_too_short")


def test_rejects_idempotency_key_pattern():
    with pytest.raises(ValidationError) as exc:
        review(idempotency_key="bad key 0001")
    _assert_one_error(exc.value, loc=("idempotency_key",), type_="string_pattern_mismatch")


@pytest.mark.parametrize("field", ["attempt_id", "result_entry_id"])
def test_rejects_uuid_fields_not_uuid(field):
    with pytest.raises(ValidationError) as exc:
        review(**{field: "nope"})
    _assert_one_error(exc.value, loc=(field,), type_="uuid_parsing")


def test_rejects_extra_key():
    with pytest.raises(ValidationError) as exc:
        review(x=1)
    _assert_one_error(exc.value, loc=("x",), type_="extra_forbidden")


def test_rejects_feedback_too_long():
    with pytest.raises(ValidationError) as exc:
        review(feedback="x" * 2001)
    _assert_one_error(exc.value, loc=("feedback",), type_="string_too_long")


def test_rejects_feedback_too_long_hides_input():
    with pytest.raises(ValidationError) as exc:
        review(feedback="SECRET" + "x" * 2000)
    _assert_one_error(exc.value, loc=("feedback",), type_="string_too_long")
    assert "SECRET" not in str(exc.value)


@pytest.mark.parametrize("field", REQUIRED_FIELDS)
def test_rejects_missing_required_field(field):
    body = {**BASE}
    del body[field]
    with pytest.raises(ValidationError) as exc:
        HandoffReview.model_validate(body)
    _assert_one_error(exc.value, loc=(field,), type_="missing")
