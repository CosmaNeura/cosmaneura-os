from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from tests.integration.test_workspace_bot_tasks import install
from tests.integration.test_workspace_capture import capture_case as _capture_case

from cosmas_os.api import app as api
from cosmas_os.application import provider_team as team
from cosmas_os.models import AuditEvent, ExternalIdentity, SchedulingAccount
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.scheduling import (
    AvailabilitySlot,
    GoogleCalendarCoverage,
    GoogleSchedulingAvailability,
)

capture_case = _capture_case


class LocalScheduling:
    def __init__(self):
        self.calls = []
        self.after = lambda: None
        self.fault = None

    def verified_availability(self, selection, window):
        self.calls.append(selection)
        self.after()
        if self.fault == "unavailable":
            raise ConnectorUnavailable("PRIVATE backend failure")
        checked = datetime.now(UTC) - (timedelta(minutes=2) if self.fault == "stale" else timedelta())
        if self.fault == "scope":
            selection = selection.model_copy(update={"practice_id": uuid4()})
        result = GoogleSchedulingAvailability(selection=selection, window=window,
            slots=(AvailabilitySlot(starts_at=window.starts_at, ends_at=window.starts_at + timedelta(minutes=30)),),
            observed_at=datetime.now(UTC), google=GoogleCalendarCoverage(provider="google", calendar_id="primary", connection_id=uuid4(),
                connected_at=checked - timedelta(days=1), checked_at=checked))
        return result.model_copy(update={"google": {"private": "PRIVATE"}}) if self.fault == "malformed" else result


@pytest.fixture
def scheduling_case(capture_case):
    f = capture_case
    f.configuration.workspace_scheduling_enabled = True
    _, saved = install(f)
    f.bot = {"address": "follow_up", "team_revision": saved["revision"]}
    f.agent = saved["members"][2]["agent_id"]
    row = SchedulingAccount(external_identity_id=f.identity_id,
        practice_id=str(uuid4()), actor_id=str(uuid4()), practitioner_id=str(uuid4()),
        location_id=str(uuid4()), appointment_type_id=str(uuid4()), label="Invented follow-up",
        reviewed_by="Invented owner", evidence_ref="synthetic:w11", reviewed_at=datetime.now(UTC))
    f.session.add(row)
    f.session.commit()
    f.scheduling_id = row.id
    f.scheduling = LocalScheduling()
    f.scheduling_path = f"/workspaces/{f.workspace['id']}/scheduling/availability"
    api.app.dependency_overrides[api._scheduling_connection] = lambda: f.scheduling
    try:
        yield f
    finally:
        api.app.dependency_overrides.pop(api._scheduling_connection, None)


def read(f, **changes):
    now = datetime.now(UTC) + timedelta(days=1)
    return f.client.post(f.scheduling_path, headers={"Authorization": "Bearer " + f.token()},
        json={"bot": f.bot, "window": {"starts_at": now.isoformat(), "ends_at": (now + timedelta(days=7)).isoformat()}, **changes})


def test_scoped_followup_read_has_google_receipt_and_no_work_mutation(scheduling_case):
    f = scheduling_case
    old_revision = f.workspace["revision"]
    response = read(f)
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["source"] == "google_primary" and len(value["slots"]) == 1
    assert value["label"] == "Invented follow-up" and value["workspace_id"] == f.workspace["id"]
    assert set(value) == {"workspace_id", "source", "window", "label", "slots", "checked_at", "valid_until"}
    assert f.scheduling.calls[0].owner_id == f.scheduling.calls[0].owner_id.__class__(f.actor)
    event = f.session.scalar(select(AuditEvent).where(AuditEvent.aggregate_id == f.workspace["id"],
        AuditEvent.event_type == "workspace.bot_availability_read"))
    assert event.actor_principal_id == f.agent and event.initiated_by_principal_id == f.actor
    assert event.detail["slot_count"] == 1 and set(event.detail) == {"slot_count", "receipt_sha256"}
    current = f.client.get(f"/workspaces/{f.workspace['id']}", headers={"Authorization": "Bearer " + f.token()}).json()
    assert current["revision"] == old_revision and not current["follow_ups"]


@pytest.mark.parametrize("target", ["identity", "account", "bot"])
def test_revocation_during_request_discards_receipt(scheduling_case, target):
    f = scheduling_case
    def revoke():
        with Session(f.engine) as s:
            if target == "identity":
                s.get(ExternalIdentity, f.identity_id).active = False
            elif target == "account":
                s.get(SchedulingAccount, f.scheduling_id).revoked_at = datetime.now(UTC)
            else:
                state = team.read(s, f.box, f.actor)
                config = deepcopy(state["configuration"])
                config["bots"][2]["enabled"] = False
                team.save(s, f.box, f.actor, expected=state["revision"], key="pause-scheduling", configuration=config)
            s.commit()
    f.scheduling.after = revoke
    response = read(f)
    assert response.status_code in {403, 404, 409} and "slots" not in response.json()
    assert not f.session.scalar(select(AuditEvent).where(AuditEvent.aggregate_id == f.workspace["id"],
        AuditEvent.event_type == "workspace.bot_availability_read"))


@pytest.mark.parametrize("fault", ["scope", "stale", "unavailable", "malformed"])
def test_bad_receipt_or_service_error_never_becomes_free_time(scheduling_case, fault):
    f = scheduling_case
    f.scheduling.fault = fault
    response = read(f)
    assert response.status_code == 503 and response.json() == {"detail": "scheduling_unavailable"}
    assert "PRIVATE" not in response.text


@pytest.mark.parametrize("fault", ["disabled", "unconnected", "wrong_bot", "stale_bot", "foreign_workspace", "body_selector"])
def test_missing_authority_does_not_call_scheduling(scheduling_case, fault):
    f = scheduling_case
    if fault == "disabled":
        f.configuration.workspace_scheduling_enabled = False
    elif fault == "unconnected":
        f.session.get(SchedulingAccount, f.scheduling_id).revoked_at = datetime.now(UTC)
        f.session.commit()
    elif fault == "wrong_bot":
        f.bot["address"] = "scribe"
    elif fault == "stale_bot":
        f.bot["team_revision"] += 1
    elif fault == "foreign_workspace":
        f.scheduling_path = f"/workspaces/{uuid4()}/scheduling/availability"
    response = read(f, **({"practice_id": "PRIVATE"} if fault == "body_selector" else {}))
    assert response.status_code in {403, 404, 409, 422}
    assert not f.scheduling.calls


def test_reviewed_correspondence_is_immutable_but_can_revoke(scheduling_case):
    f = scheduling_case
    with Session(f.engine) as s:
        with pytest.raises(DBAPIError):
            s.execute(text("UPDATE scheduling_accounts SET practice_id=:value WHERE id=:id"),
                      {"value": str(uuid4()), "id": f.scheduling_id})
            s.commit()
        s.rollback()
        s.get(SchedulingAccount, f.scheduling_id).revoked_at = datetime.now(UTC)
        s.commit()
        with pytest.raises(DBAPIError):
            s.execute(text("UPDATE scheduling_accounts SET revoked_at=NULL WHERE id=:id"), {"id": f.scheduling_id})
            s.commit()
        s.rollback()


def test_default_factory_does_not_acquire_real_identity(scheduling_case):
    f = scheduling_case
    api.app.dependency_overrides.pop(api._scheduling_connection)
    assert read(f).status_code == 503
    assert not f.scheduling.calls
