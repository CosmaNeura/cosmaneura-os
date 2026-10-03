"""Received-fax path using the real prepared SQL privilege set on an owned local DB.

Signed product API, real PG ledger/parser/model services, invented HTTP only.
No administrator access is used for fax setup, reads, approvals or handoffs.
The private deployment privilege helpers are applied unchanged to this actual
w1a_ database. This does not qualify public prepare_beta_database, hosted TLS,
or hosted startup; those have separate deployment-profile acceptance tests.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from tests.integration import test_efax_source_full_workflow as flow

from cosmas_os.api import app as api
from cosmas_os.application import database_preparation as preparation
from cosmas_os.application import handoff_revision as revisions
from cosmas_os.application import workspace as ws
from cosmas_os.config import settings
from cosmas_os.db import make_session_factory
from cosmas_os.models import ModelWorkAdmission

managed_case = flow.managed_case
efax_http = flow.efax_http
source_http = flow.source_http

# These helper functions remain private to migration-owned trigger execution.
HELPERS = (
    "public.efax_inbound_owner(uuid,uuid)",
    "public.efax_inbound_grant_current(uuid)",
    "public.efax_inbound_document_valid(uuid)",
    "public.efax_inbound_source_valid(uuid)",
    "public.efax_inbound_source_current(uuid)",
    "public.handoff_review_sources_current(uuid,uuid,uuid,jsonb)",
    "public.selected_google_model_sources_current(public.model_work_admissions)",
)


@pytest.fixture
def restricted_fax(source_http, monkeypatch):
    f = source_http
    admin_engine = f.case.engine
    role = "fax_runtime_test_" + uuid4().hex[:12]
    runtime_url = admin_engine.url.set(username=role, password="invented-runtime-password-1234")
    runtime_engine = create_engine(runtime_url, echo=False, hide_parameters=True)
    quoted_role = admin_engine.dialect.identifier_preparer.quote_identifier(role)
    try:
        assert admin_engine.url.database.startswith("w1a_")
        assert admin_engine.url.host in {"localhost", "127.0.0.1", "::1"}
        assert settings.workspace_available and settings.cosmas_env == "synth_os"
        # Public preparation deliberately requires cosmas_os/TLS. Applying its
        # exact privilege helpers here proves the permission behavior on this
        # genuine local product profile, without a fictional URL or gate bypass.
        with admin_engine.begin() as connection:
            preparation._ensure_unprivileged_role(connection, runtime_url)
            preparation._apply_runtime_privileges(connection, runtime_url)
        f.case.engine = runtime_engine
        monkeypatch.setattr(api, "SessionLocal", make_session_factory(runtime_engine))
        yield SimpleNamespace(f=f, engine=runtime_engine, role=role)
    finally:
        # Restore the fixture's existing administrator engine only for teardown.
        # Its managed TestClient is already closed before this point.
        f.case.engine = admin_engine
        monkeypatch.setattr(api, "SessionLocal", make_session_factory(admin_engine))
        runtime_engine.dispose()
        with admin_engine.begin() as connection:
            if connection.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=:role)"), {"role": role}):
                connection.execute(text(f"DROP OWNED BY {quoted_role}"))
                connection.execute(text(f"DROP ROLE {quoted_role}"))


def assert_private(r):
    with r.engine.connect() as connection:
        assert connection.scalar(text("SELECT current_user")) == r.role
        flags = connection.execute(text("SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls "
            "FROM pg_roles WHERE rolname=current_user")).one()
        assert all(flag is False for flag in flags)
        assert connection.scalar(text("SELECT NOT EXISTS(SELECT 1 FROM pg_auth_members m "
            "JOIN pg_roles member ON member.oid=m.member WHERE member.rolname=current_user)")) is True
        assert connection.scalar(text("SELECT NOT has_schema_privilege(current_user,'public','CREATE')")) is True
        assert connection.scalar(text("SELECT NOT has_table_privilege(current_user,'public.audit_events','UPDATE') "
            "AND NOT has_table_privilege(current_user,'public.audit_events','DELETE') "
            "AND NOT has_table_privilege(current_user,'public.audit_events','TRUNCATE')")) is True
        permitted = set(connection.scalars(text("SELECT p.oid FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname='public' AND has_function_privilege(current_user,p.oid,'EXECUTE')")))
        assert permitted == set(preparation._runtime_validator_oids(connection) or ()) and len(permitted) == 7
        for signature in HELPERS:
            assert connection.scalar(text("SELECT NOT has_function_privilege(current_user,to_regprocedure(:name),'EXECUTE')"),
                {"name": signature}) is True
    for expression in ("public.efax_inbound_source_current(gen_random_uuid())",
        "public.efax_inbound_grant_current(gen_random_uuid())"):
        with r.engine.connect() as connection, pytest.raises(DBAPIError) as refusal:
            connection.execute(text("SELECT " + expression))
        assert refusal.value.orig.sqlstate == "42501"
    for statement in ("CREATE TABLE public.fax_runtime_forbidden(id integer)",
        "UPDATE public.audit_events SET event_type=event_type WHERE false",
        "DELETE FROM public.audit_events WHERE false"):
        with r.engine.connect() as connection, pytest.raises(DBAPIError) as refusal:
            connection.execute(text(statement))
        assert refusal.value.orig.sqlstate == "42501"


def test_restricted_signed_received_fax_source_chief_human_revision_and_revoke(restricted_fax, monkeypatch):
    r, f = restricted_fax, restricted_fax.f
    assert_private(r)
    monkeypatch.setattr(settings, "workspace_agent_tools_enabled", True)
    with f.case.start(f.profile) as client:
        # Do not launch model background workers; drive exact reservations after
        # ordinary disabled-model startup, using the real product services.
        monkeypatch.setattr(settings, "workspace_llm_backend", "azure_gpt41")
        monkeypatch.setattr(settings, "workspace_llm_api_key", SecretStr("invented-product-http-key"))
        f.client = client
        f.before = flow.fax.read(f, client)
        acquired = flow.fax.acquire(f, client)
        f.fax_command = flow.fax.review_command(f, client, acquired, passage=flow.LONG_PASSAGE)
        f.fax_saved = flow.fax.signed_fixture.result(client.post(f.path, headers=f.headers(), json=f.fax_command))
        flow.fax.validate_commitments(f, f.fax_command, f.fax_saved)
        with Session(r.engine) as s:
            configured = flow.team.save(s, f.box, f.owner, expected=0,
                key=flow.fax.signed_fixture.key(), configuration=flow.team.default_configuration())
            f.team_revision = configured["revision"]
        flow.run_model(f, flow.claim(f, flow.reserve(f)), delegate=True)
        with Session(r.engine) as s:
            rows = list(s.scalars(select(ModelWorkAdmission).where(ModelWorkAdmission.workspace_id == f.wid,
                ModelWorkAdmission.kind == "private_handoff")))
            child_ids = [(row.id, row.request_body["role"]) for row in rows]
        assert {role for _, role in child_ids} == {"scribe", "visit_prep", "follow_up"}
        scribe_hid = None
        for aid, role in child_ids:
            flow.run_model(f, flow.claim(f, aid))
            with Session(r.engine) as s:
                row = s.get(ModelWorkAdmission, aid)
                hid = s.get(flow.WorkspaceHandoffAttempt, row.handoff_attempt_id).handoff_id
            if role == "scribe":
                scribe_hid = hid
                review_id, _ = flow.human_review(f, hid, "changes_requested", flow.FEEDBACK)
            else:
                flow.human_review(f, hid)
        assert scribe_hid is not None
        with Session(r.engine) as s:
            current = ws.read(s, f.box, f.owner, f.wid)
            saved = revisions.reserve(s, f.box, f.owner, f.wid, scribe_hid,
                expected=current["revision"], key="runtime-fax-revision-" + str(uuid4()), review_id=review_id)
            child = next(h for h in saved["workspace"]["handoffs"] if h["id"] == saved["revision_handoff_id"])
            aid = s.scalar(select(ModelWorkAdmission.id).where(ModelWorkAdmission.handoff_attempt_id == child["attempt_id"]))
        flow.run_model(f, flow.claim(f, aid), revised=True)
        flow.human_review(f, child["id"])
        flow.revoke(f)
        masked = flow.fax.read(f, client)
        assert masked["note"] == f.before["note"]
        assert flow.LATE_FACT not in str(masked) and flow.FEEDBACK not in str(masked)
        assert flow.fax.resolve(f, client, f.fax_command)["source_withheld"] is True
    assert len(f.wire) == 2 and len(f.credentials) == 2
    assert_private(r)
