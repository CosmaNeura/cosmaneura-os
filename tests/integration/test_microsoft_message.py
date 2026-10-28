"""Real PostgreSQL custody and human source review; all messages are invented."""

import hashlib
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from tests.integration.test_handoff_review import isolate_http_request, request_sessions
from tests.integration.test_note_review import prepare
from tests.integration.test_workspace_auth import signed_workspace as _signed_workspace
from tests.unit.test_core_capture_notes import draft

from cosmas_os.api import app as api_module
from cosmas_os.application import core_note_review
from cosmas_os.application import microsoft_message as messages
from cosmas_os.application import note_review as notes
from cosmas_os.application import workspace as ws
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.microsoft_connection_models import MicrosoftConnectionCredential
from cosmas_os.microsoft_message_models import (
    MicrosoftMessageReadRequest,
    MicrosoftMessageSnapshot,
    MicrosoftMessageSourceReview,
)
from cosmas_os.models import (
    Decision,
    EncounterWorkspace,
    ExternalIdentity,
    Operation,
    Principal,
    Ticket,
    WorkspaceCoreNoteSource,
    WorkspaceEntry,
    WorkspaceNote,
    WorkspaceNoteReview,
)
from cosmas_os.ports.core_notes import CoreDraftReceipt, CoreDraftReference
from cosmas_os.ports.microsoft_message import MicrosoftMessageBinding, MicrosoftMessageRead

signed_workspace = _signed_workspace


class InventedMicrosoft:
    def __init__(self, session, account, connected):
        self.session, self.account, self.connected = session, account, connected
        self.grant = "b" * 64
        self.text = "Subject: Invented message\nFrom: sender@example.invalid\n\nInvented administrative request café."
        self.calls = []
        self.after = lambda _: None
        self.fail = False
        self.incomplete = False

    def message_binding(self, identity, *, require_full=False, session=None):
        assert session is self.session
        assert identity.external_identity_id == self.account
        return MicrosoftMessageBinding(
            account_id=self.account,
            binding_digest="a" * 64,
            connected_at=self.connected,
            grant_sha256=self.grant,
        )

    def message_status(self, identity, *, session=None):
        return dict(
            contract_version=1,
            state="connected",
            full_mail_read=True,
            account={"label": "Invented account", "email": "owner@example.invalid"},
        )

    def step(self, name):
        assert not self.session.in_transaction(), "provider I/O must not hold a SQL transaction"
        self.calls.append(name)
        self.after(name)
        if self.fail:
            raise TimeoutError("invented lost provider response")

    def mail(self, identity):
        self.step("list")
        now = datetime.now(UTC).isoformat()
        return {
            "kind": "mail",
            "account": {"label": "Invented account", "email": "owner@example.invalid"},
            "items": [
                {
                    "id": "invented-message",
                    "subject": "Invented message",
                    "sender": "sender@example.invalid",
                    "received_at": now,
                    "is_read": False,
                }
            ],
            "more": False,
            "observed_at": now,
        }

    def read_message(self, identity, selection):
        self.step("read")
        return MicrosoftMessageRead(
            message_id=selection.message_id,
            thread_id="invented-thread",
            change_key="123",
            subject="Invented message",
            sender="sender@example.invalid",
            received_at=datetime.now(UTC),
            is_read=False,
            observed_at=datetime.now(UTC),
            status="needs_human" if self.incomplete else "complete",
            content=None if self.incomplete else self.text,
            reason="attachment" if self.incomplete else None,
            raw_sha256="c" * 64,
            content_sha256=None
            if self.incomplete
            else hashlib.sha256(self.text.encode()).hexdigest(),
            custody=self.message_binding(identity, session=self.session),
        )


@pytest.fixture
def case(session, seeded):
    box, owner, w, patient = prepare(session, seeded)
    account = ExternalIdentity(
        box_id=box,
        principal_id=owner,
        issuer=f"https://clerk-{uuid4()}.example.invalid",
        subject="invented-owner",
        organization_id="invented-org",
        reviewed_by="invented owner",
        evidence_ref="synthetic test",
    )
    session.add(account)
    session.flush()
    now = datetime.now(UTC)
    session.add(
        MicrosoftConnectionCredential(
            account_id=account.id,
            binding_digest="a" * 64,
            status="ready",
            sealed=b"i" * 40,
            connected_at=now,
            expires_at=now + timedelta(hours=1),
        )
    )
    session.commit()
    port = InventedMicrosoft(session, account.id, now)
    with messages.install_binding_reader(
        lambda s, a, full: port.message_binding(
            messages._scoped_identity(a), require_full=full, session=s
        )
    ):
        yield SimpleNamespace(
            s=session, box=box, owner=owner, w=w, patient=patient, account=account.id, port=port
        )


def observed(f, **changes):
    return messages.list_observed(
        f.s, f.box, f.owner, f.account, key=changes.pop("key", "list-1"), port=f.port, **changes
    )


def read(f, observation=None, **changes):
    observation = observation or observed(f)
    return messages.read_selected(
        f.s,
        f.box,
        f.owner,
        f.account,
        **{
            "key": "read-1",
            "observation_id": observation["read_id"],
            "observation_sha256": observation["source_sha256"],
            "message_id": "invented-message",
            "port": f.port,
            **changes,
        },
    )


def select_message(f, receipt=None, **changes):
    receipt = receipt or read(f)
    current = f.s.get(EncounterWorkspace, f.w["id"], populate_existing=True)
    return messages.select_review(
        f.s,
        f.box,
        f.owner,
        f.w["id"],
        **{
            "expected": current.revision,
            "key": "review-1",
            "read_id": receipt["read_id"],
            "source_sha256": receipt["source_sha256"],
            "patient_link_id": f.patient,
            "reviewed_patient": True,
            "reviewed_exact_message": True,
            "reviewed_untrusted_source": True,
            "port": f.port,
            "external_identity_id": f.account,
            **changes,
        },
    )


def rows(f, model):
    query = select(func.count()).select_from(model)
    if hasattr(model, "workspace_id"):
        query = query.where(model.workspace_id == f.w["id"])
    elif hasattr(model, "box_id"):
        query = query.where(model.box_id == f.box)
    return f.s.scalar(query)


def test_unselected_provider_read_is_private_then_explicit_human_review_saves_exact_source(case):
    f = case
    before = rows(f, WorkspaceEntry)
    prohibited = {
        m: rows(f, m)
        for m in (
            WorkspaceNote,
            WorkspaceNoteReview,
            WorkspaceCoreNoteSource,
            Ticket,
            Decision,
            Operation,
        )
    }
    receipt = read(f)
    assert rows(f, WorkspaceEntry) == before
    assert rows(f, MicrosoftMessageReadRequest) == 2 and rows(f, MicrosoftMessageSnapshot) == 2
    assert "custody" not in receipt["message"]
    result = select_message(f, receipt)
    entry = f.s.get(WorkspaceEntry, result["entry_id"])
    assert entry.kind == "microsoft_message" and entry.content == f.port.text
    assert result["source"]["content_sha256"] == hashlib.sha256(entry.content.encode()).hexdigest()
    assert rows(f, MicrosoftMessageSourceReview) == 1
    assert prohibited == {m: rows(f, m) for m in prohibited}
    assert f.port.calls == ["list", "read"]


def test_lost_read_and_selected_review_response_exact_replay_after_reopen_never_duplicates(case):
    f = case
    observation = observed(f)
    first = read(f, observation)
    f.s.expire_all()
    assert read(f, observation) == first
    assert (
        messages.resolve_read(
            f.s, f.box, f.owner, f.account, key="read-1", kind="message", port=f.port
        )
        == first
    )
    selected = select_message(f, first)
    again = select_message(f, first, expected=selected["entry_revision"] - 1)
    assert (
        again["entry_id"] == selected["entry_id"]
        and again["entry_revision"] == selected["entry_revision"]
    )
    with Session(bind=f.s.connection(), join_transaction_mode="create_savepoint") as reopened:
        w = reopened.get(EncounterWorkspace, f.w["id"])
        assert messages.historical_source(reopened, w, selected["entry_id"]).content == f.port.text
    assert rows(f, MicrosoftMessageSourceReview) == 1 and f.port.calls == ["list", "read"]


def test_unconfirmed_list_resolves_and_same_key_never_calls_provider_again(case):
    f = case
    f.port.fail = True
    with pytest.raises(ws.WorkspaceError, match="microsoft_message_read_unconfirmed"):
        observed(f)
    assert (
        messages.resolve_read(
            f.s, f.box, f.owner, f.account, key="list-1", kind="list", port=f.port
        )["status"]
        == "unconfirmed"
    )
    with pytest.raises(ws.WorkspaceError, match="microsoft_message_read_unconfirmed"):
        observed(f)
    assert f.port.calls == ["list"] and rows(f, MicrosoftMessageSnapshot) == 0
    assert (
        messages.resolve_read(
            f.s, f.box, f.owner, f.account, key="not-issued", kind="message", port=f.port
        )["status"]
        == "not_found"
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"message_id": "unobserved"},
        {"thread_id": "unobserved-thread"},
        {"observation_sha256": "0" * 64},
        {"observation_id": str(uuid4())},
    ],
)
def test_original_metadata_observation_is_exact_read_admission(case, changes):
    f = case
    observation = observed(f)
    with pytest.raises(ws.WorkspaceError):
        read(f, observation, **changes)
    assert f.port.calls == ["list"] and rows(f, MicrosoftMessageReadRequest) == 1


@pytest.mark.parametrize(
    "changes",
    [{"message_id": "changed"}, {"observation_sha256": "0" * 64}, {"thread_id": "changed"}],
)
def test_same_read_key_changed_selection_conflicts(case, changes):
    f = case
    observation = observed(f)
    read(f, observation)
    with pytest.raises(ws.WorkspaceError, match="idempotency_conflict"):
        read(f, observation, **changes)
    assert f.port.calls == ["list", "read"]


@pytest.mark.parametrize(
    "changes", [{"source_sha256": "0" * 64}, {"expected": 99}, {"read_id": str(uuid4())}]
)
def test_same_review_key_changed_intent_cannot_duplicate(case, changes):
    f = case
    receipt = read(f)
    selected = select_message(f, receipt)
    with pytest.raises(ws.WorkspaceError):
        select_message(
            f,
            receipt,
            expected=selected["entry_revision"] - 1,
            **{k: v for k, v in changes.items() if k != "expected"},
        ) if "expected" not in changes else select_message(f, receipt, **changes)
    assert rows(f, MicrosoftMessageSourceReview) == 1


@pytest.mark.parametrize(
    "field", ["reviewed_patient", "reviewed_exact_message", "reviewed_untrusted_source"]
)
def test_each_human_acknowledgment_required(case, field):
    f = case
    receipt = read(f)
    with pytest.raises(ws.WorkspaceError, match="invalid_microsoft_message_review"):
        select_message(f, receipt, **{field: False})
    assert rows(f, MicrosoftMessageSourceReview) == 0


def test_incomplete_message_cannot_be_selected_or_model_exposed(case):
    f = case
    f.port.incomplete = True
    receipt = read(f)
    assert receipt["message"]["content"] is None and receipt["status"] == "needs_human"
    with pytest.raises(ws.WorkspaceError, match="microsoft_message_incomplete"):
        select_message(f, receipt)
    assert rows(f, MicrosoftMessageSourceReview) == 0


@pytest.mark.parametrize("boundary", ["before", "during", "after"])
def test_external_identity_revocation_blocks_read_settlement(case, boundary):
    f = case
    observation = observed(f)
    calls = 0

    def revoke():
        nonlocal calls
        calls += 1
        if (boundary == "before" and calls == 1) or (boundary == "after" and calls == 3):
            f.s.get(ExternalIdentity, f.account).active = False
            f.s.flush()

    if boundary == "during":

        def during(name):
            if name == "read":
                f.s.get(ExternalIdentity, f.account).active = False
                f.s.commit()

        f.port.after = during
    with pytest.raises(ws.WorkspaceError, match="workspace_access_denied"):
        read(f, observation, reauthenticate=revoke)
    assert rows(f, MicrosoftMessageSnapshot) == 1 and rows(f, MicrosoftMessageSourceReview) == 0


@pytest.mark.parametrize("change", ["disconnect", "expiry", "binding", "consent", "semantic"])
def test_selected_source_current_grant_each_disclosure_and_historical_receipt_retained(
    case, change
):
    f = case
    selected = select_message(f)
    w = f.s.get(EncounterWorkspace, f.w["id"])
    assert (
        messages.validate_selected_source(f.s, w, selected["entry_id"]).id == selected["entry_id"]
    )
    credential = f.s.get(MicrosoftConnectionCredential, f.account)
    if change == "disconnect":
        credential.status = "disconnected"
    elif change == "expiry":
        credential.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    elif change == "binding":
        credential.binding_digest = "d" * 64
    elif change == "consent":
        credential.connected_at += timedelta(seconds=1)
    else:
        f.port.grant = "d" * 64
    f.s.flush()
    with pytest.raises(ws.WorkspaceError):
        messages.validate_selected_source(f.s, w, selected["entry_id"])
    assert messages.historical_source(f.s, w, selected["entry_id"]).content == f.port.text
    assert (
        messages.selected_entries(f.s, w, {"role": "chief", "include_evidence": True}, w.revision)
        == []
    )


def test_token_refresh_preserves_semantic_grant_and_source(case):
    f = case
    selected = select_message(f)
    credential = f.s.get(MicrosoftConnectionCredential, f.account)
    credential.sealed = b"r" * 60
    credential.expires_at += timedelta(hours=1)
    f.s.flush()
    w = f.s.get(EncounterWorkspace, f.w["id"])
    assert (
        messages.validate_selected_source(f.s, w, selected["entry_id"]).id == selected["entry_id"]
    )


@pytest.mark.parametrize("change", ["disconnect", "expiry", "superseded"])
def test_lost_source_review_reply_confirms_exact_command_without_restoring_access(case, change):
    f = case
    receipt = read(f)
    expected = f.s.get(EncounterWorkspace, f.w["id"]).revision
    selected = select_message(f, receipt, expected=expected)
    commitment = payload_hash(dict(
        workspace_id=f.w["id"], expected_revision=expected, idempotency_key="review-1",
        read_id=receipt["read_id"], source_sha256=receipt["source_sha256"],
        content_sha256=receipt["message"]["content_sha256"], reviewed_patient=True,
        reviewed_exact_message=True, reviewed_untrusted_source=True,
    ))
    assert selected["request_sha256"] == commitment and selected["source_withheld"] is False
    if change == "superseded":
        read(f, key="replacement-read")
    else:
        credential = f.s.get(MicrosoftConnectionCredential, f.account)
        if change == "disconnect":
            credential.status = "disconnected"
            credential.sealed = None
        else:
            credential.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        f.s.commit()
    calls = list(f.port.calls)
    replay = select_message(f, receipt, expected=expected)
    assert replay["request_sha256"] == commitment and replay["source_withheld"] is True
    assert replay["entry_id"] == selected["entry_id"] and replay["source"] == selected["source"]
    entry = next(e for e in replay["workspace"]["entries"] if e["id"] == selected["entry_id"])
    assert entry["content"] == "" and entry["microsoft_source_state"] == "unavailable"
    assert rows(f, MicrosoftMessageSourceReview) == 1 and f.port.calls == calls
    with pytest.raises(ws.WorkspaceError):
        select_message(f, receipt, expected=expected, key="new-review-intent")
    with pytest.raises(ws.WorkspaceError, match="idempotency_conflict"):
        select_message(f, receipt, expected=expected + 1)
    f.s.rollback()


def test_later_reservation_invalidates_older_body_even_when_newer_read_unconfirmed(case):
    f = case
    observation = observed(f)
    first = read(f, observation)
    saved = select_message(f, first)
    f.port.fail = True
    with pytest.raises(ws.WorkspaceError, match="microsoft_message_read_unconfirmed"):
        read(f, observation, key="read-2")
    w = f.s.get(EncounterWorkspace, f.w["id"])
    with pytest.raises(ws.WorkspaceError, match="microsoft_message_source_superseded"):
        messages.validate_selected_source(f.s, w, saved["entry_id"])
    assert messages.historical_source(f.s, w, saved["entry_id"]).content == f.port.text
    with pytest.raises(ws.WorkspaceError, match="microsoft_message_source_superseded"):
        select_message(f, first, key="old-review")


def test_out_of_order_old_response_never_replaces_newer_source(case):
    f = case
    observation = observed(f)
    original = f.port.read_message
    responses = []
    entered = False

    def interleaved(identity, selection):
        nonlocal entered
        if not entered:
            entered = True
            newer = messages.read_selected(
                f.s,
                f.box,
                f.owner,
                f.account,
                key="newer-body",
                observation_id=observation["read_id"],
                observation_sha256=observation["source_sha256"],
                message_id="invented-message",
                port=f.port,
            )
            responses.append(newer)
            f.s.commit()  # End settlement's projection transaction before the older provider completes.
        return original(identity, selection)

    f.port.read_message = interleaved
    older = read(f, observation, key="older-body")
    with pytest.raises(ws.WorkspaceError, match="microsoft_message_source_superseded"):
        select_message(f, older, key="old-source")
    saved = select_message(f, responses[0], key="new-source")
    w = f.s.get(EncounterWorkspace, f.w["id"])
    assert messages.validate_selected_source(f.s, w, saved["entry_id"]).id == saved["entry_id"]
    assert rows(f, MicrosoftMessageSourceReview) == 1


def test_manually_reviewed_clinical_note_coexists_unchanged(case):
    f = case
    w = notes.save(
        f.s,
        f.box,
        f.owner,
        f.w["id"],
        expected=1,
        key="note",
        base_note_id=None,
        source_reply_id=None,
        content="Invented reviewed clinical note.",
    )["workspace"]
    note = w["note"]["latest"]
    reviewed = notes.review(
        f.s,
        f.box,
        f.owner,
        f.w["id"],
        note["id"],
        expected=w["revision"],
        key="note-review",
        content_hash=note["content_hash"],
        source_hash=note["source_fingerprint"],
    )["workspace"]["note"]
    selected = select_message(f)
    assert selected["workspace"]["note"] == reviewed
    assert rows(f, WorkspaceNote) == 1 and rows(f, WorkspaceNoteReview) == 1
    assert rows(f, Ticket) == 0 and rows(f, Operation) == 0


def test_saved_reviewed_core_clinical_note_coexists_without_replacement(case):
    f = case
    checked = CoreDraftReceipt.model_validate(draft(uuid4()))
    selected = CoreDraftReference.from_draft(checked)
    w = core_note_review.import_saved(
        f.s,
        f.box,
        f.owner,
        f.w["id"],
        expected=1,
        key="core-note",
        base_note_id=None,
        selected=selected,
        checked=checked,
    )["workspace"]
    n = w["note"]["latest"]
    reviewed = notes.review(
        f.s,
        f.box,
        f.owner,
        f.w["id"],
        n["id"],
        expected=w["revision"],
        key="core-review",
        content_hash=n["content_hash"],
        source_hash=n["source_fingerprint"],
        core_checked=checked,
    )["workspace"]["note"]
    before = rows(f, WorkspaceCoreNoteSource)
    microsoft = select_message(f)
    assert microsoft["workspace"]["note"] == reviewed
    assert rows(f, WorkspaceCoreNoteSource) == before == 1
    assert rows(f, WorkspaceNote) == 1 and rows(f, WorkspaceNoteReview) == 1


def test_wrong_owner_or_agent_cannot_read_observe_or_review(case):
    f = case
    receipt = read(f)
    nurse = Principal(box_id=f.box, principal_type="human", display_name="Invented nurse")
    agent = Principal(box_id=f.box, principal_type="agent", display_name="Invented agent")
    f.s.add_all([nurse, agent])
    f.s.flush()
    for actor in (nurse.id, agent.id):
        with pytest.raises(ws.WorkspaceError):
            messages.list_observed(f.s, f.box, actor, f.account, key="foreign", port=f.port)
        with pytest.raises(ws.WorkspaceError):
            messages.inspect_read(
                f.s, f.box, actor, f.account, read_id=receipt["read_id"], port=f.port
            )
        with pytest.raises(ws.WorkspaceError):
            messages.select_review(
                f.s,
                f.box,
                actor,
                f.w["id"],
                expected=1,
                key="foreign",
                read_id=receipt["read_id"],
                source_sha256=receipt["source_sha256"],
                patient_link_id=f.patient,
                reviewed_patient=True,
                reviewed_exact_message=True,
                reviewed_untrusted_source=True,
                port=f.port,
            )
    assert f.port.calls == ["list", "read"] and rows(f, MicrosoftMessageSourceReview) == 0


@pytest.mark.parametrize(
    "table",
    ["microsoft_message_read_requests", "microsoft_message_snapshots", "microsoft_message_source_reviews"],
)
def test_database_immutable_custody_and_review(table, case):
    f = case
    select_message(f)
    with pytest.raises(DBAPIError), f.s.begin_nested():
        f.s.execute(text(f"UPDATE {table} SET owner_id=owner_id"))


@pytest.mark.parametrize("field,value", [
    ("raw_sha256", None), ("raw_sha256", 123),
    ("thread_id", None), ("thread_id", 123), ("change_key", 123),
    ("status", None), ("status", 123), ("reason", None), ("reason", 123),
] + [
    (field, value)
    for field in ("received_at", "observed_at", "custody.connected_at", "list.observed_at", "list.received_at")
    for value in (None, 17, "2026-10-02T12:00:00", "2026-02-30T12:00:00+00:00")
])
def test_database_rejects_forged_null_type_or_naive_snapshot_fields(case, field, value):
    f = case
    observation = observed(f)
    receipt = read(f, observation)
    valid = f.s.scalar(select(MicrosoftMessageSnapshot).where(MicrosoftMessageSnapshot.read_id == receipt["read_id"]))
    original = f.s.get(MicrosoftMessageReadRequest, receipt["read_id"])
    assert valid is not None and original is not None
    list_payload = field.startswith("list.")
    payload = deepcopy(observation["observation"] if list_payload else valid.payload)
    if field == "reason":
        payload.update(status="needs_human", content=None, content_sha256=None, reason=value)
    elif field == "custody.connected_at":
        payload["custody"]["connected_at"] = value
    elif field == "list.received_at":
        payload["items"][0]["received_at"] = value
    else:
        payload[field.removeprefix("list.")] = value
    before = rows(f, MicrosoftMessageSnapshot)
    with pytest.raises(DBAPIError) as error, f.s.begin_nested():
        request_body = messages._request_body("list", f.account) if list_payload else messages._request_body(
            "message", f.account, observation["read_id"], observation["source_sha256"], "invented-message"
        )
        forged_read = MicrosoftMessageReadRequest(
            id=str(uuid4()), box_id=f.box, owner_id=f.owner, ordinal=original.ordinal + 1,
            idempotency_key="forged-snapshot", request_hash=payload_hash(request_body),
            binding_digest=original.binding_digest, connected_at=original.connected_at,
            grant_sha256=original.grant_sha256, **request_body,
        )
        f.s.add(forged_read)
        f.s.flush()
        payload_sha256 = messages._payload_digest(payload)
        f.s.add(MicrosoftMessageSnapshot(
            box_id=f.box, owner_id=f.owner, read_id=forged_read.id, payload=payload,
            payload_sha256=payload_sha256, source_sha256=messages._commitment(forged_read, payload_sha256),
        ))
        f.s.flush()  # Bypass application typed parsing; only the real DB guard can refuse this.
    assert getattr(error.value.orig, "sqlstate", None) == "23514"
    assert rows(f, MicrosoftMessageSnapshot) == before and rows(f, MicrosoftMessageSourceReview) == 0


def test_database_refuses_microsoft_entry_without_explicit_review(case):
    f = case
    w = f.s.get(EncounterWorkspace, f.w["id"])
    with pytest.raises(DBAPIError), f.s.begin_nested():
        w.revision += 1
        f.s.add(
            WorkspaceEntry(
                workspace_id=w.id,
                box_id=f.box,
                actor_id=f.owner,
                revision=w.revision,
                kind="microsoft_message",
                content="Invented forged source",
                source_label="Microsoft",
                idempotency_key="forged",
                request_hash="a" * 64,
            )
        )
        f.s.flush()
        f.s.execute(text("SET CONSTRAINTS microsoft_message_entry_guard IMMEDIATE"))


@pytest.fixture
def http_case(signed_workspace, session, monkeypatch):
    f = signed_workspace
    monkeypatch.setattr(f.configuration, "workspace_microsoft_message_enabled", True)
    monkeypatch.setattr(f.configuration, "workspace_microsoft_connection_enabled", True)
    now = datetime.now(UTC)
    session.add(
        MicrosoftConnectionCredential(
            account_id=f.binding.id,
            binding_digest="a" * 64,
            status="ready",
            sealed=b"i" * 40,
            connected_at=now,
            expires_at=now + timedelta(hours=1),
        )
    )
    session.commit()
    port = InventedMicrosoft(session, f.binding.id, now)
    # Every actual HTTP request owns a fresh session, just as production does.
    original_binding = port.message_binding

    def binding(identity, *, require_full=False, session=None):
        assert session is not None
        port.session = session
        return original_binding(identity, require_full=require_full, session=session)

    port.message_binding = binding
    port.message_status = lambda identity, session=None: dict(
        contract_version=1,
        state="connected",
        full_mail_read=True,
        account={"label": "Invented account", "email": "owner@example.invalid"},
    )
    monkeypatch.setattr(api_module.app.state, "microsoft_connection", port, raising=False)
    monkeypatch.setitem(
        api_module.app.dependency_overrides, api_module.get_session, request_sessions(session)
    )
    monkeypatch.setattr(f.client, "request", isolate_http_request(f.client, session))
    f.port = port
    f.s = session
    f.headers = {"Authorization": "Bearer " + f.token(), "X-Cosmas-Microsoft-Messages": "1"}
    with messages.install_binding_reader(
        lambda s, a, full: binding(messages._scoped_identity(a), require_full=full, session=s)
    ):
        yield f


def post(f, body, path="/connections/microsoft/messages", **kwargs):
    return f.client.post(path, headers=f.headers, json=body, **kwargs)


def test_signed_http_list_read_review_replay_and_reopen_uses_actual_routes(http_case):
    f = http_case
    first = post(f, {"action": "list", "idempotency_key": "http-list"})
    assert first.status_code == 200, first.text
    observation = first.json()
    command = {
        "action": "read",
        "idempotency_key": "http-read",
        "observation_id": observation["read_id"],
        "observation_sha256": observation["source_sha256"],
        "message_id": "invented-message",
    }
    receipt = post(f, command)
    assert receipt.status_code == 200, receipt.text
    assert post(f, command).json() == receipt.json()
    body = {
        "expected_revision": 1,
        "idempotency_key": "http-review",
        "read_id": receipt.json()["read_id"],
        "source_sha256": receipt.json()["source_sha256"],
        "reviewed_patient": True,
        "reviewed_exact_message": True,
        "reviewed_untrusted_source": True,
    }
    path = f"/workspaces/{f.workspace['id']}/microsoft-messages/review"
    saved = post(f, body, path)
    assert saved.status_code == 200, saved.text
    again = post(f, body, path)
    assert again.status_code == 200, again.text
    assert again.json()["entry_id"] == saved.json()["entry_id"]
    resolved = post(f, {"action": "resolve", "kind": "message", "idempotency_key": "http-read"})
    assert resolved.status_code == 200 and resolved.json() == receipt.json()
    assert f.port.calls == ["list", "read"]
    for response in (first, receipt, saved, again, resolved):
        assert response.headers["cache-control"] == "no-store"


def test_browser_preflight_admits_only_the_registered_outlook_contract_header(http_case):
    f = http_case
    before = len(f.port.calls)
    response = f.client.options("/connections/microsoft/messages", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type,x-cosmas-microsoft-messages"})
    assert response.status_code == 200
    assert "x-cosmas-microsoft-messages" in response.headers["access-control-allow-headers"].lower()
    assert len(f.port.calls) == before


@pytest.mark.parametrize("completed", [False, True])
def test_resolve_lost_grant_keeps_exact_owned_intent_without_disclosing_any_message(case, completed):
    f = case
    observation = observed(f)
    if completed:
        receipt = read(f, observation)
        key, kind = receipt["read_key"], "message"
    else:
        f.port.fail = True
        with pytest.raises(ws.WorkspaceError):
            read(f, observation, key="lost-outlook-grant")
        key, kind = "lost-outlook-grant", "message"
    credential = f.s.get(MicrosoftConnectionCredential, f.account)
    assert credential is not None
    credential.status, credential.sealed = "failed", None
    f.s.commit()
    before = list(f.port.calls)
    result = messages.resolve_read(f.s, f.box, f.owner, f.account, key=key, kind=kind, port=f.port)
    assert set(result) == {"status", "kind", "read_key", "read_id"}
    assert result["status"] == "unavailable" and result["read_key"] == key and result["read_id"]
    assert f.port.calls == before and "sender@example.invalid" not in str(result)


@pytest.mark.parametrize(
    "body",
    [
        {"action": "list", "idempotency_key": "bad", "account_id": str(uuid4())},
        {
            "action": "read",
            "idempotency_key": "bad",
            "observation_id": str(uuid4()),
            "observation_sha256": "a" * 64,
            "message_id": "invented",
            "body": "forged",
        },
        {
            "action": "read",
            "idempotency_key": "bad",
            "observation_id": str(uuid4()),
            "observation_sha256": "a" * 64,
            "message_id": "invented",
            "url": "https://example.invalid",
        },
        {"action": "list", "idempotency_key": "bad", "actor_id": str(uuid4())},
    ],
)
def test_signed_http_closed_schema_denies_browser_supplied_custody_or_content(http_case, body):
    response = post(http_case, body)
    assert response.status_code == 422 and http_case.port.calls == []
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("fault", ["missing_header", "query", "duplicate_json"])
def test_signed_http_strict_request_fences_before_provider_io(http_case, fault):
    f = http_case
    if fault == "missing_header":
        response = f.client.post(
            "/connections/microsoft/messages",
            headers={"Authorization": f.headers["Authorization"]},
            json={"action": "list", "idempotency_key": "strict"},
        )
    elif fault == "query":
        response = post(
            f,
            {"action": "list", "idempotency_key": "strict"},
            "/connections/microsoft/messages?account=forged",
        )
    else:
        response = f.client.post(
            "/connections/microsoft/messages",
            headers={**f.headers, "Content-Type": "application/json"},
            content='{"action":"list","action":"read","idempotency_key":"strict"}',
        )
    assert response.status_code == 422 and f.port.calls == []


def test_signed_http_identity_revoked_after_read_hides_source_and_refuses_review(http_case):
    f = http_case
    observation = post(f, {"action": "list", "idempotency_key": "revoke-list"}).json()
    receipt = post(
        f,
        {
            "action": "read",
            "idempotency_key": "revoke-read",
            "observation_id": observation["read_id"],
            "observation_sha256": observation["source_sha256"],
            "message_id": "invented-message",
        },
    )
    assert receipt.status_code == 200, receipt.text
    f.binding.active = False
    f.s.commit()
    response = post(f, {"action": "inspect", "read_id": receipt.json()["read_id"]})
    assert response.status_code == 403 and "content" not in response.text
