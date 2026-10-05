"""Generic fax acquisition and reviewed source using the actual non-admin privilege set."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from tests.integration import test_fax_inbound_source_api as fax

from cosmas_os.api import app as api
from cosmas_os.application import database_preparation as preparation
from cosmas_os.config import settings
from cosmas_os.db import make_session_factory

managed_case = fax.managed_case
inbox = fax.inbox
source_http = fax.source_http
HELPERS = (
    "public.fax_inbound_hash(jsonb)",
    "public.fax_inbound_grant_current(uuid)",
    "public.fax_inbound_document_valid(uuid)",
    "public.fax_inbound_source_valid(uuid)",
    "public.fax_inbound_source_current(uuid)",
    "public.fax_inbound_outcome_hash(public.fax_inbound_outcomes)",
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
    for expression in ("public.fax_inbound_source_current(gen_random_uuid())",
        "public.fax_inbound_grant_current(gen_random_uuid())"):
        with r.engine.connect() as connection, pytest.raises(DBAPIError) as refusal:
            connection.execute(text("SELECT " + expression))
        assert refusal.value.orig.sqlstate == "42501"
    for statement in ("CREATE TABLE public.fax_runtime_forbidden(id integer)",
        "UPDATE public.audit_events SET event_type=event_type WHERE false",
        "DELETE FROM public.audit_events WHERE false"):
        with r.engine.connect() as connection, pytest.raises(DBAPIError) as refusal:
            connection.execute(text(statement))
        assert refusal.value.orig.sqlstate == "42501"



def test_restricted_signed_generic_received_fax_passage_and_recovery(restricted_fax):
    r, f = restricted_fax, restricted_fax.f
    assert_private(r)
    with f.case.start(f.profile) as client:
        before = fax.read(f, client)
        acquired = fax.acquire(f, client)
        command = fax.review_command(f, client, acquired)
        saved = fax.signed_fixture.reply(client.post(f.path, headers=f.headers(), json=command))
        fax.validate_commitments(f, command, saved)
        assert fax.resolve(f, client, command) == saved
        assert fax.read(f, client)["note"] == before["note"]
        fax.signed_fixture.reply(client.post("/fax-inbound/revoke", headers=f.headers(),
            json={"idempotency_key": fax.signed_fixture.key(), "grant_id": f.grant_id}))
        assert fax.resolve(f, client, command)["source_withheld"] is True
        assert fax.PASSAGE not in str(fax.read(f, client))
        assert len(f.wire) == 2
