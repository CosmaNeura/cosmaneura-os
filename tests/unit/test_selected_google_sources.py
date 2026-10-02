"""Typed custody dispatch and uncited lineage masking; no live account or DB."""

from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy.orm import Session

from cosmas_os.application import handoff_review, model_work, note_review
from cosmas_os.application import selected_google_sources as sources
from cosmas_os.application import workspace as ws
from cosmas_os.ports.bot_capabilities import SourcePassage


class FakeSession:
    def __init__(self, entries):
        self.entries = {row.id: row for row in entries}
        self.scalar_result: SimpleNamespace | None = None

    def get(self, _, entry_id):
        return self.entries.get(entry_id)

    def scalar(self, _):
        return self.scalar_result


def entry(identifier, kind, revision=1):
    return SimpleNamespace(
        id=identifier,
        kind=kind,
        revision=revision,
        source_label="Invented " + kind,
        content="Invented bounded source " + identifier,
    )


@pytest.mark.parametrize(
    "kind,field",
    [("google_message", "google_source_state"), ("google_calendar", "calendar_source_state")],
)
def test_only_dedicated_custody_validates_and_historical_is_separate(monkeypatch, kind, field):
    row = entry("source_a", kind)
    session, workspace = FakeSession([row]), object()
    calls = []
    service = SimpleNamespace(
        validate_selected_source=lambda s, w, i: calls.append(("current", s, w, i)) or row,
        historical_source=lambda s, w, i: calls.append(("historical", s, w, i)) or row,
    )
    monkeypatch.setattr(
        sources,
        "_service",
        lambda requested: service if requested == kind else pytest.fail("wrong custody"),
    )
    assert sources.validate_selected_source(session, workspace, row.id) is row
    assert sources.historical_source(session, workspace, row.id) is row
    assert [call[0] for call in calls] == ["current", "historical"]
    assert sources.source_state_field(kind) == field


@pytest.mark.parametrize("kind", ["evidence", "scratchpad", "google", None])
def test_ordinary_or_missing_source_cannot_be_normalized(kind):
    row = entry("source_a", kind) if kind else None
    session = FakeSession([row] if row else [])
    with pytest.raises(ws.WorkspaceError, match="selected_google_source_invalid"):
        sources.validate_selected_source(session, object(), "source_a")
    with pytest.raises(ws.WorkspaceError, match="selected_google_source_invalid"):
        sources.historical_source(session, object(), "source_a")


def test_all_frozen_inputs_mask_uncited_result_and_feedback_independently(monkeypatch):
    rows = [
        entry("email", "google_message"),
        entry("calendar", "google_calendar"),
        entry("ordinary", "evidence"),
    ]
    context = SimpleNamespace(
        sources=tuple(
            SourcePassage(row.id, row.revision, row.source_label, "evidence", row.content)
            for row in rows
        )
    )

    def validate(_, __, identifier):
        raise ws.WorkspaceError(
            "calendar_source_expired"
            if identifier == "calendar"
            else "google_message_grant_unavailable"
        )

    monkeypatch.setattr(sources, "validate_selected_source", validate)
    assert sources.unavailable_states(FakeSession(rows), object(), context) == {
        "google_source_state",
        "calendar_source_state",
    }
    assert sources.projection_unavailable({"calendar_source_state": "unavailable"})
    assert sources.projection_unavailable(
        {"google_source_state": "unavailable", "calendar_source_state": "current"}
    )
    assert not sources.projection_unavailable({"calendar_source_state": "current"})


def test_source_passages_merge_in_exact_revision_order(monkeypatch):
    mail = SourcePassage("mail", 4, "Invented mail", "evidence", "Invented email")
    calendar = SourcePassage("calendar", 3, "Invented calendar", "evidence", "Invented summary")
    monkeypatch.setattr(model_work, "_google_message_passages", lambda *args: (mail,))
    monkeypatch.setattr(model_work, "_google_calendar_passages", lambda *args: (calendar,))
    assert model_work._selected_google_passages(None, None, None) == (calendar, mail)


@pytest.mark.parametrize("kind", ["google_message", "google_calendar"])
def test_connector_derived_reply_never_imports_into_clinical_note(monkeypatch, kind):
    row = entry("private_source", kind)
    session = FakeSession([row])
    session.scalar_result = SimpleNamespace(prepared_envelope={"context": "invented"})
    from cosmas_os.adapters import gpt41

    monkeypatch.setattr(
        gpt41, "_context", lambda _: SimpleNamespace(sources=(SimpleNamespace(entry_id=row.id),))
    )
    workspace = SimpleNamespace(id="workspace", box_id="box", owner_id="owner")
    with pytest.raises(ws.WorkspaceError, match=kind + "_note_import_unavailable"):
        note_review._require_note_lineage(cast(Session, session), workspace, "reply")


def test_calendar_masks_exact_historical_review_command_receipt(monkeypatch):
    review = SimpleNamespace(
        workspace_revision=9,
        result_entry_id="result",
        handoff_id="handoff",
        expected_revision=8,
        idempotency_key="review_key",
        attempt_id="attempt",
        result_sha256="a" * 64,
        decision="accepted",
        feedback="Invented private feedback",
    )
    workspace = SimpleNamespace(id="workspace", box_id="box", owner_id="owner")
    snapshot = {
        "entries": [
            {"id": "result", "calendar_source_state": "unavailable", "content": "", "reply": None}
        ]
    }
    monkeypatch.setattr(ws, "read", lambda *args: snapshot)
    receipt = handoff_review._command_receipt(None, workspace, review)
    assert receipt["feedback_withheld"] and receipt["workspace"] is snapshot
    assert len(receipt["request_sha256"]) == 64 and receipt["entry_revision"] == 9
