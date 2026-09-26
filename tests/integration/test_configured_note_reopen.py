"""Reviewed-English lineage survives the actual private note/review HTTP flow."""
from tests.integration.test_core_note_review import capture_case as _capture_case
from tests.integration.test_core_note_review import case as _case
from tests.integration.test_core_note_review import reviewed

from cosmas_os.ports.core_notes import CoreDraftReceipt, CoreDraftReference

capture_case, case = _capture_case, _case


def test_reviewed_source_is_saved_reviewed_and_reopened(case):
    f = case
    source = {"kind": "reviewed_english", "source_version": 1,
              "working_transcript_id": f.draft["scribe_source_id"], "working_version": 2}
    f.draft["reviewed_source"] = source
    f.source = CoreDraftReference.from_draft(CoreDraftReceipt.model_validate(f.draft)).model_dump(mode="json")
    workspace = reviewed(f)
    note = workspace["note"]["latest"]
    assert note["core_source"]["reviewed_source"] == source and note["review"]
    result = f.client.get(f.root, headers={"Authorization": "Bearer " + f.token()})
    assert result.status_code == 200, result.text
    assert result.json()["note"]["latest"]["core_source"]["reviewed_source"] == source
    assert result.json()["note"]["latest"]["review"]["id"] == note["review"]["id"]
