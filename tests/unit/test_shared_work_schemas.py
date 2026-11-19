"""Unit tests for WorkHandoffCommand."""

import pytest
from pydantic import ValidationError

from cosmas_os.api.shared_work_schemas import WorkHandoffCommand

UUID_A = "00000000-0000-4000-8000-000000000001"
UUID_B = "00000000-0000-4000-8000-000000000002"
UUID_C = "00000000-0000-4000-8000-000000000003"


def command(**overrides) -> WorkHandoffCommand:
    base = {
        "expected_version": 1,
        "revision_id": UUID_A,
        "payload_hash": "a" * 64,
        "idempotency_key": "handoff-key-0001",
        "kind": "reclaim",
    }
    base.update(overrides)
    return WorkHandoffCommand(**base)


def test_valid_offer():
    cmd = command(kind="offer", recipient_id=UUID_B)
    assert cmd.kind == "offer"
    assert str(cmd.recipient_id) == UUID_B
    assert cmd.offer_id is None


@pytest.mark.parametrize("kind", ["accept", "decline", "recall"])
def test_valid_responses(kind):
    cmd = command(kind=kind, offer_id=UUID_C)
    assert cmd.kind == kind
    assert str(cmd.offer_id) == UUID_C
    assert cmd.recipient_id is None


def test_valid_reclaim():
    cmd = command(kind="reclaim")
    assert cmd.recipient_id is None
    assert cmd.offer_id is None


@pytest.mark.parametrize(
    "kind, recipient_id, offer_id",
    [
        ("offer", None, None),
        ("accept", UUID_B, UUID_C),
        ("decline", UUID_B, UUID_C),
        ("recall", UUID_B, UUID_C),
        ("reclaim", UUID_B, None),
    ],
)
def test_invalid_recipient_presence(kind, recipient_id, offer_id):
    with pytest.raises(ValidationError):
        command(kind=kind, recipient_id=recipient_id, offer_id=offer_id)


@pytest.mark.parametrize(
    "kind, recipient_id, offer_id",
    [
        ("accept", None, None),
        ("decline", None, None),
        ("recall", None, None),
        ("offer", UUID_B, UUID_C),
        ("reclaim", None, UUID_C),
    ],
)
def test_invalid_offer_presence(kind, recipient_id, offer_id):
    with pytest.raises(ValidationError):
        command(kind=kind, recipient_id=recipient_id, offer_id=offer_id)


@pytest.mark.parametrize(
    "overrides",
    [
        {"unexpected": "x"},
        {"expected_version": 0},
        {"expected_version": "1"},
        {"payload_hash": "A" * 64},
        {"payload_hash": "a" * 63},
        {"idempotency_key": "short"},
        {"idempotency_key": "has space!"},
        {"kind": "other"},
    ],
)
def test_schema_validation_errors(overrides):
    with pytest.raises(ValidationError):
        command(**overrides)
