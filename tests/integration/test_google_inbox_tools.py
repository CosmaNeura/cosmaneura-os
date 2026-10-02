"""Offline Google custody, exact selected evidence, real human F8 responsibility."""

import hashlib
import json
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
from lab.account_tools import prepared_account_sandboxes
from lab.application import Application
from lab.cases import CLINIC
from lab.inbox_tools import InboxTools
from lab.store import LabError, Store
from sqlalchemy import func, select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from cosmas_os.application import google_inbox, note_review, workspace
from cosmas_os.models import (
    Decision,
    ExternalIdentity,
    FollowUpReceipt,
    Operation,
    Principal,
    Ticket,
    WorkHandoff,
    WorkspaceCoreNoteSource,
    WorkspaceEntry,
    WorkspaceNote,
    WorkspaceNoteReview,
)
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable


@pytest.fixture
def inbox(engine, tmp_path):
    store = Store(tmp_path)
    app = Application(engine, CLINIC, lambda role, kind, **values: store.event("inbox", role, kind, **values))
    with prepared_account_sandboxes(app, ("google",)) as boxes:
        tools = InboxTools(app, store, "inbox")
        yield app, store, boxes["google"], tools


def call(inbox, name, args, role="follow_up"):
    return inbox[3].call(role, name, args)


def revision(app):
    with Session(app.engine) as session:
        return workspace.read(session, app.box, app.owner, app.workspace)["revision"]


def select_message(inbox, read_key="read-one", key="select-one"):
    receipt = call(inbox, "google_inbox_read_headers", {"idempotency_key": read_key})
    assert receipt["status"] == "ready", receipt
    args = {"read_key": read_key, "message_id": "lab1", "expected_workspace_revision": revision(inbox[0]), "idempotency_key": key}
    return receipt, args, call(inbox, "google_inbox_select_message", args)


def prepare(inbox):
    receipt, selection, saved = select_message(inbox)
    assert saved["status"] == "saved", saved
    command = {"selection_key": selection["idempotency_key"], "expected_workspace_revision": revision(inbox[0]), "idempotency_key": "review-one"}
    draft = call(inbox, "google_inbox_prepare_review", command)
    assert draft["status"] == "private_draft", draft
    return receipt, selection, saved, command, draft


def counts(app):
    with Session(app.engine) as session:
        return {name: session.scalar(select(func.count()).select_from(model).where(model.box_id == app.box))
            for name, model in (("tickets", Ticket), ("decisions", Decision), ("operations", Operation),
                                ("receipts", FollowUpReceipt), ("handoffs", WorkHandoff), ("note_reviews", WorkspaceNoteReview))}


def test_lost_reply_reopens_journal_exact_selection_draft_and_actual_human_handoff(inbox):
    app, store, box, tools = inbox
    receipt, selection, saved, command, draft = prepare(inbox)
    before = len(box.calls)
    tools.store = Store(store.root)
    reread = call(inbox, "google_inbox_read_headers", {"idempotency_key": "read-one"})
    resave = call(inbox, "google_inbox_select_message", selection)
    redraft = call(inbox, "google_inbox_prepare_review", command)
    assert reread["observation"] == receipt["observation"] and reread["idempotent_replay"]
    assert saved["entry_id"] == resave["entry_id"] and resave["idempotent_replay"]
    assert draft["draft_entry_id"] == redraft["draft_entry_id"] and redraft["idempotent_replay"]
    assert len(box.calls) == before
    assert counts(app) == {"tickets": 0, "decisions": 0, "operations": 0, "receipts": 0, "handoffs": 0, "note_reviews": 0}
    with Session(app.engine) as session:
        entry = session.get(WorkspaceEntry, saved["entry_id"])
        assert entry is not None
        payload = json.loads(entry.content)
        assert hashlib.sha256(entry.content.encode()).hexdigest() == saved["content_sha256"]
        assert payload["read_receipt_sha256"] == receipt["read_receipt_sha256"]
        assert payload["message"] == receipt["observation"]["items"][0]
        private = session.get(WorkspaceEntry, draft["draft_entry_id"])
        assert private is not None and private.kind == "scratchpad"
    assert len(app.sources()) == (len(CLINIC.inputs) or 1) + 1
    discovered = call(inbox, "google_inbox_list_reviews", {}, role="chief")
    assert discovered["items"][0]["review_key"] == "review-one"
    human = {"actor_id": app.owner, "expected_workspace_revision": revision(app),
             "idempotency_key": "human-review-one", "metadata_only_acknowledged": True}
    offered = tools.human_review_assign(draft["draft_entry_id"], **human)
    repeated = tools.human_review_assign(draft["draft_entry_id"], **human)
    assert repeated["f8"]["ticket_id"] == offered["f8"]["ticket_id"]
    assert offered["responsible_id"] == app.owner and offered["f8"]["pending_offer"] is not None
    assert '"gmail_message_id":"lab1"' in offered["f8"]["body"]
    assert '"sender":"jordan@example.invalid"' in offered["f8"]["body"]
    assert "untrusted metadata" in offered["f8"]["body"]
    assert counts(app) == {"tickets": 1, "decisions": 1, "operations": 1, "receipts": 1, "handoffs": 1, "note_reviews": 1}
    accept = {"actor_id": tools.reviewer_id, "idempotency_key": "accept-one",
              "offer_id": offered["f8"]["pending_offer"]["id"], "expected_version": offered["f8"]["version"]}
    received = tools.human_accept(draft["draft_entry_id"], **accept)
    retry = tools.human_accept(draft["draft_entry_id"], **accept)
    assert received["responsible_id"] == retry["responsible_id"] == tools.reviewer_id
    assert received["f8"]["pending_offer"] is None and len(received["f8"]["handoffs"]) == 2
    status = call(inbox, "google_inbox_review_status", {"review_key": "review-one"}, role="chief")
    assert status["metadata_reviewed_by_human"] and status["metadata_review_current"]
    assert status["classification"] == "needs_human" and status["incomplete_message"]
    assert not status["whole_message_reviewed"] and not status["completed"] and status["external_effects"] == 0
    with Session(app.engine) as session:
        decision = session.scalar(select(Decision).where(Decision.box_id == app.box))
        assert decision is not None
        actor = session.get(Principal, decision.actor_principal_id)
        assert actor is not None and actor.principal_type == "human"
        operation = session.scalar(select(Operation).where(Operation.box_id == app.box))
        assert operation is not None and operation.adapter == "workspace_synthetic"
        local_receipt = session.scalar(select(FollowUpReceipt).where(FollowUpReceipt.operation_id == operation.id))
        assert local_receipt is not None and operation.external_reference == "local:" + local_receipt.id
    assert len(box.calls) == before
    assert Store(store.root).visible("inbox", "chief") == []


@pytest.mark.parametrize("role", ["scribe", "visit_prep", "research"])
def test_wrong_role_cannot_read_or_create_google_review(inbox, role):
    result = call(inbox, "google_inbox_read_headers", {"idempotency_key": "read"}, role=role)
    assert result["error"] == "google_inbox_tool_role_denied"
    assert counts(inbox[0])["tickets"] == 0


@pytest.mark.parametrize("fault", ["read_timeout", "oversized", "long_retry_after_429", "revoked_during_read"])
def test_failed_read_is_not_empty_or_selected_and_retry_has_no_partial_observation(inbox, fault):
    app, store, box, _ = inbox
    box.fault = fault
    result = call(inbox, "google_inbox_read_headers", {"idempotency_key": "read-failed"})
    assert result["status"] == "failed" and "observation" not in result
    assert Store(store.root).visible("inbox:google-inbox", "follow_up") == []
    assert len(app.sources()) == (len(CLINIC.inputs) or 1)
    if fault == "read_timeout":
        recovered = call(inbox, "google_inbox_read_headers", {"idempotency_key": "read-failed"})
        assert recovered["status"] == "ready"
    if fault == "revoked_during_read":
        before = len(box.calls)
        again = call(inbox, "google_inbox_read_headers", {"idempotency_key": "read-failed"})
        assert again["status"] == "failed" and len(box.calls) == before


def test_unobserved_or_other_role_key_and_changed_save_intent_rejected(inbox):
    _, selection, saved = select_message(inbox)
    assert saved["status"] == "saved"
    for args in ({**selection, "message_id": "unknown"}, {**selection, "read_key": "never-read"}):
        failed = call(inbox, "google_inbox_select_message", args)
        assert failed["status"] == "failed"
    wrong_role = call(inbox, "google_inbox_select_message", selection, role="chief")
    assert wrong_role["error"] == "artifact_not_found"
    before = revision(inbox[0])
    inbox[2].now += timedelta(seconds=1)
    second = call(inbox, "google_inbox_read_headers", {"idempotency_key": "read-two"})
    assert second["status"] == "ready"
    changed = call(inbox, "google_inbox_select_message", {**selection, "read_key": "read-two"})
    assert changed["error"] == "idempotency_conflict" and revision(inbox[0]) == before


def test_local_out_of_order_capture_cannot_replace_current_metadata_and_equal_time_conflicts(inbox):
    app, _, box, _ = inbox
    _, _, first = select_message(inbox)
    first_time = box.now
    box.now -= timedelta(minutes=1)
    _, _, old = select_message(inbox, "older-read", "older-save")
    assert old["source_state"] == "superseded"
    old_prepare = call(inbox, "google_inbox_prepare_review", {"selection_key": "older-save",
        "expected_workspace_revision": revision(app), "idempotency_key": "older-draft"})
    assert old_prepare["error"] == "google_inbox_superseded"
    box.now = first_time
    original = box.respond
    def changed_response(request):
        result = original(request)
        if request.url.path.endswith("/messages/lab1"):
            result.read()
            payload = result.json()
            payload["payload"]["headers"][0]["value"] = "Synthetic changed Subject at same capture time"
            return httpx.Response(200, headers={"content-type": "application/json"},
                stream=httpx.ByteStream(json.dumps(payload).encode()))
        return result
    box.service._transport = httpx.MockTransport(changed_response)
    _, _, conflict = select_message(inbox, "conflict-read", "conflict-save")
    assert conflict["source_state"] == "source_conflict"
    first_prepare = call(inbox, "google_inbox_prepare_review", {"selection_key": "select-one",
        "expected_workspace_revision": revision(app), "idempotency_key": "first-draft"})
    assert first_prepare["error"] == "google_inbox_source_conflict"
    assert first["source_state"] == "current"  # Immutable earlier receipt remains historical.


def test_agent_human_review_and_implicit_acknowledgment_refused(inbox):
    app, _, _, tools = inbox
    *_, draft = prepare(inbox)
    args = {"expected_workspace_revision": revision(app), "idempotency_key": "human-review"}
    with pytest.raises(workspace.WorkspaceError, match="google_inbox_metadata_acknowledgment_required"):
        tools.human_review_assign(draft["draft_entry_id"], actor_id=app.owner, **args)
    with pytest.raises(workspace.WorkspaceError):
        tools.human_review_assign(draft["draft_entry_id"], actor_id=app.agent_id("follow_up"), metadata_only_acknowledged=True, **args)
    assert counts(app)["decisions"] == counts(app)["note_reviews"] == 0


def test_revoked_account_blocks_old_read_save_status_and_human_admission(inbox):
    app, _, box, tools = inbox
    *_, draft = prepare(inbox)
    with Session(app.engine) as session:
        account = session.get(ExternalIdentity, box.account)
        assert account is not None
        account.active = False
        session.commit()
    before = len(box.calls)
    for name, args in (("google_inbox_read_headers", {"idempotency_key": "read-one"}),
            ("google_inbox_review_status", {"review_key": "review-one"}),
            ("google_inbox_list_reviews", {})):
        result = call(inbox, name, args)
        assert result["status"] == "failed" and "observation" not in result and "f8" not in result
    with pytest.raises((ConnectorUnavailable, workspace.WorkspaceError)):
        tools.human_review_assign(draft["draft_entry_id"], actor_id=app.owner,
            expected_workspace_revision=revision(app), idempotency_key="human-revoked", metadata_only_acknowledged=True)
    assert len(box.calls) == before and counts(app)["decisions"] == 0


def test_new_selected_source_invalidates_metadata_review_and_rejects_staff_accept(inbox):
    app, _, box, tools = inbox
    *_, draft = prepare(inbox)
    offered = tools.human_review_assign(draft["draft_entry_id"], actor_id=app.owner,
        expected_workspace_revision=revision(app), idempotency_key="human-review", metadata_only_acknowledged=True)
    box.now += timedelta(seconds=2)
    _, _, latest = select_message(inbox, "new-read", "new-save")
    assert latest["source_state"] == "current"
    status = call(inbox, "google_inbox_review_status", {"review_key": "review-one"}, role="chief")
    assert status["status"] == "needs_human" and not status["metadata_review_current"]
    assert status["metadata_reviewed_by_human"] and not status["whole_message_reviewed"]
    with pytest.raises(Exception, match="google_inbox_source_changed"):
        tools.human_accept(draft["draft_entry_id"], actor_id=tools.reviewer_id, idempotency_key="accept-stale",
            offer_id=offered["f8"]["pending_offer"]["id"], expected_version=offered["f8"]["version"])
    assert counts(app)["handoffs"] == 1


def test_revoked_recipient_cannot_accept_but_original_offer_reply_is_recoverable(inbox):
    app, _, _, tools = inbox
    *_, draft = prepare(inbox)
    args = {"actor_id": app.owner, "expected_workspace_revision": revision(app),
        "idempotency_key": "human-review", "metadata_only_acknowledged": True}
    offered = tools.human_review_assign(draft["draft_entry_id"], **args)
    with Session(app.engine) as session:
        person = session.get(Principal, tools.reviewer_id)
        assert person is not None
        person.state = "disabled"
        session.commit()
    replay = tools.human_review_assign(draft["draft_entry_id"], **args)
    assert replay["f8"]["pending_offer"]["id"] == offered["f8"]["pending_offer"]["id"]
    with pytest.raises(workspace.WorkspaceError):
        tools.human_accept(draft["draft_entry_id"], actor_id=tools.reviewer_id, idempotency_key="accept-revoked",
            offer_id=offered["f8"]["pending_offer"]["id"], expected_version=offered["f8"]["version"])
    assert counts(app)["handoffs"] == 1


def test_changed_metadata_acknowledgment_key_cannot_duplicate_human_work(inbox):
    app, _, _, tools = inbox
    *_, draft = prepare(inbox)
    args = {"actor_id": app.owner, "expected_workspace_revision": revision(app),
        "idempotency_key": "human-review", "metadata_only_acknowledged": True}
    tools.human_review_assign(draft["draft_entry_id"], **args)
    with pytest.raises(workspace.WorkspaceError, match="idempotency_conflict"):
        tools.human_review_assign(draft["draft_entry_id"], **{**args, "idempotency_key": "changed-human-key"})
    assert counts(app)["tickets"] == 1


def test_role_revocation_during_read_never_publishes_header_receipt(inbox):
    app, store, box, _ = inbox
    original = box.respond
    def revoke_role(request):
        response = original(request)
        if request.url.path.endswith("/messages/lab1"):
            with Session(app.engine) as session:
                agent = session.get(Principal, app.agent_id("follow_up"))
                assert agent is not None
                agent.state = "disabled"
                session.commit()
        return response
    box.service._transport = httpx.MockTransport(revoke_role)
    receipt = call(inbox, "google_inbox_read_headers", {"idempotency_key": "revoked-role"})
    assert receipt["status"] == "failed" and "observation" not in receipt
    assert Store(store.root).visible("inbox:google-inbox", "follow_up") == []


def test_real_database_rejects_mutation_of_selected_evidence(inbox):
    app, _, _, _ = inbox
    _, _, saved = select_message(inbox)
    with Session(app.engine) as session:
        source = session.get(WorkspaceEntry, saved["entry_id"])
        assert source is not None
        payload = json.loads(source.content)
        payload["message"]["subject"] = "invented custody tampering"
        source.content = json.dumps(payload)
        with pytest.raises(ProgrammingError, match="workspace history is immutable"):
            session.commit()
        session.rollback()
    result = call(inbox, "google_inbox_prepare_review", {"selection_key": "select-one",
        "expected_workspace_revision": revision(app), "idempotency_key": "tampered-review"})
    assert result["status"] == "private_draft"
    assert counts(app)["tickets"] == 0


def test_lost_reply_after_durable_approval_recovers_same_operation_before_offer(inbox, monkeypatch):
    from cosmas_os.application import follow_up
    app, _, _, tools = inbox
    *_, draft = prepare(inbox)
    args = {"actor_id": app.owner, "expected_workspace_revision": revision(app),
        "idempotency_key": "human-interrupted", "metadata_only_acknowledged": True}
    original = follow_up.deliver
    def interrupted(*args, **kwargs):
        raise LabError("injected_lost_reply_after_approval")
    monkeypatch.setattr(follow_up, "deliver", interrupted)
    with pytest.raises(LabError, match="injected_lost_reply_after_approval"):
        tools.human_review_assign(draft["draft_entry_id"], **args)
    assert counts(app) == {"tickets": 1, "decisions": 1, "operations": 1, "receipts": 0, "handoffs": 0, "note_reviews": 1}
    monkeypatch.setattr(follow_up, "deliver", original)
    recovered = tools.human_review_assign(draft["draft_entry_id"], **args)
    assert recovered["f8"]["pending_offer"] is not None
    assert counts(app) == {"tickets": 1, "decisions": 1, "operations": 1, "receipts": 1, "handoffs": 1, "note_reviews": 1}


def test_account_revoked_after_approval_cannot_execute_local_effect_or_offer(inbox, monkeypatch):
    from cosmas_os.application import follow_up
    app, _, box, tools = inbox
    *_, draft = prepare(inbox)
    original = follow_up.decide
    def revoke_after_approval(*args, **kwargs):
        result = original(*args, **kwargs)
        with Session(app.engine) as session:
            identity = session.get(ExternalIdentity, box.account)
            assert identity is not None
            identity.active = False
            session.commit()
        return result
    monkeypatch.setattr(follow_up, "decide", revoke_after_approval)
    with pytest.raises((ConnectorUnavailable, workspace.WorkspaceError)):
        tools.human_review_assign(draft["draft_entry_id"], actor_id=app.owner,
            expected_workspace_revision=revision(app), idempotency_key="human-revoke-between",
            metadata_only_acknowledged=True)
    assert counts(app) == {"tickets": 1, "decisions": 1, "operations": 1, "receipts": 0, "handoffs": 0, "note_reviews": 1}


@pytest.mark.parametrize("content", ["[]", "null"])
def test_unrelated_json_values_do_not_break_selection_draft_or_human_status(inbox, content):
    app, _, _, tools = inbox
    with Session(app.engine) as session:
        for kind in ("evidence", "scratchpad", "conversation"):
            workspace.append(session, app.box, app.owner, app.workspace, expected=revision(app),
                key="unrelated-" + kind, kind=kind, content=content,
                source_label="Synthetic unrelated JSON" if kind == "evidence" else None)
    *_, draft = prepare(inbox)
    assert call(inbox, "google_inbox_list_reviews", {}, role="chief")["status"] == "ready"
    human = tools.human_review_assign(draft["draft_entry_id"], actor_id=app.owner,
        expected_workspace_revision=revision(app), idempotency_key="human-unrelated-json", metadata_only_acknowledged=True)
    assert human["status"] == "human_handoff"
    assert call(inbox, "google_inbox_review_status", {"review_key": "review-one"}, role="chief")["status"] == "human_handoff"


def test_review_key_is_unique_across_roles_and_exact_original_retry_still_resolves(inbox):
    app, _, _, _ = inbox
    *_, original_command, draft = prepare(inbox)
    read = call(inbox, "google_inbox_read_headers", {"idempotency_key": "chief-read"}, role="chief")
    assert read["status"] == "ready"
    saved = call(inbox, "google_inbox_select_message", {"read_key": "chief-read", "message_id": "lab1",
        "expected_workspace_revision": revision(app), "idempotency_key": "chief-select"}, role="chief")
    assert saved["status"] == "saved"
    before = revision(app)
    collision = call(inbox, "google_inbox_prepare_review", {"selection_key": "chief-select",
        "expected_workspace_revision": before, "idempotency_key": "review-one"}, role="chief")
    assert collision["error"] == "google_inbox_review_key_conflict" and revision(app) == before
    replay = call(inbox, "google_inbox_prepare_review", original_command)
    assert replay["draft_entry_id"] == draft["draft_entry_id"] and replay["idempotent_replay"]
    status = call(inbox, "google_inbox_review_status", {"review_key": "review-one"}, role="chief")
    assert status["draft_entry_id"] == draft["draft_entry_id"]


@pytest.mark.parametrize("core_linked", [False, True])
def test_existing_manual_or_core_note_is_preserved_and_refusal_writes_no_review_stage(inbox, core_linked):
    from tests.unit.test_core_capture_notes import draft as core_draft

    from cosmas_os.ports.core_notes import CoreDraftReceipt, CoreDraftReference
    app, _, _, tools = inbox
    *_, prepared = prepare(inbox)
    with Session(app.engine) as session:
        snapshot = note_review.save(session, app.box, app.owner, app.workspace,
            expected=revision(app), key="existing-encounter-note", base_note_id=None, source_reply_id=None,
            content="SYNTHETIC EXISTING ENCOUNTER NOTE — preserve its current content.")["workspace"]
        original = snapshot["note"]["latest"]
        if core_linked:
            checked = CoreDraftReceipt.model_validate(core_draft(uuid4()))
            reference = CoreDraftReference.from_draft(checked).model_dump(mode="json")
            session.add(WorkspaceCoreNoteSource(note_id=original["id"], workspace_id=app.workspace,
                box_id=app.box, owner_id=app.owner, content_hash=original["content_hash"],
                source_fingerprint=original["source_fingerprint"], note_type=checked.note_type, **reference))
            session.commit()
        before = workspace.read(session, app.box, app.owner, app.workspace)
    with pytest.raises(workspace.WorkspaceError, match="metadata_handoff_requires_separate_reviewed_note_context"):
        tools.human_review_assign(prepared["draft_entry_id"], actor_id=app.owner,
            expected_workspace_revision=before["revision"], idempotency_key="human-preserve-note", metadata_only_acknowledged=True)
    with Session(app.engine) as session:
        after = workspace.read(session, app.box, app.owner, app.workspace)
        assert after["revision"] == before["revision"] and after["entries"] == before["entries"]
        assert after["note"]["latest"] == before["note"]["latest"]
        assert session.scalar(select(func.count()).select_from(WorkspaceNote).where(WorkspaceNote.workspace_id == app.workspace)) == 1
        assert session.scalar(select(func.count()).select_from(WorkspaceCoreNoteSource).where(WorkspaceCoreNoteSource.workspace_id == app.workspace)) == int(core_linked)
        stages = [json.loads(row.content) for row in session.scalars(select(WorkspaceEntry).where(
            WorkspaceEntry.workspace_id == app.workspace, WorkspaceEntry.kind == "conversation"))]
        assert not any(isinstance(row, dict) and row.get("schema") == google_inbox.REVIEW for row in stages)
    assert counts(app) == {"tickets": 0, "decisions": 0, "operations": 0, "receipts": 0, "handoffs": 0, "note_reviews": 0}
