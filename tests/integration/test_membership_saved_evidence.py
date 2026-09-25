"""Real PostgreSQL/main-app saved evidence; no local journal or provider I/O."""

import base64
import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import attributes
from tests.integration import test_finance_work as financial
from tests.integration import test_membership_work as member
from tests.integration import test_vendor_artifact_ledger as artifacts
from tests.integration.test_membership_privacy import other_humans as other_humans
from tests.integration.test_membership_privacy import production_client as production_client
from tests.integration.test_membership_retirement_main_app import headers
from tests.integration.test_vendor_work import gates as gates
from tests.integration.test_vendor_work import vendor_case as vendor_case

from cosmas_os.adapters.vendor_artifacts import LocalVendorArtifactStore
from cosmas_os.api import app as api
from cosmas_os.api import finance_work_schemas as fp
from cosmas_os.api import membership_saved_evidence_schemas as schema
from cosmas_os.api import vendor_work_schemas as public
from cosmas_os.application import finance_execution, finance_work
from cosmas_os.application import membership_saved_evidence as saved
from cosmas_os.application import membership_work as flow
from cosmas_os.application.workspace import WorkspaceError
from cosmas_os.finance_models import FinanceReceipt
from cosmas_os.membership_models import MembershipReceipt
from cosmas_os.models import EncounterWorkspace, Operation, Principal


@pytest.fixture
def saved_case(session, vendor_case, tmp_path, monkeypatch):
    c = vendor_case
    factory = getattr(financial.finance_case, "__wrapped__", None)
    assert callable(factory)
    fc = factory(session, c)
    ftid, _, d = financial.approved(session, fc)
    _, invoke = financial.call(
        session,
        fc,
        finance_execution.claim_submit,
        ftid,
        public.BoundCommand(**financial.bound(d)),
        policy=financial.POLICY,
    )
    finance_execution.mark_invocation(session, invoke)
    finance_execution.settle(session, invoke, observation=financial.created_observation(invoke))
    d = financial.call(session, fc, finance_work.detail, ftid)
    _, read = financial.call(
        session,
        fc,
        finance_execution.claim_read,
        ftid,
        public.BoundCommand(**financial.bound(d)),
        policy=financial.POLICY,
    )
    finance_execution.settle(session, read, observation=financial.payment(read))
    d = financial.call(session, fc, finance_work.detail, ftid)
    human = financial.call(
        session,
        fc,
        finance_work.record_result,
        ftid,
        fp.FinanceResult(
            **financial.bound(d),
            observation_head=d["summary"]["observation_head"],
            evidence_sha256=d["summary"]["evidence_sha256"],
            disposition="reported_paid",
            evidence="Invented owner observed payment result.",
        ),
    )
    d = financial.call(session, fc, finance_work.detail, ftid)
    request = fp.FinanceVerify(
        **financial.bound(d),
        result_receipt_id=human["effect"]["receipt_id"],
        result_receipt_sha256=human["receipt_sha256"],
        observation_head=d["summary"]["observation_head"],
        evidence_sha256=d["summary"]["evidence_sha256"],
        reviewed_result=True,
        reviewed_observations=True,
        outcome_confirmed=True,
        reviewed_conflicting_evidence=False,
    )
    verified = financial.call(session, fc, finance_work.verify, ftid, request)
    # Reuse a preserved real generated PDF; this test qualifies custody, not visual interpretation.
    fixture = json.loads(
        (
            Path(__file__).parents[2]
            / "web/src/__fixtures__/membership/actual-membership-saved-evidence.json"
        ).read_text()
    )
    pdf = base64.b64decode(fixture["pdf_base64"])
    monkeypatch.setattr(artifacts, "PDF", pdf)
    monkeypatch.setattr(member, "PDF", pdf)
    tid = member.created(session, c)
    ledger = member.ready_ledger(session, c, tmp_path)
    ledger["finance"] = {
        "ticket_id": ftid,
        "verification_receipt_id": verified["effect"]["receipt_id"],
        "verification_receipt_sha256": verified["receipt_sha256"],
        "evidence_sha256": d["summary"]["evidence_sha256"],
    }
    result = member.result(session, c, tid, disposition="record_reviewed", ledger=ledger)
    return c | {
        "fc": fc,
        "tid": tid,
        "ftid": ftid,
        "ledger": ledger,
        "result_id": result["effect"]["receipt_id"],
        "request": request,
        "pdf": pdf,
        "store": LocalVendorArtifactStore(next(tmp_path.glob("membership-proof-*"))),
    }


def path(c, *, tid=None, result_id=None):
    return f"/workspaces/{c['wid']}/membership-work/{tid or c['tid']}/results/{result_id or c['result_id']}/finance-evidence"


def inspect(s, c):
    return saved.finance_evidence(
        s, c["box"], c["actor"], c["wid"], c["tid"], c["result_id"], policy=member.POLICY
    )


def test_actual_main_app_other_device_original_request_and_later_finance_command(
    session,
    saved_case,
    production_client,
    tmp_path,
):
    c, http = saved_case, production_client
    member.call(
        session, c, flow.command, c["tid"], "verify", member.verification(session, c, c["tid"])
    )
    # Another finance proposal replaces a device's last journal without changing this proof.
    financial.call(
        session, c["fc"], finance_work.propose, financial.proposal(c["fc"]), policy=financial.POLICY
    )
    before = session.scalar(select(func.count()).select_from(FinanceReceipt))
    response = http.get(path(c), headers=headers(c))
    assert response.status_code == 200, response.text
    v = response.json()
    assert schema.MembershipSavedFinance.model_validate(v).public() == v
    assert len(response.content) <= 65536
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["access-control-allow-origin"] == headers(c)["Origin"]
    row = session.get(FinanceReceipt, c["ledger"]["finance"]["verification_receipt_id"])
    assert v["request"] == row.public_request == c["request"].public()
    assert public.canonical(v["request"]) == public.canonical(row.public_request)
    assert (
        fp.request_digest(
            "verify",
            {"kind": "workspace", "id": c["wid"]},
            fp.FinanceVerify.model_validate(v["request"]),
        )
        == row.request_sha256
        == v["receipt"]["request_sha256"]
    )
    assert v["receipt"]["receipt_sha256"] == row.receipt_sha256
    assert (
        v["membership"]["version"] == 4 and v["membership"]["result_receipt_id"] == c["result_id"]
    )
    assert session.scalar(select(func.count()).select_from(FinanceReceipt)) == before
    assert session.scalar(select(Operation.id).where(Operation.ticket_id == c["tid"])) is None
    vector = {
        "response": v,
        "membership_detail": member.detail(session, c, c["tid"]),
        "membership_history": member.call(session, c, flow.history, c["tid"]),
        "pdf_base64": base64.b64encode(c["pdf"]).decode(),
        "response_bytes": len(response.content),
    }
    (tmp_path / "actual-membership-cross-device-evidence.json").write_text(
        json.dumps(vector, indent=2)
    )


@pytest.mark.parametrize("who", ["owner", "staff", "ticket", "result"])
def test_private_404_for_foreign_or_wrong_saved_binding(
    session, saved_case, production_client, other_humans, who
):
    c = saved_case
    h = (
        headers(c, other_humans[0 if who == "owner" else 1])
        if who in {"owner", "staff"}
        else headers(c)
    )
    url = path(
        c,
        **(
            {"tid": str(uuid4())}
            if who == "ticket"
            else {"result_id": str(uuid4())}
            if who == "result"
            else {}
        ),
    )
    response = production_client.get(url, headers=h)
    assert response.status_code == 404
    assert response.json() == {
        "contract_version": 1,
        "error": {"code": "membership_work_unavailable"},
    }
    assert c["ledger"]["record_reference"] not in response.text


@pytest.mark.parametrize("mode", ["missing", "duplicate", "wrong", "query"])
def test_closed_contract_and_query_policy(saved_case, production_client, mode):
    c = saved_case
    h = headers(c)
    url = path(c)
    if mode == "missing":
        h.pop("X-Cosmas-Membership-Contract")
    elif mode == "wrong":
        h["X-Cosmas-Membership-Contract"] = "2"
    elif mode == "query":
        url += "?finance_ticket=" + c["ftid"]
    else:
        h = list(h.items()) + [("X-Cosmas-Membership-Contract", "1")]
    response = production_client.get(url, headers=h)
    assert response.status_code == 426 and response.headers["cache-control"] == "no-store"


def test_historical_note_remains_inspectable_without_new_approval(
    session, saved_case, production_client
):
    c = saved_case
    w = session.get(EncounterWorkspace, c["wid"])
    w.revision += 1
    session.commit()
    assert not member.detail(session, c, c["tid"])["summary"]["source_current"]
    before = session.scalar(select(func.count()).select_from(MembershipReceipt))
    assert production_client.get(path(c), headers=headers(c)).status_code == 200
    assert session.scalar(select(func.count()).select_from(MembershipReceipt)) == before


def test_replaced_result_is_not_inspectable_as_current(session, saved_case, production_client):
    c = saved_case
    member.result(
        session,
        c,
        c["tid"],
        disposition="record_reviewed",
        ledger=c["ledger"],
        evidence="Updated owner result",
    )
    assert production_client.get(path(c), headers=headers(c)).status_code == 404


def test_current_finance_contradiction_withholds_proof(session, saved_case, production_client):
    c = saved_case
    d = financial.call(session, c["fc"], finance_work.detail, c["ftid"])
    _, read = financial.call(
        session,
        c["fc"],
        finance_execution.claim_read,
        c["ftid"],
        public.BoundCommand(**financial.bound(d)),
        policy=financial.POLICY,
    )
    finance_execution.settle(session, read, observation=financial.payment(read, "canceled"))
    response = production_client.get(path(c), headers=headers(c))
    assert (
        response.status_code == 409
        and response.json()["error"]["code"] == "membership_evidence_changed"
    )


@pytest.mark.parametrize("field", ["request_sha256", "receipt_sha256", "public_request"])
def test_retained_finance_hash_corruption_fails_closed(session, saved_case, field):
    c = saved_case
    row = session.get(FinanceReceipt, c["ledger"]["finance"]["verification_receipt_id"])
    # Simulate corrupt loaded storage without bypassing SQL immutability or committing a mutation.
    original = getattr(row, field)
    altered = {**original, "outcome_confirmed": False} if field == "public_request" else "0" * 64
    attributes.set_committed_value(row, field, altered)
    try:
        with pytest.raises(WorkspaceError):
            inspect(session, c)
    finally:
        attributes.set_committed_value(row, field, original)


def test_final_authority_revocation_prevents_disclosure(session, saved_case):
    c = saved_case

    def revoked():
        raise WorkspaceError("membership_work_unavailable", 403)

    session.info["membership_final_authority"] = revoked
    try:
        with pytest.raises(WorkspaceError):
            inspect(session, c)
    finally:
        session.info.pop("membership_final_authority")


def test_disabled_private_selector_denies_read(session, saved_case):
    c = saved_case
    with pytest.raises(WorkspaceError):
        saved.finance_evidence(session, c["box"], c["actor"], c["wid"], c["tid"], c["result_id"])


@pytest.mark.parametrize("revoke_during_read", [False, True])
def test_saved_historical_pdf_uses_actual_two_phase_owner_preview(
    session,
    saved_case,
    production_client,
    revoke_during_read,
):
    c = saved_case
    workspace = session.get(EncounterWorkspace, c["wid"])
    workspace.revision += 1
    session.commit()
    assert member.detail(session, c, c["tid"])["summary"]["source_current"] is False
    store = c["store"]

    class CheckedStore:
        def read_verified(self, scope, *, deadline):
            data = store.read_verified(scope, deadline=deadline)
            if revoke_during_read:
                session.get(Principal, c["actor"]).state = "disabled"
                session.commit()
            return data

    production_client.app.dependency_overrides[api._vendor_artifact_store] = CheckedStore
    h = headers(c)
    h.pop("X-Cosmas-Membership-Contract")
    h["X-Cosmas-Vendor-Contract"] = "1"
    aid = c["ledger"]["document"]["artifact_id"]
    response = production_client.get(
        f"/workspaces/{c['wid']}/vendor-artifacts/{aid}/content", headers=h
    )
    assert response.headers["cache-control"] == "no-store"
    if revoke_during_read:
        assert response.status_code in {401, 403, 404}
        assert c["pdf"] not in response.content
    else:
        assert response.status_code == 200, response.text
        assert response.content == c["pdf"]
        assert len(response.content) == c["ledger"]["document"]["byte_length"]
        assert response.headers["content-type"] == "application/pdf"


@pytest.mark.parametrize("field", ["request_sha256", "receipt_sha256", "request"])
def test_saved_membership_result_corruption_withholds_finance(session, saved_case, field):
    c = saved_case
    row = session.get(MembershipReceipt, c["result_id"])
    original = getattr(row, field)
    altered = {**original, "evidence": "Changed saved result"} if field == "request" else "0" * 64
    attributes.set_committed_value(row, field, altered)
    try:
        with pytest.raises(WorkspaceError):
            inspect(session, c)
    finally:
        attributes.set_committed_value(row, field, original)
