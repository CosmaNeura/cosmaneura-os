"""Tests for routine brief schemas."""

import pytest
from pydantic import ValidationError

from cosmas_os.api.routine_brief_schemas import (
    IncomingCounts,
    IncomingItem,
    IncomingSection,
    Person,
)

UUID_A = "00000000-0000-4000-8000-000000000001"
UUID_B = "00000000-0000-4000-8000-000000000002"
UUID_C = "00000000-0000-4000-8000-000000000003"
UUID_D = "00000000-0000-4000-8000-000000000004"
UUID_E = "00000000-0000-4000-8000-000000000005"
UUID_F = "00000000-0000-4000-8000-000000000006"
UUID_G = "00000000-0000-4000-8000-000000000007"
DIGEST = "a" * 64


def person():
    return Person(id=UUID_A, name="Synthetic Person", available=True)


def item(**overrides):
    base = {
        "ticket_id": UUID_B,
        "revision_id": UUID_C,
        "payload_hash": DIGEST,
        "version": 1,
        "state": "approved",
        "body": "Synthetic body",
        "due_date": "2026-12-01",
        "responsible": person(),
        "originator_id": UUID_D,
        "requires_owner_attention": False,
        "pending_offer": False,
        "ready_for_review": False,
        "verified_current": False,
        "publication_receipt_id": None,
        "result_receipt_id": None,
        "verification_receipt_id": None,
        "changed_since_report": False,
    }
    base.update(overrides)
    return IncomingItem(**base)


def counts():
    return IncomingCounts(
        pending_approval=0,
        open=0,
        overdue=0,
        awaiting_acceptance=0,
        responsible_unavailable=0,
        awaiting_review=0,
        verified_complete=0,
        source_unavailable=0,
        work_changed=0,
    )


def section(**overrides):
    base = {
        "coverage": "complete",
        "reason": None,
        "items": [item()],
        "matching_items": 1,
        "counts": counts(),
        "withheld_sources": False,
    }
    base.update(overrides)
    return IncomingSection(**base)


def test_valid_incoming_item():
    res = item()
    assert isinstance(res, IncomingItem)
    assert res.ticket_id == UUID_B
    assert res.state == "approved"


def test_incoming_item_verified_but_not_closed():
    with pytest.raises(ValidationError) as exc:
        item(
            verified_current=True,
            state="approved",
            publication_receipt_id=UUID_E,
            result_receipt_id=UUID_F,
            verification_receipt_id=UUID_G,
        )
    assert len(exc.value.errors()) == 1
    assert exc.value.errors()[0]["type"] == "value_error"
    assert exc.value.errors()[0]["loc"] == ()


@pytest.mark.parametrize(
    "missing_receipt",
    ["publication_receipt_id", "result_receipt_id", "verification_receipt_id"],
)
def test_incoming_item_closed_missing_one_receipt_rejected(missing_receipt):
    kwargs = {
        "state": "closed",
        "verified_current": True,
        "publication_receipt_id": UUID_E,
        "result_receipt_id": UUID_F,
        "verification_receipt_id": UUID_G,
        missing_receipt: None,
    }
    with pytest.raises(ValidationError) as exc:
        item(**kwargs)
    assert len(exc.value.errors()) == 1
    assert exc.value.errors()[0]["type"] == "value_error"
    assert exc.value.errors()[0]["loc"] == ()


def test_incoming_item_verified_and_closed_with_receipts():
    res = item(
        verified_current=True,
        state="closed",
        publication_receipt_id=UUID_A,
        result_receipt_id=UUID_A,
        verification_receipt_id=UUID_A,
    )
    assert isinstance(res, IncomingItem)
    assert res.verified_current is True
    assert res.state == "closed"


def test_incoming_item_pending_offer_but_not_approved():
    with pytest.raises(ValidationError) as exc:
        item(pending_offer=True, state="closed")
    assert len(exc.value.errors()) == 1
    assert exc.value.errors()[0]["type"] == "value_error"
    assert exc.value.errors()[0]["loc"] == ()


def test_incoming_item_source_unavailable_with_body():
    with pytest.raises(ValidationError) as exc:
        item(
            state="source_unavailable",
            body="Synthetic body",
            due_date=None,
            publication_receipt_id=None,
            result_receipt_id=None,
            verification_receipt_id=None,
        )
    assert len(exc.value.errors()) == 1
    assert exc.value.errors()[0]["type"] == "value_error"
    assert exc.value.errors()[0]["loc"] == ()


def test_incoming_item_source_unavailable_withheld_accepted():
    res = item(
        state="source_unavailable",
        body=None,
        due_date=None,
        publication_receipt_id=None,
        result_receipt_id=None,
        verification_receipt_id=None,
    )
    assert res.state == "source_unavailable"
    assert res.body is None
    assert res.due_date is None
    assert res.publication_receipt_id is None
    assert res.result_receipt_id is None
    assert res.verification_receipt_id is None


@pytest.mark.parametrize("state", ["source_unavailable", "work_changed"])
@pytest.mark.parametrize(
    "field,value",
    [
        ("body", "Synthetic body"),
        ("due_date", "2026-12-01"),
        ("publication_receipt_id", UUID_E),
        ("result_receipt_id", UUID_F),
        ("verification_receipt_id", UUID_G),
    ],
)
def test_incoming_item_withheld_fields_rejected(state, field, value):
    kwargs = {
        "state": state,
        "body": None,
        "due_date": None,
        "publication_receipt_id": None,
        "result_receipt_id": None,
        "verification_receipt_id": None,
        field: value,
    }
    with pytest.raises(ValidationError) as exc:
        item(**kwargs)
    assert len(exc.value.errors()) == 1
    assert exc.value.errors()[0]["type"] == "value_error"
    assert exc.value.errors()[0]["loc"] == ()


def test_valid_complete_section():
    res = section()
    assert isinstance(res, IncomingSection)
    assert res.coverage == "complete"
    assert len(res.items) == 1


def test_incoming_section_duplicate_ticket_ids():
    with pytest.raises(ValidationError) as exc:
        section(items=[item(), item()], matching_items=2)
    assert len(exc.value.errors()) == 1
    assert exc.value.errors()[0]["type"] == "value_error"
    assert exc.value.errors()[0]["loc"] == ()


def test_incoming_section_unavailable_coverage_accepted():
    res = section(
        coverage="unavailable",
        reason="source_unavailable",
        items=[],
        matching_items=0,
        counts=None,
        withheld_sources=True,
    )
    assert isinstance(res, IncomingSection)
    assert res.coverage == "unavailable"
    assert res.withheld_sources is True


def test_incoming_section_unavailable_with_counts():
    with pytest.raises(ValidationError) as exc:
        section(
            coverage="unavailable",
            reason="source_unavailable",
            items=[],
            matching_items=0,
            counts=counts(),
            withheld_sources=True,
        )
    assert len(exc.value.errors()) == 1
    assert exc.value.errors()[0]["type"] == "value_error"
    assert exc.value.errors()[0]["loc"] == ()


def test_incoming_section_complete_with_withheld_sources():
    with pytest.raises(ValidationError) as exc:
        section(coverage="complete", withheld_sources=True)
    assert len(exc.value.errors()) == 1
    assert exc.value.errors()[0]["type"] == "value_error"
    assert exc.value.errors()[0]["loc"] == ()
