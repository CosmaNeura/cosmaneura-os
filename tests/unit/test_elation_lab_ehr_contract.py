"""Closed clinical command and cross-layer exact source serialization checks."""
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError
from tests.unit.test_elation_lab_read import REPORT, SCOPE, Harness

from cosmas_os.api.ehr_read_schemas import EHR_COMMAND, ReviewEhr
from cosmas_os.application.elation_lab_ehr import candidate_item, decoded, encoded, report_item
from cosmas_os.application.elation_lab_snapshot import prepare_lab_review
from cosmas_os.config import Settings
from cosmas_os.domain.hashing import canonical_json
from cosmas_os.ports.elation_lab_ehr import LabPrivateItem, LabReportItem

BODY = dict(provider="elation", action="lab_reports", workspace_id=str(UUID(int=6)), connection_id=str(UUID(int=3)),
    binding_sha256="a"*64, observation_id=str(UUID(int=9)), observation_sha256="b"*64,
    item_handle=str(UUID(int=10)), item_sha256="c"*64, idempotency_key="invented-lab-read-key")


@pytest.mark.parametrize("change", ["no_provider", "tebra", "athena", "fhir", "null_protocol", "no_workspace", "raw_report_id", "raw_patient_id", "next_page", "authorization_sha256", "no_parent"])
def test_lab_command_refuses_implicit_identity_or_client_authority(change):
    body: dict[str, Any] = dict(BODY)
    if change == "no_provider":
        del body["provider"]
    elif change in ("tebra", "athena"):
        body["provider"] = change
    elif change in ("fhir", "null_protocol"):
        body["protocol"] = "fhir" if change == "fhir" else None
    elif change == "no_workspace":
        del body["workspace_id"]
    elif change == "no_parent":
        del body["observation_id"]
    else:
        body[change] = "123456789012345678"
    with pytest.raises(ValidationError):
        EHR_COMMAND.validate_python(body)


def test_explicit_lab_actions_and_optional_capability_do_not_change_legacy_shape():
    for action in ("lab_reports", "lab_report"):
        parsed = EHR_COMMAND.validate_python(dict(BODY, action=action))
        assert parsed.model_dump(mode="json", exclude_none=True) == dict(BODY, action=action)
    legacy = EHR_COMMAND.validate_python(dict(action="status"))
    assert legacy.model_dump(mode="json", exclude_none=True) == dict(action="status")
    assert EHR_COMMAND.validate_python(dict(action="status", provider="elation", include_labs=True)).include_labs is True
    assert Settings().workspace_elation_labs_enabled is False


@pytest.mark.parametrize("body", [dict(action="status", include_labs=True), dict(action="status", provider="tebra", include_labs=True), dict(action="status", provider="elation", include_labs=False), dict(action="status", provider="elation", include_labs=None)])
def test_lab_status_is_explicit_and_closed(body):
    with pytest.raises(ValidationError):
        EHR_COMMAND.validate_python(body)


def test_report_review_retains_visit_and_other_three_explicit_fresh_checks():
    body: dict[str, Any] = {key: BODY[key] for key in ("provider", "observation_id", "observation_sha256", "item_handle", "item_sha256", "idempotency_key")}
    body.update(expected_revision=1, reviewed_visit=True, reviewed_patient_identity=True, reviewed_exact_snapshot=True, reviewed_untrusted_source=True)
    assert ReviewEhr.model_validate(body).reviewed_visit is True
    for flag in ("reviewed_visit", "reviewed_patient_identity", "reviewed_exact_snapshot", "reviewed_untrusted_source"):
        invalid = dict(body)
        del invalid[flag]
        with pytest.raises(ValidationError):
            ReviewEhr.model_validate(invalid)


def test_exact_page_and_reader_roundtrip_keeps_int64_unicode_and_recorded_values():
    h = Harness()
    page = h.reader.list_reports()
    assert decoded(encoded(page), page=True) == page
    item = LabPrivateItem(handle=UUID(int=10), report_id=str(REPORT["id"]), report_sha256=page.candidates[0].report_sha256)
    metadata = candidate_item(item, page.candidates[0])
    assert '123456789012345678' not in metadata["metadata_json"]
    assert '"patient"' not in metadata["metadata_json"] and '"physician"' not in metadata["metadata_json"]
    read = h.read(page)
    assert decoded(encoded(read)) == read
    prepared = prepare_lab_review(read, expected_scope=SCOPE, expected_source_sha256=read.source_sha256,
        expected_candidates_sha256=page.source_sha256, expected_report_id=REPORT["id"], authorize_read=lambda _: True)
    public = LabReportItem.model_validate(report_item(item, prepared))
    assert public.source_content == prepared.source_content
    assert public.report_json == canonical_json(REPORT)
    assert '123456789012345678' in public.report_json and '"001.2300"' in public.report_json
    assert public.changed_since_selection is False and public.warnings == prepared.warnings
    assert public.content_sha256 == prepared.source_content_sha256


@pytest.mark.parametrize("stamp", ["2026-10-26T12:00:00Z", "2026-10-26T12:00:00.000000+00:00", "2026-10-26T12:00:00.1+00:00"])
def test_private_reader_roundtrip_rejects_timestamp_spelling_that_changes_formatter(stamp):
    h = Harness()
    read = replace(h.read(), observed_at=datetime(2026,10,26,12,tzinfo=UTC))
    raw = deepcopy(__import__('json').loads(encoded(read)))
    raw["observed_at"] = stamp
    with pytest.raises(ValueError, match="noncanonical_lab_proof"):
        decoded(canonical_json(raw))
