"""Real signed API and PostgreSQL; synthetic Core and model transports."""

from datetime import UTC, datetime

import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session
from tests.integration.test_session_prep import read, setup
from tests.integration.test_workspace_capture import capture_case as _capture_case

from cosmas_os.application import conversation, handoffs
from cosmas_os.application import model_work as work
from cosmas_os.application import provider_team as team
from cosmas_os.application.session_prep_analysis import anchor
from cosmas_os.models import (
    CoreCaptureAccount,
    EncounterWorkspace,
    ExternalIdentity,
    ModelWorkAdmission,
    Principal,
    WorkspaceReply,
)
from cosmas_os.ports.bot_capabilities import BotReply, ModelCallFailure

capture_case = _capture_case


@pytest.fixture
def case(capture_case, monkeypatch):
    f = capture_case
    f.configuration.workspace_llm_backend = "azure_gpt41"
    f.configuration.workspace_llm_api_key = SecretStr("invented-no-network")
    for module in (conversation, handoffs, team):
        monkeypatch.setattr(module, "runtime_settings", f.configuration)
    f.bot, _ = setup(f, monkeypatch)
    result = read(f, f.bot)
    assert result.status_code == 200, result.text
    f.selected = anchor(result.json()["receipt"])
    f.prep.calls.clear()
    f.base = f"/workspaces/{f.workspace['id']}"
    f.headers = {"Authorization": "Bearer " + f.token(), "X-Cosmas-Model-Contract": "1"}
    f.body = {"expected_revision": 1, "team_revision": 1, "role": "visit_prep",
              "idempotency_key": "invented-prep-question", "content": "What should I discuss?",
              "session_prep_analysis": f.selected}
    f.model_calls = []

    def no_locked_rows(_phase):
        # This would fail immediately if a model or Core phase retained SQL locks.
        with Session(f.engine) as current:
            for model, identity in ((EncounterWorkspace, f.workspace["id"]),
                                    (Principal, f.actor), (ExternalIdentity, f.identity_id),
                                    (CoreCaptureAccount, f.account_id)):
                assert current.get(model, identity, with_for_update={"nowait": True}) is not None

    f.prep.after = no_locked_rows

    def model(claim):
        no_locked_rows("model")
        f.model_calls.append(claim)
        return BotReply("Invented answer using the selected brief.", (), "azure_gpt41", 20, 7)

    monkeypatch.setattr(work, "dispatch_claim", model)
    return f


def test_selected_brief_is_used_once_and_replay_resolve_reopen_keep_exact_selection(case, tmp_path):
    f = case
    saved = f.client.post(f.base + "/conversation", headers=f.headers, json=f.body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["outcome"] == "saved" and saved.json()["admission"]["usage"] == "verified"
    assert len(f.model_calls) == 1 and len(f.prep.calls) == 12
    context = f.model_calls[0].envelope["context"]
    assert any(source["kind"] == "session_prep" and "Invented reviewed visit summary." in source["content"] for source in context["sources"])
    assert "not the underlying clinical notes" in f.model_calls[0].envelope["body"]["messages"][0]["content"]
    current = f.client.get(f.base, headers=f.headers)
    assert current.status_code == 200, current.text
    entry = current.json()["entries"][-1]
    assert entry["model_request"]["request"]["session_prep_analysis"] == f.selected
    assert entry["model_request"]["request_sha256"] == saved.json()["request_sha256"]
    import json

    (tmp_path / "session-prep-chat.json").write_text(json.dumps({
        "request": f.body, "observation": saved.json(), "workspace": current.json(),
    }, indent=2) + "\n")
    f.configuration.workspace_session_prep_enabled = False
    f.configuration.workspace_llm_backend = "none"
    for path in ("/conversation", "/conversation/resolve"):
        replay = f.client.post(f.base + path, headers=f.headers, json=f.body)
        assert replay.status_code == 200 and replay.json() == saved.json(), replay.text
    assert len(f.model_calls) == 1 and len(f.prep.calls) == 12
    omitted = {key: value for key, value in f.body.items() if key != "session_prep_analysis"}
    assert f.client.post(f.base + "/conversation/resolve", headers=f.headers, json=omitted).status_code == 409


def test_changed_display_prevents_admission_or_model_call(case):
    f = case
    f.prep.state = "refreshing"
    result = f.client.post(f.base + "/conversation", headers=f.headers, json=f.body)
    assert result.status_code == 409 and result.json()["detail"] == "source_changed", result.text
    assert not f.model_calls
    with Session(f.engine) as s:
        assert s.scalar(select(ModelWorkAdmission).where(ModelWorkAdmission.workspace_id == f.workspace["id"])) is None


@pytest.mark.parametrize("change", ["brief", "account", "identity"])
def test_changed_or_revoked_source_after_model_withholds_answer_and_retains_usage(case, monkeypatch, change):
    f = case

    def model(claim):
        f.model_calls.append(claim)
        if change == "brief":
            f.prep.state = "refreshing"
        else:
            with Session(f.engine) as s:
                if change == "account":
                    s.get(CoreCaptureAccount, f.account_id).revoked_at = datetime.now(UTC)
                else:
                    s.get(ExternalIdentity, f.identity_id).active = False
                s.commit()
        return BotReply("Must never be published.", (), "azure_gpt41", 20, 7)

    monkeypatch.setattr(work, "dispatch_claim", model)
    result = f.client.post(f.base + "/conversation", headers=f.headers, json=f.body)
    assert result.status_code in {403, 409}, result.text
    assert "Must never be published" not in result.text
    with Session(f.engine) as s:
        row = s.scalar(select(ModelWorkAdmission).where(ModelWorkAdmission.workspace_id == f.workspace["id"]))
        assert row.state == "failed" and row.result_entry_id is None
        observed = work.admission_observation(s, row, datetime.now(UTC))
        assert observed["usage"] == "verified" and observed["input_tokens"] == 20 and observed["output_tokens"] == 7
        assert s.get(WorkspaceReply, row.request_entry_id) is None
    assert len(f.model_calls) == 1


def test_uncertain_model_is_not_resent_and_does_not_refresh_sources_after_dispatch(case, monkeypatch):
    f = case

    def model(claim):
        f.model_calls.append(claim)
        raise ModelCallFailure(dispatch="started_unconfirmed")

    monkeypatch.setattr(work, "dispatch_claim", model)
    first = f.client.post(f.base + "/conversation", headers=f.headers, json=f.body)
    assert first.status_code == 409 and first.json()["outcome"] == "unknown", first.text
    for path in ("/conversation", "/conversation/resolve"):
        result = f.client.post(f.base + path, headers=f.headers, json=f.body)
        assert result.json() == first.json()
    assert len(f.model_calls) == 1 and len(f.prep.calls) == 6


def test_removing_brief_also_excludes_uncited_previous_answers_from_history(case):
    f = case
    result = f.client.post(f.base + "/conversation", headers=f.headers, json=f.body)
    assert result.status_code == 200, result.text
    body = {key: value for key, value in f.body.items() if key != "session_prep_analysis"}
    body.update(expected_revision=2, idempotency_key="invented-local-only-question")
    second = f.client.post(f.base + "/conversation", headers=f.headers, json=body)
    assert second.status_code == 200, second.text
    assert len(f.model_calls) == 2 and len(f.prep.calls) == 12
    context = f.model_calls[-1].envelope["context"]
    assert context["history"] == []
    assert all(source["kind"] != "session_prep" for source in context["sources"])
