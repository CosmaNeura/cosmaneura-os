"""Signed problem-list read, exact recovery, patient binding and SQL source custody."""

import json
from copy import deepcopy

import httpx
import pytest
from sqlalchemy import select, text
from tests.integration.test_ehr_reads import (
    action,
    review,
    revoke,
    verified,
)
from tests.integration.test_ehr_reads import (
    ehr_case as _ehr_case,
)
from tests.integration.test_ehr_reads import (
    signed_workspace as _signed_workspace,
)

from cosmas_os.application import ehr_reads as ehr
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.ehr_read_models import EhrReadRequest, EhrReadSnapshot

signed_workspace = _signed_workspace
ehr_case = _ehr_case


def problem_row(**changes):
    return dict(id=951, patient=930, practice=910, description="Invented chart concern",
        status="Active", start_date="2025-01-02", resolved_date=None,
        verification_status="unconfirmed", deleted_date=None, dx=[], synopsis="Excluded prose", **changes)


@pytest.fixture
def problem_case(ehr_case, monkeypatch):
    f = ehr_case
    monkeypatch.setattr(f.configuration, "workspace_elation_problems_enabled", True)
    monkeypatch.setattr(f.port, "_problems_enabled", lambda: f.configuration.workspace_elation_problems_enabled)
    f.problem_response = dict(count=1, results=[problem_row()], next=None, previous=None)
    f.problem_after = lambda: None

    def handler(request):
        if request.url.path == "/api/2.0/oauth2/token/":
            assert not f.provider.session.in_transaction()
            f.provider.calls.append((request.method, request.url.path))
            return httpx.Response(200, json=dict(access_token="invented-clinical-token", token_type="Bearer",
                expires_in=3600, scope=httpx.QueryParams(request.content.decode())["scope"]))
        if request.url.path == "/api/2.0/problems/":
            assert not f.provider.session.in_transaction()
            assert dict(request.url.params) == {"patient": "930", "practice": "910", "limit": "25"}
            f.provider.calls.append((request.method, request.url.path))
            f.problem_after()
            return httpx.Response(200, json=f.problem_response)
        return f.provider(request)

    monkeypatch.setattr(f.port, "_transport", httpx.MockTransport(handler))
    yield f


def body(f, visit, key="problem-read-1", **changes):
    item = visit["observation"]["item"]
    return dict(action="problems", connection_id=str(f.scope.connection_id), binding_sha256=f.scope.commitment(),
        observation_id=visit["observation_id"], observation_sha256=visit["source_sha256"],
        item_handle=item["handle"], item_sha256=item["sha256"], idempotency_key=key) | changes


def problem_read(f, visit=None, **changes):
    visit = verified(f) if visit is None else visit
    response = action(f, body(f, visit, **changes))
    assert response.status_code == 200, response.text
    return response.json()


def test_signed_problem_read_review_and_exact_recovery(problem_case):
    f = problem_case
    assert "problems" not in action(f, {"action": "status"}).json()
    assert action(f, {"action": "status", "include_problems": True}).json()["problems"] == "available"
    visit = verified(f)
    before = len(f.provider.calls)
    receipt = problem_read(f, visit)
    assert len(f.provider.calls) == before + 4  # Token, same appointment, same patient, one problem page.
    public = receipt["observation"]
    assert public["kind"] == "verified_problems"
    assert public["parent"] == dict(observation_id=visit["observation_id"], source_sha256=visit["source_sha256"],
        item_sha256=visit["observation"]["item"]["sha256"])
    assert public["item"]["problems"]["items"][0]["verification_status"] == "unconfirmed"
    assert not any(key in json.dumps(public) for key in ('"patient_id"', '"problem_id"', '"synopsis"', '"dx"'))
    assert receipt["payload_sha256"] == payload_hash(public)
    assert public["item"]["sha256"] == ehr.item_hash("verified_problems", public["item"])
    calls = len(f.provider.calls)
    assert action(f, body(f, visit)).json() == receipt
    assert action(f, {"action": "resolve", "idempotency_key": "problem-read-1"}).json() == receipt
    assert action(f, {"action": "inspect", "observation_id": receipt["observation_id"]}).json() == receipt
    assert len(f.provider.calls) == calls
    saved = review(f, receipt)
    assert saved.status_code == 200, saved.text
    entry = next(e for e in saved.json()["workspace"]["entries"] if e["id"] == saved.json()["entry_id"])
    assert entry["source_label"] == "Elation: reviewed problem list"
    assert entry["content"] == ehr.source_content(public)
    assert "Verification: unconfirmed" in entry["content"]
    assert "not confirmed diagnoses" in entry["content"]
    assert not saved.json()["source_withheld"]


@pytest.mark.parametrize("capability", [False, True])
def test_problem_capability_is_explicit_and_old_appointment_read_remains(problem_case, capability):
    f = problem_case
    f.configuration.workspace_elation_problems_enabled = capability
    visit = verified(f)
    before = len(f.provider.calls)
    response = action(f, body(f, visit))
    assert response.status_code == (200 if capability else 404)
    if not capability:
        assert len(f.provider.calls) == before
        assert not f.s.scalar(select(EhrReadRequest).where(EhrReadRequest.kind == "problems"))
    assert action(f, {"action": "status", "include_problems": True}).json()["problems"] == ("available" if capability else "not_enabled")


@pytest.mark.parametrize("kind", ["patient", "appointment"])
def test_changed_verified_identity_refuses_before_problem_io_and_retains_exact_intent(problem_case, kind):
    f = problem_case
    visit = verified(f)
    if kind == "patient":
        f.provider.change_patient = lambda row: dict(row, last_name="Different")
    else:
        f.provider.change_appointment = lambda row: dict(row, duration=45)
    response = action(f, body(f, visit))
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "ehr_read_" + kind + "_changed"
    assert ("GET", "/api/2.0/problems/") not in f.provider.calls
    calls = len(f.provider.calls)
    resolved = action(f, {"action": "resolve", "idempotency_key": "problem-read-1"})
    assert resolved.json()["status"] == "unconfirmed"
    assert len(f.provider.calls) == calls


@pytest.mark.parametrize("mode", ["empty", "partial", "unknown"])
def test_empty_partial_and_unknown_are_distinct_reviewable_facts(problem_case, mode):
    f = problem_case
    if mode == "empty":
        f.problem_response = dict(results=[], count=0, next=None)
    elif mode == "partial":
        f.problem_response.update(count=2, next="https://sandbox.elationemr.com/api/2.0/problems/?offset=1")
    else:
        f.problem_response.pop("next")
    receipt = problem_read(f)
    expected = {"empty": "end_of_results", "partial": "more_rows_available", "unknown": "unknown"}[mode]
    assert receipt["observation"]["item"]["problems"]["coverage"] == expected
    response = review(f, receipt)
    assert response.status_code == 200, response.text
    content = ehr.source_content(receipt["observation"])
    if mode == "empty":
        assert "does not establish absence" in content
    if mode == "partial":
        assert "only this page was read" in content
    if mode == "unknown":
        assert "did not establish whether" in content


def test_oversize_projection_is_refused_not_truncated(problem_case):
    f = problem_case
    f.problem_response.update(count=25, results=[problem_row() | {"id": 1000+i, "description": "A"*200} for i in range(25)])
    visit = verified(f)
    response = action(f, body(f, visit))
    assert response.status_code == 503, response.text
    assert response.json()["detail"] == "ehr_read_response_too_large"
    assert action(f, {"action": "resolve", "idempotency_key": "problem-read-1"}).json()["status"] == "unconfirmed"


@pytest.mark.parametrize("tamper", ["patient", "status", "verification", "parent", "private_identity", "coverage", "source_size", "unicode_blank"])
def test_sql_rejects_forged_clinical_projection(problem_case, tamper):
    f = problem_case
    receipt = problem_read(f)
    snap = f.s.scalar(select(EhrReadSnapshot).where(EhrReadSnapshot.observation_id == receipt["observation_id"]))
    assert snap is not None
    value = deepcopy(snap.payload)
    item = value["public"]["item"]
    if tamper == "patient":
        value["private"]["problems"][0]["patient_id"] = "931"
    elif tamper == "status":
        item["problems"]["items"][0]["status"] = "Diagnosed"
    elif tamper == "verification":
        item["problems"]["items"][0]["verification_status"] = "confirmed"
    elif tamper == "parent":
        value["public"]["parent"]["source_sha256"] = "0"*64
    elif tamper == "private_identity":
        value["private"]["items"][0]["patient"]["last_name"] = "Different"
    elif tamper == "unicode_blank":
        item["problems"]["items"][0]["description"] = "\u2003"
        value["private"]["problems"][0]["description"] = "\u2003"
    elif tamper == "coverage":
        item["problems"]["total_count"] = 99
    else:
        item["problems"]["items"][0]["description"] = "x"*5001
    item["sha256"] = ehr.item_hash("verified_problems", item)
    valid = f.s.execute(text("SELECT public.ehr_read_payload_valid(CAST(:payload AS jsonb),r) FROM ehr_read_requests r WHERE r.id=:rid"),
        {"payload": json.dumps(value), "rid": receipt["observation_id"]}).scalar_one()
    assert valid is False


def test_revoke_during_problem_io_withholds_result(problem_case):
    f = problem_case
    visit = verified(f)
    f.problem_after = lambda: revoke(f)
    response = action(f, body(f, visit))
    assert response.status_code in (409, 503), response.text
    assert "Invented chart concern" not in response.text
    assert f.s.scalar(select(EhrReadSnapshot).join(EhrReadRequest, EhrReadRequest.id == EhrReadSnapshot.observation_id)
        .where(EhrReadRequest.kind == "problems")) is None


def test_capability_withdrawal_withholds_saved_problem_source_but_not_visit(problem_case):
    f = problem_case
    visit = verified(f)
    receipt = problem_read(f, visit)
    saved = review(f, receipt)
    assert saved.status_code == 200, saved.text
    f.configuration.workspace_elation_problems_enabled = False
    response = action(f, {"action": "inspect", "observation_id": receipt["observation_id"]})
    assert response.status_code == 404 and "Invented chart concern" not in response.text
    assert action(f, {"action": "inspect", "observation_id": visit["observation_id"]}).status_code == 200
    replay = review(f, receipt)
    assert replay.status_code == 200 and replay.json()["source_withheld"]
    assert "Invented chart concern" not in json.dumps(replay.json()["workspace"])


def test_host_gate_masks_advertised_capability_even_if_mock_runtime_is_enabled(problem_case, monkeypatch):
    f = problem_case
    monkeypatch.setattr(f.port, "_problems_enabled", lambda: True)
    f.configuration.workspace_elation_problems_enabled = False
    response = action(f, {"action": "status", "include_problems": True})
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["problems"] == "not_enabled"
    assert "problems" not in action(f, {"action": "status"}).json()
    assert f.provider.calls == []
