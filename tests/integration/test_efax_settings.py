"""Real eFax setup and execution ledger; provider HTTP stays inside MockTransport."""

import base64
import json
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from tests.integration.test_vendor_artifact_ledger import PDF, admitted, claim, resolver, settle
from tests.integration.test_vendor_settings import account, recipient, view
from tests.integration.test_vendor_settings import setup_case as setup_case
from tests.integration.test_vendor_work import bound
from tests.integration.test_vendor_work import gates as gates
from tests.integration.test_vendor_work import vendor_case as vendor_case

from cosmas_os.adapters.vendor_artifacts import LocalVendorArtifactStore
from cosmas_os.adapters.vendor_connectors.transport import Credential
from cosmas_os.api import vendor_work_schemas as public
from cosmas_os.application import vendor_artifacts, vendor_readiness, vendor_settings, vendor_work
from cosmas_os.application import vendor_execution as execution
from cosmas_os.application import vendor_settings_admission as admission
from cosmas_os.application import workspace as ws
from cosmas_os.application.vendor_settings_execution import VendorSettingsExecution
from cosmas_os.config import settings
from cosmas_os.models import Operation
from cosmas_os.ports.vendor_connectors import ConnectionSelection, DocumentBinding
from cosmas_os.vendor_models import (
    VendorConnectionVersion,
    VendorCorrespondenceVersion,
    VendorProviderObservation,
    VendorReadClaim,
    VendorSubmitClaim,
)
from cosmas_os.vendor_setup_models import VendorSetup


@pytest.fixture
def efax_case(setup_case):
    c = setup_case
    item = vendor_settings.Installation(ConnectionSelection(
        vendor="efax", connection_id=uuid4(), box_id=c["box"], owner_id=c["actor"],
        environment="production", remote_account_id="invented_api_user",
        credential_ref=uuid4(), configuration_sha256="a" * 64,
    ), "Invented eFax practice", "Invented sender", {"caller_id": "2125550100"}, ("efax_fax",))
    return {**c, "installed": vendor_settings.Catalog((item,))}


def _managed_guard(session, c):
    # Match the installed-catalog fence used by the registered work routes.
    session.info["vendor_managed_selection_guard"] = lambda w, connection_id, mutating=True: admission.require(
        session, w, connection_id, c["installed"], mutating=mutating
    )


def _approved_efax_work(session, efax_case, tmp_path):
    c = efax_case
    _managed_guard(session, c)
    a = account(session, c, "efax")
    r = recipient(session, c, a, "fax")
    av, rv = view(session, c, a), view(session, c, r)
    native = session.get(VendorConnectionVersion, av["review"]["connection_version_id"])
    mapping = session.get(VendorCorrespondenceVersion, rv["review"]["correspondence_version_id"])
    artifact_case = {**c, "owner": c["actor"]}
    initial, admission = admitted(session, artifact_case)
    store = LocalVendorArtifactStore(tmp_path / "efax-private-pdf")
    assert vendor_artifacts.write_content(store, claim(admission), PDF) == "ready"
    assert settle(session, admission, "ready") == "settled"
    recovered = vendor_artifacts.resolve(session, c["box"], c["actor"], c["wid"], resolver(initial))
    assert recovered["artifact"]["state"] == "ready"
    doc = recovered["artifact"]["document"]
    request = public.VendorProposal.model_validate({
        "expected_workspace_revision": 3, "idempotency_key": "efax-proposal-" + str(uuid4()),
        "proposed_operation_id": str(uuid4()), "action": "efax_fax",
        "connection": {k: vendor_work._connection_view(native)[k] for k in ("id", "revision", "public_sha256")},
        "correspondence": {k: vendor_work._correspondence_view(mapping, datetime.now(UTC))[k] for k in ("id", "revision", "public_sha256")},
        "source": c["source"], "document": doc, "due_date": "2026-10-01",
        "expected_outcome": "Review invented eFax document", "share_to_practice": False,
    })
    response = vendor_work.propose(session, c["box"], c["actor"], c["wid"], request)
    tid = response["effect"]["ticket_id"]
    pending = vendor_work.detail(session, c["box"], c["actor"], c["wid"], tid)
    assert pending["summary"]["state"] == "pending_approval"
    assert not pending["summary"]["submit_claimed"]
    assert pending["review"]["action"] == "efax_fax" and pending["review"]["document"] == doc
    vendor_work.decide(session, c["box"], c["actor"], c["wid"], tid,
                       public.VendorDecision(**bound(pending, review_sha256=pending["review_sha256"], choice="approve")))
    approved = vendor_work.detail(session, c["box"], c["actor"], c["wid"], tid)
    assert approved["summary"]["state"] == "approved" and not approved["summary"]["submit_claimed"]
    assert approved["summary"]["transport"] == "not_observed"
    return SimpleNamespace(case=c, ticket_id=tid, detail=approved, store=store,
                           selection=ConnectionSelection.model_validate(native.private_selection))


def test_efax_approved_work_uses_bound_private_pdf_recipient_and_separate_approval(session, efax_case, tmp_path):
    prepared = _approved_efax_work(session, efax_case, tmp_path)
    assert prepared.detail["availability"]["verify"] == {"allowed": False, "reason": "result_required"}


def _runtime(session, prepared, handler):
    connection, c = session.get_bind(), prepared.case
    seen = SimpleNamespace(calls=[], credentials=[])

    @contextmanager
    def sessions():
        # Fresh sequential worker sessions share only the fixture's outer rollback
        # transaction. Do not replace application authorization or settlement.
        with Session(bind=connection, join_transaction_mode="create_savepoint", autoflush=False) as scoped:
            _managed_guard(scoped, c)
            yield scoped

    async def credentials(selected):
        assert selected == prepared.selection
        seen.credentials.append(selected.commitment())
        return Credential(selection_sha256=selected.commitment(), credential_ref=str(selected.credential_ref),
                          secret=SecretStr("invented-current-efax-bearer"))

    async def identity_current():
        return True

    async def exchange(request):
        seen.calls.append(request)
        assert request.headers["authorization"] == "Bearer invented-current-efax-bearer"
        assert request.headers["user-id"] == prepared.selection.remote_account_id
        return handler(request)

    return VendorSettingsExecution(sessions, credentials, artifact_store=prepared.store,
        transport=httpx.MockTransport(exchange), identity_current=identity_current,
        installed_catalog=lambda: c["installed"]), seen


async def _invoke(session, runtime, invocation):
    assert invocation is not None
    # End the foreground read savepoint before worker sessions use the connection.
    session.commit()
    await runtime.invoke(invocation)
    session.expire_all()


def _call(session, prepared, function, *args):
    c = prepared.case
    return function(session, c["box"], c["actor"], c["wid"], *args)


@pytest.mark.asyncio
async def test_efax_approved_pdf_submits_and_status_settles_without_human_verification(
    session, efax_case, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "vendor_io_enabled", True)
    prepared = _approved_efax_work(session, efax_case, tmp_path)
    fax_id = str(uuid4())
    statuses = iter(("NEW", "COMPLETE"))

    def provider(request):
        if request.method == "POST":
            assert str(request.url) == "https://api.securedocex.com/faxes"
            assert json.loads(request.content) == {
                "destinations": [{"fax_number": "+12125550123"}],
                "documents": [{"document_type": "PDF", "document_content": base64.b64encode(PDF).decode("ascii")}],
                "fax_options": {"custom_CallerID": "12125550100", "include_cover_page": False,
                                "non_billable_retries": 0, "billable_retries": 0},
            }
            return httpx.Response(201, json=[{"fax_id": fax_id, "destination_fax_number": "2125550123"}])
        assert request.method == "GET" and not request.content
        assert str(request.url) == f"https://api.securedocex.com/faxes/{fax_id}/metadata"
        return httpx.Response(200, json={
            "fax_id": fax_id, "direction": "OUTBOUND", "destination_fax_number": "+12125550123",
            "fax_status": "STORED", "pages": 2, "completed_timestamp": datetime.now(UTC).isoformat(),
            "transmission_data": {"transmission_status": next(statuses), "error_code": "", "error_message": ""},
        })

    runtime, seen = _runtime(session, prepared, provider)
    receipt, invocation = _call(session, prepared, execution.claim_submit, prepared.ticket_id,
                               public.BoundCommand(**bound(prepared.detail)))
    assert receipt["summary"]["effect"] == "submit_claimed"
    assert invocation.command.selection == prepared.selection
    assert invocation.command.intent.document == DocumentBinding.model_validate(prepared.detail["review"]["document"])
    assert seen.calls == seen.credentials == []
    await _invoke(session, runtime, invocation)
    accepted = _call(session, prepared, vendor_work.detail, prepared.ticket_id)
    assert accepted["summary"]["acceptance"] == "accepted"
    assert accepted["summary"]["dispatch"] == "response_observed"
    assert accepted["summary"]["transport"] == "not_observed"
    assert accepted["availability"]["submit"] == {"allowed": False, "reason": "submit_already_claimed"}
    assert accepted["availability"]["reconcile"]["allowed"]

    current = accepted
    for transport in ("pending", "delivered"):
        read_receipt, read = _call(session, prepared, execution.claim_read, prepared.ticket_id,
                                  public.BoundCommand(**bound(current)))
        assert read_receipt["summary"]["effect"] == "read_claimed"
        assert read.reference.value == fax_id
        assert read.reference.selection_sha256 == prepared.selection.commitment()
        await _invoke(session, runtime, read)
        current = _call(session, prepared, vendor_work.detail, prepared.ticket_id)
        assert current["summary"]["transport"] == transport
        assert current["summary"]["state"] == "approved"
        assert current["summary"]["verification"] == "pending"
        assert current["latest_result"] is None
        read_claim = session.get(VendorReadClaim, read.claim_id)
        assert read_claim.state == "settled" and read_claim.completed_at is not None

    page = _call(session, prepared, vendor_work.observations, prepared.ticket_id)
    facts = page["observations"]
    assert [row["kind"] for row in facts] == ["dispatch", "submission", "transport", "transport"]
    assert facts[2]["transport"] == "pending" and "pages_delivered" not in facts[2]
    assert facts[3]["transport"] == "delivered" and facts[3]["pages_total"] == facts[3]["pages_delivered"] == 2
    assert current["availability"]["verify"] == {"allowed": False, "reason": "result_required"}
    operation = session.get(Operation, invocation.operation_id)
    assert operation.status == "succeeded" and operation.attempt_count == 1
    assert session.get(VendorSubmitClaim, operation.id).completed_at is not None
    saved = list(session.scalars(select(VendorProviderObservation).where(
        VendorProviderObservation.operation_id == operation.id).order_by(VendorProviderObservation.sequence)))
    assert [row.source for row in saved] == ["internal_dispatch", "submit", "read", "read"]
    assert all(row.private_reference["value"] == fax_id for row in saved[1:])
    assert [request.method for request in seen.calls] == ["POST", "GET", "GET"]
    assert len(seen.credentials) == 3
    public_json = json.dumps({"detail": current, "observations": page})
    assert fax_id not in public_json and "invented-current-efax-bearer" not in public_json
    assert base64.b64encode(PDF).decode("ascii") not in public_json
    session.commit()
    with runtime.sessions() as reopened:
        assert _call(reopened, prepared, vendor_work.detail, prepared.ticket_id)["summary"] == current["summary"]
        assert _call(reopened, prepared, vendor_work.observations, prepared.ticket_id)["observations"] == facts


@pytest.mark.asyncio
async def test_efax_ambiguous_send_is_durable_and_never_replayed(session, efax_case, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "vendor_io_enabled", True)
    prepared = _approved_efax_work(session, efax_case, tmp_path)

    def lost_response(request):
        assert request.method == "POST" and str(request.url) == "https://api.securedocex.com/faxes"
        raise httpx.ReadTimeout("Invented private provider diagnostic", request=request)

    runtime, seen = _runtime(session, prepared, lost_response)
    request = public.BoundCommand(**bound(prepared.detail))
    receipt, invocation = _call(session, prepared, execution.claim_submit, prepared.ticket_id, request)
    await _invoke(session, runtime, invocation)
    uncertain = _call(session, prepared, vendor_work.detail, prepared.ticket_id)
    assert uncertain["summary"]["submit_claimed"]
    assert uncertain["summary"]["dispatch"] == uncertain["summary"]["acceptance"] == "unconfirmed"
    assert uncertain["summary"]["transport"] == "not_observed"
    assert uncertain["summary"]["verification"] == "pending"
    assert uncertain["availability"]["submit"] == {"allowed": False, "reason": "submit_already_claimed"}
    assert uncertain["availability"]["reconcile"] == {"allowed": False, "reason": "reference_unavailable"}
    recovered, replay = _call(session, prepared, execution.claim_submit, prepared.ticket_id, request)
    assert recovered["effect"] == receipt["effect"] and replay is None
    resolved = _call(session, prepared, vendor_work.resolve, public.VendorResolve(
        command_kind="submit", idempotency_key=request.idempotency_key, request_sha256=receipt["request_sha256"]))
    assert resolved["effect"] == receipt["effect"]
    with pytest.raises(ws.WorkspaceError, match="vendor_submit_already_claimed"):
        _call(session, prepared, execution.claim_submit, prepared.ticket_id,
              public.BoundCommand(**bound(uncertain)))
    with pytest.raises(ws.WorkspaceError, match="vendor_reference_unavailable"):
        _call(session, prepared, execution.claim_read, prepared.ticket_id,
              public.BoundCommand(**bound(uncertain)))
    # Even accidental redelivery of the already-completed internal invocation
    # cannot acquire credentials or start another provider request.
    await _invoke(session, runtime, invocation)
    current = _call(session, prepared, vendor_work.detail, prepared.ticket_id)
    assert current["summary"] == uncertain["summary"]
    operation = session.get(Operation, invocation.operation_id)
    assert operation.status == "unknown" and operation.attempt_count == 1
    assert session.get(VendorSubmitClaim, operation.id).completed_at is not None
    assert session.scalar(select(func.count()).select_from(VendorSubmitClaim).where(
        VendorSubmitClaim.operation_id == operation.id)) == 1
    assert session.scalar(select(func.count()).select_from(VendorReadClaim).where(
        VendorReadClaim.operation_id == operation.id)) == 0
    page = _call(session, prepared, vendor_work.observations, prepared.ticket_id)
    assert [row["kind"] for row in page["observations"]] == ["dispatch", "submission"]
    assert page["observations"][-1]["safe_error"] == "transport_unconfirmed"
    assert "Invented private provider diagnostic" not in json.dumps(page)
    assert len(seen.calls) == len(seen.credentials) == 1


def test_one_account_row_per_owner_installation_keeps_readiness_counts_consistent(session, efax_case):
    c = efax_case
    a = account(session, c, "efax")
    row = session.get(VendorSetup, a["effect"]["setup_id"])
    values = {column.name: getattr(row, column.name) for column in VendorSetup.__table__.columns}
    values["id"] = str(uuid4())
    with pytest.raises(IntegrityError, match="uq_vendor_setup_installation"), session.begin_nested():
        session.add(VendorSetup(**values))
        session.flush()
    result = vendor_readiness.readiness(session, c["box"], c["actor"], c["installed"], policy=vendor_settings.VendorSetupPolicy(True))
    efax = next(row for row in result["providers"] if row["id"] == "efax")
    assert efax["installed_accounts"] == efax["active_accounts"] == 1
