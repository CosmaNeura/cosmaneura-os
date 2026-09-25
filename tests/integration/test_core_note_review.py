"""Exact Core lineage and current signed authority across the private F-8 loop."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from tests.integration.test_workspace_capture import admit
from tests.integration.test_workspace_capture import capture_case as _capture_case
from tests.unit.test_core_capture_notes import draft

from cosmas_os.api import app as api
from cosmas_os.application import core_note_review
from cosmas_os.application import follow_up as follow
from cosmas_os.application import workspace as ws
from cosmas_os.models import (
    CoreCaptureAccount,
    Decision,
    ExternalIdentity,
    FollowUpReceipt,
    Operation,
    PatientLink,
    WorkspaceCoreNoteSource,
    WorkspaceNote,
    WorkspaceNoteReview,
)
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.core_notes import CoreDraftReceipt, CoreDraftReference, note_content_hash

capture_case = _capture_case


@pytest.fixture
def case(capture_case):
    f = capture_case
    f.configuration.workspace_capture_notes_enabled = True
    assert admit(f).status_code == 200
    f.draft = draft(f.port.saved.session_id)
    f.source = CoreDraftReference.from_draft(CoreDraftReceipt.model_validate(f.draft)).model_dump(
        mode="json"
    )
    f.root = f"/workspaces/{f.workspace['id']}"
    f.port.calls.clear()

    def current(*_):
        f.port.step("note")
        return CoreDraftReceipt.model_validate(f.draft)

    f.port.capture_note = current
    return f


def post(f, path, body):
    return f.client.post(f.root + path, headers={"Authorization": "Bearer " + f.token()}, json=body)


def link(f, **changes):
    return post(
        f,
        "/capture/note-links",
        {
            "expected_revision": 1,
            "idempotency_key": "core-link",
            "base_note_id": None,
            "source": f.source,
            **changes,
        },
    )


def reviewed(f):
    result = link(f)
    assert result.status_code == 200, result.text
    f.note = result.json()["workspace"]["note"]["latest"]
    f.review_body = {
        "expected_revision": 2,
        "idempotency_key": "core-review",
        "content_hash": f.note["content_hash"],
        "source_fingerprint": f.note["source_fingerprint"],
    }
    result = post(f, f"/notes/{f.note['id']}/review", f.review_body)
    assert result.status_code == 200, result.text
    return result.json()["workspace"]


def proposal(f):
    return post(
        f,
        "/follow-ups",
        {
            "expected_revision": 3,
            "idempotency_key": "core-proposal",
            "note_id": f.note["id"],
            "body": "Invented visit reminder.",
            "due_date": "2026-09-25",
            "expected_outcome": "Invented appointment confirmed.",
            "share": True,
        },
    )


def proposed(f):
    reviewed(f)
    result = proposal(f)
    assert result.status_code == 200, result.text
    f.item = result.json()["workspace"]["follow_ups"][0]
    return f.item


def decide(f, choice="approve"):
    return post(
        f,
        f"/follow-ups/{f.item['ticket_id']}/decide",
        {
            "revision_id": f.item["revision_id"],
            "payload_hash": f.item["payload_hash"],
            "choice": choice,
        },
    )


def count(f, model):
    with Session(f.engine) as s:
        return s.scalar(select(func.count()).select_from(model).where(model.box_id == f.box))


def test_saved_core_note_to_review_to_exact_follow_up_and_completion(case):
    f = case
    proposed(f)
    assert f.note["source_reply_id"] is None
    assert f.note["content"] == "CC\nInvented visit\n\nPlan\nDiscuss sleep — synthetic only."
    assert f.note["core_source"] == {**f.source, "note_type": "Visit note"}
    assert f.item["core_check_required"] is True
    f.port.calls.clear()
    result = decide(f)
    assert result.status_code == 200, result.text
    assert f.port.calls == ["exchange", "resolve", "binding", "admit", "note"] * 2
    assert result.json()["workspace"]["follow_ups"][0]["state"] == "sent"
    assert decide(f).status_code == 200
    assert count(f, Operation) == count(f, Decision) == count(f, FollowUpReceipt) == 1
    result = post(
        f,
        f"/follow-ups/{f.item['ticket_id']}/complete",
        {
            "revision_id": f.item["revision_id"],
            "payload_hash": f.item["payload_hash"],
            "idempotency_key": "core-complete",
            "evidence": "Invented patient confirmed the visit in rehearsal.",
        },
    )
    assert result.status_code == 200, result.text
    assert result.json()["workspace"]["follow_ups"][0]["state"] == "closed"
    assert count(f, FollowUpReceipt) == 2


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_sha256", "b" * 64),
        ("note_ref", "visit_note_" + "0" * 25 + "2"),
        ("scribe_source_id", None),
        ("transcript_ref", "ai_visit_transcript_" + "0" * 25 + "2"),
        ("fields", None),
    ],
)
@pytest.mark.parametrize("phase", ["link", "review", "propose", "approve"])
def test_current_core_version_must_match_at_each_boundary(case, phase, field, value):
    f = case
    if phase in {"review", "propose", "approve"}:
        reviewed(f)
    if phase == "approve":
        result = proposal(f)
        assert result.status_code == 200, result.text
        f.item = result.json()["workspace"]["follow_ups"][0]
    if field == "fields":
        f.draft["fields"]["Plan"] = "Changed private sentinel"
        f.draft["note_sha256"] = note_content_hash(f.draft["fields"])
    else:
        f.draft[field] = str(uuid4()) if value is None else value
    if phase == "link":
        result = link(f)
    elif phase == "review":
        result = post(f, f"/notes/{f.note['id']}/review", f.review_body)
    elif phase == "propose":
        result = proposal(f)
    else:
        result = decide(f)
    assert result.status_code == 409, result.text
    assert "private sentinel" not in result.text
    assert count(f, Operation) == count(f, FollowUpReceipt) == 0


def test_idempotent_link_and_review_preserve_exact_history_and_reject_local_edit(case):
    f = case
    reviewed(f)
    assert link(f).status_code == 200
    assert post(f, f"/notes/{f.note['id']}/review", f.review_body).status_code == 200
    assert (
        count(f, WorkspaceNote)
        == count(f, WorkspaceNoteReview)
        == count(f, WorkspaceCoreNoteSource)
        == 1
    )
    result = post(
        f,
        "/notes",
        {
            "expected_revision": 3,
            "idempotency_key": "fork-clinical",
            "base_note_id": f.note["id"],
            "source_reply_id": None,
            "content": "Independently edited clinical record",
            "sources_reconciled": True,
        },
    )
    assert result.status_code == 409
    assert count(f, WorkspaceNote) == 1


@pytest.mark.parametrize("phase", ["exchange", "resolve", "binding", "admit", "note"])
@pytest.mark.parametrize("target", ["identity", "account", "patient"])
def test_revocation_during_core_check_prevents_local_review(case, phase, target):
    f = case
    result = link(f)
    assert result.status_code == 200, result.text
    n = result.json()["workspace"]["note"]["latest"]
    f.port.calls.clear()

    def revoke(observed):
        if observed != phase:
            return
        with Session(f.engine) as s:
            model, key = {
                "identity": (ExternalIdentity, f.identity_id),
                "account": (CoreCaptureAccount, f.account_id),
                "patient": (PatientLink, f.patient_link_id),
            }[target]
            row = s.get(model, key)
            if target == "identity":
                row.active = False
            else:
                row.revoked_at = datetime.now(UTC)
            s.commit()

    f.port.after = revoke
    result = post(
        f,
        f"/notes/{n['id']}/review",
        {
            "expected_revision": 2,
            "idempotency_key": "revoked-review",
            "content_hash": n["content_hash"],
            "source_fingerprint": n["source_fingerprint"],
        },
    )
    assert result.status_code in {403, 404, 409}, result.text
    assert count(f, WorkspaceNoteReview) == 0


@pytest.mark.parametrize("fault", ["changed", "unavailable", "revoked"])
def test_second_check_after_durable_approval_blocks_delivery_and_allows_recovery(case, fault):
    f = case
    proposed(f)
    seen = 0
    original = f.draft.copy()

    def fail(phase):
        nonlocal seen
        if phase != "note":
            return
        seen += 1
        if seen != 2:
            return
        if fault == "unavailable":
            raise ConnectorUnavailable("capture_notes_unavailable")
        if fault == "changed":
            f.draft["note_ref"] = "visit_note_" + "0" * 25 + "2"
        if fault == "revoked":
            with Session(f.engine) as s:
                s.get(CoreCaptureAccount, f.account_id).revoked_at = datetime.now(UTC)
                s.commit()

    f.port.after = fail
    result = decide(f)
    assert result.status_code in {409, 503}, result.text
    assert count(f, Operation) == count(f, Decision) == 1
    assert count(f, FollowUpReceipt) == 0
    with Session(f.engine) as s:
        with pytest.raises(ws.WorkspaceError, match="core_note_check_required"):
            follow.deliver(
                s,
                f.box,
                f.actor,
                f.workspace["id"],
                f.item["ticket_id"],
                revision_id=f.item["revision_id"],
                digest=f.item["payload_hash"],
            )
    f.port.after = lambda _: None
    if fault == "unavailable":
        f.draft = original
        assert decide(f).status_code == 200
        assert count(f, FollowUpReceipt) == 1
    else:
        assert decide(f, "reject").status_code == 200
        assert count(f, FollowUpReceipt) == 0


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE workspace_core_note_sources SET note_ref = note_ref",
        "DELETE FROM workspace_core_note_sources",
    ],
)
def test_core_reference_is_append_only(case, mutation):
    f = case
    assert link(f).status_code == 200
    with Session(f.engine) as s:
        with pytest.raises(DBAPIError):
            s.execute(text(mutation + " WHERE box_id = :box"), {"box": f.box})
            s.commit()


def test_core_read_is_required_and_flag_blocks_link_without_io(case):
    f = case
    f.configuration.workspace_capture_notes_enabled = False
    assert link(f).status_code == 404
    assert not f.port.calls
    with Session(f.engine) as s:
        with pytest.raises(ws.WorkspaceError, match="core_note_check_required"):
            core_note_review.import_saved(
                s,
                f.box,
                f.actor,
                f.workspace["id"],
                expected=1,
                key="bypass",
                base_note_id=None,
                selected=CoreDraftReference.model_validate(f.source),
                checked=None,
            )


@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_link_keeps_one_version_and_never_holds_local_locks_during_core_io(case, same_key):
    f = case
    barrier = Barrier(2)
    f.port.after = lambda phase: barrier.wait(timeout=10) if phase == "note" else None
    previous = api.app.dependency_overrides[api.get_session]

    def sessions():
        with Session(f.engine) as session:
            yield session

    api.app.dependency_overrides[api.get_session] = sessions
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(link, f, idempotency_key="same-link" if same_key else f"competing-link-{i}") for i in range(2)]
            responses = [future.result(timeout=20) for future in futures]
        assert sorted(response.status_code for response in responses) == ([200, 200] if same_key else [200, 409])
        assert count(f, WorkspaceNote) == count(f, WorkspaceCoreNoteSource) == 1
    finally:
        api.app.dependency_overrides[api.get_session] = previous
