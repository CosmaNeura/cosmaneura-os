"""Signed hosted proposals persist locally; invented receiver reads never book."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session
from tests.integration.test_appointment_work import prepare as setup_mapping
from tests.integration.test_scheduling_patient_setup import install_personal_fixture
from tests.integration.test_workspace_capture import capture_case as _capture_case
from tests.unit.test_hosted_workspace_config import hosted

from cosmas_os.adapters.scheduling import HttpSchedulingAvailability
from cosmas_os.adapters.scheduling_actions import HttpSchedulingAppointments
from cosmas_os.api import app as api
from cosmas_os.application import appointment_work as work
from cosmas_os.application import note_review as notes
from cosmas_os.application import provider_team as team
from cosmas_os.application import team_resources, team_setup
from cosmas_os.application import workspace as ws
from cosmas_os.models import (
    ActionRevision,
    AppointmentReceipt,
    AppointmentWork,
    Decision,
    ExternalIdentity,
    Operation,
    SchedulingAccount,
    SchedulingPatientAccount,
    Ticket,
)

capture_case = _capture_case
ORIGIN = "https://workspace.example.invalid"
RECEIVER = "https://scheduling.example.invalid"


class InventedReceiver:
    """Real bounded adapters consume nonce/scope receipts through MockTransport."""

    def __init__(self, f, selected):
        self.f, self.selected = f, selected
        self.calls: list[str] = []
        self.credentials: list[object] = []
        self.after = lambda: None
        self.fault: str | None = None
        self.connection = str(uuid4())
        self.availability = HttpSchedulingAvailability(RECEIVER, self.credential,
            transport=httpx.MockTransport(self.respond))
        self.appointments = HttpSchedulingAppointments(RECEIVER, self.credential,
            transport=httpx.MockTransport(self.respond))

    def credential(self, selected):
        self.credentials.append(selected)
        return SecretStr("invented-read-only-staff-token")

    def respond(self, request):
        assert request.url.host == "scheduling.example.invalid" and request.method == "GET"
        assert "/appointment-operations" not in request.url.path
        assert "cookie" not in request.headers
        # The read must release its private SQL transaction before provider I/O.
        assert not self.f.session.in_transaction()
        assert self.f.request_session is not None and not self.f.request_session.in_transaction()
        self.calls.append(request.url.path)
        self.after()
        selected, now = self.selected, datetime.now(UTC)
        if request.url.path.endswith("/availability/verified"):
            starts, ends = request.url.params["from"], request.url.params["to"]
            value = {"contract_version": "1", "request_nonce": request.url.params["requestNonce"],
                "practice_id": str(selected.practice_id), "actor_id": str(selected.expected_actor_id),
                "practitioner_id": str(selected.practitioner_id), "location_id": str(selected.location_id),
                "appointment_type_id": str(selected.appointment_type_id), "range_start": starts, "range_end": ends,
                "google": {"provider": "google", "calendar_id": "primary", "connection_id": self.connection,
                    "connected_at": (now - timedelta(days=1)).isoformat(), "checked_at": now.isoformat()},
                "slots": [] if self.fault == "missing_slot" else [{"starts_at": starts, "ends_at": ends}]}
            if self.fault == "stale":
                value["google"]["checked_at"] = (now - timedelta(seconds=31)).isoformat()
            if self.fault == "substituted":
                value["actor_id"] = str(uuid4())
        else:
            assert request.url.path == f"/v1/appointments/{self.f.remote_appointment}/verified"
            value = {"contract_version": "1", "request_nonce": request.url.params["requestNonce"],
                "practice_id": str(selected.practice_id), "actor_id": str(selected.expected_actor_id),
                "checked_at": now.isoformat(), "appointment": {"id": self.f.remote_appointment, "version": 3,
                    "status": "confirmed", "client_id": None,
                    **{name: str(getattr(selected, name)) for name in (
                        "patient_id", "practitioner_id", "location_id", "appointment_type_id")},
                    "starts_at": (now + timedelta(days=1)).isoformat(),
                    "ends_at": (now + timedelta(days=1, minutes=30)).isoformat()}}
        return httpx.Response(200, json=value, headers={"Content-Type": "application/json", "Cache-Control": "no-store"})

    def close(self):
        self.availability.close()
        self.appointments.close()


@pytest.fixture
def proposal_case(capture_case, monkeypatch):
    f = capture_case
    # The signing key/verifier use this same Settings object. Only the profile
    # changes; the token remains a real signed invented Clerk-shaped session.
    configuration = hosted(beta_box_id=f.box, clerk_issuer=f.configuration.clerk_issuer,
        clerk_jwks_url=f.configuration.clerk_jwks_url,
        clerk_audience=f.configuration.clerk_audience, workspace_scheduling_enabled=True,
        workspace_appointments_enabled=True, workspace_team_setup_enabled=True,
        workspace_scheduling_login_enabled=True, workspace_scheduling_patient_setup_enabled=True)
    for name, value in configuration.model_dump().items():
        setattr(f.configuration, name, value)
    assert f.configuration.workspace_scheduling_available and f.configuration.workspace_hosted_enabled
    assert "db.example.invalid" in f.configuration.database_url
    monkeypatch.setattr(team, "runtime_settings", f.configuration)
    case = setup_mapping(f.session, {"box_id": f.box, "owner_id": f.actor}, existing=f, patient_mapping=False)
    f.mapping, f.owner, f.wid = case, f.actor, case.wid
    f.remote_appointment = str(uuid4())
    f.appointment.source, f.appointment.external_id = "cosmas_scheduling", f.remote_appointment
    f.session.commit()
    account = f.session.get(SchedulingAccount, case.account)
    assert account is not None
    resource = team_resources.reference(f.box, f.owner, case.identity, "scheduling_context", account)
    selected = team.default_configuration()
    follow = next(bot for bot in selected["bots"] if bot["role"] == "follow_up")
    follow["resources"] = {"version": 1, "allowed": [{"purpose": "scheduling_context", "resource_ref": resource}]}
    rehearsal = team_setup.rehearsal(f.session, f.box, f.owner, case.identity,
        expected=0, configuration=selected, contract=4)
    saved = team.save(f.session, f.box, f.owner, expected=0, key="hosted-proposal-team", configuration=selected,
        setup_review=rehearsal["setup_review"], external_identity_id=case.identity, team_contract=4)
    f.bot = {"address": "follow_up", "team_revision": saved["revision"]}
    state = ws.read(f.session, f.box, f.owner, f.wid)
    state = notes.save(f.session, f.box, f.owner, f.wid, expected=state["revision"], key="hosted-existing-note",
        base_note_id=None, source_reply_id=None, content="Invented reviewed clinical note retained exactly.")["workspace"]
    note = state["note"]["latest"]
    state = notes.review(f.session, f.box, f.owner, f.wid, note["id"], expected=state["revision"], key="hosted-note-review",
        content_hash=note["content_hash"], source_hash=note["source_fingerprint"])["workspace"]
    f.note_before, f.entries_before, f.revision_before = state["note"], state["entries"], state["revision"]
    f.session.commit()
    f.receiver = InventedReceiver(f, case.selection)
    f.path = f"/workspaces/{f.wid}/appointments"
    f.headers = {"Authorization": "Bearer " + f.token(azp=ORIGIN)}
    f.request_session = None
    def request_session():
        with Session(f.engine) as owned:
            f.request_session = owned
            try:
                yield owned
            finally:
                f.request_session = None
    api.app.dependency_overrides[api.get_session] = request_session
    api.app.dependency_overrides[api._scheduling_connection] = lambda: f.receiver.availability
    api.app.dependency_overrides[api._appointment_connection] = lambda: f.receiver.appointments
    try:
        with install_personal_fixture(f.session, box=f.box, owner=f.owner, wid=f.wid,
                identity_id=case.identity, account=account, configuration=f.configuration,
                patient_id=str(case.selection.patient_id)) as mapping_receipt:
            case.patient = mapping_receipt["mapping"]["mapping_id"]
            f.session.commit()
            yield f
    finally:
        api.app.dependency_overrides.pop(api._scheduling_connection, None)
        api.app.dependency_overrides.pop(api._appointment_connection, None)
        f.receiver.close()


def command(f, action="book", **changes):
    now = datetime.now(UTC)
    return {"bot": f.bot, "action": action, "share": True, "idempotency_key": str(uuid4()),
        "slot": None if action == "cancel" else {"starts_at": (now + timedelta(days=2)).isoformat(),
            "ends_at": (now + timedelta(days=2, minutes=30)).isoformat()}, **changes}


def proposed(f, body=None):
    response = f.client.post(f.path, headers=f.headers, json=body or command(f))
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def decide(f, item, choice="approve"):
    response = f.client.post(f.path + "/" + item["ticket_id"] + "/decide", headers=f.headers,
        json={"revision_id": item["revision_id"], "payload_hash": item["payload_hash"], "choice": choice})
    assert response.status_code == 200, response.text
    return response.json()


def assert_unchanged_and_unsubmitted(f, item):
    with Session(f.engine) as s:
        current = ws.read(s, f.box, f.owner, f.wid)
        assert current["note"] == f.note_before and current["entries"] == f.entries_before
        assert current["revision"] == f.revision_before
        assert s.scalar(select(func.count()).select_from(AppointmentReceipt).where(AppointmentReceipt.box_id == f.box)) == 0
        revision = s.get(ActionRevision, item["revision_id"])
        assert revision is not None and revision.config_version == "authenticated-proposal-v1"
        if item["operation_id"]:
            operation = s.get(Operation, item["operation_id"])
            assert operation is not None and operation.started_at is None and operation.attempt_count == 0
            assert operation.external_reference is None


@pytest.mark.parametrize("action", ["book", "reschedule", "cancel"])
def test_signed_hosted_save_approval_reopen_and_withdraw_never_writes_receiver(proposal_case, action):
    f, body = proposal_case, command(proposal_case, action)
    item = proposed(f, body)
    expected = 1 if action in {"book", "cancel"} else 2
    assert len(f.receiver.calls) == expected and item["operation_id"] is None
    assert proposed(f, body) == item and len(f.receiver.calls) == expected
    catalog = f.client.get(f.path, headers=f.headers)
    assert catalog.status_code == 200 and catalog.json()["items"][0]["ticket_id"] == item["ticket_id"]
    approved = decide(f, item)
    assert approved["state"] == "approved" and approved["operation_status"] == "pending"
    assert approved["appointment_saved"] is False and approved["calendar_state"] == "unconfirmed"
    reopened = f.client.get(f.path + "/" + item["ticket_id"],
        headers={"Authorization": "Bearer " + f.token(azp=ORIGIN, sid="invented-reopened-session")})
    assert reopened.status_code == 200 and reopened.json() == approved
    assert decide(f, item) == approved
    rejected = decide(f, item, "reject")
    assert rejected["state"] == "rejected" and decide(f, item, "reject") == rejected
    assert len(f.receiver.calls) == expected and len(f.receiver.credentials) == expected
    assert_unchanged_and_unsubmitted(f, rejected)


@pytest.mark.parametrize("mode", ["submit", "reconcile", "retry"])
def test_hosted_execution_modes_are_denied_even_after_exact_human_approval(proposal_case, mode):
    f = proposal_case
    approved = decide(f, proposed(f))
    calls, credentials = len(f.receiver.calls), len(f.receiver.credentials)
    response = f.client.post(f.path + "/" + approved["ticket_id"] + "/execute", headers=f.headers,
        json={"operation_id": approved["operation_id"], "revision_id": approved["revision_id"],
            "payload_hash": approved["payload_hash"], "mode": mode})
    assert response.status_code == 403 and response.headers["cache-control"] == "no-store"
    assert response.json()["detail"] == "appointment_execution_not_available"
    assert len(f.receiver.calls) == calls and len(f.receiver.credentials) == credentials
    assert_unchanged_and_unsubmitted(f, approved)


def test_hosted_execute_denies_before_body_parser_or_provider_factory(proposal_case, monkeypatch):
    f = proposal_case

    def forbidden_factory():
        pytest.fail("hosted execution constructed its provider port")

    async def forbidden_body(*args, **kwargs):
        pytest.fail("hosted execution parsed its command body")

    api.app.dependency_overrides[api._appointment_connection] = forbidden_factory
    monkeypatch.setattr(api, "read_capture_request", forbidden_body)
    path = f.path + "/" + str(uuid4()) + "/execute"
    for content_type, content in (("text/plain", "invalid command"),
                                  ("application/json", '{"oversized":"' + "x" * 5000 + '"}')):
        response = f.client.post(path, headers={**f.headers, "Content-Type": content_type}, content=content)
        assert response.status_code == 403
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["detail"] == "appointment_execution_not_available"
    assert f.receiver.calls == [] and f.receiver.credentials == []
    with Session(f.engine) as s:
        assert not s.scalar(select(AppointmentWork.ticket_id).where(AppointmentWork.workspace_id == f.wid))
        assert not s.scalar(select(Ticket.id).where(Ticket.box_id == f.box, Ticket.lane == work.LANE))
        assert not s.scalar(select(Operation.id).where(Operation.box_id == f.box))
        state = ws.read(s, f.box, f.owner, f.wid)
        assert state["revision"] == f.revision_before
        assert state["note"] == f.note_before and state["entries"] == f.entries_before


@pytest.mark.parametrize("fault", ["mapping", "account", "identity", "bot", "grant"])
def test_hosted_current_authority_failure_happens_before_any_receiver_read(proposal_case, fault):
    f, body = proposal_case, command(proposal_case)
    with Session(f.engine) as s:
        if fault == "mapping":
            row = s.get(SchedulingPatientAccount, f.mapping.patient)
            assert row is not None
            row.revoked_at = datetime.now(UTC)
        elif fault == "account":
            row = s.get(SchedulingAccount, f.mapping.account)
            assert row is not None
            row.revoked_at = datetime.now(UTC)
        elif fault == "identity":
            row = s.get(ExternalIdentity, f.mapping.identity)
            assert row is not None
            row.active = False
        elif fault == "bot":
            body["bot"] = {**f.bot, "team_revision": f.bot["team_revision"] + 1}
        else:
            previous = team.read(s, f.box, f.owner)
            selected = deepcopy(previous["configuration"])
            next(bot for bot in selected["bots"] if bot["role"] == "follow_up")["resources"]["allowed"] = []
            rehearsal = team_setup.rehearsal(s, f.box, f.owner, f.mapping.identity,
                expected=previous["revision"], configuration=selected, contract=4)
            changed = team.save(s, f.box, f.owner, expected=previous["revision"], key="hosted-remove-grant",
                configuration=selected, setup_review=rehearsal["setup_review"], external_identity_id=f.mapping.identity,
                team_contract=4)
            body["bot"] = {**f.bot, "team_revision": changed["revision"]}
        s.commit()
    response = f.client.post(f.path, headers=f.headers, json=body)
    assert response.status_code in {403, 409}
    assert f.receiver.calls == [] and f.receiver.credentials == []
    with Session(f.engine) as s:
        assert not s.scalar(select(AppointmentWork.ticket_id).where(AppointmentWork.workspace_id == f.wid))


@pytest.mark.parametrize("fault", ["account", "mapping", "disabled", "missing_slot", "stale", "substituted"])
def test_intervening_revocation_or_bad_receipt_discards_hosted_proposal(proposal_case, fault):
    f = proposal_case
    def change():
        if fault == "disabled":
            f.configuration.workspace_appointments_enabled = False
        elif fault in {"account", "mapping"}:
            with Session(f.engine) as s:
                model, identifier = (SchedulingAccount, f.mapping.account) if fault == "account" else (
                    SchedulingPatientAccount, f.mapping.patient)
                row = s.get(model, identifier)
                assert row is not None
                row.revoked_at = datetime.now(UTC)
                s.commit()
    f.receiver.after = change
    f.receiver.fault = fault
    response = f.client.post(f.path, headers=f.headers, json=command(f))
    assert response.status_code in {403, 404, 409, 503}
    assert len(f.receiver.calls) == 1
    with Session(f.engine) as s:
        assert not s.scalar(select(AppointmentWork.ticket_id).where(AppointmentWork.workspace_id == f.wid))
        assert not s.scalar(select(Ticket.id).where(Ticket.box_id == f.box, Ticket.lane == work.LANE))


def test_lost_reply_exact_saved_intent_recovers_after_mapping_revocation_without_reread(proposal_case):
    f, body = proposal_case, command(proposal_case)
    item = proposed(f, body)  # Its successful response is deliberately not acted on.
    calls = len(f.receiver.calls)
    with Session(f.engine) as s:
        mapping = s.get(SchedulingPatientAccount, f.mapping.patient)
        assert mapping is not None
        mapping.revoked_at = datetime.now(UTC)
        s.commit()
    assert proposed(f, body) == item and len(f.receiver.calls) == calls
    changed = f.client.post(f.path, headers=f.headers, json={**body, "action": "cancel", "slot": None})
    assert changed.status_code == 409 and changed.json()["detail"] == "idempotency_conflict"
    chosen = f.client.post(f.path + "/" + item["ticket_id"] + "/decide", headers=f.headers,
        json={"revision_id": item["revision_id"], "payload_hash": item["payload_hash"], "choice": "approve"})
    assert chosen.status_code == 409
    with Session(f.engine) as s:
        assert s.scalar(select(func.count()).select_from(AppointmentWork).where(AppointmentWork.workspace_id == f.wid)) == 1
        assert not s.scalar(select(Operation.id).where(Operation.ticket_id == item["ticket_id"]))
    assert_unchanged_and_unsubmitted(f, item)


@pytest.mark.parametrize("fault", ["unbound", "identity_headers", "body_actor", "foreign_workspace", "private_body"])
def test_untrusted_hosted_request_cannot_select_identity_or_expand_receipt_scope(proposal_case, fault):
    f, body = proposal_case, command(proposal_case)
    headers, path = dict(f.headers), f.path
    if fault == "unbound":
        headers["Authorization"] = "Bearer " + f.token(azp=ORIGIN, sub="invented-unbound-human")
    elif fault == "identity_headers":
        headers["X-Actor-Principal-Id"] = f.owner
    elif fault == "body_actor":
        body["owner_id"] = f.owner
    elif fault == "foreign_workspace":
        path = f"/workspaces/{uuid4()}/appointments"
    else:
        body["intent"] = {"content": "PRIVATE invented body must not enter proposal"}
    response = f.client.post(path, headers=headers, json=body)
    assert response.status_code in {401, 403, 404, 422}
    assert "PRIVATE" not in response.text and response.headers["cache-control"] == "no-store"
    assert f.receiver.calls == [] and f.receiver.credentials == []
    with Session(f.engine) as s:
        assert not s.scalar(select(AppointmentWork.ticket_id).where(AppointmentWork.workspace_id == f.wid))


@pytest.mark.parametrize("phase", ["proposal", "approval", "withdrawal"])
def test_feature_disable_at_local_persistence_fence_rolls_back_new_commit(proposal_case, phase):
    f = proposal_case
    item = proposed(f) if phase != "proposal" else None
    if phase == "withdrawal":
        assert item is not None
        item = decide(f, item)
    with Session(f.engine) as s:
        prior = {model: s.scalar(select(func.count()).select_from(model).where(model.box_id == f.box))
            for model in (Ticket, Operation, Decision)}
        def disable(session, context, instances):
            if any(isinstance(row, ActionRevision if phase == "proposal" else Decision) for row in session.new):
                f.configuration.workspace_appointments_enabled = False
        event.listen(s, "before_flush", disable)
        try:
            with pytest.raises(ws.WorkspaceError, match="appointment_proposals_unavailable"):
                if phase == "proposal":
                    # A direct trusted caller already has a qualified immutable
                    # receipt; source orchestration is separately tested above.
                    from tests.unit.test_scheduling_actions import NOW, operation
                    work.propose(s, f.box, f.owner, f.wid, external_identity_id=f.mapping.identity,
                        intent=operation(f.mapping.selection).intent, key="hosted-fence-proposal", share=True,
                        now=NOW, configuration=f.configuration)
                else:
                    assert item is not None
                    work.decide(s, f.box, f.owner, f.wid, item["ticket_id"], external_identity_id=f.mapping.identity,
                        revision_id=item["revision_id"], digest=item["payload_hash"],
                        choice="reject" if phase == "withdrawal" else "approve", configuration=f.configuration)
            s.rollback()
        finally:
            event.remove(s, "before_flush", disable)
        assert {model: s.scalar(select(func.count()).select_from(model).where(model.box_id == f.box))
            for model in prior} == prior
