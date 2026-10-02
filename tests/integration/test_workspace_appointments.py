from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from tests.integration.test_appointment_work import prepare as setup_approval
from tests.integration.test_workspace_auth import signed_workspace as _signed_workspace

from cosmas_os.api import app as api
from cosmas_os.api.capture_schemas import CaptureBotSelection
from cosmas_os.api.scheduling_schemas import AppointmentPrepare
from cosmas_os.application import appointment_work as work
from cosmas_os.application import provider_team as team
from cosmas_os.application import services as svc
from cosmas_os.application import workspace as ws
from cosmas_os.application import workspace_appointments as prep
from cosmas_os.models import (
    AppointmentObservation,
    AppointmentWork,
    EncounterWorkspace,
    ExternalIdentity,
    SchedulingAccount,
    SchedulingPatientAccount,
)
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.scheduling import (
    AvailabilitySlot,
    GoogleCalendarCoverage,
    GoogleSchedulingAvailability,
)
from cosmas_os.ports.scheduling_actions import AppointmentSnapshot, ObservedAppointment

signed_workspace = _signed_workspace


class LocalReader:
    def __init__(self, case):
        self.case = case
        self.calls = []
        self.after = lambda: None
        self.fault = None

    def read_appointment(self, selected, aid):
        self.calls.append("appointment")
        self.after()
        now = datetime.now(UTC)
        result = ObservedAppointment(selection=selected, observed_at=now, appointment=AppointmentSnapshot(
            id=aid, version=3, status="confirmed",
            **{name: getattr(selected, name) for name in ("patient_id", "practitioner_id", "location_id", "appointment_type_id")},
            starts_at=now + timedelta(days=1), ends_at=now + timedelta(days=1, minutes=30)))
        if self.fault == "appointment":
            return result.model_copy(update={"appointment": result.appointment.model_copy(update={"patient_id": uuid4()})})
        if self.fault == "stale":
            return result.model_copy(update={"observed_at": now - timedelta(minutes=2)})
        return result

    def verified_availability(self, selected, window):
        self.calls.append("availability")
        self.after()
        now = datetime.now(UTC)
        if self.fault == "unavailable":
            raise ConnectorUnavailable("PRIVATE")
        return GoogleSchedulingAvailability(selection=selected, window=window,
            slots=() if self.fault == "missing_slot" else (AvailabilitySlot(starts_at=window.starts_at, ends_at=window.ends_at),),
            observed_at=now, google=GoogleCalendarCoverage(provider="google", calendar_id="primary",
                connection_id=self.case.connection_id, connected_at=now-timedelta(days=2),
                checked_at=now-timedelta(minutes=2) if self.fault == "google" else now))


def setup(s, seed, existing=None, *, patient_mapping=True):
    case = setup_approval(s, seed, existing=existing, patient_mapping=patient_mapping)
    team.save(s, case.box, case.owner, expected=0, key="appointment-team", configuration=team.default_configuration())
    case.bot = CaptureBotSelection(address="follow_up", team_revision=1)
    case.connection_id = uuid4()
    case.remote_appointment = uuid4()
    wid = s.get(EncounterWorkspace, case.wid)
    observation = s.get(AppointmentObservation, wid.appointment_id)
    observation.source = prep.SCHEDULING_SOURCE
    observation.external_id = str(case.remote_appointment)
    s.commit()
    case.port = LocalReader(case)
    return case


@pytest.fixture
def case(session, seeded):
    return setup(session, seeded)


def command(case, action="book", **changes):
    now = datetime.now(UTC)
    return AppointmentPrepare.model_validate({"bot": case.bot.model_dump(), "action": action, "share": True,
        "slot": None if action == "cancel" else {"starts_at": now+timedelta(days=2), "ends_at": now+timedelta(days=2, minutes=30)},
        "idempotency_key": str(uuid4()), **changes})


def prepare(s, case, body, reauthenticate=lambda: None):
    return prep.prepare(s, box=case.box, owner=case.owner, workspace_id=case.wid, external_identity_id=case.identity,
                        body=body, appointment_port=case.port, availability_port=case.port, reauthenticate=reauthenticate)


@pytest.mark.parametrize("action", ["book", "reschedule", "cancel"])
def test_fresh_sources_prepare_exact_proposal_and_lost_reply_recovers_without_reread(session, case, action):
    body = command(case, action)
    item = prepare(session, case, body)
    calls = list(case.port.calls)
    assert item["state"] == "pending_approval" and item["operation_id"] is None
    assert item["intent"]["action"] == action and item["intent"]["selection"]["patient_id"] == str(case.selection.patient_id)
    assert calls == (["availability"] if action == "book" else ["appointment"] if action == "cancel" else ["appointment", "availability"])
    assert prepare(session, case, body) == item and case.port.calls == calls
    assert session.scalar(select(func.count()).select_from(AppointmentWork).where(AppointmentWork.workspace_id == case.wid)) == 1


def test_changed_command_same_key_cannot_replace_proposal(session, case):
    body = command(case)
    item = prepare(session, case, body)
    changed = command(case, "cancel", idempotency_key=body.idempotency_key)
    with pytest.raises(ws.WorkspaceError, match="idempotency_conflict"):
        prepare(session, case, changed)
    assert work.read(session, case.box, case.owner, case.wid, item["ticket_id"]) == item


@pytest.mark.parametrize("fault,action", [("appointment", "cancel"), ("stale", "reschedule"), ("google", "book"), ("missing_slot", "book"), ("unavailable", "book")])
def test_invalid_sources_do_not_create_proposals(session, case, fault, action):
    case.port.fault = fault
    with pytest.raises(ws.WorkspaceError, match="scheduling_unavailable"):
        prepare(session, case, command(case, action))
    assert not session.scalar(select(AppointmentWork.ticket_id).where(AppointmentWork.workspace_id == case.wid))


@pytest.mark.parametrize("fault", ["bot", "source", "mapping", "identity"])
def test_missing_authority_prevents_receiver_reads(session, case, fault):
    if fault == "bot":
        case.bot = case.bot.model_copy(update={"team_revision": 2})
    elif fault == "source":
        w = session.get(EncounterWorkspace, case.wid)
        session.get(AppointmentObservation, w.appointment_id).source = "unreviewed"
    elif fault == "mapping":
        session.get(SchedulingPatientAccount, case.patient).revoked_at = datetime.now(UTC)
    else:
        session.get(ExternalIdentity, case.identity).active = False
    session.commit()
    with pytest.raises(ws.WorkspaceError):
        prepare(session, case, command(case, "cancel"))
    assert case.port.calls == []


@pytest.mark.parametrize("target", ["account", "patient", "bot", "observation"])
def test_no_local_locks_during_io_and_intervening_revocation_discards_proposal(engine, target):
    with Session(engine) as s:
        case = setup(s, svc.provision_box(svc.Container(s), "Invented source race"))

        def revoke():
            with Session(engine) as other:
                other.execute(text("SET LOCAL lock_timeout = '1s'"))
                if target == "account":
                    other.get(SchedulingAccount, case.account).revoked_at = datetime.now(UTC)
                elif target == "patient":
                    other.get(SchedulingPatientAccount, case.patient).revoked_at = datetime.now(UTC)
                elif target == "observation":
                    w = other.get(EncounterWorkspace, case.wid)
                    other.get(AppointmentObservation, w.appointment_id).external_id = str(uuid4())
                else:
                    saved = team.read(other, case.box, case.owner)
                    config = deepcopy(saved["configuration"])
                    config["bots"][2]["enabled"] = False
                    team.save(other, case.box, case.owner, expected=saved["revision"], key="pause-appointment", configuration=config)
                other.commit()
        case.port.after = revoke
        with pytest.raises(ws.WorkspaceError):
            prepare(s, case, command(case))
        assert not s.scalar(select(AppointmentWork.ticket_id).where(AppointmentWork.workspace_id == case.wid))


def test_current_appointment_is_derived_from_workspace_not_client_selector(session, case):
    result = prep.read_current(session, box=case.box, owner=case.owner, workspace_id=case.wid,
        external_identity_id=case.identity, bot=case.bot, port=case.port, reauthenticate=lambda: None)
    assert UUID(result["appointment"]["id"]) == case.remote_appointment
    assert result["workspace_id"] == case.wid
    w = session.get(EncounterWorkspace, case.wid)
    session.get(AppointmentObservation, w.appointment_id).source = "unreviewed"
    session.commit()
    result = prep.read_current(session, box=case.box, owner=case.owner, workspace_id=case.wid,
        external_identity_id=case.identity, bot=case.bot, port=case.port, reauthenticate=lambda: None)
    assert result["appointment"] is None and case.port.calls == ["appointment"]


def test_paginated_history_retains_pending_and_withdrawn_work(session, case):
    expected = []
    for _ in range(21):
        expected.append(prepare(session, case, command(case))["ticket_id"])
    first = work.catalog(session, case.box, case.owner, case.wid)
    assert len(first["items"]) == 20 and first["next_cursor"]
    second = work.catalog(session, case.box, case.owner, case.wid, cursor=first["next_cursor"])
    assert len(second["items"]) == 1 and second["next_cursor"] is None
    assert {x["ticket_id"] for x in first["items"] + second["items"]} == set(expected)
    for summary in first["items"] + second["items"]:
        item = work.read(session, case.box, case.owner, case.wid, summary["ticket_id"])
        assert {name: datetime.fromisoformat(value) for name, value in summary["appointment_window"].items()} == {
            name: datetime.fromisoformat(value) for name, value in item["intent"]["slot"].items()}


@pytest.mark.parametrize("signed_workspace", ["apple", "desktop"], indirect=True)
def test_signed_api_preparation_catalog_current_review_and_withdrawal(session, signed_workspace):
    signed = signed_workspace
    signed.configuration.workspace_scheduling_enabled = True
    signed.configuration.workspace_appointments_enabled = True
    signed.configuration.workspace_scheduling_login_enabled = True
    signed.configuration.workspace_scheduling_patient_setup_enabled = True
    case = setup(session, {"box_id": signed.box, "owner_id": signed.actor}, existing=signed, patient_mapping=False)
    from tests.integration.test_scheduling_patient_setup import install_personal_fixture

    account = session.get(SchedulingAccount, case.account)
    assert account is not None
    api.app.dependency_overrides[api._scheduling_connection] = lambda: case.port
    api.app.dependency_overrides[api._appointment_connection] = lambda: case.port
    try:
        with install_personal_fixture(session, box=case.box, owner=case.owner, wid=case.wid,
                identity_id=case.identity, account=account, configuration=signed.configuration,
                patient_id=str(case.selection.patient_id)) as mapping_receipt:
            case.patient = mapping_receipt["mapping"]["mapping_id"]
            path = f"/workspaces/{case.wid}/appointments"
            headers = {"Authorization": "Bearer " + signed.token()}
            current = signed.client.post(path + "/current", headers=headers, json={"bot": case.bot.model_dump()})
            assert current.status_code == 200, current.text
            body = command(case, "reschedule").model_dump(mode="json")
            proposed = signed.client.post(path, headers=headers, json=body)
            assert proposed.status_code == 200, proposed.text
            item = proposed.json()
            assert signed.client.post(path, headers=headers, json=body).json() == item
            assert signed.client.get(path, headers=headers).json()["items"][0]["ticket_id"] == item["ticket_id"]
            chosen = {"revision_id": item["revision_id"], "payload_hash": item["payload_hash"], "choice": "approve"}
            assert signed.client.post(path + "/" + item["ticket_id"] + "/decide", headers=headers, json=chosen).json()["state"] == "approved"
            chosen["choice"] = "reject"
            assert signed.client.post(path + "/" + item["ticket_id"] + "/decide", headers=headers, json=chosen).json()["state"] == "rejected"
            for bad in ({"patient_id": str(uuid4())}, {"appointment_id": str(uuid4())}, {"intent": {"private": "PRIVATE"}}):
                response = signed.client.post(path, headers=headers, json={**body, **bad})
                assert response.status_code == 422 and "PRIVATE" not in response.text
    finally:
        api.app.dependency_overrides.pop(api._scheduling_connection, None)
        api.app.dependency_overrides.pop(api._appointment_connection, None)


@pytest.mark.parametrize("current", [False, True])
def test_disabling_appointments_during_source_read_discards_result(session, signed_workspace, current):
    signed = signed_workspace
    signed.configuration.workspace_scheduling_enabled = True
    signed.configuration.workspace_appointments_enabled = True
    signed.configuration.workspace_scheduling_login_enabled = True
    signed.configuration.workspace_scheduling_patient_setup_enabled = True
    case = setup(session, {"box_id": signed.box, "owner_id": signed.actor}, existing=signed, patient_mapping=False)
    from tests.integration.test_scheduling_patient_setup import install_personal_fixture

    account = session.get(SchedulingAccount, case.account)
    assert account is not None
    case.port.after = lambda: setattr(signed.configuration, "workspace_appointments_enabled", False)
    api.app.dependency_overrides[api._scheduling_connection] = lambda: case.port
    api.app.dependency_overrides[api._appointment_connection] = lambda: case.port
    try:
        with install_personal_fixture(session, box=case.box, owner=case.owner, wid=case.wid,
                identity_id=case.identity, account=account, configuration=signed.configuration,
                patient_id=str(case.selection.patient_id)) as mapping_receipt:
            case.patient = mapping_receipt["mapping"]["mapping_id"]
            path = f"/workspaces/{case.wid}/appointments" + ("/current" if current else "")
            body = {"bot": case.bot.model_dump()} if current else command(case).model_dump(mode="json")
            result = signed.client.post(path, headers={"Authorization": "Bearer " + signed.token()}, json=body)
            assert result.status_code == 404
            assert "patient_id" not in result.text and "appointment" not in result.text
            assert not session.scalar(select(AppointmentWork.ticket_id).where(AppointmentWork.workspace_id == case.wid))
    finally:
        api.app.dependency_overrides.pop(api._scheduling_connection, None)
        api.app.dependency_overrides.pop(api._appointment_connection, None)
