"""Owner-scoped next steps from saved operational evidence; never an action grant."""

from datetime import UTC, datetime

from cosmas_os.api.vendor_work_schemas import public_digest
from cosmas_os.application import (
    appointment_work,
    finance_work,
    follow_up,
    inbox_work,
    membership_work,
)
from cosmas_os.application import workspace as ws
from cosmas_os.config import Settings
from cosmas_os.config import settings as runtime
from cosmas_os.ports.bot_capabilities import supports_skill

KINDS = frozenset({"inbox", "follow_up", "scheduling", "membership", "payment"})
LINKED_LANES = {"encounter_follow_up": "follow_up", "scheduling_appointment": "scheduling",
                "encounter_membership_work": "membership", "encounter_payment_request": "payment"}


def step(code, label, *, human=True):
    return {"code": code, "label": label, "requires_human": human}


def project(kind, facts):
    """Deterministic interpretation prevents approvals or local reviews becoming done claims."""
    state = facts["state"]
    if facts.get("source_current") is False:
        return step("review_updated_source", "Review the changed or unavailable source"), "unconfirmed"
    if state in {"rejected", "withdrawn"}:
        return step("no_action", "This work was rejected or withdrawn", human=False), "not_established"
    if kind == "inbox":
        steps = {
            "needs_review": step("review_incoming_source", "Review the incoming item and matching encounter"),
            "needs_human": step("provider_review", "Ask the provider to review this incoming item"),
            "reviewed": step("triage_incoming_source", "Choose the appropriate administrative or provider review"),
            "triaged": step("prepare_review_result", "Prepare an administrative draft for human review"),
            "result_recorded": step("verify_local_review", "Verify the recorded administrative review"),
            "closed_local_review": step("review_complete", "Local inbox review is complete", human=False),
        }
        return steps.get(state, step("review_status", "Review the saved inbox status")), "no_external_action"
    if state == "pending_approval":
        return step("review_and_approve", "Review the exact proposal before approving"), "not_established"
    if kind == "follow_up":
        if state == "closed":
            return step("review_complete", "Human outcome recorded for the synthetic follow-up", human=False), "synthetic_only"
        if "local_delivery" in facts["receipt_kinds"]:
            return step("record_human_outcome", "Record the human-verified outcome"), "synthetic_only"
        return step("review_delivery_action", "Review the approved follow-up delivery action"), "not_established"
    if kind == "scheduling":
        if facts["appointment_saved"]:
            if facts["calendar_state"] == "synced":
                return step("review_receipt", "Review the saved appointment and calendar receipt", human=False), "calendar_synced"
            return step("check_calendar_sync", "Check calendar synchronization for the saved appointment"), "appointment_saved_calendar_unconfirmed"
        if facts["dispatch_started"]:
            return step("check_existing_operation", "Check the existing scheduling operation before any further action"), "unconfirmed"
        if facts.get("execution_available") is False:
            return step("review_saved_proposal", "Review the saved proposal; booking or changing a visit is not available yet"), "not_established"
        return step("review_booking_action", "Review the approved appointment action"), "not_established"
    if kind == "membership":
        if facts["evidence_current"] == "changed":
            return step("review_changed_evidence", "Review the changed membership evidence"), "membership_not_established"
        if state == "closed":
            return step("review_complete", "Local membership review is complete; membership remains unverified", human=False), "membership_not_established"
        if facts["result"] == "needs_human":
            return step("provider_review", "Resolve the membership exception with a human"), "membership_not_established"
        if facts["can_verify"]:
            return step("verify_local_review", "Verify the prepared local membership review"), "membership_not_established"
        return step("prepare_review_result", "Prepare the membership review and record its evidence"), "membership_not_established"
    if facts["conflicting_evidence"]:
        return step("resolve_payment_evidence", "Review the conflicting payment receipts"), "unconfirmed"
    if facts["payment_state"] == "succeeded":
        return step("review_payment_receipt", "Review the payment receipt; it does not establish membership"), "payment_recorded_membership_not_established"
    if facts["submit_claimed"]:
        return step("check_existing_payment", "Check the existing payment request before any further action"), "unconfirmed"
    return step("review_payment_action", "Review the exact approved payment action"), "not_established"


def read(s, box, owner, workspace_id, *, kind, record_id, inbox_registry=inbox_work.no_registry,
         inbox_policy=inbox_work.DEFAULT_POLICY, membership_policy=membership_work.DEFAULT_POLICY, now=None,
         configuration: Settings | None = None):
    if type(kind) is not str or kind not in KINDS or type(record_id) is not str:
        raise ws.WorkspaceError("operations_selection_invalid", 422)
    moment = datetime.now(UTC) if now is None else now
    if not isinstance(moment, datetime) or moment.tzinfo is None or moment.utcoffset() is None:
        raise ws.WorkspaceError("operations_selection_invalid", 422)
    w = ws._workspace(s, box, owner, workspace_id)
    if kind == "follow_up":
        items = follow_up.read(s, w, w.revision)
        selected = next((row for row in items if row["ticket_id"] == record_id), None)
        if selected is None:
            raise ws.WorkspaceError("operations_record_unavailable", 404)
        facts = {"state": selected["state"], "version": selected["ticket_version"], "payload_hash": selected["payload_hash"],
                 "revision_id": selected["revision_id"], "note_version": selected["note_version"],
                 "source_current": not selected["source_changed"], "operation_status": selected["operation_status"],
                 "receipt_kinds": [r["kind"] for r in selected["receipts"]],
                 "receipts": [{"id": r["id"], "sha256": public_digest("cosmas-follow-up-receipt.v1", r)}
                              for r in selected["receipts"]]}
        provenance = "saved synthetic delivery and human outcome receipts"
    elif kind == "scheduling":
        selected = appointment_work.read(s, box, owner, workspace_id, record_id, configuration=configuration)
        facts = {key: selected[key] for key in ("state", "payload_hash", "appointment_saved", "calendar_state", "dispatch_started", "operation_status")}
        facts.update(version=selected["ticket_version"], source_current=None)
        if configuration is not None:
            facts["execution_available"] = configuration.workspace_appointment_execution_available
        expires = datetime.fromisoformat(selected["intent"]["expires_at"])
        if not selected["dispatch_started"] and moment >= expires:
            facts["source_current"] = False
        provenance = "saved appointment operation and verified receiver receipt"
    elif kind == "inbox":
        if not inbox_policy.enabled:
            raise ws.WorkspaceError("operations_record_unavailable", 404)
        selected = inbox_work.detail(s, box, owner, record_id, registry=inbox_registry, policy=inbox_policy)["summary"]
        if selected["patient_link_id"] != w.patient_link_id or selected["workspace_id"] not in {None, workspace_id}:
            raise ws.WorkspaceError("operations_record_unavailable", 404)
        facts = {key: selected[key] for key in ("state", "version", "source_id", "source_sha256", "classification")}
        facts["source_current"] = selected["binding_current"] and not selected["read_issue"] and not selected["source_conflict"]
        provenance = "current incoming-source and local human review receipts"
    elif kind == "membership":
        selected = membership_work.detail(s, box, owner, workspace_id, record_id, policy=membership_policy)["summary"]
        facts = {key: selected[key] for key in ("state", "version", "payload_hash", "source_current", "result", "can_verify", "evidence_current", "evidence_classification")}
        provenance = "local membership preparation and human-recorded evidence; no service authority"
    else:
        selected = finance_work.detail(s, box, owner, workspace_id, record_id)["summary"]
        facts = {key: selected[key] for key in ("state", "version", "payload_hash", "creation", "payment_state", "submit_claimed", "conflicting_evidence", "observation_head", "evidence_sha256")}
        facts["source_current"] = None
        provenance = "saved payment operation and provider observations; no membership authority"
    next_step, external_outcome = project(kind, facts)
    scope = {"box_id": box, "owner_id": owner, "workspace_id": workspace_id}
    value = {"contract_version": 1, "scope": scope,
             "kind": kind, "record_id": record_id, "state": facts["state"], "next_step": next_step,
             "evidence": {"source_current": facts["source_current"],
                          "workflow_closed": facts["state"] in {"closed", "closed_local_review", "rejected", "withdrawn"},
                          "external_outcome": external_outcome, "provenance": provenance, "version": facts["version"],
                          "commitment": public_digest("cosmas-operations-status.v1",
                              {"scope": scope, "kind": kind, "record_id": record_id, "facts": facts})}}
    # Do not publish even minimal status after owner/encounter scope changes.
    ws._workspace(s, box, owner, workspace_id)
    return {**value, "observed_at": moment.astimezone(UTC).isoformat()}


def _unavailable(box, owner, workspace_id, kind, record_id, *, source_entry_id=None):
    value = {"contract_version": 1, "scope": {"box_id": box, "owner_id": owner, "workspace_id": workspace_id},
             "kind": kind, "record_id": record_id, "state": "unavailable",
             "next_step": step("open_work_for_review", "Open this linked work to check its current availability"),
             "evidence": {"source_current": None, "workflow_closed": False,
                          "external_outcome": "unconfirmed", "provenance": "Current private work could not be verified",
                          "version": None, "commitment": None}, "observed_at": datetime.now(UTC).isoformat()}
    if source_entry_id is not None:
        value["source_entry_id"] = source_entry_id
    return value


def linked(s, box, owner, workspace_id, snapshot, settings):
    """Native Chief reads only already-linked records, without scanning other work."""
    if settings["role"] != "chief" or not supports_skill(settings, "work_status"):
        return ()
    w = ws._workspace(s, box, owner, workspace_id)
    if snapshot["id"] != w.id or snapshot["revision"] != w.revision:
        raise ws.WorkspaceError("workspace_revision_conflict")
    selected = {}
    for entry in reversed(snapshot["entries"]):
        if entry["kind"] != "work_link":
            continue
        ticket = entry.get("ticket")
        if ticket is None:
            # The saved link remains visible even when its ticket has been
            # removed from the current private-work projection.
            selected[("entry", entry["id"])] = ("linked_work", None, entry["id"])
        elif ticket["lane"] in LINKED_LANES:
            selected.setdefault(("ticket", ticket["id"]), (LINKED_LANES[ticket["lane"]], ticket["id"], None))
    for item in snapshot.get("follow_ups", ()):
        selected.setdefault(("ticket", item["ticket_id"]), ("follow_up", item["ticket_id"], None))
    result = []
    # This mirrors the existing membership private-work API policy. The central
    # owner/encounter/private-lane selectors remain authoritative for each read.
    membership_policy = membership_work.MembershipPolicy(
        enabled=runtime.workspace_available and runtime.membership_work_enabled, private_selectors_ready=True)
    for kind, record_id, source_entry_id in list(selected.values())[:12]:
        if record_id is None:
            result.append(_unavailable(box, owner, workspace_id, kind, record_id, source_entry_id=source_entry_id))
            continue
        try:
            value = read(s, box, owner, workspace_id, kind=kind, record_id=record_id,
                         membership_policy=membership_policy, configuration=runtime)
        except ws.WorkspaceError:
            # A linked row may have been retired or its current source withdrawn.
            # Do not replace a failed read with a cached state or provider details.
            value = _unavailable(box, owner, workspace_id, kind, record_id)
        result.append(value)
    ws._workspace(s, box, owner, workspace_id)
    return tuple(result)
