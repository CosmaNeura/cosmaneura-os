"""Saved source restrictions never grant correspondence or bypass existing checks."""

from contextvars import Context
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from tests.integration.test_model_work_api import capture_case as capture_case
from tests.integration.test_model_work_api import case as case
from tests.integration.test_workspace_prep import read as read_prep
from tests.integration.test_workspace_scheduling import LocalScheduling
from tests.unit.test_encounter_prep import receipt

from cosmas_os.api import app as api
from cosmas_os.models import (
    CoreCaptureAccount,
    ExternalIdentity,
    ModelUsageObservation,
    ModelWorkAdmission,
    Principal,
    SchedulingAccount,
)
from cosmas_os.ports.encounter_prep import CorePrepReceipt


def save_policy(f, config, revision):
    rehearsal = f.client.post(
        "/provider-team/rehearsal",
        headers=f.headers,
        json={
            "expected_revision": revision,
            "configuration": config,
            "scenario_id": "team_policy_setup.v1",
        },
    )
    assert rehearsal.status_code == 200, rehearsal.text
    saved = f.client.post(
        "/provider-team",
        headers=f.headers,
        json={
            "expected_revision": revision,
            "configuration": config,
            "idempotency_key": "invented-policy-" + uuid4().hex,
            "setup_review": rehearsal.json()["setup_review"],
        },
    )
    assert saved.status_code == 200, saved.text
    return saved.json()


def configuration(f):
    result = f.client.get("/provider-team", headers=f.headers)
    assert result.status_code == 200, result.text
    return deepcopy(result.json()["configuration"])


def test_core_denial_survives_setup_gate_off_and_allowance_is_not_a_new_grant(case):
    f = case
    f.port.encounter_context = lambda binding, credential: CorePrepReceipt.model_validate(
        receipt(binding.appointment_ref)
    )
    resources = f.client.get("/provider-team/resources", headers=f.headers).json()["resources"]
    core = next(row for row in resources if row["purpose"] == "core_preparation")
    config = configuration(f)
    config["bots"][1]["resources"] = {"version": 1, "allowed": []}
    save_policy(f, config, 1)
    f.configuration.workspace_team_setup_enabled = False
    denied = read_prep(f, {"address": "visit_prep", "team_revision": 2})
    assert (
        denied.status_code == 409
        and denied.json() == {"detail": "bot_resource_restricted"}
        and f.port.calls == []
    )
    f.configuration.workspace_team_setup_enabled = True
    config["bots"][1]["resources"]["allowed"] = [{k: core[k] for k in ("purpose", "resource_ref")}]
    save_policy(f, config, 2)
    accepted = read_prep(f, {"address": "visit_prep", "team_revision": 3})
    assert accepted.status_code == 200, accepted.text
    before = len(f.port.calls)
    # A matching selector does not restore a separately excluded source class.
    config["bots"][1]["include_evidence"] = False
    save_policy(f, config, 3)
    denied = read_prep(f, {"address": "visit_prep", "team_revision": 4})
    assert denied.status_code == 409 and len(f.port.calls) == before


def test_stale_selection_retained_on_same_bot_but_cannot_be_copied_to_another(case):
    f = case
    current = f.client.get("/provider-team/resources", headers=f.headers).json()
    core = next(row for row in current["resources"] if row["purpose"] == "core_preparation")
    config = configuration(f)
    binding = {k: core[k] for k in ("purpose", "resource_ref")}
    config["bots"][1]["resources"] = {"version": 1, "allowed": [binding]}
    save_policy(f, config, 1)
    with Session(f.engine) as s:
        s.get(CoreCaptureAccount, f.account_id).revoked_at = datetime.now(UTC)
        s.commit()
    changed = f.client.get("/provider-team/resources", headers=f.headers).json()
    assert changed["inventory_sha256"] != current["inventory_sha256"] and changed["resources"] == []
    config["practice_context"] = "Changed invented practice preference"
    save_policy(f, config, 2)
    setup = f.client.get("/provider-team/setup", headers=f.headers).json()
    readiness = next(
        row
        for row in setup["setup"]["capabilities"]
        if row["bot"] == "visit_prep" and row["capability"] == "encounter_prep"
    )
    assert readiness["state"] == "resource_unavailable" and readiness["restricted"] is False
    copied = deepcopy(config)
    copied["bots"][0]["resources"] = deepcopy(config["bots"][1]["resources"])
    rejected = f.client.post(
        "/provider-team/rehearsal",
        headers=f.headers,
        json={
            "expected_revision": 3,
            "configuration": copied,
            "scenario_id": "team_policy_setup.v1",
        },
    )
    assert rejected.status_code == 409 and rejected.json() == {"detail": "team_resource_changed"}
    del config["bots"][1]["resources"]
    save_policy(f, config, 3)
    assert f.port.calls == [] and f.calls == []


def test_restriction_added_during_core_io_withholds_receipt(case):
    f = case
    f.port.encounter_context = lambda binding, credential: CorePrepReceipt.model_validate(
        receipt(binding.appointment_ref)
    )
    config = configuration(f)

    def restrict(phase):
        if phase == "exchange":
            config["bots"][1]["resources"] = {"version": 1, "allowed": []}
            # A separate user request must not inherit the in-flight Core
            # request's session ownership or serialization budget.
            Context().run(save_policy, f, config, 1)

    f.port.after = restrict
    result = read_prep(f, {"address": "visit_prep", "team_revision": 1})
    assert result.status_code == 409 and "intake" not in result.text.lower()
    assert f.port.calls == ["exchange"]


def test_scheduling_denial_and_matching_reference_still_require_evidence(case):
    f = case
    f.configuration.workspace_scheduling_enabled = True
    with Session(f.engine) as s:
        row = SchedulingAccount(
            external_identity_id=f.identity_id,
            practice_id=str(uuid4()),
            actor_id=str(uuid4()),
            practitioner_id=str(uuid4()),
            location_id=str(uuid4()),
            appointment_type_id=str(uuid4()),
            label="Private label must not appear in inventory",
            reviewed_by="Invented reviewer",
            evidence_ref="synthetic:policy",
            reviewed_at=datetime.now(UTC),
        )
        s.add(row)
        s.commit()
    inventory = f.client.get("/provider-team/resources", headers=f.headers)
    assert "Private label" not in inventory.text
    selected = next(
        row for row in inventory.json()["resources"] if row["purpose"] == "scheduling_context"
    )
    config = configuration(f)
    config["bots"][2]["resources"] = {"version": 1, "allowed": []}
    save_policy(f, config, 1)
    port = LocalScheduling()
    api.app.dependency_overrides[api._scheduling_connection] = lambda: port

    def read(revision):
        start = datetime.now(UTC) + timedelta(days=1)
        return f.client.post(
            f.base + "/scheduling/availability",
            headers=f.headers,
            json={
                "bot": {"address": "follow_up", "team_revision": revision},
                "window": {
                    "starts_at": start.isoformat(),
                    "ends_at": (start + timedelta(days=7)).isoformat(),
                },
            },
        )

    try:
        assert read(2).json() == {"detail": "bot_resource_restricted"} and port.calls == []
        config["bots"][2]["resources"]["allowed"] = [
            {k: selected[k] for k in ("purpose", "resource_ref")}
        ]
        save_policy(f, config, 2)
        result = read(3)
        assert result.status_code == 200, result.text
        config["bots"][2]["include_evidence"] = False
        save_policy(f, config, 3)
        assert read(4).status_code == 409 and len(port.calls) == 1
    finally:
        api.app.dependency_overrides.pop(api._scheduling_connection, None)


def test_rehearsal_reserves_no_model_units_and_inventory_is_identity_scoped(case):
    f = case
    with Session(f.engine) as s:
        before = [
            s.scalar(select(func.count()).select_from(model))
            for model in (ModelWorkAdmission, ModelUsageObservation)
        ]
        other = Principal(
            box_id=f.box, principal_type="human", display_name="Invented unconnected owner"
        )
        s.add(other)
        s.flush()
        identity = ExternalIdentity(
            box_id=f.box,
            principal_id=other.id,
            provider="clerk",
            issuer=f.configuration.clerk_issuer,
            subject="user_invented_other",
            organization_id="org_invented",
            reviewed_by="Invented reviewer",
            evidence_ref="synthetic:policy",
        )
        s.add(identity)
        s.commit()
    config = configuration(f)
    config["model_work"] = {"version": 1, "max_attempts_per_24h": 1}
    response = f.client.post(
        "/provider-team/rehearsal",
        headers=f.headers,
        json={
            "expected_revision": 1,
            "configuration": config,
            "scenario_id": "team_policy_setup.v1",
        },
    )
    assert response.status_code == 200, response.text
    other = f.client.get(
        "/provider-team/resources",
        headers={**f.headers, "Authorization": "Bearer " + f.token(sub="user_invented_other")},
    )
    assert other.status_code == 200 and other.json()["resources"] == []
    with Session(f.engine) as s:
        assert [
            s.scalar(select(func.count()).select_from(model))
            for model in (ModelWorkAdmission, ModelUsageObservation)
        ] == before
    assert f.calls == [] and f.port.calls == []
