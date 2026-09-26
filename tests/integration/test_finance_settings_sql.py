"""Direct SQL cannot forge settings consent, replay scope or managed native state."""

from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import insert, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from tests.integration.test_finance_settings import POLICY, account, activation, call, detail
from tests.integration.test_finance_settings import case as case
from tests.integration.test_vendor_work import gates as gates
from tests.integration.test_vendor_work import immediate
from tests.integration.test_vendor_work import vendor_case as vendor_case

from cosmas_os.api.vendor_work_schemas import public_digest
from cosmas_os.application import finance_settings as flow
from cosmas_os.application import finance_setup
from cosmas_os.finance_setup_models import FinanceSetupReceipt


@pytest.mark.parametrize(
    "wrong",
    ["false_attestation", "unknown_request", "wrong_digest", "late_version", "wrong_effect"],
)
def test_rehashed_direct_sql_settings_receipt_cannot_bypass_exact_review(session, case, wrong):
    c = case
    saved = call(
        session,
        c,
        flow.propose,
        "propose_account",
        c["account_request"],
        c["installed"],
        policy=POLICY,
    )
    d = detail(session, c, c["account_request"].setup_id)
    immediate(session)
    original = session.get(FinanceSetupReceipt, saved["receipt_id"])
    row = {col.name: deepcopy(getattr(original, col.name)) for col in original.__table__.columns}
    request = activation(d).public()
    row.update(
        id=str(uuid4()),
        command_kind="activate",
        version=2,
        state="active",
        idempotency_key=request["idempotency_key"],
        request=request,
    )
    if wrong == "false_attestation":
        request["reviewed_account"] = False
    elif wrong == "unknown_request":
        request["credential"] = "invented-forbidden-field"
    elif wrong == "late_version":
        request["expected_version"] = 2
    row["request_sha256"] = public_digest(
        "cosmas-finance-setup-request.v1",
        {"scope": flow.scope(c["box"], c["actor"]), "command_kind": "activate", "request": request},
    )
    if wrong == "wrong_digest":
        row["request_sha256"] = "0" * 64
    response = {
        **deepcopy(row["response"]),
        "command_kind": "activate",
        "receipt_id": row["id"],
        "idempotency_key": row["idempotency_key"],
        "request_sha256": row["request_sha256"],
        "effect": {**row["response"]["effect"], "version": 2, "state": "active"},
    }
    response.pop("receipt_sha256")
    if wrong == "wrong_effect":
        response["effect"]["review_sha256"] = "0" * 64
    row["receipt_sha256"] = public_digest("cosmas-finance-setup-receipt.v1", response)
    response["receipt_sha256"] = row["receipt_sha256"]
    row["response"] = response
    with session.begin_nested() as nested:
        with pytest.raises(DBAPIError):
            session.execute(insert(FinanceSetupReceipt).values(**row))
            immediate(session)
        nested.rollback()
    assert len(call(session, c, flow.history, c["account_request"].setup_id)["receipts"]) == 1


def test_managed_account_customer_admission_requires_atomic_settings_review(session, case):
    c = case
    a = account(session, c)
    immediate(session)
    with session.begin_nested() as nested:
        with pytest.raises(DBAPIError, match="managed customer binding requires setup review"):
            with Session(
                bind=session.connection(), join_transaction_mode="create_savepoint"
            ) as child:
                finance_setup.review_customer(
                    child,
                    c["box"],
                    c["actor"],
                    a["review"]["connection_version_id"],
                    c["patient_id"],
                    "cus_WithoutReview",
                    label="Invented orphan customer",
                )
            immediate(session)
        nested.rollback()
    assert (
        session.scalar(
            select(FinanceSetupReceipt.id).where(
                FinanceSetupReceipt.setup_id == a["summary"]["setup_id"]
            )
        )
        is not None
    )
