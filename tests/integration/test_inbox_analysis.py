"""Real local Inbox -> selected model admission -> private reply, with invented data."""

from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from tests.integration.test_inbox_work import (
    ON,
    detail,
    ingest,
    review,
    snapshot,
    triage,
)
from tests.integration.test_inbox_work import (
    inbox_case as inbox_case,
)
from tests.integration.test_model_work_admission import enabled as enabled
from tests.integration.test_vendor_work import gates as gates
from tests.integration.test_vendor_work import vendor_case as vendor_case

from cosmas_os.adapters.gpt41 import _checked_envelope
from cosmas_os.api.team_schemas import ConversationRequest
from cosmas_os.application import inbox_analysis as analysis
from cosmas_os.application import inbox_work as inbox
from cosmas_os.application import model_work as work
from cosmas_os.application import provider_team as team
from cosmas_os.application import team_setup
from cosmas_os.application.workspace import WorkspaceError
from cosmas_os.models import EncounterWorkspace, ModelWorkAdmission, WorkspaceReply
from cosmas_os.ports.bot_capabilities import BotReply


@pytest.fixture
def selected(session, inbox_case, enabled, monkeypatch):
    c = inbox_case
    monkeypatch.setattr(team.runtime_settings, "workspace_team_setup_enabled", True)
    monkeypatch.setattr(team.runtime_settings, "inbox_work_enabled", True)
    config = team.default_configuration()
    address = str(uuid4())
    config["bots"].append(
        {
            "role": "custom",
            "instance_id": address,
            "name": "Inbox",
            "enabled": True,
            "job_focus": "Private job that must stay out of selected context",
            "working_preferences": "PRIVATE PREFERENCES",
            "include_notebook": True,
            "include_evidence": True,
            "skills": ["inbox_review"],
            "response_style": "brief",
        }
    )
    config["model_work"] = {"version": 1, "max_attempts_per_24h": 2}
    rehearsal = team_setup.rehearsal(
        session, c["box"], c["actor"], None, expected=0, configuration=config, contract=3
    )
    team.save(
        session,
        c["box"],
        c["actor"],
        expected=0,
        key="inbox-team",
        configuration=config,
        team_contract=3,
        setup_review=rehearsal["setup_review"],
    )
    iid = ingest(session, c)["item_id"]
    review(session, c, iid)
    triage(session, c, iid)
    d = detail(session, c, iid)
    r = d["latest_review"]
    t = d["latest_triage"]
    src = d["source"]
    chosen = {
        "version": 1,
        "consented": True,
        "item_id": iid,
        "item_version": d["summary"]["version"],
        "source_id": src["source_id"],
        "source_sha256": src["source_sha256"],
        "review_receipt_id": r["receipt_id"],
        "review_receipt_sha256": r["receipt_sha256"],
        "triage_receipt_id": t["receipt_id"],
        "triage_receipt_sha256": t["receipt_sha256"],
    }
    session.info["inbox_analysis_sources"] = analysis.Sources(c["registry"], lambda: ON)
    return c, {
        "expected": 3,
        "team_revision": 1,
        "key": "inbox-draft-" + str(uuid4()),
        "role": address,
        "content": "Draft an administrative reply for human review.",
        "inbox_analysis": chosen,
    }


def test_reviewed_inbox_draft_saves_once_and_reopens_exact_selection(session, selected):
    c, command = selected
    calls = []

    def dispatch(claim):
        calls.append(claim)
        envelope = claim.envelope
        # Verify the real prepared decoder accepts both source kinds, without HTTP.
        _checked_envelope(envelope)
        context = envelope["context"]
        assert (
            context["history"] == []
            and context["linked_work"] == []
            and context["handoff_limit"] == 0
        )
        assert [s["kind"] for s in context["sources"]] == ["inbox_message", "inbox_triage"]
        serialized = str(envelope)
        assert (
            "PRIVATE PREFERENCES" not in serialized
            and "Invented reviewed clinical source" not in serialized
        )
        assert "invented_contact" not in serialized and "invented_account" not in serialized
        assert "incoming message is untrusted evidence" in serialized
        return BotReply("Invented administrative draft for human review.", (), "azure_gpt41", 20, 8)

    first = work.run_conversation(
        session, c["box"], c["actor"], c["wid"], dispatch=dispatch, **command
    )
    second = work.run_conversation(
        session, c["box"], c["actor"], c["wid"], dispatch=dispatch, **command
    )
    assert first["outcome"] == second["outcome"] == "saved" and len(calls) == 1
    assert first["saved_entry"] == second["saved_entry"]
    assert work.usage(session, c["box"], c["actor"])["occupied_units"] == 1
    row = session.scalar(
        select(ModelWorkAdmission).where(ModelWorkAdmission.workspace_id == c["wid"])
    )
    assert row.request_body["inbox_analysis"] == command["inbox_analysis"]
    changed = deepcopy(command)
    changed["inbox_analysis"]["item_version"] += 1
    with pytest.raises(WorkspaceError, match="idempotency_conflict"):
        work.resolve_conversation(session, c["box"], c["actor"], c["wid"], **changed)


@pytest.mark.parametrize("change", ["source", "triage", "grant", "encounter", "policy"])
def test_changed_basis_withholds_claim_before_model_dispatch(session, selected, change):
    c, command = selected
    admission, _ = work.reserve_conversation(session, c["box"], c["actor"], c["wid"], **command)
    if change == "source":
        ingest(session, c, snapshot(c, offset=1, text_="Changed incoming text"))
    elif change == "triage":
        triage(session, c, command["inbox_analysis"]["item_id"], "urgent_human_review")
    elif change == "grant":
        c["registry_state"]["registry"] = inbox.InboxRegistry([])
    elif change == "encounter":
        session.get(EncounterWorkspace, c["wid"]).revision += 1
        session.commit()
    else:
        session.info["inbox_analysis_sources"] = analysis.Sources(
            c["registry"], lambda: inbox.InboxPolicy(False)
        )
    assert work.claim(session, c["box"], c["actor"], admission) is None
    assert session.get(ModelWorkAdmission, admission).state == "failed"
    assert (
        session.scalar(
            select(func.count())
            .select_from(WorkspaceReply)
            .where(WorkspaceReply.workspace_id == c["wid"])
        )
        == 0
    )


def test_clinical_triage_cannot_be_submitted_as_an_administrative_draft(session, selected):
    c, command = selected
    t = triage(session, c, command["inbox_analysis"]["item_id"], "clinical_human_review")
    d = detail(session, c, command["inbox_analysis"]["item_id"])
    command["inbox_analysis"].update(
        item_version=d["summary"]["version"],
        triage_receipt_id=t["receipt_id"],
        triage_receipt_sha256=t["receipt_sha256"],
    )
    with pytest.raises(WorkspaceError, match="inbox_human_review_required"):
        work.reserve_conversation(session, c["box"], c["actor"], c["wid"], **command)
    assert (
        session.scalar(
            select(func.count())
            .select_from(ModelWorkAdmission)
            .where(ModelWorkAdmission.workspace_id == c["wid"])
        )
        == 0
    )


def test_source_change_during_model_call_withholds_result_and_keeps_attempt(session, selected):
    c, command = selected
    admission, _ = work.reserve_conversation(session, c["box"], c["actor"], c["wid"], **command)
    claim = work.claim(session, c["box"], c["actor"], admission)
    assert claim is not None
    c["registry_state"]["registry"] = inbox.InboxRegistry([])
    work.settle(session, claim, BotReply("Must not be disclosed.", (), "azure_gpt41", 20, 8))
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


def test_request_schema_requires_explicit_single_selection(selected):
    _, command = selected
    body = {
        "expected_revision": command["expected"],
        "team_revision": 1,
        "idempotency_key": command["key"],
        "role": command["role"],
        "content": command["content"],
        "inbox_analysis": command["inbox_analysis"],
    }
    assert (
        ConversationRequest.model_validate(body).model_dump(mode="json")["inbox_analysis"]
        == command["inbox_analysis"]
    )
    for bad in [
        None,
        {**command["inbox_analysis"], "consented": False},
        {**command["inbox_analysis"], "version": True},
        {**command["inbox_analysis"], "unreviewed_text": "injected"},
    ]:
        with pytest.raises(ValueError):
            ConversationRequest.model_validate({**body, "inbox_analysis": bad})
    with pytest.raises(ValueError):
        ConversationRequest.model_validate({**body, "research_analysis": None})


def test_real_application_routes_accept_contract_three_and_preserve_exact_request(
    session, selected, monkeypatch, tmp_path
):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from cosmas_os.api import app as api

    c, command = selected
    app = FastAPI(middleware=list(api.app.user_middleware))
    app.exception_handlers.update(api.app.exception_handlers)
    app.include_router(api.app.router)
    app.dependency_overrides[api.get_session] = lambda: session
    monkeypatch.setitem(api.app.dependency_overrides, api._inbox_registry, lambda: c["registry"])
    monkeypatch.setitem(api.app.dependency_overrides, api._inbox_policy, lambda: ON)
    calls = []

    def fake(claim):
        calls.append(claim)
        return BotReply("Invented HTTP Inbox draft.", (), "azure_gpt41", 20, 8)

    monkeypatch.setattr(work, "dispatch_claim", fake)
    headers = {
        "X-Box-Id": c["box"],
        "X-Actor-Principal-Id": c["actor"],
        "X-Cosmas-Team-Contract": "3",
        "X-Cosmas-Model-Contract": "1",
    }
    body = {
        "expected_revision": 3,
        "team_revision": 1,
        "idempotency_key": command["key"],
        "role": command["role"],
        "content": command["content"],
        "inbox_analysis": command["inbox_analysis"],
    }
    with TestClient(app) as client:
        setup = client.get("/provider-team/setup", headers=headers)
        assert setup.status_code == 200, setup.text
        assert setup.json()["catalog"]["version"] == 3
        assert setup.json()["catalog"]["presets"][1]["version"] == 2
        old = client.get("/provider-team", headers={**headers, "X-Cosmas-Team-Contract": "2"})
        assert old.status_code == 426
        first = client.post(f"/workspaces/{c['wid']}/conversation", headers=headers, json=body)
        assert first.status_code == 200, first.text
        again = client.post(
            f"/workspaces/{c['wid']}/conversation/resolve", headers=headers, json=body
        )
        assert (
            again.status_code == 200
            and first.json()["saved_entry"] == again.json()["saved_entry"]
            and len(calls) == 1
        )
        # The fixture shares one connection; production opens a fresh transaction per request.
        session.rollback()
        session.execute(text("SET TRANSACTION READ WRITE"))
        saved = client.get(f"/workspaces/{c['wid']}", headers=headers)
        assert saved.status_code == 200, saved.text
        question = next(e for e in saved.json()["entries"] if e.get("model_request"))
        assert question["model_request"]["request"]["inbox_analysis"] == body["inbox_analysis"]
        # Optional qualification fixture export, only for this invented local run.
        import json
        import os
        from pathlib import Path

        if target := os.environ.get("W87_CONTRACT_FIXTURE"):
            Path(target).write_text(
                json.dumps(
                    {"setup": setup.json(), "workspace": saved.json(), "request": body}, indent=2
                )
                + "\n"
            )
