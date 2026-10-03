"""Real database passage custody; PDF bytes/provider boundary entirely invented."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from tests.integration.test_efax_inbound_ledger import claimed, inbound, received
from tests.integration.test_google_message import case as google_case
from tests.integration.test_google_message import select_message
from tests.integration.test_note_review import prepare
from tests.unit.test_core_capture_notes import draft

from cosmas_os.application import core_note_review
from cosmas_os.application import efax_inbound as ledger
from cosmas_os.application import efax_inbound_source as source
from cosmas_os.application import note_review as notes
from cosmas_os.application import services as svc
from cosmas_os.application import workspace as ws
from cosmas_os.application.workspace import WorkspaceError
from cosmas_os.efax_inbound_models import EFaxInboundOutcome
from cosmas_os.efax_source_models import EFaxInboundSourceReview
from cosmas_os.models import (
    EncounterWorkspace,
    Principal,
    WorkspaceEntry,
    WorkspaceNote,
    WorkspaceNoteReview,
)
from cosmas_os.ports.core_notes import CoreDraftReceipt, CoreDraftReference

inbound = inbound
google_case = google_case


@pytest.fixture
def case(inbound, seeded):
    f = inbound
    box, actor, workspace, patient = prepare(f.s, seeded)
    assert (box, actor) == (f.box, f.owner)
    f.workspace, f.patient = workspace, patient
    _, invocation = claimed(f)
    assert ledger.mark_invocation(f.s, invocation, current=f.current)
    receipt, pdf = received(invocation)
    ledger.settle_image(f.s, invocation, receipt, pdf)
    f.operation_id, f.document_sha256 = invocation.operation_id, receipt.document_sha256
    f.configuration = SimpleNamespace(efax_inbound_source_available=True)
    with source.install_binding_reader(f.current):
        yield f


def save(f, **changes):
    current = f.s.get(EncounterWorkspace, f.workspace["id"], populate_existing=True)
    args = dict(expected=current.revision, key="fax-source-review-1", operation_id=f.operation_id,
        document_sha256=f.document_sha256, passage="Human-reviewed invented café request. Selected passage only.",
        page_numbers=[1], reviewed_patient=True, reviewed_exact_document=True, reviewed_exact_text=True,
        reviewed_untrusted_source=True, configuration=f.configuration)
    return source.select_review(f.s, f.box, f.owner, f.workspace["id"], **{**args, **changes})


def count(f, cls):
    # Committed signed workflow fixtures can coexist in the same guarded DB;
    # counts establish this practice's effects, not unrelated retained history.
    return f.s.scalar(select(func.count()).select_from(cls).where(cls.box_id == f.box))


def test_exact_source_review_saved_and_reopened_without_provider_or_note_writes(case):
    f = case
    before = count(f, WorkspaceNote)
    receipt = save(f)
    assert receipt["coverage"] == "human_selected_passage" and receipt["extraction"] == "human_entered_no_ocr"
    assert receipt["source_withheld"] is False
    assert "passage" not in receipt and "document" not in receipt
    w = f.s.get(EncounterWorkspace, f.workspace["id"])
    entry = source.validate_selected_source(f.s, w, receipt["entry_id"], configuration=f.configuration)
    assert entry.content == "Human-reviewed invented café request. Selected passage only."
    assert entry.kind == "efax_inbound_source"
    f.s.expire_all()
    recovered = source.resolve_review(f.s, f.box, f.owner, w.id, key="fax-source-review-1", configuration=f.configuration)
    assert recovered == receipt and count(f, WorkspaceNote) == before


def test_lost_reply_exact_retry_and_changed_body_conflict(case):
    f = case
    original_revision = f.s.get(EncounterWorkspace, f.workspace["id"]).revision
    first = save(f)
    second = save(f, expected=original_revision)
    assert first == second and count(f, EFaxInboundSourceReview) == 1
    with pytest.raises(WorkspaceError, match="idempotency_conflict"):
        save(f, expected=original_revision, passage="Changed human text")
    f.s.rollback()
    assert count(f, EFaxInboundSourceReview) == 1


def test_revoked_account_masks_receipt_but_never_deletes_or_reauthorizes_source(case):
    f = case
    original_revision = f.s.get(EncounterWorkspace, f.workspace["id"]).revision
    saved = save(f)
    f.active = False
    replay = save(f, expected=original_revision)
    assert replay["review_id"] == saved["review_id"] and replay["source_withheld"] is True
    w = f.s.get(EncounterWorkspace, f.workspace["id"])
    assert source.historical_source(f.s, w, saved["entry_id"]).content
    with pytest.raises(WorkspaceError, match="efax_inbound_grant_unavailable"):
        source.validate_selected_source(f.s, w, saved["entry_id"], configuration=f.configuration)
    assert count(f, EFaxInboundSourceReview) == 1


def test_legacy_grant_revocation_withholds_and_refuses_new_review(case):
    f = case
    saved = save(f)
    review = f.s.scalar(select(EFaxInboundSourceReview).where(EFaxInboundSourceReview.entry_id == saved["entry_id"]))
    ledger.revoke_grant(f.s, f.box, f.owner, review.grant_id, key="revoke-fax-source")
    with pytest.raises(WorkspaceError, match="efax_inbound_grant_unavailable"):
        save(f, key="fax-source-review-2")
    f.s.rollback()
    assert source.resolve_review(f.s, f.box, f.owner, f.workspace["id"], key="fax-source-review-1", configuration=f.configuration)["source_withheld"] is True


def test_revised_human_passage_supersedes_old_current_source_without_destroying_history(case):
    f = case
    first = save(f)
    second = save(f, key="fax-source-review-2", passage="Human revised selected passage.")
    w = f.s.get(EncounterWorkspace, f.workspace["id"])
    assert source.historical_source(f.s, w, first["entry_id"]).content
    with pytest.raises(WorkspaceError, match="efax_inbound_source_superseded"):
        source.validate_selected_source(f.s, w, first["entry_id"], configuration=f.configuration)
    assert source.validate_selected_source(f.s, w, second["entry_id"], configuration=f.configuration).content == "Human revised selected passage."
    assert source.resolve_review(f.s, f.box, f.owner, w.id, key="fax-source-review-1", configuration=f.configuration)["source_withheld"] is True


@pytest.mark.parametrize("change,code", [(dict(document_sha256="f" * 64), "efax_inbound_source_document_changed"),
    (dict(page_numbers=[2]), "efax_inbound_source_document_changed"), (dict(expected=400), "workspace_revision_conflict"),
    (dict(reviewed_patient=False), "efax_inbound_source_review_invalid")])
def test_wrong_document_pages_revision_or_ack_refused_without_new_entry(case, change, code):
    f = case
    before = count(f, WorkspaceEntry)
    with pytest.raises(WorkspaceError, match=code):
        save(f, **change)
    f.s.rollback()
    assert count(f, EFaxInboundSourceReview) == 0 and count(f, WorkspaceEntry) == before


def test_disabled_gate_and_missing_current_reader_refuse_before_source_creation(case):
    f = case
    with pytest.raises(WorkspaceError, match="efax_inbound_source_disabled"):
        save(f, configuration=SimpleNamespace(efax_inbound_source_available=False))
    f.s.rollback()
    with source.install_binding_reader(None), pytest.raises(WorkspaceError, match="efax_inbound_source_unavailable"):
        save(f)
    f.s.rollback()
    assert count(f, EFaxInboundSourceReview) == 0


def test_foreign_human_and_agent_cannot_review_or_read_owner_source(case, seeded):
    f = case
    before = count(f, WorkspaceEntry)
    other = Principal(box_id=f.box, display_name="Invented foreign person", principal_type="human", state="active", is_owner=False,
        charter_version="1", policy_version="1", config_version="1")
    f.s.add(other)
    f.s.commit()
    for actor in (other.id, seeded["agents"]["chief"]):
        with pytest.raises(WorkspaceError):
            source.select_review(f.s, f.box, actor, f.workspace["id"], expected=1, key="foreign-review-1",
                operation_id=f.operation_id, document_sha256=f.document_sha256, passage="Human text", page_numbers=[1],
                reviewed_patient=True, reviewed_exact_document=True, reviewed_exact_text=True, reviewed_untrusted_source=True,
                configuration=f.configuration)
        f.s.rollback()
    assert count(f, WorkspaceEntry) == before and count(f, EFaxInboundSourceReview) == 0


def test_precommit_revocation_and_reauthentication_callback_are_rechecked(case):
    f = case
    calls = []
    def reauthenticate():
        calls.append(1)
        if len(calls) == 2:
            f.active = False
    with pytest.raises(WorkspaceError, match="efax_inbound_grant_unavailable"):
        save(f, reauthenticate=reauthenticate)
    f.s.rollback()
    assert len(calls) == 2 and count(f, EFaxInboundSourceReview) == 0


def test_existing_manual_reviewed_note_material_preserved(case):
    f = case
    w = notes.save(f.s, f.box, f.owner, f.workspace["id"], expected=1, key="manual-note-save", base_note_id=None,
        source_reply_id=None, content="Invented existing clinical note.")["workspace"]
    n = w["note"]["latest"]
    reviewed = notes.review(f.s, f.box, f.owner, f.workspace["id"], n["id"], expected=w["revision"], key="manual-note-review",
        content_hash=n["content_hash"], source_hash=n["source_fingerprint"])["workspace"]["note"]
    before = deepcopy(reviewed)
    save(f)
    assert ws.read(f.s, f.box, f.owner, f.workspace["id"])["note"] == before
    assert count(f, WorkspaceNote) == 1 and count(f, WorkspaceNoteReview) == 1


def test_existing_reviewed_core_note_is_not_replaced_or_refingerprinted(case):
    f = case
    checked = CoreDraftReceipt.model_validate(draft(uuid4()))
    w = core_note_review.import_saved(f.s, f.box, f.owner, f.workspace["id"], expected=1,
        key="saved-core-note", base_note_id=None, selected=CoreDraftReference.from_draft(checked), checked=checked)["workspace"]
    n = w["note"]["latest"]
    before = notes.review(f.s, f.box, f.owner, f.workspace["id"], n["id"], expected=w["revision"], key="core-note-review",
        content_hash=n["content_hash"], source_hash=n["source_fingerprint"], core_checked=checked)["workspace"]["note"]
    save(f)
    assert ws.read(f.s, f.box, f.owner, f.workspace["id"])["note"] == before
    assert count(f, WorkspaceNote) == 1 and count(f, WorkspaceNoteReview) == 1


def test_existing_independent_evidence_remains_exactly_unchanged(case):
    f = case
    # A regular jotted/evidence source remains independent of selected fax custody.
    w = ws.append(f.s, f.box, f.owner, f.workspace["id"], expected=1, key="existing-evidence",
        kind="evidence", content="Invented existing independently reviewed context.", source_label="Existing context")
    before = [(e["id"], e["content"], e["source_label"]) for e in w["workspace"]["entries"]]
    save(f)
    entries = ws.read(f.s, f.box, f.owner, f.workspace["id"])["entries"]
    assert [(e["id"], e["content"], e["source_label"]) for e in entries if e["id"] in {a[0] for a in before}] == before


def test_actual_selected_gmail_source_coexists_with_reviewed_fax_passage(google_case, inbound):
    g, f = google_case, inbound
    assert (g.box, g.owner) == (f.box, f.owner)
    gmail = select_message(g)
    before = ws.read(g.s, g.box, g.owner, g.w["id"])
    original = next(e for e in before["entries"] if e["id"] == gmail["entry_id"])
    f.workspace, f.patient = g.w, g.patient
    _, invocation = claimed(f)
    assert ledger.mark_invocation(f.s, invocation, current=f.current)
    receipt, pdf = received(invocation)
    ledger.settle_image(f.s, invocation, receipt, pdf)
    f.operation_id, f.document_sha256 = invocation.operation_id, receipt.document_sha256
    f.configuration = SimpleNamespace(efax_inbound_source_available=True)
    with source.install_binding_reader(f.current):
        fax = save(f)
        after = ws.read(f.s, f.box, f.owner, f.workspace["id"])
    assert next(e for e in after["entries"] if e["id"] == gmail["entry_id"]) == original
    assert fax["source_withheld"] is False


@pytest.mark.parametrize("insert_kind", ["orm_flush", "direct_sql"])
def test_forged_source_entry_without_immutable_review_is_rejected(case, insert_kind):
    f = case
    w = f.s.get(EncounterWorkspace, f.workspace["id"])
    entry_id, original_revision = str(uuid4()), w.revision
    before = count(f, WorkspaceEntry)
    with pytest.raises(DBAPIError) as error, f.s.begin_nested():
        w.revision += 1
        values = dict(id=entry_id, workspace_id=w.id, box_id=f.box, actor_id=f.owner,
            revision=w.revision, kind=source.SOURCE_KIND, content="Forged human text",
            source_label=source.SOURCE_LABEL, idempotency_key="forged-entry-key", request_hash="a" * 64)
        if insert_kind == "orm_flush":
            f.s.add(WorkspaceEntry(**values))
            # The product Session deliberately has autoflush=False. SET
            # CONSTRAINTS alone cannot test an ORM row that was never inserted.
            f.s.flush()
        else:
            f.s.flush()
            f.s.execute(text("INSERT INTO public.workspace_entries "
                "(id,workspace_id,box_id,actor_id,revision,kind,content,source_label,idempotency_key,request_hash) "
                "VALUES(:id,:workspace_id,:box_id,:actor_id,:revision,:kind,:content,:source_label,:idempotency_key,:request_hash)"),
                values)
        assert f.s.scalar(select(WorkspaceEntry.id).where(WorkspaceEntry.id == entry_id)) == entry_id
        assert count(f, EFaxInboundSourceReview) == 0
        f.s.execute(text("SET CONSTRAINTS efax_inbound_source_entry_guard IMMEDIATE"))
    assert getattr(error.value.orig, "sqlstate", None) == "23514"
    assert count(f, WorkspaceEntry) == before
    assert f.s.get(WorkspaceEntry, entry_id) is None
    assert f.s.get(EncounterWorkspace, w.id, populate_existing=True).revision == original_revision


@pytest.mark.parametrize("change", [{"document_sha256": "f" * 64}, {"content_sha256": "f" * 64},
    {"source_sha256": "f" * 64}, {"page_numbers": [2]}, {"page_numbers": [1, 1]},
    {"reviewed_exact_text": False}])
def test_forged_review_cannot_bypass_document_text_or_page_commitments(case, change):
    f = case
    w = f.s.get(EncounterWorkspace, f.workspace["id"])
    w.revision += 1
    command = source.EFaxSourceReviewCommand(expected_revision=w.revision-1, idempotency_key="forged-review-key",
        operation_id=f.operation_id, document_sha256=f.document_sha256, passage="Human selected passage.", page_numbers=(1,),
        reviewed_patient=True, reviewed_exact_document=True, reviewed_exact_text=True, reviewed_untrusted_source=True)
    sha = source.request_hash(f.box, f.owner, w.id, command)
    entry = WorkspaceEntry(workspace_id=w.id, box_id=f.box, actor_id=f.owner, revision=w.revision, kind=source.SOURCE_KIND,
        content=command.passage, source_label=source.SOURCE_LABEL, idempotency_key=command.idempotency_key, request_hash=sha)
    f.s.add(entry)
    f.s.flush()
    _, outcome, _, grant = source._document_history(f.s, f.box, f.owner, f.operation_id)
    content_sha = hashlib.sha256(command.passage.encode()).hexdigest()
    values = dict(workspace_id=w.id, box_id=f.box, owner_id=f.owner, entry_id=entry.id, operation_id=f.operation_id,
        grant_id=grant.id, patient_link_id=w.patient_link_id, ordinal=1, expected_revision=w.revision-1,
        workspace_revision=w.revision, idempotency_key=command.idempotency_key, request_sha256=sha, content_sha256=content_sha,
        document_sha256=f.document_sha256, outcome_receipt_sha256=outcome.receipt_sha256, selection_sha256=grant.selection_sha256,
        source_sha256=source.source_hash(f.operation_id, grant.id, f.document_sha256, outcome.receipt_sha256,
            grant.selection_sha256, content_sha, [1]), page_numbers=[1], reviewed_patient=True, reviewed_exact_document=True,
        reviewed_exact_text=True, reviewed_untrusted_source=True)
    f.s.add(EFaxInboundSourceReview(**{**values, **change}))
    with pytest.raises(DBAPIError) as error:
        # Exercise the forged review itself, not just a deferred entry with a
        # still-pending ORM review that PostgreSQL has never seen.
        f.s.flush()
        f.s.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    assert getattr(error.value.orig, "sqlstate", None) == "23514"
    f.s.rollback()


def test_source_review_rows_and_original_pdf_are_immutable(case):
    f = case
    save(f)
    review = f.s.scalar(select(EFaxInboundSourceReview))
    review.content_sha256 = "f" * 64
    with pytest.raises(DBAPIError):
        f.s.flush()
    f.s.rollback()
    outcome = f.s.get(EFaxInboundOutcome, f.operation_id)
    outcome.document = b"%PDF changed"
    with pytest.raises(DBAPIError):
        f.s.flush()
    f.s.rollback()


def test_concurrent_identical_human_reviews_commit_one_receipt(engine, monkeypatch):
    with Session(engine) as s:
        seed = svc.provision_box(svc.Container(s), "Invented fax-source concurrency")
        f = cast(Any, inbound).__wrapped__(s, seed, monkeypatch)
        _, _, w, _ = prepare(s, seed)
        _, invocation = claimed(f)
        assert ledger.mark_invocation(s, invocation, current=f.current)
        receipt, pdf = received(invocation)
        ledger.settle_image(s, invocation, receipt, pdf)
        box, owner, wid, operation_id, document_sha = f.box, f.owner, w["id"], invocation.operation_id, receipt.document_sha256
        selection = f.installation.selection.model_dump(mode="json")
        s.commit()
    barrier = Barrier(2)
    def run(_):
        with Session(engine) as s:
            barrier.wait(timeout=10)
            return source.select_review(s, box, owner, wid, expected=1, key="concurrent-review-key",
                operation_id=operation_id, document_sha256=document_sha, passage="Identical human selected passage.",
                page_numbers=[1], reviewed_patient=True, reviewed_exact_document=True, reviewed_exact_text=True,
                reviewed_untrusted_source=True, configuration=SimpleNamespace(efax_inbound_source_available=True))["review_id"]
    with source.install_binding_reader(lambda s, g: g.selection == selection), ThreadPoolExecutor(max_workers=2) as pool:
        assert len(set(pool.map(run, range(2)))) == 1
    with Session(engine) as s:
        assert s.scalar(select(func.count()).select_from(EFaxInboundSourceReview).where(EFaxInboundSourceReview.workspace_id == wid)) == 1
