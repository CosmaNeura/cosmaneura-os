from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from tests.integration.test_workspace_bot_tasks import install
from tests.integration.test_workspace_capture import LocalCore
from tests.integration.test_workspace_capture import capture_case as _capture_case
from tests.unit.test_core_session_prep import receipt

from cosmas_os.api import app as api
from cosmas_os.application import provider_team as team
from cosmas_os.models import AuditEvent, CoreCaptureAccount, ExternalIdentity, PatientLink
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.core_capture import CoreInteractionCredential
from cosmas_os.ports.core_session_prep import CoreSessionPrepRead, CoreSessionPrepReceipt
from cosmas_os.ports.core_session_prep_flow import CoreSessionPrepContext

capture_case = _capture_case


class CorePrep(LocalCore):
    state = "ready"

    def resolve_context(self, selection, token, client_turn_id):
        self.step("resolve")
        return CoreSessionPrepContext(
            credential=CoreInteractionCredential(
                mount_context_token=token.context_token,
                interaction_ref="interaction_invented_current",
                client_turn_id=client_turn_id,
            ),
            context_snapshot_ref="context_invented_current",
        )

    def accept_action(self, context):
        self.step("accept")
        return CoreSessionPrepRead(
            credential=context.credential,
            context_snapshot_ref=context.context_snapshot_ref,
            source_turn_ref="conversation_turn_invented_current",
            idempotency_key="read." + str(context.credential.client_turn_id),
        )

    def read_brief(self, selection):
        self.step("confirm" if "read" in self.calls else "read")
        return CoreSessionPrepReceipt.model_validate(receipt(self.state))

    def complete_action(self, selection, result):
        self.step("complete")


def setup(f, monkeypatch):
    f.configuration.workspace_prep_enabled = True
    f.configuration.workspace_session_prep_enabled = True
    f.configuration.core_session_prep_scope = "api://synthetic-session-prep/.default"
    f.configuration.core_session_prep_managed_identity_client_id = str(uuid4())
    monkeypatch.setattr(team, "runtime_settings", f.configuration)
    bot, saved = install(f)
    f.session.commit()
    bot["address"] = "visit_prep"
    f.prep = CorePrep()

    @contextmanager
    def connection(configuration, budget):
        assert budget is not None and configuration.workspace_session_prep_available
        try:
            yield f.prep
        finally:
            f.prep.closed = True

    monkeypatch.setattr(api, "session_prep_connection", connection)
    return bot, saved


def read(f, bot, **changes):
    return f.client.post(
        f"/workspaces/{f.workspace['id']}/capture/prep",
        json={"view": "brief", "idempotency_key": str(uuid4()), "bot": bot, **changes},
        headers={"Authorization": "Bearer " + f.token()},
    )


@pytest.mark.parametrize("state", ["ready", "pending", "refreshing", "unavailable"])
def test_signed_application_returns_authorized_brief_without_recording_or_chat(
    capture_case, monkeypatch, state
):
    f = capture_case
    bot, saved = setup(f, monkeypatch)
    f.prep.state = state
    response = read(f, bot)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["receipt"]["state"] == state
    assert f.prep.calls == ["exchange", "resolve", "accept", "read", "complete", "confirm"]
    assert f.port.calls == [] and f.port.saved is None and f.prep.closed
    assert "conversation_turn_" not in response.text and "source_invented_" not in response.text
    event = f.session.scalar(
        select(AuditEvent).where(
            AuditEvent.aggregate_id == f.workspace["id"],
            AuditEvent.event_type == "workspace.session_prep_read",
        )
    )
    assert (
        event.actor_principal_id == saved["members"][1]["agent_id"]
        and event.initiated_by_principal_id == f.actor
    )
    assert "Invented reviewed" not in str(event.detail)


@pytest.mark.parametrize(
    "phase,target",
    [
        ("exchange", "identity"),
        ("resolve", "account"),
        ("accept", "patient"),
        ("read", "team"),
        ("complete", "patient"),
        ("confirm", "flag"),
    ],
)
def test_revocation_between_remote_phases_withholds_the_brief(
    capture_case, monkeypatch, phase, target
):
    f = capture_case
    bot, saved = setup(f, monkeypatch)

    def revoke(observed):
        if observed != phase:
            return
        if target == "flag":
            f.configuration.workspace_session_prep_enabled = False
            return
        with Session(f.engine) as session:
            if target == "identity":
                session.get(ExternalIdentity, f.identity_id).active = False
            elif target == "account":
                session.get(CoreCaptureAccount, f.account_id).revoked_at = datetime.now(UTC)
            elif target == "patient":
                session.get(PatientLink, f.patient_link_id).revoked_at = datetime.now(UTC)
            else:
                config = deepcopy(saved["configuration"])
                config["bots"][1]["include_evidence"] = False
                team.save(
                    session, f.box, f.actor, expected=1, key="revoke-prep", configuration=config
                )
            session.commit()

    f.prep.after = revoke
    response = read(f, bot)
    assert response.status_code in {403, 404, 409}, response.text
    assert "Invented reviewed" not in response.text and f.prep.calls[-1] == phase
    assert f.prep.closed


def test_core_source_change_at_final_confirmation_does_not_disclose_old_brief(
    capture_case, monkeypatch
):
    f = capture_case
    bot, _ = setup(f, monkeypatch)

    def changed(phase):
        if phase == "confirm":
            raise ConnectorUnavailable("session_prep_request_conflict")

    f.prep.after = changed
    response = read(f, bot)
    assert response.status_code == 409 and "Invented reviewed" not in response.text
    assert f.prep.closed


def test_retransmission_cannot_start_a_second_canonical_action(capture_case, monkeypatch):
    f = capture_case
    bot, _ = setup(f, monkeypatch)
    resolved = set()
    resolve = f.prep.resolve_context

    def current_mount(selection, token, turn):
        if turn in resolved:
            # Core rejects a reused client turn with a newly exchanged mount.
            raise ConnectorUnavailable("session_prep_request_conflict")
        resolved.add(turn)
        return resolve(selection, token, turn)

    monkeypatch.setattr(f.prep, "resolve_context", current_mount)
    key = str(uuid4())
    assert read(f, bot, idempotency_key=key).status_code == 200
    assert read(f, bot, idempotency_key=key).status_code == 409
    assert f.prep.calls.count("accept") == 1 and len(resolved) == 1
    assert read(f, bot).status_code == 200
    assert f.prep.calls.count("accept") == 2 and len(resolved) == 2


@pytest.mark.parametrize(
    "fault",
    ["disabled", "missing_identity", "missing_scope", "missing_bot", "wrong_bot", "stale_team"],
)
def test_unactivated_or_wrong_bot_never_starts_a_core_phase(capture_case, monkeypatch, fault):
    f = capture_case
    bot, _ = setup(f, monkeypatch)
    if fault == "disabled":
        f.configuration.workspace_session_prep_enabled = False
    elif fault == "missing_identity":
        f.configuration.core_session_prep_managed_identity_client_id = ""
    elif fault == "missing_scope":
        f.configuration.core_session_prep_scope = ""
    elif fault == "missing_bot":
        bot = None
    elif fault == "wrong_bot":
        bot["address"] = "chief"
    else:
        bot["team_revision"] = 99
    response = read(f, bot)
    assert response.status_code in {404, 409, 422}, response.text
    assert not f.prep.calls and not f.port.calls


def test_capability_stays_saved_context_until_dedicated_permission_is_configured(
    capture_case, monkeypatch
):
    f = capture_case
    setup(f, monkeypatch)

    def contract():
        return next(
            cap["contract"]
            for member in team.read(f.session, f.box, f.actor)["members"]
            if member["role"] == "visit_prep"
            for cap in member["capabilities"]
            if cap["key"] == "core.session_prep.read"
        )

    assert contract() == "core.session-prep.brief.v1"
    f.configuration.core_session_prep_managed_identity_client_id = ""
    assert contract() == "core.encounter-context.v1"
