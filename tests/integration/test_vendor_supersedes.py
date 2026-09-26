"""Explicit replacement creates new approval without resetting prior dispatch custody."""

from uuid import uuid4

import pytest
from tests.integration.test_vendor_work import (  # noqa: F401
    acceptance,
    approved,
    bound,
    call,
    gates,
    proposal,
)
from tests.integration.test_vendor_work import vendor_case as vendor_case
from tests.integration.test_vendor_work_api import client as client
from tests.integration.test_vendor_work_api import headers, root

from cosmas_os.api import vendor_work_schemas as schema
from cosmas_os.application import vendor_execution as execution
from cosmas_os.application import vendor_work as work
from cosmas_os.config import settings
from cosmas_os.models import Operation
from cosmas_os.vendor_models import VendorSubmitClaim


@pytest.mark.parametrize("outcome", ["uncertain", "rejected"])
def test_supersedes_claimed_prior_preserves_old_receipt_and_needs_new_approval(
    client, session, vendor_case, monkeypatch, outcome
):
    c = vendor_case
    monkeypatch.setattr(settings, "vendor_io_enabled", True)
    tid, d = approved(session, c)
    command = schema.BoundCommand(**bound(d))
    saved, invocation = call(session, c, execution.claim_submit, tid, command)
    if outcome == "rejected":
        execution.settle(session, invocation, observation=acceptance(invocation, "rejected"))
    old_detail = call(session, c, work.detail, tid)
    old_claim = session.get(VendorSubmitClaim, invocation.operation_id)
    old_token, old_status = (
        old_claim.claim_token,
        session.get(Operation, invocation.operation_id).status,
    )
    request = proposal(
        c, supersedes_operation_id=invocation.operation_id, acknowledge_prior_uncertainty=True
    )
    response = client.post(root(c), headers=headers(c), json=request.public())
    assert response.status_code == 200, response.text
    new_tid = response.json()["effect"]["ticket_id"]
    new_detail = client.get(root(c) + "/" + new_tid, headers=headers(c)).json()
    assert new_tid != tid and new_detail["summary"]["operation_id"] != invocation.operation_id
    assert new_detail["summary"]["state"] == "pending_approval"
    assert not new_detail["summary"]["submit_claimed"]
    assert new_detail["review"]["supersedes"]["uncertainty_acknowledged"] is True
    assert session.get(Operation, new_detail["summary"]["operation_id"]) is None
    assert call(session, c, work.detail, tid)["summary"] == old_detail["summary"]
    assert session.get(VendorSubmitClaim, invocation.operation_id).claim_token == old_token
    assert session.get(Operation, invocation.operation_id).status == old_status
    replay, again = call(session, c, execution.claim_submit, tid, command)
    assert again is None and replay["effect"] == saved["effect"]
    session.refresh(old_claim)
    assert old_claim.command_receipt_id == saved["effect"]["receipt_id"]


@pytest.mark.parametrize("wrong", ["unclaimed", "unknown", "reused_operation", "missing_ack"])
def test_supersedes_rejects_invalid_prior_or_reused_identity(
    client, session, vendor_case, monkeypatch, wrong
):
    c = vendor_case
    monkeypatch.setattr(settings, "vendor_io_enabled", True)
    tid, d = approved(session, c)
    operation = d["summary"]["operation_id"]
    if wrong != "unclaimed":
        call(session, c, execution.claim_submit, tid, schema.BoundCommand(**bound(d)))
    raw = proposal(c).public()
    raw.update(
        supersedes_operation_id=str(uuid4()) if wrong == "unknown" else operation,
        acknowledge_prior_uncertainty=True,
    )
    if wrong == "reused_operation":
        raw["proposed_operation_id"] = operation
    if wrong == "missing_ack":
        del raw["acknowledge_prior_uncertainty"]
    response = client.post(root(c), headers=headers(c), json=raw)
    assert response.status_code in {400, 409}, response.text


def test_supersedes_rejects_other_workspace_same_owner_and_other_patient(
    client, session, vendor_case, seeded, monkeypatch
):
    c = vendor_case
    monkeypatch.setattr(settings, "vendor_io_enabled", True)
    tid, d = approved(session, c)
    call(session, c, execution.claim_submit, tid, schema.BoundCommand(**bound(d)))
    from cosmas_os.application import workspace as ws

    original_create = ws.create
    monkeypatch.setattr(
        ws,
        "create",
        lambda s, box, actor, visit, key: original_create(s, box, actor, visit, key + str(uuid4())),
    )
    other = globals()["vendor_case"].__wrapped__(session, seeded)
    raw = proposal(
        other,
        supersedes_operation_id=d["summary"]["operation_id"],
        acknowledge_prior_uncertainty=True,
    ).public()
    response = client.post(root(other), headers=headers(other), json=raw)
    assert response.status_code == 409, response.text
