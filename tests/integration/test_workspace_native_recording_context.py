from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session
from tests.integration.test_workspace_capture_operations import capture_case as capture_case
from tests.integration.test_workspace_capture_operations import perform, prepare

from cosmas_os.models import CoreCaptureAccount, ExternalIdentity, PatientLink
from cosmas_os.ports.capture_protocol import NativeRecordingContext
from cosmas_os.ports.core_capture import ConfiguredCaptureSelection


def prepare_context(f):
    prepare(f)
    f.port.saved = f.port.saved.model_copy(update={"configured_capture":
        ConfiguredCaptureSelection(schema_version="1.0", language_mode="en-US")})
    f.tenant_id = uuid4()

    def operation(binding, credential, session_id, selected, key):
        assert selected.kind == "native_recording_context" and str(session_id) == f.session_id
        f.port.step("operation")
        return NativeRecordingContext(schema_version="1.0", workspace_id=binding.workspace_id,
            tenant_id=f.tenant_id, session_id=session_id, status="capturing")

    f.port.perform_capture_operation = operation


def test_context_read_reauthorizes_same_configured_workspace(capture_case):
    f = capture_case
    prepare_context(f)
    response = perform(f, operation={"kind": "native_recording_context"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["receipt"] == {
        "schema_version": "1.0", "workspace_id": response.json()["workspace_id"],
        "session_id": f.session_id, "tenant_id": str(f.tenant_id), "status": "capturing"}
    assert f.port.calls == ["exchange", "resolve", "binding", "admit", "operation"]


def test_legacy_session_cannot_select_native_recording_context(capture_case):
    f = capture_case
    prepare(f)
    response = perform(f, operation={"kind": "native_recording_context"})
    assert response.status_code == 409
    assert response.json()["detail"] == "capture_source_unavailable"
    assert f.port.calls == ["exchange", "resolve", "binding", "admit"]


@pytest.mark.parametrize("target", ["identity", "account", "patient"])
def test_revocation_during_context_read_withholds_namespace(capture_case, target):
    f = capture_case
    prepare_context(f)

    def revoke(phase):
        if phase != "operation":
            return
        model, key = {"identity": (ExternalIdentity, f.identity_id),
            "account": (CoreCaptureAccount, f.account_id),
            "patient": (PatientLink, f.patient_link_id)}[target]
        with Session(f.engine) as session:
            row = session.get(model, key)
            if isinstance(row, ExternalIdentity):
                row.active = False
            else:
                row.revoked_at = datetime.now(UTC)
            session.commit()

    f.port.after = revoke
    response = perform(f, operation={"kind": "native_recording_context"})
    assert response.status_code in {403, 404, 409}
    assert "receipt" not in response.text and str(f.tenant_id) not in response.text


def test_client_cannot_choose_key_namespace(capture_case):
    f = capture_case
    prepare_context(f)
    response = perform(f, operation={"kind": "native_recording_context", "tenant_id": str(uuid4())})
    assert response.status_code == 422 and not f.port.calls


@pytest.mark.parametrize("fault", ["workspace", "session", "type"])
def test_unrelated_port_context_is_not_released(capture_case, fault):
    f = capture_case
    prepare_context(f)
    original = f.port.perform_capture_operation

    def incorrect(*args):
        value = original(*args)
        if fault == "type":
            return {"tenant_id": str(f.tenant_id)}
        return value.model_copy(update={fault + "_id": UUID("00000000-0000-4000-8000-000000000999")})

    f.port.perform_capture_operation = incorrect
    response = perform(f, operation={"kind": "native_recording_context"})
    assert response.status_code == 503 and "receipt" not in response.text
