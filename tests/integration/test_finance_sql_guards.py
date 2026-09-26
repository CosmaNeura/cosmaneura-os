"""Adversarial direct PostgreSQL writes cannot substitute financial evidence."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import insert, text
from sqlalchemy.exc import DBAPIError
from tests.integration.test_finance_work import POLICY, approved, bound, call, created_observation
from tests.integration.test_finance_work import finance_case as finance_case
from tests.integration.test_vendor_work import gates, vendor_case  # noqa: F401

from cosmas_os.api import finance_work_schemas as schema
from cosmas_os.api import vendor_work_schemas as public
from cosmas_os.application import finance_execution as execution
from cosmas_os.application import finance_work as work
from cosmas_os.finance_models import (
    FinanceConnectionVersion,
    FinanceCustomerVersion,
    FinanceObservation,
    FinanceReadClaim,
    FinanceSubmitClaim,
    FinanceWorkRevision,
)


def immediate(s):
    s.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    s.execute(text("SET CONSTRAINTS ALL DEFERRED"))


def rejected(s, action, *, reason=None, sqlstate="23514"):
    with s.begin_nested() as transaction:
        with pytest.raises(DBAPIError) as caught:
            action()
            immediate(s)
        assert caught.value.orig.sqlstate == sqlstate
        if reason:
            assert reason in str(caught.value.orig)
        transaction.rollback()


def copy_row(row):
    return {column.name: deepcopy(getattr(row, column.name)) for column in row.__table__.columns}


def reading(s, c):
    tid, _, d = approved(s, c)
    _, invocation = call(
        s, c, execution.claim_submit, tid, public.BoundCommand(**bound(d)), policy=POLICY
    )
    execution.mark_invocation(s, invocation)
    execution.settle(s, invocation, observation=created_observation(invocation))
    d = call(s, c, work.detail, tid)
    _, read = call(s, c, execution.claim_read, tid, public.BoundCommand(**bound(d)), policy=POLICY)
    immediate(s)
    return tid, read


def raw_payment(s, read, state="succeeded"):
    r = s.get(FinanceWorkRevision, str(read.command.revision_id))
    h = work.head(s, r)
    oid = str(uuid4())
    now = datetime.now(UTC)
    value = {
        "id": oid,
        "sequence": h["sequence"] + 1,
        "operation_id": read.operation_id,
        "kind": "payment",
        "recorded_at": public.timestamp(now),
        "payment_state": state,
        "amount": r.amount,
        "currency": "usd",
        "amount_received": r.amount if state == "succeeded" else 0,
        "livemode": False,
    }
    return {
        "id": oid,
        "operation_id": read.operation_id,
        "action_revision_id": r.action_revision_id,
        "ticket_id": r.ticket_id,
        "box_id": r.box_id,
        "owner_id": r.owner_id,
        "workspace_id": r.workspace_id,
        "sequence": value["sequence"],
        "kind": "payment",
        "read_claim_id": read.claim_id,
        "submit_claim_id": None,
        "private_reference": read.reference.model_dump(mode="json"),
        "recorded_at": now,
        "public_observation": value,
    }, h


def rehash(row, h):
    value = {k: v for k, v in row["public_observation"].items() if k != "sha256"}
    sha = public.public_digest("cosmas-finance-public-observation.v1", value)
    row["public_observation"] = {**value, "sha256": sha}
    row["public_sha256"] = sha
    row["head_sha256"] = public.public_digest(
        "cosmas-finance-observation-head.v1",
        {
            "operation_id": row["operation_id"],
            "sequence": row["sequence"],
            "previous_sha256": h["sha256"],
            "observation_sha256": sha,
        },
    )


@pytest.mark.parametrize(
    "corruption",
    [
        "skipped_sequence",
        "wrong_operation",
        "underpaid_success",
        "overpaid",
        "wrong_environment",
        "private_field",
        "wrong_reference",
        "submit_as_payment",
        "changed_clock",
    ],
)
def test_rehashed_invalid_financial_observation_is_rejected(session, finance_case, corruption):
    _, read = reading(session, finance_case)
    row, h = raw_payment(session, read)
    v = row["public_observation"]
    if corruption == "skipped_sequence":
        row["sequence"] += 1
        v["sequence"] += 1
    elif corruption == "wrong_operation":
        v["operation_id"] = str(uuid4())
    elif corruption == "underpaid_success":
        v["amount_received"] -= 1
    elif corruption == "overpaid":
        v["amount_received"] += 1
    elif corruption == "wrong_environment":
        v["livemode"] = True
    elif corruption == "private_field":
        v["client_secret"] = "forbidden-invented-secret"
    elif corruption == "wrong_reference":
        row["private_reference"]["value"] = "pi_Unrelated"
    elif corruption == "submit_as_payment":
        row["read_claim_id"] = None
        row["submit_claim_id"] = read.operation_id
    elif corruption == "changed_clock":
        v["recorded_at"] = public.timestamp(datetime.now(UTC) + timedelta(days=1))
    rehash(row, h)
    rejected(
        session,
        lambda: session.execute(insert(FinanceObservation).values(**row)),
        reason="finance observation binding mismatch",
    )


@pytest.mark.parametrize(
    "corruption",
    [
        "other_pi",
        "other_account",
        "wrong_request",
        "wrong_deadline",
        "approval_receipt",
        "same_receipt",
    ],
)
def test_read_claim_cannot_substitute_reference_or_approval(session, finance_case, corruption):
    _, read = reading(session, finance_case)
    claim = session.get(FinanceReadClaim, read.claim_id)
    row = copy_row(claim)
    row["id"], row["claim_token"] = str(uuid4()), str(uuid4())
    if corruption == "other_pi":
        row["private_reference"]["value"] = "pi_Unrelated"
    elif corruption == "other_account":
        row["private_reference"]["connection_id"] = str(uuid4())
    elif corruption == "wrong_request":
        row["private_reference"]["request_sha256"] = "0" * 64
    elif corruption == "wrong_deadline":
        row["deadline"] += timedelta(seconds=1)
    elif corruption == "approval_receipt":
        row["command_receipt_id"] = session.get(
            FinanceSubmitClaim, read.operation_id
        ).approval_receipt_id
    rejected(
        session,
        lambda: session.execute(insert(FinanceReadClaim).values(**row)),
        reason="finance read requires original accepted reference",
    )


@pytest.mark.parametrize(
    "kind", ["account_owner", "account_commitment", "customer_mapping", "customer_public"]
)
def test_setup_admission_rejects_rehashed_wrong_account_and_mapping(session, finance_case, kind):
    if kind.startswith("account"):
        model = FinanceConnectionVersion
        old = session.get(model, finance_case["finance_connection"]["id"])
    else:
        model = FinanceCustomerVersion
        old = session.get(model, finance_case["customer"]["id"])
    immediate(session)
    row = copy_row(old)
    row["id"], row["family_id"] = str(uuid4()), str(uuid4())
    row["public_view"]["id"] = row["id"]
    if kind.startswith("account"):
        row["private_selection"]["connection_id"] = row["id"]
        if kind == "account_owner":
            row["private_selection"]["owner_id"] = str(uuid4())
        row["private_sha256"] = public.public_digest(
            "cosmas-vendor-selection.v1", row["private_selection"]
        )
        if kind == "account_commitment":
            row["private_sha256"] = "0" * 64
    elif kind == "customer_mapping":
        row["customer_id"] = "cus_Unrelated"
    elif kind == "customer_public":
        row["public_view"]["connection_id"] = str(uuid4())
    row["public_sha256"] = public.public_digest(
        "cosmas-finance-public-selection.v1",
        {k: v for k, v in row["public_view"].items() if k != "public_sha256"},
    )
    row["public_view"]["public_sha256"] = row["public_sha256"]
    rejected(session, lambda: session.execute(insert(model).values(**row)), reason="finance setup")


def manually_verified(s, c):
    tid, read = reading(s, c)
    execution.settle(s, read, failure=None)
    d = call(s, c, work.detail, tid)
    result = call(
        s,
        c,
        work.record_result,
        tid,
        schema.FinanceResult(
            **bound(
                d,
                observation_head=d["summary"]["observation_head"],
                evidence_sha256=d["summary"]["evidence_sha256"],
                disposition="verified_in_processor",
                evidence="Invented owner checked the account independently.",
            )
        ),
    )
    d = call(s, c, work.detail, tid)
    call(
        s,
        c,
        work.verify,
        tid,
        schema.FinanceVerify(
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
        ),
    )
    immediate(s)
    return tid


def test_direct_new_contradiction_cannot_leave_verified_financial_work_closed(
    session, finance_case
):
    c = finance_case
    tid = manually_verified(session, c)
    d = call(session, c, work.detail, tid)
    _, read = call(
        session, c, execution.claim_read, tid, public.BoundCommand(**bound(d)), policy=POLICY
    )
    row, h = raw_payment(session, read, "canceled")
    rehash(row, h)
    rejected(
        session,
        lambda: session.execute(insert(FinanceObservation).values(**row)),
        reason="contradictory evidence requires reopen",
    )


def test_unknown_status_after_manual_verification_does_not_erase_verified_outcome(
    session, finance_case
):
    c = finance_case
    tid = manually_verified(session, c)
    d = call(session, c, work.detail, tid)
    _, read = call(
        session, c, execution.claim_read, tid, public.BoundCommand(**bound(d)), policy=POLICY
    )
    row, h = raw_payment(session, read, "unknown")
    rehash(row, h)
    session.execute(insert(FinanceObservation).values(**row))
    immediate(session)
    assert call(session, c, work.detail, tid)["summary"]["state"] == "closed"
