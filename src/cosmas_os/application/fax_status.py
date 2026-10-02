"""Receipt-bound fax follow-through. This module never calls a provider or changes work."""

from pydantic import ValidationError
from sqlalchemy import select

from cosmas_os.api import fax_status_schemas as schema
from cosmas_os.api import vendor_work_schemas as public
from cosmas_os.application import core_note_review, note_review, vendor_execution, workspace
from cosmas_os.application import vendor_work as work
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.models import WorkspaceEntry, WorkspaceNoteReview
from cosmas_os.vendor_models import VendorProviderObservation

FAX_ACTIONS = {"spruce_fax": "spruce", "srfax_fax": "srfax", "documo_fax": "documo", "efax_fax": "efax"}


def _step(code, label, *, human=True):
    return {"code": code, "label": label, "requires_human": human}


def project(facts):
    """Saved transport and current permission remain independent facts."""
    provider = facts["provider"]
    transport = facts["transport"]
    # Spruce's posting/read API never establishes fax transport delivery. Keep
    # that limit even if a historical row contains a terminal transport value.
    spruce_terminal = provider == "spruce" and transport in {"delivered", "failed"}
    outcome = ("unconfirmed" if facts["conflicting_evidence"] else
               "unconfirmed" if spruce_terminal else
               "provider_transport_delivered" if transport == "delivered" else
               "provider_transport_failed" if transport == "failed" else
               "spruce_posted_delivery_unconfirmed" if provider == "spruce" and facts["posted"] else
               "unconfirmed" if facts["dispatch"] == "unconfirmed" or transport == "unknown" else
               "not_established")
    label = ("Conflicting delivery evidence" if facts["conflicting_evidence"] else
             "Spruce receipt needs manual delivery verification" if spruce_terminal else
             "Fax transport delivered" if transport == "delivered" else
             "Fax transport failed; review the outcome" if transport == "failed" else
             "Posted in Spruce; fax delivery unconfirmed" if provider == "spruce" and facts["posted"] else
             "Submission accepted; delivery unconfirmed" if facts["acceptance"] == "accepted" else
             "Submission outcome unconfirmed" if facts["dispatch"] == "unconfirmed" or facts["acceptance"] == "unconfirmed" else
             "Fax proposal awaiting review" if facts["state"] == "pending_approval" else
             "Fax has not been sent")
    if facts["conflicting_evidence"]:
        step = _step("review_conflicting_receipts", "Review the conflicting receipts in the provider system; do not resend automatically")
    elif facts["source_current"] is not True:
        step = _step("review_current_source", "Check the current reviewed note before any new action; saved transport evidence remains recorded")
    elif facts["verification"] == "verified":
        step = _step("review_verified_result", "Local human outcome verified; review the separately recorded transport evidence", human=False)
    elif facts["state"] in {"rejected", "withdrawn", "superseded"}:
        step = _step("no_current_action", "This proposal is rejected, withdrawn or superseded; review its retained receipt", human=False)
    elif facts["state"] == "pending_approval":
        step = _step("review_exact_proposal", "Review the exact PDF and recipient before approving")
    elif not facts["submit_claimed"]:
        step = _step("review_approved_action", "Open the saved approved fax and review sending availability; sending needs an explicit human action")
    elif facts["dispatch"] == "unconfirmed" or facts["acceptance"] in {"unconfirmed", "not_observed", "rejected"}:
        step = _step("inspect_existing_operation", "Inspect the existing operation or verify in the provider system; do not send again automatically")
    elif facts["result"] == "recorded_exception" or transport == "failed":
        step = _step("review_fax_exception", "Review the exception and any reported partial pages with the responsible human")
    elif spruce_terminal:
        step = _step("verify_in_spruce", "Verify fax delivery in Spruce; its API posting evidence cannot confirm delivery")
    elif transport == "delivered":
        step = _step("review_human_result", "Review or record the human result, then verify the exact delivery receipt")
    elif provider == "spruce" and facts["posted"]:
        step = _step("verify_in_spruce", "Verify fax delivery in Spruce; its API posting evidence cannot confirm delivery")
    elif not facts["original_account_available"]:
        step = _step("review_original_account", "Check access to the original account before another explicit status read")
    else:
        step = _step("check_existing_fax", "Check the existing fax status; checking does not send another fax")
    return label, step, outcome


def _check(row):
    value = public.Observation.model_validate(row.public_observation).public()
    check = {key: item for key, item in value.items() if key != "sha256"}
    if (value["id"] != row.id or value["operation_id"] != row.operation_id or
        value["sequence"] != row.sequence or value["sha256"] != row.public_sha256 or
        public.public_digest("cosmas-vendor-public-observation.v1", check) != row.public_sha256):
        work.error("vendor_unavailable", 503)
    return value


def _recorded(value):
    return {key: value[key] for key in ("id", "sha256", "sequence", "observed_at", "recorded_at")}


def read(s, box, owner, wid, tid, *, require_link=False):
    w = work._owner(s, box, owner, wid)
    if require_link and s.scalar(select(WorkspaceEntry.id).where(
        WorkspaceEntry.workspace_id == wid, WorkspaceEntry.box_id == box,
        WorkspaceEntry.actor_id == owner, WorkspaceEntry.kind == "work_link",
        WorkspaceEntry.ticket_id == tid,
    )) is None:
        work.error("vendor_work_unavailable", 404)
    _, ticket, revision, command = work._bound(s, w, tid, writing=False)
    provider = FAX_ACTIONS.get(revision.action)
    if provider is None:
        work.error("vendor_work_unavailable", 404)
    summary = work._summary(s, ticket, revision)
    # Every row, including uncited/older evidence, remains bound to this exact
    # operation. Verify the chain rather than trusting a cached latest status.
    rows = list(s.scalars(select(VendorProviderObservation).where(
        VendorProviderObservation.operation_id == revision.intended_operation_id,
    ).order_by(VendorProviderObservation.sequence).limit(301)))
    if len(rows) > 300:
        work.error("vendor_history_limit")
    previous = public.public_digest("cosmas-vendor-observation-head.v1", {
        "operation_id": revision.intended_operation_id, "sequence": 0})
    values = []
    for sequence, row in enumerate(rows, 1):
        if (row.box_id, row.owner_id, row.workspace_id, row.ticket_id,
            row.action_revision_id, row.connection_version_id) != (
            box, owner, wid, tid, revision.action_revision_id, revision.connection_version_id):
            work.error("vendor_unavailable", 503)
        value = _check(row)
        expected = public.public_digest("cosmas-vendor-observation-head.v1", {
            "operation_id": revision.intended_operation_id, "sequence": sequence,
            "previous_sha256": previous, "observation_sha256": row.public_sha256})
        if row.sequence != sequence or row.head_sha256 != expected:
            work.error("vendor_unavailable", 503)
        previous = expected
        values.append(value)
    if summary["observation_head"] != {"sequence": len(values), "sha256": previous}:
        work.error("vendor_unavailable", 503)
    note = note_review._latest(s, wid)
    source_current = bool(note and (note.id, note.content_hash, note.source_fingerprint) == (
        revision.note_id, revision.content_hash, revision.source_fingerprint) and
        payload_hash({"content": note.content}) == note.content_hash and
        note_review.source_fingerprint(s, wid, w.revision) == revision.source_fingerprint and
        s.scalar(select(WorkspaceNoteReview.id).where(WorkspaceNoteReview.note_id == note.id)))
    if source_current and core_note_review.source_for(s, note) is not None:
        source_current = None  # A DB-only read cannot claim a current external Core version.
    try:
        vendor_execution._historical_connection(s, w, revision, command)
        account_available = True
    except (workspace.WorkspaceError, ValidationError):
        account_available = False
    facts = {**summary, "provider": provider, "source_current": source_current,
             "original_account_available": account_available,
             "posted": provider == "spruce" and any(v.get("transport") == "pending" for v in values)}
    label, step, outcome = project(facts)
    pages_value = next((v for v in reversed(values) if v.get("pages_total") is not None), None)
    pages = ({"observation": _recorded(pages_value), "total": pages_value["pages_total"],
              "delivered": pages_value["pages_delivered"]} if pages_value else None)
    body = {"contract_version": 1, "scope": {"box_id": box, "owner_id": owner, "workspace_id": wid},
        "ticket_id": tid, "operation_id": summary["operation_id"], "revision_id": summary["revision_id"],
        "payload_hash": summary["payload_hash"], "provider": provider,
        **{key: summary[key] for key in ("state", "version", "acceptance", "dispatch", "transport", "result", "verification", "conflicting_evidence", "responsible_id", "observation_head", "evidence_sha256")},
        "source_current": source_current, "original_account_available": account_available,
        "status_label": label, "next_step": step, "external_outcome": outcome,
        "last_recorded": _recorded(values[-1]) if values else None, "pages": pages,
        "observed_at": public.timestamp(work._clock(s))}
    body["sha256"] = public.public_digest("cosmas-fax-status.v1", {
        key: value for key, value in body.items() if key != "observed_at"})
    value = schema.FaxStatus.model_validate(body).public()
    work._final_authority(s)
    work._owner(s, box, owner, wid)
    return public.bounded(value, 8192)
