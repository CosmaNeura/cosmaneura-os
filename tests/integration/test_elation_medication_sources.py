"""Signed medication-record read, exact recovery, patient binding and SQL source custody."""

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


def medication_row(**changes) -> dict:
    return dict(id=951, patient=930, practice=910,
        medication=dict(name="Invented medication", strength="10 mg", route="Oral", form="Tablet"),
        directions="Take one tablet\nwith food", medication_type="prescription", order_type="New",
        is_doc_med=False, signed_date="2025-01-02T09:00:00", deleted_date=None,
        thread=dict(dc_date=None, is_permanent=True), start_date="2025-01-02",
        document_date="2025-01-02T08:30:00+05:30") | changes


@pytest.fixture
def medication_case(ehr_case, monkeypatch):
    f = ehr_case
    monkeypatch.setattr(f.configuration, "workspace_elation_medications_enabled", True)
    monkeypatch.setattr(f.port, "_medications_enabled", lambda: f.configuration.workspace_elation_medications_enabled)
    f.medication_response = dict(count=1, results=[medication_row()], next=None, previous=None)
    f.medication_after = lambda: None

    def handler(request):
        if request.url.path == "/api/2.0/oauth2/token/":
            assert not f.provider.session.in_transaction()
            f.provider.calls.append((request.method, request.url.path))
            return httpx.Response(200, json=dict(access_token="invented-clinical-token", token_type="Bearer",
                expires_in=3600, scope=httpx.QueryParams(request.content.decode())["scope"]))
        if request.url.path == "/api/2.0/medications/":
            assert not f.provider.session.in_transaction()
            assert dict(request.url.params) == {"patient": "930", "practice": "910", "limit": "25"}
            f.provider.calls.append((request.method, request.url.path))
            f.medication_after()
            return httpx.Response(200, json=f.medication_response)
        return f.provider(request)

    monkeypatch.setattr(f.port, "_transport", httpx.MockTransport(handler))
    yield f


def body(f, visit, key="medication-read-1", **changes):
    item = visit["observation"]["item"]
    return dict(action="medications", connection_id=str(f.scope.connection_id), binding_sha256=f.scope.commitment(),
        observation_id=visit["observation_id"], observation_sha256=visit["source_sha256"],
        item_handle=item["handle"], item_sha256=item["sha256"], idempotency_key=key) | changes


def medication_read(f, visit=None, **changes):
    visit = verified(f) if visit is None else visit
    response = action(f, body(f, visit, **changes))
    assert response.status_code == 200, response.text
    return response.json()


def test_signed_medication_read_review_and_exact_recovery(medication_case):
    f = medication_case
    assert "medications" not in action(f, {"action": "status"}).json()
    assert action(f, {"action": "status", "include_medications": True}).json()["medications"] == "available"
    visit = verified(f)
    before = len(f.provider.calls)
    receipt = medication_read(f, visit)
    assert len(f.provider.calls) == before + 4  # Token, same appointment, same patient, one medication page.
    public = receipt["observation"]
    assert public["kind"] == "verified_medications"
    assert public["parent"] == dict(observation_id=visit["observation_id"], source_sha256=visit["source_sha256"],
        item_sha256=visit["observation"]["item"]["sha256"])
    assert public["item"]["medications"]["items"][0]["signature_state"] == "date_recorded"
    assert not any(key in json.dumps(public) for key in ('"patient_id"', '"medication_id"', '"synopsis"', '"dx"'))
    assert receipt["payload_sha256"] == payload_hash(public)
    assert public["item"]["sha256"] == ehr.item_hash("verified_medications", public["item"])
    calls = len(f.provider.calls)
    assert action(f, body(f, visit)).json() == receipt
    assert action(f, {"action": "resolve", "idempotency_key": "medication-read-1"}).json() == receipt
    assert action(f, {"action": "inspect", "observation_id": receipt["observation_id"]}).json() == receipt
    assert len(f.provider.calls) == calls
    saved = review(f, receipt)
    assert saved.status_code == 200, saved.text
    entry = next(e for e in saved.json()["workspace"]["entries"] if e["id"] == saved.json()["entry_id"])
    assert entry["source_label"] == "Elation: reviewed medication records"
    assert entry["content"] == ehr.source_content(public)
    assert "Signed date: 2025-01-02T09:00:00" in entry["content"]
    assert "Directions: Take one tablet\nwith food" in entry["content"]
    assert "not a reconciled current medication list" in entry["content"]
    assert not saved.json()["source_withheld"]


@pytest.mark.parametrize("capability", [False, True])
def test_medication_capability_is_explicit_and_old_appointment_read_remains(medication_case, capability):
    f = medication_case
    f.configuration.workspace_elation_medications_enabled = capability
    visit = verified(f)
    before = len(f.provider.calls)
    response = action(f, body(f, visit))
    assert response.status_code == (200 if capability else 404)
    if not capability:
        assert len(f.provider.calls) == before
        assert not f.s.scalar(select(EhrReadRequest).where(EhrReadRequest.kind == "medications"))
    assert action(f, {"action": "status", "include_medications": True}).json()["medications"] == ("available" if capability else "not_enabled")


@pytest.mark.parametrize("kind", ["patient", "appointment"])
def test_changed_verified_identity_refuses_before_medication_io_and_retains_exact_intent(medication_case, kind):
    f = medication_case
    visit = verified(f)
    if kind == "patient":
        f.provider.change_patient = lambda row: dict(row, last_name="Different")
    else:
        f.provider.change_appointment = lambda row: dict(row, duration=45)
    response = action(f, body(f, visit))
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "ehr_read_" + kind + "_changed"
    assert ("GET", "/api/2.0/medications/") not in f.provider.calls
    calls = len(f.provider.calls)
    resolved = action(f, {"action": "resolve", "idempotency_key": "medication-read-1"})
    assert resolved.json()["status"] == "unconfirmed"
    assert len(f.provider.calls) == calls


@pytest.mark.parametrize("mode", ["empty", "partial", "unknown"])
def test_empty_partial_and_unknown_are_distinct_reviewable_facts(medication_case, mode):
    f = medication_case
    if mode == "empty":
        f.medication_response = dict(results=[], count=0, next=None)
    elif mode == "partial":
        f.medication_response.update(count=2, next="https://sandbox.elationemr.com/api/2.0/medications/?offset=1")
    else:
        f.medication_response.pop("next")
    receipt = medication_read(f)
    expected = {"empty": "end_of_results", "partial": "more_rows_available", "unknown": "unknown"}[mode]
    assert receipt["observation"]["item"]["medications"]["coverage"] == expected
    response = review(f, receipt)
    assert response.status_code == 200, response.text
    content = ehr.source_content(receipt["observation"])
    if mode == "empty":
        assert "does not establish absence" in content
    if mode == "partial":
        assert "only this page was read" in content
    if mode == "unknown":
        assert "did not establish whether" in content


def test_oversize_projection_is_refused_not_truncated(medication_case):
    f = medication_case
    f.medication_response.update(count=25, results=[medication_row() | {"id": 1000+i, "directions": "A"*1000} for i in range(25)])
    visit = verified(f)
    response = action(f, body(f, visit))
    assert response.status_code == 503, response.text
    assert response.json()["detail"] == "ehr_read_response_too_large"
    assert action(f, {"action": "resolve", "idempotency_key": "medication-read-1"}).json()["status"] == "unconfirmed"


@pytest.mark.parametrize("tamper", ["patient", "state", "date", "directions", "extra", "parent", "private_identity", "coverage", "source_size", "unicode_blank", "flag", "proof_count"])
def test_sql_rejects_forged_medication_projection(medication_case, tamper):
    f = medication_case
    receipt = medication_read(f)
    snap = f.s.scalar(select(EhrReadSnapshot).where(EhrReadSnapshot.observation_id == receipt["observation_id"]))
    assert snap is not None
    value = deepcopy(snap.payload)
    item = value["public"]["item"]
    shown = item["medications"]["items"][0]
    private = value["private"]["medications"][0]
    if tamper == "patient":
        private["patient_id"] = "931"
    elif tamper == "state":
        shown["signature_state"] = private["signature_state"] = "no_date_recorded"
    elif tamper == "date":
        shown["signed_date"] = private["signed_date"] = "2025-02-30T09:00:00"
    elif tamper == "directions":
        shown["directions"] = private["directions"] = "contains\x1fcontrol"
    elif tamper == "extra":
        shown["active"] = private["active"] = True
    elif tamper == "parent":
        value["public"]["parent"]["source_sha256"] = "0"*64
    elif tamper == "private_identity":
        value["private"]["items"][0]["patient"]["last_name"] = "Different"
    elif tamper == "unicode_blank":
        shown["medication_name"] = private["medication_name"] = "\u2003"
    elif tamper == "coverage":
        item["medications"]["total_count"] = 99
    elif tamper == "flag":
        shown["is_doc_med"] = private["is_doc_med"] = "false"
    elif tamper == "proof_count":
        value["private"]["provider_sources"].pop()
    else:
        shown["directions"] = private["directions"] = "x"*5001
    item["sha256"] = ehr.item_hash("verified_medications", item)
    valid = f.s.execute(text("SELECT public.ehr_read_payload_valid(CAST(:payload AS jsonb),r) FROM ehr_read_requests r WHERE r.id=:rid"),
        {"payload": json.dumps(value), "rid": receipt["observation_id"]}).scalar_one()
    assert valid is False


def test_revoke_during_medication_io_withholds_result(medication_case):
    f = medication_case
    visit = verified(f)
    f.medication_after = lambda: revoke(f)
    response = action(f, body(f, visit))
    assert response.status_code in (409, 503), response.text
    assert "Invented medication" not in response.text
    assert f.s.scalar(select(EhrReadSnapshot).join(EhrReadRequest, EhrReadRequest.id == EhrReadSnapshot.observation_id)
        .where(EhrReadRequest.kind == "medications")) is None


def test_capability_withdrawal_withholds_saved_medication_source_but_not_visit(medication_case):
    f = medication_case
    visit = verified(f)
    receipt = medication_read(f, visit)
    saved = review(f, receipt)
    assert saved.status_code == 200, saved.text
    f.configuration.workspace_elation_medications_enabled = False
    response = action(f, {"action": "inspect", "observation_id": receipt["observation_id"]})
    assert response.status_code == 404 and "Invented medication" not in response.text
    assert action(f, {"action": "inspect", "observation_id": visit["observation_id"]}).status_code == 200
    replay = review(f, receipt)
    assert replay.status_code == 200 and replay.json()["source_withheld"]
    assert "Invented medication" not in json.dumps(replay.json()["workspace"])


def test_host_gate_masks_advertised_capability_even_if_mock_runtime_is_enabled(medication_case, monkeypatch):
    f = medication_case
    monkeypatch.setattr(f.port, "_medications_enabled", lambda: True)
    f.configuration.workspace_elation_medications_enabled = False
    response = action(f, {"action": "status", "include_medications": True})
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["medications"] == "not_enabled"
    assert "medications" not in action(f, {"action": "status"}).json()
    assert f.provider.calls == []


@pytest.mark.parametrize("state", ["absent", "null", "recorded"])
def test_provider_date_presence_is_preserved_without_current_status_inference(medication_case, state):
    f = medication_case
    row = medication_row()
    if state == "absent":
        row.pop("signed_date")
        row.pop("deleted_date")
        row.pop("thread")
    elif state == "null":
        row.update(signed_date=None, deleted_date=None, thread=dict(dc_date=None))
    else:
        row.update(signed_date="2024-02-29T23:59:59.123456-23:59", deleted_date="2024-03-01T00:00:00Z",
            thread=dict(dc_date="2024-02-29"))
    f.medication_response["results"] = [row]
    receipt = medication_read(f)
    shown = receipt["observation"]["item"]["medications"]["items"][0]
    expected = {"absent": "unknown", "null": "no_date_recorded", "recorded": "date_recorded"}[state]
    assert all(shown[name] == expected for name in ("signature_state", "discontinuation_state", "deletion_state"))
    assert "active" not in shown
    assert review(f, receipt).status_code == 200


def test_medication_child_cannot_be_used_as_a_new_clinical_parent(medication_case):
    f = medication_case
    receipt = medication_read(f)
    calls = len(f.provider.calls)
    response = action(f, body(f, receipt, key="medication-child-2"))
    assert response.status_code == 409, response.text
    assert len(f.provider.calls) == calls


def test_optional_empty_strings_and_multiline_directions_match_sql_source(medication_case):
    f = medication_case
    row = medication_row(directions="First line\r\n\tSecond line", order_type="", medication_type="discontinued")
    row["medication"].update(strength="", route=None, form=None)
    f.medication_response["results"] = [row]
    receipt = medication_read(f)
    saved = review(f, receipt)
    assert saved.status_code == 200, saved.text
    content = ehr.source_content(receipt["observation"])
    assert "Strength: (blank)" in content and "Medication type: discontinued" in content
    assert "First line\r\n\tSecond line" in content


def test_sql_refuses_whole_packet_over_limit_even_when_every_row_is_valid(medication_case):
    f = medication_case
    receipt = medication_read(f)
    snap = f.s.scalar(select(EhrReadSnapshot).where(EhrReadSnapshot.observation_id == receipt["observation_id"]))
    value = deepcopy(snap.payload)
    original = value["private"]["medications"][0]
    value["private"]["medications"] = [original | {"medication_id": str(1100+i), "directions": "x"*1000} for i in range(6)]
    listing = value["public"]["item"]["medications"]
    listing.update(total_count=6, items=[{k: v for k, v in row.items() if k not in ("medication_id", "patient_id", "practice_id")}
        for row in value["private"]["medications"]])
    item = value["public"]["item"]
    item["sha256"] = ehr.item_hash("verified_medications", item)
    assert len(ehr.source_content(value["public"])) > 5000
    valid = f.s.execute(text("SELECT public.ehr_read_payload_valid(CAST(:payload AS jsonb),r) FROM ehr_read_requests r WHERE r.id=:rid"),
        {"payload": json.dumps(value), "rid": receipt["observation_id"]}).scalar_one()
    assert valid is False


def test_sql_and_python_recorded_timestamp_validation_agree(medication_case):
    from pydantic import ValidationError
    from tests.unit.test_elation_medication_contract import display_row

    from cosmas_os.ports.ehr_reads import MedicationDisplay

    f = medication_case
    samples = ["2024-02-29T23:59:59", "2024-02-29T23:59:59.123456Z", "2024-02-29T23:59:59-23:59",
        "2024-02-29T23:59:59+00:60", "2024-02-29T23:59:59+24:00", "2024-02-29T23:59:60Z",
        "2025-02-29T23:59:59", "0000-01-01T00:00:00", "2024-02-29T23:59:59\n", "2024-02-29T23:59:59\r",
        "2024-02-29 23:59:59", "2024-02-29T23:59:59.1234567", "2024-02-29"]
    for stamp in samples:
        try:
            MedicationDisplay.model_validate(display_row(document_date=stamp))
            expected = True
        except ValidationError:
            expected = False
        actual = f.s.execute(text("SELECT public.ehr_medication_time(CAST(:value AS jsonb))"),
            {"value": json.dumps(stamp)}).scalar_one()
        assert actual is expected, repr(stamp)


def test_exact_source_cap_uses_canonical_timestamp_before_acceptance(medication_case, monkeypatch):
    from datetime import UTC, datetime

    f = medication_case
    original_adapter = f.port._adapter

    def precise_now():
        # Real current time, with a stable six-digit fractional representation.
        current = datetime.now(UTC)
        while current.microsecond == 0:
            current = datetime.now(UTC)
        return current

    def adapter(*args, **kwargs):
        result = original_adapter(*args, **kwargs)
        result.now = precise_now
        return result

    monkeypatch.setattr(f.port, "_adapter", adapter)
    visit = verified(f)
    sample = medication_read(f, visit)
    public = deepcopy(sample["observation"])
    listing = public["item"]["medications"]
    listing.update(total_count=4, items=[listing["items"][0] | {"directions": "x"} for _ in range(4)])
    remaining = 5000-len(ehr.source_content(public))
    assert 0 < remaining <= 3996
    for row in listing["items"]:
        added = min(999, remaining)
        row["directions"] += "x"*added
        remaining -= added
    assert remaining == 0 and len(ehr.source_content(public)) == 5000
    f.medication_response.update(count=4, results=[medication_row(id=1100+i, directions=row["directions"])
        for i, row in enumerate(listing["items"])])
    receipt = medication_read(f, visit, key="medication-exact-limit-2")
    assert len(ehr.source_content(receipt["observation"])) == 5000
    saved = review(f, receipt)
    assert saved.status_code == 200, saved.text
    for row in f.medication_response["results"]:
        if len(row["directions"]) < 1000:
            row["directions"] += "x"
            break
    response = action(f, body(f, visit, key="medication-over-limit-3"))
    assert response.status_code == 503, response.text
    assert response.json()["detail"] == "ehr_read_response_too_large"
