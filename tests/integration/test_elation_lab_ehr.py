"""Signed laboratory selection, original report review and existing EHR source custody."""

import json
from copy import deepcopy

import httpx
import pytest
from sqlalchemy import func, select
from tests.integration.test_ehr_reads import (
    action,
    review_body,
    revoke,
    verified,
)
from tests.integration.test_ehr_reads import ehr_case as _ehr_case
from tests.integration.test_ehr_reads import signed_workspace as _signed_workspace
from tests.unit.test_elation_lab_read import PATIENT, REPORT

from cosmas_os.application import ehr_reads as ehr
from cosmas_os.application import workspace as ws
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.ehr_read_models import EhrReadRequest

signed_workspace = _signed_workspace
ehr_case = _ehr_case


@pytest.fixture
def lab_case(ehr_case, monkeypatch):
    """The existing signed Elation visit fixture plus one entirely invented Lab report."""
    f = ehr_case
    monkeypatch.setattr(f.configuration, "workspace_elation_labs_enabled", True)
    monkeypatch.setattr(
        f.port, "_labs_enabled", lambda: f.configuration.workspace_elation_labs_enabled
    )
    f.patient = dict(deepcopy(PATIENT), id=930, caregiver_practice=910, primary_physician=920)
    f.patient_name = "Alex Éxample"
    f.provider.change_patient = lambda row: row | f.patient
    f.report = dict(deepcopy(REPORT), patient=930, practice=910, physician=920)
    f.other_report = dict(deepcopy(f.report), id=29, report_type="Imaging")
    f.lab_after = lambda: None
    f.lab_fail = False
    f.lab_page_extra = dict(count=2, next=None, previous=None)

    def handler(request):
        if request.url.path.startswith("/api/2.0/reports/"):
            assert not f.provider.session.in_transaction(), "No SQL transaction crosses report I/O"
            assert request.method == "GET" and request.url.host == "sandbox.elationemr.com"
            f.provider.calls.append((request.method, request.url.path))
            f.lab_after()
            if f.lab_fail:
                raise httpx.ReadTimeout("invented report failure", request=request)
            if request.url.path == "/api/2.0/reports/":
                assert dict(request.url.params) == dict(
                    patient="930", practice="910", limit="25", order_by="-document_date"
                )
                data = dict(results=[f.report, f.other_report], **f.lab_page_extra)
            else:
                assert request.url.path == f"/api/2.0/reports/{f.report['id']}/"
                assert not request.url.params
                data = f.report
            return httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                stream=httpx.ByteStream(json.dumps(data).encode()),
            )
        response = f.provider(request)
        # The same invented Patient endpoint is read by the async visit adapter
        # and the synchronous, streaming laboratory reader.
        return httpx.Response(
            response.status_code,
            headers=response.headers,
            stream=httpx.ByteStream(response.content),
        )

    monkeypatch.setattr(f.port, "_transport", httpx.MockTransport(handler))
    yield f


def body(f, parent, key="lab-reports-1", action_name="lab_reports", **changes):
    public = parent["observation"]
    item = public["item"] if public["kind"] == "verified_visit" else public["items"][0]
    return (
        dict(
            provider="elation",
            action=action_name,
            workspace_id=f.workspace["id"],
            connection_id=str(f.scope.connection_id),
            binding_sha256=f.scope.commitment(),
            observation_id=parent["observation_id"],
            observation_sha256=parent["source_sha256"],
            item_handle=item["handle"],
            item_sha256=item["sha256"],
            idempotency_key=key,
        )
        | changes
    )


def lab_reports(f, visit=None, **changes):
    parent = verified(f) if visit is None else visit
    response = action(f, body(f, parent, **changes))
    assert response.status_code == 200, response.text
    return response.json()


def lab_report(f, page=None, **changes):
    parent = lab_reports(f) if page is None else page
    response = action(
        f,
        body(
            f, parent, key=changes.pop("key", "lab-report-1"), action_name="lab_report", **changes
        ),
    )
    assert response.status_code == 200, response.text
    return response.json()


def lab_review(f, receipt, **changes):
    return f.client.post(
        f"/workspaces/{f.workspace['id']}/ehr-read/review",
        headers=f.headers(),
        json=review_body(f, receipt) | {"provider": "elation"} | changes,
    )


def test_signed_report_selection_review_recovery_and_exact_saved_source(lab_case):
    f = lab_case
    assert "labs" not in action(f, {"action": "status"}).json()
    assert (
        action(f, {"action": "status", "provider": "elation", "include_labs": True}).json()["labs"]
        == "available"
    )
    visit = verified(f)
    before = len(f.provider.calls)
    page = lab_reports(f, visit)
    assert len(f.provider.calls) == before + 5
    shown = page["observation"]
    assert shown["kind"] == "lab_reports" and shown["workspace_id"] == f.workspace["id"]
    assert shown["returned_report_count"] == 2 and shown["other_report_count"] == 1
    assert len(shown["items"]) == 1 and shown["reported_total"] == "2"
    assert "123456789012345678" not in json.dumps(shown["items"])
    receipt = lab_report(f, page)
    assert len(f.provider.calls) == before + 10
    public = receipt["observation"]
    assert public["kind"] == "verified_lab_report"
    assert public["item"]["handle"] == shown["items"][0]["handle"]
    assert public["parent"] == dict(
        observation_id=page["observation_id"],
        source_sha256=page["source_sha256"],
        item_sha256=shown["items"][0]["sha256"],
    )
    assert receipt["payload_sha256"] == payload_hash(public)
    assert public["item"]["sha256"] == ehr.item_hash("verified_lab_report", public["item"])
    assert '"id":123456789012345678' in public["item"]["report_json"]
    assert '"value":"001.2300"' in public["item"]["report_json"]
    calls = len(f.provider.calls)
    assert action(f, body(f, visit)).json() == page
    assert action(f, body(f, page, key="lab-report-1", action_name="lab_report")).json() == receipt
    for record in (page, receipt):
        assert (
            action(
                f,
                {
                    "action": "resolve",
                    "provider": "elation",
                    "idempotency_key": record["observation_key"],
                },
            ).json()
            == record
        )
        assert (
            action(
                f,
                {
                    "action": "inspect",
                    "provider": "elation",
                    "observation_id": record["observation_id"],
                },
            ).json()
            == record
        )
    assert len(f.provider.calls) == calls
    saved = lab_review(f, receipt)
    assert saved.status_code == 200, saved.text
    entry = next(
        e for e in saved.json()["workspace"]["entries"] if e["id"] == saved.json()["entry_id"]
    )
    assert entry["source_label"] == "Elation: reviewed laboratory report"
    assert entry["content"] == public["item"]["source_content"] == ehr.source_content(public)
    assert '"reference_min":"< 0.10"' in entry["content"]
    assert not saved.json()["source_withheld"]


def test_lab_capability_is_explicit_before_reservation_and_legacy_visit_remains(lab_case):
    f = lab_case
    f.configuration.workspace_elation_labs_enabled = False
    visit = verified(f)
    calls = len(f.provider.calls)
    response = action(f, body(f, visit))
    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "ehr_read_labs_unavailable"
    assert not f.s.scalar(select(EhrReadRequest).where(EhrReadRequest.kind == "lab_reports"))
    assert len(f.provider.calls) == calls


@pytest.mark.parametrize("kind", ["patient", "appointment"])
def test_changed_visit_identity_stops_before_report_discovery(lab_case, kind):
    f = lab_case
    visit = verified(f)
    if kind == "patient":
        f.patient["last_name"] = "Changed"
    else:
        f.provider.change_appointment = lambda row: row | {"duration": 45}
    response = action(f, body(f, visit))
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "ehr_read_" + kind + "_changed"
    assert not any(path.startswith("/api/2.0/reports/") for _, path in f.provider.calls)
    assert (
        action(
            f, {"action": "resolve", "provider": "elation", "idempotency_key": "lab-reports-1"}
        ).json()["status"]
        == "unconfirmed"
    )


def test_fresh_corrected_values_require_review_and_preserve_changed_selection_notice(lab_case):
    f = lab_case
    page = lab_reports(f)
    f.report["grids"][0]["results"][0]["value"] = "001.2400"
    receipt = lab_report(f, page)
    item = receipt["observation"]["item"]
    assert item["changed_since_selection"]
    assert '"value":"001.2400"' in item["source_content"]
    assert "Report fields changed after the candidate list was loaded" in item["source_content"]
    assert lab_review(f, receipt).status_code == 200


def test_unlinked_private_workspace_is_rejected_before_reserving_or_reading(lab_case):
    f = lab_case
    visit = verified(f)
    private = ws.create_private_draft(
        f.s, f.box, f.owner, "Invented private note", "lab-private-note"
    )
    f.s.commit()
    calls = len(f.provider.calls)
    before = f.s.scalar(select(func.count()).select_from(EhrReadRequest))
    f.s.commit()
    response = action(f, body(f, visit, workspace_id=private["id"]))
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "workspace_appointment_required"
    assert len(f.provider.calls) == calls
    assert f.s.scalar(select(func.count()).select_from(EhrReadRequest)) == before


@pytest.mark.parametrize("withdrawal", ["binding", "lab_flag", "ehr_flag"])
def test_saved_lab_source_is_withheld_when_current_authority_is_withdrawn(lab_case, withdrawal):
    f = lab_case
    receipt = lab_report(f)
    saved = lab_review(f, receipt)
    assert saved.status_code == 200, saved.text
    if withdrawal == "binding":
        revoke(f)
    else:
        setattr(
            f.configuration,
            "workspace_elation_labs_enabled"
            if withdrawal == "lab_flag"
            else "workspace_ehr_read_enabled",
            False,
        )
    calls = len(f.provider.calls)
    result = f.client.get(f"/workspaces/{f.workspace['id']}", headers=f.headers())
    assert result.status_code == 200, result.text
    entry = next(e for e in result.json()["entries"] if e["id"] == saved.json()["entry_id"])
    assert entry["content"] == "" and entry["ehr_source_state"] == "unavailable"
    assert len(f.provider.calls) == calls


def test_oversized_original_panel_is_unconfirmed_and_never_saved_as_a_partial_source(lab_case):
    f = lab_case
    f.report["grids"][0]["results"] *= 12
    page = lab_reports(f)
    response = action(f, body(f, page, key="oversized-report", action_name="lab_report"))
    assert response.status_code == 503, response.text
    assert response.json()["detail"] == "ehr_read_response_too_large"
    assert (
        action(
            f, {"provider": "elation", "action": "resolve", "idempotency_key": "oversized-report"}
        ).json()["status"]
        == "unconfirmed"
    )


def test_later_report_discovery_supersedes_earlier_workspace_selection(lab_case):
    f = lab_case
    visit = verified(f)
    first = lab_reports(f, visit)
    lab_reports(f, visit, key="new-report-page")
    calls = len(f.provider.calls)
    response = action(f, body(f, first, key="stale-report", action_name="lab_report"))
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "ehr_read_superseded"
    assert len(f.provider.calls) == calls
