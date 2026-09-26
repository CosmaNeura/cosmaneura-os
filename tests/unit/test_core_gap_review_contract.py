import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from cosmas_os.ports.core_notes import CoreDraftReceipt

FIXTURE = Path(__file__).parents[1] / "fixtures/capture_gap_draft.json"


def test_consumer_pins_actual_core_gap_draft_fixture():
    draft = json.loads(FIXTURE.read_text())["draft"]
    assert CoreDraftReceipt.model_validate(draft).model_dump(mode="json") == draft


@pytest.mark.parametrize("mutation", ["duplicate", "missing", "order", "false", "integer", "extra"])
def test_invalid_gap_review_evidence_is_rejected(mutation):
    draft = json.loads(FIXTURE.read_text())["draft"]
    CoreDraftReceipt.model_validate(draft)
    evidence = draft["capture_gap_review"]
    if mutation == "duplicate":
        evidence["observations"].append(copy.deepcopy(evidence["observations"][0]))
    elif mutation == "missing":
        evidence["observations"] = []
    elif mutation == "order":
        evidence["observations"][0]["observed_at"] = "2100-01-01T00:00:00Z"
    elif mutation == "extra":
        evidence["inferred_gap_duration"] = 30
    else:
        evidence["review_required"] = False if mutation == "false" else 1
    with pytest.raises(ValidationError):
        CoreDraftReceipt.model_validate(draft)
