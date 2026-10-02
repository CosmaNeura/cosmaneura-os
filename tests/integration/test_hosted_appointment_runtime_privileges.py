"""Signed hosted proposals under restricted SQL credentials, invented reads only."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from tests.integration import test_hosted_appointment_proposals as hosted

from cosmas_os.api import app as api
from cosmas_os.application import database_preparation as preparation
from cosmas_os.application import workspace as ws
from cosmas_os.models import AppointmentReceipt, AppointmentWork, Decision, Operation

capture_case = hosted.capture_case
proposal_case = hosted.proposal_case

PRIVATE_FUNCTIONS = (
    "public.guard_google_calendar_observation()",
    "public.guard_google_calendar_snapshot()",
    "public.guard_google_calendar_review()",
    "public.guard_google_calendar_entry()",
    "public.guard_google_message_read()",
    "public.guard_google_message_snapshot()",
    "public.guard_google_message_review()",
    "public.guard_google_message_entry()",
    "public.guard_handoff_review()",
    "public.guard_handoff_revision()",
    "public.guard_selected_google_model_sources()",
    "public.google_calendar_source_current(uuid)",
    "public.google_message_source_current(uuid)",
    "public.handoff_review_sources_current(uuid,uuid,uuid,jsonb)",
    "public.selected_google_model_sources_current(public.model_work_admissions)",
)


@pytest.fixture
def restricted(proposal_case):
    # Existing fixture provisions only invented account/patient/resource/visit
    # mappings as administrator. Every API command below uses the new role.
    f, admin_engine = proposal_case, proposal_case.engine
    role = "appointment_runtime_test_" + uuid4().hex[:12]
    runtime_url = admin_engine.url.set(username=role, password="invented-runtime-password-1234")
    runtime_engine = create_engine(runtime_url, echo=False, hide_parameters=True)
    quoted_role = admin_engine.dialect.identifier_preparer.quote_identifier(role)
    previous_session = api.app.dependency_overrides[api.get_session]
    try:
        evidence = preparation.prepare_beta_database(admin_engine.url.render_as_string(hide_password=False),
            runtime_url.render_as_string(hide_password=False), require_verify_full=False)
        assert evidence.status == "ready" and evidence.runtime_role_non_admin
        assert evidence.runtime_ddl_denied and evidence.audit_update_denied and evidence.audit_delete_denied
        with admin_engine.connect() as connection:
            admin_role = connection.scalar(text("SELECT current_user"))
        f.engine = runtime_engine

        def request_session():
            with Session(runtime_engine) as owned:
                f.request_session = owned
                try:
                    yield owned
                finally:
                    f.request_session = None

        api.app.dependency_overrides[api.get_session] = request_session
        yield SimpleNamespace(f=f, engine=runtime_engine, admin_engine=admin_engine, role=role,
            admin_role=admin_role, runtime_url=runtime_url)
    finally:
        api.app.dependency_overrides[api.get_session] = previous_session
        f.engine = admin_engine
        runtime_engine.dispose()
        with admin_engine.begin() as connection:
            if connection.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=:role)"), {"role": role}):
                connection.execute(text(f"DROP OWNED BY {quoted_role}"))
                connection.execute(text(f"DROP ROLE {quoted_role}"))


def assert_restricted_authority(r):
    with r.engine.connect() as connection:
        assert connection.scalar(text("SELECT current_user")) == r.role != r.admin_role
        flags = connection.execute(text("SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls "
            "FROM pg_roles WHERE rolname=current_user")).one()
        assert all(flag is False for flag in flags)
        assert connection.scalar(text("SELECT NOT EXISTS(SELECT 1 FROM pg_auth_members m "
            "JOIN pg_roles member ON member.oid=m.member WHERE member.rolname=current_user)")) is True
        assert connection.scalar(text("SELECT NOT has_schema_privilege(current_user,'public','CREATE')")) is True
        assert connection.scalar(text("SELECT NOT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='public' AND c.relowner=(SELECT oid FROM pg_roles WHERE rolname=current_user))")) is True
        permitted = set(connection.scalars(text("SELECT p.oid FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname='public' AND has_function_privilege(current_user,p.oid,'EXECUTE')")))
        assert permitted == set(preparation._runtime_validator_oids(connection) or ()) and len(permitted) == 7
        for signature in PRIVATE_FUNCTIONS:
            assert connection.scalar(text("SELECT NOT has_function_privilege(current_user,to_regprocedure(:name),'EXECUTE')"),
                {"name": signature}) is True
    for expression in ("public.google_calendar_source_current(gen_random_uuid())",
                       "public.google_message_source_current(gen_random_uuid())",
                       "public.guard_selected_google_model_sources()"):
        with r.engine.connect() as connection, pytest.raises(DBAPIError) as refusal:
            connection.execute(text("SELECT " + expression))
        assert getattr(refusal.value.orig, "sqlstate", None) == "42501"


@pytest.mark.parametrize("action", ["book", "reschedule", "cancel"])
def test_signed_hosted_proposal_exact_review_with_restricted_runtime_role(restricted, action):
    r, f = restricted, restricted.f
    assert_restricted_authority(r)
    body = hosted.command(f, action)
    item = hosted.proposed(f, body)
    expected_reads = 2 if action == "reschedule" else 1
    assert len(f.receiver.calls) == expected_reads and item["operation_id"] is None
    assert hosted.proposed(f, body) == item and len(f.receiver.calls) == expected_reads
    catalog = f.client.get(f.path, headers=f.headers)
    assert catalog.status_code == 200 and catalog.json()["items"][0]["ticket_id"] == item["ticket_id"]
    approved = hosted.decide(f, item)
    assert approved["state"] == "approved" and approved["operation_status"] == "pending"
    reopened = f.client.get(f.path + "/" + item["ticket_id"],
        headers={"Authorization": "Bearer " + f.token(azp=hosted.ORIGIN, sid="invented-runtime-reopened")})
    assert reopened.status_code == 200 and reopened.json() == approved
    assert hosted.decide(f, item) == approved
    # Execution remains closed even for this exact signed human approval and a
    # database role that can persist internal proposals and decisions.
    denied = f.client.post(f.path + "/" + item["ticket_id"] + "/execute", headers=f.headers,
        json={"operation_id": approved["operation_id"], "revision_id": item["revision_id"],
            "payload_hash": item["payload_hash"], "mode": "submit"})
    assert denied.status_code == 403 and denied.headers["cache-control"] == "no-store"
    assert denied.json()["detail"] == "appointment_execution_not_available"
    withdrawn = hosted.decide(f, item, "reject")
    assert withdrawn["state"] == "rejected" and hosted.decide(f, item, "reject") == withdrawn
    assert len(f.receiver.calls) == expected_reads and len(f.receiver.credentials) == expected_reads
    hosted.assert_unchanged_and_unsubmitted(f, withdrawn)
    with Session(r.engine) as s:
        current = ws.read(s, f.box, f.owner, f.wid)
        assert current["note"] == f.note_before and current["entries"] == f.entries_before
        assert current["revision"] == f.revision_before
        assert len(list(s.scalars(select(AppointmentWork).where(AppointmentWork.workspace_id == f.wid)))) == 1
        decisions = list(s.scalars(select(Decision).where(Decision.ticket_id == item["ticket_id"])))
        assert sorted(row.kind for row in decisions) == ["approve", "reject"]
        assert all(row.actor_principal_id == f.owner for row in decisions)
        operation = s.get(Operation, approved["operation_id"])
        assert operation is not None and operation.status == "failed"
        assert operation.started_at is None and operation.attempt_count == 0 and operation.external_reference is None
        assert not s.scalar(select(AppointmentReceipt.id).where(AppointmentReceipt.box_id == f.box))
    assert_restricted_authority(r)
