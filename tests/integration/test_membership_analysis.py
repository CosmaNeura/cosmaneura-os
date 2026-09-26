"""Selected real local membership/payment records to private, recoverable model review."""

from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from tests.integration.test_finance_work import (
    POLICY,
    approved,
    bound,
    call,
    created_observation,
    payment,
)
from tests.integration.test_finance_work import finance_case as finance_case
from tests.integration.test_membership_work import created, detail, result
from tests.integration.test_model_work_admission import enabled as enabled
from tests.integration.test_vendor_work import gates as gates
from tests.integration.test_vendor_work import vendor_case as vendor_case

from cosmas_os import (
    inbox_models,  # noqa: F401 - register referenced ORM tables before test DB creation
)
from cosmas_os.adapters.gpt41 import _checked_envelope
from cosmas_os.api import vendor_work_schemas as public
from cosmas_os.api.team_schemas import ConversationRequest
from cosmas_os.application import finance_execution, finance_work, team_setup
from cosmas_os.application import membership_analysis as analysis
from cosmas_os.application import model_work as work
from cosmas_os.application import provider_team as team
from cosmas_os.application import workspace as ws
from cosmas_os.application.workspace import WorkspaceError
from cosmas_os.finance_models import FinanceConnectionVersion
from cosmas_os.models import ModelWorkAdmission, Ticket, WorkspaceReply
from cosmas_os.ports.bot_capabilities import BotReply


@pytest.fixture(params=["membership", "payment"])
def selected(session, finance_case, enabled, monkeypatch, request):
    c = finance_case
    for name in ("workspace_team_setup_enabled", "membership_work_enabled", "finance_work_enabled"):
        monkeypatch.setattr(team.runtime_settings, name, True)
    config = team.default_configuration()
    address = str(uuid4())
    config["bots"].append(
        {
            "role": "custom",
            "instance_id": address,
            "name": "Membership / Billing",
            "enabled": True,
            "job_focus": "PRIVATE JOB",
            "working_preferences": "PRIVATE PREFERENCES",
            "include_notebook": True,
            "include_evidence": True,
            "skills": ["membership_review"],
            "response_style": "brief",
        }
    )
    config["model_work"] = {"version": 1, "max_attempts_per_24h": 2}
    rehearsal = team_setup.rehearsal(
        session, c["box"], c["actor"], None, expected=0, configuration=config, contract=4
    )
    team.save(
        session,
        c["box"],
        c["actor"],
        expected=0,
        key="membership-team",
        configuration=config,
        team_contract=4,
        setup_review=rehearsal["setup_review"],
    )
    kind = request.param
    if kind == "membership":
        tid = created(session, c)
        result(session, c, tid)
        d = detail(session, c, tid)
    else:
        tid, _, d = approved(session, c)
        _, invocation = call(
            session,
            c,
            finance_execution.claim_submit,
            tid,
            public.BoundCommand(**bound(d)),
            policy=POLICY,
        )
        finance_execution.mark_invocation(session, invocation)
        finance_execution.settle(session, invocation, observation=created_observation(invocation))
        d = call(session, c, finance_work.detail, tid)
        _, observed = call(
            session,
            c,
            finance_execution.claim_read,
            tid,
            public.BoundCommand(**bound(d)),
            policy=POLICY,
        )
        finance_execution.settle(session, observed, observation=payment(observed))
        d = call(session, c, finance_work.detail, tid)
        assert (
            d["summary"]["payment_state"] == "succeeded"
            and d["summary"]["verification"] == "pending"
        )
    chosen = {
        "version": 1,
        "consented": True,
        "kind": kind,
        "ticket_id": tid,
        "ticket_version": d["summary"]["version"],
        "revision_id": d["summary"]["revision_id"],
        "payload_hash": d["summary"]["payload_hash"],
        "snapshot_sha256": public.public_digest(analysis.DOMAIN, analysis.snapshot(kind, d)),
    }
    return (
        c,
        {
            "expected": 3,
            "team_revision": 1,
            "key": "membership-review-" + str(uuid4()),
            "role": address,
            "content": "Review selected work and concrete human next steps.",
            "membership_analysis": chosen,
        },
        d,
    )


def test_selected_review_saves_once_and_retains_exact_binding(session, selected):
    c, command, d = selected
    calls = []

    def dispatch(claim):
        calls.append(claim)
        _checked_envelope(claim.envelope)
        context = claim.envelope["context"]
        assert (
            context["history"] == []
            and context["linked_work"] == []
            and context["handoff_limit"] == 0
        )
        assert context["sources"][0]["kind"] == (
            "membership_work"
            if command["membership_analysis"]["kind"] == "membership"
            else "payment_work"
        )
        serialized = str(claim.envelope)
        for private in (
            "PRIVATE JOB",
            "PRIVATE PREFERENCES",
            "Invented reviewed clinical source",
            "acct_Invented",
            "cus_Invented",
            "Invented patient billing account",
        ):
            assert private not in serialized
        assert "a payment does not establish membership" in serialized
        return BotReply("Invented evidence review and human next steps.", (), "azure_gpt41", 20, 8)

    first = work.run_conversation(
        session, c["box"], c["actor"], c["wid"], **command, dispatch=dispatch
    )
    again = work.run_conversation(
        session, c["box"], c["actor"], c["wid"], **command, dispatch=dispatch
    )
    assert first["outcome"] == again["outcome"] == "saved" and len(calls) == 1
    assert first["saved_entry"] == again["saved_entry"]
    saved = work.project_workspace(session, ws.read(session, c["box"], c["actor"], c["wid"]))
    entry = next(e for e in saved["entries"] if e.get("model_request"))
    assert (
        entry["model_request"]["request"]["membership_analysis"] == command["membership_analysis"]
    )


@pytest.mark.parametrize("change", ["selection", "workspace", "feature"])
def test_changed_selection_scope_or_feature_refuses_admission(
    session, selected, monkeypatch, change
):
    c, command, _ = selected
    if change == "selection":
        command = deepcopy(command)
        command["membership_analysis"]["snapshot_sha256"] = "0" * 64
    elif change == "workspace":
        command = {**command, "expected": 2}
    else:
        monkeypatch.setattr(
            team.runtime_settings,
            "membership_work_enabled"
            if command["membership_analysis"]["kind"] == "membership"
            else "finance_work_enabled",
            False,
        )
    with pytest.raises(WorkspaceError):
        work.reserve_conversation(session, c["box"], c["actor"], c["wid"], **command)
    assert (
        session.scalar(
            select(func.count())
            .select_from(ModelWorkAdmission)
            .where(ModelWorkAdmission.workspace_id == c["wid"])
        )
        == 0
    )


def test_changed_authority_after_dispatch_withholds_answer(session, selected, monkeypatch):
    c, command, _ = selected
    admission, _ = work.reserve_conversation(session, c["box"], c["actor"], c["wid"], **command)
    claim = work.claim(session, c["box"], c["actor"], admission)
    assert claim is not None
    if command["membership_analysis"]["kind"] == "payment":
        connection = session.get(FinanceConnectionVersion, c["finance_connection"]["id"])
        connection.read_enabled = False
        session.commit()
    else:
        monkeypatch.setattr(team.runtime_settings, "membership_work_enabled", False)
    work.settle(session, claim, BotReply("Must be withheld", (), "azure_gpt41", 20, 8))
    assert session.get(ModelWorkAdmission, admission).state == "failed"
    assert (
        session.scalar(
            select(func.count())
            .select_from(WorkspaceReply)
            .where(WorkspaceReply.workspace_id == c["wid"])
        )
        == 0
    )
    assert work.usage(session, c["box"], c["actor"])["occupied_units"] == 1


def test_explicit_single_consent_and_legacy_hash(session, selected):
    _, command, _ = selected
    body = {
        "expected_revision": 3,
        "team_revision": 1,
        "idempotency_key": command["key"],
        "role": command["role"],
        "content": command["content"],
        "membership_analysis": command["membership_analysis"],
    }
    assert ConversationRequest.model_validate(body).model_dump(mode="json") == body
    for bad in (
        None,
        {**command["membership_analysis"], "consented": False},
        {**command["membership_analysis"], "version": True},
        {**command["membership_analysis"], "unreviewed_text": "injected"},
    ):
        with pytest.raises(ValueError):
            ConversationRequest.model_validate({**body, "membership_analysis": bad})
    for field in ("inbox_analysis", "research_analysis"):
        with pytest.raises(ValueError):
            ConversationRequest.model_validate({**body, field: None})
    body.pop("membership_analysis")
    assert ConversationRequest.model_validate(body).model_dump(mode="json") == body


def test_actual_routes_and_exported_client_fixture(session, selected, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from cosmas_os.api import app as api

    c, command, d = selected
    app = FastAPI(middleware=list(api.app.user_middleware))
    app.exception_handlers.update(api.app.exception_handlers)
    app.include_router(api.app.router)
    app.dependency_overrides[api.get_session] = lambda: session
    monkeypatch.setattr(
        work,
        "dispatch_claim",
        lambda _: BotReply("Invented HTTP work review", (), "azure_gpt41", 20, 8),
    )
    headers = {
        "X-Box-Id": c["box"],
        "X-Actor-Principal-Id": c["actor"],
        "X-Cosmas-Team-Contract": "4",
        "X-Cosmas-Model-Contract": "1",
    }
    body = {
        "expected_revision": 3,
        "team_revision": 1,
        "idempotency_key": command["key"],
        "role": command["role"],
        "content": command["content"],
        "membership_analysis": command["membership_analysis"],
    }
    with TestClient(app) as client:
        setup = client.get("/provider-team/setup", headers=headers)
        assert setup.status_code == 200, setup.text
        assert (
            setup.json()["catalog"]["version"] == 4
            and setup.json()["catalog"]["presets"][2]["version"] == 2
        )
        old = client.get("/provider-team", headers={**headers, "X-Cosmas-Team-Contract": "3"})
        assert old.status_code == 426
        first = client.post(f"/workspaces/{c['wid']}/conversation", headers=headers, json=body)
        assert first.status_code == 200, first.text
        again = client.post(
            f"/workspaces/{c['wid']}/conversation/resolve", headers=headers, json=body
        )
        assert (
            again.status_code == 200 and first.json()["saved_entry"] == again.json()["saved_entry"]
        ), again.text
        session.rollback()
        session.execute(text("SET TRANSACTION READ WRITE"))
        saved = client.get(f"/workspaces/{c['wid']}", headers=headers)
        assert saved.status_code == 200, saved.text
        import json
        import os
        from pathlib import Path

        if folder := os.environ.get("W88_CONTRACT_FIXTURES"):
            Path(folder, command["membership_analysis"]["kind"] + "-analysis-w88.json").write_text(
                json.dumps(
                    {
                        "setup": setup.json(),
                        "workspace": saved.json(),
                        "request": body,
                        "detail": d,
                        "snapshot": analysis.snapshot(command["membership_analysis"]["kind"], d),
                    },
                    indent=2,
                )
                + "\n"
            )


def test_work_change_after_admission_refuses_dispatch(session, selected):
    c, command, _ = selected
    admission, _ = work.reserve_conversation(session, c["box"], c["actor"], c["wid"], **command)
    ticket = session.get(Ticket, command["membership_analysis"]["ticket_id"])
    ticket.version += 1
    session.commit()
    assert work.claim(session, c["box"], c["actor"], admission) is None
    row = session.get(ModelWorkAdmission, admission)
    assert row.state == "failed" and row.reason == "source_changed"
