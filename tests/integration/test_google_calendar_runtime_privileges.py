"""Calendar workflows under actual restricted SQL credentials, invented I/O only."""

import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from tests.integration import test_google_calendar_model_work as lineage
from tests.integration import test_product_agent_tool_workflow as product

from cosmas_os.application import database_preparation as preparation
from cosmas_os.application import model_work as work
from cosmas_os.application import workspace as ws
from cosmas_os.google_connection_models import GoogleConnectionCredential
from cosmas_os.models import (
    AppointmentObservation,
    ModelWorkAdmission,
    PatientLink,
    Principal,
    WorkspaceReply,
)

google_case = lineage.google_case
calendar_case = lineage.calendar_case

PRIVATE_FUNCTIONS = (
    "public.guard_google_calendar_observation()", "public.guard_google_calendar_snapshot()",
    "public.guard_google_calendar_review()", "public.guard_google_calendar_entry()",
    "public.guard_google_message_read()", "public.guard_google_message_snapshot()", "public.guard_google_message_review()",
    "public.guard_google_message_entry()", "public.guard_handoff_review()",
    "public.guard_handoff_revision()", "public.guard_selected_google_model_sources()",
    "public.google_calendar_source_current(uuid)", "public.google_calendar_source_valid(uuid)",
    "public.google_calendar_snapshot_valid(uuid)", "public.google_calendar_observation_current(uuid)",
    "public.google_message_source_current(uuid)", "public.handoff_review_sources_current(uuid,uuid,uuid,jsonb)",
    "public.selected_google_model_sources_current(public.model_work_admissions)",
)
DEFINER_TRIGGERS = PRIVATE_FUNCTIONS[:4] + PRIVATE_FUNCTIONS[5:11]


@pytest.fixture
def restricted(calendar_case):
    f = calendar_case
    admin_engine = f.engine
    role = "calendar_runtime_test_" + uuid4().hex[:12]
    runtime_url = admin_engine.url.set(username=role, password="invented-runtime-password-1234")
    admin_text = admin_engine.url.render_as_string(hide_password=False)
    runtime_text = runtime_url.render_as_string(hide_password=False)
    runtime_engine = create_engine(runtime_url, echo=False, hide_parameters=True)
    quoted_role = admin_engine.dialect.identifier_preparer.quote_identifier(role)
    try:
        evidence = preparation.prepare_beta_database(admin_text, runtime_text, require_verify_full=False)
        assert evidence.status == "ready" and evidence.runtime_role_non_admin
        with admin_engine.connect() as connection:
            admin_role = connection.scalar(text("SELECT current_user"))
        f.engine = runtime_engine
        yield SimpleNamespace(f=f, engine=runtime_engine, admin_engine=admin_engine,
            role=role, runtime_url=runtime_url, runtime_text=runtime_text, admin_role=admin_role)
    finally:
        f.engine = admin_engine
        # Close only this fixture's interrupted reservations through the real
        # authority fence while its installed binding readers still exist.
        with Session(admin_engine) as s:
            credential = s.get(GoogleConnectionCredential, f.account)
            assert credential is not None
            credential.status, credential.sealed = "disconnected", None
            principal = s.get(Principal, f.owner)
            assert principal is not None
            prior_state = principal.state
            principal.state = "disabled"
            s.commit()
            ids = list(s.scalars(select(ModelWorkAdmission.id).where(ModelWorkAdmission.box_id == f.box,
                ModelWorkAdmission.owner_id == f.owner, ModelWorkAdmission.state == "reserved")))
            for admission_id in ids:
                assert work.claim(s, f.box, f.owner, admission_id) is None
            principal = s.get(Principal, f.owner)
            assert principal is not None
            principal.state = prior_state
            s.commit()
        runtime_engine.dispose()
        with admin_engine.begin() as connection:
            if connection.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=:role)"), {"role": role}):
                connection.execute(text(f"DROP OWNED BY {quoted_role}"))
                connection.execute(text(f"DROP ROLE {quoted_role}"))


def assert_private_functions_denied(r, *, check_metadata=False):
    with r.engine.connect() as connection:
        permitted = set(connection.scalars(text("SELECT p.oid FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname='public' AND has_function_privilege(current_user,p.oid,'EXECUTE')")))
        assert permitted == set(preparation._runtime_validator_oids(connection) or ()) and len(permitted) == 7
        for signature in PRIVATE_FUNCTIONS:
            assert connection.scalar(text("SELECT NOT has_function_privilege(current_user,to_regprocedure(:name),'EXECUTE')"),
                {"name": signature}) is True
            if check_metadata:
                metadata = connection.execute(text("""SELECT p.prosecdef,p.proconfig,pg_get_userbyid(p.proowner),
                    NOT EXISTS(SELECT 1 FROM aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a
                        WHERE a.grantee=0 AND a.privilege_type='EXECUTE')
                    FROM pg_proc p WHERE p.oid=to_regprocedure(:name)"""), {"name": signature}).one()
                assert metadata.prosecdef == (signature in DEFINER_TRIGGERS)
                assert "search_path=pg_catalog" in (metadata.proconfig or [])
                assert metadata[2] == r.admin_role and metadata[2] != r.role
                assert metadata[3] is True
    for expression in ("public.google_calendar_source_current(gen_random_uuid())",
        "public.google_calendar_source_valid(gen_random_uuid())", "public.guard_selected_google_model_sources()"):
        with r.engine.connect() as connection, pytest.raises(DBAPIError) as refusal:
            connection.execute(text("SELECT " + expression))
        assert getattr(refusal.value.orig, "sqlstate", None) == "42501"


def test_restricted_ordinary_admission_needs_no_direct_google_helper_execute(restricted):
    r, f = restricted, restricted.f
    assert_private_functions_denied(r)
    # Seed only this new synthetic visit as administrator. The complete
    # admission/claim/tool/read/publication below uses restricted credentials.
    with Session(r.admin_engine) as s:
        link = PatientLink(box_id=f.box, source_pair_key="runtime-ordinary:" + str(uuid4()), label="Invented ordinary visit",
            state="confirmed", confirmed_by_principal_id=f.owner, attested_at=datetime.now(UTC))
        s.add(link)
        s.flush()
        appointment = AppointmentObservation(box_id=f.box, patient_link_id=link.id, external_id=str(uuid4()), source="synthetic",
            start_at=datetime.now(UTC), patient_label="Invented ordinary visit")
        s.add(appointment)
        s.commit()
        state = ws.create(s, f.box, f.owner, appointment.id, "runtime-ordinary-create")
        state = ws.append(s, f.box, f.owner, state["id"], expected=state["revision"], key="runtime-ordinary-source",
            kind="evidence", source_label="Invented ordinary transcript", content=product.TRANSCRIPT)["workspace"]
    with Session(r.engine) as s:
        admission, _ = work.reserve_conversation(s, f.box, f.owner, state["id"], expected=state["revision"],
            team_revision=1, key="runtime-ordinary-question", role="chief", content="Prepare questions from this invented transcript.")
        claimed = work.claim(s, f.box, f.owner, admission)
        assert claimed is not None
        assert all(source["entry_id"] != f.calendar_selected["entry_id"] for source in claimed.envelope["context"]["sources"])
    transport, calls, reads = product.tool_http(r.engine, claimed)
    assert product.dispatch_and_settle(r.engine, claimed, transport)[0] == "completed"
    assert len(calls) == 2 and len(reads) == 1
    assert preparation._verify_runtime_role(r.runtime_text, r.runtime_url)["non_admin"] is True
    assert_private_functions_denied(r, check_metadata=True)


def test_restricted_calendar_observation_tool_handoffs_revision_acceptance_and_revoke(restricted):
    r, f = restricted, restricted.f
    assert_private_functions_denied(r, check_metadata=True)
    # The inherited Gmail read trigger calls only an already-permitted pure
    # digest and scoped table reads. Prove it needs no definer privilege.
    f.selected = lineage.gmail.select_current(f, key="restricted")
    before_google = len(f.calendar_port.calls)
    f.calendar_selected = lineage.select_calendar(f, "restricted")
    assert len(f.calendar_port.calls) == before_google + 1 and f.calendar_selected["source_withheld"] is False
    with r.engine.connect() as connection, pytest.raises(DBAPIError) as forged:
        connection.execute(text("""INSERT INTO public.google_calendar_observation_requests
            (id,box_id,owner_id,account_id,ordinal,idempotency_key,request_hash,binding_digest,
             grant_sha256,connected_at,window_start,window_end)
            SELECT gen_random_uuid(),box_id,:wrong_owner,account_id,ordinal+1,'runtime-forged-owner',
             request_hash,binding_digest,grant_sha256,connected_at,window_start,window_end
            FROM public.google_calendar_observation_requests WHERE account_id=:account
            ORDER BY ordinal DESC LIMIT 1"""), {"wrong_owner": str(uuid4()), "account": f.account})
    assert getattr(forged.value.orig, "sqlstate", None) == "23514"
    command, handoff = lineage.finish_handoff(f, cited=False)
    with Session(r.engine) as s:
        saved = lineage.reviews.review(s, f.box, f.owner, f.wid, handoff["id"], **command)
        review = next(h for h in saved["workspace"]["handoffs"] if h["id"] == handoff["id"])["review"]
        revised = lineage.revisions.reserve(s, f.box, f.owner, f.wid, handoff["id"], expected=saved["workspace"]["revision"],
            key="runtime-calendar-revision", review_id=review["id"])
        child = next(h for h in revised["workspace"]["handoffs"] if h["id"] == revised["revision_handoff_id"])
        admission = s.scalar(select(ModelWorkAdmission).where(ModelWorkAdmission.handoff_attempt_id == child["attempt_id"]))
        assert admission is not None
        claimed = work.claim(s, f.box, f.owner, admission.id)
        assert claimed is not None
    transport, calls = lineage.model_http(f, claimed)
    assert product.dispatch_and_settle(r.engine, claimed, transport)[0] == "completed" and len(calls) == 2
    with Session(r.engine) as s:
        current = ws.read(s, f.box, f.owner, f.wid)
        child = next(h for h in current["handoffs"] if h["id"] == revised["revision_handoff_id"])
        reply = s.get(WorkspaceReply, child["result_entry_id"])
        assert reply is not None
        accepted = lineage.reviews.review(s, f.box, f.owner, f.wid, child["id"], expected=current["revision"],
            key="runtime-calendar-accepted", attempt_id=child["attempt_id"], result_entry_id=reply.entry_id,
            result_sha256=hashlib.sha256(reply.content.encode()).hexdigest(), decision="accepted", feedback="")
        assert accepted["workspace"]["note"]["latest"] == f.note_before
        assert next(h for h in accepted["workspace"]["handoffs"] if h["id"] == child["id"])["review"]["decision"] == "accepted"
        credential = s.get(GoogleConnectionCredential, f.account)
        assert credential is not None
        credential.status, credential.sealed = "disconnected", None
        s.commit()
        masked = lineage.reviews.review(s, f.box, f.owner, f.wid, handoff["id"], **command)
        assert masked["request_sha256"] == saved["request_sha256"] and masked["feedback_withheld"] is True
        assert lineage.gmail.private_fact_paths(masked, ["calendar café", "Google calendar: Invented calendar"]) == []
        with pytest.raises(ws.WorkspaceError):
            lineage.revisions.reserve(s, f.box, f.owner, f.wid, handoff["id"], expected=masked["workspace"]["revision"],
                key="runtime-stale-revision", review_id=review["id"])
        s.rollback()
    assert_private_functions_denied(r)
