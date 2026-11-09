"""Adapter-failure copy offer: flag, marks, unchanged reads, safe hook, audit."""

from __future__ import annotations

import logging
from uuid import UUID

import httpx
import pytest
from tests.unit.test_athena_allergy_read_runtime import CONNECTION, GRANT, Harness

import cosmas_os.application.ehr_export.fallback as fallback
from cosmas_os.adapters.athena_allergy_read import AthenaAllergyError
from cosmas_os.adapters.elation_read import ElationReadAdapter, ElationReadError, ElationReadScope
from cosmas_os.adapters.elation_read_runtime import SyntheticElationReads
from cosmas_os.adapters.tebra_fhir_read import TebraFhirReadError
from cosmas_os.adapters.tebra_fhir_read_runtime import (
    SyntheticTebraFhirReads,
    TebraFhirConnectionScope,
)
from cosmas_os.application.ehr_export import ABSOLUTE_EXPIRY_SECONDS, audit_contains_note_text
from cosmas_os.config import Settings, settings

NOTE = "Sore throat for two days"


@pytest.fixture(autouse=True)
def _clear_fallback():
    fallback.clear_fallback_state()
    yield
    fallback.clear_fallback_state()


def _enable(monkeypatch):
    monkeypatch.setattr(settings, "copy_to_ehr_fallback_enabled", True)


def _elation(enabled: bool = True):
    scope = ElationReadScope(
        UUID(int=11), UUID(int=12), UUID(int=13), UUID(int=14), 15, "Invented Practice",
    )
    port = SyntheticElationReads(
        (scope,),
        httpx.MockTransport(lambda request: httpx.Response(204)),
        enabled=lambda: enabled,
    )
    return scope, port


def _tebra():
    scope = TebraFhirConnectionScope(
        UUID(int=21), UUID(int=22), UUID(int=23), UUID(int=24), UUID(int=25), "Invented Tebra",
    )
    port = SyntheticTebraFhirReads(
        (scope,),
        (),
        httpx.MockTransport(lambda request: httpx.Response(204)),
        enabled=lambda: True,
    )
    return scope, port


def test_flag_defaults_off_and_skips_the_mark():
    assert Settings().copy_to_ehr_fallback_enabled is False
    scope, port = _elation(enabled=False)
    with pytest.raises(ElationReadError) as raised:
        port.visit(scope, 4242, 7, authorize=lambda: True)
    assert raised.value.code == "disabled"
    assert raised.value.args == ("disabled",)
    assert fallback.visit_view(4242)["visit_copy_to_ehr_status"] == "unset"
    assert fallback.visit_view(4242)["offer"] == ""
    assert fallback.fallback_audit_events() == ()


def test_adapter_error_marks_the_visit(monkeypatch):
    _enable(monkeypatch)
    scope, port = _elation(enabled=False)
    with pytest.raises(ElationReadError) as raised:
        port.visit(scope, 4242, 7, authorize=lambda: True)
    assert type(raised.value) is ElationReadError
    assert raised.value.code == "disabled"
    assert raised.value.args == ("disabled",)
    view = fallback.visit_view(4242)
    assert view["visit_copy_to_ehr_status"] == "not_sent_copy_instead"
    assert view["offer"] == "not sent, Copy to EHR"
    event = fallback.fallback_audit_events()[-1]
    assert event.event == "copy_to_ehr.fallback_shown"
    assert event.profile_id == "generic"
    assert event.outcome == "error"
    assert audit_contains_note_text(event.detail, [NOTE]) is False


def test_disconnect_marks_the_visit(monkeypatch):
    _enable(monkeypatch)

    async def disconnect(self, appointment_id):
        raise ElationReadError("connection_changed")

    monkeypatch.setattr(ElationReadAdapter, "appointment", disconnect)
    scope, port = _elation(enabled=True)
    with pytest.raises(ElationReadError) as raised:
        port.visit(scope, 5150, 7, authorize=lambda: True)
    assert raised.value.code == "connection_changed"
    assert raised.value.args == ("connection_changed",)
    view = fallback.visit_view(5150)
    assert view["visit_copy_to_ehr_status"] == "not_sent_copy_instead"
    assert view["offer"] == "not sent, Copy to EHR"
    event = fallback.fallback_audit_events()[-1]
    assert event.outcome == "disconnect"
    assert event.profile_id == "generic"
    assert audit_contains_note_text(event.detail, [NOTE, "Taylor Morgan"]) is False


def test_athena_return_value_and_error_stay_the_same(monkeypatch):
    _enable(monkeypatch)
    harness = Harness()
    found = harness.port.patient_candidates(
        CONNECTION, GRANT.workspace_id, GRANT.patient_link_id, authorize=lambda: True,
    )
    assert found == (GRANT,)
    assert fallback.visit_view(GRANT.patient_link_id)["visit_copy_to_ehr_status"] == "unset"

    with pytest.raises(AthenaAllergyError) as raised:
        harness.port.patient_candidates(
            CONNECTION, GRANT.workspace_id, GRANT.patient_link_id, authorize=lambda: False,
        )
    assert type(raised.value) is AthenaAllergyError
    assert raised.value.code == "access_denied"
    assert raised.value.args == ("access_denied",)
    assert fallback.visit_view(GRANT.patient_link_id)["visit_copy_to_ehr_status"] == "not_sent_copy_instead"


def test_tebra_error_marks_patient_link_and_empty_read_is_unchanged(monkeypatch):
    _enable(monkeypatch)
    scope, port = _tebra()
    link = UUID(int=28)
    assert port.patient_candidates(scope, UUID(int=29), link, authorize=lambda: True) == ()
    assert fallback.visit_view(link)["visit_copy_to_ehr_status"] == "unset"

    with pytest.raises(TebraFhirReadError) as raised:
        port.patient_candidates(scope, UUID(int=29), link, authorize=lambda: False)
    assert type(raised.value) is TebraFhirReadError
    assert raised.value.code == "access_denied"
    assert raised.value.args == ("access_denied",)
    assert fallback.visit_view(link)["visit_copy_to_ehr_status"] == "not_sent_copy_instead"
    assert fallback.fallback_audit_events()[-1].profile_id == "generic"


def test_unknown_vendor_uses_generic_and_atlas_uses_its_profile(monkeypatch):
    _enable(monkeypatch)
    fallback.note_adapter_failure("visit-unknown", "not_a_vendor", kind="error", error_code="unavailable")
    fallback.note_adapter_failure("visit-atlas", "atlas_md", kind="disconnect", error_code="connection_changed")
    events = fallback.fallback_audit_events()
    assert events[0].profile_id == "generic"
    assert events[1].profile_id == "atlas_md"
    assert "not_a_vendor" not in events[0].detail


def test_hook_failure_is_swallowed_and_the_read_error_is_unchanged(monkeypatch, caplog):
    _enable(monkeypatch)

    def explode(*args, **kwargs):
        raise RuntimeError(NOTE)

    monkeypatch.setattr(fallback, "build_audit_event", explode)
    scope, port = _elation(enabled=False)
    with caplog.at_level(logging.INFO, logger="cosmas_os.ehr_export.fallback"):
        with pytest.raises(ElationReadError) as raised:
            port.visit(scope, 6161, 7, authorize=lambda: True)
    assert type(raised.value) is ElationReadError
    assert raised.value.code == "disabled"
    assert raised.value.args == ("disabled",)
    assert "copy_to_ehr.fallback_hook_failed" in caplog.text
    assert NOTE not in caplog.text
    for record in caplog.records:
        blob = record.getMessage()
        for _key, value in record.__dict__.items():
            if isinstance(value, str):
                blob += " " + value
        assert NOTE not in blob


def test_audit_drops_note_text(monkeypatch):
    _enable(monkeypatch)
    fallback.note_adapter_failure(
        "visit-note",
        "elation",
        kind="error",
        error_code=NOTE,
    )
    event = fallback.fallback_audit_events()[-1]
    packed = {
        "event": event.event,
        "profile_id": event.profile_id,
        "outcome": event.outcome,
        "detail": dict(event.detail),
        "correlation_id": event.correlation_id,
    }
    assert audit_contains_note_text(packed, [NOTE, "Taylor Morgan"]) is False
    assert "error_code" not in event.detail
    assert event.event == "copy_to_ehr.fallback_shown"


def test_audit_events_stay_bounded_at_500(monkeypatch):
    _enable(monkeypatch)
    for index in range(550):
        fallback.note_adapter_failure(
            f"visit-bound-{index}", "elation", kind="error", error_code="unavailable",
        )
    assert len(fallback.fallback_audit_events()) == 500


def test_visit_mark_expires_and_is_pruned_after_absolute_window(monkeypatch):
    _enable(monkeypatch)
    clock = {"now": 10_000.0}
    monkeypatch.setattr(fallback, "_now", lambda: clock["now"])
    fallback.note_adapter_failure(
        "visit-window", "elation", kind="error", error_code="unavailable",
    )
    assert fallback.visit_view("visit-window")["visit_copy_to_ehr_status"] == "not_sent_copy_instead"
    clock["now"] += ABSOLUTE_EXPIRY_SECONDS - 1
    assert fallback.visit_view("visit-window")["visit_copy_to_ehr_status"] == "not_sent_copy_instead"
    clock["now"] += 1
    fallback.note_adapter_failure(
        "visit-later", "elation", kind="disconnect", error_code="connection_changed",
    )
    assert "visit-window" not in fallback._marks
    expired = fallback.visit_view("visit-window")
    assert expired["visit_copy_to_ehr_status"] == "unset"
    assert expired["offer"] == ""
    assert fallback.visit_view("visit-later")["visit_copy_to_ehr_status"] == "not_sent_copy_instead"
