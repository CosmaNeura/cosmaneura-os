"""Tebra clinical custody through real Chief admission, exact source tools and settlement."""

import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session
from tests.integration import test_product_agent_tool_workflow as product
from tests.integration.test_note_review import prepare
from tests.unit.test_tebra_fhir_read_runtime import PATIENT, Harness

from cosmas_os.adapters.gpt41 import ENDPOINT, _context
from cosmas_os.adapters.tebra_fhir_read_runtime import (
    SyntheticTebraFhirReads,
    TebraFhirAuthorizedPatient,
    TebraFhirConnectionScope,
)
from cosmas_os.application import conversation, handoffs
from cosmas_os.application import ehr_reads as ehr
from cosmas_os.application import model_work as work
from cosmas_os.application import note_review as notes
from cosmas_os.application import provider_team as team
from cosmas_os.application import services as svc
from cosmas_os.application import tebra_fhir_ehr as clinical
from cosmas_os.application import workspace as ws
from cosmas_os.config import Settings
from cosmas_os.domain.hashing import canonical_json, payload_hash
from cosmas_os.ehr_read_models import EhrFhirPatientGrant, EhrReadBinding
from cosmas_os.models import AuditEvent, ExternalIdentity, Principal, WorkspaceReply


class InventedClinicalProvider(Harness):
    def __init__(self, session):
        super().__init__()
        self.session = session
        self.row["medicationCodeableConcept"] = {"text": "Invented clinical medication"}
        self.row["note"] = [{"text": "Original qualifier: " + "Invented context remains unconfirmed. " * 40
            + "Final qualifier remains present."}]

    def send(self, request):
        assert not self.session.in_transaction(), "Vendor I/O must not retain a SQL transaction"
        return super().send(request)


@pytest.fixture
def tebra_fhir_model_case(engine, monkeypatch):
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
        workspace_tebra_fhir_enabled=True,
        workspace_llm_backend="azure_gpt41", workspace_llm_api_key=SecretStr("invented-product-http-key"),
    )
    for module in (team, conversation, handoffs):
        monkeypatch.setattr(module, "runtime_settings", configuration)
    with Session(engine) as s:
        seeded = svc.provision_box(svc.Container(s), "Invented Tebra clinical review clinic")
    configuration.beta_box_id = seeded["box_id"]
    with Session(engine) as s:
        box, owner, initial, patient_link_id = prepare(s, seeded)
        team.save(s, box, owner, expected=0, key="invented-fhir-team", configuration=team.default_configuration())
        state = notes.save(s, box, owner, initial["id"], expected=initial["revision"],
            key="invented-note-before-fhir", base_note_id=None, source_reply_id=None,
            content="Invented reviewed note: reconcile chart facts with the clinician before any action.")["workspace"]
        note = state["note"]["latest"]
        state = notes.review(s, box, owner, state["id"], note["id"], expected=state["revision"],
            key="invented-note-review-before-fhir", content_hash=note["content_hash"],
            source_hash=note["source_fingerprint"])["workspace"]
        account = ExternalIdentity(box_id=box, principal_id=owner,
            issuer="https://clerk-" + str(uuid4()) + ".example.invalid", subject="invented-owner",
            organization_id="org_invented", reviewed_by="Invented owner", evidence_ref="invented:tebra-clinical")
        s.add(account)
        s.flush()
        scope = TebraFhirConnectionScope(UUID(box), UUID(owner), UUID(account.id), uuid4(), uuid4(),
            "Invented Tebra Clinical")
        binding = EhrReadBinding(box_id=box, owner_id=owner, account_id=account.id, vendor="tebra", protocol="fhir",
            connection_id=str(scope.connection_id), credential_generation=str(scope.credential_generation),
            practice_id=None, practice_name=scope.display_label, environment="synthetic",
            binding_digest=scope.commitment(), state="active")
        s.add(binding)
        s.flush()
        grant = TebraFhirAuthorizedPatient(uuid4(), scope, UUID(state["id"]), UUID(patient_link_id),
            PATIENT["id"], "a" * 64, canonical_json(PATIENT), payload_hash(PATIENT))
        s.add(EhrFhirPatientGrant(id=str(grant.grant_id), box_id=box, owner_id=owner, account_id=account.id,
            binding_id=binding.id, workspace_id=state["id"], patient_link_id=patient_link_id,
            fhir_patient_id=grant.fhir_patient_id, authorization_sha256=grant.authorization_sha256,
            identity_json=grant.identity_json, identity_sha256=grant.identity_sha256,
            grant_digest=grant.commitment(), state="active"))
        s.commit()
        provider = InventedClinicalProvider(s)
        port = SyntheticTebraFhirReads((scope,), (grant,), httpx.MockTransport(provider.send), enabled=lambda: True)
        f = SimpleNamespace(engine=engine, box=box, owner=owner, wid=state["id"], account=account.id,
            patient=patient_link_id, grant_id=str(grant.grant_id), binding_id=binding.id, scope=scope,
            port=port, provider=provider, configuration=configuration, note_before=state["note"]["latest"])
        with ehr.install_runtime_reader(lambda: port):
            root = clinical.patients(s, box, owner, account.id, key="invented-fhir-patients",
                connection_id=str(scope.connection_id), binding_sha256=scope.commitment(), workspace_id=f.wid, port=port)
            assert not provider.calls
            root_public = root["observation"]
            assert isinstance(root_public, dict)
            item = root_public["items"][0]
            assert isinstance(item, dict)
            assert isinstance(root["observation_id"], str) and isinstance(root["source_sha256"], str)
            receipt = clinical.medications(s, box, owner, account.id, key="invented-fhir-medications",
                connection_id=str(scope.connection_id), binding_sha256=scope.commitment(), workspace_id=f.wid,
                observation_id=root["observation_id"], observation_sha256=root["source_sha256"],
                item_handle=item["handle"], item_sha256=item["sha256"], port=port)
            medication_public = receipt["observation"]
            assert isinstance(medication_public, dict)
            item = medication_public["item"]
            assert isinstance(item, dict)
            assert isinstance(receipt["observation_id"], str) and isinstance(receipt["source_sha256"], str)
            f.selected = ehr.select_review(s, box, owner, f.wid, expected=state["revision"],
                key="invented-fhir-review", observation_id=receipt["observation_id"],
                observation_sha256=receipt["source_sha256"], item_handle=item["handle"], item_sha256=item["sha256"],
                reviewed_visit=None, reviewed_patient_identity=True, reviewed_exact_snapshot=True,
                reviewed_untrusted_source=True, port=port, external_identity_id=account.id, provider="tebra", protocol="fhir")
            selected_workspace = f.selected["workspace"]
            assert isinstance(selected_workspace, dict)
            f.content = next(e["content"] for e in selected_workspace["entries"] if e["id"] == f.selected["entry_id"])
            assert len(provider.calls) == 2 and 2000 < len(f.content) <= 5000
            s.commit()
            yield f


def revoke(f):
    withdrawal = getattr(f, "withdrawal", "grant")
    if withdrawal == "clinical_switch":
        f.configuration.workspace_tebra_fhir_enabled = False
        return
    if withdrawal == "ehr_switch":
        f.configuration.workspace_ehr_read_enabled = False
        return
    with Session(f.engine) as s:
        grant = s.get(EhrFhirPatientGrant, f.grant_id)
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
            # all recorded directions and dates before a reply can settle.
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


def test_reviewed_medications_reach_chief_tool_without_altering_the_note(tebra_fhir_model_case):
    f = tebra_fhir_model_case
    assert "Invented clinical medication" in f.content and "Recorded status: stopped" in f.content
    assert "Do-not-perform flag: true" in f.content and "Authored date/time: 2025-01" in f.content
    assert canonical_json(f.provider.row["dosageInstruction"]) in f.content
    assert "Original qualifier" in f.content and "Final qualifier remains present." in f.content
    claimed = product.reserve(f.engine, (f.box, f.owner, f.wid),
        "Prepare questions about the reviewed medication records; preserve unknown facts.", "invented-fhir-chart-chief")
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
        assert "Invented clinical medication" not in json.dumps(audit[0].detail)


@pytest.mark.parametrize("withdrawal", ["grant", "clinical_switch"])
@pytest.mark.parametrize("revoke_at", [1, 2])
def test_access_loss_during_chief_work_prevents_publication(tebra_fhir_model_case, revoke_at, withdrawal):
    f = tebra_fhir_model_case
    f.withdrawal = withdrawal
    claimed = product.reserve(f.engine, (f.box, f.owner, f.wid),
        "Prepare chart-review questions.", "invented-fhir-chart-revoked-during-model")
    transport, calls, _ = model_http(f, claimed, revoke_at=revoke_at)
    state, result_id, _ = product.dispatch_and_settle(f.engine, claimed, transport)
    assert state == "failed" and result_id is None and len(calls) == revoke_at


@pytest.mark.parametrize("withdrawal", ["grant", "clinical_switch", "ehr_switch"])
def test_later_access_loss_withholds_both_medication_text_and_derived_reply(tebra_fhir_model_case, withdrawal):
    f = tebra_fhir_model_case
    f.withdrawal = withdrawal
    claimed = product.reserve(f.engine, (f.box, f.owner, f.wid),
        "Prepare chart-review questions.", "invented-fhir-chart-later-revocation")
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
