"""Recovery operations retain the current signed private-workspace boundary."""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session
from tests.integration import test_workspace_capture as shared

from cosmas_os.models import CoreCaptureAccount, ExternalIdentity, PatientLink
from cosmas_os.ports.capture_limits import MAX_CAPTURE_CHUNKS
from cosmas_os.ports.capture_recovery import (
    CaptureRecoveryReceipt,
    CaptureRecoveryRequest,
    CaptureRecoveryState,
)
from cosmas_os.ports.capture_working import canonical_hash

capture_case = shared.capture_case
FIXTURE = Path(__file__).parents[1] / "fixtures/capture_recovery.json"


def prepare(f):
    f.configuration.workspace_capture_recovery_enabled = True
    assert shared.admit(f).status_code == 200
    f.session_id = str(f.port.saved.session_id)
    f.port.calls.clear()

    def operation(binding, credential, session_id, selected, key):
        assert str(session_id) == f.session_id
        f.port.step("operation")
        fixture = json.loads(FIXTURE.read_text())
        receipt = fixture["receipt"]
        receipt["session_id"] = f.session_id
        receipt["lease"]["session_id"] = f.session_id
        if selected.kind == "recover_capture":
            receipt["request"] = selected.payload.model_dump(mode="json")
            receipt["request_sha256"] = canonical_hash(selected.payload)
            receipt["lease"]["lease_id"] = str(selected.payload.capture_lease_id)
            receipt["lease"]["generation"] = selected.payload.capture_lease_generation + 1
            if selected.payload.decision == "finish_capture":
                receipt["following_segment_id"] = None
            return CaptureRecoveryReceipt.model_validate(receipt)
        current = fixture["state"]
        current["history"] = {"session_id": f.session_id, "recoveries": [receipt]}
        current["current_lease"] = receipt["lease"]
        return CaptureRecoveryState.model_validate(current)

    f.port.perform_capture_operation = operation


def perform(f, kind="recover_capture", **changes):
    operation = {"kind": kind}
    if kind == "recover_capture":
        operation["payload"] = json.loads(FIXTURE.read_text())["request"]
    return f.client.post(
        f.path.replace("admission", "operations"),
        headers={"Authorization": "Bearer " + f.token()},
        json={
            "session_id": f.session_id,
            "idempotency_key": uuid4().hex,
            "operation": operation,
            **changes,
        },
    )


@pytest.mark.parametrize("kind", ["recover_capture", "capture_recovery_state"])
def test_recovery_uses_current_signed_workspace(capture_case, kind):
    f = capture_case
    prepare(f)
    response = perform(f, kind)
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert response.json()["session_id"] == f.session_id
    assert f.port.calls == ["exchange", "resolve", "binding", "admit", "operation"]


@pytest.mark.parametrize("kind", ["recover_capture", "capture_recovery_state"])
def test_dark_recovery_flag_calls_no_core(capture_case, kind):
    f = capture_case
    prepare(f)
    f.configuration.workspace_capture_recovery_enabled = False
    assert perform(f, kind).status_code == 404 and not f.port.calls


@pytest.mark.parametrize("kind", ["recover_capture", "capture_recovery_state"])
@pytest.mark.parametrize("phase", ["exchange", "resolve", "binding", "admit", "operation"])
@pytest.mark.parametrize("target", ["identity", "account", "patient"])
def test_revocation_at_any_phase_prevents_recovery_disclosure(capture_case, kind, phase, target):
    f = capture_case
    prepare(f)

    def revoke(observed):
        if observed != phase:
            return
        with Session(f.engine) as db:
            model, key = {
                "identity": (ExternalIdentity, f.identity_id),
                "account": (CoreCaptureAccount, f.account_id),
                "patient": (PatientLink, f.patient_link_id),
            }[target]
            value = db.get(model, key)
            if target == "identity":
                value.active = False
            else:
                value.revoked_at = datetime.now(UTC)
            db.commit()

    f.port.after = revoke
    response = perform(f, kind)
    assert response.status_code in {403, 404, 409}
    assert "receipt" not in response.text
    assert (
        len(f.port.calls)
        == ["exchange", "resolve", "binding", "admit", "operation"].index(phase) + 1
    )


@pytest.mark.parametrize("fault", ["scope", "boolean", "sequence", "decision"])
def test_invalid_recovery_never_reaches_core(capture_case, fault):
    f = capture_case
    prepare(f)
    payload = json.loads(FIXTURE.read_text())["request"]
    if fault == "scope":
        payload["practitioner_id"] = "private_sentinel"
    elif fault == "boolean":
        payload["capture_lease_generation"] = True
    elif fault == "sequence":
        payload["next_sequence_number"] = MAX_CAPTURE_CHUNKS + 1
    else:
        payload["decision"] = "private_sentinel"
    response = perform(f, operation={"kind": "recover_capture", "payload": payload})
    assert response.status_code == 422 and not f.port.calls
    assert "private_sentinel" not in response.text


@pytest.mark.parametrize("next_sequence,decision", [
    (1001, "resume_capture"),
    (MAX_CAPTURE_CHUNKS - 1, "resume_capture"),
    (MAX_CAPTURE_CHUNKS, "finish_capture"),
])
def test_current_recovery_boundaries_keep_exact_signed_request(capture_case, next_sequence, decision):
    f = capture_case
    prepare(f)
    payload = json.loads(FIXTURE.read_text())["request"]
    payload.update(next_sequence_number=next_sequence, decision=decision)
    response = perform(f, operation={"kind": "recover_capture", "payload": payload})
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    receipt = response.json()["receipt"]
    assert receipt["request"] == payload
    assert receipt["request_sha256"] == canonical_hash(CaptureRecoveryRequest.model_validate(payload))
    assert receipt["review_state"] == "required"
    assert f.port.calls == ["exchange", "resolve", "binding", "admit", "operation"]


@pytest.mark.parametrize("changes", [
    {"next_sequence_number": MAX_CAPTURE_CHUNKS, "decision": "resume_capture"},
    {"first_sequence_number": MAX_CAPTURE_CHUNKS, "next_sequence_number": MAX_CAPTURE_CHUNKS,
     "decision": "finish_capture"},
    {"segment_ordinal": 1000},
])
def test_current_recovery_endpoint_and_segment_bounds_call_no_core(capture_case, changes):
    f = capture_case
    prepare(f)
    payload = json.loads(FIXTURE.read_text())["request"]
    payload.update(changes)
    response = perform(f, operation={"kind": "recover_capture", "payload": payload})
    assert response.status_code == 422 and not f.port.calls
