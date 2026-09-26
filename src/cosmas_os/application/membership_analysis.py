"""Current private work evidence for Membership/Billing; no processor or ledger I/O."""

import json
from types import SimpleNamespace

from cosmas_os.api import vendor_work_schemas as public
from cosmas_os.api.membership_analysis_schemas import MembershipAnalysis
from cosmas_os.application import finance_work as finance
from cosmas_os.application import membership_work as membership
from cosmas_os.application import workspace as ws
from cosmas_os.config import settings as runtime
from cosmas_os.ports.bot_capabilities import BotContext, SourcePassage, supports_skill

DOMAIN = "cosmas-membership-analysis.v1"


def selection(value):
    try:
        return MembershipAnalysis.model_validate(value).model_dump(mode="json")
    except (ValueError, TypeError, RecursionError):
        raise ws.WorkspaceError("invalid_membership_analysis", 422) from None


def snapshot(kind, detail):
    """Allow-listed model data and separate identity/evidence commitment; also used by UI."""
    summary, review, result = detail["summary"], detail["review"], detail["latest_result"]
    if kind == "membership":
        keys = (
            "purpose",
            "due_date",
            "state",
            "evidence_classification",
            "evidence_current",
            "result",
            "verification",
            "external_service_verified",
            "membership_authority",
            "source_current",
        )
        proposal = review["proposal"]
        ledger = result["request"].get("ledger") if result else None
        data = {
            "status": {key: summary[key] for key in keys},
            "expected_outcome": proposal["expected_outcome"],
            "instructions": proposal["instructions"],
            "human_evidence": result["request"]["evidence"] if result else None,
            "ledger_observation": {
                "observed_at": ledger["observed_at"],
                "membership_state": ledger["observed_membership_state"],
                "billing_state": ledger["observed_billing_state"],
                "linked_finance_review": ledger.get("finance") is not None,
                "authority": "human_recorded_not_independent_service_verification",
            }
            if ledger
            else None,
        }
    else:
        keys = (
            "state",
            "amount",
            "currency",
            "creation",
            "payment_state",
            "amount_received",
            "submit_claimed",
            "conflicting_evidence",
            "result",
            "verification",
        )
        data = {
            "status": {key: summary[key] for key in keys},
            "due_date": review["due_date"],
            "expected_outcome": review["expected_outcome"],
            "human_evidence": result["evidence"] if result else None,
            "amount_unit": "minor_currency_unit",
            "membership_authority": "not_established_by_payment",
        }
    return {
        "kind": kind,
        "data": data,
        "review_sha256": detail["review_sha256"],
        "result_receipt": {"id": result["receipt_id"], "sha256": result["receipt_sha256"]}
        if result
        else None,
        "finance_evidence": {
            "observation_head": summary["observation_head"],
            "evidence_sha256": summary["evidence_sha256"],
        }
        if kind == "payment"
        else None,
    }


def build_context(s, workspace, settings, command):
    if settings["role"] != "custom" or not supports_skill(settings, "membership_review"):
        raise ws.WorkspaceError("membership_bot_required")
    chosen = selection(command["membership_analysis"])
    expected = command["expected_revision"]
    if workspace.revision not in {expected, expected + 1}:
        raise ws.WorkspaceError("source_changed")
    if not runtime.workspace_available or not (
        runtime.membership_work_enabled
        if chosen["kind"] == "membership"
        else runtime.finance_work_enabled
    ):
        raise ws.WorkspaceError("membership_analysis_unavailable")
    if chosen["kind"] == "membership":
        policy = membership.MembershipPolicy(True, True)
        membership.owner(s, workspace.box_id, workspace.owner_id, workspace.id, policy=policy)
        t, r = membership.bound(s, workspace, chosen["ticket_id"])
        d = membership.detail(
            s, workspace.box_id, workspace.owner_id, workspace.id, t.id, policy=policy
        )
        # The saved question advances the encounter once. It cannot invalidate its
        # own reviewed source; all other note/source changes remain observable.
        baseline = SimpleNamespace(
            **{
                key: getattr(workspace, key)
                for key in ("id", "box_id", "owner_id", "patient_link_id", "appointment_id")
            },
            revision=expected,
        )
        d["summary"] = membership.summary(s, baseline, t, r, policy=policy)
    else:
        finance.owner(s, workspace.box_id, workspace.owner_id, workspace.id)
        t, r, _ = finance.bound(s, workspace, chosen["ticket_id"])
        if (
            t.patient_link_id != workspace.patient_link_id
            or t.appointment_id != workspace.appointment_id
        ):
            raise ws.WorkspaceError("source_changed")
        review = r.public_review
        connection = SimpleNamespace(
            **{key: review["connection"][key] for key in ("id", "revision", "public_sha256")}
        )
        customer = SimpleNamespace(
            **{key: review["customer"][key] for key in ("id", "revision", "public_sha256")}
        )
        c, _, _, _, _ = finance.selected(s, workspace, connection, customer, writing=False)
        if not c.read_enabled:
            raise ws.WorkspaceError("authority_changed")
        d = finance.detail(s, workspace.box_id, workspace.owner_id, workspace.id, t.id)
    current = d["summary"]
    if (
        current["ticket_id"],
        current["version"],
        current["revision_id"],
        current["payload_hash"],
    ) != (
        chosen["ticket_id"],
        chosen["ticket_version"],
        chosen["revision_id"],
        chosen["payload_hash"],
    ):
        raise ws.WorkspaceError("source_changed")
    selected = snapshot(chosen["kind"], d)
    if public.public_digest(DOMAIN, selected) != chosen["snapshot_sha256"]:
        raise ws.WorkspaceError("source_changed")
    content = json.dumps(selected["data"], ensure_ascii=False, sort_keys=True, indent=2)
    if len(content) > 5000 or len(content.encode("utf-8")) > 20000:
        raise ws.WorkspaceError("membership_analysis_too_large", 422)
    return BotContext(
        workspace_id=workspace.id,
        context_revision=expected,
        role="custom",
        question=command["content"],
        response_style=settings["response_style"],
        sources=(
            SourcePassage(
                current["ticket_id"],
                current["version"],
                "Selected membership work"
                if chosen["kind"] == "membership"
                else "Selected payment work",
                "membership_work" if chosen["kind"] == "membership" else "payment_work",
                content,
            ),
        ),
        linked_work=(),
        skills=("membership_review",),
        handoff_limit=0,
    )
