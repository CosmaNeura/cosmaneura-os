"""Invented visit rechecks precede report discovery and exact selected source review."""

import json
from collections.abc import Callable
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import pytest
from tests.unit.test_elation_lab_read import CONNECTION, PATIENT, REPORT, SCOPE

from cosmas_os.adapters.elation_lab_read import ElationLabError, page_hash
from cosmas_os.adapters.elation_read import (
    SCOPES,
    ElationAppointment,
    ElationPatient,
    ElationReadError,
)
from cosmas_os.adapters.elation_read_runtime import SyntheticElationReads

APPOINTMENT = dict(
    id=904,
    practice=901,
    patient=903,
    physician=902,
    scheduled_date="2026-10-25T13:00:00Z",
    duration=30,
    time_slot_type="appointment",
    status={"status": "Confirmed"},
    deleted_date=None,
)


class Harness:
    def __init__(self):
        self.calls = []
        self.patient, self.appointment, self.report = (
            deepcopy(PATIENT),
            deepcopy(APPOINTMENT),
            deepcopy(REPORT),
        )
        self.enabled, self.labs, self.authorized = True, True, True
        self.verified = []
        self.patient_reads = 0
        self.after: Callable[[httpx.Request], None] = lambda _: None
        self.identity = True
        self.transport = httpx.MockTransport(self.send)
        self.port = SyntheticElationReads(
            (CONNECTION,),
            self.transport,
            enabled=lambda: self.enabled,
            labs_enabled=lambda: self.labs,
        )

    def send(self, request):
        self.calls.append(request)
        path = request.url.path
        if path == "/api/2.0/oauth2/token/":
            assert request.method == "POST"
            assert httpx.QueryParams(request.content.decode())["scope"] == SCOPES
            body = dict(
                access_token="invented-visit-token",
                token_type="Bearer",
                expires_in=3600,
                scope=SCOPES,
            )
        else:
            assert request.method == "GET"
            if path == "/api/2.0/appointments/904/":
                body = self.appointment
            elif path == "/api/2.0/patients/903/":
                self.patient_reads += 1
                body = self.patient
            elif path == "/api/2.0/reports/":
                assert dict(request.url.params) == dict(
                    patient="903", practice="901", limit="25", order_by="-document_date"
                )
                body = dict(results=[self.report], next=None, previous=None, count=1)
            else:
                assert path == f"/api/2.0/reports/{REPORT['id']}/"
                body = self.report
        self.after(request)
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            stream=httpx.ByteStream(json.dumps(body).encode()),
        )

    def verify(self, appointment, patient):
        self.verified.append((appointment, patient))
        assert not any(r.url.path.startswith("/api/2.0/reports/") for r in self.calls[-3:])
        return self.identity

    def page(self, scope=SCOPE):
        return self.port.lab_reports(
            scope, 904, authorize=lambda: self.authorized, verify_identity=self.verify
        )[2]

    def read(self, page, **changes):
        args = dict(
            scope=SCOPE,
            appointment_id=904,
            page=page,
            report_id=REPORT["id"],
            expected_candidates_sha256=page.source_sha256,
            authorize=lambda: self.authorized,
            verify_identity=self.verify,
        )
        args.update(changes)
        return self.port.lab_report(**args)[2]


def test_discovery_and_selected_read_recheck_visit_identity_before_fresh_patient_and_report():
    h = Harness()
    page = h.page()
    h.report["grids"][0]["results"][0]["value"] = "001.2400"
    source = h.read(page)
    sequence = [r.url.path for r in h.calls]
    prefix = [
        "/api/2.0/oauth2/token/",
        "/api/2.0/appointments/904/",
        "/api/2.0/patients/903/",
        "/api/2.0/patients/903/",
    ]
    assert sequence == prefix + ["/api/2.0/reports/"] + prefix + [
        f"/api/2.0/reports/{REPORT['id']}/"
    ]
    assert len(h.verified) == 2 and h.patient_reads == 4
    assert source.observation.changed_since_selection
    assert '"value":"001.2400"' in source.source_content
    assert '"reference_min":"< 0.10"' in source.source_content
    assert source.observation.scope == SCOPE


@pytest.mark.parametrize("flag", [False, None, 1])
def test_explicit_literal_lab_enablement_is_required_before_any_provider_io(flag):
    h = Harness()
    h.labs = flag
    with pytest.raises(ElationLabError, match="access_denied"):
        h.page()
    assert h.calls == []


def test_default_dark_lab_option_preserves_existing_visit_read():
    h = Harness()
    h.port = SyntheticElationReads((CONNECTION,), h.transport, enabled=lambda: True)
    assert not h.port.labs_available(CONNECTION)
    appointment, patient = h.port.visit(CONNECTION, 904, 903, authorize=lambda: True)
    assert isinstance(appointment.rows[0], ElationAppointment)
    assert isinstance(patient.rows[0], ElationPatient)
    assert appointment.rows[0].patient_id == patient.rows[0].patient_id == 903
    with pytest.raises(ElationLabError, match="access_denied"):
        h.page()
    assert len(h.calls) == 3


@pytest.mark.parametrize("change", ["connection", "generation", "host", "authorization"])
def test_current_connection_generation_host_and_authority_are_required(change):
    h = Harness()
    scope = SCOPE
    if change in ("connection", "generation"):
        key = "connection_id" if change == "connection" else "credential_generation"
        scope = replace(scope, connection_scope=replace(CONNECTION, **{key: UUID(int=99)}))
    elif change == "host":
        h.enabled = False
    else:
        h.authorized = False
    with pytest.raises(ElationLabError, match="access_denied"):
        h.page(scope)
    assert not h.calls


@pytest.mark.parametrize("change", ["appointment_patient", "identity_check", "fresh_patient"])
def test_changed_visit_or_patient_is_withheld_before_report_io(change):
    h = Harness()
    if change == "appointment_patient":
        h.appointment["patient"] = 999
    elif change == "identity_check":
        h.identity = False
    else:

        def after(request):
            if request.url.path == "/api/2.0/patients/903/" and h.patient_reads == 2:
                h.patient["last_name"] = "Changed"

        h.after = after
    with pytest.raises((ElationLabError, ElationReadError)):
        h.page()
    assert not any(r.url.path.startswith("/api/2.0/reports/") for r in h.calls)


@pytest.mark.parametrize("withdraw", ["host", "labs", "authorization"])
def test_withdrawal_during_report_io_withholds_the_entire_page(withdraw):
    h = Harness()

    def after(request):
        if request.url.path == "/api/2.0/reports/":
            setattr(
                h,
                {"host": "enabled", "labs": "labs", "authorization": "authorized"}[withdraw],
                False,
            )

    h.after = after
    with pytest.raises(ElationLabError, match="access_denied"):
        h.page()
    assert len(h.calls) == 5


@pytest.mark.parametrize("bad", ["hash", "report", "workspace", "account", "expired"])
def test_invalid_selection_is_refused_before_visit_or_clinical_io(bad):
    h = Harness()
    page = h.page()
    before = len(h.calls)
    changes = {}
    if bad == "hash":
        changes["expected_candidates_sha256"] = "0" * 64
    elif bad == "report":
        changes["report_id"] = REPORT["id"] + 1
    elif bad in ("workspace", "account"):
        changes["scope"] = replace(SCOPE, **{bad + "_id": UUID(int=90)})
    else:
        page = replace(
            page, observed_at=datetime.now(UTC) - timedelta(minutes=31), source_sha256=""
        )
        page = replace(page, source_sha256=page_hash(page))
    with pytest.raises(ElationLabError):
        h.read(page, **changes)
    assert len(h.calls) == before


def test_oversized_original_report_is_refused_as_a_whole_before_source_release():
    h = Harness()
    h.report["grids"][0]["results"] *= 12
    page = h.page()
    with pytest.raises(ElationLabError, match="source_too_large"):
        h.read(page)
