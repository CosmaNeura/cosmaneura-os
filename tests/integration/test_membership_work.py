"""Actual PostgreSQL membership review, manual evidence and immutable exact recovery."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from tests.integration.test_vendor_artifact_ledger import PDF, admitted, claim, settle
from tests.integration.test_vendor_work import gates as gates
from tests.integration.test_vendor_work import immediate
from tests.integration.test_vendor_work import vendor_case as vendor_case

from cosmas_os.adapters.local import LocalBlobAdapter
from cosmas_os.adapters.vendor_artifacts import LocalVendorArtifactStore
from cosmas_os.api import membership_work_routes as routes
from cosmas_os.api import membership_work_schemas as p
from cosmas_os.api import vendor_work_schemas as public
from cosmas_os.api.auth import RequestIdentity
from cosmas_os.application import membership_work as flow
from cosmas_os.application import services, vendor_artifacts
from cosmas_os.application import workspace as ws
from cosmas_os.membership_models import MembershipReceipt, MembershipWork
from cosmas_os.models import EncounterWorkspace, Operation, Principal
from cosmas_os.vendor_models import VendorArtifact

POLICY = flow.MembershipPolicy(True, True)
OFF = flow.MembershipPolicy(False, True)


def call(s, c, method, *args, **kwargs):
    return method(
        s, c["box"], c["actor"], c["wid"], *args, policy=kwargs.pop("policy", POLICY), **kwargs
    )


def proposal(s, c, **extra):
    options = call(s, c, flow.options)
    return p.Proposal.model_validate(
        {
            "expected_workspace_revision": options["expected_workspace_revision"],
            "idempotency_key": "membership-propose-" + str(uuid4()),
            "source": options["source"],
            "patient_link_id": options["patient_link_id"],
            "purpose": "enrollment_assistance",
            "due_date": "2026-09-30",
            "expected_outcome": "Review invented enrollment information",
            "instructions": "Prepare a local review; no patient enrollment or charge.",
            **extra,
        }
    )


def detail(s, c, tid):
    return call(s, c, flow.detail, tid)


def bound(d, **extra):
    x = d["summary"]
    return {
        "ticket_id": x["ticket_id"],
        "expected_version": x["version"],
        "revision_id": x["revision_id"],
        "payload_hash": x["payload_hash"],
        "idempotency_key": "membership-command-" + str(uuid4()),
        **extra,
    }


def approve(s, c, tid):
    d = detail(s, c, tid)
    req = p.Decision(
        **bound(d),
        review_sha256=d["review_sha256"],
        choice="approve",
        reviewed_patient=True,
        reviewed_local_only_authority=True,
    )
    return call(s, c, flow.command, tid, "decide", req)


def created(s, c, **extra):
    initial = call(s, c, flow.propose, proposal(s, c, **extra))
    tid = initial["effect"]["ticket_id"]
    approve(s, c, tid)
    return tid


def result(s, c, tid, **extra):
    request = p.Result(
        **bound(detail(s, c, tid)),
        disposition="local_preparation_ready",
        evidence="Invented local information was reviewed; membership is unreconciled.",
    )
    request = p.Result.model_validate(request.public() | extra)
    return call(s, c, flow.command, tid, "result", request)


def verification(s, c, tid):
    d = detail(s, c, tid)
    return p.Verify(
        **bound(d),
        result_receipt_id=d["latest_result"]["receipt_id"],
        result_receipt_sha256=d["latest_result"]["receipt_sha256"],
        evidence_classification=d["summary"]["evidence_classification"],
        reviewed_patient=True,
        reviewed_result=True,
        reviewed_evidence_limits=True,
        confirm_review_completion=True,
    )


def ready_ledger(s, c, tmp_path):
    initial, admission = admitted(s, {**c, "owner": c["actor"]})
    store = LocalVendorArtifactStore(tmp_path / ("membership-proof-" + str(uuid4())))
    assert vendor_artifacts.write_content(store, claim(admission), PDF) == "ready"
    settle(s, admission, "ready")
    a = s.get(VendorArtifact, initial["effect"]["artifact_id"])
    return {
        "source_label": "Invented practice membership ledger",
        "system_kind": "practice_owned_ledger",
        "record_reference": "invented-member-001",
        "observed_at": public.timestamp(datetime.now(UTC)),
        "document": {
            "artifact_id": a.artifact_id,
            "sha256": a.sha256,
            "byte_length": a.byte_length,
            "media_type": a.media_type,
        },
        "observed_membership_state": "pending_enrollment",
        "observed_billing_state": "unknown",
        "reviewed_record_matches_patient": True,
        "reviewed_document": True,
    }


@pytest.mark.parametrize(
    "purpose", ["enrollment_assistance", "membership_status_review", "failed_payment_follow_up"]
)
def test_local_review_closes_only_as_unreconciled_without_operation(session, vendor_case, purpose):
    c = vendor_case
    tid = created(session, c, purpose=purpose)
    result(session, c, tid)
    request = verification(session, c, tid)
    receipt = call(session, c, flow.command, tid, "verify", request)
    assert call(session, c, flow.command, tid, "verify", request, policy=OFF) == receipt
    immediate(session)
    d = detail(session, c, tid)
    assert d["summary"]["state"] == "closed"
    assert d["summary"]["evidence_classification"] == "local_unreconciled"
    assert d["summary"]["membership_authority"] == "not_established"
    assert d["summary"]["external_service_verified"] is False
    assert session.scalar(select(Operation.id).where(Operation.ticket_id == tid)) is None
    assert len(call(session, c, flow.history, tid)["items"]) == 4


def test_named_artifact_is_manual_evidence_not_service_acceptance(session, vendor_case, tmp_path):
    c = vendor_case
    tid = created(session, c)
    ledger = ready_ledger(session, c, tmp_path)
    result(session, c, tid, disposition="record_reviewed", ledger=ledger)
    request = verification(session, c, tid)
    call(session, c, flow.command, tid, "verify", request)
    immediate(session)
    d = detail(session, c, tid)
    assert d["summary"]["evidence_classification"] == "manual_ledger_record"
    assert d["summary"]["external_service_verified"] is False
    assert d["latest_result"]["request"]["ledger"] == ledger
    assert call(session, c, flow.options)["installed_membership_service"] == "not_selected"
    (tmp_path / "actual-membership-manual-evidence.json").write_text(
        json.dumps(
            {
                "detail": d,
                "verify_request": request.public(),
                "history": call(session, c, flow.history, tid),
            },
            indent=2,
        )
    )


def test_quarantined_evidence_blocks_later_verification(session, vendor_case, tmp_path):
    c = vendor_case
    tid = created(session, c)
    ledger = ready_ledger(session, c, tmp_path)
    result(session, c, tid, disposition="record_reviewed", ledger=ledger)
    request = verification(session, c, tid)
    a = session.get(VendorArtifact, ledger["document"]["artifact_id"])
    a.state, a.version = "quarantined", a.version + 1
    session.commit()
    assert detail(session, c, tid)["summary"]["evidence_current"] == "changed"
    assert detail(session, c, tid)["summary"]["can_verify"] is False
    with pytest.raises(ws.WorkspaceError, match="membership_evidence_changed"):
        call(session, c, flow.command, tid, "verify", request)


def test_needs_human_cannot_close_and_replaced_result_stales_old_verification(session, vendor_case):
    c = vendor_case
    tid = created(session, c)
    result(session, c, tid, disposition="needs_human")
    assert detail(session, c, tid)["summary"]["can_verify"] is False
    old = verification(session, c, tid)
    with pytest.raises(ws.WorkspaceError, match="membership_exception_unresolved"):
        call(session, c, flow.command, tid, "verify", old)
    result(session, c, tid)
    with pytest.raises(ws.WorkspaceError, match="membership_revision_changed"):
        call(session, c, flow.command, tid, "verify", old)
    call(session, c, flow.command, tid, "verify", verification(session, c, tid))


def test_exact_proposal_replay_disabled_and_changed_body_conflict(session, vendor_case):
    c = vendor_case
    request = proposal(session, c)
    original = call(session, c, flow.propose, request)
    assert call(session, c, flow.propose, request, policy=OFF) == original
    assert (
        call(
            session,
            c,
            flow.resolve,
            p.Resolve(
                command_kind="propose",
                idempotency_key=request.idempotency_key,
                request_sha256=original["request_sha256"],
            ),
            policy=OFF,
        )
        == original
    )
    changed = p.Proposal.model_validate(request.public() | {"instructions": "Changed exact body"})
    with pytest.raises(ws.WorkspaceError, match="membership_idempotency_conflict"):
        call(session, c, flow.propose, changed)
    with pytest.raises(ws.WorkspaceError, match="membership_work_unavailable"):
        call(session, c, flow.catalog, policy=flow.DEFAULT_POLICY)


@pytest.mark.parametrize("changed", ["source", "owner", "patient"])
def test_changed_authority_or_source_denies_new_result(session, vendor_case, changed):
    c = vendor_case
    tid = created(session, c)
    d = detail(session, c, tid)
    request = p.Result(
        **bound(d), disposition="local_preparation_ready", evidence="Invented result"
    )
    if changed == "source":
        w = session.get(EncounterWorkspace, c["wid"])
        w.revision += 1
    elif changed == "owner":
        session.get(Principal, c["actor"]).state = "disabled"
    else:
        from cosmas_os.models import PatientLink

        session.get(
            PatientLink, session.get(EncounterWorkspace, c["wid"]).patient_link_id
        ).state = "ambiguous"
    session.flush()
    if changed == "source":
        assert detail(session, c, tid)["summary"]["source_current"] is False
        assert detail(session, c, tid)["summary"]["can_verify"] is False
    with pytest.raises(ws.WorkspaceError):
        call(session, c, flow.command, tid, "result", request)
    assert (
        session.scalar(
            select(func.count())
            .select_from(MembershipReceipt)
            .where(MembershipReceipt.ticket_id == tid)
        )
        == 2
    )


def test_only_verified_finance_review_can_support_manual_ledger_record(
    session, vendor_case, tmp_path
):
    from tests.integration import test_finance_work as financial

    from cosmas_os.api import finance_work_schemas as fp
    from cosmas_os.application import finance_execution, finance_work

    c = vendor_case
    factory = getattr(financial.finance_case, "__wrapped__", None)
    assert callable(factory)
    fc = factory(session, c)
    ftid, _, fd = financial.approved(session, fc)
    dispatch, invocation = financial.call(
        session,
        fc,
        finance_execution.claim_submit,
        ftid,
        public.BoundCommand(**financial.bound(fd)),
        policy=financial.POLICY,
    )
    finance_execution.mark_invocation(session, invocation)
    finance_execution.settle(
        session, invocation, observation=financial.created_observation(invocation)
    )
    tid = created(session, c)
    ledger = ready_ledger(session, c, tmp_path)
    fd = financial.call(session, fc, finance_work.detail, ftid)
    ledger["finance"] = {
        "ticket_id": ftid,
        "verification_receipt_id": dispatch["effect"]["receipt_id"],
        "verification_receipt_sha256": dispatch["receipt_sha256"],
        "evidence_sha256": fd["summary"]["evidence_sha256"],
    }
    with pytest.raises(ws.WorkspaceError, match="membership_evidence_changed"):
        result(session, c, tid, disposition="record_reviewed", ledger=ledger)
    _, read = financial.call(
        session,
        fc,
        finance_execution.claim_read,
        ftid,
        public.BoundCommand(**financial.bound(fd)),
        policy=financial.POLICY,
    )
    finance_execution.settle(session, read, observation=financial.payment(read))
    fd = financial.call(session, fc, finance_work.detail, ftid)
    human = financial.call(
        session,
        fc,
        finance_work.record_result,
        ftid,
        fp.FinanceResult(
            **financial.bound(fd),
            observation_head=fd["summary"]["observation_head"],
            evidence_sha256=fd["summary"]["evidence_sha256"],
            disposition="reported_paid",
            evidence="Invented owner review of observed full payment.",
        ),
    )
    fd = financial.call(session, fc, finance_work.detail, ftid)
    verified = financial.call(
        session,
        fc,
        finance_work.verify,
        ftid,
        fp.FinanceVerify(
            **financial.bound(fd),
            result_receipt_id=human["effect"]["receipt_id"],
            result_receipt_sha256=human["receipt_sha256"],
            observation_head=fd["summary"]["observation_head"],
            evidence_sha256=fd["summary"]["evidence_sha256"],
            reviewed_result=True,
            reviewed_observations=True,
            outcome_confirmed=True,
            reviewed_conflicting_evidence=False,
        ),
    )
    ledger["finance"] = {
        "ticket_id": ftid,
        "verification_receipt_id": verified["effect"]["receipt_id"],
        "verification_receipt_sha256": verified["receipt_sha256"],
        "evidence_sha256": fd["summary"]["evidence_sha256"],
    }
    result(session, c, tid, disposition="record_reviewed", ledger=ledger)
    assert (
        detail(session, c, tid)["summary"]["evidence_classification"]
        == "manual_ledger_and_finance_review"
    )
    assert detail(session, c, tid)["summary"]["external_service_verified"] is False
    request = verification(session, c, tid)
    fd = financial.call(session, fc, finance_work.detail, ftid)
    _, read = financial.call(
        session,
        fc,
        finance_execution.claim_read,
        ftid,
        public.BoundCommand(**financial.bound(fd)),
        policy=financial.POLICY,
    )
    finance_execution.settle(session, read, observation=financial.payment(read, "canceled"))
    immediate(session)
    assert detail(session, c, tid)["summary"]["can_verify"] is False
    with pytest.raises(ws.WorkspaceError, match="membership_evidence_changed"):
        call(session, c, flow.command, tid, "verify", request)


def test_sql_cannot_promote_local_result_to_manual_or_service_evidence(session, vendor_case):
    c = vendor_case
    tid = created(session, c)
    result(session, c, tid)
    request = p.Verify.model_validate(
        verification(session, c, tid).public() | {"evidence_classification": "manual_ledger_record"}
    )
    with pytest.raises(DBAPIError), session.begin_nested():
        w = flow.owner(session, c["box"], c["actor"], c["wid"], policy=POLICY, writing=True)
        t, r = flow.bound(session, w, tid)
        _, digest = flow.saved(session, w, "verify", request)
        t.state, t.closed_at, t.version = "closed", flow.common._clock(session), t.version + 1
        flow.record(
            session,
            w,
            t,
            r,
            "verify",
            request,
            digest,
            "review_verified",
            result=flow.latest_result(session, tid),
        )
    assert detail(session, c, tid)["summary"]["state"] == "approved"


def test_other_owner_cannot_read_receipts_or_link_scope(session, vendor_case):
    c = vendor_case
    req = proposal(session, c)
    receipt = call(session, c, flow.propose, req)
    other = Principal(
        box_id=c["box"],
        principal_type="human",
        display_name="Invented membership colleague",
        state="active",
        is_owner=True,
    )
    session.add(other)
    session.flush()
    for method, args in [
        (flow.catalog, ()),
        (flow.detail, (receipt["effect"]["ticket_id"],)),
        (
            flow.resolve,
            (
                p.Resolve(
                    command_kind="propose",
                    idempotency_key=req.idempotency_key,
                    request_sha256=receipt["request_sha256"],
                ),
            ),
        ),
    ]:
        with pytest.raises(ws.WorkspaceError, match="membership_work_unavailable"):
            method(session, c["box"], other.id, c["wid"], *args, policy=POLICY)


@pytest.mark.parametrize("mutation", ["disabled_withdrawal", "extra_decision"])
def test_sql_cannot_add_commands_without_current_human_or_receipt(session, vendor_case, mutation):
    from cosmas_os.models import Decision

    c = vendor_case
    tid = created(session, c)
    d = detail(session, c, tid)
    request = p.Withdraw(**bound(d), confirm_withdraw=True)
    with pytest.raises(DBAPIError), session.begin_nested():
        if mutation == "extra_decision":
            session.add(Decision(box_id=c["box"], ticket_id=tid, action_revision_id=d["summary"]["revision_id"], actor_principal_id=c["actor"], kind="approve"))
            session.flush()
        else:
            w = flow.owner(session, c["box"], c["actor"], c["wid"], policy=POLICY, writing=True)
            t, r = flow.bound(session, w, tid)
            _, digest = flow.saved(session, w, "withdraw", request)
            session.get(Principal, c["actor"]).state = "disabled"
            t.state, t.version = "withdrawn", t.version + 1
            flow.record(session, w, t, r, "withdraw", request, digest, "withdrawn")
        immediate(session)


@pytest.mark.parametrize("mutation", ["ticket", "operation", "action", "receipt"])
def test_direct_sql_cannot_bypass_review_or_create_executable_work(session, vendor_case, mutation):
    tid = created(session, vendor_case)
    r = session.get(MembershipWork, tid)
    with pytest.raises(DBAPIError), session.begin_nested():
        if mutation == "ticket":
            session.execute(
                text(
                    "UPDATE tickets SET state='closed',version=version+1,closed_at=clock_timestamp() WHERE id=:id"
                ),
                {"id": tid},
            )
            immediate(session)
        elif mutation == "operation":
            session.add(
                Operation(
                    id=str(uuid4()),
                    box_id=r.box_id,
                    ticket_id=tid,
                    action_revision_id=r.revision_id,
                    idempotency_key="forbidden-" + str(uuid4()),
                    adapter="notify",
                    status="pending",
                )
            )
            session.flush()
        elif mutation == "action":
            session.execute(
                text("UPDATE action_revisions SET content='not private' WHERE id=:id"),
                {"id": r.revision_id},
            )
        else:
            session.execute(
                text("DELETE FROM membership_receipts WHERE ticket_id=:id"), {"id": tid}
            )


def test_final_authority_loss_rolls_back_admission(session, vendor_case):
    c = vendor_case
    request = proposal(session, c)

    def lost():
        raise ws.WorkspaceError("membership_work_unavailable", 403)

    session.info["membership_final_authority"] = lost
    try:
        with pytest.raises(ws.WorkspaceError), session.begin_nested():
            call(session, c, flow.propose, request)
    finally:
        session.info.pop("membership_final_authority")
    assert (
        session.scalar(
            select(MembershipReceipt.id).where(
                MembershipReceipt.idempotency_key == request.idempotency_key
            )
        )
        is None
    )


def test_concurrent_exact_admission_creates_one_private_ticket(engine, tmp_path):
    with Session(engine, expire_on_commit=False) as s:
        seed = services.provision_box(
            services.Container(s, blob=LocalBlobAdapter(tmp_path / "seed")),
            "Invented membership concurrency",
        )
        factory = getattr(vendor_case, "__wrapped__", None)
        assert callable(factory)
        c = factory(s, seed)
        assert isinstance(c, dict)
        request = proposal(s, c)
        s.commit()

    def propose():
        with Session(engine, expire_on_commit=False) as s:
            return call(s, c, flow.propose, request)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(lambda _: propose(), range(2)))
    assert first == second
    with Session(engine) as s:
        assert (
            s.scalar(
                select(func.count())
                .select_from(MembershipWork)
                .where(MembershipWork.workspace_id == c["wid"])
            )
            == 1
        )


@pytest.fixture
def client(session, vendor_case):
    c = vendor_case
    app = FastAPI()
    identity = RequestIdentity(box_id=c["box"], principal_id=c["actor"], auth_mode="synth_headers")
    routes.register(
        app,
        lambda: session,
        lambda: identity,
        policy_dependency=lambda: POLICY,
        reauthenticate=lambda *args: None,
    )
    with TestClient(app) as client:
        client.headers["X-Cosmas-Membership-Contract"] = "1"
        yield client


def test_http_exact_recovery_views_and_closed_contract(client, session, vendor_case, tmp_path):
    c = vendor_case
    root = f"/workspaces/{c['wid']}/membership-work"
    options = client.get(root + "/options")
    assert options.status_code == 200 and options.headers["cache-control"] == "no-store"
    request = proposal(session, c)
    first = client.post(root, json=request.public())
    assert first.status_code == 200, first.text
    receipt = first.json()
    assert client.post(root, json=request.public()).json() == receipt
    assert (
        client.post(
            root + "/resolve",
            json={
                "command_kind": "propose",
                "idempotency_key": request.idempotency_key,
                "request_sha256": receipt["request_sha256"],
            },
        ).json()
        == receipt
    )
    tid = receipt["effect"]["ticket_id"]
    assert client.get(root + "/" + tid).status_code == 200
    assert client.get(root + "/" + tid + "/history").status_code == 200
    assert client.get(root + "?extra=1").status_code == 426
    assert client.get(root, headers={"X-Cosmas-Membership-Contract": "2"}).status_code == 426
    assert client.post(root, json=request.public() | {"charge": True}).status_code == 400
    assert (
        client.post(
            root, content=b"x" * 8193, headers={"Content-Type": "application/json"}
        ).status_code
        == 413
    )
    (tmp_path / "actual-membership-http.json").write_text(
        json.dumps(
            {
                "options": options.json(),
                "proposal_request": request.public(),
                "receipt": receipt,
                "detail": client.get(root + "/" + tid).json(),
            },
            indent=2,
        )
    )
