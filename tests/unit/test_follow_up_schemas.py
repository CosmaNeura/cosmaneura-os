"""Unit tests for follow-up schemas."""

from datetime import date

import pytest
from pydantic import ValidationError

from cosmas_os.api.follow_up_schemas import (
    FollowUpComplete,
    FollowUpDecision,
    FollowUpPropose,
)

UUID_A = "00000000-0000-4000-8000-000000000001"
DIGEST_VALID = "a" * 64
DIGEST_INVALID_CHAR = "g" * 64
DIGEST_SHORT = "a" * 63


def get_valid_propose_dict():
    return {
        "expected_revision": 1,
        "idempotency_key": "followup-key-001",
        "note_id": UUID_A,
        "body": "Call back",
        "due_date": date(2026, 12, 1),
        "expected_outcome": "Form returned",
        "share": False,
    }


def get_valid_decision_dict():
    return {
        "revision_id": UUID_A,
        "payload_hash": DIGEST_VALID,
        "choice": "approve",
    }


def get_valid_complete_dict():
    return {
        "revision_id": UUID_A,
        "payload_hash": DIGEST_VALID,
        "idempotency_key": "valid-key-123",
        "evidence": "Done",
    }


def test_follow_up_propose_valid():
    data = get_valid_propose_dict()
    model = FollowUpPropose(**data)
    assert model.body == "Call back"
    assert model.expected_outcome == "Form returned"
    assert model.share is False
    assert model.expected_revision == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"body": ""},
        {"body": "a" * 4001},
        {"expected_outcome": ""},
        {"expected_outcome": "a" * 501},
        {"expected_revision": 0},
        {"expected_revision": "1"},
        {"share": "yes"},
        {"share": 1},
        {"extra_field": "not_allowed"},
        {"due_date": "not-a-date"},
    ],
)
def test_follow_up_propose_invalid(overrides):
    data = get_valid_propose_dict()
    data.update(overrides)
    with pytest.raises(ValidationError):
        FollowUpPropose(**data)


def test_follow_up_propose_boundaries():
    # body of 4000 chars
    data = get_valid_propose_dict()
    data["body"] = "a" * 4000
    model = FollowUpPropose(**data)
    assert len(model.body) == 4000

    # expected_outcome of 500 chars
    data = get_valid_propose_dict()
    data["expected_outcome"] = "a" * 500
    model = FollowUpPropose(**data)
    assert len(model.expected_outcome) == 500


@pytest.mark.parametrize("choice", ["approve", "reject"])
def test_follow_up_decision_valid(choice):
    data = get_valid_decision_dict()
    data["choice"] = choice
    model = FollowUpDecision(**data)
    assert model.choice == choice


@pytest.mark.parametrize(
    "overrides",
    [
        {"choice": "maybe"},
        {"payload_hash": DIGEST_INVALID_CHAR},
        {"payload_hash": DIGEST_SHORT},
        {"extra_field": "not_allowed"},
    ],
)
def test_follow_up_decision_invalid(overrides):
    data = get_valid_decision_dict()
    data.update(overrides)
    with pytest.raises(ValidationError):
        FollowUpDecision(**data)


def test_follow_up_complete_valid():
    # Default expected_version is None
    data = get_valid_complete_dict()
    model = FollowUpComplete(**data)
    assert model.evidence == "Done"
    assert model.expected_version is None

    # expected_version=1 accepted
    data["expected_version"] = 1
    model = FollowUpComplete(**data)
    assert model.expected_version == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"expected_version": 0},
        {"evidence": ""},
        {"evidence": "a" * 2001},
        {"idempotency_key": "bad key"},
    ],
)
def test_follow_up_complete_invalid(overrides):
    data = get_valid_complete_dict()
    data.update(overrides)
    with pytest.raises(ValidationError):
        FollowUpComplete(**data)


def test_follow_up_complete_boundaries():
    # evidence of 2000 chars
    data = get_valid_complete_dict()
    data["evidence"] = "a" * 2000
    model = FollowUpComplete(**data)
    assert len(model.evidence) == 2000
