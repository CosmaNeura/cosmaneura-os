"""Actual owned PostgreSQL service effects, offline arrivals and failure recovery."""

from uuid import uuid4

import pytest
from lab.inbound_sandbox import InboundSandbox
from lab.inbound_workflow import PROVIDERS, SCENARIO_IDS, fixture, run_arrival, run_inbound
from lab.inbox_sandbox import exercise_inbox
from lab.store import LabError
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from tests.integration.test_virtual_clinic_lab import clinic as clinic

from cosmas_os.application import model_work
from cosmas_os.models import ModelWorkAdmission, WorkspaceEntry


@pytest.mark.parametrize("provider", PROVIDERS)
def test_incoming_work_uses_real_chief_research_and_reviewed_follow_up(clinic, provider):
    app, store = clinic
    result = run_arrival(app, store, "incoming-" + provider, provider)
    assert result["passed"], result["checks"]
    assert result["metrics"]["handoff_correct"] == result["metrics"]["handoff_total"] == 3
    assert result["metrics"]["duplicate_actions"] == 0
    assert result["metrics"]["time_to_first_useful_result_ms"] > 0
    assert result["metrics"]["persona_task_steps"] == len(result["persona_steps"]) == 6
    assert result["inbound_transport"] == "lab_only_reviewed_source_import"
    assert result["workflow"]["agent_approval_denied"]
    assert result["workflow"]["session_restart_recovered"]
    assert len({c["source_id"] for c in result["admitted_contexts"]}) == 1
    assert len({c["text_sha256"] for c in result["admitted_contexts"]}) == 1
    with Session(app.engine) as session:
        admissions = list(session.scalars(select(ModelWorkAdmission).where(ModelWorkAdmission.workspace_id == app.workspace)))
        assert len(admissions) == 5
        for admission in admissions:
            assert model_work.claim(session, app.box, app.owner, admission.id) is None
        assert len({r["result_entry_id"] for r in result["handoff_receipts"]}) == 3


@pytest.mark.parametrize("fault,reason", [
    ("attachment_missing", "attachment_missing_or_extra"), ("attachment_changed", "attachment_integrity_error"),
    ("not_reviewed", "human_source_review_required"), ("wrong_encounter", "reviewed_encounter_mapping_required"),
    ("wrong_patient", "reviewed_encounter_mapping_required"), ("same_event_changed", "immutable_event_conflict"),
    ("same_message_other_thread", "immutable_message_identity_conflict"), ("conflicting_revision", "source_not_current"),
])
def test_inbound_fault_does_not_publish_an_unreviewed_or_misattributed_source(clinic, fault, reason):
    app, store = clinic
    event, blobs = fixture(app, "google")
    ledger = InboundSandbox(app, store.root / "arrival")
    ledger.arrive(event)
    with Session(app.engine) as session:
        before = session.scalar(select(func.count()).select_from(WorkspaceEntry).where(WorkspaceEntry.workspace_id == app.workspace))
    with pytest.raises(LabError, match=reason):
        if fault == "wrong_encounter":
            ledger.arrive(event.model_copy(update={"event_id": uuid4(), "workspace_id": uuid4()}))
        elif fault == "wrong_patient":
            ledger.arrive(event.model_copy(update={"event_id": uuid4(), "patient_link_id": uuid4()}))
        elif fault == "same_event_changed":
            ledger.arrive(event.model_copy(update={"text": "Changed immutable event"}))
        elif fault == "same_message_other_thread":
            ledger.arrive(event.model_copy(update={"event_id": uuid4(), "thread_id": uuid4()}))
        else:
            if fault == "attachment_missing":
                blobs = {}
            elif fault == "attachment_changed":
                blobs = {"administrative-pdf": b"different attachment"}
            elif fault == "conflicting_revision":
                assert ledger.arrive(event.model_copy(update={"event_id": uuid4(), "text": "Conflicting same-time update"})) == "conflict"
            ledger.import_reviewed(event, blobs, reviewed=fault != "not_reviewed")
    with Session(app.engine) as session:
        assert session.scalar(select(func.count()).select_from(WorkspaceEntry).where(WorkspaceEntry.workspace_id == app.workspace)) == before
        assert session.scalar(select(func.count()).select_from(ModelWorkAdmission).where(ModelWorkAdmission.workspace_id == app.workspace)) == 0


def test_actual_secure_inbox_orders_sources_flags_attachments_and_closes_only_after_review(clinic):
    result = exercise_inbox(clinic[0])
    assert result["passed"], result
    assert result["source_versions"] == 4
    assert result["provider_reads"] == 8
    assert result["external_actions"] == 0


def test_distinct_delivery_ids_reuse_one_source_and_old_delivery_cannot_be_imported(clinic):
    from datetime import timedelta

    app, store = clinic
    event, blobs = fixture(app, "srfax")
    ledger = InboundSandbox(app, store.root / "separate-deliveries")
    ledger.arrive(event)
    first = ledger.import_reviewed(event, blobs, reviewed=True)
    redelivery = event.model_copy(update={"event_id": uuid4()})
    assert ledger.arrive(redelivery) == "current"
    assert ledger.import_reviewed(redelivery, blobs, reviewed=True) == first
    older = event.model_copy(update={"event_id": uuid4(), "modified_at": event.modified_at - timedelta(seconds=1)})
    assert ledger.arrive(older) == "older"
    with pytest.raises(LabError, match="source_not_current"):
        ledger.import_reviewed(older, blobs, reviewed=True)


def test_missing_attachment_arrival_remains_recoverable_without_placeholder_or_redelivery(clinic):
    app, store = clinic
    event, blobs = fixture(app, "documo")
    ledger = InboundSandbox(app, store.root / "missing-file")
    ledger.arrive(event)
    with pytest.raises(LabError, match="attachment_missing_or_extra"):
        ledger.import_reviewed(event, {}, reviewed=True)
    reopened = InboundSandbox(app, store.root / "missing-file")
    assert reopened.arrive(event) == "duplicate"
    receipt = reopened.import_reviewed(event, blobs, reviewed=True)
    assert reopened.import_reviewed(event, blobs, reviewed=True) == receipt
    with Session(app.engine) as session:
        assert session.scalar(select(func.count()).select_from(WorkspaceEntry).where(
            WorkspaceEntry.workspace_id == app.workspace, WorkspaceEntry.idempotency_key == "inbound-" + event.source_hash())) == 1


def test_complete_inbound_matrix_keeps_acceptance_separate_from_delivery(clinic):
    from datetime import UTC, datetime

    from lab.report import render

    result = run_inbound(*clinic, "inbound-matrix")
    assert result["passed"], result["failures"]
    assert set(SCENARIO_IDS) <= set(result["checks"])
    assert len(result["inbound_scenarios"]) == 4
    for fax in result["fax_receipts"]:
        assert sum(call["action"] == "submit" for call in fax["requests"]) == 1
        ticket = fax["ticket"]
        assert ticket["state"] == "approved"
        if fax["scenario"] == "lost_reply":
            assert (ticket["acceptance"], ticket["transport"]) == ("unconfirmed", "not_observed")
        elif fax["scenario"] == "failed":
            assert (ticket["acceptance"], ticket["transport"]) == ("accepted", "failed")
        else:
            assert (ticket["acceptance"], ticket["transport"]) == ("accepted", "delivered")
        assert fax["receipt_stages"][0]["transport"] == "not_observed"
    render(clinic[1].root, {"episodes": [result], "coverage": [], "limits": result["limits"], "mode": "replay",
        "model": "deterministic; no public model or provider", "status": "passed", "concurrency": 3,
        "fault": "duplicate and lost replies", "source": {"commit": "synthetic-test", "source_sha256": "a" * 64},
        "started_at": datetime.now(UTC).isoformat()})
    html = (clinic[1].root / "report.html").read_text()
    assert "First useful Chief plan:" in html and "Handoffs correct: 3/3" in html
    assert "unconfirmed · not_observed" in html and "accepted · delivered" in html
    assert "Browser clicks" in html or "browser clicks" in html
