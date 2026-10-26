"""Calendar-file custody under actual restricted SQL credentials, invented data only."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from tests.integration import test_calendar_import_custody as custody
from tests.integration import test_calendar_imports as signed
from tests.integration.test_google_message_model_work import google_case as _google_case

from cosmas_os.application import calendar_imports as imports
from cosmas_os.application import database_preparation as preparation
from cosmas_os.application import provider_team
from cosmas_os.calendar_import_models import CalendarImportRequest, CalendarImportSourceReview
from cosmas_os.models import EncounterWorkspace, WorkspaceEntry

google_case = _google_case

TRIGGERS = {
    "guard_calendar_import_request", "guard_calendar_import_snapshot",
    "guard_calendar_import_review", "guard_calendar_import_entry",
    "guard_calendar_import_revocation",
}
SHARED_ENTRY_TRIGGERS = {"guard_ehr_read_entry", "guard_microsoft_message_entry"}


@pytest.fixture
def restricted_import(google_case, monkeypatch):
    # The inherited fixture commits one invented workspace as administrator.
    # All import, review, recovery, revocation and forgery work below uses a
    # separately authenticated, genuinely restricted PostgreSQL connection.
    f = google_case
    admin = f.engine
    role = "import_runtime_test_" + uuid4().hex[:12]
    runtime_url = admin.url.set(username=role, password="invented-runtime-password-1234")
    runtime = create_engine(runtime_url, echo=False, hide_parameters=True)
    quoted_role = admin.dialect.identifier_preparer.quote_identifier(role)
    monkeypatch.setattr(provider_team.runtime_settings, "workspace_calendar_import_enabled", True)
    try:
        assert admin.url.database.startswith("w1a_")
        assert admin.url.host in {"localhost", "127.0.0.1", "::1"}
        with admin.begin() as connection:
            preparation._ensure_unprivileged_role(connection, runtime_url)
            preparation._apply_runtime_privileges(connection, runtime_url)
            admin_role = connection.scalar(text("SELECT current_user"))
        with Session(runtime) as s:
            yield SimpleNamespace(s=s, engine=runtime, role=role, admin_role=admin_role,
                box=f.box, owner=f.owner, account=f.account, patient=f.patient,
                w=s.get(EncounterWorkspace, f.wid))
    finally:
        runtime.dispose()
        with admin.begin() as connection:
            if connection.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=:role)"), {"role": role}):
                connection.execute(text(f"DROP OWNED BY {quoted_role}"))
                connection.execute(text(f"DROP ROLE {quoted_role}"))


def assert_private(r):
    with r.engine.connect() as connection:
        assert connection.scalar(text("SELECT current_user")) == r.role
        allowed = set(connection.scalars(text("SELECT p.oid FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname='public' AND has_function_privilege(current_user,p.oid,'EXECUTE')")))
        assert allowed == set(preparation._runtime_validator_oids(connection) or ()) and len(allowed) == 7
        rows = connection.execute(text("""SELECT p.proname, p.prosecdef, p.proconfig,
            pg_get_userbyid(p.proowner) AS owner,
            has_function_privilege(current_user,p.oid,'EXECUTE') AS executable,
            EXISTS(SELECT 1 FROM aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a
                WHERE a.grantee=0 AND a.privilege_type='EXECUTE') AS public_execute
            FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname='public' AND (p.proname LIKE 'calendar_import_%'
                OR p.proname LIKE 'guard_calendar_import_%'
                OR p.proname IN ('guard_ehr_read_entry','guard_microsoft_message_entry',
                    'ehr_read_source_valid','microsoft_message_source_valid'))""")).mappings().all()
        assert {row["proname"] for row in rows if row["prosecdef"]} == TRIGGERS | SHARED_ENTRY_TRIGGERS
        assert {row["proname"] for row in rows} >= TRIGGERS | {"calendar_import_source_valid", "calendar_import_lock_scope"}
        for row in rows:
            assert row["owner"] == r.admin_role and row["owner"] != r.role
            assert row["executable"] is False and row["public_execute"] is False
            assert "search_path=pg_catalog" in row["proconfig"]
    # Execution itself must fail, not merely privilege metadata inspection.
    for expression in (
        "public.calendar_import_source_valid(gen_random_uuid())",
        "public.calendar_import_source_current(gen_random_uuid())",
        "public.calendar_import_snapshot_valid(gen_random_uuid())",
        "public.ehr_read_source_valid(gen_random_uuid())",
        "public.microsoft_message_source_valid(gen_random_uuid())",
        *(f"public.{name}()" for name in sorted(TRIGGERS | SHARED_ENTRY_TRIGGERS)),
    ):
        with r.engine.connect() as connection, pytest.raises(DBAPIError) as refusal:
            connection.execute(text("SELECT " + expression))
        assert getattr(refusal.value.orig, "sqlstate", None) == "42501"


def test_restricted_calendar_import_review_recovery_and_withdrawal(restricted_import):
    f = restricted_import
    assert_private(f)
    starts = datetime.now(UTC).date()
    fixture = SimpleNamespace(ics=signed.synthetic_ics, starts_on=starts,
        window=dict(starts_on=starts.isoformat(), ends_on=(starts + timedelta(days=7)).isoformat(), timezone="UTC"))
    body = signed.upload_body(fixture)
    body.pop("action")
    body["key"] = body.pop("idempotency_key")
    scope = (f.s, f.box, f.owner, f.account, f.w.id)
    receipt = imports.upload(*scope, **body)
    assert imports.inspect_import(*scope, import_id=receipt["import_id"]) == receipt
    assert imports.resolve_import(*scope, key=body["key"]) == receipt
    assert imports.upload(*scope, **body) == receipt
    item = receipt["payload"]["items"][0]
    review = dict(expected=f.w.revision, key="restricted-import-review",
        import_id=receipt["import_id"], source_sha256=receipt["source_sha256"],
        item_index=item["item_index"], item_sha256=imports.item_hash(item),
        reviewed_visit=True, reviewed_exact_summary=True, reviewed_untrusted_source=True)
    saved = imports.select_review(*scope, **review)
    entry = imports.validate_selected_source(f.s, f.w, saved["entry_id"])
    content = imports.source_content(receipt["payload"], item)
    assert entry.content == content and entry.kind == "calendar_import_source"
    assert saved["source_withheld"] is False
    assert imports.select_review(*scope, **review)["entry_id"] == entry.id
    revoke = dict(expected=f.w.revision, key="restricted-import-revoke", import_id=receipt["import_id"],
        source_sha256=receipt["source_sha256"])
    removed = imports.revoke_import(*scope, **revoke)
    assert removed["status"] == "revoked"
    assert imports.revoke_import(*scope, **revoke)["request_sha256"] == removed["request_sha256"]
    assert imports.resolve_import(*scope, key=body["key"])["status"] == "withheld"
    replay = imports.select_review(*scope, **review)
    assert replay["source_withheld"] is True
    workspace = replay["workspace"]
    assert isinstance(workspace, dict) and isinstance(workspace["entries"], list)
    public = next(e for e in workspace["entries"] if e["id"] == entry.id)
    assert public["content"] == "" and public["source_label"] == "Unavailable calendar import"
    assert imports.historical_source(f.s, f.w, entry.id).content == content
    for model in (CalendarImportRequest, CalendarImportSourceReview):
        assert f.s.scalar(select(func.count()).select_from(model).where(model.workspace_id == f.w.id)) == 1
    assert_private(f)


@pytest.mark.parametrize("kind", ["ehr_read_source", "microsoft_message"])
def test_restricted_shared_entry_guards_reject_orphan_sources(restricted_import, kind):
    f = restricted_import
    f.w.revision += 1
    with pytest.raises(DBAPIError) as refusal:
        f.s.add(WorkspaceEntry(workspace_id=f.w.id, box_id=f.box, actor_id=f.owner,
            revision=f.w.revision, kind=kind, content="No reviewed source exists",
            source_label="Invented orphan source", idempotency_key="forged-source-entry", request_hash="a" * 64))
        f.s.commit()
    assert getattr(refusal.value.orig, "sqlstate", None) == "23514"
    f.s.rollback()
    assert_private(f)


@pytest.mark.parametrize("boundary", ["request", "snapshot", "review", "entry", "revocation"])
def test_restricted_calendar_guards_reject_forged_custody(restricted_import, boundary):
    f = restricted_import
    read = None if boundary == "request" else custody.request(f)
    snap = custody.snapshot(f, read) if boundary in {"review", "revocation"} else None
    with pytest.raises(DBAPIError) as refusal:
        if boundary == "request":
            custody.request(f, account_id=uuid4())
        elif boundary == "snapshot":
            custody.snapshot(f, read, mutate=lambda payload: payload.update(coverage="invented_authority"))
        elif boundary == "review":
            custody.review(f, snap, content="Forged text replacing the exact calendar summary")
        elif boundary == "entry":
            f.w.revision += 1
            f.s.add(WorkspaceEntry(workspace_id=f.w.id, box_id=f.box, actor_id=f.owner,
                revision=f.w.revision, kind="calendar_import_source", content="No source review exists",
                source_label=imports.SOURCE_LABEL, idempotency_key="forged-import-entry", request_hash="a" * 64))
            f.s.commit()
        else:
            custody.revoke(f, read, snap, import_sha256="0" * 64)
    assert getattr(refusal.value.orig, "sqlstate", None) == "23514"
    f.s.rollback()
    assert f.s.scalar(select(func.count()).select_from(CalendarImportSourceReview).where(
        CalendarImportSourceReview.workspace_id == f.w.id)) == 0
    assert_private(f)
