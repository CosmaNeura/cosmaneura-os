"""Reviewed Outlook source through real Chief admission, tool read, and private output custody."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session
from tests.helpers.task_brief import REQUIREMENTS
from tests.integration import test_product_agent_tool_workflow as product
from tests.integration.test_microsoft_message import InventedMicrosoft

from cosmas_os.adapters.gpt41 import ENDPOINT, _context
from cosmas_os.application import conversation, handoffs
from cosmas_os.application import microsoft_message as messages
from cosmas_os.application import model_work as work
from cosmas_os.application import note_review as notes
from cosmas_os.application import provider_team as team
from cosmas_os.application import workspace as ws
from cosmas_os.config import Settings
from cosmas_os.microsoft_connection_models import MicrosoftConnectionCredential
from cosmas_os.models import (
    AuditEvent,
    ExternalIdentity,
    Principal,
    WorkspaceEntry,
    WorkspaceReply,
)
from cosmas_os.ports.microsoft_message import MicrosoftMessageBinding


class CommittedInventedMicrosoft(InventedMicrosoft):
    """A fake provider port whose DB-only binding works in real worker sessions."""

    def message_binding(self, identity, *, require_full=False, session=None):
        assert session is not None and identity.external_identity_id == self.account
        return MicrosoftMessageBinding(account_id=self.account, binding_digest="a" * 64,
            connected_at=self.connected, grant_sha256=self.grant)


@pytest.fixture
def microsoft_case(engine, monkeypatch):
    # Every product reader opens its own Session; use committed rows, not a fixture savepoint.
    configuration = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue] -- BaseSettings runtime-only option.
        workspace_enabled=True, workspace_authenticated_enabled=True,
        database_url="postgresql+psycopg://w1a_synth@127.0.0.1:55439/w1a_w1b_test",
        auth_mode="clerk_jwt", synth_seed=False,
        clerk_issuer="https://clerk.example.invalid",
        clerk_jwks_url="https://clerk.example.invalid/.well-known/jwks.json",
        clerk_audience="cosmas-workspace-local", clerk_organization_id="org_invented",
        clerk_authorized_parties="http://localhost:5173", cors_allowed_origins="http://localhost:5173",
        workspace_agent_tools_enabled=True, workspace_microsoft_connection_enabled=True,
        workspace_microsoft_message_enabled=True, workspace_llm_backend="azure_gpt41",
        workspace_llm_api_key=SecretStr("invented-product-http-key"),
    )
    # Provision needs only local product state. Bind the full authenticated profile before work.
    for module in (team, conversation, handoffs):
        monkeypatch.setattr(module, "runtime_settings", configuration)
    with Session(engine) as s:
        from cosmas_os.application import services as svc

        seeded = svc.provision_box(svc.Container(s), "Invented Outlook model clinic")
    configuration.beta_box_id = seeded["box_id"]
    assert configuration.workspace_available and configuration.workspace_microsoft_message_available
    # Reuse the committed product Scribe intake and team fixture, within this fresh Box.
    with Session(engine) as s:
        from tests.integration.test_note_review import prepare

        box, owner, initial, patient = prepare(s, seeded)
        team.save(s, box, owner, expected=0, key="invented-microsoft-team", configuration=team.default_configuration())
        state = ws.append(s, box, owner, initial["id"], expected=initial["revision"],
            key="invented-microsoft-transcript", kind="evidence", source_label="Invented Scribe transcript",
            content=product.TRANSCRIPT)["workspace"]
        state = notes.save(s, box, owner, state["id"], expected=state["revision"],
            key="invented-existing-note", base_note_id=None, source_reply_id=None,
            content="Invented clinical note: record review is pending; no clinical action approved.")["workspace"]
        note = state["note"]["latest"]
        state = notes.review(s, box, owner, state["id"], note["id"], expected=state["revision"],
            key="invented-existing-note-review", content_hash=note["content_hash"],
            source_hash=note["source_fingerprint"])["workspace"]
        note_before = state["note"]["latest"]
        now = datetime.now(UTC)
        account = ExternalIdentity(box_id=box, principal_id=owner,
            issuer="https://clerk-" + str(uuid4()) + ".example.invalid", subject="invented-owner",
            organization_id="org_invented", reviewed_by="Invented owner", evidence_ref="invented:microsoft-model")
        s.add(account)
        s.flush()
        s.add(MicrosoftConnectionCredential(account_id=account.id, binding_digest="a" * 64,
            status="ready", sealed=b"i" * 40, connected_at=now, expires_at=now + timedelta(hours=1)))
        s.commit()
        port = CommittedInventedMicrosoft(s, account.id, now)
        f = SimpleNamespace(engine=engine, box=box, owner=owner, wid=state["id"], patient=patient,
            account=account.id, port=port, note_before=note_before, selected=None, replacement=None)
        with messages.install_binding_reader(lambda current, identity, full: port.message_binding(
            messages._scoped_identity(identity), require_full=full, session=current)):
            f.selected = select_current(f, key="initial")
            yield f


def select_current(f, *, key):
    with Session(f.engine) as s:
        f.port.session = s
        observation = messages.list_observed(s, f.box, f.owner, f.account, key="list-" + key, port=f.port)
        receipt = messages.read_selected(s, f.box, f.owner, f.account, key="read-" + key,
            observation_id=observation["read_id"], observation_sha256=observation["source_sha256"],
            message_id="invented-message", port=f.port)
        current = ws.read(s, f.box, f.owner, f.wid)
        return messages.select_review(s, f.box, f.owner, f.wid, expected=current["revision"],
            key="review-" + key, read_id=receipt["read_id"], source_sha256=receipt["source_sha256"],
            patient_link_id=f.patient, reviewed_patient=True, reviewed_exact_message=True,
            reviewed_untrusted_source=True, port=f.port, external_identity_id=f.account)


def change_source(f, fault):
    if fault == "superseded":
        f.port.text = "Subject: Invented replacement\nFrom: sender@example.invalid\n\nInvented revised administrative request."
        f.replacement = select_current(f, key="replacement")
    elif fault == "semantic_grant":
        f.port.grant = "d" * 64
    else:
        with Session(f.engine) as s:
            credential = s.get(MicrosoftConnectionCredential, f.account)
            assert credential is not None
            credential.status = "disconnected"
            s.commit()


def reserve(f, key):
    return product.reserve(f.engine, (f.box, f.owner, f.wid),
        "Use Scribe and the reviewed Microsoft message to prepare an administrative draft for my review.", key)


def model_http(f, claimed, *, offer=False, cite_microsoft=True, change_at_round=None, fault=None):
    """Only provider HTTP is fake: actual admission, parser, tool reader and settle run."""
    calls, receipts = [], []
    context = _context(claimed.envelope["context"])
    source = next(p for p in context.sources if p.entry_id == f.selected["entry_id"])
    handle = next(h for h in claimed.envelope["tool_selection"]["sources"] if h["entry_id"] == source.entry_id)
    assert source.kind == handle["kind"] == "evidence" and source.content == f.port.text
    assert handle["sha256"] == hashlib.sha256(source.content.encode()).hexdigest()
    def respond(request):
        assert str(request.url) == ENDPOINT
        body = json.loads(request.content)
        calls.append(body)
        assert body["store"] is False and body["model"] == "gpt-4.1-dzus"
        with Session(f.engine) as check:
            assert check.scalar(select(Principal).where(Principal.id == f.owner).with_for_update(nowait=True))
        if change_at_round == len(calls):
            change_source(f, fault)
        if len(calls) == 1:
            supplied = json.loads(body["messages"][1]["content"])["sources"]
            assert any(p["source_id"] == source.entry_id and p["text"] == source.content for p in supplied)
            return httpx.Response(200, json=product.response(calls=[product.read_call(handle)]))
        assert len(calls) == 2
        result = json.loads(body["messages"][-1]["content"])
        assert result["data"]["content"] == source.content
        assert result["receipt"]["initiated_by_human_id"] == f.owner
        assert result["receipt"]["actor_agent_id"] != f.owner
        receipts.append(result)
        output = {"answer": "Invented administrative draft derived from the reviewed message; clinician review remains required.",
            "source_ids": [p.entry_id for p in context.sources if cite_microsoft or p.entry_id != source.entry_id]}
        if claimed.envelope["baseline"]["flags"]["work_status"]:
            output["intent"] = "conversation"
        if claimed.envelope["baseline"]["flags"]["can_handoff"]:
            output["handoffs"] = [{"role": "follow_up", "intended_role": "follow_up",
                "brief": "Prepare an invented administrative draft; preserve unknown clinical facts.",
                "requirements": REQUIREMENTS}] if offer else []
        return httpx.Response(200, json=product.response(output))
    return httpx.MockTransport(respond), calls, receipts


def test_reviewed_microsoft_source_executes_real_product_tool_and_preserves_clinical_note(microsoft_case):
    f = microsoft_case
    claimed = reserve(f, "invented-microsoft-context")
    transport, calls, receipts = model_http(f, claimed)
    state, result_id, result = product.dispatch_and_settle(f.engine, claimed, transport)
    assert state == "completed" and result_id and len(calls) == 2 and len(receipts) == 1
    assert result.input_tokens == 200 and result.output_tokens == 40
    with Session(f.engine) as s:
        current = ws.read(s, f.box, f.owner, f.wid)
        note = current["note"]["latest"]
        for name in ("id", "content", "content_hash", "source_fingerprint", "review"):
            assert note[name] == f.note_before[name]
        assert note["sources_changed"] is False
        assert notes.source_fingerprint(s, f.wid, current["revision"]) == f.note_before["source_fingerprint"]
        entry = s.get(WorkspaceEntry, f.selected["entry_id"])
        assert entry is not None and entry.kind == "microsoft_message"
        reply = s.get(WorkspaceReply, result_id)
        assert reply is not None and next(c for c in reply.citations if c["entry_id"] == entry.id)["kind"] == "evidence"
        audits = list(s.scalars(select(AuditEvent).where(AuditEvent.aggregate_id == claimed.admission_id,
            AuditEvent.event_type == "workspace.agent_tool_read")))
        assert len(audits) == 1 and f.port.text not in json.dumps(audits[0].detail)
        assert "grant_sha256" not in json.dumps(audits[0].detail)


@pytest.mark.parametrize("change", ["disconnect", "reconnect"])
def test_later_disconnect_or_reconnect_withholds_previously_derived_private_chief_output(microsoft_case, change):
    f = microsoft_case
    claimed = reserve(f, "invented-outlook-derived-output")
    transport, calls, _ = model_http(f, claimed)
    state, result_id, _ = product.dispatch_and_settle(f.engine, claimed, transport)
    assert state == "completed" and result_id is not None and len(calls) == 2
    with Session(f.engine) as s:
        before = ws.read(s, f.box, f.owner, f.wid)
        public = next(e for e in before["entries"] if e["id"] == result_id)
        assert public["reply"] is not None and public["reply"]["content"]
        credential = s.get(MicrosoftConnectionCredential, f.account)
        assert credential is not None
        if change == "disconnect":
            credential.status, credential.sealed = "disconnected", None
        else:
            credential.connected_at += timedelta(seconds=1)
        s.commit()
    with Session(f.engine) as s:
        current = work.project_workspace(s, ws.read(s, f.box, f.owner, f.wid))
        selected = next(e for e in current["entries"] if e["id"] == f.selected["entry_id"])
        public = next(e for e in current["entries"] if e["id"] == result_id)
        assert selected["microsoft_source_state"] == "unavailable" and selected["content"] == ""
        assert public["microsoft_source_state"] == "unavailable" and public["content"] == "" and public["reply"] is None
        assert f.port.text not in json.dumps(current)
        stored = s.get(WorkspaceReply, result_id)
        assert stored is not None and stored.content  # Durable history is retained, not newly authorized.
    assert len(calls) == 2 and f.port.calls == ["list", "read"]
