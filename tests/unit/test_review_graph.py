"""A stale/wrong reviewer or duplicate decision cannot manufacture completion."""

import pytest
from lab.review_graph import ReviewGraph
from lab.store import LabError


def material(graph, key="draft1", *, body="Invented draft", **extra):
    return graph.add(key, kind="material", scope="encounter1", role="scribe", body=body, **extra)


def test_edit_revision_and_exact_reviewer_loop_survives_restart(tmp_path):
    g = ReviewGraph(tmp_path)
    first = material(g)
    args = dict(persona="provider", scope="encounter1", expected_sha256=first["sha256"],
        choice="request_edits", feedback="Keep the planned medication-list request unresolved.", request_id="review1")
    assert g.decide("draft1", **args) == g.decide("draft1", **args)
    assert not g.snapshot()["complete"]
    second = material(g, "draft2", body="Revised invented draft with the missing fact preserved", dependencies=("draft1",))
    g.supersede("draft1", "draft2")
    assert not g.snapshot()["complete"]
    g.decide("draft2", persona="provider", scope="encounter1", expected_sha256=second["sha256"],
        choice="sign_off", feedback="The revised material preserves the missing fact.", request_id="review2")
    snapshot = ReviewGraph(tmp_path).snapshot()
    assert snapshot["complete"]
    assert not snapshot["real_clinical_signoff"]
    assert len(snapshot["edges"]) == 2


@pytest.mark.parametrize("change", [{"persona": "nurse"}, {"scope": "other"}, {"expected_sha256": "0" * 64}])
def test_foreign_stale_and_wrong_role_review_refused(tmp_path, change):
    g = ReviewGraph(tmp_path)
    first = material(g)
    args = dict(persona="provider", scope="encounter1", expected_sha256=first["sha256"],
        choice="sign_off", feedback="Checked", request_id="review1")
    with pytest.raises(LabError, match="graph_review_binding_changed"):
        g.decide("draft1", **(args | change))
    assert not g.snapshot()["complete"]


def test_completed_review_does_not_transfer_to_new_material(tmp_path):
    g = ReviewGraph(tmp_path)
    first = material(g)
    g.decide("draft1", persona="provider", scope="encounter1", expected_sha256=first["sha256"],
        choice="sign_off", feedback="Checked", request_id="review1")
    material(g, "draft2", dependencies=("draft1",))
    assert not g.snapshot()["complete"]


def test_unchanged_material_cannot_claim_to_address_requested_edits(tmp_path):
    g = ReviewGraph(tmp_path)
    first = material(g)
    g.decide("draft1", persona="provider", scope="encounter1", expected_sha256=first["sha256"],
        choice="request_edits", feedback="Please add an owner", request_id="review1")
    material(g, "draft2", dependencies=("draft1",))
    with pytest.raises(LabError, match="graph_revision_binding_changed"):
        g.supersede("draft1", "draft2")
    assert not g.snapshot()["complete"]
