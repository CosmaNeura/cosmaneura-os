"""Closed wire projections and canonical commitments; no database or vendor I/O."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from cosmas_os.api.calendar_import_schemas import COMMAND, Review
from cosmas_os.application.calendar_imports import (
    _review_body,
    _selected_hash,
    item_hash,
    source_content,
    upload_body,
)
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.ports.calendar_imports import SnapshotPayload

WINDOW = dict(starts_on="2026-10-25", ends_on="2026-11-01", timezone="America/New_York")
ROW = dict(item_index=0, title="Invented visit", title_truncated=False,
           starts_at="2026-10-25T13:00:00Z", ends_at="2026-10-25T13:30:00Z", all_day=False, cancelled=False)
PAYLOAD = dict(imported_at="2026-10-25T12:00:00Z", reported_source="atlas_md", window=WINDOW,
               items=[ROW], total_events=1, matching_events=1, more=False, coverage="file_window_only")
UPLOAD = dict(action="upload", idempotency_key="invented-upload", byte_sha256="a" * 64,
              file_base64="QUJD", window=WINDOW, reported_source="atlas_md")


def test_canonical_request_never_contains_file_bytes_or_filename():
    command = COMMAND.validate_python(UPLOAD)
    assert command.action == "upload"
    body = upload_body("workspace", command.idempotency_key, command.byte_sha256,
                       command.reported_source, command.window.model_dump(mode="json"))
    assert set(body) == {"kind", "action", "workspace_id", "idempotency_key", "byte_sha256", "reported_source", "window"}
    assert "QUJD" not in repr(command) and "QUJD" not in str(command)
    assert payload_hash(body) != payload_hash({**body, "reported_source": "other_calendar"})
    assert payload_hash(body) != payload_hash({**body, "workspace_id": "other-workspace"})


@pytest.mark.parametrize("field,value", [
    ("filename", "invented.ics"), ("feed_url", "https://example.invalid/feed"),
    ("uid", "invented-uid"), ("continuation", "next"), ("file_base64", "A" * 1398105),
    ("reported_source", "verified_atlas_api"), ("byte_sha256", "A" * 64),
])
def test_unknown_or_unbounded_upload_fields_are_refused(field, value):
    with pytest.raises(ValidationError):
        COMMAND.validate_python({**UPLOAD, field: value})


@pytest.mark.parametrize("field,value", [
    ("title", "https://example.invalid/feed"), ("title", "encoded%20value"),
    ("title", "other &encoded-value;"), ("title", "hidden\u200bvalue"),
    ("title", "hidden\u00advalue"), ("title", "hidden\u061cvalue"),
    ("title", "fullwidth\uff0520value"), ("title", "fullwidth\uff06amp\uff1b"),
    ("title", "x" * 301), ("item_index", 1), ("cancelled", 1),
    ("title_truncated", True), ("starts_at", "2026-10-25T13:00:00-04:00"),
    ("ends_at", "2026-10-25T12:00:00Z"), ("UID", "invented-uid"),
])
def test_retained_item_subset_rejects_unchecked_or_hidden_fields(field, value):
    row = deepcopy(ROW)
    row[field] = value
    body = {**PAYLOAD, "items": [row]}
    with pytest.raises(ValidationError):
        SnapshotPayload.model_validate(body)


@pytest.mark.parametrize("field,value", [
    ("more", True), ("matching_events", 2), ("total_events", 0),
    ("coverage", "complete_atlas_schedule"), ("imported_at", "2026-10-25T12:00:00+00:00"),
    ("filename", "invented.ics"), ("raw", "BEGIN:VCALENDAR"),
])
def test_snapshot_shape_and_coverage_cannot_expand(field, value):
    with pytest.raises(ValidationError):
        SnapshotPayload.model_validate({**PAYLOAD, field: value})


def test_import_label_is_self_reported_and_hashes_bind_exact_reviewed_row():
    retained = SnapshotPayload.model_validate(PAYLOAD).model_dump(mode="json")
    content = source_content(retained, ROW)
    assert content.startswith("Imported calendar snapshot\nSource reported by user: Atlas.md\n")
    assert "does not verify patient or chart identity" in content
    other = {**retained, "reported_source": "other_calendar"}
    assert "Atlas.md" not in source_content(other, ROW)
    assert item_hash(ROW) != item_hash({**ROW, "title": "Changed"})
    assert _selected_hash("a" * 64, 0, item_hash(ROW)) != _selected_hash("b" * 64, 0, item_hash(ROW))
    body = _review_body("w", 1, "invented-key", "i", "a" * 64, 0, item_hash(ROW), True, True, True)
    assert body["action"] == "review" and body["workspace_id"] == "w"


@pytest.mark.parametrize("check", ["reviewed_visit", "reviewed_exact_summary", "reviewed_untrusted_source"])
@pytest.mark.parametrize("value", [False, 1, "true"])
def test_confirmation_requires_literal_true(check, value):
    body = dict(expected_revision=1, idempotency_key="invented-review", import_id="00000000-0000-0000-0000-000000000001",
        source_sha256="a" * 64, item_index=0, item_sha256="b" * 64,
        reviewed_visit=True, reviewed_exact_summary=True, reviewed_untrusted_source=True)
    body[check] = value
    with pytest.raises(ValidationError):
        Review.model_validate(body)
