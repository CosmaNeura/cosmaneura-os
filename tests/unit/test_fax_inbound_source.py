"""Closed human passage commands; no provider read or document interpretation."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from cosmas_os.application import fax_inbound_source as source
from cosmas_os.application.workspace import WorkspaceError


def command(**changes):
    return {**dict(expected_revision=1, idempotency_key="review-source-1", operation_id=str(uuid4()),
        document_sha256="a" * 64, passage="Human reviewed café passage.\nSelected facts only.", page_numbers=[1],
        reviewed_patient=True, reviewed_exact_document=True, reviewed_exact_text=True,
        reviewed_untrusted_source=True), **changes}


def test_exact_utf8_human_text_and_explicit_coverage():
    value = source.FaxSourceReviewCommand.model_validate(command())
    assert value.passage == "Human reviewed café passage.\nSelected facts only."
    assert value.page_numbers == (1,)
    assert source.FaxSourceReviewCommand.model_validate(command(passage="x" * 12000)).passage == "x" * 12000


@pytest.mark.parametrize("change", [dict(expected_revision=True), dict(idempotency_key="short"),
    dict(operation_id="not-uuid"), dict(document_sha256="A" * 64), dict(passage=" "),
    dict(passage="x" * 12001), dict(passage="bad\x00text"), dict(passage="bad\x7ftext"),
    dict(page_numbers=[]), dict(page_numbers=[2, 1]), dict(page_numbers=[1, 1]),
    dict(page_numbers=[True]), dict(page_numbers=[0]), dict(page_numbers=[51]), dict(patient_link_id=str(uuid4())),
    dict(source_url="https://example.invalid"), dict(ocr=True)])
def test_closed_command_refuses_inference_aliases_or_unbounded_passage(change):
    with pytest.raises(ValidationError):
        source.FaxSourceReviewCommand.model_validate(command(**change))


@pytest.mark.parametrize("field", ["reviewed_patient", "reviewed_exact_document", "reviewed_exact_text", "reviewed_untrusted_source"])
@pytest.mark.parametrize("value", [False, 1, "true", None])
def test_human_acknowledgments_are_literal_true(field, value):
    with pytest.raises(ValidationError):
        source.FaxSourceReviewCommand.model_validate(command(**{field: value}))


def test_public_command_hash_binds_scope_key_text_pages_and_document_without_private_selection():
    box, owner, wid = (str(uuid4()) for _ in range(3))
    body = command()
    original = source.request_hash(box, owner, wid, body)
    for scope in [(str(uuid4()), owner, wid), (box, str(uuid4()), wid), (box, owner, str(uuid4()))]:
        assert source.request_hash(*scope, body) != original
    for changed in [dict(idempotency_key="review-source-2"), dict(passage="Changed exact text"),
                    dict(page_numbers=[2]), dict(document_sha256="b" * 64), dict(expected_revision=2)]:
        assert source.request_hash(box, owner, wid, {**body, **changed}) != original


def test_source_hash_binds_private_original_receipt_separately_from_public_review():
    args = [str(uuid4()), str(uuid4()), "a" * 64, "b" * 64, "c" * 64, "d" * 64, [1]]
    original = source.source_hash(*args)
    for index in range(7):
        changed = list(args)
        changed[index] = [2] if index == 6 else str(uuid4()) if index < 2 else "f" * 64
        assert source.source_hash(*changed) != original


def test_default_gate_and_binding_lifecycle_fail_closed(monkeypatch):
    monkeypatch.setattr(source, "runtime_settings", SimpleNamespace())
    for value in (None, SimpleNamespace(), SimpleNamespace(fax_inbound_source_available=False), SimpleNamespace(fax_inbound_source_available=1)):
        with pytest.raises(WorkspaceError, match="fax_inbound_source_disabled"):
            source._gate(value)
    source._gate(SimpleNamespace(fax_inbound_source_available=True))
    first, second = lambda s, grant: True, lambda s, grant: False
    assert source._binding_reader is None
    with source.install_binding_reader(first):
        assert source._binding_reader is first
        with source.install_binding_reader(second):
            assert source._binding_reader is second
        assert source._binding_reader is first
    assert source._binding_reader is None
