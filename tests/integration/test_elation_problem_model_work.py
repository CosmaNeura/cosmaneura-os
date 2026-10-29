"""Reviewed problem-list text through real Chief admission, source tools and settlement."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session
from tests.integration import test_product_agent_tool_workflow as product
from tests.integration.test_ehr_reads import InventedElation
from tests.integration.test_note_review import prepare

from cosmas_os.adapters.elation_read import ElationReadScope
from cosmas_os.adapters.elation_read_runtime import SyntheticElationReads
from cosmas_os.adapters.gpt41 import ENDPOINT, _context
from cosmas_os.application import conversation, handoffs
from cosmas_os.application import ehr_reads as ehr
from cosmas_os.application import model_work as work
from cosmas_os.application import note_review as notes
from cosmas_os.application import provider_team as team
from cosmas_os.application import services as svc
from cosmas_os.application import workspace as ws
from cosmas_os.config import Settings
from cosmas_os.ehr_read_models import EhrReadBinding
from cosmas_os.models import AuditEvent, ExternalIdentity, Principal, WorkspaceReply


class InventedProblemProvider(InventedElation):
    def __call__(self, request):
        assert not self.session.in_transaction(), "Vendor I/O must not retain a SQL transaction"
        assert request.url.host == "sandbox.elationemr.com"
        if request.url.path == "/api/2.0/oauth2/token/":
            self.calls.append((request.method, request.url.path))
            assert request.method == "POST"
            scope = httpx.QueryParams(request.content.decode())["scope"]
            return httpx.Response(200, json=dict(access_token="invented-problem-token",
                token_type="Bearer", expires_in=3600, scope=scope))
        if request.url.path == "/api/2.0/problems/":
            self.calls.append((request.method, request.url.path))
            assert request.method == "GET"
            assert dict(request.url.params) == {"patient": "930", "practice": "910", "limit": "25"}
            return httpx.Response(200, json=dict(count=2, next=None, previous=None, results=[
                dict(id=951, patient=930, practice=910, description="Invented condition needing record review",
                    status="Active", verification_status="unconfirmed", start_date="2025-01-02",
                    resolved_date=None, deleted_date=None, dx=[], synopsis="", rank=1),
                dict(id=952, patient=930, practice=910, description="Invented resolved historical concern",
                    status="Resolved", verification_status=None, start_date="2023-04-05",
                    resolved_date="2024-02-03", deleted_date=None, dx=[], synopsis="", rank=2),
            ]))
        return super().__call__(request)


@pytest.fixture
def problem_model_case(engine, monkeypatch):
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
        workspace_elation_problems_enabled=True,
        workspace_llm_backend="azure_gpt41", workspace_llm_api_key=SecretStr("invented-product-http-key"),
    )
    for module in (team, conversation, handoffs):
        monkeypatch.setattr(module, "runtime_settings", configuration)
    with Session(engine) as s:
        seeded = svc.provision_box(svc.Container(s), "Invented Elation chart-review clinic")
    configuration.beta_box_id = seeded["box_id"]
    with Session(engine) as s:
        box, owner, initial, patient = prepare(s, seeded)
        team.save(s, box, owner, expected=0, key="invented-problems-team", configuration=team.default_configuration())
        state = notes.save(s, box, owner, initial["id"], expected=initial["revision"],
            key="invented-note-before-problems", base_note_id=None, source_reply_id=None,
            content="Invented clinical note: reconcile chart facts with the clinician before any action.")["workspace"]
        note = state["note"]["latest"]
        state = notes.review(s, box, owner, state["id"], note["id"], expected=state["revision"],
            key="invented-note-review-before-problems", content_hash=note["content_hash"],
            source_hash=note["source_fingerprint"])["workspace"]
        account = ExternalIdentity(box_id=box, principal_id=owner,
            issuer="https://clerk-" + str(uuid4()) + ".example.invalid", subject="invented-owner",
            organization_id="org_invented", reviewed_by="Invented owner", evidence_ref="invented:elation-chart")
        s.add(account)
        s.flush()
        scope = ElationReadScope(UUID(box), UUID(owner), uuid4(), uuid4(), 910, "Invented Elation Clinic")
        binding = EhrReadBinding(box_id=box, owner_id=owner, account_id=account.id, vendor="elation",
            connection_id=str(scope.connection_id), credential_generation=str(scope.credential_generation),
            practice_id="910", practice_name=scope.practice_name, environment="sandbox",
            binding_digest=scope.commitment(), state="active")
        s.add(binding)
        s.commit()
        provider = InventedProblemProvider(s)
        port = SyntheticElationReads((scope,), httpx.MockTransport(provider),
            enabled=lambda: True, problems_enabled=lambda: True)
        f = SimpleNamespace(engine=engine, box=box, owner=owner, wid=state["id"], account=account.id,
            patient=patient, binding_id=binding.id, scope=scope, port=port, provider=provider,
            note_before=state["note"]["latest"])
        with ehr.install_runtime_reader(lambda: port):
            start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
            window = ehr.observe(s, box, owner, account.id, key="invented-chart-window",
                connection_id=str(scope.connection_id), binding_sha256=scope.commitment(),
                starts_at=start, ends_at=start + timedelta(days=1), port=port)
            item = window["observation"]["items"][0]
            visit = ehr.verify(s, box, owner, account.id, key="invented-chart-verify",
                connection_id=str(scope.connection_id), binding_sha256=scope.commitment(),
                observation_id=window["observation_id"], observation_sha256=window["source_sha256"],
                item_handle=item["handle"], item_sha256=item["sha256"], port=port)
            item = visit["observation"]["item"]
            problems = ehr.problems(s, box, owner, account.id, key="invented-chart-problems",
                connection_id=str(scope.connection_id), binding_sha256=scope.commitment(),
                observation_id=visit["observation_id"], observation_sha256=visit["source_sha256"],
                item_handle=item["handle"], item_sha256=item["sha256"], port=port)
            item = problems["observation"]["item"]
            f.selected = ehr.select_review(s, box, owner, f.wid, expected=state["revision"],
                key="invented-chart-review", observation_id=problems["observation_id"],
                observation_sha256=problems["source_sha256"], item_handle=item["handle"], item_sha256=item["sha256"],
                reviewed_visit=True, reviewed_patient_identity=True, reviewed_exact_snapshot=True,
                reviewed_untrusted_source=True, port=port, external_identity_id=account.id)
            selected_workspace = f.selected["workspace"]
            assert isinstance(selected_workspace, dict)
            f.content = next(e["content"] for e in selected_workspace["entries"] if e["id"] == f.selected["entry_id"])
            s.commit()
            yield f


def revoke(f):
    with Session(f.engine) as s:
        binding = s.get(EhrReadBinding, f.binding_id)
        assert binding is not None
        binding.state, binding.revoked_at = "revoked", datetime.now(UTC)
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
            supplied = json.loads(body["messages"][1]["content"])["sources"]
            assert any(p["source_id"] == source.entry_id and p["text"] == f.content for p in supplied)
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


def test_reviewed_problems_reach_chief_tool_without_altering_the_note(problem_model_case):
    f = problem_model_case
    assert "unconfirmed" in f.content and "Resolved" in f.content
    claimed = product.reserve(f.engine, (f.box, f.owner, f.wid),
        "Prepare questions about the reviewed problem list; preserve unknown facts.", "invented-chart-chief")
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


@pytest.mark.parametrize("revoke_at", [1, 2])
def test_access_loss_during_chief_work_prevents_publication(problem_model_case, revoke_at):
    f = problem_model_case
    claimed = product.reserve(f.engine, (f.box, f.owner, f.wid),
        "Prepare chart-review questions.", "invented-chart-revoked-during-model")
    transport, calls, _ = model_http(f, claimed, revoke_at=revoke_at)
    state, result_id, _ = product.dispatch_and_settle(f.engine, claimed, transport)
    assert state == "failed" and result_id is None and len(calls) == revoke_at


def test_later_access_loss_withholds_both_problem_text_and_derived_reply(problem_model_case):
    f = problem_model_case
    claimed = product.reserve(f.engine, (f.box, f.owner, f.wid),
        "Prepare chart-review questions.", "invented-chart-later-revocation")
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
