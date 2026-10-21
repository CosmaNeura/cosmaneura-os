"""Current Core creator-edit receipts retain originals and exact edit lineage.

The invented receipt matches Core69's scribe_creator_edit_consumer_test.py.
It is data, not an import of Core source or a live receiver call.
"""

from copy import deepcopy
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError
from tests.unit.test_core_capture_operations import exercise

from cosmas_os.application import scribe_source
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.creator_review import CreatorReviewView


def edited_view(session_id=None) -> dict[str, Any]:
    session_id, segment_id, speaker_id, working_id = (
        str(session_id or uuid4()), str(uuid4()), str(uuid4()), str(uuid4())
    )
    segment = dict(
        source_segment_id=segment_id, source_segment_version=1, source_locale="en-US",
        speaker_id=speaker_id, speaker_role="patient", start_ms=0, end_ms=1000,
    )
    return dict(
        schema_version="1.0", session_id=session_id, status="transcript_ready",
        source=dict(
            schema_version="1.0", source_transcript_version=1, language_mode="en-US+es-US",
            transcription_adapter_id="synthetic", transcription_model_profile_id="synthetic",
            normalization_profile_id="synthetic", duration_ms=1000,
            segments=[dict(**segment, content="Synthetic wrist soreness.", locale_confidence=0.9)],
        ),
        working=dict(
            schema_version="1.0", working_transcript_id=working_id, working_transcript_version=2,
            source_transcript_version=1,
            segments=[dict(
                **{**segment, "speaker_role": "clinician"}, resolution="english_source",
                content="Synthetic mild wrist soreness.", translation_id=None,
                translation_version=None, translation_review_id=None,
            )], blockers=[], note_ready=True,
        ),
        review_queue=dict(
            schema_version="1.0", session_id=session_id, source_transcript_version=1,
            working_transcript_id=working_id, working_transcript_version=2,
            status="complete", items=[],
        ), translation_progress=[], editing_allowed=True,
        review_edits=[dict(
            edit_id=str(uuid4()), working_transcript_version=2,
            created_at="2026-10-21T00:00:00+00:00",
            request=dict(
                schema_version="1.0", expected_source_transcript_version=1,
                expected_working_transcript_id=working_id, expected_working_transcript_version=1,
                corrections=[dict(
                    source_segment_id=segment_id, expected_source_segment_version=1,
                    content="Synthetic mild wrist soreness.",
                )], speakers=[dict(
                    speaker_id=speaker_id, role="clinician", display_name="Synthetic Provider",
                    detail=None,
                )],
            ),
        )],
    )


def test_current_core_edited_view_retains_immutable_source_and_exact_history():
    value = edited_view()
    parsed = CreatorReviewView.model_validate(value)
    assert parsed.source is not None and parsed.working is not None
    assert parsed.source.segments[0].content == "Synthetic wrist soreness."
    assert parsed.source.segments[0].speaker_role == "patient"
    assert parsed.working.segments[0].content == "Synthetic mild wrist soreness."
    assert parsed.working.segments[0].speaker_role == "clinician"
    assert parsed.model_dump(mode="json")["review_edits"] == [
        {**value["review_edits"][0], "created_at": "2026-10-21T00:00:00Z"}
    ]


def test_current_core_edited_receipt_crosses_exact_admitted_transport_once():
    def current_core(response):
        response["receipt"].clear()
        response["receipt"].update(edited_view(response_session))

    # exercise supplies the actual admitted session; retain it before replacing
    # the invented receipt, so its ordinary scope and envelope proof still run.
    def retain_session(response):
        nonlocal response_session
        response_session = response["receipt"]["session_id"]
        current_core(response)

    response_session = None
    result = exercise("creator_review", retain_session)
    assert isinstance(result, CreatorReviewView)
    assert result.source is not None and result.working is not None
    assert result.source.segments[0].content == "Synthetic wrist soreness."
    assert result.working.segments[0].content == "Synthetic mild wrist soreness."


@pytest.mark.parametrize("fault", [
    "missing_history", "wrong_text", "wrong_role", "wrong_source", "future_version",
    "foreign_speaker", "foreign_working", "foreign_segment", "segment_version",
    "duplicate_edit", "unknown_field", "naive_timestamp", "nul_text", "overlong_text",
])
def test_changed_projection_requires_exact_current_edit_evidence(fault):
    value = edited_view()
    edit = value["review_edits"][0]
    if fault == "missing_history":
        value.pop("review_edits")
    elif fault == "wrong_text":
        value["working"]["segments"][0]["content"] = "Unevidenced synthetic assertion"
    elif fault == "wrong_role":
        value["working"]["segments"][0]["speaker_role"] = "other"
    elif fault == "wrong_source":
        edit["request"]["expected_source_transcript_version"] = 2
    elif fault == "future_version":
        edit["working_transcript_version"] = 3
        edit["request"]["expected_working_transcript_version"] = 2
    elif fault == "foreign_speaker":
        edit["request"]["speakers"][0]["speaker_id"] = str(uuid4())
    elif fault == "foreign_working":
        edit["request"]["expected_working_transcript_id"] = str(uuid4())
    elif fault == "foreign_segment":
        edit["request"]["corrections"][0]["source_segment_id"] = str(uuid4())
    elif fault == "segment_version":
        edit["request"]["corrections"][0]["expected_source_segment_version"] = 2
    elif fault == "duplicate_edit":
        value["review_edits"].append(deepcopy(edit))
    elif fault == "unknown_field":
        edit["request"]["untrusted_permission"] = True
    elif fault == "naive_timestamp":
        edit["created_at"] = "2026-10-21T00:00:00"
    elif fault == "nul_text":
        edit["request"]["corrections"][0]["content"] = "Synthetic\x00text"
    else:
        edit["request"]["corrections"][0]["content"] = "x" * 100001
    with pytest.raises(ValidationError):
        CreatorReviewView.model_validate(value)


def test_latest_validated_edit_projects_without_replacing_original():
    value = edited_view()
    second = deepcopy(value["review_edits"][0])
    second.update(edit_id=str(uuid4()), working_transcript_version=3)
    second["request"]["expected_working_transcript_version"] = 2
    second["request"]["corrections"][0]["content"] = "Synthetic revised wrist soreness."
    second["request"]["speakers"][0]["role"] = "patient"
    value["review_edits"].append(second)
    value["working"]["working_transcript_version"] = 3
    value["review_queue"]["working_transcript_version"] = 3
    value["working"]["segments"][0].update(
        content="Synthetic revised wrist soreness.", speaker_role="patient",
    )
    parsed = CreatorReviewView.model_validate(value)
    assert parsed.source is not None and parsed.working is not None
    assert parsed.source.segments[0].content == "Synthetic wrist soreness."
    assert parsed.working.segments[0].content == second["request"]["corrections"][0]["content"]
    value["review_edits"].reverse()
    with pytest.raises(ValidationError):
        CreatorReviewView.model_validate(value)


def test_edited_receipt_still_rejects_replacement_session_at_transport_boundary():
    def wrong_session(response):
        response["receipt"].clear()
        response["receipt"].update(edited_view())
    with pytest.raises(ConnectorUnavailable, match="^core_capture_receipt_invalid$"):
        exercise("creator_review", wrong_session)


def test_legacy_serialization_remains_unchanged_and_edit_capability_alone_is_valid():
    value = edited_view()
    value.pop("review_edits")
    value.pop("editing_allowed")
    value["working"]["segments"][0].update(content="Synthetic wrist soreness.", speaker_role="patient")
    result = CreatorReviewView.model_validate(value).model_dump(mode="json")
    assert "review_edits" not in result and "editing_allowed" not in result
    value["editing_allowed"] = True
    assert CreatorReviewView.model_validate(value).model_dump(mode="json")["editing_allowed"] is True


def test_saved_team_source_uses_corrected_words_and_full_exact_review_fingerprint():
    value = edited_view()
    view = CreatorReviewView.model_validate(value)
    selected = scribe_source.selection(view)
    assert selected is not None
    content = scribe_source.packet_content(view, selected)
    assert "Synthetic mild wrist soreness." in content
    assert "clinician" in content and "version 2" in content
    assert selected.snapshot_sha256 in content
    assert value["source"]["segments"][0]["content"] == "Synthetic wrist soreness."
    changed = deepcopy(value)
    changed["review_edits"][0]["edit_id"] = str(uuid4())
    assert scribe_source.selection(CreatorReviewView.model_validate(changed)) != selected
