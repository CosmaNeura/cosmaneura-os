"""Private review is explicit, exclusive, and cannot relabel visit authority."""
from uuid import uuid4

import pytest
from pydantic import ValidationError

from cosmas_os.api.google_calendar_schemas import CALENDAR_COMMAND, ReviewCalendar
from cosmas_os.application.google_calendar import _review_body
from cosmas_os.domain.hashing import payload_hash


def body():
    return dict(expected_revision=1, idempotency_key="private-review", observation_id=str(uuid4()),
        observation_sha256="a" * 64, event_id="invented", event_sha256="b" * 64,
        reviewed_private_notebook=True, reviewed_exact_summary=True, reviewed_untrusted_source=True)


@pytest.mark.parametrize("change", [{"reviewed_private_notebook": False}, {"reviewed_private_notebook": 1},
    {"reviewed_private_notebook": "true"}, {"reviewed_private_notebook": None}, {"reviewed_visit": True},
    {"reviewed_visit": None}, {"patient_link_id": str(uuid4())}, {"appointment_id": str(uuid4())}])
def test_private_contract_rejects_ambiguous_or_client_patient_authority(change):
    with pytest.raises(ValidationError):
        ReviewCalendar.model_validate({**body(), **change})


def test_old_visit_hash_is_exact_and_private_hash_is_distinct():
    request = body()
    original = {**request, "workspace_id": str(uuid4())}
    original.pop("reviewed_private_notebook")
    original["reviewed_visit"] = True
    args = (original["workspace_id"], 1, original["idempotency_key"], original["observation_id"],
        original["observation_sha256"], "invented", original["event_sha256"], True, True, True)
    assert _review_body(*args) == original
    private = _review_body(*args, reviewed_private_notebook=True)
    assert "reviewed_visit" not in private and private["reviewed_private_notebook"] is True
    assert payload_hash(private) != payload_hash(original)
    assert ReviewCalendar.model_validate(request).reviewed_visit is None


@pytest.mark.parametrize("value", [False, 1, "true", None])
def test_capability_negotiation_is_opt_in_literal(value):
    with pytest.raises(ValidationError):
        CALENDAR_COMMAND.validate_python({"action": "status", "include_private_notebook": value})


def test_old_and_opted_in_status_remain_distinct_closed_requests():
    assert CALENDAR_COMMAND.validate_python({"action": "status"}).include_private_notebook is None
    assert CALENDAR_COMMAND.validate_python({"action": "status", "include_private_notebook": True}).include_private_notebook is True
