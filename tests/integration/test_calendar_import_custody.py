"""Real SQL imported-file custody; no raw file persistence or provider calls."""

import hashlib
import json
from datetime import UTC, date
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from tests.integration.test_note_review import prepare

from cosmas_os.application import calendar_imports as imports
from cosmas_os.calendar_import_models import (
    CalendarImportRequest,
    CalendarImportRevocation,
    CalendarImportSnapshot,
    CalendarImportSourceReview,
)
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.models import EncounterWorkspace, ExternalIdentity, WorkspaceEntry


@pytest.fixture
def calendar_custody(session, seeded):
    box, owner, workspace, patient = prepare(session, seeded)
    account = ExternalIdentity(
        box_id=box,
        principal_id=owner,
        issuer=f"https://{uuid4()}.example.invalid",
        subject="invented-calendar-owner",
        organization_id="invented-org",
        reviewed_by="invented owner",
        evidence_ref="synthetic calendar",
    )
    session.add(account)
    session.commit()
    return SimpleNamespace(
        s=session,
        box=box,
        owner=owner,
        w=session.get(EncounterWorkspace, workspace["id"]),
        patient=patient,
        account=account.id,
    )


def request(f, **changes):
    now = f.s.scalar(select(func.clock_timestamp())).astimezone(UTC).replace(microsecond=0)
    values = dict(
        box_id=f.box,
        owner_id=f.owner,
        account_id=f.account,
        workspace_id=f.w.id,
        patient_link_id=f.w.patient_link_id,
        idempotency_key="import-" + uuid4().hex,
        byte_sha256="1" * 64,
        reported_source="atlas_md",
        window_start=date(2026, 11, 1),
        window_end=date(2026, 11, 8),
        timezone="America/New_York",
        created_at=now,
    )
    values.update(changes)
    row = CalendarImportRequest(**values, request_hash="0" * 64)
    row.request_hash = payload_hash(imports._request_body(row))
    f.s.add(row)
    f.s.flush()
    f.s.commit()
    return row


def snapshot(f, read, mutate=None):
    item = dict(
        item_index=0,
        title="Invented café follow-up",
        title_truncated=False,
        starts_at="2026-11-01T15:00:00Z",
        ends_at="2026-11-01T15:30:00Z",
        all_day=False,
        cancelled=False,
    )
    payload = dict(
        imported_at=read.created_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        reported_source=read.reported_source,
        window=dict(
            starts_on=read.window_start.isoformat(),
            ends_on=read.window_end.isoformat(),
            timezone=read.timezone,
        ),
        items=[item],
        total_events=1,
        matching_events=1,
        more=False,
        coverage="file_window_only",
    )
    if mutate:
        mutate(payload)
    digest = payload_hash(payload)
    row = CalendarImportSnapshot(
        box_id=f.box,
        owner_id=f.owner,
        workspace_id=f.w.id,
        import_id=read.id,
        payload=payload,
        payload_sha256=digest,
        source_sha256=payload_hash(imports._commitment(read, digest)),
    )
    f.s.add(row)
    f.s.flush()
    f.s.commit()
    return row


def review(f, snap, changes=None, *, content=None):
    read = f.s.get(CalendarImportRequest, snap.import_id)
    item = snap.payload["items"][0]
    key, expected = "review-" + uuid4().hex, f.w.revision
    content = imports.source_content(snap.payload, item) if content is None else content
    body = imports._review_body(
        f.w.id,
        expected,
        key,
        read.id,
        snap.source_sha256,
        item["item_index"],
        imports.item_hash(item),
        True,
        True,
        True,
    )
    f.w.revision += 1
    entry = WorkspaceEntry(
        workspace_id=f.w.id,
        box_id=f.box,
        actor_id=f.owner,
        revision=f.w.revision,
        kind="calendar_import_source",
        content=content,
        source_label=imports.SOURCE_LABEL,
        idempotency_key=key,
        request_hash=payload_hash(body),
    )
    f.s.add(entry)
    f.s.flush()
    values = dict(
        workspace_id=f.w.id,
        box_id=f.box,
        owner_id=f.owner,
        entry_id=entry.id,
        snapshot_id=snap.id,
        patient_link_id=f.w.patient_link_id,
        expected_revision=expected,
        workspace_revision=f.w.revision,
        idempotency_key=key,
        request_hash=payload_hash(body),
        import_sha256=snap.source_sha256,
        item_index=item["item_index"],
        item_sha256=imports.item_hash(item),
        source_sha256=imports._selected_hash(
            snap.source_sha256, item["item_index"], imports.item_hash(item)
        ),
        content_sha256=hashlib.sha256(content.encode()).hexdigest(),
        reviewed_visit=True,
        reviewed_exact_summary=True,
        reviewed_untrusted_source=True,
    )
    values.update(changes or {})
    row = CalendarImportSourceReview(**values)
    f.s.add(row)
    f.s.flush()
    f.s.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    f.s.commit()
    return entry, row


def revoke(f, read, snap, **changes):
    key = "revoke-" + uuid4().hex
    body = imports._revocation_body(f.w.id, f.w.revision, key, read.id, snap.source_sha256)
    values = dict(
        workspace_id=f.w.id,
        box_id=f.box,
        owner_id=f.owner,
        import_id=read.id,
        expected_revision=f.w.revision,
        idempotency_key=key,
        import_sha256=snap.source_sha256,
        request_hash=payload_hash(body),
    )
    values.update(changes)
    row = CalendarImportRevocation(**values)
    f.s.add(row)
    f.s.commit()
    return row


def scalar(f, function, identifier):
    assert function in {
        "calendar_import_source_valid",
        "calendar_import_source_current",
        "calendar_import_snapshot_valid",
        "calendar_import_request_current",
    }
    return f.s.scalar(text("SELECT public." + function + "(:id)"), {"id": identifier})


def test_exact_unicode_projection_review_and_explicit_revocation(calendar_custody):
    f = calendar_custody
    read = request(f)
    snap = snapshot(f, read)
    entry, _ = review(f, snap)
    sql_content = f.s.scalar(
        text("SELECT public.calendar_import_source_content(CAST(:payload AS jsonb),0)"),
        {"payload": json.dumps(snap.payload)},
    )
    assert (
        sql_content == entry.content
        and "does not verify patient or chart identity" in entry.content
    )
    assert scalar(f, "calendar_import_source_current", entry.id) is True
    revision = f.w.revision
    revoke(f, read, snap)
    assert f.w.revision == revision
    assert scalar(f, "calendar_import_source_current", entry.id) is False
    assert scalar(f, "calendar_import_source_valid", entry.id) is True
    assert scalar(f, "calendar_import_snapshot_valid", snap.id) is True


@pytest.mark.parametrize(
    "change",
    [
        "extra",
        "title_uri",
        "title_encoded",
        "title_entity",
        "title_nfkc",
        "count",
        "more",
        "index",
        "naive",
        "outside",
        "reversed",
        "imported_at",
    ],
)
def test_self_consistent_hash_cannot_store_untrusted_projection(calendar_custody, change):
    f = calendar_custody
    read = request(f)

    def mutate(payload):
        row = payload["items"][0]
        if change == "extra":
            row["url"] = "https://example.invalid/private"
        elif change == "title_uri":
            row["title"] = "Open https://example.invalid/private"
        elif change == "title_encoded":
            row["title"] = "https%3A%2F%2Fexample.invalid"
        elif change == "title_entity":
            row["title"] = "https&colon;//example.invalid"
        elif change == "title_nfkc":
            row["title"] = "ｈｔｔｐｓ：／／example.invalid"
        elif change == "count":
            payload["total_events"] = 0
        elif change == "more":
            payload["more"] = True
        elif change == "index":
            row["item_index"] = 1
        elif change == "naive":
            row["starts_at"] = "2026-11-01T15:00:00"
        elif change == "outside":
            row.update(starts_at="2026-12-01T15:00:00Z", ends_at="2026-12-01T15:30:00Z")
        elif change == "reversed":
            row["ends_at"] = row["starts_at"]
        else:
            payload["imported_at"] = "2026-01-01T00:00:00Z"

    with pytest.raises(DBAPIError, match="snapshot custody or payload"):
        snapshot(f, read, mutate)
    f.s.rollback()


@pytest.mark.parametrize(
    "change",
    [
        "item_sha256",
        "import_sha256",
        "source_sha256",
        "request_hash",
        "patient_link_id",
        "reviewed_exact_summary",
    ],
)
def test_review_cannot_substitute_exact_event_or_existing_visit(calendar_custody, change):
    f = calendar_custody
    snap = snapshot(f, request(f))
    value = (
        False
        if change == "reviewed_exact_summary"
        else str(uuid4())
        if change == "patient_link_id"
        else "0" * 64
    )
    with pytest.raises(DBAPIError):
        review(f, snap, {change: value})
    f.s.rollback()


def test_cancelled_event_cannot_become_a_selected_source(calendar_custody):
    f = calendar_custody
    snap = snapshot(f, request(f), lambda payload: payload["items"][0].update(cancelled=True))
    with pytest.raises(DBAPIError):
        review(f, snap)
    f.s.rollback()


def test_freeform_calendar_source_has_no_review_bypass(calendar_custody):
    f = calendar_custody
    f.w.revision += 1
    f.s.add(
        WorkspaceEntry(
            workspace_id=f.w.id,
            box_id=f.box,
            actor_id=f.owner,
            revision=f.w.revision,
            kind="calendar_import_source",
            content="invented unsupported source",
            source_label=imports.SOURCE_LABEL,
            idempotency_key="orphan-calendar-entry",
            request_hash="0" * 64,
        )
    )
    with pytest.raises(DBAPIError, match="Exact calendar import source review"):
        f.s.flush()
        f.s.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        f.s.commit()
    f.s.rollback()


@pytest.mark.parametrize("change", ["request_hash", "import_sha256", "expected_revision"])
def test_revocation_requires_exact_import_and_current_revision(calendar_custody, change):
    f = calendar_custody
    read = request(f)
    snap = snapshot(f, read)
    with pytest.raises(DBAPIError, match="revocation custody or commitment"):
        revoke(
            f,
            read,
            snap,
            **{change: f.w.revision + 1 if change == "expected_revision" else "0" * 64},
        )
    f.s.rollback()
    assert scalar(f, "calendar_import_request_current", read.id) is True


@pytest.mark.parametrize(
    "table",
    [
        "calendar_import_requests",
        "calendar_import_snapshots",
        "calendar_import_source_reviews",
        "calendar_import_revocations",
    ],
)
def test_calendar_ledgers_cannot_be_rewritten_or_deleted(calendar_custody, table):
    f = calendar_custody
    read = request(f)
    snap = snapshot(f, read)
    _, reviewed = review(f, snap)
    revoked = revoke(f, read, snap)
    identifier = {
        "calendar_import_requests": read.id,
        "calendar_import_snapshots": snap.id,
        "calendar_import_source_reviews": reviewed.id,
        "calendar_import_revocations": revoked.id,
    }[table]
    for verb in (
        "DELETE FROM " + table + " WHERE id=:id",
        "UPDATE " + table + " SET id=id WHERE id=:id",
    ):
        with pytest.raises(DBAPIError):
            f.s.execute(text(verb), {"id": identifier})
            f.s.commit()
        f.s.rollback()


def test_account_loss_withholds_source_without_relabeling_history(calendar_custody):
    f = calendar_custody
    read = request(f)
    entry, _ = review(f, snapshot(f, read))
    account = f.s.get(ExternalIdentity, f.account)
    account.active = False
    f.s.commit()
    assert scalar(f, "calendar_import_source_current", entry.id) is False
    assert scalar(f, "calendar_import_source_valid", entry.id) is True
    with pytest.raises(DBAPIError, match="authority or request"):
        request(f)
    f.s.rollback()


@pytest.mark.parametrize("character", ["\u00ad", "\u061c", "\ue000", "\u0378"])
def test_sql_rejects_all_category_c_characters(session, character):
    title = "Visible" + character + "title"
    result = session.scalar(
        text("SELECT public.calendar_import_title_valid(to_jsonb(CAST(:title AS text)))"),
        {"title": title},
    )
    assert result is False


@pytest.mark.parametrize(
    "title", ["Invented café 🫀", "مراجعة اليوم", "Review 95% complete", "A & B", "Ends in space "]
)
def test_sql_retained_title_accepts_ordinary_unicode_and_truncated_space(session, title):
    assert (
        session.scalar(
            text("SELECT public.calendar_import_title_valid(to_jsonb(CAST(:title AS text)))"),
            {"title": title},
        )
        is True
    )


def test_model_guard_checks_exact_imported_source_and_revocation(calendar_custody):
    f = calendar_custody
    read = request(f)
    snap = snapshot(f, read)
    entry, _ = review(f, snap)
    source = dict(
        entry_id=entry.id,
        revision=entry.revision,
        kind="evidence",
        label=entry.source_label,
        content=entry.content,
    )
    value = dict(
        workspace_id=f.w.id,
        box_id=f.box,
        owner_id=f.owner,
        request_body=dict(content="Draft directions"),
        prepared_envelope=dict(context=dict(sources=[source])),
    )

    def valid(body):
        return f.s.scalar(
            text(
                "SELECT public.selected_google_model_sources_current(jsonb_populate_record(NULL::public.model_work_admissions,CAST(:value AS jsonb)))"
            ),
            {"value": json.dumps(body)},
        )

    assert valid(value) is True
    changed = {
        **value,
        "prepared_envelope": {
            "context": {"sources": [{**source, "content": entry.content + " changed"}]}
        },
    }
    assert valid(changed) is False
    descriptor_only = {
        **value,
        "prepared_envelope": {"context": {"sources": []}},
        "request_body": {
            "content": "Draft directions",
            "task_brief": {
                "source_versions": [
                    dict(
                        entry_id=entry.id,
                        revision=entry.revision,
                        sha256=hashlib.sha256(entry.content.encode()).hexdigest(),
                    )
                ]
            },
        },
    }
    assert valid(descriptor_only) is False
    revoke(f, read, snap)
    assert valid(value) is False


@pytest.mark.parametrize("reserved_by", ["upload", "revoke"])
def test_later_ordinary_entry_cannot_reuse_calendar_operation_key(calendar_custody, reserved_by):
    f = calendar_custody
    read = request(f)
    key = read.idempotency_key
    if reserved_by == "revoke":
        key = revoke(f, read, snapshot(f, read)).idempotency_key
    f.w.revision += 1
    f.s.add(
        WorkspaceEntry(
            workspace_id=f.w.id,
            box_id=f.box,
            actor_id=f.owner,
            revision=f.w.revision,
            kind="scratchpad",
            content="Invented ordinary note",
            idempotency_key=key,
            request_hash="0" * 64,
        )
    )
    with pytest.raises(DBAPIError, match="Calendar import key already reserved"):
        f.s.flush()
        f.s.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        f.s.commit()
    f.s.rollback()
