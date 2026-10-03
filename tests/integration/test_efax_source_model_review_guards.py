"""Database source custody rejects forged admissions and stale human reviews.

Actual PostgreSQL triggers are exercised through INSERT, without application
validation. Vendor/model exchanges use the existing invented long-fax fixture.
No vendor delivery, credential or outside patient data is exercised here.
"""

from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, insert, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from tests.integration import test_efax_source_full_workflow as flow

from cosmas_os.adapters.gpt41 import _context
from cosmas_os.application import model_work as work
from cosmas_os.application import workspace as ws
from cosmas_os.models import (
    EncounterWorkspace,
    ModelWorkAdmission,
    WorkspaceEntry,
    WorkspaceHandoffAttempt,
    WorkspaceHandoffReview,
    WorkspaceReply,
)

managed_case = flow.managed_case
efax_http = flow.efax_http
source_http = flow.source_http
long_fax = flow.long_fax


def template(f):
    """Retain a real service-created admission as a valid raw-INSERT template."""
    aid = flow.reserve(f)
    with Session(f.case.engine) as s:
        row = s.get(ModelWorkAdmission, aid)
        values = {c.name: deepcopy(getattr(row, c.name)) for c in ModelWorkAdmission.__table__.columns}
        at = s.scalar(select(func.clock_timestamp()))
        work._finish(s, row, "failed", "authority_changed", at)
        s.commit()
    return values


def insert_admission(f, values, mutate=lambda value: None):
    """Change hashes consistently, leaving the source trigger as the boundary."""
    with Session(f.case.engine) as s:
        w = s.get(EncounterWorkspace, f.wid)
        expected = w.revision
        w.revision += 1
        key = "forged-admission-" + str(uuid4())
        entry = WorkspaceEntry(workspace_id=f.wid, box_id=f.box, actor_id=f.owner,
            revision=w.revision, kind="conversation", content=values["request_body"]["content"],
            idempotency_key=key, request_hash="a" * 64)
        s.add(entry)
        s.flush()
        data = deepcopy(values)
        at = s.scalar(select(func.clock_timestamp()))
        data.update(id=str(uuid4()), request_key=key, request_entry_id=entry.id,
            expected_revision=expected, admitted_at=at, reservation_expires_at=at + timedelta(seconds=10))
        data["request_body"].update(idempotency_key=key, expected_revision=expected)
        mutate(data)
        data["request_hash"] = work.digest(data["request_body"])
        data["envelope_sha256"] = work.digest(data["prepared_envelope"])
        try:
            context = _context(data["prepared_envelope"]["context"])
            data["source_sha256"] = work.source_digest(context)
        except (KeyError, TypeError, ValueError):
            pass  # The raw DB guard must also reject structurally malformed input.
        s.execute(insert(ModelWorkAdmission).values(**data))
        s.flush()
        return data["id"]  # Session close rolls back even successful control rows.


def fax_source(data, f):
    return next(p for p in data["prepared_envelope"]["context"]["sources"]
        if p["entry_id"] == f.fax_saved["entry_id"])


def test_current_real_service_admission_is_accepted_by_raw_sql_control(long_fax):
    f = long_fax
    assert insert_admission(f, template(f))


@pytest.mark.parametrize("field,value", [
    ("revision", 999), ("kind", "synthetic_source"), ("label", "Forged label"),
    ("content", "Forged content with a recomputed envelope hash"),
    ("entry_id", "00000000-0000-0000-0000-000000000000"),
])
def test_raw_reserved_insert_rejects_forged_fax_source_even_with_recomputed_hashes(long_fax, field, value):
    f = long_fax
    values = template(f)
    def mutate(data):
        fax_source(data, f)[field] = value
    with pytest.raises(IntegrityError) as error:
        insert_admission(f, values, mutate)
    assert error.value.orig.sqlstate == "23514"


@pytest.mark.parametrize("carrier", ["tool_selection", "source_delivery", "task_brief"])
@pytest.mark.parametrize("fault", ["missing_context", "changed_revision", "changed_hash"])
def test_declared_fax_handle_cannot_contradict_full_saved_context(long_fax, carrier, fault):
    f = long_fax
    values = template(f)
    def mutate(data):
        envelope = data["prepared_envelope"]
        if carrier == "tool_selection":
            handles = envelope["tool_selection"]["sources"]
        elif carrier == "source_delivery":
            handles = envelope["source_delivery"]
        else:
            handles = deepcopy(envelope["tool_selection"]["sources"])
            data["request_body"]["task_brief"] = {"source_versions": handles}
        handle = next(h for h in handles if h["entry_id"] == f.fax_saved["entry_id"])
        if fault == "missing_context":
            envelope["context"]["sources"] = [p for p in envelope["context"]["sources"]
                if p["entry_id"] != f.fax_saved["entry_id"]]
        elif fault == "changed_revision":
            handle["revision"] += 1
        else:
            handle["sha256"] = "b" * 64
    with pytest.raises(IntegrityError) as error:
        insert_admission(f, values, mutate)
    assert error.value.orig.sqlstate == "23514"


def test_feature_omission_does_not_infer_all_current_fax_inventory(long_fax):
    f = long_fax
    def omit(data):
        envelope = data["prepared_envelope"]
        envelope["context"]["sources"] = [p for p in envelope["context"]["sources"]
            if p["entry_id"] != f.fax_saved["entry_id"]]
        for handles in (envelope["tool_selection"]["sources"], envelope["source_delivery"]):
            handles[:] = [h for h in handles if h["entry_id"] != f.fax_saved["entry_id"]]
    assert insert_admission(f, template(f), omit)


@pytest.mark.parametrize("analysis", ["session_prep_analysis", "inbox_analysis", "membership_analysis", "research_analysis"])
def test_specialized_context_can_use_nonworkspace_source_ids(long_fax, analysis):
    f = long_fax
    def specialize(data):
        envelope = data["prepared_envelope"]
        data["request_body"][analysis] = {}
        envelope["context"]["sources"] = [{**fax_source(data, f), "entry_id": str(uuid4())}]
        envelope.pop("tool_selection")
        envelope.pop("source_delivery")
    # Only this narrow source helper is qualified here. Other application
    # validators still own each actual specialized analysis contract.
    assert insert_admission(f, template(f), specialize)


@pytest.mark.parametrize("carrier", ["context", "tool_selection", "source_delivery", "task_brief"])
def test_raw_insert_rejects_nonarray_source_carrier(long_fax, carrier):
    f = long_fax
    def malformed(data):
        if carrier == "context":
            data["prepared_envelope"]["context"]["sources"] = {}
        elif carrier == "task_brief":
            data["request_body"]["task_brief"] = {"source_versions": {}}
        elif carrier == "tool_selection":
            data["prepared_envelope"][carrier]["sources"] = {}
        else:
            data["prepared_envelope"][carrier] = {}
    with pytest.raises(IntegrityError) as error:
        insert_admission(f, template(f), malformed)
    assert error.value.orig.sqlstate == "23514"


@pytest.mark.parametrize("fault", ["revoked", "superseded"])
def test_raw_reserved_insert_rejects_stale_fax_custody(long_fax, fault):
    f = long_fax
    values = template(f)
    invalidate(f, fault)
    with pytest.raises(IntegrityError) as error:
        insert_admission(f, values)
    assert error.value.orig.sqlstate == "23514"


def invalidate(f, fault):
    if fault == "revoked":
        flow.revoke(f)
    else:
        command = {**f.fax_command, "expected_revision": flow.fax.read(f, f.client)["revision"],
            "idempotency_key": "source-superseded-" + str(uuid4()),
            "passage": "A newly reviewed invented fax passage retaining unknown DOB."}
        saved = flow.fax.signed_fixture.result(f.client.post(f.path, headers=f.headers(), json=command))
        assert saved["entry_id"] != f.fax_saved["entry_id"]


@pytest.mark.parametrize("fault", ["revoked", "superseded"])
@pytest.mark.parametrize("decision", ["accepted", "changes_requested"])
def test_raw_human_review_insert_rejects_revoked_or_superseded_fax(long_fax, fault, decision):
    f = long_fax
    chief = flow.claim(f, flow.reserve(f))
    flow.run_model(f, chief, delegate=True)
    with Session(f.case.engine) as s:
        child = s.scalar(select(ModelWorkAdmission).where(ModelWorkAdmission.workspace_id == f.wid,
            ModelWorkAdmission.kind == "private_handoff", ModelWorkAdmission.request_body["role"].astext == "scribe"))
        child_id = child.id
    flow.run_model(f, flow.claim(f, child_id))
    with Session(f.case.engine) as s:
        child = s.get(ModelWorkAdmission, child_id)
        attempt = s.get(WorkspaceHandoffAttempt, child.handoff_attempt_id)
        reply = s.get(WorkspaceReply, attempt.result_entry_id)
        values = dict(workspace_id=f.wid, box_id=f.box, owner_id=f.owner, handoff_id=attempt.handoff_id,
            attempt_id=attempt.id, result_entry_id=attempt.result_entry_id, agent_id=reply.agent_id,
            result_sha256=flow.sha(reply.content), source_sha256=child.source_sha256,
            source_versions=deepcopy(child.request_body["task_brief"]["source_versions"]),
            decision=decision, feedback="Keep unknown DOB" if decision == "changes_requested" else "",
            idempotency_key="raw-human-review-" + str(uuid4()), request_hash="a" * 64)
        # Prove our candidate binds current sources before invalidating custody.
        assert s.scalar(text("SELECT public.handoff_review_sources_current(:wid, :owner, :hid, CAST(:versions AS jsonb))"),
            {"wid": f.wid, "owner": f.owner, "hid": attempt.handoff_id,
             "versions": work.canonical(values["source_versions"]).decode()}) is True
        with s.begin_nested() as savepoint:
            w = s.get(EncounterWorkspace, f.wid)
            expected = w.revision
            w.revision += 1
            s.flush()
            s.execute(insert(WorkspaceHandoffReview).values(**values,
                expected_revision=expected, workspace_revision=w.revision))
            s.flush()
            savepoint.rollback()
        s.rollback()
    invalidate(f, fault)
    with Session(f.case.engine) as s:
        w = s.get(EncounterWorkspace, f.wid)
        values.update(expected_revision=w.revision, workspace_revision=w.revision + 1)
        w.revision += 1
        s.flush()
        with pytest.raises(IntegrityError) as error:
            s.execute(insert(WorkspaceHandoffReview).values(**values))
        assert error.value.orig.sqlstate == "23514"
        s.rollback()
        assert s.scalar(select(func.count()).select_from(WorkspaceHandoffReview)
            .where(WorkspaceHandoffReview.workspace_id == f.wid)) == 0
        assert ws.read(s, f.box, f.owner, f.wid)["note"] == f.before["note"]
