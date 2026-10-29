"""Athena medication custody through real Chief admission, exact source tools and settlement."""

import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session
from tests.integration import test_product_agent_tool_workflow as product
from tests.integration.test_athena_medication_ehr import InventedAthena, install_grant
from tests.integration.test_note_review import prepare

from cosmas_os.adapters.athena_medication_read import clinical_dumps, clinical_loads
from cosmas_os.adapters.athena_medication_read_runtime import SyntheticAthenaMedicationReads
from cosmas_os.adapters.ehr_read_runtime import EhrReadRuntimes
from cosmas_os.adapters.gpt41 import ENDPOINT, _context
from cosmas_os.application import athena_medication_ehr as clinical
from cosmas_os.application import conversation, handoffs
from cosmas_os.application import ehr_reads as ehr
from cosmas_os.application import model_work as work
from cosmas_os.application import note_review as notes
from cosmas_os.application import provider_team as team
from cosmas_os.application import services as svc
from cosmas_os.application import workspace as ws
from cosmas_os.config import Settings
from cosmas_os.ehr_read_models import EhrAthenaMedicationPatientGrant
from cosmas_os.models import (
    AuditEvent,
    ExternalIdentity,
    ModelWorkAdmission,
    Principal,
    WorkspaceReply,
)


class InventedClinicalProvider(InventedAthena):
    def __init__(self, session):
        super().__init__(session)
        section = clinical_loads(self.raw_section_json)
        # Retain the entire golden section and raw number tokens while forcing
        # real marked-excerpt delivery followed by the complete source tool.
        section["sectionnote"] += ("\nOriginal model-review qualifier: "
            + "Invented medication context remains unconfirmed. " * 36
            + "Final qualifier remains present.")
        self.raw_section_json = clinical_dumps(section)


@pytest.fixture
def athena_medication_model_case(engine, monkeypatch):
    configuration = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue] -- BaseSettings runtime option.
        workspace_enabled=True, workspace_authenticated_enabled=True,
        database_url="postgresql+psycopg://w1a_synth@127.0.0.1:55439/w1a_w1b_test",
        auth_mode="clerk_jwt", synth_seed=False,
        clerk_issuer="https://clerk.example.invalid",
        clerk_jwks_url="https://clerk.example.invalid/.well-known/jwks.json",
        clerk_audience="cosmas-workspace-local", clerk_organization_id="org_invented",
        clerk_authorized_parties="http://localhost:5173", cors_allowed_origins="http://localhost:5173",
        workspace_agent_tools_enabled=True, workspace_ehr_read_enabled=True,
        workspace_athena_medications_enabled=True,
        workspace_llm_backend="azure_gpt41", workspace_llm_api_key=SecretStr("invented-product-http-key"),
    )
    for module in (team, conversation, handoffs):
        monkeypatch.setattr(module, "runtime_settings", configuration)
    with Session(engine) as s:
        seeded = svc.provision_box(svc.Container(s), "Invented Athena medication review clinic")
    configuration.beta_box_id = seeded["box_id"]
    with Session(engine) as s:
        box, owner, initial, patient_link_id = prepare(s, seeded)
        team.save(s, box, owner, expected=0, key="invented-athena-medication-team", configuration=team.default_configuration())
        state = notes.save(s, box, owner, initial["id"], expected=initial["revision"],
            key="invented-note-before-athena-medication", base_note_id=None, source_reply_id=None,
            content="Invented reviewed note: reconcile chart facts with the clinician before any action.")["workspace"]
        note = state["note"]["latest"]
        state = notes.review(s, box, owner, state["id"], note["id"], expected=state["revision"],
            key="invented-note-review-before-athena-medication", content_hash=note["content_hash"],
            source_hash=note["source_fingerprint"])["workspace"]
        account = ExternalIdentity(box_id=box, principal_id=owner,
            issuer="https://clerk-" + str(uuid4()) + ".example.invalid", subject="invented-owner",
            organization_id="org_invented", reviewed_by="Invented owner", evidence_ref="invented:athena-medication")
        s.add(account)
        s.flush()
        scope, binding, _stored_grant, grant = install_grant(
            s, box, owner, account.id, state["id"], patient_link_id)
        provider = InventedClinicalProvider(s)
        port = SyntheticAthenaMedicationReads((scope,), (grant,), httpx.MockTransport(provider), enabled=lambda: True)
        runtimes = EhrReadRuntimes(athena_medications=port)
        f = SimpleNamespace(engine=engine, box=box, owner=owner, wid=state["id"], account=account.id,
            patient=patient_link_id, grant_id=str(grant.grant_id), binding_id=binding.id, scope=scope,
            port=port, runtimes=runtimes, provider=provider, configuration=configuration, note_before=state["note"]["latest"])
        with ehr.install_runtime_reader(lambda: runtimes):
            root = clinical.patients(s, box, owner, account.id, key="invented-athena-medication-patients",
                connection_id=str(scope.connection_id), binding_sha256=scope.commitment(), workspace_id=f.wid, port=port)
            assert not provider.calls
            root_public = root["observation"]
            assert isinstance(root_public, dict)
            item = root_public["items"][0]
            assert isinstance(item, dict)
            assert isinstance(root["observation_id"], str) and isinstance(root["source_sha256"], str)
            receipt = clinical.medications(s, box, owner, account.id, key="invented-athena-medication-records",
                connection_id=str(scope.connection_id), binding_sha256=scope.commitment(), workspace_id=f.wid,
                observation_id=root["observation_id"], observation_sha256=root["source_sha256"],
                item_handle=item["handle"], item_sha256=item["sha256"], port=port)
            medication_public = receipt["observation"]
            assert isinstance(medication_public, dict)
            item = medication_public["item"]
            assert isinstance(item, dict)
            assert isinstance(receipt["observation_id"], str) and isinstance(receipt["source_sha256"], str)
            f.selected = ehr.select_review(s, box, owner, f.wid, expected=state["revision"],
                key="invented-athena-medication-review", observation_id=receipt["observation_id"],
                observation_sha256=receipt["source_sha256"], item_handle=item["handle"], item_sha256=item["sha256"],
                reviewed_visit=None, reviewed_patient_identity=True, reviewed_exact_snapshot=True,
                reviewed_untrusted_source=True, port=port, external_identity_id=account.id, provider="athena", protocol="core", clinical_scope="medications")
            selected_workspace = f.selected["workspace"]
            assert isinstance(selected_workspace, dict)
            f.section_json = item["section_json"]
            assert f.section_json == clinical_dumps(clinical_loads(provider.raw_section_json))
            f.content = next(e["content"] for e in selected_workspace["entries"] if e["id"] == f.selected["entry_id"])
            assert len(provider.calls) == 2 and 2000 < len(f.content) <= 5000
            s.commit()
            yield f


def revoke(f):
    withdrawal = getattr(f, "withdrawal", "grant")
    if withdrawal == "clinical_switch":
        f.configuration.workspace_athena_medications_enabled = False
        return
    if withdrawal == "ehr_switch":
        f.configuration.workspace_ehr_read_enabled = False
        return
    with Session(f.engine) as s:
        grant = s.get(EhrAthenaMedicationPatientGrant, f.grant_id)
        assert grant is not None
        grant.state, grant.revoked_at = "revoked", datetime.now(UTC)
        s.commit()


def model_http(f, claimed, revoke_at=None):
    context = _context(claimed.envelope["context"])
    source = next(p for p in context.sources if p.entry_id == f.selected["entry_id"])
    handle = next(h for h in claimed.envelope["tool_selection"]["sources"] if h["entry_id"] == source.entry_id)
    assert source.content == f.content and handle["sha256"] == hashlib.sha256(f.content.encode()).hexdigest()
    calls, reads = [], []

    def respond(request):
        assert str(request.url) == ENDPOINT
        body = json.loads(request.content)
        assert body["store"] is False
        calls.append(body)
        with Session(f.engine) as check:
            assert check.scalar(select(Principal).where(Principal.id == f.owner).with_for_update(nowait=True))
        if revoke_at == len(calls):
            revoke(f)
        if len(calls) == 1:
            supplied = json.loads(body["messages"][1]["content"])
            initial = next(p for p in supplied["sources"] if p["source_id"] == source.entry_id)
            # This deliberately long medication snapshot uses the existing
            # marked-excerpt delivery. The exact tool read below must return
            # all original groups, number tokens, qualifiers and dates before a reply can settle.
            assert initial["truncated"] is True
            assert 0 < len(initial["text"]) < len(f.content)
            assert f.content.startswith(initial["text"])
            delivery = next(p for p in supplied["source_delivery"] if p["entry_id"] == source.entry_id)
            assert delivery["delivery"] == "excerpt"
            assert "sha256" not in delivery and "excerpt_sha256" not in delivery
            saved_delivery = next(p for p in claimed.envelope["source_delivery"] if p["entry_id"] == source.entry_id)
            assert saved_delivery["sha256"] == handle["sha256"]
            assert saved_delivery["excerpt_sha256"] == hashlib.sha256(initial["text"].encode()).hexdigest()
            outbound_handles = json.loads(body["messages"][3]["content"])["tool_selection"]["sources"]
            assert next(p for p in outbound_handles if p["entry_id"] == source.entry_id) == handle
            return httpx.Response(200, json=product.response(calls=[product.read_call(handle)]))
        assert len(calls) == 2
        result = json.loads(body["messages"][-1]["content"])
        assert result["data"]["content"] == f.content
        assert result["receipt"]["initiated_by_human_id"] == f.owner
        assert result["receipt"]["actor_agent_id"] != f.owner
        reads.append(result)
        output = {"answer": "Invented chart-review questions; recorded statuses require clinician reconciliation.",
            "source_ids": [p.entry_id for p in context.sources]}
        if claimed.envelope["baseline"]["flags"]["work_status"]:
            output["intent"] = "conversation"
        if claimed.envelope["baseline"]["flags"]["can_handoff"]:
            output["handoffs"] = []
        return httpx.Response(200, json=product.response(output))

    return httpx.MockTransport(respond), calls, reads


def test_reviewed_medications_reach_chief_tool_without_altering_the_note(athena_medication_model_case):
    f = athena_medication_model_case
    assert "Athena: recorded medication entries" in f.content
    assert "No medications reported statement: Explicitly true" in f.content
    assert f.section_json in f.content
    for exact in ('"quantity":0.50', '"tiny":1e-7', '"signedzero":-0', '"minimum":-9223372036854775808', '"maximum":9223372036854775807', '"\\ue000":0.500', '"\\ud83d\\ude00":1E+3'):
        assert exact in f.section_json
    assert "Returned medication groups: 3; returned entries: 2" in f.content
    assert "have not yet been submitted" in f.content
    assert "Original model-review qualifier" in f.content and "Final qualifier remains present." in f.content
    claimed = product.reserve(f.engine, (f.box, f.owner, f.wid),
        "Prepare questions about the reviewed medication records; preserve unknown facts.", "invented-athena-medication-chart-chief")
    transport, calls, reads = model_http(f, claimed)
    state, result_id, _ = product.dispatch_and_settle(f.engine, claimed, transport)
    assert state == "completed" and result_id and len(calls) == 2 and len(reads) == 1
    with Session(f.engine) as s:
        current = ws.read(s, f.box, f.owner, f.wid)
        for name in ("id", "content", "content_hash", "source_fingerprint", "review"):
            assert current["note"]["latest"][name] == f.note_before[name]
        assert current["note"]["latest"]["sources_changed"] is False
        audit = list(s.scalars(select(AuditEvent).where(AuditEvent.aggregate_id == claimed.admission_id,
            AuditEvent.event_type == "workspace.agent_tool_read")))
        assert len(audit) == 1 and f.content not in json.dumps(audit[0].detail)
        assert "Invented tablet" not in json.dumps(audit[0].detail)


@pytest.mark.parametrize("withdrawal", ["grant", "clinical_switch", "ehr_switch"])
@pytest.mark.parametrize("revoke_at", [1, 2])
def test_access_loss_during_chief_work_prevents_publication(athena_medication_model_case, revoke_at, withdrawal):
    f = athena_medication_model_case
    f.withdrawal = withdrawal
    claimed = product.reserve(f.engine, (f.box, f.owner, f.wid),
        "Prepare chart-review questions.", "invented-athena-medication-chart-revoked-during-model")
    transport, calls, _ = model_http(f, claimed, revoke_at=revoke_at)
    state, result_id, _ = product.dispatch_and_settle(f.engine, claimed, transport)
    assert state == "failed" and result_id is None and len(calls) == revoke_at
    with Session(f.engine) as s:
        events = list(s.scalars(select(AuditEvent).where(AuditEvent.aggregate_id == claimed.admission_id,
            AuditEvent.event_type == "workspace.agent_tool_read")))
        assert len(events) == revoke_at - 1
        assert s.scalar(select(WorkspaceReply).where(WorkspaceReply.workspace_id == f.wid)) is None


@pytest.mark.parametrize("withdrawal", ["grant", "clinical_switch", "ehr_switch"])
def test_later_access_loss_withholds_both_medication_text_and_derived_reply(athena_medication_model_case, withdrawal):
    f = athena_medication_model_case
    f.withdrawal = withdrawal
    claimed = product.reserve(f.engine, (f.box, f.owner, f.wid),
        "Prepare chart-review questions.", "invented-athena-medication-chart-later-revocation")
    transport, calls, _ = model_http(f, claimed)
    state, result_id, _ = product.dispatch_and_settle(f.engine, claimed, transport)
    assert state == "completed" and result_id
    provider_calls = list(f.provider.calls)
    revoke(f)
    with Session(f.engine) as s:
        projected = work.project_workspace(s, ws.read(s, f.box, f.owner, f.wid))
        source = next(e for e in projected["entries"] if e["id"] == f.selected["entry_id"])
        reply = next(e for e in projected["entries"] if e["id"] == result_id)
        assert source["ehr_source_state"] == reply["ehr_source_state"] == "unavailable"
        assert source["content"] == reply["content"] == "" and reply["reply"] is None
        assert f.content not in json.dumps(projected)
        stored = s.get(WorkspaceReply, result_id)
        assert stored is not None and stored.content  # Retained history is not new authorization.
    assert len(calls) == 2 and f.provider.calls == provider_calls


@pytest.mark.parametrize("withdrawal", ["grant", "clinical_switch", "ehr_switch"])
def test_access_lost_before_admission_omits_medications_from_context_and_tool_selection(athena_medication_model_case, withdrawal):
    f = athena_medication_model_case
    f.withdrawal = withdrawal
    revoke(f)
    before = list(f.provider.calls)
    claimed = product.reserve(f.engine, (f.box, f.owner, f.wid),
        "Prepare questions from the currently available saved context.", "invented-athena-medication-unavailable-before-admission")
    context = _context(claimed.envelope["context"])
    assert f.selected["entry_id"] not in {source.entry_id for source in context.sources}
    assert f.selected["entry_id"] not in {handle["entry_id"] for handle in claimed.envelope["tool_selection"]["sources"]}
    assert f.content not in json.dumps(claimed.envelope) and "Invented tablet" not in json.dumps(claimed.envelope)
    calls = []
    def respond(request):
        assert str(request.url) == ENDPOINT
        body = json.loads(request.content)
        calls.append(body)
        assert body["store"] is False
        supplied = json.loads(body["messages"][1]["content"])
        assert f.selected["entry_id"] not in {item["source_id"] for item in supplied["sources"]}
        assert "Invented tablet" not in json.dumps(body)
        output = {"answer": "Invented preparation from currently available sources; no medication assessment.",
            "source_ids": [source.entry_id for source in context.sources]}
        if claimed.envelope["baseline"]["flags"]["work_status"]:
            output["intent"] = "conversation"
        if claimed.envelope["baseline"]["flags"]["can_handoff"]:
            output["handoffs"] = []
        return httpx.Response(200, json=product.response(output))
    state, result_id, _ = product.dispatch_and_settle(f.engine, claimed, httpx.MockTransport(respond))
    assert state == "completed" and result_id and len(calls) == 1
    assert f.provider.calls == before


@pytest.mark.parametrize("withdrawal", ["grant", "clinical_switch", "ehr_switch"])
def test_access_lost_after_reservation_blocks_the_dispatch_claim(athena_medication_model_case, withdrawal):
    f = athena_medication_model_case
    f.withdrawal = withdrawal
    before = list(f.provider.calls)
    with Session(f.engine) as s:
        revision = ws.read(s, f.box, f.owner, f.wid)["revision"]
        admission_id, _ = work.reserve_conversation(s, f.box, f.owner, f.wid, expected=revision,
            team_revision=1, key="invented-athena-medication-revoked-before-claim", role="chief",
            content="Prepare questions about the reviewed medication source.")
        row = s.get(ModelWorkAdmission, admission_id)
        assert row is not None and row.state == "reserved"
        assert f.selected["entry_id"] in {source.entry_id for source in _context(row.prepared_envelope["context"]).sources}
    revoke(f)
    with Session(f.engine) as s:
        # Claim is the existing dispatch authorization boundary; no model HTTP
        # or tool execution is allowed when the reserved source has changed.
        assert work.claim(s, f.box, f.owner, admission_id) is None
        row = s.get(ModelWorkAdmission, admission_id)
        assert row is not None and row.state == "failed" and row.result_entry_id is None
        assert row.dispatch_id is None and row.started_at is None
        assert s.scalar(select(AuditEvent).where(AuditEvent.aggregate_id == admission_id,
            AuditEvent.event_type == "workspace.agent_tool_read")) is None
    assert f.provider.calls == before
