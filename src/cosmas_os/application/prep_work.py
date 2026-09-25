"""Source-bound internal preparation work on F-8; no patient sender or Core writer."""
import hashlib
import html
import json
import re
from urllib.parse import unquote

from sqlalchemy import func, select

from cosmas_os.application import follow_up as follow
from cosmas_os.application import note_review as notes
from cosmas_os.application import workspace as ws
from cosmas_os.config import settings
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.models import ActionRevision, AuditEvent, Decision, FollowUpReceipt, FollowUpSource, Operation, Ticket
from cosmas_os.ports.encounter_prep import CorePrepReceipt

LANE = "visit_preparation"
ACTION = "preparation.internal_publication"
ADAPTER = "workspace_internal_preparation"
CHANNEL = "internal_work"
INTAKE_REF = re.compile(r"intake_[0-7][0-9a-hjkmnp-tv-z]{25}", re.IGNORECASE)


def available():
    if not settings.workspace_prep_work_enabled or not settings.workspace_available:
        raise ws.WorkspaceError("prep_work_unavailable", 404)


def _local(s):
    available()
    follow._local(s)


def _tokens(receipt):
    if isinstance(receipt, CorePrepReceipt):
        receipt = receipt.model_dump(mode="json")
    result = set()
    for source in (receipt or {}).get("sources", []):
        if source.get("kind") == "patient_intake_summary":
            reference = source.get("source_ref", "")
            if INTAKE_REF.fullmatch(reference):
                result.update((reference, reference.removeprefix("intake_")))
    return result


def _decoded(value):
    for _ in range(2):
        value = html.unescape(unquote(value))
    return value.casefold()


def _contains_secret(value, tokens):
    value = _decoded(value)
    return bool(INTAKE_REF.search(value) or any(token.casefold() in value for token in tokens))


def _known_tokens(s, w, current=None):
    tokens = _tokens(current)
    for receipt in s.scalars(select(FollowUpSource.prep_receipt).where(
        FollowUpSource.workspace_id == w.id, FollowUpSource.box_id == w.box_id,
        FollowUpSource.owner_id == w.owner_id, FollowUpSource.source_kind == "core_prep")):
        tokens.update(_tokens(receipt))
    for proof in s.scalars(select(FollowUpReceipt.source_proof).join(FollowUpSource,
        FollowUpSource.ticket_id == FollowUpReceipt.ticket_id).where(
            FollowUpSource.workspace_id == w.id, FollowUpSource.box_id == w.box_id,
            FollowUpReceipt.source_proof.is_not(None))):
        tokens.update(_tokens(proof))
    return tokens


def _text(s, w, value, maximum, current=None):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or "\0" in value:
        raise ws.WorkspaceError("invalid_prep_work", 400)
    if _contains_secret(value, _known_tokens(s, w, current)):
        raise ws.WorkspaceError("prep_work_private_link", 422)


def public_prep_receipt(receipt: CorePrepReceipt):
    """Opaque display identifiers; the Core commitment is distinct from display integrity."""
    tokens = _tokens(receipt)

    def opaque(value):
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def redact(value):
        clean = INTAKE_REF.sub("[Private link removed]", value)
        for token in sorted(tokens, key=len, reverse=True):
            clean = re.sub(re.escape(token), "[Private link removed]", clean, flags=re.IGNORECASE)
        if _contains_secret(clean, tokens):
            clean = "[Private link removed]"
        return clean

    sources = []
    for source in receipt.sources:
        label, content = redact(source.label), redact(source.content)
        sources.append({"source_id": opaque(source.source_ref), "appointment_ref": opaque(source.appointment_ref),
            "kind": source.kind, "label": label, "source_at": source.source_at.isoformat(),
            "content_sha256": opaque(content), "content": content, "truncated": source.truncated,
            "content_redacted": label != source.label or content != source.content})
    value = {"appointment_ref": opaque(receipt.appointment_ref), "sources": sources,
        "additional_notes_available": receipt.additional_notes_available, "snapshot_sha256": receipt.snapshot_sha256}
    value["display_sha256"] = hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":")).encode("utf-8")).hexdigest()
    return value


def _snapshot(s, w, checked, expected):
    if not isinstance(checked, CorePrepReceipt) or checked.snapshot_sha256 != expected:
        raise ws.WorkspaceError("prep_work_source_changed")
    appointment = ws._encounter(s, w.box_id, w.appointment_id, w.patient_link_id, owner=w.owner_id)
    if appointment.source != "cosmaneura_core" or checked.appointment_ref != appointment.external_id:
        raise ws.WorkspaceError("prep_work_source_changed")
    return checked


def _bound(s, w, tid, revision_id, digest, *, writing=True):
    b = s.scalar(select(FollowUpSource).where(FollowUpSource.ticket_id == tid,
        FollowUpSource.workspace_id == w.id, FollowUpSource.box_id == w.box_id,
        FollowUpSource.owner_id == w.owner_id, FollowUpSource.source_kind == "core_prep"))
    if not b:
        raise ws.WorkspaceError("prep_work_unavailable", 404)
    t = s.scalar(select(Ticket).where(Ticket.id == tid).with_for_update(read=not writing).execution_options(populate_existing=True))
    r = s.get(ActionRevision, b.action_revision_id)
    if (not t or not r or b.action_revision_id != revision_id or b.payload_hash != digest
        or t.current_revision_id != r.id or r.invalidated or t.lane != LANE or t.created_by_principal_id != w.owner_id
        or t.box_id != w.box_id or t.appointment_id != w.appointment_id or t.patient_link_id != w.patient_link_id
        or r.payload_hash != digest or payload_hash(r.payload) != digest or r.content != r.payload.get("body")
        or r.target_ref != f"patient_link:{w.patient_link_id}" or r.target_ref != r.payload.get("target_ref")
        or r.payload.get("owner_id") != w.owner_id or r.action_type != ACTION or r.payload.get("action") != ACTION
        or r.payload.get("channel") != CHANNEL or r.automation_class != "hitl_required"):
        raise ws.WorkspaceError("prep_work_approval_changed")
    return b, t, r


def receipt(s, ticket, kind):
    return s.scalar(select(FollowUpReceipt).where(FollowUpReceipt.ticket_id == ticket.id,
        FollowUpReceipt.box_id == ticket.box_id, FollowUpReceipt.kind == kind))


def _operation(s, ticket, revision):
    op = s.scalar(select(Operation).where(Operation.action_revision_id == revision.id).with_for_update().execution_options(populate_existing=True))
    if op and (op.ticket_id != ticket.id or op.box_id != ticket.box_id or op.adapter != ADAPTER
               or op.external_reference is not None):
        raise ws.WorkspaceError("prep_work_approval_changed")
    return op


def is_open(s, ticket, revision):
    op = _operation(s, ticket, revision)
    return ticket.state == "approved" and op is not None and op.status == "succeeded" and receipt(s, ticket, "internal_publication") is not None


def ready(s, ticket):
    return ticket.state == "approved" and receipt(s, ticket, "ready_for_review") is not None


def _event(s, w, ticket, revision, kind, outcome, *, actor=None, approved=False):
    s.add(AuditEvent(box_id=w.box_id, aggregate_type="ticket", aggregate_id=ticket.id,
        event_type=kind, actor_principal_id=actor or w.owner_id,
        approved_by_principal_id=w.owner_id if approved else None, action_revision_id=revision.id,
        payload_hash=revision.payload_hash, policy_version=revision.policy_version,
        charter_version=revision.charter_version, config_version=revision.config_version,
        outcome=outcome, detail={"channel": CHANNEL}))


def _response(s, w, ticket, revision):
    from cosmas_os.application import shared_work
    item = shared_work._view(s, w.owner_id, ticket, revision, shared_work.history(s, ticket))
    source = s.get(FollowUpSource, ticket.id)
    item["proposed_snapshot_sha256"] = source.prep_snapshot_sha256
    return {"entry_revision": w.revision, "item": item}


def detail(s, box, actor, wid, tid):
    _local(s)
    w = ws._workspace(s, box, actor, wid)
    source = s.get(FollowUpSource, tid)
    if source is None:
        raise ws.WorkspaceError("prep_work_unavailable", 404)
    _, t, r = _bound(s, w, tid, source.action_revision_id, source.payload_hash, writing=False)
    return _response(s, w, t, r)


def catalog(s, box, actor, wid):
    _local(s)
    w = ws._workspace(s, box, actor, wid)
    rows = s.scalars(select(FollowUpSource).where(FollowUpSource.workspace_id == wid,
        FollowUpSource.box_id == box, FollowUpSource.owner_id == actor,
        FollowUpSource.source_kind == "core_prep").order_by(FollowUpSource.workspace_revision.desc()).limit(50))
    return {"entry_revision": w.revision, "items": [detail(s, box, actor, wid, row.ticket_id)["item"] for row in rows]}


def recover_proposal(s, box, actor, wid, command):
    _local(s)
    w = ws._workspace(s, box, actor, wid)
    prior = s.scalar(select(FollowUpSource).where(FollowUpSource.workspace_id == wid,
        FollowUpSource.idempotency_key == command["idempotency_key"]))
    if prior:
        if prior.source_kind != "core_prep" or prior.request_hash != payload_hash(command):
            raise ws.WorkspaceError("idempotency_conflict")
        _, t, r = _bound(s, w, prior.ticket_id, prior.action_revision_id, prior.payload_hash, writing=False)
        return _response(s, w, t, r)
    s.commit()  # The upcoming Core read never holds a local lock.
    return None


def propose(s, box, actor, wid, command, checked):
    _local(s)
    w = ws._workspace(s, box, actor, wid, writing=True)
    prior = s.scalar(select(FollowUpSource).where(FollowUpSource.workspace_id == wid,
        FollowUpSource.idempotency_key == command["idempotency_key"]))
    if prior:
        if prior.source_kind != "core_prep" or prior.request_hash != payload_hash(command):
            raise ws.WorkspaceError("idempotency_conflict")
        _, t, r = _bound(s, w, prior.ticket_id, prior.action_revision_id, prior.payload_hash)
        return _response(s, w, t, r)
    checked = _snapshot(s, w, checked, command["snapshot_sha256"])
    if command["share_context"] is not True:
        raise ws.WorkspaceError("prep_work_share_required", 400)
    _text(s, w, command["body"], 4000, checked)
    _text(s, w, command["expected_outcome"], 500, checked)
    count = s.scalar(select(func.count()).select_from(FollowUpSource).where(
        FollowUpSource.workspace_id == wid, FollowUpSource.source_kind == "core_prep"))
    if count >= 50:
        raise ws.WorkspaceError("prep_work_history_limit")
    notes._advance(w, command["expected_entry_revision"])
    payload = {"action": ACTION, "channel": CHANNEL, "body": command["body"],
        "target_ref": f"patient_link:{w.patient_link_id}", "owner_id": actor,
        "due_date": command["due_date"], "expected_outcome": command["expected_outcome"]}
    t = Ticket(box_id=box, lane=LANE, state="pending_approval", created_by_principal_id=actor,
        appointment_id=w.appointment_id, patient_link_id=w.patient_link_id)
    s.add(t); s.flush()
    r = ActionRevision(ticket_id=t.id, box_id=box, revision_number=1, action_type=ACTION,
        target_ref=payload["target_ref"], content=payload["body"], payload=payload,
        payload_hash=payload_hash(payload), automation_class="hitl_required",
        policy_version="internal-preparation-v1", charter_version="human-selected-v1",
        config_version="local-only-v1", created_by_principal_id=actor)
    s.add(r); s.flush(); t.current_revision_id = r.id
    s.add(FollowUpSource(ticket_id=t.id, box_id=box, workspace_id=wid, owner_id=actor,
        source_kind="core_prep", prep_snapshot_sha256=checked.snapshot_sha256,
        prep_receipt=checked.model_dump(mode="json"), action_revision_id=r.id,
        payload_hash=r.payload_hash, workspace_revision=w.revision,
        idempotency_key=command["idempotency_key"], request_hash=payload_hash(command)))
    _event(s, w, t, r, "prep_work.proposed", "pending_approval")
    s.commit()
    return _response(s, w, t, r)


def recover_decision(s, box, actor, wid, tid, command):
    _local(s)
    w = ws._workspace(s, box, actor, wid)
    _, t, r = _bound(s, w, tid, command["revision_id"], command["payload_hash"], writing=False)
    published = receipt(s, t, "internal_publication")
    if command["choice"] == "approve" and published:
        if published.actor_id != actor or published.request_hash != payload_hash(command):
            raise ws.WorkspaceError("idempotency_conflict")
        return _response(s, w, t, r)
    if command["choice"] == "reject" and t.state == "rejected":
        if t.version != command["expected_version"] + 1:
            raise ws.WorkspaceError("idempotency_conflict")
        return _response(s, w, t, r)
    if t.state != "pending_approval":
        raise ws.WorkspaceError("prep_work_not_pending")
    if t.version != command["expected_version"]:
        raise ws.WorkspaceError("shared_work_changed")
    s.commit()
    return None


def decide(s, box, actor, wid, tid, command, checked=None):
    _local(s)
    w = ws._workspace(s, box, actor, wid, writing=True)
    b, t, r = _bound(s, w, tid, command["revision_id"], command["payload_hash"])
    published = receipt(s, t, "internal_publication")
    if command["choice"] == "approve" and published:
        if published.actor_id != actor or published.request_hash != payload_hash(command):
            raise ws.WorkspaceError("idempotency_conflict")
        return _response(s, w, t, r)
    if command["choice"] == "reject" and t.state == "rejected":
        if t.version != command["expected_version"] + 1:
            raise ws.WorkspaceError("idempotency_conflict")
        return _response(s, w, t, r)
    if t.state != "pending_approval":
        raise ws.WorkspaceError("prep_work_not_pending")
    if t.version != command["expected_version"]:
        raise ws.WorkspaceError("shared_work_changed")
    if command["choice"] == "reject":
        t.state = "rejected"; t.version += 1; w.revision += 1
        s.add(Decision(box_id=box, ticket_id=tid, action_revision_id=r.id, actor_principal_id=actor, kind="reject"))
        _event(s, w, t, r, "decision.rejected", "rejected")
    else:
        checked = _snapshot(s, w, checked, command["expected_snapshot_sha256"])
        if checked.snapshot_sha256 != b.prep_snapshot_sha256:
            raise ws.WorkspaceError("prep_work_source_changed")
        _text(s, w, r.content, 4000, checked)
        _text(s, w, r.payload["expected_outcome"], 500, checked)
        op = Operation(box_id=box, ticket_id=tid, action_revision_id=r.id,
            idempotency_key=f"prep:{r.id}", adapter=ADAPTER, status="succeeded", attempt_count=1)
        s.add(op); s.flush()
        published = FollowUpReceipt(ticket_id=tid, box_id=box, operation_id=op.id, actor_id=actor,
            kind="internal_publication", content="Opened as internal preparation work. No patient message was sent.",
            request_hash=payload_hash(command), idempotency_key=op.idempotency_key)
        s.add(published); s.flush()
        op.started_at = op.completed_at = published.created_at
        op.result_receipt_hash = payload_hash({"receipt_id": published.id, "request_hash": published.request_hash})
        s.add(Decision(box_id=box, ticket_id=tid, action_revision_id=r.id, actor_principal_id=actor, kind="approve"))
        t.state = "approved"; t.version += 1; w.revision += 1
        _event(s, w, t, r, "decision.approved", "approved", approved=True)
        _event(s, w, t, r, "prep_work.internal_publication", "internal_publication")
    s.commit()  # Exact approval and the internal DB publication are one atomic effect.
    return _response(s, w, t, r)


def record_ready(s, w, t, r, *, actor, expected, key, evidence):
    from cosmas_os.application.shared_work import responsible
    _local(s)
    _text(s, w, evidence, 2000)
    request_hash = payload_hash({"expected_version": expected, "revision_id": r.id,
        "payload_hash": r.payload_hash, "evidence": evidence})
    prior = receipt(s, t, "ready_for_review")
    if prior:
        if prior.actor_id != actor or prior.idempotency_key != key or prior.request_hash != request_hash:
            raise ws.WorkspaceError("idempotency_conflict")
        return
    if type(expected) is not int or expected < 1 or t.version != expected:
        raise ws.WorkspaceError("shared_work_changed")
    if responsible(s, t) != actor:
        raise ws.WorkspaceError("shared_work_responsibility_required")
    if not is_open(s, t, r):
        raise ws.WorkspaceError("prep_work_publication_required")
    op = _operation(s, t, r)
    s.add(FollowUpReceipt(ticket_id=t.id, box_id=t.box_id, operation_id=op.id, actor_id=actor,
        kind="ready_for_review", content=evidence, request_hash=request_hash, idempotency_key=key))
    t.version += 1; w.revision += 1
    _event(s, w, t, r, "prep_work.ready_for_review", "ready_for_review", actor=actor)


def recover_verification(s, box, actor, wid, tid, command):
    _local(s)
    w = ws._workspace(s, box, actor, wid)
    _, t, r = _bound(s, w, tid, command["revision_id"], command["payload_hash"], writing=False)
    prior = receipt(s, t, "provider_verification")
    if prior:
        if prior.actor_id != actor or prior.idempotency_key != command["idempotency_key"] or prior.request_hash != payload_hash(command):
            raise ws.WorkspaceError("idempotency_conflict")
        return _response(s, w, t, r)
    if command["reviewed_summary"] is not True:
        raise ws.WorkspaceError("prep_work_review_required", 400)
    if t.version != command["expected_version"]:
        raise ws.WorkspaceError("shared_work_changed")
    if not ready(s, t):
        raise ws.WorkspaceError("prep_work_staff_evidence_required")
    s.commit()
    return None


def verify(s, box, actor, wid, tid, command, checked):
    _local(s)
    w = ws._workspace(s, box, actor, wid, writing=True)
    _, t, r = _bound(s, w, tid, command["revision_id"], command["payload_hash"])
    prior = receipt(s, t, "provider_verification")
    if prior:
        if prior.actor_id != actor or prior.idempotency_key != command["idempotency_key"] or prior.request_hash != payload_hash(command):
            raise ws.WorkspaceError("idempotency_conflict")
        return _response(s, w, t, r)
    if command["reviewed_summary"] is not True:
        raise ws.WorkspaceError("prep_work_review_required", 400)
    if t.version != command["expected_version"]:
        raise ws.WorkspaceError("shared_work_changed")
    if not is_open(s, t, r) or not ready(s, t):
        raise ws.WorkspaceError("prep_work_staff_evidence_required")
    checked = _snapshot(s, w, checked, command["current_snapshot_sha256"])
    summary = next((source for source in checked.sources if source.kind == "patient_intake_summary"), None)
    if summary is None or summary.truncated or not summary.content.strip():
        raise ws.WorkspaceError("prep_work_saved_summary_required")
    if any(source["content_redacted"] for source in public_prep_receipt(checked)["sources"] if source["kind"] == "patient_intake_summary"):
        raise ws.WorkspaceError("prep_work_summary_redacted")
    op = _operation(s, t, r)
    proof = FollowUpReceipt(ticket_id=t.id, box_id=box, operation_id=op.id, actor_id=actor,
        kind="provider_verification", content="Provider reviewed the current saved intake summary.",
        request_hash=payload_hash(command), idempotency_key=command["idempotency_key"],
        source_snapshot_sha256=checked.snapshot_sha256, source_proof=checked.model_dump(mode="json"))
    s.add(proof); s.flush()
    t.state = "closed"; t.closed_at = proof.created_at; t.version += 1; w.revision += 1
    _event(s, w, t, r, "prep_work.provider_verification", "closed")
    s.commit()
    return _response(s, w, t, r)
