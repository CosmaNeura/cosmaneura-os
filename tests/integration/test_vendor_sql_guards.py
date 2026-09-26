"""Direct PostgreSQL failures for immutable vendor publication and completion proof."""

from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import insert, select, text
from sqlalchemy.exc import DBAPIError
from tests.integration.test_vendor_work import (
    acceptance,
    approved,
    bound,
    call,
    gates,
    immediate,
    proposal,
    vendor_case,
)

from cosmas_os.api import vendor_work_schemas as p
from cosmas_os.application import vendor_execution as execution
from cosmas_os.application import vendor_work as flow
from cosmas_os.config import settings
from cosmas_os.models import Ticket
from cosmas_os.ports import vendor_connectors as private
from cosmas_os.vendor_models import (
    VendorCommandReceipt,
    VendorProviderObservation,
    VendorWorkRevision,
)

# Both fixtures must remain visible to pytest, including the autouse gates.
__all__ = ["gates", "vendor_case"]


def record_result(s, c, tid, disposition="verified_in_vendor"):
    d = call(s, c, flow.detail, tid)
    return call(s, c, flow.record_result, tid, p.VendorResult(**bound(
        d, observation_head=d["summary"]["observation_head"], evidence_sha256=d["summary"]["evidence_sha256"],
        disposition=disposition, evidence="Invented owner result for SQL proof.",
    )))


def verification(s, c, tid, result):
    d = call(s, c, flow.detail, tid)
    return p.VendorVerify(**bound(d, result_receipt_id=result["effect"]["receipt_id"],
        result_receipt_sha256=result["effect"]["receipt_sha256"], observation_head=d["summary"]["observation_head"],
        evidence_sha256=d["summary"]["evidence_sha256"], reviewed_result=True, reviewed_observations=True,
        outcome_confirmed=True, reviewed_conflicting_evidence=d["summary"]["conflicting_evidence"]))


def receipt(c, tid, request, kind="verify", projection=None):
    value = deepcopy(request)
    rid, now = str(uuid4()), datetime.now(UTC)
    scope = {"kind": "workspace", "id": c["wid"]}
    digest = p.public_digest("cosmas-vendor-public-request.v1", {"command_kind": kind, "scope": scope, "request": value})
    effect = {"ticket_id": tid, "operation_id": value["operation_id"], "revision_id": value["revision_id"],
        "payload_hash": value["payload_hash"], "receipt_id": rid, "effect_version": value["expected_version"] + 1,
        "recorded_at": p.timestamp(now)}
    summary = {"effect": {"verify": "verified", "publish": "published", "decide": "approved"}[kind],
               "publication_recorded": projection is not None}
    sha = p.public_digest("cosmas-vendor-public-receipt.v1", {"scope": scope, "command_kind": kind,
        "idempotency_key": value["idempotency_key"], "request_sha256": digest, "effect": effect, "summary": summary})
    effect["receipt_sha256"] = sha
    return dict(id=rid, box_id=c["box"], workspace_id=c["wid"], owner_id=c["actor"], actor_id=c["actor"],
        origin="user", scope_kind="workspace", scope_id=c["wid"], command_kind=kind,
        idempotency_key=value["idempotency_key"], public_request=value, request_sha256=digest, ticket_id=tid,
        action_revision_id=value["revision_id"], operation_id=value["operation_id"], effect_version=effect["effect_version"],
        effect={"effect": effect, "summary": summary}, receipt_sha256=sha, recorded_at=now,
        result_receipt_id=value.get("result_receipt_id"), observation_head_sha256=value.get("observation_head", {}).get("sha256"),
        evidence_sha256=value.get("evidence_sha256"), publication_projection=projection,
        publication_sha256=p.public_digest("cosmas-vendor-public-review.v1", projection) if projection else None)


def insert_receipt(s, row):
    s.execute(text("UPDATE tickets SET version=:version,state=:state,closed_at=:closed WHERE id=:tid"),
        {"version": row["effect_version"], "state": "closed" if row["command_kind"] == "verify" else "approved",
         "closed": row["recorded_at"] if row["command_kind"] == "verify" else None, "tid": row["ticket_id"]})
    s.execute(insert(VendorCommandReceipt.__table__).values(**row))
    immediate(s)


@pytest.mark.parametrize("field,value", [
    ("reviewed_result", False), ("reviewed_observations", "true"), ("outcome_confirmed", None),
    ("reviewed_conflicting_evidence", True), ("result_receipt_sha256", "0" * 64),
    ("evidence_sha256", "0" * 64), ("observation_head", {"sequence": 1, "sha256": "0" * 64}),
])
def test_sql_verification_requires_exact_current_proof(session, vendor_case, field, value):
    c = vendor_case
    tid, _ = approved(session, c)
    result = record_result(session, c, tid)
    request = verification(session, c, tid, result).public()
    request[field] = value
    row = receipt(c, tid, request)
    with pytest.raises(DBAPIError), session.begin_nested():
        insert_receipt(session, row)


@pytest.mark.parametrize("column", ["request_sha256", "receipt_sha256", "observation_head_sha256", "evidence_sha256"])
def test_sql_verification_rejects_tampered_stored_hashes(session, vendor_case, column):
    tid, _ = approved(session, vendor_case)
    result = record_result(session, vendor_case, tid)
    row = receipt(vendor_case, tid, verification(session, vendor_case, tid, result).public())
    row[column] = "0" * 64
    with pytest.raises(DBAPIError), session.begin_nested():
        insert_receipt(session, row)


def test_sql_verification_rejects_older_result_even_with_current_evidence(session, vendor_case):
    c = vendor_case
    tid, _ = approved(session, c)
    old = record_result(session, c, tid)
    record_result(session, c, tid)
    row = receipt(c, tid, verification(session, c, tid, old).public())
    with pytest.raises(DBAPIError), session.begin_nested():
        insert_receipt(session, row)


@pytest.mark.parametrize("delivery", ["unknown", "failed", "conflicting"])
def test_sql_unresolved_delivery_requires_manual_owner_result(session, vendor_case, monkeypatch, delivery):
    c = vendor_case
    if delivery == "unknown":
        tid, _ = approved(session, c)
    else:
        tid, _ = accepted_case(session, c, monkeypatch)
        if delivery == "conflicting":
            read_delivery(session, c, tid, "transport_delivered")
        read_delivery(session, c, tid, "transport_failed")
    result = record_result(session, c, tid, "reported_success")
    row = receipt(c, tid, verification(session, c, tid, result).public())
    with pytest.raises(DBAPIError), session.begin_nested():
        insert_receipt(session, row)


@pytest.mark.parametrize("change", ["extra_private_field", "body", "share", "projection_hash", "receipt_hash"])
def test_sql_publication_requires_exact_safe_projection_and_explicit_share(session, vendor_case, change):
    c = vendor_case
    tid, d = approved(session, c)
    revision = session.get(VendorWorkRevision, d["summary"]["revision_id"])
    projection = flow._safe_publication(revision)
    request = p.VendorPublication(**bound(d, review_sha256=d["review_sha256"], share_to_practice=True)).public()
    if change == "extra_private_field":
        projection["private_message"] = "Invented private content"
    if change == "body":
        projection["body"] = "Unapproved invented text"
    if change == "share":
        request["share_to_practice"] = False
    row = receipt(c, tid, request, "publish", projection)
    if change == "projection_hash":
        row["publication_sha256"] = "0" * 64
    if change == "receipt_hash":
        row["receipt_sha256"] = "0" * 64
    with pytest.raises(DBAPIError), session.begin_nested():
        insert_receipt(session, row)


def test_sql_approval_cannot_publish_unshared_original_review(session, vendor_case):
    c = vendor_case
    first = call(session, c, flow.propose, proposal(c, share_to_practice=False))
    tid = first["effect"]["ticket_id"]
    d = call(session, c, flow.detail, tid)
    r = session.get(VendorWorkRevision, d["summary"]["revision_id"])
    request = p.VendorDecision(**bound(d, review_sha256=d["review_sha256"], choice="approve")).public()
    with pytest.raises(DBAPIError), session.begin_nested():
        insert_receipt(session, receipt(c, tid, request, "decide", flow._safe_publication(r)))


def accepted_case(s, c, monkeypatch):
    monkeypatch.setattr(settings, "vendor_io_enabled", True)
    tid, d = approved(s, c)
    _, invocation = call(s, c, execution.claim_submit, tid, p.BoundCommand(**bound(d)))
    execution.mark_invocation(s, invocation)
    observed = acceptance(invocation)
    observed = observed.model_copy(update={"reference": observed.reference.model_copy(update={"kind": "conversation_item", "value": "invented_item"})})
    execution.settle(s, invocation, observation=observed)
    return tid, invocation


def read_delivery(s, c, tid, state):
    d = call(s, c, flow.detail, tid)
    _, invocation = call(s, c, execution.claim_read, tid, p.BoundCommand(**bound(d)))
    execution.settle(s, invocation, observation=private.DeliveryObservation(reference=invocation.reference,
        observed_at=datetime.now(UTC), state=state, response_sha256="d" * 64))


def observation(s, invocation, kind="submission", value="accepted"):
    original = s.scalar(select(VendorProviderObservation).where(VendorProviderObservation.operation_id == invocation.operation_id)
                        .order_by(VendorProviderObservation.sequence.desc()))
    row = {column.name: deepcopy(getattr(original, column.name)) for column in VendorProviderObservation.__table__.columns}
    row.update(id=str(uuid4()), sequence=original.sequence + 1, canonical_sha256=uuid4().hex * 2, kind=kind)
    public = {k: v for k, v in row["public_observation"].items() if k not in {"acceptance", "transport", "dispatch", "safe_error", "pages_total", "pages_delivered", "sha256"}}
    public.update(id=row["id"], sequence=row["sequence"], kind=kind, **{{"submission": "acceptance", "transport": "transport"}[kind]: value})
    row["public_sha256"] = p.public_digest("cosmas-vendor-public-observation.v1", public)
    public["sha256"] = row["public_sha256"]
    row["public_observation"] = public
    row["head_sha256"] = p.public_digest("cosmas-vendor-observation-head.v1", {"operation_id": invocation.operation_id,
        "sequence": row["sequence"], "previous_sha256": original.head_sha256, "observation_sha256": row["public_sha256"]})
    return row


@pytest.mark.parametrize("change", ["public_hash", "head_hash", "skipped_sequence", "body_after_hash"])
def test_sql_observation_requires_rehashed_exact_next_chain(session, vendor_case, monkeypatch, change):
    _, invocation = accepted_case(session, vendor_case, monkeypatch)
    row = observation(session, invocation)
    if change == "public_hash":
        row["public_sha256"] = row["public_observation"]["sha256"] = "0" * 64
    if change == "head_hash":
        row["head_sha256"] = "0" * 64
    if change == "skipped_sequence":
        # Recompute every digest so the rejection proves the sequence rule itself.
        previous = session.scalar(select(VendorProviderObservation).where(VendorProviderObservation.operation_id == invocation.operation_id)
                                  .order_by(VendorProviderObservation.sequence.desc()))
        row["sequence"] += 1
        row["public_observation"]["sequence"] += 1
        row["public_sha256"] = p.public_digest("cosmas-vendor-public-observation.v1", {k: v for k, v in row["public_observation"].items() if k != "sha256"})
        row["public_observation"]["sha256"] = row["public_sha256"]
        row["head_sha256"] = p.public_digest("cosmas-vendor-observation-head.v1", {"operation_id": invocation.operation_id,
            "sequence": row["sequence"], "previous_sha256": previous.head_sha256, "observation_sha256": row["public_sha256"]})
    if change == "body_after_hash":
        row["public_observation"]["acceptance"] = "rejected"
    with pytest.raises(DBAPIError), session.begin_nested():
        session.execute(insert(VendorProviderObservation.__table__).values(**row))
        immediate(session)


def test_compatible_observation_keeps_historical_verification_and_contradiction_requires_reopen(session, vendor_case, monkeypatch):
    c = vendor_case
    tid, invocation = accepted_case(session, c, monkeypatch)
    read_delivery(session, c, tid, "transport_delivered")
    result = record_result(session, c, tid, "reported_success")
    call(session, c, flow.verify, tid, verification(session, c, tid, result))
    # A compatible later observation preserves the historical receipt and closed state.
    read_delivery(session, c, tid, "transport_delivered")
    immediate(session)
    assert session.get(Ticket, tid).state == "closed"
    row = observation(session, invocation, "transport", "failed")
    with pytest.raises(DBAPIError), session.begin_nested():
        session.execute(insert(VendorProviderObservation.__table__).values(**row))
        immediate(session)
    # The actual application appends the contradiction and reopens in one unit of work.
    read_delivery(session, c, tid, "transport_failed")
    immediate(session)
    assert session.get(Ticket, tid).state == "approved"
    manual = record_result(session, c, tid)
    call(session, c, flow.verify, tid, verification(session, c, tid, manual))
    immediate(session)
    assert session.get(Ticket, tid).state == "closed"


def test_sql_public_hash_matches_unicode_nested_protocol_and_rejects_float(session):
    value = {"z": [True, None, -7, {"label": "Invented é\nquote\""}], "a": {"empty": [], "amount": 2147483647}}
    from sqlalchemy import bindparam
    from sqlalchemy.dialects.postgresql import JSONB
    statement = text("SELECT public.vendor_public_digest('example.v1',:value)").bindparams(bindparam("value", type_=JSONB))
    assert session.scalar(statement, {"value": value}) == p.public_digest("example.v1", value)
    with pytest.raises(DBAPIError), session.begin_nested():
        session.scalar(statement, {"value": {"amount": 1.5}})


@pytest.mark.parametrize("change", ["retire", "revoke"])
def test_sql_correspondence_retirement_and_revocation_preserve_private_version(session, vendor_case, change):
    mapping = vendor_case["correspondence"]
    before = dict(session.execute(text("SELECT to_jsonb(c) FROM vendor_correspondence_versions c WHERE id=:id"), {"id": mapping.id}).scalar_one())
    if change == "retire":
        session.execute(text("UPDATE vendor_correspondence_versions SET is_current=false WHERE id=:id"), {"id": mapping.id})
    else:
        session.execute(text("UPDATE vendor_correspondence_versions SET revoked_at=:at WHERE id=:id"), {"id": mapping.id, "at": datetime.now(UTC)})
    immediate(session)
    after = dict(session.execute(text("SELECT to_jsonb(c) FROM vendor_correspondence_versions c WHERE id=:id"), {"id": mapping.id}).scalar_one())
    assert {k:v for k,v in after.items() if k not in {"is_current", "revoked_at"}} == {k:v for k,v in before.items() if k not in {"is_current", "revoked_at"}}
    assert after["is_current"] is False if change == "retire" else after["revoked_at"] is not None
    with pytest.raises(DBAPIError), session.begin_nested():
        session.execute(text("UPDATE vendor_correspondence_versions SET private_sha256=:sha WHERE id=:id"), {"id": mapping.id, "sha": "0"*64})
    if change == "revoke":
        with pytest.raises(DBAPIError), session.begin_nested():
            session.execute(text("UPDATE vendor_correspondence_versions SET revoked_at=NULL WHERE id=:id"), {"id": mapping.id})


def test_sql_revoked_connection_cannot_reenable_reads_or_writes(session, vendor_case):
    connection = vendor_case["config"]
    session.execute(text("UPDATE vendor_connection_versions SET revoked_at=:at,read_enabled=false,write_enabled=false WHERE id=:id"), {"id": connection.id, "at":datetime.now(UTC)})
    immediate(session)
    for field in ("read_enabled", "write_enabled"):
        with pytest.raises(DBAPIError), session.begin_nested():
            session.execute(text(f"UPDATE vendor_connection_versions SET {field}=true WHERE id=:id"), {"id":connection.id})
