"""Guard: a connector failure shows a visible copy offer and does not block."""

from typing import get_args

import cosmas_os.application.ehr_export.fallback as fallback
from cosmas_os.application.ehr_export.types import VisitCopyToEhrStatus
from cosmas_os.config import settings


def test_connection_failure_fallback_module_marks_visible_offer(monkeypatch):
    monkeypatch.setattr(settings, "copy_to_ehr_fallback_enabled", True)
    fallback.clear_fallback_state()
    visible: VisitCopyToEhrStatus = "not_sent_copy_instead"
    visit = {"visit_copy_to_ehr_status": "unset", "offer": ""}
    note = {"review_state": "reviewed", "saved": True}

    error_offer = fallback.note_adapter_failure(
        "visit-invented-guard",
        "elation",
        kind="error",
        error_code="record_unavailable",
        visit_view_field=visit,
    )
    assert error_offer is not None
    assert error_offer.visit_copy_to_ehr_status == visible
    assert error_offer.visit_copy_to_ehr_status in get_args(VisitCopyToEhrStatus)
    assert error_offer.offer == "not sent, Copy to EHR"
    assert error_offer.blocks_visit is False
    assert error_offer.blocks_note is False
    assert visit["visit_copy_to_ehr_status"] == visible
    assert visit["offer"] == "not sent, Copy to EHR"
    assert fallback.visit_view("visit-invented-guard")["visit_copy_to_ehr_status"] == visible
    assert fallback.visit_view("visit-invented-guard")["offer"] == "not sent, Copy to EHR"

    # The visit and the note are still free to finish.
    assert note["saved"] is True
    note["ready"] = True
    assert note["ready"] is True

    disconnect_offer = fallback.note_adapter_failure(
        "visit-invented-guard",
        "tebra",
        kind="disconnect",
        error_code="connection_changed",
        visit_view_field=visit,
    )
    assert disconnect_offer is not None
    assert disconnect_offer.visit_copy_to_ehr_status == visible
    assert disconnect_offer.offer == "not sent, Copy to EHR"
    assert disconnect_offer.blocks_visit is False
    assert disconnect_offer.blocks_note is False
    assert note["saved"] is True
    fallback.clear_fallback_state()
