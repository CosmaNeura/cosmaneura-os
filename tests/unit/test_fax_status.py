"""Saved facts cannot promote approval, posting or a human result to fax delivery."""

from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from cosmas_os.api import fax_status_schemas as schema
from cosmas_os.api import vendor_work_schemas as public
from cosmas_os.application import fax_status, workspace


def facts(**changes):
    return {"provider": "documo", "state": "approved", "acceptance": "accepted",
        "dispatch": "response_observed", "transport": "pending", "result": "none",
        "verification": "pending", "conflicting_evidence": False, "source_current": True,
        "original_account_available": True, "posted": False, "submit_claimed": True, **changes}


@pytest.mark.parametrize("changes,code,outcome", [
    ({"state": "pending_approval", "submit_claimed": False, "acceptance": "not_observed"}, "review_exact_proposal", "not_established"),
    ({"submit_claimed": False, "acceptance": "not_observed"}, "review_approved_action", "not_established"),
    ({"result": "recorded_success"}, "check_existing_fax", "not_established"),
    ({"transport": "delivered"}, "review_human_result", "provider_transport_delivered"),
    ({"transport": "failed", "result": "recorded_exception"}, "review_fax_exception", "provider_transport_failed"),
    ({"transport": "delivered", "source_current": False}, "review_current_source", "provider_transport_delivered"),
    ({"transport": "delivered", "source_current": None}, "review_current_source", "provider_transport_delivered"),
    ({"transport": "delivered", "conflicting_evidence": True}, "review_conflicting_receipts", "unconfirmed"),
    ({"acceptance": "unconfirmed", "dispatch": "unconfirmed", "transport": "unknown"}, "inspect_existing_operation", "unconfirmed"),
    ({"provider": "spruce", "posted": True}, "verify_in_spruce", "spruce_posted_delivery_unconfirmed"),
    ({"provider": "spruce", "posted": True, "transport": "delivered"}, "verify_in_spruce", "unconfirmed"),
    ({"original_account_available": False}, "review_original_account", "not_established"),
    ({"transport": "unknown", "verification": "verified"}, "review_verified_result", "unconfirmed"),
])
def test_transport_and_current_authority_are_separate(changes, code, outcome):
    label, step, observed = fax_status.project(facts(**changes))
    assert label and step["code"] == code and observed == outcome


def status():
    identifier = str(uuid4())
    return {"contract_version": 1, "scope": {"box_id": identifier, "owner_id": identifier, "workspace_id": identifier},
        "ticket_id": identifier, "operation_id": identifier, "revision_id": identifier, "payload_hash": "a" * 64,
        "provider": "documo", "state": "approved", "version": 1, "acceptance": "accepted",
        "dispatch": "response_observed", "transport": "pending", "result": "none", "verification": "pending",
        "conflicting_evidence": False, "source_current": None, "original_account_available": False,
        "responsible_id": identifier, "status_label": "Delivery unconfirmed",
        "next_step": {"code": "review_current_source", "label": "Review the current source", "requires_human": True},
        "external_outcome": "not_established", "observation_head": {"sequence": 0, "sha256": "b" * 64},
        "evidence_sha256": "c" * 64, "last_recorded": None, "pages": None,
        "observed_at": "2026-10-02T12:00:00.000000Z", "sha256": "d" * 64}


def test_closed_status_preserves_required_unknown_fields():
    value = status()
    assert schema.FaxStatus.model_validate(value).public() == value
    with pytest.raises(ValidationError):
        schema.FaxStatus.model_validate({**value, "provider_response": "forbidden"})
    with pytest.raises(ValidationError):
        schema.FaxStatus.model_validate({**value, "version": True})
    with pytest.raises(ValidationError):
        schema.FaxStatus.model_validate({**value, "contract_version": True})
    with pytest.raises(ValidationError):
        schema.FaxStatus.model_validate({**value, "version": 0})
    with pytest.raises(ValidationError):
        schema.FaxStatus.model_validate({**value, "provider": "spruce", "external_outcome": "provider_transport_delivered"})


def test_reported_pages_require_exact_bounded_observation():
    value = status()
    recorded = {"id": str(uuid4()), "sha256": "a" * 64, "sequence": 1,
                "observed_at": value["observed_at"], "recorded_at": value["observed_at"]}
    value.update(observation_head={"sequence": 1, "sha256": "b" * 64}, last_recorded=recorded,
                 pages={"observation": recorded, "total": 3, "delivered": 1})
    checked = schema.FaxStatus.model_validate(value)
    assert checked.pages is not None and checked.pages.delivered == 1
    for change in ({"total": 0}, {"delivered": 1_000_001}, {"observation": {**recorded, "sequence": 2}}):
        invalid = deepcopy(value)
        invalid["pages"].update(change)
        with pytest.raises(ValidationError):
            schema.FaxStatus.model_validate(invalid)


def test_observation_hash_scope_cannot_be_forged():
    value = {"id": str(uuid4()), "operation_id": str(uuid4()), "sequence": 1, "kind": "transport",
        "transport": "delivered", "observed_at": "2026-10-02T12:00:00.000000Z", "recorded_at": "2026-10-02T12:00:00.000000Z"}
    value["sha256"] = public.public_digest("cosmas-vendor-public-observation.v1", value)
    row = SimpleNamespace(public_observation=value, public_sha256=value["sha256"],
                          id=value["id"], operation_id=value["operation_id"], sequence=1)
    assert fax_status._check(row) == value
    row.public_observation = {**value, "transport": "failed"}
    with pytest.raises(workspace.WorkspaceError, match="vendor_unavailable"):
        fax_status._check(row)
