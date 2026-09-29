"""Selected-brief source boundaries; no live patient, Core or model requests."""

import hashlib
import json
from copy import deepcopy
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest
from pydantic import ValidationError
from tests.unit.test_core_session_prep import receipt

from cosmas_os.api.session_prep_analysis_schemas import (
    ConversationAnalysisFields,
    SessionPrepAnalysis,
)
from cosmas_os.application import session_prep_analysis as analysis
from cosmas_os.application.session_prep import public_brief
from cosmas_os.application.workspace import WorkspaceError
from cosmas_os.ports.core_session_prep import CoreSessionPrepReceipt


def displayed(state="ready"):
    return public_brief(CoreSessionPrepReceipt.model_validate(receipt(state)))


def scoped(value, reader=None):
    workspace = NS(id=str(uuid4()), box_id=str(uuid4()), owner_id=str(uuid4()))
    chosen = analysis.anchor(value)
    command = {"role": "scribe", "team_revision": 3, "session_prep_analysis": chosen}
    sources = analysis.Sources(
        workspace.id, workspace.box_id, workspace.owner_id,
        "scribe", 3, chosen, reader or (lambda _: value),
    )
    return workspace, command, sources


def test_selection_is_an_opaque_exact_display_anchor_and_preserves_absence():
    value = displayed()
    value["prepared_brief"]["recap"]["text"] = "Invented café 🩺"
    selected = analysis.anchor(value)
    canonical = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    assert selected["snapshot_sha256"] == hashlib.sha256(canonical.encode()).hexdigest()
    assert "café" not in json.dumps(selected) and "prepared_brief" not in selected
    assert ConversationAnalysisFields.model_validate({}).model_dump(mode="json") == {}
    assert ConversationAnalysisFields.model_validate({"session_prep_analysis": selected}).model_dump(mode="json") == {"session_prep_analysis": selected}
    for field in ("freshness", "completeness", "generated_at"):
        changed = deepcopy(value)
        changed[field] = "different"
        assert analysis.anchor(changed) != selected


@pytest.mark.parametrize("change", [
    {"version": True}, {"consented": 1}, {"consented": False},
    {"brief_version": True}, {"brief_version": "1"},
    {"brief_version": 2**31}, {"clinical_text": "Do not accept client text"},
])
def test_selection_rejects_coercion_extra_content_and_implicit_consent(change):
    with pytest.raises(ValidationError):
        SessionPrepAnalysis.model_validate({**analysis.anchor(displayed()), **change})


def test_selection_rejects_null_and_mixed_analysis_even_when_other_is_null():
    with pytest.raises(ValidationError):
        ConversationAnalysisFields.model_validate({"session_prep_analysis": None})
    for field in ("membership_analysis", "inbox_analysis", "research_analysis"):
        with pytest.raises(ValidationError):
            ConversationAnalysisFields.model_validate({
                "session_prep_analysis": analysis.anchor(displayed()), field: None,
            })


def test_current_sources_bind_scope_and_own_an_immutable_copy():
    value = displayed()
    workspace, command, sources = scoped(value)
    with pytest.raises(WorkspaceError, match="source_changed"):
        sources.current(workspace, command)
    sources.refresh("before")
    assert sources.current(workspace, command) == value
    local = sources.current(workspace, command)
    local["prepared_brief"]["recap"]["text"] = "Changed return value"
    value["prepared_brief"]["recap"]["text"] = "Changed transport buffer"
    assert "Changed" not in sources.current(workspace, command)["prepared_brief"]["recap"]["text"]
    for field in ("id", "box_id", "owner_id"):
        changed = NS(**vars(workspace))
        setattr(changed, field, str(uuid4()))
        with pytest.raises(WorkspaceError, match="source_changed"):
            sources.current(changed, command)
    for field, value in (("role", "visit_prep"), ("team_revision", 4)):
        with pytest.raises(WorkspaceError, match="source_changed"):
            sources.current(workspace, {**command, field: value})


@pytest.mark.parametrize("failure", ["changed", "revoked", "repeated"])
def test_after_failure_clears_previous_content_and_cannot_be_retried(failure):
    value = displayed()
    calls = []

    def read(phase):
        calls.append(phase)
        if phase == "after":
            if failure == "revoked":
                raise WorkspaceError("session_prep_access_unavailable", 403)
            changed = deepcopy(value)
            changed["prepared_brief"]["recap"]["text"] = "New clinical summary"
            return changed
        return value

    workspace, command, sources = scoped(value, read)
    sources.refresh("before")
    with pytest.raises(WorkspaceError):
        sources.refresh("before" if failure == "repeated" else "after")
    assert sources.value is None
    with pytest.raises(WorkspaceError, match="source_changed"):
        sources.current(workspace, command)
    attempts = len(calls)
    with pytest.raises(WorkspaceError, match="session_prep_analysis_unavailable"):
        sources.refresh("after")
    assert len(calls) == attempts


def test_matching_after_read_remains_usable_without_sharing_mutable_selection():
    value = displayed()
    workspace, command, sources = scoped(value)
    selected = deepcopy(command["session_prep_analysis"])
    command["session_prep_analysis"]["brief_version"] = 99
    assert sources.chosen == selected
    command["session_prep_analysis"] = selected
    sources.refresh("before")
    sources.refresh("after")
    assert sources.current(workspace, command) == value


def test_passages_preserve_every_section_provenance_and_stable_scoped_citations():
    value = displayed("refreshing")
    value["brief_version"] = 501  # A Core brief version is not a workspace revision.
    value["completeness"] = "partial"
    source = value["sources"][0]["source_id"]
    brief = value["prepared_brief"]
    for key in ("trajectory_and_material_changes", "open_threads", "cautions"):
        brief[key] = [{"text": "Invented " + key, "source_refs": [source]}]
    patient_source = "b" * 64
    value["sources"].append({**value["sources"][0], "source_id": patient_source,
                            "source_class": "patient_reported_visit_prep"})
    brief["patient_reported"] = {"summary": "Invented patient concern", "source_refs": [patient_source]}
    value["sources"].append({"included": False, "source_class": "clinician_finalized_note",
                            "reason_code": "not_available"})
    wid = str(uuid4())
    passages = analysis.passages(value, wid)
    joined = "\n".join(source.content for source in passages)
    assert "Freshness: stale. Coverage: partial." in joined
    assert "derived excerpts, not the underlying clinical notes" in joined
    assert "Patient-reported Visit Prep" in joined and "not_available" in joined
    assert "Invented patient concern [2]" in joined
    for item in (brief["recap"], *[row for key in (
        "trajectory_and_material_changes", "talking_points", "open_threads", "cautions", "suggested_outline",
    ) for row in brief[key]]):
        assert item["text"] + " [1]" in joined
    assert all(source.kind == "session_prep" and source.revision == 501 for source in passages)
    assert passages == analysis.passages(value, wid)
    assert {source.entry_id for source in passages}.isdisjoint(
        {source.entry_id for source in analysis.passages(value, str(uuid4()))}
    )


def test_oversized_brief_is_refused_without_silently_truncating_selected_content():
    value = displayed()
    item = value["prepared_brief"]["talking_points"][0]
    item["text"] = "x" * 1000
    value["prepared_brief"]["talking_points"] = [deepcopy(item) for _ in range(8)]
    accepted = analysis.passages(value, str(uuid4()))
    assert sum(source.content.count("x" * 1000) for source in accepted) == 8
    for key in ("trajectory_and_material_changes", "open_threads", "cautions", "suggested_outline"):
        value["prepared_brief"][key] = [deepcopy(item) for _ in range(8)]
    with pytest.raises(WorkspaceError, match="session_prep_analysis_too_large"):
        analysis.passages(value, str(uuid4()))
    value = displayed()
    value["prepared_brief"]["recap"]["source_refs"] = ["c" * 64]
    with pytest.raises(WorkspaceError, match="source_changed"):
        analysis.passages(value, str(uuid4()))


@pytest.mark.parametrize("state", ["pending", "unavailable"])
def test_unavailable_brief_cannot_be_selected(state):
    with pytest.raises(WorkspaceError, match="session_prep_not_ready"):
        analysis.anchor(displayed(state))
