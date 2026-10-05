"""Explicit human passage custody, never OCR, PDF acquisition, note or F8 writes.

Only a reviewed passage is model-readable. The immutable private PDF remains
bound to the original one-shot acquisition; every current check is DB-only.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from contextlib import contextmanager
from typing import Annotated
from uuid import UUID

from pydantic import Field, StrictBool, StrictInt, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cosmas_os.application import fax_inbound as ledger
from cosmas_os.application import model_work
from cosmas_os.application import workspace as ws
from cosmas_os.config import settings as runtime_settings
from cosmas_os.fax_inbound_models import (
    FaxInboundAttempt,
    FaxInboundGrant,
    FaxInboundImage,
    FaxInboundOutcome,
)
from cosmas_os.fax_source_models import FaxInboundSourceReview
from cosmas_os.models import ActionRevision, WorkspaceEntry
from cosmas_os.ports.scribe_capture import ProtectedModel
from cosmas_os.ports.vendor_connectors import digest

SOURCE_KIND = "fax_inbound_source"
SOURCE_LABEL = "Received practice fax passage (human reviewed)"
MAX_PASSAGE = 12000
_binding_reader: Callable[[Session, FaxInboundGrant], bool] | None = None
_HASH = re.compile(r"^[a-f0-9]{64}$")


class FaxSourceReviewCommand(ProtectedModel):
    expected_revision: StrictInt = Field(ge=1, le=500)
    idempotency_key: str = Field(strict=True, pattern=r"^[A-Za-z0-9:_-]{8,100}$")
    operation_id: UUID
    document_sha256: str = Field(strict=True, pattern=r"^[a-f0-9]{64}$")
    passage: str = Field(strict=True, min_length=1, max_length=MAX_PASSAGE)
    page_numbers: tuple[Annotated[int, Field(strict=True, ge=1, le=50)], ...] = Field(min_length=1, max_length=50)
    reviewed_patient: StrictBool
    reviewed_exact_document: StrictBool
    reviewed_exact_text: StrictBool
    reviewed_untrusted_source: StrictBool

    @field_validator("passage")
    @classmethod
    def bounded_text(cls, value):
        if not value.strip() or any(ord(c) < 32 and c not in "\n\t" or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in value):
            raise ValueError("invalid reviewed passage")
        return value

    @field_validator("page_numbers")
    @classmethod
    def selected_pages(cls, value):
        if tuple(sorted(set(value))) != value:
            raise ValueError("pages must be explicit, ordered and unique")
        return value

    @field_validator("reviewed_patient", "reviewed_exact_document", "reviewed_exact_text", "reviewed_untrusted_source")
    @classmethod
    def human_ack(cls, value):
        if value is not True:
            raise ValueError("explicit human review required")
        return value


@contextmanager
def install_binding_reader(reader):
    """Lifecycle-owned managed runtime.current; no refresh/network/new Session."""
    global _binding_reader
    previous, _binding_reader = _binding_reader, reader
    try:
        yield
    finally:
        _binding_reader = previous


def _gate(configuration=None):
    configuration = runtime_settings if configuration is None else configuration
    if getattr(configuration, "fax_inbound_source_available", False) is not True:
        raise ws.WorkspaceError("fax_inbound_source_disabled", 403)


def request_hash(box, owner, workspace_id, command):
    body = command.model_dump(mode="json") if isinstance(command, FaxSourceReviewCommand) else command
    return digest("cosmas-fax-inbound-source-command.v1", {"scope": {"box_id": box, "owner_id": owner, "workspace_id": workspace_id}, "request": body})


def source_hash(operation_id, grant_id, document_sha256, outcome_sha256, installation_sha256, content_sha256, page_numbers):
    return digest("cosmas-fax-inbound-reviewed-source.v1", dict(operation_id=operation_id, grant_id=grant_id,
        document_sha256=document_sha256, outcome_sha256=outcome_sha256,
        installation_sha256=installation_sha256, content_sha256=content_sha256,
        page_numbers=list(page_numbers), coverage="human_selected_passage", extraction="human_entered_no_ocr"))


def outcome_hash(outcome):
    return digest("cosmas-fax-inbound-outcome.v1", dict(operation_id=outcome.operation_id,
        state=outcome.state, document_sha256=outcome.document_sha256,
        document_ciphertext_sha256=outcome.document_ciphertext_sha256,
        document_byte_length=outcome.document_byte_length, document_key_id=outcome.document_key_id,
        pages=outcome.pages))


def _document_history(s, box, owner, operation_id):
    from cosmas_os.domain.hashing import payload_hash
    from cosmas_os.fax_inbound_models import FaxInboundDispatch
    from cosmas_os.models import Decision, Operation
    claim = s.get(FaxInboundAttempt, operation_id)
    outcome = s.get(FaxInboundOutcome, operation_id)
    revision = s.get(FaxInboundImage, claim.image_id) if claim else None
    grant = s.get(FaxInboundGrant, revision.grant_id) if revision else None
    action = s.get(ActionRevision, revision.revision_id) if revision else None
    operation = s.get(Operation, operation_id)
    if any(row is None for row in (claim, outcome, revision, grant, action, operation)):
        raise ws.WorkspaceError("fax_inbound_source_unavailable", 404)
    if any((row.box_id, row.owner_id) != (box, owner) for row in (claim, outcome, revision, grant)):
        raise ws.WorkspaceError("fax_inbound_source_unavailable", 404)
    try:
        obs, scope, fax = ledger.source(s, box, owner, revision.observation_id, revision.source_sha256)
        if (outcome.state != "acquired" or type(outcome.document) is not bytes
            or not 1 <= outcome.document_byte_length <= 1048576
            or len(outcome.document) != outcome.document_byte_length + 28
            or hashlib.sha256(outcome.document).hexdigest() != outcome.document_ciphertext_sha256
            or revision.operation_id != operation_id
            or claim.ticket_id != revision.ticket_id or claim.account_sha256 != grant.account_sha256
            or claim.locator_sha256 != ledger.commitment({"locator": fax.locator})
            or obs.grant_id != grant.id or scope.selection != ledger.installation(grant.installation).selection
            or grant.installation_sha256 != ledger.commitment(grant.installation)
            or revision.source_sha256 != fax.key() or outcome.pages != fax.pages
            or action.box_id != box or action.ticket_id != revision.ticket_id
            or action.payload != {"contract_version": 1, "fax_inbound_image_id": revision.id, "source_sha256": revision.source_sha256}
            or action.payload_hash != payload_hash(action.payload) or action.payload_hash != revision.payload_sha256
            or operation.box_id != box or operation.ticket_id != revision.ticket_id
            or operation.action_revision_id != revision.revision_id or operation.adapter != ledger.ADAPTER
            or operation.status != "succeeded" or operation.attempt_count != 1
            or operation.result_receipt_hash != outcome.document_sha256
            or s.get(FaxInboundDispatch, operation_id) is None
            or not s.scalar(select(Decision.id).where(Decision.box_id == box,
                Decision.ticket_id == revision.ticket_id, Decision.action_revision_id == revision.revision_id,
                Decision.actor_principal_id == owner, Decision.kind == "approve"))
            ):
            raise ValueError
    except Exception:
        raise ws.WorkspaceError("fax_inbound_source_invalid") from None
    return claim, outcome, revision, grant


def _current_document(s, w, operation_id, *, configuration=None):
    _gate(configuration)
    if _binding_reader is None:
        raise ws.WorkspaceError("fax_inbound_source_unavailable")
    try:
        document = ledger.document(s, w.box_id, w.owner_id, operation_id, current=_binding_reader)
    except ws.WorkspaceError:
        raise
    except Exception:
        raise ws.WorkspaceError("fax_inbound_source_unavailable") from None
    rows = _document_history(s, w.box_id, w.owner_id, operation_id)
    if hashlib.sha256(document).hexdigest() != rows[1].document_sha256:
        raise ws.WorkspaceError("fax_inbound_source_invalid")
    return rows


def _command(review, passage):
    return FaxSourceReviewCommand(expected_revision=review.expected_revision, idempotency_key=review.idempotency_key,
        operation_id=review.operation_id, document_sha256=review.document_sha256, passage=passage,
        page_numbers=tuple(review.page_numbers), reviewed_patient=review.reviewed_patient,
        reviewed_exact_document=review.reviewed_exact_document, reviewed_exact_text=review.reviewed_exact_text,
        reviewed_untrusted_source=review.reviewed_untrusted_source)


def historical_source(s, w, entry_id):
    model_work.read_workspace(s, w.box_id, w.owner_id, w.id)
    entry = s.get(WorkspaceEntry, entry_id)
    review = s.scalar(select(FaxInboundSourceReview).where(FaxInboundSourceReview.entry_id == entry_id))
    if entry is None or review is None or entry.kind != SOURCE_KIND or (entry.workspace_id, entry.box_id, entry.actor_id) != (w.id, w.box_id, w.owner_id):
        raise ws.WorkspaceError("fax_inbound_source_unavailable", 404)
    _, outcome, _, grant = _document_history(s, w.box_id, w.owner_id, review.operation_id)
    try:
        command = _command(review, entry.content)
        if ((review.workspace_id, review.box_id, review.owner_id, review.patient_link_id) != (w.id, w.box_id, w.owner_id, w.patient_link_id)
            or review.workspace_revision != entry.revision or review.workspace_revision != review.expected_revision+1 or not 1 <= review.ordinal <= 500
            or review.grant_id != grant.id or review.document_sha256 != outcome.document_sha256
            or review.outcome_sha256 != outcome_hash(outcome) or review.installation_sha256 != grant.installation_sha256
            or max(review.page_numbers) > outcome.pages or review.content_sha256 != hashlib.sha256(entry.content.encode()).hexdigest()
            or review.request_sha256 != request_hash(w.box_id, w.owner_id, w.id, command)
            or entry.request_hash != review.request_sha256 or entry.idempotency_key != review.idempotency_key
            or entry.source_label != SOURCE_LABEL or review.source_sha256 != source_hash(review.operation_id, review.grant_id,
                review.document_sha256, review.outcome_sha256, review.installation_sha256, review.content_sha256, review.page_numbers)):
            raise ValueError
    except Exception:
        raise ws.WorkspaceError("fax_inbound_source_invalid") from None
    return entry


def validate_selected_source(s, w, entry_id, *, configuration=None):
    model_work.read_workspace(s, w.box_id, w.owner_id, w.id)
    entry = historical_source(s, w, entry_id)
    review = s.scalar(select(FaxInboundSourceReview).where(FaxInboundSourceReview.entry_id == entry_id))
    _current_document(s, w, review.operation_id, configuration=configuration)
    if s.scalar(select(FaxInboundSourceReview.id).where(FaxInboundSourceReview.workspace_id == w.id,
        FaxInboundSourceReview.operation_id == review.operation_id, FaxInboundSourceReview.ordinal > review.ordinal)):
        raise ws.WorkspaceError("fax_inbound_source_superseded")
    return entry


def selected_entries(s, w, settings, at_revision):
    from cosmas_os.ports.bot_capabilities import supports_skill
    if not supports_skill(settings, "saved_context") or not settings["include_evidence"]:
        return []
    result = []
    for entry in s.scalars(select(WorkspaceEntry).where(WorkspaceEntry.workspace_id == w.id, WorkspaceEntry.box_id == w.box_id,
        WorkspaceEntry.actor_id == w.owner_id, WorkspaceEntry.kind == SOURCE_KIND, WorkspaceEntry.revision <= at_revision).order_by(WorkspaceEntry.revision)):
        try:
            result.append(validate_selected_source(s, w, entry.id))
        except ws.WorkspaceError:
            continue
    return result


def _receipt(s, w, review, entry, *, configuration=None):
    withheld = False
    try:
        validate_selected_source(s, w, entry.id, configuration=configuration)
    except ws.WorkspaceError:
        withheld = True
    return dict(contract_version=1, scope=dict(box_id=w.box_id, owner_id=w.owner_id, workspace_id=w.id),
        idempotency_key=review.idempotency_key, request_sha256=review.request_sha256, review_id=review.id,
        entry_id=entry.id, entry_revision=entry.revision, operation_id=review.operation_id,
        source_sha256=review.source_sha256, content_sha256=review.content_sha256, document_sha256=review.document_sha256,
        page_numbers=list(review.page_numbers), coverage="human_selected_passage", extraction="human_entered_no_ocr",
        source_withheld=withheld, state="saved")


def resolve_review(s, box, actor, wid, *, key, configuration=None):
    if type(key) is not str or re.fullmatch(r"[A-Za-z0-9:_-]{8,100}", key) is None:
        raise ws.WorkspaceError("fax_inbound_request_invalid", 400)
    w = ws._workspace(s, box, actor, wid)
    review = s.scalar(select(FaxInboundSourceReview).where(FaxInboundSourceReview.workspace_id == wid, FaxInboundSourceReview.idempotency_key == key))
    if review is None:
        return dict(contract_version=1, scope=dict(box_id=box, owner_id=actor, workspace_id=wid), idempotency_key=key, state="not_found")
    entry = historical_source(s, w, review.entry_id)
    return _receipt(s, w, review, entry, configuration=configuration)


def select_review(s, box, actor, wid, *, expected, key, operation_id, document_sha256, passage, page_numbers,
                  reviewed_patient, reviewed_exact_document, reviewed_exact_text, reviewed_untrusted_source,
                  configuration=None, reauthenticate=None):
    try:
        command = FaxSourceReviewCommand(expected_revision=expected, idempotency_key=key, operation_id=operation_id,
            document_sha256=document_sha256, passage=passage, page_numbers=page_numbers,
            reviewed_patient=reviewed_patient, reviewed_exact_document=reviewed_exact_document,
            reviewed_exact_text=reviewed_exact_text, reviewed_untrusted_source=reviewed_untrusted_source)
    except Exception:
        raise ws.WorkspaceError("fax_inbound_source_review_invalid", 422) from None
    operation_id = str(command.operation_id)
    model_work.lock_owner(s, box, actor)
    if reauthenticate is not None:
        reauthenticate()
    w = ws._workspace(s, box, actor, wid, writing=True)
    sha = request_hash(box, actor, wid, command)
    replay = s.scalar(select(FaxInboundSourceReview).where(FaxInboundSourceReview.workspace_id == wid, FaxInboundSourceReview.idempotency_key == key))
    if replay is not None:
        if replay.request_sha256 != sha:
            raise ws.WorkspaceError("idempotency_conflict")
        entry = historical_source(s, w, replay.entry_id)
        if reauthenticate is not None:
            reauthenticate()
        return _receipt(s, w, replay, entry, configuration=configuration)
    _, outcome, _, grant = _current_document(s, w, operation_id, configuration=configuration)
    if expected != w.revision:
        raise ws.WorkspaceError("workspace_revision_conflict")
    if document_sha256 != outcome.document_sha256 or max(command.page_numbers) > outcome.pages:
        raise ws.WorkspaceError("fax_inbound_source_document_changed")
    if w.revision >= 500:
        raise ws.WorkspaceError("workspace_history_limit")
    if s.scalar(select(WorkspaceEntry.id).where(WorkspaceEntry.workspace_id == wid, WorkspaceEntry.idempotency_key == key)):
        raise ws.WorkspaceError("idempotency_conflict")
    ordinal = 1 + (s.scalar(select(func.max(FaxInboundSourceReview.ordinal)).where(
        FaxInboundSourceReview.workspace_id == wid, FaxInboundSourceReview.operation_id == operation_id)) or 0)
    content_sha = hashlib.sha256(passage.encode()).hexdigest()
    source_sha = source_hash(operation_id, grant.id, document_sha256, outcome_hash(outcome), grant.installation_sha256, content_sha, command.page_numbers)
    w.revision += 1
    entry = WorkspaceEntry(workspace_id=wid, box_id=box, actor_id=actor, revision=w.revision, kind=SOURCE_KIND,
        content=passage, source_label=SOURCE_LABEL, idempotency_key=key, request_hash=sha)
    s.add(entry)
    s.flush()
    review = FaxInboundSourceReview(workspace_id=wid, box_id=box, owner_id=actor, entry_id=entry.id,
        operation_id=operation_id, grant_id=grant.id, patient_link_id=w.patient_link_id, ordinal=ordinal,
        expected_revision=expected, workspace_revision=w.revision, idempotency_key=key, request_sha256=sha,
        source_sha256=source_sha, content_sha256=content_sha, document_sha256=document_sha256,
        outcome_sha256=outcome_hash(outcome), installation_sha256=grant.installation_sha256,
        page_numbers=list(command.page_numbers), reviewed_patient=True, reviewed_exact_document=True,
        reviewed_exact_text=True, reviewed_untrusted_source=True)
    s.add(review)
    ws._audit(s, w, "fax_inbound_passage_reviewed")
    if reauthenticate is not None:
        reauthenticate()
    _current_document(s, w, operation_id, configuration=configuration)
    s.commit()
    return _receipt(s, w, review, entry, configuration=configuration)
