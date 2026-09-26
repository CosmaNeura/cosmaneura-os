import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session
from tests.integration import test_workspace_capture as shared

from cosmas_os.models import CoreCaptureAccount, ExternalIdentity, PatientLink
from cosmas_os.ports.capture_working import CaptureWorkingTranscript

capture_case = shared.capture_case
GOLDEN = json.loads((Path(__file__).parents[1] / "fixtures/capture_working.json").read_text())


def prepare(f):
    f.configuration.workspace_capture_notes_enabled = True
    f.configuration.workspace_capture_corrections_enabled = True
    assert shared.admit(f).status_code == 200
    f.session_id = str(f.port.saved.session_id)
    f.port.calls.clear()
    def operation(binding, credential, session_id, selected, key):
        assert str(session_id) == f.session_id
        f.port.step("operation")
        value = {**GOLDEN["second" if selected.kind == "correct_transcript" else "base"], "session_id": f.session_id}
        return CaptureWorkingTranscript.model_validate(value)
    f.port.perform_capture_operation = operation


def perform(f, kind="correct_transcript", **changes):
    operation = {"kind": kind}
    if kind == "correct_transcript":
        operation["payload"] = GOLDEN["correction"]
    return f.client.post(f.path.replace("admission", "operations"),
        headers={"Authorization": "Bearer " + f.token()},
        json={"session_id":f.session_id, "idempotency_key":uuid4().hex, "operation":operation, **changes})


@pytest.mark.parametrize("kind", ["working_transcript", "correct_transcript"])
def test_working_operations_use_current_signed_workspace(capture_case, kind):
    f = capture_case
    prepare(f)
    result = perform(f, kind)
    assert result.status_code == 200 and result.headers["cache-control"] == "no-store"
    assert result.json()["session_id"] == f.session_id
    assert f.port.calls == ["exchange", "resolve", "binding", "admit", "operation"]


@pytest.mark.parametrize("flag", ["workspace_capture_notes_enabled", "workspace_capture_corrections_enabled"])
def test_disabled_corrections_do_not_call_core(capture_case, flag):
    f = capture_case
    prepare(f)
    setattr(f.configuration, flag, False)
    assert perform(f).status_code == 404 and not f.port.calls


@pytest.mark.parametrize("phase", ["exchange", "resolve", "binding", "admit", "operation"])
@pytest.mark.parametrize("target", ["identity", "account", "patient"])
def test_revocation_blocks_correction_phase_or_disclosure(capture_case, phase, target):
    f = capture_case
    prepare(f)
    def revoke(observed):
        if observed != phase:
            return
        with Session(f.engine) as db:
            model, key = {"identity":(ExternalIdentity,f.identity_id), "account":(CoreCaptureAccount,f.account_id), "patient":(PatientLink,f.patient_link_id)}[target]
            value = db.get(model,key)
            if target == "identity":
                value.active = False
            else:
                value.revoked_at = datetime.now(UTC)
            db.commit()
    f.port.after = revoke
    result = perform(f)
    assert result.status_code in {403,404,409}
    assert "receipt" not in result.text and "Invented corrected" not in result.text
    assert len(f.port.calls) == ["exchange","resolve","binding","admit","operation"].index(phase)+1


@pytest.mark.parametrize("fault", ["scope", "speaker", "base", "text", "size"])
def test_invalid_correction_never_reaches_core(capture_case, fault):
    f = capture_case
    prepare(f)
    operation = {"kind":"correct_transcript", "payload":json.loads(json.dumps(GOLDEN["correction"]))}
    if fault == "scope":
        operation["practitioner_id"] = "private_sentinel"
    elif fault == "speaker":
        operation["payload"]["corrections"][0]["speaker_role"] = "doctor"
    elif fault == "base":
        operation["payload"]["expected_working_version"] = True
    else:
        operation["payload"]["corrections"][0]["content"] = "private_sentinel\0" if fault == "text" else "x" * 1_048_577
    result = perform(f, operation=operation)
    assert result.status_code == 422 and not f.port.calls
    assert "private_sentinel" not in result.text
