"""Owner-only inspection, derived from saved server receipts, never a command."""

from pydantic import ValidationError

from cosmas_os.api import finance_work_schemas as financial
from cosmas_os.api import membership_saved_evidence_schemas as schema
from cosmas_os.api import membership_work_schemas as membership
from cosmas_os.api import vendor_work_schemas as public
from cosmas_os.application import finance_work
from cosmas_os.application import membership_work as flow
from cosmas_os.application.workspace import WorkspaceError
from cosmas_os.finance_models import FinanceReceipt


def finance_evidence(s, box, actor, wid, tid, result_id, *, policy=flow.DEFAULT_POLICY):
    """Inspect only the latest result. Historical note versions remain inspectable.

    IDs come only from the saved result. Current workspace/patient authority and
    current verified finance evidence are required, but a changed source note
    does not turn inspection into a new approval or a new source admission.
    """
    w = flow.owner(s, box, actor, wid, policy=policy)
    t, r = flow.bound(s, w, tid)
    latest = flow.latest_result(s, tid)
    if latest is None or latest.id != result_id:
        flow.error("membership_work_unavailable", 404)
    try:
        original = membership.Result.model_validate(latest.request)
        recorded = flow.response(latest)
        if (
            original.public() != latest.request
            or membership.request_digest("result", flow.scope(w), original) != latest.request_sha256
            or (latest.box_id, latest.owner_id, latest.workspace_id, latest.ticket_id)
            != (box, actor, wid, tid)
            or (original.ticket_id, original.revision_id, original.payload_hash)
            != (tid, r.revision_id, r.payload_hash)
            or recorded["scope"] != flow.scope(w)
            or recorded["command_kind"] != "result"
            or recorded["idempotency_key"] != original.idempotency_key
            or recorded["effect"]["ticket_id"] != tid
            or recorded["effect"]["revision_id"] != r.revision_id
            or recorded["effect"]["payload_hash"] != r.payload_hash
            or recorded["effect"]["version"] != original.expected_version + 1
            or recorded["request_sha256"] != latest.request_sha256
            or recorded["effect"]["receipt_id"] != latest.id
            or original.ledger is None
            or original.ledger.finance is None
        ):
            flow.error("membership_evidence_changed")
        ledger = original.ledger
        flow.proof(s, w, ledger)
        proof = ledger.finance
        assert proof is not None
        row = s.get(FinanceReceipt, proof.verification_receipt_id)
        if row is None:
            flow.error("membership_evidence_changed")
        # Validate the retained original; never reconstruct it from effect fields.
        request = financial.FinanceVerify.model_validate(row.public_request)
        if (
            request.public() != row.public_request
            or financial.request_digest("verify", {"kind": "workspace", "id": wid}, request)
            != row.request_sha256
        ):
            flow.error("membership_evidence_changed")
        receipt = finance_work.response(s, row)
        detail = finance_work.detail(s, box, actor, wid, proof.ticket_id)
        current, effect = detail["summary"], receipt["effect"]
        if (
            (
                row.ticket_id,
                row.workspace_id,
                row.box_id,
                row.owner_id,
                row.actor_id,
                row.command_kind,
                row.receipt_sha256,
            )
            != (
                proof.ticket_id,
                wid,
                box,
                actor,
                actor,
                "verify",
                proof.verification_receipt_sha256,
            )
            or receipt["idempotency_key"] != request.idempotency_key
            or effect is None
            or effect["effect"] != "verified"
            or effect["receipt_id"] != proof.verification_receipt_id
            or current["state"] != "closed"
            or current["verification"] != "verified"
            or current["conflicting_evidence"]
            or (
                effect["ticket_id"],
                effect["revision_id"],
                effect["operation_id"],
                effect["payload_hash"],
                effect["effect_version"],
            )
            != (
                current["ticket_id"],
                current["revision_id"],
                current["operation_id"],
                current["payload_hash"],
                current["version"],
            )
            or (
                request.revision_id,
                request.operation_id,
                request.payload_hash,
                request.expected_version + 1,
            )
            != (
                current["revision_id"],
                current["operation_id"],
                current["payload_hash"],
                current["version"],
            )
            or request.evidence_sha256 != proof.evidence_sha256
            or current["evidence_sha256"] != proof.evidence_sha256
            or request.observation_head.public() != current["observation_head"]
            or detail["latest_result"] is None
            or (request.result_receipt_id, request.result_receipt_sha256)
            != (detail["latest_result"]["receipt_id"], detail["latest_result"]["receipt_sha256"])
        ):
            flow.error("membership_evidence_changed")
        value = {
            "contract_version": 1,
            "scope": flow.scope(w),
            "membership": {
                "ticket_id": tid,
                "version": t.version,
                "revision_id": r.revision_id,
                "payload_hash": r.payload_hash,
                "result_receipt_id": latest.id,
                "result_receipt_sha256": latest.receipt_sha256,
            },
            "request": row.public_request,
            "receipt": receipt,
            "detail": detail,
        }
        checked = schema.MembershipSavedFinance.model_validate(value).public()
        # Exact original request JSON survives validation and response serialization.
        if checked != value:
            flow.error("membership_evidence_changed")
        result = public.bounded(checked, 65536)
    except (ValidationError, ValueError, KeyError, TypeError):
        flow.error("membership_evidence_changed")
    except WorkspaceError as exc:
        if exc.status in {401, 403, 404}:
            flow.error("membership_work_unavailable", 404)
        raise
    flow.final_authority(s)
    return result
