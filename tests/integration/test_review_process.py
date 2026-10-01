"""Operational review loops publish real drafts; their agents cannot approve care."""

import pytest
from lab.application import Application
from lab.cases import Case
from lab.review_process import INPUTS, run_reviews
from tests.integration.test_virtual_clinic_lab import clinic as clinic


@pytest.mark.parametrize("workers", [1, 3])
def test_three_reviewer_edit_loops_use_exact_durable_handoffs(clinic, workers):
    original, store = clinic
    app = Application(original.engine, Case("review_loops", "Invented reviewer process", "Private draft review", "", (), inputs=INPUTS),
        lambda role, kind, **v: store.event("review", role, kind, **v))
    result = run_reviews(app, store, "review", None, concurrency=workers)
    assert result["passed"], result["failures"]
    graph = result["review_graph"]
    assert graph["complete"] and not graph["real_clinical_signoff"]
    assert len(result["handoff_receipts"]) == 6
    assert len([edge for edge in graph["edges"] if edge["relation"] == "revised_after_feedback"]) == 3
    for node in graph["nodes"]:
        if node["kind"] == "material":
            assert node["application_receipt"]["entry_id"]
            assert node["decisions"][0]["material_sha256"] == node["sha256"]
    assert result["application"]["external_effects"] == 0
