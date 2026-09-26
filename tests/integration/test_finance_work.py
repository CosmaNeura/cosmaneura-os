"""Financial request custody on real PostgreSQL; all identifiers are invented."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from tests.integration.test_vendor_work import gates  # noqa: F401
from tests.integration.test_vendor_work import vendor_case as vendor_case

from cosmas_os.api import finance_work_schemas as schema
from cosmas_os.api import vendor_work_schemas as public
from cosmas_os.application import finance_execution as execution
from cosmas_os.application import finance_setup as setup
from cosmas_os.application import finance_work as work
from cosmas_os.application import workspace as ws
from cosmas_os.finance_models import FinanceObservation, FinanceReceipt, FinanceSubmitClaim
from cosmas_os.models import ActionRevision, EncounterWorkspace, Operation
from cosmas_os.ports import vendor_connectors as private

POLICY = work.FinancePolicy(enabled=True, io_enabled=True, events_enabled=True)


@pytest.fixture
def finance_case(session, vendor_case):
    c = vendor_case
    selection = private.ConnectionSelection(
        vendor="stripe",
        connection_id=uuid4(),
        box_id=c["box"],
        owner_id=c["actor"],
        environment="sandbox",
        remote_account_id="acct_Invented",
        credential_ref=uuid4(),
        configuration_sha256="a" * 64,
    )
    cv = setup.review_connection(
        session,
        c["box"],
        c["actor"],
        selection,
        label="Invented Stripe sandbox",
        write_enabled=True,
        read_enabled=True,
    )
    w = session.get(EncounterWorkspace, c["wid"])
    mv = setup.review_customer(
        session,
        c["box"],
        c["actor"],
        cv["id"],
        w.patient_link_id,
        "cus_Invented",
        label="Invented patient billing account",
    )
    return {**c, "finance_connection": cv, "customer": mv, "private_selection": selection}


def proposal(c, **extra):
    return schema.FinanceProposal.model_validate(
        {
            "expected_workspace_revision": 3,
            "idempotency_key": "finance-proposal-" + str(uuid4()),
            "proposed_operation_id": str(uuid4()),
            "source": c["source"],
            "connection": {
                k: c["finance_connection"][k] for k in ("id", "revision", "public_sha256")
            },
            "customer": {k: c["customer"][k] for k in ("id", "revision", "public_sha256")},
            "amount": 12500,
            "currency": "usd",
            "due_date": "2026-10-01",
            "expected_outcome": "Invented patient completes the reviewed payment request.",
            **extra,
        }
    )


def call(s, c, fn, *args, **kwargs):
    return fn(s, c["box"], c["actor"], c["wid"], *args, **kwargs)


def bound(detail, **extra):
    x = detail["summary"]
    return {
        "expected_version": x["version"],
        "revision_id": x["revision_id"],
        "operation_id": x["operation_id"],
        "payload_hash": x["payload_hash"],
        "idempotency_key": "finance-command-" + str(uuid4()),
        **extra,
    }


def approved(s, c):
    created = call(s, c, work.propose, proposal(c), policy=POLICY)
    tid = created["effect"]["ticket_id"]
    d = call(s, c, work.detail, tid)
    saved = call(
        s,
        c,
        work.decide,
        tid,
        schema.FinanceDecision(**bound(d, review_sha256=d["review_sha256"], choice="approve")),
        policy=POLICY,
    )
    return tid, saved, call(s, c, work.detail, tid)


def created_observation(invocation):
    command = invocation.command
    reference = private.ProviderReference(
        vendor="stripe",
        connection_id=command.selection.connection_id,
        environment="sandbox",
        selection_sha256=command.selection.commitment(),
        operation_id=command.operation_id,
        request_sha256=command.commitment(),
        kind="payment_intent",
        value="pi_Invented",
        observed_at=datetime.now(UTC),
    )
    return private.SubmissionObservation(
        vendor="stripe",
        connection_id=command.selection.connection_id,
        operation_id=command.operation_id,
        request_sha256=command.commitment(),
        observed_at=datetime.now(UTC),
        state="accepted",
        reference=reference,
        safe_error=None,
        response_sha256="b" * 64,
    )


def payment(read, state="succeeded"):
    return private.PaymentObservation(
        reference=read.reference,
        observed_at=datetime.now(UTC),
        state=state,
        amount=12500,
        currency="usd",
        amount_received=12500 if state == "succeeded" else 0,
        livemode=False,
        response_sha256="c" * 64,
    )


def test_finance_approval_is_local_and_preserves_private_f8_envelope(session, finance_case):
    c = finance_case
    tid, _, d = approved(session, c)
    session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    assert (
        d["summary"]["creation"] == "not_observed"
        and d["summary"]["payment_state"] == "not_observed"
    )
    assert d["review"]["processor_confirmation"] == "not_requested"
    assert session.get(EncounterWorkspace, c["wid"]).revision == 3
    assert session.get(FinanceSubmitClaim, d["summary"]["operation_id"]) is None
    assert session.get(Operation, d["summary"]["operation_id"]).attempt_count == 0
    action = session.get(ActionRevision, d["summary"]["revision_id"])
    assert (
        action.content == work.CONTENT
        and "cus_Invented" not in str(action.payload)
        and "12500" not in str(action.payload)
    )
    assert "cus_Invented" not in str(d) and str(c["private_selection"].credential_ref) not in str(d)


def test_finance_default_off_but_recorded_commands_remain_recoverable(session, finance_case):
    c = finance_case
    request = proposal(c)
    with pytest.raises(ws.WorkspaceError, match="finance_feature_disabled"):
        call(session, c, work.propose, request)
    session.rollback()
    saved = call(session, c, work.propose, request, policy=POLICY)
    replay = call(session, c, work.propose, request)
    assert replay["effect"] == saved["effect"]
    resolved = call(
        session,
        c,
        work.resolve,
        schema.FinanceResolve(
            command_kind="propose",
            idempotency_key=request.idempotency_key,
            request_sha256=saved["request_sha256"],
        ),
    )
    assert resolved["effect"] == saved["effect"]


def test_finance_submit_is_claimed_once_and_creation_does_not_prove_paid(session, finance_case):
    c = finance_case
    tid, _, d = approved(session, c)
    command = public.BoundCommand(**bound(d))
    receipt, invocation = call(session, c, execution.claim_submit, tid, command, policy=POLICY)
    again, none = call(session, c, execution.claim_submit, tid, command, policy=POLICY)
    assert none is None and again["effect"] == receipt["effect"]
    execution.mark_invocation(session, invocation)
    execution.settle(session, invocation, observation=created_observation(invocation))
    d = call(session, c, work.detail, tid)
    assert (
        d["summary"]["creation"] == "accepted"
        and d["summary"]["payment_state"] == "not_observed"
        and d["summary"]["state"] == "approved"
    )
    with pytest.raises(ws.WorkspaceError, match="finance_submit_already_claimed"):
        call(
            session, c, execution.claim_submit, tid, public.BoundCommand(**bound(d)), policy=POLICY
        )


def test_finance_status_paid_requires_human_result_then_exact_verification(session, finance_case):
    c = finance_case
    tid, _, d = approved(session, c)
    _, invocation = call(
        session, c, execution.claim_submit, tid, public.BoundCommand(**bound(d)), policy=POLICY
    )
    execution.mark_invocation(session, invocation)
    execution.settle(session, invocation, observation=created_observation(invocation))
    d = call(session, c, work.detail, tid)
    _, read = call(
        session, c, execution.claim_read, tid, public.BoundCommand(**bound(d)), policy=POLICY
    )
    execution.settle(session, read, observation=payment(read))
    d = call(session, c, work.detail, tid)
    assert d["summary"]["payment_state"] == "succeeded" and d["summary"]["state"] == "approved"
    result = call(
        session,
        c,
        work.record_result,
        tid,
        schema.FinanceResult(
            **bound(
                d,
                observation_head=d["summary"]["observation_head"],
                evidence_sha256=d["summary"]["evidence_sha256"],
                disposition="reported_paid",
                evidence="Invented owner matched the completed payment to this request.",
            )
        ),
    )
    d = call(session, c, work.detail, tid)
    request = schema.FinanceVerify(
        **bound(
            d,
            result_receipt_id=result["effect"]["receipt_id"],
            result_receipt_sha256=result["receipt_sha256"],
            observation_head=d["summary"]["observation_head"],
            evidence_sha256=d["summary"]["evidence_sha256"],
            reviewed_result=True,
            reviewed_observations=True,
            outcome_confirmed=True,
            reviewed_conflicting_evidence=False,
        )
    )
    call(session, c, work.verify, tid, request)
    assert call(session, c, work.detail, tid)["summary"]["verification"] == "verified"
    d = call(session, c, work.detail, tid)
    _, contradiction = call(
        session, c, execution.claim_read, tid, public.BoundCommand(**bound(d)), policy=POLICY
    )
    execution.settle(session, contradiction, observation=payment(contradiction, "canceled"))
    session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    reopened = call(session, c, work.detail, tid)
    assert (
        reopened["summary"]["state"] == "approved" and reopened["summary"]["conflicting_evidence"]
    )


def test_finance_spent_claim_cannot_be_reset_or_closed_directly(session, finance_case):
    c = finance_case
    tid, _, d = approved(session, c)
    _, invocation = call(
        session, c, execution.claim_submit, tid, public.BoundCommand(**bound(d)), policy=POLICY
    )
    with session.begin_nested() as transaction:
        with pytest.raises(DBAPIError):
            session.execute(
                text("DELETE FROM finance_submit_claims WHERE operation_id=:id"),
                {"id": invocation.operation_id},
            )
        transaction.rollback()
    with session.begin_nested() as transaction:
        with pytest.raises(DBAPIError):
            session.execute(text("UPDATE tickets SET state='closed' WHERE id=:id"), {"id": tid})
            session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        transaction.rollback()
    assert (
        session.scalar(
            select(func.count()).select_from(FinanceReceipt).where(FinanceReceipt.ticket_id == tid)
        )
        == 3
    )
    assert (
        session.scalar(
            select(func.count())
            .select_from(FinanceObservation)
            .where(FinanceObservation.ticket_id == tid)
        )
        == 0
    )


def test_finance_is_excluded_from_generic_queue_audit_and_legacy_edit(session, finance_case):
    from cosmas_os.application import services
    from cosmas_os.domain.rules import AuthorizationError

    c = finance_case
    tid, _, d = approved(session, c)
    container = services.Container(session)
    assert tid not in {row["id"] for row in services.list_queue(container, c["box"])}
    for action in [
        lambda: services.audit_timeline(container, c["box"], tid),
        lambda: services.edit_revision(container, tid, c["actor"], "Forbidden generic edit"),
        lambda: services.decide(container, tid, c["actor"], "approve"),
    ]:
        with pytest.raises(AuthorizationError):
            action()
    assert call(session, c, work.detail, tid)["summary"] == d["summary"]


def test_other_provider_cannot_discover_or_link_private_financial_work(session, finance_case):
    from cosmas_os.models import Principal

    c = finance_case
    tid, _, _ = approved(session, c)
    original = session.get(EncounterWorkspace, c["wid"])
    other = Principal(
        box_id=c["box"],
        principal_type="human",
        display_name="Invented colleague",
        state="active",
        is_owner=True,
    )
    session.add(other)
    session.commit()
    theirs = ws.create(
        session, c["box"], other.id, original.appointment_id, "finance-colleague-" + str(uuid4())
    )
    assert tid not in {row["id"] for row in theirs["work_candidates"]}
    with pytest.raises(ws.WorkspaceError, match="work_unavailable"):
        ws.append(
            session,
            c["box"],
            other.id,
            theirs["id"],
            expected=1,
            key="forbidden-finance-link",
            kind="work_link",
            ticket_id=tid,
        )
    with pytest.raises(ws.WorkspaceError, match="finance_work_unavailable"):
        work.detail(session, c["box"], other.id, c["wid"], tid)
