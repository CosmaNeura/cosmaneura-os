"""The deployed Scribe advertises editing support on unedited source reviews."""

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from tests.unit.test_core_capture_operations import exercise

from cosmas_os.ports.creator_review import CreatorReviewView

FIXTURES = json.loads((Path(__file__).parents[1] / "fixtures" / "creator_review.json").read_text())


def ready():
    return copy.deepcopy(FIXTURES["ready"])


def english_ready():
    wire = ready()
    wire["source"]["language_mode"] = "en-US"
    for original, projected in zip(
        wire["source"]["segments"], wire["working"]["segments"], strict=True
    ):
        original["source_locale"] = projected["source_locale"] = "en-US"
        original["content"] = projected["content"] = "Invented sleep diary discussion."
        projected["resolution"] = "english_source"
        for field in ("translation_id", "translation_version", "translation_review_id"):
            projected[field] = None
    return wire


def test_accepts_english_source_with_deployed_capability():
    wire = english_ready()
    wire["editing_allowed"] = True
    assert CreatorReviewView.model_validate(wire).working.note_ready


def test_core_bridge_releases_same_review_with_capability():
    def completed_review(envelope):
        session = envelope["receipt"]["session_id"]
        wire = english_ready()
        wire["session_id"] = wire["review_queue"]["session_id"] = session
        wire["editing_allowed"] = True
        envelope["receipt"].clear()
        envelope["receipt"].update(wire)

    result = exercise("creator_review", completed_review)
    assert result.editing_allowed is True
    assert result.working.note_ready


def test_accepts_deployed_capability_without_changing_source():
    legacy = CreatorReviewView.model_validate(ready())
    wire = ready()
    wire["editing_allowed"] = True
    current = CreatorReviewView.model_validate(wire)
    assert current.source == legacy.source
    assert current.working == legacy.working
    assert current.review_queue == legacy.review_queue
    assert current.model_dump(mode="json")["editing_allowed"] is True
    assert current.model_dump(mode="json", exclude={"editing_allowed"}) == legacy.model_dump(
        mode="json"
    )


def test_preserves_legacy_wire_without_capability():
    assert "editing_allowed" not in CreatorReviewView.model_validate(ready()).model_dump(
        mode="json"
    )


@pytest.mark.parametrize("value", [False, 1, "true"])
def test_rejects_false_or_non_boolean_capability(value):
    wire = ready()
    wire["editing_allowed"] = value
    with pytest.raises(ValidationError):
        CreatorReviewView.model_validate(wire)


def test_rejects_capability_without_a_current_source():
    wire = {
        "schema_version": "1.0",
        "session_id": FIXTURES["ready"]["session_id"],
        "status": "processing",
        "source": None,
        "working": None,
        "review_queue": None,
        "translation_progress": [],
        "editing_allowed": True,
    }
    with pytest.raises(ValidationError):
        CreatorReviewView.model_validate(wire)


def test_capability_does_not_allow_changed_english_source():
    wire = english_ready()
    CreatorReviewView.model_validate(wire)
    wire["editing_allowed"] = True
    original = next(
        segment for segment in wire["source"]["segments"] if segment["source_locale"] == "en-US"
    )
    projected = next(
        segment
        for segment in wire["working"]["segments"]
        if segment["source_segment_id"] == original["source_segment_id"]
    )
    projected["content"] = "Invented tampered wording."
    with pytest.raises(ValidationError):
        CreatorReviewView.model_validate(wire)


@pytest.mark.parametrize("field", ["unrecognized_capability", "review_edits"])
def test_rejects_other_fields_and_unsupported_edit_histories(field):
    wire = ready()
    wire["editing_allowed"] = True
    wire[field] = [{}]
    with pytest.raises(ValidationError) as error:
        CreatorReviewView.model_validate(wire)
    assert any(
        item["type"] == "extra_forbidden" for item in error.value.errors(include_input=False)
    )
