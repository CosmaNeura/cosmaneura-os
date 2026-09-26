"""Signed Scribe task/source selection around existing Core admission and notes."""

from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from tests.integration.test_workspace_capture import admit
from tests.integration.test_workspace_capture import capture_case as _capture_case
from tests.integration.test_workspace_capture_notes import perform, setup
from tests.unit.test_core_capture_notes import draft

from cosmas_os.application import provider_team as team
from cosmas_os.application import workspace as ws
from cosmas_os.models import AuditEvent
from cosmas_os.ports.core_notes import CoreDraftReceipt, CoreDraftReference
from cosmas_os.ports.notebook_source import NotebookSource

capture_case = _capture_case


def install(f):
    config = team.default_configuration()
    address = str(uuid4())
    config["bots"].append({**config["bots"][0], "instance_id": address, "name": "Visit partner"})
    saved = team.save(f.session, f.box, f.actor, expected=0, key="team", configuration=config)
    return {"address": address, "team_revision": 1}, saved


def jot(f, expected=1, content="Invented clinician scratch notes"):
    return ws.append(f.session, f.box, f.actor, f.workspace["id"], expected=expected,
                     key=str(uuid4()), kind="scratchpad", content=content)


def sourced_port(f):
    observed = []
    def note(binding, credential, session_id, selection):
        observed.append(selection)
        f.port.step("note")
        value = draft(session_id)
        if selection.scratch_notes:
            value["notebook_source"] = selection.scratch_notes.model_dump(mode="json", exclude={"content"})
        return CoreDraftReceipt.model_validate(value)
    f.port.capture_note = note
    return observed


@pytest.mark.parametrize("capture,notes", [(False, False), (True, False), (True, True)])
def test_scribe_settings_describe_current_capture_services(capture_case, monkeypatch, capture, notes):
    f = capture_case
    monkeypatch.setattr(team, "runtime_settings", f.configuration)
    monkeypatch.setattr(team.runtime_settings, "workspace_capture_backend", "core" if capture else "disabled")
    monkeypatch.setattr(team.runtime_settings, "workspace_capture_notes_enabled", notes)
    _, saved = install(f)
    capabilities = {item["key"]: item for item in saved["members"][-1]["capabilities"]}
    assert capabilities["scribe.capture"]["state"] == ("enabled" if capture else "awaiting_connection")
    assert capabilities["core.note.draft"]["state"] == ("enabled" if capture and notes else "awaiting_connection")


def test_scribe_task_uses_exact_bot_and_server_saved_notebook(capture_case):
    f = capture_case
    bot, saved = install(f)
    assert admit(f, bot=bot).status_code == 200
    setup(f)
    scratch = jot(f)
    observed = sourced_port(f)
    result = perform(f, "prepare", scratchpad_entry_id=scratch["entry_id"], bot=bot)
    assert result.status_code == 200, result.text
    assert observed[0].scratch_notes.content == "Invented clinician scratch notes"
    assert observed[0].scratch_notes.revision == 2
    receipt = result.json()["receipt"]
    assert receipt["notebook_source"]["entry_id"] == scratch["entry_id"]
    audit = f.session.scalar(select(AuditEvent).where(AuditEvent.aggregate_id == f.workspace["id"],
        AuditEvent.event_type == "workspace.bot_note_confirmed"))
    assert audit.actor_principal_id == saved["members"][-1]["agent_id"]
    assert audit.initiated_by_principal_id == f.actor and audit.detail["note_ref"] == receipt["note_ref"]


@pytest.mark.parametrize("phase", ["exchange", "resolve", "binding", "admit", "note"])
def test_notebook_change_during_remote_work_withholds_result(capture_case, phase):
    f = capture_case
    setup(f)
    scratch = jot(f)
    sourced_port(f)
    def change(observed):
        if observed == phase:
            with Session(f.engine) as s:
                ws.append(s, f.box, f.actor, f.workspace["id"], expected=2,
                    key=str(uuid4()), kind="scratchpad", content="A newer invented source")
    f.port.after = change
    response = perform(f, "prepare", scratchpad_entry_id=scratch["entry_id"])
    assert response.status_code == 409 and "receipt" not in response.json()
    assert len(f.port.calls) == ["exchange", "resolve", "binding", "admit", "note"].index(phase) + 1


@pytest.mark.parametrize("fault", ["paused", "retired", "stale", "foreign_bot", "wrong_template", "source_disabled"])
def test_bot_preferences_cannot_grant_capture_or_source_authority(capture_case, fault):
    f = capture_case
    setup(f)
    bot, saved = install(f)
    scratch = jot(f)
    config = deepcopy(saved["configuration"])
    if fault in {"paused", "retired", "source_disabled"}:
        config["bots"][-1]["include_notebook" if fault == "source_disabled" else "enabled"] = False
        if fault == "retired":
            config["bots"][-1]["retired"] = True
        team.save(f.session, f.box, f.actor, expected=1, key="change", configuration=config)
        bot["team_revision"] = 2
    if fault == "stale":
        bot["team_revision"] = 2
    if fault == "foreign_bot":
        bot["address"] = str(uuid4())
    if fault == "wrong_template":
        bot["address"] = "chief"
    response = perform(f, "prepare", scratchpad_entry_id=scratch["entry_id"], bot=bot)
    assert response.status_code == 409
    assert f.port.calls == []


def test_browser_cannot_supply_notebook_text_or_choose_an_old_revision(capture_case):
    f = capture_case
    setup(f)
    scratch = jot(f)
    newer = jot(f, expected=2, content="Latest invented notes")
    assert perform(f, "prepare", scratchpad_entry_id=scratch["entry_id"]).status_code == 409
    assert perform(f, "prepare", scratchpad_entry_id=str(uuid4())).status_code == 409
    response = perform(f, "prepare", scratchpad_entry_id=newer["entry_id"], note={"action": "prepare",
        "schema_ref": "doctor_note_schema_" + "0" * 25 + "1", "scratch_notes": {"content": "Substituted private sentinel"}})
    assert response.status_code == 422 and "private sentinel" not in response.text and not f.port.calls


def test_link_and_review_bind_notebook_provenance_and_reject_later_notebook(capture_case):
    f = capture_case
    setup(f)
    scratch = jot(f)
    observed = sourced_port(f)
    response = perform(f, "prepare", scratchpad_entry_id=scratch["entry_id"])
    receipt = CoreDraftReceipt.model_validate(response.json()["receipt"])
    source = CoreDraftReference.from_draft(receipt).model_dump(mode="json")
    assert NotebookSource.model_validate(source["notebook_source"]).entry_id == observed[0].scratch_notes.entry_id
    f.port.capture_note = lambda *_: receipt
    path = f"/workspaces/{f.workspace['id']}"
    headers = {"Authorization": "Bearer " + f.token()}
    linked = f.client.post(path + "/capture/note-links", headers=headers, json={"expected_revision": 2,
        "idempotency_key": "source-link", "base_note_id": None, "source": source})
    assert linked.status_code == 200, linked.text
    note = linked.json()["workspace"]["note"]["latest"]
    assert note["core_source"]["notebook_source"] == source["notebook_source"]
    jot(f, expected=3, content="A newer notebook after draft preparation")
    result = f.client.post(path + f"/notes/{note['id']}/review", headers=headers, json={"expected_revision": 4,
        "idempotency_key": "review-stale-notebook", "content_hash": note["content_hash"],
        "source_fingerprint": note["source_fingerprint"]})
    assert result.status_code == 409
