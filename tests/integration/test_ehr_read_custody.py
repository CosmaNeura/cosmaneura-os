"""Real PostgreSQL custody guards; invented observations and no provider I/O."""

import hashlib
import json
from copy import deepcopy
from datetime import UTC, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from tests.integration.test_note_review import prepare

from cosmas_os.adapters.elation_read import ElationReadScope
from cosmas_os.adapters.elation_read_runtime import SyntheticElationReads
from cosmas_os.application import ehr_reads, selected_connector_sources
from cosmas_os.application import workspace as ws
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.ehr_read_models import (
    EhrReadBinding,
    EhrReadRequest,
    EhrReadSnapshot,
    EhrReadSourceReview,
)
from cosmas_os.models import EncounterWorkspace, ExternalIdentity, PatientLink, WorkspaceEntry


def stamp(value):
    return value.isoformat().replace("+00:00", "Z")


@pytest.fixture
def ehr_custody(session, seeded):
    box, owner, workspace, patient = prepare(session, seeded)
    account = ExternalIdentity(box_id=box, principal_id=owner, issuer=f"https://{uuid4()}.example.invalid",
        subject="invented-owner", organization_id="invented-org", reviewed_by="invented owner",
        evidence_ref="synthetic EHR custody")
    session.add(account)
    session.flush()
    scope = ElationReadScope(UUID(box), UUID(owner), uuid4(), uuid4(), 913, "Invented café 🫀")
    binding = EhrReadBinding(box_id=box, owner_id=owner, account_id=account.id,
        connection_id=str(scope.connection_id), credential_generation=str(scope.credential_generation),
        practice_id=str(scope.practice_id), practice_name=scope.practice_name, binding_digest=scope.commitment())
    session.add(binding)
    session.commit()
    port = SyntheticElationReads((scope,), httpx.MockTransport(lambda _: pytest.fail("custody never calls provider")),
        enabled=lambda: True, timezone="America/New_York")
    with ehr_reads.install_runtime_reader(lambda: port):
        yield SimpleNamespace(s=session, box=box, owner=owner, w=workspace, patient=patient,
            account=account.id, binding=binding, scope=scope)


def request(f, *, parent=None, key=None, changes=None):
    s, b = f.s, f.binding
    now = s.scalar(select(func.clock_timestamp()))
    if parent is None:
        # Past appointments remain valid observed evidence until the read TTL.
        begins, ends = now - timedelta(days=2), now - timedelta(days=1)
        body = dict(action="observe", connection_id=b.connection_id, binding_sha256=b.binding_digest,
            idempotency_key=key or "window-" + uuid4().hex, starts_at=stamp(begins), ends_at=stamp(ends))
        parent_id, handle, expires = None, None, now + timedelta(minutes=30)
    else:
        root = s.get(EhrReadRequest, parent.observation_id)
        begins, ends, expires = root.window_start, root.window_end, min(root.valid_until, now + timedelta(minutes=30))
        item = parent.payload["public"]["items"][0]
        parent_id, handle = parent.id, item["handle"]
        body = dict(action="verify", connection_id=b.connection_id, binding_sha256=b.binding_digest,
            idempotency_key=key or "verify-" + uuid4().hex, observation_id=root.id,
            observation_sha256=parent.source_sha256, item_handle=handle, item_sha256=item["sha256"])
    values = dict(box_id=f.box, owner_id=f.owner, account_id=f.account, binding_id=b.id,
        connection_id=b.connection_id, credential_generation=b.credential_generation, practice_id=b.practice_id,
        binding_digest=b.binding_digest, kind="window" if parent is None else "verify",
        ordinal=(s.scalar(select(func.max(EhrReadRequest.ordinal)).where(EhrReadRequest.binding_id == b.id)) or 0) + 1,
        idempotency_key=body["idempotency_key"], request_hash=payload_hash(body), request_json=body,
        parent_snapshot_id=parent_id, item_handle=handle, window_start=begins, window_end=ends,
        valid_until=expires, created_at=now)
    values.update(changes or {})
    row = EhrReadRequest(**values)
    s.add(row)
    s.flush()
    s.commit()
    return row


def snapshot(f, read, *, parent=None, mutate=None):
    now = f.s.scalar(select(func.clock_timestamp()))
    if parent is None:
        handle = str(uuid4())
        appointment = dict(appointment_id="812", patient_id="451", physician_id="71",
            starts_at=stamp(read.window_start + timedelta(hours=1)), ends_at=stamp(read.window_start + timedelta(hours=2)),
            status="Confirmed", scheduled_date_raw=stamp(read.window_start + timedelta(hours=1)), deleted_at=None)
        private = dict(handle=handle, appointment=appointment, patient=None)
        item = {**{key: appointment[key] for key in ("starts_at", "ends_at", "status")},
            "handle": handle, "selectable": True}
        item["sha256"] = payload_hash(dict(kind="ehr_window_item.v1", item=item.copy()))
        public = dict(kind="window", provider="elation", mode="synthetic",
            practice=dict(label=f.binding.practice_name, timezone="America/New_York"), observed_at=stamp(now),
            window=dict(starts_at=stamp(read.window_start), ends_at=stamp(read.window_end)),
            coverage="more_rows_available", items=[item])
    else:
        private = deepcopy(parent.payload["private"]["items"][0])
        private["patient"] = dict(patient_id="451", first_name="Invented Zoë", last_name="Example",
            birth_date="1990-03-17", primary_physician_id="71", deleted_at=None)
        public = deepcopy(parent.payload["public"])
        item = public.pop("items")[0]
        item.pop("selectable")
        item.pop("sha256")
        item["patient"] = {key: private["patient"][key] for key in ("first_name", "last_name", "birth_date")}
        item["sha256"] = payload_hash(dict(kind="ehr_verified_item.v1", item=item.copy()))
        public.update(kind="verified_visit", observed_at=stamp(now), item=item)
    payload = dict(public=public, private=dict(binding_sha256=read.binding_digest, request_sha256=read.request_hash,
        items=[private], provider_sources=["1" * 64, "2" * 64]))
    if mutate:
        mutate(payload)
    digest = payload_hash(payload)
    source = payload_hash(dict(observation_id=read.id, request_sha256=read.request_hash,
        binding_sha256=read.binding_digest, payload_sha256=digest,
        valid_until=read.valid_until.astimezone(UTC).isoformat(timespec="microseconds")))
    row = EhrReadSnapshot(box_id=f.box, owner_id=f.owner, observation_id=read.id,
        payload=payload, payload_sha256=digest, source_sha256=source)
    f.s.add(row)
    f.s.flush()
    f.s.commit()
    return row


def verified(f):
    window = snapshot(f, request(f))
    visit = snapshot(f, request(f, parent=window), parent=window)
    return window, visit


def review(f, visit, *, change_entry=None, change_review=None):
    w = f.s.get(EncounterWorkspace, f.w["id"])
    read = f.s.get(EhrReadRequest, visit.observation_id)
    item = visit.payload["public"]["item"]
    expected, key = w.revision, "review-" + uuid4().hex
    body = dict(workspace_id=w.id, expected_revision=expected, idempotency_key=key,
        observation_id=read.id, observation_sha256=visit.source_sha256, item_handle=item["handle"], item_sha256=item["sha256"],
        reviewed_visit=True, reviewed_patient_identity=True, reviewed_exact_snapshot=True, reviewed_untrusted_source=True)
    w.revision += 1
    content = ehr_reads.source_content(visit.payload["public"])
    values = dict(workspace_id=w.id, box_id=f.box, actor_id=f.owner, revision=w.revision,
        kind="ehr_read_source", content=content, source_label="Elation: reviewed appointment",
        idempotency_key=key, request_hash=payload_hash(body))
    values.update(change_entry or {})
    entry = WorkspaceEntry(**values)
    f.s.add(entry)
    f.s.flush()
    values = dict(workspace_id=w.id, box_id=f.box, owner_id=f.owner, entry_id=entry.id, snapshot_id=visit.id,
        patient_link_id=f.patient, expected_revision=expected, workspace_revision=w.revision,
        idempotency_key=key, request_hash=payload_hash(body), observation_sha256=visit.source_sha256,
        item_handle=item["handle"], item_sha256=item["sha256"], valid_until=read.valid_until,
        content_sha256=hashlib.sha256(content.encode()).hexdigest(),
        source_sha256=payload_hash({key: body[key] for key in ("observation_sha256", "item_handle", "item_sha256")}),
        reviewed_visit=True, reviewed_patient_identity=True, reviewed_exact_snapshot=True, reviewed_untrusted_source=True)
    values.update(change_review or {})
    row = EhrReadSourceReview(**values)
    f.s.add(row)
    f.s.flush()
    f.s.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    f.s.commit()
    return entry, row


def current(f, entry):
    return f.s.scalar(text("SELECT public.ehr_read_source_current(:entry)"), {"entry": entry.id})


def test_exact_unicode_snapshot_and_past_visit_use_read_expiry(ehr_custody):
    f = ehr_custody
    _, visit = verified(f)
    entry, receipt = review(f, visit)
    assert current(f, entry) is True
    assert f.s.scalar(text("SELECT public.ehr_read_source_content(CAST(:pub AS jsonb))"),
        {"pub": json.dumps(visit.payload["public"])}) == entry.content
    assert receipt.valid_until > f.s.scalar(select(func.clock_timestamp()))
    w = f.s.get(EncounterWorkspace, f.w["id"])
    assert selected_connector_sources.validate_selected_source(f.s, w, entry.id).id == entry.id
    projection = ws.read(f.s, f.box, f.owner, w.id)
    assert next(e for e in projection["entries"] if e["id"] == entry.id)["ehr_source_state"] == "current"


@pytest.mark.parametrize("field,value", [("practice_id", "914"), ("connection_id", str(uuid4())),
    ("credential_generation", str(uuid4())), ("binding_digest", "0" * 64)])
def test_request_cannot_substitute_binding_fields(ehr_custody, field, value):
    with pytest.raises(DBAPIError):
        request(ehr_custody, changes={field: value})
    ehr_custody.s.rollback()


def test_request_exact_body_hash_and_ordinals_are_enforced(ehr_custody):
    f = ehr_custody
    for changes in ({"request_hash": "0" * 64}, {"ordinal": 2}, {"request_json": {"action": "observe"}}):
        with pytest.raises(DBAPIError):
            request(f, changes=changes)
        f.s.rollback()
    row = request(f, key="exact-key-1")
    with pytest.raises(DBAPIError):
        request(f, key="exact-key-1")
    f.s.rollback()
    assert f.s.get(EhrReadRequest, row.id).idempotency_key == "exact-key-1"


@pytest.mark.parametrize("target", ["patient", "appointment", "item", "private_field", "digest"])
def test_self_consistent_outer_hash_does_not_hide_changed_exact_item(ehr_custody, target):
    f = ehr_custody
    window = snapshot(f, request(f))
    read = request(f, parent=window)
    def change(payload):
        if target == "patient":
            payload["private"]["items"][0]["patient"]["patient_id"] = "452"
        elif target == "appointment":
            payload["private"]["items"][0]["appointment"]["appointment_id"] = "813"
        elif target == "item":
            payload["public"]["item"]["patient"]["first_name"] = "Different invented person"
        elif target == "private_field":
            payload["private"]["items"][0]["patient"]["contact"] = "must not be retained"
        else:
            payload["public"]["item"]["sha256"] = "0" * 64
    with pytest.raises(DBAPIError):
        snapshot(f, read, parent=window, mutate=change)
    f.s.rollback()
    assert f.s.scalar(select(EhrReadSnapshot.id).where(EhrReadSnapshot.observation_id == read.id)) is None


@pytest.mark.parametrize("changes", [dict(reviewed_patient_identity=False), dict(item_handle=str(uuid4())),
    dict(item_sha256="0" * 64), dict(observation_sha256="0" * 64), dict(request_hash="0" * 64),
    dict(expected_revision=99), dict(content_sha256="0" * 64)])
def test_review_cannot_forge_exact_selection(ehr_custody, changes):
    f = ehr_custody
    _, visit = verified(f)
    with pytest.raises(DBAPIError):
        review(f, visit, change_review=changes)
    f.s.rollback()


@pytest.mark.parametrize("changes", [dict(content="Forged clinical text"), dict(source_label="Different EHR"),
    dict(kind="evidence")])
def test_review_has_no_generic_evidence_or_content_fallback(ehr_custody, changes):
    f = ehr_custody
    _, visit = verified(f)
    with pytest.raises(DBAPIError):
        review(f, visit, change_entry=changes)
    f.s.rollback()


def test_source_without_review_is_rejected_at_commit(ehr_custody):
    f = ehr_custody
    w = f.s.get(EncounterWorkspace, f.w["id"])
    w.revision += 1
    f.s.add(WorkspaceEntry(workspace_id=w.id, box_id=f.box, actor_id=f.owner, revision=w.revision,
        kind="ehr_read_source", content="Unreviewed invented text", source_label="Elation: reviewed appointment",
        idempotency_key="no-review", request_hash="0" * 64))
    with pytest.raises(DBAPIError):
        f.s.flush()
        f.s.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    f.s.rollback()


def test_review_cannot_substitute_another_patient_link(ehr_custody):
    f = ehr_custody
    _, visit = verified(f)
    other = PatientLink(box_id=f.box, source_pair_key="other:" + uuid4().hex, label="Other invented patient",
        state="confirmed", confirmed_by_principal_id=f.owner, attested_at=f.s.scalar(select(func.clock_timestamp())))
    f.s.add(other)
    f.s.commit()
    with pytest.raises(DBAPIError):
        review(f, visit, change_review={"patient_link_id": other.id})
    f.s.rollback()


def test_verify_does_not_supersede_sibling_but_new_window_withholds_all(ehr_custody):
    f = ehr_custody
    window, visit = verified(f)
    entry, _ = review(f, visit)
    sibling = snapshot(f, request(f, parent=window), parent=window)
    assert sibling.id != visit.id and current(f, entry) is True
    request(f)  # Even a response-lost newer explicit read supersedes this source.
    assert current(f, entry) is False
    w = f.s.get(EncounterWorkspace, f.w["id"])
    assert ehr_reads.historical_source(f.s, w, entry.id).id == entry.id
    with pytest.raises(ws.WorkspaceError, match="ehr_read_superseded"):
        selected_connector_sources.validate_selected_source(f.s, w, entry.id)
    projected = next(row for row in ws.read(f.s, f.box, f.owner, w.id)["entries"] if row["id"] == entry.id)
    assert projected["ehr_source_state"] == "unavailable" and projected["content"] == ""


@pytest.mark.parametrize("authority", ["binding", "account"])
def test_revocation_withholds_source_preserving_only_historical_provenance(ehr_custody, authority):
    f = ehr_custody
    _, visit = verified(f)
    entry, _ = review(f, visit)
    if authority == "binding":
        f.binding.state, f.binding.revoked_at = "revoked", f.s.scalar(select(func.clock_timestamp()))
    else:
        f.s.get(ExternalIdentity, f.account).active = False
    f.s.commit()
    assert current(f, entry) is False
    w = f.s.get(EncounterWorkspace, f.w["id"])
    assert ehr_reads.historical_source(f.s, w, entry.id).id == entry.id
    with pytest.raises(ws.WorkspaceError):
        selected_connector_sources.validate_selected_source(f.s, w, entry.id)


@pytest.mark.parametrize("table", ["ehr_read_bindings", "ehr_read_requests", "ehr_read_snapshots", "ehr_read_source_reviews"])
def test_ledgers_cannot_be_rewritten_or_deleted(ehr_custody, table):
    f = ehr_custody
    _, visit = verified(f)
    _, reviewed = review(f, visit)
    ids = dict(ehr_read_bindings=f.binding.id, ehr_read_requests=visit.observation_id,
        ehr_read_snapshots=visit.id, ehr_read_source_reviews=reviewed.id)
    for query in (f"UPDATE {table} SET id=id WHERE id=:id", f"DELETE FROM {table} WHERE id=:id"):
        with pytest.raises(DBAPIError):
            f.s.execute(text(query), {"id": ids[table]})
        f.s.rollback()


def test_revoked_binding_cannot_reactivate_or_publish_reserved_result(ehr_custody):
    f = ehr_custody
    read = request(f)
    f.binding.state, f.binding.revoked_at = "revoked", f.s.scalar(select(func.clock_timestamp()))
    f.s.commit()
    with pytest.raises(DBAPIError):
        snapshot(f, read)
    f.s.rollback()
    with pytest.raises(DBAPIError):
        f.s.execute(text("UPDATE ehr_read_bindings SET state='active', revoked_at=NULL WHERE id=:id"), {"id": f.binding.id})
    f.s.rollback()


def test_model_guard_checks_exact_ehr_source_and_current_authority(ehr_custody):
    f = ehr_custody
    _, visit = verified(f)
    entry, _ = review(f, visit)
    source = dict(entry_id=entry.id, revision=entry.revision,
        kind="evidence", label=entry.source_label, content=entry.content)
    value = dict(workspace_id=f.w["id"], box_id=f.box, owner_id=f.owner, request_body=dict(content="Draft directions"),
        prepared_envelope=dict(context=dict(sources=[source])))
    def valid(body):
        return f.s.scalar(text("SELECT public.selected_google_model_sources_current("
            "jsonb_populate_record(NULL::public.model_work_admissions, CAST(:value AS jsonb)))"), {"value": json.dumps(body)})
    assert valid(value) is True
    changed = {**value, "prepared_envelope": {"context": {"sources": [
        {**source, "content": entry.content + " altered"}]}}}
    assert valid(changed) is False
    descriptor_only = {**value, "prepared_envelope": {"context": {"sources": []}},
        "request_body": {"content": "Draft directions", "task_brief": dict(source_versions=[dict(entry_id=entry.id,
            revision=entry.revision, sha256=hashlib.sha256(entry.content.encode()).hexdigest())])}}
    assert valid(descriptor_only) is False
    f.binding.state, f.binding.revoked_at = "revoked", f.s.scalar(select(func.clock_timestamp()))
    f.s.commit()
    assert valid(value) is False
