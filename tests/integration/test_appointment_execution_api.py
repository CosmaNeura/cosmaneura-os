"""Exact signed commands exercise locked execution; HTTP receiver has separate wire proof."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from tests.integration.test_appointment_execution import Journal, claim, run, setup
from tests.integration.test_appointment_work import decide, prepare, propose
from tests.integration.test_scheduling_patient_setup import (
    InventedReceiver,
    confirm,
    confirmation,
    preview,
)
from tests.integration.test_workspace_auth import signed_workspace as _signed_workspace
from tests.unit.test_scheduling_actions import operation

from cosmas_os.api import app as api
from cosmas_os.application import scheduling_patient_setup as patient_setup
from cosmas_os.application import workspace as ws
from cosmas_os.models import AppointmentReceipt, Operation, SchedulingPatientAccount
from cosmas_os.ports.scheduling import SchedulingSelection
from cosmas_os.scheduling_login_models import SchedulingLoginCredential

signed_workspace = _signed_workspace


@pytest.mark.parametrize(
    "mode,error",
    [
        ("reconcile", "appointment_dispatch_required"),
        ("retry", "appointment_retry_requires_dispatch"),
    ],
)
def test_pending_operation_cannot_dispatch_through_recovery_mode(session, seeded, mode, error):
    case = setup(session, seeded)
    with pytest.raises(ws.WorkspaceError, match=error):
        run(session, case, mode=mode)
    op = session.get(Operation, case.approved["operation_id"])
    assert op.attempt_count == 0 and op.started_at is None and not case.port.calls


@pytest.mark.parametrize("field", ["operation_id", "revision_id", "digest"])
def test_exact_command_checked_before_active_claim_or_historical_replay(session, seeded, field):
    case = setup(session, seeded)
    wrong = {field: "f" * 64 if field == "digest" else str(uuid4())}
    for state in ("pending", "active", "saved"):
        with pytest.raises(ws.WorkspaceError, match="appointment_approval_changed"):
            run(session, case, **wrong)
        if state == "pending":
            first = claim(session, case, mode="submit")
            assert first
        elif state == "active":
            from cosmas_os.application import appointment_execution

            appointment_execution.record(
                session, first, case.port.result(first.operation), clock=lambda: case.port.now
            )
    assert not case.port.calls


def test_replayed_submit_never_retries_or_reconciles_uncertain_operation(session, seeded):
    case = setup(session, seeded)
    case.port.lose = True
    unknown = run(session, case, mode="submit")
    for _ in range(3):
        assert run(session, case, mode="submit") == unknown
    assert [kind for kind, _ in case.port.calls] == ["submit"]
    case.port.now += timedelta(minutes=6)
    saved = run(session, case, mode="reconcile")
    assert saved["appointment_saved"] and saved["operation_id"] == unknown["operation_id"]
    assert [kind for kind, _ in case.port.calls] == ["submit", "reconcile"]


@pytest.fixture
def signed_patient_case(session, signed_workspace):
    signed = signed_workspace
    signed.configuration.workspace_scheduling_enabled = True
    signed.configuration.workspace_appointments_enabled = True
    signed.configuration.workspace_scheduling_login_enabled = True
    signed.configuration.workspace_scheduling_patient_setup_enabled = True
    case = prepare(session, {"box_id": signed.box, "owner_id": signed.actor},
                   existing=signed, patient_mapping=False)
    connected = datetime.now(UTC)
    session.add(SchedulingLoginCredential(account_id=case.account, binding_digest="a" * 64,
        status="ready", sealed=b"i" * 40, connected_at=connected,
        expires_at=connected + timedelta(hours=1)))
    session.commit()
    fixture = SimpleNamespace(s=session, box=case.box, owner=case.owner, wid=case.wid,
        identity=case.identity, configuration=signed.configuration,
        before=ws.read(session, case.box, case.owner, case.wid))
    fixture.port = InventedReceiver(fixture)

    def binding(_session, identity_id, account):
        assert identity_id == case.identity and account.id == case.account
        return patient_setup.PatientSetupBinding(account_id=account.id,
            selection=SchedulingSelection.model_validate(dict(box_id=case.box, owner_id=case.owner,
                practice_id=account.practice_id, expected_actor_id=account.actor_id,
                practitioner_id=account.practitioner_id, location_id=account.location_id,
                appointment_type_id=account.appointment_type_id)),
            binding_sha256="a" * 64, connected_at=connected, grant_sha256="b" * 64)

    with patient_setup.install_binding_reader(binding):
        observed = preview(fixture)
        saved = confirm(fixture, confirmation(fixture, observed))
        assert saved["status"] == "saved" and not saved["source_withheld"]
        case.patient = saved["mapping"]["mapping_id"]
        patient = session.get(SchedulingPatientAccount, case.patient)
        assert patient is not None
        case.selection = case.selection.model_copy(update={"patient_id": UUID(patient.patient_id)})
        yield signed, case


@pytest.fixture
def signed_case(session, signed_patient_case):
    signed, case = signed_patient_case
    now = datetime.now(UTC)
    original = operation(case.selection).intent
    assert original.slot is not None
    intent = original.model_copy(
        update={
            "expires_at": now + timedelta(minutes=3),
            "google": original.google.model_copy(update={"checked_at": now}),
            "slot": original.slot.model_copy(update={
                "starts_at": now + timedelta(days=2),
                "ends_at": now + timedelta(days=2, minutes=30),
            }),
        }
    )
    case.item = propose(session, case, intent=intent, now=now)
    case.approved = decide(session, case, case.item, now=now)
    case.port = Journal()
    case.port.now = now
    case.path = f"/workspaces/{case.wid}/appointments/{case.item['ticket_id']}/execute"
    case.headers = {"Authorization": "Bearer " + signed.token()}
    case.body = {
        "operation_id": case.approved["operation_id"],
        "revision_id": case.item["revision_id"],
        "payload_hash": case.item["payload_hash"],
        "mode": "submit",
    }
    api.app.dependency_overrides[api._appointment_connection] = lambda: case.port
    try:
        yield signed, case
    finally:
        api.app.dependency_overrides.pop(api._appointment_connection, None)


@pytest.mark.parametrize("signed_workspace", ["apple", "desktop"], indirect=True)
def test_signed_execution_and_explicit_calendar_read_preserve_same_effect(session, signed_case):
    signed, case = signed_case

    def request(body):
        return signed.client.post(case.path, headers=case.headers, json=body)

    first = request(case.body)
    assert first.status_code == 200 and first.headers["cache-control"] == "no-store", first.json()
    saved = first.json()
    assert (
        saved["appointment_saved"]
        and saved["calendar_state"] == "pending"
        and saved["state"] == "sent"
    )
    assert request(case.body).json() == saved and len(case.port.calls) == 1
    case.port.now = datetime.now(UTC)
    case.port.calendar = "synced"
    second = request({**case.body, "mode": "reconcile"})
    assert second.status_code == 200 and second.json()["calendar_state"] == "synced"
    assert second.json()["result"]["appointment"] == saved["result"]["appointment"]
    assert [kind for kind, _ in case.port.calls] == ["submit", "reconcile"]


@pytest.mark.parametrize(
    "fault", ["extra", "mode", "digest", "missing", "oversized", "duplicate", "disabled", "expired"]
)
def test_bad_or_unauthorized_execution_request_does_no_io(session, signed_case, fault):
    signed, case = signed_case
    body = dict(case.body)
    headers = dict(case.headers)
    content = None
    expected = 422
    if fault == "extra":
        body["private_result"] = "PRIVATE"
    elif fault == "mode":
        body["mode"] = "automatic"
    elif fault == "digest":
        body["payload_hash"] = "0" * 64
        expected = 409
    elif fault == "missing":
        body.pop("operation_id")
    elif fault == "oversized":
        content = json.dumps(body).encode().ljust(2049, b" ")
        expected = 422
    elif fault == "duplicate":
        content = b'{"mode":"submit","mode":"retry"}'
        expected = 422
    elif fault == "disabled":
        signed.configuration.workspace_appointments_enabled = False
        expected = 404
    elif fault == "expired":
        headers["Authorization"] = "Bearer " + signed.token(
            exp=datetime.now(UTC) - timedelta(minutes=1)
        )
        expected = 401
    if content is not None:
        headers["Content-Type"] = "application/json"
    response = signed.client.post(
        case.path, headers=headers, **({"content": content} if content else {"json": body})
    )
    assert response.status_code == expected, response.text
    assert "PRIVATE" not in response.text and not case.port.calls
    assert session.get(Operation, case.approved["operation_id"]).attempt_count == 0


def test_expired_auth_after_slow_body_is_rechecked_before_claim(session, signed_case, monkeypatch):
    signed, case = signed_case
    original = api.read_capture_request

    async def slow_body(request, schema, **kwargs):
        result = await original(request, schema, **kwargs)

        def expired(**kwargs):
            raise HTTPException(401, "authentication_required")

        monkeypatch.setattr(api, "_identity", expired)
        return result

    monkeypatch.setattr(api, "read_capture_request", slow_body)
    response = signed.client.post(case.path, headers=case.headers, json=case.body)
    assert response.status_code == 401 and not case.port.calls
    assert session.get(Operation, case.approved["operation_id"]).attempt_count == 0


def test_revoked_signed_identity_during_io_retains_receipt_but_returns_no_private_result(
    session, signed_case
):
    signed, case = signed_case

    def revoke():
        signed.binding.active = False
        session.commit()

    case.port.after = revoke
    response = signed.client.post(case.path, headers=case.headers, json=case.body)
    assert (
        response.status_code == 403
        and "patient_id" not in response.text
        and "appointment_saved" not in response.text
    )
    op = session.get(Operation, case.approved["operation_id"])
    assert op.status == "succeeded" and op.attempt_count == 1
    assert session.scalar(
        select(AppointmentReceipt.id).where(AppointmentReceipt.operation_id == op.id)
    )
