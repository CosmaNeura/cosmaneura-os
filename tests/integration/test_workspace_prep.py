from copy import deepcopy

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from tests.integration.test_workspace_bot_tasks import install
from tests.integration.test_workspace_capture import capture_case as _capture_case
from tests.unit.test_encounter_prep import receipt

from cosmas_os.application import provider_team as team
from cosmas_os.models import AuditEvent, ExternalIdentity
from cosmas_os.ports.encounter_prep import CorePrepReceipt

capture_case = _capture_case


def setup(f):
    f.configuration.workspace_prep_enabled = True
    bot, saved = install(f)

    def context(binding, credential):
        f.port.step("prep")
        return CorePrepReceipt.model_validate(receipt(binding.appointment_ref))

    f.port.encounter_context = context
    return bot, saved


def read(f, bot, **changes):
    return f.client.post(
        f"/workspaces/{f.workspace['id']}/capture/prep",
        json={"idempotency_key": "invented-prep", "bot": bot, **changes},
        headers={"Authorization": "Bearer " + f.token()},
    )


@pytest.mark.parametrize("role", ["additional_scribe", "visit_prep"])
def test_exact_bot_reads_current_context_without_consent(capture_case, role):
    f = capture_case
    bot, saved = setup(f)
    expected_agent = saved["members"][-1]["agent_id"]
    if role == "visit_prep":
        bot["address"] = "visit_prep"
        expected_agent = saved["members"][1]["agent_id"]
    response = read(f, bot)
    assert response.status_code == 200, response.text
    assert f.port.calls == ["exchange", "resolve", "binding", "prep"] and f.port.saved is None
    event = f.session.scalar(
        select(AuditEvent).where(
            AuditEvent.aggregate_id == f.workspace["id"],
            AuditEvent.event_type == "workspace.bot_prep_read",
        )
    )
    assert (
        event.actor_principal_id == expected_agent
        and event.initiated_by_principal_id == f.actor
    )


@pytest.mark.parametrize("phase", ["exchange", "resolve", "binding", "prep"])
def test_revocation_during_read_withholds_private_context(capture_case, phase):
    f = capture_case
    bot, _ = setup(f)

    def revoke(observed):
        if observed == phase:
            with Session(f.engine) as s:
                identity = s.get(ExternalIdentity, f.identity_id)
                identity.active = False
                s.commit()

    f.port.after = revoke
    response = read(f, bot)
    assert response.status_code in {403, 404, 409} and "Invented intake" not in response.text


@pytest.mark.parametrize(
    "fault",
    ["paused", "source_disabled", "stale", "wrong_template", "disabled_flag", "body_authority"],
)
def test_read_respects_source_settings_and_gate(capture_case, fault):
    f = capture_case
    bot, saved = setup(f)
    if fault in {"paused", "source_disabled"}:
        config = deepcopy(saved["configuration"])
        config["bots"][-1]["enabled" if fault == "paused" else "include_evidence"] = False
        team.save(f.session, f.box, f.actor, expected=1, key="pause", configuration=config)
        bot["team_revision"] = 2
    elif fault == "stale":
        bot["team_revision"] = 2
    elif fault == "wrong_template":
        bot["address"] = "chief"
    elif fault == "disabled_flag":
        f.configuration.workspace_prep_enabled = False
    response = read(
        f, bot, **({"patient_id": "private sentinel"} if fault == "body_authority" else {})
    )
    assert response.status_code in {404, 409, 422}
    assert f.port.calls == [] and "private sentinel" not in response.text
