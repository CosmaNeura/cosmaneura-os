"""Actual signed HTTP/ASGI and PostgreSQL admission boundaries, with no model network."""

import json
from copy import deepcopy

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from tests.helpers.task_brief import REQUIREMENTS
from tests.integration.test_workspace_capture import capture_case as _capture_case

from cosmas_os.api import app as api
from cosmas_os.application import conversation, handoffs
from cosmas_os.application import model_work as work
from cosmas_os.application import provider_team as team
from cosmas_os.models import ExternalIdentity, ModelWorkAdmission, WorkspaceReply
from cosmas_os.ports.bot_capabilities import BotReply, ModelCallFailure

capture_case = _capture_case


@pytest.fixture
def case(capture_case, monkeypatch):
    f = capture_case
    f.configuration.workspace_team_setup_enabled = True
    f.configuration.workspace_prep_enabled = True
    f.configuration.workspace_llm_backend = "azure_gpt41"
    f.configuration.workspace_llm_api_key = SecretStr("invented-no-network")
    for module in (team, conversation, handoffs):
        monkeypatch.setattr(module, "runtime_settings", f.configuration)
    f.headers = {
        "Authorization": "Bearer " + f.token(),
        "X-Cosmas-Team-Contract": "2",
        "X-Cosmas-Model-Contract": "1",
    }
    f.base = f"/workspaces/{f.workspace['id']}"
    f.body = {
        "expected_revision": 1,
        "team_revision": 1,
        "idempotency_key": "invented-model-request",
        "role": "visit_prep",
        "content": "Summarize the invented preparation.",
    }
    f.calls = []

    def reply(claim):
        f.calls.append(claim.envelope_sha256)
        return BotReply("Invented response for review.", (), "azure_gpt41", 20, 7)

    monkeypatch.setattr(work, "dispatch_claim", reply)

    def sessions():
        with Session(f.engine) as s:
            yield s

    api.app.dependency_overrides[api.get_session] = sessions
    result = f.client.post(
        "/provider-team",
        headers=f.headers,
        json={
            "expected_revision": 0,
            "idempotency_key": "invented-initial-team",
            "configuration": team.default_configuration(),
        },
    )
    assert result.status_code == 200, result.text
    yield f


def test_signed_admission_receipt_pending_projection_and_historical_replay(case, tmp_path):
    f = case
    before = f.client.post(f.base + "/conversation/resolve", headers=f.headers, json=f.body)
    assert before.status_code == 200 and before.json()["outcome"] == "not_found"
    saved = f.client.post(f.base + "/conversation", headers=f.headers, json=f.body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["outcome"] == "saved" and saved.json()["admission"]["usage"] == "verified"
    assert len(f.calls) == 1 and len(saved.content) < 16384
    assert (
        f.client.get(f.base, headers={"Authorization": f.headers["Authorization"]}).status_code
        == 426
    )
    current = f.client.get(f.base, headers=f.headers)
    assert current.status_code == 200, current.text
    row = current.json()["entries"][-1]
    assert row["model_request"]["admission"]["state"] == "completed"
    assert row["reply"]["content"] == "Invented response for review."
    assert row["model_request"]["request_sha256"] == saved.json()["request_sha256"]
    f.configuration.workspace_llm_backend = "none"
    assert (
        f.client.post(f.base + "/conversation", headers=f.headers, json=f.body).json()
        == saved.json()
    )
    assert len(f.calls) == 1
    for name, value in [("model-saved", saved.json()), ("model-workspace", current.json())]:
        (tmp_path / (name + ".json")).write_text(json.dumps(value, sort_keys=True))


def test_unconfirmed_call_returns_closed_409_and_resolve_never_redispatches(case, monkeypatch):
    f = case

    def lost(_):
        f.calls.append("lost")
        raise ModelCallFailure(dispatch="started_unconfirmed")

    monkeypatch.setattr(work, "dispatch_claim", lost)
    result = f.client.post(f.base + "/conversation", headers=f.headers, json=f.body)
    assert result.status_code == 409, result.text
    assert result.json()["outcome"] == "unknown" and result.json()["saved_entry"] is None
    f.configuration.workspace_llm_backend = "none"
    for _ in range(2):
        observed = f.client.post(f.base + "/conversation/resolve", headers=f.headers, json=f.body)
        assert observed.status_code == 200 and observed.json() == result.json()
    assert len(f.calls) == 1
    current = f.client.get(f.base, headers=f.headers).json()
    assert (
        current["entries"][-1]["reply"] is None
        and current["entries"][-1]["model_request"]["admission"]["state"] == "unknown"
    )
    assert (
        f.client.post(
            f.base + "/conversation",
            headers=f.headers,
            json={**f.body, "content": "Changed exact body"},
        ).status_code
        == 409
    )


@pytest.mark.parametrize("header", [None, "0", "2", "1, 1"])
def test_missing_or_unknown_model_contract_never_starts_inference(case, header):
    f = case
    headers = {k: v for k, v in f.headers.items() if k != "X-Cosmas-Model-Contract"}
    if header is not None:
        headers["X-Cosmas-Model-Contract"] = header
    response = f.client.post(f.base + "/conversation", headers=headers, json=f.body)
    assert response.status_code == 426, response.text
    assert f.calls == []


@pytest.mark.parametrize("change", ["duplicate", "oversize", "surrogate", "query", "extra"])
def test_closed_request_rejection_precedes_admission(case, change):
    f = case
    body = json.dumps(f.body)
    path = f.base + "/conversation"
    if change == "duplicate":
        body = body[:-1] + ',"role":"chief"}'
    if change == "oversize":
        body = " " * 65537 + body
    if change == "surrogate":
        body = body.replace("Summarize the invented preparation.", "\\ud800")
    if change == "query":
        path += "?retry=1"
    if change == "extra":
        body = body[:-1] + ',"tools":[]}'
    response = f.client.post(
        path, headers={**f.headers, "Content-Type": "application/json"}, content=body
    )
    assert response.status_code == 422, response.text
    assert response.json() == {"detail": "invalid_model_request"} and f.calls == []


def test_signed_v2_policy_resources_usage_and_saved_denial_when_gate_off(case, tmp_path):
    f = case
    initial = f.client.get("/provider-team/setup", headers=f.headers)
    assert initial.status_code == 200, initial.text
    resources = f.client.get("/provider-team/resources", headers=f.headers)
    assert resources.status_code == 200, resources.text
    config = deepcopy(initial.json()["team"]["configuration"])
    config["model_work"] = {"version": 1, "max_attempts_per_24h": 0}
    config["bots"][1]["resources"] = {"version": 1, "allowed": []}
    request = {
        "expected_revision": 1,
        "configuration": config,
        "scenario_id": "team_policy_setup.v1",
    }
    rehearsal = f.client.post("/provider-team/rehearsal", headers=f.headers, json=request)
    assert rehearsal.status_code == 200, rehearsal.text
    saved = f.client.post(
        "/provider-team",
        headers=f.headers,
        json={
            **{k: v for k, v in request.items() if k != "scenario_id"},
            "idempotency_key": "invented-limit-save",
            "setup_review": rehearsal.json()["setup_review"],
        },
    )
    assert saved.status_code == 200, saved.text
    blocked = f.client.post(
        f.base + "/conversation", headers=f.headers, json={**f.body, "team_revision": 2}
    )
    assert blocked.status_code == 409 and blocked.json() == {"detail": "team_work_limit"}
    meter = f.client.get("/provider-team/usage", headers=f.headers)
    assert meter.status_code == 200, meter.text
    assert meter.json()["occupied_units"] == 0 and meter.json()["remaining_units"] == 0
    f.configuration.workspace_team_setup_enabled = False
    assert f.client.post(
        f.base + "/conversation", headers=f.headers, json={**f.body, "team_revision": 2}
    ).json() == {"detail": "team_work_limit"}
    assert f.calls == []
    f.configuration.workspace_team_setup_enabled = True
    setup = f.client.get("/provider-team/setup", headers=f.headers)
    assert setup.status_code == 200, setup.text
    for name, value in [
        ("team-setup-v2", setup.json()),
        ("team-resources-v1", resources.json()),
        ("team-usage-v1", meter.json()),
        ("team-rehearsal-v2", rehearsal.json()),
    ]:
        encoded = json.dumps(value, sort_keys=True)
        assert (
            f.account_id not in encoded
            and f.identity_id not in encoded
            and "authority_actor_" not in encoded
        )
        (tmp_path / (name + ".json")).write_text(encoded)


def test_current_identity_revocation_rejects_receipt_read_and_prevents_publication(
    case, monkeypatch
):
    f = case

    def revoke(_):
        with Session(f.engine) as s:
            s.get(ExternalIdentity, f.identity_id).active = False
            s.commit()
        return BotReply("Withheld private result.", (), "azure_gpt41", 22, 8)

    monkeypatch.setattr(work, "dispatch_claim", revoke)
    result = f.client.post(f.base + "/conversation", headers=f.headers, json=f.body)
    assert result.status_code == 403, result.text
    assert (
        f.client.post(f.base + "/conversation/resolve", headers=f.headers, json=f.body).status_code
        == 403
    )
    with Session(f.engine) as s:
        row = s.scalar(
            select(ModelWorkAdmission).where(ModelWorkAdmission.workspace_id == f.workspace["id"])
        )
        assert row.state == "failed" and row.reason == "authority_changed"
        assert (
            s.scalar(
                select(func.count())
                .select_from(WorkspaceReply)
                .where(WorkspaceReply.workspace_id == row.workspace_id)
            )
            == 0
        )
        assert work.usage(s, f.box, f.actor)["verified_input_tokens"] == 22


def test_signed_handoff_retry_records_queue_once_and_resolves_that_exact_attempt(
    case, monkeypatch, tmp_path
):
    from cosmas_os.models import WorkspaceHandoffAttempt
    from cosmas_os.ports.bot_capabilities import DraftBrief

    f = case
    monkeypatch.setattr(
        work,
        "dispatch_claim",
        lambda claim: BotReply(
            "Draft requested.",
            (),
            "azure_gpt41",
            13,
            5,
            (DraftBrief("scribe", "Organize saved invented notes.", REQUIREMENTS),),
        ),
    )
    result = f.client.post(
        f.base + "/conversation", headers=f.headers, json={**f.body, "role": "chief"}
    )
    assert result.status_code == 200, result.text
    snapshot = f.client.get(f.base, headers=f.headers).json()
    handoff = snapshot["handoffs"][0]
    with Session(f.engine) as s:
        admission = s.scalar(
            select(ModelWorkAdmission).where(
                ModelWorkAdmission.handoff_attempt_id == handoff["attempt_id"]
            )
        )
        claimed = work.claim(s, f.box, f.actor, admission.id)
        work.settle(s, claimed, ModelCallFailure(dispatch="not_dispatched"))
    body = {
        "expected_revision": 3,
        "previous_attempt_id": handoff["attempt_id"],
        "idempotency_key": "invented-exact-handoff-retry",
    }
    path = f.base + "/handoffs/" + handoff["id"] + "/retry"
    assert (
        f.client.post(path + "/resolve", headers=f.headers, json=body).json()["outcome"]
        == "not_found"
    )
    recorded = f.client.post(path, headers=f.headers, json=body)
    assert recorded.status_code == 200, recorded.text
    assert (
        recorded.json()["outcome"] == "recorded"
        and recorded.json()["recorded"]["status"] == "queued"
    )
    assert recorded.json()["recorded"]["result_entry"] is None
    f.configuration.workspace_llm_backend = "none"
    assert f.client.post(path, headers=f.headers, json=body).json() == recorded.json()
    assert f.client.post(path + "/resolve", headers=f.headers, json=body).json() == recorded.json()
    with Session(f.engine) as s:
        assert (
            s.scalar(
                select(func.count())
                .select_from(WorkspaceHandoffAttempt)
                .where(WorkspaceHandoffAttempt.handoff_id == handoff["id"])
            )
            == 2
        )
        assert (
            s.scalar(
                select(func.count())
                .select_from(ModelWorkAdmission)
                .where(ModelWorkAdmission.workspace_id == f.workspace["id"])
            )
            == 3
        )
    (tmp_path / "model-handoff-recorded.json").write_text(
        json.dumps(recorded.json(), sort_keys=True)
    )
    (tmp_path / "model-handoff-request.json").write_text(
        json.dumps(
            {"workspace_id": f.workspace["id"], "handoff_id": handoff["id"], "body": body},
            sort_keys=True,
        )
    )

    # Leave no queued work for a later independent synthetic worker test.
    with Session(f.engine) as s:
        assert work.claim(s, f.box, f.actor, recorded.json()["recorded"]["admission"]["id"]) is None
