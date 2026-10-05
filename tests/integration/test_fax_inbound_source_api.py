"""Signed human passage admission from a real acquired PDF, with no live I/O.

Registered managed routes/identity/ledger/PDF parser are real. Vendor transport
and the optional model/Gmail upstream fixtures are explicitly invented.
"""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from tests.helpers.task_brief import REQUIREMENTS
from tests.integration import test_fax_inbound_api as signed_fixture
from tests.integration.test_google_message import InventedGoogle, select_message

from cosmas_os.adapters.gpt41 import _context
from cosmas_os.application import agent_tools
from cosmas_os.application import fax_inbound_source as source
from cosmas_os.application import google_message as gmail
from cosmas_os.application import model_work as work
from cosmas_os.application import provider_team as team
from cosmas_os.config import settings
from cosmas_os.fax_inbound_models import FaxInboundOutcome
from cosmas_os.fax_source_models import FaxInboundSourceReview
from cosmas_os.google_connection_models import GoogleConnectionCredential
from cosmas_os.models import (
    EncounterWorkspace,
    ExternalIdentity,
    ModelWorkAdmission,
)
from cosmas_os.ports.bot_capabilities import BotReply, DraftBrief, ModelCallFailure

managed_case = signed_fixture.managed_case
inbox = signed_fixture.inbox
PASSAGE = "Human-reviewed invented café passage: cardiac history is incomplete. DOB and trial eligibility remain unknown."


@pytest.fixture
def source_http(inbox, monkeypatch):
    f = inbox
    monkeypatch.setattr(settings, "fax_inbound_source_enabled", True)
    monkeypatch.setattr(settings, "workspace_draft_recovery_required", True)
    assert settings.fax_inbound_source_available
    f.wid = f.case.vendor["wid"]
    f.box = f.case.vendor["box"]
    f.owner = f.case.vendor["actor"]
    f.path = "/workspaces/" + f.wid + "/fax-inbound-source"
    try:
        yield f
    finally:
        # Test helpers commit; keep a failed assertion from contaminating an
        # unrelated product worker by abandoning only this fixture's own rows.
        with Session(f.case.engine) as session:
            rows = list(session.scalars(select(ModelWorkAdmission).where(
                ModelWorkAdmission.workspace_id == f.wid, ModelWorkAdmission.box_id == f.box,
                ModelWorkAdmission.owner_id == f.owner, ModelWorkAdmission.state.in_(("reserved", "running")))))
            for row in rows:
                if row.state == "reserved":
                    claimed = work.claim(session, f.box, f.owner, row.id)
                else:
                    assert row.dispatch_id is not None
                    claimed = work.ModelClaim(row.id, f.box, f.owner, f.wid, row.dispatch_id,
                        row.envelope_sha256, row.prepared_envelope)
                if claimed is not None:
                    work.settle(session, claimed, ModelCallFailure(dispatch="not_dispatched"))
            assert not list(session.scalars(select(ModelWorkAdmission.id).where(
                ModelWorkAdmission.workspace_id == f.wid, ModelWorkAdmission.state.in_(("reserved", "running")))))


def read(f, client):
    value = signed_fixture.reply(client.get("/workspaces/" + f.wid,
        headers={**f.headers(), "X-Cosmas-Model-Contract": "1"}))
    # Negotiated model projection includes the fresh observation clock. It is
    # not durable workspace state; all identity/revision/source/note fields
    # remain part of the exact before/after comparisons below.
    value.pop("model_observed_at", None)
    return value


def acquire(f, client):
    g, observation = signed_fixture.begin(f, client, "documo")
    f.grant_id = g["grant_id"]
    command = signed_fixture.approved(f, client, g, observation)
    receipt = signed_fixture.reply(client.post("/fax-inbound/acquire", headers=f.headers(), json=command))
    assert receipt["state"] == "acquired" and receipt["source_withheld"] is False
    assert len(f.wire) == 2
    return receipt


def review_command(f, client, acquired, **changes):
    return {"expected_revision": read(f, client)["revision"], "idempotency_key": signed_fixture.key(),
        "operation_id": acquired["operation_id"], "document_sha256": acquired["document_sha256"],
        "passage": PASSAGE, "page_numbers": [1], "reviewed_patient": True,
        "reviewed_exact_document": True, "reviewed_exact_text": True, "reviewed_untrusted_source": True,
        **changes}


def resolve(f, client, command):
    return signed_fixture.reply(client.post(f.path + "/resolve", headers=f.headers(),
        json={"idempotency_key": command["idempotency_key"]}))


def count_reviews(f):
    with Session(f.case.engine) as session:
        return session.scalar(select(func.count()).select_from(FaxInboundSourceReview).where(
            FaxInboundSourceReview.workspace_id == f.wid))


def failed(response, status, code=None):
    value = signed_fixture.reply(response, status)
    assert set(value) == {"error"} and type(value["error"]) is str
    if code is not None:
        assert value["error"] == code
    return value


def validate_commitments(f, command, saved):
    assert saved["state"] == "saved" and saved["source_withheld"] is False
    assert set(saved) == {"contract_version", "scope", "idempotency_key", "request_sha256", "review_id",
        "entry_id", "entry_revision", "operation_id", "source_sha256", "content_sha256", "document_sha256",
        "page_numbers", "coverage", "extraction", "source_withheld", "state"}
    assert saved["scope"] == {"box_id": f.box, "owner_id": f.owner, "workspace_id": f.wid}
    assert saved["request_sha256"] == source.request_hash(f.box, f.owner, f.wid, command)
    assert saved["content_sha256"] == hashlib.sha256(command["passage"].encode()).hexdigest()
    assert saved["document_sha256"] == hashlib.sha256(f.pdf).hexdigest()
    assert saved["page_numbers"] == [1] and saved["entry_revision"] == command["expected_revision"] + 1
    assert (saved["coverage"], saved["extraction"]) == ("human_selected_passage", "human_entered_no_ocr")
    assert "passage" not in saved and "document" not in saved
    with Session(f.case.engine) as session:
        review = session.get(FaxInboundSourceReview, saved["review_id"])
        assert review is not None
        outcome = session.get(FaxInboundOutcome, review.operation_id)
        assert outcome is not None
        assert review.source_sha256 == source.source_hash(review.operation_id, review.grant_id,
            review.document_sha256, source.outcome_hash(outcome), review.installation_sha256,
            review.content_sha256, command["page_numbers"])
        workspace = session.get(EncounterWorkspace, f.wid)
        assert workspace is not None
        entry = source.validate_selected_source(session, workspace, saved["entry_id"])
        assert (entry.kind, entry.source_label, entry.content) == (source.SOURCE_KIND, source.SOURCE_LABEL, command["passage"])
        assert review.patient_link_id == workspace.patient_link_id and workspace.patient_link_id is not None


def test_signed_review_passage_exact_receipt_note_preserved_and_restarted_db_only_resolution(source_http):
    f = source_http
    with f.case.start(f.profile) as client:
        before = read(f, client)
        acquired = acquire(f, client)
        command = review_command(f, client, acquired)
        assert count_reviews(f) == 0
        saved = signed_fixture.reply(client.post(f.path, headers=f.headers(), json=command))
        validate_commitments(f, command, saved)
        current = read(f, client)
        assert current["note"] == before["note"] and current["note"] is not None
        assert [e for e in current["entries"] if e["id"] in {old["id"] for old in before["entries"]}] == before["entries"]
        entry = next(e for e in current["entries"] if e["id"] == saved["entry_id"])
        assert entry["kind"] == "fax_inbound_source" and entry["practice_fax_source_state"] == "current" and entry["content"] == PASSAGE
        # Lost response after a committed save: exact same request retrieves its
        # immutable receipt; it is never inferred from status or a similar text.
        assert signed_fixture.reply(client.post(f.path, headers=f.headers(), json=command)) == saved
        assert resolve(f, client, command) == saved and count_reviews(f) == 1
    with f.case.start(f.profile) as client:
        assert resolve(f, client, command) == saved
        assert read(f, client)["note"] == before["note"]
    assert len(f.wire) == 2


def test_signed_duplicate_key_changed_text_and_newer_review_preserve_history(source_http):
    f = source_http
    with f.case.start(f.profile) as client:
        acquired = acquire(f, client)
        command = review_command(f, client, acquired)
        first = signed_fixture.reply(client.post(f.path, headers=f.headers(), json=command))
        failed(client.post(f.path, headers=f.headers(), json={**command, "passage": "Altered private passage"}), 409)
        assert count_reviews(f) == 1
        revised = review_command(f, client, acquired, passage="Revised human café passage; unknown DOB is retained.")
        second = signed_fixture.reply(client.post(f.path, headers=f.headers(), json=revised))
        assert second["review_id"] != first["review_id"] and count_reviews(f) == 2
        old = resolve(f, client, command)
        assert old["source_withheld"] is True and old["request_sha256"] == first["request_sha256"]
        current = read(f, client)
        assert next(e for e in current["entries"] if e["id"] == first["entry_id"])["content"] == ""
        assert next(e for e in current["entries"] if e["id"] == second["entry_id"])["content"] == revised["passage"]
    assert len(f.wire) == 2


@pytest.mark.parametrize("change", [
    {"reviewed_patient": False}, {"reviewed_exact_document": False}, {"reviewed_exact_text": False},
    {"reviewed_untrusted_source": False}, {"reviewed_patient": "true"}, {"passage": " "},
    {"passage": "a" * 12001}, {"passage": "unsafe\x00text"}, {"page_numbers": []},
    {"page_numbers": [1, 1]}, {"page_numbers": [2, 1]}, {"page_numbers": [True]},
    {"patient_link_id": str(uuid4())}, {"remote_patient_id": "invented-unreviewed"},
])
def test_signed_four_acks_pages_text_and_closed_patient_scope_required_before_save(source_http, change):
    f = source_http
    with f.case.start(f.profile) as client:
        acquired = acquire(f, client)
        before = read(f, client)
        command = review_command(f, client, acquired, **change)
        failed(client.post(f.path, headers=f.headers(), json=command), 400, "fax_inbound_request_invalid")
        assert count_reviews(f) == 0 and read(f, client) == before
    assert len(f.wire) == 2


@pytest.mark.parametrize("change,code", [({"page_numbers": [2]}, "fax_inbound_source_document_changed"),
    ({"document_sha256": "f" * 64}, "fax_inbound_source_document_changed"),
    ({"operation_id": str(uuid4())}, "fax_inbound_unavailable")])
def test_signed_exact_acquired_document_binding_and_page_bounds(source_http, change, code):
    f = source_http
    with f.case.start(f.profile) as client:
        acquired = acquire(f, client)
        before = read(f, client)
        command = review_command(f, client, acquired, **change)
        failed(client.post(f.path, headers=f.headers(), json=command), 404 if "operation_id" in change else 409, code)
        assert count_reviews(f) == 0 and read(f, client) == before


def test_signed_source_authority_headers_foreign_actor_agent_disabled_and_large_body(source_http, monkeypatch):
    f = source_http
    with f.case.start(f.profile) as client:
        acquired = acquire(f, client)
        command = review_command(f, client, acquired)
        for subject in ("peer",):
            response = client.post(f.path, headers=f.headers(subject), json=command)
            assert response.status_code in (403, 404)
        headers = dict(f.headers())
        headers.pop("X-Cosmas-Fax-Inbound")
        failed(client.post(f.path, headers=headers, json=command), 426)
        monkeypatch.setattr(settings, "fax_inbound_source_enabled", False)
        failed(client.post(f.path, headers=f.headers(), json=command), 403, "fax_inbound_source_disabled")
        assert count_reviews(f) == 0


def test_signed_resolve_before_save_and_revoked_lost_reply_are_db_only(source_http):
    f = source_http
    with f.case.start(f.profile) as client:
        acquired = acquire(f, client)
        command = review_command(f, client, acquired)
        assert resolve(f, client, command) == {"contract_version": 1,
            "scope": {"box_id": f.box, "owner_id": f.owner, "workspace_id": f.wid},
            "idempotency_key": command["idempotency_key"], "state": "not_found"}
        original = signed_fixture.reply(client.post(f.path, headers=f.headers(), json=command))
        signed_fixture.reply(client.post("/fax-inbound/revoke", headers=f.headers(),
            json={"idempotency_key": signed_fixture.key(), "grant_id": f.grant_id}))
        recovered = resolve(f, client, command)
        assert recovered == {**original, "source_withheld": True}
        assert signed_fixture.reply(client.post(f.path, headers=f.headers(), json=command)) == recovered
        unavailable = read(f, client)
        entry = next(e for e in unavailable["entries"] if e["id"] == original["entry_id"])
        assert entry["practice_fax_source_state"] == "unavailable" and entry["content"] == ""
        assert entry["source_label"] == "Unavailable received practice-fax source"
        failed(client.post(f.path, headers=f.headers(), json={**command,
            "expected_revision": unavailable["revision"], "idempotency_key": signed_fixture.key()}), 403)
        assert count_reviews(f) == 1
    with f.case.start(f.profile) as client:
        assert resolve(f, client, command) == recovered
        assert PASSAGE not in client.get("/workspaces/" + f.wid, headers=f.headers()).text
    assert len(f.wire) == 2


def test_signed_json_framing_duplicate_keys_and_stale_revision_fail_without_source_entry(source_http):
    f = source_http
    with f.case.start(f.profile) as client:
        acquired = acquire(f, client)
        before = read(f, client)
        command = review_command(f, client, acquired)
        raw = json.dumps(command)
        duplicate = raw[:-1] + ',"reviewed_exact_text":true}'
        failed(client.post(f.path, headers={**f.headers(), "Content-Type": "application/json"},
            content=duplicate), 400, "fax_inbound_request_invalid")
        failed(client.post(f.path, headers={**f.headers(), "Content-Type": "application/json; charset=utf-8"},
            content=raw), 400, "fax_inbound_request_invalid")
        failed(client.post(f.path, headers={**f.headers(), "Content-Type": "application/json", "Content-Encoding": "gzip"},
            content=raw), 400, "fax_inbound_request_invalid")
        failed(client.post(f.path + "?patient=unreviewed", headers=f.headers(), json=command), 426)
        failed(client.post(f.path, headers=f.headers(), json={**command, "expected_revision": 400}), 409)
        assert count_reviews(f) == 0 and read(f, client) == before
    assert len(f.wire) == 2


def test_signed_gmail_source_and_existing_reviewed_note_coexist_with_fax(source_http, monkeypatch):
    f = source_http
    with f.case.start(f.profile) as client, Session(f.case.engine) as session:
        # The actual managed lifespan is initialized before installing this
        # explicit invented Gmail binding; no OAuth client or provider is used.
        monkeypatch.setattr(settings, "workspace_google_connection_enabled", True)
        monkeypatch.setattr(settings, "workspace_google_message_enabled", True)
        before = read(f, client)
        acquired = acquire(f, client)
        account = ExternalIdentity(box_id=f.box, principal_id=f.owner,
            issuer="https://invented-google-" + uuid4().hex + ".invalid", subject="invented-mail-owner",
            reviewed_by="Invented human", evidence_ref="synthetic signed fax coexistence", organization_id="org_invented")
        session.add(account)
        session.flush()
        connected = datetime.now(UTC)
        session.add(GoogleConnectionCredential(account_id=account.id, binding_digest="a" * 64,
            status="ready", sealed=b"i" * 40, connected_at=connected, expires_at=connected + timedelta(hours=1)))
        session.commit()
        port = InventedGoogle(session, account.id, connected)
        def current(s, identity, full):
            port.session = s
            return port.message_binding(gmail._scoped_identity(identity), require_full=full, session=s)
        encounter = session.get(EncounterWorkspace, f.wid)
        assert encounter is not None
        patient, account_id = encounter.patient_link_id, account.id
        session.rollback()
        g = SimpleNamespace(s=session, box=f.box, owner=f.owner, w=before,
            patient=patient, account=account_id, port=port)
        with gmail.install_binding_reader(current):
            selected = select_message(g)
            # select_message commits the reviewed source, then reads its
            # workspace in this caller session. Release that shared read lock
            # before the real HTTP route independently acquires a write lock.
            session.rollback()
            prior = read(f, client)
            email = next(e for e in prior["entries"] if e["id"] == selected["entry_id"])
            assert email["google_source_state"] == "current"
            command = review_command(f, client, acquired)
            saved = signed_fixture.reply(client.post(f.path, headers=f.headers(), json=command))
            after = read(f, client)
            assert after["note"] == before["note"]
            assert next(e for e in after["entries"] if e["id"] == email["id"]) == email
            assert next(e for e in after["entries"] if e["id"] == saved["entry_id"])["content"] == PASSAGE
            assert port.calls == ["list", "read"]
    assert len(f.wire) == 2


def test_actual_scoped_tool_and_derived_chief_handoff_are_withheld_after_signed_revoke(source_http, monkeypatch):
    f = source_http
    monkeypatch.setattr(settings, "workspace_agent_tools_enabled", True)
    monkeypatch.setattr(settings, "workspace_llm_backend", "azure_gpt41")
    monkeypatch.setattr(settings, "workspace_llm_api_key", SecretStr("invented-no-model-network"))
    with f.case.start(f.profile) as client:
        before = read(f, client)
        acquired = acquire(f, client)
        command = review_command(f, client, acquired)
        saved = signed_fixture.reply(client.post(f.path, headers=f.headers(), json=command))
        with Session(f.case.engine) as session:
            team_state = team.save(session, f.box, f.owner, expected=0, key=signed_fixture.key(),
                configuration=team.default_configuration())
            session.rollback()  # Release projection owner locks before another HTTP transaction.
            initial = read(f, client)
            admission, _ = work.reserve_conversation(session, f.box, f.owner, f.wid,
                expected=initial["revision"], team_revision=team_state["revision"], key=signed_fixture.key(), role="chief",
                content="Review the human-selected fax passage and prepare a private Follow-up draft, retaining unknown DOB.")
            assert admission is not None
            claimed = work.claim(session, f.box, f.owner, admission)
            assert claimed is not None
            context = _context(claimed.envelope["context"])
            selected = next(p for p in context.sources if p.entry_id == saved["entry_id"])
            handle = next(h for h in claimed.envelope["tool_selection"]["sources"] if h["entry_id"] == saved["entry_id"])
            tool = agent_tools.AgentToolExecutor(session, claimed).execute({"tool": "read_selected_source",
                **{name: handle[name] for name in ("entry_id", "revision", "sha256")}})
            assert tool["data"]["content"] == PASSAGE and tool["data"]["kind"] == "evidence"
            assert handle["sha256"] == hashlib.sha256(PASSAGE.encode()).hexdigest()
            assert tool["receipt"]["initiated_by_human_id"] == f.owner
            assert tool["receipt"]["actor_agent_id"] != f.owner
            work.settle(session, claimed, BotReply("Chief private summary: " + PASSAGE, (selected,), "azure_gpt41", 30, 9,
                (DraftBrief("follow_up", "Create a private follow-up draft; retain unknown DOB.", REQUIREMENTS),)))
            chief = session.get(ModelWorkAdmission, admission)
            assert chief is not None and chief.state == "completed"
            child = session.scalar(select(ModelWorkAdmission).where(ModelWorkAdmission.workspace_id == f.wid,
                ModelWorkAdmission.kind == "private_handoff"))
            assert child is not None
            child_claim = work.claim(session, f.box, f.owner, child.id)
            assert child_claim is not None
            work.settle(session, child_claim, BotReply("Follow-up private draft: " + PASSAGE, (), "azure_gpt41", 15, 6))
            completed_child = session.get(ModelWorkAdmission, child.id)
            assert completed_child is not None and completed_child.state == "completed"
        current = read(f, client)
        handoff = current["handoffs"][0]
        assert handoff["status"] == "completed" and handoff["result_sha256"]
        assert PASSAGE in str(current) and current["note"] == before["note"]
        signed_fixture.reply(client.post("/fax-inbound/revoke", headers=f.headers(),
            json={"idempotency_key": signed_fixture.key(), "grant_id": f.grant_id}))
        masked = read(f, client)
        assert PASSAGE not in str(masked) and masked["note"] == before["note"]
        assert next(e for e in masked["entries"] if e["id"] == saved["entry_id"])["practice_fax_source_state"] == "unavailable"
        derived = [e for e in masked["entries"] if e["kind"] in {"conversation", "handoff_result"}]
        assert len(derived) >= 2 and all(e["reply"] is None for e in derived)
        assert resolve(f, client, command)["source_withheld"] is True
    assert len(f.wire) == 2


def test_direct_forged_source_entry_and_review_commitments_are_rejected(source_http):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    from cosmas_os.models import WorkspaceEntry
    f = source_http
    with f.case.start(f.profile) as client:
        acquired = acquire(f, client)
        command = review_command(f, client, acquired)
        saved = signed_fixture.reply(client.post(f.path, headers=f.headers(), json=command))
    with Session(f.case.engine) as s:
        w = s.get(EncounterWorkspace, f.wid)
        for execute_sql in (False, True):
            with pytest.raises(DBAPIError) as failure, s.begin_nested():
                w.revision += 1
                values = dict(id=str(uuid4()), workspace_id=w.id, box_id=f.box, actor_id=f.owner,
                    revision=w.revision, kind=source.SOURCE_KIND, content="Forged reviewed content",
                    source_label=source.SOURCE_LABEL, idempotency_key=signed_fixture.key(), request_hash="a" * 64)
                if execute_sql:
                    s.execute(text("INSERT INTO public.workspace_entries "
                        "(id,workspace_id,box_id,actor_id,revision,kind,content,source_label,idempotency_key,request_hash) "
                        "VALUES(:id,:workspace_id,:box_id,:actor_id,:revision,:kind,:content,:source_label,:idempotency_key,:request_hash)"), values)
                else:
                    s.add(WorkspaceEntry(**values))
                s.flush()
                s.execute(text("SET CONSTRAINTS fax_inbound_source_entry_guard IMMEDIATE"))
            assert failure.value.orig.sqlstate == "23514"
            s.expire_all()
        for statement in (
            "UPDATE fax_inbound_source_reviews SET content_sha256=repeat('a',64)",
            "DELETE FROM fax_inbound_source_reviews", "UPDATE workspace_entries SET content='changed' WHERE kind='fax_inbound_source'",
        ):
            with pytest.raises(DBAPIError), s.begin_nested():
                s.execute(text(statement))
        review = s.get(FaxInboundSourceReview, saved["review_id"])
        assert review.content_sha256 == hashlib.sha256(PASSAGE.encode()).hexdigest()


def test_changed_account_key_and_identity_withhold_selected_passage_and_resolution(source_http, monkeypatch):
    from dataclasses import replace
    f = source_http
    with f.case.start(f.profile) as client:
        acquired = acquire(f, client)
        command = review_command(f, client, acquired)
        signed_fixture.reply(client.post(f.path, headers=f.headers(), json=command))
    changed = replace(f.profile, fax_inbound_installations=tuple(
        replace(i, label=i.label + " changed") if i.selection.vendor == "documo" else i for i in f.items))
    with f.case.start(changed) as client:
        assert resolve(f, client, command)["source_withheld"] is True
        assert PASSAGE not in str(read(f, client))
        assert len(f.wire) == 2
    with f.case.start(f.profile) as client:
        assert resolve(f, client, command)["source_withheld"] is False
        original_key = settings.fax_inbound_document_encryption_key
        monkeypatch.setattr(settings, "fax_inbound_document_encryption_key", None)
        assert resolve(f, client, command)["source_withheld"] is True
        assert PASSAGE not in str(read(f, client))
        monkeypatch.setattr(settings, "fax_inbound_document_encryption_key", original_key)
        assert resolve(f, client, command)["source_withheld"] is False
        with Session(f.case.engine) as s:
            account = s.get(ExternalIdentity, f.case.owner_binding)
            account.active = False
            s.commit()
        denied = client.post(f.path + "/resolve", headers=f.headers(), json={"idempotency_key": command["idempotency_key"]})
        assert denied.status_code == 403 and PASSAGE not in denied.text
        assert len(f.wire) == 2
