"""Closed administrative delivery tools cannot choose or attest external authority."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from cosmas_os.api.vendor_work_schemas import VendorDecision
from cosmas_os.ports.agent_delivery_tools import (
    DELIVERY_REQUEST_ADAPTER,
    DELIVERY_TOOL_NAMES,
    ToolSelectionV3,
    tool_definitions,
)


def handle():
    return {"ticket_id": str(uuid4()), "revision_id": str(uuid4()),
        "operation_id": str(uuid4()), "payload_hash": "a" * 64}


@pytest.mark.parametrize("extra", [{"administrative_delivery_confirmed": True},
    {"follow_up_bot_id": str(uuid4())}, {"message": "change"}, {"destination": "change"},
    {"provider": "spruce"}, {"owner_id": str(uuid4())}, {"idempotency_key": "retry"},
    {"approval_receipt_id": str(uuid4())}])
def test_model_arguments_never_choose_content_identity_approval_or_retry(extra):
    with pytest.raises(ValidationError):
        DELIVERY_REQUEST_ADAPTER.validate_python({"tool": "execute_reviewed_delivery",
            **handle(), **extra})


@pytest.mark.parametrize("change", [{"payload_hash": "A" * 64}, {"operation_id": "unknown"},
    {"revision_id": str(uuid4()).upper()}, {"tool": "approve_delivery"}])
def test_invalid_or_noncanonical_handles_refused(change):
    with pytest.raises(ValidationError):
        DELIVERY_REQUEST_ADAPTER.validate_python({"tool": "read_delivery_status", **handle(), **change})


def test_delivery_definitions_expose_two_exact_closed_calls():
    definitions = tool_definitions()
    assert [item["name"] for item in definitions] == list(DELIVERY_TOOL_NAMES)
    assert all(item["parameters"]["additionalProperties"] is False for item in definitions)
    assert all(set(item["parameters"]["properties"]) == set(handle()) for item in definitions)


def test_selection_v3_freezes_exact_approval_identity_and_evidence_once():
    intent = {"kind": "vendor_delivery", **handle(), "approval_receipt_id": str(uuid4()),
        "approval_receipt_sha256": "b" * 64, "authority_sha256": "c" * 64,
        "agent_id": str(uuid4()), "team_revision_id": str(uuid4()),
        "external_identity_id": str(uuid4()), "evidence_sha256": "d" * 64}
    value = {"contract": "cosmas-agent-tool-selection.v3", "sources": [], "teammate_drafts": [],
        "operations": [], "connector_capabilities": [], "connector_intents": [],
        "delivery_intents": [intent], "sha256": "e" * 64}
    assert ToolSelectionV3.model_validate(value).delivery_intents[0].authority_sha256 == "c" * 64
    with pytest.raises(ValidationError):
        ToolSelectionV3.model_validate({**value, "delivery_intents": [intent, intent]})
    with pytest.raises(ValidationError):
        ToolSelectionV3.model_validate({**value, "delivery_intents": [{**intent, "evidence_sha256": 1}]})


@pytest.mark.parametrize("fields", [{"administrative_delivery_confirmed": True},
    {"follow_up_bot_id": str(uuid4())},
    {"administrative_delivery_confirmed": False, "follow_up_bot_id": str(uuid4())},
    {"administrative_delivery_confirmed": True, "follow_up_bot_id": str(uuid4()), "choice": "reject"}])
def test_human_delegation_requires_exact_confirmation_bot_and_approval(fields):
    value = {**{key: item for key, item in handle().items() if key != "ticket_id"},
        "expected_version": 1, "idempotency_key": "invented-decision", "review_sha256": "b" * 64,
        "choice": "approve", **fields}
    with pytest.raises(ValidationError):
        VendorDecision.model_validate(value)
