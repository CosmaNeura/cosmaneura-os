from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session
from tests.capture_source_fixture import source_packet
from tests.integration import test_workspace_capture as shared

from cosmas_os.models import CoreCaptureAccount, ExternalIdentity, PatientLink
from cosmas_os.ports.capture_source import CaptureSourceEnvelope

capture_case = shared.capture_case


def prepare(f):
    f.configuration.workspace_capture_source_enabled = True
    f.configuration.workspace_capture_notes_enabled = True
    f.configuration.workspace_capture_corrections_enabled = True
    assert shared.admit(f).status_code == 200
    f.session_id = str(f.port.saved.session_id)
    f.port.calls.clear()

    def operation(binding, credential, session_id, selected, key):
        assert str(session_id) == f.session_id
        f.port.step("operation")
        return CaptureSourceEnvelope.model_validate(source_packet(selected.kind, session_id)[1])

    f.port.perform_capture_operation = operation


def perform(f, kind="capture_source", **changes):
    operation, _ = source_packet(kind, f.session_id)
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


@pytest.mark.parametrize("kind", ["capture_source", "correct_capture_source"])
def test_qualified_source_uses_current_signed_workspace(capture_case, kind):
    f = capture_case
    prepare(f)
    response = perform(f, kind)
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert response.json()["receipt"]["capture_incomplete"] is True
    assert f.port.calls == ["exchange", "resolve", "binding", "admit", "operation"]


@pytest.mark.parametrize(
    "flag",
    [
        "workspace_capture_source_enabled",
        "workspace_capture_notes_enabled",
        "workspace_capture_corrections_enabled",
    ],
)
@pytest.mark.parametrize("kind", ["capture_source", "correct_capture_source"])
def test_unqualified_source_gate_never_calls_core(capture_case, flag, kind):
    f = capture_case
    prepare(f)
    setattr(f.configuration, flag, False)
    assert perform(f, kind).status_code == 404 and not f.port.calls


@pytest.mark.parametrize("kind", ["capture_source", "correct_capture_source"])
@pytest.mark.parametrize("phase", ["exchange", "resolve", "binding", "admit", "operation"])
@pytest.mark.parametrize("target", ["identity", "account", "patient"])
def test_revocation_before_source_disclosure_at_every_phase(capture_case, kind, phase, target):
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
    assert "receipt" not in response.text and "Invented" not in response.text
    assert (
        len(f.port.calls)
        == ["exchange", "resolve", "binding", "admit", "operation"].index(phase) + 1
    )
