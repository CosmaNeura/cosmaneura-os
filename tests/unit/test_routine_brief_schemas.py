import pytest
from pydantic import ValidationError
from cosmas_os.api.routine_brief_schemas import IncomingCounts, IncomingItem, IncomingSection, Person

UUID_A = "00000000-0000-4000-8000-000000000001"
UUID_B = "00000000-0000-4000-8000-000000000002"
UUID_C = "00000000-0000-4000-8000-000000000003"
UUID_D = "00000000-0000-4000-8000-000000000004"
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
        pending_approval=0, open=0, overdue=0, awaiting_acceptance=0,
        responsible_unavailable=0, awaiting_review=0, verified_complete=0,
        source_unavailable=0, work_changed=0
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
    assert item()

def test_incoming_item_verified_but_not_closed():
    with pytest.raises(ValidationError):
        item(verified_current=True, state="approved")

def test_incoming_item_verified_and_closed_with_receipts():
    assert item(
        verified_current=True,
        state="closed",
        publication_receipt_id=UUID_A,
        result_receipt_id=UUID_A,
        verification_receipt_id=UUID_A
    )

def test_incoming_item_pending_offer_but_not_approved():
    with pytest.raises(ValidationError):
        item(pending_offer=True, state="closed")

def test_incoming_item_source_unavailable_with_body():
    with pytest.raises(ValidationError):
        item(state="source_unavailable", body="Synthetic body")

def test_valid_complete_section():
    assert section()

def test_incoming_section_duplicate_ticket_ids():
    with pytest.raises(ValidationError):
        section(items=[item(), item()], matching_items=2)

def test_incoming_section_unavailable_coverage_accepted():
    assert section(
        coverage="unavailable",
        reason="source_unavailable",
        items=[],
        matching_items=0,
        counts=None,
        withheld_sources=True
    )

def test_incoming_section_unavailable_with_counts():
    with pytest.raises(ValidationError):
        section(coverage="unavailable", counts=counts())

def test_incoming_section_complete_with_withheld_sources():
    with pytest.raises(ValidationError):
        section(coverage="complete", withheld_sources=True)
