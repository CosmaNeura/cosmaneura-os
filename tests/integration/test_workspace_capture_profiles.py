from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session
from tests.capture_profile_fixture import profile_packet
from tests.integration.test_workspace_capture_operations import capabilities, perform, prepare
from tests.integration.test_workspace_capture_operations import capture_case as capture_case
from tests.unit.test_core_capture_operations import packet

from cosmas_os.models import CoreCaptureAccount, ExternalIdentity, PatientLink
from cosmas_os.ports import capture_protocol as p


def prepare_profile(f):
    prepare(f)
    f.profile = p.CaptureProfileReceipt.model_validate(profile_packet(f.session_id))

    def operation(binding, credential, session, selected, key, *, capture_profile=None):
        if selected.kind in {"capture_profile", "select_capture_profile"}:
            assert capture_profile is None
            f.port.step("profile")
            return f.profile
        assert capture_profile == f.profile
        assert selected.profile_receipt_id == f.profile.receipt_id
        f.port.step("operation")
        if selected.kind == "reserve_chunks":
            return p.ReservationReceipt.model_validate(packet("reserve_chunks", UUID(f.session_id))[1])
        return p.LongVisitCapabilities.model_validate({**capabilities().model_dump(),
            "max_chunks": 720, "remaining_aggregate_plaintext_bytes": 268435456})

    f.port.perform_capture_operation = operation


def acknowledged(f, kind):
    operation = packet(kind, UUID(f.session_id))[0]
    return {**operation, "profile_receipt_id": str(f.profile.receipt_id)}


@pytest.mark.parametrize("kind", ["capabilities", "reserve_chunks"])
def test_profile_reads_are_reauthorized_before_acknowledged_operation(capture_case, kind):
    f = capture_case
    prepare_profile(f)
    response = perform(f, operation=acknowledged(f, kind))
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert f.port.calls == ["exchange", "resolve", "binding", "admit", "profile", "operation"]


def test_selection_gate_preserves_profile_recovery_and_acknowledged_operations(capture_case):
    f = capture_case
    prepare_profile(f)
    selection = {"kind": "select_capture_profile", "payload": f.profile.request.model_dump(mode="json")}
    assert not f.configuration.workspace_capture_long_visits_enabled
    assert perform(f, operation=selection).status_code == 404
    assert not f.port.calls
    f.configuration.workspace_capture_long_visits_enabled = True
    chosen = perform(f, operation=selection)
    assert chosen.status_code == 200
    assert chosen.json()["receipt"]["receipt_id"] == str(f.profile.receipt_id)
    f.configuration.workspace_capture_long_visits_enabled = False
    recovered = perform(f, operation={"kind": "capture_profile"})
    assert recovered.status_code == 200
    assert recovered.json()["receipt"] == chosen.json()["receipt"]
    assert perform(f, operation=acknowledged(f, "capabilities")).status_code == 200


@pytest.mark.parametrize("phase", ["profile", "operation"])
@pytest.mark.parametrize("target", ["identity", "account", "patient"])
@pytest.mark.parametrize("kind", ["capabilities", "reserve_chunks"])
def test_revocation_during_profile_or_operation_blocks_next_call_or_receipt(capture_case, phase, target, kind):
    f = capture_case
    prepare_profile(f)

    def revoke(observed):
        if observed != phase:
            return
        model, key = {"identity": (ExternalIdentity, f.identity_id),
            "account": (CoreCaptureAccount, f.account_id), "patient": (PatientLink, f.patient_link_id)}[target]
        with Session(f.engine) as session:
            row = session.get(model, key)
            if isinstance(row, ExternalIdentity):
                row.active = False
            else:
                row.revoked_at = datetime.now(UTC)
            session.commit()

    f.port.after = revoke
    response = perform(f, operation=acknowledged(f, kind))
    assert response.status_code in {403, 404, 409}
    assert "receipt" not in response.text
    assert f.port.calls == ["exchange", "resolve", "binding", "admit", "profile"] + (
        ["operation"] if phase == "operation" else [])


@pytest.mark.parametrize("fault", ["session", "id", "type"])
def test_wrong_profile_never_reaches_final_operation(capture_case, fault):
    f = capture_case
    prepare_profile(f)
    request = acknowledged(f, "reserve_chunks")
    f.profile = capabilities() if fault == "type" else f.profile.model_copy(update={
        "session_id" if fault == "session" else "receipt_id": uuid4()})
    response = perform(f, operation=request)
    assert response.status_code == 503 and response.json()["detail"] == "core_capture_receipt_invalid"
    assert f.port.calls[-1] == "profile" and "operation" not in f.port.calls
